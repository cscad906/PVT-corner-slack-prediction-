# example — 처음부터 끝까지 한 번 돌려 보기

**실제 디자인(BoomCoreV3, 3nm)으로 전 과정을 돌려 본 예제**입니다.
여기 있는 3개의 `.tcl` 을 순서대로 실행하면 `report_timing` 부터
14열 crosstalk 리포트까지 전부 나옵니다. 검증된 흐름이므로, 현장에서는 이 순서를
그대로 따라가면서 **경로와 코너 이름만** 자기 것으로 바꾸면 됩니다.

전체 소요: PT 약 5분 + 파이썬 약 30초.

---

## 0. 준비 — 파이썬 정하기

```bash
cd <이 패키지 폴더>
python3 0_check.py --dir .
```

화면에 **어떤 파이썬을 쓸지** 나옵니다. `python3` 을 쓰라고 하면 그대로,
전체 경로가 나오면 그 경로를 명령 앞에 붙여 쓰시면 됩니다.

> 시스템 `python3` 이 2.7 이나 3.6 이어도 상관없습니다. `0_check.py` 가
> PT 안에 들어 있는 3.6 을 찾아 줍니다.
> 각 단계가 끝날 때 다음 명령이 경로까지 통째로 찍히니 복사만 하시면 됩니다.

---

## 1. PT 띄우고 디자인 읽기

```
pt_shell
pt_shell> source example/00_setup.tcl
```

`00_setup.tcl` 은 **1회차(2번)에만 필요합니다.** 2회차부터는 `02_round2*.tcl`
이 코너마다 알아서 db 를 읽으므로 안 씁니다.

---

## 2. 1회차 — 코너마다 경로 뽑기

```
pt_shell> source example/01_round1.tcl
```

`example/round1/corners/` 아래에 코너별 `.rpt` 가 생깁니다.

**현장에서는 코너(db)를 바꿔 로드할 때마다 아래 한 줄만 반복**하면 됩니다.
파일 이름이 곧 코너 이름이 되므로 알아볼 수 있게 지으세요.

```tcl
redirect -file round1/corners/<코너이름>.rpt {
  report_timing -delay_type max -path_type full_clock_expanded \
    -nets -input_pins -nosplit -significant_digits 6 \
    -nworst 3 -max_paths 3000 -slack_lesser_than 0.05
}
```

- `-nets -input_pins -nosplit -path_type full_clock_expanded` 이 **네 개는 빼면 안 됩니다.**
- `-slack_lesser_than` : 위반 + 위반 위험을 어디까지 볼지. 기본 0.05(=50ps).
- hidden 코너는 **이 폴더에 넣지 마세요.** 2회차에서는 측정만 하면 됩니다.

---

## 3. 합집합 — 어느 코너에서든 위험했던 경로 모으기

셸(pt_shell 아님)에서:

```bash
python3 1_union.py --dir example/round1/corners
```

```
  코너                     리포트   사용   제외
  tt0p6v25c_Cnom             300    300      0
  tt0p7v25c_Cnom             200    200      0
  tt0p8v25c_Cnom             120    120      0

  합집합 경로 : 294개
  한 코너에서만 나온 경로 : 94   <- 합집합이 필요한 이유
  모든 코너에 나온 경로   : 120
```

세 파일이 생깁니다.

| 파일 | 용도 |
|---|---|
| `union_summary.txt` | **vi 로 읽는 용도.** 경로별로 어느 코너에서 몇 ns 였는지 |
| `union_paths.tsv` | 같은 내용, 나중에 스크립트로 처리할 때 |
| `fixed_paths.tcl` | **2회차에서 PT 가 읽을 파일** |

---

## 4. 2회차 — 합집합 경로를 코너마다 다시 측정

**코너 목록을 적어두고 한 번에 돕니다.** `02_round2_all.tcl` 위쪽의 목록만
자기 것으로 바꾸면 됩니다.

```tcl
set CORNERS {}
lappend CORNERS [list TT_0p6V_25C "$L/TT_0p6V_25C_op_cond_all.db" "$S/boomcorev3_25.spef"]
lappend CORNERS [list TT_0p7V_25C "$L/TT_0p7V_25C_op_cond_all.db" "$S/boomcorev3_25.spef"]
lappend CORNERS [list TT_0p8V_25C "$L/TT_0p8V_25C_op_cond_all.db" "$S/boomcorev3_25.spef"]
```

| 칸 | 뜻 |
|---|---|
| 코너이름 | 폴더 이름이자 산출물 파일 이름. **db 이름과 맞추는 게 안전** |
| db | **이게 코너를 결정합니다** (전압/온도/공정) |
| spef | 배선 RC. **온도만** 맞추면 됩니다 (전압/공정과 무관) |

```
pt_shell> source example/02_round2_all.tcl
```

코너마다 db 를 새로 읽고(30초) 측정합니다(30초). 결과:

```
[1/3] TT_0p6V_25C
        db   : TT_0p6V_25C_op_cond_all.db
        spef : boomcorev3_25.spef
  측정된 경로   : 294
  pin_attr.txt  <- 핀 1347 개
        기록   : .../TT_0p6V_25C/corner_info.tcl

코너별 결과 (2회차)
  TT_0p6V_25C                    OK
  TT_0p7V_25C                    OK
  TT_0p8V_25C                    OK
```

코너 폴더마다 네 개가 생깁니다.

```
<코너>.rpt          294 경로 (1회차에서 뽑은 그 경로들, 번호 동일)
pin_attr.txt        Cpin, arrival, slew
net_attr.txt        crosstalk delta, aggressor, coupling cap
corner_info.tcl     ★ 무슨 db/spef 로 만들었는지 기록
```

### `corner_info.tcl` 이 왜 중요한가

crosstalk 단계(`xtalk_all.tcl`)는 **나중에 따로 돕니다.** 그때 이 폴더가 어느 db 로
만들어졌는지 알아야 같은 db 로 다시 로드할 수 있습니다.

이게 없으면 처음 로드된 db 하나로 모든 코너를 계산해 버립니다. **값은 나오고
화면엔 `OK` 로 뜹니다** — 제일 나쁜 실패라, 없으면 아예 건너뛰도록 해 두었습니다.

```
[2/3] TT_0p7V_25C
  corner_info.tcl 이 없습니다. 이 코너는 건너뜁니다.
  (어느 db 로 만든 폴더인지 알 수 없어, 틀린 값을 만들지 않으려고 멈춥니다)
```

### 코너 하나만 다시 볼 때

`02_round2.tcl` 은 코너 하나짜리입니다. 위쪽 세 줄(`CORNER` / `CI_DB` /
`CI_SPEF`)만 바꿔서 쓰세요.

---

## 5. 열 붙이기 — Dist / Res / Cpin

SPEF 를 그 폴더에 `design.spef` 라는 이름으로 놓거나 링크합니다.

```bash
ln -s <SPEF 파일> example/round2/<코너>/design.spef

python3 0_check.py     --dir $D      # 입력이 다 있는지 먼저 확인
python3 2a_cpin.py     --dir $D      # -> cpin.tsv      (약 1초)
python3 2b_distres.py  --dir $D      # -> distres.tsv   (SPEF 크기에 따라 10초~2분)
python3 2c_merge.py    --dir $D      # -> <코너>_fixed_annotated.txt
```

정상이면 이렇게 나옵니다.

```
  (net) 줄   : 8930
  3열 다 있음: 8930
  일부 N/A   : 0
  정상 종료           [ OK-MERGE ]
```

`<코너>_fixed_annotated.txt` 는 기존 리포트 오른쪽에 `Dist  Res  Cpin` 세 열이 붙은 것입니다.
**리포트 형식은 그대로**라, 기존 파일들과 같은 방식으로 읽으면 됩니다.

```
  Point                        Fanout   Cap    Trans   Incr    Path      Dist       Res     Cpin
  ZCTSNET_6904 (net)               12 0.023539                        5.7240  488.8332   0.0005
```

단위: `Dist` = µm, `Res` = Ω, `Cpin` = pF.

> 코너 전부를 한 번에 하려면 `python3 4_all_corners.py --root <round2> --phase 1`
> 로 2a+2b+2c+5a 를 대신할 수 있습니다. 단계를 나눠 놓은 이유는 어디서 틀어졌는지
> 보기 위해서입니다.

---

## 6. crosstalk 14열 리포트

모델이 읽는 crosstalk 파일은 **victim-aggressor 쌍 하나가 한 줄**인 14열
리포트입니다. 이건 `report_attribute` 로는 안 나오고
`report_delay_calculation -crosstalk` 을 넷마다 돌려야 나옵니다.
그래서 PT 를 한 번 더 지나갑니다.

```bash
python3 5a_contexts.py --dir $D      # -> PT 에 물어볼 넷 목록 (중복 제거)
```
```
pt_shell> cd $D
pt_shell> set XT_DIR "xtalk"                 ;# 결과를 $D/xtalk/ 에 바로
pt_shell> source <패키지>/pt/xtalk_all.tcl   # 약 1분. 끝에 [ OK-XTALK ]
```
```bash
python3 5b_pairs.py --dir $D         # -> 쌍 13,947줄
python3 5c_report.py --dir $D        # -> <코너>.path_context_si_compact.by_path.rpt
```

`xtalk_all.tcl` 이 넷마다 crosstalk 을 계산하고, **거기서 나온 aggressor 이름을
그 자리에서 긁어** 그 넷들의 도착시각·slew 까지 이어서 뽑습니다. aggressor 는
**우리 경로 밖의 남의 넷**이라 `pin_attr.txt` 에 없고, crosstalk 은 victim 과
aggressor 가 같은 시점에 움직여야 실제 영향이 있으므로 그 도착시각이 필요합니다.
예전에는 이 두 가지 때문에 PT 를 두 번 다녀왔지만, 지금은 한 번이면 됩니다.

> `XT_DIR` 을 안 주면 결과가 **PT 에 올라온 db 이름**으로 `$D/<db이름>/xtalk/`
> 에 떨어집니다(hold 는 `<db이름>_hold/xtalk/`). 그 경우 5b/5c 에
> `--xtalk $D/<db이름>/xtalk` 을 같이 주면 됩니다.

---

## 7. 코너마다 반복 — 손으로 vs 묶어서

PT 쪽 2회차는 코너마다 해야 합니다.

```
pt_shell> (코너 db 로드: read_db / link_design / update_timing)
pt_shell> (02_round2.tcl 의 CORNER 한 줄을 그 코너 이름으로 고침)
pt_shell> source example/02_round2.tcl
```

그다음은 **코너를 다 뽑아 놓고 묶어서** 돌리는 게 편합니다. 터미널 왕복이
코너 수와 상관없이 3번으로 끝납니다.

```bash
# 셸
python3 4_all_corners.py --root example/round2 --spef <SPEF> --phase 1
```
```
# pt_shell — 화면에 찍힌 파일을 그대로 source (고칠 것 없음)
pt_shell> source example/round2/run_pt_xtalk.tcl
```
```bash
python3 4_all_corners.py --root example/round2 --phase 2
```

`run_pt_xtalk.tcl` 은 `--phase 1` 이 **자동으로 만들어 줍니다.**
절대경로가 이미 박혀 있어 고칠 것이 없습니다.

### 묶어도 디버깅은 그대로

`4_all_corners.py` 는 **하위 스크립트를 대신 쳐줄 뿐**입니다. 새로 계산하는 게
없고 결과 파일도 바이트 단위로 같습니다(md5 확인). 그래서

- `--quiet` 을 안 주면 각 스크립트 화면이 **그대로** 흘러갑니다
- 끝에 **코너 x 단계 표**가 붙어 어디서 틀어졌는지 한눈에 보입니다
- 한 코너가 실패해도 **나머지는 계속 돕니다**
- `--skip-done` 으로 끊긴 데서 이어서 할 수 있습니다

```
  코너                      2a cpin       2b distres    2c merge      5a contexts
  tt0p6v25c_Cnom          OK-CPIN       OK-DISTRES    OK-MERGE      OK-XCTX
  tt0p7v25c_Cnom          E-NOFILE      -             -             -

  실패한 코너 1개: tt0p7v25c_Cnom
      python3 2a_cpin.py --dir example/round2/tt0p7v25c_Cnom
```

문제가 난 코너는 **그 한 줄만 따로 돌리면** 평소와 똑같은 자세한 화면이
나옵니다. PT 쪽도 마찬가지로 그 코너 폴더로 `cd` 해서 `xtalk_all.tcl` 을 직접
source 하면 됩니다(hold 는 `xtalk_all_hold.tcl`).

### 코너마다 나오는 학습 입력 두 개

**이름은 기존 운영 산출물과 같은 규약**입니다. 코너 폴더 이름이 앞에 붙습니다.

```
<코너>_fixed_annotated.txt                     Dist/Res/Cpin 이 붙은 리포트
<코너>.path_context_si_compact.by_path.rpt     crosstalk 14열
```

운영 쪽 실제 파일과 비교하면:

```
운영  saed14rvt_tt0p6v25c_ccs_full387_nldmrx_fixed_annotated.txt
우리  tt0p6v25c_Cnom_fixed_annotated.txt

운영  TT_0p605V_125C.path_context_si_compact.by_path.rpt
우리  tt0p6v25c_Cnom.path_context_si_compact.by_path.rpt
```

앞부분(코너 이름)만 다릅니다. **운영 파일과 글자까지 똑같이 맞춰야 하면 코너
폴더를 그 이름으로 지으면 됩니다** (`02_round2.tcl` 의 `CORNER` 줄).

`path_idx` 가 코너 사이에 공통이라, 나중에 코너 이름 + `path_idx` 로 한 경로가
특정됩니다.

---

## 막히면

화면 마지막 블록의 **`하실 일`** 을 먼저 해 보세요. 안 되면 `에러 코드`(예:
`E-RES0`)만 알려주시면 됩니다. 전체 목록은 `코드표.md`, 화면 읽는 법은
`원격문의.md`.

그래도 안 풀리면:

```bash
# 막히면 화면 맨 아래 코드(예: W-CPIN)를 코드표.md 에서 찾는다
```
