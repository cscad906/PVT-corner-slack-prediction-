# PrimeTime scaling 결과 분석

이 디렉토리는 PrimeTime 실행이 끝난 뒤 사용하는 Python 후처리 도구를 모아 둡니다.
PrimeTime에서 `source`하는 Tcl 파일은 `pt/` 디렉토리에 있습니다.

- `compare_scaling_mae.py`: path별 MAE·최대오차·fixed-path WNS 및 누적 지연 오차 분해
- `compare_point_delays.py`: 동일 timing point의 `Incr` delay를 cell/net 및 path 구간별로 비교
- `plot_ground_truth_slack.py`: 여러 ground-truth report의 slack 통계, CSV, SVG 및 터미널 histogram 생성
- `recover_fixed_paths_from_ground_truth.py`: 남아 있는 ground-truth report에서 scaling용 fixed path 목록 복원
- `check_scaling_result.py`: scaling 결과 폴더의 LOO·스케일링 검증 항목을 한 번에 검사(읽기 전용)

## scaling 결과 자동 검사 (`check_scaling_result.py`)

```bash
python3 analysis/check_scaling_result.py <RESULT_FOLDER> [<RESULT_FOLDER> ...]
```

폴더 안의 `restored_scaled_*.rpt` 를 전부 찾아 코너마다 검사합니다(path 모드와
net 모드 `_net.rpt` 모두). 중간에 멈춘 실행도 로그로 찾아서 보여 줍니다.
결과 파일은 읽기만 하고, 같은 내용을 `<RESULT_FOLDER>/check_summary.txt` 에 씁니다.
화면 출력은 영어이고, 맨 끝 `WHAT THE ITEMS MEAN` 에 항목 뜻이 나옵니다.

판정: 하나라도 `FAIL` 이면 그 코너 숫자는 쓰지 않습니다. `WARN` 은 LOO 는 깨끗하지만
일부가 스케일링 안 됐거나 경로가 빠진 경우입니다.

| 항목 | 무엇을 보나 | 뜻 |
|---|---|---|
| `run` | 로그의 `RUN END` | PT 실행이 끝까지 성공했는가. FAIL 이면 그 결과는 못 씀 |
| `loo TL-001` | 로그 | 설계의 어떤 셀도 목표 코너 DB 에 링크돼 있지 않다(hold min 매핑 포함). 셀이 정답 DB 를 직접 읽지 않음 |
| `loo TL-003` | 로그 | 설계가 쓰는 scaling group 어디에도 목표 코너 DB 가 없다(파일 경로 비교). 보간에도 정답이 섞일 수 없음 |
| `loo LOO_CHECK` | `.loo_check.txt` | 위 두 검사의 파일 기록. "not even loaded" 는 목표 DB 가 세션에 아예 없음(가장 강함), "loaded, none linked or grouped" 도 LOO |
| `loo .dcalc` | `.dcalc` | **PT 가 직접** 실제 셀 지연 계산에 쓴 DB 목록. 목표 DB 나 이름에 목표 전압이 든 DB 가 없어야 함. 스크립트 판단과 독립된 증거 |
| `inputs` | `.inputs.txt` | 보간 입력 DB 가 목표 아래와 위에 다 있다. 목표와 같은 입력은 누설, 한쪽뿐이면 외삽 |
| `coverage` | 로그 | WARN = **scaling net 위**인데 library 에 그룹이 없어 스케일링 안 된 fixed-path 셀 수(링크 코너 값 그대로, 진짜 빈틈). INFO = 자동 fixed net 위 셀이라 원래 안 바뀌어야 하는 것(정상) |
| `paths` | 로그 | PT 가 이번 실행에서 못 잡은 경로 수. MAE 비교에서 빠짐 |
| `evidence` | 로그 | `SCALING VERIFICATION`: fixed path 의 실제 셀에 스케일링이 적용됐고 외삽이 없음 |
| `net` | 로그 | net 모드만. NET-001 net 위 library 모두 그룹 있음 / net power 모든 PG 핀이 목표 전압 / clock 클럭 셀도 스케일링됨 |
| `nets` | 로그 | 적은 net 과 자동 fixed net 목록. 스케일링해야 할 net 이 fixed 쪽에 있으면 에러 없이 그 셀이 빠지므로 눈으로 확인 |

맨 끝 `SUMMARY` 표: `target_dbs` 는 세션에 올라온 목표 코너 DB 수(0 이 가장 좋음),
`used_dbs_V` 는 PT 가 실제로 쓴 DB 전압, `static`/`missing` 은 위 coverage/paths 숫자입니다.
마지막 줄 코드: `OK-SCALECHECK` 전부 PASS, `W-SCALECHECK` WARN 있음, `E-SCALECHECK` FAIL 있음.

```bash
python3 analysis/compare_scaling_mae.py scaled.rpt ground_truth.rpt \
    --analysis setup --output-dir results/pt_scaling_comparison

python3 analysis/compare_scaling_mae.py scaled_hold.rpt ground_truth_hold.rpt \
    --analysis hold --output-dir results/pt_scaling_comparison

python3 analysis/compare_point_delays.py scaled.rpt ground_truth.rpt \
    --output-dir results/point_delay_comparison

python3 analysis/plot_ground_truth_slack.py ground_truth/ \
    --output-dir results/ground_truth_slack
```

### 디자인 전체 코너를 한 번에 (`compare_all_corners.py`)

```bash
python3 analysis/compare_all_corners.py --scaled-dir <RESULT_FOLDER> --gt-dir <.../PERIC0>
```

`RESULT_FOLDER` 의 `restored_scaled_*.rpt` 를 전부 찾아, `<gt-dir>/setup/` 과
`<gt-dir>/hold/` 에서 이름의 공정·전압(숫자로 비교, `0p6`=`0p60`)·온도·BEOL 이 같은
`.rpt` 하나와 짝지어 비교합니다. 짝이 없거나 여럿이면 비교하지 않고 `NOT COMPARED` 에
후보와 함께 적습니다. 계산은 `compare_scaling_mae.py` 함수를 그대로 쓰므로 코너 하나씩
돌린 것과 같고, 코너별 상세 파일도 그대로 남습니다. `--analysis setup|hold` 를 주지 않으면
둘 다 합니다.

결과는 화면과 `<output-dir>/summary_all.txt`(있으면 `_runN`) 하나입니다. 표 두 개:
- `RAW`: 경로 수, GT slack 평균, MAE·MAE%, max err·max%, GT/PT WNS·WNS 오차·WNS%, clock 상태
- `PERIOD-ALIGNED`: 경로마다 자기 클럭 edge 차이를 뺀 MAE·MAE%·bias·max·WNS 오차(아래 `--align-period` 와 같은 계산)

퍼센트: `MAE%`, `max%` = 값 / mean(|GT slack|) x 100, `WNS%` = |WNS 오차| / |GT WNS| x 100.

### 코너별 클럭 주기가 다를 때 (`--align-period`)

스케일링 run 은 링크 코너 세션의 SDC 주기를, GT 는 목표 코너의 주기를 씁니다. 둘이
다르면 slack 오차에 주기 차이가 통째로 들어가 MAE 가 커집니다(`CLOCK VALIDATION:
INVALID`, `capture clock edge MAE` 가 주기 차이와 비슷).

```bash
python3 analysis/compare_scaling_mae.py scaled.rpt ground_truth.rpt --analysis setup --align-period
```

기존 출력은 그대로 두고 `=== PERIOD-ALIGNED ===` 블록과 `period_aligned.txt` 를 더
만듭니다. 경로마다 **그 경로 리포트에 찍힌 launch/capture edge 시간**의 차이를 slack
오차에서 뺍니다(setup: capture−launch, hold: launch−capture). 전체 주기를 하나로 가정하지
않으므로 클럭이 여러 개거나 분주 클럭·multicycle 이어도 경로별로 맞게 빠집니다. 클럭
이름·rise/fall·path group/type 이 두 리포트에서 다르거나 edge 줄이 여러 개인 경로는
보정하지 않고 개수만 셉니다(`clock_mismatch`, `multi_edge`). 코너별 SDC 의 uncertainty
같은 다른 차이는 빠지지 않으며 `path_diagnostics.txt` 에 따로 보입니다.
보정 후 MAE 가 주기 차이를 뺀 스케일링 오차입니다.

`plot_ground_truth_slack.py`에 디렉터리를 주면 하위 `.rpt`를 모두 읽습니다.
리포트별 통계와 함께 `ALL_REPORTS` 행에 전체 path 관측값의 평균·분포를
기록합니다. 같은 path가 여러 코너에 있으면 코너마다 한 번씩 집계합니다.
직접 파일을 나열하는 기존 방식도 사용할 수 있습니다.

원본 `fixed_paths.tcl`을 잃어버렸지만 ground-truth report가 남아 있으면 다음처럼
복원합니다.

```bash
python3 analysis/recover_fixed_paths_from_ground_truth.py ground_truth.rpt
```

출력된 `fixed_paths_<ground-truth-name>.tcl`의 절대경로를
`auto_scaling::run` 명령의 `-fixed-path` 옵션에 넣습니다. timing table이 없는
실패 block은 복원할 수 없으며, 스크립트가 제외 개수와 사유를 출력합니다.

`--output-dir`을 생략하면 ground-truth report의 파일명을 target corner 이름으로
사용해 `pt_scaling_comparison/setup/<target-corner>/` 또는
`pt_scaling_comparison/hold/<target-corner>/` 아래에 `path_errors.txt`,
`path_diagnostics.txt`, `summary.txt`, `summary.json`을 생성합니다.
`--output-dir`은 setup/hold 폴더를 담는 상위 폴더입니다. 같은 코너를 다시 실행하면
해당 분석 타입 안에서 `<target-corner>_run2`, `_run3` 폴더를 자동으로 만들어
기존 결과를 덮어쓰지 않습니다. Setup과 hold의 실행 번호는 각각 관리합니다.

`--analysis`를 생략하면 두 report의 `Path Type: max`는 setup, `min`은 hold로
판별합니다. Path Type이 없거나 max/min이 섞여 있으면 결과 폴더를 만들기 전에
중단하고 `--analysis setup` 또는 `--analysis hold`를 명시하도록 안내합니다.
폴더 분류는 파일명에 포함된 setup/hold 문자열로 추측하지 않습니다.

`path_errors.txt`는 외부 프로그램 없이 `less -S`로 볼 수 있는 고정폭 텍스트입니다.
모든 path의 ground-truth slack, scaling slack, signed error, absolute error와 제외
사유를 저장합니다. 비교 가능한 path는 absolute error가 큰 순서로 정렬하며,
unresolved/missing path는 파일 마지막에 둡니다. 터미널에는 전체 내용을
쏟아내지 않고 absolute error가 큰 상위 10개 path만 출력합니다.

timing report에 `data arrival time`과 `data required time`이 있으면 각 항목의
scaling-GT 오차도 함께 기록합니다. setup은 path별로
`slack error = required error - arrival error`이므로 arrival와 required가 같은
방향과 비슷한 크기로 이동하면 둘의 개별 MAE가 커도 slack MAE는 작을 수 있습니다.
예를 들어 arrival MAE 283 ps, required MAE 268 ps, slack MAE 15 ps는 공통 이동이
slack에서 상쇄된 가능한 조합입니다. 개별 component MAE만으로 실패를 판정하지
말고 `path_errors.txt`에서 두 signed error의 부호와 차이를 함께 확인합니다.
둘이 비슷하게 움직이지 않으면서 slack MAE도 크면 launch/data 또는
capture/constraint 조건 차이를 조사합니다.
비교 프로그램이 정상 종료된 것만으로 두 PrimeTime session의 분석 조건이 같다고
판정할 수는 없습니다.

별도 `grep` 없이 Python 실행 직후의 `CLOCK VALIDATION` 구역을 확인합니다.
`PASS`는 clock 이름/edge와 path group/type이 모두 같다는 뜻입니다. `INVALID`는
clock identity, 선택 cycle/edge 또는 path 조건이 달라 현재 MAE를 scaling 오차로
사용할 수 없다는 뜻입니다. `REVIEW`는 generated-clock 후보가 여러 개이거나 clock
정보를 읽지 못해 해당 report 원문 확인이 필요하다는 뜻입니다. 같은 판정과 원인,
최악의 launch/capture edge path는 `summary.txt`에도 저장됩니다.
회사 터미널의 EUC-KR/UTF-8 설정과 무관하게 깨지지 않도록 실행 결과의 `reason`과
`action` 문장은 ASCII 영어로 출력합니다.
실행 결과가 길면 맨 마지막 `COPY THIS RESULT`의 요약 줄을 전달하면 됩니다.
이 요약에는 회사 clock/path 이름을 포함하지 않습니다.

`launch clock edge`, `capture clock edge`는 두 report가 사용한 clock edge time을
비교합니다. 이 MAE가 clock period에 가까우면 서로 다른 cycle/edge 또는 다른
constraint/session을 비교한 것입니다. `identity_mismatches`, `path-group
mismatches`, `path-type mismatches`는 모두 0이어야 합니다. Edge와 group은 같은데
required 오차만 크면 capture clock-tree의 scaling 범위를 우선 확인합니다. Parser는
`data arrival time` 앞의 첫 clock edge를 launch, 뒤의 첫 edge를 capture로
구분합니다. `multi_edge_blocks`가 0이 아니면 generated-clock 구조이므로 해당
worst path의 원문도 직접 대조합니다.

일부 report에 `data required time` 줄이 없으면 `Path Type: max|min`과 path별
slack/arrival 관계식으로 required 오차를 유도합니다. `path_errors.txt`의
`req_source`가 `direct`, `derived_setup`, `derived_hold` 중 어느 방식인지
표시합니다. report에 `Path Type`도 없으면 실행할 때 `--analysis setup` 또는
`--analysis hold`를 지정합니다.

새 scaling report의 결과 폴더에서 `details/<scaled-report>.inputs.txt`를 먼저 찾고,
없으면 예전처럼 report 옆의 `<scaled-report>.inputs.txt`도 찾습니다. 그 내용을
`summary.txt`의 `Scaling inputs used by PrimeTime` 아래에도 복사합니다. 따라서
MAE와 함께 각 library family가 사용한 입력 P/V/T/DB와 target을 한 파일에서
확인할 수 있습니다.

```bash
cat results/pt_scaling_comparison/setup/<target-corner>/summary.txt
less -S results/pt_scaling_comparison/setup/<target-corner>/path_errors.txt
```

Hold 결과를 볼 때는 위 경로의 `setup`을 `hold`로 바꿉니다.

`compare_scaling_mae.py`는 입력 `.rpt`의 slack을 항상 ns로 읽고 결과를 ps로
저장합니다.

같은 명령으로 `path_diagnostics.txt`도 자동 생성합니다. 기존 GT/scaling
report만 사용하므로 GT 세션 접근이나 PrimeTime 재실행은 필요하지 않습니다.

```bash
less -S results/pt_scaling_comparison/setup/<target-corner>/path_diagnostics.txt
```

경로마다 launch clock, data, capture clock의 `Incr`를 cell/net별로 합산하고,
source/network latency, 선택 edge, uncertainty, CPPR, library setup/hold 항목을
`GT / scaling / error`로 보여 줍니다. `error`는 scaling−GT이고 결과는 ps입니다.
`net`은 timing report의 증분이며 SPEF의 순수 RC 값을 추출한 것은 아닙니다.
핀 순서·rise/fall 전이·library cell 구성이 다른 경로도 `REVIEW`로 표시합니다.
상세 파일은 slack 절대오차 내림차순이고, 양쪽 WNS 경로는 `summary.txt`의
idx/key로 찾을 수 있습니다. `summary.txt`와 터미널에는 구간별 누적 지연
오차의 MAE와 설명되지 않은 오차의 MAE를 함께 출력합니다.

`N/A`는 항목이 없거나 읽을 수 없다는 뜻이며 측정된 0과 구분합니다.
`*_unexplained_error_ps`는 알려진 항목의 합산으로 설명되지 않은 두 report의
차이입니다. `scaled_*_residual_ps`, `ground_truth_*_residual_ps`는 각각의 report
자체에서 설명되지 않은 나머지입니다. 반올림, 보고되지 않은 통계 보정이나
해석하지 못한 행 등이 포함될 수 있으므로 잔여값만으로 SDC/POCV를 원인으로
확정하지 않습니다. 6자리 ns 리포트의 반올림 허용값도 경로마다 표시합니다.

`EXPLAINED`는 리포트 항목으로 arrival/required를 재구성할 수 있다는 뜻이며
scaling이 정확하거나 두 세션의 설정이 같다는 뜻이 아닙니다. 기존
`CLOCK VALIDATION`도 함께 확인합니다. timing table이 없는 report는
`UNAVAILABLE`로 표시하면서 기존 MAE/WNS 계산은 계속 수행합니다.

WNS는 양쪽에서 slack을 읽을 수 있는 **동일 fixed path 집합의 최소 slack**이며,
양수이면 양수 그대로 표시합니다. 디자인 전체 WNS와 구분해야 합니다.
WNS 오차율은 `|PT WNS − GT WNS| / |GT WNS| × 100`이고 GT가 0이면 `N/A`입니다.
짧게 전달할 때는 `COPY THIS RESULT`의 `WNS_SHARE`, `DELAY_SHARE`도 활용합니다.

`compare_point_delays.py`는 ideal clock edge 차이가 누적되는 `Path` 열을 사용하지
않고 각 timing point의 `Incr` 열만 비교합니다. 같은 instance의 연속 pin 사이
증분은 `cell`, 새로운 instance의 sink pin에 도달하는 증분은 `net`으로 분류합니다.
여기서 `net`은 timing report에 표시되는 sink-pin 증분이며 SPEF의 순수 RC delay를
직접 추출한 값은 아닙니다. `point_delay_errors.txt`는 absolute error가 큰 순서이고,
터미널 마지막 `POINT_SHARE` 한 줄에는 회사의 point/path 이름을 넣지 않습니다.
`cell`, `net`, `data`의 세 숫자는 각각 `MAE/P95/최대 absolute error` 순서입니다.
`CAPTURE_SHARE`는 capture clock 구간만 다시 cell과 net으로 나눈 결과입니다.

MAE 실행 결과의 `status counts`는 제외 원인을 다음처럼 구분합니다.

- `missing_scaling_block` / `missing_ground_truth_block`: 양쪽 report의 path key가 다름
- `unresolved_scaling_path`: scaling report에서 해당 path의 slack을 측정하지 못함
- `unresolved_ground_truth_path`: ground truth에서 해당 path의 slack을 측정하지 못함
- `unresolved_both_paths`: 양쪽 모두 해당 path의 slack을 측정하지 못함

터미널 histogram은 다음 명령으로 확인합니다.

```bash
less -S results/ground_truth_slack/ground_truth_slack_terminal.txt
```
