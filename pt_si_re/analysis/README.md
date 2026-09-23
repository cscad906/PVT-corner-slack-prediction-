# PrimeTime scaling 결과 분석

이 디렉토리는 PrimeTime 실행이 끝난 뒤 사용하는 Python 후처리 도구를 모아 둡니다.
PrimeTime에서 `source`하는 Tcl 파일은 `pt/` 디렉토리에 있습니다.

- `compare_scaling_mae.py`: PT scaling report와 target-corner ground truth의 path별 오차 및 MAE 계산
- `plot_ground_truth_slack.py`: 여러 ground-truth report의 slack 통계, CSV, SVG 및 터미널 histogram 생성
- `recover_fixed_paths_from_ground_truth.py`: 남아 있는 ground-truth report에서 scaling용 fixed path 목록 복원

```bash
python3 analysis/compare_scaling_mae.py scaled.rpt ground_truth.rpt \
    --output-dir results/pt_scaling_comparison

python3 analysis/plot_ground_truth_slack.py ground_truth/*.rpt \
    --output-dir results/ground_truth_slack
```

원본 `fixed_paths.tcl`을 잃어버렸지만 ground-truth report가 남아 있으면 다음처럼
복원합니다.

```bash
python3 analysis/recover_fixed_paths_from_ground_truth.py ground_truth.rpt
```

출력된 `fixed_paths_<ground-truth-name>.tcl`의 절대경로를
`auto_scaling::run` 명령의 `-fixed-path` 옵션에 넣습니다. timing table이 없는
실패 block은 복원할 수 없으며, 스크립트가 제외 개수와 사유를 출력합니다.

`--output-dir`을 생략하면 ground-truth report의 파일명을 target corner 이름으로
사용해 `pt_scaling_comparison/<target-corner>/` 아래에 `path_errors.txt`,
`summary.txt`, `summary.json`을 생성합니다. 같은 코너를 다시 실행하면 기존 결과를
덮어쓰지 않고 `<target-corner>_run2`, `_run3` 폴더를 자동으로 만듭니다.

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
실행 결과가 길면 맨 마지막 `COPY THIS RESULT`의 세 줄만 복사해 전달하면 됩니다.
이 세 줄에는 회사 clock/path 이름을 포함하지 않습니다.

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

새 scaling report 옆에 `<scaled-report>.inputs.txt`가 있으면 그 내용을
`summary.txt`의 `Scaling inputs used by PrimeTime` 아래에도 복사합니다. 따라서
MAE와 함께 각 library family가 사용한 입력 P/V/T/DB와 target을 한 파일에서
확인할 수 있습니다.

```bash
cat results/pt_scaling_comparison/<target-corner>/summary.txt
less -S results/pt_scaling_comparison/<target-corner>/path_errors.txt
```

두 스크립트 모두 입력 `.rpt`의 slack을 항상 ns로 읽고 결과를 ps로 저장합니다.

MAE 실행 결과의 `status counts`는 제외 원인을 다음처럼 구분합니다.

- `missing_scaling_block` / `missing_ground_truth_block`: 양쪽 report의 path key가 다름
- `unresolved_scaling_path`: scaling report에서 해당 path의 slack을 측정하지 못함
- `unresolved_ground_truth_path`: ground truth에서 해당 path의 slack을 측정하지 못함
- `unresolved_both_paths`: 양쪽 모두 해당 path의 slack을 측정하지 못함

터미널 histogram은 다음 명령으로 확인합니다.

```bash
less -S results/ground_truth_slack/ground_truth_slack_terminal.txt
```
