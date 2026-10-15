# PII Guardrail + Gemini 초간단 웹 예제

브라우저에서 입력한 한국어 문장을 로컬 `KoreanPII`로 먼저 마스킹하고,
마스킹된 결과만 Gemini API에 보내는 최소 예제입니다.

```text
브라우저 → 로컬 FastAPI → KoreanPII 탐지·마스킹 → Gemini API
                          원문은 여기서 멈춤 ───────┘
```

## 1. 설치

저장소 루트에서 Python 3.10 이상의 별도 가상환경을 만듭니다.

```bash
python3.10 -m venv .venv-gemini-demo
source .venv-gemini-demo/bin/activate
python -m pip install .
python -m pip install -r examples/simple_gemini_web/requirements.txt
```

## 2. 서버 환경변수 설정

PII 모델 4개, 공식 주소 인덱스, Gemini API 키를 서버 프로세스에만
설정합니다. API 키를 `index.html`이나 Git에 넣으면 안 됩니다.

```bash
export KOREAN_PII_DEVICE=cpu  # CUDA 서버이면 cuda
export KOREAN_PII_MODEL_FRAME=/absolute/path/to/frame
export KOREAN_PII_MODEL_KOREDACT=/absolute/path/to/koredact
export KOREAN_PII_MODEL_ATONLEE=/absolute/path/to/atonlee
export KOREAN_PII_MODEL_SEONGYEON=/absolute/path/to/seongyeon
export KOREAN_PII_ADDRESS_INDEX=/absolute/path/to/official_address_index.sqlite
export GEMINI_API_KEY=your_server_side_api_key
export GEMINI_MODEL=gemini-3.8-flash
```

모델과 주소 인덱스 준비 방법은 저장소 루트의
[`docs/deployment_guide_ko.md`](../../docs/deployment_guide_ko.md)를 먼저 확인합니다.

## 3. 준비 상태 확인

```bash
korean-pii-model-check --verify-hashes
korean-pii-health
```

두 명령이 각각 모델 파일 무결성과 전체 탐지 준비 상태를 검사합니다.
`korean-pii-health`가 `ready`가 아니면 이 웹 예제도 원문 전송을 차단합니다.

## 4. 실행

```bash
cd examples/simple_gemini_web
uvicorn app:app --host 127.0.0.1 --port 8000
```

브라우저에서 <http://127.0.0.1:8000>을 엽니다. 화면에는 Gemini 답변과
Gemini에 실제로 보낸 마스킹 문장이 함께 표시됩니다.

모델 4개를 메모리에 유지해야 하므로 데모에서는 worker를 하나만 사용합니다.
운영 배포 시 worker를 늘리면 worker마다 모델을 별도로 적재한다는 점을
용량 산정에 반영해야 합니다.

## 5. 원문 전송 차단 테스트

이 테스트는 실제 모델이나 Gemini API를 호출하지 않습니다. 가짜 탐지기와
가짜 Gemini 클라이언트로 다음을 확인합니다.

- 원문 개인정보가 Gemini 호출 인자에 없음
- 마스킹 토큰만 Gemini 호출 인자에 있음
- PII 탐지 실패 시 Gemini 호출이 0회임
- Gemini API 키가 없으면 요청을 차단함

```bash
cd examples/simple_gemini_web
python -m unittest -v test_app.py
```

## 운영 전 주의사항

- 이 코드는 로컬 검증용이며 외부에 그대로 공개하는 웹 서비스가 아닙니다.
- 운영 환경에는 인증, TLS, 요청 크기·빈도 제한, CSRF 정책을 추가해야 합니다.
- 원문과 탐지된 개인정보 값을 애플리케이션·프록시·분석 로그에 남기지 마세요.
- 탐지기는 완전무결하지 않으므로 승인된 실제 분포의 데이터로 별도 평가하세요.
- 탐지 또는 마스킹 실패 때 원문을 대신 보내는 fallback을 만들지 마세요.
