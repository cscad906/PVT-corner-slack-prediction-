#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+)\s+key=(.+)$")
START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
END_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
PATH_GROUP_RE = re.compile(r"^\s*Path Group:\s+(.+)$")
PATH_TYPE_RE = re.compile(r"^\s*Path Type:\s+(.+)$")
SLACK_RE = re.compile(r"^\s*slack\s+\(([^)]+)\)\s+([-+0-9.]+)")
PIN_RE = re.compile(r"^\s+(\S+)\s+\(([^)]+)\)")
EDGE_RE = re.compile(r"\s([rf])\s*$")


def clean_num(value: str) -> str:
    try:
        return str(float(value))
    except ValueError:
        return ""


def parse_net_line(line: str) -> Optional[Dict[str, str]]:
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


def parse_pin(line: str) -> Tuple[str, str]:
    match = PIN_RE.match(line)
    if not match:
        return "", ""
    name = match.group(1)
    if name in {"clock", "data"}:
        return "", ""
    edge_match = EDGE_RE.search(line)
    return name, edge_match.group(1) if edge_match else ""


def add_arc(
    rows: List[Dict[str, str]],
    pending_net: Dict[str, str],
    segment: str,
    arc_idx: int,
    segment_arc_idx: int,
    driver_pin: str,
    driver_edge: str,
    load_pin: str,
    load_edge: str,
) -> None:
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


def flush_path(summary: Dict[str, str], rows: List[Dict[str, str]], summaries: List[Dict[str, str]], emit) -> None:
    """경로 하나가 끝날 때 그 경로의 줄들을 **바로 내보낸다.**

    예전에는 all_rows 에 전부 쌓아 두고 마지막에 한 번에 썼다. 리포트가 크면
    net 행이 백만 줄이 넘고, 줄마다 dict 하나라 1.8GB 가 넘어간다. 코너를 여러
    개 동시에 돌리면 그만큼 곱해져 스왑으로 넘어가고, 그러면 병렬로 돌린
    의미가 없어진다. 경로 단위로 흘려 보내면 메모리가 경로 하나 크기로 준다.
    """
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
        emit(row)


def parse_report(report: Path, emit) -> List[Dict[str, str]]:
    summaries: List[Dict[str, str]] = []
    summary: Dict[str, str] = {}
    rows: List[Dict[str, str]] = []
    segment = ""
    last_pin = ""
    last_edge = ""
    pending_net: Optional[Dict[str, str]] = None
    arc_idx = 0
    segment_counts: defaultdict[str, int] = defaultdict(int)
    seen_data_start = False

    with report.open(errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()
            path_match = PATH_RE.match(line)
            if path_match:
                flush_path(summary, rows, summaries, emit)
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

    flush_path(summary, rows, summaries, emit)
    return summaries


def write_tsv(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: parse_setup_annotated_with_clock_segments.py <annotated_rpt> <path_summary.tsv> <path_victim_nets.tsv>", file=sys.stderr)
        return 2
    report = Path(sys.argv[1])
    summary_out = Path(sys.argv[2])
    victim_out = Path(sys.argv[3])

    # victim 쪽을 먼저 열어 두고, 경로가 끝날 때마다 그 줄들을 바로 쓴다.
    # 전부 모아 두면 큰 리포트에서 메모리가 GB 단위로 간다.
    victim_fields = [
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
    ]
    n_rows = 0
    with victim_out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=victim_fields, delimiter="\t",
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()

        def emit(row):
            nonlocal n_rows
            writer.writerow(row)
            n_rows += 1

        summaries = parse_report(report, emit)

    write_tsv(
        summary_out,
        ["path_id", "path_key", "startpoint", "endpoint", "path_group", "path_type", "slack_status", "slack"],
        summaries,
    )
    print(f"path_count={len(summaries)}")
    print(f"timing_net_arc_rows={n_rows}")
    print(f"path_summary={summary_out}")
    print(f"path_victim_nets={victim_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
