import type { AnalysisRequest } from "./types";
import { Button } from "../../components/Button";
import { Play, CalendarDays } from "lucide-react";

export const regions = {
  jeju: "제주 전체",
  hallim: "한림",
  jocheon: "조천",
  haengwon: "행원",
};
export function AnalysisForm({
  value,
  onChange,
  onSubmit,
  disabled,
}: {
  value: AnalysisRequest;
  onChange: (value: AnalysisRequest) => void;
  onSubmit: () => void;
  disabled: boolean;
}) {
  return (
    <form
      className="analysis-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="field">
        <label htmlFor="date">
          <CalendarDays size={14} />
          예측 대상일
        </label>
        <input
          id="date"
          type="date"
          required
          value={value.date}
          onChange={(e) => onChange({ ...value, date: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor="region">분석 지역</label>
        <select
          id="region"
          value={value.region}
          onChange={(e) =>
            onChange({
              ...value,
              region: e.target.value as AnalysisRequest["region"],
            })
          }
        >
          {Object.entries(regions).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="mode">데이터 모드</label>
        <select
          id="mode"
          value={value.mode}
          onChange={(e) =>
            onChange({
              ...value,
              mode: e.target.value as AnalysisRequest["mode"],
            })
          }
        >
          <option value="demo">시연 데이터</option>
          <option value="live">외부 데이터 · 검증 전</option>
        </select>
      </div>
      {value.mode === "demo" && (
        <div className="field">
          <label htmlFor="scenario">시연 조건</label>
          <select
            id="scenario"
            value={value.scenario}
            onChange={(e) =>
              onChange({
                ...value,
                scenario: e.target.value as AnalysisRequest["scenario"],
              })
            }
          >
            <option value="critical">위험일</option>
            <option value="normal">정상일</option>
            <option value="boundary">경계 재조회</option>
            <option value="boundary_stable">경계 유지</option>
          </select>
        </div>
      )}
      <Button type="submit" disabled={disabled || !value.date}>
        <Play size={15} />
        분석 요청
      </Button>
    </form>
  );
}
