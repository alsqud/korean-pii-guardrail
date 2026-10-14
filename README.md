Korean PII Guardrail
한국어 개인정보 탐지·마스킹 Python 라이브러리입니다. 경량 NER 모델, 규칙, 후보별 전문 모델 라우팅과 경계 보정을 결합합니다.
지원 범위
기본 활성 13종: 이름, 상세 주소, 계좌번호, 전화번호, 이메일, IPv4 주소, 카드번호, 주민등록번호, 생년월일, 로그인 아이디, 여권번호, 운전면허번호, 차량번호.
건강보험증 번호(KR_NHIS)는 선택 기능이며 기본 OFF입니다. 전용 LoRA 가중치는 이 저장소에 포함하지 않습니다. 활성화에는 별도 가중치 준비 및 검증이 필요합니다. 나이와 환자번호는 지원하지 않습니다.
설치
Python 3.10 이상이 필요합니다. 실제 검증 환경은 Python 3.10과 NVIDIA L4 CUDA 환경입니다.
저장소를 내려받아 프로젝트 루트에서 실행합니다:
python -m pip install .
의존성 버전은 pyproject.toml에 고정되어 있습니다. GPU용 PyTorch 빌드와 드라이버 호환성을 먼저 확인하십시오. 기존 검증 서버에서 wheel 설치와 기능 테스트를 통과했으며, 새로운 빈 환경에서의 전체 의존성 설치는 별도 확인이 필요합니다.
모델 준비
모델 가중치는 Python 패키지에 포함하지 않습니다. source/korean_pii/model-manifest.json에 명시된 모델 ID와 revision의 모델·토크나이저 파일을 별도로 준비하십시오.
모델별 경로 환경변수:
- KOREAN_PII_MODEL_FRAME
- KOREAN_PII_MODEL_KOREDACT
- KOREAN_PII_MODEL_ATONLEE
- KOREAN_PII_MODEL_SEONGYEON
각 변수에 해당 모델이 저장된 로컬 디렉터리를 지정합니다. 기본 경로는 ~/.cache/korean-pii/models/ 아래의 frame, koredact, atonlee, seongyeon입니다.
GPU 실행 설정:
export KOREAN_PII_DEVICE=cuda
모델 파일 확인:
python -m korean_pii.model_check --verify-hashes
사용
Python에서 호출:
from korean_pii import detect, mask
text = "김민수님에게 연락해주세요."
spans = detect(text)
masked_text = mask(text)
print(masked_text)
탐지는 유형과 문자 위치 등을 반환하고, 마스킹은 탐지된 부분을 유형별 태그로 바꿉니다. 동일 프로세스에서 모델 인스턴스를 재사용합니다. detect와 mask를 각각 호출하면 탐지를 두 번 수행하므로 마스킹만 필요하면 mask만 호출하십시오.
터미널 수동 테스트:
python -m korean_pii.cli
CLI를 새로 실행할 때마다 모델 로딩 시간이 발생할 수 있습니다.
설정
source/korean_pii/default-policy.json 전체를 별도 JSON 파일로 복사한 뒤 수정합니다. KOREAN_PII_CONFIG 환경변수에 그 파일 경로를 지정하고 프로세스를 다시 시작하십시오.
- types의 해당 유형 enabled=false: 해당 유형 비활성화
- candidate_threshold: 적용 가능한 모델 후보의 점수 필터
- expert_threshold: 해당 전문 모델 결과의 점수 필터
- context_chars: 후보 주변 문맥 범위
임계값을 0으로 설정하는 것은 비활성화가 아닙니다. 규칙과 직접 출력 경로에는 전문 모델 임계값이 적용되지 않습니다. 점수는 모델별 원시 점수이며 실제 정답 확률을 뜻하지 않습니다. 설정 변경 후에는 회귀 테스트를 다시 실행하십시오.
검증 결과와 한계
기본 정책 internal-0.2.2rc1-nhis-default-off에서 합성 장문 4개, 사전 정의 확인 항목 115개가 모두 통과했습니다. 이는 28,000개 전체 데이터셋 평가나 실서비스 정확도 보장이 아닙니다.
NVIDIA L4, 669~898자 합성 문서, 모델 로딩 제외 측정:
- 평균 703.1ms, 중앙값 651.0ms, p95 880.0ms
- 첫 요청은 모델 로딩 포함 약 10.48초
- 8건 동시 도착을 단일 worker FIFO로 처리: 평균 완료지연 3.11초, p95 5.49초
8건 GPU 병렬 추론 결과가 아니며, 작은 합성 표본 측정으로 SLA를 보장하지 않습니다. 4B·9B 생성 모델과 동일 조건 비교는 수행하지 않았습니다.
회귀 테스트는 저장소 루트에서 실행합니다:
python tests/validate_v4_default_off.py
결과는 results/v4-default-off.json에 저장됩니다.
주소는 상세 주소 경계 보정을 사용하며 전국 주소 사전 검증은 포함하지 않습니다. 오탐·미탐이 발생할 수 있으므로 적용 업무 데이터로 검증해야 합니다. 이미지·PDF 파싱과 이미지 좌표 마스킹은 별도 구성 요소가 필요합니다.
라이선스 및 배포
외부 모델·라이브러리 고지는 THIRD_PARTY_NOTICES.md를 확인하십시오. 일부 모델은 CC-BY-SA-4.0입니다. 이 저장소의 코드에 대한 공개 라이선스는 아직 지정되지 않았습니다. 모델 가중치, 실제 개인정보, 인증정보, 서버 전용 환경 설정은 저장소에 올리지 마십시오.
모델 다운로드 도구
저장소 루트의 download_models.py는 model-manifest.json에 기록된 고정 revision을 사용합니다. 다운로드 도구는 huggingface-hub 1.33.0 환경에서 목록 출력까지 확인했습니다. 실제 네트워크 다운로드는 별도 검증이 필요합니다.
다운로드 대상만 확인:
python download_models.py
모델이 없는 새 환경에서 실제 다운로드:
python download_models.py --download
모델 경로 환경변수가 있으면 그 경로를 사용하고, 없으면 manifest의 기본 경로를 사용합니다. 기존 디렉터리는 덮어쓰지 않고 중단합니다. 다운로드한 가중치의 SHA-256을 확인한 뒤 대상 경로로 배치합니다.
이미 모델을 준비한 환경에서는 다시 다운로드할 필요 없이 다음 명령으로 확인합니다:
python -m korean_pii.model_check --verify-hashes
