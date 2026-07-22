# pt_spice_deck — SPICE deck 생성 (PrimeTime 기반)

design + PrimeTime으로 SPICE deck을 만드는 코드. **출력 = .sp deck** (full-path base deck, arc-align crosstalk deck, PT SI on/off 리포트).

## 파일

### tcl/ — PrimeTime이 실행하는 tcl (write_spice_deck)
- `run_pt_native_spice_deck.tcl` — full-path base deck 생성 (aggressor 없는 순수 victim)
- `run_pt_aligned_path_arcs_spice_deck.tcl` — arc-align crosstalk deck 생성 (전 stage)
- `run_pt_aligned_arc_spice_deck.tcl` — 단일 arc deck
- `report_fixed_paths_si_on_off.tcl` — PT SI-on/off + crosstalk_delta 리포트

### py/ — PT 구동 + deck 후처리
- `run_pt_native_spice_flow.py` — full-path base deck 배치 생성 (pt_shell 호출)
- `patch_pt_native_spice_deck.py` / `patch_targeted_spice_measures.py` — deck 조건 패치
- `retarget_corner_deck.py` — arc-align deck을 다른 전압으로 retarget (unseen corner)
- `inject_victim_slew.py` — victim 입력 slew 주입 (method ③)
- `shift_aggressor_pwl.py` / `_perstage.py` — aggressor PWL 시각 이동
- `freeze_noneffective_aggressors.py` / `reduce_aggressor_rc.py` / `interp_spef_temp.py` — deck 비용/조건 조정

### config/ — 전압/코너별 config (json)
- `pt_native_spice_config_input2_cnom25.json` — 0.8V 기준
- `..._0p78v/0p7v/0p625v/0p6v.json` — 저전압 코너
- `..._0p6v_origmodel.json` — 원본 modelcard 사용판

### *.sh — 마스터 오케스트레이터 (PT deck 생성 + HSPICE 실행 + 분석 전부)
- `run_fullflow.sh` (0.8V), `run_fullflow_0p78v/0p7v/0p625v/0p6v.sh`
- **주의**: 이건 spice/ 쪽 도구(HSPICE 실행·분석)도 호출한다 → 두 디렉토리 다 필요.

## ★ 새 머신에서 반드시 가져와야 할 것

### 1) 데이터 (design + 라이브러리, ~9GB) — 원래 `.../pt_spice_deck/` 아래
| 경로 | 크기 | 내용 |
|---|---|---|
| `input2/design_files/` | 4.7G | verilog(.v.gz), sdc, spef |
| `input2/CCS/*.db` | 1.6G | 0.8V CCS Liberty .db |
| `input2/modelcard/` | 78M | saed14nm_hspice_local.lib, saed14nm_rvt.spf, saed14nm_cksplt_alias.sp |
| `input2/tcl/` | 6.4M | BoomCore_input2_Cnom25_fixed_paths_3000.tcl (fixed path 정의) |
| `input2/pt_result/` | 252M | annotated 리포트 (분석용) |
| `0p7V/ 0p6V/ 0p625/ 0p78/` | ~456M each | 저전압 CCS Liberty .db (커스텀 특성화) |

### 2) 툴 (새 머신에 설치/경로 확인 필요)
- `pt_shell`: /home/synopsys_tool/Primetime/W-2024.09-SP3/bin/pt_shell
- `prime.bashrc`: /home/synopsys_tool/prime.bashrc
- 라이선스: `SNPSLMD_LICENSE_FILE=26585@cscad` (새 머신용 서버로 교체)

## ★ 새 머신에서 고쳐야 할 경로 (하드코딩)
- `run_fullflow*.sh`: `BASE=`, `PT=`, `HS=`, `source .../prime.bashrc`, `$BASE/code/...` 경로 → 새 위치로
- `config/*.json`: `verilog/sdc/spef/lib_db/model_card/cell_spf/fixed_tcl/tcl/setup_script` 절대경로 → 새 위치로
- `config/..._0p6v_origmodel.json`: model_card = `/home/0Park/.../saed14nm.lib` (원본 modelcard, 별도 가져오기)

## 흐름 요약
```
design(verilog/sdc/spef) + CCS lib + modelcard
  → [tcl + run_pt_native_spice_flow.py]  → base deck (.sp)
  → [run_pt_aligned_path_arcs...tcl]     → arc-align deck (.sp)
  → [retarget_corner_deck.py]            → 다른 전압 deck (.sp)
  → (이후 spice/ 에서 HSPICE 실행)
```
