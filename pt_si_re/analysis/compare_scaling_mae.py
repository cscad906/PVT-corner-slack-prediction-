#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Compare PrimeTime scaling slack with target-corner ground truth.

QUICK START (run from the pt_si_re directory)
    python3 analysis/compare_scaling_mae.py \
        auto_scaling_output/scaled_TARGET.rpt \
        ground_truth/TARGET.rpt \
        --input-unit ns \
        --output-prefix results/pt_scaling_vs_groundtruth

INPUT ORDER
    1) scaled_rpt       : scaled_*.rpt from run_scaling_after_restore.tcl
    2) ground_truth_rpt : fixed-path report measured with the real target DB/lib

    Do not reverse the files because error and bias signs would be reversed.

REQUIRED REPORT FORMAT
    Both reports must come from the same fixed_paths.tcl and contain this marker
    before every path:

        ### FIXED_PATH idx=... key=...

    Paths are matched by key, not idx. Compare setup with setup or hold with
    hold, using the same constraints and report time unit.

TIME UNIT
    --input-unit is the slack unit in both reports and defaults to ns. All
    reported slack and error values are converted to ps.

METRICS
    error = PT scaling slack - ground-truth slack
    MAE   = mean absolute error
    RMSE  = root mean square error
    bias  = signed mean error; positive means scaling slack is larger than GT
    worst = largest absolute error

    Only paths with readable slack in both reports enter the metrics. Missing
    or unresolved paths remain in the CSV with a status and are excluded from
    MAE, RMSE, and bias.

OUTPUT
    --output-prefix results/pt_scaling_vs_groundtruth creates:
      results/pt_scaling_vs_groundtruth.csv   per-path values and errors
      results/pt_scaling_vs_groundtruth.json  counts and summary metrics

    The parent directory is created automatically. Give a prefix without an
    extension so the .csv and .json output names are clear.

VIEW WITHOUT VS CODE
    cat results/pt_scaling_vs_groundtruth.json
    column -s, -t results/pt_scaling_vs_groundtruth.csv | less -S

RUNTIME
    Python 3.6 or newer. No external Python package is required.
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
        description="PrimeTime scaling slack\uc640 \uc2e4\uc81c target-corner slack\uc758 path\ubcc4 MAE\ub97c \uacc4\uc0b0\ud569\ub2c8\ub2e4.")
    parser.add_argument("scaled_rpt", type=Path, help="run_scaling_after_restore.tcl \uacb0\uacfc .rpt")
    parser.add_argument("ground_truth_rpt", type=Path, help="\uc2e4\uc81c target library\ub85c \uce21\uc815\ud55c fixed-path .rpt")
    parser.add_argument("--input-unit", choices=TO_PS, default="ns",
                        help="\ub450 report\uc758 slack \uc2dc\uac04 \ub2e8\uc704 (\uae30\ubcf8\uac12: ns)")
    parser.add_argument("--output-prefix", type=Path, default=Path("pt_scaling_vs_groundtruth"),
                        help="\ucd9c\ub825 \ud30c\uc77c \uc55e\ubd80\ubd84 (\uae30\ubcf8\uac12: pt_scaling_vs_groundtruth)")
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
