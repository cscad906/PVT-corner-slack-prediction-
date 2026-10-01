# Restore session 기반 PrimeTime scaling 운영 가이드

이 문서는 처음 코드를 전달받은 담당자가 PrimeTime restore session에서 native
library scaling을 실행하고, 동일한 fixed path의 ground truth와 비교하는 절차를
설명합니다. 일반 scaling 실행 파일은 `run_scaling_after_restore.tcl`입니다.

## 1. 전달할 파일과 담당자 준비물

전달할 파일은 다음과 같습니다.

| 파일 | 용도 | 실행 환경 |
|---|---|---|
| `pt/run_scaling_after_restore.tcl` | restore session에서 PT scaling 및 fixed-path 측정 | `pt_shell` |
| `pt/run_scaling_after_restore_net.tcl` | (실험) net 모드: `SCALING_POWER_NET` 전체에 목표 전압을 걸어 clock tree·경로 밖 셀까지 스케일링. 원본을 load-only로 불러 씀 | `pt_shell` |
| `pt/check_loo_groups_after_restore.tcl` | 현재 full-group session에서 fixed-path 관련 그룹의 목표 코너 포함 여부를 읽기 전용으로 일괄 조회 | `pt_shell` |
| `pt/show_library_voltages.tcl` | 로드된 library의 Operating Conditions 전압/온도 목록 조회 | `pt_shell` |
| `pt/show_library_scaling_group.tcl` | 입력한 library가 속한 scaling group의 전체 library와 전압/온도/rail 조회 | `pt_shell` |
| `fixed_paths.tcl` | 모든 비교에 공통으로 사용할 경로 목록 | `pt_shell` |
| `analysis/compare_scaling_mae.py` | scaling과 ground truth의 path별 오차 및 MAE 계산 | Linux shell |
| `analysis/plot_ground_truth_slack.py` | ground-truth slack 통계 및 분포 생성 | Linux shell |

담당자는 다음 환경을 준비해야 합니다.

1. 설계, SDC, parasitic, 필요한 PVT library가 복원되는 PrimeTime session
2. 실제 target corner를 사용하는 ground-truth session 또는 scenario
3. 동일한 netlist에서 `1_union.py`로 만든 `fixed_paths.tcl`
4. Python 3.6 이상

### LOO 가드 (TL-001 ~ TL-003)

`run_scaling_after_restore.tcl`은 목표 코너 DB가 타이밍에 들어갈 수 있는
경로가 하나라도 있으면 **그룹 정의·V/T 변경·update_timing 전에** 멈춥니다.
DB 파일 경로로 비교하므로 `report_lib_groups`의 반올림(0.685 → 0.69) 영향을
받지 않습니다.

| 번호 | 멈추는 경우 | 시점 |
|---|---|---|
| `TL-001` | 설계의 어떤 셀(clock tree 등 fixed path 밖 포함)이 목표 코너 DB에 링크됨. hold용 min-library 매핑도 포함 | `PLAN_DESIGN_LIBRARIES` 끝 |
| `TL-002` | nearest 정책이 목표 코너 DB를 고름 → 멈추지 않고 후보에서 제외. 목표 DB밖에 없으면 `NL-001` | 계획 중 |
| `TL-003` | 설계가 쓰는 library의 active scaling group 멤버에 목표 코너 DB가 있음 (세션에 있던 그룹, 이 스크립트가 만든 그룹 모두) | `PREPARE_SCALING_GROUPS` 끝 |

"목표 코너 DB"는 목표 process·전압·온도와 정확히 같은 로드된 DB입니다. 이번
scaling rail의 library set이거나 전압 격자가 있는 set만 셉니다. 다른 rail의 한
점짜리 library(IO 등)가 우연히 목표 전압과 같은 것은 제외합니다.

목표 코너별로 받는 세션(예: 목표 0.6 V → 0.64 V에 링크, 그룹은 0.6 V만 뺀 전체)은
세 검사를 모두 통과해야 합니다. 로그에 다음 두 줄이 있어야 합니다.

```text
LOO CHECK TL-001: PASSED | target_dbs_loaded=... design_libraries=... linked_to_target=0
LOO CHECK TL-003: PASSED | active_groups_checked=... groups_with_target_db=0 | evidence=...
```

증거 파일은 `details/<결과 rpt 이름>.loo_check.txt`이며 마지막 줄이
`LOO_CHECK_STATUS: PASSED`여야 합니다. `target_dbs_loaded=0`은 목표 코너 DB가
세션에 아예 없다는 뜻으로 정상입니다.

### u_mem VDDPE LOO가 필요한 경우

기존 `run_scaling_after_restore.tcl`은 u_mem의 **활성 그룹에 목표 VDDPE가
남아 있으면 `UM-015`로 중단**합니다. PrimeTime은 활성 그룹에서 라이브러리
하나만 안전하게 빼는 명령을 제공하지 않습니다. 따라서 현재 full-group
restore session에서 LOO timing을 바로 재실행할 수 없습니다.
`UM-015`에는 목표 라이브러리를 제외한 뒤 **같은 활성 그룹**에 남는 VDDPE
전압과 내삽 가능 여부가 표시됩니다. 예를 들어 그룹이 `0.475, 0.685 V`이고
목표가 `0.685 V`라면 한 점만 남으므로 `NO_BRACKET`입니다. 이 경우 그룹을
다시 만들 수 있어도 별도의 호환 가능한 고전압 입력 DB가 없으면 PT 내삽 LOO는
성립하지 않습니다. `BRACKET`이더라도 현재 활성 그룹을 제자리에서 바꿀 수
없다는 제한은 그대로입니다.
`UM-015`보다 앞서 로그의 `LOO GROUP AUDIT`가 fixed-path target rail에
연결된 코어 그룹과 선택된 u_mem 그룹을 모두 읽기 전용으로 검사합니다.
`TARGET`은 그 rail/온도에 목표 라이브러리가 있음을, `ABSENT`는 해당
그룹 보고서에 목표점이 없음을, `RAIL_UNVERIFIED`는 보고서에서 해당 rail을
확인하지 못했음을 뜻합니다. 이 목록은 초기 후보 범위의 진단이며 최종
스케일링 셋 선택은 뒤의 planner가 결정합니다. u_mem이 먼저 중단됐다고
다른 그룹이 LOO를 통과했다는 뜻은 아닙니다.
현재 세션에서 timing 실행 없이 이 감사만 하려면 다음을 source합니다.

```tcl
source /path/to/pt/check_loo_groups_after_restore.tcl
```

결과는 `<RESULT_FOLDER>/details/<목표 결과 이름>.loo_groups.log`에 저장됩니다.
`TARGET` 또는 `RAIL_UNVERIFIED`가 있는 그룹을 확인하면 됩니다. 이 명령은
전압·온도, scaling group, 타이밍을 변경하지 않습니다.
같은 라이브러리로 `define_scaling_lib_group`을 다시 호출해도 기존 그룹은
교체되지 않습니다. 로컬 PrimeTime V-2023.12-SP4 검증에서는 `SLG-316`이
출력되고 명령의 반환값이 `0`이었으며 그룹 내용은 그대로였습니다.

u_mem 을 스케일링하려면 일반 파일의 USER SETTINGS 에서 네이티브 모드를 켭니다.
이 모드는 library 이름이 아니라 PrimeTime 그룹의 `VDDPE` rail 값을 직접 읽어
목표 위아래 DB 를 고릅니다. 이름에 전압이 두 개 들어 있어 이름만으로 축을
정할 수 없는 u_mem library 도 이 방식으로 처리됩니다.

```tcl
set VDDPE_SCALING_NAME_PATTERNS "*u_mem*"
set TARGET_VDDPE_VOLTAGE <TARGET_VOLTAGE 와 같은 값>   ;# VDDPE 가 코어 net 에 있음
```

LOO 는 목표 코너를 그룹에서 뺀 코너별 restore session 으로 보장합니다. 그 세션의
u_mem 그룹에도 목표 VDDPE 가 남아 있으면 `UM-015` 로 멈춥니다.

`run_scaling_after_restore.tcl`은 DB, netlist, SDC, SPEF를 새로 읽지 않습니다.
전부 restore session에 들어 있어야 합니다. target library가 메모리에 로드되어
있는 것은 괜찮지만 보간하는 scaling group에서는 제외되어야 합니다.
아래의 명시적 고정 셋 예외는 restore DB를 유지하며, 해당 셋을 보간하지 않습니다.

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
복원합니다. 먼저 primary power PG pin의 실제 supply 연결을 조회하고,
`SCALING_POWER_NET`에 연결된 fixed-path cell이 사용하는 library family만
내삽 검사 및 scaling group 구성 대상으로 선택합니다.
사용 여부는 연결된 library의 **원본 DB 경로와 내부 library 이름을 함께**
비교합니다. 같은 내부 이름을 쓰는 다른 DB가 로드돼 있다는 이유만으로
그 DB의 셋을 필수 대상으로 선택하지 않습니다. 실제 사용 중인 library의
source 경로를 확인할 수 없으면 `LS-001`로 중단합니다.
fixed path 밖의 cell과 SI aggressor는 restore 상태를 유지합니다.

다른 supply net에만 연결된 셋은 입력 전압이 여러 개여도 내삽 검사에서 제외하고
restore 상태를 유지합니다. 같은 셋이 고정 rail과 scaling rail 양쪽에 사용되면
그 셋은 내삽 검사하되 실제 전압 변경은 scaling rail의 cell/PG pin에만 적용합니다.
따라서 scaling rail의 셋에서 양쪽 입력이 부족하면 여전히 `Cannot bracket`로
중단합니다. 추가로 지정하지 않은 셋은 범위 밖 target을 가까운 DB로 대체하지 않습니다.
PG 연결을 확인할 수 없는 fixed-path cell은 고정이라고 추측하지 않고
`FP-006` 또는 `FP-007`로 중단합니다.

고정된 한 점만 있는 SRAM, macro, IO library set은 scaling group에 넣지 않고
restore session에 연결된 DB를 그대로 사용합니다. 해당 block을 통과하는 path는
부분적으로만 scaling될 수 있으므로 결과 해석 시 구분해야 합니다.

특정 셋을 내삽에서 제외하고 restore 세션에 연결된 DB와 V/T를 유지하려면
`FIXED_LIBRARY_SET`에 셋 이름이나 공통 패턴을 입력하고
`FIXED_LIBRARY_VOLTAGE`를 기본값 `"restore"`로 둡니다. 다른 전압 DB를 고르거나
셀을 재연결하지 않고, 해당 셀에 target 전압·온도를 적용하지 않습니다.
여러 셋의 실제 DB nominal 전압이 달라도 공통 전압값을 입력할 필요가 없습니다.
셋 이름이 빈칸이면 명시적 예외를 사용하지 않습니다. 고정 supply net에만 연결된
셀은 이 옵션을 입력하지 않아도 자동으로 제외됩니다. 옵션의 존재나 DB 전압
개수만으로 scaling 대상 여부를 판정하지 않습니다.

숫자 등이 다른 여러 셋을 추가로 고정해야 하면 공통 이름 뒤에 `*`를 붙여
한 번에 선택할 수 있습니다. 다음 예시의 `macro_`는 실제 셋의 공통 부분으로
바꿉니다. `FIXED_LIBRARY_SET`은 여전히 공란으로 실행할 수 있습니다.

```tcl
set FIXED_LIBRARY_SET "macro_*"
set FIXED_LIBRARY_VOLTAGE "restore"
```

여러 이름/패턴을 공백으로 나열하는 `"macro_* io_*"`도 지원합니다. 정확한
전체 이름이 있으면 먼저 그 이름으로 선택하며, 패턴에서는 `*`와 `?`만
와일드카드입니다. 이름의 대괄호는 문자 그대로 처리합니다. 선택 범위는
fixed path에서 실제 사용하는 셋으로 제한하고, 하나라도 매칭하지 않는
입력은 중단합니다. `FIXED LIBRARY SET SELECTION`에 선택 개수와 이름을 표시합니다.
`*`는 이름 중간에도 쓸 수 있습니다. 예를 들어 `block_rcmax_rev1`과
`block_cmax_rev1`을 지정하려면 `"block_*_rev1"`로 선택할 수 있습니다.
셋을 하나로 합치는 기능은 아닙니다. 기본 restore 정책은 각 셀의 기존 DB를 유지합니다.
숫자를 입력하면 재연결 없이 기존 DB nominal 전압이 그 숫자와 같은지만 확인합니다.

과거의 가까운 DB 근사를 의도적으로 사용할 때만 `"nearest"`를 명시합니다.
이는 PrimeTime 외삽 기능이 아니며 기본 동작에서 실행하지 않습니다. 각 셋 안에서 동일 process와 목표 온도의
로드된 DB 중 목표 전압에 가장 가까운 전압 하나를 선택합니다. BEOL이나 보조 rail
전압 등 셋 이름의 다른 부분은 유지하며 다른 셋의 DB를 가져와 채우지 않습니다.
후보가 0.475/0.685 V라면 목표 0.5 V에서는 0.475 V, 0.8 V에서는 0.685 V입니다.
거리가 같으면 낮은 전압을 선택합니다. 같은 선택 전압의 revision이 여러 개거나
목표 온도의 후보가 없으면 중단합니다. exact target DB도 이 정책에서는 선택할 수 있습니다.

선택한 DB로 실제 재연결하는 범위는 해당 셋의 fixed-path cell 중
`SCALING_POWER_NET`에 연결된 cell뿐입니다. 같은 셋의 다른 고정 rail cell과
fixed path 밖의 cell은 restore 상태를 유지합니다. 같은 셀 이름과 signal-pin
이름/방향을 사전 확인하고, PrimeTime `size_cell`의 기능 동등성 검사를 거쳐
재연결합니다. PG-pin 이름/종류와 supply 연결이 달라지면 중단하고 원래 DB로
되돌리기를 시도합니다. 이때 `eco_strict_pin_name_equivalence`는 일시적으로
켜고 원래 설정으로 복구합니다.

재연결된 cell은 선택 DB의 nominal 전압으로 계산하며 hold용 min 전압도 같은
값을 적용합니다. 해당 cell에서 원래 scaling supply에 연결된 PG pin만 변경하고,
다른 PG pin과 supply net의 전압은 유지합니다. 온도는 선택 DB의 목표 온도를 씁니다.
선택 DB에 별도의 min library 연결이 있으면 그 DB도 같은 nominal 전압/온도인지
확인하고, 다르면 재연결 전에 `NL-002`로 중단합니다. 같은 전압/온도의 min 연결은
유지하며 `MIN_DB`에 기록합니다. 다른 cell에도 영향을 주는 library 전체의
max/min 관계를 이 스크립트가 바꾸지는 않습니다.
로그의 `NEAREST DB BINDING VERIFIED`는 모든 해당 cell의 실제 연결 DB 경로를
검증한 결과입니다. `NEAREST_DB_BOUND`에는 목표 전압, 선택 전압, cell 개수와 DB가
표시되고 같은 내용이 `details/*.rpt.inputs.txt` 및 `.selection.tcl`에 저장됩니다.
일반 내삽 셋의 대표 arc 검증 결과 `.dcalc`는 그대로 생성됩니다.

기존처럼 재연결 없이 restore DB를 유지하려면 `FIXED_LIBRARY_VOLTAGE`에
`0.685` 같은 숫자를 넣습니다. 이 경우 선택된 모든 셋에 공통으로 적용되는 예상
nominal 전압을 실제 연결 DB와 비교하며, 다른 전압 DB가 연결되어 있으면 중단합니다.
고정 rail에만 있는 셋은 이 옵션 없이도 자동 제외됩니다.

숫자를 입력하는 기존 정책에서는 fixed path에서 실제 사용하는 library의
`report_lib` 전압이 지정 값과 일치하는지 변경 전에 검증합니다.
전압 확인 시에는 보고서 자릿수를 일시적으로 높여 0.685 V를 0.69 V로
오인하지 않도록 하고, 확인 후 원래 보고서 자릿수 설정을 복구합니다.
0.475 V DB가 연결되어 있다면 0.685 V DB가 메모리에 있어도 중단합니다.
고정 셋의 온도·rail 조건·기존 group은 restore 상태를 유지하며, 이 설정만으로
모든 rail의 실제 전압을 검증했다는 뜻은 아닙니다. 따라서 ground truth에서도
같은 고정 셋 조건을 사용해야 비교할 수 있습니다.

기존 group에 target이 포함되어 있어도 group 전체가 지정한 고정 셋에만 속하면
그대로 유지합니다. 고정 셋과 보간 셋이 섞인 group은 예외 처리하지 않습니다.
scaling rail의 나머지 셋은 목표 DB를 제외한 기존 보간 규칙을 계속 적용합니다.
기존 group의 target 포함 검사도 이번에 scaling할 셋과 연결된 group을 대상으로
하며, 그 셋과 다른 셋이 섞인 group은 group 전체를 검사합니다.

library 이름에 주 전압과 보조 rail 전압이 함께 들어간 multi-rail library는
`report_lib` Operating Conditions의 주 전압만 scaling 축으로 인식합니다. 이름의
다른 rail 전압은 family 구분값으로 유지하므로, 보조 전압이 다른 library를 같은
scaling group에 섞지 않습니다.

target voltage를 적용할 supply net 하나만 Tcl 맨 위 `USER SETTINGS`에 명시합니다.
restore session에서 조회된 나머지 supply net은 모두 자동으로 fixed 처리합니다. 스크립트는
fixed-path cell의 `type=primary_power` PG pin과 실제 `supply_connection`을 확인한 뒤,
scaling rail에 연결된 PG pin만 `set_voltage -cell ... -pg_pin_name ...`으로 변경합니다.
선택된 u_mem의 `VDDPE` PG 핀은 별도 예외입니다. `VDDPE`는 **핀 이름**이므로
`available supply nets`에 같은 이름의 넷이 없어도 됩니다. 이 핀이 실제로 연결된
supply net은 다른 이름일 수 있습니다. `TARGET_VDDPE_VOLTAGE`를 설정하면 선택된
fixed-path u_mem 셀의 `VDDPE` 핀에만 셀 단위 전압을 적용하고, 연결된 supply net
자체는 변경하지 않습니다. 실행 전후 핀 전압과 supply-net 보고서를 별도로 검증합니다.
일반 scaling 대상 외의 fixed rail과 fixed path 밖의 cell에는 전압을 적용하지 않습니다.
fixed는 임의 전압을 새로 설정한다는 뜻이 아니라 restore 상태를 그대로 유지한다는
뜻입니다. temperature도 scaling 대상 cell 집합에만 적용합니다.

## 4. 실행 설정

`run_scaling_after_restore.tcl` 맨 위 `USER SETTINGS`에 실행 조건을 모두 입력합니다.
파일을 `source`하면 설정을 검사한 뒤 scaling을 바로 시작하므로 별도의 실행 명령은
필요하지 않습니다.

```tcl
set TARGET_PROCESS      "SSPG"
set TARGET_VOLTAGE      0.57
set TARGET_TEMPERATURE  25
set TARGET_BEOL         "rcmax"
set SCALING_AXIS        "V"
set ANALYSIS            "setup"

set FIXED_PATH_FILE "/company/work/pt_scaling_eval/input/fixed_paths.tcl"
set RESULT_FOLDER   "/company/work/pt_scaling_eval/scaling_output"
set PROGRESS_INTERVAL_MINUTES 10

set SCALING_POWER_NET "실제_scaling_rail_이름"   ;# 여러 개면 "VDD VDD_CPU" 또는 "VDD,VDD_CPU"

# Optional: selected sets keep their restored DB and conditions.
set FIXED_LIBRARY_SET     ""          ;# 셋 이름/공통 패턴, 없으면 빈칸
set FIXED_LIBRARY_VOLTAGE "restore"   ;# 현재 연결 DB 유지. 숫자는 nominal 전압 확인만 수행
```

`PROGRESS_INTERVAL_MINUTES`는 긴 작업 중 현재 단계, 해당 단계 경과 시간과 전체
경과 시간을 몇 분마다 터미널에 출력할지만 정합니다. scaling 계산과 결과에는
영향을 주지 않습니다.

각 설정의 의미는 다음과 같습니다.

| 설정 | 입력 방법 |
|---|---|
| `TARGET_PROCESS` | `report_lib`의 Operating Conditions에 표시되는 실제 process 이름 |
| `TARGET_VOLTAGE` | 목표 voltage, V 단위 |
| `TARGET_TEMPERATURE` | 목표 온도, 섭씨. 영하 25도는 `-25` |
| `TARGET_BEOL` | `rcmax`, `rcmin`, `cmax` 또는 회사 고유 `CORNER_NAME` |
| `SCALING_AXIS` | `V`, `T`, `VT` 중 하나 |
| `ANALYSIS` | setup은 `setup`, hold는 `hold` |
| `FIXED_PATH_FILE` | 공통 `fixed_paths.tcl`의 절대경로 |
| `RESULT_FOLDER` | 결과 `.rpt`를 저장할 폴더의 절대경로. 부산물은 자동으로 `details/`에 저장 |
| `SCALING_POWER_NET` | `available supply nets`에 실제로 있는 코어 target supply net의 정확한 이름. 여러 개면 공백 또는 쉼표로 구분하며 모두 같은 `TARGET_VOLTAGE`를 받음. 빠뜨린 net의 셀은 조용히 fixed가 되므로 로그의 `AUTO-FIXED POWER NETS`를 확인. u_mem의 `VDDPE` PG 핀 이름을 입력하는 곳이 아님 |
| `FIXED_LIBRARY_SET` | 내삽에서 제외하고 기존 DB를 유지할 셋 이름/공통 패턴. 여러 개는 공백으로 구분. 빈칸이면 명시적 예외 없음 |
| `FIXED_LIBRARY_VOLTAGE` | 기본 `"restore"`: 기존 DB와 V/T 유지. 숫자: 기존 DB nominal 전압 확인. `"nearest"`를 명시할 때만 가까운 DB로 재연결 |

setup용 `fixed_paths.tcl`은 내부 `DTYPE`이 `max`, hold용은 `min`이어야 합니다.
스크립트가 `ANALYSIS`와 다르면 실행을 중단합니다.

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

로드된 library별 전압을 간단히 확인하려면 다음 조회 전용 Tcl을 실행합니다.

```tcl
source /path/to/repository/pt_si_re/pt/show_library_voltages.tcl
```

파일 내부에 설정할 항목은 없으며 `restore_session` 뒤 `source`만 하면 됩니다.
각 library의 Operating Conditions에 정의된 전압·온도·condition 이름과 전체
library 개수를 출력합니다. 조건이 여러 개면 전부 표시하고, 값을 읽을 수 없으면
`UNAVAILABLE`로 표시합니다. 메모리에 로드된 모든 library를 대상으로 하므로
현재 design에서 사용하지 않는 library도 포함될 수 있습니다.
이 값은 library 기준 전압이며 셀별 `set_voltage` override나 multi-rail PG pin의
모든 전압을 조회한 결과는 아닙니다. 이 조회는 전압·온도·scaling group을
변경하거나 timing을 갱신하지 않으며 파일도 만들지 않습니다.

특정 library에서 외삽 경고가 발생했다면 `show_library_scaling_group.tcl` 맨 위의
빈 입력란에 PrimeTime library 이름 **또는 오류의 `library set '...'` 안에 나온
셋 이름**을 입력합니다. 실제 library 이름을 넣을 때는 DB 파일 경로나
`library/cell` 이름이 아니라 `get_libs`에 표시되는 이름을 정확히 적습니다.
같은 이름이 여러 DB에 있으면 후보 `extended_name`을 출력하며 중단합니다.
그때는 표시된 후보 중 하나를 `DB경로:library이름` 형태 그대로 입력합니다.

`PLAN_DESIGN_LIBRARIES`에서 `Cannot build scaling inputs for required library set`
오류가 났다면 **`LIBRARY_NAME ""`를 그대로 두어도 됩니다.** 같은 pt_shell에 남은
`scaling_config`의 실행 로그를 읽고 마지막 `RUN ERROR`에서 실패한 셋 이름을
자동 추출합니다. `details/`와 이전 형식의 report 옆 로그를 모두 지원합니다.
로그의 마지막 오류가 다른 종류이거나 로그가 없으면 임의로 셋을 고르지 않고
`LG-001`로 중단합니다. 이 조회 때문에 scaling을 다시 실행하지 않습니다.

```tcl
set LIBRARY_NAME "실제_library_이름_또는_library_set_이름"
```

경고가 발생한 **같은 `pt_shell` 세션**에서 실행합니다. 이미 restore했다면 다시
restore할 필요가 없습니다.

```tcl
source /path/to/repository/pt_si_re/pt/show_library_scaling_group.tcl
```

실제 library 이름을 입력하면 그 library가 속한 scaling group만 조회하며, 그 group의 모든 member
library 이름과 process·온도·전압·`extended_name`을 PrimeTime 원본 표로 출력합니다. multi-rail
library는 rail별 전압도 표에 그대로 표시됩니다. 이 값은 library group의 값이며
셀/PG pin에 적용된 `set_voltage` override를 보여주는 것은 아닙니다.
전압 내삽 여부는 같은 조건에서 **대상 rail**의 전압이 target 양쪽에 있는지 확인합니다.

셋 이름은 scaling Tcl이 만든 묶음 이름이므로 `get_libs`에서 직접 찾을 수 없습니다.
실제 library 이름으로 찾지 못하면, 같은 세션에 이미 정의된 `auto_scaling::catalog`를
사용해 **scaling과 동일한 PVT/family 해석 규칙**으로 로드된 셋 구성원을 조회합니다.
scaling 실행의 process 설정으로 필터링하며, 셋 내 library별 전압·온도·process·DB
경로를 출력하고 현재 생성된 PrimeTime scaling group은 별도 표로 표시합니다.
로드된 셋 구성원에는 planner가 제외하는 target/다른 온도 library도 있을 수 있으므로,
이 목록 전체가 실제 scaling 입력이라는 뜻은 아닙니다. catalog 전압은 scaling 코드의
해석 값이며 native group 표에는 실제 group의 rail별 전압이 표시됩니다.

셋 조회의 `CATALOG AUDIT`는 실제 로드된 library 수와 PVT 해석 성공·실패·catalog
누락 수를 나누어 표시합니다. `CATALOG VOLTAGES`는 **모든 셋·공정·온도에서 해석된
전압의 합집합**이며, 그 전압들이 선택한 셋의 내삽 입력이라는 뜻은 아닙니다.
`SET LOOKUP AUDIT`의 `other_set`은 다른 셋으로 분류된 DB 수,
`same_set_other_process`는 같은 셋이지만 공정 설정 때문에 빠진 DB 수입니다.
`V INPUT AUDIT`는 목표 온도에서의 후보, 다른 온도, 목표점 제외를 별도로 셉니다.
nearest 정책에서는 목표점도 후보로 인정하므로 `nearest_candidates`로 표시합니다.

다른 전압 DB가 있는데 위쪽 `LIB=... voltage=...` 목록에는 두 전압만 나온다면,
조회 Tcl 맨 위를 다음처럼 설정하고 같은 세션에서 다시 source합니다.

```tcl
set SHOW_ALL_LOADED_LIBRARIES 1
```

전체 catalog row의 `AUDIT LIB`에 원본 library·DB·분류된 셋과 제외 이유를 표시합니다.
`OTHER_LIBRARY_SET`, `OTHER_PROCESS`, `OTHER_TEMPERATURE`, `EXCLUDED_TARGET_POINT`를
구분하며, PVT 해석 실패는 `UNPARSED`와 실제 실패 이유로 출력합니다.
`NOT_CATALOGED ... SOURCE_PATH_REUSED`는 같은 DB 파일 안의 다른 내부 library가
source 경로 중복 제거로 catalog에서 빠졌다는 뜻이고, `NO_SOURCE_FILE`은 source
경로를 조회할 수 없다는 뜻입니다. 기본값 `0`은 간단한 개수·전압 요약과 해석
실패/누락 각각 최대 3개만 보여줍니다. 이 진단은 후보를 합치거나 scaling 규칙을
변경하지 않고, 추가 `report_lib`·PG pin 검색·timing 갱신도 수행하지 않습니다.
전압 범위 표 자체는 supply 자격을 판정하지 않습니다. 최신 run Tcl에서 계획을
수행했다면 같은 세션의 `RECORDED SET SCOPE`가 DB 경로와 내부 이름으로 확인한
사용 여부 및 PG 연결 판정을 보여줍니다. `FIXED_RAIL_ONLY`는 고정 전원에서만
사용되어 내삽이 필요 없는 셋, `NOT_USED_BY_FIXED_PATHS`는 fixed path에서
사용하지 않는 셋입니다. `TARGET_RAIL_MATCH`는 대상 전원의 셀에서 사용하는
셋이며, 이후 static/명시적 fixed 정책에 따라 실제 내삽 여부를 결정합니다.
`SCOPE LINKED LIB`에는 그 판정의 근거가 된 실제 연결 DB만 출력합니다.
이 정보는 계획 시점에 기록한 것이므로 nearest DB 교체 후의 현재 연결을
증명하는 표는 아닙니다. 설정이나 current design이 바뀌거나 이전 run Tcl이라
기록이 없으면 `UNAVAILABLE`로 표시합니다. 조회 때문에 PG 연결을 다시 검색하지
않습니다. 고정 메모리 셋의 `CANNOT_BRACKET`을 실행 중 외삽 오류로 해석하면 안 됩니다.

시간이 오래 걸리는 STA를 실행하지 않고 대상 선택만 확인하려면, run Tcl의
USER SETTINGS를 실제 조건으로 설정한 뒤 **restore된 pt_shell**에서 다음을
실행합니다. 두 경로는 실제 파일 경로로 바꿉니다. 이 과정은 DB·전압·온도·그룹을
변경하지 않고 보고서 파일도 만들지 않습니다. fixed path의 PG 연결 및 library
catalog 조회 시간은 필요합니다.

```tcl
set auto_scaling_restored_load_only 1
source /path/to/pt/run_scaling_after_restore.tcl
unset auto_scaling_restored_load_only
set scaling_config [auto_scaling::build_restore_config]
auto_scaling::plan $scaling_config
source /path/to/pt/show_library_scaling_group.tcl
```

`plan`이 `Cannot bracket`로 끝나도 그전에 대상 판정이 기록되므로 다음 source
명령을 실행할 수 있습니다. query Tcl의 `LIBRARY_NAME`에는 확인할 셋 이름을
입력합니다. 빈칸 자동 선택은 기존 실행 로그가 있을 때만 사용할 수 있고,
위의 계획 조회는 새 실행 로그를 생성하지 않습니다. 현재 세션이 이미 변경된
상태라면 이 조회는 그 상태를 기준으로 하며, 원래 restore 상태를 증명하지 않습니다.

V 축 조회에는 다음처럼 target 온도의 전압과 목표점 제외 후의 양쪽 입력도 표시합니다.

```text
V CHECK: target=0.76 temperature=25 loaded_at_target_temperature=0.54 0.685
V CHECK: after_target_exclusion=0.54 0.685 lower=0.685 upper=NONE status=CANNOT_BRACKET
```

`upper=NONE`이면 target보다 높은 입력이 없고, `lower=NONE`이면 낮은 입력이
없습니다. `STATIC_ON_V_AXIS`는 그 온도에서 전압이 한 점 이하인 셋,
`EXPLICIT_FIXED_SET`은 명시적으로 고정한 셋입니다. 이 표는 catalog의 범위
진단이며 실제 cell/PG 전압 또는 전체 scaling 성공을 증명하는 표는 아닙니다.
셋 조회가 `found 0`이면 `SET LOOKUP`의 process 필터와 이름이 일치한 공정도
표시하므로, 이름 자체가 없는 경우와 다른 공정에서만 일치하는 경우를 구분합니다.

셋 조회는 `run_scaling_after_restore.tcl`을 이미 실행한 **같은 세션**에서 사용합니다.
scaling이 외삽 오류로 중단된 뒤에도 조회할 수 있으며, group을 만들기 전에
중단됐다면 구성원 목록은 나오고 `CURRENT GROUP: NONE`이 표시됩니다.
조회 Tcl은 scaling Tcl을 다시 source하거나 timing을 변경하지 않습니다.

library가 로드되어 있어도 group에 속하지 않으면 `SCALING GROUP: NONE`을
표시합니다. scaling 실행 중 생성한 group은 저장하지 않은 fresh restore session에는
없을 수 있습니다. 이름이 없거나 일치하지 않으면 설정 안내와 함께 중단합니다.
이 파일 하나만 사용하며 scaling이나 timing 변경은 수행하지 않습니다.

확인 기준은 다음과 같습니다.

- `BEOL`이 `TARGET_BEOL`과 같아야 합니다. `RC_MAX_model`처럼 이름에 `rcmax`가
  들어가면 `TARGET_BEOL "rcmax"`로 인식합니다.
- `PARASITIC_TEMP`가 `TARGET_TEMPERATURE`와 정확히 같아야 합니다.
- voltage 내삽에 필요한 양쪽 voltage DB가 `LIBRARIES`에 있어야 합니다.
- 모든 library가 메모리에 로드된 것은 정상입니다.
- 보간용 기존 scaling group에 target voltage/temperature가 들어 있으면 leave-one-out이
  아니므로 스크립트가 중단합니다. 가능하면 scaling group이 없는 fresh restore
  session을 사용합니다. 명시적으로 지정한 고정 셋만으로 구성된 group은 유지할 수 있습니다.

고유 BEOL 이름이 `rcmax`, `rcmin`, `cmax`를 포함하지 않으면 Tcl의
`TARGET_BEOL`에 실제 이름을 그대로 적습니다. 비교할 때는 대소문자와 `-`, `_`
같은 구분 문자를 제거하지만 그 밖의 이름은 정확히 같아야 합니다.

## 6. PT scaling 실행

Tcl 맨 위 `USER SETTINGS`를 저장한 뒤 복원한 `pt_shell`에서 source합니다.

```tcl
restore_session /company/session/path
source /company/work/pt_scaling_eval/config/run_scaling_after_restore.tcl
```

`source` 직후 설정 검증, library 선택과 timing 변경이 자동으로 시작됩니다.

스크립트가 자동으로 다음 작업을 수행합니다.

1. restore된 전체 supply net 개수/이름 확인, 설정한 scaling net 하나만 scaling으로 지정하고 나머지는 자동 fixed 처리
2. 현재 parasitic의 BEOL과 온도 확인
3. fixed path cell의 primary PG pin과 실제 supply 연결을 먼저 조회
4. restore된 library의 process/voltage/temperature 조사
5. 지정한 scaling net의 fixed-path cell이 쓰는 셋의 내삽 입력 선택; 지정 예외 셋은 가까운 DB 선택 및 재연결 사전 검사
6. scaling library group 구성 또는 기존 group 검증
7. nearest 정책이면 지정 셋의 target-rail fixed-path cell을 가까운 DB로 재연결하고 DB nominal 전압/온도 적용
8. 앞서 조회한 전원 연결과 실제 active scaling group으로 일반 내삽 cell/PG pin 대상 확정
9. 내삽 cell에는 target voltage/temperature 적용 후 `update_timing`
10. 동일한 fixed path만 최종 report로 측정하며 key 끝의 원본 `#idx` 유지
11. nearest 셀의 실제 연결 DB 및 `report_delay_calculation`의 일반 내삽 증거 확인

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

1. `VERIFY_POWER_NETS`: 전체 supply net 조회, 설정한 하나를 scaling으로 매칭하고 나머지는 자동 fixed 처리
2. `VERIFY_PARASITICS`: restore된 BEOL과 parasitic 온도 검사
3. `CLASSIFY_FIXED_PATH_SUPPLY`: group 생성 전 fixed-path cell의 실제 primary supply 연결 조회
4. `PLAN_DESIGN_LIBRARIES`: 일반 셋 내삽 입력 및 nearest 셋 DB 선택/사전 검사
5. `PREPARE_SCALING_GROUPS`: scaling group 생성 또는 기존 group 검증
6. `APPLY_NEAREST_LIBRARY_DB`: nearest 정책일 때만 DB 재연결, PG 연결 보존 확인 및 nominal V/T 적용
7. `CLASSIFY_FIXED_PATH_POWER`: 이미 조회한 전원 연결과 계획된 active group으로 일반 내삽 V/T 대상 확정
8. `APPLY_TARGET_VOLTAGE_TEMP`: 내삽 대상의 목표 voltage/temperature 적용
9. `UPDATE_TIMING_SI_POCV`: SI/POCV를 포함한 timing 갱신
10. `GENERATE_TIMING_REPORT`: fixed path별 timing report 생성
11. `VERIFY_SCALING_RESULT`: nearest DB 연결 및 일반 내삽 증거 검사

일반적으로 전체 시간의 대부분은 `UPDATE_TIMING_SI_POCV`와 fixed path 수에
비례하는 `GENERATE_TIMING_REPORT`에서 사용됩니다. 정확한 시간은 설계 크기,
SI aggressor 수, POCV 설정, RC fallback warning 수와 서버 부하에 따라 달라집니다.

restore session에 기존 scaling group이 있으면 scaling rail의 모든 fixed-path scalable family의
계획된 입력 DB가 그 group들에 실제 포함됐는지도 검사합니다. 일부 family만 있는
group이면 `Existing scaling groups do not cover...` 오류로 중단합니다.

`FIXED-RAIL LIBRARY SETS (no interpolation check)`에는 다른 supply net에만
연결되어 내삽 검사에서 제외한 셋을 표시합니다. `details/*.inputs.txt`에도
`FIXED_RAIL_UNSCALED`와 제외 이유를 남깁니다. `CLASSIFY_FIXED_PATH_SUPPLY`에서
조회한 연결을 같은 실행의 후속 대상 선택에 재사용합니다. nearest 재연결이 있으면
그 셀들의 PG 연결이 유지됐는지 확인하기 위한 별도 조회만 추가합니다.

이 순서와 rail 선택의 회귀 테스트는 저장소 루트에서 다음처럼 실행합니다.
PrimeTime 라이선스 없이 mock collection으로 계획 단계의 조건을 검사합니다.

```bash
tclsh pt_si_re/pt/tests/test_supply_before_scaling.tcl
```

rail 분류 로그는 다음 형태입니다.

```text
RESTORED SUPPLY NETS: count=12 names=<전체 supply net 이름>
CONFIGURED SCALING POWER NET MATCH: requested=<설정 이름> matched=<실제 이름> count=1
SCALING POWER NETS: count=1 names=<scaling rail 이름>
AUTO-FIXED POWER NETS (unchanged): count=11 names=<나머지 supply net 이름>
FIXED-PATH VOLTAGE GROUP: pg_pin=VDD cells=... rails=<scaling rail 이름>
FIXED-PATH CELL SCOPE: all=... scalable_library=... target_voltage=... static_library=...
AUTO-FIXED POWER NETS (unchanged): count=11 names=<나머지 supply net 이름>
SCALING POWER NETS (fixed-path cell override only): <scaling rail 이름>
APPLY CELL-LEVEL VOLTAGE: target=... pg_pin=VDD cells=... rails=...
```

`SCALING COVERAGE`는 내삽 가능한 family와 한 점뿐인 static family 개수를,
`FIXED-PATH CELL SCOPE`는 path 전체 cell, scaling library 소속, 실제 target
voltage를 받는 cell과 static library cell 개수를 보여줍니다. fixed-path scalable
cell의 primary rail이 restore session의 supply 목록에 없으면 임의 처리하지 않고
중단합니다.

정상 실행의 마지막 부분은 다음 형태입니다.

```text
FIXED PATHS RESULT: requested=294 measured=290 missing=4
DONE: restore-session scaling report = <결과 파일>
VERIFY: scaling library evidence = <RESULT_FOLDER>/details/<결과 rpt 이름>.dcalc
RUN COMPLETE: Restored-session scaling and fixed-path reporting finished.
RUN LOG: <RESULT_FOLDER>/details/<결과 rpt 이름>.log
```

스크립트는 같은 코너·축·analysis의 결과와 로그가 이미 있어도 **덮어쓰며 재실행**합니다.
실행을 시작할 때 해당 `.rpt`와 아래 표의 부가 파일을 정리하고 로그를 새로 기록합니다.
재실행이 중간에 실패해도 이전 `.dcalc`나 report가 새 결과처럼 남지 않도록 합니다.
다른 코너/analysis의 파일과 결과 폴더 내 다른 파일은 삭제하지 않습니다.
별도 덮어쓰기 설정은 필요 없으며, 로그에 `OUTPUT MODE: overwrite`가 표시됩니다.

Tcl이 출력하는 안내·오류 문구는 영어로 표시합니다. 소스의 한국어 주석은 유지하며,
UTF-8/EUC-KR 표시 환경 차이 때문에 오류 본문이 깨지는 것을 방지합니다.
fixed-path 오류에는 아래의 짧은 번호도 표시되므로 긴 회사 이름을 전달할 필요가 없습니다.

| 번호 | 의미 |
|---|---|
| `FP-000` | `FIXED_PATH_FILE` 설정 누락 |
| `FP-001`~`FP-003` | fixed-path pin/instance 형식 또는 현재 design의 cell 조회 문제 |
| `FP-004` | path cell과 연결된 lib_cell 개수 불일치 |
| `FP-005` | 고정 library 제외 후 active scaling group을 사용하는 path cell이 없음 |
| `FP-006` | fixed-path cell의 primary power PG pin 또는 연결을 확인하지 못함 |
| `FP-007` | path cell의 supply가 restore된 supply map에서 확인되지 않음 |
| `FP-008` | active scaling cell의 primary PG pin이 지정한 `SCALING_POWER_NET`에 연결되지 않음 |
| `FP-009` | scaling cell을 포함하는 timing path가 핀·edge·constraint 조건으로 resolve되지 않음 |
| `FP-010` | key 끝에 유효한 원본 `#idx`가 없음; 임의로 재번호를 매기지 않고 중단 |
| `FP-011` | 서로 다른 경로에 같은 원본 idx가 있어 중단 |
| `SV-001` | resolve된 경로들에 scaling cell의 입력→출력 delay arc가 없음 |
| `SV-002` | `report_delay_calculation` 명령 실행 실패 |
| `SV-003` | delay calculation에서 외삽 또는 scaling 취소 감지 |
| `SV-004` | `Scaling libraries used` 적용 증거 없음 |
| `SV-005` | 검증 재시도 시 저장된 실행 정보와 현재 design/config 불일치 |
| `NL-001` | 가까운 DB의 동일 process/목표 온도 후보가 없거나(목표 코너 DB 자체는 후보가 아님) 선택 전압의 revision이 여러 개 |
| `TL-001` | 설계 셀이 목표 코너 DB에 링크됨(min-library 매핑 포함). LOO 불가, 다른 코너에 링크된 세션 필요 |
| `TL-003` | 설계가 쓰는 active scaling group에 목표 코너 DB가 있음. 목표를 뺀 그룹의 세션 필요 |
| `NL-002` | DB/동일 이름 셀 조회, signal pin, 실제 V/T 또는 min-library 매핑 사전 검사 실패 |
| `NL-003` | 재연결 후 PG-pin/supply 연결이 달라짐. 재연결 중 실패하면 원래 DB로 되돌리기 시도 |
| `NL-004` | 실제 cell 연결 DB가 선택한 가까운 DB와 다르거나 min-library 매핑이 변경됨 |

`FP-005`는 실제 scaling 대상이 남아 있는지, `FP-008`은 rail 선택과 PG 연결이
맞는지 확인해야 합니다. 번호만으로 fixed path 파일 자체가 잘못되었다고 단정하지 않습니다.

`### FIXED_PATH idx=`와 `.missing`의 `idx=`에는 fixed-path key 끝의 원본 번호를
그대로 사용합니다. 예를 들어 `7_cut.py`로 `#7`, `#42`, `#105`만 남겼으면
결과 idx도 `7, 42, 105`이며, 42번 측정이 실패해도 그 번호를 유지합니다.
경로 출력 순서는 입력 목록과 같고, 진행률과 `requested`는 원본 idx와 별도로
실제 처리한 경로 수를 셉니다. 기존 fixed-path 파일을 새로 만들 필요는 없습니다.
새로 `1_union.py`가 생성하는 Tcl의 직접 실행도 같은 규칙을 사용합니다.

### `CLASSIFY_FIXED_PATH_SUPPLY`에서 `FP-002`가 난 경우

fixed path에서 추출한 instance 이름을 현재 디자인에서 유일하게 찾지 못한
오류입니다. 다른 코너에서 성공했더라도 이번 restore 디자인/조회 위치/실제로
읽힌 fixed-path 파일이 같은지 확인해야 합니다. 오류만으로 전체 파일 불일치인지
일부 오래되거나 잘못된 path인지 판단할 수 없습니다.

오류가 난 같은 pt_shell에서 다음 조회 전용 파일을 source합니다.

```tcl
source /path/to/repository/pt_si_re/pt/check_fixed_path_cells.tcl
```

설정 항목은 없으며 원래 `scaling_config`의 fixed-path 파일을 읽습니다.
실제 파일 절대경로와 디자인을 표시하고, 최상위에서 cell을 조회한 뒤 원래
`current_instance`로 돌아옵니다. 이름 대신 `COUNTS`와 원본 path idx를 출력합니다.
`NONE_MATCH`는 추출한 셀 이름을 하나도 찾지 못한 경우, `PARTIAL_MATCH`는 일부만
못 찾은 경우입니다. `affected_paths`는 해당 셀이 포함된 fixed path 개수입니다.
`SAMPLE`의 `pin_matches=1 pin_owner_cells=1`인데 `cell_matches=0`이면 pin 객체는
존재하므로 문자열로 추출한 cell 이름 처리 문제를 먼저 확인합니다.
`ALL_CELLS_MATCH`는 cell 조회 통과이며 timing path/PG 연결이 정상이라는 뜻은
아닙니다. 이 조회는 V/T나 timing을 변경하지 않고 path를 삭제/제외하지 않습니다.
담당자에게 이름을 복사하기 어려우면 `FIXED CELL CHECK`와 `COUNTS` 두 줄만 전달합니다.

### `VERIFY_SCALING_RESULT`에서 cell arc 오류가 난 경우

기존 검증 코드는 scaling cell의 핀이 하나라도 있는 첫 경로를 골랐습니다.
그 셀이 capture flop의 D 핀으로만 등장하면 같은 셀의 입력→출력 delay arc가
없어 검증이 중단될 수 있습니다. 수정된 코드는 다음 fixed path도 확인하여
실제 scaling 대상 cell delay arc가 있는 경로를 사용합니다. capture 입력 핀만
있다는 이유로 scaling 실패 또는 외삽이라고 판정하지 않습니다.

`.dcalc`는 검증 시작 시 만들며, 실패해도 `SCALING_VERIFICATION_STATUS: FAILED`와
오류 코드를 남깁니다. setup에서는 `report_delay_calculation -max`, hold에서는
`-min`으로 원래 analysis와 같은 delay를 확인합니다. 이 검증은 대표 cell arc의
scaling 사용 확인이며 모든 경로/셀이 올바르다는 전수 검증을 의미하지 않습니다.

긴 timing 계산이 끝난 뒤 이 오류가 났으면 **실패한 동일 pt_shell을 닫거나
다른 session을 restore하지 않은 상태**에서 아래 순서로 검증만 재시도합니다.
먼저 파일을 수정된 버전으로 교체하되 기존 회사 `USER SETTINGS`는 유지합니다.

```tcl
# 1. 새 함수만 읽고 자동 scaling 실행을 막습니다.
set ::auto_scaling_restored_load_only 1
source /path/to/run_scaling_after_restore.tcl
unset ::auto_scaling_restored_load_only

# 2. 실패한 실행에서 남아 있는 원래 config로 검증만 합니다.
auto_scaling::verify_after_run $scaling_config
```

`scaling_config`는 실패한 실행의 설정이며 다시 만들지 않습니다. 재시도는 기존
`.selection.tcl`과 fixed-path 파일을 읽어 대상을 확인하고 `.dcalc`를 갱신합니다.
library group 생성, V/T 적용, 명시적인 `update_timing`, report 재생성은 호출하지
않으며 기존 `.rpt`/`.missing`/입력 기록은 유지합니다. 로그는 `details/`의 기존 `.rpt.log`에
추가하며 `VERIFY ONLY END: status=SUCCESS/FAILED`로 이번 검증 상태를 구분합니다.
세션을 변경했거나 `scaling_config`가 남아 있지 않으면 이 복구 절차를 사용하지 않습니다.

## 7. scaling 결과 파일

예를 들어 설정이 `SSPG/0.57 V/25 C/rcmax/V/setup`이면 파일 이름은 다음
형태입니다.

```text
restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt
```

결과 폴더 최상위에는 timing report만 두고, 나머지 파일은 `details/`에 저장합니다.
파일 이름에 코너·축·analysis가 있으므로 여러 코너가 같은 폴더를 사용해도 구분됩니다.

```text
<RESULT_FOLDER>/
  restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt
  details/
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.log
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.missing
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.inputs.txt
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.selection.tcl
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.libgroups.before
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.libgroups
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.loo_check.txt
    restored_scaled_SSPG_0p57V_25C_RCMAX_V_setup.rpt.dcalc
```

`details/`는 자동 생성되므로 `RESULT_FOLDER`만 설정하면 됩니다. 이전 형식으로
report 옆에 남아 있는 같은 코너의 부산물은 일반 재실행 시 정리됩니다. 검증만
재시도할 때는 기존 내용과 로그를 `details/`로 옮겨 보존하며, 같은 파일이 양쪽에
있으면 임의로 합치지 않고 중단합니다. 다른 코너 파일은 변경하지 않습니다.

각 파일의 의미는 다음과 같습니다.

| 파일 | 확인 내용 |
|---|---|
| `.rpt` | fixed path별 PT scaling timing report와 slack |
| `details/<결과 rpt 이름>.missing` | 찾지 못했거나 timing이 완성되지 않은 fixed path |
| `details/<결과 rpt 이름>.inputs.txt` | family별 실제 입력 P/V/T/DB와 목표 코너의 사람이 읽기 쉬운 요약 |
| `details/<결과 rpt 이름>.log` | terminal에 표시된 scaling 실행 과정과 오류를 함께 저장한 log |
| `details/<결과 rpt 이름>.selection.tcl` | 선택된 library family와 scaling 입력 기록 |
| `details/<결과 rpt 이름>.libgroups.before` | 실행 전 scaling group |
| `details/<결과 rpt 이름>.libgroups` | 실행에 사용한 scaling group |
| `details/<결과 rpt 이름>.loo_check.txt` | 목표 코너 DB 목록과 TL-001/TL-003 결과. 마지막 줄 `LOO_CHECK_STATUS: PASSED` |
| `details/<결과 rpt 이름>.dcalc` | 실제 cell arc에서 scaling library가 사용된 증거 |

다음 문자열이 `.dcalc`에 있어야 합니다.

```bash
grep -n "Scaling libraries used" /company/work/pt_scaling_eval/scaling_output/details/*.dcalc
```

문자열이 없거나 `SLG-320`, `DEL-012`가 있으면 결과를 사용하지 않습니다.
Tcl도 `.dcalc`에서 이 두 오류 또는 외삽 취소 문구를 발견하면 완료 처리하지 않고
중단합니다. PrimeTime은 외삽 실패 뒤에도 `Scaling libraries used` 목록을 표시할
수 있으므로, 목록 존재 여부만으로 성공을 판단하면 안 됩니다.

어떤 두 점 또는 네 점을 사용해 target을 계산했는지는 다음처럼 확인합니다.

```bash
cat /company/work/pt_scaling_eval/scaling_output/details/*.rpt.inputs.txt
```

각 family 아래에 `INPUT 1`, `INPUT 2`와 필요하면 `INPUT 3`, `INPUT 4`가
process/voltage/temperature/DB 경로와 함께 표시되고, 마지막
`INTERPOLATION ... -> target=...` 줄에 목표점이 표시됩니다. 실제 target DB가
로드되어 있었으면 leave-one-out을 증명하기 위해 `EXCLUDED_TARGET`에도 기록됩니다.

```bash
grep -nE "SLG-320|DEL-012|Error:|Fatal:" \
    /company/work/pt_scaling_eval/scaling_output/details/*
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
절대경로를 Tcl 맨 위 `FIXED_PATH_FILE`에 넣습니다.

복원 결과가 `DTYPE=max`이면 `ANALYSIS "setup"`, `DTYPE=min`이면
`ANALYSIS "hold"`로 설정한 뒤 restore session에서 실행합니다.
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
| P/V/T library를 찾지 못함 | `TARGET_PROCESS`가 `report_lib`의 실제 이름과 다르거나 bracket DB 없음 | Operating Conditions와 loaded library 확인 |
| library selection ambiguous | 같은 PVT의 revision/중복 library가 여러 개 | 담당자가 사용할 PDK revision 하나를 정해 session 정리 |
| `needs exactly one library ... found N` | 같은 family/PVT로 분류된 DB가 없거나 여러 개 | 오류 아래 `MATCH: LIB=... DB=...` 목록 확인. 서로 다른 LIB면 family 분류를 수정하고, 같은 LIB의 여러 DB면 사용할 revision 하나를 결정 |
| target corner가 기존 scaling group에 포함 | leave-one-out 조건 위반 | target이 들어 있지 않은 fresh restore session 사용 |
| BEOL 또는 parasitic temperature 불일치 | 다른 scenario/session의 parasitic 활성 | 정확한 target BEOL/temperature session을 restore |
| `incomplete fixed path` 또는 missing path | 원래 invalid path이거나 netlist revision 불일치 | `.missing`에서 기존 invalid 목록과 비교 |
| power/supply net 오류 | UPF 연결 또는 multi-voltage domain이 예상과 다름 | `get_supply_nets` 확인 후 담당 STA 방법론에 맞는 domain 결정 |
| 설정한 scaling power net을 찾지 못함 | `SCALING_POWER_NET` 이름과 restore session의 `full_name`이 다름 | `get_object_name [get_supply_nets -hierarchy *]` 결과의 정확한 이름 입력 |
| fixed-path primary rail이 supply 목록에 없음 | UPF 연결이 해석되지 않았거나 hierarchical 이름이 다름 | 오류에 나온 rail과 restore session의 supply 연결 확인 |
| `SV-001` / `cell arc`를 찾지 못함 | 검증 후보가 capture 입력만 포함하거나 모든 후보에 scaling delay arc가 없음 | 수정된 Tcl로 동일 세션에서 검증만 재시도. 모든 후보에 arc가 없으면 결과 검증은 미완료 |
| scaling evidence 없음 | 실제 scaling이 cell arc에 적용되지 않음 | 결과 폐기 후 `.dcalc`, `.libgroups` 검사 |
| `SLG-320` 또는 `DEL-012` | 외삽 또는 scaling 적용 실패 | target을 둘러싸는 interpolation DB 준비 |

multi-voltage/UPF 설계에서 어떤 supply domain에 target voltage를 적용할지는
설계 방법론 결정입니다. 단일 `VDD/VSS`로 가정하지 말고 담당 STA 엔지니어가
domain을 확정한 뒤 실행해야 합니다.

## 12. 결과 인계 체크리스트

- [ ] 실행 Git commit hash를 기록했다.
- [ ] Tcl 맨 위 `USER SETTINGS`의 target process/voltage/temperature/BEOL/axis/analysis를 기록했다.
- [ ] `FIXED_PATH_FILE`과 `RESULT_FOLDER`를 절대경로로 지정했다.
- [ ] target voltage를 실제로 적용할 `SCALING_POWER_NET`의 정확한 이름을 모두 설정했다(여러 개면 공백/쉼표 구분). `AUTO-FIXED POWER NETS`에 스케일링할 net이 남아 있지 않다.
- [ ] 로그에서 나머지 supply net이 `AUTO-FIXED POWER NETS`로 분류됐는지 확인했다.
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
