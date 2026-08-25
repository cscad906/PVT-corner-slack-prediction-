# START — 도착해서 처음부터 끝까지

**이 문서 하나만 위에서 아래로 따라가면 된다.** 막히면 각 STEP 끝의 표를 본다.

> 회사 장비 할당(`ub_sub`), python 인터프리터 경로 지정, 실측 소요 시간·메모리는
> **[MACHINE.md](MACHINE.md)** 에 따로 있다. 장비에서 처음 돌린다면 그쪽을 먼저.

명령은 `bash scripts/run.sh <단계>` 하나뿐이고, 설정은 `config.yaml` 하나뿐이다.
아무 인자 없이 `bash scripts/run.sh` 를 치면 단계 목록이 나온다.

```
recon → config.yaml 수정 → list → build → base → train → bundle → predict → merge
 정찰     (여기만 고침)     검산    캐시   base점검  학습   가중치묶기  예측   통합
```
`run.sh all` 이 build 부터 merge 까지 한 번에 한다.

---

## STEP 0. 옮기고 환경 만들기

이 폴더(`si_corner_model/`)를 회사 서버로 옮긴다. **회로 폴더들과 나란히** 두는 걸
권장한다 — 그러면 `root` 를 안 적어도 된다.

```bash
cd /user/s5e9965p5/academy_experiment   # 회로 폴더들이 있는 곳
# (si_corner_model 을 여기로 복사/클론)
cd si_corner_model

bash scripts/find_python.sh             # ★ 먼저 이것부터
```

`find_python.sh` 가 **서버에 이미 깔려 있는 python 들을 전부 뒤져서** numpy/pyyaml/
torch 가 있는 놈을 찾아준다. EDA 서버에는 보통 Synopsys/Cadence 가 끼워 넣은
python 이 여러 개 있고 그중 하나는 torch까지 갖고 있다. 출력 맨 아래가 알려주는
대로 하면 된다:

**쉘에 따라 문법이 다르다.** `echo $SHELL` 로 확인하고 맞는 쪽을 쓴다:

```bash
export PY=/usr/bin/python3              # bash / zsh
```
```csh
setenv PY /usr/bin/python3              # csh / tcsh  (EDA 서버 기본값인 경우가 많다)
```

한 번만 쓸 거면 쉘과 무관하게 `env` 를 앞에 붙이면 된다:

```
env PY=/usr/bin/python3 bash scripts/run.sh all
```

`PY=... bash scripts/run.sh all` 처럼 **접두로 쓰는 건 bash/zsh 전용**이다.
csh 에서 그러면 `PY=/usr/bin/python3: Command not found.` 가 난다.

**설치가 필요 없다면 여기서 STEP 1 로 넘어간다.** 인터넷이 막힌 서버가 많아
`pip install` 이 안 되는 경우가 흔한데, 그래도 위 방법이면 대부분 그냥 돌아간다.

새로 만들어야 할 때만:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[train]                 # numpy, pyyaml, torch
python -c "import numpy,yaml,torch; print('OK, cuda =', torch.cuda.is_available())"
```

**torch 설치가 안 되면 일단 넘어가도 된다.** `recon` / `list` / `build` / `base`
까지는 numpy + pyyaml 만으로 돌아간다. 데이터가 제대로 읽히는지 확인하는 데는
그걸로 충분하고, `train` 할 때만 torch 가 필요하다.

```bash
pip install numpy pyyaml                # 최소 설치
bash scripts/run.sh                     # 단계 목록 확인
```

---

## STEP 1. 폴더 구조 — 내 경우가 어느 것인지 고른다

빌더가 기대하는 최소 조건은 **딱 두 개**다:

1. `root` 밑에 **회로마다 폴더 하나**
2. 그 폴더 밑 어딘가에 **코너마다 리포트 하나** (하위 몇 겹이든 재귀로 찾음)

### 케이스 A — 표준 (권장)

**이게 회사 배치다. 이 경우 config 는 고칠 것이 없다.**

```
/user/s5e9965p5/academy_experiment/          ← root
├── si_corner_model/                         ← 이 repo
├── MFC_Timing_Report/
│   ├── setup/
│   │   ├── report.sspg_0p5000_125c_rcmax.rpt      ← 코너당 1개
│   │   ├── report.sspg_0p5000_125c_cmax.rpt
│   │   ├── report.sspg_0p5400_m25c_rcmin.rpt
│   │   ├── ...   (125 / m25 것이 섞여 있어도 됨 — 파일명 온도로 걸러진다)
│   │   └── xtalk/
│   │       ├── xt.sspg_0p5000_125c_rcmax.rpt      ← 코너당 1개, annotated 와 같은 코너 집합
│   │       └── ...
│   └── hold/                                ← hold 는 mode 를 바꿔 따로 돌린다
│       └── (setup 과 같은 구조)
├── MIF_Timing_Report/     (동일)
├── PERIC0_Timing_Report/  (동일)
├── pr_si/                 ← designs 에 안 적었으니 무시됨
└── spice/                 ← 무시됨
```

```yaml
mode: setup         # setup/ 와 setup/xtalk/ 를 읽고 cache/setup, runs/setup 에 쓴다
root: auto          # si_corner_model 이 회로들과 나란히 -> 자동
designs:            # pr_si / spice 가 섞여 있으니 auto 로 두지 말고 명시한다
  - MFC_Timing_Report
  - MIF_Timing_Report
  - PERIC0_Timing_Report
files:
  subdir: auto              # = <mode>
  crosstalk_subdir: auto    # = <mode>/xtalk
```

리포트가 `setup/` 없이 회로 폴더 바로 밑에 있으면 `files: {subdir: ""}` 로 두면 된다
(하위 몇 겹이든 재귀로 찾는다).

### 케이스 B — 회로 폴더 밑에 하위폴더가 있다

```
academy_experiment/cpu/reports/report.sspg_...rpt
academy_experiment/cpu/logs/...
```

```yaml
files: {subdir: ""}         # 그냥 두면 재귀로 찾는다 (logs 는 정규식에 안 걸려 무시됨)
# 또는 명시적으로:
files: {subdir: reports}
```

`subdir` 을 명시하면 탐색 범위가 좁아져 **엉뚱한 파일이 걸리는 사고**를 막을 수 있다.
`corner ... matched by more than one file` 에러가 나면 이걸 쓴다.

### 케이스 C — si_corner_model 이 딴 데 있다

```yaml
root: /user/s5e9965p5/academy_experiment     # 절대경로로 적는다
```
또는 파일 안 고치고: `env SI_ROOT=/user/... bash scripts/run.sh list`

### 케이스 D — root 밑에 회로가 아닌 폴더도 섞여 있다

```
academy_experiment/{cpu, gpu, lib, scripts, tmp}
```
`designs: auto` 는 `lib`, `scripts`, `tmp` 도 회로로 착각한다. 명시한다:

```yaml
designs: [cpu, gpu]
```

### 케이스 E — 레벨이 하위폴더고 파일명엔 전압만

```
academy_experiment/cpu/rcmax/xxx_tt0p5000v_125c.rpt
academy_experiment/cpu/cmax/ xxx_tt0p5000v_125c.rpt
```

```yaml
files:
  layout: levels
  annotated_suffix: .rpt
  voltage_regex: '_tt(0p\d+)v'
```

### 케이스 F — setup 과 hold 가 따로 있다

setup/hold 는 **분리 차원**이라 한 번에 못 섞는다. 대신 고칠 곳은 `mode` 한 줄뿐이다.

```yaml
mode: setup     # -> 읽기 <root>/<회로>/setup/ + setup/xtalk/ , 쓰기 cache/setup/ runs/setup/
mode: hold      # -> 읽기 <root>/<회로>/hold/  + hold/xtalk/  , 쓰기 cache/hold/  runs/hold/
```

파일을 안 고치고 그 실행에만 적용하려면 `--mode` 를 쓴다 (권장):

```bash
bash scripts/run.sh all                    # config 의 mode (보통 setup)
bash scripts/run.sh all --mode hold        # 이 실행만 hold
env SI_MODE=hold bash scripts/run.sh all   # 같은 뜻
```

`--mode` 는 되돌리는 걸 잊을 일이 없어서 안전하다. config 를 직접 고치는 방식도 된다:

```bash
vi config.yaml                 # mode: setup
bash scripts/run.sh all
vi config.yaml                 # mode: hold  (이 한 줄만)
bash scripts/run.sh all
```

**출력 경로가 `mode` 를 따라가므로 hold 결과가 setup 결과를 덮어쓰지 않는다.**
예전에는 `files.subdir` / `files.crosstalk_subdir` / `out.cache` / `out.runs` 를
각각 고쳐야 했고, subdir 만 바꾸고 out 을 잊으면 조용히 덮어썼다.

폴더 이름이 `setup`/`hold` 가 아니면(예: `reports/`) `files.subdir` 에 직접 적는다 —
`auto` 가 아닌 값은 그대로 쓰인다.

### 케이스 G — 이 중 어느 것도 아니다

리포트가 한 파일에 다 들어있다거나, 완전히 다른 도구의 출력이면
→ 텍스트 파서를 건너뛰고 npz 를 직접 만든다: [PARSING.md §7](PARSING.md).
그 뒤 STEP 5(base)부터는 동일하다.

---

## STEP 2. 정찰 — 눈으로 확인 (제일 먼저)

```bash
bash scripts/run.sh recon              # config.yaml 의 root 사용
bash scripts/run.sh recon /real/root   # root 만 임시 지정
```

`recon_out.txt` 가 생긴다. 안에 들어있는 것:

| # | 내용 | 확정할 config 키 |
|---|---|---|
| 1 | root 밑 폴더 목록 | `root`, `designs` |
| 2 | 회로별 구조 + 확장자별 개수 | `files.subdir` |
| 3 | **파일명 샘플** | `files.annotated_regex` |
| 4 | 코너 토큰 분포 (전압/온도/BEOL 실제 표기) | `corners.voltages`, `temps[].token`, `temps[].levels` |
| 5 | **리포트 본문 앞 120줄 + 키워드 개수** | 파서를 고쳐야 하는지 판정 → STEP 7 |
| 6 | 코너별 `Startpoint` 개수 | **경로 집합이 같은지** → STEP 7 |
| 7 | 크로스토크 파일 위치 | `files.crosstalk_subdir` |
| 8 | 파이썬/numpy/torch 환경 | — |

**막히면 `recon_out.txt` 를 통째로 공유하면 된다.** 거기 있는 정보로 config 와
파서를 확정할 수 있다.

---

## STEP 3. `config.yaml` 채우기 — 무엇을 어디에 적나

고칠 곳은 파일 위쪽 `[필수]` 부분뿐이다. **어떤 값이 어디로 가는지**부터:

| 적는 곳 | 무엇 | 이게 바뀌면 |
|---|---|---|
| `root`, `designs` | 회로 폴더들이 어디 있고 뭐가 회로인가 | **모델 개수**가 바뀐다 |
| `temps[]` | 온도 몇 개, 각 온도의 BEOL 레벨 | **모델 개수**가 바뀐다 |
| `corners.*` | 전압/레벨 좌표, 앵커 | 코너 그리드가 바뀐다 |
| `temps[].hidden_*` | **온도별로** 숨길 코너 | 검증 대상이 바뀐다 |
| `files.*` | 파일 찾는 법 | 리포트를 못 찾으면 여기 |

```yaml
root: auto                              # si_corner_model 이 회로들과 나란히 있으면 이대로
designs: auto                           # 또는 [회로1, 회로2, 회로3]

temps:
  - tag: "125"
    token: 125                          # 파일명 안의 온도 토큰
    levels: [rcmax, cmax]               # 125C 에 존재하는 BEOL 레벨
    hidden_corners: [[0.5, rcmax], [0.6, cmax]]        # 이 온도만의 홀드아웃
  - tag: m25
    token: m25
    levels: [rcmax, cmax, rcmin]         # m25C 는 3개
    hidden_corners: [[0.54, rcmin], [0.685, rcmax]]

corners:
  process: SSPG
  voltages: [0.5, 0.54, 0.6, 0.685]
  ref_voltage: 0.685                    # 앵커. 반드시 seen
  ref_level: cmax                       #   모든 온도에 존재하는 레벨이어야 함
  level_values: {rcmin: -1, cmax: 0, rcmax: 1}

files:
  layout: flat
  annotated_regex: auto                 # 순서·대소문자·구분자 무관
  crosstalk_subdir: null                # SI 위치 모르면 null
```

### 3-1. 온도마다 다른 모델 — 자동이다

온도는 **분리 차원**이라 `temps[]` 에 적은 개수만큼 모델이 따로 생긴다.
회로 3개 × 온도 2개 = **모델 6개**, 각각:

```
cache/<mode>/<회로>/<온도>/dataset.npz    ← 데이터도 따로
runs/<mode>/<회로>/<온도>/best.pt         ← 학습도 따로 (학습 중 체크포인트)
runs/<mode>/<회로>/model.pt               ← ★ 그 회로의 온도 전부가 이 한 파일에
runs/<mode>/_all/predictions_hidden.csv   ← 결과는 design,temp 열이 붙어 한 파일로
```

**밖에서는 회로 하나 = 모델 하나로 보인다.** 온도를 나누는 건 물리적 이유가 있다 —
125C 와 m25C 는 BEOL 레벨 집합부터 다르고(`rcmax,cmax` vs `rcmax,cmax,rcmin`),
온도가 2개뿐이라 그 축으로는 보간 다항식을 세울 수도 없다. 그래서 적합은 따로
하되, `run.sh bundle` 이 온도별 가중치를 회로당 `model.pt` 하나로 묶는다
(`run.sh all` 에 포함). `predict` 는 이 파일 하나만 있으면 모든 온도를 예측하므로,
넘길 때도 받을 때도 회로당 파일 하나만 신경 쓰면 된다.

**온도별로 다르게 줄 수 있는 것**: `levels`(필수 — 온도마다 레벨이 다름),
`hidden_corners` / `hidden_per_voltage` / `hidden_voltages` / `seen_voltages` /
`hidden_levels` / `query_corners`. 나머지(전압 목록, 앵커, 차수, 학습 설정)는
공통이다.

온도 하나만 돌리려면 `bash scripts/run.sh train --temp 125`.

### 3-2. 숨길 코너 — 온도마다 따로 (★ 여기가 헷갈리는 지점)

125C 는 8코너(4V × 2레벨), m25C 는 12코너(4V × 3레벨)로 **레벨 수가 다르다**.
그래서 "이 코너를 숨겨라" 를 전역 목록 하나로 쓸 수 없다 — `rcmin` 은 m25C 에만
있기 때문. 반드시 `temps[]` 안에 적는다.

**코너가 적을 땐 전압 행을 통째로 빼지 말 것.** 그 전압의 앵커가 전부 사라진다.
칸을 흩어서 빼면 전압마다 최소 하나가 남는다:

```yaml
temps:
  - tag: "125"
    hidden_corners: [[0.5, rcmax], [0.6, cmax]]    # 콕 집어 2칸
  - tag: m25
    hidden_per_voltage: 1                          # 전압마다 1칸씩 자동(=4칸)
```

몇 칸까지 되는지, 왜 그런지는 → **[HOLDOUT.md](HOLDOUT.md)** (이 주제 전용 문서).

### 3-3. 회로마다 데이터가 다를 때

| 상황 | 방법 |
|---|---|
| 회로마다 폴더만 다름 (보통) | 아무것도 안 해도 됨. `designs: auto` 가 다 찾는다 |
| 일부 회로만 돌리고 싶음 | `designs: [회로1, 회로2]` 또는 `run.sh build --design 회로1` |
| 회로마다 리포트가 하위폴더에 | `files.subdir: reports` (모든 회로에 공통 적용) |
| 회로마다 **코너·홀드아웃이 다름** | `designs:` 를 **매핑**으로 (아래). 파일은 그대로 하나 |

**기본은 전부 공통이다.** 회로 3개, 코너 20개(125C 8 + m25C 12), 홀드아웃까지
전부 같으면 `designs: auto` 로 두고 아무것도 더 안 적으면 된다.

회로 하나만 다르면 `designs:` 를 매핑으로 바꾼다. **적은 키만 덮어쓰고 나머지는
전역을 그대로 물려받으므로, config 를 복사할 필요가 없다:**

```yaml
designs:
  회로1: {}                                    # 전역 그대로
  회로2:
    files: {subdir: reports}                   # 리포트 위치만 다름
  회로3:
    corners: {voltages: [0.5, 0.6, 0.685]}     # 이 회로만 전압 3개
    temps:                                     # 홀드아웃도 이 회로만 따로
      - {tag: "125", token: 125, levels: [rcmax, cmax],
         hidden_corners: [[0.5, rcmax]]}
      - {tag: m25, token: m25, levels: [rcmax, cmax, rcmin],
         hidden_per_voltage: 1}
```

`run.sh list` 로 회로별 결과를 확인한다:

```
  ── 회로1/125   hidden 2개   전체 8 = seen 6 + hidden 2
  ── 회로3/125   hidden 1개   전체 6 = seen 5 + hidden 1     ← 전압 3개라 6코너
```

덮어쓸 수 있는 것: `corners` / `temps` / `files` / `parsing` / `base` / `model` /
`train` / `split`. 회로 하나만 돌리려면 `run.sh all --design 회로3`.

### 3-4. PT 결과를 가져와서 쓰는 구조일 때

PT 가 이 서버에서 안 돌고 **결과만 가져오는** 경우, 필요한 건 리포트 파일뿐이다.
가져올 때 지킬 것:

1. **회로 폴더 구조를 유지**해서 `root` 밑에 놓는다 (`<root>/<회로>/...`).
2. **한 회로의 전 코너를 다 가져온다.** 코너 하나가 빠지면 `min_seen` 가드가
   `degenerate split` 로 잡아준다 (조용히 부실하게 학습되지 않게).
3. **파일명에 전압·온도·레벨 토큰이 남아 있어야** 한다. 이름을 바꿔야 하면
   그 세 가지만 유지하면 순서·대소문자는 상관없다.
4. 크로스토크(SI) 리포트도 같이 가져오면 `files.crosstalk_subdir` 에 위치를
   적는다. 없으면 `null` 로 두고 SI 없이 먼저 돌린다.
5. 가져온 뒤 **`bash scripts/run.sh check`** 로 본문이 파서와 맞는지 먼저 본다.

리포트가 아주 크면 `dataset.npz`(캐시)만 만들어 옮기는 것도 방법이다 —
`build` 는 numpy 만 있으면 되므로 리포트가 있는 쪽에서 돌리고, 그 npz 를
`cache/<회로>/<온도>/dataset.npz` 로 복사하면 `base`/`train` 부터 이어서 된다.

## STEP 4. `list` 로 검산 — 파일 안 건드림

```bash
bash scripts/run.sh list
```

실제 출력은 이렇다 (회사와 같은 배치로 리허설한 결과 그대로):

```
root    : /user/s5e9965p5/academy_experiment
task    : slack    models: 6    process: SSPG
voltages: [0.5, 0.54, 0.6, 0.685]    levels: {'rcmin': -1, 'cmax': 0, 'rcmax': 1}
anchor  : 0.685V x cmax  (항상 seen)

  ── MFC_Timing_Report/125  [SI:on ]
     reports : /user/s5e9965p5/academy_experiment/MFC_Timing_Report/setup
     levels  : ['rcmax', 'cmax']   ref: SSPG_0p685V_cmax   temp token: 125
     out     : cache/setup/MFC_Timing_Report/125/dataset.npz  |  runs/setup/MFC_Timing_Report/125
     hidden  : 2개 SSPG_0p54V_rcmax, SSPG_0p6V_cmax
     corners : 전체 8 = seen 6 + hidden 2   (min_seen 가드 6)
     basis   : v^3 x level^1 까지 -> 최대 6 파라미터 [...]  ⚠ seen 이 파라미터 수 이하 -- ...
               (최종 기저는 build 때 seen-LOO 로 선택된다 -- run.sh base 로 확인)
     base    : weighting=adaptive  cross_max_degree=2
     files   : 디렉토리 존재, 파일 40개
```

`basis` 줄의 **⚠ 는 정상이다** — 여기 적힌 건 "최대 이만큼까지 쓸 수 있다"는 상한이고,
실제 기저는 `build` 때 seen-LOO 로 더 작게 골라진다(125C 는 5 파라미터). 확정된
기저와 그 성적은 `run.sh base` 가 찍는다.

**여기서 확인할 것 5가지:**

1. `models:` 개수가 맞나 (회로 수 × 온도 수 = 3 × 2 = **6**)
2. `files : 디렉토리 존재` 인가 — `(!) 디렉토리 없음` 이면 `root`/`designs`/`subdir`
3. `corners : 전체 N` 이 예상과 맞나 (전압 수 × 레벨 수). 125 는 4×2=8, m25 는 4×3=12
4. `hidden : 2개` 가 온도마다 의도한 코너인가
5. `[SI:on ]` 인가 — `[SI:off]` 면 `xtalk/` 를 못 찾은 것

틀린 게 있으면 config 고치고 다시 `list`. 여기서 맞을 때까지는 build 로 안 넘어간다.

---

## STEP 5. `build` → `base` — 데이터가 제대로 읽혔는지 (GPU 불필요)

```bash
bash scripts/run.sh build      # 리포트 -> cache/<mode>/<회로>/<온도>/dataset.npz
bash scripts/run.sh base       # OLS base 오차 (numpy만, 수 초)
```

`build` 성공 로그:
`wrote cache/setup/MFC_Timing_Report/125/dataset.npz: N=<경로수> C=8 S=... A=...`
→ **C 가 STEP 4 의 코너 수와 같은지 확인.**

`base` 출력:

```
    hidden SSPG_0p54V_cmax        12.431 ps
    hidden SSPG_0p54V_rcmax       15.882 ps
    [hidden mean]                 14.156 ps  (worst 15.882)
    [seen-LOO   ]                  3.204 ps  (worst 5.1)
```

**수치가 상식적인지**만 보면 된다 (경로 slack 규모 대비 수~수십 ps). 터무니없으면
파싱이나 코너 정의가 틀린 것이니 STEP 3 으로 돌아간다. 읽는 법은 [OLS.md §7](OLS.md).

### build 에러 대응

| 증상 | 원인 / 고칠 곳 |
|---|---|
| `regex matched NO filenames` | `files.annotated_regex` — recon 의 파일명에 맞춘다 |
| `regex matched some filenames` | 정규식은 맞음. `process` / `temps[].token` / `temps[].levels` 중 하나가 실제 토큰과 불일치 |
| `corner ... matched by more than one file` | 정규식이 헐렁 → `files.subdir` 을 더 깊게 |
| `ref corner ... not in the discovered grid` | `ref_voltage`/`ref_level` 이 실제 코너에 없음 |
| `degenerate split: N seen < min_seen=M` | 리포트 누락, 또는 `voltages`/`levels` 선언이 실제와 다름 |
| **`파싱된 경로가 0개`** | 파일은 찾았는데 **본문**이 다름 → **STEP 7** |

---

## STEP 6. `train` → 결과

```bash
bash scripts/run.sh all                # ★ build -> base -> train -> bundle -> predict -> merge

# 단계별로 하고 싶으면:
bash scripts/run.sh train                              # 학습 (온도별로 best.pt)
bash scripts/run.sh bundle                             # 회로당 model.pt 하나로 묶기
bash scripts/run.sh predict                            # 히든 코너 예측
bash scripts/run.sh merge                              # 전 회로·전 온도를 한 파일로

# 회로/온도만 골라서:
bash scripts/run.sh all --design MFC_Timing_Report
bash scripts/run.sh train --design MFC_Timing_Report --temp 125
bash scripts/run.sh predict --corners all              # seen 코너까지 다 예측
```

한 모델이 실패해도 나머지는 계속 돌고, 끝에 실패 목록을 찍고 exit 1 한다.

결과:

```
runs/<mode>/_all/predictions_hidden.csv   ★ 전 회로·전 온도 통합본
runs/<mode>/_all/summary.json             ★ 모델별 지표
runs/<mode>/<회로>/model.pt               ★ 넘길 가중치 (온도 전부 포함, 회로당 하나)
runs/<mode>/<회로>/<온도>/                 온도별 개별 (best.pt, summary.json, predictions_*.csv)
```

```
design,temp,path_key,corner,truth_ps,model_ps,model_err_ps
MFC_Timing_Report,125,A->B,SSPG_0p54V_rcmax,12.000,12.500,0.500
MFC_Timing_Report,m25,A->B,SSPG_0p685V_rcmin,20.000,19.100,-0.900
```

`model_ps` 가 최종 예측값이다. **base 수치는 여기 안 나온다** — 모델 수치와
헷갈리지 않게 분리했다. base 는 `run.sh base` 로만 본다.

`merge` 는 끝에 **코너별 성적표**를 찍고 같은 내용을 `summary.json` 의
`by_corner` 에 넣는다. 모델(회로x온도)은 내부 분할일 뿐이라, 넘길 때 궁금한
"이 코너가 얼마나 잘 맞았나" 를 코너 기준 한 표로 본다:

```
  코너별 성적 (모델이 아니라 코너 기준)
    회로                    온도    코너                       경로       MAE     worst
    MFC_Timing_Report     125   SSPG_0p54V_rcmax       3000   14.00ps   24.65ps
    MFC_Timing_Report     125   SSPG_0p6V_cmax         3000    6.15ps   14.81ps
    MFC_Timing_Report     m25   SSPG_0p5V_cmax         3000   13.78ps   27.46ps
    MFC_Timing_Report     m25   SSPG_0p685V_rcmin      3000    8.99ps   18.42ps
    전체                                                12000   10.73ps   27.46ps
```

`summary.json` 은 두 부분이다:

| 키 | 내용 |
|---|---|
| `by_corner` | ★ 위 표. 코너마다 `mae_ps` / `worst_ps` / `n_paths` |
| `by_model` | 모델별 상세 (`hidden_mae_ps`, `best_epoch`, `si_branch` ...) |

정답이 없는 `query_corners` 는 `n_paths` 만 세고 `mae_ps` 는 비어 있다.


### 학습을 중간에 끊었을 때

**끊어도 된다. 그때까지의 최선이 남아 있다.** `best.pt` 는 **매 epoch**,
히든 코너 성적이 좋아질 때만 덮어쓰므로 언제 끊든 마지막 개선 지점이 파일로 남는다.

> 주의: epoch 을 히든 코너로 고르므로 **보고되는 히든 수치는 낙관적이다** —
> 고르는 데 쓴 그 값의 최소치이기 때문이다. 학습이 끝날 때 그 사실을 함께 찍고,
> `summary.json` 에 `selected_on: hidden_corners` 로 남는다.

```bash
# Ctrl-C 로 끊은 뒤 -- 학습을 다시 할 필요 없다
bash scripts/run.sh bundle       # 그때까지의 best.pt 를 model.pt 로
bash scripts/run.sh predict      # 예측 다시 뽑기  ★ 반드시 다시 돌릴 것
bash scripts/run.sh merge        # 코너별 성적표
```

**`predict` 를 꼭 다시 돌려야 한다.** `predictions_*.csv` 는 학습이 끝까지
갔을 때만 자동으로 쓰인다. 안 돌리면 이전 실행의 예측이 그대로 남아 있고,
새 체크포인트와 아귀가 안 맞는다.

같은 이유로 `summary.json`(모델별)도 끝까지 간 실행에서만 갱신된다. `merge` 가
이걸 감지해서 짚어준다:

```
(!) by_model 이 오래됨 (best.pt 보다 이전): ['MFC_Timing_Report/125']
    학습을 중간에 끊었으면 그 모델의 by_model 수치는 이전 실행 것이다.
    코너별 성적(by_corner)은 방금 예측에서 뽑은 값이라 정확하다.
```

**`by_corner` 를 보면 된다** — 방금 만든 예측 CSV 에서 뽑으므로 항상 맞다.

이어서 학습하는(resume) 기능은 없다. `run.sh train` 을 다시 치면 **처음부터**
다시 학습한다. 지금 결과가 마음에 들면 위 세 단계로 마무리하고, 더 돌리고
싶으면 `train` 을 다시 치면 된다 (기존 `best.pt` 는 더 좋아질 때만 덮인다 --
정확히는 새 실행이 자기 기준으로 처음부터 비교하므로, 지금 것을 지키려면
`model.pt` 를 먼저 만들어 두거나 `best.pt` 를 복사해 둔다).

### 실전 예측 — 측정 안 한 코너

```yaml
corners:
  query_corners: [[0.57, cmax], [0.62, rcmax]]   # 정답 없는 코너
```
```bash
bash scripts/run.sh build      # 코너가 추가되므로 재빌드
bash scripts/run.sh predict
```
`truth_ps` 는 빈칸이고 `model_ps` 만 채워져 나온다. 지표에는 안 들어간다.

---

## STEP 7. ★ 코드를 고쳐야 하는 유일한 경우

`파싱된 경로가 0개` 에러가 났을 때다. 에러 메시지가 파일 앞부분을 같이 찍어준다.

`### FIXED_PATH` 헤더는 *고정 경로 리스트를 모든 코너에서 다시 annotate 했다*는
표시인데, **중요한 건 헤더가 아니라 코너마다 경로 집합이 같은가** 이다. 이 모델의
전제가 "같은 경로를 여러 코너에서 관측했다" 이기 때문이다.

```bash
cd <회로폴더>
# ① 코너마다 경로 수가 같은가
for f in report.sspg_*_125c_rcmax.rpt; do echo -n "$f : "; grep -c 'Startpoint' "$f"; done
# ② 실제로 같은 경로들인가
grep -E 'Startpoint|Endpoint' report.sspg_0p5000_125c_rcmax.rpt | head -20 > /tmp/a
grep -E 'Startpoint|Endpoint' report.sspg_0p6850_125c_rcmax.rpt | head -20 > /tmp/b
diff /tmp/a /tmp/b && echo "SAME (좋음)" || echo "DIFFERENT (재-annotate 필요)"
```

| 결과 | 조치 |
|---|---|
| **같다** | 헤더만 없는 것. `Startpoint→Endpoint` 로 키를 만드는 모드를 `annotated.py` 에 추가하면 된다. 작은 수정 |
| **다르다** | 코너별 worst path 라 전제가 깨진다. 고정 경로로 재-annotate 한 리포트가 필요 (옆 `pt_si_re/` 에 그 파이프라인 있음). **파서로 우회 불가** |
| **SSTA 라 열이 더 붙음** | 우선 nominal/mean 만 뽑아 기존 구조에 태울 것. sigma 예측은 그 다음 |

자세한 건 [PARSING.md §4·§5](PARSING.md).

---

## STEP 8. 크로스토크(SI) 붙이기

리포트를 `<root>/<회로>/` 안 아무 하위폴더에 두고 이름만 알려준다:

```
<root>/boomcore/
├── report.sspg_0p5000_125c_rcmax.rpt     ← annotated
└── xtalk/                                 ← 크로스토크
    └── xt.sspg_0p5000_125c_rcmax.rpt
```

```yaml
files:
  crosstalk_subdir: xtalk     # <root>/<회로>/xtalk (아래 몇 겹이든 재귀)
  crosstalk_regex: auto       # 파일명 규칙은 annotated 와 동일
```

```bash
bash scripts/run.sh build      # S=<스테이지수> A=<aggr슬롯> 이 찍히면 SI 켜진 것
bash scripts/run.sh train
bash scripts/run.sh sweep      # lambda_si {0,0.1,1,10} 비교
```

지킬 것:

- **annotated 와 코너 집합이 정확히 일치** (아니면 `I1: corner sets differ`)
- `### FIXED_PATH` 의 idx·key 와 `# Slack:` 이 annotated 와 같아야 함 (I2/I3)
- 파일명 접두사는 아무거나. 전압·온도·레벨 토큰만 있으면 됨
- 이 폴더는 annotated 탐색에서 **자동 제외**되므로 회로폴더 안에 둬도 됨
- **hold 면 델타가 음수**여야 함 (`-crosstalk -min`). 아니면 조용히 틀림

위치를 모르면 `crosstalk_subdir: null` 로 두고 SI 없이 먼저 돌린다
(`summary.json` 에 `"si_branch": false`). 나중에 두 줄만 채우고 재빌드하면 켜진다.

파일 내부 형식(탭 14열)과 SI feature 가 만들어지는 원리는
[PARSING.md §6](PARSING.md).

---

## 체크리스트

```
[ ] STEP 0  si_corner_model 을 회로폴더 옆에 두고  bash scripts/find_python.sh
[ ]         쉘 확인: bash 면 export PY=... / csh 면 setenv PY ...
[ ] STEP 1  내 폴더 구조가 A~G 중 어느 케이스인지 확인 (회사 배치 = 케이스 A)
[ ] STEP 2  bash scripts/run.sh recon   -> recon_out.txt
[ ] STEP 3  config.yaml: mode/root/designs/temps/corners/files
[ ]         + 온도별 홀드아웃 (temps[].hidden_corners)  -> docs/HOLDOUT.md
[ ] STEP 4  bash scripts/run.sh list    -> models 6개 / corners / hidden 2개 / [SI:on]
[ ] STEP 5  build -> C 확인, base -> 수치 상식적인지
[ ] STEP 6  bash scripts/run.sh all     -> runs/<mode>/_all/predictions_hidden.csv
[ ]                                        + runs/<mode>/<회로>/model.pt
[ ] STEP 7  파싱 0개면: 코너 간 경로 집합 동일한지 확인
[ ] STEP 8  SI: crosstalk_subdir 채우고 재빌드 -> S=... 확인
[ ] 학습을 중간에 끊었다면: bundle -> predict -> merge (predict 를 꼭 다시)
[ ] hold 도 돌린다면: `--mode hold` 를 붙여 위를 반복 (또는 config 의 mode 를 바꾼다)
```

## 어디를 볼지

| 궁금한 것 | 문서 |
|---|---|
| **어떤 코너를 숨길지 / 온도마다 따로 주는 법** | **[HOLDOUT.md](HOLDOUT.md)** |
| config 키 전부 / 에러표 | [CONFIG.md](CONFIG.md) |
| base 가 뭘 하나 / 차수·대역폭 튜닝 / base 수치 읽는 법 | [OLS.md](OLS.md) |
| 파일명·본문 형식 / FIXED_PATH / npz 직접 만들기 | [PARSING.md](PARSING.md) |
| 명령 목록 | `bash scripts/run.sh` (인자 없이) |
