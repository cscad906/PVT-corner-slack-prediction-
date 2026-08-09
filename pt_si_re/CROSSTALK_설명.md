# `3_crosstalk.py` 설명서 — 결과 표 읽는 법

코딩을 몰라도 결과를 확인하고 넘길 수 있게 쓴 문서입니다.

---

## 1. 무엇을 만드나

```
넣는 것   timing.rpt      경로 순서와 핀·넷 연결
          net_attr.txt    crosstalk 값        (dump_attr.tcl 이 만듦)
          pin_attr.txt    arrival, slew, Cpin (같은 파일이 만듦)

나오는 것 crosstalk.tsv   한 줄 = 경로의 한 구간(arc). 28열.
```

```bash
$PY 3_crosstalk.py --dir round2/<코너>
```

**SPEF 를 읽지 않습니다.** 그래서 몇 초면 끝납니다.

### 왜 세 파일을 합쳐야 하나

- `net_attr.txt` / `pin_attr.txt` 에는 **"어느 경로의 넷인지" 정보가 없습니다.** 넷·핀 단위로만 나옵니다.
- `timing.rpt` 에는 **crosstalk 값이 없습니다.**

이 스크립트가 리포트에서 `경로 → 핀 → 넷` 순서를 읽고, 속성을 이름으로 붙입니다.

---

## 2. 한 줄이 무엇인가

리포트에서 신호가 지나가는 **한 구간**입니다.

```
리포트                                    crosstalk.tsv
  U1/A (INV)     ← 핀                       arc_idx=5  pin=U1/A   net=(빈칸)
  U1/X (INV)     ← 핀                       arc_idx=6  pin=U1/X   net=n123
  n123 (net)     ← 그 핀이 구동하는 넷
  U2/B (AND)     ← 다음 핀                  arc_idx=7  pin=U2/B   net=(빈칸)
```

**핀 줄 하나가 결과 한 줄**이 됩니다. 그 핀 바로 뒤에 `(net)` 줄이 있으면 `net` 열이 채워지고, 없으면 빕니다.

그래서 `net` 열이 **절반쯤 비는 것이 정상**입니다(핀·넷이 번갈아 나오므로).

---

## 3. 28개 열

### 경로 정보 (1~12) — 어느 경로의 어디인가

| # | 열 | 뜻 |
|---|---|---|
| 1 | `path_idx` | 경로 번호. **`### FIXED_PATH idx=` 와 같은 번호** |
| 2 | `startpoint` | 시작 플립플롭 |
| 3 | `endpoint` | 끝 플립플롭 |
| 4 | `path_group` | 클럭 그룹 |
| 5 | `path_type` | max(setup) / min(hold) |
| 6 | `slack_status` | VIOLATED / MET |
| 7 | `slack` | 그 경로의 slack. **경로의 모든 줄에 같은 값** |
| 8 | `arc_idx` | 경로 안에서 몇 번째 구간인지 |
| 9 | `pin` | 이 구간의 핀 |
| 10 | `cell` | 그 핀이 속한 셀 종류 |
| 11 | `edge` | r(상승) / f(하강) |
| 12 | `net` | 그 핀이 구동하는 넷 (없으면 빈칸) |

**`path_idx` 가 핵심입니다.** 코너가 달라도 같은 번호는 같은 물리 경로라, 코너별 파일을 이 번호로 이어 붙이면 됩니다.

### 넷 속성 (13~21) — crosstalk

| # | 열 | 뜻 | 단위 |
|---|---|---|---|
| 13 | `net.annotated_delay_delta_max` | **crosstalk 로 늘어난 딜레이** | ns |
| 14 | `net.annotated_delay_delta_min` | 같은 것의 min 쪽 (음수 가능) | ns |
| 15 | `net.number_of_aggressors` | 옆에 붙은 넷 개수 | — |
| 16 | `net.number_of_effective_aggressors` | 그중 **실제로 영향을 준** 것 | — |
| 17 | `net.total_coupling_capacitance` | 결합 용량 합 | pF |
| 18 | `net.total_effective_coupling_capacitance` | 그중 유효한 것 | pF |
| 19 | `net.effective_aggressors` | 영향을 준 넷 **이름 목록** | — |
| 20 | `net.si_xtalk_bumps` | 넷별 전압 튐 값/사유 | — |
| 21 | `net.net_resistance_max` | PT 가 본 넷 저항 | **kΩ** |

> `net_resistance_max` 는 **PT 단위라 kΩ** 입니다. `annotated.txt` 의 `Res`(SPEF 에서 계산, **Ω**)와 1000배 차이가 나니 섞으면 안 됩니다.

### 핀 속성 (22~28) — 언제 도착하고 얼마나 느린가

| # | 열 | 뜻 | 단위 |
|---|---|---|---|
| 22 | `pin.pin_capacitance_max` | 그 핀의 입력 용량 (= Cpin) | pF |
| 23~26 | `min/max_rise/fall_arrival` | 신호 도착 시각 범위 | ns |
| 27~28 | `actual_rise/fall_transition_max` | 신호 기울기(slew) | ns |

도착 시각 범위가 필요한 이유: crosstalk 는 **victim 과 aggressor 가 같은 시점에 움직일 때만** 실제 영향이 있습니다. 그 판단 재료입니다.

---

## 4. 화면 읽는 법

```
  경로        : 868
  줄(구간)    : 55418
  컬럼        : 기본 12 + 넷 9 + 핀 7
  넷 속성 매칭: 27709  (못 찾음 0)
  핀 속성 매칭: 53682
  crosstalk 값이 0 이 아닌 줄: 13236

  정상 종료           [ OK-XTALK ]
```

| 항목 | 정상 범위 |
|---|---|
| 경로 | 리포트의 경로 수와 같음 |
| 줄(구간) | 경로 수 × 수십 |
| **넷 속성 못 찾음** | **0 이어야 정상** |
| 핀 속성 매칭 | 전체 줄의 90% 이상 |
| crosstalk 0 아닌 줄 | 전체의 10~50% 정도 |

### 이러면 이상합니다

| 증상 | 원인 | 할 일 |
|---|---|---|
| 넷 속성 못 찾음이 많음 | `net_attr.txt` 를 **다른 리포트로** 만듦 | 지금 리포트로 `dump_attr.tcl` 다시 |
| `crosstalk 0 아닌 줄 : 0` (`W-XT0`) | SI 가 꺼졌거나 SPEF 에 coupling 없음 | PT 에서 `si_enable_analysis` 확인 |
| 컬럼이 `넷 9` 보다 적음 | 속성 일부가 덤프에 없음 | `dump_attr.tcl` 의 `NET_ATTRS` 확인 |

---

## 5. 빈 칸이 정상인 경우

| 열 | 빈 비율 | 왜 |
|---|---|---|
| `net` 과 `net.*` | **약 50%** | 핀·넷이 번갈아 나오므로. 핀 뒤에 넷이 없으면 빔 |
| `effective_aggressors`, `si_xtalk_bumps` | 약 60% 채워짐 | 영향을 준 aggressor 가 없는 넷은 빔 |
| `pin.*` | 약 3% 빔 | 포트 등 속성이 없는 핀 |
| `slack`, `path_idx` | **0%** | 모든 줄에 있어야 함 |

`slack` 이나 `path_idx` 가 비어 있으면 문제입니다.

---

## 6. 결과 직접 확인하기 (vi / 터미널)

```bash
# 줄 수와 열 수
head -1 round2/<코너>/crosstalk.tsv | tr '\t' '\n' | wc -l     # 28 이어야 함
wc -l round2/<코너>/crosstalk.tsv

# 열 이름 보기
head -1 round2/<코너>/crosstalk.tsv | tr '\t' '\n' | nl

# crosstalk 값이 있는 줄 몇 개 보기 (13번째 열)
awk -F'\t' 'NR>1 && $13!="" && $13+0!=0 {print $1, $12, $13}' round2/<코너>/crosstalk.tsv | head

# 경로 1번만 보기
awk -F'\t' '$1=="1"' round2/<코너>/crosstalk.tsv | head -20
```

vi 로 열면 탭 때문에 어긋나 보입니다. 위 `awk` 로 필요한 열만 뽑아 보는 게 낫습니다.

---

## 7. 코너별 파일을 나중에 합칠 때

각 코너가 `round2/<코너>/crosstalk.tsv` 를 만듭니다. 합칠 때는 `--corner` 로 이름을 붙여 두면 편합니다.

```bash
$PY 3_crosstalk.py --dir round2/tt0p65v25c --corner tt0p65v25c
```

`corner` 열이 맨 앞에 추가됩니다. 그러면 여러 코너 파일을 그냥 이어 붙여도 어느 코너인지 구분됩니다.

```bash
# 첫 파일은 헤더까지, 나머지는 헤더 빼고 이어 붙이기
head -1 round2/코너1/crosstalk.tsv                >  all_crosstalk.tsv
for f in round2/*/crosstalk.tsv; do tail -n +2 $f >> all_crosstalk.tsv; done
```

`path_idx` 가 코너 사이에 공통이므로, `corner` + `path_idx` + `arc_idx` 세 개면 한 줄이 특정됩니다.

---

## 8. 막히면

화면 마지막의 **`문제 발생` / `확인 필요`** 블록을 먼저 보세요. 무엇이 문제이고 무엇을 하면 되는지 나옵니다.

그래도 안 되면 `에러 코드`(예: `E-NETNAME`, `W-XT0`)를 알려주시면 됩니다.
전체 목록은 `코드표.md` 에 있습니다.
