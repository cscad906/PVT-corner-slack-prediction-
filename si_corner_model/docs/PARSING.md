# 파싱 & 데이터 적응 가이드
---

## 1. 파이프라인

```
raw 리포트 ──► dataset.npz ──►(자동)──► si_features.npz ──► 학습기
   (텍스트)     [N 경로 ×            (보간된,                (base + 신경망)
                C 코너]              누수 안전 SI)
```

`N` = 경로 수, `C` = 코너 수, `A` = 연속축 개수(2개: 전압 + BEOL/RC 또는
전압 + 온도). **들어오는 방법은 두 가지:**

- **(A) 번들 파서 재사용** (`si_model/parsing/build_dataset.py`,
  `si_model/tasks/slew/build_slew.py`) — 리포트가 PrimeTime `report_timing` +
  compact crosstalk면 **config만으로**(§3), 많아야 정규식 몇 개로 적응.
- **(B) `dataset.npz`를 직접 생성** — 어떤 도구로든 §4의 **배열 계약**만 맞추면 됨.
  엔진은 raw 텍스트를 다시 읽지 않고 npz만 읽어. 형식이 완전히 다를 때의 탈출구.

### 1.1 형식을 전혀 모를 때 — 판단 트리

핵심 사실 하나: **엔진은 raw 파일을 절대 직접 읽지 않는다. 항상 npz만 읽는다.**
그래서 "파일 형식이 뭐든" 문제는 npz를 만드는 단계 하나로 좁혀지고, 그 단계는
아래처럼 흡수된다:

```
새 데이터 도착 (형식/내용 미지)
 ├─ 열어보니 PrimeTime류 리포트다
 │     → config만: rc_corners + axes.levels + ref + data.patterns   (§3, 코드 0줄)
 ├─ 개념은 같은데 줄 모양/열이 다르다
 │     → annotated.py / crosstalk.py 정규식·열 인덱스 몇 줄          (§5, §8)
 └─ 완전히 다르다 / 알 수 없는 도구다
       → 아무 스크립트로 §4의 npz 배열 계약만 충족                   (옵션 B)
         → 그 뒤 build/train/평가는 전부 동일
```

### 1.2 형식과 무관한 최소 요구 "정보" (이건 우회 불가)

파일이 어떻게 생겼든, 데이터가 **내용적으로** 담고 있어야 하는 것:

| 정보 | 필수? | 없으면 |
|---|---|---|
| 같은 경로 집합이 **여러 코너**(V × 2번째 축 그리드)에서 측정된 타이밍 값 | **필수** | 모델의 전제 자체가 성립 안 함 |
| 각 측정의 코너 식별 (어떤 V, 어떤 레벨/온도인지) | **필수** | 그리드/축을 세울 수 없음 |
| 경로 내부 stage 정보 (cell/net 체인) | 권장 | 인코더 입력이 빈약해짐 — 최소한의 배열로 대체 필요 |
| 크로스토크/aggressor 정보 (delta, bump, 윈도우) | 선택 | SI branch 사용 불가 → SI 배열 0/빈 값 + `lambda_si: 0`로 base+attention만 (이 경로는 아직 실데이터 검증 전) |

---

## 2. 레퍼런스 형식 (번들 파서가 기대하는 것)

### 2.1 디렉토리 배치 (탐색)

```
<annotated_dir>/<LEVEL>/  saed..._tt<v>v<t>c_..._fixed_annotated.txt   # 전압당 1파일
<crosstalk_dir>/<LEVEL>/  TT_<v>V_<temp>C.path_context_si_compact.by_path.rpt
```

`<LEVEL>` = 2번째 축 레벨 하위폴더 (기본 `Cmin/Cnom/Cmax`, 이름 자유 — §3 참고).
한 `(sta, temp)` 모델은 한 온도의 파일을 모든 레벨에 걸쳐 읽어. 탐색은
`discover()`에 있고, annotated와 crosstalk의 **코너 집합이 일치**하는지 검증(무결성
체크 **I1**).

### 2.2 annotated 리포트 (`annotated.py`)

`### FIXED_PATH idx=<i> key=<start>-><end>` 블록마다 전체
`report_timing -path_type full_clock_expanded -nets` 표. 파서가 뽑는 것:

| 필드 | 매칭되는 줄 |
|---|---|
| `slack` (라벨) | `slack (VIOLATED\|MET...) <num>` |
| `arrival`, `required` | `data arrival time` / `data required time` |
| `launch_clk`, `capture_clk` | `<start>/CK` / `<end>/CK` 의 클럭 arrival |
| `lib_check_time` | `library (setup\|hold) time <incr> <path>` |
| stage cell 행 | `<inst/pin> (<libcell>) [<-] <trans> <incr> <path> <r\|f>` |
| stage net 행 | `<net> (net) <fanout> <cap> [<dist> <res> <cpin>]` |

14nm 특성 이미 처리됨: FF 클럭핀 `/CK`, launch→data 핸드오프는 `<start>/Q|/QN`
정확 매칭(계층명 안전), net 행의 BEOL `Dist/Res/Cpin` 열,
`slack (VIOLATED: increase significant digits)` 변형.

### 2.3 crosstalk 리포트 (`crosstalk.py`)

탭 구분, 경로당 14열, `### FIXED_PATH` + `# Slack:` 헤더. 열:

```
segment  victim_net  aggressor_net  crosstalk_delta  aggressor_bump
n_aggressors  victim_load_pin  victim_min_arrival  victim_max_arrival
aggr_driver_pin  aggr_min_arrival  aggr_max_arrival  aggr_slew_max  coupling_cap_ff
```

- `aggressor_net == "0"` → 이 코너에 ACTIVE aggressor 없음.
- ACTIVE(`A`) aggressor당 1행; victim `crosstalk_delta`는 반복(net당 값이라
  일치 검증 — 안 맞으면 파서가 에러).
- setup dump = MAX 델타(+), hold dump = MIN 델타(−). 14nm hold는 `-min`으로
  뽑혀서 두 체크 다 부호가 맞음.

---

## 3. CONFIG로 바꾸는 것 (코드 X) — 적응 3단계

### 1단계 — 코너 **이름/값**이 다를 때 (가장 흔함)

BEOL/공정 코너가 `Cmin/Cnom/Cmax`가 아니면, 그냥 선언:

```yaml
data:
  rc_corners: [Cbest, Ctyp, Cworst]        # 데이터의 레벨 하위폴더 이름
base:
  axes:
    - {name: v,  ref: 0.75, order: 3}
    - {name: rc, ref: 0, order: 2, levels: {Cbest: -1, Ctyp: 0, Cworst: 1}}
```

`levels`가 각 이름을 축 좌표로 매핑. 전압은 파일명에서 나오고, `ref`가 축마다
기준 코너 값을 지정. `levels`를 생략하면 내장 기본 `Cmin/Cnom/Cmax → -1/0/1` 사용.

### 2단계 — **파일명 / 라벨 문자열**이 다를 때

패턴을 덮어씀(기본값 표시):

```yaml
data:
  corner_prefix: TT                          # 코너 라벨/파일명의 공정 토큰
                                             #   (다른 데이터에선 FFPG/SSPG 등)
  patterns:
    annotated_suffix: _fixed_annotated.txt   # 고를 파일 확장자
    crosstalk_suffix: .by_path.rpt
    voltage_regex: '_tt(0p\d+)v'             # 그룹1 = 전압 토큰, 예: 0p605
```

코너 *라벨*(`<prefix>_<v>V_<level>`)은 `parse_corner`가 파싱 — `corner_prefix`
(공정 토큰), 임의 `levels` 맵, 온도 형식 `<prefix>_<v>V_<m?NN>C` 전부 지원.
**공정은 분리 차원**이므로 접두사가 여러 개(FFPG/SSPG/TT...)면 접두사마다 config
하나(= 모델 하나).

### 2.5단계 — 예시: "전부 다른" 딜리버러블 하나를 통째로

접두사 FFPG, BEOL 이름 Cbest/Ctyp/Cworst, V 범위 0.5~0.65, 온도 125 하나,
파일명도 다른 가상의 데이터라면 — config는 이게 전부:

```yaml
data:
  annotated_dir: /data/vendorX/ffpg/125c/annotated     # 안에 Cbest/ Ctyp/ Cworst/
  crosstalk_dir: /data/vendorX/ffpg/xtalk
  temp: 125
  corner_prefix: FFPG                                  # 라벨 = FFPG_0p55V_Ctyp ...
  rc_corners: [Cbest, Ctyp, Cworst]
  ref_corner: FFPG_0p65V_Ctyp
  cache: cache/vendorX/ffpg_125/dataset.npz
  patterns:
    annotated_suffix: .timing.rpt                      # 그쪽 파일 확장자
    voltage_regex: '_v(0p\d+)_'                        # 그쪽 전압 토큰 위치
split:
  seen_voltages: [0.5, 0.55, 0.6, 0.65]
base:
  axes:
    - {name: v,  ref: 0.65, order: 3}                  # ref/범위 전부 그 데이터 기준
    - {name: rc, ref: 0, order: 2, levels: {Cbest: -1, Ctyp: 0, Cworst: 1}}
train:
  out_dir: runs/vendorX/ffpg_125/v1
```

여기까지 **코드 0줄**. 리포트 **본문**의 줄 배치까지 다르면 §5(정규식 몇 줄) 또는
§4(옵션 B: npz 직접 생성)로.

### 3단계 — 온도를 분리모델이 아니라 **축**으로

온도가 촘촘히 변해서 (분리모델이 아니라) 보간하고 싶으면(3nm 예시처럼):

```yaml
base:
  axes:
    - {name: v, ref: 0.7, order: 3}
    - {name: t, ref: 25, order: 4, fit_scale: 100, token_scale: 100}   # dt = (T-25)/100
```

`fit_scale`은 피팅 전에 좌표를 나눔(`dt`를 O(1)로), `token_scale`은 신경망
feature의 단위.

---

## 4. 배열 계약 (옵션 B — `dataset.npz`를 직접 생성)

리포트가 너무 달라서 번들 코드로 못 파싱하면, 아래 배열을 담은 `.npz`를
생성하는 어떤 스크립트든 짜면 돼. 학습기는 이 배열들만 읽어. `N`=경로,
`C`=코너, `L`=최대 stage 체인 길이, `S`=SI 스테이지, `A`=스테이지당 최대 aggressor.

### 4.1 slack 모델 (`dataset.npz`)

**코너 그리드**
| 키 | shape / dtype | 의미 |
|---|---|---|
| `corners` | `[C]` str | 라벨, 예: `TT_0p65V_Cnom` |
| `vt` | `[C,2]` f32 | 코너별 `(전압, 레벨값)` |
| `measured` | `[C]` bool (선택) | False = 측정 없는 **순수 추론 코너**(`data.query_corners`가 자동 생성; 직접 npz를 만들 때도 NaN 측정 + False로 두면 예측만 출력됨). 생략 시 전부 True |

**경로×코너 스칼라** (전부 `[N,C]` f32, 단위 없는 것 빼고 **ns**)
`slack`(라벨, SI 포함), `si_label`(Σ 크로스토크 델타), `arrival`, `required`,
`launch_clk`, `capture_clk`, `lib_check_time`.

**경로 식별 / 인코더 옆입력**
| 키 | shape | 의미 |
|---|---|---|
| `path_keys` | `[N]` str | 정규화된 경로 키 |
| `path_idx` | `[N]` i32 | 원본 리포트 idx |
| `path_sig` | `[N,27]` f32 | 세그먼트별 경로 시그니처 |
| `sig_names` | `[27]` str | 그 열 이름 |
| `node_fam` | `[N,L]` i16 | ref 코너 stage 체인 패밀리 id |
| `node_feat` | `[N,L,9]` f32 | 노드별 feature (열 5 = critical 마커) |
| `edge_feat` | `[N,L-1,5]` f32 | 엣지별 feature (cap,fanout,res,dist,cpin) |
| `node_mask` | `[N,L]` bool | 유효 stage 체인 노드 |
| `fam_vocab` | `[V]` str | 패밀리 어휘 (인덱스 0 = `<pad>`) |
| `node_feat_names`,`edge_feat_names` | str | 열 이름 |

**SI-branch 입력** (SI 스테이지별)
| 키 | shape | 의미 |
|---|---|---|
| `stage_path` | `[S]` i32 | 스테이지 → 경로 인덱스 |
| `stage_seg` | `[S]` i8 | 0/1 = launch/data(유지), ≥2 버림 |
| `n_aggr` | `[S]` i16 | aggressor 수 |
| `vwin` | `[S,C,2]` f32 | victim (min,max) arrival 윈도우, ns |
| `arc_delta` | `[S,C]` f32 | victim 크로스토크 델타, ns |
| `abump` | `[S,A,C]` f32 | aggressor bump 비율 (이미 /VDD) |
| `awin` | `[S,A,C,2]` f32 | aggressor (min,max) arrival 윈도우, ns |
| `aslew` | `[S,A,C]` f32 | aggressor slew, ns |
| `acc` | `[S,A]` f32 | 커플링 cap (V/RC 무관) |

없는 항목은 `NaN`(예: 어떤 코너에서 비활성 aggressor); feature 단계가 보간하고
마스킹함. `si_features.npz`는 자동 생성.

### 4.2 slew 모델 (`slew.npz`)

더 작음: `corners`, `vt`, `path_keys`, `path_idx`, `slew` `[N,C]`(ns, 라벨),
`cap` `[N,C]`(학습 안 함, 이웃에서 가져옴), 그리고 동일한 인코더 배열
(`path_sig`, `sig_names`, `node_fam`, `node_feat`, `edge_feat`, `node_mask`,
`fam_vocab`, `node_feat_names`, `edge_feat_names`). SI/crosstalk 배열 없음.

---

## 5. 코드로 손대는 지점 (옵션 A 정규식으로 부족할 때만)

어떤 config도 임의의 텍스트 형식을 파싱할 순 없어. 코드를 고치는 곳은 **오직
이 3곳**이고, 각각 작고 독립적:

| 파일 | 파싱하는 것 | 언제 고치나 |
|---|---|---|
| `si_model/parsing/annotated.py` | 타이밍 리포트 한 개의 줄 배치 | 리포트 열/키워드가 다를 때 |
| `si_model/parsing/crosstalk.py` | 14열 crosstalk 행 | crosstalk dump 스키마가 다를 때 |
| `si_model/parsing/build_dataset.py` → `cell_family`,`cell_drive` | 셀명 → 함수 패밀리 / 드라이브 | 비-SAED14 표준셀 라이브러리 |

`cell_family`는 인코더의 패밀리 임베딩만 먹임; 모르는 셀은 `<unk>`로 매핑되고도
학습됨 — 처음엔 대충 분류해도 됨.

---

## 6. 코너 키 & 무결성 체크 (건너뛰지 말 것)

- **`#idx` 함정.** 경로 키는 `<start>-><end>_#<idx>` 모양. `#idx`는 리포트별
  일련번호일 뿐 **식별자 아님**. `norm_path_key`가 이걸 떼. 원본 키로 정렬하면
  공통 경로 ~2758개가 ~8개로 붕괴. 직접 짠 파서도 코너간 join 전에 똑같이 떼야 함.
- **I1** (`discover`): annotated와 crosstalk 코너 집합이 일치해야 함.
- **I2/I3** (`build`): 두 소스가 idx→key 매핑과 (경로,코너)별 `slack`에 대해
  5e-5 이내로 일치해야 함. 직접 짠 빌더가 이걸 assert 못 하면, 최소한 코너간
  키가 맞는지는 검증해.

---

## 7. 새 딜리버러블 적응 — 빠른 레시피

1. **리포트를 봐.** PrimeTime `report_timing -nets` + compact crosstalk?
   → 옵션 A. 다른 거? → 옵션 B (§4).
2. **config를 디렉토리에 겨눔**, `rc_corners`를 레벨 폴더명으로, `axes[1].levels`를
   그 좌표로, `ref` 코너 설정.
3. **빌드 시도:** `bash scripts/build.sh configs/<너>/<모델>.yaml`.
   - "no corners discovered" → `patterns.voltage_regex` / suffix 수정.
   - "corner sets differ" (I1) → annotated vs crosstalk 폴더 불일치.
4. **본문 파싱이 깨지면**, `annotated.py`/`crosstalk.py` 정규식 조정(§5), 아니면
   옵션 B로 전환해 npz 직접 생성.
5. **점검:** 출력된 `N`, `C`, `S`, `A`와 짧은 학습의 base-only hidden MAE.

---

## 8. 코드 맵 — 어느 파일이 무엇을, 함수별로

전체 파싱 경로를 위에서 아래로. 함수마다: 무엇을 하는지, 그리고 **[수정]** =
데이터가 다를 때 손대는 곳(아니면 그대로).

### `si_model/parsing/keys.py` — 코너 & 경로 키 헬퍼 (파일 I/O 없음)

| 함수 | 하는 일 | 새 데이터에 수정? |
|---|---|---|
| `RC_VAL`, `RC_NAMES`, `TEMP_MAP` | 기본 BEOL/온도 이름→값 맵 | 아니오 — config `axes.levels`로 덮음 |
| `norm_path_key(key)` | `_#<idx>` / `#<idx>` 일련번호를 떼 코너간 매칭 | **[수정]** idx 접미사가 다를 때만 |
| `volt_to_float` / `volt_to_tok` | `0p605` ↔ `0.605` | **[수정]** 전압이 `0p<숫자>`가 아닐 때 |
| `parse_voltage_from_annotated(fname, regex)` | annotated 파일명에서 전압 추출 | 수정 대신 `data.patterns.voltage_regex` 전달 |
| `parse_xt_name(fname)` | crosstalk 파일명 → `(전압, 온도토큰)` | **[수정]** crosstalk 파일명이 다를 때 |
| `corner_label(v, axis1)` | 표준 `TT_<v>V_<level>` 문자열 생성 | 드묾 |
| `parse_corner(label, levels)` | 라벨 → `(전압, 레벨값)`; config `levels` 사용, RC→온도 폴백 | 아니오 — config에서 `levels` 공급 |

### `si_model/parsing/annotated.py` — 타이밍 리포트 본문

- **상단 정규식들** (`FIXED_PATH_RE`, `SLACK_RE`, `ARRIVAL_RE`, `REQUIRED_RE`,
  `CHECK_RE`, `CELL_RE`, `NET_RE`)이 줄 문법을 정의.
  **[수정] 리포트 형식이 다를 때 1순위로 고치는 곳.**
- `Stage` / `AnnotatedPath` 데이터클래스 = 스테이지별/경로별 추출 필드.
- `parse_annotated(fp, with_stages)` = 줄 루프: `### FIXED_PATH` 블록 분리,
  launch_clock→data→capture_clock 세그먼트 추적,
  `slack, arrival, required, launch_clk, capture_clk, lib_check_time`(+ `with_stages`면
  cell/net `stages`) 채움. `{idx: AnnotatedPath}` 반환.
- 산출(경로당): 라벨 `slack` + 스칼라들 + 인코더 입력이 되는 ref 코너 stage 체인.

### `si_model/parsing/crosstalk.py` — crosstalk 리포트 본문

- 행 스키마 = **14 탭 구분 열** (파일 헤더에 문서화됨).
  **[수정]** dump가 다르면 `parse_crosstalk`의 열 인덱스.
- `Aggressor` / `VictimArc` / `CrosstalkPath` 데이터클래스가 파싱된 행 보관.
- `CrosstalkPath.si_total()` = 경로별 SI 델타(launch+data 유니크 arc 델타 합) →
  `si_label`이 됨.
- `parse_crosstalk(fp)`는 `{idx: CrosstalkPath}` 반환; 반복 victim 델타 일관성 검증.

### `si_model/parsing/build_dataset.py` — `dataset.npz` 조립 (총괄)

이게 네가 실행하는 파일(`python -m si_model.parsing.build_dataset`). 순서:

1. `load_config(fp)` → `_defaults.yaml` 병합.
2. `corner_levels(cfg)` → 2번째 축 이름→값 맵 (`axes.levels`, RC 폴백).
   **config 주도; 수정 불필요.**
3. `discover(cfg)` → `<annotated_dir>/<level>`, `<crosstalk_dir>/<level>` 순회,
   파일을 코너 라벨에 매칭, 두 집합 일치 assert(**I1**). 레벨 폴더명은
   `data.rc_corners`, 파일 suffix+전압 정규식은 `data.patterns`.
   **[수정]** 디렉토리 배치가 특이할 때만.
4. `cell_family(cell)` / `cell_drive(cell)` → SAED14 셀명 → 함수 패밀리 + 드라이브
   강도(인코더 feature). **[수정] 비-SAED 라이브러리.** 모르는 셀 → `<unk>`, 학습은 됨.
5. `path_signature(stages)` → 27차 세그먼트별 경로 요약(`path_sig`).
6. `stage_sequence(stages)` → 인코더가 먹는 ref 코너 cell/net 체인
   (`node_fam`, `node_feat`, `edge_feat`).
7. `build(cfg)` → 메인 루프: 코너마다 annotated(+crosstalk) 읽고, 정규화 키로
   경로 정렬, slack 일치 검사(**I2/I3**), `[N,C]` 스칼라 배열 + SI 스테이지 배열
   조립, `np.savez_compressed`로 `data.cache`에 저장. `N C S A` 출력.

### `si_model/tasks/slew/build_slew.py` — `slew.npz` 조립

build_dataset과 같은 모양이지만 **annotated만**(crosstalk 없음):
`discover`(레벨 폴더), `slew_cap_of(path)`(파싱된 스테이지에서 launch slew +
endpoint cap), `build` → `slew`, `cap`, 인코더 배열 저장.

### `si_model/features/si_features.py` — `dataset.npz` → `si_features.npz`

`build_si_features(ds, phi, seen)`가 aggressor bump/윈도우/slew를 코너 전체로
보간(seen 코너에서 누수 안전 LOO)하고 overlap 계산. 파일 없으면 첫 학습 때
**자동 실행**; 직접 부르지 않고 거의 수정 안 함.

### `si_model/config.py` — 파싱 관련 config 헬퍼

`load_config`(기본 병합), `axis_levels`(BEOL/공정 레벨 맵),
`fit_scales`/`token_scales`(축 좌표 스케일). `expand_terms`는 OLS 기저를
만들지만 파싱과는 무관.

---

## 9. "내 데이터가 다르면 정확히 여기만" — 치트시트

| 내 데이터가 ...가 다르면 | 바꿀 것 (config 먼저, 코드 최후) |
|---|---|
| BEOL/공정 **레벨 이름·값** | `data.rc_corners` + `axes[1].levels` |
| **전압/ref** 지점 | `split.seen_voltages` + `axes[].ref` |
| **온도** 처리 | 분리 → 모델마다 `data.temp`; 축 → `t` 축 추가 |
| **공정 코너 접두사** (TT가 아니라 FFPG/SSPG 등) | `data.corner_prefix` (+ `ref_corner`도 그 접두사로); 접두사마다 config 하나 |
| **파일명**(suffix/전압 토큰) | `data.patterns.{annotated_suffix, crosstalk_suffix, voltage_regex}` |
| **타이밍 리포트 본문**(열/키워드) | `annotated.py`의 정규식 |
| **crosstalk dump** 스키마 | `crosstalk.py`의 열 인덱스 |
| **표준셀 라이브러리** | `build_dataset.py`의 `cell_family` / `cell_drive` |
| **완전히 다른 도구** | 텍스트 파서 건너뛰고 §4대로 `dataset.npz` 직접 생성 |

새 데이터셋 실행 순서:
`build.sh <config>` → (처음) `train.sh <config>`가 `si_features.npz` 자동 빌드 →
`runs/.../summary.json` 확인. 전체 명령어 레퍼런스는 [USAGE.md](USAGE.md).
