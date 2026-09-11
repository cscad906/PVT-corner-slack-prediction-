#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Read-only completion check for every corner under a round2 directory.

This is deliberately separate from 4_all_corners.py.  It never runs a stage,
creates a file, removes a file, or changes a timestamp.

Examples:
    python3 4_check_results.py --root round2 --phase 3 --mode hold
    python3 4_check_results.py --root round2 --phase 1

Status meanings:
    OK       final products and cross-file counts are consistent
    PARTIAL  some output exists, but a file/count/order check failed
    MISSING  no output for that group exists
"""
import argparse
import csv
import os
import sys


CPIN_COLS = ("line_no", "net", "recv_pin", "cpin")
DISTRES_COLS = ("line_no", "net", "dist", "res")
VICTIM_COLS = ("path_id", "victim_net", "victim_driver_pin",
               "victim_load_pin")
SUMMARY_COLS = ("path_id", "startpoint", "endpoint")
ACTIVE_COLS = ("path_id", "analysis_type", "victim_net")
CONTEXT_COLS = ("context_id", "report_status")
FLAT_COLS = (
    "path_segment", "victim_net", "aggressor_net", "crosstalk_delta",
    "aggressor_bump", "number_of_aggressors", "victim_load_pin",
    "victim_load_min_arrival", "victim_load_max_arrival",
    "aggressor_driver_pin", "aggressor_driver_min_arrival",
    "aggressor_driver_max_arrival", "aggressor_driver_slew_max",
    "coupling_cap_ff",
)


def file_nonempty(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0


def ends_with_newline(path):
    if not file_nonempty(path):
        return False
    with open(path, "rb") as fh:
        fh.seek(-1, os.SEEK_END)
        return fh.read(1) == b"\n"


def tsv_info(path, required, need_rows=True, collect=None):
    """Return (ok, row_count, collected_values, reason)."""
    if not os.path.isfile(path):
        return False, 0, set(), "missing %s" % path
    if os.path.getsize(path) == 0:
        return False, 0, set(), "empty %s" % path
    if not ends_with_newline(path):
        return False, 0, set(), "last line is incomplete: %s" % path

    values = set()
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="surrogateescape",
                  newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            fields = tuple(reader.fieldnames or ())
            missing = [name for name in required if name not in fields]
            if missing:
                return (False, 0, set(), "missing columns %s: %s"
                        % (",".join(missing), path))
            for row in reader:
                count += 1
                if None in row or any(value is None for value in row.values()):
                    return (False, count, values,
                            "broken TSV row %d: %s" % (count + 1, path))
                if collect:
                    value = row.get(collect, "").strip()
                    if value:
                        values.add(value)
    except (OSError, UnicodeError, csv.Error) as exc:
        return False, count, values, "cannot parse %s (%s)" % (path, exc)

    if need_rows and count == 0:
        return False, 0, values, "header only: %s" % path
    return True, count, values, ""


def count_prefix(path, prefix):
    count = 0
    with open(path, "rb") as fh:
        for line in fh:
            if line.startswith(prefix):
                count += 1
    return count


def part_files(directory):
    found = []
    for base, _dirs, files in os.walk(directory):
        for name in files:
            if name.endswith(".part"):
                found.append(os.path.join(base, name))
    return sorted(found)


def group_status(has_any, problems):
    if problems:
        return "PARTIAL" if has_any else "MISSING"
    return "OK"


def check_annotation(name, directory, root):
    cpin = os.path.join(directory, "cpin.tsv")
    distres = os.path.join(directory, "distres.tsv")
    annotated = os.path.join(directory, name + "_fixed_annotated.txt")
    products = (cpin, distres, annotated)
    has_any = any(os.path.exists(path) for path in products)
    problems = []

    for path, cols in ((cpin, CPIN_COLS), (distres, DISTRES_COLS)):
        ok, _rows, _values, why = tsv_info(path, cols)
        if not ok:
            problems.append(why)

    if not os.path.isfile(annotated):
        problems.append("missing %s" % annotated)
    elif os.path.getsize(annotated) == 0:
        problems.append("empty %s" % annotated)

    root_parts = [path for path in part_files(directory)
                  if os.path.dirname(path) == directory]
    for path in root_parts:
        problems.append("unfinished .part: %s" % path)
    has_any = has_any or bool(root_parts)

    clean = [why.replace(root + os.sep, "") for why in problems]
    return group_status(has_any, clean), clean


def check_crosstalk(name, directory, root, wanted_mode):
    work = os.path.join(directory, "xtalk")
    victim = os.path.join(work, "path_victim_nets.tsv")
    summary = os.path.join(work, "path_summary.tsv")
    context = os.path.join(work, "context_summary.tsv")
    active = os.path.join(work, "active_features.tsv")
    vpins = os.path.join(work, "victim_load_pins.txt")
    anets = os.path.join(work, "aggressor_nets.txt")
    flat = os.path.join(work, "compact_flat.tsv")
    final = os.path.join(
        directory, name + ".path_context_si_compact.by_path.rpt")
    products = (victim, summary, context, active, vpins, anets, flat, final)
    has_any = any(os.path.exists(path) for path in products)
    problems = []

    checks = {}
    for label, path, cols, collect in (
            ("victim", victim, VICTIM_COLS, "path_id"),
            ("summary", summary, SUMMARY_COLS, "path_id"),
            ("context", context, CONTEXT_COLS, None),
            ("active", active, ACTIVE_COLS, "path_id"),
            ("flat", flat, FLAT_COLS, None)):
        checks[label] = tsv_info(path, cols, collect=collect)
        if not checks[label][0]:
            problems.append(checks[label][3])

    if not file_nonempty(vpins):
        problems.append(("empty " if os.path.isfile(vpins) else "missing ") + vpins)
    if not os.path.isfile(anets):
        problems.append("missing %s" % anets)
    elif not ends_with_newline(anets) and os.path.getsize(anets) > 0:
        problems.append("last line is incomplete: %s" % anets)

    if not file_nonempty(final):
        problems.append(("empty " if os.path.isfile(final) else "missing ") + final)
    elif not ends_with_newline(final):
        problems.append("last line is incomplete: %s" % final)

    if checks["victim"][0] and checks["summary"][0]:
        victim_ids = checks["victim"][2]
        summary_ids = checks["summary"][2]
        if not victim_ids.issubset(summary_ids):
            problems.append("5a path IDs disagree (victim is not a subset of summary)")
        if os.path.getmtime(summary) < os.path.getmtime(victim):
            problems.append("5a summary is older than victim output")

    if checks["active"][0]:
        if file_nonempty(vpins) and os.path.getmtime(vpins) < os.path.getmtime(active):
            problems.append("5b victim request is older than active output")
        if os.path.isfile(anets) and os.path.getmtime(anets) < os.path.getmtime(active):
            problems.append("5b aggressor request is older than active output")
        if wanted_mode:
            mode_ok, _n, modes, _why = tsv_info(
                active, ACTIVE_COLS, collect="analysis_type")
            if mode_ok and modes != {wanted_mode}:
                problems.append("mode is %s, expected %s"
                                % (",".join(sorted(modes)) or "blank",
                                   wanted_mode))

    if checks["active"][0] and checks["flat"][0]:
        active_rows = checks["active"][1]
        flat_rows = checks["flat"][1]
        if active_rows != flat_rows:
            problems.append("5c row mismatch: active=%d flat=%d"
                            % (active_rows, flat_rows))

    if checks["active"][0] and file_nonempty(final):
        active_paths = len(checks["active"][2])
        final_paths = count_prefix(final, b"### FIXED_PATH ")
        if active_paths != final_paths:
            problems.append("5c path mismatch: active=%d final=%d"
                            % (active_paths, final_paths))
        if file_nonempty(flat) and os.path.getmtime(final) < os.path.getmtime(flat):
            problems.append("5c by-path report is older than flat output")

    cross_parts = part_files(work) if os.path.isdir(work) else []
    for path in cross_parts:
        problems.append("unfinished .part: %s" % path)
    has_any = has_any or bool(cross_parts)

    clean = []
    for why in problems:
        clean.append(why.replace(root + os.sep, ""))
    return group_status(has_any, clean), clean


def corner_dirs(root):
    return [(name, os.path.join(root, name))
            for name in sorted(os.listdir(root))
            if not name.startswith(".")
            and os.path.isdir(os.path.join(root, name))]


def main():
    parser = argparse.ArgumentParser(
        description="Read-only per-corner completion and partial-file check")
    parser.add_argument("--root", required=True,
                        help="directory containing corner directories")
    parser.add_argument("--phase", choices=("1", "2", "3"), default="3",
                        help="1=annotation, 2=crosstalk, 3=both (default)")
    parser.add_argument("--mode", choices=("setup", "hold"), default=None,
                        help="also verify active_features analysis_type")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("ERROR: root directory does not exist: %s" % root)
        return 2
    corners = corner_dirs(root)
    if not corners:
        print("ERROR: no corner directories under %s" % root)
        return 2

    print("=" * 76)
    print("4 - result status (read only)")
    print("root: %s" % root)
    print("phase: %s%s" % (args.phase,
                            "  mode: " + args.mode if args.mode else ""))
    print("=" * 76)
    print("%-36s %-11s %-11s" % ("corner", "annotation", "crosstalk"))
    print("-" * 76)

    bad = []
    results = []
    for name, directory in corners:
        ann, ann_why = ("-", [])
        cross, cross_why = ("-", [])
        if args.phase in ("1", "3"):
            ann, ann_why = check_annotation(name, directory, root)
        if args.phase in ("2", "3"):
            cross, cross_why = check_crosstalk(
                name, directory, root, args.mode)
        print("%-36s %-11s %-11s" % (name[:35], ann, cross))
        reasons = [("annotation", value) for value in ann_why]
        reasons += [("crosstalk", value) for value in cross_why]
        if reasons:
            bad.append(name)
        results.append((name, ann, cross, reasons))

    detail_rows = []
    for name, ann, cross, reasons in results:
        for group, why in reasons:
            if ((group == "annotation" and ann == "MISSING") or
                    (group == "crosstalk" and cross == "MISSING")):
                continue
            detail_rows.append((name, group, why))

    if detail_rows:
        print("")
        print("Partial details")
        print("-" * 76)
        for name, group, why in detail_rows:
            print("%-28s %-10s %s" % (name[:27], group, why))

    print("")
    print("OK corners: %d / %d" % (len(corners) - len(bad), len(corners)))
    print("No files were created, changed, or removed.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
