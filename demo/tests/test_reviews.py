"""Review state and API tests using tiny fixtures, never held-out documents."""
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi.testclient import TestClient

from demo.app import create_app
from demo.masking import make_proposal
from demo.reviews import ReviewError, ReviewStore


def proposal(text="A#\nB", spans=()):
    results = [SimpleNamespace(entity_type=label, start=start, end=end) for label, start, end in spans]
    return make_proposal(text, results, "f" * 64)


class MaskIdentityTests(unittest.TestCase):
    def test_original_hash_and_lf_distinguish_invisible_coverage(self):
        empty = proposal()
        hashed = proposal(spans=[("ID", 1, 2)])
        newline = proposal(spans=[("ID", 2, 3)])
        self.assertEqual({item["masked_proposal"] for item in (empty, hashed, newline)}, {"A#\nB"})
        self.assertEqual(len({item["revision_id"] for item in (empty, hashed, newline)}), 3)
        self.assertEqual(hashed["mask_intervals"], [[1, 2]])
        self.assertEqual(newline["detection_counts"]["covered_lf_count"], 1)
        self.assertEqual(newline["detection_counts"]["masked_code_point_count"], 0)

    def test_equivalent_reordered_overlapping_and_adjacent_spans_are_canonical(self):
        many = proposal("abcdefg", [("ID", 4, 7), ("PERSON", 0, 3), ("ID", 2, 4)])
        one = proposal("abcdefg", [("ID", 0, 7)])
        self.assertEqual(many["mask_intervals"], [[0, 7]])
        self.assertEqual(many["revision_id"], one["revision_id"])
        self.assertEqual(many["detection_counts"]["raw_span_count"], 3)
        self.assertEqual(many["detection_counts"]["covered_code_point_count"], 7)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.store = ReviewStore(capacity=2, ttl=10, clock=lambda: self.now)

    def assert_error(self, code, function, *args):
        with self.assertRaises(ReviewError) as result:
            function(*args)
        self.assertEqual(result.exception.code, code)

    def test_expiry_is_fixed_not_extended_by_reads_or_actions(self):
        review = self.store.create(proposal())
        self.now += 9
        approved = self.store.transition(review["review_id"], review["revision_id"], "approve")
        self.assertEqual(approved["expires_in_seconds"], 1)
        self.now += 1
        self.assert_error("review_missing_or_expired", self.store.get, review["review_id"])
        self.assert_error("review_missing_or_expired", self.store.output, review["review_id"], approved["revision_id"])

    def test_capacity_does_not_evict_live_reviews_and_expiry_releases_slots(self):
        first = self.store.create(proposal())
        self.store.create(proposal())
        self.assert_error("review_capacity", self.store.create, proposal())
        self.assertEqual(self.store.get(first["review_id"])["status"], "pending")
        self.now += 10
        self.assertEqual(self.store.create(proposal())["status"], "pending")

    def test_new_review_identity_and_clear(self):
        first, second = self.store.create(proposal()), self.store.create(proposal())
        self.assertNotEqual(first["review_id"], second["review_id"])
        self.assertNotEqual(first["revision_id"], second["revision_id"])
        self.assertEqual(first["proposal_revision_id"], second["proposal_revision_id"])
        self.store.clear()
        self.assert_error("review_missing_or_expired", self.store.get, first["review_id"])

    def test_corrections_canonicalize_and_keep_original_detections(self):
        review = self.store.create(proposal("abcdefg", [("ID", 0, 2)]))
        edited = self.store.correct(review["review_id"], review["revision_id"], "add", [[4, 6], [1, 4], [6, 7]])
        self.assertEqual(edited["mask_intervals"], [[0, 7]])
        removed = self.store.correct(edited["review_id"], edited["revision_id"], "remove", [[2, 5]])
        self.assertEqual(removed["mask_intervals"], [[0, 2], [5, 7]])
        self.assertEqual(removed["masked_text"], "##cde##")
        self.assertEqual(removed["canonical_original"], "abcdefg")
        self.assertEqual(removed["detected_mask_intervals"], [[0, 2]])
        self.assertEqual(removed["detection_counts"], review["detection_counts"])
        self.assertEqual(removed["coverage_counts"]["covered_code_point_count"], 4)

    def test_snapshot_cannot_mutate_stored_mask(self):
        review = self.store.create(proposal(spans=[("ID", 0, 1)]))
        review["mask_intervals"][0][1] = 4
        review["detected_mask_intervals"].clear()
        self.assertEqual(self.store.get(review["review_id"])["mask_intervals"], [[0, 1]])
        self.assertEqual(self.store.get(review["review_id"])["detected_mask_intervals"], [[0, 1]])

    def test_noop_and_edit_back_cannot_restore_an_old_revision(self):
        review = self.store.create(proposal())
        edited = self.store.correct(review["review_id"], review["revision_id"], "add", [[1, 2]])
        back = self.store.correct(edited["review_id"], edited["revision_id"], "remove", [[1, 2]])
        noop = self.store.correct(back["review_id"], back["revision_id"], "remove", [[1, 2]])
        self.assertEqual(back["mask_intervals"], review["mask_intervals"])
        self.assertEqual(len({r["revision_id"] for r in [review, edited, back, noop]}), 4)
        self.assert_error("stale_revision", self.store.transition, review["review_id"], review["revision_id"], "approve")

    def test_competing_updates_only_one_consumes_the_revision(self):
        review = self.store.create(proposal())
        ready = threading.Barrier(2)
        def attempt(interval):
            ready.wait(timeout=3)
            try:
                return self.store.correct(review["review_id"], review["revision_id"], "add", [interval])["status"]
            except ReviewError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [[0, 1], [3, 4]]))
        self.assertCountEqual(results, ["pending", "stale_revision"])
        self.assertEqual(self.store.get(review["review_id"])["revision_number"], 2)

    def test_competing_approval_and_edit_never_approve_an_unseen_mask(self):
        review = self.store.create(proposal())
        ready = threading.Barrier(2)
        def approve():
            ready.wait(timeout=3)
            return self.store.transition(review["review_id"], review["revision_id"], "approve")
        def edit():
            ready.wait(timeout=3)
            return self.store.correct(review["review_id"], review["revision_id"], "add", [[0, 1]])
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(action) for action in [approve, edit]]
            outcomes = []
            for future in pending:
                try:
                    outcomes.append(future.result()["status"])
                except ReviewError as error:
                    outcomes.append(error.code)
        self.assertEqual(outcomes.count("stale_revision"), 1)
        final = self.store.get(review["review_id"])
        if final["status"] == "approved":
            self.assertEqual(final["mask_intervals"], [])
        else:
            self.assert_error("review_not_approved", self.store.output, final["review_id"], final["revision_id"])

    def test_output_and_edit_are_atomic_with_respect_to_the_approved_revision(self):
        review = self.store.create(proposal())
        approved = self.store.transition(review["review_id"], review["revision_id"], "approve")
        ready = threading.Barrier(2)
        def output():
            ready.wait(timeout=3)
            try:
                return self.store.output(approved["review_id"], approved["revision_id"])
            except ReviewError as error:
                return error.code
        def edit():
            ready.wait(timeout=3)
            return self.store.correct(approved["review_id"], approved["revision_id"], "add", [[0, 1]])
        with ThreadPoolExecutor(max_workers=2) as pool:
            read, write = pool.submit(output), pool.submit(edit)
            returned, edited = read.result(), write.result()
        self.assertIn(returned, [(approved["masked_text"], approved["revision_id"]), "stale_revision"])
        self.assertEqual(edited["status"], "pending")
        self.assert_error("stale_revision", self.store.output, approved["review_id"], approved["revision_id"])
        self.assert_error("review_not_approved", self.store.output, edited["review_id"], edited["revision_id"])

    def test_noop_correction_revokes_approval(self):
        review = self.store.create(proposal())
        approved = self.store.transition(review["review_id"], review["revision_id"], "approve")
        noop = self.store.correct(approved["review_id"], approved["revision_id"], "remove", [[0, 1]])
        self.assertEqual(noop["mask_intervals"], approved["mask_intervals"])
        self.assertNotEqual(noop["revision_id"], approved["revision_id"])
        self.assertEqual(noop["status"], "pending")
        self.assert_error("stale_revision", self.store.output, approved["review_id"], approved["revision_id"])


class ReviewApiTests(unittest.TestCase):
    def client(self, error=False, store=None):
        class Analyzer:
            def analyze(self, **kwargs):
                if error:
                    raise RuntimeError("SYNTHETIC_CANARY")
                return []
        return TestClient(create_app(analyzer_factory=Analyzer, hash_verifier=lambda: "f" * 64, review_store=store))

    def create(self, client, text="A#\nB"):
        response = client.post("/reviews", json={"text": text, "synthetic_input": True})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def action(self, client, review, action):
        return client.post(f'/reviews/{review["review_id"]}/{action}', json={"expected_revision": review["revision_id"]})

    def output(self, client, review):
        return client.get(f'/reviews/{review["review_id"]}/output', params={"expected_revision": review["revision_id"]})

    def test_approve_download_edit_invalidates_output_and_replay(self):
        with self.client() as client:
            review = self.create(client)
            self.assertEqual(self.output(client, review).status_code, 409)
            approved = self.action(client, review, "approve").json()
            output = self.output(client, approved)
            self.assertEqual(output.status_code, 200)
            self.assertEqual(output.text, "A#\nB")
            self.assertEqual(output.headers["x-review-revision"], approved["revision_id"])
            self.assertEqual(output.headers["cache-control"], "no-store")
            self.assertIn("attachment", output.headers["content-disposition"])
            self.assertFalse(approved["review_required"])
            self.assertEqual(self.action(client, review, "approve").status_code, 409)
            self.assertEqual(self.action(client, approved, "approve").status_code, 409)
            edited = client.patch(f'/reviews/{review["review_id"]}/mask', json={
                "expected_revision": approved["revision_id"], "operation": "add", "intervals": [[1, 3]]}).json()
            self.assertEqual(edited["masked_text"], approved["masked_text"])
            self.assertNotEqual(edited["revision_id"], approved["revision_id"])
            self.assertTrue(edited["review_required"])
            self.assertEqual(self.output(client, approved).status_code, 409)
            self.assertEqual(self.output(client, edited).status_code, 409)
            approved_again = self.action(client, edited, "approve").json()
            self.assertEqual(self.output(client, approved_again).text, "A#\nB")
            self.assertEqual(self.output(client, approved).status_code, 409)

    def test_rejection_is_terminal_even_after_approval(self):
        with self.client() as client:
            review = self.create(client)
            approved = self.action(client, review, "approve").json()
            rejected = self.action(client, approved, "reject").json()
            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(self.output(client, rejected).status_code, 409)
            self.assertEqual(self.output(client, approved).status_code, 409)
            self.assertEqual(self.action(client, rejected, "approve").status_code, 409)
            self.assertEqual(self.action(client, rejected, "reject").status_code, 409)
            self.assertEqual(client.patch(f'/reviews/{rejected["review_id"]}/mask', json={
                "expected_revision": rejected["revision_id"], "operation": "add", "intervals": [[0, 1]]}).status_code, 409)

    def test_interval_validation_is_sanitized_and_does_not_consume_revision(self):
        with self.client() as client:
            review = self.create(client)
            base = {"expected_revision": review["revision_id"], "operation": "add"}
            for intervals in [[], [[-1, 1]], [[1, 1]], [[3, 2]], [[0, 5]], [[True, 2]], [[0.5, 2]], [[0]], [[0, 1, 2]], [["SYNTHETIC_CANARY", 2]]]:
                response = client.patch(f'/reviews/{review["review_id"]}/mask', json={**base, "intervals": intervals})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("SYNTHETIC_CANARY", response.text)
            self.assertEqual(client.get(f'/reviews/{review["review_id"]}').json()["revision_id"], review["revision_id"])

    def test_revision_is_required_for_actions_and_output(self):
        with self.client() as client:
            review = self.create(client)
            root = f'/reviews/{review["review_id"]}'
            for action in ["approve", "reject"]:
                self.assertEqual(client.post(root + "/" + action, json={}).status_code, 422)
                self.assertEqual(client.post(root + "/" + action, json={"expected_revision": "0" * 64}).status_code, 409)
            self.assertEqual(client.get(root + "/output").status_code, 422)

    def test_missing_expired_capacity_and_shutdown(self):
        now = [0.0]
        store = ReviewStore(capacity=1, ttl=5, clock=lambda: now[0])
        with self.client(store=store) as client:
            self.assertEqual(client.get('/reviews/' + '0' * 32).status_code, 404)
            first = self.create(client)
            self.assertEqual(client.post('/reviews', json={"text": "new synthetic", "synthetic_input": True}).status_code, 503)
            now[0] = 5.0
            expired = client.get(f'/reviews/{first["review_id"]}')
            self.assertEqual(expired.status_code, 404)
            self.assertEqual(expired.json()["detail"]["code"], "review_missing_or_expired")
            latest = self.create(client)
        with self.assertRaises(ReviewError):
            store.get(latest["review_id"])

    def test_analysis_failure_does_not_create_review_or_output(self):
        store = ReviewStore()
        with self.client(error=True, store=store) as client:
            with self.assertNoLogs(level="ERROR"):
                response = client.post('/reviews', json={"text": "SYNTHETIC_CANARY", "synthetic_input": True})
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("SYNTHETIC_CANARY", response.text)
            self.assertEqual(len(store._reviews), 0)
            self.assertEqual(client.get('/reviews/' + '0' * 32 + '/output', params={"expected_revision": 'f'*64}).status_code, 404)

    def test_html_is_static_and_user_text_remains_data(self):
        text = '<img src=x onerror="alert(1)">\n<script>throw 1</script>'
        with self.client() as client:
            page = client.get('/')
            self.assertEqual(page.status_code, 200)
            self.assertIn("script-src 'self'", page.headers["content-security-policy"])
            review = self.create(client, text)
            self.assertEqual(review["canonical_original"], text)
            self.assertNotIn(text, page.text)
            self.assertNotIn('innerHTML', client.get('/static/review.js').text)
            approved = self.action(client, review, 'approve').json()
            output = self.output(client, approved)
            self.assertTrue(output.headers['content-type'].startswith('text/plain'))
            self.assertEqual(output.text, text)

    def test_existing_review_link_is_validated_and_never_injects_text(self):
        with self.client() as client:
            review = self.create(client)
            page = client.get('/', params={"review_id": review["review_id"]})
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(review["review_id"], page.text)
            self.assertEqual(client.get(f'/reviews/{review["review_id"]}').status_code, 200)
            bad = client.get('/', params={"review_id": "<script>SYNTHETIC_CANARY</script>"})
            self.assertEqual(bad.status_code, 422)
            self.assertNotIn('SYNTHETIC_CANARY', bad.text)


if __name__ == "__main__":
    unittest.main()
