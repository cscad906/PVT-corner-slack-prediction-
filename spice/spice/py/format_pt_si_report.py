#!/usr/bin/env python3
"""Create PT SI-on stage reports and PT-vs-HSPICE comparison reports.

The PrimeTime deck-generation step writes one `report_timing` dump per path.
This script parses those dumps into the same stage convention used by
`native_stage_compact.csv`:

  stage = cell arc delay + following net delay

It then compares the PT SI-on stages against the HSPICE-native stage report.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
PATH_DIR_RE = re.compile(r"^path_(\d+)$")
HEADER_RE = re.compile(r"^### PT_NATIVE_SMOKE_PATH idx=(\d+) key=(.*)$")
STARTPOINT_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
ENDPOINT_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
PIN_RE = re.compile(
    rf"^\s+(?P<point>\S+)\s+\((?P<cell>[^)]*)\)\s*(?P<mark><-)?\s*"
    rf"(?P<trans>{FLOAT_RE})\s+(?P<incr>{FLOAT_RE})\s+&\s+"
    rf"(?P<path>{FLOAT_RE})\s+(?P<edge>[rf])\s*$",
    re.IGNORECASE,
)
DATA_ARRIVAL_RE = re.compile(rf"^\s*data arrival time\s+(?P<path>{FLOAT_RE})\s*$", re.IGNORECASE)


PT_STAGE_FIELDS = [
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
    "cell_type",
    "net_name",
    "target_vdd",
    "target_temp",
    "input_slew_ps",
    "output_load_ff",
    "path_key",
    "pt_from_pin",
    "pt_to_pin",
    "path_dir",
]

PT_PATH_FIELDS = [
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
    "pt_ck_to_d_ps",
    "pt_q_to_d_ps",
    "data_arrival_path_ns",
    "path_dir",
]

COMPARE_STAGE_FIELDS = [
    "path_id",
    "stage_idx",
    "pt_cell_ps",
    "spice_cell_ps",
    "cell_delta_ps",
    "pt_net_ps",
    "spice_net_ps",
    "net_delta_ps",
    "pt_stage_ps",
    "spice_stage_ps",
    "stage_delta_ps",
    "pt_out_slew_ps",
    "spice_out_slew_ps",
    "out_slew_delta_ps",
    "pt_cell_from",
    "pt_cell_to",
    "pt_net_to",
    "spice_cell_from",
    "spice_cell_to",
    "spice_net_to",
]

COMPARE_PATH_FIELDS = [
    "path_id",
    "status",
    "pt_ck_to_d_ps",
    "spice_ck_to_d_ps",
    "delta_ps",
    "delta_pct",
    "pt_q_to_d_ps",
    "spice_total_cell_ps",
    "spice_total_net_ps",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", required=True, type=Path)
    parser.add_argument("--pt-stage-csv", type=Path)
    parser.add_argument("--pt-path-summary-csv", type=Path)
    parser.add_argument("--pt-report-rpt", type=Path)
    parser.add_argument("--native-stage-csv", type=Path)
    parser.add_argument("--native-path-summary-csv", type=Path)
    parser.add_argument("--compare-stage-csv", type=Path)
    parser.add_argument("--compare-path-csv", type=Path)
    parser.add_argument("--compare-rpt", type=Path)
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--name-width", type=int, default=74)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def fnum(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt(value: Any, digits: int = 3) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_delta(delta: float | None, digits: int = 3) -> str:
    if delta is None:
        return ""
    return f"{delta:.{digits}f}"


def compact(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def split_pin(point: str) -> tuple[str, str]:
    if "/" not in point:
        return point, ""
    inst, pin = point.rsplit("/", 1)
    return inst, pin


def same_instance(a: str, b: str) -> bool:
    return split_pin(a)[0].lower() == split_pin(b)[0].lower()


def path_id_from_dir(path_dir: Path) -> int | None:
    match = PATH_DIR_RE.match(path_dir.name)
    if not match:
        return None
    return int(match.group(1))


def resolve_path_dirs(batch_dir: Path, batch_rows: list[dict[str, str]]) -> list[tuple[int, Path, dict[str, str]]]:
    by_id: dict[int, dict[str, str]] = {}
    for row in batch_rows:
        try:
            by_id[int(row.get("path_id", ""))] = row
        except ValueError:
            continue

    dirs: list[tuple[int, Path, dict[str, str]]] = []
    for path_dir in sorted(batch_dir.glob("path_*")):
        if not path_dir.is_dir():
            continue
        path_id = path_id_from_dir(path_dir)
        if path_id is None:
            continue
        dirs.append((path_id, path_dir, by_id.get(path_id, {})))
    return dirs


def find_pt_rpt(path_dir: Path) -> Path | None:
    preferred = path_dir / f"{path_dir.name}.rpt"
    if preferred.is_file():
        return preferred
    candidates = sorted(path_dir.glob("*.rpt"))
    return candidates[0] if candidates else None


def parse_pin_line(line: str) -> dict[str, Any] | None:
    match = PIN_RE.match(line)
    if not match:
        return None
    point = match.group("point")
    return {
        "point": point,
        "cell_type": match.group("cell"),
        "is_data_marker": bool(match.group("mark")),
        "trans_ps": float(match.group("trans")) * 1000.0,
        "incr_ps": float(match.group("incr")) * 1000.0,
        "path_ps": float(match.group("path")) * 1000.0,
        "edge": match.group("edge"),
    }


def parse_pt_report(path: Path) -> dict[str, Any]:
    path_key = ""
    fixed_index = None
    startpoint = ""
    endpoint = ""
    data_arrival_ns = None
    pin_rows: list[dict[str, Any]] = []
    all_pin_rows: list[dict[str, Any]] = []
    data_started = False
    launch_clock_pin: dict[str, Any] | None = None
    last_pin_before_data: dict[str, Any] | None = None

    for line in path.read_text(errors="ignore").splitlines():
        header = HEADER_RE.match(line)
        if header:
            fixed_index = int(header.group(1))
            path_key = header.group(2).strip()
            continue
        start = STARTPOINT_RE.match(line)
        if start:
            startpoint = start.group(1)
            continue
        end = ENDPOINT_RE.match(line)
        if end:
            endpoint = end.group(1)
            continue
        arrival = DATA_ARRIVAL_RE.match(line)
        if arrival and data_started:
            data_arrival_ns = float(arrival.group("path"))
            data_started = False
            continue

        pin = parse_pin_line(line)
        if not pin:
            continue
        all_pin_rows.append(pin)
        if not data_started and pin["is_data_marker"]:
            data_started = True
            launch_clock_pin = last_pin_before_data
        if data_started:
            pin_rows.append(pin)
        else:
            last_pin_before_data = pin

    return {
        "path_key": path_key,
        "fixed_index": fixed_index,
        "startpoint": startpoint,
        "endpoint": endpoint,
        "launch_clock_pin": launch_clock_pin,
        "data_pins": pin_rows,
        "all_pins": all_pin_rows,
        "data_arrival_ns": data_arrival_ns,
        "report": str(path),
    }


def build_stages(parsed: dict[str, Any], meta: dict[str, str], path_id: int, path_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data_pins: list[dict[str, Any]] = parsed["data_pins"]
    launch_clock_pin = parsed["launch_clock_pin"]
    rows: list[dict[str, Any]] = []
    if not data_pins:
        summary = path_summary(path_id, path_dir, parsed, meta, rows)
        return rows, summary

    stage_idx = 1
    output_index = 0
    while output_index < len(data_pins):
        cell_to = data_pins[output_index]
        if output_index == 0:
            cell_from = launch_clock_pin
        else:
            cell_from = data_pins[output_index - 1]
        net_to = data_pins[output_index + 1] if output_index + 1 < len(data_pins) else None

        if cell_from is None:
            cell_from_point = ""
            in_slew_ps = ""
        else:
            cell_from_point = cell_from["point"]
            in_slew_ps = cell_from.get("trans_ps", "")

        net_ps = net_to["incr_ps"] if net_to is not None else 0.0
        net_to_point = net_to["point"] if net_to is not None else ""
        row = {
            "path_id": path_id,
            "fixed_index": parsed.get("fixed_index") or meta.get("fixed_index") or path_id,
            "path": path_dir.name,
            "status": meta.get("status", ""),
            "stage_idx": stage_idx,
            "cell_from": cell_from_point,
            "cell_to": cell_to["point"],
            "cell_arc": f"{cell_from_point} -> {cell_to['point']}" if cell_from_point else cell_to["point"],
            "net_from": cell_to["point"],
            "net_to": net_to_point,
            "net_arc": f"{cell_to['point']} -> {net_to_point}" if net_to_point else "",
            "stage_from": cell_from_point,
            "stage_to": net_to_point or cell_to["point"],
            "stage_arc": f"{cell_from_point} -> {net_to_point or cell_to['point']}" if cell_from_point else "",
            "cell_ps": round(cell_to["incr_ps"], 6),
            "net_ps": round(net_ps, 6),
            "stage_ps": round(cell_to["incr_ps"] + net_ps, 6),
            "in_slew_ps": round(float(in_slew_ps), 6) if in_slew_ps != "" else "",
            "out_slew_ps": round(cell_to["trans_ps"], 6),
            "cell_type": cell_to.get("cell_type", ""),
            "net_name": "",
            "target_vdd": meta.get("target_vdd", ""),
            "target_temp": meta.get("target_temp", ""),
            "input_slew_ps": meta.get("input_slew_ps", ""),
            "output_load_ff": meta.get("output_load_ff", ""),
            "path_key": parsed.get("path_key") or meta.get("path_key", ""),
            "pt_from_pin": meta.get("from_pin", ""),
            "pt_to_pin": meta.get("to_pin", ""),
            "path_dir": str(path_dir),
        }
        rows.append(row)
        stage_idx += 1
        output_index += 2

    summary = path_summary(path_id, path_dir, parsed, meta, rows)
    return rows, summary


def path_summary(
    path_id: int,
    path_dir: Path,
    parsed: dict[str, Any],
    meta: dict[str, str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total_cell = sum(fnum(row.get("cell_ps")) for row in rows)
    total_net = sum(fnum(row.get("net_ps")) for row in rows)
    stage_sum = total_cell + total_net
    first_cell = fnum(rows[0].get("cell_ps")) if rows else 0.0
    launch_clock_pin = parsed.get("launch_clock_pin") or {}
    data_arrival_ns = parsed.get("data_arrival_ns")
    if data_arrival_ns is not None and launch_clock_pin.get("path_ps") is not None:
        pt_ck_to_d = float(data_arrival_ns) * 1000.0 - float(launch_clock_pin["path_ps"])
    else:
        pt_ck_to_d = stage_sum
    return {
        "path_id": path_id,
        "fixed_index": parsed.get("fixed_index") or meta.get("fixed_index") or path_id,
        "path": path_dir.name,
        "status": meta.get("status", ""),
        "from_pin": meta.get("from_pin", ""),
        "to_pin": meta.get("to_pin", ""),
        "path_key": parsed.get("path_key") or meta.get("path_key", ""),
        "target_vdd": meta.get("target_vdd", ""),
        "target_temp": meta.get("target_temp", ""),
        "input_slew_ps": meta.get("input_slew_ps", ""),
        "output_load_ff": meta.get("output_load_ff", ""),
        "stage_count": len(rows),
        "total_cell_ps": round(total_cell, 6),
        "total_net_ps": round(total_net, 6),
        "total_path_ps": round(pt_ck_to_d, 6),
        "pt_ck_to_d_ps": round(pt_ck_to_d, 6),
        "pt_q_to_d_ps": round(pt_ck_to_d - first_cell, 6) if rows else "",
        "data_arrival_path_ns": parsed.get("data_arrival_ns") or "",
        "path_dir": str(path_dir),
    }


def generate_pt_outputs(batch_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    batch_rows = read_csv(batch_dir / "batch_summary.csv")
    stage_rows: list[dict[str, Any]] = []
    path_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for path_id, path_dir, meta in resolve_path_dirs(batch_dir, batch_rows):
        rpt = find_pt_rpt(path_dir)
        if rpt is None:
            errors.append({"path": str(path_dir), "error": "missing PT report"})
            continue
        try:
            parsed = parse_pt_report(rpt)
            stages, summary = build_stages(parsed, meta, path_id, path_dir)
        except Exception as exc:  # noqa: BLE001 - report generation should continue path-by-path.
            errors.append({"path": str(rpt), "error": str(exc)})
            continue
        stage_rows.extend(stages)
        path_rows.append(summary)

    return stage_rows, path_rows, errors


def keyed(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, Any]]:
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row.get(item, "")) for item in keys)
        result[key] = row
    return result


def compare_stage_rows(pt_rows: list[dict[str, Any]], spice_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    spice_by_key = keyed(spice_rows, ("path_id", "stage_idx"))
    compared: list[dict[str, Any]] = []
    for pt in pt_rows:
        key = (str(pt.get("path_id", "")), str(pt.get("stage_idx", "")))
        spice = spice_by_key.get(key, {})
        pt_cell = fnum(pt.get("cell_ps"))
        spice_cell = fnum(spice.get("cell_ps"), 0.0)
        pt_net = fnum(pt.get("net_ps"))
        spice_net = fnum(spice.get("net_ps"), 0.0)
        pt_stage = fnum(pt.get("stage_ps"))
        spice_stage = fnum(spice.get("stage_ps"), 0.0)
        pt_slew = fnum(pt.get("out_slew_ps"))
        spice_slew = fnum(spice.get("out_slew_ps"), 0.0)
        compared.append(
            {
                "path_id": pt.get("path_id", ""),
                "stage_idx": pt.get("stage_idx", ""),
                "pt_cell_ps": round(pt_cell, 6),
                "spice_cell_ps": round(spice_cell, 6) if spice else "",
                "cell_delta_ps": round(spice_cell - pt_cell, 6) if spice else "",
                "pt_net_ps": round(pt_net, 6),
                "spice_net_ps": round(spice_net, 6) if spice else "",
                "net_delta_ps": round(spice_net - pt_net, 6) if spice else "",
                "pt_stage_ps": round(pt_stage, 6),
                "spice_stage_ps": round(spice_stage, 6) if spice else "",
                "stage_delta_ps": round(spice_stage - pt_stage, 6) if spice else "",
                "pt_out_slew_ps": round(pt_slew, 6),
                "spice_out_slew_ps": round(spice_slew, 6) if spice else "",
                "out_slew_delta_ps": round(spice_slew - pt_slew, 6) if spice else "",
                "pt_cell_from": pt.get("cell_from", ""),
                "pt_cell_to": pt.get("cell_to", ""),
                "pt_net_to": pt.get("net_to", ""),
                "spice_cell_from": spice.get("cell_from", ""),
                "spice_cell_to": spice.get("cell_to", ""),
                "spice_net_to": spice.get("net_to", ""),
            }
        )
    return compared


def compare_path_rows(pt_rows: list[dict[str, Any]], spice_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    spice_by_id = keyed(spice_rows, ("path_id",))
    compared: list[dict[str, Any]] = []
    for pt in pt_rows:
        path_id = str(pt.get("path_id", ""))
        spice = spice_by_id.get((path_id,), {})
        pt_total = fnum(pt.get("pt_ck_to_d_ps"))
        spice_total = fnum(spice.get("total_path_ps"), 0.0)
        delta = spice_total - pt_total if spice else None
        delta_pct = (delta / pt_total * 100.0) if delta is not None and pt_total else None
        compared.append(
            {
                "path_id": path_id,
                "status": spice.get("status", pt.get("status", "")),
                "pt_ck_to_d_ps": round(pt_total, 6),
                "spice_ck_to_d_ps": round(spice_total, 6) if spice else "",
                "delta_ps": round(delta, 6) if delta is not None else "",
                "delta_pct": round(delta_pct, 6) if delta_pct is not None else "",
                "pt_q_to_d_ps": pt.get("pt_q_to_d_ps", ""),
                "spice_total_cell_ps": spice.get("total_cell_ps", ""),
                "spice_total_net_ps": spice.get("total_net_ps", ""),
                "stage_count": spice.get("stage_count", pt.get("stage_count", "")),
                "input_slew_ps": spice.get("input_slew_ps", pt.get("input_slew_ps", "")),
                "output_load_ff": spice.get("output_load_ff", pt.get("output_load_ff", "")),
                "target_vdd": spice.get("target_vdd", pt.get("target_vdd", "")),
                "target_temp": spice.get("target_temp", pt.get("target_temp", "")),
                "failed_measures": spice.get("failed_measures", ""),
                "nodes": spice.get("nodes", ""),
                "elements": spice.get("elements", ""),
                "peak_memory_mb": spice.get("peak_memory_mb", ""),
                "pt_from_pin": pt.get("from_pin", ""),
                "pt_to_pin": pt.get("to_pin", ""),
                "path_key": pt.get("path_key", ""),
            }
        )
    return compared


def write_pt_report(path: Path, batch_dir: Path, path_rows: list[dict[str, Any]], stage_rows: list[dict[str, Any]], name_width: int) -> None:
    stages_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in stage_rows:
        stages_by_path[str(row.get("path_id", ""))].append(row)

    lines: list[str] = []
    lines.append("PrimeTime SI-on Stage Timing Report\n")
    lines.append(f"Batch : {batch_dir.name}\n")
    lines.append(f"Source: PT report_timing dumps under {batch_dir}\n\n")
    lines.append("=" * 96 + "\n")
    lines.append("Path Summary\n")
    lines.append("-" * 96 + "\n")
    lines.append("Path  Status  Stages  Cell(ps)  Net(ps)  CK->D(ps)  Q->D(ps)  From -> To\n")
    lines.append("----  ------  ------  --------  -------  ---------  --------  ----------\n")
    for row in path_rows:
        arc = compact(f"{row.get('from_pin', '')} -> {row.get('to_pin', '')}", name_width)
        lines.append(
            f"{int(row['path_id']):4d}  {str(row.get('status', '')):6s}"
            f"  {int(row.get('stage_count') or 0):6d}"
            f"  {fmt(row.get('total_cell_ps'), 2):>8s}"
            f"  {fmt(row.get('total_net_ps'), 2):>7s}"
            f"  {fmt(row.get('pt_ck_to_d_ps'), 2):>9s}"
            f"  {fmt(row.get('pt_q_to_d_ps'), 2):>8s}  {arc}\n"
        )

    for row in path_rows:
        path_id = str(row.get("path_id", ""))
        lines.append("\n" + "=" * 96 + "\n")
        lines.append(f"Path {path_id}  {row.get('status', '')}\n")
        lines.append("-" * 96 + "\n")
        lines.append(f"From: {row.get('from_pin', '')}\n")
        lines.append(f"To  : {row.get('to_pin', '')}\n")
        lines.append(f"Key : {row.get('path_key', '')}\n\n")
        lines.append("Stage  Cell(ps)  Net(ps)  Stage(ps)  InSlew  OutSlew  Arc\n")
        lines.append("-----  --------  -------  ---------  ------  -------  ---\n")
        for stage in stages_by_path.get(path_id, []):
            arc = compact(str(stage.get("stage_arc", "")), name_width)
            lines.append(
                f"{int(stage['stage_idx']):5d}"
                f"  {fmt(stage.get('cell_ps'), 3):>8s}"
                f"  {fmt(stage.get('net_ps'), 3):>7s}"
                f"  {fmt(stage.get('stage_ps'), 3):>9s}"
                f"  {fmt(stage.get('in_slew_ps'), 3):>6s}"
                f"  {fmt(stage.get('out_slew_ps'), 3):>7s}  {arc}\n"
            )
    path.write_text("".join(lines))


def write_compare_report(
    path: Path,
    batch_dir: Path,
    path_rows: list[dict[str, Any]],
    stage_rows: list[dict[str, Any]],
    name_width: int,
) -> None:
    stages_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in stage_rows:
        stages_by_path[str(row.get("path_id", ""))].append(row)

    lines: list[str] = []
    lines.append("PrimeTime SI-on vs HSPICE comparison\n")
    lines.append("Basis: PT SI-on stage increments vs HSPICE native measure stages\n")
    lines.append(f"Batch: {batch_dir.name}\n\n")
    lines.append("Path  Status  PT CK->D(ps)  HSPICE(ps)  Delta(ps)  Delta(%)  Stages\n")
    lines.append("----  ------  ------------  ----------  ---------  --------  ------\n")
    for row in path_rows:
        lines.append(
            f"{int(row['path_id']):4d}  {str(row.get('status', '')):6s}"
            f"  {fmt(row.get('pt_ck_to_d_ps'), 2):>12s}"
            f"  {fmt(row.get('spice_ck_to_d_ps'), 2):>10s}"
            f"  {fmt(row.get('delta_ps'), 2):>9s}"
            f"  {fmt(row.get('delta_pct'), 2):>8s}"
            f"  {str(row.get('stage_count', '')):>6s}\n"
        )

    for row in path_rows:
        path_id = str(row.get("path_id", ""))
        lines.append("\n" + "=" * 112 + "\n")
        lines.append(f"Path {path_id}  {row.get('status', '')}\n")
        lines.append("-" * 112 + "\n")
        lines.append("Stage  PT_cell  SP_cell  dCell  PT_net  SP_net   dNet  PT_stage  SP_stage  dStage  Arc\n")
        lines.append("-----  -------  -------  -----  ------  ------  -----  --------  --------  ------  ---\n")
        for stage in stages_by_path.get(path_id, []):
            arc = compact(str(stage.get("pt_cell_from", "")) + " -> " + str(stage.get("pt_net_to", "")), name_width)
            lines.append(
                f"{int(stage['stage_idx']):5d}"
                f"  {fmt(stage.get('pt_cell_ps'), 2):>7s}"
                f"  {fmt(stage.get('spice_cell_ps'), 2):>7s}"
                f"  {fmt_delta(fnum(stage.get('cell_delta_ps')), 2):>5s}"
                f"  {fmt(stage.get('pt_net_ps'), 2):>6s}"
                f"  {fmt(stage.get('spice_net_ps'), 2):>6s}"
                f"  {fmt_delta(fnum(stage.get('net_delta_ps')), 2):>5s}"
                f"  {fmt(stage.get('pt_stage_ps'), 2):>8s}"
                f"  {fmt(stage.get('spice_stage_ps'), 2):>8s}"
                f"  {fmt_delta(fnum(stage.get('stage_delta_ps')), 2):>6s}  {arc}\n"
            )
    path.write_text("".join(lines))


def main() -> int:
    args = parse_args()
    batch_dir = args.batch_dir.resolve()
    pt_stage_csv = args.pt_stage_csv or batch_dir / "pt_si_stage_compact.csv"
    pt_path_csv = args.pt_path_summary_csv or batch_dir / "pt_si_path_summary.csv"
    pt_report = args.pt_report_rpt or batch_dir / "pt_si_timing_report.rpt"
    native_stage_csv = args.native_stage_csv or batch_dir / "native_stage_compact.csv"
    native_path_csv = args.native_path_summary_csv or batch_dir / "native_path_summary.csv"
    compare_stage_csv = args.compare_stage_csv or batch_dir / "pt_vs_native_stage_compare.csv"
    compare_path_csv = args.compare_path_csv or batch_dir / "pt_vs_native_path_compare.csv"
    compare_rpt = args.compare_rpt or batch_dir / "pt_vs_native_compare.rpt"
    summary_json = args.summary_json or batch_dir / "pt_si_report_summary.json"

    pt_stage_rows, pt_path_rows, errors = generate_pt_outputs(batch_dir)
    write_csv(pt_stage_csv, PT_STAGE_FIELDS, pt_stage_rows)
    write_csv(pt_path_csv, PT_PATH_FIELDS, pt_path_rows)
    write_pt_report(pt_report, batch_dir, pt_path_rows, pt_stage_rows, args.name_width)

    native_stage_rows = read_csv(native_stage_csv)
    native_path_rows = read_csv(native_path_csv)
    compare_stage = compare_stage_rows(pt_stage_rows, native_stage_rows)
    compare_path = compare_path_rows(pt_path_rows, native_path_rows)
    write_csv(compare_stage_csv, COMPARE_STAGE_FIELDS, compare_stage)
    write_csv(compare_path_csv, COMPARE_PATH_FIELDS, compare_path)
    write_compare_report(compare_rpt, batch_dir, compare_path, compare_stage, args.name_width)

    summary = {
        "batch_dir": str(batch_dir),
        "pt_stage_csv": str(pt_stage_csv),
        "pt_path_summary_csv": str(pt_path_csv),
        "pt_report_rpt": str(pt_report),
        "compare_stage_csv": str(compare_stage_csv),
        "compare_path_csv": str(compare_path_csv),
        "compare_rpt": str(compare_rpt),
        "path_count": len(pt_path_rows),
        "stage_count": len(pt_stage_rows),
        "errors": errors,
    }
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
