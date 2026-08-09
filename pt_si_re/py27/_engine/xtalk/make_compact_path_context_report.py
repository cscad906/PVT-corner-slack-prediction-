#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import division, print_function

import csv
import sys
from collections import OrderedDict


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


def read_tsv_by_key(path, key):
    with open(path, "rb") as fh:
        return dict((row[key], row) for row in csv.DictReader(fh, delimiter="\t"))


def read_segment_map(path):
    out = {}
    with open(path, "rb") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            key = (row["path_id"], row["arc_idx"], row["victim_net"], row["victim_driver_pin"], row["victim_load_pin"])
            out[key] = row["path_segment"]
    return out


def pf_to_ff(value):
    if not value:
        return ""
    try:
        return "%.6f" % (float(value) * 1000.0)
    except ValueError:
        return ""


def zero_if_blank(value):
    return value if value else "0"


def build_rows(
    feature_file,
    path_arc_file,
    victim_windows,
    aggressor_windows,
):
    segment_by_arc = read_segment_map(path_arc_file)
    by_path = OrderedDict()
    with open(feature_file, "rb") as fh:
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


def write_flat(by_path, out):
    count = 0
    with open(out, "wb") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for data in by_path.values():
            for row in data["rows"]:
                writer.writerow(row)
                count += 1
    return count


def write_by_path(by_path, out):
    with open(out, "wb") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, delimiter="\t", lineterminator="\n")
        for data in by_path.values():
            meta = data["meta"]
            fh.write("### FIXED_PATH idx={0} key={1}\n".format(meta["path_id"], meta["path_key"]))
            fh.write("# Startpoint: {0}\n".format(meta["startpoint"]))
            fh.write("# Endpoint: {0}\n".format(meta["endpoint"]))
            fh.write("# Path Group: {0}\n".format(meta["path_group"]))
            fh.write("# Path Type: {0}\n".format(meta["path_type"]))
            fh.write("# Slack: {0} {1}\n".format(meta["slack_status"], meta["slack"]))
            writer.writeheader()
            for row in data["rows"]:
                writer.writerow(row)
            fh.write("\n")


def main():
    if len(sys.argv) != 7:
        print(
            "usage: make_compact_path_context_report_with_segments.py "
            "<active_features.tsv> <path_arc_file.tsv> <victim_windows.tsv> <aggressor_windows.tsv> "
            "<compact_flat.tsv> <compact_by_path.rpt>",
            file=sys.stderr,
        )
        return 2
    feature_file = sys.argv[1]
    path_arc_file = sys.argv[2]
    victim_window_file = sys.argv[3]
    aggressor_window_file = sys.argv[4]
    flat_out = sys.argv[5]
    by_path_out = sys.argv[6]
    by_path = build_rows(
        feature_file,
        path_arc_file,
        read_tsv_by_key(victim_window_file, "victim_load_pin"),
        read_tsv_by_key(aggressor_window_file, "aggressor_net"),
    )
    rows = write_flat(by_path, flat_out)
    write_by_path(by_path, by_path_out)
    print("paths={0}".format(len(by_path)))
    print("rows={0}".format(rows))
    print("columns={0}".format(len(FIELDNAMES)))
    print("flat_out={0}".format(flat_out))
    print("by_path_out={0}".format(by_path_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
