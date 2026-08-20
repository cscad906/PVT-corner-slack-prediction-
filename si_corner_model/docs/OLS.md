# OLS — base 가 뭘 하는지, 어떻게 맞추는지

예측의 8할은 이 base 다. 신경망은 base 가 못 잡는 **잔차**만 학습한다.
그래서 base 가 어긋나 있으면 학습을 아무리 돌려도 안 된다 —
**학습 전에 `bash scripts/run.sh base` 를 먼저 보는 이유**다.

```
예측 = OLS_base(V, level)                      ← 이 문서
     + gate · [ CorrHead(측정된 코너 attention)
              + SI_branch ]
```

---

## 1. base 는 "경로마다 하나씩" 이다

전체를 아우르는 모델 하나가 아니라, **경로 N개면 다항식 N개**를 푼다.
경로 하나의 slack 을 코너 좌표의 다항식으로 본다:

```
slack(V, level) ≈ β0 + β1·dv + β2·dv² + β3·dlevel + β4·dv·dlevel + ...
      dv     = V     − ref_voltage
      dlevel = level − level_values[ref_level]
```

계수 β 는 그 경로의 **측정된(seen) 코너들**로 최소자승으로 푼다. 경로가 수천 개라도
설계행렬 Φ 는 코너 수 × 항 수로 전부 공유되므로 한 번에 행렬 연산으로 끝난다.

**왜 경로별인가**: 경로마다 스테이지 구성이 달라 전압 민감도가 다르다. 공통
계수를 억지로 쓰면 그 차이가 전부 잔차로 넘어가고, 신경망이 감당할 양이 폭증한다.

---

## 2. 누수 없이 검증하는 법 (leave-one-out)

| 코너 종류 | base 가 쓰는 데이터 |
|---|---|
| **hidden** (측정 안 함) | seen 코너 **전부**로 피팅 → 그 좌표에서 평가. 애초에 측정이 없으니 누수 불가 |
| **seen** (측정함) | **자기 자신을 뺀** 나머지 seen 으로 피팅 → 자기 좌표에서 평가 |

seen 코너에서 자기 자신을 빼는 건 hat matrix 로 닫힌 형태로 계산된다
(`e_loo = (y − ŷ)/(1 − h)`), 그래서 코너마다 다시 피팅할 필요가 없다.
이게 `run.sh base` 가 찍는 **seen-LOO** 수치이고, 홀드아웃이 없을 때의 유일한
검증 수단이다.

---

## 3. 차수 — `v_order` / `level_order`

**핵심 제약: N개 레벨로는 N−1차까지만 식별할 수 있다.** 전압 seen 이 3개면
`dv³` 은 애초에 풀 수 없다. `auto` 가 이걸 자동으로 지킨다:

```yaml
base:
  v_order: auto        # = min(6, seen 전압 수 − 1)
  level_order: auto    # = min(2, seen 레벨 수 − 1)
```

이번 데이터에서 실제로 이렇게 갈린다:

| | seen 전압 | seen 레벨 | 차수 | 항 | 파라미터(절편 포함) |
|---|---|---|---|---|---|
| 125C | 3 | 2 | v²×level¹ | `dv, dv², dlevel, dv·dlevel` | **5** |
| m25C | 3 | 3 | v²×level² | + `dlevel²` | **6** |

넘치는 항은 자동으로 제거되고 `[BASIS] dropped ...` 로 찍힌다 (정상 동작).

### 파라미터 수 vs seen 코너 수 — 여기가 함정

| seen 코너 − 파라미터 | 상태 |
|---|---|
| 음수 | 못 푼다 (rank 부족) |
| 0 | 완전히 fit — 잔차 0, LOO 무의미. **최악** |
| 1~2 | 매우 불안정. LOO leverage 가 1에 가까워 값이 튄다 |
| 3 이상 | 쓸만함 |

`run.sh list` 가 `corners : 전체 8 = seen 6 + hidden 2` 와
`basis : v^2 x level^1 -> 5 파라미터` 를 같이 찍고, seen ≤ 파라미터면
**⚠ 경고**를 낸다. 이번 125C 는 6 − 5 = **1** 이라 빠듯하다.

**빠듯하면 셋 중 하나:**

1. 차수를 낮춘다 — `v_order: 1` (선형). 코너가 정말 적으면 이게 정답일 수 있다.
2. 교차항을 끈다 — `cross_terms: false` → 125C 파라미터 5 → 4.
3. **홀드아웃을 포기하고** 전 코너를 seen 으로 쓰고, 검증은 seen-LOO 로:
   ```yaml
   corners:
     hidden_voltages: []
     query_corners: [[0.57, cmax], [0.62, rcmax]]
   ```
   실사용 목적이 "안 잰 코너 예측" 이라면 이게 가장 자연스럽다.

---

## 4. `weighting` — 세 가지 피팅 방식

```yaml
base:
  weighting: adaptive     # plain | local | adaptive
```

### `plain` — 전역 OLS 한 번

모든 seen 코너를 동등하게 써서 계수 한 벌을 푼다. 가장 단순하고, 코너가 매우
적으면 오히려 이게 낫다. 단점: 그리드 한쪽 끝의 큰 오차가 반대쪽 예측까지 오염시킨다.

### `local` — 고정 대역폭 가중 OLS

질의 코너마다 다시 푸는데, 가까운 코너에 가우시안 가중을 준다.

```yaml
weighting: local
bandwidth: [0.05, 1.0]    # (dv 볼트, dlevel 좌표) 단위
```

`bandwidth` 가 작으면 국소적(유연하지만 불안정), 크면 전역에 가까워진다.
값의 감은 **seen 그리드 간격**에서 온다 — 전압이 0.05V 간격이면 `0.05~0.1` 근처.

### `adaptive` — 코너마다 대역폭을 자동으로 (기본 아님)

> **기본값은 `plain` 이다.** base 단독 성적만 보면 adaptive 가 나아 보일 수 있지만,
> base 는 혼자 쓰이지 않는다 — 그 위에서 신경망이 잔차를 배운다. adaptive base
> 위에서는 그 학습이 **아예 안 됐다** (14nm 실측):
>
> | | base 단독 | 학습 후 |
> |---|---|---|
> | 125C adaptive | 3.151 ps | 3.08 ps 에서 정지 |
> | 125C plain | 2.148 ps | **0.94 ps** |
> | m25 adaptive | 11.20 ps | 30 epoch 내내 11.19 ps |
> | m25 plain | 11.00 ps | **10.25 ps** |
>
> m25 는 base 단독으로는 adaptive 가 worst 에서 앞서는데(13.5 vs 19.6) 최종은
> plain 이 이긴다. **base 만 보고 고르면 안 된다**는 뜻이다.
> `run.sh base` 가 세 방식을 다 재서 비교표로 찍어주니 직접 확인할 수 있다.

후보 대역폭들을 다 계산해두고, **질의 코너마다** 가장 좋은 걸 고른다. 평평한
영역은 좁은 커널(정확), 가파른 영역은 넓은 커널(안정)을 자동으로 쓴다.

고르는 기준이 **라벨을 안 본다**는 게 핵심이다 — 그 코너 자신의 정답이 아니라,
**가까운 seen 이웃 k개에서의 LOO 오차**로 고른다. 그래서 hidden 코너에서도
똑같은 절차가 성립하고 누수가 없다.

| 키 | 기본 | 의미 |
|---|---|---|
| `adaptive_grid` | `null` | 후보 대역폭. `null` = seen 간격에서 자동 유도 ({1×, 2×, 4×} 중앙값 간격 + 전역) |
| `adaptive_k` | 6 | 대역폭 고를 때 볼 이웃 seen 코너 수 |
| `adaptive_amp_ratio` | 1.5 | **외삽 가드**: 예측 분산이 전역 피팅의 1.5배를 넘는 대역폭은 거부 |
| `adaptive_clip_frac` | 0.3 | 후보 예측을 측정범위 ±0.3×range 로 clip |

뒤의 두 개는 안전장치다. 좁은 커널은 seen 영역 **바깥**에서 폭주하는데, 이웃 LOO
기준만으로는 그게 안 보인다 (이웃은 다 내삽이라). `amp_ratio` 가 분산으로 그걸
잡고, `clip_frac` 이 최종 방어선이다.

직접 후보를 주려면 (그리드 간격을 알 때):

```yaml
adaptive_grid: [[0.02, 1.0], [0.05, 1.0], [0.1, 2.0], null]   # null 항목 = 전역 피팅도 후보
```

`run.sh base` 가 어떤 대역폭이 몇 개 코너에서 뽑혔는지(`[adaptive] ...`) 찍어준다.
전부 `null`(전역)로 뽑히면 그리드가 너무 성겨 국소 피팅이 의미 없다는 뜻이다.

---

## 5. 교차항

```yaml
cross_terms: true
cross_max_degree: 2      # 코너가 적으면 2, 넉넉하면 3
```

`dv·dlevel` 같은 혼합항. "전압이 낮을수록 BEOL 영향이 커진다" 같은 상호작용을
표현한다. 물리적으로는 있는 현상이지만 파라미터를 잡아먹으니, 코너가 적으면
`cross_max_degree: 2` 로 제한하거나 아예 끄는 게 낫다.

- `cross_max_degree: 2` → `dv·dlevel` 까지
- `cross_max_degree: 3` → `dv²·dlevel`, `dv·dlevel²` 까지

---

## 6. 스케일 (거의 안 건드림)

| 키 | 언제 |
|---|---|
| `v_fit_scale` / `level_fit_scale` | 피팅 **전에** 좌표를 나눈다. 축 범위가 O(1)에서 크게 벗어날 때만 (예: 온도를 축으로 쓰면 100) |
| `v_token_scale` / `level_token_scale` | 신경망 feature 의 좌표 단위. base 와 무관 |
| `v_gap_cap` / `level_gap_cap` | 신경망 gate 가 쓰는 "외삽 거리" feature 의 상한 |

전압 0.5~0.685, 레벨 −1~1 이면 전부 이미 O(1)이라 기본값(1.0)으로 충분하다.

---

## 7. 튜닝 절차

```bash
bash scripts/run.sh build      # 캐시 생성
bash scripts/run.sh base       # ← 여기만 보면 된다 (numpy만, GPU 불필요, 수 초)
```

출력:

```
    hidden SSPG_0p54V_cmax        12.431 ps
    hidden SSPG_0p54V_rcmax       15.882 ps
    [hidden mean]                 14.156 ps  (worst 15.882)
    [seen-LOO   ]                  3.204 ps  (worst 5.1)
```

읽는 법:

| 관찰 | 해석 | 조치 |
|---|---|---|
| hidden 이 상식 밖 (수 ns 등) | 파싱/코너 정의가 틀렸다 | `level_values` 간격, `ref_voltage`, 전압 파싱 확인 |
| hidden ≫ seen-LOO | 과적합 | 차수↓, `cross_terms: false`, `adaptive_amp_ratio`↓ |
| hidden ≈ seen-LOO 인데 둘 다 큼 | 표현력 부족 | 차수↑, `cross_max_degree: 3` |
| seen-LOO 가 거의 0 | 파라미터가 seen 코너 수와 같다 | **차수를 낮춰라** (LOO 가 무의미한 상태) |
| 특정 코너만 나쁨 | 그리드 가장자리 외삽 | `adaptive` 확인, `adaptive_grid` 에 넓은 후보 추가 |

여기서 납득할 수치가 나온 다음에 `run.sh train` 으로 넘어간다.
학습 로그·`summary.json`·예측 CSV 에는 **base 수치가 안 나온다** — 모델 수치와
헷갈리지 않게 일부러 분리해뒀다.
