#!/usr/bin/env python3
"""Compare a PrimeTime scaling fixed-path report with target-corner ground truth."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+)\s+key=(.*)$")
SLACK_RE = re.compile(
    r"^\s*slack\s+\((?:MET|VIOLATED)[^)]*\)\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
TO_PS = {"s": 1.0e12, "ms": 1.0e9, "us": 1.0e6,
         "ns": 1.0e3, "ps": 1.0, "fs": 1.0e-3}


@dataclass(frozen=True)
class PathResult:
    idx: int
    key: str
    slack: float | None


def parse_report(path: Path) -> dict[str, PathResult]:
    """Read ### FIXED_PATH blocks and the slack in each successfully measured block."""
    results: dict[str, PathResult] = {}
    current_idx: int | None = None
    current_key: str | None = None
    current_slack: float | None = None

    def finish() -> None:
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


def evaluate(scaled: dict[str, PathResult], truth: dict[str, PathResult], factor: float) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    errors: list[float] = []
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


def write_csv(path: Path, rows: list[dict]) -> None:
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


def main() -> None:
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
