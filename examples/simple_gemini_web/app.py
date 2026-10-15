"""Local demo: mask Korean PII before sending text to Gemini.

Run with:
    uvicorn app:app --host 127.0.0.1 --port 8000

The browser never receives the Gemini API key. The source text is handled only
by this Python process; only ``masked_text`` is passed to the Gemini SDK.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from korean_pii import DetectionError, KoreanPII


LOGGER = logging.getLogger("simple_gemini_web")
HERE = Path(__file__).resolve().parent
MAX_TEXT_CHARS = 100_000
SMOKE_TEXT = (
    "개인 담당자: 김민수 | 개인 휴대전화: 010-2345-6789 | "
    "개인 이메일: minsu@example.invalid"
)
SMOKE_LABELS = {"PERSON", "KR_PHONE_NUMBER", "EMAIL_ADDRESS"}
SYSTEM_INSTRUCTION = """당신은 한국어로 답하는 업무 도우미입니다.
입력의 <PERSON>, <KR_PHONE_NUMBER> 같은 토큰은 개인정보 보호를 위해
의도적으로 마스킹된 값입니다. 마스킹된 원래 값을 추측하거나 복원하지
말고, 토큰을 그대로 유지하면서 사용자의 요청에 답하세요.
"""


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class DetectionSummary(BaseModel):
    label: str
    count: int


class ChatResponse(BaseModel):
    answer: str
    masked_text: str
    detected_items: int
    detections: list[DetectionSummary]
    gemini_model: str


def _default_detector_factory() -> KoreanPII:
    return KoreanPII()


def _default_gemini_factory():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def _prepare_detector(detector) -> None:
    """Load every required local resource and reject a partial setup."""

    detector.address_gazetteer.load()
    spans = detector.detect(SMOKE_TEXT)
    labels = {span.label for span in spans}
    status = detector.status
    required_models = set(detector.policy.models)
    loaded_models = set(status["loaded_models"])
    address_status = status["address_gazetteer"]

    if SMOKE_LABELS - labels:
        raise RuntimeError("PII smoke test did not find every expected label")
    if loaded_models != required_models:
        raise RuntimeError("not every configured PII model was loaded")
    if not address_status["configured"] or not address_status["loaded"]:
        raise RuntimeError("the official address index is not ready")


def create_app(
    detector_factory: Callable[[], object] = _default_detector_factory,
    gemini_factory: Callable[[], object | None] = _default_gemini_factory,
) -> FastAPI:
    """Build the app. Factories are injectable so routing can be tested offline."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.detector = None
        app.state.gemini = None
        app.state.pii_ready = False
        app.state.pii_error_type = None
        app.state.gemini_configured = False
        app.state.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

        try:
            detector = detector_factory()
            _prepare_detector(detector)
            app.state.detector = detector
            app.state.pii_ready = True
        except Exception as exc:  # Keep the page available for setup diagnostics.
            app.state.pii_error_type = type(exc).__name__
            LOGGER.error("PII startup failed (%s); source text will not be sent", type(exc).__name__)

        try:
            app.state.gemini = gemini_factory()
            app.state.gemini_configured = app.state.gemini is not None
        except Exception as exc:
            LOGGER.error("Gemini startup failed (%s)", type(exc).__name__)

        yield

        client = app.state.gemini
        close = getattr(client, "close", None)
        if callable(close):
            close()

    app = FastAPI(
        title="Korean PII Guardrail + Gemini Demo",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(HERE / "index.html")

    @app.get("/api/health")
    def health() -> dict:
        ready = app.state.pii_ready and app.state.gemini_configured
        return {
            "status": "ready" if ready else "not_ready",
            "pii_ready": app.state.pii_ready,
            "pii_error_type": app.state.pii_error_type,
            "gemini_configured": app.state.gemini_configured,
            "gemini_model": app.state.gemini_model,
        }

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        if not request.text.strip():
            raise HTTPException(status_code=422, detail="내용을 입력해 주세요.")
        if not app.state.pii_ready:
            raise HTTPException(
                status_code=503,
                detail="개인정보 탐지기가 준비되지 않아 전송을 차단했습니다.",
            )
        if not app.state.gemini_configured:
            raise HTTPException(
                status_code=503,
                detail="GEMINI_API_KEY가 설정되지 않아 전송을 차단했습니다.",
            )

        try:
            spans = app.state.detector.detect(request.text)
            masked_text = app.state.detector.mask(request.text, spans)
        except DetectionError:
            raise HTTPException(
                status_code=503,
                detail="개인정보 보호 처리에 실패해 전송을 차단했습니다.",
            ) from None
        except Exception as exc:
            LOGGER.error("PII request failed (%s); source text was not sent", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="개인정보 보호 처리에 실패해 전송을 차단했습니다.",
            ) from None

        try:
            response = app.state.gemini.models.generate_content(
                model=app.state.gemini_model,
                contents=masked_text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.2,
                ),
            )
            answer = response.text
            if not answer:
                raise RuntimeError("Gemini returned an empty response")
        except Exception as exc:
            LOGGER.error("Gemini request failed (%s)", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="Gemini 응답을 받지 못했습니다.",
            ) from None

        counts = Counter(span.label for span in spans)
        return ChatResponse(
            answer=answer,
            masked_text=masked_text,
            detected_items=len(spans),
            detections=[
                DetectionSummary(label=label, count=count)
                for label, count in sorted(counts.items())
            ],
            gemini_model=app.state.gemini_model,
        )

    return app


app = create_app()
