#!/usr/bin/env python3
"""Fast SI-on/SI-off fixed-path arrival comparison.

This intentionally avoids full arc parsing.  It checks fixed-path key stability
and compares arrival/slack values for the same FIXED_PATH index.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
from pathlib import Path

MARKER_RE = re.compile(r"^### FIXED_PATH idx=(?P<idx>\d+) key=(?P<key>.*)$")
VOLT_RE = re.compile(r"tt0p(?P<tag>[0-9]+)v(?:m?\d+)c")
FLOAT_RE = re.compile(r"[-+]?\d+\.\d+")


def voltage_from_name(name: str) -> float:
    if "tt0p8v25c_ccs_vendor" in name:
        return 0.800
    match = VOLT_RE.search(name)
    if not match:
        raise ValueError(f"Cannot parse voltage from {name}")
    return float("0." + match.group("tag"))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    rank = (len(vals) - 1) * pct / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (rank - lo)


def report_map(report_dir: Path) -> dict[float, Path]:
    reports = sorted(report_dir.glob("*_fixed.rpt"), key=lambda p: voltage_from_name(p.name))
    if not reports:
        raise SystemExit(f"no *_fixed.rpt files under {report_dir}")
    return {voltage_from_name(path.name): path for path in reports}


def parse_report_values(path: Path) -> dict[int, dict[str, object]]:
    rows: dict[int, dict[str, object]] = {}
    cur: dict[str, object] | None = None

    def finish() -> None:
        if cur is not None:
            rows[int(cur["idx"])] = dict(cur)

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            match = MARKER_RE.match(line)
            if match:
                finish()
                cur = {
                    "idx": int(match.group("idx")),
                    "key": match.group("key"),
                    "arrival": None,
                    "slack": None,
                }
                continue
            if cur is None:
                continue
            if "data arrival time" in line and cur["arrival"] is None:
                nums = FLOAT_RE.findall(line)
                if nums:
                    cur["arrival"] = float(nums[-1])
                continue
            if "slack" in line:
                nums = FLOAT_RE.findall(line)
                if nums:
                    cur["slack"] = float(nums[-1])
    finish()
    return rows


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def stat(vals: list[float], fn, default: float = float("nan")) -> float:
    return fn(vals) if vals else default


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--si-reports-dir", required=True, type=Path)
    parser.add_argument("--sioff-reports-dir", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--mode", choices=["setup", "hold"], required=True)
    parser.add_argument("--temp-label", required=True)
    parser.add_argument("--rc", required=True)
    parser.add_argument("--suspicious-ps", type=float, default=200.0)
    parser.add_argument("--hard-fail-ps", type=float, default=1000.0)
    parser.add_argument("--top-n", type=int, default=50)
    args = parser.parse_args()

    si_reports = report_map(args.si_reports_dir)
    sioff_reports = report_map(args.sioff_reports_dir)
    voltages = sorted(set(si_reports) | set(sioff_reports))

    detail_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for voltage in voltages:
        si_path = si_reports.get(voltage)
        sioff_path = sioff_reports.get(voltage)
        si_data = parse_report_values(si_path) if si_path else {}
        sioff_data = parse_report_values(sioff_path) if sioff_path else {}
        path_ids = sorted(set(si_data) | set(sioff_data))
        voltage_rows: list[dict[str, object]] = []

        for path_id in path_ids:
            si = si_data.get(path_id)
            sioff = sioff_data.get(path_id)
            comparable = (
                si is not None
                and sioff is not None
                and si.get("arrival") is not None
                and sioff.get("arrival") is not None
            )
            key_mismatch = bool(si and sioff and si.get("key") != sioff.get("key"))
            arrival_delta_ps = ""
            slack_delta_ps = ""
            if comparable:
                arrival_delta_ps = (float(si["arrival"]) - float(sioff["arrival"])) * 1000.0
                if si.get("slack") is not None and sioff.get("slack") is not None:
                    slack_delta_ps = (float(si["slack"]) - float(sioff["slack"])) * 1000.0
            row = {
                "mode": args.mode,
                "temp": args.temp_label,
                "rc": args.rc,
                "voltage": f"{voltage:.3f}",
                "path_id": path_id,
                "path_key": (si or sioff or {}).get("key", ""),
                "arrival_sion_ns": si.get("arrival", "") if si else "",
                "arrival_sioff_ns": sioff.get("arrival", "") if sioff else "",
                "arrival_si_minus_sioff_ps": arrival_delta_ps,
                "slack_sion_ns": si.get("slack", "") if si else "",
                "slack_sioff_ns": sioff.get("slack", "") if sioff else "",
                "slack_si_minus_sioff_ps": slack_delta_ps,
                "comparable": int(comparable),
                "missing_si": int(si is None),
                "missing_sioff": int(sioff is None),
                "path_key_mismatch": int(key_mismatch),
                "si_report": si_path.name if si_path else "",
                "sioff_report": sioff_path.name if sioff_path else "",
            }
            detail_rows.append(row)
            voltage_rows.append(row)

        arrival = [
            float(row["arrival_si_minus_sioff_ps"])
            for row in voltage_rows
            if row["comparable"]
        ]
        slack = [
            float(row["slack_si_minus_sioff_ps"])
            for row in voltage_rows
            if row["comparable"] and row["slack_si_minus_sioff_ps"] != ""
        ]
        abs_arrival = [abs(value) for value in arrival]
        summary_rows.append(
            {
                "voltage": f"{voltage:.3f}",
                "path_count": len(voltage_rows),
                "comparable_path_count": len(arrival),
                "path_key_mismatch_count": sum(1 for row in voltage_rows if row["path_key_mismatch"]),
                "missing_si_count": sum(1 for row in voltage_rows if row["missing_si"]),
                "missing_sioff_count": sum(1 for row in voltage_rows if row["missing_sioff"]),
                "arrival_delta_mean_ps": stat(arrival, statistics.mean),
                "arrival_delta_p50_ps": percentile(arrival, 50),
                "arrival_delta_p95_ps": percentile(arrival, 95),
                "arrival_delta_p99_ps": percentile(arrival, 99),
                "arrival_delta_min_ps": stat(arrival, min),
                "arrival_delta_max_ps": stat(arrival, max),
                "abs_arrival_delta_p99_ps": percentile(abs_arrival, 99),
                "abs_arrival_delta_max_ps": stat(abs_arrival, max),
                "suspicious_abs_delta_count": sum(1 for value in abs_arrival if value >= args.suspicious_ps),
                "hard_fail_abs_delta_count": sum(1 for value in abs_arrival if value >= args.hard_fail_ps),
                "slack_delta_mean_ps": stat(slack, statistics.mean),
                "slack_delta_min_ps": stat(slack, min),
                "slack_delta_max_ps": stat(slack, max),
            }
        )

    detail_fields = [
        "mode",
        "temp",
        "rc",
        "voltage",
        "path_id",
        "path_key",
        "arrival_sion_ns",
        "arrival_sioff_ns",
        "arrival_si_minus_sioff_ps",
        "slack_sion_ns",
        "slack_sioff_ns",
        "slack_si_minus_sioff_ps",
        "comparable",
        "missing_si",
        "missing_sioff",
        "path_key_mismatch",
        "si_report",
        "sioff_report",
    ]
    summary_fields = [
        "voltage",
        "path_count",
        "comparable_path_count",
        "path_key_mismatch_count",
        "missing_si_count",
        "missing_sioff_count",
        "arrival_delta_mean_ps",
        "arrival_delta_p50_ps",
        "arrival_delta_p95_ps",
        "arrival_delta_p99_ps",
        "arrival_delta_min_ps",
        "arrival_delta_max_ps",
        "abs_arrival_delta_p99_ps",
        "abs_arrival_delta_max_ps",
        "suspicious_abs_delta_count",
        "hard_fail_abs_delta_count",
        "slack_delta_mean_ps",
        "slack_delta_min_ps",
        "slack_delta_max_ps",
    ]
    write_csv(args.outdir / "si_vs_sioff_path_delta_fast.csv", detail_rows, detail_fields)
    write_csv(args.outdir / "si_vs_sioff_voltage_summary_fast.csv", summary_rows, summary_fields)

    comparable_rows = [row for row in detail_rows if row["comparable"]]
    top_rows = sorted(
        comparable_rows,
        key=lambda row: abs(float(row["arrival_si_minus_sioff_ps"])),
        reverse=True,
    )[: args.top_n]
    write_csv(args.outdir / "top_abs_arrival_delta_paths_fast.csv", top_rows, detail_fields)

    hard_fails = sum(int(row["hard_fail_abs_delta_count"]) for row in summary_rows)
    suspicious = sum(int(row["suspicious_abs_delta_count"]) for row in summary_rows)
    key_mismatch = sum(int(row["path_key_mismatch_count"]) for row in summary_rows)
    missing = sum(int(row["missing_si_count"]) + int(row["missing_sioff_count"]) for row in summary_rows)
    max_abs = max((float(row["abs_arrival_delta_max_ps"]) for row in summary_rows), default=float("nan"))

    with (args.outdir / "summary_fast.md").open("w", encoding="utf-8") as handle:
        handle.write("# Fast SI-On Vs SI-Off Value Sanity\n\n")
        handle.write(f"- mode: {args.mode}\n")
        handle.write(f"- temp: {args.temp_label}\n")
        handle.write(f"- rc: {args.rc}\n")
        handle.write(f"- voltages: {len(summary_rows)}\n")
        handle.write(f"- total_paths_compared: {len(comparable_rows)}\n")
        handle.write(f"- missing_records: {missing}\n")
        handle.write(f"- path_key_mismatch_records: {key_mismatch}\n")
        handle.write(f"- suspicious_abs_delta_count_ge_{args.suspicious_ps:g}ps: {suspicious}\n")
        handle.write(f"- hard_fail_abs_delta_count_ge_{args.hard_fail_ps:g}ps: {hard_fails}\n")
        handle.write(f"- max_abs_arrival_delta_ps: {max_abs}\n")
        handle.write("\n## Interpretation\n\n")
        handle.write("- This is a fixed-path value comparison, not a voltage monotonic check.\n")
        handle.write("- It compares SI-on arrival/slack against matching SI-off reports for identical fixed-path indices and keys.\n")

    print(f"SUMMARY={args.outdir / 'summary_fast.md'}")
    print(f"hard_fail_abs_delta_count={hard_fails}")
    print(f"suspicious_abs_delta_count={suspicious}")
    print(f"path_key_mismatch_records={key_mismatch}")
    print(f"missing_records={missing}")
    print(f"max_abs_arrival_delta_ps={max_abs}")


if __name__ == "__main__":
    main()
