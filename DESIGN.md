---
version: beta
source: "Figma PC_스타일가이드 (2026_업데이트.v02)"
colors:
  brandMain: "#00C853"
  brandSub1: "#6200EA"
  brandSub2: "#00C853"
  background: "#F7F7FB"
  surface: "#FFFFFF"
  text: "#111111"
  textSub: "#505050"
  muted: "#6B6B6B"
  disabled: "#999999"
  line: "#E5E5EC"
  lineLight: "#F1F1F5"
  primary: "#00C853"
  onPrimary: "#111111"
  primaryInk: "#007A35"
  danger: "#C62828"
  warningFill: "#FBC02D"
  warningText: "#8F5B0D"
  successFill: "#00C853"
  successText: "#1B7A3E"
  dim: "#111111 / 60%"
typography:
  sans:
    fontFamily: "Pretendard Variable, system-ui, sans-serif"
    weights: [600, 500, 400]
    tracking: "-2.5%"
  scale: { headline3: 32, headline4: 28, headline5: 24, headline6: 20, title: 18, body1: 16, body2: 15, body3: 14, body4: 13, caption1: 12, caption2: 11 }
rounded:
  panel: "16px"
  control: "4px"
spacing: [2, 4, 8, 12, 16, 20, 24, 28, 32, 40, 48]
components:
  Button:
    large: "48px (primary actions)"
    medium: "42px (secondary)"
    small: "36px (desktop only; 44px on mobile)"
    gap: "8px"
---

## Overview
지자체 담당자의 다음날 발전량 검토 도구. 차분한 밝은 수급 분석표와 24시간 위험 띠가 특징이다. 업무 상태의 진실성이 시각 효과보다 우선한다. 현재 시연 상태를 지속적으로 표시한다.

## Colors
Figma 06. Color Guide를 따르며 값은 frontend/src/styles/tokens.css의 CSS 변수로 연결한다. 브랜드 초록(#00C853)은 기본 행동의 면 색이며, 그 위 글자는 #111111(8.4:1)을 쓴다. 흰 배경 위 초록 글자·링크는 #007A35(5.5:1)를 쓴다(흰 글자 on #00C853은 2.24:1로 금지), 노랑은 경계, 적색은 위험/실패이며 항상 텍스트와 함께 사용한다. 노랑(#FBC02D)·초록(#00C853)은 흰 배경 위 글자 대비가 부족하므로 배경·점·막대에만 쓰고 글자는 --warning-text·--success-text를 쓴다. 글자색은 #111111/#505050/#6B6B6B(회색 배경 위에서도 4.5:1 유지), #999999는 비활성에만 쓴다. 버튼·입력칸 선은 #E5E5EC, 팝업 딤은 #111111 60%.

## Typography
Pretendard Variable을 로컬 패키지에서 제공한다. Figma 05. Typography Guide에 따라 Semibold(600)·Medium(500)·Regular(400)만 쓰고 자간은 -2.5%. 본문 13~16px(Body 1~4), 페이지 제목 28px(Headline 4), 섹션 제목 18px(Title). 수치는 tabular-nums. 11~12px(Caption)은 보조 출처에만 사용한다.

## Layout
데스크톱 220px 사이드바, 본문 32px 여백. 넓은 발전량 차트와 검토 요약. 900px 아래 한 열, 640px 아래 수평 내비게이션. 세로 간격은 Figma 01. Spacing의 짝수 단계(2·4·8·12·16·20·24·28·32·40·48)만 쓴다. 문서 스크롤을 사용하고 중첩 스크롤을 최소화한다.

## Elevation & Depth
패널은 얇은 #E5E5EC 테두리, 모달에만 그림자를 강조하고 모달 뒤는 #111111 60% 딤을 깐다. 배경 blur와 지속적인 움직임은 없다.

## Shapes
패널 16px, 입력과 버튼 4px(Figma 버튼 가이드 기준, 스크린샷으로 추정). 버튼은 Figma 07. Button Guide의 Large 48px(주요 행동), Medium 42px(보조), Small 36px(데스크톱 전용)을 쓰고, 640px 이하에서는 터치 대상 44px 이상을 유지한다. 버튼 간격 8px. 버튼 종류는 BG 강조(primary), Line 비강조(secondary), BG 비강조(ghost). 비활성화 상태에서도 설명을 읽을 수 있다.

## Components
공통 Button, StatusBadge, Modal, EmptyState, 오류 안내를 재사용한다. 색상 피드백 80ms, 메뉴 전환 즉시, 보조 패널 최대 120ms. reduced-motion은 애니메이션을 제거한다. 서버 완료를 추정하는 카운트업이나 가짜 진행률은 없다.

## Do's and Don'ts
차트 빈 상태에 가짜 수치를 넣지 않는다. 예측과 시연, 승인과 발송, 발송과 설비 동작을 구분한다. 불확실한 상태에서 승인 버튼을 활성화하지 않는다.
