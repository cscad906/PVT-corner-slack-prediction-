# 전체 플로우 실행 가이드 (PT vs SPICE crosstalk)

스크립트 맨 위 **USER CONFIG 블록**만 편집하면 됨. 본문은 안 건드림.

## A. 준비 (한 번만)

1. **데이터·툴 위치 확인** (README.md의 "가져와야 할 것" — design/CCS/modelcard/SPF + pt_shell/hspice)
2. `run_fullflow.sh` 맨 위 **USER CONFIG** 에서 아래를 새 환경에 맞게:
   - `BASE / PT / HS / PRIME_BASHRC / LICENSE` (툴·라이선스)
   - `DESIGN_TOP / VERILOG_FILE / SDC_FILE / SPEF_FILE / LIB_DB_FILE / CELL_SPF_FILE / MODEL_CARD_FILE / FIXED_TCL_FILE / CONFIG` (설계 파일)

> 원래 위치(`.../pt_spice_deck`)에선 이미 채워져 있어 수정 없이 실행 가능.

---

## B. 전체 플로우 실행 — 한 줄 (0.8V)

```bash
cd /home/KSW/auto_spice_breakdown/codex/pt_spice_deck
bash code/native_flow/run_fullflow.sh \
     "146 153 366 966 2135" \
     "IntToFP FP_fpiu FP_FDivSqrt brinfos_regfile mem_issue" \
     myrun
```
- **arg1** = PT fixed-path 인덱스 (공백 구분)
- **arg2** = 라벨 (같은 순서, ASCII만; 생략하려면 `""` → `path<idx>`로 표시)
- **arg3** = run 이름 → `output/input2/myrun/`

→ path 병렬 실행, path당 ~5~9분.

---

## C. 내부 5단계 (path마다 병렬)

| 단계 | 도구 | 하는 일 |
|---|---|---|
| **S1** | `report_fixed_paths_si_on_off.tcl` | PT SI on/off + crosstalk_delta 리포트 |
| **S2** | `run_pt_native_spice_flow.py` | full-path base deck + HSPICE → cell/net base |
| **S3a** | `path_arc_quiet_compare.py prepare-stage-csv-from-report` | stage arc 목록(sl.csv) |
| **S3b** | `run_pt_aligned_path_arcs_spice_deck.tcl` | arc-align crosstalk deck 생성 |
| **S3c** | `path_arc_quiet_compare.py run-quiet-compare` | 각 arc HSPICE quiet+align → ac.csv |

이후 자동 집계: `summary_pt_spice.py` / `stage_pt_spice_compare.py` / `crosstalk_delta_compare.py`

---

## D. 출력 (`output/input2/myrun/`)

```
summary_myrun.{md,txt,csv}          path=행 요약
p<P>/stage_detail_p<P>.{md,txt,csv} stage별 절대 cell/net + d(SP-PT)
p<P>/xtalk_delta_p<P>.{md,txt,csv}  stage별 crosstalk delta (PT SIoff/on vs HSPICE quiet/align)
```
검증: base cell gap ±수%, total(vs PT SI-on) 96~103%, crosstalk repro 111~134%.

---

## E. input slew / output load 넣기 (patch 모드)

`run_fullflow.sh` 맨 위 USER CONFIG **3)** 블록만 수정:
```bash
PATCH_MODE=true         # false → true 로 (그래야 반영됨)
INPUT_SLEW_PS=50        # 경로 시작(launch) 입력 slew [ps]
OUTPUT_LOAD_FF=10       # 경로 끝(종점) load [fF]
```
→ 39행/45행 안 건드려도 됨. `PATCH_MODE=true`면 자동으로 `--skip-patch`가 빠지고 ml.csv 값이 반영.
⚠️ slew/load는 **경로 boundary**(시작·끝)지 stage별 아님. base deck에만 적용(crosstalk 무관).

---

## F. 다른 전압 (unseen corner) — 통합 스크립트

```bash
# run_fullflow_unseen.sh 맨 위 USER CONFIG 3)에서 목표 전압 3개만 교체:
#   TARGET_VDD=0.7
#   LIB_DB_FILE=.../0p7V/...tt0p7v25c...mono.db
#   CONFIG=.../pt_native_spice_config_input2_0p7v.json
#   (전압별 값은 스크립트 주석 표 참고: 0.7/0.78/0.625/0.6)
# 그리고 4) RETARGET_KSLEW: 1.0=b-1(권장) / 1.258=b-2

bash code/native_flow/run_fullflow_unseen.sh \
     "146 153 366 966 2135" "IntToFP FP_fpiu FP_FDivSqrt brinfos_regfile mem_issue" myrun_0p7v
```
- **선행**: 먼저 `run_fullflow.sh`로 0.8V arc-align deck(=`SRC_RUN`)을 생성해둬야 함 (retarget 대상).
- 유효구간: 0.7V↑ (total 96~103%). 0.6V는 near-threshold로 붕괴(82%).
- (구 `run_fullflow_0p7v/0p78v/0p625v/0p6v.sh`는 이 통합본으로 대체됨.)

**(선택) 양쪽-코너 보간 reference** — 어떤 코너가 제공될지 모를 때, 목표전압을 감싸는
두 코너 run이 있으면 USER CONFIG 7)에 지정 (예: `INTERP_HI_RUN=fullflow_5paths`,
`INTERP_LO_RUN=fullflow_5paths_0p6v`). 끝나면 `p<P>/interp_ref_p<P>.csv` (stage별
예측 PT cell/net/slew) + `stage_detail_interp_p<P>.txt` (**보간-PT vs SPICE cell/net
분리 표**, 기존 stage_detail과 동일 양식)가 생성됨 (검증: 0.8+0.6→0.7 cell합 -0.3%).
crosstalk delta는 b-1로 충분하므로 이 보간은 base/절대 타이밍 예측용.

### F-1. 새 사이트에서 코너를 받았을 때 — 수정 순서 (시나리오별)

예: 그쪽에서 **0.75V와 0.55V** Liberty를 주고, 목표(미제공)는 **0.65V**인 경우.

**① 먼저 받은 코너로 reference run 생성** (보간은 "이미 돌린 run의 CSV"를 입력으로 씀):
```bash
# run_fullflow.sh USER CONFIG에서 그 코너 db/config 지정 후, 코너마다 한 번씩
bash run_fullflow.sh "146 153 ..." "..." run_0p75v
bash run_fullflow.sh "146 153 ..." "..." run_0p55v
```

**② run_fullflow_unseen.sh USER CONFIG 수정**:
```bash
# --- 3) 목표 전압 ---
TARGET_VDD=0.65

# --- 5) retarget (crosstalk용 b-1) ---
SRC_RUN=run_0p75v      # 받은 코너 중 하나를 reference로
VREF=0.75              # ★ 0.8 고정 아님 — reference run의 "실제 전압"으로 반드시 변경

# --- 7) 보간 (base/절대 타이밍용) ---
INTERP_HI_RUN=run_0p75v    INTERP_HI_VDD=0.75
INTERP_LO_RUN=run_0p55v    INTERP_LO_VDD=0.55
INTERP_VTH=0.45            # 공정 Vth 앵커 (SAED14=0.45 유지)
```

**시나리오별 요약**:

| 받은 코너 | 수정할 것 |
|---|---|
| **1개만** (예: 0.75V) | 7)은 비워둠(`INTERP_HI_RUN=""` → 스킵). 5)의 `SRC_RUN/VREF`만 그 코너로 → b-1 retarget만 |
| **감싸는 2개** | 위처럼 7) 다섯 개 채움. crosstalk은 여전히 b-1(5번) 담당, 보간은 base 예측 추가 |
| **목표가 두 코너 밖** (외삽) | 돌긴 돌지만 경고 출력 — 정확도 보장 못 함. 가능하면 감싸는 쌍 요청 |

**주의 2가지**:
1. **`VREF`는 0.8 하드코딩이 아님** — reference deck을 만든 코너의 실제 전압. 받은 코너가
   0.8V가 아니면 반드시 같이 변경 (안 바꾸면 전압 스케일 비율 `Vnew/Vref`가 틀어짐).
2. **`INTERP_VTH`는 공정 의존** — SAED14면 0.45 유지. 다른 공정이면 그 공정의 대략적
   트랜지스터 Vth를 넣고, 검증 코너가 하나라도 있으면 ±0.05 스윕으로 캘리브레이션
   (±0.05 → 결과 ±1~2%라 민감하진 않음).

풀플로우 없이 CSV만 있으면 단독 실행도 가능:
```bash
python3 pt_spice_deck/py/interp_pt_corner.py \
  --hi-csv <0.75V run>/p146/p146_base/pt_vs_native_stage_compare.csv --hi-vdd 0.75 \
  --lo-csv <0.55V run>/p146/p146_base/pt_vs_native_stage_compare.csv --lo-vdd 0.55 \
  --target-vdd 0.65 --out-csv interp_p146.csv
```

---

## F-2. 새 사이트 검증 순서 (데이터 형식이 다를 수 있을 때)

DK-less corner 예측으로 가기 전에, 아래 순서로 단계마다 "정답 있는" 검증을 통과시킨다.

```
0.   스모크: 1-path 관통 + 단위/임계값/(V,T) 목록/lib 포맷 확인
1.   Ref corner 풀플로우 → 판정 기준표로 확인
1.5  Ref A → Ref B retarget → B의 실제 PT와 crosstalk 비교 (b-1 검증)
2.   Ref A + Ref C → B 보간 → B의 실제 PT와 base 비교 + Vth 캘리브레이션
3.   DK-less corner: crosstalk=b-1, base=보간, 오차는 2단계 실측치로 보고
```

### 0. 스모크 테스트 — 상관관계 보기 전에 "돌긴 하나"부터
(입력 데이터 9종의 형식 표 + 암묵 가정 A~D + 사전 질문 리스트 = **§F-3** 참고)
- **path 1개**로 deck 생성→HSPICE→파싱 관통 확인 (batch 전에).
- Liberty가 `.lib`로만 오면 **lc_shell로 `.db` 변환** 필요 (PT는 .db).
- fixed_paths tcl은 **회로별** — 새 회로면 재생성 (§H, `get_timing_paths` worst-slack 대체 가능).
- **단위 확인**: lib cap 단위 pf vs ff **1000× 함정** (실제로 당함). time 단위도.
- **Liberty 측정 임계값 확인**: 이 플로우는 slew 20-80% / delay 50% 전제. 새 lib이
  다른 임계값(30-70% 등)이면 `.measure`와 안 맞아 1단계가 가짜로 틀어짐 —
  `slew_lower/upper_threshold`, `slew_derate_from_library`부터 볼 것.
- **코너 (V,T) 목록 확인**: 이 방법론은 전부 **V-only·25°C 검증**. 코너 쌍이 같은 T면
  그대로 적용, T가 다르면 검증 범위 밖 (b-1도 보간 모델도 T를 안 다룸).

### 1. Ref corner 풀플로우 — 판정 기준표
"일치"의 기대값은 100%가 아니다. 이 기준 없이 보면 정상을 비정상으로 오판한다:

| 지표 | 정상 범위 | 벗어나면 의심할 것 |
|---|---|---|
| base cell gap | ±수% | 임계값/단위/모델카드 불일치 |
| quiet ≈ SI-off | **±3%** | **surrogate/측정오류 (최우선 디버그 신호)** |
| total vs PT SI-on | 96~103% | — |
| crosstalk repro | **111~134%가 정상** (worst-align 상한이라 100% 초과가 맞음) | 100% 미만이면 정렬/tran창 의심 |

- `TRAN_SIZE_NS=4.8`이 새 회로/전압에서 충분한지 확인 (slew 길어지면 measure 잘림 —
  `.mt0` failed 개수 체크).
- 고립 셀 플로우(§G)는 SAED14 종속 — 새 라이브러리면 스킵.

### 1.5 b-1 retarget 검증 — 2단계(보간)와 별개로 반드시
2단계는 **base** 검증이고 **crosstalk은 b-1 retarget** 담당이라 따로 검증해야 한다:
- Ref A에서 만든 arc-align deck을 **B로 retarget → B의 실제 PT crosstalk과 비교**
  (둘 다 Liberty 있으니 정답 존재).
- 기대값: 전압점프 작으면 ~100%, 0.1V 점프에 total 96~103%.
- 이걸 건너뛰면 3단계에서 crosstalk이 틀렸을 때 원인(retarget vs 보간) 분리 불가.

### 2. 보간 검증 + Vth 캘리브레이션
- Ref A + Ref C → 가운데 B 보간 → B의 실제 PT와 cell/net/slew 합 비교 (기대: cell ~0.5%).
- **`INTERP_VTH`를 새 공정 Vth로 캘리브레이션**: B가 정답이 있으니 ±0.05 스윕해서
  cell합 오차 최소점을 찾고 그 값을 3단계에 사용 (0.45는 SAED14 값).
- 코너 3개 이상이면 **leave-one-out 전부** — 이때 측정한 오차가 3단계 예측의 **error bar**.

### 3. DK-less corner 실전
- crosstalk = b-1 retarget / base·slew = 보간 reference (`INTERP_*` 지정, §F-1).
- 목표가 ref 쌍 **바깥이면 외삽** — 도구가 경고 출력, 정확도 미검증. 감싸는 쌍 요청 권장.
- 목표가 그 공정 **near-threshold 근처면 base는 붕괴 구간**일 수 있음 (우리 기준 0.6V:
  crosstalk은 유효했지만 절대 타이밍 -25%) — 보수적으로 보고.
- 정답이 없으므로 결과에 **2단계 실측 오차를 반드시 병기** (예: "±0.5%, bracketing 검증 기준").

---

## F-3. 입력 데이터 형식 + 암묵 가정 (새 사이트 사전 점검)

### 데이터 받기 전 한 줄 질문 리스트 (제일 싼 방법)
> ① SPEF **coupled** 추출본인가요? ② 설계가 **단일 전원 도메인**인가요?
> ③ Liberty는 **.db**인가요 .lib인가요? ④ HSPICE **라이선스 토큰** 몇 개까지 쓸 수 있나요?

### 입력 데이터 9종과 형식
| # | 파일 | 형식 | 체크포인트 |
|---|---|---|---|
| 1 | VERILOG_FILE | 게이트레벨 Verilog (.v/.v.gz, post-route) | 인스턴스명이 SPEF/SDC와 같은 P&R 세트 |
| 2 | SDC_FILE | 표준 SDC | 코너 맞는 것 |
| 3 | SPEF_FILE | **coupled SPEF** | ★cc cap 보존본 필수 (`read_parasitics -keep_capacitive_coupling`). decoupled(lumped-to-GND)면 **실험 자체 불가** — cap 줄에 net이 2개 나오는지 grep으로 확인 |
| 4 | LIB_DB_FILE | Liberty **.db** (우리는 CCS) | .lib만 오면 lc_shell 변환. 임계값 slew 20-80/delay 50 확인 |
| 5 | CELL_SPF_FILE | 스탠다드셀 `.SUBCKT` 모음 (DSPF/CDL) | 셀명·핀명·핀순서가 Liberty와 일치 |
| 6 | MODEL_CARD_FILE | HSPICE 모델 (`.lib TT` 섹션 + `.param VDD`) | 코너 섹션명 TT 아니면 deck 헤더 수정; VDD가 param이어야 retarget 가능 |
| 7 | FIXED_TCL_FILE | path 목록 tcl (회로별) | 새 회로면 재생성 (§H) |
| 8 | ml.csv | `path_id,input_slew_ps,output_load_ff,target_vdd,target_temp` | 스크립트가 자동 생성 |
| 9 | config json | 경로 12키 + deck 파라미터 | CONFIG_KNOBS ⓪-B |

중간 산출물(sl.csv/manifest/mt0/ac.csv/pt_vs_native_stage_compare.csv)은 자동 생성 — 신경 불필요.

### 암묵 가정 — 새 데이터가 이걸 깨면 형식이 맞아도 어긋남

**A. 설계 구조**
1. **단일 전원 도메인**: patch·retarget이 `.param VDD` 하나만 바꿈. multi-voltage/level-shifter 경유 path는 제외.
2. **flop-발 path**: base deck은 launch flop CK만 구동. input-port 시작 path는 빼는 게 안전. latch/multi-clock 미검증.
3. **인스턴스 이름 규칙**: 파서가 `U123/X` 패턴 의존. escaped name(`\a/b[8]`) 많으면 정규식 깨질 수 있음(스모크에서 드러남). HSPICE measure 이름 길이 제한으로 긴 이름 잘림→mt0 충돌 가능.

**B. 라이브러리 구조**
4. **`.SUBCKT` 핀 순서**: 고립 플로우는 `VDD VSS X <입력들>` 가정 — well 핀(VNW/VPW) 있는 5~6핀 라이브러리면 고립 플로우 파싱 어긋남 (메인 플로우는 무관).
5. **cell SPF ↔ modelcard 모델명 연결**: SPF의 트랜지스터 모델 참조명(`.lib ... T_nfet` 식)이 modelcard 섹션명과 일치해야 HSPICE가 돎.

**C. 실행 환경**
6. **HSPICE 라이선스 토큰 수**: path 병렬×stage deck으로 동시 수십 개 실행 — 토큰 적으면 병렬도(path 수) 낮출 것. (`-mt`는 별도 라이선스 — 우리 사이트선 막혔음.)
7. **PT 버전**: `write_spice_deck -align_aggressors` 동작·aggressor emit 시각이 버전 의존일 수 있음(검증=W-2024.09-SP3). 1단계 판정표의 quiet≈SI-off ±3%가 안전망.

**D. 당해본 함정**
8. **디스크**: deck/tr0가 path당 수 GB (tr0는 자동 삭제되나 여유 필요).
9. **`cp -i` alias**: 덮어쓰기가 조용히 스킵돼 옛 결과가 새 결과처럼 보임 — 수동 복사는 `\cp -f`.

스모크(§F-2 0단계)에서 자동으로 걸러지는 것: A-3, B-4, B-5. **미리 물어봐야 하는 것: 위 질문 리스트 4개.**

---

## G. 고립 셀 플로우 (선택 — PT slew를 SPICE에 주입해 순수 모델차 확인)

```bash
python3 code/native_flow/gen_isolated_cell_decks.py \
  --stage-csv output/input2/myrun/p146/p146_base/pt_vs_native_stage_compare.csv \
  --anno input2/pt_result/BoomCore_input2_Cnom25_fixed_annotated.txt \
  --outdir output/input2/iso_p146 --vdd 0.8 --spf <cells.spf>
# → stg_*.sp HSPICE batch 실행 →
python3 code/native_flow/gen_isolated_report.py \
  --isodir output/input2/iso_p146 \
  --fullpath output/input2/myrun/p146/p146_base/pt_vs_native_stage_compare.csv \
  --name p146 --vdd 0.8
```

---

## H. path 인덱스 고르는 법

- FIXED_TCL(`..._fixed_paths_3000.tcl`)의 3000개 path 중 인덱스.
- crosstalk 큰 path: annotated 리포트 net-delay 프록시 → PT SI off/on 실측 확인.
- 새 회로면: 그 회로의 fixed-path tcl 생성 또는 `get_timing_paths`(worst slack)로 대체.

---

## 한 장 요약
```
run_fullflow.sh 맨 위 USER CONFIG 편집  (경로/전압/PATCH_MODE)
  └ bash run_fullflow.sh "paths" "labels" runname
     ├ S1 PT SI on/off
     ├ S2 base deck + HSPICE
     ├ S3 arc-align + HSPICE
     └ 집계: summary / stage_detail / xtalk_delta
  → output/input2/<runname>/

전압 스윕:  run_fullflow_unseen.sh 맨 위 TARGET_VDD/LIB_DB/CONFIG 교체
slew/load:  run_fullflow.sh 맨 위 PATCH_MODE=true + INPUT_SLEW_PS/OUTPUT_LOAD_FF
```
