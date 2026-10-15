"""Offline tests proving that only masked text reaches the Gemini client."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import SMOKE_TEXT, create_app
from korean_pii import DetectionError, Span


class FakeAddressGazetteer:
    def load(self) -> None:
        pass


class FakeDetector:
    def __init__(self, fail_on_source: bool = False):
        self.address_gazetteer = FakeAddressGazetteer()
        self.policy = SimpleNamespace(models={"one": object()})
        self.status = {
            "loaded_models": ("one",),
            "address_gazetteer": {"configured": True, "loaded": True},
        }
        self.fail_on_source = fail_on_source

    def detect(self, text: str):
        if text == SMOKE_TEXT:
            return (
                Span("PERSON", 9, 12, "fake"),
                Span("KR_PHONE_NUMBER", 24, 37, "fake"),
                Span("EMAIL_ADDRESS", 48, 69, "fake"),
            )
        if self.fail_on_source:
            raise DetectionError("synthetic failure")
        start = text.index("김민수")
        return (Span("PERSON", start, start + 3, "fake"),)

    def mask(self, text: str, spans):
        span = spans[0]
        return text[:span.start] + "<PERSON>" + text[span.end:]


class FakeGeminiModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text="마스킹된 요청을 처리했습니다.")


class FakeGemini:
    def __init__(self):
        self.models = FakeGeminiModels()

    def close(self):
        pass


class DemoTests(unittest.TestCase):
    def build_client(self, detector=None, gemini=None):
        detector = detector or FakeDetector()
        gemini = gemini or FakeGemini()
        app = create_app(lambda: detector, lambda: gemini)
        return TestClient(app), gemini

    def test_only_masked_text_reaches_gemini(self):
        source = "개인 담당자 김민수의 일정을 정리해줘."
        client, gemini = self.build_client()
        with patch.dict(os.environ, {"GEMINI_MODEL": "test-model"}), client:
            response = client.post("/api/chat", json={"text": source})

        self.assertEqual(response.status_code, 200)
        sent = gemini.models.calls[0]["contents"]
        self.assertNotIn("김민수", sent)
        self.assertIn("<PERSON>", sent)
        self.assertEqual(response.json()["masked_text"], sent)
        self.assertNotIn("김민수", str(gemini.models.calls))

    def test_page_and_health_are_available(self):
        client, _ = self.build_client()
        with client:
            page = client.get("/")
            health = client.get("/api/health")

        self.assertEqual(page.status_code, 200)
        self.assertIn("PII Guardrail + Gemini", page.text)
        self.assertEqual(health.json()["status"], "ready")

    def test_detection_failure_blocks_gemini(self):
        client, gemini = self.build_client(detector=FakeDetector(fail_on_source=True))
        with client:
            response = client.post(
                "/api/chat", json={"text": "개인 담당자 김민수의 일정을 정리해줘."}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(gemini.models.calls, [])
        self.assertNotIn("김민수", response.text)

    def test_missing_gemini_key_blocks_request(self):
        app = create_app(lambda: FakeDetector(), lambda: None)
        with TestClient(app) as client:
            health = client.get("/api/health")
            response = client.post(
                "/api/chat", json={"text": "개인 담당자 김민수의 일정을 정리해줘."}
            )

        self.assertEqual(health.json()["status"], "not_ready")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
