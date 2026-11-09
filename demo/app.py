"""Local synthetic-text proposals and temporary human review."""
import asyncio
import hashlib
from contextlib import asynccontextmanager
from importlib import metadata
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path as ApiPath, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from starlette.concurrency import run_in_threadpool

from demo.masking import CONFIGURATION, MAX_CODE_POINTS, InvalidPredictions, canonicalize, make_proposal
from demo.reviews import ReviewError, ReviewStore
from scripts.run_presidio import build_analyzer
from scripts.runner_common import CUSTOM_SOURCES, require_custom_freeze


class MaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(strict=True, min_length=1, max_length=MAX_CODE_POINTS)
    synthetic_input: bool = Field(strict=True)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        if not value.strip():
            raise ValueError("Nonempty text required")
        value.encode("utf-8", errors="strict")
        return value

    @field_validator("synthetic_input")
    @classmethod
    def acknowledgement_required(cls, value):
        if value is not True:
            raise ValueError("Synthetic acknowledgement required")
        return value


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")


class CorrectionRequest(RevisionRequest):
    operation: Literal["add", "remove"]
    intervals: list[list[StrictInt]] = Field(min_length=1, max_length=MAX_CODE_POINTS)


ReviewId = Annotated[str, ApiPath(pattern=r"^[0-9a-f]{32}$")]
STATIC = Path(__file__).with_name("static")


def verify_source():
    require_custom_freeze(config=CONFIGURATION)
    return hashlib.sha256(CUSTOM_SOURCES[CONFIGURATION].read_bytes()).hexdigest()


def build_fixed_analyzer():
    # Refuse a missing model instead of allowing Presidio's automatic download.
    metadata.version("en-core-web-sm")
    from spacy.util import fix_random_seed
    fix_random_seed(42)
    return build_analyzer(CONFIGURATION)


def problem(status, code, message):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def create_app(*, analyzer_factory=None, hash_verifier=None, review_store=None):
    @asynccontextmanager
    async def lifespan(app):
        try:
            app.state.source_hash = (hash_verifier or verify_source)()
            app.state.analyzer = (analyzer_factory or build_fixed_analyzer)()
            if app.state.analyzer is None:
                raise RuntimeError()
        except Exception:
            app.state.analyzer = None
            raise RuntimeError("Demo analyzer startup failed; check installation and freeze") from None
        app.state.analysis_lock = asyncio.Lock()
        app.state.reviews.clear()
        try:
            yield
        finally:
            app.state.analyzer = None
            app.state.reviews.clear()

    app = FastAPI(title="Synthetic masking proposal demo", lifespan=lifespan, debug=False)
    app.state.analyzer = None
    app.state.reviews = review_store if review_store is not None else ReviewStore()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Default validation errors may include the submitted input; do not expose them.
        return JSONResponse(status_code=422, headers={"Cache-Control": "no-store"}, content={"detail": {
            "code": "invalid_request",
            "message": "Invalid request; check text (1-20000 code points), synthetic acknowledgement, revision, and intervals; no extra fields",
        }})

    @app.exception_handler(ReviewError)
    async def review_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    @app.get("/", include_in_schema=False)
    async def review_page(review_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")] = None):
        return FileResponse(STATIC / "index.html")

    @app.get("/static/review.js", include_in_schema=False)
    async def review_script():
        return FileResponse(STATIC / "review.js", media_type="text/javascript")

    @app.get("/static/review.css", include_in_schema=False)
    async def review_style():
        return FileResponse(STATIC / "review.css", media_type="text/css")

    @app.get("/health")
    async def health():
        ready = app.state.analyzer is not None
        return JSONResponse(status_code=200 if ready else 503,
                            content={"ready": ready, "configuration": CONFIGURATION})

    async def analyze(body):
        if app.state.analyzer is None:
            raise problem(503, "not_ready", "Analyzer is unavailable")
        text = canonicalize(body.text)
        try:
            # One shared analyzer, one call at a time; health remains responsive.
            async with app.state.analysis_lock:
                results = await run_in_threadpool(app.state.analyzer.analyze, text=text, language="en")
                return make_proposal(text, results, app.state.source_hash)
        except InvalidPredictions:
            raise problem(500, "invalid_predictions", "Analyzer returned invalid span data") from None
        except Exception:
            # Do not print/return exception messages, arguments, or tracebacks containing text.
            raise problem(500, "analysis_failed", "Analysis failed; no proposal was produced") from None

    @app.post("/mask")
    async def mask(body: MaskRequest):
        return await analyze(body)

    @app.post("/reviews", status_code=201)
    async def create_review(body: MaskRequest):
        return app.state.reviews.create(await analyze(body))

    @app.get("/reviews/{review_id}")
    async def get_review(review_id: ReviewId):
        return app.state.reviews.get(review_id)

    @app.patch("/reviews/{review_id}/mask")
    async def correct_review(review_id: ReviewId, body: CorrectionRequest):
        return app.state.reviews.correct(review_id, body.expected_revision, body.operation, body.intervals)

    @app.post("/reviews/{review_id}/approve")
    async def approve_review(review_id: ReviewId, body: RevisionRequest):
        return app.state.reviews.transition(review_id, body.expected_revision, "approve")

    @app.post("/reviews/{review_id}/reject")
    async def reject_review(review_id: ReviewId, body: RevisionRequest):
        return app.state.reviews.transition(review_id, body.expected_revision, "reject")

    @app.get("/reviews/{review_id}/output")
    async def approved_output(review_id: ReviewId, expected_revision: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")]):
        text, revision = app.state.reviews.output(review_id, expected_revision)
        return Response(content=text.encode("utf-8"), media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="synthetic-reviewed.txt"',
                                 "X-Review-Revision": revision})

    return app


app = create_app()
