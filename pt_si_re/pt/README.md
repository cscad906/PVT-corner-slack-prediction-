# Restore session 기반 PrimeTime scaling 운영 가이드

이 문서는 처음 코드를 전달받은 담당자가 PrimeTime restore session에서 native
library scaling을 실행하고, 동일한 fixed path의 ground truth와 비교하는 절차를
설명합니다. `pt/`에서 scaling에 사용하는 파일은 `run_scaling_after_restore.tcl`
하나입니다.

## 1. 전달할 파일과 담당자 준비물

전달할 파일은 다음과 같습니다.

| 파일 | 용도 | 실행 환경 |
|---|---|---|
| `pt/run_scaling_after_restore.tcl` | restore session에서 PT scaling 및 fixed-path 측정 | `pt_shell` |
| `fixed_paths.tcl` | 모든 비교에 공통으로 사용할 경로 목록 | `pt_shell` |
| `analysis/compare_scaling_mae.py` | scaling과 ground truth의 path별 오차 및 MAE 계산 | Linux shell |
| `analysis/plot_ground_truth_slack.py` | ground-truth slack 통계 및 분포 생성 | Linux shell |

담당자는 다음 환경을 준비해야 합니다.

1. 설계, SDC, parasitic, 필요한 PVT library가 복원되는 PrimeTime session
2. 실제 target corner를 사용하는 ground-truth session 또는 scenario
3. 동일한 netlist에서 `1_union.py`로 만든 `fixed_paths.tcl`
4. Python 3.6 이상

`run_scaling_after_restore.tcl`은 DB, netlist, SDC, SPEF를 새로 읽지 않습니다.
전부 restore session에 들어 있어야 합니다. target library가 메모리에 로드되어
있는 것은 괜찮지만 scaling group에서는 제외되어야 합니다.

## 2. 권장 작업 폴더

아래는 예시입니다. 회사 경로에 맞게 바꿉니다.

```text
/company/work/pt_scaling_eval/
├── config/
│   └── run_scaling_after_restore.tcl
├── input/
│   └── fixed_paths.tcl
├── ground_truth/
│   └── SSPG_0p57V_25C_RCMAX_setup/
├── scaling_output/
└── analysis_output/
```

Git 저장소의 Tcl을 작업 폴더로 복사합니다. 업데이트를 받으면 다시 복사하여
이전 복사본과 섞이지 않게 합니다.

```bash
mkdir -p /company/work/pt_scaling_eval/{config,input,ground_truth,scaling_output,analysis_output}
cp /path/to/repository/pt/run_scaling_after_restore.tcl \
   /company/work/pt_scaling_eval/config/
cp /path/to/generated/fixed_paths.tcl \
   /company/work/pt_scaling_eval/input/fixed_paths.tcl
```

재현성을 위해 실행한 버전도 기록합니다.

```bash
cd /path/to/repository
git rev-parse HEAD
```

## 3. 내삽 조건

`-axis`에 따라 필요한 Liberty grid가 다릅니다.

| 값 | 필요한 scaling 입력 |
|---|---|
| `V` | target과 같은 process/temperature에서 target보다 낮고 높은 voltage DB |
| `T` | target과 같은 process/voltage에서 target보다 낮고 높은 temperature DB |
| `VT` | target을 둘러싸는 두 voltage × 두 temperature의 네 DB |

target이 입력 grid 바깥이면 외삽이므로 중단합니다. BEOL은 scaling하지 않습니다.
restore session에서 현재 활성화된 target temperature/BEOL parasitic을 그대로
사용합니다. voltage가 달라도 같은 temperature와 BEOL의 parasitic을 사용합니다.

외삽 차단은 PrimeTime V-2023.12-SP4의 command reference와 실행 결과로 확인한
조건입니다. 이 버전의 `define_scaling_lib_group` 도움말은 scaling group 범위
밖의 operating condition을 사용할 수 없다고 설명합니다. 0.60/0.65 V library
group에 0.55 V를 설정한 검사에서도 PrimeTime이 `SLG-320`과 `DEL-012`를 내고
scaling 적용을 취소했습니다. 다른 PrimeTime major version을 사용할 때는 해당
버전의 `man SLG-320`과 `man define_scaling_lib_group`을 다시 확인합니다.

현재 운영 모드는 fixed path에 포함된 cell만 scaling합니다. `1_union.py`가
`FIXED_PATHS`에 저장한 launch/capture pin과 전체 data-pin chain으로 cell 집합을
복원하고, 그 cell들이 사용하는 library family만 scaling group에 포함합니다.
fixed path 밖의 cell과 SI aggressor는 restore 상태를 유지합니다.

고정된 한 점만 있는 SRAM, macro, IO library set은 scaling group에 넣지 않고
restore session에 연결된 DB를 그대로 사용합니다. 해당 block을 통과하는 path는
부분적으로만 scaling될 수 있으므로 결과 해석 시 구분해야 합니다.

library 이름에 주 전압과 보조 rail 전압이 함께 들어간 multi-rail library는
`report_lib` Operating Conditions의 주 전압만 scaling 축으로 인식합니다. 이름의
다른 rail 전압은 family 구분값으로 유지하므로, 보조 전압이 다른 library를 같은
scaling group에 섞지 않습니다.

네 power rail의 역할은 `auto_scaling::run` 옵션에 명시합니다. 레벨시프터 입력 전 rail과
memory rail은 fixed, 나머지 두 rail은 scaling 대상으로 둡니다. 스크립트는
fixed-path cell의 `type=primary_power` PG pin과 실제 `supply_connection`을 확인한 뒤,
scaling rail에 연결된 PG pin만 `set_voltage -cell ... -pg_pin_name ...`으로 변경합니다.
따라서 같은 rail에 연결된 fixed path 밖의 cell이나 fixed rail 전체에는 전압을
적용하지 않습니다. temperature도 이 cell 집합에만 적용합니다.

## 4. 실행 옵션

`run_scaling_after_restore.tcl` 맨 위 `USER SETTINGS`에는 설계마다 고정되는 네
supply net 이름과 진행 출력 간격만 한 번 입력합니다. `source`는 명령만 로드하며
design이나 timing 상태를 바꾸지 않습니다. 실험마다 달라지는 target, fixed path,
결과 폴더는 이후 `auto_scaling::run` 명령의 옵션으로 전달합니다.

```tcl
variable FIXED_POWER_NET_BEFORE_LS "실제_고정_rail_이름"
variable SCALING_POWER_NET_1       "실제_scaling_rail_1"
variable SCALING_POWER_NET_2       "실제_scaling_rail_2"
variable FIXED_MEMORY_POWER_NET    "실제_memory_rail_이름"
variable PROGRESS_INTERVAL_MINUTES 10
```

`PROGRESS_INTERVAL_MINUTES`는 긴 작업 중 현재 단계, 해당 단계 경과 시간과 전체
경과 시간을 몇 분마다 터미널에 출력할지만 정합니다. scaling 계산과 결과에는
영향을 주지 않습니다.

```tcl
auto_scaling::run \
  -target-process SSPG \
  -target-voltage 0.57 \
  -target-temperature 25 \
  -target-beol rcmax \
  -axis V \
  -analysis setup \
  -fixed-path /company/work/pt_scaling_eval/input/fixed_paths.tcl \
  -result-folder /company/work/pt_scaling_eval/scaling_output
```

각 옵션의 의미는 다음과 같습니다.

| 옵션 | 입력 방법 |
|---|---|
| `-target-process` | `report_lib`의 Operating Conditions에 표시되는 실제 process 이름 |
| `-target-voltage` | 목표 voltage, V 단위 |
| `-target-temperature` | 목표 온도, 섭씨. 영하 25도는 `-25` |
| `-target-beol` | `rcmax`, `rcmin`, `cmax` 또는 회사 고유 `CORNER_NAME` |
| `-axis` | `V`, `T`, `VT` 중 하나. 생략 시 `V` |
| `-analysis` | setup은 `setup`, hold는 `hold`. 생략 시 `setup` |
| `-fixed-path` | 공통 `fixed_paths.tcl`의 절대경로 |
| `-result-folder` | 결과를 저장할 새 폴더의 절대경로 |

setup용 `fixed_paths.tcl`은 내부 `DTYPE`이 `max`, hold용은 `min`이어야 합니다.
스크립트가 `-analysis`와 다르면 실행을 중단합니다. 전체 형식은 source 후 다음
명령으로 확인합니다.

```tcl
auto_scaling::run -help
```

## 5. restore session 확인

`pt_shell`을 열고 session을 복원합니다.

```tcl
restore_session /company/session/path
```

다음 명령으로 현재 상태를 확인합니다.

```tcl
puts "DESIGN=[get_object_name [current_design]]"
puts "BEOL=[get_attribute [current_design] parasitics_corner_name]"
puts "PARASITIC_TEMP=[get_attribute [current_design] parasitics_operating_temperature]"
puts "PARASITIC_TECH=[get_attribute [current_design] parasitics_tech_file]"
puts "LIBRARIES=[get_object_name [get_libs *]]"
puts "SUPPLY_NETS=[get_object_name [get_supply_nets -quiet -hierarchy *]]"
report_units
report_lib_groups -scaling -show {voltage temperature process}
```

확인 기준은 다음과 같습니다.

- `BEOL`이 `-target-beol`과 같아야 합니다. `RC_MAX_model`처럼 이름에 `rcmax`가
  들어가면 `-target-beol rcmax`로 인식합니다.
- `PARASITIC_TEMP`가 `-target-temperature`와 정확히 같아야 합니다.
- voltage 내삽에 필요한 양쪽 voltage DB가 `LIBRARIES`에 있어야 합니다.
- 모든 library가 메모리에 로드된 것은 정상입니다.
- 기존 scaling group에 target voltage/temperature가 들어 있으면 leave-one-out이
  아니므로 스크립트가 중단합니다. 가능하면 scaling group이 없는 fresh restore
  session을 사용합니다.

고유 BEOL 이름이 `rcmax`, `rcmin`, `cmax`를 포함하지 않으면 Tcl의
`-target-beol`에 실제 이름을 그대로 적습니다. 비교할 때는 대소문자와 `-`, `_`
같은 구분 문자를 제거하지만 그 밖의 이름은 정확히 같아야 합니다.

## 6. PT scaling 실행

복원한 `pt_shell`에서 Tcl을 source한 뒤 외부 명령으로 실행 옵션을 전달합니다.

```tcl
source /company/work/pt_scaling_eval/config/run_scaling_after_restore.tcl

auto_scaling::run \
  -target-process SSPG \
  -target-voltage 0.57 \
  -target-temperature 25 \
  -target-beol rcmax \
  -axis V \
  -analysis setup \
  -fixed-path /company/work/pt_scaling_eval/input/fixed_paths.tcl \
  -result-folder /company/work/pt_scaling_eval/scaling_output
```

`source` 직후에는 `AUTO SCALING LOADED`만 출력되고 분석은 시작되지 않습니다.
`auto_scaling::run`을 실행해야 library 선택과 timing 변경이 시작됩니다.

스크립트가 자동으로 다음 작업을 수행합니다.

1. restore된 library의 process/voltage/temperature 조사
2. fixed path cell이 실제 사용하는 library set만 선택
3. target library를 제외한 내삽 입력 선택
4. 현재 parasitic의 BEOL과 온도 확인
5. scaling library group 구성 또는 기존 group 검증
6. fixed path cell의 primary PG pin과 네 supply 역할 검증
7. scaling rail에 연결된 fixed-path cell/PG pin에만 target voltage와 temperature 적용 후 incremental `update_timing`
8. 동일한 fixed path만 최종 report로 측정
9. `report_delay_calculation`에서 scaling library 사용 증거 확인

실행 직후부터 각 단계의 시작과 완료 시간이 다음처럼 표시됩니다. 작업이 한
단계에서 오래 걸리면 별도 감시 프로세스가 기본 10분 간격으로 현재 단계,
그 단계의 경과 시간, 전체 경과 시간과 PrimeTime 프로세스 상태를 출력합니다.
이 감시는 `update_timing`이 Tcl 명령 처리를 막고 있는 동안에도 동작합니다.

```text
RUN START: PT_PID=12345 | progress_interval=10 min
PHASE START: UPDATE_TIMING_SI_POCV       | section=0.0 min | total=4.21 min
PROGRESS: phase=UPDATE_TIMING_SI_POCV | section=10 min | total=14 min | running=yes | PT_PID=12345 | state=R | cpu=98.7%
PROGRESS: phase=UPDATE_TIMING_SI_POCV | section=20 min | total=24 min | running=yes | PT_PID=12345 | state=R | cpu=98.9%
PHASE DONE : UPDATE_TIMING_SI_POCV       | section=23.81 min | total=28.02 min
FIXED PATH PROGRESS: 100/3000 | section=1.35 min | total=29.37 min
RUN END: status=SUCCESS | phase=VERIFY_SCALING_RESULT | section=0.01 min | total=71.42 min
```

`state=R`은 실행 중, `state=S`는 PrimeTime 프로세스가 잠시 대기 중임을 뜻합니다.
프로세스가 살아 있으면 `running=yes`가 나오며, 오류로 끝나면 마지막 줄의
`status=FAILED`와 중단된 `phase`를 확인할 수 있습니다. fixed path report는
첫 path, 100개마다, 마지막 path에서 처리 개수와 해당 단계 시간을 출력합니다.

구간 이름은 다음 순서입니다.

1. `VERIFY_PARASITICS`: restore된 BEOL과 parasitic 온도 검사
2. `PLAN_DESIGN_LIBRARIES`: instantiated library 분류와 내삽 입력 선택
3. `PREPARE_SCALING_GROUPS`: scaling group 생성 또는 기존 group 검증
4. `CLASSIFY_FIXED_PATH_POWER`: fixed-path cell과 설정한 supply 역할 검증
5. `APPLY_TARGET_VOLTAGE_TEMP`: 목표 voltage/temperature 적용
6. `UPDATE_TIMING_SI_POCV`: SI/POCV를 포함한 timing 갱신
7. `GENERATE_TIMING_REPORT`: fixed path별 timing report 생성
8. `VERIFY_SCALING_RESULT`: scaling library 적용 증거 검사

일반적으로 전체 시간의 대부분은 `UPDATE_TIMING_SI_POCV`와 fixed path 수에
비례하는 `GENERATE_TIMING_REPORT`에서 사용됩니다. 정확한 시간은 설계 크기,
SI aggressor 수, POCV 설정, RC fallback warning 수와 서버 부하에 따라 달라집니다.

restore session에 기존 scaling group이 있으면 모든 fixed-path scalable family의
계획된 입력 DB가 그 group들에 실제 포함됐는지도 검사합니다. 일부 family만 있는
group이면 `Existing scaling groups do not cover...` 오류로 중단합니다.

rail 분류 로그는 다음 형태입니다.

```text
FIXED-PATH VOLTAGE GROUP: pg_pin=VDD cells=... rails=<scaling rail 이름>
FIXED-PATH CELL SCOPE: all=... scalable_library=... target_voltage=... static_library=...
FIXED POWER NETS (unchanged): <고정 rail> <memory rail>
SCALING POWER NETS (fixed-path cell override only): <scaling rail 1> <scaling rail 2>
APPLY CELL-LEVEL VOLTAGE: target=... pg_pin=VDD cells=... rails=...
```

`SCALING COVERAGE`는 내삽 가능한 family와 한 점뿐인 static family 개수를,
`FIXED-PATH CELL SCOPE`는 path 전체 cell, scaling library 소속, 실제 target
voltage를 받는 cell과 static library cell 개수를 보여줍니다. fixed-path scalable
cell의 primary rail이 네 설정 중 어디에도 없으면 임의 처리하지 않고 중단합니다.

정상 실행의 마지막 부분은 다음 형태입니다.

```text
FIXED PATHS RESULT: requested=294 measured=290 missing=4
DONE: restore-session scaling report = <결과 파일>
VERIFY: scaling library evidence = <결과 파일>.dcalc
RUN 완료: 복원 세션 기반 scaling과 fixed-path report 생성이 끝났습니다.
```

스크립트는 기존 결과를 덮어쓰지 않습니다. `Output already exists`가 나오면
이전 결과를 보존하고 `-result-folder`에 새 폴더를 지정합니다.

## 7. scaling 결과 파일

예를 들어 설정이 `SSPG/0.57 V/25 C/rcmax/V/setup`이면 파일 이름은 다음
형태입니다.

```text
restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt
```

같은 이름 뒤에 다음 파일이 생성됩니다.

| 파일 | 확인 내용 |
|---|---|
| `.rpt` | fixed path별 PT scaling timing report와 slack |
| `.rpt.missing` | 찾지 못했거나 timing이 완성되지 않은 fixed path |
| `.rpt.selection.tcl` | 선택된 library family와 scaling 입력 기록 |
| `.rpt.libgroups.before` | 실행 전 scaling group |
| `.rpt.libgroups` | 실행에 사용한 scaling group |
| `.rpt.dcalc` | 실제 cell arc에서 scaling library가 사용된 증거 |

다음 문자열이 `.dcalc`에 있어야 합니다.

```bash
grep -n "Scaling libraries used" /company/work/pt_scaling_eval/scaling_output/*.dcalc
```

문자열이 없거나 `SLG-320`, `DEL-012`가 있으면 결과를 사용하지 않습니다.
Tcl도 `.dcalc`에서 이 두 오류 또는 외삽 취소 문구를 발견하면 완료 처리하지 않고
중단합니다. PrimeTime은 외삽 실패 뒤에도 `Scaling libraries used` 목록을 표시할
수 있으므로, 목록 존재 여부만으로 성공을 판단하면 안 됩니다.

```bash
grep -nE "SLG-320|DEL-012|Error:|Fatal:" \
    /company/work/pt_scaling_eval/scaling_output/*
```

## 8. ground truth 생성

scaling을 수행한 PT process를 이어서 사용하지 말고 별도 `pt_shell`에서 실제
target corner session을 새로 restore합니다. target Liberty와 target
temperature/BEOL parasitic이 실제로 활성화되어 있어야 하며 native scaling
group은 사용하지 않습니다.

동일한 `fixed_paths.tcl`을 수정하지 않고 source해야 합니다. 이 파일은 현재
작업 폴더 이름을 output report 이름으로 사용하고 기존 동일 이름 report를
삭제하므로, 비어 있는 전용 폴더에서 실행합니다.

```tcl
restore_session /company/ground_truth/session/path
file mkdir /company/work/pt_scaling_eval/ground_truth/SSPG_0p57V_25C_RCMAX_setup
cd /company/work/pt_scaling_eval/ground_truth/SSPG_0p57V_25C_RCMAX_setup
source /company/work/pt_scaling_eval/input/fixed_paths.tcl
```

결과는 다음 위치에 생성됩니다.

```text
/company/work/pt_scaling_eval/ground_truth/SSPG_0p57V_25C_RCMAX_setup/
    SSPG_0p57V_25C_RCMAX_setup.rpt
```

scaling report와 ground truth report에서 block 수를 확인합니다.

```bash
grep -c '^### FIXED_PATH idx=' /path/to/scaling.rpt
grep -c '^### FIXED_PATH idx=' /path/to/ground_truth.rpt
grep -c 'Startpoint:' /path/to/scaling.rpt
grep -c 'Startpoint:' /path/to/ground_truth.rpt
```

두 report의 `### FIXED_PATH` block 수는 같아야 합니다. 기존부터 잘못된 path가
있으면 `Startpoint:` 수는 더 적을 수 있으며, scaling의 `.missing`과 대조합니다.

## 9. MAE 계산

### 원본 fixed_paths.tcl을 잃어버린 경우

ground-truth fixed-path report가 남아 있으면 Linux shell에서 다음을 실행합니다.

```bash
python3 /path/to/repository/analysis/recover_fixed_paths_from_ground_truth.py \
    /path/to/SSPG_0p57V_25C_RCMAX_setup.rpt
```

스크립트가 report의 기존 path key, 전체 data-pin chain과 rise/fall 방향을 읽어
`fixed_paths_SSPG_0p57V_25C_RCMAX_setup.tcl`을 만듭니다. 기존 출력은 덮어쓰지
않으며 반복 실행하면 `_run2`, `_run3`가 붙습니다. 출력 마지막에 표시되는
절대경로를 `auto_scaling::run`의 `-fixed-path` 옵션에 넣습니다.

복원 결과가 `DTYPE=max`이면 `-analysis setup`, `DTYPE=min`이면
`-analysis hold`로 설정한 뒤 restore session에서 실행합니다.
timing table이 없던 ground-truth block은 핀 경로를 복원할 수 없으므로 제외되며,
복원 스크립트가 그 개수와 이유를 출력합니다.

Linux shell에서 Python 버전을 확인합니다.

```bash
python3 --version
```

Python 3.6 이상이면 다음처럼 실행합니다. 입력 report의 slack은 항상 ns로
읽으며 결과는 ps로 저장됩니다.

```bash
python3 /path/to/repository/analysis/compare_scaling_mae.py \
    /path/to/restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt \
    /path/to/SSPG_0p57V_25C_RCMAX_setup.rpt \
    --output-dir /company/work/pt_scaling_eval/analysis_output/SSPG_0p57_rcmax
```

생성 파일은 다음과 같습니다.

- `path_errors.txt`: path별 ground truth, scaling slack, signed error, absolute error와 상태. absolute error 내림차순
- `summary.txt`: 터미널에서 바로 확인하는 compared/excluded 수, MAE, RMSE, bias, worst error
- `summary.json`: 후처리 프로그램용 전체 요약

기업 Linux 환경에서는 별도 프로그램 없이 다음처럼 확인합니다. 터미널에는
absolute error가 큰 상위 10개 path만 출력하고, 전체 path는 텍스트 파일에만
저장하므로 출력이 과도하게 길어지지 않습니다.

```bash
cat /company/work/pt_scaling_eval/analysis_output/SSPG_0p57_rcmax/<코너이름>/summary.txt
less -S /company/work/pt_scaling_eval/analysis_output/SSPG_0p57_rcmax/<코너이름>/path_errors.txt
```

`--output-dir`은 코너별 결과 폴더가 들어갈 상위 폴더입니다. 생략하면 실행
위치의 `pt_scaling_comparison/<ground-truth-report-name>/`에 두 파일이
생성됩니다. 같은 코너를 다시 실행하면 기존 파일을 덮어쓰지 않고 폴더 이름에
`_run2`, `_run3`가 자동으로 붙습니다.

`scaled_blocks`, `ground_truth_blocks`, `compared_paths`, `excluded_paths`를 반드시
확인합니다. known-invalid path 외에 새로 제외된 path가 있으면 MAE를 승인하지
않습니다.

터미널의 `status counts`와 `summary.txt`는 제외 원인을 보여줍니다.
`missing_*_block`이 많으면 서로 다른 `fixed_paths.tcl` 또는 잘못 선택한 report를
의심하고, `unresolved_*_path`가 많으면 해당 report에서 실제 timing path가
생성되지 않은 것이므로 scaling의 `.missing`과 PrimeTime 로그를 확인합니다.

## 10. ground-truth slack 분포 확인

여러 target-corner ground truth report를 한꺼번에 입력할 수 있습니다.

```bash
python3 /path/to/repository/analysis/plot_ground_truth_slack.py \
    /company/work/pt_scaling_eval/ground_truth/*/*.rpt \
    --bins 20 \
    --output-dir /company/work/pt_scaling_eval/analysis_output/slack_distribution
```

GUI가 없는 서버에서는 다음 파일을 봅니다.

```bash
less -S /company/work/pt_scaling_eval/analysis_output/slack_distribution/ground_truth_slack_terminal.txt
```

`q`를 누르면 `less`를 종료합니다. CSV도 터미널에서 볼 수 있습니다.

```bash
column -s, -t \
    /company/work/pt_scaling_eval/analysis_output/slack_distribution/ground_truth_slack_summary.csv \
    | less -S
```

평균과 분포에는 resolved path만 들어가며 negative slack은 포함합니다.
`unresolved_paths`가 예상 개수인지 확인합니다.

## 11. 자주 발생하는 오류

| 메시지 또는 증상 | 원인 | 조치 |
|---|---|---|
| `missing close-brace` | Tcl이 일부만 복사됐거나 구버전 사용 | Git의 최신 파일을 다시 복사하고 전체 파일을 source |
| P/V/T library를 찾지 못함 | `-target-process`가 `report_lib`의 실제 이름과 다르거나 bracket DB 없음 | Operating Conditions와 loaded library 확인 |
| library selection ambiguous | 같은 PVT의 revision/중복 library가 여러 개 | 담당자가 사용할 PDK revision 하나를 정해 session 정리 |
| `needs exactly one library ... found N` | 같은 family/PVT로 분류된 DB가 없거나 여러 개 | 오류 아래 `MATCH: LIB=... DB=...` 목록 확인. 서로 다른 LIB면 family 분류를 수정하고, 같은 LIB의 여러 DB면 사용할 revision 하나를 결정 |
| target corner가 기존 scaling group에 포함 | leave-one-out 조건 위반 | target이 들어 있지 않은 fresh restore session 사용 |
| BEOL 또는 parasitic temperature 불일치 | 다른 scenario/session의 parasitic 활성 | 정확한 target BEOL/temperature session을 restore |
| `incomplete fixed path` 또는 missing path | 원래 invalid path이거나 netlist revision 불일치 | `.missing`에서 기존 invalid 목록과 비교 |
| power/supply net 오류 | UPF 연결 또는 multi-voltage domain이 예상과 다름 | `get_supply_nets` 확인 후 담당 STA 방법론에 맞는 domain 결정 |
| 설정한 fixed/scaling power net을 찾지 못함 | 실행 옵션의 이름과 restore session의 `full_name`이 다름 | `get_object_name [get_supply_nets -hierarchy *]` 결과의 정확한 이름 입력 |
| fixed-path primary rail이 네 설정에 없음 | path cell이 다섯 번째 rail을 사용하거나 hierarchical 이름이 다름 | 오류에 나온 rail을 확인하고 네 역할 정의가 실제 설계와 맞는지 검토 |
| scaling evidence 없음 | 실제 scaling이 cell arc에 적용되지 않음 | 결과 폐기 후 `.dcalc`, `.libgroups` 검사 |
| `SLG-320` 또는 `DEL-012` | 외삽 또는 scaling 적용 실패 | target을 둘러싸는 interpolation DB 준비 |

multi-voltage/UPF 설계에서 어떤 supply domain에 target voltage를 적용할지는
설계 방법론 결정입니다. 단일 `VDD/VSS`로 가정하지 말고 담당 STA 엔지니어가
domain을 확정한 뒤 실행해야 합니다.

## 12. 결과 인계 체크리스트

- [ ] 실행 Git commit hash를 기록했다.
- [ ] 실행한 `auto_scaling::run` 명령의 target process/voltage/temperature/BEOL/axis/analysis를 기록했다.
- [ ] `-fixed-path`와 `-result-folder`를 절대경로로 지정했다.
- [ ] 레벨시프터 전단/scaling 2개/memory rail의 정확한 supply 이름을 설정했다.
- [ ] 로그의 `FIXED-PATH CELL SCOPE`에서 target-voltage cell 수를 확인했다.
- [ ] `APPLY CELL-LEVEL VOLTAGE`가 설정한 scaling rail만 표시한다.
- [ ] scaling과 ground truth가 같은 `fixed_paths.tcl`을 사용했다.
- [ ] 두 실행이 같은 netlist revision을 사용했다.
- [ ] restore parasitic의 BEOL/temperature가 target과 일치한다.
- [ ] target을 둘러싸는 scaling 입력 DB가 있다.
- [ ] target DB가 scaling group에서 제외됐다.
- [ ] `.dcalc`에 `Scaling libraries used`가 있다.
- [ ] `.missing`은 기존 known-invalid path만 포함한다.
- [ ] scaling/ground-truth block 수와 report unit이 일치한다.
- [ ] MAE의 compared/excluded path 수를 확인했다.
- [ ] 실행 명령, `.selection.tcl`, `.libgroups*`, `.dcalc`, `.missing`, scaling report,
      ground-truth report, MAE TXT/JSON을 함께 보관했다.
