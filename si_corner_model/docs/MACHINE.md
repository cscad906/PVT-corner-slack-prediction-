# 회사 장비에서 돌리기 (RHEL8 / LSF·xterm 할당 / python 경로 명시)

로그인 노드에서 바로 돌리지 않는다. 장비를 할당받아 그 안에서 돌린다.
파이썬도 `python3` 만 치면 2.7 이거나 numpy 가 없을 수 있어서 **경로를 명시**한다.

이 문서는 그 두 가지만 다룬다. 무엇을 왜 돌리는지는
[START.md](START.md), 설정은 [CONFIG.md](CONFIG.md).

---

## 1. 장비 할당

```bash
ub_sub -rhel 8 -cpu 16 xterm
```

새 xterm 이 뜨면 **그 창 안이 할당받은 장비**다. 이후 모든 작업은 그 창에서 한다.

들어가서 확인:

```bash
hostname                 # 로그인 노드와 다른 이름이어야 한다
nproc                    # 16 이 나와야 한다
free -g | head -2        # 쓸 수 있는 메모리 (아래 §5 에서 필요)
cd <이 repo 가 있는 곳>/si_corner_model
```

> **xterm 을 닫으면 그 안에서 돌던 것도 같이 죽는다.** 학습은 몇 시간 걸리므로
> §6 의 `nohup` 방식으로 띄운다.

---

## 2. 파이썬 찾기

```bash
sh scripts/find_python.sh
```

후보를 전부 훑어서 표로 보여주고, 쓸 것을 골라준다:

```
  interpreter                                    version    numpy    pyyaml   torch
  /usr/bin/python3                               3.6.10     1.19.5   5.3.1    1.10.2
  /usr/synopsys/pt/V-2023.12-SP4/etc/Python/bin/python3   3.6.10  1.19.5  5.3.1  1.10.2

 [ ALL OK ] use this one, training included:
     env PY=/usr/bin/python3 bash scripts/run.sh all
```

필요 조건은 이렇다:

| | 필요한 것 | 되는 단계 |
|---|---|---|
| 최소 | python ≥ 3.6 + numpy + pyyaml | `recon` `check` `list` `build` `base` |
| 추가 | torch | `train` `predict` (CPU 로 충분, GPU 불필요) |

torch 가 없어도 **데이터 확인과 OLS base 점검까지는 다 된다.** 거기까지 먼저
돌려보고 파싱이 맞는지 확인한 뒤 학습으로 넘어가는 게 안전하다.

찾은 경로를 아래에서 계속 쓴다. 여기서는 `/usr/bin/python3` 로 적는다.

---

## 3. 파이썬 경로를 지정하는 세 가지 방법

`scripts/run.sh` 는 `PY` 환경변수를 보고, 없으면 `python3` 을 쓴다.
그래서 **경로만 알려주면 되고 파일을 고칠 필요는 없다.**

### ① 매번 앞에 붙이기 (제일 안전)

```bash
env PY=/usr/bin/python3 bash scripts/run.sh list
```

### ② 세션에 한 번만 지정

셸에 따라 문법이 다르다. `echo $SHELL` 로 확인한다.

```bash
# bash / zsh
export PY=/usr/bin/python3
bash scripts/run.sh list

# csh / tcsh
setenv PY /usr/bin/python3
bash scripts/run.sh list
```

> **csh/tcsh 에서 `PY=... bash ...` 접두 문법은 안 먹는다.** 그 형태는 bash/zsh
> 전용이다. `setenv` 를 먼저 하거나 ①의 `env` 를 쓴다.

### ③ 셔뱅(`#!`)으로 박아두기

"인터프리터 경로를 `#!` 에 명시하고 실행하라"는 지시가 있으면 이 방법을 쓴다.
`scripts/run.sh` 첫 줄은 지금 이렇게 되어 있다:

```bash
#!/usr/bin/env bash
```

이건 **bash** 의 셔뱅이지 파이썬이 아니다. 이 파일은 파이썬 스크립트가 아니라
`$PY -m si_model.run` 을 부르는 얇은 껍데기이므로, 파이썬 경로는 셔뱅이 아니라
`PY` 로 준다. 그래도 굳이 한 파일로 만들어 쓰고 싶으면 이렇게 감싼다:

```bash
cat > run_here.sh <<'EOF'
#!/usr/bin/env bash
export PY=/usr/bin/python3
exec bash scripts/run.sh "$@"
EOF
chmod +x run_here.sh
./run_here.sh list
```

파이썬을 직접 부르고 싶다면 `run.sh` 를 건너뛰고 이렇게 해도 완전히 같다:

```bash
/usr/bin/python3 -m si_model.run list
/usr/bin/python3 -m si_model.run build --design MFC_Timing_Report --temp 125
```

이때는 **반드시 `si_corner_model/` 안에서** 실행한다 (`-m` 이 패키지를 그 위치에서
찾는다).

---

## 4. 실행 순서

> **셸 변수를 쓰지 말 것.** `P="env PY=..."` 같은 축약은 bash 전용이라 csh/tcsh
> 에서는 안 풀리고, `$P` 가 그대로 파이썬까지 넘어가 `unrecognized argument $`
> 로 죽는다. 아래처럼 **매번 전부 적는 쪽**이 어느 셸에서도 안전하다.

```
env PY=/usr/bin/python3 bash scripts/run.sh recon   # ① 데이터 정찰 -> recon_out.txt
env PY=/usr/bin/python3 bash scripts/run.sh check   # ② 리포트 하나를 파서에 통과
env PY=/usr/bin/python3 bash scripts/run.sh list    # ③ 뭐가 돌지 확인 (파일 안 건드림)
env PY=/usr/bin/python3 bash scripts/run.sh build   # ④ 리포트 -> cache/.../dataset.npz
env PY=/usr/bin/python3 bash scripts/run.sh base    # ⑤ OLS base 오차만 (수 초, torch 불필요)
env PY=/usr/bin/python3 bash scripts/run.sh train   # ⑥ 학습 (몇 시간, §5)
env PY=/usr/bin/python3 bash scripts/run.sh bundle
env PY=/usr/bin/python3 bash scripts/run.sh predict
env PY=/usr/bin/python3 bash scripts/run.sh merge
```

매번 치기 싫으면 셸에 한 번 등록한다 (그러면 `env PY=...` 를 빼고 쓴다):

```csh
setenv PY /usr/bin/python3          # csh / tcsh
bash scripts/run.sh list
```
```bash
export PY=/usr/bin/python3          # bash / zsh
bash scripts/run.sh list
```

`all` 은 ④~⑨ 를 한 번에 돈다. 처음에는 **한 단계씩** 돌려 각 단계 출력을 확인하는
편이 낫다.

### 단계마다 꼭 볼 것

> **다시 돌릴 때 파싱을 반복하지 않는다.** `run.sh all` 은 `dataset.npz` 가
> 모든 리포트와 `config.yaml` 보다 새것이면 build 를 건너뛴다(`[SKIP]` 이 찍힌다).
> 학습이 죽어서 `all` 을 다시 돌려도 몇 시간짜리 파싱을 되풀이하지 않는다.
>
> **`run.sh build` 를 직접 부르면 항상 다시 만든다.** 데이터가 바뀌었다고 판단하는
> 건 사람이지 타임스탬프가 아니므로, 새로 뽑은 리포트를 덮어썼다면 이쪽을 쓴다.
> `all` 안에서도 강제하려면 `SI_REBUILD=1`.

| 단계 | 봐야 할 줄 | 이상하면 |
|---|---|---|
| `check` | `verdict: OK` | `MISS` 인 정규식의 '실제' 줄을 보고 [PARSING.md §4](PARSING.md) |
| `list` | `corners : total N = seen S + hidden H` | seen/hidden 이 의도와 다르면 [HOLDOUT.md](HOLDOUT.md) |
| `build` | `[CELLS]` `[NETS]` `[XT]` `[KEYS]` `[PATHS]` | 아래 참조 |
| `build` | `wrote ... dataset.npz: N=... C=...` | 이 줄이 나와야 그 모델이 저장된 것 |
| `base` | `[hidden mean] X ps` + weighting 비교표 | base 가 터무니없으면 파싱부터 의심 |
| `train` | `E<n> ... val-hidden` 이 줄어드는지 | |

**`[PATHS]` 의 남은 경로 수를 반드시 본다.**

```
[PATHS] keeping only paths measured at every corner: 33282 -> 7375 (dropped 25907)
```

경로는 **모든 코너에서 측정된 것만** 남는다. 한 코너에서만 실패해도 그 경로는
전체에서 빠진다. 3만 개가 몇 천 개로 줄면 코너마다 실패한 경로가 다르다는 뜻이고,
리포트를 다시 뽑아야 한다.

그 외 진단 줄:

```
[CELLS] ... SAED14 taxonomy covers 100% -- using it      셀 이름 규칙 (자동)
[NETS]  N of M net rows have no Dist/Res/Cpin            BEOL 값 누락 비율
[XT]    N of M numeric fields were N/A -> 0.0            크로스토크 N/A 비율
[KEYS]  ... only in the annotated report -- dropped      annotated/crosstalk 짝 정리
```

`[NETS]` 나 `[XT]` 가 20% 를 넘으면 경고 문구가 붙는다. 그러면 추출을 확인한다.

---

## 4.5 화면에 뭐가 나오나 (그리고 다 보고 싶을 때)

기본은 **조용**하다. 모델 6개를 도는 동안 화면이 수치로 덮이지 않게, 진행과
최종 결과만 남긴다.

```
[ 1/8] SSPG_0p5V_cmax: paths=3000 si_stages=0        <- build 진행
[MEM] corner 1/8   anon 0.20 GB ...                  <- 메모리 궤적
E  1/40 loss=  207.27  lr=1.3e-03 *                  <- 학습 진행 (* = 저장됨)
E  2/40 loss=  218.36  lr=2.0e-03

=== hidden-corner results (best epoch 25) ===
  [all paths] model 0.97 ps (worst 1.20)             <- 통합 결과
  NOTE: the epoch was selected on these corners ...   <- 편향 경고
```

`base` 단계의 OLS 수치와 학습 중 `val-seen` / `val-hidden` / 코너별 성적은
**화면에서만** 빠진다. 전부 파일에 남는다:

| 무엇 | 어디에 |
|---|---|
| 코너별 모델 오차 · SI 오차 | `runs/<mode>/<회로>/<온도>/summary.json` 의 `by_corner` |
| 전체 통합 코너 표 | `runs/<mode>/_all/summary.json` (코너 단위. 모델별 분할은 없다) |
| train/val/test 별 요약, best epoch | 같은 파일 |
| 경로별 예측 (사람이 읽는 것) | `runs/<mode>/_all/predict_<온도>_hidden.rpt` |
| 홀드아웃 코너 리포트 (사람이 읽는 것) | `runs/<mode>/_all/predict_<온도>_hidden.rpt` |

### 설정은 `config.yaml` 의 `run:` 에 있다

```yaml
run:
  verbose: false      # 수치를 다 볼지
  rebuild: false      # all 안에서 build 를 강제할지
  memlog: true        # [MEM] 추적
```

**환경변수가 파일을 이긴다** — 그 실행에만 바꾸고 싶을 때 쓴다:

| 환경변수 | config 키 | 하는 일 |
|---|---|---|
| `SI_VERBOSE=1` | `run.verbose` | OLS·학습 수치 전부 표시 |
| `SI_REBUILD=1` | `run.rebuild` | `all` 안에서도 build 강제 |
| `SI_MEMLOG=0` | `run.memlog` | `[MEM]` 추적 끄기 |
| `SI_MODE=hold` | `mode` | setup/hold (`--mode` 와 같음) |
| `SI_ROOT=/경로` | `root` | 데이터 위치 |
| `SI_DESIGNS=a,b` | `designs` | 그 회로만 |

### 다 보고 싶으면

```csh
env SI_VERBOSE=1 bash scripts/run.sh all
```

한 번에 되살아나는 것:

- `[BASIS]` 후보 표 (차수 후보 전부와 각각의 seen-LOO)
- `[BASE]` / `[BASE-ADAPTIVE]` 진단
- `base` 단계의 코너별 오차와 weighting 비교표
- 학습 중 `val-seen` · `val-hidden` · `si` 수치
- 마지막 코너별 성적

`base` 만 따로 부르면 `SI_VERBOSE` 없이도 전부 나온다 — 그게 그 단계의 목적이다:

```csh
bash scripts/run.sh base --design MFC_Timing_Report --temp 125
```

---

## 5. 시간과 메모리 (16코어 실측)

경로 3만 개, 코너 8개(seen 6), 스레드 16개로 잰 값이다:

```
데이터 적재 + base       35 초
1 epoch (평가 포함)      526 초 ≈ 8.8 분
40 epoch                 약 5.8 시간
메모리 최대              6.3 GB
```

**epoch 시간은 seen 코너 수에 비례한다** — 학습이 seen 코너마다 전체 경로를 돌기
때문이다. 위 값을 코너 수로 환산하면:

| 모델 | seen 코너 | 40 epoch |
|---|---|---|
| seen 6 | 6 | 5.8 시간 |
| seen 8 | 8 | 7.8 시간 |
| seen 10 | 10 | 9.7 시간 |
| seen 12 | 12 | 11.7 시간 |
| seen 17 | 17 | 16.6 시간 |

`run.sh list` 의 `seen S` 를 보고 위 표로 어림잡으면 된다.

### 스레드 수를 명시할 것

torch 는 CPU 에서 OpenMP/MKL 로 병렬화한다 — 행렬 연산 하나를 여러 스레드로
쪼개는 방식이고, 학습 루프 자체(코너 하나씩, 배치 하나씩)는 순차다.

문제는 **스레드 수를 장비 전체 코어 수에서 잡는다**는 점이다. 16코어를 할당받아도
장비가 112코어면 56개를 띄워 서로 방해한다. 할당받은 만큼만 쓰게 못 박는다:

```csh
setenv OMP_NUM_THREADS 16
setenv MKL_NUM_THREADS 16
```

병렬이 실제로 먹는지는 `[MEM]` 의 `cpu / wall` 비율로 본다. 16코어면 그 비율이
10 언저리면 정상이고, 1 에 가까우면 병렬이 안 되고 있는 것이다.

### 줄이는 방법 (효과 순)

1. **`epochs: 40` → `30`** — 최고점이 대체로 E22~E26 이라 손해가 거의 없고 25% 단축
2. `model.enc_dim: 128 → 48`, `model.enc_blocks: 3 → 2` — 추가 30~40% 단축

> **모델을 동시에 여러 개 띄우지 말 것.** 16코어에서 3개를 띄우면 각각 16스레드를
> 잡아 48스레드가 16코어를 두고 다투고, 메모리도 3배가 된다. 하나씩 순차가 빠르다.
> 굳이 동시에 하려면 `OMP_NUM_THREADS` 를 나눠 준다 (2개면 8씩).

**메모리는 모델당 6.3 GB 다.** 동시에 3개면 약 19 GB 가 필요하니 `free -g` 로
먼저 확인한다.

---

## 6. 몇 시간짜리 작업 띄우기

xterm 을 닫아도 죽지 않게 `nohup` 으로 띄우고 로그를 남긴다.

**리다이렉트 문법이 셸마다 다르다.** csh/tcsh 에 `2>&1` 은 없고 `>&` 를 쓴다 —
bash 문법을 그대로 치면 `ambiguous output redirect` 가 난다.

```csh
# csh / tcsh   -- 한 번에 하나씩. 끝나면 다음 것을 띄운다 (§5 참고)
setenv OMP_NUM_THREADS 16
nohup env PY=/usr/bin/python3 bash scripts/run.sh train --design MFC_Timing_Report --temp 125 >& log.mfc.125 &
```
```bash
# bash / zsh
nohup env PY=/usr/bin/python3 bash scripts/run.sh train \
      --design MFC_Timing_Report --temp 125 > log.mfc.125 2>&1 &
```

셸이 헷갈리면 `bash` 를 한 번 치고 들어가서 아래쪽 문법으로 통일하는 게 편하다.

진행 상황 보기:

```bash
tail -f log.mfc.125                       # 실시간
grep -E '^E ' log.mfc.125 | tail -5       # 최근 epoch 5개
jobs                                       # 이 셸에서 띄운 것
ps -u $USER -o pid,etime,args | grep si_model.run    # 전부
```

멈추기:

```bash
kill <PID>
```

> **학습을 중간에 끊어도 된다.** `best.pt` 는 매 epoch, 히든 성적이 좋아질 때만
> 덮어쓰므로 마지막 개선 지점이 남아 있다. 이어서 `bundle` → `predict` → `merge`
> 를 돌리면 된다. 단 **`build` 는 모델이 끝날 때 한 번에 저장**하므로 중간에
> 끊으면 그 모델의 `dataset.npz` 는 생기지 않는다.

---

## 7. setup / hold

한 번에 못 섞는다. 그 실행에만 적용하려면 파일을 고치지 말고 `--mode` 를 쓴다:

```bash
env PY=/usr/bin/python3 bash scripts/run.sh all --mode hold
env SI_MODE=hold PY=/usr/bin/python3 bash scripts/run.sh all    # 같은 뜻
```

읽는 폴더와 쓰는 폴더가 **함께** 바뀌므로 setup 결과를 덮어쓸 일이 없다.
config 의 `mode` 를 직접 고쳐도 되지만, 되돌리는 걸 잊으면 다음 setup 실행이
hold 폴더를 읽게 된다.

---

## 8. 결과가 어디에 있나

```
si_corner_model/
├── cache/<mode>/<회로>/<온도>/dataset.npz     build 산출물
└── runs/<mode>/
    ├── <회로>/<온도>/best.pt                  학습된 가중치
    ├── <회로>/<온도>/summary.json             성적
    ├── <회로>/<온도>/predictions_hidden.npz   경로별 예측 (merge 입력)
    ├── <회로>/model.pt                        회로당 한 파일 (bundle)
    ├── _all/predict_<온도>_hidden.rpt         홀드아웃 코너 리포트 (predict)
    ├── _all/runtime.rpt                      회로별 소요시간 (실행마다 한 줄 추가)
    └── _all/plots/                           scripts/plot.py 가 그리는 그림 (별도 실행)
    └── _all/predictions_hidden.npz            전 회로·온도 합본 (merge, 기계용)
    └── _all/summary.json                      코너별 성적표
```

넘길 때 필요한 건 보통 `runs/<mode>/_all/` 두 개와 회로별 `model.pt` 다.

### 홀드아웃 코너 리포트 (`predict`)

config 가 `hidden_corners` 로 빼 둔 코너는 **좌표를 다시 칠 필요가 없다.** 그냥:

```
bash scripts/run.sh predict                 # --corners hidden 이 기본값
bash scripts/run.sh predict --temp m25      # 그 온도만
```

학습이 끝나 있으면 이 한 줄로 온도마다
`runs/<mode>/_all/predict_<온도>_hidden.rpt` 가 나온다. 아래 `--at` 리포트와
**형식이 완전히 같고**, 이 코너들은 정답이 있으므로 measured·오차·WNS 오차 줄이
전부 채워진다. 회로마다 홀드아웃이 다르면 각 회로는 **자기 홀드아웃 열만** 채우고
나머지는 빈칸이다 (남의 홀드아웃은 이 회로엔 학습에 쓴 코너라 같은 숫자가 아니다).

`merge` 가 읽는 회로별 `predictions_hidden.npz` 도 같이 갱신된다.

### 측정 안 한 코너까지 예측하기 (`predict --at` / `--sweep`)

리포트가 없는 코너도 좌표만 주면 예측한다. rebuild 도 재학습도 필요 없다.

```
bash scripts/run.sh predict --sweep 0.48:0.70:0.02 --level cmax   # 전압 스윕
bash scripts/run.sh predict --at 0.57:cmax,0.62:rcmax --temp m25  # 콕 집어서
```

**온도마다 파일 하나**가 `runs/<mode>/_all/predict_<온도>_<요청>.rpt` 로 나온다.
**CSV 가 아니라 프라임타임 리포트 같은 텍스트 파일**이라 vim 으로 바로 열면 열이
맞아 있다. 온도마다 있는 RC 코너가 달라서(125C 는 rcmax·cmax, m25 는 rcmin 까지)
각 파일에는 **그 온도에 있는 코너만** 들어간다. `--temp` 를 주면 그 온도 파일 하나만
나온다. 같은 요청을 다시 돌리면 `_2` 가 붙은 새 파일이 생기고 앞의 것은 그대로 남는다
(`--name` 으로 이름 지정 가능).

```
************************************************************************
Report      : predicted slack
Temperature : m25
Designs     : PERIC0_Timing_Report
Clock       : 2.0000 -> 1.7999 ns  (500.0 -> 555.6 MHz)
Corners     : 0.500V_cmax, 0.550V_cmax, 0.685V_rcmin
************************************************************************

Design: PERIC0_Timing_Report

   idx path                                0.500V_cmax    0.550V_cmax   0.685V_rcmin
                                            slack (ps)     slack (ps)     slack (ps)
  ---- -------------------------------- -------------- -------------- --------------
     0 u_a/reg_0_->u_b/reg_0_                    100.7          211.0          434.7
     1 u_a/reg_1_->u_b/reg_1_                     96.7          207.0          430.7
   ...

  Summary
  ------------------------------------- -------------- -------------- --------------
  mean predicted slack (ps)                       78.7          189.0          412.7
  mean measured slack (ps)                        78.8                         412.9
  mean absolute error (ps)                         0.1                           0.2
  worst absolute error (ps)                        0.1                           0.2
  WNS predicted (ps)                              56.7          167.0          390.7
  WNS measured (ps)                               56.8                         390.9
  WNS error (ps)                                  -0.1                          -0.2
  WNS error (%)                                 -0.18%                        -0.05%
  sum of negative slacks (ps)                      0.0            0.0            0.0
  paths with negative slack (out of 12)              0              0              0
  max clock frequency (MHz)                      573.7          612.4          709.6
```

- 한 줄 = 경로 하나, **리포트의 path 인덱스 순서대로**. `idx` 는 `### FIXED_PATH idx=<n>`
  의 n, `path` 는 같은 줄의 `key=`
- 측정된 코너에만 `mean measured`·오차·`WNS measured`·`WNS error` 줄이 채워진다.
  측정 안 한 코너는 빈칸. `WNS error (%)` 는 그 경로 자신의 측정 slack 기준
- 요청한 코너가 그 온도에 하나도 없으면 그 온도 파일은 안 만든다

### 클럭 주파수·주기를 바꿔서 보기 (`--freq` / `--period`)

```
bash scripts/run.sh predict --sweep 0.5:0.7:0.02 --level cmax --freq 950      # MHz
bash scripts/run.sh predict --sweep 0.5:0.7:0.02 --level cmax --period 3.8    # ns, 같은 얘기
```

둘은 같은 스위치를 다르게 말한 것이고, 같이 주면 에러다. 파일 이름에는 준 대로
들어간다 (`F950MHz` 또는 `T3.8ns`).

리포트의 주기 대신 **그 주파수에서의 slack** 을 낸다. 근사가 아니라 정확하다:

```
slack(T') = slack(T) + N x (T' - T)        N = 그 경로의 사이클 수
```

주기는 캡처 엣지 시각으로만 식에 들어오고, 경로의 어떤 지연도 주기에 의존하지 않기
때문이다. 그래서 예측을 다시 할 필요 없이 뺄셈 한 번이면 된다.

- **멀티사이클 경로는 자기 N 만큼** 움직인다. 빌드 때 경로마다
  `캡처 엣지 - 발사 엣지` 를 저장하므로 자동이다
- **hold 모드에서는 아무것도 안 바뀐다.** hold 는 발사·캡처가 같은 엣지라 그 간격이
  0 이고, 주파수와 무관하다. `--period` 를 주면 그렇다고 알려준다
- 요약에 **`max clock frequency (MHz)`** 가 같이 나온다: 그 코너에서 아무 경로도
  위반하지 않는 최대 주파수. `--period` 를 뭘로 주든 **이 값은 안 변한다** (코너의
  성질이지 보고 주기의 성질이 아니다). 전압 스윕과 합치면 Vmin-Fmax 곡선이 된다
- 클럭 엣지 시각을 읽는 건 새로 들어간 기능이라 **빌드를 다시 해야** 쓸 수 있다.
  안 하면 그렇다고 알려준다
- **리포트에 그 줄이 있는지 먼저 확인할 것.** 벤더마다 형식이 다르므로 가정하지 말고
  `bash scripts/run.sh check` 로 본다:

  ```
  clock edge         24 lines OK   e.g. clock clk (rise edge)   0.0000   0.0000
    launch_edge=0.0 capture_edge=2.0 -> cycle gap=2.0   (predict --period needs this)
  ```

  `cycle gap` 이 나오면 `--period` 를 쓸 수 있다. `clock edge ... MISS` 이거나
  `no clock-edge times` 가 뜨면 나머지는 다 되지만 `--period` 만 못 쓴다
- 스윕 범위 안의 **측정 전압은 자동으로 들어간다** — 곡선이 실측점을 지나는지 보라고
- 모든 값은 모델 예측이다. **SI(크로스토크) 항도 측정 안 한 코너에서 똑같이 계산된다** —
  어느 코너든 자기 리포트를 쓰지 않고 seen 코너에 맞춘 보간을 그 좌표에서 평가하기
  때문에, 리포트가 없는 코너라고 다르게 취급할 이유가 없다
- 온도는 125 / m25 만 가능하다. 온도마다 모델이 따로라 그 사이 온도는 못 만든다

### 다른 회로에서 학습한 모델 쓰기 (`--weights`)

```
bash scripts/run.sh predict --design MIF_Timing_Report --temp m25 \
     --weights runs/setup/PERIC0_Timing_Report/model.pt --sweep 0.5:0.7:0.02
```

- **base 는 대상 회로 자기 리포트로 새로 적합한다.** 경로별 다항식이라 옮길 수가
  없다. 옮겨오는 건 신경망 보정뿐이다
- base 의 **설정**(차수·교차항·weighting·레벨좌표)은 학습 때 것을 쓴다. 보정이 그
  설정으로 만든 잔차를 고치도록 배웠기 때문. 대상 그리드가 그 차수를 못 받치면
  식별 불가능한 항은 자동으로 빠진다
- 셀 패밀리 사전과 입력 스케일은 **소스 모델 것**을 따라간다. 사전은 회로마다
  번호가 달라서 **이름으로 변환**한다. 소스에 없던 패밀리가 나오면 `<unk>` 로
  가고 몇 개인지 `[TRANSFER]` 줄에 찍힌다 — 그 수가 크면 두 회로가 셀 이름을
  다르게 분류하고 있다는 뜻이니 `parsing.cell_taxonomy` 를 config 에 고정할 것
- 파일 이름에 `_from_<소스회로>` 가 붙어서 누구 모델로 낸 값인지 남는다
- 온도는 같아야 한다 (온도마다 모델이 따로다)
- **소스 모델은 이 기능이 생긴 뒤에 학습된 것이어야 한다.** 사전과 스케일을
  체크포인트에 안 들고 있으면 거부하고 다시 학습하라고 알려준다

#### 대상 회로 설정은 어디서 하나

`--weights` 자체는 설정할 게 없다. **대상 회로의 코너 구성은 원래대로 `designs:`
아래 그 회로 항목에 적는다** — 새 회로면 항목을 하나 추가하면 된다:

```yaml
designs:
  NEW_Timing_Report:
    corners:
      voltages: [0.5, 0.6, 0.685]     # 그 회로가 실제로 돌린 전압만
    temps:
      - {tag: m25, token: m25, levels: [rcmax, cmax, rcmin], hidden_corners: []}
```

- **홀드아웃(`hidden_corners`)은 비워도 된다.** 측정한 건 전부 seen 이고 안 한 걸
  예측하는 게 목적이니까. `predict --at/--sweep` 은 코너를 직접 지정하므로 홀드아웃이
  필요 없다 (`base` 와 `train` 은 채점할 대상이 있어야 하니 여전히 필요하다)
- **대상 회로에서는 아무것도 측정하거나 고르지 않는다.** 레벨 좌표도, 다항식 차수도,
  weighting 도 전부 소스 모델 것을 그대로 쓴다. 대상에서 계산하는 건 **경로별 OLS
  계수**(그 회로 리포트로 맞춘 값)와 그 위의 보정뿐이다. 실행하면 뭘 가져오는지 찍힌다:

  ```
  [TRANSFER] from the source, not measured here: v^3 cross=True(deg3), level^2,
             weighting local, levels rcmax=-1.000, cmax=-0.001, rcmin=+1.000
  [TRANSFER] computed here: the per-path OLS fit on this circuit's own reports,
             and the correction on top of it
  ```

  그래서 `base.select_on: hidden` 을 신경 쓸 필요가 없다. 새 회로엔 고를 근거(정답)가
  없는데, 애초에 고르지 않는다
- 온도 이름(`tag`)은 소스 모델과 같아야 한다

전압 범위가 넓은 회로로 학습해서 좁은 회로에 쓰는 방향이 맞다. 반대면 학습 때 못 본
좌표를 묻게 되고, 그럴 때 보정을 줄이도록 만들어져 있다 (MIF 0.475~0.95 가 나머지
둘을 덮는다).

---

## 8.3 학습 없이 결과 보기 — `base --save`

`base` 는 OLS만 풀고 **초 단위**다. 거기에 `--save` 를 붙이면 **학습한 것과 똑같은
모양의 결과물**이 나온다 — 리포트와 그림까지.

```csh
bash scripts/run.sh base --save
python3 scripts/plot.py --corners base
```

```
runs/setup/<회로>/<온도>/predictions_base.npz    경로 x 코너 (기계용)
runs/setup/_all/predict_<온도>_base.rpt          ★ 코너별 Summary (WNS 포함)
runs/setup/_all/plots/*_base.png                 ★ scatter + rank
```

`.rpt` 의 Summary 는 predict 가 쓰는 것과 **같은 블록**이다:

```
  clock period (ns)                      2.0000    2.0000
  mean predicted slack (ps)               274.6     247.2
  mean measured slack (ps)                278.9     242.9
  mean absolute error (ps)                  4.3       4.3
  WNS predicted (ps)                      252.6     225.2
  WNS measured (ps)                       256.9     220.9
  WNS error (ps)                           -4.3       4.3
  WNS error (%)                          -1.67%     1.95%
  max clock frequency (MHz)               572.3     563.4
```

- **모든 코너가 들어간다** (seen 포함). seen 코너의 값은 **그 코너를 빼고 적합한
  LOO 예측**이라 거기서도 예측이다. 그래서 rank 궤적이 격자 전체로 길게 나온다
  (scatter 는 전처럼 홀드아웃만 그린다)
- 파일 이름 끝에 `_base` 가 붙어서 **학습 결과와 안 섞인다**
- **`--save` 를 안 주면 아무것도 안 쓴다.** base 는 진단이고, 두 번 돌렸을 때
  파일이 남아 있으면 헷갈린다

설정을 바꿔가며 보는 고리가 이걸로 닫힌다: 고치고 → `base --save` → `.rpt` 의 WNS
확인 → 그림. 학습은 마지막에 한 번만 하면 된다.

---

## 8.4 그림 그리기 — `scripts/plot.py`

발표 자료의 **scatter plot** 과 **rank movement** 그래프를 예측 파일에서 바로 그린다.

```csh
python3 scripts/plot.py                                   # runs/setup 전부
python3 scripts/plot.py --runs runs/extrapolation/setup   # 외삽 실험 쪽
python3 scripts/plot.py --design MFC_Timing_Report --temp 125
python3 scripts/plot.py --corners all --only rank         # seen 까지, rank 만
```

**그림은 그 결과 폴더 안에** 들어간다 (`--out` 으로 바꿀 수 있다):

```
runs/setup/_all/plots/scatter_<회로>_<온도>_<코너>.png   코너마다 하나. 실측 vs 예측, y=x, MAE·N
runs/setup/_all/plots/rank_<회로>_<온도>.png             True / Predicted 순위 궤적 2단
runs/extrapolation/setup/_all/plots/...                  외삽 실험은 자기 폴더로
```

실행한 위치에 `plots/` 를 만들지 않는다. 그러면 setup 과 외삽 실험을 차례로 그릴 때
**회로·온도·코너가 같아서 같은 파일 이름으로 덮어쓴다.**

- **scatter**: 대각선에서 떨어진 거리가 오차다. 한쪽 끝에서만 휘면 "범위 가운데는
  맞고 끝에서 틀리는" 모델인데, MAE 하나로는 안 보인다
- **rank movement**: 추적할 경로는 **첫 코너 → 마지막 코너에서 순위가 가장 많이
  움직인 것** 5개를 자동으로 고른다 (`--track` 로 개수 변경). 순위가 그대로인 경로는
  수천 개 중 거의 전부라 아무것도 말해주지 않는다. 왼쪽이 실측 순위, 오른쪽이 예측
  순위이고, **모양이 같으면 그 모델로 critical path 를 골라도 된다**는 뜻이다. ps 오차가
  조금 있어도 순서가 살아있으면 쓸모가 있다
- 코너가 많아야 궤적이 보인다. **`--corners all` 은 먼저 `predict` 에 줘야 한다** —
  `plot.py` 는 어떤 파일을 읽을지 고를 뿐이다:

  ```csh
  bash scripts/run.sh predict --corners all      # predictions_all.npz 를 만든다
  python3 scripts/plot.py --corners all --only rank
  ```

  그러면 회로마다 **자기 격자 전체**가 궤적이 된다 (PERIC0 8/12, MFC 10/15,
  MIF 14/21 코너). seen 코너도 예측값이다 — 자기 토큰을 가린 LOO 방식이라
  외운 값이 아니다
- **seen 코너는 아예 안 그린다** (scatter 도 rank 도). 모델이 그 위에서 적합된 코너라
  자기 데이터에 대고 그린 그림이다. `--corners all` 로 돌려도 **홀드아웃만** 나온다.
  순위는 코너 하나 안에서의 위치라, seen 을 빼도 남은 코너의 순위는 그대로다 —
  선이 홀드아웃 코너끼리 바로 이어질 뿐이다. 측정값 없는 코너(query)도 빠진다
- `--include-seen` 으로 켤 수는 있다 (그때는 x축 라벨에 `(seen)` 이 붙는다)
- `--only rank` / `--only scatter` 로 한 종류만 그릴 수 있다

**다른 회로의 가중치로 예측한 결과도 똑같이 그린다:**

```csh
bash scripts/run.sh predict --design MFC_Timing_Report --temp 125 \
     --weights runs/setup/MIF_Timing_Report/model.pt
python3 scripts/plot.py --corners hidden_from_MIF_Timing_Report
```

파일 이름 끝에 출처가 붙어서 자기 모델 그림과 **섞이지 않는다**:

```
scatter_MFC_Timing_Report_125_SSPG_0p5V_cmax.png                          자기 모델
scatter_MFC_Timing_Report_125_SSPG_0p5V_cmax_hidden_from_MIF_...png       MIF 가중치
rank_MFC_Timing_Report_125.png  /  rank_MFC_Timing_Report_125_hidden_from_MIF_...png
```

**matplotlib 이 필요하다.** 파이프라인의 다른 부분은 쓰지 않으므로, 없는 장비에서는
이 스크립트만 안 되고 그렇다고 한 줄로 알려준다 (`pip install matplotlib`). 디스플레이가
없어도 되게 Agg 백엔드로 고정돼 있다.

---

## 8.5 PrimeTime 스케일링과 비교 — `scripts/compare_scaling.py`

PrimeTime 은 **라이브러리가 없는 코너**도 있는 코너를 스케일해서 리포트할 수 있다.
그게 이 모델이 답하는 질문의 **다른 답**이다. 두 답을 같은 경로 위에 같이 찍는다.

```csh
# 반드시 먼저: 파일 이름을 어떤 코너로 읽었는지 확인 (그리지 않는다)
python3 scripts/compare_scaling.py --scaling pt_si/pt_si_re/example/scaling/PERIC0 --list

# 그리기
python3 scripts/compare_scaling.py --scaling pt_si/pt_si_re/example/scaling/PERIC0
python3 scripts/compare_scaling.py --scaling .../scaling/PERIC0 --mode hold
```

`--scaling` 아래를 **재귀적으로** 뒤지므로 그 밑에 `hold/` `setup/` 이 갈려 있어도 한 번에
다 처리된다. 회로 이름은 경로에서 추측한다 (`--design` 으로 덮어쓸 수 있다).

**그림** (`<runs>/_all/plots/ptscale_<회로>_<mode>_<온도>_<전압>_<레벨>.png`):

- 위: x = **path index** (`### FIXED_PATH idx=<n>`), y = slack (ps). PT 스케일링 /
  이 모델 / (측정이 있는 코너면) 실측 세 가지
- 아래: **PT 스케일링 − 모델**. 경향 차이를 보는 건 여기다 — 한쪽으로 치우쳐
  있는지, slack 이 클수록 벌어지는지가 점 모양으로 바로 보인다
- 선이 아니라 **점**이다. x 축은 양이 아니라 식별자라, 이으면 없는 추세가 그려진다

**코너는 파일 이름의 토큰으로 찾는다.** 순서나 대소문자가 달라도 된다:

| | 읽는 형태 |
|---|---|
| 전압 | `0p52V` / `0.52V` / `520mV` |
| 온도 | `125C` / `m25C` / `-40C` / `n40C` |
| BEOL | `rcmax` `rcmin` `cmax` `cmin` `cnom` `cworst` `cbest` `ctyp` `typical` |
| 체크 | `hold` / `setup` (파일명에 없으면 상위 폴더 이름으로) |

`restored_scaled_SSPG_0p52V_125C_RCMAX_V_hold.rpt` 도, `SSPG-0.52v-RCmax-125c.hold.rpt`
도 같은 코너로 읽는다. **모델 쪽 코너 라벨(`SSPG_0p52V_RCMAX`)도 같은 함수로
읽는다** — 한 규칙이라 두 쪽이 어긋나질 수 없다. 못 읽는 이름은 **추측하지 않고**
건너뛰며 목록에 찍는다. 그래서 `--list` 를 먼저 돌리라는 것 — 코너를 하나 잘못 읽으면
**다른 코너끼리 비교해 놓고 모델이 틀린 것처럼 보인다.**

**모델 값은 이미 써둔 걸 읽는다:**

```
runs/<mode>/<회로>/<온도>/predictions_*.npz    base --save / train / predict
runs/<mode>/_all/predict_<온도>_*.rpt         predict --at / --sweep
```

스케일링한 코너는 보통 **측정 격자에 없는 코너**라서 (그러니까 스케일링을 한
것이다) 예측 파일에도 없다. 그럴 땐 **돌릴 명령을 그대로 찍어준다**:

```
to produce the missing ones:
  bash scripts/run.sh predict --at 0.52:rcmax --temp 125 --mode hold
```

그걸 돌리고 다시 실행하면 그 리포트를 읽어서 그린다.

**경로는 idx 로 맞춘다.** 양쪽 다 `### FIXED_PATH idx=` 를 가지고 있으면 idx 로,
아니면 경로 키로 맞춘다. **줄 순서로는 절대 안 맞춘다** — 두 도구가 개수가 다른
경로를 내놓을 수 있고, 그럼 서로 다른 경로를 비교하면서 모델 오차처럼 보인다.
몇 개가 무엇으로 맞았는지 매번 찍는다:

```
  [matched] 0.520V rcmax   125C hold  : 1842 paths joined on idx (with measurement;
            PT read as FIXED_PATH; model SSPG_0p52V_RCMAX <- PERIC0/125/predictions_base.npz)
```

PT 리포트가 `### FIXED_PATH` 없는 **그냥 `report_timing` 출력**이어도 읽는다
(Startpoint/Endpoint 로 키를 만든다). 그때는 x 축이 idx 가 아니라 리포트 순서고,
그렇다고 축 라벨에 쓴다.

**matplotlib 이 필요하다.** 없으면 `--list` 만 동작한다 (숫자는 그때도 다 찍힌다).

---

## 8.6 소요시간 — `_all/runtime.rpt`

실행할 때마다 한 줄씩 덧붙는다. 덮어쓰지 않으므로 이전 기록이 남는다.

```
# si_corner_model runtime -- one line per stage, appended. wall/cpu: cpu > wall means threads.
date             stage     circuit                  mode   temps  paths corners      wall       cpu  thr host
2026-10-02 12:43 build     MFC_Timing_Report        setup      2     12      20     3h12m    41h02m   16 knuee-srv5
2026-10-02 15:55 train     MFC_Timing_Report        setup      2     12      20    28m04s   3h40m    16 knuee-srv5  epochs=40
2026-10-02 16:23 inference -                        setup      -      -       -     13.6s    22.7s   16 knuee-srv5  bundle corners=hidden merge
```

**단계는 세 개만 기록한다:**

- **`build`** 리포트 파싱 → `dataset.npz`
- **`train`** OLS base 적합을 **포함**한다. 따로 안 쪼갠다 — 학습 한 번의 시간이다
- **`inference`** 학습 뒤에 결과물을 만드는 전부 (predict · 리포트 · bundle · merge)
  를 합친 것
- `base` 와 `sweep` 은 **기록하지 않는다.** 진단용이고 초 단위다

읽는 법:

- **`build` · `train` 은 회로마다 한 줄**이고 그 회로의 **온도는 합산**된다 (`temps`
  가 몇 개였는지). 온도는 내부 분할이고, 묻는 건 "이 회로 setup 이 얼마 걸렸나" 다.
  `mode` 열이 setup/hold 를 구분한다
- **`inference` 는 실행당 한 줄**이다 (회로 `-`). 회로별로 나눌 수 없는 단계(리포트,
  merge)가 섞여 있고 어차피 전부 초 단위다
- **`wall`** 은 실제 경과, **`cpu`** 는 쓴 CPU 시간 합. `cpu > wall` 이면 스레드를
  쓰는 중, `cpu ≈ wall` 이면 한 코어로 기다리는 중이다
- **`paths` / `corners`** 가 없으면 "3시간"이 빠른지 느린지 알 수 없다 — 경로 12개의
  3시간과 4000개의 3시간은 다른 측정이다
- **`thr` / `host`** 도 같은 이유다. 같은 build 가 16스레드에 3시간, 4스레드에 하루다
- 마지막 칸은 그 실행의 스위치 (`epochs=40`, `corners=hidden`, `from=MIF_...`,
  `freq=950`)
- 그 회로의 **마지막 온도가 끝날 때** 쓴다. 세 회로짜리 build 가 세 번째에서 죽어도
  앞의 두 줄은 남는다

---

## 8.7 실험용 두 번째 config — 외삽 (`config_extrapolation.yaml`)

같은 리포트로 **다른 질문**을 하고 싶을 때, config 를 고치는 게 아니라 **config 를
하나 더** 만들어 놓고 `--config` 로 갈아 끼운다. 지금 들어 있는 건 외삽 실험이다.

```
bash scripts/run.sh list    --config config_extrapolation.yaml   # ← 먼저 이걸로 검산
bash scripts/run.sh train   --config config_extrapolation.yaml
bash scripts/run.sh predict --config config_extrapolation.yaml
bash scripts/run.sh merge   --config config_extrapolation.yaml
```

**무엇이 다른가.** 기본 config 는 홀드아웃을 격자 **안쪽**에 흩어 놓는다 (같은 전압의
다른 레벨이 seen 으로 남아 있다). 외삽 config 는 **가장 낮은 전압 행을 통째로** 숨긴다:

| | 기본 `config.yaml` | `config_extrapolation.yaml` |
|---|---|---|
| 숨기는 것 | 온도별로 흩어진 2~4개 셀 | **최저 전압의 모든 레벨** (그것만) |
| PERIC0 / MFC | 0.5 V 는 학습에 들어감 | 0.5 V 행 전체 히든 |
| MIF | 0.475 V 는 학습에 들어감 | 0.475 V 행 전체 히든 (MIF 격자엔 0.5 가 없다) |
| 묻는 것 | 범위 **안쪽** 내삽 | 학습 범위 **아래로** 외삽 → 0.54 V 이상만 보고 그 아래를 맞히기 |

`corners.hidden_voltages: [0.5, 0.475]` 한 줄로 되어 있다. 격자에 없는 전압은 그냥
아무것도 안 걸리므로, **회로마다 자기 최저 전압 하나씩** 빠진다. 대신 `temps[]` 안에
온도별로 박혀 있던 `hidden_corners` 는 **여섯 군데 전부 비워** 두었다 (홀드아웃 키는
합집합이라, 안 비우면 그것들도 같이 숨는다).

**결과는 섞이지 않는다.** `out.tag: extrapolation` 때문에 전부 여기로 간다:

```
runs/extrapolation/setup/<회로>/<온도>/     ← 이 실험
runs/extrapolation/setup/_all/
runs/setup/<회로>/<온도>/                   ← 기존 결과, 손 안 댐
```

`mode` 보다 **위** 단계라서 `--mode hold` 도 그대로 동작한다
(`runs/extrapolation/hold/...`). 일회성으로는 `--tag <이름>` 도 된다.

**빌드는 다시 안 해도 된다.** `cache/` 는 태그가 안 붙는다 — dataset.npz 는 seen/hidden
분할과 무관하고 (분할은 매 로드마다 config 에서 다시 계산) 같은 리포트를 같은 방식으로
읽은 결과라, 기존 캐시를 그대로 쓴다. 그래서 위 예시가 `all` 이 아니라 `train` 부터
시작한다. `all` 로 돌리면 이 파일이 캐시보다 새 파일이라 **한 번** 다시 파싱하고
(몇 시간짜리) 같은 내용을 덮어쓴다. 그럴 필요 없다.

**결과를 읽을 때 알아야 할 것 세 가지.**

- seen 전압이 하나 줄어서 `base.v_order: auto` 도 같이 내려간다 (PERIC0 는 3 → 2).
  남은 전압 점을 다항식이 정확히 지나가 버리므로, 0.5 V 값은 전적으로 **곡률 가정의
  외삽**이다. `base: {v_order: 1}` (직선) 과 비교해 볼 가치가 크다
- `base.select_on: hidden` 이 기본이라 basis·weighting 을 **평가 대상인 그 코너로**
  고른다. 즉 이 숫자는 낙관적이다. 외삽 성능으로 보고할 거면 이 점을 같이 적어야 한다
- 오차는 기본 config 보다 **훨씬 크게 나오는 게 정상이다.** 외삽이니까. 합성 데이터로
  돌려 본 참고치: 내삽 MAE 0.35 ps → 외삽 MAE 6.6 ps

**이 파일은 config.yaml 의 복사본이다.** 값이 다른 곳은 위에 적은 네 군데뿐이고,
`tests/test_all.py::test_extrapolation_config_is_config_yaml_plus_the_holdout` 가
두 파일을 키 단위로 비교해서 **다섯 번째 차이가 생기면 테스트가 깨진다.** 즉
config.yaml 만 고치고 이 파일을 안 고치면 CI 가 알려준다 — 다만 **옮겨 적는 건 손으로**
해야 한다.

---

## 8.8 외삽을 더 잘하게 — 축 변수(`v_transform`)와 기준(`select_on: edge`)

`run.sh base` 는 OLS만 numpy로 풀고 **히든 코너별 오차**를 찍는다. GPU도 학습도 없고
**초 단위**다. 그래서 외삽 관련 결정은 전부 여기서 먼저 재고 넘어간다.

### 왜 손댈 게 있나

전압 3점을 **V의 2차식**도 정확히 지나가고, **1/V의 직선**도 정확히 지나간다. 둘 다
측정값을 하나도 안 틀리는데, **범위 밖의 0.5 V 에서는 서로 다른 값**을 낸다. 즉
범위 안에서는 변수 선택이 거의 무의미하고, **범위 밖에서는 변수 선택이 답의 대부분**이다.

### `base.v_transform`

```
none   V          (지금까지의 다항식)
inv    1/V
log    log V
auto   세 개를 다 재보고 select_on 기준으로 제일 좋은 걸 쓴다
```

`auto` 면 `[VAXIS]` 줄이 후보별 점수와 마진까지 찍는다. 이긴 걸 config 에
`v_transform: inv` 로 박아두면 매 실행마다 다시 고르지 않는다. 학습하면 **체크포인트에
같이 저장되고 predict 는 그걸 그대로 재생**한다 (보정은 자기가 올라탔던 base 위에서만
의미가 있다).

**일부러 상수가 없는 것만 넣었다.** `1/(V - Vth)` 는 alpha-power 지연 법칙을 코드에
박는 것이고, slack 은 셀 지연 하나가 아니라 `T - (지연 합) + skew - U` 다. 게다가 Vth 가
PDK/코너마다 다르면 **자신 있게 틀린다**. `1/V` 와 `log V` 는 틀릴 상수가 없는 단순
단조 변수 변환이라, 이걸 쓰는 건 물리 주장이 아니라 "곡률 가정을 하나 더 후보에 올린다"
는 뜻이다. 어느 게 맞는지는 드롭마다 측정한다.

### 전압마다 클럭 주기가 다를 때 (`base.period_norm`) — **가장 큰 함정**

DVFS면 전압을 낮출 때 클럭도 느리게 합니다. 정상적인 관행인데, 우리 모델에는 치명적입니다.

setup slack = `T − (지연 합) + skew − U`. 여기서 **`T`는 물리가 아니라 설계 선택**입니다.
코너마다 `T`가 다르면 우리가 적합하는 대상이 사실 `T(V) − delay(V)` 이고, `T(V)` 는
곡선이 아니라 사람이 고른 계단값입니다. 측정 구간 **안**에서는 다항식이 그걸 같이
흡수해서 아무 문제가 없습니다. 구간 **밖**으로 나가면 `T(V)` 까지 외삽하게 되는데,
그건 남의 주파수 계획을 추측하는 일입니다. 그래서 **차수를 뭘 쓰든 같은 상수만큼**
빗나갑니다.

실제로 회사 드롭에서 이게 났습니다: 모든 차수 후보가 **~1490 ps**, 그리고 최저 전압의
실측 slack이 그 위 전압보다 **더 컸습니다** — 전압을 낮췄는데 slack이 좋아지는 건
클럭을 늘려준 경우에만 가능합니다. 그게 결정적 증거입니다.

**고치는 방법은 정확한 항등식입니다** (모델이 아니라 뺄셈):

```
slack(T') = slack(T) + N x (T' - T)        N = 그 경로의 사이클 수
```

`base.period_norm: auto` (기본값) 가 적합 전에 모든 코너를 **앵커 코너의 주기**로 옮기고,
적합 후에 각 코너의 `N·(T − Tref)` 를 **다시 더해** 줍니다. 그래서:

- 적합은 순수한 지연 곡선을 봅니다 → 외삽이 의미를 가집니다
- **보고되는 숫자는 하나도 안 바뀝니다** — 각 코너의 자기 주기에서의 slack 그대로입니다
- 추정하는 값이 없습니다. 상수도 새로 안 생깁니다

합성 데이터로 같은 회로, 클럭 계획만 다르게 해서 측정:

| | 최저 전압 행 홀드아웃 오차 |
|---|---|
| `period_norm: off` (예전 동작) | **857 ps** |
| `period_norm: auto` (지금) | **7.9 ps** |

**확인 방법.** `run.sh base` 가 전압별 주기를 찍고, 평평하지 않으면 크게 경고합니다:

```
    [measured slack vs voltage]  mean over paths, ps   (* = held out)
      0.500 V      1278.9*     1242.9*    clock 3.0000 ns
      0.540 V       469.3       434.5     clock 2.1000 ns
      0.600 V       474.5       441.2     clock 2.0000 ns
      0.685 V       581.3       549.6     clock 2.0000 ns
     (!) THE CLOCK PERIOD IS NOT THE SAME AT EVERY VOLTAGE (2.0000 .. 3.0000 ns).
```

주의할 것 두 가지:

- **캐시에 클럭 엣지 정보가 있어야 합니다.** 없으면 `(clock: this cache has no edge
  times -- re-run build ...)` 라고 알려줍니다. 그러면 `build` 를 다시 해야 합니다.
- **`--freq` / `--period` 는 이 격자에서 거부됩니다.** 코너마다 주기가 다르면 전역
  주기 하나로 전부 옮기는 계산이 열마다 `N·(T_코너 − T)` 만큼 틀립니다. 조용히 틀린
  숫자를 내는 대신 에러로 멈춥니다. 각 코너를 자기 주기로 보는 건 그냥 `--freq` 없이
  돌리면 됩니다.

### `split.blind_hidden` — 히든 코너를 아예 안 본다고 가정

내삽 실험에서는 홀드아웃을 보고 고르고 있었다. 후보 basis도, 학습 에폭도 (`best.pt` 는
매 에폭 **히든 코너 점수**가 가장 좋을 때 저장된다). 그래서 보고되는 히든 오차는
"N개 중 제일 좋은 것" 이지 held-out 추정치가 아니었고, `run.sh train` 이 그렇다고
경고를 찍고 있었다.

외삽 실험에서는 그 홀드아웃이 **결과물 자체**라 그럴 수 없다. `split.blind_hidden: true`
한 줄이 **모든 결정**에서 히든 코너를 뺀다:

| 결정 | blind_hidden: false | true |
|---|---|---|
| basis (차수·cross) | 히든 오차로 고름 | seen만 (`select_on: edge`) |
| 축 변수 (`v_transform`) | 히든 오차로 고름 | seen만 |
| weighting | 히든 오차로 고름 | seen만 |
| 학습 에폭 (`best.pt`) | **히든 오차로 고름** | **seen 코너 모니터로 고름** |
| 히든 MAE·WNS 출력 | 찍음 | **그대로 찍음** |

**노브를 결정마다 따로 두지 않았다.** 노브가 여러 개면 서로 어긋난다 — 그래서 한 개고,
`base.select_on: hidden` 과 같이 켜면 **에러로 거부**한다(그 기준은 정확히 히든 라벨로
채점하는 것이니까).

측정·출력은 그대로다. 달라지는 건 그 숫자의 **의미**다. `run.sh train` 의 경고가 뒤집힌다:

```
  NOTE: split.blind_hidden -- no choice here read these corners (basis, axis
        variable, weighting and epoch were all picked on seen corners), so this
        number is a held-out estimate rather than a best-of-N.
```

`summary.json` 에도 `"selected_on": "seen_only (blind_hidden)"`, `"blind_hidden": true` 로
남는다.

**대가는 있다.** seen 기준 모니터는 히든 품질이 꺾인 뒤에도 계속 좋아져서 **늦은 에폭을
집는 경향**이 있다 (실측: 125C 에서 5.81 ps 를 저장했고 그때 피크는 0.94 ps 였다).
그게 "숫자가 말하는 그대로를 의미하게" 만드는 값이다. 홀드아웃이 손에 있고 그걸로 튜닝할
생각이면 끄고 쓰면 된다 (기본값 false, 즉 기존 동작).

### `base.select_on: edge`

`hidden` 은 홀드아웃 코너의 오차로 후보를 고른다. 외삽 실험에서는 **그 홀드아웃이 바로
결과물**이라, 그걸로 고르면 정답 보고 고르는 셈이고 보고되는 숫자는 "N개 중 제일 좋은 것"
이 된다. `edge` 는 같은 질문을 **한 칸 안쪽**에서 한다:

> seen 중 **최저 전압 행을 통째로** 빼고 남은 것으로 적합해서, 그 행을 맞혀 본다.
> 최고 전압 행에 대해서도 같이 하고 평균.

seen 코너만 쓰므로 홀드아웃 라벨을 한 번도 안 읽는다. **드롭마다 다시 계산되는 기준**
이고, 안에 박힌 상수가 없다.

**약점은 크기다.** 행을 통째로 빼면 전압 하나가 날아가서, 줄어든 격자로 식별이 안 되는
후보는 **점수가 아예 안 나온다**(표에 `-`). seen 전압이 3개뿐이면 할 말이 거의 없고,
5개 이상이면 쓸 만하다. 아무 후보도 못 재면 그렇다고 말하고 seen-LOO 로 내려간다.

그래서 **`run.sh base` 가 후보마다 seen-LOO · edge · hidden 을 나란히 찍고, edge 가
hidden-최적 basis 를 골랐는지 아닌지까지 한 줄로 말해준다.** 새 드롭에서 이 기준을
믿어도 되는지는 그 줄로 판단한다.

```
    -- basis candidates (chosen on edge extrapolation (one voltage out)) --
       v^1 cross=False  3 params   seen-LOO     2.34   edge    10.17   hidden     6.24  <- hidden picks this
       v^2 cross=True   5 params   seen-LOO     0.01   edge        -   hidden     7.80  <- seen-LOO picks this
       v^2 cross=False  4 params   seen-LOO     1.37   edge     7.29   hidden     7.89  <- chosen
       -> the edge criterion does NOT pick the hidden-best basis here.
```

### 설정 안 건드리고 쓸어보기 — `SI_BASE`

```csh
env SI_BASE="v_order=1,weighting=local" bash scripts/run.sh base --config config_extrapolation.yaml

foreach t (none inv log)
  env SI_BASE="v_transform=$t" bash scripts/run.sh base --config config_extrapolation.yaml
end
```

`base:` 아래 어떤 키든 `키=값` 으로 준다. 타입은 config 에 있는 타입으로 맞춰지고
(`cross_terms=false` 는 불리언), **모르는 키는 에러**다 — 조용히 아무것도 안 하는 설정이
제일 위험하니까. config.yaml 을 고치지 않으므로 `git pull` 이 실험을 먹지 않는다.

### 합성 데이터로 확인한 것 (실제 데이터 수치가 아니다)

테스트 픽스처의 slack 은 `1 - (0.30*(0.8/v)^1.8 + ...)`, 즉 **1/v 의 함수로 만들어져
있다.** 그래서 `auto` 가 `inv` 를 고르는 게 정답이고, 그걸 확인하는 게 테스트다:

| 설정 | 125C 히든 | m25 히든 |
|---|---|---|
| `v_transform: none`, `select_on: hidden` | 6.58 ps | 6.63 ps |
| `v_transform: auto` → inv, `select_on: hidden` | **0.29 ps** | **0.19 ps** |
| `v_transform: auto`, `select_on: edge` (실험 config 기본) | 7.89 ps | 0.19 ps |

읽는 법 두 가지:
- **변수를 고르는 것이 큰 레버다** (6.58 → 0.29). 단 이 20배는 픽스처가 1/v 로 만들어진
  덕이라 상한이다. **실제 드롭에서 얼마인지는 `[VAXIS]` 줄이 말해준다.**
- **`edge` 는 격자가 작으면 약하다.** 125C 는 seen 전압 3개 x 레벨 2개 = 6코너뿐이라,
  행을 빼면 4코너가 남고 hidden-최적이었던 5-파라미터 후보를 **점수조차 못 냈다** →
  더 나쁜 basis 를 골랐다 (7.89 vs 0.29). m25(9코너)에서는 hidden-최적과 사실상 동일.
  실제 드롭은 PERIC0 3 / MFC 4 / MIF 6 seen 전압이니, MIF 쪽이 이 기준이 제일 할 말이 많다.

---

## 8.5 `Killed` 만 뜨고 이유가 안 남을 때

`Killed` 는 SIGKILL 이다. **프로세스가 잡을 수 없어서 죽는 순간에는 아무것도 못 남긴다** —
파이썬 traceback 도, 커널 메시지도 그 프로세스에는 안 온다. 대신 두 가지가 있다.

### ① 죽기 직전까지의 궤적 (로그에 남는다)

실행을 시작하면 맨 위에 **어느 장비, 어느 job 인지**가 먼저 찍힌다. 죽은 뒤
스케줄러에 물어보려면 이 job id 가 있어야 한다:

```
[JOB] host cn0123  pid 48211  LSF job 987654  queue normal  name si_build
```

> job id 가 안 찍히고 "no scheduler job id" 가 나오면 할당받은 job **밖에서**
> 돌린 것이다. 그러면 스케줄러에 조회할 방법이 없으니, `ub_sub` 로 받은 창
> 안에서 다시 돌린다.

이어서 `[MEM]` 줄이 주기적으로 찍힌다. **마지막 줄이 어디까지 올라갔는지** 말해준다:

```
[MEM] limit: cgroup 40.0 GB
[MEM] corner 1/8             anon   4.21 GB  file   0.30 GB  cgroup 5.1/40.0 GB
[MEM] corner 2/8             anon   8.40 GB  file   0.31 GB  cgroup 9.3/40.0 GB
[MEM] corner 3/8             anon  12.6  GB  file   0.31 GB  cgroup 13.5/40.0 GB
```

줄 뒤쪽에는 **메모리 말고 다른 한도**도 같이 나온다. 이것들로 죽어도 화면에는
똑같이 `Killed` 만 뜨기 때문이다:

```
... | 42m wall 38m cpu  disk-free 120 GB  threads 65
```

`wall` 은 시작한 뒤 흐른 실제 시간, `cpu` 는 그동안 쓴 CPU 시간(전 스레드 합)이다.
**둘을 비교하면 상태를 읽을 수 있다:**

| 관계 | 뜻 |
|---|---|
| `cpu` ≈ `wall` | 단일 스레드로 꽉 차게 일하는 중 |
| `cpu` >> `wall` | 여러 스레드 병렬 (`2m wall 85m cpu` = 40여 개) |
| `cpu` 는 안 늘고 `wall` 만 늘어남 | **일을 안 하고 있음** — 디스크 대기이거나 멈춤 |

"멈춘 건가" 싶을 때 `cpu` 가 늘고 있으면 도는 중이다.

| 보이는 값 | 의심할 것 |
|---|---|
| `wall` 이 스케줄러 한도에 근접 | 실행시간 초과로 스케줄러가 죽임 |
| `disk-free` 가 줄어듦 | 이 파이프라인이 큰 배열을 파일로 쓴다. 꽉 차면 죽는다 |
| `threads` 가 계속 늘어남 | 프로세스/스레드 한도 |

`anon` 과 `file` 을 나눠 찍는 이유가 있다. **둘 중 하나만 죽일 수 있다:**

| | 뜻 | 부족할 때 |
|---|---|---|
| `anon` | 원본이 RAM 에만 있음 | **회수 불가 → 죽는다** |
| `file` | 원본이 디스크에 있음 (memory-map) | 커널이 버리고 다시 읽음 — 안 죽는다 |

`file` 이 커도 문제가 아니다. **`anon` 이 한도에 다가가는지**만 보면 된다.

로그가 없으면 `nohup ... > log 2>&1` 로 남기고 돌린다 (§6).

> **`no scheduler job id` + `limits: none visible` 이 같이 뜨면** 배치 job 안이
> 아니고 per-job 메모리 한도도 없다는 뜻이다. 그러면 죽이는 주체는 **시스템 전체
> OOM killer** 다. 그 경우 `machine-free` 를 봐야 한다 — 이건 같은 장비를 쓰는
> 다른 사람들 때문에도 줄어들고, 커널은 **그 순간 제일 큰 프로세스**를 죽인다.
> 내 잘못이 아니어도 내가 죽을 수 있다.
>
> (참고: `ulimit -v` 로 스스로 한도를 걸어 MemoryError 를 유도하는 방법은 **안 된다.**
> numpy/torch 가 시작할 때 예약하는 가상 주소공간이 커서, 쓸만한 한도를 걸면
> import 조차 못 한다. 실제로 시험해 보고 뺐다.)

### ② 죽은 뒤 원인 조회

```bash
bash scripts/why_killed.sh log.mfc.125
```

프로세스보다 오래 남는 것들을 읽어준다:

- **cgroup 카운터** — `failcnt` 가 0 이 아니면 메모리 한도에 실제로 부딪힌 것이다.
  `max_usage` 로 얼마나 올라갔는지도 나온다.
- **커널 OOM killer** — `dmesg` 가 읽히면 그 기록
- **스케줄러** — LSF 면 `bjobs -l <jobid>` / `bhist -l <jobid>` 에
  `TERM_MEMLIMIT` / `TERM_RUNLIMIT` 이 있는지

> **같은 셸/작업 안에서 돌려야 한다.** cgroup 카운터는 그 세션 것이라
> 새 창을 열면 안 보인다.

`failcnt` 가 0 인데도 죽었다면 **메모리가 아니다.** `why_killed.sh` 는 그 경우를
위해 나머지도 같이 찍는다 — `ulimit` (cpu-time / file-size / nproc), 디스크 여유와
quota, 그리고 LSF 의 종료 사유. LSF 는 `TERM_*` 로 이유를 남긴다:

| | 뜻 |
|---|---|
| `TERM_MEMLIMIT` | 메모리 초과 |
| `TERM_RUNLIMIT` | 실행시간(wall) 초과 |
| `TERM_CPULIMIT` | CPU 시간 초과 |
| `TERM_OWNER` / `TERM_ADMIN` | 사람이 죽임 |

`bhist -l <jobid>` 로 본다 — job id 는 로그 맨 위 `[JOB]` 줄에 있고,
`why_killed.sh` 에 로그를 넘기면 **거기서 알아서 찾아** 조회까지 해준다. 여기서 아무것도 안 나오면 관리자 정책(유휴 종료 등)일
수 있으니 담당자에게 jobid 와 함께 문의한다.

### 메모리가 원인일 때 줄이는 순서

```
① 모델 하나씩            run.sh build --design <회로> --temp <온도>
② SI 끄기                config.yaml: crosstalk_subdir: null
③ 배치 줄이기            train.batch_paths: 256 -> 128
④ 용량 줄이기            model.enc_dim: 128 -> 48, enc_blocks: 3 -> 2
```

---

## 9. 자주 막히는 것

| 증상 | 원인 / 대처 |
|---|---|
| `command not found: ub_sub` | 로그인 노드가 아니거나 환경 모듈 미로드. 담당자 확인 |
| `No module named numpy` | `python3` 이 잘못 잡힌 것. §2 로 경로를 다시 고른다 |
| `PY=... bash ...` 가 안 먹음 | csh/tcsh 다. `setenv PY ...` 또는 `env` 를 쓴다 |
| `root does not exist` | `config.yaml` 의 `root`. `env SI_ROOT=/실제/경로` 로 임시 지정 가능 |
| `0 paths parsed` | 리포트 형식이 다르다. `run.sh check <파일>` → [PARSING.md §4](PARSING.md) |
| `degenerate split: N seen < min_seen` | 리포트가 빠졌다. `list` 의 코너 수와 실제 파일 수를 대조 |
| `could not convert string to float` | 고쳐졌다. 그래도 나면 그 줄을 그대로 공유할 것 |
| xterm 닫으니 죽음 | §6 의 `nohup` 으로 띄운다 |
| `ambiguous output redirect` | csh 다. `> f 2>&1` 대신 `>& f` |
| `unrecognized argument $...` | 셸 변수가 안 풀렸다. `$P` 같은 축약 쓰지 말고 전부 적는다 |
| `Undefined variable` | 같은 원인 (csh). §4 의 형태로 |
| `Killed` 만 뜨고 이유 없음 | §8.5 — `bash scripts/why_killed.sh <로그>` |
| 수치가 안 보임 | 의도된 기본값. §4.5 의 `SI_VERBOSE=1` 또는 `summary.json` |
| 오래 조용함 | `[MEM]` 의 `cpu` 가 늘고 있으면 정상. §8.5 |
| 아무것도 안 찍힘 | 첫 코너를 읽는 중이다. 경로가 많으면 몇 분 걸린다. `ps` 로 살아있는지 확인 |
