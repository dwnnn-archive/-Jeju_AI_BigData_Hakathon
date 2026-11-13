# 백엔드 읽기 안내

프로세스는 이 폴더에서 실행합니다. 설치·실행 명령은 [루트 README](../README.md#실행)에 있습니다.

## 코드 읽는 순서

1. `app/main.py`: FastAPI를 만들고 작업자를 시작·종료합니다.
2. `app/api/routes.py`: HTTP 입력을 서비스에 전달합니다. 계산을 직접 하지 않습니다.
3. `app/services/jobs.py`: 작업 접수, 확인 가능한 상태, 승인 정책을 관리합니다.
4. `app/repositories/jobs.py`: 짧은 SQLite 트랜잭션으로 접수·생존 신호·결과 스냅샷을 저장합니다.
5. `app/services/worker.py`: 큐에서 실행할 작업을 찾고, 일시적인 DB 오류 후 복구합니다.
6. `app/services/analysis.py` → `app/agents/graph.py`: 기존 계산 그래프를 실행하고 승인 후 재개합니다.
7. `app/domain/rules.py`, `app/tools/`: 숫자의 단위, 위험 계산, 배분 규칙을 확인합니다.
8. `tests/test_jobs.py`, `tests/test_recovery.py`: 잘못된 승인을 막는 실패 상황을 읽습니다.

## 분석 API 예시

```bash
curl -X POST http://localhost:8000/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 77b5e20c-6b9b-4d75-b203-88241c36b3a1' \
  -d '{"date":"2026-11-15","region":"jeju","mode":"demo","scenario":"critical"}'
```

202는 접수만 뜻합니다. `GET /api/v1/analyses/77b5e20c-6b9b-4d75-b203-88241c36b3a1`로 상태를 조회합니다. 새 분석에는 새 UUID를 사용하고, 접수 응답을 잃은 경우에만 동일 UUID·동일 요청을 재사용합니다.

결과가 `awaiting_approval`이고 `can_decide=true`일 때, 응답의 `result_token`을 사용합니다.

```bash
curl -X POST http://localhost:8000/api/v1/analyses/<id>/decision \
  -H 'Content-Type: application/json' \
  -H 'X-Approver-Token: <backend/.env에 설정한 토큰>' \
  -d '{"action":"approve","reason":"시연 결과 검토","result_token":"<조회한 64자리 토큰>"}'
```

`API_TOKEN`을 설정했다면 모든 `/api/v1` 호출에 `X-API-Key`도 필요합니다. 토큰을 문서·Git에 넣지 않습니다.

| API | 의미 |
|---|---|
| POST `/api/v1/analyses` | UUID 멱등 키로 영속 접수, 202 |
| GET `/api/v1/analyses?limit=30` | 최근 이력 요약, 최대 100건 |
| GET `/api/v1/analyses/{id}` | 결과·실행·승인 가능 여부·출처 |
| POST `/api/v1/analyses/{id}/decision` | 특정 결과에 대한 승인/반려 |
| POST `/api/v1/analyses/{id}/dispatch` | 승인된 시연 알림 재처리, body에 result_token 필요 |
| GET `/api/v1/analyses/{id}/audit` | 담당자·사유·결정 시각 |
| POST `/api/v1/analyses/{id}/chat` | 저장된 결과에 대한 제한형 질의 |
| GET `/health`, `/ready` | 프로세스 응답, 작업자 준비 상태 |

401 인증 오류, 404 접수 미확인, 409 결과/결정 충돌, 422 잘못된 요청, 503 일시 사용 불가입니다. 계산 중 예외는 이미 접수된 작업의 `failed` 상태로 기록합니다. 503/통신 단절만으로 결정 실패나 미접수를 단정하면 안 됩니다.

## 저장과 잠금

`jobs`는 화면 조회용 상태, LangGraph 체크포인트는 내부 실행 상태, `decision_intents`는 담당자의 결정 의도, `audit`는 확정 기록, `outbox`는 알림 기록입니다. 각 책임을 분리하되 결정 의도와 `decision_pending`은 하나의 트랜잭션으로 저장합니다.

계산은 직렬화합니다. 상태 조회는 별도 연결로 읽어 계산을 기다리지 않습니다. 결정 처리도 계산 잠금을 최대 250ms만 기다린 뒤, 확보한 시점의 만료·최신 여부를 검증합니다. 잠금이 바쁘면 503을 반환하며 새 승인 성공을 표시하지 않습니다. 다른 요청의 접수 잠금을 오래 붙잡지 않습니다.

작업자가 중단되면 확인 가능한 체크포인트로 복구하고, 결과를 복구할 수 없는 실행은 `interrupted`로 표시합니다. 미완료 결정은 같은 action·reason·actor로만 재시도할 수 있습니다. DB 일시 오류는 재시도하고 `/ready`에서 문제를 노출합니다.
