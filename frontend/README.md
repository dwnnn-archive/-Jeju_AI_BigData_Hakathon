# 프론트엔드 읽기 안내

React 19 + TypeScript + Vite를 사용합니다. 개발 화면은 `npm ci` 후 `npm run dev`로 실행합니다. 백엔드는 8000번 포트에서 실행하고 Vite가 `/api` 요청을 전달합니다.

## 파일을 찾는 기준

| 찾는 내용 | 위치 |
|---|---|
| 메뉴, 전체 화면 조합 | `src/app/App.tsx` |
| HTTP, 인증, 응답 검증 | `src/api/client.ts` |
| 서버 상태와 브라우저 전송 상태 | `src/features/analysis/useAnalysis.ts` |
| 상태 문구·승인 표시 조건 | `src/features/analysis/state.ts` |
| 응답 데이터 형식 | `src/features/analysis/types.ts` |
| 분석 입력·24시간 차트 | `src/features/analysis/` |
| 배분안·승인·이력 | 각각 `features/allocation`, `approval`, `history` |
| 공통 버튼·모달·빈 화면 | `src/components/` |
| 화면 배치 | `src/pages/` |
| 색상·간격·반응형 | `styles/tokens.css`, `layout.css`, `components.css`, `responsive.css` 및 각 기능의 CSS |

작은 기능 테스트는 대상 파일 옆에 둡니다. 실제 API와 연결하는 Playwright 테스트는 `tests/`에 둡니다. 공통 테스트 데이터는 `src/test/`에만 둡니다. 실제 화면의 빈 상태에는 테스트 수치를 넣지 않습니다.

## 중요한 흐름

`AnalysisForm` → `useAnalysis.submit` → `api.submit` → 서버 접수 → `api.get` 반복 조회 → 응답 검증 → `StatusBadge/ForecastPage`에 표시합니다.

`transport`는 브라우저가 알고 있는 통신 상태이고 `run.status`는 서버에 저장된 업무 상태입니다. 전송을 시작했다고 `run.status=running`으로 바꾸지 않습니다. 새로고침 후에는 저장해둔 분석 ID로 서버를 다시 조회합니다.

화면 이동은 서버 응답을 기다리지 않습니다. 반면 승인은 결과 ID·토큰·대상 조건이 맞고 최신 상태를 확인했을 때만 허용합니다. 승인 창은 처음 검토한 결과에 고정되며 다른 결과로 바뀌면 확인 버튼을 잠급니다.

계산 중에는 1초, 완료 후에는 5초 간격으로 **직전 조회가 끝난 뒤** 다음 조회를 예약합니다. 탭이 숨겨지면 조회를 중지하고, 복귀하면 확인 전 승인을 막습니다. 숨기기 이전 요청의 늦은 응답은 버립니다. 7초 이내에 새 확인을 얻지 못하거나 작업자 생존 신호가 만료되면 미확인 상태가 됩니다. 검토 유효시간 만료는 별도로 관리해 승인을 잠그고, 확인된 만료 결과에서는 새 분석을 시작할 수 있습니다.

승인 인증 값은 메모리에만 유지합니다. `sessionStorage`에는 비밀이 아닌 분석 ID와 입력 조건만 저장합니다. `VITE_` 환경변수는 번들에 공개되므로 비밀 키를 넣으면 안 됩니다.

## 화면과 검증

로컬 Pretendard 글꼴, 청록색 행동 버튼, 밝은 배경, 얇은 경계로 구성했습니다. 메뉴 전환 지연은 없고 색상 전환만 80ms입니다. 차트는 결과가 생긴 후 별도 코드로 불러오며 수치를 애니메이션으로 변화시키지 않습니다. 차트 데이터는 표로도 읽을 수 있습니다. 모달은 브라우저 dialog의 포커스 관리와 Escape를 사용합니다.

`npm test`는 상태/응답 순서/승인 대상 검증, `npm run test:e2e`는 실제 분석·모의 승인·장애·모바일·키보드·axe 접근성 검사를 수행합니다. 빌드는 `npm run build`, 형식 검사는 `npm run format:check`입니다.

[전체 변경과 공부 순서](../docs/guides/learning-guide.md)를 함께 읽으세요.
