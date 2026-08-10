#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Tuple


FIELDNAMES = [
    "path_segment",
    "victim_net",
    "aggressor_net",
    "crosstalk_delta",
    "aggressor_bump",
    "number_of_aggressors",
    "victim_load_pin",
    "victim_load_min_arrival",
    "victim_load_max_arrival",
    "aggressor_driver_pin",
    "aggressor_driver_min_arrival",
    "aggressor_driver_max_arrival",
    "aggressor_driver_slew_max",
    "coupling_cap_ff",
]


def read_tsv_by_key(path: Path, key: str) -> Dict[str, Dict[str, str]]:
    with path.open(newline="") as fh:
        return {row[key]: row for row in csv.DictReader(fh, delimiter="\t")}


def read_segment_map(path: Path) -> Dict[Tuple[str, str, str, str, str], str]:
    out: Dict[Tuple[str, str, str, str, str], str] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            key = (row["path_id"], row["arc_idx"], row["victim_net"], row["victim_driver_pin"], row["victim_load_pin"])
            out[key] = row["path_segment"]
    return out


def pf_to_ff(value: str) -> str:
    if not value:
        return ""
    try:
        return f"{float(value) * 1000.0:.6f}"
    except ValueError:
        return ""


def zero_if_blank(value: str) -> str:
    return value if value else "0"


def build_rows(
    feature_file: Path,
    path_arc_file: Path,
    victim_windows: Dict[str, Dict[str, str]],
    aggressor_windows: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, object]]:
    segment_by_arc = read_segment_map(path_arc_file)
    by_path: Dict[str, Dict[str, object]] = OrderedDict()
    with feature_file.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            path_id = row["path_id"]
            if path_id not in by_path:
                by_path[path_id] = {
                    "meta": {
                        "path_id": path_id,
                        "path_key": row["path_key"],
                        "startpoint": row["startpoint"],
                        "endpoint": row["endpoint"],
                        "path_group": row["path_group"],
                        "path_type": row["path_type"],
                        "slack_status": row["slack_status"],
                        "slack": row["slack"],
                    },
                    "rows": [],
                }
            arc_key = (row["path_id"], row["arc_idx"], row["victim_net"], row["victim_driver_pin"], row["victim_load_pin"])
            victim_win = victim_windows.get(row["victim_load_pin"], {})
            aggressor_win = aggressor_windows.get(row["aggressor_net"], {}) if row["aggressor_net"] else {}
            by_path[path_id]["rows"].append({
                "path_segment": segment_by_arc.get(arc_key, ""),
                "victim_net": row["victim_net"],
                "aggressor_net": zero_if_blank(row["aggressor_net"]),
                "crosstalk_delta": zero_if_blank(row["crosstalk_delta"]),
                "aggressor_bump": zero_if_blank(row["aggressor_switching_bump_ratio_vdd"]),
                "number_of_aggressors": zero_if_blank(row["number_of_aggressors"]),
                "victim_load_pin": row["victim_load_pin"],
                "victim_load_min_arrival": victim_win.get("victim_load_min_arrival", ""),
                "victim_load_max_arrival": victim_win.get("victim_load_max_arrival", ""),
                "aggressor_driver_pin": zero_if_blank(aggressor_win.get("aggressor_driver_pin", "")),
                "aggressor_driver_min_arrival": zero_if_blank(aggressor_win.get("aggressor_driver_min_arrival", "")),
                "aggressor_driver_max_arrival": zero_if_blank(aggressor_win.get("aggressor_driver_max_arrival", "")),
                "aggressor_driver_slew_max": zero_if_blank(aggressor_win.get("aggressor_driver_slew_max", "")),
                "coupling_cap_ff": zero_if_blank(pf_to_ff(row["aggressor_coupling_cap_pf"])),
            })
    return by_path


def write_flat(by_path: Dict[str, Dict[str, object]], out: Path) -> int:
    count = 0
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for data in by_path.values():
            for row in data["rows"]:
                writer.writerow(row)
                count += 1
    return count


def write_by_path(by_path: Dict[str, Dict[str, object]], out: Path) -> None:
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, delimiter="\t", lineterminator="\n")
        for data in by_path.values():
            meta = data["meta"]
            fh.write(f"### FIXED_PATH idx={meta['path_id']} key={meta['path_key']}\n")
            fh.write(f"# Startpoint: {meta['startpoint']}\n")
            fh.write(f"# Endpoint: {meta['endpoint']}\n")
            fh.write(f"# Path Group: {meta['path_group']}\n")
            fh.write(f"# Path Type: {meta['path_type']}\n")
            fh.write(f"# Slack: {meta['slack_status']} {meta['slack']}\n")
            writer.writeheader()
            for row in data["rows"]:
                writer.writerow(row)
            fh.write("\n")


def main() -> int:
    if len(sys.argv) != 7:
        print(
            "usage: make_compact_path_context_report_with_segments.py "
            "<active_features.tsv> <path_arc_file.tsv> <victim_windows.tsv> <aggressor_windows.tsv> "
            "<compact_flat.tsv> <compact_by_path.rpt>",
            file=sys.stderr,
        )
        return 2
    feature_file = Path(sys.argv[1])
    path_arc_file = Path(sys.argv[2])
    victim_window_file = Path(sys.argv[3])
    aggressor_window_file = Path(sys.argv[4])
    flat_out = Path(sys.argv[5])
    by_path_out = Path(sys.argv[6])
    by_path = build_rows(
        feature_file,
        path_arc_file,
        read_tsv_by_key(victim_window_file, "victim_load_pin"),
        read_tsv_by_key(aggressor_window_file, "aggressor_net"),
    )
    rows = write_flat(by_path, flat_out)
    write_by_path(by_path, by_path_out)
    print(f"paths={len(by_path)}")
    print(f"rows={rows}")
    print(f"columns={len(FIELDNAMES)}")
    print(f"flat_out={flat_out}")
    print(f"by_path_out={by_path_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
