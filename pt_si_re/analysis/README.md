# PrimeTime scaling 결과 분석

이 디렉토리는 PrimeTime 실행이 끝난 뒤 사용하는 Python 후처리 도구를 모아 둡니다.
PrimeTime에서 `source`하는 Tcl 파일은 `pt/` 디렉토리에 있습니다.

- `compare_scaling_mae.py`: PT scaling report와 target-corner ground truth의 path별 오차 및 MAE 계산
- `plot_ground_truth_slack.py`: 여러 ground-truth report의 slack 통계, CSV, SVG 및 터미널 histogram 생성

```bash
python3 analysis/compare_scaling_mae.py scaled.rpt ground_truth.rpt \
    --input-unit ns --output-dir results/pt_scaling_comparison

python3 analysis/plot_ground_truth_slack.py ground_truth/*.rpt \
    --input-unit ns --output-dir results/ground_truth_slack
```

`--output-dir`을 생략하면 `pt_scaling_comparison/` 폴더에
`path_errors.csv`와 `summary.json`이 생성됩니다.

터미널 histogram은 다음 명령으로 확인합니다.

```bash
less -S results/ground_truth_slack/ground_truth_slack_terminal.txt
```
