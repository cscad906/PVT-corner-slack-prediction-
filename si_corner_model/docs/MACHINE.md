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

```bash
P="env PY=/usr/bin/python3"        # bash 기준. csh 면 setenv 후 이 변수 없이

$P bash scripts/run.sh recon       # ① 데이터 정찰 -> recon_out.txt
$P bash scripts/run.sh check       # ② 리포트 한 개를 파서에 통과시켜 본다
$P bash scripts/run.sh list        # ③ 뭐가 돌지 확인 (파일 안 건드림)
$P bash scripts/run.sh build       # ④ 리포트 -> cache/.../dataset.npz
$P bash scripts/run.sh base        # ⑤ OLS base 오차만 (수 초, torch 불필요)
$P bash scripts/run.sh train       # ⑥ 학습 (몇 시간, §5)
$P bash scripts/run.sh bundle
$P bash scripts/run.sh predict
$P bash scripts/run.sh merge
```

`all` 은 ④~⑨ 를 한 번에 돈다. 처음에는 **한 단계씩** 돌려 각 단계 출력을 확인하는
편이 낫다.

### 단계마다 꼭 볼 것

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

### 줄이는 방법 (효과 순)

1. **`epochs: 40` → `30`** — 최고점이 대체로 E22~E26 이라 손해가 거의 없고 25% 단축
2. **모델별로 나눠 동시 실행** — 아래 §6. 16코어에서 2~3개가 현실적
3. `model.enc_dim: 128 → 48`, `model.enc_blocks: 3 → 2` — 추가 30~40% 단축

**메모리는 모델당 6.3 GB 다.** 동시에 3개면 약 19 GB 가 필요하니 `free -g` 로
먼저 확인한다.

---

## 6. 몇 시간짜리 작업 띄우기

xterm 을 닫아도 죽지 않게 `nohup` 으로 띄우고 로그를 남긴다.

```bash
# 모델 하나씩, 로그를 따로
nohup env PY=/usr/bin/python3 bash scripts/run.sh train \
      --design MFC_Timing_Report --temp 125 > log.mfc.125 2>&1 &

nohup env PY=/usr/bin/python3 bash scripts/run.sh train \
      --design MFC_Timing_Report --temp m25 > log.mfc.m25 2>&1 &
```

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
$P bash scripts/run.sh all --mode hold
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
    ├── <회로>/<온도>/predictions_hidden.csv   경로별 예측
    ├── <회로>/model.pt                        회로당 한 파일 (bundle)
    └── _all/predictions_hidden.csv            전 회로·온도 합본 (merge)
    └── _all/summary.json                      코너별 성적표
```

넘길 때 필요한 건 보통 `runs/<mode>/_all/` 두 개와 회로별 `model.pt` 다.

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
| `Killed` 만 뜨고 이유 없음 | §8.5 — `bash scripts/why_killed.sh <로그>` |
| 아무것도 안 찍힘 | 첫 코너를 읽는 중이다. 경로가 많으면 몇 분 걸린다. `ps` 로 살아있는지 확인 |
