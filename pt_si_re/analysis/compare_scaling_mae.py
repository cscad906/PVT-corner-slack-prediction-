#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PrimeTime scaling 결과와 target-corner 실측 결과의 path별 오차를 계산한다.

가장 자주 쓰는 명령
    pt_si_re 디렉터리에서 다음과 같이 실행한다.

    python3 analysis/compare_scaling_mae.py \
        auto_scaling_output/scaled_SSPG_0p5V_25C_rcmax_V_hold.rpt \
        ground_truth/SSPG_0p5V_25C_rcmax_hold.rpt \
        --input-unit ns \
        --output-prefix results/pt_scaling_vs_groundtruth

입력 순서
    첫 번째 파일  : PrimeTime scaling으로 만든 fixed-path timing report
                    (run_scaling_after_restore.tcl의 scaled_*.rpt)
    두 번째 파일  : 실제 target corner의 DB/lib를 사용해 측정한 ground truth
                    fixed-path timing report

    순서를 바꾸면 error와 bias의 부호가 반대로 계산되므로 주의한다.

비교 전에 맞아야 하는 것
    두 report는 같은 fixed_paths.tcl에서 생성돼야 한다. 각 경로 앞에

        ### FIXED_PATH idx=... key=...

    마커가 있어야 하며, 스크립트는 idx가 아니라 key로 같은 경로를 맞춘다.
    setup끼리 또는 hold끼리 비교해야 하고 timing constraint도 같아야 한다.
    report_timing의 시간 단위도 두 파일이 같아야 한다.

시간 단위
    --input-unit은 입력 report에 기록된 slack 숫자의 단위다. 기본값은 ns다.
    결과 CSV와 MAE/RMSE/bias 출력은 항상 ps로 변환된다. PrimeTime report가
    ns라면 기본값 그대로 사용한다.

오차 정의
    error = PT scaling slack - ground-truth slack

    MAE   : path별 |error|의 평균
    RMSE  : 큰 오차에 더 민감한 제곱평균제곱근
    bias  : error의 부호를 유지한 평균. 양수면 scaling slack이 GT보다 큼
    worst : 비교된 path 중 가장 큰 |error|

    양쪽 report에서 slack을 모두 읽은 path만 위 네 통계에 포함한다. 한쪽에
    path block이 없거나 report_timing이 실패해 slack이 없는 path는 CSV에
    상태와 함께 남지만 MAE 계산에서는 제외된다.

출력
    --output-prefix results/pt_scaling_vs_groundtruth 라고 주면 다음 두 파일이
    생긴다. 상위 폴더가 없으면 자동으로 만든다. prefix에는 확장자를 붙이지
    않는 것이 가장 명확하다.

    results/pt_scaling_vs_groundtruth.csv
        path별 GT slack, scaling slack, signed error, absolute error, 상태

    results/pt_scaling_vs_groundtruth.json
        비교 path 수, 제외 path 수, MAE, RMSE, bias, worst path 요약

결과 확인
    cat results/pt_scaling_vs_groundtruth.json
    column -s, -t results/pt_scaling_vs_groundtruth.csv | less -S

필요 환경
    Python 3.6 이상. 외부 Python 패키지는 필요 없다.
"""

import argparse
import csv
import json
import math
import re
from pathlib import Path


PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+)\s+key=(.*)$")
SLACK_RE = re.compile(
    r"^\s*slack\s+\((?:MET|VIOLATED)[^)]*\)\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
TO_PS = {"s": 1.0e12, "ms": 1.0e9, "us": 1.0e6,
         "ns": 1.0e3, "ps": 1.0, "fs": 1.0e-3}


class PathResult(object):
    """One fixed-path result; kept simple for Synopsys Python 3.6."""

    __slots__ = ("idx", "key", "slack")

    def __init__(self, idx, key, slack):
        self.idx = idx
        self.key = key
        self.slack = slack


def parse_report(path):
    """Read ### FIXED_PATH blocks and the slack in each successfully measured block."""
    results = {}
    current_idx = None
    current_key = None
    current_slack = None

    def finish():
        nonlocal current_idx, current_key, current_slack
        if current_key is None or current_idx is None:
            return
        if current_key in results:
            raise ValueError(f"duplicate path key in {path}: {current_key}")
        results[current_key] = PathResult(current_idx, current_key, current_slack)

    with path.open(errors="ignore") as report:
        for line in report:
            match = PATH_RE.match(line.rstrip("\n"))
            if match:
                finish()
                current_idx = int(match.group(1))
                current_key = match.group(2).strip()
                current_slack = None
                continue
            if current_key is not None:
                match = SLACK_RE.match(line)
                if match:
                    current_slack = float(match.group(1))
    finish()
    if not results:
        raise ValueError(f"no '### FIXED_PATH idx=... key=...' blocks: {path}")
    return results


def evaluate(scaled, truth, factor):
    rows = []
    errors = []
    scaled_resolved = sum(item.slack is not None for item in scaled.values())
    truth_resolved = sum(item.slack is not None for item in truth.values())

    for key in sorted(set(scaled) | set(truth)):
        pred = scaled.get(key)
        gt = truth.get(key)
        pred_ps = None if pred is None or pred.slack is None else pred.slack * factor
        truth_ps = None if gt is None or gt.slack is None else gt.slack * factor
        if pred_ps is not None and truth_ps is not None:
            error = pred_ps - truth_ps
            errors.append(error)
            status = "compared"
        elif pred is None:
            error = None
            status = "missing_scaling_block"
        elif gt is None:
            error = None
            status = "missing_ground_truth_block"
        elif pred_ps is None:
            error = None
            status = "unresolved_scaling_path"
        else:
            error = None
            status = "unresolved_ground_truth_path"
        rows.append({
            "idx": gt.idx if gt is not None else pred.idx,
            "path_key": key,
            "ground_truth_ps": truth_ps,
            "pt_scaling_ps": pred_ps,
            "pt_scaling_err_ps": error,
            "abs_error_ps": None if error is None else abs(error),
            "status": status,
        })

    if not errors:
        raise ValueError("no path has a resolved slack in both reports")
    abs_errors = [abs(value) for value in errors]
    compared_rows = [row for row in rows if row["abs_error_ps"] is not None]
    worst_row = max(compared_rows, key=lambda row: row["abs_error_ps"])
    summary = {
        "scaled_blocks": len(scaled),
        "scaled_resolved": scaled_resolved,
        "ground_truth_blocks": len(truth),
        "ground_truth_resolved": truth_resolved,
        "compared_paths": len(errors),
        "mae_ps": sum(abs_errors) / len(abs_errors),
        "rmse_ps": math.sqrt(sum(value * value for value in errors) / len(errors)),
        "bias_ps": sum(errors) / len(errors),
        "worst_abs_error_ps": max(abs_errors),
        "worst_path_key": worst_row["path_key"],
        "excluded_paths": len(rows) - len(errors),
    }
    return rows, summary


def write_csv(path, rows):
    columns = ["idx", "path_key", "ground_truth_ps", "pt_scaling_ps",
               "pt_scaling_err_ps", "abs_error_ps", "status"]
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: (f"{value:.6f}" if isinstance(value, float) else
                      "" if value is None else value)
                for key, value in row.items()
            })


def main():
    parser = argparse.ArgumentParser(
        description="PrimeTime scaling slack와 실제 target-corner slack의 path별 MAE를 계산합니다.")
    parser.add_argument("scaled_rpt", type=Path, help="run_scaling_after_restore.tcl 결과 .rpt")
    parser.add_argument("ground_truth_rpt", type=Path, help="실제 target library로 측정한 fixed-path .rpt")
    parser.add_argument("--input-unit", choices=TO_PS, default="ns",
                        help="두 report의 slack 시간 단위 (기본값: ns)")
    parser.add_argument("--output-prefix", type=Path, default=Path("pt_scaling_vs_groundtruth"),
                        help="출력 파일 앞부분 (기본값: pt_scaling_vs_groundtruth)")
    args = parser.parse_args()

    for path in (args.scaled_rpt, args.ground_truth_rpt):
        if not path.is_file():
            parser.error(f"file not found: {path}")

    scaled = parse_report(args.scaled_rpt)
    truth = parse_report(args.ground_truth_rpt)
    rows, summary = evaluate(scaled, truth, TO_PS[args.input_unit])
    summary.update({
        "input_unit": args.input_unit,
        "scaled_report": str(args.scaled_rpt.resolve()),
        "ground_truth_report": str(args.ground_truth_rpt.resolve()),
    })

    csv_path = args.output_prefix.with_suffix(".csv")
    json_path = args.output_prefix.with_suffix(".json")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(csv_path, rows)
    with json_path.open("w") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False)

    print("=== PrimeTime scaling vs ground truth ===")
    print(f"compared paths : {summary['compared_paths']}")
    print(f"excluded paths : {summary['excluded_paths']}")
    print(f"MAE            : {summary['mae_ps']:.3f} ps")
    print(f"RMSE           : {summary['rmse_ps']:.3f} ps")
    print(f"bias           : {summary['bias_ps']:+.3f} ps")
    print(f"worst          : {summary['worst_abs_error_ps']:.3f} ps")
    print(f"CSV            : {csv_path}")
    print(f"summary        : {json_path}")


if __name__ == "__main__":
    main()
