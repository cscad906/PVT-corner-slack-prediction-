#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Compare every scaling corner of one design with its ground truth in one run.

Usage
    python3 analysis/compare_all_corners.py --scaled-dir <RESULT_FOLDER> --gt-dir <DESIGN_GT_DIR>
    python3 analysis/compare_all_corners.py --scaled-dir ... --gt-dir ... --analysis setup

Inputs (read-only)
    <RESULT_FOLDER>/restored_scaled_<PROC>_<V>V_<T>C_<BEOL>_<AXIS>_<setup|hold>[_net].rpt
    <DESIGN_GT_DIR>/setup/*.rpt and <DESIGN_GT_DIR>/hold/*.rpt
        e.g. PERIC0/setup/SSPG_0p60v_125c_rcmax.rpt

Pairing
    A scaled report is paired with the ONE ground-truth .rpt in the matching
    setup/ or hold/ folder whose name carries the same process token, the same
    voltage (compared as a number: 0p6 == 0p60), temperature (m40c = -40) and
    BEOL (rcmax == RCMAX == rc_max). No match or several matches are listed,
    never guessed.

Comparison
    Each pair is compared with compare_scaling_mae.py's own functions, so the
    numbers equal a single-corner run of that script. Per-corner details are
    written as usual under <output-dir>/<setup|hold>/<scaled report name>/.
    The period-aligned error (--align-period of that script) is always added.

Output
    Screen and <output-dir>/summary_all.txt (a new summary_all_runN.txt when it
    exists), plain fixed-width text for less/gvim.

Percent definitions
    MAE% and max% = value / mean(|GT slack|) * 100 over the compared paths
    WNS%          = |PT WNS - GT WNS| / |GT WNS| * 100 (as compare_scaling_mae.py)
    Aligned values use only the period-aligned paths.
Python 3.6 compatible; standard library only.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


TOL = 1e-6
HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("compare_scaling_mae", str(HERE / "compare_scaling_mae.py"))
CMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CMP)

SCALED_RE = re.compile(
    r"^restored_scaled_(?P<process>.+?)_(?P<v>m?[0-9]+(?:p[0-9]+)?)V_"
    r"(?P<t>m?[0-9]+(?:p[0-9]+)?)C_(?P<beol>[^_]+)_(?P<axis>V|T|VT)_"
    r"(?P<analysis>setup|hold)(?P<net>_net)?\.rpt$")
VOLT_RE = re.compile(r"(?<![0-9.])([0-9]+)[p.]([0-9]+)v(?![a-z])", re.IGNORECASE)
TEMP_RE = re.compile(r"(?<![0-9a-z.])(m|-)?([0-9]+)c(?![a-z])", re.IGNORECASE)


def tag_number(tag):
    return float(tag.replace("p", ".").replace("m", "-"))


def canonical_beol(text):
    """Same rule as run_scaling_after_restore.tcl canonical_beol."""
    compact = re.sub(r"[^0-9a-z]", "", text.lower())
    for name in ("rcmax", "rcmin", "cmax"):
        if name in compact:
            return name.upper()
    return compact.upper()


def gt_tokens(name):
    """(first voltage, first temperature, lower-case words) read from a ground-truth file name."""
    volt = VOLT_RE.search(name)
    temp = TEMP_RE.search(name)
    v = float(volt.group(1) + "." + volt.group(2)) if volt else None
    t = None
    if temp:
        t = float(temp.group(2)) * (-1.0 if temp.group(1) else 1.0)
    words = {word.lower() for word in re.split(r"[^0-9A-Za-z]+", name) if word}
    return v, t, words


def gt_beol_matches(name, beol):
    compact = re.sub(r"[^0-9a-z]", "", name.lower())
    found = canonical_beol(compact)
    if found in ("RCMAX", "RCMIN", "CMAX"):
        return found == beol
    return beol.lower() in compact


def find_runs(scaled_dir, analysis_filter):
    runs = []
    for entry in sorted(os.listdir(scaled_dir)):
        match = SCALED_RE.match(entry)
        if not match or not os.path.isfile(os.path.join(scaled_dir, entry)):
            continue
        if analysis_filter and match.group("analysis") != analysis_filter:
            continue
        runs.append({
            "name": entry, "path": Path(scaled_dir) / entry,
            "process": match.group("process"), "v": tag_number(match.group("v")),
            "t": tag_number(match.group("t")), "beol": canonical_beol(match.group("beol")),
            "analysis": match.group("analysis"), "mode": "net" if match.group("net") else "path"})
    return runs


def find_gt(run, gt_dir):
    """Return (path or None, reason, candidates)."""
    folder = Path(gt_dir) / run["analysis"]
    if not folder.is_dir():
        return None, "no folder {}".format(folder), []
    matches, near = [], []
    for entry in sorted(os.listdir(str(folder))):
        if not entry.endswith(".rpt") or not (folder / entry).is_file():
            continue
        v, t, words = gt_tokens(entry)
        if v is None or t is None or abs(v - run["v"]) > TOL or abs(t - run["t"]) > TOL:
            continue
        if not gt_beol_matches(entry, run["beol"]):
            continue
        if run["process"].lower() in words:
            matches.append(folder / entry)
        else:
            near.append(entry)
    if len(matches) == 1:
        return matches[0], "", []
    if matches:
        return None, "AMBIGUOUS", [path.name for path in matches]
    if near:
        return None, "NO_GT (same V/T/BEOL but process '{}' not in the name)".format(run["process"]), near
    return None, "NO_GT (no {} {}V {}C {} .rpt in {})".format(
        run["process"], fmt(run["v"]), fmt(run["t"]), run["beol"], folder), []


def fmt(value):
    return "%g" % value


def mean(values):
    return sum(values) / len(values) if values else None


def pct(value, denominator):
    if value is None or not denominator:
        return None
    return abs(value) / denominator * 100.0


def compare_pair(run, gt_path, output_dir):
    """Run compare_scaling_mae.py's steps for one pair; return the table metrics."""
    analysis = run["analysis"]
    scaled = CMP.parse_report(run["path"])
    truth = CMP.parse_report(gt_path)
    rows, summary = CMP.evaluate(scaled, truth, CMP.NS_TO_PS, analysis)
    summary["path_diagnostics"] = CMP.diagnose_paths(rows, scaled, truth, analysis)
    summary.update({
        "input_unit": "ns", "output_unit": "ps", "analysis": analysis,
        "analysis_source": "scaled_report_name",
        "scaled_report": str(run["path"].resolve()), "ground_truth_report": str(gt_path.resolve())})
    inputs = run["path"].parent / "details" / (run["name"] + ".inputs.txt")
    if not inputs.is_file():
        inputs = Path(str(run["path"]) + ".inputs.txt")
    summary["scaling_input_plan_path"] = str(inputs.resolve()) if inputs.is_file() else None
    summary["scaling_input_plan"] = inputs.read_text(errors="ignore") if inputs.is_file() else None
    summary["period_alignment"] = CMP.period_alignment(rows, analysis)

    result_dir = CMP.create_result_dir(Path(output_dir) / analysis, CMP.safe_corner_name(run["path"]))
    CMP.write_path_text(result_dir / "path_errors.txt", rows)
    CMP.write_path_diagnostics(result_dir / "path_diagnostics.txt", rows)
    CMP.write_summary_text(result_dir / "summary.txt", summary)
    CMP.write_period_aligned(result_dir / "period_aligned.txt", rows)
    with (result_dir / "summary.json").open("w") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False)

    compared = [row for row in rows if row["abs_error_ps"] is not None]
    gt_slacks = [row["ground_truth_ps"] for row in compared]
    denominator = mean([abs(value) for value in gt_slacks])
    metrics = {
        "paths": summary["compared_paths"], "excluded": summary["excluded_paths"],
        "gt_mean": mean(gt_slacks), "gt_abs_mean": denominator,
        "mae": summary["mae_ps"], "bias": summary["bias_ps"], "max": summary["worst_abs_error_ps"],
        "p90": summary["abs_error_percentiles_ps"]["p90"], "p99": summary["abs_error_percentiles_ps"]["p99"],
        "gt_wns": summary["ground_truth_wns_ps"], "pt_wns": summary["pt_scaling_wns_ps"],
        "wns_err": summary["pt_scaling_wns_ps"] - summary["ground_truth_wns_ps"],
        "wns_pct": summary["wns_error_percent"], "clock": summary["clock_validation_status"],
        "result_dir": str(result_dir)}
    metrics["mae_pct"] = pct(metrics["mae"], denominator)
    metrics["max_pct"] = pct(metrics["max"], denominator)

    aligned = [row for row in rows if row.get("aligned_err_ps") is not None]
    detail = summary["period_alignment"]
    metrics.update({"a_paths": len(aligned), "a_mismatch": detail["counts"]["clock_mismatch"],
                    "a_mae": detail["mae_ps"], "a_bias": detail["bias_ps"],
                    "a_max": detail["worst_abs_error_ps"], "a_wns_err": None, "a_wns_pct": None,
                    "a_p90": detail["abs_error_percentiles_ps"]["p90"],
                    "a_p99": detail["abs_error_percentiles_ps"]["p99"],
                    "a_mae_pct": None, "a_max_pct": None})
    if aligned:
        a_denominator = mean([abs(row["ground_truth_ps"]) for row in aligned])
        a_gt_wns = min(row["ground_truth_ps"] for row in aligned)
        a_pt_wns = min(row["pt_scaling_ps"] - row["period_shift_ps"] for row in aligned)
        metrics["a_wns_err"] = a_pt_wns - a_gt_wns
        metrics["a_wns_pct"] = pct(metrics["a_wns_err"], abs(a_gt_wns))
        metrics["a_mae_pct"] = pct(metrics["a_mae"], a_denominator)
        metrics["a_max_pct"] = pct(metrics["a_max"], a_denominator)
    return metrics


def num(value, width, signed=False, digits=1):
    if value is None:
        return "NA".rjust(width)
    return ("{:+.%df}" % digits if signed else "{:.%df}" % digits).format(value).rjust(width)


def render(args, results, problems):
    out = ["COMPARE ALL CORNERS",
           "scaled dir : {}".format(os.path.abspath(args.scaled_dir)),
           "GT dir     : {}".format(os.path.abspath(args.gt_dir)),
           "unit       : ps; MAE%/max% = value / mean(|GT slack|); WNS% = |WNS err| / |GT WNS|",
           "p90/p99    : 90% / 99% of the paths have |error| at or below this value", ""]
    ordered = sorted(results, key=lambda item: (item[0]["analysis"] != "setup", item[0]["mode"], item[0]["v"]))
    head = ("{:<6} {:<5} {:<22} {:>6} {:>10} {:>9} {:>7} {:>8} {:>8} {:>9} {:>7} {:>10} {:>10} {:>9} {:>7} {:<8}").format(
        "type", "mode", "corner", "paths", "GT_mean", "MAE", "MAE%", "p90", "p99", "max_err", "max%",
        "GT_WNS", "PT_WNS", "WNS_err", "WNS%", "clock")
    out.extend(["RAW (as compare_scaling_mae.py)", head, "-" * len(head)])
    for run, m in ordered:
        corner = "{} {}V {}C {}".format(run["process"], fmt(run["v"]), fmt(run["t"]), run["beol"])
        out.append("{:<6} {:<5} {:<22} {:>6} {} {} {} {} {} {} {} {} {} {} {} {:<8}".format(
            run["analysis"], run["mode"], corner, m["paths"], num(m["gt_mean"], 10, True),
            num(m["mae"], 9), num(m["mae_pct"], 7), num(m["p90"], 8), num(m["p99"], 8),
            num(m["max"], 9), num(m["max_pct"], 7),
            num(m["gt_wns"], 10, True), num(m["pt_wns"], 10, True), num(m["wns_err"], 9, True),
            num(m["wns_pct"], 7), m["clock"]))
    head = ("{:<6} {:<5} {:<22} {:>6} {:>9} {:>7} {:>9} {:>8} {:>8} {:>9} {:>7} {:>9} {:>7} {:>8}").format(
        "type", "mode", "corner", "paths", "MAE", "MAE%", "bias", "p90", "p99", "max_err", "max%",
        "WNS_err", "WNS%", "clk_mism")
    out.extend(["", "PERIOD-ALIGNED (each path's own clock-edge difference removed; setup is the one that matters)",
                head, "-" * len(head)])
    for run, m in ordered:
        corner = "{} {}V {}C {}".format(run["process"], fmt(run["v"]), fmt(run["t"]), run["beol"])
        out.append("{:<6} {:<5} {:<22} {:>6} {} {} {} {} {} {} {} {} {} {:>8}".format(
            run["analysis"], run["mode"], corner, m["a_paths"], num(m["a_mae"], 9), num(m["a_mae_pct"], 7),
            num(m["a_bias"], 9, True), num(m["a_p90"], 8), num(m["a_p99"], 8),
            num(m["a_max"], 9), num(m["a_max_pct"], 7),
            num(m["a_wns_err"], 9, True), num(m["a_wns_pct"], 7), m["a_mismatch"]))
    if problems:
        out.extend(["", "NOT COMPARED"])
        for run, reason, candidates in problems:
            out.append("  {}: {}".format(run["name"], reason))
            for name in candidates[:5]:
                out.append("      candidate: {}".format(name))
    out.extend(["", "Per-corner details: <output-dir>/<setup|hold>/<scaled report name>/summary.txt",
                "GT_mean = mean GT slack (signed). clock = CLOCK VALIDATION of the raw comparison;",
                "INVALID with a large capture-edge MAE means the corners' clock periods differ: read the aligned table."])
    return out


def summary_path(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "summary_all.txt"
    run = 2
    while path.exists():
        path = output_dir / "summary_all_run{}.txt".format(run)
        run += 1
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare all scaling corners of one design with ground truth.")
    parser.add_argument("--scaled-dir", required=True, help="RESULT_FOLDER holding restored_scaled_*.rpt")
    parser.add_argument("--gt-dir", required=True, help="design GT folder holding setup/ and hold/")
    parser.add_argument("--analysis", choices=("setup", "hold"), default=None, help="default: both")
    parser.add_argument("--output-dir", default="pt_scaling_comparison", help="default: pt_scaling_comparison")
    args = parser.parse_args(argv)
    for label, folder in (("--scaled-dir", args.scaled_dir), ("--gt-dir", args.gt_dir)):
        if not os.path.isdir(folder):
            parser.error("{} is not a folder: {}".format(label, folder))

    runs = find_runs(args.scaled_dir, args.analysis)
    if not runs:
        print("NO SCALED REPORTS: no restored_scaled_*.rpt in {}".format(os.path.abspath(args.scaled_dir)))
        return 1
    results, problems = [], []
    for index, run in enumerate(runs, 1):
        gt_path, reason, candidates = find_gt(run, args.gt_dir)
        if gt_path is None:
            problems.append((run, reason, candidates))
            print("[{}/{}] SKIP {}: {}".format(index, len(runs), run["name"], reason))
            continue
        print("[{}/{}] {} <-> {}".format(index, len(runs), run["name"], gt_path.name))
        sys.stdout.flush()
        try:
            results.append((run, compare_pair(run, gt_path, args.output_dir)))
        except ValueError as error:
            problems.append((run, "ERROR {}".format(error), [gt_path.name]))

    text = render(args, results, problems)
    path = summary_path(Path(args.output_dir))
    path.write_text("\n".join(text) + "\n")
    print("")
    for line in text:
        print(line)
    print("")
    print("SUMMARY FILE: {}".format(path.resolve()))
    print("compared={} not_compared={}".format(len(results), len(problems)))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
