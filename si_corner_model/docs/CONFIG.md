# CONFIG — `config.yaml` 키 전부

실행 순서는 [README](../README.md).
base(OLS) 튜닝은 [OLS.md](OLS.md), 리포트 파싱은 [PARSING.md](PARSING.md).

**원칙 하나만 기억하면 된다:**

| | 처리 |
|---|---|
| 전압, BEOL 레벨 | **연속 축** → 다항식으로 보간 (측정 안 한 값을 예측) |
| 온도, 공정, 회로, setup/hold | **분리** → 각각 별도 모델 |

`designs × temps` 만큼 모델이 생기고, 나머지 키는 그 모델들에 **공통**으로 적용된다.
`bash scripts/run.sh list` 가 펼쳐진 결과를 다 보여주므로, 뭔가 고쳤으면 항상
`list` 로 검산하고 넘어간다.

---

## 1. 경로 / 모델 매트릭스

| 키 | 기본 | 의미 |
|---|---|---|
| `root` | — | 회로 폴더들이 있는 디렉토리. `auto` = 이 repo 의 부모 디렉토리. **환경변수 `SI_ROOT` 가 우선** |
| `designs` | `auto` | `auto`(root 밑 모든 하위폴더) / 리스트 `[a, b]` / **매핑**(회로별 override, 아래). **환경변수 `SI_DESIGNS=a,b` 가 우선** |
| `temps[].tag` | — | 모델/폴더 이름에 쓰일 문자열 (`125`, `m25`) |
| `temps[].token` | `tag` | **파일명 안의** 온도 토큰. tag 와 달라도 됨 |
| `temps[].levels` | — | 그 온도에 존재하는 BEOL 레벨. **온도마다 달라도 된다** |
| `mode` | `setup` | **setup/hold 를 정하는 한 줄.** 읽을 폴더(`files.subdir`, `files.crosstalk_subdir`)와 쓸 폴더(`out.*`)가 전부 여기서 유도된다 |
| `out.cache` | `auto` | `auto` = `cache/<mode>/<design>/<temp>/dataset.npz` |
| `out.runs` | `auto` | `auto` = `runs/<mode>/<design>/<temp>/` + `runs/<mode>/_all/` |
| `files.subdir` | `auto` | `auto` = `<mode>`. 폴더명이 다르면 직접 적는다 (`reports`) |
| `files.crosstalk_subdir` | `auto` | `auto` = `<mode>/xtalk`. `null` 이면 SI 끔 |
| `task` | `slack` | `slack` \| `slew` |

모델 이름은 `<design>/<tag>`. 공정이 여러 개면 `corners.process` 를 바꿔가며
**따로 돌린다** (공정도 분리 차원이라 한 번에 섞을 수 없다).

### 회로별 override — `designs:` 를 매핑으로

회로들은 기본적으로 **모든 설정을 공유한다**(코너도 홀드아웃도 동일). 한 회로만
다르면 매핑으로 쓰고 그 회로 밑에 다른 키만 적는다. 적지 않은 키는 전역을 그대로
물려받으므로 config 파일은 계속 하나다:

```yaml
designs:
  회로1: {}
  회로2: {files: {subdir: reports}}
  회로3:
    corners: {voltages: [0.5, 0.6, 0.685]}
    temps: [{tag: "125", token: 125, levels: [rcmax, cmax],
             hidden_corners: [[0.5, rcmax]]}]
```

덮어쓸 수 있는 최상위 키: `corners` `temps` `files` `parsing` `base` `model`
`train` `split`. 리스트와 스칼라는 **교체**된다(추가가 아님) — `temps` 를 덮어쓰면
그 회로는 적은 온도만 돈다.

경로를 파일 수정 없이 바꾸려면:

```bash
SI_ROOT=/real/path SI_DESIGNS=cpu,gpu bash scripts/run.sh list
```

---

## 2. `corners` — 코너 정의와 홀드아웃

| 키 | 의미 |
|---|---|
| `process` | 공정 토큰 (`SSPG`). 코너 라벨 `SSPG_0p685V_cmax` 의 접두사가 된다 |
| `voltages` | 측정된 전압 **전부** |
| `ref_voltage` / `ref_level` | 앵커 코너. 다항식 원점(`dv = V − ref`)이자 경로 선택 기준 |
| `level_values` | 레벨 이름 → 축 좌표 |
| `query_corners` | 측정이 아예 없는 순수 예측 코너 |

### 앵커(`ref_*`) 규칙 — 어기면 에러

- 반드시 **SEEN** 이어야 한다 (숨긴 전압/레벨이면 안 됨).
- **모든 온도에 존재하는 레벨**이어야 한다. 이번 데이터에서 125C 는 `rcmin` 이
  없으므로 `ref_level: rcmin` 은 불가 → `cmax` 를 쓴다.
- 최고전압 × 중앙레벨을 권장한다. 다항식 오차는 원점에서 가장 작고, 외삽보다
  내삽이 안전하기 때문.

### `level_values` — 절대값이 아니라 **간격**이 의미 있다

```yaml
level_values: {rcmin: -1, cmax: 0, rcmax: 1}
```

`ref_level` 값을 빼서 쓰므로 `{0,1,2}` 나 `{-1,0,1}` 이나 결과가 같다.
바뀌는 건 **간격**뿐이다. 예를 들어 `rcmax` 가 `cmax` 보다 훨씬 심한 코너라면:

```yaml
level_values: {rcmin: -1, cmax: 0, rcmax: 3}   # rcmax 를 멀리 -> 그 사이 기울기가 완만해짐
```

회사 코너 정의(실제 파라시틱 배율)를 보고 정하는 게 가장 좋다. 모르면 등간격으로
두고 `run.sh base` 의 hidden 오차를 보며 조정한다.

### 숨길 코너 고르기 — 자세한 건 [HOLDOUT.md](HOLDOUT.md)

**온도마다 레벨이 다르면 `temps[]` 안에 온도별로 적어야 한다.** 아래 키는 전부
`corners:`(전역) 와 `temps[]`(온도별) 양쪽에 쓸 수 있고 온도별이 우선한다.

```yaml
corners:
  hidden_voltages: [0.54]                   # ① 이 전압의 모든 레벨 (행 통째)
  seen_voltages: []                         # ②  반대: 이것만 seen, 나머지 전압은 전부 hidden
  hidden_levels: [rcmin]                     # ③ 이 레벨의 모든 전압 (열 통째)
  hidden_corners: [[0.6, rcmax]]            # ④ 콕 집어 한 칸씩
  query_corners: [[0.57, cmax]]             # ⑤ 측정 자체가 없는 코너 (항상 hidden)
```

| | 언제 쓰나 |
|---|---|
| ① `hidden_voltages` | 기본. "이 전압을 안 재도 맞히나" 를 본다 |
| ② `seen_voltages` | 촘촘한 전압 그리드를 성긴 것만으로 학습시킬 때. ①과 **동시 사용 불가** (에러) |
| ③ `hidden_levels` | "이 BEOL 코너를 안 돌려도 되나" 를 본다. `ref_level` 은 숨길 수 없다 |
| ④ `hidden_corners` | 코너가 적어 행/열을 통째로 빼면 앵커가 모자랄 때. 가장 세밀 |
| ⑤ `query_corners` | **검증이 아니라 실사용.** 정답이 없으니 지표에서 빠지고 예측값만 CSV 에 나온다 |

①~④ 는 정답이 있으므로 hidden 지표(`hidden_mae_ps`)에 들어간다. ⑤ 는 안 들어간다.

**홀드아웃을 아예 안 하고 싶으면** ①~④ 를 모두 비우고 ⑤ 를 넣는다. 그러면 전
코너가 seen 이고, 검증은 `run.sh base` 의 **seen-LOO** 수치로 한다.
(어떤 홀드아웃도 없고 `query_corners` 도 없으면 "숨길 코너가 없다" 에러가 난다 —
그 상태로는 예측할 대상 자체가 없기 때문.)

---

## 3. `split`

| 키 | 기본 | 의미 |
|---|---|---|
| `min_seen` | `auto` | seen 코너 최소 개수 가드. `auto` = `seen전압수 × seen레벨수` |
| `path_split_seed` | 42 | 경로 train/val/test(80/10/10) 분할 시드 |

`min_seen: auto` 는 사실상 **"그리드가 꽉 찼는가"** 검사다. 리포트가 하나라도
빠지면 seen 이 기대보다 적어져 `degenerate split` 에러가 난다 — 조용히 부실하게
학습되는 것보다 낫다. 그리드가 원래 성글다면(일부 코너를 안 돌렸다면) 숫자로
직접 지정한다.

`path_split_seed` 는 **학습 시드(`train.seed`)와 별개**다. 앙상블을 돌릴 때
학습 시드만 바꾸고 경로 분할은 고정해야 멤버끼리 비교가 된다.

---

## 4. `files` / `parsing`

→ 자세한 건 [PARSING.md](PARSING.md). 키 목록만:

| 키 | 기본 | 의미 |
|---|---|---|
| `layout` | `flat` | `flat` = 코너가 전부 파일명에 / `levels` = `<dir>/<레벨폴더>/<전압당 1파일>` |
| `subdir` | `""` | 회로폴더 밑 하위경로. 비우면 회로폴더 전체를 **재귀** 탐색 |
| `annotated_regex` | `auto` | (`flat`) `auto` = 순서·대소문자·구분자 무관 토큰 매칭(권장). 정규식을 주면 `(?P<v>)` `(?P<level>)` 필수, `(?P<temp>)` `(?P<proc>)` 는 필터 |
| `annotated_suffix` | `_fixed_annotated.txt` | (`levels`) 고를 파일 확장자 |
| `voltage_regex` | `_tt(0p\d+)v` | (`levels`) 그룹1 = 전압 토큰 |
| `crosstalk_subdir` | `null` | SI 리포트 위치. `null` = SI 없이 학습 |
| `crosstalk_regex` / `crosstalk_suffix` | — | 위와 동일 형식 |
| `annotated_contains` / `crosstalk_contains` | `null` | annotated 와 crosstalk 이 **같은 폴더**에 있을 때 파일명으로 구분 (pt_si_re 배치) |
| `parsing.cell_taxonomy` | `{}` | 비-SAED 라이브러리 셀 이름 규칙 ([PARSING.md §3](PARSING.md)) |
| `parsing.clock_pins` | `[CK,CLK,CP,C]` | FF 클럭핀 후보. 못 찾으면 `launch_clk`/`capture_clk` 가 조용히 NaN |
| `parsing.ff_output_pins` | `[Q,QN,QB,Z]` | FF 출력핀 후보. launch_clock→data 전환 지점 |
| `parsing.strip_path_idx` | `auto` | 경로 키의 `#번호` 를 뗄지. `auto` = 떼서 중복 생기면 유지 |

크로스토크 폴더/파일 구성은 [PARSING.md §6](PARSING.md) 에 그림과 함께 있다.

---

## 5. `base` / `model` / `train`

`base` 는 [OLS.md](OLS.md) 에서 자세히. 요약:

| 키 | 기본 | 의미 |
|---|---|---|
| `v_order` / `level_order` | `auto` | 다항식 차수. auto = 식별 가능한 최대치 |
| `cross_terms` / `cross_max_degree` | true / 2 | 교차항 사용 / 총차수 상한 |
| `weighting` | `adaptive` | `plain` \| `local` \| `adaptive` |
| `bandwidth` | — | `local` 일 때 필수 |
| `adaptive_grid` | `null` | `adaptive` 후보 대역폭. null = 자동 유도 |
| `adaptive_k` / `adaptive_amp_ratio` / `adaptive_clip_frac` | 6 / 1.5 / 0.3 | adaptive 세부 |
| `v_fit_scale` / `level_fit_scale` | 1.0 | 피팅 전 좌표 나눔 |
| `v_token_scale` / `level_token_scale` | 0.1 / 1.0 | 신경망 feature 좌표 단위 |
| `v_gap_cap` / `level_gap_cap` | 2.5 / 2.0 | 외삽 gap feature 상한 |

`model`: `enc_blocks`(3) `enc_dim`(128) `d_model`(64) `n_heads`(4) `dropout`(0.10)
`aggr_slots`(12) `si_n_time`(16) `si_elec_thresh`(0.01)

`train`: `seed`(42) `lr`(2e-3) `weight_decay`(1e-4) `batch_paths`(256) `epochs`(100)
`lambda_si`(1.0) `si_w_ns0/1` `si_tau_ps0/1` `si_w_elec0/1` `device`(cuda→없으면 cpu)

`lambda_si` 는 SI 보조손실 가중치. 얼마가 맞는지는 데이터마다 다르므로
`bash scripts/run.sh sweep` 으로 `{0, 0.1, 1, 10}` 을 비교한다 (결과는
`runs/_sweep/` 로 따로 나가 본 run 을 덮어쓰지 않는다). SI 자료가 없으면 자동 0.

---

## 6. 에러 → 고칠 곳

| 증상 | 원인 / 고칠 곳 |
|---|---|
| `root does not exist` | `root` 또는 `SI_ROOT` |
| `no design sub-directories found` | `designs` 를 명시적 리스트로 |
| `no annotated corners discovered ... (regex matched NO filenames)` | `files.annotated_regex` — `run.sh recon` 의 파일명 샘플에 맞춘다 |
| `... (regex matched some filenames)` | 정규식은 맞음. `corners.process` / `temps[].token` / `temps[].levels` 중 하나가 실제 토큰과 불일치 |
| `corner ... matched by more than one file` | 정규식이 헐렁하거나 탐색 범위가 넓음 → `files.subdir` 을 더 깊게 |
| `ref corner ... not in the discovered grid` | `ref_voltage`/`ref_level`. 0.6850 → 라벨은 `0p685` (뒤 0 제거) |
| `ref_level ... 가 이 온도의 levels 에 없다` | 모든 온도에 있는 레벨을 앵커로 |
| `corners.ref_voltage ... must be a SEEN voltage` | 앵커 전압을 숨겼다 |
| `seen_voltages 와 hidden_voltages 중 하나만` | 둘 다 선언함 |
| `degenerate split: N seen < min_seen=M` | 리포트 누락, 또는 `voltages`/`levels` 선언이 실제와 다름 |
| `degenerate split: no hidden corners` | 홀드아웃도 `query_corners` 도 없음 |
| `split.hidden_levels: unknown level` | `level_values` 에 없는 이름 |
| `파싱된 경로가 0개` | 리포트 **본문** 형식이 다름 → [PARSING.md](PARSING.md) |
| `I1: corner sets differ` | annotated 와 crosstalk 커버리지 불일치 |
| `expected 14 columns` | 크로스토크 dump 스키마가 다름 → [PARSING.md](PARSING.md) |
| CUDA RNN backward 에러 | backward 전에 `model.train()` (BiGRU 는 train 모드 필요) |
