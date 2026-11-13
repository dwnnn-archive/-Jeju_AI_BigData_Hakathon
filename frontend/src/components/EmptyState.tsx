import { ChartNoAxesCombined } from "lucide-react";
export function EmptyState({
  title = "다음날의 에너지 흐름을 확인하세요",
  description = "날짜와 지역을 선택해 분석을 요청하면, 서버가 확인한 결과를 이곳에 표시합니다.",
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <ChartNoAxesCombined size={32} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}
