"""Bounded process-local review state; each operation is atomic under one lock."""
import copy
import math
import threading
import time
import uuid
from dataclasses import dataclass

from demo.masking import interval_positions, merged_intervals, render_mask, revision_identity

REVIEW_CAPACITY = 32
REVIEW_TTL_SECONDS = 1800


class ReviewError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


@dataclass
class Review:
    review_id: str
    proposal: dict
    intervals: list
    expires: float
    version: int = 1
    status: str = "pending"


class ReviewStore:
    def __init__(self, capacity=REVIEW_CAPACITY, ttl=REVIEW_TTL_SECONDS, clock=time.monotonic):
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._reviews = {}
        self._lock = threading.RLock()

    def clear(self):
        with self._lock:
            self._reviews.clear()

    def _purge(self):
        now = self.clock()
        self._reviews = {key: review for key, review in self._reviews.items() if review.expires > now}

    def _find(self, review_id):
        self._purge()
        review = self._reviews.get(review_id)
        if review is None:
            raise ReviewError(404, "review_missing_or_expired", "Review not found or expired; submit a new review")
        return review

    @staticmethod
    def _revision(review):
        return revision_identity(review.proposal["canonical_original"], review.proposal["frozen_source_sha256"],
                                 review.intervals, [review.review_id, review.version])

    def _expected(self, review, expected):
        if expected != self._revision(review):
            raise ReviewError(409, "stale_revision", "Review changed; refresh before acting")
        if review.status == "rejected":
            raise ReviewError(409, "review_rejected", "Review was rejected; submit a new review")

    def _snapshot(self, review):
        result = copy.deepcopy(review.proposal)
        result["proposal_revision_id"] = result["revision_id"]
        result["detected_mask_intervals"] = result["mask_intervals"]
        positions = interval_positions(review.intervals, len(result["canonical_original"]))
        masked, counts = render_mask(result["canonical_original"], positions)
        result.update(review_id=review.review_id, revision_id=self._revision(review),
                      revision_number=review.version, status=review.status,
                      mask_intervals=copy.deepcopy(review.intervals), masked_text=masked,
                      coverage_counts=counts, review_required=review.status != "approved",
                      expires_in_seconds=max(0, math.ceil(review.expires - self.clock())))
        return result

    def create(self, proposal):
        with self._lock:
            self._purge()
            if len(self._reviews) >= self.capacity:
                raise ReviewError(503, "review_capacity", "Review capacity reached; wait for expiry")
            review_id = uuid.uuid4().hex
            review = Review(review_id, copy.deepcopy(proposal), copy.deepcopy(proposal["mask_intervals"]),
                            self.clock() + self.ttl)
            self._reviews[review_id] = review
            return self._snapshot(review)

    def get(self, review_id):
        with self._lock:
            return self._snapshot(self._find(review_id))

    def correct(self, review_id, expected, operation, intervals):
        with self._lock:
            review = self._find(review_id)
            self._expected(review, expected)
            text = review.proposal["canonical_original"]
            try:
                if not intervals or operation not in ("add", "remove"):
                    raise ValueError()
                selected = interval_positions(intervals, len(text))
            except ValueError:
                raise ReviewError(422, "invalid_intervals", "Use nonempty half-open code-point intervals within the canonical text") from None
            covered = interval_positions(review.intervals, len(text))
            covered = covered | selected if operation == "add" else covered - selected
            review.intervals = merged_intervals(covered)
            review.version += 1  # Even a no-op edit consumes the previous revision.
            review.status = "pending"
            return self._snapshot(review)

    def transition(self, review_id, expected, action):
        with self._lock:
            review = self._find(review_id)
            self._expected(review, expected)
            if action not in ("approve", "reject"):
                raise ValueError("Unknown review action")
            if action == "approve" and review.status != "pending":
                raise ReviewError(409, "already_approved", "Review is already approved")
            review.status = "approved" if action == "approve" else "rejected"
            review.version += 1  # Consumed action tokens cannot be replayed.
            return self._snapshot(review)

    def output(self, review_id, expected):
        with self._lock:
            review = self._find(review_id)
            self._expected(review, expected)
            if review.status != "approved":
                raise ReviewError(409, "review_not_approved", "Approve the current revision before retrieving output")
            masked, _ = render_mask(review.proposal["canonical_original"],
                                    interval_positions(review.intervals, len(review.proposal["canonical_original"])))
            # Check and copy the entire output in the same critical section.
            return masked, self._revision(review)
