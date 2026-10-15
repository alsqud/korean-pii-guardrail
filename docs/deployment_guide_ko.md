# 하이브리드 개인정보 탐지 파이프라인 배포 안내

## 배포 원칙

- 배포할 Git 커밋과 모델·정책·주소 사전 해시를 기록한다.
- 모델 가중치와 주소 DB는 저장소 밖에서 관리한다.
- 새 버전은 별도 디렉터리에 설치한 뒤 스모크 테스트를 통과해야 활성화한다.
- 기존 설치와 환경 파일을 보존해 즉시 되돌릴 수 있게 한다.

## 필수 환경변수

```bash
export KOREAN_PII_DEVICE=cuda
export KOREAN_PII_MODEL_FRAME=/path/to/frame
export KOREAN_PII_MODEL_KOREDACT=/path/to/koredact
export KOREAN_PII_MODEL_ATONLEE=/path/to/atonlee
export KOREAN_PII_MODEL_SEONGYEON=/path/to/seongyeon
export KOREAN_PII_ADDRESS_INDEX=/path/to/official_address_index.sqlite
```

실제 경로와 인증정보를 Git에 커밋하지 않는다.

## 설치 및 확인

```bash
python -m pip install .
python -m korean_pii.model_check --verify-hashes
python evaluation/audit_release_results.py
```

모델과 주소 사전이 준비된 환경에서는 장문 평가를 다시 실행할 수 있다.

```bash
PYTHONPATH=source python evaluation/run_hybrid_pipeline.py \
  --fixture evaluation/long_document_generalization/long_document_test_set.jsonl \
  --output /tmp/hybrid_pipeline_predictions.jsonl
```

## 활성화 전후 확인

동일 입력에 대해 다음 항목이 기존 검증 결과와 일치해야 한다.

- raw span의 라벨과 시작·끝 위치
- 실제 마스킹에 선택된 span
- 최종 마스킹 문자열
- 실패 건수

## 롤백

활성 환경 파일이나 배포 심볼릭 링크를 직전 버전으로 복원한 뒤 프로세스를 다시 시작한다. 롤백 명령은 운영 환경별 배포 기록에 남기되, 서버 절대경로는 공개 저장소 문서에 기록하지 않는다.
