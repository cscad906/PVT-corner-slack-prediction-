#!/usr/bin/env python3
"""Summarize PT report slew/load coverage against Liberty table indices.

This script is intentionally report-driven: it does not select cells from one
hand-picked path.  It scans PrimeTime timing reports, reconstructs adjacent
input-pin -> output-pin arcs, and compares the observed input transition and
output net capacitance against the Liberty cell_rise/cell_fall index ranges.
"""


import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


CELL_RE = re.compile(r"\((SAED[^)]+)\)")
CELL_BLOCK_RE = re.compile(r"^\s*cell\s*\(([^)]+)\)\s*\{")
TABLE_BLOCK_RE = re.compile(r"^\s*(cell_rise|cell_fall)\s*\(")
INDEX_RE = re.compile(r"index_([12])\s*\(\s*\"([^\"]+)\"")
VOLT_RE = re.compile(r"tt([0-9p]+)v25c")
FIXED_PATH_RE = re.compile(r"^###\s+FIXED_PATH\s+idx=(\d+)\s+key=(.*)$")


def parse_float_list(text: str) -> List[float]:
    values = []
    for item in text.replace("\\", "").split(","):
        item = item.strip()
        if not item:
            continue
        values.append(float(item))
    return values


def voltage_from_name(path: Path) -> str:
    m = VOLT_RE.search(path.name)
    return m.group(1).replace("p", ".") if m else ""


def infer_benchmark(path: Path) -> str:
    parts = path.parts
    if "generated0.8" in parts:
        idx = parts.index("generated0.8")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    for name in ("BoomCoreV3", "RocketCore", "SmallBoomV2", "ibex"):
        if name in parts:
            return name
    return ""


def infer_mode(path: Path) -> str:
    for part in reversed(path.parts):
        lower = part.lower()
        if lower.startswith("setup"):
            return "setup"
        if lower.startswith("hold"):
            return "hold"
    text = str(path).lower()
    if "/setup_" in text or "_setup_" in text:
        return "setup"
    if "/hold_" in text or "_hold_" in text:
        return "hold"
    return ""


def infer_rc(path: Path) -> str:
    for part in reversed(path.parts):
        if part in {"Cnom", "Cmin", "Cmax"}:
            return part
    name = path.name
    for rc in ("Cnom", "Cmin", "Cmax"):
        if rc in name:
            return rc
    return ""


def parse_lib_table_ranges(lib: Path) -> Dict[Tuple[str, str], Dict[str, Union[float, int]]]:
    """Return per-cell/table min/max index range.

    The generated SAED14 Liberty files repeat explicit index_1/index_2 inside
    timing tables.  We aggregate all cell_rise/cell_fall tables per cell, which
    is sufficient for identifying real STA points that are outside the current
    slew/load grid.
    """

    ranges: Dict[Tuple[str, str], Dict[str, Union[float, int]]] = {}
    depth = 0
    current_cell = ""
    cell_depth = -1
    current_table = ""
    table_depth = -1
    index_1: Optional[List[float]] = None
    index_2: Optional[List[float]] = None

    def update_range(cell: str, table: str, i1: List[float], i2: List[float]) -> None:
        if not cell or not table or not i1 or not i2:
            return
        key = (cell, table)
        entry = ranges.get(key)
        if entry is None:
            ranges[key] = {
                "slew_min": min(i1),
                "slew_max": max(i1),
                "load_min": min(i2),
                "load_max": max(i2),
                "slew_points_max": len(i1),
                "load_points_max": len(i2),
                "table_count": 1,
            }
        else:
            entry["slew_min"] = min(float(entry["slew_min"]), min(i1))
            entry["slew_max"] = max(float(entry["slew_max"]), max(i1))
            entry["load_min"] = min(float(entry["load_min"]), min(i2))
            entry["load_max"] = max(float(entry["load_max"]), max(i2))
            entry["slew_points_max"] = max(int(entry["slew_points_max"]), len(i1))
            entry["load_points_max"] = max(int(entry["load_points_max"]), len(i2))
            entry["table_count"] = int(entry["table_count"]) + 1

    with lib.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not current_cell:
                m_cell = CELL_BLOCK_RE.match(line)
                if m_cell:
                    current_cell = m_cell.group(1)
                    cell_depth = depth

            if current_cell and not current_table:
                m_table = TABLE_BLOCK_RE.match(line)
                if m_table:
                    current_table = m_table.group(1)
                    table_depth = depth
                    index_1 = None
                    index_2 = None

            if current_table:
                for m_index in INDEX_RE.finditer(line):
                    values = parse_float_list(m_index.group(2))
                    if m_index.group(1) == "1":
                        index_1 = values
                    else:
                        index_2 = values

            depth += raw.count("{") - raw.count("}")

            if current_table and depth <= table_depth:
                if index_1 is not None and index_2 is not None:
                    update_range(current_cell, current_table, index_1, index_2)
                current_table = ""
                table_depth = -1
                index_1 = None
                index_2 = None

            if current_cell and depth <= cell_depth:
                current_cell = ""
                cell_depth = -1

    return ranges


def parse_pin_row(line: str) -> Optional[Dict[str, object]]:
    if "(net)" in line:
        return None
    m_cell = CELL_RE.search(line)
    if not m_cell:
        return None
    tokens = line.split()
    if len(tokens) < 5 or tokens[-1] not in {"r", "f"}:
        return None
    try:
        path_time = float(tokens[-2])
        if tokens[-3] == "&":
            incr = float(tokens[-4])
            trans = float(tokens[-5])
        else:
            incr = float(tokens[-3])
            trans = float(tokens[-4])
    except (ValueError, IndexError):
        return None

    cell = m_cell.group(1)
    point_part = line[: m_cell.start()].strip()
    point_part = point_part.replace("<-", "").strip()
    if "/" not in point_part:
        return None
    inst, pin = point_part.rsplit("/", 1)
    return {
        "inst": inst,
        "pin": pin,
        "cell": cell,
        "trans": trans,
        "incr": incr,
        "path_time": path_time,
        "edge": tokens[-1],
        "is_data_marked": "<-" in line,
    }


def parse_net_row(line: str) -> Optional[Dict[str, object]]:
    if "(net)" not in line:
        return None
    tokens = line.split()
    if len(tokens) < 4:
        return None
    try:
        fanout = int(tokens[-2])
        cap = float(tokens[-1])
    except ValueError:
        return None
    net_name = line.split("(net)", 1)[0].strip()
    return {"net": net_name, "fanout": fanout, "cap": cap}


def compare_to_range(
    input_slew: float,
    output_cap: Optional[float],
    grid: Optional[Dict[str, Union[float, int]]],
) -> Dict[str, object]:
    result: Dict[str, object] = {
        "lib_slew_min": "",
        "lib_slew_max": "",
        "lib_load_min": "",
        "lib_load_max": "",
        "slew_below": "",
        "slew_above": "",
        "load_below": "",
        "load_above": "",
        "slew_above_ratio": "",
        "load_above_ratio": "",
        "is_extrapolated": True,
        "qa_flag": "missing_lib_grid",
    }
    if grid is None:
        return result

    slew_min = float(grid["slew_min"])
    slew_max = float(grid["slew_max"])
    load_min = float(grid["load_min"])
    load_max = float(grid["load_max"])
    slew_below = max(0.0, slew_min - input_slew)
    slew_above = max(0.0, input_slew - slew_max)
    if output_cap is None:
        load_below = math.nan
        load_above = math.nan
        load_extrap = True
        qa = "missing_output_net_cap"
    else:
        load_below = max(0.0, load_min - output_cap)
        load_above = max(0.0, output_cap - load_max)
        load_extrap = load_below > 0.0 or load_above > 0.0
        qa = ""
    slew_extrap = slew_below > 0.0 or slew_above > 0.0
    result.update(
        {
            "lib_slew_min": slew_min,
            "lib_slew_max": slew_max,
            "lib_load_min": load_min,
            "lib_load_max": load_max,
            "slew_below": slew_below,
            "slew_above": slew_above,
            "load_below": "" if math.isnan(load_below) else load_below,
            "load_above": "" if math.isnan(load_above) else load_above,
            "slew_above_ratio": (input_slew / slew_max) if slew_max > 0 else "",
            "load_above_ratio": (
                "" if output_cap is None or load_max <= 0 else output_cap / load_max
            ),
            "is_extrapolated": slew_extrap or load_extrap,
            "qa_flag": qa,
        }
    )
    return result


def update_summary(summary: Dict[str, object], row: Dict[str, object]) -> None:
    summary["arc_count"] = int(summary.get("arc_count", 0)) + 1
    if row["phase"] == "data":
        summary["data_arc_count"] = int(summary.get("data_arc_count", 0)) + 1
    if row["is_extrapolated"]:
        summary["extrapolated_arc_count"] = int(summary.get("extrapolated_arc_count", 0)) + 1
    if row["qa_flag"]:
        summary["qa_count"] = int(summary.get("qa_count", 0)) + 1
    for key in ("input_slew", "output_cap", "output_transition", "incr"):
        val = row.get(key)
        if isinstance(val, (int, float)):
            max_key = f"max_{key}"
            if max_key not in summary or val > float(summary[max_key]):
                summary[max_key] = val
    for key in ("slew_above", "load_above", "slew_above_ratio", "load_above_ratio"):
        val = row.get(key)
        if isinstance(val, (int, float)):
            max_key = f"max_{key}"
            if max_key not in summary or val > float(summary[max_key]):
                summary[max_key] = val
                summary[f"{max_key}_example"] = (
                    f"{row['benchmark']} {row['voltage']}V path={row['path_idx']} "
                    f"{row['inst']} {row['arc']}"
                )


def iter_report_arcs(report: Path, lib_ranges: Dict[Tuple[str, str], Dict[str, Union[float, int]]]):
    benchmark = infer_benchmark(report)
    mode = infer_mode(report)
    rc = infer_rc(report)
    voltage = voltage_from_name(report)
    path_idx = ""
    path_key = ""
    previous_pin: Optional[Dict[str, object]] = None
    pending_arc: Optional[Dict[str, object]] = None
    data_seen = False

    with report.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m_path = FIXED_PATH_RE.match(line)
            if m_path:
                if pending_arc:
                    yield pending_arc
                pending_arc = None
                previous_pin = None
                data_seen = False
                path_idx = m_path.group(1)
                path_key = m_path.group(2)
                continue

            net = parse_net_row(line)
            if net:
                if pending_arc:
                    pending_arc["net"] = net["net"]
                    pending_arc["fanout"] = net["fanout"]
                    pending_arc["output_cap"] = net["cap"]
                    cmp_result = compare_to_range(
                        float(pending_arc["input_slew"]),
                        float(net["cap"]),
                        lib_ranges.get((str(pending_arc["cell"]), str(pending_arc["table_type"]))),
                    )
                    pending_arc.update(cmp_result)
                    yield pending_arc
                    pending_arc = None
                previous_pin = None
                continue

            pin = parse_pin_row(line)
            if pin is None:
                continue

            if (
                previous_pin
                and previous_pin["inst"] == pin["inst"]
                and previous_pin["cell"] == pin["cell"]
                and previous_pin["pin"] != pin["pin"]
            ):
                if pending_arc:
                    yield pending_arc
                output_edge = str(pin["edge"])
                table_type = "cell_rise" if output_edge == "r" else "cell_fall"
                phase = "data" if data_seen or bool(pin["is_data_marked"]) or bool(previous_pin["is_data_marked"]) else "clock"
                arc = f"{previous_pin['pin']}->{pin['pin']}"
                pending_arc = {
                    "benchmark": benchmark,
                    "mode": mode,
                    "rc": rc,
                    "voltage": voltage,
                    "path_idx": path_idx,
                    "path_key": path_key,
                    "phase": phase,
                    "inst": pin["inst"],
                    "cell": pin["cell"],
                    "arc": arc,
                    "from_pin": previous_pin["pin"],
                    "to_pin": pin["pin"],
                    "input_edge": previous_pin["edge"],
                    "output_edge": output_edge,
                    "table_type": table_type,
                    "input_slew": previous_pin["trans"],
                    "output_transition": pin["trans"],
                    "incr": pin["incr"],
                    "net": "",
                    "fanout": "",
                    "output_cap": None,
                }
                cmp_result = compare_to_range(
                    float(previous_pin["trans"]),
                    None,
                    lib_ranges.get((str(pin["cell"]), table_type)),
                )
                pending_arc.update(cmp_result)

            if pin["is_data_marked"]:
                data_seen = True
            previous_pin = pin

    if pending_arc:
        yield pending_arc


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lib", required=True, help="Representative generated Liberty file.")
    p.add_argument("--reports", nargs="+", required=True, help="Timing report files or directories.")
    p.add_argument("--outdir", required=True)
    p.add_argument("--include-clock", action="store_true", help="Include clock-tree arcs in summaries.")
    p.add_argument("--write-all-records", action="store_true", help="Write all arc records, not only extrapolated/QA rows.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    lib = Path(args.lib)
    outdir = Path(args.outdir)
    reports: List[Path] = []
    for item in args.reports:
        path = Path(item)
        if path.is_dir():
            reports.extend(sorted(path.rglob("*_fixed.rpt")))
        elif path.exists():
            reports.append(path)

    if not reports:
        raise SystemExit("No report files found.")

    lib_ranges = parse_lib_table_ranges(lib)
    outdir.mkdir(parents=True, exist_ok=True)

    record_fields = [
        "benchmark",
        "mode",
        "rc",
        "voltage",
        "path_idx",
        "phase",
        "cell",
        "arc",
        "inst",
        "from_pin",
        "to_pin",
        "input_edge",
        "output_edge",
        "table_type",
        "input_slew",
        "output_cap",
        "output_transition",
        "incr",
        "fanout",
        "net",
        "lib_slew_min",
        "lib_slew_max",
        "lib_load_min",
        "lib_load_max",
        "slew_below",
        "slew_above",
        "load_below",
        "load_above",
        "slew_above_ratio",
        "load_above_ratio",
        "is_extrapolated",
        "qa_flag",
        "path_key",
    ]
    all_records_path = outdir / "arc_slew_load_records.csv"
    extrap_records_path = outdir / "extrapolation_records.csv"
    all_records_file = all_records_path.open("w", newline="", encoding="utf-8") if args.write_all_records else None
    extrap_file = extrap_records_path.open("w", newline="", encoding="utf-8")
    all_writer = csv.DictWriter(all_records_file, fieldnames=record_fields) if all_records_file else None
    extrap_writer = csv.DictWriter(extrap_file, fieldnames=record_fields)
    if all_writer:
        all_writer.writeheader()
    extrap_writer.writeheader()

    cell_summary: Dict[Tuple[str, str, str, str, str, str, str], Dict[str, object]] = defaultdict(dict)
    bench_summary: Dict[Tuple[str, str, str, str], Dict[str, object]] = defaultdict(dict)
    processed_reports = []
    total_arcs = 0
    total_data_arcs = 0
    total_extrap = 0

    for report in reports:
        report_arcs = 0
        report_extrap = 0
        for row in iter_report_arcs(report, lib_ranges):
            if not args.include_clock and row["phase"] != "data":
                continue
            total_arcs += 1
            report_arcs += 1
            if row["phase"] == "data":
                total_data_arcs += 1
            if row["is_extrapolated"]:
                total_extrap += 1
                report_extrap += 1
                extrap_writer.writerow({key: row.get(key, "") for key in record_fields})
            if all_writer:
                all_writer.writerow({key: row.get(key, "") for key in record_fields})
            cell_key = (
                str(row["benchmark"]),
                str(row["mode"]),
                str(row["rc"]),
                str(row["phase"]),
                str(row["cell"]),
                str(row["arc"]),
                str(row["table_type"]),
            )
            bench_key = (
                str(row["benchmark"]),
                str(row["mode"]),
                str(row["rc"]),
                str(row["voltage"]),
            )
            update_summary(cell_summary[cell_key], row)
            update_summary(bench_summary[bench_key], row)
        processed_reports.append(
            {
                "report": str(report),
                "benchmark": infer_benchmark(report),
                "mode": infer_mode(report),
                "rc": infer_rc(report),
                "voltage": voltage_from_name(report),
                "arc_count": report_arcs,
                "extrapolated_arc_count": report_extrap,
            }
        )

    if all_records_file:
        all_records_file.close()
    extrap_file.close()

    cell_rows = []
    for key, summary in cell_summary.items():
        benchmark, mode, rc, phase, cell, arc, table_type = key
        arc_count = int(summary.get("arc_count", 0))
        extrap_count = int(summary.get("extrapolated_arc_count", 0))
        cell_rows.append(
            {
                "benchmark": benchmark,
                "mode": mode,
                "rc": rc,
                "phase": phase,
                "cell": cell,
                "arc": arc,
                "table_type": table_type,
                "arc_count": arc_count,
                "extrapolated_arc_count": extrap_count,
                "extrapolated_arc_pct": (100.0 * extrap_count / arc_count) if arc_count else 0.0,
                **summary,
            }
        )
    cell_rows.sort(
        key=lambda r: (
            -float(r.get("max_slew_above_ratio", 0) or 0),
            -float(r.get("max_load_above_ratio", 0) or 0),
            -int(r.get("extrapolated_arc_count", 0)),
        )
    )

    bench_rows = []
    for key, summary in bench_summary.items():
        benchmark, mode, rc, voltage = key
        arc_count = int(summary.get("arc_count", 0))
        extrap_count = int(summary.get("extrapolated_arc_count", 0))
        bench_rows.append(
            {
                "benchmark": benchmark,
                "mode": mode,
                "rc": rc,
                "voltage": voltage,
                "arc_count": arc_count,
                "extrapolated_arc_count": extrap_count,
                "extrapolated_arc_pct": (100.0 * extrap_count / arc_count) if arc_count else 0.0,
                **summary,
            }
        )
    bench_rows.sort(key=lambda r: (r["benchmark"], r["mode"], r["rc"], float(r["voltage"] or 0)))

    cell_fields = [
        "benchmark",
        "mode",
        "rc",
        "phase",
        "cell",
        "arc",
        "table_type",
        "arc_count",
        "data_arc_count",
        "extrapolated_arc_count",
        "extrapolated_arc_pct",
        "qa_count",
        "max_input_slew",
        "max_output_cap",
        "max_output_transition",
        "max_incr",
        "max_slew_above",
        "max_slew_above_ratio",
        "max_slew_above_ratio_example",
        "max_load_above",
        "max_load_above_ratio",
        "max_load_above_ratio_example",
    ]
    bench_fields = [
        "benchmark",
        "mode",
        "rc",
        "voltage",
        "arc_count",
        "data_arc_count",
        "extrapolated_arc_count",
        "extrapolated_arc_pct",
        "qa_count",
        "max_input_slew",
        "max_output_cap",
        "max_output_transition",
        "max_incr",
        "max_slew_above",
        "max_slew_above_ratio",
        "max_load_above",
        "max_load_above_ratio",
    ]
    write_csv(outdir / "cell_arc_summary.csv", cell_rows, cell_fields)
    write_csv(outdir / "benchmark_voltage_summary.csv", bench_rows, bench_fields)
    write_csv(
        outdir / "processed_reports.csv",
        processed_reports,
        ["report", "benchmark", "mode", "rc", "voltage", "arc_count", "extrapolated_arc_count"],
    )

    top_rows = [row for row in cell_rows if int(row.get("extrapolated_arc_count", 0) or 0) > 0][:20]
    with (outdir / "SUMMARY.md").open("w", encoding="utf-8") as f:
        f.write("# Slew/Load Coverage Summary\n\n")
        f.write(f"- Liberty: `{lib}`\n")
        f.write(f"- Parsed reports: {len(processed_reports)}\n")
        f.write(f"- Total arcs considered: {total_arcs}\n")
        f.write(f"- Data arcs considered: {total_data_arcs}\n")
        f.write(f"- Extrapolated/QA arcs: {total_extrap}\n")
        f.write(f"- Include clock arcs: {args.include_clock}\n\n")
        f.write("## Top Extrapolated Cell/Arc Rows\n\n")
        f.write("|benchmark|cell|arc|table|count|extrap %|max slew|slew/max|max cap|cap/max|\n")
        f.write("|---|---|---|---|---:|---:|---:|---:|---:|---:|\n")
        for row in top_rows:
            f.write(
                "|{benchmark}|{cell}|{arc}|{table_type}|{extrapolated_arc_count}|"
                "{extrapolated_arc_pct:.2f}|{max_input_slew}|{max_slew_above_ratio}|"
                "{max_output_cap}|{max_load_above_ratio}|\n".format(**row)
            )
        f.write("\n## Files\n\n")
        f.write("- `cell_arc_summary.csv`\n")
        f.write("- `benchmark_voltage_summary.csv`\n")
        f.write("- `extrapolation_records.csv`\n")
        if args.write_all_records:
            f.write("- `arc_slew_load_records.csv`\n")
        f.write("- `processed_reports.csv`\n")

    print(f"OUT_DIR={outdir}")
    print(f"REPORTS={len(processed_reports)}")
    print(f"TOTAL_ARCS={total_arcs}")
    print(f"EXTRAPOLATED_OR_QA_ARCS={total_extrap}")


if __name__ == "__main__":
    main()
