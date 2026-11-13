---
version: alpha
colors:
  background: "#F3F6F8"
  surface: "#FFFFFF"
  text: "#20313F"
  muted: "#586B78"
  primary: "#067477"
  warning: "#8F5B0D"
  danger: "#B23846"
typography:
  sans:
    fontFamily: "Pretendard Variable, system-ui, sans-serif"
rounded:
  panel: "12px"
  control: "8px"
spacing:
  page: "32px"
  gap: "24px"
components:
  Button:
    minHeight: "44px"
---

## Overview
지자체 담당자의 다음날 발전량 검토 도구. 차분한 밝은 수급 분석표와 24시간 위험 띠가 특징이다. 업무 상태의 진실성이 시각 효과보다 우선한다. 현재 시연 상태를 지속적으로 표시한다.

## Colors
위 frontmatter의 값은 frontend/src/styles/tokens.css의 동명 CSS 변수로 연결한다. 청록은 기본 행동, 황갈색은 경계, 적색은 위험/실패이며 텍스트와 함께 사용한다.

## Typography
Pretendard Variable을 로컬 패키지에서 제공한다. 본문 14~16px, 제목 26px, 수치는 tabular-nums. 작은 글씨는 보조 출처에만 사용한다.

## Layout
데스크톱 220px 사이드바, 본문 32px 여백. 넓은 발전량 차트와 검토 요약. 900px 아래 한 열, 640px 아래 수평 내비게이션. 문서 스크롤을 사용하고 중첩 스크롤을 최소화한다.

## Elevation & Depth
패널은 얇은 테두리, 모달에만 그림자를 강조한다. 배경 blur와 지속적인 움직임은 없다.

## Shapes
패널 12px, 입력과 버튼 8px. 버튼 높이 최소 44px. 비활성화 상태에서도 설명을 읽을 수 있다.

## Components
공통 Button, StatusBadge, Modal, EmptyState, 오류 안내를 재사용한다. 색상 피드백 80ms, 메뉴 전환 즉시, 보조 패널 최대 120ms. reduced-motion은 애니메이션을 제거한다. 서버 완료를 추정하는 카운트업이나 가짜 진행률은 없다.

## Do's and Don'ts
차트 빈 상태에 가짜 수치를 넣지 않는다. 예측과 시연, 승인과 발송, 발송과 설비 동작을 구분한다. 불확실한 상태에서 승인 버튼을 활성화하지 않는다.
