# PVT 데이터 추출 — 현장 실행 안내

PrimeTime 에서 타이밍 리포트와 속성을 뽑고, 파이썬으로 **Dist / Res / Cpin** 과
**crosstalk feature** 를 붙이는 절차입니다.

읽는 순서대로 따라 하면 됩니다. 각 명령은 끝날 때 **`[ 정상 ]` 또는 `[ 실패 ]`** 와
다음에 칠 명령을 화면에 알려줍니다.

---

## 0. 준비 — 파이썬 찾기

시스템 `python` 이 2.7 이어도 상관없습니다. **PrimeTime 설치본 안에 Python 3.6 과
networkx 가 들어 있어서**, PT 가 도는 곳이면 따로 설치할 필요가 없습니다.

```bash
python3 0_check.py
```

화면에 나온 경로를 그대로 복사해 둡니다.

```bash
export PY=/.../pt/etc/Python/bin/python3      # bash
setenv PY /.../pt/etc/Python/bin/python3      # csh
```

이후 모든 명령에서 `python3` 대신 `$PY` 를 씁니다.

---

## 폴더 구조

```
round1/                 1회차 — 어떤 경로를 볼지 고르는 단계
  corners/  <코너>.rpt    ← 합집합(union) 대상
  hidden/   <코너>.rpt    ← 합집합에서 제외. 2회차에서 측정만 한다

round2/                 2회차 — 고정된 같은 경로를 코너마다 다시 측정
  <코너>/  timing.rpt        재측정 결과
           pin_attr.txt      핀 속성
           net_attr.txt      넷 속성
           design.spef       그 코너의 SPEF (또는 --spef 로 경로 지정)
           annotated.txt     결과 ①
           crosstalk.tsv     결과 ②
```

**1회차 파일은 2회차에서 건드리지 않습니다.** 서로 다른 폴더에 남겨 두세요.

`hidden/` 은 "경로를 고를 때는 빼고, 나중에 측정만 할" 코너입니다.
그 코너에서만 위반인 경로가 목록에 끼지 않게 하면서, 측정값은 확보하는 용도입니다.
필요 없으면 `hidden/` 없이 전부 `corners/` 에 넣으면 됩니다.

---

## 1회차 — 코너마다 경로 뽑기 (PT)

담당자가 세팅해 둔 pt_shell 에서, **코너를 바꿔 로드할 때마다** 아래를 실행합니다.

```tcl
report_timing -delay_type max -path_type full_clock_expanded \
  -nets -input_pins -nosplit \
  -nworst 3 -max_paths 3000 -slack_lesser_than 0.05 \
  > round1/corners/tt0p65v25c_Cnom.rpt
```

- **파일 이름이 그대로 코너 이름**이 됩니다. 전압·온도·RC 를 알아볼 수 있게 지으세요.
- `-slack_lesser_than` 은 **모든 코너에 같은 값**을 주세요. 코너마다 다르면 합집합이 한쪽으로 치우칩니다.
- `0.05` 는 SDC 시간 단위 기준입니다(보통 ns → 50ps). 위반(slack<0)뿐 아니라 **위반 위험**까지 담는 값입니다.
- hidden 코너는 같은 명령을 쓰되 `round1/hidden/` 에 저장합니다.

> 1회차 리포트는 경로를 고르는 데만 쓰므로 `-nets -input_pins` 만 있으면 됩니다.

---

## 1. 합집합 만들기 (파이썬)

```bash
$PY 1_union.py --dir round1/corners
```

만들어지는 것:

| 파일 | 내용 |
|---|---|
| `union_paths.tsv` | 합집합 경로 목록. 코너별 slack 이 열로 들어 있어 엑셀로 볼 수 있습니다 |
| `fixed_paths.tcl` | 2회차에 pt_shell 에서 `source` 할 파일 |

**왜 합집합인가**: 코너마다 위반하는 경로가 다릅니다. 실제로 돌려 보면
`한 코너에서만 나온 경로` 가 상당수입니다. 어느 한 코너 기준으로 고르면 그만큼을
놓치므로, 전 코너의 목록을 합친 뒤 그 전체를 모든 코너에서 똑같이 재측정합니다.

**같은 경로인지 판단하는 기준**은 `(시작 FF, 끝 FF, 지나는 핀 전부)` 입니다.
같은 FF 쌍 사이에도 지나는 길이 다른 별개 경로가 있어서, 핀 목록까지 같아야
같은 경로로 칩니다. rise/fall 방향도 함께 고정하므로, 코너가 바뀌어도 같은 번호가
같은 물리 경로를 가리킵니다.

---

## 2. 2회차 — 고정 경로 재측정 (PT)

`fixed_paths.tcl` 상단의 `OUT` 을 그 코너용 경로로 바꾸고, **코너마다** 실행합니다.
hidden 코너도 여기서는 포함합니다.

```tcl
set OUT "round2/tt0p65v25c_Cnom/timing.rpt"
source round1/corners/fixed_paths.tcl
```

이어서 속성을 뽑습니다. `pt/dump_attr.tcl` 상단 두 줄을 그 코너에 맞게 바꾼 뒤:

```tcl
source pt/dump_attr.tcl
```

```tcl
set RPT     "round2/tt0p65v25c_Cnom/timing.rpt"
set OUTDIR  "round2/tt0p65v25c_Cnom"
```

`pin_attr.txt`, `net_attr.txt` 가 만들어집니다.

> **전체 핀을 덤프하면 파일이 9GB 를 넘습니다.** 그래서 `dump_attr.tcl` 은 리포트에
> 등장하는 것만 골라 뽑습니다(실제 데이터에서 핀 9,184개 / 210MB).

SPEF 를 그 폴더에 `design.spef` 로 두거나, 파이썬 실행 시 `--spef` 로 경로를 줍니다.

---

## 3. 파이썬으로 값 붙이기 (코너마다)

```bash
$PY 0_check.py    --dir round2/tt0p65v25c_Cnom     # 입력 점검
$PY 2a_cpin.py    --dir round2/tt0p65v25c_Cnom     # Cpin      (SPEF 안 읽음, 몇 초)
$PY 2b_distres.py --dir round2/tt0p65v25c_Cnom     # Dist/Res  (SPEF 읽음, 수십 초~수 분)
$PY 2c_merge.py   --dir round2/tt0p65v25c_Cnom     # 합치기    (즉시)
$PY 3_crosstalk.py --dir round2/tt0p65v25c_Cnom    # crosstalk 표
```

세 단계로 나눈 이유:

- `2a` 는 **SPEF 를 읽지 않아** 몇 초면 끝납니다. 핀 이름이 안 맞는 문제를 기다림 없이 확인할 수 있습니다.
- SPEF 를 잘못 물려도 `2a` 결과(Cpin)는 살아남습니다.
- 중간 파일 `cpin.tsv`, `distres.tsv` 는 `line_no / 이름 / 값` 형태라 **엑셀로 열어 빈칸만 걸러 보면** 무엇이 문제인지 바로 보입니다.

한 번에 하고 싶으면 `2_annotate.py` 를 쓰면 됩니다(결과는 위 세 개와 동일).

---

## 결과 파일

| 파일 | 내용 |
|---|---|
| `annotated.txt` | 리포트의 `(net)` 줄 끝에 **Dist / Res / Cpin** 3열이 붙은 것 |
| `crosstalk.tsv` | 한 줄 = 경로의 한 구간. 28열(경로 정보 + 넷 속성 + 핀 속성) |

### 값의 출처와 단위

| 값 | 단위 | 어디서 오나 |
|---|---|---|
| **Dist** | µm | SPEF 좌표. 드라이버–리시버 맨해튼 거리 |
| **Res** | Ω | SPEF `*RES`. 두 핀 사이 배선 저항 |
| **Cpin** | pF | PT 핀 속성 `pin_capacitance_max` |
| Trans / Incr / Path / Cap | ns / pF | PT 리포트 |

- PT 자체의 저항 단위는 kΩ 이지만, **Res 는 SPEF 에서 직접 계산하므로 Ω** 입니다.
  나중에 PT 의 `net_resistance_max` 와 섞으면 1000배 차이가 나니 주의하세요.
- 숫자는 소수점 6자리로 반올림하고 뒤쪽 0 은 뗍니다. `report_timing` 의
  `-significant_digits 6` 과 자릿수를 맞춘 것입니다.

---

## 막혔을 때

### N/A 가 나온다

```bash
$PY 9_diagnose.py --dir round2/<코너>
```

원인을 네 가지로 분류해 줍니다.

| 원인 | 뜻 | 할 일 |
|---|---|---|
| **A** | 넷이 SPEF 에 아예 없음 | SPEF 가 그 코너/디자인 것이 맞는지 확인. 클럭 넷은 원래 빠질 수 있습니다 |
| **B** | 이름 표기만 다름 | **그 화면을 그대로 가져오세요.** 이름 규칙을 넓히면 해결됩니다 |
| **C** | 찾았는데 저항 경로가 없음 | SPEF 를 R 포함으로 다시 뽑아야 합니다 |
| **D** | Cpin 만 빔 | `pin_attr.txt` 를 다시 뽑아야 합니다 |

### 자주 나오는 실패

| 화면 | 원인 | 해결 |
|---|---|---|
| `(net) 줄이 없습니다` | `report_timing` 에 `-nets` 가 빠짐 | 옵션 추가 후 다시 |
| `pin_capacitance_max 를 못 읽었습니다` | `report_attribute` 에 `-application` 이 빠짐 | 옵션 추가 후 다시 |
| `crosstalk 값이 전부 0` | SI 가 꺼졌거나 SPEF 에 coupling 없음 | `si_enable_analysis true` + coupling 유지 SPEF |
| `경로가 하나도 없습니다` | `-slack_lesser_than` 이 너무 빡셈 | 값을 키워서 다시 |
| `Res 를 하나도 못 구했습니다` | SPEF 가 그 리포트와 짝이 아님 | 코너에 맞는 SPEF 인지 확인 |

### PT 쪽에서 미리 확인할 것

```tcl
get_app_var si_enable_analysis                  ;# crosstalk 을 뽑으려면 true
get_app_var timing_save_pin_arrival_and_slack   ;# 핀 arrival 을 뽑으려면 true
```

둘 중 하나라도 `false` 면 값을 켜고 `update_timing -full` 을 한 뒤 다시 뽑아야 합니다.

---

## 파일 목록

```
0_check.py       환경·입력 점검
1_union.py       코너별 리포트 -> 합집합 + fixed_paths.tcl
2a_cpin.py       Cpin        (SPEF 불필요)
2b_distres.py    Dist / Res  (SPEF 사용)
2c_merge.py      위 둘을 리포트에 붙이기
2_annotate.py    2a+2b+2c 를 한 번에 (결과 동일)
3_crosstalk.py   crosstalk / timing window 표
9_diagnose.py    N/A 원인 분류
pt/dump_attr.tcl PT 에서 핀·넷 속성 덤프
_engine/         내부 계산 코드 (열어볼 필요 없음)
```
