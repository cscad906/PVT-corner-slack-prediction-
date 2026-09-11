# PrimeTime scaling 결과 분석

이 디렉토리는 PrimeTime 실행이 끝난 뒤 사용하는 Python 후처리 도구를 모아 둡니다.
PrimeTime에서 `source`하는 Tcl 파일은 `pt/` 디렉토리에 있습니다.

- `compare_scaling_mae.py`: PT scaling report와 target-corner ground truth의 path별 오차 및 MAE 계산
- `plot_ground_truth_slack.py`: 여러 ground-truth report의 slack 통계, CSV, SVG 및 터미널 histogram 생성

```bash
python3 analysis/compare_scaling_mae.py scaled.rpt ground_truth.rpt \
    --output-dir results/pt_scaling_comparison

python3 analysis/plot_ground_truth_slack.py ground_truth/*.rpt \
    --output-dir results/ground_truth_slack
```

`--output-dir`을 생략하면 ground-truth report의 파일명을 target corner 이름으로
사용해 `pt_scaling_comparison/<target-corner>/` 아래에 `path_errors.csv`와
`summary.json`을 생성합니다. 같은 코너를 다시 실행하면 기존 결과를 덮어쓰지
않고 `<target-corner>_run2`, `_run3` 폴더를 자동으로 만듭니다.

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
