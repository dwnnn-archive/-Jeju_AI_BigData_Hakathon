# 예보 저장 장치

서비스가 받은 **예보 원본**과 **판정 기록**을 쌓아 두는 장치다. 나중에 예보 오차를 재고, 임계값을 예보 기준으로 다시 맞추고, ML 모델을 개선하는 데 쓰려고 만들었다.

## 왜 필요한가

- 기상청은 **최근 3일 치 발표분만** 다시 준다(`최근 3일 간의 자료만 제공합니다`). 저장하지 않으면 3일이 지난 예보는 영영 구할 수 없다.
- 지금까지의 모든 검증은 **실측 기상**으로 했다. 서비스는 예보를 쓰므로 실제 성능은 더 낮고(예보 오차를 가정하면 위험 판정 정밀도 77% → 49~63%), 실제 예보 오차는 아직 모른다.
- 당일 점검(초단기예보)의 이득(포착 81~83% → 약 93%)도 오차를 **가정한** 시뮬레이션이다. 실제 예보를 쌓아야 확인된다.

## 무엇을 저장하나

저장 파일은 `FORECAST_ARCHIVE_PATH`(기본: DB 파일 옆 `runtime/forecasts.sqlite`, Git에 올라가지 않는다). `FORECAST_ARCHIVE_ENABLED=false`로 끌 수 있다.

| 테이블 | 내용 |
|---|---|
| `forecast_issues` | 발표 한 건: 출처(`short` 단기예보, `ultra_fcst` 초단기예보, `ultra_ncst` 초단기실황), 격자(nx, ny), 발표 일시, 받은 시각. 같은 발표는 한 번만 저장한다 |
| `forecast_values` | 발표별 **받은 모든 항목**의 원본: 유효 일시, 항목, 숫자값, 원문. 단기예보는 풍속·기온·하늘상태 외에 강수확률·습도·풍향·파고 등 14개, 초단기예보 11개, 실황 8개. 범주 문자열(`강수없음`)은 원문으로만 남는다 |
| `evaluations` | 분석 실행마다 판정 결과(등급, 최대 비율, 피크 잉여, 시간별 발전량·수요·비율), 사용한 입력(당일 점검은 이어 붙인 날씨와 시간별 출처, 하루 전 발표분), 모델 정보(학습 기간) |

받은 항목 전부를 저장하는 이유는 지금 모델이 안 쓰는 항목(강수확률, 습도, 풍향 등)도 나중에 입력 후보가 될 수 있기 때문이다.

## 어떻게 쌓이나

1. **자동**: 분석(하루 전·당일 점검)이 예보를 받을 때마다 원본을 저장하고 판정을 기록한다. 저장 실패는 분석을 막지 않는다(경고만 남긴다).
2. **정기 수집**: 분석 요청이 없는 날에도 이력이 쌓이도록 스케줄러가 호출하는 명령이 있다. 같은 발표는 중복 저장되지 않아 스케줄러가 겹쳐 돌아도 안전하다.

```bash
cd backend   # backend/.env 에 KMA_API_KEY 필요
python -m scripts.forecast_archive collect                          # 현재 예보를 받아 저장(두 격자 x 3출처)
python -m scripts.collect_asos 2026-11 2026-11 runtime/asos_recent  # ASOS 실측(어제까지). 학습용 runtime/asos 와 폴더를 분리한다(병합 파일을 덮어쓰므로)
python -m scripts.forecast_archive export runtime/asos_recent runtime/forecast_dataset.csv   # 실측과 맞춘 학습용 표
python -m scripts.forecast_archive report runtime/asos_recent       # 예보가 실제로 얼마나 틀렸는지
```

### Windows 작업 스케줄러로 자동 수집

```powershell
powershell -ExecutionPolicy Bypass -File backend\scripts\register_collect_task.ps1          # 등록(다시 실행하면 덮어쓴다)
powershell -ExecutionPolicy Bypass -File backend\scripts\register_collect_task.ps1 -Remove  # 해제
Start-ScheduledTask -TaskName JejuForecastArchive-Collect                                   # 지금 한 번 실행
```

- 작업 이름 `JejuForecastArchive-Collect`. 매일 02:15부터 **3시간마다**(02:15, 05:15, …, 23:15 = 단기예보 발표 15분 뒤) `scripts\collect_forecasts.cmd`를 실행한다. 로그는 `backend\runtime\collect.log`.
- 로그인한 사용자 권한으로만 돈다(비밀번호를 저장하지 않는다). **PC가 켜져 있고 로그인돼 있어야 한다.** 배터리여도 실행하고, 이전 실행이 끝나지 않았으면 겹쳐 돌지 않으며, 20분을 넘기면 중단한다.
- **놓친 발표 따라잡기**: PC가 꺼져 있었으면 다음 실행에서 최근 약 70시간 안의 발표 중 저장 안 된 것만 다시 받는다(기상청은 단기·초단기예보를 약 72시간만 다시 준다). 실패한 건은 한 번 재시도하고, 그래도 실패하면 다음 실행에서 다시 채운다. 이미 저장한 발표는 호출하지 않는다.
- **초단기실황은 따라잡을 수 없다.** 기상청이 최근 1일만 주고, 실행 때마다 최신 한 건만 받는다. 3시간 간격이라 실황은 3시간에 한 건씩만 쌓인다(실측 비교는 ASOS로 한다).
- 72시간 넘게 PC가 꺼져 있으면 그 사이 발표는 복구할 수 없다.
- 서버 PC가 아닌 개발 PC에 걸어 둔 것이다. 장기 운영은 항상 켜진 서버로 옮기는 것이 안전하다.

### ASOS 실측도 자동 수집 (하루 한 번)

예보 오차를 재려면 같은 시각의 실측이 있어야 한다. 실측(ASOS)은 **전일 자료까지만** 받을 수 있어서 하루 한 번이면 충분하다.

```powershell
powershell -ExecutionPolicy Bypass -File backend\scripts\register_asos_task.ps1          # 등록
powershell -ExecutionPolicy Bypass -File backend\scripts\register_asos_task.ps1 -Remove  # 해제
python -m scripts.collect_asos recent runtime/asos_recent                                  # 손으로 한 번 실행
```

- 작업 이름 `JejuForecastArchive-ASOS`, 매일 03:30. 같은 로그 `backend\runtime\collect.log` 에 `asos start/end exit=` 로 남는다.
- **어제가 속한 달과 그 전 달**을 `runtime/asos_recent` 에 받는다. 끝나지 않은 달은 어제까지만 받고 매번 다시 받는다. 월말에 받은 파일이 끝부분이 비어 있으면(마지막 날까지 안 담김) 다음 실행에서 다시 받는다.
- 학습용 폴더 `runtime/asos` 는 건드리지 않는다. (병합 파일을 덮어쓰기 때문에 폴더를 분리했다.)
- PC가 꺼져 있었으면 켜졌을 때 따라잡아 실행한다. 월 단위로 다시 받으므로 며칠 비어도 채워진다.
- 하루 호출 수는 4개 지점 x 2개 달 = 8번이다.

### 하루 전 분석을 매일 자동으로 (판정 기록 쌓기)

`evaluations`(판정 기록)는 분석을 돌릴 때만 쌓인다. 매일 17:30에 내일 대상 하루 전 분석을 한 번 돌린다.

```powershell
powershell -ExecutionPolicy Bypass -File backend\scripts\register_day_ahead_task.ps1          # 등록
powershell -ExecutionPolicy Bypass -File backend\scripts\register_day_ahead_task.ps1 -Remove  # 해제
python -m scripts.run_day_ahead                                                    # 손으로 한 번 실행
```

- 작업 이름 `JejuDayAhead-Analysis`. 서버를 따로 켜지 않는다(앱을 프로세스 안에서 띄워 1건 돌리고 끝난다). 로그는 `backend\runtime\collect.log` 의 `day-ahead start/end exit=`.
- 17:30은 17시 발표 단기예보가 들어온 직후라서 정했다. KPX 전망의 게시 시각은 확인하지 못해 이 시각을 그것과 맞춘 것이라고 말하지 않는다.
- 대상은 실행 시점의 **내일**이다(오늘 날짜는 지난 시간대 예보가 없어 돌릴 수 없다). **17:15~23:50 밖이면 건너뛴다.** PC가 꺼져 있다 늦게 켜져 따라잡기로 실행되면 "내일"이 엉뚱한 날이 되기 때문이다. 건너뛴 날의 판정 기록은 복구되지 않는다.
- 같은 날짜는 같은 멱등 키를 써서 두 번 호출해도 기록이 한 건이다. 앞선 시도가 실패로 끝났으면 키를 바꿔 한 번 다시 시도한다.
- 모델 경로 설정이 없으면 `runtime/models/jeju`, `runtime/models/demand` 를 쓴다(있을 때만). 이 경로가 없으면 live 분석이 실패한다.
- live 모드에서 위험이면 **승인 대기 건이 매일 남는다.** 이 스크립트는 승인하지 않고, live 에서는 승인과 발송이 막혀 있다.
- 통보문 초안을 위해 ANTHROPIC_API_KEY 가 있으면 판정 결과가 LLM 으로 전송된다.
- 이 기록의 정답(KPX 실적)은 분기마다 공개되므로 맞았는지는 바로 평가할 수 없다. KPX가 공개하는 전망이 있다면 비교 기준선이 될 수 있다(공개 시각·형식은 확인하지 못했다).

## ML 개선에 쓰는 방법

`export`가 만드는 표(`runtime/forecast_dataset.csv`)의 열: `source, nx, ny, base_date, base_time, valid_date, valid_hour, lead_hours, category, forecast, raw, observed_wind_ms, observed_temperature_c, observed_sky`.

| 용도 | 방법 |
|---|---|
| 예보 오차 측정 | 출처·항목·선행 시간대별 MAE와 편향(`report`). 하루 전 예보와 초단기예보가 각각 얼마나 틀리는지 처음으로 알 수 있다 |
| 예보 보정 | 풍속 예보가 평균적으로 얼마나 높거나 낮은지(편향), 선행 시간별 오차를 학습해서 예보 풍속을 보정하는 모델 |
| 임계값 재보정 | 예보 입력으로 판정을 다시 돌려 위험 비율 임계값(0.40 / 0.45)을 예보 기준으로 맞춘다. 정밀도 하락(77% → 49~63%)을 되찾는 방법 |
| 학습 입력 교체 | 지금 모델은 ASOS 실측으로 학습한다. 저장된 예보로 학습하면 학습과 서비스의 입력이 같아진다 |
| 당일 점검 효과 검증 | 저장된 초단기예보와 하루 전 예보를 같은 날 실제 출력제한과 비교해 시뮬레이션의 93%를 확인한다 |
| 추가 입력 후보 | 강수확률·습도·풍향 등 지금 안 쓰는 항목이 발전·수요 예측을 개선하는지 시험 |

판정 기록(`evaluations`)에는 그날 모델이 낸 시간별 예측이 있어서, 나중에 KPX 실제 발전량·수요·출력제어 이력과 맞추면 **서비스가 실제로 낸 판정의 성적**을 낼 수 있다(KPX 자료는 분기마다 공개된다).

## 한계

- 아직 데이터가 쌓이기 시작한 단계다. 의미 있는 평가에는 몇 주~몇 달의 이력이 필요하다(출력제한은 봄과 10월에 몰려 있다).
- 실측(ASOS)은 전일(D-1) 자료만 제공되고 같은 날 지난 시간의 실측은 구할 수 없다. 평가는 하루 이상 지난 예보부터 가능하다.
- 용량: 하루 약 2만 행(발표 8회 x 2격자 x 약 1,000행 + 초단기 매시)으로 **추정**한다(연 수백만 행, 수백 MB 안팎). 실제 증가를 보며 필요하면 수집 주기를 줄이거나 항목을 제한한다.
- 두 격자만 저장한다(고산 46,35, 제주시 53,38). 고산 격자 = ASOS 고산(185), 제주시 격자 = ASOS 제주(184).
