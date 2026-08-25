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

## 역할이 나뉜다 — 이게 제일 중요하다

| | 누가 | 무엇을 |
|---|---|---|
| **PT** | **담당자분(현장 PT 엔지니어)** | 우리가 드린 tcl 을 pt_shell 에서 `source` |
| **파이썬** | **우리** | 받은 결과를 **현장 서버에서** 후처리 |

**우리는 pt_shell 을 직접 만지지 않는다.** 담당자분께 드리는 것은 tcl 두 개뿐이다.

```
pt/xtalk_all.tcl        setup 용
pt/xtalk_all_hold.tcl   hold 용   (DELAY_TYPE 한 줄만 다르다)
```

그리고 `1_union.py` 가 만들어 주는 `fixed_paths.tcl` 을 같이 드린다.

파이썬은 **현장 서버에서** 돌린다. 연구실로 가져와서 돌리는 것이 아니다.

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

---

## 전체 흐름

**PT 는 총 3번**이다. 다만 2회차와 3회차(crosstalk)는 **같은 pt_shell 세션에서
이어서** 할 수 있으므로, 담당자분이 세션을 여시는 것은 **2번**이면 된다.

```
[PT 1회차]  코너마다 report_timing                 -> round1/corners/<코너>.rpt
[우리]      union — 측정할 경로 결정               -> fixed_paths.tcl
[PT 2회차]  source fixed_paths.tcl                 -> <코너>.rpt
[PT   이어서] source xtalk_all.tcl                 -> <db이름>/xtalk/  (4개)
[우리]      받은 것 검사 -> 후처리 -> 최종 2종
```

`fixed_paths.tcl` 과 `xtalk_all.tcl` 사이에 파이썬이 끼지 않는다. 예전에는
넷 목록을 파이썬으로 만들어 넘겨야 해서 중간에 한 번 나왔어야 했는데, 지금은
`xtalk_all.tcl` 이 리포트를 읽어 **자기가 직접** 목록을 만든다.

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

> 리포트가 너무 커서 union 이 버거우면 `0_trim.py --dir <폴더> --keep N` 으로
> 코너마다 나쁜 것 N개만 남긴 사본을 만들 수 있다. 다만 **코너별로 자르는
> 것**이라 아래 `--per-corner-max` 와 같은 편향이 생긴다.

---

## union — 측정할 경로 결정 (우리)

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

리포트가 크면 `-j`(`--jobs`) 로 코너를 동시에 읽을 수 있다. **결과는 몇을 주든
완전히 같다** — 시간과 메모리만 바뀐다.

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
| `fixed_paths.tcl` | **담당자분께 드릴 파일** |

자세한 설명은 `UNION_설명.md`.

---

## 2회차 + crosstalk — 담당자분께 드리는 부분 (PT)

드리는 파일은 세 개뿐이다.

```
fixed_paths.tcl         union 이 만든 것 (경로 목록)
pt/xtalk_all.tcl        setup
pt/xtalk_all_hold.tcl   hold
```

담당자분은 **코너(db)를 로드한 뒤, 같은 세션에서 이어서** 두 줄을 치신다.

```tcl
pt_shell> source <경로>/fixed_paths.tcl
pt_shell> source <경로>/xtalk_all.tcl        ;# hold 면 xtalk_all_hold.tcl
```

### `xtalk_all.tcl` 이 리포트를 스스로 찾는다 — cd 가 필요 없다

찾는 순서는 이렇다.

1. 파일 맨 위 `RPT_FILE` 에 박아 둔 경로 (비어 있으면 넘어감)
2. **같은 세션의 `OUT` 변수** — `fixed_paths.tcl` 이 남겨 둔 것. 보통 여기서 잡힌다
3. 지금 폴더의 `*.rpt` 중 **첫 줄이 `### FIXED_PATH` 로 시작**하는 것

셋 다 실패하면 `E-NORPTFILE` 로 멈춘다. 위처럼 두 줄을 이어서 치면 2번에서
잡히므로 `cd` 할 일이 없다.

### 결과가 어디에 쌓이나 — 로드된 db 이름으로 갈린다

`xtalk_all.tcl` 은 `link_path` 에서 db 이름을 뽑아 그 이름으로 폴더를 만든다.

```
<db이름>/xtalk/          setup
<db이름>_hold/xtalk/     hold
```

**같은 자리에서 코너를 여러 개 돌려도 서로 안 덮어쓴다.** 화면 마지막이
`[ OK-XTALK ]` 이면 정상이다.

> `fixed_paths.tcl` 쪽은 사정이 다르다. 리포트 이름을 `set CORNER [file tail [pwd]]`
> 로 **지금 폴더 이름**에서 가져온다. 그래서 코너마다 이름이 갈리려면
> 코너별 폴더에서 돌리시거나, `fixed_paths.tcl` 맨 위 `set CORNER` 한 줄을
> 코너 이름으로 고치셔야 한다. 화면에 `이번 코너 : <이름> -> <이름>.rpt` 가
> 찍히니 거기서 확인할 수 있다.

담당자분께 그대로 보내 드릴 한 장은 `담당자요청.md` 다.

---

## 받는 것 — 코너마다 이 네 덩어리

| | 무엇 |
|---|---|
| `<코너>.rpt` | `fixed_paths.tcl` 산출물 |
| `xtalk/` | 파일 4개 — `unique_contexts.tsv`, `context_raw.rpt`, `victim_windows.tsv`, `aggressor_windows.tsv` |
| **Cpin 표** | 담당자분이 PT 로 뽑아 주신 2열 이상 표 (예: `핀이름  pin_cap  wire_cap`, 띄어쓰기 구분, 헤더 없음) |
| SPEF | 현장에 이미 있다 |

### Cpin 은 코너마다 다르다 — 한 표를 돌려 쓰면 안 된다

0.6V 와 0.8V 를 실측해 보면 **중앙값 5.95%, 최대 8.27%** 차이가 난다.
788개 중 값이 같은 것은 **176개뿐**이다. 코너별로 받아서 각 폴더에 두는 것이 맞다.

---

## 폴더를 이렇게 둔다

```
round2/<코너>/<코너>.rpt
round2/<코너>/cpin_map.txt      <- 받은 Cpin 표를 이 이름으로
round2/<코너>/xtalk/            <- 받은 4개
```

`cpin_map.txt` 라는 **이름은 우리가 정한 규약**이다. 이 이름으로 만들어 주는
코드는 없다 — 받은 파일을 그 이름으로 두면 배치가 알아서 집는다는 뜻이다
(SPEF 의 `design.spef` 와 같은 방식).

코너마다 SPEF 가 다르면 코너 폴더에 `design.spef` 로 둔다. 그러면 `--spef` 보다
그쪽이 우선한다.

---

## 우리가 돌리는 것 — 네 줄

```bash
python3 8_check_xtalk.py --root round2                          # 받은 것 검사
python3 4_all_corners.py --root round2 --phase 1   # 2a 2b 2c  (annotation, SPEF 불필요)
python3 4_all_corners.py --root round2 --phase 2   # 5a 5b 5c  (crosstalk)
python3 6_collect.py     --root round2 --out deliver --mode setup
```

hold 는 **작업 폴더를 따로 두고** 같은 네 줄에 `--mode hold` 를 붙인다
(`4_all_corners.py` 와 `6_collect.py` 에). `8_check_xtalk.py` 는 setup/hold 를
PT 원문에서 자동 판별하므로 붙일 필요가 없다.

### 8 — 받은 것 검사 (먼저 한다)

```bash
python3 8_check_xtalk.py --root round2
```

받은 폴더 아래에서 이름이 `xtalk` 인 폴더를 **전부** 찾아 한 번에 본다.
setup 과 hold 가 섞여 있어도 알아서 갈라 본다. **읽기만 하고 아무것도 안 고친다.**

코너마다 보는 것:

- 파일 4개가 다 있고 비어 있지 않은가
- **어느 전압으로 계산됐는가** (PT 원문에 찍힌 VDD)
- **setup 인가 hold 인가** (원문의 `Annotated max/min`)
- crosstalk 이 실제로 잡혔는가 (delta 가 0 이 아닌 넷 수)
- victim/aggressor 도착시각이 채워졌는가

그리고 코너끼리 비교한다. **같은 분석 안에서 전압이 코너마다 다른가** — 같으면
코너를 바꿔 놓고 db 를 안 갈아 끼운 것이다. 화면에는 정상으로 뜨고 값만 틀리는
경우라 제일 잡기 어렵다. 이 검사가 그것을 잡으라고 있는 것이다.

### 4 — 코너 전부 후처리

```bash
python3 4_all_corners.py --root round2 --phase 1
python3 4_all_corners.py --root round2 --phase 2
```

`--phase 1` 이 `2a → 2b → 2c`(annotation), `--phase 2` 가 `5a → 5b → 5c`(crosstalk) 다.
두 묶음은 서로 독립이라 순서를 바꿔도 된다. PT 는 둘 사이가 아니라 **둘 다보다 앞**에
있다 — 담당자분이 이미 돌려 주신 것이다.
(묶음이 나뉘어 있는 것은 원래 그 사이에 PT 가 끼던 흔적이다. 지금은 crosstalk
계산이 현장에서 이미 끝나 있으므로 **두 줄을 연달아 치면 된다.**)

> `--phase 1` 과 `--phase 2` 는 서로 독립이다. 어느 쪽을 먼저 돌려도 되고,
> 한쪽이 막혀도 다른 쪽은 나온다.

묶음마다 이 표가 나온다.

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
| `--cpin-map <파일>` | 코너들이 같은 Cpin 표를 쓸 때. 폴더에 `cpin_map.txt` 가 있으면 그쪽 우선. **코너별로 받았으면 폴더에 두는 쪽이 맞다** |
| `--skip-done` | **중간에 끊겼을 때.** 이미 만든 단계는 건너뛴다 |
| `--quiet` | 화면을 숨기고 결과 표만 |
| `--only 2a,2b` | 그 묶음 안에서 일부만 |
| `--mode hold` | hold 데이터를 만들 때 (5b 에 전달) |

### 6 — 넘길 형태로 모으기

```bash
python3 6_collect.py --root round2 --out deliver --mode setup
```

작업 폴더에는 중간 파일(`cpin.tsv`, `distres.tsv`, `xtalk/...`)이 잔뜩 남는데,
넘길 때 필요한 것은 두 종류뿐이다. 그것만 아래 형태로 모은다.
**원본은 건드리지 않고 복사만 한다**(`--move` 를 주면 옮긴다).

```
deliver/setup/report.<코너>_fixed_annotated.rpt
deliver/setup/xtalk/xt.<코너>.path_context_si_compact.by_path.rpt
deliver/hold/   (같은 구조. --mode hold 로 한 번 더)
```

파일 이름의 코너는 **코너 폴더 이름**을 그대로 쓴다. 모아 놓고 보면 어느 코너인지가
이름뿐이라 여기서 통일해 둔다.

### 7 — 경로 개수를 줄이기 (필요할 때만)

```bash
python3 7_cut.py --root round2 --keep 300
python3 6_collect.py --root round2_top300 --out deliver --mode setup
```

다 나온 뒤에 "역시 300개면 충분하다" 가 될 때 쓴다. `1_union.py --max-paths` 는
**2회차를 돌리기 전에** 정하는 것이라 이 시점에는 못 쓴다(PT 를 다시 부탁드릴 수
없다). 그래서 **나온 파일을 그대로 자른다.**

- 자르는 단위는 `### FIXED_PATH` 블록이고, **파일에 나온 순서대로 앞에서 N개**다.
  그 순서가 1회차 worst_slack 나쁜 것부터라, 앞 N개 = 제일 위험한 N개다.
- **번호(`idx <= N`)로 자르지 않는다.** 현장 리포트는 idx 가 1부터 시작하지 않거나
  중간이 비기도 한다(PT 가 그 경로를 못 잡으면 그 번호가 빠진다). 번호로 걸면
  N개보다 적게 남는다. 순서로 세면 idx 가 어떻게 생겼든 항상 N개가 나온다.
- 결과는 `<root>_top<N>/` 에 **코너 폴더 구조와 파일 이름 그대로** 만든다.
  그래서 그대로 `6_collect.py --root` 에 넣으면 된다. **원본은 안 건드린다.**
- 두 산출물(annotation, crosstalk)을 같이 자른다. `fixed_paths.tcl` 도 자를 수 있다.

화면에 `idx kept` 열로 실제로 남은 번호 범위가 찍힌다. `3..8 (-2)` 는 3번부터
8번까지인데 그 사이에 2개가 비었다는 뜻이다. 코너끼리 남은 번호 집합이 다르면
`W-IDXDIFF` 로 알린다 — 그러면 코너 간 짝이 어긋나므로 넘기기 전에 봐야 한다.
`measured` 열은 그중 **경로가 실제로 담긴** 블록 수다. 이보다 적으면 PT 가 못 잡은
빈 블록이 섞여 있다는 뜻이고 `W-EMPTY` 가 뜬다.

---

## Cpin 표 — 2a 가 알아서 판별한다

담당자분마다 뽑아 주시는 표 모양이 다르다. `2a_cpin.py` 는 **1열이 뭔지**와
**어느 열이 Cpin 인지**를 리포트와 대조해 스스로 정한다.

### 1열 판별

| 1열이 이것이면 | 예 | 어떻게 |
|---|---|---|
| 설계 핀 (`inst/pin`) | `U123/A` | 그대로 쓴다 |
| 셀의 핀 (`cell/pin`) | `gt3_6t_and2_x1_rvt/A` | 리포트로 펼쳐 쓴다 |
| lib 핀 (`lib/cell/pin`) | `op_cond_all/..._x1_rvt/A` | 앞을 떼고 펼쳐 쓴다 |
| **셀 이름만** | `gt3_6t_and2_x1_rvt` | **멈춘다** |
| **넷 이름** | `ZCTSNET_4157` | **멈춘다** |

뒤의 둘에서 멈추는 것은 **핀 구분이 없어 조용히 틀린 값이 들어가기** 때문이다.
Cpin 은 핀마다 다르다. 실측하면 80%는 그대로였지만 상위 10%가 1.6%, 최악은
146% 틀렸다.

앞의 셋은 셋 다 **byte 단위로 같은** `cpin.tsv` 가 나온다 (BoomCoreV3 로 확인).

### 값 열 판별

`pin_cap` 과 `wire_cap` 이 같이 있어도, 순서가 어느 쪽이어도 된다.
리포트의 `(net)` 줄에 그 넷의 **전체** cap 이 찍혀 있는데, Cpin 은 리시버
하나 몫이라 그보다 작아야 한다. 열마다 그 비율을 재서 제일 높은 열을 쓴다.

```
  값 열 : 2번째 (자동 선택, 넷 전체 cap 보다 작은 비율 100%)
      3번째 열은 12% -- 안 씀
```

먼저 앞 300개만 보고, 열이 확연히 안 갈리면 전체로 다시 센다.
직접 정하려면 `--cpin-col N` (이름 열이 1).

### 담당자분께 부탁드릴 PT 명령

```tcl
# (가) 설계 핀 -- 제일 정확. 핀 수만큼 나온다
foreach_in_collection p [get_pins -hierarchical *] {
    puts "[get_object_name $p]\t[get_attribute -quiet $p pin_capacitance_max]"
}

# (나) 라이브러리 핀 -- 훨씬 작다(셀 종류 수). 값은 (가)와 같다
foreach_in_collection p [get_lib_pins *] {
    puts "[get_object_name $p]\t[get_attribute -quiet $p pin_capacitance]"
}
```

lib_pin 에서는 attribute 이름이 `pin_capacitance` 다. `capacitance` 나
`pin_capacitance_max` 는 빈 값으로 나온다(실측).

---

## crosstalk 과 annotation 은 서로 독립이다

한쪽이 막혀도 다른 쪽은 나온다. 기다릴 필요가 없다.

| | 쓰는 입력 | 안 쓰는 것 |
|---|---|---|
| **annotation** (2a/2b/2c) | `<코너>.rpt` + Cpin 표 + SPEF | `xtalk/` 를 안 본다 |
| **crosstalk** (5a/5b/5c) | `<코너>.rpt` + `xtalk/` 4개 | Dist/Res/Cpin 을 안 쓴다 |

crosstalk 쪽은 annotated 파일이 있으면 그것을 쓰지만 없으면 원본 `.rpt` 로도
같은 결과가 나온다(byte 동일 확인). 그래서 SPEF 가 아직 없거나 `2b` 가 오래
걸릴 때 crosstalk 을 먼저 돌려도 된다.

```bash
# annotation 만 (PT 결과의 xtalk/ 가 아직 없어도 된다)
python3 4_all_corners.py --root round2 --phase 1

# crosstalk 만 (SPEF 도 Cpin 표도 필요 없다)
python3 4_all_corners.py --root round2 --phase 2
```

---

## 5a / 5b / 5c 가 하는 일

crosstalk 14열을 만드는 세 조각이다.

| | 하는 일 | 나오는 것 |
|---|---|---|
| **5a** | 리포트를 읽어 **경로별 victim 넷 + 구간**을 만든다. `unique_contexts.tsv` 는 만들지 않는다 — 그건 담당자분 쪽 산출물이라 덮으면 안 된다 | `xtalk/path_victim_nets.tsv` |
| PT (`xtalk_all.tcl`) | **현장에서 이미 끝나 있다.** 그 넷마다 `report_delay_calculation -crosstalk`, **이어서** 거기서 긁은 aggressor 의 도착시각·slew 까지 | `xtalk/context_raw.rpt`, `xtalk/*_windows.tsv` |
| **5b** | PT 출력을 파싱해 **victim–aggressor 쌍**으로 만든다 | `xtalk/active_features.tsv` |
| **5c** | 위를 합쳐 14열로 쓴다 | `<코너>.path_context_si_compact.by_path.rpt` ★ |

받아 온 폴더에 `unique_contexts.tsv` 가 이미 들어 있는데도 5a 를 도는 이유는
**`path_victim_nets.tsv` 때문**이다. 5c 가 그것을 쓰는데 담당자분 쪽 산출물에는
없다(PT 는 경로 개념이 없어서 안 만든다).

**5a 는 `unique_contexts.tsv` 를 만들지 않는다.** 그건 PT 가 만들어 준 것이고,
"PT 가 실제로 무엇을 물어봤는지" 를 담은 유일한 기록이다. 덮어쓰면 그 기록이
사라진다. 5b 가 그 파일을 읽지만, 받은 것을 그대로 읽는다.

실제 숫자(294경로 기준): victim 넷 줄 8,930 → 물어볼 넷 **788개**(중복 제거) →
쌍 **13,947줄**.

**PT 안에서 무슨 일이 일어나나**

- `report_attribute` 로는 **합계**만 나온다. "이 넷에 aggressor 151개, coupling cap
  합은 얼마".
- 14열은 **하나하나**를 요구한다. "그중 `gre_a_INV_857_152` 가 0.023240 밀었고,
  걔 coupling cap 은 0.315fF". 이건 `report_delay_calculation -crosstalk` 만 안다.
- 그런데 그 aggressor 가 **언제 스위칭하는지**는 안 알려준다. crosstalk 은 victim 과
  aggressor 가 같은 시점에 움직여야 실제 영향이 있으므로 그게 필요하다. aggressor 는
  우리 경로 밖의 남의 넷이라 리포트에 없다.
- 그래서 예전에는 PT 1차(계산) → 파이썬(aggressor 이름 추출) → PT 2차(도착시각)
  로 **PT 를 두 번** 다녀와야 했다. 지금은 `xtalk_all.tcl` 이 **자기가 방금 받은
  출력에서 aggressor 이름을 직접 긁어** 이어서 처리하므로 **한 번이면 된다.**
  담당자분이 세션을 두 번만 여시면 되는 것이 이 덕이다.

---

## 한 단계씩 / 일부만 돌리기

`--only` 로 그 묶음 안에서 원하는 단계만 돌린다. 이름은 `2a` `2b` `2c` `5a` `5b` `5c`.

```bash
python3 4_all_corners.py --root <round2> --phase 1 --only 2a
python3 4_all_corners.py --root <round2> --phase 1 --only 2b
python3 4_all_corners.py --root <round2>                --phase 1 --only 2c
python3 4_all_corners.py --root <round2>                --phase 2 --only 5a
```

순서는 지켜야 한다. `2c` 는 `2a`/`2b` 결과를 합치는 것이고, `5b`/`5c` 는
`xtalk/context_raw.rpt` (담당자분 산출물)가 있어야 한다.

```
2a ──┐
     ├──> 2c ──> <코너>_fixed_annotated.txt
2b ──┘

5a ──> [받은 xtalk/] ──> 5b ──> 5c ──> 14열 리포트
```

### 중간에 끊겼을 때

```bash
python3 4_all_corners.py --root <round2> --phase 1 --skip-done
```

이미 만들어진 단계는 `SKIP` 으로 건너뛰고 안 된 것만 이어서 한다.
코너 17개 중 12개에서 끊겨도 처음부터 다시 할 필요가 없다.

### 코너 하나만 손으로

`4_all_corners.py` 는 아래를 대신 쳐줄 뿐이다. 결과 파일은 바이트 단위로 같다.
한 코너가 실패해서 화면을 자세히 보고 싶을 때 이렇게 한다.

```bash
D=<round2>/<코너>
python3 2a_cpin.py     --dir $D --cpin-map $D/cpin_map.txt   # -> cpin.tsv     1초
python3 2b_distres.py  --dir $D --spef <SPEF>                # -> distres.tsv  SPEF 크기에 따라
python3 2c_merge.py    --dir $D                              # -> <코너>_fixed_annotated.txt ★
python3 5a_contexts.py --dir $D                              # -> 물어볼 넷 목록 + 경로별 victim
python3 5b_pairs.py    --dir $D                              # -> 쌍
python3 5c_report.py   --dir $D                              # -> <코너>.path_...by_path.rpt ★
```

> 받은 `xtalk` 폴더가 코너 폴더 바로 아래가 아니라 `<db이름>/xtalk` 처럼 한 겹
> 더 들어가 있으면, 5a/5b/5c 에 `--xtalk <그 폴더 절대경로>` 를 같이 준다.
> hold 면 5b 에 `--mode hold` 도.

---

## SPEF 대신 표를 받아 쓸 때 — 2b_distres_table.py

SPEF 를 직접 못 뽑는 사이트에서, **상대(기업 등)가 계산해 준 표**로 Dist/Res 를 채운다.
`2b_distres.py` 자리에 그대로 끼운다. 출력이 같은 `distres.tsv` 라서 `2c_merge.py` 부터는
아무것도 안 바뀐다.

```bash
D=round2/TT_0p8V_25C
python3 2b_distres_table.py --dir $D                      # -> distres.tsv
python3 2c_merge.py         --dir $D                      # 이하 동일

# 코너 전부에 한 번에 (묶음 1 이 이미 이 방식이다)
python3 4_all_corners.py --root round2 --phase 1
```

### 받은 표를 어디에 어떤 이름으로 두나

`2a` 의 `cpin_map.txt` 와 같은 규약이다. **코너 폴더 안에 두 개**를 둔다.

| 파일 | 열 |
|---|---|
| `res_map.txt` | `넷 이름 / res` |
| `dist_map.txt` | `넷 이름 / dist` |

넷 이름으로 둘을 합쳐서 쓴다. 한쪽에만 있는 넷은 그쪽 값만 채우고 나머지는 `N/A` 로
남는다 — 조용히 0 을 넣지 않고, 몇 개가 그런지 화면에 찍는다.

```
round2/TT_0p8V_25C/
  TT_0p8V_25C.rpt      리포트 (원래 있던 것)
  cpin_map.txt         받은 Cpin 표   -> 2a
  res_map.txt          받은 Res 표    -> 2b     ★ 이 두 개
  dist_map.txt         받은 Dist 표   -> 2b     ★
```

**코너 폴더마다 하나씩 있어야 한다.** `cpin_map.txt` 와 같다.

Res 는 온도에 따라 달라지므로, 그 코너의 온도에 맞는 표를 그 폴더에 둔다.
전압으로는 안 변하니 같은 온도의 코너들에는 같은 내용이 들어간다.

각각 **2열**이면 된다.

```
res_map.txt                    dist_map.txt
  n57401     11.1137             n57401      7.3315
  clock      51.5246             clock     131.1135
```

파일이 갈려 있어 어느 값인지 이름이 말해 주므로 순서를 헷갈릴 일이 없다.

헤더가 붙어 오면 열 이름으로 찾으므로 열이 더 있어도 되고 순서가 달라도 된다
(`resistance`, `length` 같은 이름도 알아본다). 없으면 두 번째 열을 값으로 본다. 구분자는
공백/탭/쉼표/세미콜론/파이프 중에서 알아서 고르고, `#`/`//` 주석줄과 빈 줄은
건너뛴다.

단위가 다르면 `--res-scale` / `--dist-scale` 로 맞춘다. 코드는 안 고쳐도 된다.

### 열 3개면 절반 가까이가 부정확하다

Dist/Res 는 **드라이버 핀에서 그 리시버 핀까지**의 값인데, 넷 이름만 키로 쓰면 넷 하나에
값이 하나뿐이다. 리시버가 여럿인 넷은 그 줄들이 전부 같은 값을 받는다.

| 표의 열 구성 | SPEF 계산값과 일치 |
|---|---|
| `net_name res dist` | 79.5% (example/round2/TT_0p8V_25C 기준) |
| `net_name driver_pin receiver_pin res dist` | **100%** |

그래서 **driver/receiver 핀 열 2개를 더** 달라고 하는 게 좋다. 열 이름에
driver/receiver(또는 drv/recv/load/sink)가 들어 있으면 자동으로 핀 쌍 키로 바꿔 쓴다.
핀 표기는 리포트와 같은 `인스턴스/핀` 형식이어야 한다.
3열로 받아도 돌아가긴 한다 — 대신 영향 받는 줄 수를 `W-NETKEY` 로 매번 알려준다.

### 표가 몇 개 필요한가

- **Dist 는 표 1개면 된다.** 배치 좌표라 전압·온도·RC 코너가 바뀌어도 안 변한다.
- **Res 는 온도마다 표가 따로 있어야 한다.** 실측으로 25C→125C 에서 전 넷이 +39%,
  -40C→125C 에서 +86% 움직인다 (`R(T) = R(0C) x (1 + 0.00432 x T)`, 구리 TCR 0.43%/도).
  한 개만 받아 돌려 쓰면 배선 RC 의 온도 의존성이 사라진다.
- **전압별로는 필요 없다.** 배선 RC 는 전원 전압과 무관해서 값이 전혀 안 변한다.
- RC 코너(Cmin/Cnom/Cmax)별로도 받으면 좋지만 우선순위는 낮다 — 실측상 83% 의 넷이
  코너 간 저항 차이 0.1% 미만이다.

### 검증한 것

`example/round2/TT_0p8V_25C` 의 SPEF 산출물에서 표를 역으로 만들어 이 경로로 다시 돌린 결과,
핀 열이 있는 표에서는 `<코너>_fixed_annotated.txt` 가 원본과 **바이트 단위로 같았다**
(8,930 (net) 줄, `OK-DISTRES` → `OK-MERGE`).

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
| 담당자분이 source 할 tcl | `pt/xtalk_all.tcl` | **`pt/xtalk_all_hold.tcl`** |
| `4_all_corners.py` | `--mode setup` (기본) | **`--mode hold`** |
| `6_collect.py` | `--mode setup` | **`--mode hold`** |

`1_union.py --mode` 는 생성되는 `fixed_paths.tcl` 의 `set DTYPE` 을 정한다.
이걸 안 주면 hold 리포트로 고른 경로를 **setup 으로 측정**하게 된다.
화면에 어느 쪽인지 찍히니 확인할 것.

```
  분석 : hold  (2회차는 -delay_type min 로 측정)
```

`xtalk_all.tcl` 은 같은 세션의 `DTYPE` 과 자기 `DELAY_TYPE` 이 다르면 화면에
경고를 띄운다(값을 몰래 바꾸지는 않는다). setup 용 tcl 을 hold 세션에서 돌리면
거기서 걸린다.

hold 결과 폴더는 `<db이름>_hold/xtalk/` 로 갈리므로, 담당자분이 같은 자리에서
setup 과 hold 를 연달아 돌리셔도 안 섞인다.

> db/spef 는 setup/hold 와 무관하다. **같은 코너 목록을 그대로 쓰면 된다.**
> 달라지는 것은 `-delay_type` 과 출력 폴더뿐이다.

---

## 코너 구성이 바뀔 때

| 바뀌는 것 | 고칠 곳 |
|---|---|
| 경로 선정 코너 | 1회차 `.rpt` 를 `round1/corners/` 에 넣느냐 마느냐 |
| 측정 코너 (hidden 포함) | 담당자분이 로드하실 db 목록. 우리 쪽에 고칠 것 없음 |
| 경로 개수 | `1_union.py --max-paths` / `--slack-max` |

**파이썬 코드는 손댈 일이 없다.** 코너가 몇 개든 `--root` 아래 폴더를 전부 돈다.

---

## 막혔을 때

화면 마지막 블록의 **`하실 일`** 을 먼저 한다. 안 되면 **`에러 코드` 하나만**
전달하면 된다. 원격(핸드폰)으로 물어볼 때 타자를 아끼려고 이렇게 만들어 두었다.

```
==================================================================
  문제 발생
    무엇이   : SPEF 에서 저항(Res)을 하나도 못 구했습니다
    하실 일  : SPEF 가 이 리포트와 같은 디자인/코너인지 확인해 주세요.

    에러 코드: E-RES0
==================================================================
```

**화면 맨 아래 코드만 물어보면 된다.** 예를 들어 `W-CPIN` 이나 `E-NORPTFILE`
하나만 보내면 어느 단계에서 무엇이 막혔는지 정해진다. 코드 목록과 조치는
`코드표.md` (47개), 화면 읽는 법은 `원격문의.md`.

`W-` 는 파일은 나왔지만 데이터가 불완전한 경우다. **몇 퍼센트인지**가 중요하다.

### N/A 가 남았을 때 — 어느 쪽인지 2c 가 갈라 준다

```
  [Cpin]      1,204줄 -- 리시버 핀이 Cpin 표에 없습니다
  [Dist/Res]     37줄 -- SPEF 에서 못 찾았습니다
```

조치할 곳이 다르다.

| | 어디를 보나 |
|---|---|
| `[Cpin]` | 받은 Cpin 표. 담당자분의 `get_pins` 범위가 좁았거나, 표가 다른 코너 것 |
| `[Dist/Res]` | SPEF. 리포트와 짝이 맞는지, `*RES` 가 들어 있는지 |

SPEF 쪽을 **넷 단위로 더 잘게** 보고 싶을 때만 따로 돌린다.

```bash
python3 9_diagnose.py --dir <코너폴더> --spef <SPEF>
```

원인 A(넷이 SPEF 에 없음) / B(이름 표기가 다름) / C(`*RES` 없음) / D(Cpin 만 빔)
으로 갈라 개수와 조치를 찍는다. 2c 는 SPEF 를 다시 훑지 않아 빠르고, 9 는
훑으므로 느리다.

### PT 쪽에서 미리 확인할 것

```
pt_shell> printvar si_enable_analysis      # false 면 crosstalk 이 전부 0
```

SPEF 에 coupling 이 있어야 한다 (`read_parasitics -keep_capacitive_coupling`,
StarRC `COUPLING_CAP: YES`). grounded SPEF 면 crosstalk 결과가 무의미하다.
`xtalk_all.tcl` 도 `si_enable_analysis` 가 꺼져 있으면 화면에 경고를 띄운다.

---

## 파일 목록

### 우리가 셸에서 돌리는 것

```
0_check.py         환경/입력 점검. 처음에 한 번 (파이썬 2.7 로도 돌아간다)
0_trim.py          리포트가 너무 클 때 코너마다 worst N개만 남긴 사본
1_union.py         코너 합치기 -> fixed_paths.tcl               ★ 담당자분께 드림
8_check_xtalk.py   받은 crosstalk 결과 검사 (읽기만 한다)
2a_cpin.py         Cpin        (SPEF 안 읽음, 1초)
2b_distres_table.py  Dist/Res  (받은 표를 읽음)          ★ 지금 쓰는 것
2b_distres.py      Dist/Res    (SPEF 읽음. 예전 방식)
2c_merge.py        -> <코너>_fixed_annotated.txt                ★
5a_contexts.py     경로별 victim 넷 + PT 에 물어볼 넷 목록
5b_pairs.py        받은 PT 출력에서 victim-aggressor 쌍
5c_report.py       -> 14열 리포트                                ★
4_all_corners.py   위를 코너 전부에 (--phase 1 / 2)
6_collect.py       최종 2종만 넘길 형태로 모으기
9_diagnose.py      N/A 원인을 넷 단위로 분류 (필요할 때만)
```

### 담당자분께 드리는 tcl — 이 두 개뿐

```
pt/xtalk_all.tcl        crosstalk PT — 코너 하나, setup(-max)
pt/xtalk_all_hold.tcl   같은 것의 hold(-min) 판
```

여기에 `1_union.py` 가 만든 `fixed_paths.tcl` 을 같이 드린다.
**`pt/` 에 이 두 개만 둔 것은 일부러다** — 현장에 나가는 파일이 그 둘뿐이라
섞이지 않게 갈라 뒀다.

### 우리 내부용 — 현장에 안 나간다

```
dev/round2_one.tcl          2회차 한 코너
dev/load_corner.tcl         코너 하나를 PT 에 올리는 부품 (remove_design 부터)
dev/dump_attr.tcl           pin_attr.txt / net_attr.txt 덤프 (Cpin 을 우리가 뽑을 때)
dev/all_xtalk_one.tcl       xtalk_all.tcl 을 코너 폴더 전부에 (우리가 PT 를 돌릴 때)
dev/make_hold.py            xtalk_all.tcl -> xtalk_all_hold.tcl 재생성
example/*.tcl               예제용 (BoomCoreV3 로 전 과정을 우리가 돌려 본 것)
debug/why_dropped.py        union 에서 경로가 왜 빠졌는지
```

`xtalk_all.tcl` 을 고쳤으면 `python3 dev/make_hold.py` 로 hold 판을 맞춰 줘야
두 파일이 어긋나지 않는다.

### 예시 폴더

```
example/final_output_example/   최종 산출물 2종 (annotated + 14열). 앞부분만 잘라 둔 것
example/xtalk_output_example/   담당자분께 받는 xtalk/ 4개. 앞부분만
```

### 문서

```
README.md          이 파일. 현장 실행 안내
담당자요청.md      PT 담당자께 드릴 한 장 (무엇을 source 하고 세션에 뭘 하는지)
UNION_설명.md      union 이 하는 일과 결과 읽는 법
코드표.md          결과 코드 전체 목록
원격문의.md        화면 읽는 법, 원격으로 물어볼 때
example/README.md  BoomCoreV3 로 전 과정을 돌려 본 기록
```

---

## 한 번 돌려 보고 가려면

`example/README.md` 에 실제 디자인(BoomCoreV3, 3nm)으로 처음부터 끝까지 돌린
기록이 있다. 숫자까지 그대로 적어 두었으니, 현장에서 나온 숫자와 비교해 보면
된다. 다만 그 기록은 **우리가 PT 까지 직접 돌리던 때**의 것이라, 2회차와
crosstalk 을 우리가 `example/*.tcl` 로 도는 형태로 적혀 있다. 숫자와 파일 형식은
그대로 유효하고, 누가 PT 를 치느냐만 지금과 다르다.
