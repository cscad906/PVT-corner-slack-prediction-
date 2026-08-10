# HOLDOUT — 어떤 코너를 숨길지 (온도마다 따로)

**숨긴다 = "이 코너는 안 잰 셈 치고, 모델이 맞히는지 본다".**
숨긴 코너의 정답은 학습에 **일절 들어가지 않는다** (실험으로 검증됨 — 숨긴 코너
라벨을 난수로 바꿔도 학습된 가중치가 비트 단위로 동일).

---

## 1. 왜 온도마다 따로 적어야 하나

이번 데이터는 온도마다 BEOL 레벨이 다르다:

```
125C :  4 전압 x {rcmax, cmax}          =  8 코너
m25C :  4 전압 x {rcmax, cmax, rcmin}    = 12 코너
```

`rcmin` 은 m25C 에만 있다. 그래서 "`[0.54, rcmin]` 을 숨겨라" 를 **전역에 한 번**
적으면 125C 에서는 존재하지도 않는 코너를 가리키게 된다. 홀드아웃은 `temps[]`
안에 온도별로 적는다:

```yaml
temps:
  - tag: "125"
    token: 125
    levels: [rcmax, cmax]
    hidden_corners: [[0.5, rcmax], [0.6, cmax]]        # 125C 만의 홀드아웃
  - tag: m25
    token: m25
    levels: [rcmax, cmax, rcmin]
    hidden_corners: [[0.54, rcmin], [0.685, rcmax]]     # m25C 만의 홀드아웃
```

`corners:` 아래에 적으면 **모든 온도 공통**, `temps[]` 안에 적으면 **그 온도만**
(키 단위로 덮어쓴다 — 한 온도가 `hidden_corners` 만 바꾸고 `query_corners` 는
전역 값을 그대로 물려받을 수 있다).

없는 레벨을 적으면 조용히 무시하지 않고 에러난다:

```
temp 125: hidden_corners 의 레벨 'rcmin' 이 이 온도의 levels ['rcmax','cmax'] 에 없다
  -- 온도마다 레벨이 다르므로 holdout 도 temps[] 안에서 따로 적어야 한다
```

---

## 2. 숨기는 방법 5가지

| 키 | 무엇을 숨기나 | 코너가 적을 때 |
|---|---|---|
| `hidden_corners` | **콕 집어 한 칸씩** `[[0.6, rcmax], ...]` | ★ **권장** |
| `hidden_per_voltage` | **모든 전압에서 N칸씩** 자동 선택 | 상황에 따라 |
| `hidden_voltages` | 그 전압의 **모든 레벨** (행 통째) | 비권장 |
| `seen_voltages` | 반대: 이것만 seen, 나머지 전압 전부 hidden | 비권장 |
| `hidden_levels` | 그 레벨의 **모든 전압** (열 통째) | 비권장 |

전부 섞어 쓸 수 있고 결과는 합집합이다. `query_corners`(측정 자체가 없는 코너)는
별개이며 항상 hidden 이고 지표에서 빠진다.

### 왜 행/열 통째로는 비권장인가

행을 통째로 빼면 **그 전압의 앵커가 전부 사라진다.** 8코너짜리 그리드에서 한 행
(2칸)을 빼면 그 전압에 대해 아무 관측도 없이 외삽해야 한다. 반면 칸을 흩어서 빼면
전압마다 최소 하나는 남아 그 전압이 계속 고정된다.

레퍼런스 14nm 는 51코너라 행을 빼도 됐지만, 이번 건 8/12 코너다.

### `hidden_per_voltage` — "모든 전압에서 하나씩"

```yaml
corners:
  hidden_per_voltage: 1        # 전압마다 1칸씩, 레벨을 돌아가며 자동 선택
```

레벨을 전압 순서에 따라 회전시켜 **대각선으로 흩어지게** 고른다(한 레벨에 몰리지
않게). 앵커 코너는 절대 고르지 않는다. 그 온도의 레벨 수보다 크면 에러난다
(그 전압의 모든 레벨을 숨기면 앵커가 안 남으므로).

---

## 3. 몇 칸까지 숨겨도 되나 — 산수

숨길수록 seen 이 줄고, seen 이 다항식 파라미터 수 이하가 되면 **자유도 0** 이라
피팅이 모든 점을 그대로 통과해 LOO 검증이 무의미해진다.

`bash scripts/run.sh list` 가 이 산수를 대신 해준다:

```
  ── boomcore/125
     hidden  : 2개 SSPG_0p5V_rcmax, SSPG_0p6V_cmax
     corners : 전체 8 = seen 6 + hidden 2   (min_seen 가드 6)
     basis   : v^2 x level^1 -> 5 파라미터 ['drc','dv','dvdrc','dv2']
```

seen 6 > 파라미터 5 → OK. 파라미터가 seen 이상이면 **⚠ 경고**가 붙는다.

이번 그리드의 실제 결과:

| 홀드아웃 | 125C (8코너) | m25C (12코너) |
|---|---|---|
| **온도별 2칸씩** | seen 6, 파라미터 5 (`v^2`) ✓ | seen 10, 파라미터 7 (`v^3`) ✓ |
| `hidden_per_voltage: 1` (4칸) | seen 4, 파라미터 4 ⚠ **무리** | seen 8, 파라미터 7 ✓ |

**125C 는 8코너뿐이라 4칸(전압마다 하나)은 무리다.** 2칸이 상한에 가깝다.
m25C 는 12코너라 4칸도 된다. 온도별로 다르게 적을 수 있는 이유가 이것이다:

```yaml
temps:
  - tag: "125"
    levels: [rcmax, cmax]
    hidden_corners: [[0.5, rcmax], [0.6, cmax]]    # 2칸
  - tag: m25
    levels: [rcmax, cmax, rcmin]
    hidden_per_voltage: 1                          # 4칸 (전압마다 하나)
```

`v_order: auto` 는 이 산수를 자동으로 반영한다 — seen 코너 수보다 파라미터가
많아지지 않을 때까지 전압 차수를 낮춘다. 위 표에서 125C 가 `v^2`, m25C 가 `v^3`
로 갈린 게 그 결과다.

---

## 4. 규칙 (어기면 에러)

- **앵커 코너(`ref_voltage` × `ref_level`)는 숨길 수 없다.** 다항식 원점이자 경로
  선택 기준이라 반드시 seen 이어야 한다.
- `ref_level` 은 **모든 온도에 존재하는 레벨**이어야 한다. 이번엔 125C 에 `rcmin`
  이 없으므로 `cmax` 를 쓴다.
- `seen_voltages` 와 `hidden_voltages` 는 **동시 사용 불가** (서로 모순).
- `hidden_per_voltage` 와 `hidden_corners` 는 **동시 사용 불가** (한 온도 안에서).
- 숨긴 코너가 하나도 없고 `query_corners` 도 없으면 에러 — 예측할 대상이 없다.

---

## 5. 검증만 하고 싶지 않을 때 (실전 예측)

홀드아웃은 "맞히는지 보는" 용도다. 실제로 **안 잰 코너를 예측**하려면
`query_corners` 를 쓴다. 정답이 없으니 지표에서 빠지고 예측값만 CSV 에 나온다.

```yaml
temps:
  - tag: "125"
    levels: [rcmax, cmax]
    hidden_corners: [[0.5, rcmax], [0.6, cmax]]    # 검증용
    query_corners: [[0.57, cmax], [0.62, rcmax]]   # 실전 예측용 (측정 없음)
```

`query_corners` 를 추가하면 코너가 늘어나므로 **재빌드**해야 한다:

```bash
bash scripts/run.sh build
bash scripts/run.sh predict
```

검증을 아예 안 하고 전 코너를 학습에 쓰려면 홀드아웃 키를 모두 비우고
`query_corners` 만 넣는다. 그 경우 품질 확인은 `run.sh base` 의 **seen-LOO**
수치로 한다.

---

## 6. 바꾼 뒤 반드시

```bash
bash scripts/run.sh list      # hidden 목록 / seen 개수 / 파라미터 수 확인
```

`hidden :` 줄에 **의도한 코너가 정확히** 찍히는지, `⚠` 가 없는지 본다.
여기서 맞을 때까지는 build/train 으로 넘어가지 않는다.

관련 문서: 전체 키 목록은 [CONFIG.md](CONFIG.md), 차수/대역폭 튜닝은
[OLS.md](OLS.md), 처음부터 순서는 [START.md](START.md).
