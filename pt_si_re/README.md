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
python 0_check.py
```

**이 파일만은 파이썬 2.7 로도 돌아간다.** 현장에 파이썬 3 이 있는지 모르는
상태에서 제일 먼저 돌리는 파일이라 그렇게 만들어 두었다. `python` 이든
`python3` 이든 되는 쪽으로 치면 된다.

화면에 **어떤 파이썬을 쓸지** 나온다.

```
  >>> 이 파이썬을 쓰세요:

      /usr/synopsys/pt/V-2023.12-SP4/etc/Python/bin/python3

      시스템 python3 이 낡았거나 없어서, 위 전체 경로를 그대로
      명령 앞에 붙여 쓰세요.
        예)  /usr/synopsys/pt/V-2023.12-SP4/etc/Python/bin/python3 1_union.py --dir round1/corners
```

- 그냥 `python3` 을 쓰라고 나오면 아래 예시대로 `python3 ...` 로 치면 된다.
- 전체 경로가 나오면 **그 경로를 명령 앞에 붙여서** 친다. (시스템 python3 이
  3.6 미만이어서, `0_check.py` 가 PT 설치본 안의 3.6 을 찾아 준 것이다)
- **이 뒤로는 외울 필요가 없다.** 각 단계가 끝날 때 다음에 칠 명령이 경로까지
  통째로 화면에 찍히므로 복사해서 쓰면 된다.

  ```
  [ 정상 ] Cpin 8930/8930.
           다음 단계:  /usr/synopsys/pt/.../python3 2b_distres.py --dir round2/TT_0p6V_25C
  ```


**터미널을 두 개 띄운다.** 하나는 pt_shell, 하나는 셸. 파이썬 터미널은
라이선스를 안 먹으므로 PT 는 켜 둔 채로 왔다 갔다 한다.

---

## 전체 흐름

```
[PT]  1회차   코너마다 report_timing        -> round1/corners/<코너>.rpt
[셸]  union   합쳐서 측정할 경로 결정        -> fixed_paths.tcl
[PT]  2회차   그 경로를 코너마다 재측정      -> round2/<코너>/
[셸]  묶음 1  Dist/Res/Cpin + crosstalk 준비
[PT]  crosstalk  계산 + 도착시각/slew 를 한 번에  (xtalk_all.tcl)
[셸]  묶음 2  쌍 정리 + 14열 리포트 완성
```

**터미널 왕복은 코너가 몇 개든 6번**이다. 각 단계가 끝날 때 다음에 칠 명령이
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
python3 1_union.py --dir round1/corners
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

**너무 많으면 줄여서 다시 돌린다. PT 를 다시 돌릴 필요 없다.** 두 가지 방법이 있다.

```bash
# (1) 개수로 자르기 -- 간단하다. 가장 나쁜 slack 부터 남는다
python3 1_union.py --dir round1/corners --max-paths 10000
#   --max-paths 10000 로 80000개 중 10000개만 남겼습니다.
#     (가장 나쁜 slack 부터. 자른 지점의 slack = -0.1102)
#   합집합 경로 : 10000개

# (2) 문턱값으로 자르기 -- "slack 이 이보다 나쁜 것만" 이 기준일 때
python3 1_union.py --dir round1/corners --slack-max -0.2815
#   합집합 경로 : 3000개
```

보통은 **(1)** 이 편하다. 위 표에서 문턱값을 읽어 옮겨 적을 필요가 없다.
둘을 같이 주면 둘 다 적용된다(문턱값으로 거른 뒤 개수로 자른다).

### 자르는 시점 — 합친 뒤 vs 합치기 전

| 옵션 | 언제 자르나 |
|---|---|
| `--max-paths N` | **합친 뒤.** 전 코너를 다 본 다음 가장 위험한 N개 |
| `--slack-max V` | 합치기 전(코너별 경로를 문턱값으로 거름) |
| `--per-corner-max N` | **합치기 전. 코너마다** worst N개만 |

`--per-corner-max` 는 리포트가 너무 커서 코너별로 먼저 줄여야 할 때만 쓴다.
**코너마다 자기 기준으로 자르므로, 그 코너 목록에서 밀려난 경로는 다른
코너에서 위험했더라도 합집합에 못 들어온다.**

실측(예제 3코너, 목표 100개):

```
--max-paths 100        경로 100   slack -0.185816 ~ -0.116877
--per-corner-max 100   경로 127   slack -0.185816 ~ -0.107307
  양쪽 공통 100 / per-corner 에만 27
```

`--per-corner-max` 쪽이 27개를 더 담았다. 코너별로 100개씩 뽑다 보니 합치면
100보다 많아지고, 그중에는 전체 기준으로는 덜 위험한 것도 섞인다. 즉
**개수를 정확히 맞추려면 `--max-paths`**, 코너별 상한이 목적이면
`--per-corner-max` 다. 둘을 같이 주면 코너별로 자른 뒤 전체에서 또 자른다.

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

## 값 붙이기 — 묶음 1/2 (셸 ↔ PT)

파이썬이 PT 를 부를 수 없어서 두 토막으로 나뉜다. `--phase` 가 그 번호다.
**중간에 PT 를 한 번만 다녀오면 된다.**

```bash
# 셸
python3 4_all_corners.py --root /data/results/round2 --spef /data/spef/core_25.spef --phase 1
```
```
pt_shell> source /data/results/round2/run_pt_xtalk.tcl
```
```bash
python3 4_all_corners.py --root /data/results/round2 --phase 2
```

`run_pt_xtalk.tcl` 은 **`4_all_corners.py --phase 1` 이 절대경로로 만들어 준다.**
고칠 것이 없고, 화면에 경로가 찍히니 복사만 하면 된다.

### 묶음마다 이 표가 나온다

```
  코너                      2a cpin       2b distres    2c merge      5a contexts
  TT_0p6V_25C             OK-CPIN       OK-DISTRES    OK-MERGE      OK-XCTX
  TT_0p7V_25C             E-NOFILE      -             -             -

  실패한 코너 1개: TT_0p7V_25C
      python3 2a_cpin.py --dir /data/results/round2/TT_0p7V_25C
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

### 5a / 5b / 5c 가 하는 일

crosstalk 14열을 만드는 세 조각이다. 중간에 PT 를 한 번 다녀와야 해서 5a 와 5b
사이가 끊긴다.

| | 하는 일 | 나오는 것 |
|---|---|---|
| **5a** | 리포트를 읽어 **PT 에 뭘 물어볼지** 목록을 만든다. 같은 넷이 여러 경로에 나오므로 중복을 뺀다 | `xtalk/unique_contexts.tsv`, `xtalk/path_victim_nets.tsv` |
| PT (`xtalk_all.tcl`) | 그 넷마다 `report_delay_calculation -crosstalk`, **이어서** 거기서 긁은 aggressor 의 도착시각·slew 까지 | `xtalk/context_raw.rpt`, `xtalk/*_windows.tsv` |
| **5b** | PT 출력을 파싱해 **victim–aggressor 쌍**으로 만든다 | `xtalk/active_features.tsv` |
| **5c** | 위를 합쳐 14열로 쓴다 | `<코너>.path_context_si_compact.by_path.rpt` ★ |

실제 숫자(294경로 기준): victim 넷 줄 8,930 → 물어볼 넷 **788개**(중복 제거) →
쌍 **13,947줄**.

**PT 안에서 무슨 일이 일어나나**

- `report_attribute`(2회차에서 이미 뽑음)로는 **합계**만 나온다.
  "이 넷에 aggressor 151개, coupling cap 합은 얼마".
- 14열은 **하나하나**를 요구한다. "그중 `gre_a_INV_857_152` 가 0.023240 밀었고,
  걔 coupling cap 은 0.315fF". 이건 `report_delay_calculation -crosstalk` 만 안다.
- 그런데 그 aggressor 가 **언제 스위칭하는지**는 안 알려준다. crosstalk 은 victim 과
  aggressor 가 같은 시점에 움직여야 실제 영향이 있으므로 그게 필요하다. aggressor 는
  우리 경로 밖의 남의 넷이라 `pin_attr.txt` 에 없다.
- 그래서 예전에는 PT 1차(계산) → 파이썬(aggressor 이름 추출) → PT 2차(도착시각)
  로 **PT 를 두 번** 다녀왔다. 지금은 `xtalk_all.tcl` 이 **자기가 방금 받은 출력에서
  aggressor 이름을 직접 긁어** 이어서 처리하므로 **한 번이면 된다.**

---

## 한 단계씩 / 일부만 돌리기

`--only` 로 그 묶음 안에서 원하는 단계만 돌린다. 이름은 `2a` `2b` `2c` `5a` `5b` `5c`.

### annotation 만

```bash
python3 4_all_corners.py --root <round2> --spef <SPEF> --phase 1 --only 2a,2b,2c
```
```
생긴 파일:  cpin.tsv  distres.tsv  <코너>_fixed_annotated.txt
```

crosstalk 준비를 건너뛰고 **annotation 만** 나온다. PT 를 더 안 가도 된다.

### crosstalk 만

```bash
python3 4_all_corners.py --root <round2> --phase 1 --only 5a
```

**SPEF 도 `annotated` 도 필요 없다.** crosstalk 14열은 Dist/Res/Cpin 을 쓰지
않으므로 2회차 `.rpt` 만 있으면 된다. SPEF 가 아직 없거나 `2b` 가 오래 걸릴 때
이쪽을 먼저 돌려도 된다.

### 한 단계씩

```bash
python3 4_all_corners.py --root <round2> --spef <SPEF> --phase 1 --only 2a
python3 4_all_corners.py --root <round2> --spef <SPEF> --phase 1 --only 2b
python3 4_all_corners.py --root <round2>                --phase 1 --only 2c
python3 4_all_corners.py --root <round2>                --phase 1 --only 5a
```

순서는 지켜야 한다. `2c` 는 `2a`/`2b` 결과를 합치는 것이고, `5b`/`5c` 는
PT(`xtalk_all.tcl`)를 거쳐야 한다.

```
2a ──┐
     ├──> 2c ──> <코너>_fixed_annotated.txt
2b ──┘

5a ──> [PT: xtalk_all.tcl] ──> 5b ──> 5c ──> 14열 리포트
```

### 중간에 끊겼을 때

```bash
python3 4_all_corners.py --root <round2> --spef <SPEF> --phase 1 --skip-done
```

이미 만들어진 단계는 `SKIP` 으로 건너뛰고 안 된 것만 이어서 한다.
코너 17개 중 12개에서 끊겨도 처음부터 다시 할 필요가 없다.

---

### 코너 하나만 손으로

`4_all_corners.py` 는 아래를 대신 쳐줄 뿐이다. 결과 파일은 바이트 단위로 같다.
한 코너가 실패해서 화면을 자세히 보고 싶을 때 이렇게 한다.

```bash
D=<round2>/<코너>
python3 2a_cpin.py     --dir $D                    # -> cpin.tsv       1초
python3 2b_distres.py  --dir $D --spef <SPEF>      # -> distres.tsv    SPEF 크기에 따라
python3 2c_merge.py    --dir $D                    # -> <코너>_fixed_annotated.txt ★
python3 5a_contexts.py --dir $D                    # -> 물어볼 넷 목록
```
```
pt_shell> cd $D
pt_shell> set XT_DIR "xtalk"                       ;# 결과를 $D/xtalk/ 에 바로
pt_shell> source <패키지>/pt/xtalk_all.tcl         # hold 면 xtalk_all_hold.tcl
```
```bash
python3 5b_pairs.py --dir $D                       # -> 쌍
python3 5c_report.py --dir $D                      # -> <코너>.path_...by_path.rpt ★
```

> `XT_DIR` 을 안 주면 xtalk_all.tcl 은 **PT 에 올라온 db 이름으로** 폴더를
> 만든다 — `$D/<db이름>/xtalk/` (hold 는 `<db이름>_hold/xtalk/`). 한 자리에서
> 코너를 여러 개 돌려도 서로 안 덮어쓰게 하려는 것이다. 그 경우 5b/5c 에는
> `--xtalk $D/<db이름>/xtalk` 을 같이 준다.
>
> 화면 마지막이 `[ OK-XTALK ]` 이면 정상이다. `XT_DIR` 은 세션에 남으므로,
> 다른 코너로 넘어가기 전에 `unset XT_DIR` 하는 것이 안전하다.

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

## setup 과 hold — 완전히 별개 2세트

**섞이면 안 되고, 폴더를 나누는 게 유일한 방법이다.** 산출물 이름이 코너 이름
하나로 정해지므로, 같은 폴더에 두면 서로 덮어쓴다.

```
/data/results/setup/
    round1/corners/*.rpt          report_timing -delay_type max
    round2/<코너>/...
/data/results/hold/
    round1/corners/*.rpt          report_timing -delay_type min
    round2/<코너>/...
```

각 단계에서 바꿀 것:

| 단계 | setup | hold |
|---|---|---|
| 1회차 `report_timing` | `-delay_type max` | `-delay_type min` |
| `1_union.py` | `--mode setup` (기본) | **`--mode hold`** |
| `02_round2_all.tcl` | `FIXED`/`OUTTOP` 을 setup 폴더로 | hold 폴더로 |
| `4_all_corners.py` | `--mode setup` (기본) | **`--mode hold`** |

`1_union.py --mode` 는 생성되는 `fixed_paths.tcl` 의 `set DTYPE` 을 정한다.
이걸 안 주면 hold 리포트로 고른 경로를 **setup 으로 측정**하게 된다.
화면에 어느 쪽인지 찍히니 확인할 것.

```
  분석 : hold  (2회차는 -delay_type min 로 측정)
```

`4_all_corners.py --mode hold` 는 `5b_pairs.py` 와 crosstalk PT 단계의
`DELAY_TYPE` 에 전달된다.

> db/spef 는 setup/hold 와 무관하다. **같은 코너 목록을 그대로 쓰면 된다.**
> 달라지는 것은 `-delay_type` 과 출력 폴더뿐이다.

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
python3 9_diagnose.py --dir <코너폴더>          # Dist/Res 가 빌 때 원인 분류
# 막히면 화면 맨 아래 **코드**(예: W-CPIN)를 그대로 물어보면 된다.
# 코드 목록과 조치는 코드표.md 에 있다.
```

전체 코드 목록은 `코드표.md` (47개), 화면 읽는 법은 `원격문의.md`.

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
5b_pairs.py        crosstalk 2단계 - 쌍 정리  (PT 를 다녀온 뒤)
5c_report.py       crosstalk 3단계 -> 14열 리포트   ★
4_all_corners.py   위를 코너 전부에 (--phase 1/2)
9_diagnose.py      Dist/Res N/A 원인 분류
```

### pt_shell 에서 source 하는 것

```
example/00_setup.tcl        예제용 디자인 로드 (현장에선 안 씀)
example/01_round1.tcl       1회차 예제/템플릿
example/02_round2_all.tcl   2회차 — 코너 전부   ★ 목록을 여기서 고침
example/02_round2.tcl       2회차 — 코너 하나
pt/xtalk_all.tcl            crosstalk PT — 코너 하나, setup(-max)
pt/xtalk_all_hold.tcl       같은 것의 hold(-min) 판
```

**`pt/` 에는 이 두 개만 있다.** 현장 담당자에게 드릴 파일이 그 둘뿐이라
일부러 갈라 뒀다. 그 외 tcl 은 전부 `dev/` 에 있고 **우리가 직접 돌릴 때만**
쓴다 -- 현장에 나가지 않는다.

```
dev/round2_one.tcl          2회차 한 코너 (example/02_round2*.tcl 이 부름)
dev/load_corner.tcl         코너 하나를 PT 에 올리는 부품 (remove_design 부터)
dev/dump_attr.tcl           pin_attr.txt / net_attr.txt 덤프 (Cpin)
dev/all_xtalk_one.tcl       xtalk_all.tcl 을 코너 폴더 전부에 (4_all_corners.py)
dev/make_hold.py            xtalk_all.tcl -> xtalk_all_hold.tcl 재생성
```

`dev/` 는 **직접 열 일이 없다.** `example/*.tcl` 과 `4_all_corners.py` 가
알아서 부른다. 다만 `xtalk_all.tcl` 을 고쳤으면 `python3 dev/make_hold.py` 로
hold 판을 맞춰 줘야 두 파일이 어긋나지 않는다.

### 문서

```
README.md          이 파일. 현장 실행 안내
담당자요청.md      PT 담당자께 드릴 한 장 (무엇을 source 하고 세션에 뭘 하는지)
UNION_설명.md      union 이 하는 일과 결과 읽는 법
코드표.md          에러 코드 47개 전체
원격문의.md        화면 읽는 법, 원격으로 물어볼 때
example/README.md  BoomCoreV3 로 전 과정을 돌려 본 기록
```

---

## 한 번 돌려 보고 가려면

`example/README.md` 에 실제 디자인(BoomCoreV3, 3nm)으로 처음부터 끝까지 돌린
기록이 있다. 숫자까지 그대로 적어 두었으니, 현장에서 나온 숫자와 비교해 보면
된다.
