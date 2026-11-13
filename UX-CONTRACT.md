# 공통 동작 계약

권위: 사용자 지시 및 docs/architecture/execution-contract.md. 한국어, Asia/Seoul, WCAG 2.2 AA를 목표로 한다.

| 기능 | 공통 소유자 | 선택 |
|---|---|---|
| API 응답 검증 | frontend/src/api/client.ts | Zod 런타임 검증, no-store, 타임아웃 |
| 실행 상태 | frontend/src/features/analysis/useAnalysis.ts | 서버 상태만 채택, ID/버전/요청 세대 확인 |
| 버튼 | frontend/src/components/Button.tsx | busy 크기 유지, 중복 실행 금지 |
| 선택 | AnalysisForm의 native select | OS 동작 허용, 한국어 선택지 |
| 날짜 | AnalysisForm의 native date | OS 달력 허용, 결과 대상 날짜 별도 표시 |
| 모달 | frontend/src/components/Modal.tsx | dialog, focus trap, Escape, 포커스 복원 |
| 피드백 | 페이지 내 role=status/alert | 중요한 정보는 토스트로만 전달하지 않음 |
| 스크롤 | frontend/src/styles/base.css | 문서 스크롤, 안정된 gutter, 전역 thumb/track |
| 승인 | ApprovalPanel | 실제로 확인한 result_token, 사유·확인, 서버 성공 후 표시 |

접수 응답 전에는 전송 중이다. 실패/응답 유실은 상태 확인 불가이며 동일 ID로 조회한다. 상태 읽기 실패, 만료, 역순 응답은 조치 가능으로 간주하지 않는다. API 키/담당자 토큰은 메모리만 사용한다. localStorage에는 비밀 값을 저장하지 않는다. 미완료 요청 ID와 비민감 분석 조건만 sessionStorage에 저장한다. 탭 복귀 시 재확인하며 확인 전 승인 불가.

분석 갱신은 한 번에 한 요청만 진행하고 직전 요청이 끝난 뒤 다음 조회를 예약한다. 계산 중에는 1초 간격, 검토 결과는 5초 간격으로 확인한다. 실패 시 자동 성공을 추정하지 않는다. 문서가 숨겨지면 폴링을 중단하고 상태를 미확인으로 취급한다.

메뉴를 바꿔도 선택한 분석을 보존한다. 이전 결과를 새 요청의 결과처럼 보여주지 않는다. 위험 차트는 텍스트 표로도 읽을 수 있다. 모의 승인 버튼은 실제 조치로 오인하지 않도록 시연 검토라고 명시한다.
