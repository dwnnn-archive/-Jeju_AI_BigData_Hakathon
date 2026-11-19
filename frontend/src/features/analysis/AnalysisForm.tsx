import { useId } from "react";
import type { AnalysisRequest } from "./types";
import { Button } from "../../components/Button";
import { DateField } from "../../components/DateField";
import { todayKst } from "./state";
import { Play, CalendarDays } from "lucide-react";

export const regions = {
  jeju: "제주 전체",
  hallim: "한림",
  jocheon: "조천",
  haengwon: "행원",
};
export const modes = {
  demo: "시연 데이터",
  live: "외부 데이터 · 운영 검증 전",
};
export const scenarios = {
  critical: "위험일",
  normal: "정상일",
  boundary: "경계 재조회",
  boundary_stable: "경계 유지",
  intraday_escalation: "당일 위험 전환",
};

/** Single-choice segmented control built on native radio buttons. */
function Segmented<K extends string>({
  legend,
  name,
  area,
  options,
  value,
  onChange,
}: {
  legend: string;
  name: string;
  area: string;
  options: Record<K, string>;
  value: K;
  onChange: (value: K) => void;
}) {
  return (
    <fieldset className={`seg-field cond-${area}`}>
      <legend>{legend}</legend>
      <div className="seg">
        {(Object.entries(options) as [K, string][]).map(([key, label]) => (
          <label key={key} className="seg-option">
            <input
              type="radio"
              name={name}
              value={key}
              checked={value === key}
              onChange={() => onChange(key)}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

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
  const id = useId();
  return (
    <form
      className="analysis-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="field cond-date">
        <label htmlFor="date">
          <CalendarDays size={14} />
          예측 대상일
        </label>
        <DateField
          id="date"
          value={value.date}
          onChange={(date) => onChange({ ...value, date })}
        />
      </div>
      <Segmented
        legend="분석 지역"
        area="region"
        name={`${id}-region`}
        options={regions}
        value={value.region}
        onChange={(region) => onChange({ ...value, region })}
      />
      <Segmented
        legend="데이터 모드"
        area="mode"
        name={`${id}-mode`}
        options={modes}
        value={value.mode}
        onChange={(mode) => onChange({ ...value, mode })}
      />
      {value.mode === "demo" && (
        <Segmented
          legend="시연 조건"
          area="scenario"
          name={`${id}-scenario`}
          options={scenarios}
          value={value.scenario}
          onChange={(scenario) =>
            onChange({
              ...value,
              scenario,
              ...(scenario === "intraday_escalation"
                ? { date: todayKst() }
                : {}),
            })
          }
        />
      )}
      <Button
        type="submit"
        className="cond-submit"
        disabled={disabled || !value.date}
      >
        <Play size={15} />
        분석 요청
      </Button>
    </form>
  );
}
