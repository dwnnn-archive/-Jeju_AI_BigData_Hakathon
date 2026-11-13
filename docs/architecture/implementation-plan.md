# 정확한 상태 전달과 프론트엔드 구현 계획

Goal: 서버가 증명하는 실행 상태를 표시하고 결과에 묶인 승인을 제공한다.
Spec: execution-contract.md. Stack: FastAPI, LangGraph, SQLite, React, TypeScript, Vite.

1. backend/app, backend/tests, backend/scripts, backend/data 및 frontend/src 기능별 구조로 정리한다. 기존 48개 테스트를 이동 후 재실행한다.
2. repositories/jobs.py: 접수/멱등성/생존 신호/스냅샷/버전/결과토큰을 테스트 우선 구현한다.
3. services/jobs.py, services/worker.py: 계산과 조회 분리, 재시작 복구, 승인 정책을 테스트한다. API는 202와 상태 조회 계약으로 전환한다.
4. frontend: 공통 API 클라이언트와 상태 관리, 분석·배분·승인·이력 화면을 구현한다. 실제 상태 확인 전 분석 중 표시 금지, 응답 유실/역순/중복 클릭을 검증한다.
5. 브라우저 검증: 데스크톱/모바일/키보드/오류/승인 시연과 스크린샷. 오래 걸리는 계산 중 상태 조회 지연과 UI 갱신 비용을 측정하고 불필요한 반복 호출을 제거한다.
6. 독립 코드 리뷰, 전체 테스트, 빌드와 파일 변경 학습 가이드를 작성하고 dwnnn에 반영한다.

Review focus: 접수 전 오표시, 통신 유실, worker 장애, stale result 승인, 오래된 응답 덮어쓰기, 운영 데이터 폴백, 중복 결정, 전송/설비조치 상태 혼동.

진행 결과: 1~6 구현 및 검증 완료. 발견한 경계 상황과 수정 결과는 `../verification/current.md`, 공부 순서는 `../guides/learning-guide.md`에 기록한다.
