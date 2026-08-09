# PVT 데이터 추출 — 현장 실행 안내

PrimeTime 으로 **여러 코너에서 같은 경로를 재측정**하고, 거기에 Dist/Res/Cpin 과
crosstalk 을 붙여 학습 입력 두 개를 만든다.

```
코너마다
    <코너>_fixed_annotated.txt                     Dist / Res / Cpin
    <코너>.path_context_si_compact.by_path.rpt     crosstalk 14열
```

이 문서 하나로 끝까지 갈 수 있게 써 두었다. 막히면 `코드표.md`, 원격으로 물어볼
때는 `원격문의.md`.

---

## 준비 — 파이썬 정하기 (한 번)

```bash
python3 0_check.py
```

화면에 `setenv PY ...` 한 줄이 나온다. 그대로 복사해서 실행한다. 이후 모든
파이썬 명령에서 `python3` 대신 `$PY` 를 쓴다.

```csh
setenv PY /usr/synopsys/pt/V-2023.12-SP4/etc/Python/bin/python3
```

- 시스템 `python3` 이 3.6 이상이면 그냥 `python3` 을 써도 된다.
- 2.7 밖에 없으면 `0_check.py` 가 PT 설치본 안의 3.6 을 찾아 준다.
- 그것도 없을 때만 `py27/` 을 쓴다 (`py27/README.md` 에 제약 명시).

**터미널을 두 개 띄운다.** 하나는 pt_shell, 하나는 셸. 파이썬 터미널은
라이선스를 안 먹으므로 PT 는 켜 둔 채로 왔다 갔다 한다.

---

## 전체 흐름

```
[PT]  1회차   코너마다 report_timing        -> round1/corners/<코너>.rpt
[셸]  union   합쳐서 측정할 경로 결정        -> fixed_paths.tcl
[PT]  2회차   그 경로를 코너마다 재측정      -> round2/<코너>/
[셸]  묶음 1  Dist/Res/Cpin + crosstalk 준비
[PT]  PT 1차  crosstalk 계산
[셸]  묶음 2  쌍 정리
[PT]  PT 2차  도착시각 / slew
[셸]  묶음 3  14열 리포트 완성
```

**터미널 왕복은 코너가 몇 개든 8번**이다. 각 단계가 끝날 때 다음에 칠 명령이
화면에 그대로 찍히니 외울 필요는 없다.

---

## 1회차 — 코너마다 경로 뽑기 (PT)

코너(db)를 바꿔 로드할 때마다 아래를 한 번씩. **파일 이름이 곧 코너 이름**이
되므로 db 이름과 맞춰 짓는다.

```tcl
redirect -file round1/corners/TT_0p6V_25C.rpt {
  report_timing -delay_type max -path_type full_clock_expanded \
    -nets -input_pins -nosplit -significant_digits 6 \
    -nworst 3 -max_paths 100000 -slack_lesser_than 0.05
}
```

| 옵션 | 왜 |
|---|---|
| `-nets -input_pins -nosplit -path_type full_clock_expanded` | **넷 다 필수.** 하나라도 빠지면 뒤에서 전부 막힌다 |
| `-slack_lesser_than` | 위험 마진. **넉넉하게** 준다 (좁히는 건 union 에서 공짜) |
| `-nworst` | 끝점 하나당 몇 개. 경로가 너무 많으면 여기서 줄인다 |
| `-max_paths` | **줄이는 용도로 쓰지 말 것.** 상한에 닿으면 코너마다 다른 지점에서 잘려 union 이 편향된다. 안 잘릴 만큼 크게 |

**hidden 코너는 이 폴더에 넣지 않는다.** 경로 선정에서 빠질 뿐, 2회차에서는
측정한다. 따로 제외 옵션은 필요 없다.

---

## union — 측정할 경로 결정 (셸)

```bash
$PY 1_union.py --dir round1/corners
```

폴더 안의 `.rpt` 를 전부 읽어 합집합한다. 코너가 3개든 20개든 코드는 안 건드린다.

```
  코너                     리포트   사용   제외
  TT_0p6V_25C                300    300      0
  TT_0p7V_25C                200    200      0
  TT_0p8V_25C                120    120      0

  [ 몇 개로 줄일까 ]  --slack-max <문턱값> 으로 다시 돌리면 그만큼이 된다
        경로 수          문턱값      2회차 시간/코너
         1000         -0.4210              1분
         3000         -0.2815              5분
        80000          0.0498            133분  (전체)

  합집합 경로 : 80000개
  한 코너에서만 나온 경로 : 12043   <- 합집합이 필요한 이유
```

**너무 많으면 표를 보고 문턱값을 골라 다시 돌린다.** PT 를 다시 돌릴 필요 없다.

```bash
$PY 1_union.py --dir round1/corners --slack-max -0.2815
#   합집합 경로 : 3000개
```

나오는 파일 셋:

| 파일 | 용도 |
|---|---|
| `union_summary.txt` | **vi 로 읽는 용도.** 경로별로 어느 코너에서 몇 ns 였는지 |
| `union_paths.tsv` | 같은 내용 TSV |
| `fixed_paths.tcl` | **2회차에서 PT 가 읽을 파일** |

자세한 설명은 `UNION_설명.md`.

---

## 2회차 — 코너마다 재측정 (PT)

`example/02_round2_all.tcl` 위쪽의 **코너 목록만** 자기 것으로 바꾼다.
`00_setup.tcl` 은 필요 없다 — 이 파일이 코너마다 알아서 로드한다.

```tcl
### 코너 목록 -- 적는 곳은 여기뿐 ###
set CORNERS {}
lappend CORNERS [list TT_0p6V_25C  "$L/TT_0p6V_25C_op_cond_all.db"  "$S/core_25.spef"]
lappend CORNERS [list TT_0p7V_25C  "$L/TT_0p7V_25C_op_cond_all.db"  "$S/core_25.spef"]
lappend CORNERS [list TT_0p6V_125C "$L/TT_0p6V_125C_op_cond_all.db" "$S/core_125.spef"]

### 디자인 -- 코너와 무관 ###
set CI_TOP     "MyCore"
set CI_VERILOG "$S/core_icc2.v"
set CI_SDC     "$S/core.sdc"

### 어디서 읽고 어디에 쓸지 ###
set FIXED  "/data/results/round1/corners/fixed_paths.tcl"
set OUTTOP "/data/results/round2"
```

| 칸 | 뜻 |
|---|---|
| 코너이름 | 폴더 이름이자 산출물 파일 이름. **db 이름과 맞추는 게 안전** |
| db | **이것이 코너를 결정한다** (전압/온도/공정) |
| spef | 배선 RC. **온도만** 맞추면 된다 (전압/공정과 무관) |

```
pt_shell> source example/02_round2_all.tcl
```

코너당 30초(로드) + 30초(측정). 코너 폴더마다 네 개가 생긴다.

```
<코너>.rpt          합집합 경로를 이 코너에서 측정한 것
pin_attr.txt        Cpin, arrival, slew
net_attr.txt        crosstalk delta, aggressor, coupling cap
corner_info.tcl     ★ 무슨 db/spef 로 만들었는지 기록
```

### `corner_info.tcl` 이 왜 중요한가

crosstalk 단계는 **나중에 따로 돈다.** 그때 이 폴더가 어느 db 로 만들어졌는지
알아야 같은 db 로 다시 로드할 수 있다. 없으면 처음 로드된 db 하나로 모든 코너를
계산해 버린다 — **값은 나오고 화면엔 `OK` 로 뜬다.** 그래서 없으면 아예
건너뛰도록 해 두었다.

### 한 코너만 다시 볼 때

`example/02_round2.tcl` 은 코너 하나짜리다. 위쪽 세 줄(`CORNER` / `CI_DB` /
`CI_SPEF`)만 바꿔 쓴다.

---

## 값 붙이기 — 묶음 1/2/3 (셸 ↔ PT)

파이썬이 PT 를 부를 수 없어서 세 토막으로 나뉜다. `--phase` 가 그 번호다.

```bash
# 셸
$PY 4_all_corners.py --root /data/results/round2 --spef /data/spef/core_25.spef --phase 1
```
```
pt_shell> source /data/results/round2/run_pt1_xtalk_calc.tcl
```
```bash
$PY 4_all_corners.py --root /data/results/round2 --phase 2
```
```
pt_shell> source /data/results/round2/run_pt2_xtalk_windows.tcl
```
```bash
$PY 4_all_corners.py --root /data/results/round2 --phase 3
```

`run_pt*.tcl` 두 개는 **`4_all_corners.py` 가 절대경로로 만들어 준다.** 고칠
것이 없고, 화면에 경로가 찍히니 복사만 하면 된다.

### 묶음마다 이 표가 나온다

```
  코너                      2a cpin       2b distres    2c merge      5a contexts
  TT_0p6V_25C             OK-CPIN       OK-DISTRES    OK-MERGE      OK-XCTX
  TT_0p7V_25C             E-NOFILE      -             -             -

  실패한 코너 1개: TT_0p7V_25C
      $PY 2a_cpin.py --dir /data/results/round2/TT_0p7V_25C
```

**어느 코너 어느 단계**인지 한눈에 보이고, 다시 볼 명령까지 찍어 준다.
한 코너가 실패해도 나머지는 계속 돈다.

| 옵션 | 언제 |
|---|---|
| `--spef <파일>` | 코너들이 같은 SPEF 를 쓸 때. 폴더에 `design.spef` 가 있으면 그쪽 우선 |
| `--skip-done` | **중간에 끊겼을 때.** 이미 만든 단계는 건너뛴다 |
| `--quiet` | 화면을 숨기고 결과 표만 |
| `--only 2a,2b` | 그 묶음 안에서 일부만 |
| `--mode hold` | hold 데이터를 만들 때 (5b 에 전달) |

### 손으로 하나씩 하고 싶으면

`4_all_corners.py` 는 아래를 대신 쳐줄 뿐이다. 결과 파일은 바이트 단위로 같다.

```bash
setenv D /data/results/round2/TT_0p6V_25C
$PY 2a_cpin.py     --dir $D                    # -> cpin.tsv       1초
$PY 2b_distres.py  --dir $D --spef <SPEF>      # -> distres.tsv    SPEF 크기에 따라
$PY 2c_merge.py    --dir $D                    # -> <코너>_fixed_annotated.txt ★
$PY 5a_contexts.py --dir $D                    # -> 물어볼 넷 목록
```
```
pt_shell> cd $D
pt_shell> source <패키지>/pt/xtalk_calc.tcl
```
```bash
$PY 5b_pairs.py --dir $D                       # -> 쌍
```
```
pt_shell> cd $D
pt_shell> source <패키지>/pt/xtalk_windows.tcl
```
```bash
$PY 5c_report.py --dir $D                      # -> <코너>.path_...by_path.rpt ★
```

---

## 결과 파일

### `<코너>_fixed_annotated.txt`

기존 리포트 오른쪽에 세 열이 붙은 것. **리포트 형식은 그대로**다.

```
  Point                        Fanout   Cap    Trans   Incr    Path      Dist       Res     Cpin
  ZCTSNET_6904 (net)               12 0.023539                        5.7240  488.8332   0.0005
```

| 열 | 무엇 | 단위 | 어디서 |
|---|---|---|---|
| `Dist` | 드라이버 핀 → 수신 핀 배선 거리 | µm | SPEF 좌표 |
| `Res` | 그 구간 저항 | Ω | SPEF `*RES` |
| `Cpin` | 수신 핀 입력 용량 | pF | PT `pin_capacitance_max` |

### `<코너>.path_context_si_compact.by_path.rpt`

**victim–aggressor 쌍 하나가 한 줄**, 14열. 기존 운영 산출물과 같은 형식이다.

```
path_segment  victim_net  aggressor_net  crosstalk_delta  aggressor_bump
number_of_aggressors  victim_load_pin  victim_load_min/max_arrival
aggressor_driver_pin  aggressor_driver_min/max_arrival
aggressor_driver_slew_max  coupling_cap_ff
```

---

## 코너 구성이 바뀔 때

| 바뀌는 것 | 고칠 곳 |
|---|---|
| 경로 선정 코너 | 1회차 `.rpt` 를 `round1/corners/` 에 넣느냐 마느냐 |
| 측정 코너 (hidden 포함) | `02_round2_all.tcl` 의 `CORNERS` 목록 |
| 디자인 | 같은 파일의 `CI_TOP` / `CI_VERILOG` / `CI_SDC` |
| 경로 개수 | `1_union.py --slack-max` |

**파이썬 코드는 손댈 일이 없다.**

---

## 막혔을 때

화면 마지막 블록의 **`하실 일`** 을 먼저 한다. 안 되면 `에러 코드`만 전달한다.

```
==================================================================
  문제 발생
    무엇이   : SPEF 에서 저항(Res)을 하나도 못 구했습니다
    하실 일  : SPEF 가 이 리포트와 같은 디자인/코너인지 확인해 주세요.

    에러 코드: E-RES0
==================================================================
```

`W-` 는 파일은 나왔지만 데이터가 불완전한 경우다. **몇 퍼센트인지**가 중요하다.

```bash
$PY 9_diagnose.py --dir <코너폴더>          # Dist/Res 가 빌 때 원인 분류
$PY 8_snapshot.py --dir <코너폴더>          # 상황 100줄 요약
$PY 8_snapshot.py --dir <코너폴더> --mask   # 설계 이름을 가리고
```

전체 코드 목록은 `코드표.md` (44개), 화면 읽는 법은 `원격문의.md`.

### PT 쪽에서 미리 확인할 것

```
pt_shell> printvar si_enable_analysis      # false 면 crosstalk 이 전부 0
```

SPEF 에 coupling 이 있어야 한다 (`read_parasitics -keep_capacitive_coupling`,
StarRC `COUPLING_CAP: YES`). grounded SPEF 면 crosstalk 결과가 무의미하다.

---

## 파일 목록

### 셸에서 돌리는 것

```
0_check.py         환경/입력 점검. 처음에 한 번
1_union.py         코너 합치기 -> fixed_paths.tcl
2a_cpin.py         Cpin        (SPEF 안 읽음, 1초)
2b_distres.py      Dist/Res    (SPEF 읽음)
2c_merge.py        -> <코너>_fixed_annotated.txt   ★
2_annotate.py      2a+2b+2c 를 한 번에 (나눠 놓은 게 디버깅엔 낫다)
5a_contexts.py     crosstalk 1단계 - 물어볼 넷 목록
5b_pairs.py        crosstalk 3단계 - 쌍 정리
5c_report.py       crosstalk 5단계 -> 14열 리포트   ★
4_all_corners.py   위를 코너 전부에 (--phase 1/2/3)
8_snapshot.py      막혔을 때 상황 요약
9_diagnose.py      Dist/Res N/A 원인 분류
```

### pt_shell 에서 source 하는 것

```
example/00_setup.tcl        예제용 디자인 로드 (현장에선 안 씀)
example/01_round1.tcl       1회차 예제/템플릿
example/02_round2_all.tcl   2회차 — 코너 전부   ★ 목록을 여기서 고침
example/02_round2.tcl       2회차 — 코너 하나
pt/xtalk_calc.tcl           crosstalk PT 1차 — 코너 하나 (디버깅)
pt/xtalk_windows.tcl        crosstalk PT 2차 — 코너 하나 (디버깅)
```

`pt/` 의 나머지(`load_corner.tcl`, `round2_one.tcl`, `dump_attr.tcl`,
`all_xtalk_*.tcl`)는 **직접 열 일이 없다.** 위 파일들이나 `4_all_corners.py`
가 알아서 부른다.

### 문서

```
README.md          이 파일. 현장 실행 안내
UNION_설명.md      union 이 하는 일과 결과 읽는 법
코드표.md          에러 코드 44개 전체
원격문의.md        화면 읽는 법, 원격으로 물어볼 때
example/README.md  BoomCoreV3 로 전 과정을 돌려 본 기록
py27/README.md     파이썬 3 이 전혀 없을 때만 (제약 있음)
```

---

## 한 번 돌려 보고 가려면

`example/README.md` 에 실제 디자인(BoomCoreV3, 3nm)으로 처음부터 끝까지 돌린
기록이 있다. 숫자까지 그대로 적어 두었으니, 현장에서 나온 숫자와 비교해 보면
된다.
