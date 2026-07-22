# spice — 파일별 상세 (HSPICE 실행 + 분석)

SPICE deck을 HSPICE로 돌리고, mt0를 파싱해 PT와 비교/리포트하는 코드. 전부 `py/` 아래.

크게 3그룹: **① HSPICE 실행·파싱** / **② PT vs SPICE 비교·리포트** / **③ 고립 셀 플로우**.

---

## ① HSPICE 실행 + mt0 파싱

### `path_arc_quiet_compare.py` ★ (arc-align HSPICE 실행기)
- **3개 서브커맨드**:
  - `prepare-stage-csv-from-report --si-rpt --path-id --out-dir --output-name` — PT SI 리포트 → stage arc 목록(sl.csv). (deck 생성 준비 단계, S3a)
  - `prepare-stage-csv` — PT stage csv 버전.
  - `run-quiet-compare --stage-csv --manifest --out-csv --out-rpt --hspice [--force --continue-on-error]` — 각 arc deck을 **HSPICE로 quiet + align 실행** 후 crosstalk 집계 → `ac.csv`. (S3c)
- ac.csv = stage별 pt_si/pt_arc_delta/quiet/align worst·center 등 (모든 비교의 원천 데이터).

### `parse_pt_native_mt0.py`
- **full-path base deck의 HSPICE .mt0 파싱**. `native_raw_measure.csv`(전 measure 원본) + `native_delay_breakdown.csv`(cell/net delay·slew 분류, 핀 역할 기반).
- 인자: `--batch-dir [--raw-csv --breakdown-csv --summary-json --fail-on-missing]`.
- run_pt_native_spice_flow가 내부적으로 호출; `pt_vs_native_stage_compare.csv`의 SPICE값 근원.

---

## ② PT vs SPICE 비교 / 리포트

### `stage_pt_spice_compare.py` ★ (stage별 절대 delay 뷰)
- full-path base(cell/net) + arc-align(crosstalk)을 stage_idx로 조인 → stage별 **PT vs SPICE cell/net delay** 표 + `d(SP-PT)`(stage 총 delay 차) 컬럼.
- 인자: `--fullpath(pt_vs_native_stage_compare.csv) --arc(ac.csv) --title --out-csv [--top]`. `--top 0`=전 stage.

> `stage_pt_spice_compare.py`의 `--interp <interp_ref.csv>` 옵션: PT 컬럼(cell/net)을 보간 reference(`interp_pt_corner.py` 출력)로 교체해 같은 양식의 표 생성 — unseen corner에서 "예측 PT vs SPICE" cell/net 분리 비교용. 미지정 시 기존 동작과 동일.

### `crosstalk_delta_compare.py` ★ (stage별 crosstalk delta 뷰)
- crosstalk **효과만** 비교: PT(SIoff→SIon) vs HSPICE(quiet→align). dPT=pt_arc_delta_selected, dSP=align_worst−quiet. + repro%.
- 인자: `--arc(ac.csv) --fullpath(핀라벨용) --title --out-csv [--center]`. `--center`=align center(nominal).

### `summary_pt_spice.py` ★ (path=행 요약)
- run 아래 p{P}/의 s1(PT SI off/on) + base + ac.csv를 읽어 **path마다 한 줄**: base cell(PT|SP|gap%), SI-on net(PT|SP재귀속|repro%), total(PT|SP|%).
- 인자: `--root --paths(146,153,..) --labels --name`.

### `format_pt_native_report.py`
- parse_pt_native_mt0 출력을 **사람이 읽는 compact stage 표**로 포맷. 인자: `--batch-dir [--fail-on-missing]`.

### `format_pt_si_report.py`
- PT deck-gen이 남긴 report_timing dump를 stage 규약으로 파싱 → **PT stage csv + PT-vs-HSPICE 비교** 리포트. 인자: `--batch-dir --pt-stage-csv --native-stage-csv --compare-* ...`.

### `format_cell_net_split_report.py`
- PT SI + quiet/aligned HSPICE를 **cell/net breakdown**으로 포맷. 인자: `--path-id --si-off-rpt --si-on-rpt --arc-csv --out-rpt`.

### `compare_pt_annotated_native.py`
- PT annotated path JSON vs native SPICE 비교 (launch clock핀→종점 D 기준). 인자: `--batch-dir --path-compare-csv --stage-compare-csv --report-rpt`.

### `compare_native_vs_retarget.py`
- **b-1 retarget 검증**: NATIVE(그 전압 Liberty로 PT가 직접 만든 arc-align deck) vs RETARGET(0.8V deck 전압만 retarget) 비교. retarget의 ac.csv PT컬럼은 stale(reference 코너)임에 주의.
- 인자: `--native --retarget --title --out-csv`.

---

## ③ 고립 셀 플로우 (PT 무관, 순수 SPICE 모델차 확인)

### `gen_isolated_cell_decks.py` ★
- 각 stage 구동셀을 **고립**시켜 HSPICE deck 생성: **PT의 입력 slew + 올바른 path 핀 + 실제 net load**로 구동, 나머지 입력은 sensitize(단순게이트 INV/BUF/ND/NR/AN/OR 자동, 복합/B-입력/flop은 skip).
- 인자: `--stage-csv(pt_vs_native_stage_compare.csv) --anno(annotated 리포트) --outdir --vdd --spf --tran-ps(기본 400; **0.6V는 1200 필요** — slew 최대 208ps→램프 347ps)`.
- 출력: `stg_<N>.sp` + `manifest.csv`. (라이브러리-종속: SAED14 셀명/sensitization 하드코딩)
- 검증 결과: 47-stage SUM = 0.8V +0.8% / 0.6V **-0.8%** (풀패스 -24.9%와 대비 → 0.6V 붕괴는 100% slew 전파 탓).

### `gen_isolated_report.py`
- 위 deck들의 HSPICE 결과(mt0) vs PT CCS cell delay를 **리포트**로: 고립(PT-slew) SUM/중앙 gap + full-path(SPICE-slew) 대조. 이상치 표시.
- 인자: `--isodir --fullpath --name --vdd`. 출력: `REPORT_<name>.{md,txt}`.

---

## 데이터/툴 의존성 (실행 전 필요)
- **HSPICE**: `/home/synopsys_tool/Hspice/.../hspice` (실행파일 경로) + 라이선스.
- **modelcard/SPF**: deck의 `.lib`/`.include`가 참조 (base deck은 자체 포함; 고립 플로우는 `gen_isolated_cell_decks.py` 상단 `MODELCARD`/`SPF` 상수 또는 `--spf`).
- **annotated 리포트**: 고립 플로우 입력 (셀ref/net cap/방향).

## 전형적 흐름
```
[pt_spice_deck에서 만든 deck]
  → path_arc_quiet_compare.py run-quiet-compare → ac.csv (HSPICE 실행)
  → stage_pt_spice_compare.py / crosstalk_delta_compare.py / summary_pt_spice.py → 비교표

[고립 셀, PT 무관]
  annotated + modelcard + SPF
  → gen_isolated_cell_decks.py → stg_*.sp → HSPICE → gen_isolated_report.py → 리포트
```
