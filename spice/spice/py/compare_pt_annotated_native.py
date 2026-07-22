#!/usr/bin/env python3
"""Compare parsed PrimeTime annotated path JSON against native SPICE results.

The comparison basis is launch clock pin to endpoint D, matching the native
stage total that starts at the launch clock pin and ends at the endpoint pin.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


CLOCK_PINS = {"CK", "CLK", "CP", "G", "GN", "E", "EN"}

PATH_FIELDS = [
    "path_id",
    "status",
    "pt_ck_to_d_ps",
    "native_ck_to_d_ps",
    "delta_ps",
    "delta_pct",
    "pt_q_to_d_ps",
    "native_total_cell_ps",
    "native_total_net_ps",
    "stage_count",
    "input_slew_ps",
    "output_load_ff",
    "target_vdd",
    "target_temp",
    "failed_measures",
    "nodes",
    "elements",
    "peak_memory_mb",
    "pt_from_pin",
    "pt_to_pin",
    "path_key",
]

STAGE_FIELDS = [
    "path_id",
    "stage_idx",
    "pt_cell_ps",
    "native_cell_ps",
    "cell_delta_ps",
    "pt_net_ps",
    "native_net_ps",
    "net_delta_ps",
    "pt_stage_ps",
    "native_stage_ps",
    "stage_delta_ps",
    "pt_out_slew_ps",
    "native_out_slew_ps",
    "out_slew_delta_ps",
    "pt_cell_from",
    "pt_cell_to",
    "pt_net_to",
    "native_cell_from",
    "native_cell_to",
    "native_net_to",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare PT annotated timing against native SPICE summaries.")
    parser.add_argument("--batch-dir", required=True, type=Path, help="Native SPICE batch output directory.")
    parser.add_argument(
        "--annotated-json",
        required=True,
        type=Path,
        help="PT annotated timing JSON with arrival records.",
    )
    parser.add_argument("--path-compare-csv", type=Path, help="Default: batch-dir/pt_vs_native_path_compare.csv")
    parser.add_argument("--stage-compare-csv", type=Path, help="Default: batch-dir/pt_vs_native_stage_compare.csv")
    parser.add_argument("--report-rpt", type=Path, help="Default: batch-dir/pt_vs_native_compare.rpt")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"ERROR: missing CSV: {path}")
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SystemExit(f"ERROR: CSV has no header: {path}")
        return list(reader)


def canonical_id(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def pin_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in record.get("records", []) if row.get("kind") == "pin"]


def find_pt_pins(record: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int, int]:
    pins = pin_rows(record)
    startpoint = record.get("startpoint")
    endpoint = record.get("endpoint")
    launch_idx: int | None = None
    q_idx: int | None = None
    end_idx: int | None = None

    for idx, row in enumerate(pins):
        if row.get("inst") == startpoint and row.get("pin") in CLOCK_PINS:
            launch_idx = idx
        if q_idx is None and row.get("inst") == startpoint and row.get("pin") not in CLOCK_PINS:
            q_idx = idx
        if end_idx is None and row.get("inst") == endpoint:
            end_idx = idx

    if launch_idx is None or q_idx is None or end_idx is None:
        path_idx = record.get("path_idx")
        raise SystemExit(f"ERROR: could not locate launch/Q/endpoint pins for path {path_idx}")
    return pins, launch_idx, q_idx, end_idx


def build_pt_data(annotated_records: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    pt_paths: dict[str, dict[str, Any]] = {}
    pt_stages: dict[tuple[str, int], dict[str, Any]] = {}

    for record in annotated_records:
        path_id = canonical_id(record.get("path_idx"))
        pins, launch_idx, q_idx, end_idx = find_pt_pins(record)
        launch = pins[launch_idx]
        q_pin = pins[q_idx]
        endpoint_pin = pins[end_idx]

        pt_paths[path_id] = {
            "path_id": path_id,
            "path_key": record.get("path_key", ""),
            "from_pin": q_pin.get("point", ""),
            "to_pin": endpoint_pin.get("point", ""),
            "launch_ck_pin": launch.get("point", ""),
            "launch_ck_trans_ps": float(launch["trans_ns"]) * 1000.0,
            "launch_ck_path_ns": float(launch["path_ns"]),
            "start_q_path_ns": float(q_pin["path_ns"]),
            "endpoint_path_ns": float(endpoint_pin["path_ns"]),
            "pt_ck_to_d_ps": (float(endpoint_pin["path_ns"]) - float(launch["path_ns"])) * 1000.0,
            "pt_q_to_d_ps": (float(endpoint_pin["path_ns"]) - float(q_pin["path_ns"])) * 1000.0,
            "slack_ns": record.get("slack_ns"),
            "slack_status": record.get("slack_status"),
        }

        seq = [launch] + pins[q_idx : end_idx + 1]
        stage_idx = 1
        pos = 0
        while pos + 2 < len(seq):
            cell_in = seq[pos]
            cell_out = seq[pos + 1]
            net_to = seq[pos + 2]
            cell_ps = (float(cell_out["path_ns"]) - float(cell_in["path_ns"])) * 1000.0
            net_ps = (float(net_to["path_ns"]) - float(cell_out["path_ns"])) * 1000.0
            stage_ps = (float(net_to["path_ns"]) - float(cell_in["path_ns"])) * 1000.0
            pt_stages[(path_id, stage_idx)] = {
                "path_id": path_id,
                "stage_idx": stage_idx,
                "pt_cell_from": cell_in.get("point", ""),
                "pt_cell_to": cell_out.get("point", ""),
                "pt_net_from": cell_out.get("point", ""),
                "pt_net_to": net_to.get("point", ""),
                "pt_cell_ps": cell_ps,
                "pt_net_ps": net_ps,
                "pt_stage_ps": stage_ps,
                "pt_out_slew_ps": float(cell_out["trans_ns"]) * 1000.0,
            }
            stage_idx += 1
            pos += 2

    return pt_paths, pt_stages


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def build_path_rows(pt_paths: dict[str, dict[str, Any]], native_paths: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path_id in sorted(pt_paths, key=lambda item: int(item)):
        pt = pt_paths[path_id]
        native = native_paths.get(path_id)
        if native is None:
            continue
        pt_total = float(pt["pt_ck_to_d_ps"])
        native_total = to_float(native.get("total_path_ps"))
        delta = None if native_total is None else native_total - pt_total
        rows.append(
            {
                "path_id": path_id,
                "status": native.get("status", ""),
                "pt_ck_to_d_ps": fmt(pt_total),
                "native_ck_to_d_ps": fmt(native_total),
                "delta_ps": fmt(delta),
                "delta_pct": fmt(None if delta is None else delta / pt_total * 100.0),
                "pt_q_to_d_ps": fmt(float(pt["pt_q_to_d_ps"])),
                "native_total_cell_ps": fmt(to_float(native.get("total_cell_ps"))),
                "native_total_net_ps": fmt(to_float(native.get("total_net_ps"))),
                "stage_count": native.get("stage_count", ""),
                "input_slew_ps": native.get("input_slew_ps", ""),
                "output_load_ff": native.get("output_load_ff", ""),
                "target_vdd": native.get("target_vdd", ""),
                "target_temp": native.get("target_temp", ""),
                "failed_measures": native.get("failed_measures", ""),
                "nodes": native.get("nodes", ""),
                "elements": native.get("elements", ""),
                "peak_memory_mb": native.get("peak_memory_mb", ""),
                "pt_from_pin": pt.get("from_pin", ""),
                "pt_to_pin": pt.get("to_pin", ""),
                "path_key": pt.get("path_key", ""),
            }
        )
    return rows


def build_stage_rows(
    pt_stages: dict[tuple[str, int], dict[str, Any]],
    native_stages: dict[tuple[str, int], dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(pt_stages, key=lambda item: (int(item[0]), item[1])):
        pt = pt_stages[key]
        native = native_stages.get(key)
        if native is None:
            continue

        native_cell = to_float(native.get("cell_ps"))
        native_net = to_float(native.get("net_ps"))
        native_stage = to_float(native.get("stage_ps"))
        native_slew = to_float(native.get("out_slew_ps"))
        pt_cell = float(pt["pt_cell_ps"])
        pt_net = float(pt["pt_net_ps"])
        pt_stage = float(pt["pt_stage_ps"])
        pt_slew = float(pt["pt_out_slew_ps"])

        rows.append(
            {
                "path_id": key[0],
                "stage_idx": key[1],
                "pt_cell_ps": fmt(pt_cell),
                "native_cell_ps": fmt(native_cell),
                "cell_delta_ps": fmt(None if native_cell is None else native_cell - pt_cell),
                "pt_net_ps": fmt(pt_net),
                "native_net_ps": fmt(native_net),
                "net_delta_ps": fmt(None if native_net is None else native_net - pt_net),
                "pt_stage_ps": fmt(pt_stage),
                "native_stage_ps": fmt(native_stage),
                "stage_delta_ps": fmt(None if native_stage is None else native_stage - pt_stage),
                "pt_out_slew_ps": fmt(pt_slew),
                "native_out_slew_ps": fmt(native_slew),
                "out_slew_delta_ps": fmt(None if native_slew is None else native_slew - pt_slew),
                "pt_cell_from": pt.get("pt_cell_from", ""),
                "pt_cell_to": pt.get("pt_cell_to", ""),
                "pt_net_to": pt.get("pt_net_to", ""),
                "native_cell_from": native.get("cell_from", ""),
                "native_cell_to": native.get("cell_to", ""),
                "native_net_to": native.get("net_to", ""),
            }
        )
    return rows


def write_report(path: Path, path_rows: list[dict[str, Any]], batch_dir: Path) -> None:
    lines = [
        "PT annotated vs Native SPICE comparison",
        "Basis: PT launch CK -> endpoint D vs native stage total",
        "",
        f"{'Path':>4}  {'PT CK->D(ps)':>12}  {'Native(ps)':>10}  {'Delta(ps)':>9}  {'Delta(%)':>8}  {'Status':<6}  {'Failed':>6}",
        f"{'----':>4}  {'------------':>12}  {'----------':>10}  {'---------':>9}  {'--------':>8}  {'------':<6}  {'------':>6}",
    ]
    for row in path_rows:
        lines.append(
            f"{row['path_id']:>4}  {row['pt_ck_to_d_ps']:>12}  {row['native_ck_to_d_ps']:>10}  "
            f"{row['delta_ps']:>9}  {row['delta_pct']:>8}  {row['status']:<6}  {row['failed_measures']:>6}"
        )
    lines.extend(
        [
            "",
            "Generated files:",
            str(batch_dir / "pt_vs_native_path_compare.csv"),
            str(batch_dir / "pt_vs_native_stage_compare.csv"),
            str(batch_dir / "native_timing_report.rpt"),
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    batch_dir = args.batch_dir.resolve()
    if not batch_dir.is_dir():
        raise SystemExit(f"ERROR: missing batch dir: {batch_dir}")

    annotated_records = json.loads(args.annotated_json.read_text())
    if not isinstance(annotated_records, list):
        raise SystemExit(f"ERROR: annotated JSON root must be a list: {args.annotated_json}")

    path_summary = batch_dir / "native_path_summary.csv"
    stage_compact = batch_dir / "native_stage_compact.csv"
    native_paths = {canonical_id(row.get("path_id")): row for row in read_csv(path_summary)}
    native_stages = {
        (canonical_id(row.get("path_id")), int(float(row["stage_idx"]))): row
        for row in read_csv(stage_compact)
        if row.get("path_id") and row.get("stage_idx")
    }

    pt_paths, pt_stages = build_pt_data(annotated_records)
    path_rows = build_path_rows(pt_paths, native_paths)
    stage_rows = build_stage_rows(pt_stages, native_stages)

    path_compare = args.path_compare_csv or (batch_dir / "pt_vs_native_path_compare.csv")
    stage_compare = args.stage_compare_csv or (batch_dir / "pt_vs_native_stage_compare.csv")
    report = args.report_rpt or (batch_dir / "pt_vs_native_compare.rpt")

    write_csv(path_compare, PATH_FIELDS, path_rows)
    write_csv(stage_compare, STAGE_FIELDS, stage_rows)
    write_report(report, path_rows, batch_dir)

    print(f"report_rpt={report}")
    print(f"path_compare_csv={path_compare}")
    print(f"stage_compare_csv={stage_compare}")
    print(f"paths={len(path_rows)} stages={len(stage_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
