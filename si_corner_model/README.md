# si_corner_model — 측정 안 한 코너의 경로별 타이밍 예측

한 회로를 성긴 코너 그리드에서 측정해두면, **측정하지 않은 (전압 × BEOL) 코너**의
경로별 slack 을 SI(크로스토크) 포함해서 예측한다.

```
예측 = OLS_base(V, BEOL)                       # 경로별 가중 OLS, leave-one-out
     + gate · [ CorrHead(측정된 코너들 attention)   # set-invariant 잔차
              + SI_branch ]                        # 크로스토크 점프 (SI 자료 있을 때만)
```

**축 vs 분리** — 이게 전부다:

| | 처리 |
|---|---|
| 전압, BEOL 레벨 | **연속 축** → 다항식으로 보간 (측정 안 한 값을 예측) |
| 온도, 공정, 회로, setup/hold | **분리** → 각각 별도 모델 |

`config.yaml` 에 회로 목록과 온도 목록을 적으면 **(회로 × 온도) 조합마다 모델이
하나씩 자동 생성**된다. 회로 3개 × 온도 2개 = 모델 6개인데 고치는 파일은 하나다.

---

## 파일은 딱 두 개만 보면 된다

```
config.yaml          ★ 설정은 여기 하나뿐. 도착해서 고칠 것도 여기뿐.
scripts/run.sh       ★ 실행은 이거 하나뿐.

si_model/            엔진. 리포트 형식이 아주 다르지 않으면 열 일 없다.
tests/               python -m pytest tests/ -q

docs/START.md        ★ 도착해서 처음부터 (폴더 구조 케이스별 · 단계별 · 체크리스트)
docs/HOLDOUT.md      어떤 코너를 숨길지 · 온도마다 따로 주는 법
docs/CONFIG.md       config.yaml 키 전부 + 에러표
docs/OLS.md          base(예측의 뼈대)가 뭘 하는지 + 차수/대역폭 튜닝
docs/PARSING.md      리포트 읽히는 법 + FIXED_PATH 문제 + npz 직접 만들기
```

---

## 도착해서 하는 순서

**[docs/START.md](docs/START.md) 를 위에서 아래로 따라가면 된다** — 폴더 구조
케이스별 대응, recon → config → 검산 → 학습까지 전부 거기 있다. 요약만 하면:

```bash
bash scripts/run.sh                # 단계 목록 (인자 없이)
bash scripts/run.sh recon          # ① 데이터 정찰 -> recon_out.txt
vi config.yaml                     # ② recon 값을 옮겨 적기 ([필수] 표시된 부분만)
bash scripts/run.sh list           # ③ 검산 (코너 수/파라미터 수까지, 파일 안 건드림)
bash scripts/run.sh build          # ④ 캐시     (numpy만)
bash scripts/run.sh base           # ⑤ base 점검 (numpy만, 수 초) -- 학습 전 필수
bash scripts/run.sh train          # ⑥ 학습     (torch)
# 또는 ④~⑥ 한 방에:  bash scripts/run.sh all
```

회로/온도만 골라서: `run.sh train --design cpu --temp 125`
경로만 임시로: `SI_ROOT=/real/path bash scripts/run.sh list`

### 결과

```
runs/_all/predictions_hidden.csv    ★ 전 회로·전 온도 통합본
runs/_all/summary.json              ★ 모델별 지표
runs/<회로>/<온도>/                  개별 (best.pt, summary.json, predictions_*.csv)
```

```
design,temp,path_key,corner,truth_ps,model_ps,model_err_ps
cpu,125,A->B,SSPG_0p54V_cmax,12.000,12.500,0.500
cpu,m25,A->B,SSPG_0p54V_rcmin,20.000,19.100,-0.900
```

`model_ps` 가 최종 예측값. 측정값 없는 코너(`query_corners`)는 `truth_ps` 빈칸.
**OLS base 수치는 어떤 출력에도 안 나온다** — base 만 보려면 `run.sh base`.

---

## 주의할 것 세 가지

### ① 리포트에 `### FIXED_PATH` 가 없다 → 진짜 질문은 "SSTA냐"가 아니다

중요한 건 헤더가 아니라 **코너마다 경로 집합이 같은가** 다. 그냥 `report_timing`
을 코너별로 돌린 거면 코너마다 worst path 가 달라서, "같은 경로를 여러 코너에서
본다"는 이 모델의 전제 자체가 깨진다. 파서로 우회할 수 있는 문제가 아니다.
확인 방법과 세 갈래 대응은 [START.md STEP 7](docs/START.md).

### ② 코너가 적다 — 과적합 조심

레퍼런스 데이터는 51코너였는데 이번 건 온도당 8~12코너다.

| | 125C | m25C |
|---|---|---|
| 전체 → seen (0.54V 숨김) | 8 → **6** | 12 → **9** |
| 기저 파라미터 수 | 5 | 6 |
| 자유도 | **1** ← 빠듯 | 3 |

`v_order: auto` / `level_order: auto` 가 식별 가능한 최대 차수를 자동으로 잡고,
`min_seen: auto` 가 그리드가 꽉 찼는지 검사한다(리포트 하나만 빠져도 에러).
`run.sh list` 가 파라미터 수 대비 seen 이 부족하면 ⚠ 를 띄운다. → [OLS.md §3](docs/OLS.md)

### ③ BEOL 좌표는 "간격"만 의미 있다

`level_values: {rcmin: -1, cmax: 0, rcmax: 1}` 는 등간격 가정. 회사 코너 정의상
순서나 간격이 다르면 이 숫자만 고친다 (절대값은 무의미, ref 를 빼기 때문).

---

## SI(크로스토크) 없이도 돌아간다

`files.crosstalk_subdir: null` 이면 SI branch 없이 **OLS base + attention** 으로
학습된다 (`lambda_si` 자동 0, `summary.json` 에 `"si_branch": false`). SI 자료를
찾기 전에 파이프라인 전체를 끝까지 돌려볼 수 있다. 찾으면 두 줄 채우고 재빌드.

---

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[train]          # numpy, pyyaml, torch
```

`recon`/`list`/`build`/`base` 는 **numpy + pyyaml 만으로** 돈다. torch 는 `train`
에만 필요하고, GPU 없으면 자동 CPU.

## 더 볼 것

| 궁금한 것 | 문서 |
|---|---|
| **처음부터 뭘 어떻게 하나, 폴더는 어떻게 두나** | **[docs/START.md](docs/START.md)** |
| **코너를 어떻게 숨기나, 온도마다 따로 주려면** | **[docs/HOLDOUT.md](docs/HOLDOUT.md)** |
| config 키가 뭐뭐 있나, 이 에러 뭔가 | [docs/CONFIG.md](docs/CONFIG.md) |
| base 가 뭘 하나, 차수/대역폭을 어떻게 맞추나 | [docs/OLS.md](docs/OLS.md) |
| 파일명/본문 형식이 다르다, FIXED_PATH 가 없다, npz 직접 만들기 | [docs/PARSING.md](docs/PARSING.md) |
