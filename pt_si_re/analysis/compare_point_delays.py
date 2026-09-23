#!/usr/bin/env python3
"""Compare PrimeTime point-level Incr delays between scaling and ground truth.

Usage:
    python3 analysis/compare_point_delays.py \
        /absolute/path/scaling.rpt \
        /absolute/path/ground_truth.rpt \
        --output-dir point_delay_comparison

The reports must contain identical ``### FIXED_PATH idx=... key=...`` blocks and
must be generated with ``report_timing -nosplit -path_type full_clock_expanded``.
Only the ``Incr`` column is compared. The cumulative ``Path`` column is never
used because a different ideal clock edge shifts every cumulative value.

Classification is based on report order. An increment between two consecutive
pins of the same instance is labeled ``cell``. An increment arriving at a new
instance is labeled ``net``. The latter is the net-side sink-pin increment in a
PrimeTime report; it is not a direct extraction of raw SPEF RC delay.
"""

import argparse
import json
import math
import re
from pathlib import Path


PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+)\s+key=(.*)$")
STARTPOINT_RE = re.compile(r"^\s*Startpoint:\s+(.+?)(?:\s+\(|\s*$)")
ARRIVAL_RE = re.compile(r"^\s*data\s+arrival\s+time\b", re.IGNORECASE)
CELL_POINT_RE = re.compile(r"^(.*?)\s+\(([^()]*)\)\s*(?:<-)?\s*$")
NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
NS_TO_PS = 1000.0


def instance_name(point):
    return point.rsplit("/", 1)[0] if "/" in point else point


def parse_report(path):
    paths = {}
    current_idx = None
    current_key = None
    current_rows = []
    startpoint = None
    section = "launch_clock"
    previous_instance = None
    columns = None

    def finish():
        if current_key is None:
            return
        if current_key in paths:
            raise ValueError("duplicate path key in {}: {}".format(path, current_key))
        paths[current_key] = {"idx": current_idx, "points": list(current_rows)}

    with path.open(errors="ignore") as report:
        for line in report:
            marker = PATH_RE.match(line.rstrip("\n"))
            if marker:
                finish()
                current_idx = int(marker.group(1))
                current_key = marker.group(2).strip()
                current_rows = []
                startpoint = None
                section = "launch_clock"
                previous_instance = None
                columns = None
                continue
            if current_key is None:
                continue

            match = STARTPOINT_RE.match(line)
            if match:
                startpoint = match.group(1).strip()
                continue

            if ARRIVAL_RE.match(line):
                section = "capture_clock"
                previous_instance = None
                continue

            if "Point" in line and "Incr" in line and "Path" in line:
                try:
                    columns = {
                        "point_end": line.index("Fanout"),
                    }
                except ValueError:
                    columns = None
                continue
            if columns is None or len(line) <= columns["point_end"]:
                continue

            point_field = line[:columns["point_end"]].strip()
            point_match = CELL_POINT_RE.match(point_field)
            if not point_match:
                continue
            point = point_match.group(1).strip()
            library_cell = point_match.group(2).strip()
            if library_cell.lower() in ("in", "out", "net"):
                previous_instance = None
                continue
            # Cell/pin rows end with: Trans Incr [&] Path [r|f]. Header
            # labels are centered and are not the actual numeric boundaries.
            tail_numbers = NUMBER_RE.findall(line[columns["point_end"]:])
            if len(tail_numbers) < 3:
                continue
            increment = float(tail_numbers[-2])

            instance = instance_name(point)
            if section != "capture_clock" and (
                    "<-" in line or (startpoint is not None and instance == startpoint and
                                     previous_instance == instance)):
                section = "data"
            kind = "cell" if previous_instance == instance else "net"
            current_rows.append({
                "point": point,
                "library_cell": library_cell,
                "increment_ns": increment,
                "section": section,
                "kind": kind,
            })
            previous_instance = instance

    finish()
    if not paths:
        raise ValueError("no fixed-path blocks found in {}".format(path))
    return paths


def index_points(points):
    indexed = {}
    occurrences = {}
    for point in points:
        name = point["point"]
        occurrence = occurrences.get(name, 0) + 1
        occurrences[name] = occurrence
        indexed[(name, occurrence)] = point
    return indexed


def metric(values):
    if not values:
        return {"count": 0, "mae_ps": None, "rmse_ps": None,
                "bias_ps": None, "p95_abs_ps": None, "max_abs_ps": None}
    ordered = sorted(abs(value) for value in values)
    p95_index = max(0, int(math.ceil(len(ordered) * 0.95)) - 1)
    return {
        "count": len(values),
        "mae_ps": sum(ordered) / len(ordered),
        "rmse_ps": math.sqrt(sum(value * value for value in values) / len(values)),
        "bias_ps": sum(values) / len(values),
        "p95_abs_ps": ordered[p95_index],
        "max_abs_ps": ordered[-1],
    }


def compare(scaled, truth):
    rows = []
    missing_scaled = 0
    missing_truth = 0
    shared_paths = sorted(set(scaled) & set(truth))
    for path_key in shared_paths:
        scaled_points = index_points(scaled[path_key]["points"])
        truth_points = index_points(truth[path_key]["points"])
        for point_key in sorted(set(scaled_points) | set(truth_points)):
            pred = scaled_points.get(point_key)
            gt = truth_points.get(point_key)
            if pred is None:
                missing_scaled += 1
                continue
            if gt is None:
                missing_truth += 1
                continue
            scaled_ps = pred["increment_ns"] * NS_TO_PS
            truth_ps = gt["increment_ns"] * NS_TO_PS
            error = scaled_ps - truth_ps
            rows.append({
                "idx": truth[path_key]["idx"],
                "path_key": path_key,
                "point": point_key[0],
                "occurrence": point_key[1],
                "section": gt["section"] if pred["section"] == gt["section"] else "mismatch",
                "kind": gt["kind"] if pred["kind"] == gt["kind"] else "mismatch",
                "scaled_library_cell": pred["library_cell"],
                "ground_truth_library_cell": gt["library_cell"],
                "scaled_incr_ps": scaled_ps,
                "ground_truth_incr_ps": truth_ps,
                "error_ps": error,
                "abs_error_ps": abs(error),
                "library_cell_mismatch": pred["library_cell"] != gt["library_cell"],
            })

    summary = {
        "scaled_paths": len(scaled),
        "ground_truth_paths": len(truth),
        "shared_paths": len(shared_paths),
        "scaled_only_paths": len(set(scaled) - set(truth)),
        "ground_truth_only_paths": len(set(truth) - set(scaled)),
        "matched_points": len(rows),
        "missing_scaled_points": missing_scaled,
        "missing_ground_truth_points": missing_truth,
        "classification_mismatches": sum(row["kind"] == "mismatch" for row in rows),
        "section_mismatches": sum(row["section"] == "mismatch" for row in rows),
        "library_cell_mismatches": sum(row["library_cell_mismatch"] for row in rows),
        "all": metric([row["error_ps"] for row in rows]),
        "cell": metric([row["error_ps"] for row in rows if row["kind"] == "cell"]),
        "net": metric([row["error_ps"] for row in rows if row["kind"] == "net"]),
    }
    for section in ("launch_clock", "data", "capture_clock"):
        summary[section] = metric([
            row["error_ps"] for row in rows if row["section"] == section])
    return rows, summary


def number(value):
    return "NA" if value is None else "{:.3f}".format(value)


def metric_line(name, values):
    return (
        "{:<15}: points={} MAE={} ps P95={} ps max={} ps bias={} ps".format(
            name, values["count"], number(values["mae_ps"]),
            number(values["p95_abs_ps"]), number(values["max_abs_ps"]),
            number(values["bias_ps"])))


def write_details(path, rows):
    ordered = sorted(rows, key=lambda row: row["abs_error_ps"], reverse=True)
    with path.open("w") as output:
        output.write("# Values are point-level PrimeTime Incr delays in ps.\n")
        output.write("# Sorted by absolute error descending.\n")
        output.write(
            "{:>7} {:<14} {:<9} {:>12} {:>12} {:>12} {:>12} {}\n".format(
                "idx", "section", "kind", "GT_incr", "scaled_incr",
                "error", "abs_error", "point"))
        for row in ordered:
            output.write(
                "{:>7} {:<14} {:<9} {:>12.6f} {:>12.6f} {:+12.6f} "
                "{:>12.6f} {}\n".format(
                    row["idx"], row["section"], row["kind"],
                    row["ground_truth_incr_ps"], row["scaled_incr_ps"],
                    row["error_ps"], row["abs_error_ps"], row["point"]))


def share_line(summary):
    return (
        "POINT_SHARE cell={}/{}/{}ps net={}/{}/{}ps data={}/{}/{}ps "
        "launch={}ps capture={}ps "
        "matched={} missing={} class_mismatch={} section_mismatch={} lib_mismatch={}".format(
            number(summary["cell"]["mae_ps"]), number(summary["cell"]["p95_abs_ps"]),
            number(summary["cell"]["max_abs_ps"]),
            number(summary["net"]["mae_ps"]), number(summary["net"]["p95_abs_ps"]),
            number(summary["net"]["max_abs_ps"]),
            number(summary["data"]["mae_ps"]), number(summary["data"]["p95_abs_ps"]),
            number(summary["data"]["max_abs_ps"]),
            number(summary["launch_clock"]["mae_ps"]),
            number(summary["capture_clock"]["mae_ps"]),
            summary["matched_points"],
            summary["missing_scaled_points"] + summary["missing_ground_truth_points"],
            summary["classification_mismatches"], summary["section_mismatches"],
            summary["library_cell_mismatches"]))


def write_summary(path, summary, scaled_path, truth_path):
    lines = [
        "PrimeTime point Incr delay comparison",
        "scaled report       : {}".format(scaled_path.resolve()),
        "ground truth report : {}".format(truth_path.resolve()),
        "shared paths        : {}".format(summary["shared_paths"]),
        "matched points      : {}".format(summary["matched_points"]),
        "missing points      : {}".format(
            summary["missing_scaled_points"] + summary["missing_ground_truth_points"]),
        "classification mismatches: {}".format(summary["classification_mismatches"]),
        "section mismatches       : {}".format(summary["section_mismatches"]),
        "library-cell mismatches  : {}".format(summary["library_cell_mismatches"]),
        metric_line("all points", summary["all"]),
        metric_line("cell", summary["cell"]),
        metric_line("net", summary["net"]),
        metric_line("launch clock", summary["launch_clock"]),
        metric_line("data", summary["data"]),
        metric_line("capture clock", summary["capture_clock"]),
        "",
        "COPY THIS RESULT",
        share_line(summary),
    ]
    path.write_text("\n".join(lines) + "\n")


def safe_name(path):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._")
    return name or "target_corner"


def create_result_dir(root, name):
    root.mkdir(parents=True, exist_ok=True)
    number_value = 1
    while True:
        candidate = root / (name if number_value == 1 else "{}_run{}".format(name, number_value))
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            number_value += 1


def main():
    parser = argparse.ArgumentParser(
        description="Compare point-level PrimeTime Incr delays in two fixed-path reports.")
    parser.add_argument("scaled_rpt", type=Path)
    parser.add_argument("ground_truth_rpt", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("point_delay_comparison"))
    args = parser.parse_args()
    for path in (args.scaled_rpt, args.ground_truth_rpt):
        if not path.is_file():
            parser.error("file not found: {}".format(path))

    scaled = parse_report(args.scaled_rpt)
    truth = parse_report(args.ground_truth_rpt)
    rows, summary = compare(scaled, truth)
    if not rows:
        parser.error("no matching point increments found")

    result_dir = create_result_dir(args.output_dir, safe_name(args.ground_truth_rpt))
    details_path = result_dir / "point_delay_errors.txt"
    summary_path = result_dir / "point_delay_summary.txt"
    json_path = result_dir / "point_delay_summary.json"
    write_details(details_path, rows)
    write_summary(summary_path, summary, args.scaled_rpt, args.ground_truth_rpt)
    with json_path.open("w") as output:
        json.dump(summary, output, indent=2)

    print("=== PrimeTime point Incr delay comparison ===")
    print(metric_line("all points", summary["all"]))
    print(metric_line("cell", summary["cell"]))
    print(metric_line("net", summary["net"]))
    print(metric_line("launch clock", summary["launch_clock"]))
    print(metric_line("data", summary["data"]))
    print(metric_line("capture clock", summary["capture_clock"]))
    print("matched points : {}".format(summary["matched_points"]))
    print("missing points : {}".format(
        summary["missing_scaled_points"] + summary["missing_ground_truth_points"]))
    print("details        : {}".format(details_path))
    print("summary        : {}".format(summary_path))
    print("")
    print("=== COPY THIS RESULT ===")
    print(share_line(summary))


if __name__ == "__main__":
    main()
