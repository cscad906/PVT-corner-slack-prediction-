#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Recover a fixed-path list from an existing ground-truth timing report.

QUICK START
    python3 analysis/recover_fixed_paths_from_ground_truth.py \
        /path/to/SSPG_0p57V_25C_RCMAX_setup.rpt

DEFAULT OUTPUT
    fixed_paths_SSPG_0p57V_25C_RCMAX_setup.tcl

    Existing files are never overwritten. A repeated run creates _run2, _run3,
    and so on. Use --output only when an exact output path is needed.

HOW IT WORKS
    Every resolved ### FIXED_PATH block is parsed. The original marker key is
    preserved, and the complete data-pin chain and rise/fall directions are
    recovered from the full_clock_expanded timing table. Path Type max/min is
    detected automatically and written as DTYPE max/min.

LIMIT
    A block without Startpoint, Endpoint, slack, or a complete data-pin chain
    cannot be recovered and is skipped. The terminal summary reports every
    skip reason. The recovered file is intended for FIXED_PATH_FILE in
    pt/run_scaling_after_restore.tcl.

RUNTIME
    Python 3.6 or newer. No external package is required.
"""

import argparse
import re
from pathlib import Path


MARK_RE = re.compile(r"^\ufeff?\s*### FIXED_PATH idx=(\d+)\s+key=(.*)$")
START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
END_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
TYPE_RE = re.compile(r"^\s*Path Type:\s*(max|min)\s*$", re.IGNORECASE)
SLACK_RE = re.compile(
    r"^\s*slack\s*\((?:MET|VIOLATED)[^)]*\)\s*"
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)
PIN_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")
EDGE_RE = re.compile(r"\s([rf])\s*$")
STOP = ("data arrival time", "required time", "clock uncertainty",
        "library setup time", "library hold time", "slack ")


def iter_blocks(report_path):
    current = None
    lines = []
    with report_path.open("r", errors="ignore") as report:
        for line in report:
            marker = MARK_RE.match(line.rstrip("\r\n"))
            if marker:
                if current is not None:
                    yield current[0], current[1], lines
                current = (int(marker.group(1)), marker.group(2).strip())
                lines = []
            elif current is not None:
                lines.append(line)
    if current is not None:
        yield current[0], current[1], lines


def data_pin_chain(lines, start_inst, end_inst):
    items = []
    for line in lines:
        if line.strip().lower().startswith(STOP):
            break
        match = PIN_RE.match(line)
        if not match or match.group(2).lower() == "net":
            continue
        edge = EDGE_RE.search(line.rstrip())
        items.append((match.group(1), edge.group(1) if edge else ""))

    start_at = None
    for index, (name, _) in enumerate(items):
        if name.rsplit("/", 1)[0] == start_inst:
            start_at = index

    end_at = None
    for index, (name, _) in enumerate(items):
        if name.rsplit("/", 1)[0] == end_inst and (start_at is None or index > start_at):
            end_at = index
            break

    if start_at is None or end_at is None or end_at <= start_at:
        return []
    return items[start_at:end_at + 1]


def recover_block(index, key, lines):
    starts = [match.group(1) for line in lines for match in [START_RE.match(line)] if match]
    ends = [match.group(1) for line in lines for match in [END_RE.match(line)] if match]
    types = [match.group(1).lower() for line in lines for match in [TYPE_RE.match(line)] if match]
    has_slack = any(SLACK_RE.match(line) for line in lines)

    if len(starts) != 1:
        return None, "missing_or_multiple_startpoint"
    if len(ends) != 1:
        return None, "missing_or_multiple_endpoint"
    if not has_slack:
        return None, "missing_slack"
    if not types:
        return None, "missing_path_type"
    if len(set(types)) != 1:
        return None, "mixed_path_type_in_block"

    chain = data_pin_chain(lines, starts[0], ends[0])
    if len(chain) < 2:
        return None, "missing_data_pin_chain"
    pins = tuple(pin for pin, _ in chain)
    edges = tuple(edge for _, edge in chain)
    if not all(edge in ("r", "f") for edge in edges):
        edges = ()
    return {
        "index": index,
        "key": key,
        "path_type": types[0],
        "from": pins[0],
        "to": pins[-1],
        "through": pins[1:-1],
        "edges": edges,
    }, None


def tcl_word(value):
    if "\n" in value or "\r" in value or "{" in value or "}" in value:
        raise ValueError("Tcl-unsafe brace or newline in object name: %r" % value)
    return "{" + value + "}"


def tcl_list(values):
    return "{" + " ".join(tcl_word(value) for value in values) + "}"


def write_fixed_paths(output, source, dtype, records, skipped):
    output.write("# Recovered from ground-truth report: %s\n" % source.resolve())
    output.write("# Recovered paths: %d; unrecoverable blocks: %d\n" %
                 (len(records), sum(skipped.values())))
    output.write("# Use this file as FIXED_PATH_FILE in run_scaling_after_restore.tcl.\n\n")
    output.write('set DTYPE "%s"\n' % dtype)
    output.write("set FIXED_PATHS {\n")
    for record in records:
        fields = [tcl_word(record["key"]), tcl_word(record["from"]),
                  tcl_word(record["to"]), tcl_list(record["through"])]
        if record["edges"]:
            fields.append(tcl_list(record["edges"]))
        output.write("  {" + " ".join(fields) + "}\n")
    output.write("}\n")


def safe_stem(path):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._")
    return name or "ground_truth"


def open_output(requested, report_path):
    if requested is not None:
        requested.parent.mkdir(parents=True, exist_ok=True)
        return requested.open("x", encoding="utf-8"), requested

    stem = "fixed_paths_" + safe_stem(report_path)
    run_number = 1
    while True:
        suffix = "" if run_number == 1 else "_run%d" % run_number
        candidate = Path(stem + suffix + ".tcl")
        try:
            return candidate.open("x", encoding="utf-8"), candidate
        except FileExistsError:
            run_number += 1


def main():
    parser = argparse.ArgumentParser(
        description="Ground-truth report\uc5d0\uc11c PT scaling\uc6a9 fixed_paths.tcl\uc744 \ubcf5\uc6d0\ud569\ub2c8\ub2e4.")
    parser.add_argument("ground_truth_rpt", type=Path,
                        help="### FIXED_PATH block\uc774 \uc788\ub294 ground-truth .rpt")
    parser.add_argument("--output", type=Path,
                        help="\ucd9c\ub825 Tcl \uacbd\ub85c (\uc0dd\ub7b5 \uc2dc report \uc774\ub984\uc73c\ub85c \uc790\ub3d9 \uc0dd\uc131)")
    args = parser.parse_args()

    if not args.ground_truth_rpt.is_file():
        parser.error("file not found: %s" % args.ground_truth_rpt)
    if args.output is not None and args.output.exists():
        parser.error("output already exists; choose another path: %s" % args.output)

    records = []
    skipped = {}
    seen_keys = set()
    total_blocks = 0
    for index, key, lines in iter_blocks(args.ground_truth_rpt):
        total_blocks += 1
        if key in seen_keys:
            parser.error("duplicate FIXED_PATH key: %s" % key)
        seen_keys.add(key)
        record, reason = recover_block(index, key, lines)
        if record is None:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            records.append(record)

    if total_blocks == 0:
        parser.error("no '### FIXED_PATH idx=... key=...' blocks found")
    if not records:
        parser.error("no resolved fixed path could be recovered")
    path_types = set(record["path_type"] for record in records)
    if len(path_types) != 1:
        parser.error("mixed Path Type values in report: %s" % sorted(path_types))
    dtype = next(iter(path_types))

    try:
        output, output_path = open_output(args.output, args.ground_truth_rpt)
        with output:
            write_fixed_paths(output, args.ground_truth_rpt, dtype, records, skipped)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print("=== Recover fixed paths from ground truth ===")
    print("source report       : %s" % args.ground_truth_rpt)
    print("path type / DTYPE   : %s" % dtype)
    print("FIXED_PATH blocks   : %d" % total_blocks)
    print("recovered paths     : %d" % len(records))
    print("unrecoverable blocks: %d" % sum(skipped.values()))
    for reason, count in sorted(skipped.items()):
        print("  %-30s %d" % (reason, count))
    print("output Tcl          : %s" % output_path.resolve())
    print("")
    print("Set this path in pt/run_scaling_after_restore.tcl:")
    print('set FIXED_PATH_FILE "%s"' % output_path.resolve())
    print("Set ANALYSIS to setup for max or hold for min.")


if __name__ == "__main__":
    main()
