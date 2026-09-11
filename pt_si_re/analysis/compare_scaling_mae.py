#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Compare PrimeTime scaling slack with target-corner ground truth.

QUICK START (run from the pt_si_re directory)
    python3 analysis/compare_scaling_mae.py \
        auto_scaling_output/scaled_TARGET.rpt \
        ground_truth/TARGET.rpt

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
    Both input reports are always interpreted as ns. All reported slack and
    error values are converted to ps (1 ns = 1000 ps).

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
    The target-corner name is taken from the ground-truth report filename.
    For ground_truth/SSPG_0p57V_25C_RCMAX_setup.rpt, the script creates:
      pt_scaling_comparison/SSPG_0p57V_25C_RCMAX_setup/path_errors.csv
      pt_scaling_comparison/SSPG_0p57V_25C_RCMAX_setup/summary.json

    Existing results are never overwritten. Running the same corner again
    creates SSPG_0p57V_25C_RCMAX_setup_run2, then _run3, and so on.

    To select another result directory, add:
      --output-dir results/TARGET

    The selected directory is the common root for all corner result folders.

VIEW WITHOUT VS CODE
    cat pt_scaling_comparison/TARGET/summary.json
    column -s, -t pt_scaling_comparison/TARGET/path_errors.csv | less -S

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
NS_TO_PS = 1000.0


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
        elif pred_ps is None and truth_ps is None:
            error = None
            status = "unresolved_both_paths"
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
    status_counts = {}
    for row in rows:
        status = row["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    scaled_keys = set(scaled)
    truth_keys = set(truth)
    summary = {
        "scaled_blocks": len(scaled),
        "scaled_resolved": scaled_resolved,
        "ground_truth_blocks": len(truth),
        "ground_truth_resolved": truth_resolved,
        "shared_path_keys": len(scaled_keys & truth_keys),
        "scaled_only_blocks": len(scaled_keys - truth_keys),
        "ground_truth_only_blocks": len(truth_keys - scaled_keys),
        "compared_paths": len(errors),
        "status_counts": status_counts,
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


def safe_corner_name(report_path):
    """Return a filesystem-safe target-corner name from the GT report name."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", report_path.stem).strip("._")
    return name or "target_corner"


def create_result_dir(output_root, corner_name):
    """Atomically create a new corner directory without overwriting a run."""
    output_root.mkdir(parents=True, exist_ok=True)
    run_number = 1
    while True:
        directory_name = corner_name if run_number == 1 else f"{corner_name}_run{run_number}"
        result_dir = output_root / directory_name
        try:
            result_dir.mkdir()
            return result_dir
        except FileExistsError:
            run_number += 1


def main():
    parser = argparse.ArgumentParser(
        description="PrimeTime scaling slack\uc640 \uc2e4\uc81c target-corner slack\uc758 path\ubcc4 MAE\ub97c \uacc4\uc0b0\ud569\ub2c8\ub2e4.")
    parser.add_argument("scaled_rpt", type=Path, help="run_scaling_after_restore.tcl \uacb0\uacfc .rpt")
    parser.add_argument("ground_truth_rpt", type=Path, help="\uc2e4\uc81c target library\ub85c \uce21\uc815\ud55c fixed-path .rpt")
    parser.add_argument("--output-dir", type=Path, default=Path("pt_scaling_comparison"),
                        help="\ucf54\ub108\ubcc4 \uacb0\uacfc\ub97c \uc800\uc7a5\ud560 \uc0c1\uc704 \ud3f4\ub354 (\uae30\ubcf8\uac12: pt_scaling_comparison)")
    args = parser.parse_args()

    for path in (args.scaled_rpt, args.ground_truth_rpt):
        if not path.is_file():
            parser.error(f"file not found: {path}")

    scaled = parse_report(args.scaled_rpt)
    truth = parse_report(args.ground_truth_rpt)
    rows, summary = evaluate(scaled, truth, NS_TO_PS)
    summary.update({
        "input_unit": "ns",
        "output_unit": "ps",
        "scaled_report": str(args.scaled_rpt.resolve()),
        "ground_truth_report": str(args.ground_truth_rpt.resolve()),
    })

    corner_name = safe_corner_name(args.ground_truth_rpt)
    result_dir = create_result_dir(args.output_dir, corner_name)
    csv_path = result_dir / "path_errors.csv"
    json_path = result_dir / "summary.json"
    write_csv(csv_path, rows)
    with json_path.open("w") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False)

    print("=== PrimeTime scaling vs ground truth ===")
    print(f"compared paths : {summary['compared_paths']}")
    print(f"excluded paths : {summary['excluded_paths']}")
    print(f"shared keys    : {summary['shared_path_keys']}")
    print("status counts  :")
    for status, count in sorted(summary["status_counts"].items()):
        print(f"  {status:<29} {count}")
    print(f"MAE            : {summary['mae_ps']:.3f} ps")
    print(f"RMSE           : {summary['rmse_ps']:.3f} ps")
    print(f"bias           : {summary['bias_ps']:+.3f} ps")
    print(f"worst          : {summary['worst_abs_error_ps']:.3f} ps")
    print(f"CSV            : {csv_path}")
    print(f"summary        : {json_path}")


if __name__ == "__main__":
    main()
