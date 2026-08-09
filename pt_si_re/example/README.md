# example — 처음부터 끝까지 한 번 돌려 보기

**실제 디자인(BoomCoreV3, 3nm)으로 전 과정을 돌려 본 예제**입니다.
여기 있는 3개의 `.tcl` 을 순서대로 실행하면 `report_timing` 부터
`crosstalk.tsv` 까지 전부 나옵니다. 검증된 흐름이므로, 현장에서는 이 순서를
그대로 따라가면서 **경로와 코너 이름만** 자기 것으로 바꾸면 됩니다.

전체 소요: PT 약 5분 + 파이썬 약 30초.

---

## 0. 준비 — 파이썬 정하기

```bash
cd <이 패키지 폴더>
python3 0_check.py --dir .
```

화면에 `setenv PY ...` 한 줄이 나옵니다. 그대로 복사해서 실행하세요.
이후 모든 명령에서 `python3` 대신 **`$PY`** 를 씁니다.

```csh
setenv PY /usr/synopsys/pt/V-2023.12-SP4/etc/Python/bin/python3
```

> 시스템 `python3` 이 2.7 이나 3.6 이어도 상관없습니다. `0_check.py` 가
> PT 안에 들어 있는 3.6 을 찾아 줍니다.

---

## 1. PT 띄우고 디자인 읽기

```
pt_shell
pt_shell> source example/00_setup.tcl
```

`00_setup.tcl` 이 하는 일 — 넷리스트/라이브러리/SDC/SPEF 를 읽고
`si_enable_analysis true` 를 켠 뒤 `update_timing` 까지 합니다.

> **현장에서는 이 파일을 안 씁니다.** PT 세팅은 다른 분이 해 두므로,
> 이미 올라와 있는 pt_shell 에 2번부터 입력하면 됩니다.
> 다만 `si_enable_analysis` 가 켜져 있는지는 확인하세요 (`printvar si_enable_analysis`).
> 꺼져 있으면 crosstalk 값이 전부 0 으로 나옵니다.

---

## 2. 1회차 — 코너마다 경로 뽑기

```
pt_shell> source example/01_round1.tcl
```

`example/round1/corners/` 아래에 코너별 `.rpt` 가 생깁니다.

```
tt0p6v25c_Cnom.rpt   300 경로
tt0p7v25c_Cnom.rpt   200 경로
tt0p8v25c_Cnom.rpt   120 경로
```

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
  하나라도 빠지면 뒤에서 `E-NOPATH` / `E-NONET` / `W-DROP` 이 뜹니다.
- `-slack_lesser_than` : 위반 + 위반 위험을 어디까지 볼지. 기본 0.05(=50ps).
- hidden 코너(경로 선정에서 빼고 싶은 코너)는 **이 폴더에 넣지 마세요.**
  2회차에서는 측정만 하면 됩니다.

---

## 3. 합집합 — 어느 코너에서든 위험했던 경로 모으기

셸(pt_shell 아님)에서:

```bash
$PY 1_union.py --dir example/round1/corners
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

```
pt_shell> source example/02_round2.tcl
```

`example/round2/tt0p7v25c_Cnom/` 에 세 파일이 생깁니다.

```
tt0p7v25c_Cnom.rpt   294 경로   (1회차에서 뽑은 그 경로들, 순서·번호 동일)
pin_attr.txt         Cpin, arrival, slew
net_attr.txt         crosstalk delta, aggressor, coupling cap
```

**리포트 이름은 코너 이름이 됩니다.** 폴더만 봐도 어느 코너인지 알 수 있고,
다른 곳으로 옮겨도 섞이지 않습니다. 뒤 파이썬 스크립트들은 폴더 안의 `.rpt`
를 알아서 찾으므로 이름을 신경 쓸 필요가 없습니다 (`.rpt` 가 여러 개면
`E-RPTMANY` 로 멈추고 골라 달라고 합니다).

끝에 이렇게 나오면 정상입니다.

```
  요청한 경로   : 294
  측정된 경로   : 294
```

두 숫자가 다르면 그만큼 실패한 것입니다. **0 이면 대개 디자인을 안 읽은
것**이고 (`E-NODESIGN` / `E-NOMEASURED`), 1번을 먼저 하셔야 합니다.

**코너를 바꿔 가며 반복할 때는 `02_round2.tcl` 의 `CORNER` 한 줄만** 바꾸면
됩니다. 스크립트가 그 이름으로 폴더를 만들고 `cd` 한 뒤 두 tcl 을 그대로
source 합니다 (두 tcl 모두 "지금 폴더" 기준이라 고칠 것이 없습니다).

```tcl
set CORNER "tt0p6v25c_Cnom"     ;# <- 이 줄만. 폴더 이름이자 리포트 이름이 된다
```

> **이름과 db 를 반드시 맞추세요.** 코드는 둘이 맞는지 알 방법이 없습니다.
> db 는 0.7V 인데 이름을 `tt0p6v25c_Cnom` 으로 두면, 그 이름으로 0.7V 데이터가
> 저장되고 **나중에 알아낼 방법이 없습니다.** 실행하면 맨 위에
> `이번 코너 : <이름>  ->  <이름>.rpt` 가 찍히니 그때 한 번 더 확인하세요.

여기서는 **hidden 코너도 포함해 전부** 돌립니다. 경로 선정에서만 뺐을 뿐,
측정은 해야 하니까요.

---

## 5. 열 붙이기 — Dist / Res / Cpin

SPEF 를 그 폴더에 `design.spef` 라는 이름으로 놓거나 링크합니다.

```bash
setenv D example/round2/tt0p7v25c_Cnom
ln -s <SPEF 파일> $D/design.spef

$PY 0_check.py     --dir $D      # 입력이 다 있는지 먼저 확인
$PY 2a_cpin.py     --dir $D      # -> cpin.tsv      (약 1초)
$PY 2b_distres.py  --dir $D      # -> distres.tsv   (SPEF 크기에 따라 10초~2분)
$PY 2c_merge.py    --dir $D      # -> <코너>_fixed_annotated.txt
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

> 한 번에 하고 싶으면 `$PY 2_annotate.py --dir $D` 로 2a+2b+2c 를 대신할 수
> 있습니다. 나눠 놓은 이유는 어디서 틀어졌는지 보기 위해서입니다.

---

## 6. crosstalk 14열 리포트

모델이 읽는 crosstalk 파일은 **victim-aggressor 쌍 하나가 한 줄**인 14열
리포트입니다. 이건 `report_attribute` 로는 안 나오고
`report_delay_calculation -crosstalk` 을 넷마다 돌려야 나옵니다.
그래서 PT 를 두 번 더 지나갑니다.

```bash
$PY 5a_contexts.py --dir $D      # -> PT 에 물어볼 넷 목록 (중복 제거)
```
```
pt_shell> cd $D
pt_shell> source <패키지>/pt/xtalk_calc.tcl      # PT 1차, 약 30초
```
```bash
$PY 5b_pairs.py --dir $D         # -> 쌍 13,947줄
```
```
pt_shell> cd $D
pt_shell> source <패키지>/pt/xtalk_windows.tcl   # PT 2차, 약 30초
```
```bash
$PY 5c_report.py --dir $D        # -> <코너>.path_context_si_compact.by_path.rpt
```

PT 2차가 따로 필요한 이유: aggressor 는 **우리 경로 밖의 남의 넷**이라
`pin_attr.txt` 에 없습니다. crosstalk 은 victim 과 aggressor 가 같은 시점에
움직여야 실제 영향이 있으므로 그 도착시각이 필요합니다.

---

## 7. 코너마다 반복 — 손으로 vs 묶어서

PT 쪽 2회차는 코너마다 해야 합니다.

```
pt_shell> (코너 db 로드: read_db / link_design / update_timing)
pt_shell> (02_round2.tcl 의 CORNER 한 줄을 그 코너 이름으로 고침)
pt_shell> source example/02_round2.tcl
```

그다음은 **코너를 다 뽑아 놓고 묶어서** 돌리는 게 편합니다. 터미널 왕복이
코너 수와 상관없이 5번으로 끝납니다.

```bash
# 셸
$PY 4_all_corners.py --root example/round2 --spef <SPEF> --phase 1
```
```
# pt_shell — 화면에 찍힌 파일을 그대로 source (고칠 것 없음)
pt_shell> source example/round2/run_pt1_xtalk_calc.tcl
```
```bash
$PY 4_all_corners.py --root example/round2 --phase 2
```
```
pt_shell> source example/round2/run_pt2_xtalk_windows.tcl
```
```bash
$PY 4_all_corners.py --root example/round2 --phase 3
```

`run_pt*.tcl` 두 개는 `4_all_corners.py` 가 **자동으로 만들어 줍니다.**
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
      $PY 2a_cpin.py --dir example/round2/tt0p7v25c_Cnom
```

문제가 난 코너는 **그 한 줄만 따로 돌리면** 평소와 똑같은 자세한 화면이
나옵니다. PT 쪽도 마찬가지로 그 코너 폴더에서 `xtalk_calc.tcl` 을 직접
source 하면 됩니다.

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
$PY 8_snapshot.py --dir $D          # 상황 100줄 요약
$PY 9_diagnose.py --dir $D          # Dist/Res 가 빌 때 원인 분류
```
