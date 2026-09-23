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
      pt_scaling_comparison/SSPG_0p57V_25C_RCMAX_setup/path_errors.txt
      pt_scaling_comparison/SSPG_0p57V_25C_RCMAX_setup/summary.txt
      pt_scaling_comparison/SSPG_0p57V_25C_RCMAX_setup/summary.json

    Existing results are never overwritten. Running the same corner again
    creates SSPG_0p57V_25C_RCMAX_setup_run2, then _run3, and so on.

    To select another result directory, add:
      --output-dir results/TARGET

    The selected directory is the common root for all corner result folders.

VIEW WITHOUT VS CODE
    cat pt_scaling_comparison/TARGET/summary.txt
    less -S pt_scaling_comparison/TARGET/path_errors.txt

RUNTIME
    Python 3.6 or newer. No external Python package is required.
"""

import argparse
import json
import math
import re
from pathlib import Path


PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+)\s+key=(.*)$")
SLACK_RE = re.compile(
    r"^\s*slack\s+\((?:MET|VIOLATED)[^)]*\)\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
ARRIVAL_RE = re.compile(
    r"^\s*data arrival time\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)
REQUIRED_RE = re.compile(
    r"^\s*data required time\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)
NS_TO_PS = 1000.0


class PathResult(object):
    """One fixed-path result; kept simple for Synopsys Python 3.6."""

    __slots__ = ("idx", "key", "slack", "arrival", "required")

    def __init__(self, idx, key, slack, arrival=None, required=None):
        self.idx = idx
        self.key = key
        self.slack = slack
        self.arrival = arrival
        self.required = required


def parse_report(path):
    """Read ### FIXED_PATH blocks and the slack in each successfully measured block."""
    results = {}
    current_idx = None
    current_key = None
    current_slack = None
    current_arrival = None
    current_required = None

    def finish():
        nonlocal current_idx, current_key, current_slack
        nonlocal current_arrival, current_required
        if current_key is None or current_idx is None:
            return
        if current_key in results:
            raise ValueError(f"duplicate path key in {path}: {current_key}")
        results[current_key] = PathResult(
            current_idx, current_key, current_slack,
            current_arrival, current_required)

    with path.open(errors="ignore") as report:
        for line in report:
            match = PATH_RE.match(line.rstrip("\n"))
            if match:
                finish()
                current_idx = int(match.group(1))
                current_key = match.group(2).strip()
                current_slack = None
                current_arrival = None
                current_required = None
                continue
            if current_key is not None:
                match = SLACK_RE.match(line)
                if match:
                    current_slack = float(match.group(1))
                    continue
                match = ARRIVAL_RE.match(line)
                if match:
                    current_arrival = float(match.group(1))
                    continue
                match = REQUIRED_RE.match(line)
                if match:
                    current_required = float(match.group(1))
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
        pred_arrival_ps = (
            None if pred is None or pred.arrival is None else pred.arrival * factor)
        truth_arrival_ps = (
            None if gt is None or gt.arrival is None else gt.arrival * factor)
        pred_required_ps = (
            None if pred is None or pred.required is None else pred.required * factor)
        truth_required_ps = (
            None if gt is None or gt.required is None else gt.required * factor)
        arrival_error = (
            None if pred_arrival_ps is None or truth_arrival_ps is None
            else pred_arrival_ps - truth_arrival_ps)
        required_error = (
            None if pred_required_ps is None or truth_required_ps is None
            else pred_required_ps - truth_required_ps)
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
            "ground_truth_arrival_ps": truth_arrival_ps,
            "pt_scaling_arrival_ps": pred_arrival_ps,
            "arrival_error_ps": arrival_error,
            "ground_truth_required_ps": truth_required_ps,
            "pt_scaling_required_ps": pred_required_ps,
            "required_error_ps": required_error,
            "status": status,
        })

    if not errors:
        raise ValueError("no path has a resolved slack in both reports")
    abs_errors = [abs(value) for value in errors]
    compared_rows = [row for row in rows if row["abs_error_ps"] is not None]
    worst_row = max(compared_rows, key=lambda row: row["abs_error_ps"])
    arrival_errors = [
        row["arrival_error_ps"] for row in compared_rows
        if row["arrival_error_ps"] is not None]
    required_errors = [
        row["required_error_ps"] for row in compared_rows
        if row["required_error_ps"] is not None]
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
    for name, values in (("arrival", arrival_errors), ("required", required_errors)):
        summary[f"{name}_compared_paths"] = len(values)
        summary[f"{name}_mae_ps"] = (
            sum(abs(value) for value in values) / len(values) if values else None)
        summary[f"{name}_bias_ps"] = (
            sum(values) / len(values) if values else None)
    return rows, summary


def format_number(value):
    return "-" if value is None else f"{value:.6f}"


def write_path_text(path, rows):
    """Write paths by descending absolute error; unresolved paths come last."""
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            row["abs_error_ps"] is None,
            -(row["abs_error_ps"] or 0.0),
            row["path_key"],
        ),
    )
    with path.open("w") as output:
        output.write("# Input slack unit: ns; all values below: ps\n")
        output.write("# Order: abs_error descending; unresolved/missing paths last\n")
        output.write(
            f"{'idx':>7} {'gt_slack':>15} {'pt_slack':>15} "
            f"{'slack_err':>15} {'abs_err':>15} "
            f"{'arrival_err':>13} {'required_err':>13} "
            f"{'status':<29} path_key\n"
        )
        for row in ordered_rows:
            output.write(
                f"{row['idx']:>7} "
                f"{format_number(row['ground_truth_ps']):>15} "
                f"{format_number(row['pt_scaling_ps']):>15} "
                f"{format_number(row['pt_scaling_err_ps']):>15} "
                f"{format_number(row['abs_error_ps']):>15} "
                f"{format_number(row['arrival_error_ps']):>13} "
                f"{format_number(row['required_error_ps']):>13} "
                f"{row['status']:<29} {row['path_key']}\n"
            )


def write_summary_text(path, summary):
    """Write the complete metric summary as plain text for a Linux terminal."""
    lines = [
        "PrimeTime scaling vs ground truth",
        f"scaled report       : {summary['scaled_report']}",
        f"ground truth report : {summary['ground_truth_report']}",
        f"input/output unit   : {summary['input_unit']} / {summary['output_unit']}",
        f"scaled blocks       : {summary['scaled_blocks']}",
        f"scaled resolved     : {summary['scaled_resolved']}",
        f"ground truth blocks : {summary['ground_truth_blocks']}",
        f"ground truth resolved: {summary['ground_truth_resolved']}",
        f"shared path keys    : {summary['shared_path_keys']}",
        f"compared paths      : {summary['compared_paths']}",
        f"excluded paths      : {summary['excluded_paths']}",
        f"MAE                 : {summary['mae_ps']:.6f} ps",
        f"RMSE                : {summary['rmse_ps']:.6f} ps",
        f"bias                : {summary['bias_ps']:+.6f} ps",
        f"worst absolute error: {summary['worst_abs_error_ps']:.6f} ps",
        f"worst path key      : {summary['worst_path_key']}",
        component_line("arrival", summary),
        component_line("required", summary),
        "status counts:",
    ]
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"  {status:<29} {count}")
    if summary.get("scaling_input_plan"):
        lines.extend([
            "",
            "Scaling inputs used by PrimeTime",
            summary["scaling_input_plan"].rstrip("\n"),
        ])
    else:
        lines.extend([
            "",
            "Scaling inputs used by PrimeTime",
            "unavailable: adjacent <scaled-report>.inputs.txt was not found",
        ])
    path.write_text("\n".join(lines) + "\n")


def component_line(name, summary):
    """Format arrival/required diagnostics when both reports contain them."""
    count = summary[f"{name}_compared_paths"]
    mae = summary[f"{name}_mae_ps"]
    bias = summary[f"{name}_bias_ps"]
    if not count:
        return f"{name + ' diagnostic':<21}: unavailable in timing report"
    return (
        f"{name + ' diagnostic':<21}: paths={count} "
        f"MAE={mae:.6f} ps bias={bias:+.6f} ps")


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
    scaling_inputs_path = Path(str(args.scaled_rpt) + ".inputs.txt")
    if scaling_inputs_path.is_file():
        summary["scaling_input_plan_path"] = str(scaling_inputs_path.resolve())
        summary["scaling_input_plan"] = scaling_inputs_path.read_text(errors="ignore")
    else:
        summary["scaling_input_plan_path"] = None
        summary["scaling_input_plan"] = None

    corner_name = safe_corner_name(args.ground_truth_rpt)
    result_dir = create_result_dir(args.output_dir, corner_name)
    path_text_path = result_dir / "path_errors.txt"
    summary_text_path = result_dir / "summary.txt"
    json_path = result_dir / "summary.json"
    write_path_text(path_text_path, rows)
    write_summary_text(summary_text_path, summary)
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
    print(component_line("arrival", summary))
    print(component_line("required", summary))
    if summary["scaling_input_plan_path"]:
        print(f"scaling inputs : {summary['scaling_input_plan_path']}")
    else:
        print("scaling inputs : unavailable (older scaling report)")
    print("worst paths    :")
    compared_rows = [row for row in rows if row["abs_error_ps"] is not None]
    for rank, row in enumerate(
            sorted(compared_rows, key=lambda item: item["abs_error_ps"], reverse=True)[:10], 1):
        print(
            f"  {rank:>2}. idx={row['idx']} abs={row['abs_error_ps']:.3f} ps "
            f"err={row['pt_scaling_err_ps']:+.3f} ps key={row['path_key']}"
        )
    print(f"path details   : {path_text_path}")
    print(f"summary text   : {summary_text_path}")
    print(f"summary JSON   : {json_path}")


if __name__ == "__main__":
    main()
