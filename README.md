# 제주 에너지 예측·검토 에이전트

FastAPI/LangGraph 백엔드와 React/TypeScript 프론트엔드로 구성한 출력제한 대응 의사결정 지원 프로젝트입니다. **화면 탐색은 즉시 처리하고, 분석·승인 상태는 서버에서 확인한 사실만 표시합니다.**

현재 기본 실행은 고정 시나리오를 사용하는 **시연**입니다. 실제 설비 제어는 없으며, 시연 승인은 모의 알림만 기록합니다. 발전량·수요 예측 모델은 제주 전체 단위로 학습해 두었고(KPX 이력·기상청 자료), 과거 494일을 실제 출력제한일과 비교해 점검했습니다([파이프라인 점검](docs/guides/pipeline-evaluation.md)). 다만 과거 예보 이력이 없어 **실측 기상을 예보 자리에 넣고** 점검했으므로, 실제 예보로 운영할 때의 정확도는 예보 이력이 쌓인 뒤 다시 확인해야 합니다. 같은 시간의 기상·설비 특성만 쓰는 기존 XGBoost 경로는 선택 사항이며 현장 정확도는 검증되지 않았습니다.

## 대회 제출 정보

「제주 AI·빅데이터 활용 AI Agent 개발 챌린지」 제출용 프로젝트입니다.

| 항목 | 내용 |
|---|---|
| 필수 활용 데이터 | **제주데이터허브 「전기자동차 충전소 정보」(No.494, API)** → 배분 권고의 **EV 흡수 용량** 계산 |
| 허브 교차검증 | **일별 기상 정보(No.756)** 로 기상청 ASOS를 검증하고 수요 모델 입력 기온을 비교 ([결과](docs/guides/hub-weather-check.md)) |
| 보조 데이터 | KPX 발전량·수요·출력제한 이력, 기상청 단기·초단기예보·ASOS (외부 데이터) |
| 기획서 | [docs/submission/01-AI-Agent-기획서.md](docs/submission/01-AI-Agent-기획서.md) |
| 데이터 활용 명세 | [docs/submission/02-데이터-활용-명세.md](docs/submission/02-데이터-활용-명세.md) |

대회 제공 파일(데이터 목록·예시 데이터 엑셀)은 외부 배포가 금지되어 저장소에 넣지 않으며 `.gitignore`가 `*.xlsx`를 제외합니다. 허브에서 수집한 충전소 목록(`backend/runtime/ev_stations.json`)도 `runtime/` 아래라 Git에 올라가지 않습니다.

## 폴더 구조

```text
.
├── README.md                    # 프로젝트 입구: 실행·구조·제약
├── DESIGN.md                    # 색상·타이포·레이아웃 기준
├── UX-CONTRACT.md               # 상태·승인·접근성 공통 동작
├── backend/
│   ├── README.md                # 서버 읽는 순서와 API 예시
│   ├── pyproject.toml / uv.lock # Python 의존성
│   ├── .env.example
│   ├── app/
│   │   ├── main.py              # FastAPI 및 worker 생명주기
│   │   ├── api/                 # HTTP 요청·응답
│   │   ├── core/                # 설정·인증
│   │   ├── domain/              # 데이터 검증·수식·위험 규칙
│   │   ├── agents/              # LangGraph 노드·분기
│   │   ├── tools/               # Tool 1~6
│   │   ├── providers/           # 기상·수요·알림 어댑터
│   │   ├── repositories/       # SQLite 작업·결정·체크포인트
│   │   └── services/            # 접수·실행·복구·승인
│   ├── data/                   # 시연 fixture·수동 보정
│   ├── scripts/                # 선택적 XGBoost 학습
│   └── tests/                  # 서버 통합·규칙·복구 테스트
├── frontend/
│   ├── README.md
│   ├── package.json / package-lock.json
│   ├── src/
│   │   ├── app/                # 메뉴와 화면 조립
│   │   ├── api/                # 통신·인증·응답 검증
│   │   ├── components/         # Button·Modal·StatusBadge
│   │   ├── features/
│   │   │   ├── analysis/       # 입력·차트·상태 관리
│   │   │   ├── allocation/     # 피크 1시간 배분안
│   │   │   ├── approval/       # 결과에 묶인 담당자 결정
│   │   │   └── history/        # 분석 이력
│   │   ├── pages/              # 화면 구성
│   │   ├── styles/             # 토큰·공통 스타일
│   │   └── test/               # 공통 테스트 준비·데이터
│   └── tests/                  # Playwright 브라우저 테스트
└── docs/
    ├── architecture/           # 현재 실행 계약·원본 에이전트 설계
    ├── guides/                 # 학습 순서·데이터 연동
    ├── verification/           # 검증 결과·화면 증거
    └── archive/                # 이전 버전 계획·검증 기록
```

기능에 관한 코드는 `features/기능명`, 여러 기능에서 사용하는 작은 UI는 `components/`에 둡니다. 서버에서는 HTTP(`api`) → 업무 흐름(`services`) → 계산(`agents/tools/domain`) → 저장·외부 연동(`repositories/providers`) 순서로 읽습니다. 과거 문서는 `archive`에 보존하되 현재 실행 안내와 구분했습니다.

## 실행

Python 3.11 이상, Node.js 22, uv를 권장합니다. 두 터미널에서 각각 실행합니다.

```bash
# 터미널 1 — 저장소 루트에서
cd backend
uv sync --frozen --extra dev --extra ml
cp .env.example .env
# backend/.env의 APPROVER_TOKEN에 직접 만든 별도의 인증 토큰을 설정
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
# 터미널 2 — 저장소 루트에서
cd frontend
npm ci
npm run dev
```

화면: `http://localhost:5173` · API 문서: `http://localhost:8000/docs`

GPU·외부 API 키 없이 시연 분석이 가능합니다. 승인 토큰을 설정하지 않으면 승인/반려가 차단됩니다. `API_TOKEN`을 설정한 경우 화면의 **연결 설정**에도 API 키를 입력합니다. API 키는 새로고침하면 지워지며 담당자 토큰은 검토 창에서만 사용합니다. `.env`와 SQLite 파일은 Git에 저장하지 않습니다.

백엔드는 반드시 `backend/`에서 실행합니다. 이전 버전의 `.env`, `runtime/`, `models/`가 루트에 있다면 서버를 정지하고 백업한 뒤 `backend/` 아래로 옮기거나 절대 경로를 설정합니다. 구버전 분석 기록은 조회 전용으로 복구합니다. 개발 중에는 프론트엔드 Vite가 `/api`를 백엔드로 전달합니다. 배포 시에는 같은 출처의 역방향 프록시와 접근제어를 별도로 구성해야 합니다.

### 실제 데이터로 실행 (선택)

키 없이도 시연은 동작합니다. 실제 데이터를 쓰려면 `backend/.env`에 아래 키를 넣습니다. **키는 Git에 올리지 않습니다.**

| 환경변수 | 용도 | 발급 |
|---|---|---|
| `JEJUHUB_PROJECT_KEY` | 제주데이터허브 충전소 API | 허브 로그인 → 데이터를 프로젝트에 담기 → 마이페이지 > 프로젝트 관리 |
| `KMA_API_KEY` | 기상청 단기·초단기예보 | 공공데이터포털 활용신청 |
| `ASOS_API_KEY` | 과거 실측 기상(학습용) | 공공데이터포털 활용신청 |

```bash
# backend/에서: 허브 충전소 목록 수집 → runtime/ev_stations.json
python -m scripts.collect_ev_stations
```

수집 파일이 있으면 배분의 EV 용량을 **운영 중인 충전기 수**로 계산하고 화면에 허브 데이터 기반임을 표시합니다. 없으면 고정 시연값(40 MWh)을 씁니다. 충전기 출력(완속 7 kW·급속 50 kW)과 이용률(50%)은 자료가 없어 둔 **가정**이며 `EV_SLOW_KW`, `EV_FAST_KW`, `EV_IDLE_RATIO`로 바꿀 수 있습니다. 허브 데이터 기준일은 2025-09입니다.

## 기본 실행 구조

```mermaid
flowchart TD
    Click["분석 버튼 · 요청 전송 중"] --> API["FastAPI: 입력·인증 검증"]
    API --> Queue["SQLite에 queued 저장"]
    Queue --> Receipt["202 + 분석 ID · 실행 대기 표시"]
    Queue --> Worker["작업자: 실행 시작·생존 신호 기록"]
    Worker --> Graph["LangGraph + Tool 1~6"]
    Graph --> Snapshot["결과·출처·결과 토큰 저장"]
    UI["화면: 직전 조회 완료 후 다음 조회"] --> Read["독립 DB 연결로 상태 읽기"]
    Read --> Snapshot
    Snapshot --> View["ID·버전·시각·응답 스키마 검증"]
    View --> UI
    UI --> Review["담당자가 특정 결과 검토"]
    Review --> Guard["인증·토큰·최신 여부·만료·시연 조건 재검증"]
    Guard --> Intent["결정 의도 + decision_pending 원자 저장"]
    Intent --> Resume["그래프 재개 · 감사 기록 · 모의 알림"]
```

`queued`는 접수 완료, `running`은 작업자의 실행 시작 확인입니다. 응답 유실은 실패로 단정하지 않고 **상태 확인 불가**로 표시합니다. 재요청은 같은 UUID를 사용해 중복 작업을 막습니다. 조회는 긴 계산 잠금을 기다리지 않습니다. `/health`는 프로세스 응답, `/ready`는 작업자 스레드 생존과 최근 DB 오류 상태를 확인합니다.

## 에이전트 내부 구조

```mermaid
flowchart TD
    A["R1 입력 검증"] --> B["R2 기상 조회 · Tool 1"]
    B --> C["발전량 계산 · Tool 2"]
    C --> D["R3 수요 시간 매칭 · Tool 3"]
    D --> E["R5 잉여전력·위험 · Tool 4"]
    E --> F{"R4 경계값 재검증"}
    F -->|"비율 0.43~0.45 · 한도 이내"| B
    F -->|NORMAL| G["요약 저장 · 종료"]
    F -->|"CAUTION / CRITICAL"| H["R6 자원 배분 · Tool 5"]
    H --> I["R7 통보문 초안 · Tool 6"]
    I --> J["R8 담당자 검토 대기"]
    J --> K["승인 또는 반려 기록"]
```

LangGraph가 명시적인 계산·분기 규칙을 실행합니다. LLM이 발전량이나 위험 수치를 생성하지 않습니다. 선택 기능으로 `ANTHROPIC_API_KEY`(와 `uv sync --extra llm`)를 설정하면 R7 통보문 초안의 문장을 Claude가 씁니다. LLM 문장의 숫자가 입력과 다르면 템플릿 초안으로 대체하고, 키가 없거나 호출이 실패해도 분석은 그대로 진행됩니다(추적에 `R7:draft:llm` 또는 `R7:draft:template:*` 기록). 기존 제한형 질의 API는 저장된 결과에 근거해 답하고 상태를 변경하지 않습니다.

- 시간대 `Asia/Seoul`, 하루 24개의 1시간 구간, 에너지 단위 MWh.
- **위험 판단은 발전량 ÷ 수요 비율**입니다. 하루 중 최대 비율이 NORMAL `<0.40`, CAUTION `0.40 이상 0.45 미만`, CRITICAL `0.45 이상`. 잉여전력(흡수 대상)은 수요의 40% 경계선을 넘는 발전량 `max(0, 발전량 - 0.40 × 수요)`입니다. 제주 출력제한 이력(2021~2024-05)으로 보정한 값이며 이전의 `발전량 - 수요` 150/200 MWh 규칙은 실제 수요에서 출력제한을 한 번도 잡지 못해 바꿨습니다. 근거와 검증: [수요·위험 규칙](docs/guides/demand-options.md).
- 비율 `0.43~0.45`(CRITICAL 직전)는 기본 1회 재조회. 경계가 해소되지 않으면 승인을 막습니다.
- **이중 설계**: 기본은 하루 전 계획(단기예보)입니다. 하루 전이 **정상**으로 끝난 날만 당일에 초단기실황·초단기예보로 최대 2회 다시 점검하고(`phase: intraday`, 당일·직전 결과 NORMAL일 때만 서버가 접수), 위험이 나오면 하루 전 위험과 같은 배분·승인 흐름으로 갑니다. 실패한 점검은 횟수에 세지 않습니다. [당일 점검](docs/guides/intraday-check.md) · [예보 저장 장치](docs/guides/forecast-archive.md)
- 수요는 KPX 하루전 예측(`KPX_URL` 중계)이 1순위이고, 중계가 없거나 끊기면 자체 수요 모델(`JEJU_DEMAND_MODEL_DIR`)이 이어받습니다. 둘 다 없으면 시연값으로 바꾸지 않고 실패합니다(폴백을 켠 경우만 시연값). [수요 모델](docs/guides/demand-model.md)
- 배분은 **피크 1시간**만 대상으로 BESS 37.7(제주 ESS 계량 실적의 시간당 최대 충전량) → VPP 30 → P2X 3.3(제주 행원 그린수소 실증단지 수전해 설비 3.3 MW 보도) → EV 순서입니다. EV 용량은 허브 충전소 파일이 있으면 **그 시각에 운영 중인 충전기로 계산한 값**이고, 없으면 고정 시연값 40 MWh입니다. 충전 이력 프로필(`runtime/ev_profile.json`)이 있으면 실측 평균 전력과 시간대별 점유율을 쓰고(12시 기준 약 109 MWh), 없으면 가정(출력 7/50 kW, 이용률 50%)을 씁니다(약 83 MWh). 나머지 자원은 시연 추정치입니다. 위험 시 **충전 여력이 큰 충전소 TOP 5**도 함께 보여 주며, 순위는 충전소별 설치 규모 기준이라 충전소별 혼잡도는 반영하지 못합니다. 24시간 ESS 운전 최적화가 아닙니다.
- 위험일 시연: 수요 700 MWh, 정오 발전량 510 MWh(비율 0.73) → 피크 잉여 230 MWh. 충전소 파일이 없을 때(EV 고정 40 MWh)는 흡수 111.0 MWh(48.3%) → 잔여 119.0 MWh, 충전소 파일과 충전 이력이 있으면(EV 109.0 MWh) 흡수 180.0 MWh(78.3%) → 잔여 50.0 MWh. 수소 환산은 두 경우 모두 42.9 kg(P2X 3.3 MWh × 13 kg/MWh 가정). 공개된 제주 설비 규모로는 위험일 잉여를 다 받지 못한다는 뜻입니다.
- 외부 조회 실패 시 시연 데이터로 바꾸는 폴백은 기본 꺼져 있습니다. live 결과는 모델·가용량이 미검증이므로 승인과 실제 발송을 차단합니다.
- 같은 날짜·지역·모드의 새 작업이 접수되면 이전 결과의 신규 승인을 막습니다. 기본 검토 유효시간은 완료 후 60분입니다.
- 승인 기록, 모의 알림 기록, 실제 설비 동작은 서로 다릅니다. 이 버전에는 실제 저장·출력제한 명령 경로가 없습니다.

## 검증과 학습

```bash
# backend/에서
uv run pytest -q
uv run ruff check .
uv run ruff format --check .

# frontend/에서
npm test
npm run build
npm run format:check
npx playwright install chromium
npm run test:e2e
```

브라우저 테스트는 서버를 자동으로 띄우며 로컬에서 이미 실행 중이면 재사용합니다. 재사용 서버의 승인 토큰은 테스트용 `local-review-test`여야 합니다. 실제 계정·운영 DB와 분리된 로컬 시연 환경에서 실행합니다.

- [변경 내용과 공부 순서](docs/guides/learning-guide.md)
- [백엔드/API 안내](backend/README.md) · [프론트엔드 안내](frontend/README.md)
- [상태·승인 실행 계약](docs/architecture/execution-contract.md)
- [데이터 연동·기존 회귀 모델 계약](docs/guides/data-contracts.md)
- [파이프라인 점검(과거 날짜 vs 실제 출력제한일)](docs/guides/pipeline-evaluation.md)
- [당일 점검(초단기예보, 시험 브랜치)](docs/guides/intraday-check.md)
- [예보 저장 장치(ML 개선용 이력)](docs/guides/forecast-archive.md)
- [허브 일별 기상 교차검증](docs/guides/hub-weather-check.md)
- [검증 기록](docs/verification/current.md)
- [기획서](docs/submission/01-AI-Agent-기획서.md) · [데이터 활용 명세](docs/submission/02-데이터-활용-명세.md)

현재 구성은 단일 호스트 SQLite 작업 큐입니다. 여러 서버에 걸친 작업 분산, 실제 관측 데이터의 품질 검증, 실제 예보 이력 기반의 예측 정확도 평가와 임계값 재보정, 충전 이력 기반 이용률 보정, 현장 자원 상태 검증은 후속 구현 대상입니다.
