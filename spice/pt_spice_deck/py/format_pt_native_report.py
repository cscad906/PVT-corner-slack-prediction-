#!/usr/bin/env python3
"""Format PrimeTime native SPICE parser outputs into readable reports.

The parser output is intentionally verbose for traceability.  This formatter
builds a compact stage table for humans while keeping full node names and
measure names in CSV outputs for follow-up analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any


PATH_DIR_RE = re.compile(r"^path_(\d+)$")


PATH_SUMMARY_FIELDS = [
    "path_id",
    "fixed_index",
    "path",
    "status",
    "from_pin",
    "to_pin",
    "path_key",
    "target_vdd",
    "target_temp",
    "input_slew_ps",
    "output_load_ff",
    "stage_count",
    "total_cell_ps",
    "total_net_ps",
    "total_path_ps",
    "failed_measures",
    "unknown_delay_count",
    "pt_ok",
    "patch_ok",
    "hspice_ok",
    "nodes",
    "elements",
    "peak_memory_mb",
    "total_cpu_sec",
    "total_elapsed_sec",
    "path_dir",
]


STAGE_FIELDS = [
    "path_id",
    "fixed_index",
    "path",
    "status",
    "stage_idx",
    "cell_from",
    "cell_to",
    "cell_arc",
    "net_from",
    "net_to",
    "net_arc",
    "stage_from",
    "stage_to",
    "stage_arc",
    "cell_ps",
    "net_ps",
    "stage_ps",
    "in_slew_ps",
    "out_slew_ps",
    "cell_measure",
    "net_measure",
    "stage_measure",
    "in_slew_measure",
    "out_slew_measure",
    "cell_confidence",
    "net_confidence",
    "stage_confidence",
    "target_vdd",
    "target_temp",
    "input_slew_ps",
    "output_load_ff",
    "path_key",
    "pt_from_pin",
    "pt_to_pin",
    "hspice_nodes",
    "hspice_elements",
    "hspice_peak_memory_mb",
    "path_dir",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create PT-style native SPICE timing reports from native_delay_breakdown.csv."
    )
    parser.add_argument("--batch-dir", required=True, type=Path, help="Batch output directory.")
    parser.add_argument(
        "--breakdown-csv",
        type=Path,
        help="Input native_delay_breakdown.csv. Default: batch-dir/native_delay_breakdown.csv",
    )
    parser.add_argument(
        "--batch-summary-csv",
        type=Path,
        help="Input batch_summary.csv. Default: batch-dir/batch_summary.csv",
    )
    parser.add_argument(
        "--report-rpt",
        type=Path,
        help="Output readable report. Default: batch-dir/native_timing_report.rpt",
    )
    parser.add_argument(
        "--stage-csv",
        type=Path,
        help="Output compact stage CSV. Default: batch-dir/native_stage_compact.csv",
    )
    parser.add_argument(
        "--path-summary-csv",
        type=Path,
        help="Output path summary CSV. Default: batch-dir/native_path_summary.csv",
    )
    parser.add_argument(
        "--name-width",
        type=int,
        default=54,
        help="Maximum arc text width in the human-readable report.",
    )
    parser.add_argument("--fail-on-missing", action="store_true", help="Exit non-zero if optional inputs are missing.")
    return parser.parse_args()


def read_csv(path: Path, label: str, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise SystemExit(f"ERROR: missing {label}: {path}")
        return []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SystemExit(f"ERROR: {label} has no header: {path}")
        return list(reader)


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def canonical_path_id(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if text == "":
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return text


def path_sort_key(path_id: str) -> tuple[int, int | str]:
    try:
        return (0, int(path_id))
    except ValueError:
        return (1, path_id)


def path_dir_index(path_dir: Path) -> str:
    match = PATH_DIR_RE.match(path_dir.name)
    return str(int(match.group(1))) if match else ""


def nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def pick(*values: Any) -> Any:
    for value in values:
        if nonempty(value):
            return value
    return ""


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan", "n/a", "failed", "fail"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    if number is None:
        return None
    return int(number)


def is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok", "pass"}


def fmt_number(value: Any, digits: int = 6) -> str:
    number = to_float(value)
    if number is None:
        return ""
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def fmt_fixed(value: Any, digits: int = 2) -> str:
    number = to_float(value)
    if number is None:
        return "NA"
    return f"{number:.{digits}f}"


def fmt_count(value: Any) -> str:
    number = to_int(value)
    return "NA" if number is None else str(number)


def arc_text(from_node: Any, to_node: Any) -> str:
    if not nonempty(from_node) and not nonempty(to_node):
        return ""
    return f"{from_node} -> {to_node}"


def shorten_middle(text: Any, width: int) -> str:
    text = str(text if text is not None else "")
    if width <= 3 or len(text) <= width:
        return text
    keep = width - 3
    left = keep // 2
    right = keep - left
    return text[:left] + "..." + text[-right:]


def status_ok_text(value: Any) -> str:
    if str(value).strip() == "":
        return "NA"
    return "OK" if is_true(value) else "FAIL"


def load_statuses(batch_dir: Path) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for child in sorted(batch_dir.iterdir()):
        if not child.is_dir():
            continue
        path_id = path_dir_index(child)
        if not path_id:
            continue
        status = read_json(child / "status.json")
        if status:
            statuses[path_id] = status
    return statuses


def load_batch_summary(path: Path, *, required: bool) -> dict[str, dict[str, str]]:
    rows = read_csv(path, "batch summary CSV", required=required)
    summary: dict[str, dict[str, str]] = {}
    for row in rows:
        path_id = canonical_path_id(row.get("path_id"))
        if path_id:
            summary[path_id] = row
    return summary


def status_nested(status: dict[str, Any], *keys: str) -> Any:
    value: Any = status
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value


def first_row_value(rows: list[dict[str, str]], key: str) -> str:
    for row in rows:
        value = row.get(key, "")
        if nonempty(value):
            return value
    return ""


def path_metadata(
    path_id: str,
    rows: list[dict[str, str]],
    summary: dict[str, str],
    status: dict[str, Any],
) -> dict[str, Any]:
    hspice_scan = status_nested(status, "hspice", "scan")
    hspice_scan = hspice_scan if isinstance(hspice_scan, dict) else {}
    pt_path = status.get("pt_path") if isinstance(status.get("pt_path"), dict) else {}
    return {
        "path_id": pick(summary.get("path_id"), status.get("path_id"), first_row_value(rows, "path_id"), path_id),
        "fixed_index": pick(summary.get("fixed_index"), status.get("fixed_index"), first_row_value(rows, "fixed_index")),
        "path": pick(first_row_value(rows, "path"), status.get("basename"), f"path_{int(path_id):06d}" if path_id.isdigit() else path_id),
        "status": pick(summary.get("status"), status.get("status"), first_row_value(rows, "status")),
        "from_pin": pick(summary.get("from_pin"), pt_path.get("from_pin"), first_row_value(rows, "pt_from_pin")),
        "to_pin": pick(summary.get("to_pin"), pt_path.get("to_pin"), first_row_value(rows, "pt_to_pin")),
        "path_key": pick(summary.get("path_key"), pt_path.get("path_key"), first_row_value(rows, "path_key")),
        "target_vdd": pick(summary.get("target_vdd"), status.get("target_vdd"), first_row_value(rows, "target_vdd")),
        "target_temp": pick(summary.get("target_temp"), status.get("target_temp"), first_row_value(rows, "target_temp")),
        "input_slew_ps": pick(summary.get("input_slew_ps"), status.get("input_slew_ps"), first_row_value(rows, "input_slew_ps")),
        "output_load_ff": pick(summary.get("output_load_ff"), status.get("output_load_ff"), first_row_value(rows, "output_load_ff")),
        "failed_measures": pick(summary.get("measure_failed_count"), status_nested(status, "hspice", "measure_failed_count")),
        "pt_ok": pick(summary.get("pt_ok"), status_nested(status, "prime_time", "ok")),
        "patch_ok": pick(summary.get("patch_ok"), status_nested(status, "patch", "ok")),
        "hspice_ok": pick(summary.get("hspice_ok"), status_nested(status, "hspice", "ok")),
        "nodes": pick(summary.get("nodes"), hspice_scan.get("nodes"), first_row_value(rows, "hspice_nodes")),
        "elements": pick(summary.get("elements"), hspice_scan.get("elements"), first_row_value(rows, "hspice_elements")),
        "peak_memory_mb": pick(summary.get("peak_memory_mb"), hspice_scan.get("peak_memory_mb"), first_row_value(rows, "hspice_peak_memory_mb")),
        "total_cpu_sec": pick(summary.get("total_cpu_sec"), hspice_scan.get("total_cpu_sec")),
        "total_elapsed_sec": pick(summary.get("total_elapsed_sec"), hspice_scan.get("total_elapsed_sec")),
        "path_dir": pick(summary.get("path_dir"), status.get("path_dir"), first_row_value(rows, "path_dir")),
    }


def stage_index_key(stage_idx: Any) -> tuple[int, int | str]:
    text = str(stage_idx).strip()
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def row_value_ps(row: dict[str, str] | None) -> float | None:
    if row is None or is_true(row.get("is_failed")):
        return None
    return to_float(row.get("value_ps"))


def stage_component_rows(rows: list[dict[str, str]]) -> list[dict[str, dict[str, str]]]:
    stages: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    slew_by_node: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("kind", "") == "slew":
            node = row.get("node", "")
            if node and node not in slew_by_node:
                slew_by_node[node] = row

        stage_idx = str(row.get("stage_idx", "")).strip()
        if not stage_idx:
            continue
        kind = row.get("kind", "")
        stage = stages[stage_idx]
        if kind == "cell_delay" and "cell" not in stage:
            stage["cell"] = row
        elif kind == "net_delay" and "net" not in stage:
            stage["net"] = row
        elif kind == "stage_or_cumulative_delay" and "stage" not in stage:
            stage["stage"] = row
        elif kind == "slew":
            role = row.get("node_pin_role", "")
            if role == "input" and "in_slew" not in stage:
                stage["in_slew"] = row
            elif role == "output" and "out_slew" not in stage:
                stage["out_slew"] = row

    result: list[dict[str, dict[str, str]]] = []
    for stage_idx in sorted(stages, key=stage_index_key):
        stage = dict(stages[stage_idx])
        cell = stage.get("cell") or {}
        cell_from = cell.get("from_node", "")
        cell_to = cell.get("to_node", "")
        if cell_from in slew_by_node:
            stage["in_slew"] = slew_by_node[cell_from]
        if cell_to in slew_by_node:
            stage["out_slew"] = slew_by_node[cell_to]
        stage["_stage_idx"] = {"stage_idx": stage_idx}
        result.append(stage)
    return result


def compact_stage_record(meta: dict[str, Any], stage: dict[str, dict[str, str]]) -> dict[str, Any]:
    cell = stage.get("cell") or {}
    net = stage.get("net") or {}
    stage_delay = stage.get("stage") or {}
    in_slew = stage.get("in_slew") or {}
    out_slew = stage.get("out_slew") or {}
    stage_idx = (stage.get("_stage_idx") or {}).get("stage_idx", "")
    return {
        "path_id": meta["path_id"],
        "fixed_index": meta["fixed_index"],
        "path": meta["path"],
        "status": meta["status"],
        "stage_idx": stage_idx,
        "cell_from": cell.get("from_node", ""),
        "cell_to": cell.get("to_node", ""),
        "cell_arc": arc_text(cell.get("from_node", ""), cell.get("to_node", "")),
        "net_from": net.get("from_node", ""),
        "net_to": net.get("to_node", ""),
        "net_arc": arc_text(net.get("from_node", ""), net.get("to_node", "")),
        "stage_from": stage_delay.get("from_node", ""),
        "stage_to": stage_delay.get("to_node", ""),
        "stage_arc": arc_text(stage_delay.get("from_node", ""), stage_delay.get("to_node", "")),
        "cell_ps": fmt_number(row_value_ps(cell)),
        "net_ps": fmt_number(row_value_ps(net)),
        "stage_ps": fmt_number(row_value_ps(stage_delay)),
        "in_slew_ps": fmt_number(row_value_ps(in_slew)),
        "out_slew_ps": fmt_number(row_value_ps(out_slew)),
        "cell_measure": cell.get("measure_name", ""),
        "net_measure": net.get("measure_name", ""),
        "stage_measure": stage_delay.get("measure_name", ""),
        "in_slew_measure": in_slew.get("measure_name", ""),
        "out_slew_measure": out_slew.get("measure_name", ""),
        "cell_confidence": cell.get("classification_confidence", ""),
        "net_confidence": net.get("classification_confidence", ""),
        "stage_confidence": stage_delay.get("classification_confidence", ""),
        "target_vdd": meta["target_vdd"],
        "target_temp": meta["target_temp"],
        "input_slew_ps": meta["input_slew_ps"],
        "output_load_ff": meta["output_load_ff"],
        "path_key": meta["path_key"],
        "pt_from_pin": meta["from_pin"],
        "pt_to_pin": meta["to_pin"],
        "hspice_nodes": meta["nodes"],
        "hspice_elements": meta["elements"],
        "hspice_peak_memory_mb": meta["peak_memory_mb"],
        "path_dir": meta["path_dir"],
    }


def sum_stage_column(rows: list[dict[str, Any]], key: str) -> float:
    total = 0.0
    for row in rows:
        value = to_float(row.get(key))
        if value is not None:
            total += value
    return total


def path_summary_record(meta: dict[str, Any], stage_rows: list[dict[str, Any]], source_rows: list[dict[str, str]]) -> dict[str, Any]:
    total_cell = sum_stage_column(stage_rows, "cell_ps")
    total_net = sum_stage_column(stage_rows, "net_ps")
    total_stage = sum_stage_column(stage_rows, "stage_ps")
    total_path = total_stage if total_stage else total_cell + total_net
    failed = to_int(meta.get("failed_measures"))
    if failed is None:
        failed = sum(1 for row in source_rows if is_true(row.get("is_failed")))
    return {
        "path_id": meta["path_id"],
        "fixed_index": meta["fixed_index"],
        "path": meta["path"],
        "status": meta["status"],
        "from_pin": meta["from_pin"],
        "to_pin": meta["to_pin"],
        "path_key": meta["path_key"],
        "target_vdd": meta["target_vdd"],
        "target_temp": meta["target_temp"],
        "input_slew_ps": meta["input_slew_ps"],
        "output_load_ff": meta["output_load_ff"],
        "stage_count": len(stage_rows),
        "total_cell_ps": fmt_number(total_cell),
        "total_net_ps": fmt_number(total_net),
        "total_path_ps": fmt_number(total_path),
        "failed_measures": failed,
        "unknown_delay_count": sum(1 for row in source_rows if row.get("kind") == "unknown_delay"),
        "pt_ok": meta["pt_ok"],
        "patch_ok": meta["patch_ok"],
        "hspice_ok": meta["hspice_ok"],
        "nodes": meta["nodes"],
        "elements": meta["elements"],
        "peak_memory_mb": meta["peak_memory_mb"],
        "total_cpu_sec": meta["total_cpu_sec"],
        "total_elapsed_sec": meta["total_elapsed_sec"],
        "path_dir": meta["path_dir"],
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def add_wrapped(lines: list[str], label: str, value: Any, *, width: int = 92) -> None:
    prefix = f"{label:<7}: "
    text = str(value if value is not None else "")
    text = text.replace("->", " -> ")
    wrapped = textwrap.wrap(text, width=max(10, width - len(prefix)), break_long_words=True) or [""]
    for idx, part in enumerate(wrapped):
        lines.append((prefix if idx == 0 else " " * len(prefix)) + part)


def report_table_value(value: Any, width: int, digits: int = 2) -> str:
    text = fmt_fixed(value, digits)
    return f"{text:>{width}}"


def write_report(
    path: Path,
    batch_dir: Path,
    breakdown_csv: Path,
    path_summaries: list[dict[str, Any]],
    stage_rows_by_path: dict[str, list[dict[str, Any]]],
    *,
    name_width: int,
) -> None:
    lines: list[str] = []
    lines.append("PT Native SPICE Timing Report")
    lines.append(f"Batch : {batch_dir.name}")
    lines.append(f"Source: {breakdown_csv}")
    lines.append("")
    lines.append("=" * 96)
    lines.append("Batch Summary")
    lines.append("-" * 96)
    lines.append(
        f"{'Path':>4}  {'Status':<10}  {'VDD(V)':>6}  {'Temp(C)':>7}  {'Slew(ps)':>8}  "
        f"{'Load(fF)':>8}  {'Delay(ps)':>9}  {'Failed':>6}  {'Nodes':>7}  {'Elements':>8}"
    )
    lines.append(
        f"{'----':>4}  {'------':<10}  {'------':>6}  {'-------':>7}  {'--------':>8}  "
        f"{'--------':>8}  {'---------':>9}  {'------':>6}  {'-----':>7}  {'--------':>8}"
    )
    for summary in path_summaries:
        lines.append(
            f"{str(summary.get('path_id', '')):>4}  "
            f"{str(summary.get('status', '')):<10}  "
            f"{fmt_fixed(summary.get('target_vdd'), 2):>6}  "
            f"{fmt_fixed(summary.get('target_temp'), 1):>7}  "
            f"{fmt_fixed(summary.get('input_slew_ps'), 1):>8}  "
            f"{fmt_fixed(summary.get('output_load_ff'), 1):>8}  "
            f"{fmt_fixed(summary.get('total_path_ps'), 2):>9}  "
            f"{fmt_count(summary.get('failed_measures')):>6}  "
            f"{fmt_count(summary.get('nodes')):>7}  "
            f"{fmt_count(summary.get('elements')):>8}"
        )
    lines.append("")

    for summary in path_summaries:
        path_id = canonical_path_id(summary.get("path_id"))
        stage_rows = stage_rows_by_path.get(path_id, [])
        lines.append("=" * 96)
        lines.append(f"Path {summary.get('path_id')}  {summary.get('status')}")
        lines.append("-" * 96)
        add_wrapped(lines, "From", summary.get("from_pin"))
        add_wrapped(lines, "To", summary.get("to_pin"))
        add_wrapped(lines, "Key", summary.get("path_key"))
        lines.append("")
        lines.append(
            "Target : "
            f"VDD={fmt_fixed(summary.get('target_vdd'), 2)} V  "
            f"TEMP={fmt_fixed(summary.get('target_temp'), 1)} C  "
            f"input_slew={fmt_fixed(summary.get('input_slew_ps'), 1)} ps  "
            f"output_load={fmt_fixed(summary.get('output_load_ff'), 1)} fF"
        )
        lines.append(
            "HSPICE: "
            f"nodes={fmt_count(summary.get('nodes'))}  "
            f"elements={fmt_count(summary.get('elements'))}  "
            f"peak_mem={fmt_fixed(summary.get('peak_memory_mb'), 2)} MB"
        )
        lines.append(
            "Status : "
            f"pt={status_ok_text(summary.get('pt_ok'))}  "
            f"patch={status_ok_text(summary.get('patch_ok'))}  "
            f"hspice={status_ok_text(summary.get('hspice_ok'))}  "
            f"failed_measures={fmt_count(summary.get('failed_measures'))}"
        )
        lines.append("")
        lines.append(
            f"{'Stage':>5}  {'Cell Arc / Net':<{name_width}}  "
            f"{'Cell(ps)':>8}  {'Net(ps)':>7}  {'Stage(ps)':>9}  {'OutSlew(ps)':>11}"
        )
        lines.append(
            f"{'-----':>5}  {'-' * name_width:<{name_width}}  "
            f"{'--------':>8}  {'-------':>7}  {'---------':>9}  {'-----------':>11}"
        )
        for row in stage_rows:
            cell_arc = shorten_middle(row.get("cell_arc", ""), name_width)
            net_arc = shorten_middle("net: " + str(row.get("net_arc", "")), name_width) if nonempty(row.get("net_arc")) else ""
            lines.append(
                f"{str(row.get('stage_idx', '')):>5}  "
                f"{cell_arc:<{name_width}}  "
                f"{report_table_value(row.get('cell_ps'), 8)}  "
                f"{report_table_value(row.get('net_ps'), 7)}  "
                f"{report_table_value(row.get('stage_ps'), 9)}  "
                f"{report_table_value(row.get('out_slew_ps'), 11)}"
            )
            if net_arc:
                lines.append(f"{'':>5}  {net_arc:<{name_width}}")
        lines.append("")
        lines.append("-" * 96)
        lines.append(f"Total cell delay : {fmt_fixed(summary.get('total_cell_ps'), 2)} ps")
        lines.append(f"Total net delay  : {fmt_fixed(summary.get('total_net_ps'), 2)} ps")
        lines.append(f"Total path delay : {fmt_fixed(summary.get('total_path_ps'), 2)} ps")
        lines.append(f"Stage count      : {fmt_count(summary.get('stage_count'))}")
        if to_int(summary.get("unknown_delay_count")):
            lines.append(f"Unknown delays   : {fmt_count(summary.get('unknown_delay_count'))}")
        lines.append("")
    lines.append("Note: native_stage_compact.csv keeps full node names and original measure names.")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    batch_dir = args.batch_dir.resolve()
    if not batch_dir.is_dir():
        raise SystemExit(f"ERROR: missing batch dir: {batch_dir}")

    breakdown_csv = args.breakdown_csv or (batch_dir / "native_delay_breakdown.csv")
    batch_summary_csv = args.batch_summary_csv or (batch_dir / "batch_summary.csv")
    report_rpt = args.report_rpt or (batch_dir / "native_timing_report.rpt")
    stage_csv = args.stage_csv or (batch_dir / "native_stage_compact.csv")
    path_summary_csv = args.path_summary_csv or (batch_dir / "native_path_summary.csv")

    breakdown_rows = read_csv(breakdown_csv, "native delay breakdown CSV")
    batch_summary = load_batch_summary(batch_summary_csv, required=args.fail_on_missing)
    statuses = load_statuses(batch_dir)

    rows_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in breakdown_rows:
        path_id = canonical_path_id(row.get("path_id"))
        if path_id:
            rows_by_path[path_id].append(row)

    if not rows_by_path:
        raise SystemExit(f"ERROR: no path rows found in {breakdown_csv}")

    all_stage_rows: list[dict[str, Any]] = []
    path_summaries: list[dict[str, Any]] = []
    stage_rows_by_path: dict[str, list[dict[str, Any]]] = {}

    for path_id in sorted(rows_by_path, key=path_sort_key):
        source_rows = rows_by_path[path_id]
        meta = path_metadata(path_id, source_rows, batch_summary.get(path_id, {}), statuses.get(path_id, {}))
        stages = stage_component_rows(source_rows)
        compact_rows = [compact_stage_record(meta, stage) for stage in stages]
        stage_rows_by_path[path_id] = compact_rows
        all_stage_rows.extend(compact_rows)
        path_summaries.append(path_summary_record(meta, compact_rows, source_rows))

    write_csv(stage_csv, all_stage_rows, STAGE_FIELDS)
    write_csv(path_summary_csv, path_summaries, PATH_SUMMARY_FIELDS)
    write_report(
        report_rpt,
        batch_dir,
        breakdown_csv,
        path_summaries,
        stage_rows_by_path,
        name_width=max(24, args.name_width),
    )

    print(f"report_rpt={report_rpt}")
    print(f"stage_csv={stage_csv}")
    print(f"path_summary_csv={path_summary_csv}")
    print(f"paths={len(path_summaries)} stages={len(all_stage_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
