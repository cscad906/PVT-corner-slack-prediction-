# CLAUDE.md — 현장 실행 지침 (on-site runbook)

이 파일은 이 패키지를 **다른 서버(기업 사이트)에서 실행할 때** Claude/사람이
바로 참고하도록 만든 실행 지침이다. 개념 설명이 아니라 "무엇을 세팅하고, 어떤
명령을 치고, 에러가 나면 어떻게 하는가"에 집중한다. 전체 개요는 `README.md`,
각 파이프라인 상세는 하위 `*/README.md` 를 본다.

## 이 패키지가 하는 일 (한 줄)

PrimeTime 으로 (1) 고정 경로를 여러 PVT 코너에서 재측정하며 Dist/Res/Cpin feature 를
붙이고(`pt_annotation/`), (2) 같은 축에서 crosstalk delta / victim–aggressor feature 를
뽑는다(`crosstalk_features/`). 산출 CSV/TSV/RPT 가 ML 학습 입력이다.
그 입력이 되는 coupling 유지 SPEF 는 StarRC 로 먼저 뽑는다(`spef_extraction/`,
아래 파이프라인 0 — **이미 coupled SPEF 를 받아 쓰는 사이트는 건너뛴다**).

실행 순서: **파이프라인 0 (SPEF 생산) → 1 (annotation) → 2 (crosstalk)**.
**2 는 1 의 annotated 리포트가 있어야 돌아가고, 넘기기 전에 디렉토리 재배치가
필요하다**(파이프라인 2 절 첫머리 참조). **3 은 1/2 와 무관하게 단독 실행 가능**하다.

## 실행 전 체크 (5분)

```bash
which pt_shell          # 경로가 나오면 PT_SOURCE 불필요. 안 나오면 아래 PT_SOURCE 세팅
python3 --version       # 3.9 이상 필수 (3.6 이면 SyntaxError. 아래 트러블슈팅 참조)
python3 -c "import networkx"   # pt_annotation 에만 필요. 없으면 pip install -r pt_annotation/requirements.txt
which StarXtract         # 파이프라인 0(SPEF 직접 추출)을 돌릴 때만. 없으면 STARRC_ROOT 세팅
```

## 받은 SPEF 점검 (파이프라인 0 을 돌릴지 판단)

SPEF 를 이미 받았더라도 **그대로 쓸 수 있는지 두 가지를 먼저 본다.** 둘 다 SPEF
헤더/본문만 읽으므로 몇 초면 끝난다.

```bash
SPEF=/data/deliver/mycore.Cnom_model_25.spef

# ① 단위 — 코드가 정규화하지 않고 원시값 그대로 쓰므로 출력 단위 = 이 선언
grep -m4 -iE '^\*[TCRL]_UNIT' $SPEF

# ② coupling cap 유무 — SI/crosstalk 가능 여부 (러너 pre-flight 와 같은 규칙)
python3 -c "
import sys
p=sys.argv[1]; in_cap=False
for line in open(p,errors='ignore'):
    if line.startswith('*CAP'): in_cap=True; continue
    if line.startswith('*'): in_cap=False; continue
    if in_cap:
        t=line.split()
        if len(t)==4 and t[2].startswith('*'):
            print('COUPLED  -> 그대로 사용 가능'); break
else: print('GROUNDED -> SI/crosstalk 불가. 파이프라인 0 으로 재추출 필요')
" $SPEF
```

정상 출력 예(우리 14nm 케이스):
```
*T_UNIT 1.0 NS      ← 시간 ns. --slack-threshold 0.05 = 50ps 가 성립하는 전제
*C_UNIT 1.0 FF
*R_UNIT 1.0 OHM
*L_UNIT 1.0 HENRY
```

- **`*T_UNIT` 이 NS 가 아니면 `--slack-threshold` 를 그 스케일로 환산**해서 준다
  (기본 0.05 는 ns 기준 50ps).
- `*C_UNIT`/`*R_UNIT` 이 다른 SPEF 로 만든 데이터셋은 **Dist/Res/Cpin 스케일이 달라
  한 학습셋에 섞으면 안 된다**(한 데이터셋 내부는 통일되어 문제없음).
- ②가 `GROUNDED` 면 SI/crosstalk 결과가 무의미하다. `--si` 로 돌리면
  pt_annotation 이 pre-flight 에서 자동 중단시킨다(의도된 동작).
  **SI 없이 타이밍만 볼 거라면 grounded SPEF 로도 파이프라인 1 은 돌아간다.**

PrimeTime 검증 버전: **V-2023.12-SP4**. SI/crosstalk 는 **PrimeTime SI 라이선스** +
**coupling cap 이 유지된 SPEF**(StarRC `COUPLING_CAP: YES`) 필요. grounded SPEF 로 SI 를
돌리면 러너가 pre-flight 에서 막는다(의도된 동작).

## 공통 환경변수

셸이 csh/tcsh 면 `setenv A B`, bash 면 `export A=B`. (이 프로젝트 원 서버는 csh)

| 변수 | 용도 | 없으면 |
|---|---|---|
| `PT_SOURCE` | `pt_shell` 을 PATH 에 올리는 사이트 셋업 스크립트 | `pt_shell` 이 이미 PATH 면 생략 가능 |
| `PT_LICENSE` | `LM_LICENSE_FILE` 값 (예: `27020@host`) | 라이선스가 이미 환경에 잡혀 있으면 생략 |
| `LC_ROOT` | Library Compiler 설치 루트 (pt_annotation) | 대개 생략 가능 |

파이프라인 0(SPEF 추출)만 쓰는 변수 — PT 가 아니라 **StarRC** 용이다:

| 변수 | 용도 | 없으면 |
|---|---|---|
| `PROJ_ROOT` | 프로젝트 루트 (`…/deliverables` 가 이 아래) | 필수 |
| `SNPSLMD_LICENSE_FILE` | Synopsys 라이선스 `port@host` | 필수 |
| `STARRC_ROOT` | StarRC 설치 루트 (`$STARRC_ROOT/bin/StarXtract`) | 14nm 필수 |
| `PDK_ROOT` | layer map + corners 파일 디렉토리 | 14nm, 기본 `<base>/pdk` |
| `PDK_LAYER_MAP` / `PDK_NXTGRD` | (3nm) layer 매핑 / grid(`.nxtgrd`) 파일 | 3nm 필수 |
| `STARRC_MAPPING_FILE` / `STARRC_CORNERS_FILE` | layer map / corners 를 직접 지정할 때 | 선택 |
| `STARRC_JOBS` (또는 `-j`) | 병렬 job 수 | 선택 |
| `FORCE_STARRC=1` | 기존 SPEF 가 있어도 재추출 | 선택 |

## 파이프라인 0 — spef_extraction (coupling 유지 SPEF 생산)

**이미 coupled SPEF 를 받아 쓰는 사이트는 이 단계 전체를 건너뛴다.** 아래 1~3 은
SPEF 를 입력으로 받을 뿐 만들지 않으므로, SPEF 를 직접 뽑아야 할 때만 여기서 시작한다.

PDK 기술파일(layer map, `.nxtgrd`, corners)은 **이 패키지에 포함되지 않는다** —
사이트 PDK 의 파일 경로를 위 환경변수로 지정해야 한다.

```bash
cd spef_extraction
export PROJ_ROOT=/data/pvt_project
export STARRC_ROOT=/tools/synopsys/starrc/<ver>
export SNPSLMD_LICENSE_FILE=port@license-host
export PDK_ROOT=/data/pdk/saed14

# 스모크: 디자인 1개 + 코너 1개
bash 14nm/run_starrc_temp_rc_matrix_coupled.sh --corner Cnom_model_25 MyCore
# 전체 (RC 3 × 온도 3 매트릭스, 디자인 병렬 2)
bash 14nm/run_starrc_temp_rc_matrix_coupled.sh -j 2 MyCore OtherCore
```

3nm 온도 스윕은 `bash 3nm/run_starrc_temp_spef_coupled.sh MyCore`
(`PDK_LAYER_MAP`/`PDK_NXTGRD` 필요, StarXtract 는 PATH 에 있다고 가정).

- crosstalk 의 전제 조건은 자동 생성되는 `.cmd` 의 `COUPLE_TO_GROUND: NO` +
  `COUPLING_{ABS,REL}_THRESHOLD: 0` 이다. `YES` 로 뽑으면 grounded SPEF 가 되어
  다운스트림 SI 결과가 무의미해지고, pt_annotation 이 pre-flight 에서 막는다.
- 입력으로 **ICC2 NDM** 이 필요하다 (스크립트가 `processors/<design>/icc2/<lib>` 에서 찾음).
  디자인별 `BLOCK`(top)/run-tag/prefix 는 각 스크립트 `run_one()` 상단에서 수정.
- 스크립트가 SPEF 완결성(`*PROGRAM "StarRC"` + `*END`), 코너 일치
  (`OPERATING_TEMPERATURE`/`TCAD_GRD_FILE`), (3nm) coupling 엔트리 수 > 0 을 자체 검증한다.
- SPEF 는 배선 RC 이므로 **트랜지스터 공정 코너(TT/SS/FF)와 무관** — 같은 SPEF 를
  SS/TT/FF 라이브러리 어디에나 페어링한다. 이 단계에서 늘릴 축은 BEOL(RC) 코너뿐이다.

상세는 `spef_extraction/README.md`.

## 파이프라인 1 — pt_annotation (fixed-path 스윕 + annotation)

CLI 인자로 경로를 준다(환경변수 아님). 기본값은 우리 BoomCoreV3 케이스라 **자기
디자인 값으로 바꿔야 한다.** 먼저 작은 범위로 확인 후 전체를 돌린다.

**route 를 먼저 고른다 — 두 가지고, 섞이지 않는다.**

| | 1-A: top-N | **1-B: violation union (기본 선택)** |
|---|---|---|
| 경로 선정 | ref 코너 1곳의 worst N개 | hidden 제외 **전 코너**에서 slack<TH 전부 → union |
| 명령 | `run_sweep.py` 단독 | `extract_violation_paths.py` → `run_sweep.py --reuse-strict-tcl` |
| 언제 | 빠른 샘플/스모크 | **위반+위험 경로를 빠짐없이 담아야 할 때** |

**우리 목적(위반 및 위반 위험 경로 전수 + hidden corner 실험)은 1-B 다.**
1-A 는 `--max-paths` 개수만 담으므로 위반이 그보다 많으면 통째로 놓친다.
아래 1-A 예시는 스모크/참고용이고, **실제 데이터 생산은 1-B 절차를 따른다.**

```bash
cd pt_annotation
# (필요시) setenv PT_SOURCE /site/pt_setup.cshrc

python3 run_sweep.py \
  --design MyCore --top MyCoreTop \
  --spef-prefix mycore_14nm \
  --mode setup --si \
  --verilog   /data/deliver/mycore_icc2.v \
  --sdc       /data/deliver/mycore.sdc \
  --spef-root /data/deliver/spef \
  --db-root   /data/lib_db/db  --lib-root /data/lib_db/lib \
  --ref-db    /data/lib_db/db/<ref_corner>.db \
  --out-dir   /data/results/mycore_setup_si \
  --max-paths 3000 --edge-aware-fixed-paths
```

주요 인자: `--mode setup|hold`, `--si`(SI on), `--rc-corners Cmax,Cnom,Cmin`,
`--ref-rc Cnom`, `--max-workers N`(병렬 코너 수 = PT 라이선스 소비 수),
`--spef-name-format`(기본 `{prefix}.starrc.{rc}_model_{temp}.spef`), `--spef-temp`.
전체 목록은 `python3 run_sweep.py --help`.

- SPEF 파일명 규약이 다르면 `--spef-name-format` 로 맞춘다.
- db 파일명에서 전압 토큰(`tt0p7v25c`→`0p7`)을 파싱하므로 db 이름이 이 규약과
  다르면 정렬이 깨진다. 다르면 `run_sweep.py` 상단 파싱부를 확인.
- 산출물: `<out-dir>/annotated/<RC>/<corner>_fixed_annotated.txt` (ML 입력).

## 파이프라인 1-B — violation union route (실제 데이터 생산 절차)

`setup` / `hold` 는 **완전히 별개 2세트**다. 아래를 `--mode setup` 으로 1회,
`--mode hold` 로 1회 돈다. 공통 인자(`--design/--top/--spef-prefix/--verilog/
--sdc/--spef-root/--spef-name-format/--spef-temp/--db-root/--lib-root/--si`)는
두 단계가 **같은 값**이어야 한다.

### 1단계 — 코너별 위반/위험 경로 전수 추출 + union

```bash
cd pt_annotation

python3 extract_violation_paths.py \
  --design MyCore --top MyCoreTop \
  --spef-prefix mycore_14nm \
  --mode setup --si \
  --verilog   /data/deliver/mycore_icc2.v \
  --sdc       /data/deliver/mycore.sdc \
  --spef-root /data/deliver/spef \
  --db-root   /data/lib_db/db  --lib-root /data/lib_db/lib \
  --rc-corners Cmax,Cnom,Cmin \
  --exclude-vtags 0p795 \
  --slack-threshold 0.05 \
  --max-paths 50000 --max-workers 3 \
  --emit-fixed-paths-tcl --edge-aware-fixed-paths \
  --out-dir   /data/results/mycore_violscan_setup
```

**여기서 반드시 의식하고 정해야 할 값 3개:**

| 값 | 뜻 | 잘못 주면 |
|---|---|---|
| `--slack-threshold` | slack < TH 인 경로를 뽑는다. **단위 = SDC 시간 단위**(통상 ns) | **기본 `0.05` = 50ps 마진** — 위반 + 위반 위험을 함께 뽑는다(우리가 원하는 동작이라 기본값으로 박아둠). `0.0` 을 주면 위반만. TH 밖의 경로는 리포트에 아예 없어 사후 복구 불가 → **재실행뿐**이므로 좁히지 말 것. **SDC 단위가 ns 가 아니면 0.05 는 50ps 가 아니다** — `grep -i units *.sdc` 로 확인 |
| `--exclude-vtags` | 경로 **선정**에서 뺄 hidden 코너 | 여기서 뺀 코너도 2단계에서는 **측정된다**(그게 hidden corner 실험의 요지). db-root 에서 db 파일을 지우면 안 된다 |
| `--max-paths` | 코너당 리포트 상한 | 상한에 닿으면 summary 에 `TRUNCATED?` — 아래 게이트 참조 |

`--emit-fixed-paths-tcl --edge-aware-fixed-paths` 는 **둘 다 켠다.** 전자가 없으면
2단계에 넘길 tcl 이 안 생기고, 후자는 전압별로 rise/fall worst 가 뒤바뀌어 같은
경로 번호에 다른 물리 측정이 섞이는 것을 막는다(run_sweep 쪽에 줘도 무시되므로
**여기서 켜야 한다**).

### 게이트 — 1단계 결과를 2단계로 넘기기 전 확인

```bash
grep -E "TRUNCATED|FAILED|UNION|FIXED_PATHS_TCL|THROUGH_POLICY" \
     /data/results/mycore_violscan_setup/summary.txt
```

| 봐야 할 것 | 정상 | 아니면 |
|---|---|---|
| `TRUNCATED?` | 없음 | **있으면 `--max-paths` 를 키워 재실행.** 잘린 코너는 union 비교가 무의미 |
| `FAILED` 코너 목록 | 없음 (exit 0) | 라이선스 부족 등. 원인 해결 후 재실행 (부분 결과로 진행 금지) |
| `THROUGH_POLICY` | `ALL_INTERNAL_PINS(strict)` | `SAMPLED(N)` 이면 `--fixed-through-count 0` 으로 다시 |
| `FIXED_PATHS_TCL_EDGE_AWARE` | `1`, `EDGE_FALLBACK_LEGACY` 가 0 에 가까움 | fallback 이 많으면 리포트에 방향 표기가 없는 것 — PT 옵션/버전 확인 |
| union 경로 수 | 0 이 아님 | 0 이면 TH 를 올려 재실행 |

`csv/union_paths_bypath.csv` 의 `n_corners_violating`(slack<0 코너 수)과
`n_corners_risky`(slack<TH 코너 수)로 "진짜 위반" 과 "위험" 을 사후에 나눌 수 있다.

### 2단계 — union 경로를 전 코너에서 재측정 + annotation

1단계가 만든 tcl 이름은 경로 수가 붙어 있으므로 **`ls` 로 실제 이름을 확인**한다:

```bash
ls /data/results/mycore_violscan_setup/*_violation_fixed_paths_*.tcl

python3 run_sweep.py \
  --design MyCore --top MyCoreTop \
  --spef-prefix mycore_14nm \
  --mode setup --si \
  --verilog   /data/deliver/mycore_icc2.v \
  --sdc       /data/deliver/mycore.sdc \
  --spef-root /data/deliver/spef \
  --db-root   /data/lib_db/db  --lib-root /data/lib_db/lib \
  --ref-db    /data/lib_db/db/<아무 측정 코너>.db \
  --reuse-strict-tcl /data/results/mycore_violscan_setup/<위에서 확인한>.tcl \
  --out-dir   /data/results/mycore_violscan_setup_annotated \
  --max-workers 3
```

- `--reuse-strict-tcl` 이면 run_sweep 의 `--max-paths`(top-N 추출용),
  `--edge-aware-fixed-paths`, `--max-fanout` 은 **적용되지 않는다**(strict tcl 생성
  단계를 통째로 건너뛰기 때문). `--ref-db` 는 경로 선정용이 아니라 로그/이름용으로만
  쓰이니 측정 코너 중 아무거나 준다.
- 산출물: `<out-dir>/annotated/<RC>/<corner>_fixed_annotated.txt` (ML 입력).

### 3단계 — QC (건너뛰지 말 것)

```bash
python3 qc/check_fixed_path_edge_consistency.py \
  --reports-dir /data/results/mycore_violscan_setup_annotated/reports/Cnom
python3 qc/analyze_pt_slew_load_coverage.py \
  --lib /data/lib_db/lib/<대표>.lib \
  --reports /data/results/mycore_violscan_setup_annotated/reports
```

전압 간 경로/엣지가 유지됐는지(라벨 유효성의 전제)와 Liberty grid 외삽 비율을 본다.
SI 데이터면 `qc/compare_si_on_off_arrival_fast.py` 로 SI 영향량 분포도 확인.

### 1-B 스모크 (전체 돌리기 전 필수)

```bash
# 코너 1개 + 작은 상한으로 5분 안에 끝나는 확인
python3 extract_violation_paths.py ... \
  --rc-corners Cnom --slack-threshold 0.05 \
  --max-paths 200 --max-workers 1 \
  --emit-fixed-paths-tcl --edge-aware-fixed-paths \
  --out-dir /tmp/smoke_setup
```
`summary.txt` 에 union 경로 수가 잡히고 tcl 이 생성되면 통과. 그 tcl 로 2단계도
`--rc-corners Cnom` 만 걸어 한 번 돌려 `annotated/` 가 나오는지까지 본 뒤 전체로 간다.

## 파이프라인 2 — crosstalk path_context_sweep

> **선행 조건: 파이프라인 1 의 annotated 리포트가 있어야 한다.** 7단계 중 ①단계
> (`parse_annotated_with_clock_segments.py`)의 입력이 바로 그 파일이고, 러너가 job
> 마다 존재를 확인한다(`run_sweep.py:169`). 없으면 그 job 은 못 돈다.
> (파이프라인 3 은 annotation 이 **필요 없다** — 독립 실행 가능.)

### ⚠️ 먼저 할 일 — annotation 을 파이프라인 2 가 찾는 자리에 놓는다

두 파이프라인의 디렉토리 규약이 다르다. **pt_annotation 을 돌렸다고 자동으로
저 자리에 놓이지 않는다.**

```
pt_annotation 이 쓰는 곳:
  <out-dir>/annotated/<RC>/<db_stem>_fixed_annotated.txt

path_context_sweep 이 찾는 곳 (run_sweep.py:115):
  <data-root>/annotation/<setup_sion|hold_sion>/temp_<T>/annotated/<RC>/<db_stem>_fixed_annotated.txt
                         └────────── 이 두 계층이 더 있다 ──────────┘
```

뒤쪽 `annotated/<RC>/<db_stem>_fixed_annotated.txt` 는 **양쪽이 완전히 같다.**
따라서 심볼릭 링크 한 번이면 된다(복사해도 되지만 용량이 크다):

```bash
# setup + 25C 예. mode/온도 조합마다 한 번씩.
mkdir -p /data/mycore_iter/annotation/setup_sion/temp_25
ln -s /data/results/mycore_violscan_setup_annotated/annotated \
      /data/mycore_iter/annotation/setup_sion/temp_25/annotated
```

- `setup` → `setup_sion`, `hold` → `hold_sion` (`ANALYSES`, `run_sweep.py:44`).
  이름이 `_sion` 인 데서 보듯 **SI 를 켜고(`--si`) 만든 annotation** 을 전제한다.
- `temp_<T>` 의 `T` 는 `25` / `m40` / `125`. pt_annotation 은 out-dir 하나당
  **온도 1개**만 다루므로(`--spef-temp`), 온도마다 별도 run + 별도 링크가 필요하다.
- 파일명의 `<db_stem>` 은 `DB_STEM_FORMAT` (`run_sweep.py:40`)이 만든다. db 파일명이
  우리 규약과 다르면 **`XTALK_DB_STEM_FORMAT` 환경변수로 덮어쓴다** — 코드 수정 불필요.
- 제대로 놓였는지는 `--dry-run` 이 알려준다. **전체 실행 전 반드시 한 번 돌린다.**

**환경변수로** 디자인 입력을 준다. 기본값이 우리 smallboom 케이스라 반드시 덮어쓴다.

```bash
cd crosstalk_features/path_context_sweep
setenv XTALK_VERILOG     /data/deliver/mycore_icc2.v      # bash: export
setenv XTALK_SDC         /data/deliver/mycore.sdc
setenv XTALK_SPEF_DIR    /data/deliver/spef
setenv XTALK_SPEF_PREFIX mycore_14nm
setenv XTALK_DATA_ROOT   /data/mycore_iter                # annotation/ db/ 등이 있는 루트

# 먼저 dry-run 으로 어떤 job 이 돌고 입력이 다 있는지 확인
python3 run_sweep.py --dry-run
# 스모크: 코너 1개 + context 몇 개만
python3 run_sweep.py --analysis setup --corner Cnom --temp 25 --vtag 0p8 \
                     --max-contexts 20 --jobs 1
# 전체 (옵션 생략 시 setup+hold × 3 RC × 3 온도 × 17 전압 = 306 job)
python3 run_sweep.py --jobs 12
```

`--jobs` = 동시 PT 라이선스 소비 수. `--limit-jobs N`, `--force`(기존 RPT 재생성),
`--keep-work`(중간파일 보존). 산출물:
`crosstalk/<setup|hold>/<RC>/TT_<V>V_<T>C.path_context_si_compact.by_path.rpt` (14컬럼).
디자인명/전압·온도 목록 등 사이트 종속값은 `run_sweep.py` 상단
(`TEMPS`/`VOLTAGES`/`DB_STEM_FORMAT`/`Job`)에 모여 있다.

## 파이프라인 3 — crosstalk coupling_pair_features

> **파이프라인 1/2 와 무관하게 단독으로 돌릴 수 있다.** 넷리스트·SDC·SPEF·db 와
> 시작/끝 레지스터 인스턴스 이름만 있으면 된다. annotation 산출물을 안 본다.
> (코드에 보이는 `annotated_delay_delta_max` 는 PrimeTime **넷 attribute 이름**이지
> pt_annotation 산출물이 아니다.)

단일 고정 경로(시작 FF ~ 끝 FF)에 대한 전압 스윕. **환경변수로** 준다.

```bash
cd crosstalk_features/coupling_pair_features
setenv XTALK_VERILOG    /data/deliver/mycore_icc2.v
setenv XTALK_SDC        /data/deliver/mycore.sdc
setenv XTALK_SPEF       /data/deliver/spef/mycore.Cnom_model_25.spef   # 전압 무관 1개
setenv XTALK_DB_DIR     /data/lib_db/db
setenv XTALK_OUT_DIR    /data/results/coupling_pair
setenv XTALK_START_CELL <시작 레지스터 인스턴스>
setenv XTALK_END_CELL   <끝 레지스터 인스턴스>

pt_shell -f extract_requested_si_features_unified.tcl
```

핵심 산출물: `<out>/requested_si_features_path1/requested_si_features.active_pairs.tsv`
(pair 별 crosstalk_delta, aggressor_bump, coupling_cap_ff, timing window 등).
db 파일명 패턴과 전압 목록(`VOLTAGES`)은 TCL 상단에서 수정.

## 라이선스 체크리스트 (현장에서 순서대로)

```bash
which pt_shell                                    # ① PT 가 PATH 에 있나 (없으면 PT_SOURCE 세팅)
echo $SNPSLMD_LICENSE_FILE $LM_LICENSE_FILE       # ② 라이선스 서버 env 잡혀 있나 (port@host)
lmutil lmstat -a -c $SNPSLMD_LICENSE_FILE | grep -i prime   # ③ PrimeTime 좌석 총/사용중 확인
```

- 러너들의 `--max-workers`/`--jobs` = **동시 pt_shell 프로세스 수 = 동시 라이선스 소비 수**.
  ③에서 확인한 **여유 좌석 이하**로 준다. 도구는 가용 좌석을 조회하지 않는다(단순 동시성 상한).
- pt_shell 1개 = PrimeTime base 1석. `--si`/`SI=1` 이면 **PrimeTime-SI 1석 추가** 소비.
- 좌석 초과 시 "unable to checkout license" 로 해당 job 실패.
  `extract_violation_paths.py` 는 실패 코너를 건너뛰고 계속 진행(summary 에 FAILED, exit 2);
  다른 러너는 해당 job 이 실패로 남는다. 좌석 확보 후 재실행.
- 사이트에 따라 Synopsys 라이선스 큐잉(실패 대신 대기) 정책을 쓰기도 한다 — CAD 팀에 확인.

## 트러블슈팅 (실제로 겪은 것들)

| 증상 | 원인 | 해결 |
|---|---|---|
| `SyntaxError` / `from __future__` 관련 실패 | 시스템 `python3` 이 3.6 | 3.9+ python 을 PATH 앞에 두거나 그 인터프리터로 직접 실행. 러너는 하위 파서를 `sys.executable` 로 호출하므로 러너를 3.9+ 로 띄우면 파서도 따라온다 |
| SI 결과가 이상/무의미 | grounded SPEF (coupling cap 없음) | `COUPLING_CAP: YES` 로 재추출한 SPEF 사용. pt_annotation 은 pre-flight 로 자동 중단 |
| `read_parasitics` 후 coupling 이 안 잡힘 | `-keep_capacitive_coupling` 누락 | SI 경로는 `--si`/`SI=1` 로 돌려야 tcl 이 이 옵션을 켠다 |
| db 코너 정렬이 뒤죽박죽 | db 파일명이 `tt0pNvNNc` 전압 토큰 규약과 다름 | 파일명을 규약에 맞추거나 러너 상단 파싱부 수정 |
| SPEF 를 못 찾음 | 파일명 포맷 불일치 | pt_annotation `--spef-name-format`, crosstalk 는 `XTALK_SPEF_PREFIX`/상단 포맷 확인 |
| PT 라이선스 부족으로 job 대기/실패 | `--max-workers`/`--jobs` 가 가용 라이선스 초과 | 값을 낮춘다 (가용 SI 라이선스 수 이하) |
| Res/Cpin/시간 값 스케일이 예상과 다름 | 코드가 SPEF `*R_UNIT`/`*C_UNIT`/`*L_UNIT`·Liberty 단위를 정규화하지 않고 **원시값 그대로** 사용 | `grep -m4 -iE '^\*[TCRL]_UNIT' <spef>` 로 확인("받은 SPEF 점검" 절). 출력 단위 = 입력 단위. **서로 다른 단위의 데이터셋을 한 학습셋에 섞지 말 것** (한 데이터셋 내부는 통일되어 문제없음) |
| N/A 매칭 실패가 대량 발생 | SPEF/netlist 이름 규약이 코드가 아는 평탄화 변형과 다름 (다른 추출 툴/표기) | 이름 매칭 실패는 CONN(핀 연결) 매칭이 대부분 흡수하나, 인스턴스·핀 토큰까지 다르면 뚫린다. `res.py` 의 `bus_flatten_variants`/평탄화 규칙을 그쪽 SPEF 규약에 맞게 확장. N/A 는 `summary` 의 `na_tokens`/`na_lines` 로 자가 집계되니 돌려보면 감지된다 |
| summary 에 `TRUNCATED?` | 코너 리포트가 `--max-paths` 상한에 닿음 | `--max-paths` 를 키워 **재실행**. 잘린 채 union 하면 코너 간 비교가 무의미 |
| union 경로 수가 0 | TH 안쪽에 경로가 없음 | `--slack-threshold` 를 올려 재실행. 기본 0.05 에서도 0 이면 그 코너 집합엔 위험 경로가 없는 것 — SDC 시간 단위가 ns 가 맞는지도 확인 |
| 2단계에서 경로 수가 1단계 union 보다 적음 | 데이터 핀 체인이 없는 경로는 tcl 에 안 실림 | 정상. summary 의 `PATHS_NO_DATA_CHAIN` 개수와 대조 |
| 전압마다 같은 idx 의 경로/엣지가 다름 | edge-aware 를 안 켬 | 1단계에 `--edge-aware-fixed-paths` 를 주고 재실행. run_sweep 쪽에 줘도 무시된다 |
| `summary` 의 `THROUGH_POLICY=SAMPLED(N)` | `--fixed-through-count` 에 양수를 줌 | `0`(기본, 전체 체인)으로 재실행. 샘플링은 쌍둥이 경로를 뭉갠다 |
| 파이프라인 2 `--dry-run` 이 annotated 리포트 없다고 함 | pt_annotation 산출물이 `annotation/<분석>_sion/temp_<T>/` 계층 아래에 없음 | 파이프라인 2 절의 `ln -s` 로 재배치. 뒤쪽 `annotated/<RC>/...` 는 양쪽이 같으므로 링크 하나면 된다 |
| 파이프라인 2 가 db_stem 을 못 찾음 | db 파일명이 `DB_STEM_FORMAT` 기본 패턴과 다름 | `XTALK_DB_STEM_FORMAT` 환경변수로 덮어쓴다(코드 수정 불필요) |

## Claude 를 못 쓰는 환경일 때 (사람이 직접)

이 파일 하나로 완결되게 써 뒀다. Claude 없이 진행할 때 순서:

1. **읽을 것**: 이 파일 위에서부터 순서대로. 상세가 필요하면 그때만
   `pt_annotation/README.md`(1-B 인자·산출물 상세), `crosstalk_features/README.md`,
   `spef_extraction/README.md` 를 편다. 셋 다 실행 예시가 들어 있다.
2. **환경 확인**: 위 "실행 전 체크" 3줄 + "라이선스 체크리스트" 3줄.
   `python3` 이 3.6 이면 반드시 3.9+ 인터프리터로 실행한다(`python3.11 run_sweep.py ...`
   처럼 직접 호출해도 된다 — 러너가 하위 파서를 `sys.executable` 로 부르므로 따라온다).
3. **인자 확인**: 모든 러너가 `--help` 를 지원한다. 이 문서의 예시 인자와 대조.
4. **순서대로 실행**: 파이프라인 0(필요시) → **1-B 스모크** → 1-B 1단계 → **게이트
   확인** → 1-B 2단계 → 3단계 QC → (필요시) **annotation 재배치(`ln -s`) →
   파이프라인 2 `--dry-run` → 파이프라인 2**. 파이프라인 3 은 아무 때나 단독 실행.
   `--mode setup` 과 `--mode hold` 를 각각 1세트씩.
5. **막히면**: 위 트러블슈팅 표를 먼저 본다. 대부분 여기 있다.

**판단이 필요한 지점은 딱 세 곳이고, 나머지는 기계적이다:**
`--slack-threshold`(위험 마진을 얼마로 볼지) / `--max-workers`(가용 라이선스 좌석) /
`TRUNCATED?` 가 떴을 때 `--max-paths` 를 얼마로 올릴지. 이 셋만 정하면 된다.

## Claude 에게 시킬 때 (권장 프롬프트)

> "이 패키지 `CLAUDE.md` 와 `pt_annotation/README.md` 를 읽고, 우리 디자인은
> `<디자인명>`, 넷리스트/SDC/SPEF/db 는 `<경로>` 에 있어. **파이프라인 1-B
> (violation union route)** 로 갈 거야. 먼저 `--help` 로 인자 확인하고, 1-B 스모크
> (코너 1개 + 작은 `--max-paths`)를 돌린 뒤 `summary.txt` 게이트를 확인하고,
> 정상이면 전체 명령을 제안해줘. 우리 서버 `pt_shell` 경로와 라이선스,
> `python3` 버전(3.9+)도 먼저 확인해줘."

**항상 작은 범위(1 코너 / dry-run / max-contexts)로 먼저 확인한 뒤 전체를 돌린다.**
전체 스윕은 코너 수 × 파일 I/O 가 커서 시간이 오래 걸린다.
