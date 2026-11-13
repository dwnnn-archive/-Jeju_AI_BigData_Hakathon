# Jeju Backend Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation and one independent final review.

**Goal:** 실행 가능한 백엔드 API, 영속 에이전트와 승인 흐름을 제공한다.
**Architecture:** FastAPI + 단일 LangGraph + SQLite. 순수 계산 함수와 외부 어댑터를 분리한다.
**Tech Stack:** Python 3.11+, Pydantic 2, LangGraph 1, pytest; 선택적 XGBoost 3.
**Spec:** [design.md](design.md), [README.md](../README.md).

## Global Constraints

- KST 24시간, MWh; 위험 경계 150/200, 재조회 구간 190~200, 기본 한도 1.
- BESS/VPP/P2X/EV 70/30/30/40 MWh, P2X 13kg/MWh; 피크 1시간만 배분.
- 시연·추정 자료 표시, 승인 전 발송 금지, 외부 설비 제어 없음.

## Review Focus

1. 중복/누락/다른 날짜 수요는 24시간 검증에서 거부.
2. 재시작과 동시 승인에도 발송함 하나, 반려 뒤 승인 불가.
3. 경계가 지속되어도 재조회 횟수가 유한.
4. 실 API 실패 폴백/수치 추정은 실전송 차단.
5. NaN/음수/설비 중복/범위 밖 날짜는 입력 경계에서 처리.

## Task 1: 수치 도메인

Files: backend/domain/{schemas,rules}.py, tests/test_rules.py.
Interfaces: evaluate(generation, demand) → hourly/risk/peak, allocate(peak, capacities) → 배분.
- [ ] 경계·음수·중복·시간 정렬·230MWh 수치 테스트를 먼저 작성하고 실패 확인.
- [ ] Pydantic 스키마, 순수 계산/배분 함수 구현.
- [ ] `pytest tests/test_rules.py` 전체 통과 후 커밋.

## Task 2: 도구와 데이터

Files: backend/{tools,providers}/, data/, scripts/train_model.py, tests/test_tools.py.
Interfaces: weather(request, refresh), demand(request), predict(weather, capacities), draft(result).
- [ ] 파워커브·격자·시연·기상청 파싱·수요 검증·보정 테스트 실패 확인.
- [ ] Tool 1~6 및 어댑터, XGBoost 학습/추론 구현.
- [ ] `pytest tests/test_rules.py tests/test_tools.py` 통과 후 커밋.

## Task 3: 영속 그래프와 API

Files: backend/{agents,repositories,services,api,core}/, backend/main.py, tests/test_api.py.
Interfaces: create_analysis(request), get_analysis(id), decide(id, decision), dispatch(id).
- [ ] 3개 시나리오, 인증, 재시작, 중복 승인/발송, 반려, live 게이트 테스트 실패 확인.
- [ ] LangGraph interrupt와 SQLite 저장, 인증된 FastAPI 경로 구현.
- [ ] `pytest` 전체 통과 후 커밋.

## Task 4: 실행/연동 문서와 최종 확인

Files: README.md, docs/data-contracts.md, .env.example, .github/workflows/tests.yml.
- [ ] 실제 실행 명령, curl 예시, 데이터 한계, 학습 명령을 문서화.
- [ ] `ruff check .`, `ruff format --check .`, `pytest` 실행.
- [ ] 서버 HTTP 시나리오 확인, 독립 코드 리뷰 후 필요한 수정 검증.
- [ ] dwnnn으로 커밋/푸시하고 원격 SHA 확인.
