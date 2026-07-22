# 사용법, 설정 & 실행 가이드

설치, 데이터셋 빌드, 학습, 그리고 돌릴 수 있는 모든 config 노브. 내 데이터를
넣는 방법은 [PARSING.md](PARSING.md) 참고.

---

## 0. 새 서버 퀵스타트 — clone부터 결과까지 (새 데이터 기준)

아무것도 없는 서버에서 그대로 따라 치면 되는 전체 시퀀스:

```bash
# ── 0) 서버 준비물: git, Python 3.9+  (GPU 쓰려면 NVIDIA 드라이버; 없으면 자동 CPU)

# ── 1) 클론
git clone <repo-url> si_corner_model
cd si_corner_model

# ── 2) 환경 (아래 셋 중 아무거나 — conda는 필수 아님)
# 방법 A: conda가 있으면
conda create -n si python=3.10 -y && conda activate si
pip install -e .[train]                  # pyproject.toml을 읽어 numpy, pyyaml, torch 설치

# 방법 B: conda가 없으면 — 파이썬 내장 venv (모든 Python 3에 포함)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[train]
#   (pip install -r requirements.txt 로 의존성만 깔아도 됨 — 같은 목록)

# 방법 C: 이미 numpy/torch/pyyaml 있는 환경 재사용 → 설치 자체가 불필요
#   (스크립트가 repo 루트에서 python -m 으로 실행하므로 pip install 없이도 동작)

# GPU 서버 참고: pip 기본 torch가 서버 CUDA와 안 맞으면 맞는 빌드 지정, 예:
#   pip install torch --index-url https://download.pytorch.org/whl/cu121
#   (GPU 없거나 실패해도 코드는 자동으로 CPU 폴백 — 느릴 뿐 동작함)

# 환경 확인
python -c "import numpy, yaml, torch; print('env OK, cuda =', torch.cuda.is_available())"

# ── 3) 새 데이터용 config 작성
mkdir -p configs/mycompany
cp configs/TEMPLATE.yaml configs/mycompany/setup_25c.yaml
vi configs/mycompany/setup_25c.yaml
#   반드시 채울 것:
#     data.annotated_dir / crosstalk_dir  ← 새 서버의 데이터 절대경로
#     data.temp, data.rc_corners          ← 레벨 하위폴더 이름 (그 데이터의 실제 이름)
#     data.ref_corner, data.cache
#     split.seen_voltages                 ← 측정된 V 그리드
#     base.axes                           ← ref/order/levels (그 데이터 기준)
#     train.out_dir
#   데이터 형식이 다르면 → docs/PARSING.md §1.1 판단트리부터

# ── 4) 빌드 (리포트 → dataset.npz)
bash scripts/build.sh configs/mycompany/setup_25c.yaml
#   다른 파이썬 쓰려면: PY=/path/to/python bash scripts/build.sh ...

# ── 5) 학습 (첫 실행 때 si_features.npz 자동 생성)
bash scripts/train.sh configs/mycompany/setup_25c.yaml

# ── 6) 결과 확인
cat runs/mycompany/setup_25c/v1/summary.json
#   hidden_base_mae_ps (base만) vs hidden_mae_ps (모델) 비교

# ── 7) (선택) 파서/기저 자가 테스트
python -m pytest tests/ -q
```

빌드에서 에러가 나면: `no corners discovered` → config의 경로/`patterns` 문제,
`I1: corner sets differ` → annotated/crosstalk 폴더 불일치. 전체 진단은
[PARSING.md](PARSING.md) §7·§9와 아래 §7 트러블슈팅.

---

## 1. 설치

```bash
# Python 3.9+ 아무 환경 (conda든 venv든 시스템 파이썬이든)
pip install -e .            # 코어: numpy, pyyaml
pip install -e .[train]     # + torch (학습/추론에 필요)
pip install -e .[test]      # + pytest

# 또는 패키지 설치 없이 의존성만:
pip install -r requirements.txt
```

의존성의 원본 명세는 `pyproject.toml`이고, `requirements.txt`는 같은 목록의
편의용 사본. 파서와 OLS base는 numpy만 필요; 신경망 학습만 torch 필요.
CUDA GPU가 있으면 자동 사용, 없으면 CPU.

---

## 2. 개념: config 하나 = 모델 하나

엔진은 **연속축**(전압 + BEOL/RC, 또는 전압 + 온도) 위에서 **측정 안 된 코너**의
경로별 타이밍을 예측해. 그 외에 *별도* 모델이 되어야 하는 것 — **온도(분리할 때),
공정, setup vs hold** — 은 축이 아니라 각각 다른 config/캐시/run.

```
축   (보간됨)      → base.axes          → 다항식에 들어감
분리 (별도 모델)   → config 하나씩       → 예: setup_m40, setup_125, hold_m40 ...
task              → slack | slew        → slew는 별도 폴더/config
```

즉 "14nm setup+hold를 2온도 + slew를 2온도" = slack config 4개 + slew config 2개,
전부 하나의 엔진 공유.

---

## 3. 명령어

스크립트는 config 경로를 받아 파일명(`*slew*`)으로 slack/slew 자동 분기. `PY`에
쓸 인터프리터 지정.

```bash
PY=/root/.conda/envs/torch310/bin/python

# 1) 모델 하나의 캐시 빌드
PY=$PY bash scripts/build.sh configs/beol14/setup_m40.yaml
#    -> cache/beol14/setup_m40/dataset.npz  (+ 첫 학습 때 si_features.npz)

# 2) 학습
PY=$PY bash scripts/train.sh configs/beol14/setup_m40.yaml
#    -> runs/beol14/setup_m40/v1/best.pt + summary.json

# slew (slew 빌더/학습기로 자동 분기)
PY=$PY bash scripts/build.sh configs/beol14/slew_m40.yaml
PY=$PY bash scripts/train.sh configs/beol14/slew_m40.yaml

# 3) 예측값 뽑기 (학습 없이, 저장된 best.pt에서) — (경로, 코너)별 CSV/NPZ
PY=$PY bash scripts/predict.sh configs/beol14/setup_m40.yaml --corners hidden
#    --corners hidden|seen|all, --ckpt <경로>, --out-dir <디렉토리> 선택 가능
#    -> predictions_hidden.csv / .npz (아래 §5)

# 4) SI aux-loss 가중치 스윕 (slack 전용): lambda ∈ {0, 0.1, 1, 10}
PY=$PY bash scripts/sweep.sh configs/beol14/setup_m40.yaml

# 5) (선택) OLS base 자체 품질 점검 — 학습 전 sanity check용 독립 도구
#    base 수치는 여기서만 출력됨 (학습 로그/예측 출력엔 절대 안 나옴)
$PY -m si_model.training.base_check --config configs/beol14/setup_m40.yaml

# 테스트 (파서 + OLS 기저; numpy-only는 항상 실행)
$PY -m pytest tests/ -q
```

모듈 직접 호출 (스크립트가 부르는 것), 오버라이드 플래그 포함:

```bash
$PY -m si_model.parsing.build_dataset   --config configs/beol14/setup_m40.yaml
$PY -m si_model.tasks.slack.train       --config configs/beol14/setup_m40.yaml \
       --lambda-si 1.0 --seed 42 --enc-blocks 3 --out-dir runs/beol14/setup_m40/exp1
$PY -m si_model.tasks.slack.predict     --config configs/beol14/setup_m40.yaml --corners hidden
$PY -m si_model.tasks.slew.build_slew   --config configs/beol14/slew_m40.yaml
$PY -m si_model.tasks.slew.train_slew   --config configs/beol14/slew_m40.yaml
$PY -m si_model.tasks.slew.predict      --config configs/beol14/slew_m40.yaml --corners hidden
```

---

## 4. Config 레퍼런스

모델 YAML은 `configs/_defaults.yaml` **위에** deep-merge되니, 다른 것만 적으면 됨.

### `data`
| 키 | 의미 |
|---|---|
| `annotated_dir` | annotated 리포트 디렉토리 (안에 레벨 하위폴더) |
| `crosstalk_dir` | crosstalk 리포트 디렉토리 (slew는 생략) |
| `temp` | 이 모델이 담당하는 온도, 예: `m40` / `125` (분리 차원) |
| `corner_prefix` | 코너 라벨/파일명의 공정 토큰 (기본 `TT`; 다른 데이터에선 `FFPG`/`SSPG` 등 — 공정도 분리 차원이라 접두사마다 config 하나) |
| `rc_corners` | 2번째 축 레벨 하위폴더 이름, 예: `[Cmin, Cnom, Cmax]` |
| `ref_corner` | 경로 선택 앵커 라벨; 반드시 SEEN 코너 |
| `query_corners` | **순수 추론 코너**: 측정 파일이 없는 코너를 라벨 또는 `[v, 레벨]`로 나열 (예: `[TT_0p71V_Cnom, [0.63, Cmax]]`). NaN 측정으로 그리드에 추가되고, 항상 hidden, 지표에서 제외, 예측값만 출력(truth 빈칸) |
| `cache` | 출력 `.npz` 경로 |
| `patterns` | 선택: `{annotated_suffix, crosstalk_suffix, voltage_regex}` 오버라이드 |

### `split`
| 키 | 의미 |
|---|---|
| `seen_voltages` | 측정된(coarse) V 그리드; 그 외 V는 전부 hidden |
| `hidden_voltages` | 대안: 명시적 hidden V 리스트 |
| `hidden_rc` / `hidden_temps` / `hidden_axis1` | 홀드아웃할 2번째 축 레벨 |

전압 규칙: `seen_voltages`(배포: 사이 fine 코너 예측) **또는** `hidden_voltages`
중 하나.

### `base` — OLS base
| 키 | 의미 |
|---|---|
| `axes` | 연속축 리스트; 축 0은 반드시 전압. 각각: `name`, `ref`, `order`, 선택 `levels`(범주형 맵), `fit_scale`, `token_scale`, `gap_cap` |
| `weighting` | `plain` \| `local` \| `adaptive` (최선; 코너별 대역폭) |
| `cross_terms` | 교차항 포함 (`dv·drc`, ...); 기본 true |
| `cross_max_degree` | 교차항 총차수 상한; 기본 3 |
| `bandwidth` | `weighting: local`용 `[bw0, bw1]` |
| `adaptive_grid` | adaptive용 `[bw0, bw1]` 후보 리스트 (+ `null` = 전역) |
| `adaptive_k` | 라벨-free 대역폭 선택용 kNN 이웃 수 (6) |
| `adaptive_amp_ratio` | 외삽 가드: 분산 > 이 값 × 전역인 bw 거부 (1.5) |
| `adaptive_clip_frac` | 후보 필드를 [min,max] ± 이 값×범위로 clip (0.3) |

**다항식 차수(3차/4차 선택)** = `axes[i].order`. 기저는 자동 생성되고, 가진
seen 레벨보다 많은 차수가 필요한 항은 자동 제거+로그(예: seen V 4레벨에서 `dv4`,
RC 3레벨에서 `drc3`). `terms:` 리스트를 손으로 적을 일 없음.

### `model`
`enc_blocks`(GNN 홉, 3), `d_model`(64), `n_heads`(4), `dropout`(0.10),
`aggr_slots`, `si_n_time`(SI worst-instant 샘플, 16),
`si_elec_thresh`(F6 필터, 0.01), 선택 `enc_dim`(128).

### `train`
`seed`, `lr`(2e-3), `weight_decay`(1e-4), `batch_paths`(256), `epochs`(100),
`lambda_si`(SI aux 가중치, 1.0), SI 담금질 스케줄
(`si_w_ns0/1`, `si_tau_ps0/1`, `si_w_elec0/1`), `device`, `out_dir`,
선택 `split_seed`(경로 분할; 앙상블 멤버 간 고정).

---

## 5. 출력물 & 지표

```
runs/<dataset>/<model>/v1/
  best.pt                  # hidden 난이도 모니터 최고점의 {model, enc, cfg, epoch}
  summary.json             # train/val/test/all의 hidden 코너 지표
  predictions_hidden.csv   # (경로, 코너)별 예측값 — 학습 종료 시 자동 저장
  predictions_hidden.npz   # 같은 내용의 배열판 (path_keys, corners, truth/base/model)
```

**predictions CSV 열 (slack):** `path_key, corner, truth_ps, model_ps, model_err_ps`
- `model_ps` = **최종 예측값** — 이 열이 실사용 출력.
- `truth_ps`/`model_err_ps` = 정답(측정값)이 **있을 때만** 채워짐.
  `query_corners`처럼 측정 없는 순수 추론 코너는 빈칸이고 예측값만 나옴.
- slew판 열: `truth_ns, model_ns, model_ape_pct` (%오차).
- **OLS base 값은 어떤 출력에도 포함되지 않음** — base 자체 품질을 따로
  점검하려면 독립 도구를 사용:
  `python -m si_model.training.base_check --config <cfg>` (numpy만 필요;
  hidden/seen-LOO base 오차만 별도로 출력).

학습 없이 다시 뽑으려면 `scripts/predict.sh` (또는 `-m ...predict`) —
`--corners hidden|seen|all` 로 대상 코너 선택 (seen은 자기 토큰을 가린 LOO식 예측).

- **Slack**: `hidden_mae_ps`(모델) vs `hidden_base_mae_ps`(base만) vs
  `hidden_worst_ps`, 그리고 SI MAE. base-only가 바닥값; 신경망이 그 아래로
  내려야 함.
- **Slew**: `hidden_slew_mape` vs `hidden_base_slew_mape`, 그리고
  `hidden_cap_fetch_mape`와 base보다 나빠진 코너 수.

모델 선택은 hidden 난이도에서 **seen 코너 정보만** 사용(타깃의 축 행을 추가
마스킹); hidden 코너는 절대 참조 안 함.

---

## 6. 새 데이터셋 / 분리 / task 추가

1. **새 데이터셋** → `configs/TEMPLATE.yaml`에서 `configs/<dataset>/` 만듦;
   `data.*`, `base.axes`(+ `levels`), `split.*` 설정. PARSING.md 참고.
2. **새 분리**(다른 온도/공정) → 형제 config 복사, `data.temp` / 디렉토리 /
   `cache` / `out_dir` 변경. 그냥 또 하나의 모델 인스턴스.
3. **새 task** → slack과 slew는 `si_model/tasks/`에 있음. 새 task는 거기에
   모델 + 학습을 추가하고 공유 base(`training/loo.py`)·인코더·corr head를 재사용.

---

## 7. 트러블슈팅

| 증상 | 해결 |
|---|---|
| 빌드에서 `no corners discovered` | `annotated_dir`/레벨 이름 틀림, 또는 파일명이 `patterns.voltage_regex`와 불일치 |
| `I1: corner sets differ` | annotated vs crosstalk 폴더가 같은 코너를 안 담음 |
| `ref corner ... must be seen` | `ref_corner`가 hidden에 들어감 — seen으로 바꾸거나 `split` 수정 |
| `degenerate split` | seen 코너 8개 미만 — `seen_voltages` 넓혀 |
| `[BASIS] dropped ... rank-deficient` | 정상: 그 차수에 seen 레벨 부족(정보성) |
| 커스텀 스크립트에서 CUDA RNN backward 에러 | backward 전에 `model.train()` 호출(BiGRU는 train 모드 필요) |
| base-only MAE가 높음 | 축별 `ref`와 `adaptive_grid` 대역폭이 그리드 간격과 맞는지 확인 |
