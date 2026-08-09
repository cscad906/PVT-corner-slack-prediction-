#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import division, print_function

import csv
import re
import sys
from collections import defaultdict


PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+)\s+key=(.+)$")
START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
END_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
PATH_GROUP_RE = re.compile(r"^\s*Path Group:\s+(.+)$")
PATH_TYPE_RE = re.compile(r"^\s*Path Type:\s+(.+)$")
SLACK_RE = re.compile(r"^\s*slack\s+\(([^)]+)\)\s+([-+0-9.]+)")
PIN_RE = re.compile(r"^\s+(\S+)\s+\(([^)]+)\)")
EDGE_RE = re.compile(r"\s([rf])\s*$")


def clean_num(value):
    try:
        # python3 의 str(float) 과 같은 표기를 얻으려면 2.7 에서는 repr 을 써야
        # 한다. 2.7 의 str(float) 은 유효숫자 12자리로 잘라 버린다.
        return repr(float(value))
    except ValueError:
        return ""


def parse_net_line(line):
    marker = " (net)"
    if marker not in line:
        return None
    net_name, rest = line.split(marker, 1)
    fields = rest.split()
    if len(fields) < 2:
        return None
    return {
        "victim_net": net_name.strip(),
        "fanout": clean_num(fields[0]),
        "cap": clean_num(fields[1]),
        "dist": clean_num(fields[2]) if len(fields) > 2 else "",
        "res": clean_num(fields[3]) if len(fields) > 3 else "",
        "cpin": clean_num(fields[4]) if len(fields) > 4 else "",
        "raw_net_line": line.strip(),
    }


def parse_pin(line):
    match = PIN_RE.match(line)
    if not match:
        return "", ""
    name = match.group(1)
    if name in {"clock", "data"}:
        return "", ""
    edge_match = EDGE_RE.search(line)
    return name, edge_match.group(1) if edge_match else ""


def add_arc(
    rows,
    pending_net,
    segment,
    arc_idx,
    segment_arc_idx,
    driver_pin,
    driver_edge,
    load_pin,
    load_edge,
):
    row = {
        "arc_idx": str(arc_idx),
        "path_segment": segment,
        "segment_arc_idx": str(segment_arc_idx),
        "victim_driver_pin": driver_pin,
        "victim_driver_edge": driver_edge,
        "victim_load_pin": load_pin,
        "victim_load_edge": load_edge,
    }
    row.update(pending_net)
    rows.append(row)


def flush_path(summary, rows, summaries, all_rows):
    if not summary:
        return
    summaries.append(summary.copy())
    for row in rows:
        row.update({
            "path_id": summary.get("path_id", ""),
            "path_key": summary.get("path_key", ""),
            "startpoint": summary.get("startpoint", ""),
            "endpoint": summary.get("endpoint", ""),
            "path_group": summary.get("path_group", ""),
            "path_type": summary.get("path_type", ""),
            "slack_status": summary.get("slack_status", ""),
            "slack": summary.get("slack", ""),
        })
        all_rows.append(row)


def parse_report(report):
    summaries = []
    all_rows = []
    summary = {}
    rows = []
    segment = ""
    last_pin = ""
    last_edge = ""
    pending_net = None
    arc_idx = 0
    segment_counts = defaultdict(int)
    seen_data_start = False

    with open(report, "r") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()
            path_match = PATH_RE.match(line)
            if path_match:
                flush_path(summary, rows, summaries, all_rows)
                summary = {
                    "path_id": path_match.group(1),
                    "path_key": path_match.group(2),
                    "startpoint": "",
                    "endpoint": "",
                    "path_group": "",
                    "path_type": "",
                    "slack_status": "",
                    "slack": "",
                }
                rows = []
                segment = ""
                last_pin = ""
                last_edge = ""
                pending_net = None
                arc_idx = 0
                segment_counts = defaultdict(int)
                seen_data_start = False
                continue

            if not summary:
                continue

            match = START_RE.match(line)
            if match:
                summary["startpoint"] = match.group(1)
                continue
            match = END_RE.match(line)
            if match:
                summary["endpoint"] = match.group(1)
                continue
            match = PATH_GROUP_RE.match(line)
            if match:
                summary["path_group"] = match.group(1).strip()
                continue
            match = PATH_TYPE_RE.match(line)
            if match:
                summary["path_type"] = match.group(1).strip()
                continue
            match = SLACK_RE.match(line)
            if match:
                summary["slack_status"] = match.group(1)
                summary["slack"] = match.group(2)
                continue

            if stripped.startswith("data arrival time"):
                segment = "after_data"
                last_pin = ""
                last_edge = ""
                pending_net = None
                continue

            if (
                stripped.startswith("clock reconvergence")
                or stripped.startswith("clock uncertainty")
                or stripped.startswith("library setup")
                or stripped.startswith("library hold")
                or stripped.startswith("data required")
            ):
                if segment == "capture_clock":
                    segment = "done"
                    last_pin = ""
                    last_edge = ""
                    pending_net = None
                continue

            if stripped.startswith("clock ") and segment in {"", "after_data"}:
                segment = "launch_clock" if not seen_data_start else "capture_clock"
                last_pin = ""
                last_edge = ""
                pending_net = None
                continue

            pin_name, pin_edge = parse_pin(line)
            if pin_name and not seen_data_start and "<-" in line:
                segment = "data"
                seen_data_start = True
                last_pin = pin_name
                last_edge = pin_edge
                pending_net = None
                continue

            if segment not in {"launch_clock", "data", "capture_clock"}:
                continue

            net_data = parse_net_line(line)
            if net_data is not None:
                pending_net = net_data
                continue

            if pin_name:
                if pending_net is not None and last_pin:
                    arc_idx += 1
                    segment_counts[segment] += 1
                    add_arc(
                        rows,
                        pending_net,
                        segment,
                        arc_idx,
                        segment_counts[segment],
                        last_pin,
                        last_edge,
                        pin_name,
                        pin_edge,
                    )
                    pending_net = None
                last_pin = pin_name
                last_edge = pin_edge

    flush_path(summary, rows, summaries, all_rows)
    return summaries, all_rows


def write_tsv(path, fieldnames, rows):
    with open(path, "wb") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    if len(sys.argv) != 4:
        print("usage: parse_setup_annotated_with_clock_segments.py <annotated_rpt> <path_summary.tsv> <path_victim_nets.tsv>", file=sys.stderr)
        return 2
    report = sys.argv[1]
    summary_out = sys.argv[2]
    victim_out = sys.argv[3]

    summaries, rows = parse_report(report)
    write_tsv(
        summary_out,
        ["path_id", "path_key", "startpoint", "endpoint", "path_group", "path_type", "slack_status", "slack"],
        summaries,
    )
    write_tsv(
        victim_out,
        [
            "path_id",
            "path_key",
            "startpoint",
            "endpoint",
            "path_group",
            "path_type",
            "slack_status",
            "slack",
            "arc_idx",
            "path_segment",
            "segment_arc_idx",
            "victim_net",
            "victim_driver_pin",
            "victim_driver_edge",
            "victim_load_pin",
            "victim_load_edge",
            "fanout",
            "cap",
            "dist",
            "res",
            "cpin",
            "raw_net_line",
        ],
        rows,
    )
    print("path_count={0}".format(len(summaries)))
    print("timing_net_arc_rows={0}".format(len(rows)))
    print("path_summary={0}".format(summary_out))
    print("path_victim_nets={0}".format(victim_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
