# crosstalk_features — Crosstalk / SI Feature 추출

PrimeTime SI 의 `report_delay_calculation -crosstalk` 과 net/pin attribute 를 이용해
crosstalk delta 와 victim–aggressor feature 를 추출하는 두 파이프라인.

| 하위 디렉토리 | 용도 | 산출 단위 | 성격 |
|---|---|---|---|
| `path_context_sweep/` | 전 코너 스윕 (setup/hold × RC × 온도 × 전압) | path arc 별 crosstalk delta + window | **주력** — ML 학습 데이터 생산 |
| `coupling_pair_features/` | 단일 고정 경로 심층 분석 (전압 스윕) | victim–aggressor active pair 별 feature | **보조** — 검증/대조용 |

> **두 파이프라인의 위치.** 학습 데이터 생산의 **주력은 `path_context_sweep/`** 이며,
> 전 코너 × 전 path 의 crosstalk 를 대량 추출한다. `coupling_pair_features/` 는
> 그 결과를 **검증·디버깅**하기 위한 보조 도구다 — 특정 한 경로를 골라 전압 스윕하며
> victim–aggressor 쌍 단위로 깊게 뜯어보아, `path_context_sweep/` 이 뽑은 crosstalk
> delta 가 물리적으로 타당한지 대조하는 용도다. 학습 데이터 자체는 주력 파이프라인
> 하나로 충분하며, `coupling_pair_features/` 는 필수 산출물이 아니다.

공통 PT 골격: `read_verilog → link_design(db) → read_sdc →
read_parasitics -keep_capacitive_coupling(SPEF) → set_propagated_clock →
update_timing → report_delay_calculation -crosstalk`.
**coupling cap 이 유지된 SPEF 가 필수** (StarRC `COUPLING_CAP: YES`).

> **단위 주의.** 추출되는 수치 feature(crosstalk_delta, aggressor_bump,
> coupling_cap_ff, arrival window, slew, cap 등)는 PrimeTime/ SPEF/Liberty 가
> 보고하는 **원시 단위를 그대로** 따른다. 코드가 단위를 재정규화하지 않으므로,
> SPEF 헤더(`T_UNIT`/`C_UNIT`/`R_UNIT`)와 PT 시간 단위가 데이터셋마다 다르면
> 값의 스케일이 달라진다(예: 시간 ns vs ps, cap FF vs PF). 실행 전 단위를
> 확인하고 **서로 다른 단위의 데이터셋을 섞지 말 것.**

---

## 1. path_context_sweep — 전 코너 crosstalk delta 스윕

### 흐름 (job 당 7단계, 러너가 자동 수행)

```
annotated fixed-path report (pt_annotation 산출물)
 ①parsers/parse_annotated_with_clock_segments.py   launch/data/capture 구간별 victim arc 추출
 ②parsers/make_unique_path_arc_contexts.py          (victim_net, driver, load) unique context
 ③PT tcl/dump_path_context_delay_calculation.tcl    context 별 report_delay_calculation
                                                     -crosstalk -max|-min 덤프
 ④parsers/parse_path_context_delay_calculation.py   aggressor 표/delta 파싱 → active_features
 ⑤parsers/prepare_compact_timing_window_requests.py 윈도우 조회 대상 핀/net 리스트
 ⑥PT tcl/dump_compact_timing_windows.tcl            victim/aggressor arrival window + slew
 ⑦parsers/make_compact_path_context_report.py       최종 *.by_path.rpt
```

### 실행 예시

```bash
export PT_SOURCE=/path/to/site_pt_setup.cshrc   # pt_shell 이 PATH 에 없을 때만
export PT_LICENSE=27020@license-server          # 필요 시

python3 run_sweep.py \
  --data-root /data/mycore_iter \
  --analysis setup --corner Cnom --temp 25 --vtag 0p8 \
  --jobs 3
# 전체 스윕: 옵션 생략 시 setup+hold × 3 RC × 3 온도 × 17 전압 = 306 job
# --dry-run 으로 입력 파일 존재 여부를 먼저 확인 권장
# --max-contexts N 으로 smoke test 가능
```

### `--data-root` 기대 레이아웃

```
<data-root>/
  annotation/<setup_sion|hold_sion>/temp_<T>/annotated/<RC>/<corner>_fixed_annotated.txt
  db/saed14rvt_tt<V>v<T>c_ccs_*.db
  implementation/netlist/smallboom_14nm_icc2.v
  implementation/sdc/smallboom_14nm_icc2.sdc
  implementation/spef/smallboom_14nm.<RC>_model_<T>.spef
  crosstalk/            ← 산출물이 여기 생성됨
```

파일명 패턴(디자인명, 라이브러리 스타일 태그)은 `run_sweep.py` 상단의
`TEMPS`/`VOLTAGES`/`Job` property 에 정의되어 있다. 다른 디자인/라이브러리에
적용할 때 이 부분을 수정하면 된다 — 사이트 종속성이 이 한 곳에 모여 있다.

### 산출물

`crosstalk/<setup|hold>/<RC>/TT_<V>V_<T>C.path_context_si_compact.by_path.rpt`

14컬럼: path_segment, victim_net, aggressor_net, **crosstalk_delta**,
aggressor_bump, number_of_aggressors, victim_load_pin,
victim/aggressor arrival window(min/max), aggressor_driver_slew_max,
coupling_cap_ff 등.

산출물이 어떻게 생겼는지는 **`example_path_context_by_path_excerpt.rpt`** 참조
(실제 run 에서 FIXED_PATH 1개 블록 발췌; 상단 주석에 컬럼 설명 포함).

### 이력 참고 (3nm 대비 변경점)

이 코드는 3nm BoomCoreV3 파이프라인에서 발전한 14nm 판이며 다음이 개선됐다:
- setup 에서 `report_delay_calculation -crosstalk -max` 를 **명시** (3nm 판은 옵션 없음)
- aggressor driver slew 가 hierarchy boundary 에서 0 으로 나오는 문제를
  `get_pins -leaf` 로 원천 회피 (3nm 판은 `all_fanin` 사후 추적)

---

## 2. coupling_pair_features — victim–aggressor pair feature 테이블

단일 고정 경로에 대해 전압 스윕(기본 17종)을 돌며 active aggressor 를 분류하고,
coupling cap·timing window overlap 을 결합한 pair 단위 feature 를 만든다.

### 실행 예시

```bash
export XTALK_VERILOG=/data/netlist/mycore_icc2.v
export XTALK_SDC=/data/sdc/mycore_icc2.sdc
export XTALK_SPEF=/data/spef/mycore.Cnom_model_25.spef     # 전압 무관 고정
export XTALK_DB_DIR=/data/db
export XTALK_OUT_DIR=/data/results/coupling_pair
export XTALK_START_CELL=<시작 레지스터 인스턴스>
export XTALK_END_CELL=<끝 레지스터 인스턴스>

pt_shell -f extract_requested_si_features_unified.tcl
```

모든 입력은 Tcl 변수(`pt_shell -x "set VERILOG …"`)로도 오버라이드 가능.
db 파일명 패턴과 전압 목록(`VOLTAGES`)은 TCL 상단에서 수정한다.
unified TCL 이 Pass1(PT) → Python 파서 2종 → Pass2(PT) → 최종 테이블 생성기를
한 번에 오케스트레이션한다 (`parsers/` 는 스크립트 옆에 있으면 자동 인식).

### 산출물

`<out>/requested_si_features_path1/`
- **`requested_si_features.active_pairs.tsv`** — pair 별: crosstalk_delta,
  aggressor_bump, victim load arrival window, aggressor driver arrival/slew,
  coupling_cap_ff, total cap 등 (핵심 feature 테이블)
- `requested_si_features.victims.tsv` — victim net 단위 요약
- `requested_si_features.summary.tsv` — 전압별 통계
- `active_pairs_by_voltage/<vtag>.active_pairs.tsv` — 전압별 분할본

---

## 다른 공정(SS/FF) / BEOL 코너로 확장

공정(SS/FF)은 **트랜지스터 라이브러리(.db)** 축이므로 db 이름 지정에,
BEOL(RC) 코너는 **RC 코너 이름**에 영향을 준다. (SPEF 추출 자체는
`../spef_extraction/README.md` 참조 — SPEF 는 배선 RC 라 SS/FF 와 무관.)

- **path_context_sweep — 공정 db 이름** — db 이름은 `XTALK_DB_STEM_FORMAT`
  환경변수로 **통째로 지정**하므로, `tt` 대신 공정 접두사(`ss`/`ff`/`ssg`…)를 넣은
  포맷을 그대로 넘기면 된다(코드 수정 불필요). 예:
  `export XTALK_DB_STEM_FORMAT='mylib_ss{vtag}v{db_temp}_ccs_..._{style}'`.
  출력 라벨 `feature_corner`의 공정 접두사는 `XTALK_PROCESS` 환경변수(기본 `tt`)로
  지정한다 — 예: `export XTALK_PROCESS=ss` (라벨용이라 db 조회엔 영향 없음).
- **path_context_sweep — RC(BEOL) 코너 이름** — `CORNERS` 상수(`run_sweep.py`
  상단, 기본 `Cmin/Cnom/Cmax`)를 그쪽 코너 이름으로 교체한다. SPEF 파일명은
  `<prefix>.<corner>_model_<temp>.spef` 규약(`Job.spef`)을 따르므로 코너 이름이
  파일명에 그대로 들어간다.
- **path_context_sweep — 온도** — `TEMPS` 딕셔너리(`run_sweep.py` 상단)에서
  `db_temp`/`spef_temp`/`style` 매핑을 온도별로 추가/수정한다.
- **coupling_pair_features — 공정/온도 db** — `lib_db_for_voltage` proc의 기본
  db 이름을 **`XTALK_DB_STEM_FORMAT` 환경변수**(`{vtag}` placeholder, 기본
  `saed14rvt_tt{vtag}v25c_ccs_rth0p01_full385_3ns250fj_mono`)로 지정한다 — 공정
  접두사·온도를 바꾸려면 이 포맷을 넘긴다(`setenv XTALK_DB_STEM_FORMAT
  "mylib_ss{vtag}v125c_ccs_..."`). 특정 vtag 만 다른 경로면 Tcl 변수
  `LIB_DB_BY_VTAG(<vtag>)` 배열이 최우선이다. 전압 목록은 `VOLTAGES` Tcl 변수로 override.
