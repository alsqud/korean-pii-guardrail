# 제품 통합 안내

이 문서는 팀원이 하이브리드 개인정보 탐지기를 자신의 서비스 프로세스에 설치하고 호출하기 위한 절차를 설명한다.

## 배포 단위

배포 단위는 `korean-pii-guardrail` Python wheel이다. 모델 가중치와 공식 주소 인덱스는 크기와 라이선스, 갱신 주기가 다르므로 wheel에 포함하지 않고 대상 환경에서 별도로 준비한다.

패키지 버전은 표준 Python 패키지 버전으로 관리한다. 내부 실험 번호는 모듈명이나 제품 API에 노출하지 않는다.

## 설치

Git 브랜치에서 직접 설치:

```bash
python -m pip install \
  "git+https://github.com/alsqud/korean-pii-guardrail.git@feat/hybrid-pii-long-document-guardrails"
```

wheel을 전달받은 경우:

```bash
python -m pip install korean_pii_guardrail-0.3.0rc1-py3-none-any.whl
```

배포 wheel의 SHA-256은 다음과 같다.

```text
b13aaa1117a6465656fd34568653a87d850402c874f7a2d336f41492e3a50e40
```

설치 전에 `release_manifest.json`과 다운로드한 파일의 해시가 일치하는지 확인한다.

GPU용 PyTorch와 NVIDIA 드라이버의 호환성을 먼저 확인한다.

## 모델 준비

`source/korean_pii/model-manifest.json`에 고정된 모델 ID, revision, 가중치 SHA-256을 사용한다. 준비 후 다음 환경변수를 설정한다.

```bash
export KOREAN_PII_DEVICE=cuda
export KOREAN_PII_MODEL_FRAME=/path/to/models/frame
export KOREAN_PII_MODEL_KOREDACT=/path/to/models/koredact
export KOREAN_PII_MODEL_ATONLEE=/path/to/models/atonlee
export KOREAN_PII_MODEL_SEONGYEON=/path/to/models/seongyeon
```

파일 검증:

```bash
korean-pii-model-check --verify-hashes
```

명령 결과가 `status: ok`가 아니면 프로세스를 시작하지 않는다.

## 공식 주소 인덱스 준비

행정안전부 행정동·법정동 자료와 도로명주소 개발자센터 도로명 자료를 공식 사이트에서 내려받는다.

- 행정동·법정동: <https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000052&nttId=130109>
- 도로명: <https://business.juso.go.kr/jst/jstAddressDownload?menu=7>

다운로드 파일의 날짜와 SHA-256을 내부 배포 기록에 남긴 뒤 인덱스를 생성한다.

```bash
korean-pii-build-address-index \
  --mois-zip /path/to/jscode.zip \
  --road-zip /path/to/road_names.zip \
  --road-snapshot-date YYYYMM \
  --output /path/to/official_address_index.sqlite

export KOREAN_PII_ADDRESS_INDEX=/path/to/official_address_index.sqlite
```

빌더는 입력 형식, 최소 행 수, SQLite 무결성을 검사하며 기존 출력 파일을 덮어쓰지 않는다.

## 서비스 코드에 연결

모델 로딩 비용이 크므로 요청마다 객체를 만들지 않는다. 서비스 worker가 시작할 때 한 번 생성하고 재사용한다.

```python
from korean_pii import DetectionError, KoreanPII

detector = KoreanPII()
detector.address_gazetteer.load()

def protect_user_text(text: str) -> str:
    try:
        spans = detector.detect(text)
        return detector.mask(text, spans)  # 같은 spans를 넘겨 중복 추론 방지
    except DetectionError:
        # 원문을 그대로 반환하거나 로그에 기록하지 않는다.
        raise
```

전체 예제는 `examples/product_integration.py`에 있다.

## 시작 전 헬스체크

```bash
korean-pii-health
```

다음을 모두 확인해야 `status: ready`를 반환한다.

- 네 모델의 실제 로딩
- 공식 주소 인덱스 설정과 로딩
- 짧은 합성 입력의 이름·전화번호·이메일 탐지
- 활성 파이프라인 식별자

## 입력과 실패 처리

- 기본 최대 입력 길이는 100,000자다.
- 토크나이저 길이를 넘는 입력은 공통 chunk/stride 처리 경로를 사용한다.
- 탐지 실패 시 원문을 통과시키지 않고 `DetectionError`로 fail closed한다.
- 원문, raw span 표면값, 마스킹 전 텍스트를 애플리케이션 로그에 기록하지 않는다.
- 하나의 worker 안에서 모델 객체를 재사용한다. 동시성 방식은 대상 서비스의 worker·GPU 구성으로 부하 시험한 뒤 정한다.

## 검증

모델 없이 저장된 증적을 감사한다.

```bash
python evaluation/audit_release_results.py
```

모델이 준비된 환경에서는 설치된 패키지의 raw·selected·masked 출력 동등성을 확인한다.

```bash
PYTHONPATH=source python evaluation/verify_packaged_output.py \
  --fixture evaluation/long_document_generalization/long_document_test_set.jsonl \
  --expected evaluation/long_document_generalization/raw_and_masked_predictions.jsonl \
  --output /tmp/packaged_output_equivalence.json
```

## 운영 반영과 롤백

1. 새 wheel을 별도 가상환경 또는 버전 디렉터리에 설치한다.
2. 모델 해시 검사와 `korean-pii-health`를 실행한다.
3. 제품의 대표 입력으로 사전 스모크 테스트를 실행한다.
4. 트래픽을 새 worker로 전환한다.
5. 오류율, 처리시간, 오탐·미탐 샘플링을 관찰한다.
6. 문제가 있으면 직전 wheel과 정책·주소 인덱스 조합으로 되돌린다.

wheel, Git 커밋, 모델 revision·해시, 정책 해시, 주소 인덱스 해시를 하나의 배포 기록으로 묶어야 재현 가능한 롤백이 가능하다.
