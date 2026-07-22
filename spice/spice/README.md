# spice — HSPICE 실행 + 결과 분석

SPICE deck을 HSPICE로 돌리고, mt0를 파싱해 PT와 비교/리포트하는 코드. **입력 = .sp deck (pt_spice_deck/ 에서 생성) 또는 셀 넷리스트.**

## 파일 (py/)

### HSPICE 실행 + 집계
- `path_arc_quiet_compare.py` — arc-align deck을 HSPICE로 quiet+align 실행 후 집계
  - `run-quiet-compare` = HSPICE 실행 + crosstalk 집계
  - `prepare-stage-csv-from-report` = PT SI 리포트→stage arc 목록 (deck 준비)
- `parse_pt_native_mt0.py` — full-path base deck의 .mt0 파싱 (cell/net 분류)

### PT vs SPICE 비교/리포트
- `stage_pt_spice_compare.py` — stage별 cell/net delay 비교 (+ `d(SP-PT)` 컬럼)
- `crosstalk_delta_compare.py` — stage별 crosstalk delta: PT(SIoff/on) vs HSPICE(quiet/align)
- `summary_pt_spice.py` — path=행 요약표
- `format_pt_native_report.py` / `format_pt_si_report.py` / `format_cell_net_split_report.py` — 리포트 포맷
- `compare_pt_annotated_native.py` / `compare_native_vs_retarget.py` — 대조 도구

### 고립 셀 HSPICE 플로우 (순수 spice, PT 무관)
- `gen_isolated_cell_decks.py` — 셀을 고립시켜 PT slew+실제 load로 HSPICE deck 생성 (단순게이트 자동 sensitization)
- `gen_isolated_report.py` — SPICE(PT-slew) vs PT CCS cell delay 리포트

## ★ 새 머신에서 반드시 가져와야 할 것

### 1) 데이터 (SPICE 모델 — HSPICE 실행에 필수)
| 파일 | 원경로 | 용도 |
|---|---|---|
| modelcard | `input2/modelcard/saed14nm_hspice_local.lib` | 트랜지스터 모델 (deck의 .lib) |
| 원본 modelcard | `/home/0Park/SAED14nm_PDK_12142021/SAED14_PDK/hspice/saed14nm.lib` | 고립 플로우 기본 모델 |
| cell SPF | `input2/modelcard/saed14nm_rvt.spf` (78M) | 셀 subckt 넷리스트 |
| char SPF | `/home/hyunss/thermal_aware_sta/primelib_tt0p7/saed14nm_rvt_with_clksplt_alias.spf` | 고립 플로우 subckt |
| alias | `input2/modelcard/saed14nm_cksplt_alias.sp` | 클럭 splitter alias |
| annotated 리포트 | `input2/pt_result/BoomCore_input2_..._fixed_annotated.txt` | 고립 플로우 입력(셀ref/cap/방향) |

### 2) 툴
- `hspice`: /home/synopsys_tool/Hspice/W-2024.09-SP1/hspice/linux64/hspice (디렉토리 아니라 이 실행파일)
- `prime.bashrc` + 라이선스 `SNPSLMD_LICENSE_FILE=26585@cscad`
- (재특성화 시) `primelib`: /home/synopsys_tool/Primelib/W-2024.09-SP5/bin/primelib, `lc_shell`: /home/synopsys_tool/Library_compiler/lc/T-2022.03-SP3/bin/lc_shell

## ★ 고쳐야 할 하드코딩 경로
- `gen_isolated_cell_decks.py` 상단 상수:
  - `MODELCARD = "/home/0Park/.../saed14nm.lib"`
  - `SPF = "/home/hyunss/.../saed14nm_rvt_with_clksplt_alias.spf"`
  → 새 머신 경로로 수정 (또는 `--spf` 인자 사용)

## 흐름 요약
```
(pt_spice_deck 에서 만든) .sp deck
  → [path_arc_quiet_compare.py run-quiet-compare] → HSPICE 실행 + ac.csv
  → [stage_pt_spice_compare.py / crosstalk_delta_compare.py / summary_pt_spice.py] → 비교표

고립 셀 (PT 무관):
  annotated 리포트 + modelcard + SPF
  → [gen_isolated_cell_decks.py] → 고립 deck → HSPICE → [gen_isolated_report.py] → 리포트
```
