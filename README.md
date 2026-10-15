# Korean PII Guardrail

한국어 개인정보를 탐지하고 마스킹하는 하이브리드 Python 라이브러리입니다. 네 개의 경량 NER 모델, 규칙 탐지, 공식 주소 사전, 금융결제원 계좌번호 체계 근거, 문맥·경계·겹침 후처리를 결합합니다.

## 지원 범위

기본 활성 유형은 다음 13개입니다.

- 이름
- 상세 주소
- 계좌번호
- 전화번호
- 이메일 주소
- IPv4 주소
- 신용카드번호
- 주민등록번호
- 생년월일
- 사용자명
- 여권번호
- 운전면허번호
- 차량번호

건강보험증 번호(`KR_NHIS`)는 선택 기능이며 기본적으로 비활성화됩니다. 나이와 환자번호는 지원하지 않습니다.

## 주요 구성

- `hybrid_pipeline.py`: 네 모델과 규칙을 결합하는 공개 탐지 API
- `precision_policy.py`: 문맥, 경계, 중복 및 겹침 후처리
- `address_boundaries.py`: 상세 주소의 끝 경계와 후속 일반 문장 보존
- `bank_account_catalog.py`: 금융결제원 자료 기반 기관별 계좌번호 체계
- `bank_account_evidence.py`: 같은 줄의 금융기관 근거 확인
- `bank_account_fields.py`: 명시적 계좌 필드 범위 추출
- `bank_account_linking.py`: 모델 예측과 필드·기관 근거 연결
- `gazetteer.py`: 외부 공식 주소 인덱스 로딩과 조회

내부 실험 번호 대신 각 파일의 역할을 이름에 사용합니다.

## 설치

Python 3.10 이상이 필요합니다. 검증 환경은 Python 3.10과 NVIDIA L4 CUDA입니다.

```bash
python -m pip install .
```

의존성 버전은 `pyproject.toml`에 고정되어 있습니다. GPU용 PyTorch 빌드와 드라이버 호환성을 먼저 확인하십시오.

## 모델과 주소 사전 준비

모델 가중치와 주소 DB는 저장소에 포함하지 않습니다.

```bash
export KOREAN_PII_DEVICE=cuda
export KOREAN_PII_MODEL_FRAME=/path/to/frame
export KOREAN_PII_MODEL_KOREDACT=/path/to/koredact
export KOREAN_PII_MODEL_ATONLEE=/path/to/atonlee
export KOREAN_PII_MODEL_SEONGYEON=/path/to/seongyeon
export KOREAN_PII_ADDRESS_INDEX=/path/to/official_address_index.sqlite
```

모델 파일을 확인합니다.

```bash
python -m korean_pii.model_check --verify-hashes
```

저장소에서 고정된 모델 revision을 준비할 때는 먼저 다운로드 계획을 확인한 뒤 명시적으로 실행합니다.

```bash
python tools/download_model_weights.py
python tools/download_model_weights.py --download
```

공식 주소 원본 ZIP으로 런타임 인덱스를 만드는 명령도 wheel에 포함됩니다.

```bash
korean-pii-build-address-index --help
```

## 사용

```python
from korean_pii import detect, mask

text = "김민수님에게 연락해주세요."
spans = detect(text)
masked_text = mask(text)
print(spans)
print(masked_text)
```

`detect()`는 라벨과 문자 위치를 반환하고 `mask()`는 탐지 영역을 유형별 토큰으로 바꿉니다. 동일 프로세스에서는 모델 인스턴스를 재사용합니다.

## 설정

`source/korean_pii/default-policy.json`을 별도 파일로 복사한 뒤 `KOREAN_PII_CONFIG`로 지정할 수 있습니다.

- `types.<label>.enabled`: 유형 활성화 여부
- `candidate_threshold`: 후보 모델 임계값
- `expert_threshold`: 전문 모델 임계값
- `context_chars`: 후보 주변 문맥 범위
- `runtime.max_text_chars`: 처리 가능한 전체 입력 길이

임계값을 `0`으로 설정하는 것은 비활성화가 아닙니다. 모델별 점수는 원시 점수이며 보정된 정답 확률이 아닙니다. 설정을 바꾸면 회귀 평가를 다시 실행하십시오.

## 검증 결과

예측 전에 봉인한 독립 장문 12건, 총 27,837자에서 다음 결과를 확인했습니다.

- 13개 유형 정답 156/156 전체 보호
- 부분 보호 0, 미탐 0
- 일반정보 오탐 및 정답 밖 과마스킹 0
- raw 및 최종 span 중복·겹침 0
- 유형·경계 exact TP 156, FP 0, FN 0
- 평균 503.39ms, p95 666.53ms, 초당 약 4,608자
- 기능별 과거 회귀 1,014/1,014 통과
- 기존 공개 기본 정책 검사 115/115 통과

정적 증적 감사:

```bash
python evaluation/audit_release_results.py
```

모델 환경에서 패키지 출력 동등성 확인:

```bash
PYTHONPATH=source python evaluation/verify_packaged_output.py \
  --fixture evaluation/long_document_generalization/long_document_test_set.jsonl \
  --expected evaluation/long_document_generalization/raw_and_masked_predictions.jsonl \
  --output /tmp/packaged_output_equivalence.json
```

상세 내용은 다음 문서를 참고하십시오.

- `docs/hybrid_pipeline_release_report_ko.md`
- `docs/deployment_guide_ko.md`
- `docs/product_integration_guide_ko.md`
- `evaluation/long_document_generalization/README.md`
- `release_manifest.json`

합성 독립 세트 통과는 모든 실서비스 분포에서 무오류를 보장하지 않습니다. 운영 데이터는 별도 승인·보안 절차와 지속적인 오탐·미탐 모니터링이 필요합니다.

## 라이선스 및 배포 주의사항

외부 모델과 라이브러리 고지는 `THIRD_PARTY_NOTICES.md`를 확인하십시오. 일부 모델은 CC-BY-SA-4.0입니다. 이 저장소 코드의 공개 라이선스는 아직 지정되지 않았습니다.

다음 항목은 Git에 올리지 않습니다.

- 모델 가중치
- 실제 개인정보
- 인증정보
- 서버 전용 환경 파일과 절대경로
- 공식 주소 DB 원본
