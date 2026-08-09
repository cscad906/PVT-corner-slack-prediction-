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
$PY 2c_merge.py    --dir $D      # -> annotated.txt
```

정상이면 이렇게 나옵니다.

```
  (net) 줄   : 8930
  3열 다 있음: 8930
  일부 N/A   : 0
  정상 종료           [ OK-MERGE ]
```

`annotated.txt` 는 기존 리포트 오른쪽에 `Dist  Res  Cpin` 세 열이 붙은 것입니다.
**리포트 형식은 그대로**라, 기존 파일들과 같은 방식으로 읽으면 됩니다.

```
  Point                        Fanout   Cap    Trans   Incr    Path      Dist       Res     Cpin
  ZCTSNET_6904 (net)               12 0.023539                        5.7240  488.8332   0.0005
```

단위: `Dist` = µm, `Res` = Ω, `Cpin` = pF.

> 한 번에 하고 싶으면 `$PY 2_annotate.py --dir $D` 로 2a+2b+2c 를 대신할 수
> 있습니다. 나눠 놓은 이유는 어디서 틀어졌는지 보기 위해서입니다.

---

## 6. crosstalk 표

```bash
$PY 3_crosstalk.py --dir $D --corner tt0p7v25c_Cnom
```

```
  경로        : 294
  줄(구간)    : 17860
  넷 속성 매칭: 8930  (못 찾음 0)
  crosstalk 값이 0 이 아닌 줄: 4069
  정상 종료           [ OK-XTALK ]
```

`crosstalk.tsv` 29열. `--corner` 를 주면 맨 앞에 `corner` 열이 붙어,
나중에 코너별 파일을 그냥 이어 붙여도 구분됩니다. 열 설명은
`CROSSTALK_설명.md`.

---

## 7. 코너마다 4~6 반복

PT 쪽은 코너마다 반복입니다.

```
pt_shell> (코너 db 로드: read_db / link_design / update_timing)
pt_shell> (02_round2.tcl 의 CORNER 한 줄을 그 코너 이름으로 고침)
pt_shell> source example/02_round2.tcl
```

**파이썬 쪽은 폴더마다 칠 필요 없습니다.** 코너를 다 뽑아 놓고 한 번만 돌리면
`round2` 아래 폴더를 전부 찾아서 2a → 2b → 2c → 3 을 돌려 줍니다.

```bash
$PY 4_all_corners.py --root example/round2 --spef <SPEF 파일>
```

```
  코너                      2a cpin       2b distres    2c merge      3 crosstalk
  tt0p6v25c_Cnom          OK-CPIN       OK-DISTRES    OK-MERGE      OK-XTALK
  tt0p7v25c_Cnom          OK-CPIN       OK-DISTRES    OK-MERGE      OK-XTALK
  tt0p8v25c_Cnom          OK-CPIN       OK-DISTRES    OK-MERGE      OK-XTALK
```

한 코너가 실패해도 멈추지 않고 끝까지 돈 뒤 이 표를 보여 줍니다. 실패한 칸에
에러 코드가 그대로 찍히니, 그 코너만 따로 돌려 보시면 됩니다.

| 옵션 | 언제 |
|---|---|
| `--spef <파일>` | 모든 코너가 같은 SPEF 를 쓸 때. 폴더에 `design.spef` 가 있으면 그쪽이 우선 |
| `--skip-done` | 중간에 끊겼을 때. 이미 만들어진 단계는 건너뛴다 |
| `--quiet` | 각 단계 화면을 숨기고 결과 표만 |
| `--only 2a,2b` | 일부 단계만 |

`path_idx` 가 코너 사이에 공통이라, 나중에 `corner` + `path_idx` + `arc_idx`
세 개로 한 줄이 특정됩니다.

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
