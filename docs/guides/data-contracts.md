# 데이터 연동 계약

## 공통

KST(Asia/Seoul)의 날짜와 hour 0~23으로 24개 구간을 나타낸다. hour=12는 12:00 이상 13:00 미만이다. 전력 MW와 에너지 MWh를 구별한다. 평균 출력 MW × 1h = 해당 구간 에너지 MWh이다. 누락/중복/NaN/음수/다른 날짜를 거부한다. 지역별 기상 거점 선택과 제주 전체 수요를 함께 사용하는 단순 추정 모델이며 지역별 계통 조류 모델은 아니다.

## 기상청

`KMA_API_KEY`는 디코딩된 서비스키를 넣는다. 어댑터가 requests 파라미터 인코딩을 수행한다. HTTPS 단기예보 `getVilageFcst`의 WSD/TMP/SKY를 사용한다. 발표 시각은 02/05/08/11/14/17/20/23시이며 10분 게시 지연을 둔다. 제공 범위 밖 날짜 또는 24시간 미충족은 오류/명시적 폴백이다. SKY와 시간으로 일사량을 추정하므로 실측 일사량이 아니다.

## KPX

기획서에 실제 API URL과 스키마가 없으므로 아래 **정규화 어댑터 계약**을 사용한다. KPX 공개 API를 직접 연결했다고 주장하지 않는다. 사용자가 관리하는 HTTPS 중계에 `GET ?date=YYYY-MM-DD&region=jeju`를 호출한다. 추가 인증이 필요한 원천 API는 중계에서 처리한다.

```json
{"hours": [
  {"date": "2026-11-14", "hour": 0, "mwh": 500},
  {"date": "2026-11-14", "hour": 1, "mwh": 490}
]}
```

위 JSON은 형식 예시다. 실제로는 hour=0~23의 24개 행이 필요하다. 원천이 MW이면 1시간 평균인지 확인하고 에너지로 정규화해야 한다.

## 발전소 및 수동 보정

`PLANTS_PATH`와 `CORRECTIONS_PATH`는 동일 스키마의 JSON 배열이다.

```json
[{"id":"verified-plant-id","kind":"wind","capacity_mw":10,"source":"공식 원문 URL 또는 조사 기록"}]
```

kind는 wind/solar이며, 보정 배열에서 동일 ID는 용량을 **대체**한다. 신규 ID만 추가된다. 파일 내부 중복 ID는 오류다. 한림해상풍력 등 실측 용량은 첨부자료에 확정값이 없으므로 빈 보정 파일로 제공한다. 기본 900MW/600MW 레지스트리는 가상 시연 설정이다. source를 바꿨다는 사실만으로 실측 검증이 완료되지 않는다.

## 학습 CSV

필수 열: `timestamp,wind_ms,temperature_c,irradiance_wm2,wind_capacity_mw,solar_capacity_mw,generation_mwh`.
timestamp 예: `2026-11-14T12:00:00+09:00`. 시간대 포함, 정시, 중복 금지, 최소 48행. 풍속 m/s, 기온 ℃, 일사량 W/m², 설비 MW, 해당 1시간 발전량 MWh. 실제 사용에는 계절과 기상 변화를 포함하는 충분한 실측 학습 기간이 필요하다.

```bash
python -m pip install -e '.[ml]'
python -m scripts.train_model measured.csv models/generation.json
```

시간순 앞 80% 학습/뒤 20% 평가로 MAE와 기간을 `.metrics.json`에 저장한다. `MODEL_PATH` 설정 후 live 요청에서 사용한다. 시연 시나리오는 고정 fixture를 사용하므로 모델 정확도를 검증하지 않는다. 모델 미지정 시 물리식 추정이 동작한다. XGBoost는 CPU로 학습하므로 GPU가 필요 없다.

## 승인과 알림

현재 자원 가용량은 추정치이며 실 알림 발송 대상이 아니다. `mock_sent`는 로컬 발송 시뮬레이션 기록이다. webhook 어댑터는 개발 연결 지점으로 제공하며, 추정 가용량/미검증 모델/시연 출처 중 하나라도 있으면 `blocked`로 끝난다. 실제 운용을 위해서는 검증된 SOC 공급자와 모델 검증 정책을 추가해야 한다.

향후 발송은 HTTPS POST이며 `Idempotency-Key: <analysis_id>`, `Authorization: Bearer <NOTIFICATION_TOKEN>`과 승인된 초안·계산 결과를 전달한다. 수신 서버도 동일 키의 중복 처리를 막아야 한다. 응답 유실/전송 중 종료는 delivery_unknown이며 자동 재발송하지 않는다. 수신처 확인 후 운영자가 별도 정합성을 맞춰야 한다. 현재 자동 재전송/상태 초기화 API는 제공하지 않는다. 알림은 운영 권고문이며 설비 제어 신호가 아니다.

## 확장 범위

실제 제주데이터허브 다운로드/수집 스케줄러, 실시간 ESS SOC, 지역 계통 모델, 검증된 ML 아티팩트, LLM 제공자, SMS 벤더 계정, 사용자별 권한 관리 및 실전송 운용은 추가 데이터·연동 명세가 필요하다. 현 백엔드는 3개 시연과 안전한 승인 흐름을 실행하는 개발 기준선이다.
