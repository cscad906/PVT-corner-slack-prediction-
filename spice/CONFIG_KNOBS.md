# 사용자 조정 변수·옵션 (knobs) 정리

**모든 조정값은 스크립트 맨 위 `USER CONFIG` 블록에 있음.** 본문은 안 건드림.
`① 반드시 수정(환경)` / `② 실험 조건` / `③ 고급`.

---

## ⓪ 이식 체크리스트 — 새 머신에서 바꿔야 하는 경로 전부

절대경로가 박혀 있는 곳은 딱 **4군데**다. 아래 순서로 바꾸면 끝.

### A. 셸 스크립트 USER CONFIG (`pt_spice_deck/run_fullflow.sh` + `run_fullflow_unseen.sh`)
```
CODE_DECK/CODE_SPICE  코드 위치 — 스크립트 위치에서 자동감지 (수정 불필요)
DATA_BASE             데이터 루트 (설계·Liberty·출력, ~9GB) ★
PT / HS / PRIME_BASHRC / LICENSE   툴 실행파일 + 셋업 + 라이선스 서버 ★
VERILOG_FILE / SDC_FILE / SPEF_FILE / FIXED_TCL_FILE   설계 파일 (DATA_BASE 기준) ★
LIB_DB_FILE / CONFIG  (unseen만) 목표전압 db + config json ★
```

### B. config json 내부 (`pt_spice_deck/config/*.json`, 8개 전부) — 경로 키 12개
```
project.root          데이터 루트                     → 새 DATA_BASE
project.work_dir      ★함정: /home/KSW/code/pt_spice_deck/py 절대경로
                        — 코드 폴더 위치가 다르면 데이터 안 옮겨도 깨짐 → 새 코드 위치로
project.output_root   출력 루트                       → 새 DATA_BASE/output/input2
reference_pt.verilog / .sdc / .spef / .lib_db          설계+Liberty → 새 위치
path_registry.fixed_tcl                                path 목록 tcl → 새 위치
prime_time.setup_script / hspice.setup_script          prime.bashrc → 새 위치
prime_time.tcl        ★함정: /home/KSW/code/pt_spice_deck/tcl/... 절대경로 → 새 코드 위치로
spice_model.model_card / .cell_spf                     modelcard + 셀 SPF → 새 위치
```
일괄 치환 예:
```bash
sed -i 's|/home/KSW/auto_spice_breakdown/codex/pt_spice_deck|<새 DATA_BASE>|g; s|/home/KSW/code|<새 코드 위치>|g' pt_spice_deck/config/*.json
```

### C. 파이썬 상단 상수 (고립 셀 플로우만, `spice/py/gen_isolated_cell_decks.py`)
```
MODELCARD = /home/0Park/.../saed14nm.lib      원본 PDK modelcard → 새 위치
SPF       = /home/hyunss/.../..._alias.spf    특성화용 셀 SPF (--spf 인자로도 대체 가능)
```
(메인 플로우는 이 파일 안 씀 — 고립 셀 검증 돌릴 때만.)

### D. 별도 가져가야 하는 데이터 파일 (코드 밖, 잊기 쉬움)
```
/home/0Park/.../saed14nm.lib                  원본 PDK modelcard (C + 0p6v_origmodel.json이 참조)
/home/hyunss/.../saed14nm_rvt_with_clksplt_alias.spf   고립 플로우 SPF
DATA_BASE 전체 (~9GB): input2/{design_files,modelcard,tcl,CCS} + 0p6V/0p625/0p7V/0p78 db + output/
```

### 검증 커맨드 — 빠뜨린 경로가 없는지 전수 확인
```bash
grep -rho "/home/[A-Za-z0-9_/.]*" --include="*.sh" --include="*.py" --include="*.tcl" \
     --include="*.json" /home/KSW/code | sort -u
# 위 A~D에 없는 경로가 나오면 그것도 수정 대상
```

---

## ① 반드시 환경에 맞게 수정 — `run_fullflow.sh` USER CONFIG 1)·2)

### 1) 툴 + 라이선스
| 변수 | 예시 | 설명 |
|---|---|---|
| `BASE` | 프로젝트 루트 | 모든 상대경로 기준 |
| `PT` | `.../pt_shell` | PrimeTime 실행파일 |
| `HS` | `.../hspice/linux64/hspice` | HSPICE 실행파일(디렉토리 아님) |
| `PRIME_BASHRC` | `.../prime.bashrc` | 툴 셋업 |
| `LICENSE` | `26585@cscad` | **새 머신 서버로 교체** |

### 2) 설계 파일
| 변수 | 내용 |
|---|---|
| `DESIGN_TOP` | top 모듈명 |
| `VERILOG_FILE` | 게이트넷 (.v.gz) |
| `SDC_FILE` | 제약 |
| `SPEF_FILE` | 기생 (coupled RC) |
| `LIB_DB_FILE` | CCS Liberty .db |
| `CELL_SPF_FILE` | stdcell subckt SPF |
| `MODEL_CARD_FILE` | 트랜지스터 모델 (.lib) |
| `FIXED_TCL_FILE` | path 목록 tcl (회로별) |
| `CONFIG` | base-deck flow config json |

---

## ② 실험 조건

### path 선택 — 실행 인자
```bash
run_fullflow.sh "146 153 366"  "IntToFP FP_fpiu FP_FDivSqrt"  myrun
                └ path 인덱스┘   └ 라벨(생략="")┘             └run이름┘
```
- 다른 경로 = 인덱스만 교체. 라벨 생략 시 `path146`.

### 입력 slew / 출력 load — `run_fullflow.sh` USER CONFIG 3)
```bash
PATCH_MODE=true         # ★ true 로 바꿔야 반영됨 (기본 false=PT 자연전파)
INPUT_SLEW_PS=50        # 경로 시작(launch) 입력 slew [ps]
OUTPUT_LOAD_FF=10       # 경로 끝(종점) load [fF]
TARGET_VDD=0.8          # 전압
TARGET_TEMP=25          # 온도
```
- `PATCH_MODE=true`면 자동으로 `--skip-patch`가 빠지고 값 반영. (본문 39/45행 안 건드림)
- ⚠️ 경로 boundary(시작·끝)지 stage별 아님. base deck에만.

### 전압 코너 (unseen) — `run_fullflow_unseen.sh` USER CONFIG 3)
```bash
TARGET_VDD=0.7          # 목표 전압
LIB_DB_FILE=.../0p7V/...tt0p7v25c...mono.db   # 그 전압 CCS db
CONFIG=.../pt_native_spice_config_input2_0p7v.json
# 전압별 값은 스크립트 주석 표 참고 (0.7 / 0.78 / 0.625 / 0.6)
```

### unseen retarget 방식 — `run_fullflow_unseen.sh` USER CONFIG 4)
| 변수 | 값 | 방식 |
|---|---|---|
| `RETARGET_KSLEW` | `1.0` | b-1: 전압만 retarget (**권장**) |
| `RETARGET_KSLEW` | `1.258` | b-2: slew도 스케일 (과예측) |
| `SRC_RUN` | `fullflow_5paths` | retarget할 0.8V run 이름 (먼저 생성돼 있어야 함) |
| `VREF` | `0.8` | reference 전압 |

### 양쪽-코너 보간 reference — `run_fullflow_unseen.sh` USER CONFIG 7) (선택)
목표전압을 **감싸는 두 코너 run**이 있으면 stage별 cell/net/slew를 물리모델
`y = A/(V−Vth)^α` 로 보간해 "예측 PT reference"를 만든다 (목표전압 Liberty 불필요).

| 변수 | 예 | 의미 |
|---|---|---|
| `INTERP_HI_RUN` | `fullflow_5paths` | 높은쪽 코너 run 이름 (비우면 보간 스킵) |
| `INTERP_HI_VDD` | `0.8` | 그 run의 전압 |
| `INTERP_LO_RUN` | `fullflow_5paths_0p6v` | 낮은쪽 코너 run 이름 (비우면 스킵) |
| `INTERP_LO_VDD` | `0.6` | 그 run의 전압 |
| `INTERP_VTH` | `0.45` | 모델 Vth 앵커 (±0.05 → ±1~2%) |

- 검증(0.8+0.6→0.7, p146/p153): cell합 **-0.3~-0.4%**, slew합 **+0.1~+1.2%**. 선형보간은 +14% 틀림.
- 출력: `p<P>/interp_ref_p<P>.csv`(stage별 예측 pt_cell/net/slew) + `.txt`(**stage별 cell/net/slew 표** + SPICE cell 대비 d + SUM)
  + **`stage_detail_interp_p<P>.{txt,md,csv}`** — PT 컬럼을 보간 reference로 교체한 stage별 **cell/net 분리 표**(기존 stage_detail과 동일 양식, SPICE net은 재귀속값).
- **crosstalk delta에는 불필요** (b-1로 충분 — delta는 slew가 상쇄됨). base/절대 타이밍 예측용.
- 단독 실행: `python3 py/interp_pt_corner.py --hi-csv ... --lo-csv ... --target-vdd 0.7`
- **새 사이트에서 코너를 받았을 때**: ①받은 코너마다 `run_fullflow.sh`로 run 생성 →
  ②`SRC_RUN/VREF`를 그 코너로(**VREF는 0.8 고정 아님**, reference run의 실제 전압) →
  ③감싸는 2개면 `INTERP_*` 5개 지정, 1개뿐이면 비워두고 b-1만. 시나리오 상세 = `RUN_GUIDE.md` §F-1.

### 고립 셀 — `gen_isolated_cell_decks.py` 인자
| 인자 | 설명 |
|---|---|
| `--vdd` | 전압 |
| `--spf` | 셀 subckt SPF |
| 상단 `MODELCARD` 상수 | 트랜지스터 모델 (새 경로로) |

---

## ③ 고급 (보통 그대로)

### run_fullflow.sh USER CONFIG 4)
| 변수 | 기본 | 의미 |
|---|---|---|
| `TRAN_SIZE_NS` | **4.8** | arc deck .tran 종료. 3.0이면 victim 잘림 → 유지 |
| `HSPICE_TIMEOUT` | 28800 | HSPICE 타임아웃 [s] |
| `DRIVE_PATH_INPUT_PIN` | false | cell-arc 구동 시도(surrogate) — align과 양립불가라 false 유지 |

### config json (deck 생성 세부, `deck_generation`)
| key | 기본 | 의미 |
|---|---|---|
| `transient_stop_ns` | 6.0 | base deck .tran 종료 |
| `transient_step_ns` | 0.001 | .tran 스텝 |
| `initial_delay_ns` | 1.0 | 초기 지연 |

### config json (`deck_patch`) — patch 모드에서 뭘 덮어쓸지
`patch_input_slew / patch_output_load / patch_vdd / patch_temp` (기본 전부 true), `output_load_cap_name`(C_ML_OUT_LOAD).

### config json (`hspice`)
`fail_on_hspice_error`(true) / `fail_on_measure_failed`(false).

---

## 자주 바꾸는 것 TOP 5 (전부 스크립트 맨 위 USER CONFIG)
```
1. path 인덱스        실행 인자1  "146 153 ..."
2. 입력 slew/출력 load run_fullflow.sh USER CONFIG 3) PATCH_MODE=true + INPUT_SLEW_PS/OUTPUT_LOAD_FF
3. 전압 코너          run_fullflow_unseen.sh USER CONFIG 3) TARGET_VDD/LIB_DB_FILE/CONFIG
4. 툴/라이선스/경로    run_fullflow.sh USER CONFIG 1)·2)
5. unseen slew 방식   run_fullflow_unseen.sh USER CONFIG 4) RETARGET_KSLEW (1.0=b-1 권장)
```
