#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Compare every scaling corner of one design with its ground truth in one run.

Usage
    python3 analysis/compare_all_corners.py --scaled-dir <RESULT_FOLDER> --gt-dir <DESIGN_GT_DIR>
    python3 analysis/compare_all_corners.py --scaled-dir ... --gt-dir ... --analysis setup

    End corners (PT scaling cannot extrapolate there): GT-only statistics
    python3 analysis/compare_all_corners.py --gt-dir <DESIGN_GT_DIR> \
        --end-corner 0.5:125:rcmax --end-corner 0.95:125:rcmax
    Spec is V:T:BEOL or PROCESS:V:T:BEOL (0.5 or 0p5, m40 or -40). Without
    --scaled-dir only the END CORNERS table is made (end_corners.txt); with it
    the table is added below the comparison tables in summary_all.txt.

Inputs (read-only)
    <RESULT_FOLDER>/restored_scaled_<PROC>_<V>V_<T>C_<BEOL>_<AXIS>_<setup|hold>[_net].rpt
        (also <RESULT_FOLDER>/setup/ and <RESULT_FOLDER>/hold/ when they exist, so a
        design folder laid out like the GT folder works too)
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
    exists), plain fixed-width text for less/gvim. Three tables, one row per
    corner/analysis/mode:
        RAW            paths, mean GT slack, MAE, MAE%, p90, p99, max err, max%,
                       GT/PT WNS, WNS error, WNS%, clock validation
        PERIOD-ALIGNED the same after removing each path's clock-edge difference
                       (read this one for setup)
        VIOLATIONS     GT -> PT violation count, hit / missed / false alarm,
                       MAE and bias of GT-violated and GT-met paths
    Per corner, as compare_scaling_mae.py: summary.txt, path_errors.txt,
    path_diagnostics.txt, period_aligned.txt and path_breakdown.txt (one line
    per path: where its slack error comes from).

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


def scaled_folders(scaled_dir):
    """The folder itself plus its setup/ and hold/ subfolders when present."""
    folders = [Path(scaled_dir)]
    for sub in ("setup", "hold"):
        if (Path(scaled_dir) / sub).is_dir():
            folders.append(Path(scaled_dir) / sub)
    return folders


def find_runs(scaled_dir, analysis_filter):
    runs = []
    for folder in scaled_folders(scaled_dir):
        for entry in sorted(os.listdir(str(folder))):
            run = parse_scaled(folder, entry, analysis_filter)
            if run is not None:
                runs.append(run)
    return runs


def parse_scaled(folder, entry, analysis_filter):
    match = SCALED_RE.match(entry)
    if not match or not (folder / entry).is_file():
        return None
    if analysis_filter and match.group("analysis") != analysis_filter:
        return None
    if folder.name in ("setup", "hold") and folder.name != match.group("analysis"):
        print("WARNING: {} is in {}/ but its name says {}; using the name".format(
            entry, folder.name, match.group("analysis")))
    return {"name": entry, "path": folder / entry,
            "process": match.group("process"), "v": tag_number(match.group("v")),
            "t": tag_number(match.group("t")), "beol": canonical_beol(match.group("beol")),
            "analysis": match.group("analysis"), "mode": "net" if match.group("net") else "path"}


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
    summary["violation_raw"] = CMP.violation_summary(rows, False)
    summary["violation_aligned"] = CMP.violation_summary(rows, True)

    result_dir = CMP.create_result_dir(Path(output_dir) / analysis, CMP.safe_corner_name(run["path"]))
    CMP.write_path_text(result_dir / "path_errors.txt", rows)
    CMP.write_path_diagnostics(result_dir / "path_diagnostics.txt", rows)
    CMP.write_summary_text(result_dir / "summary.txt", summary)
    CMP.write_period_aligned(result_dir / "period_aligned.txt", rows)
    CMP.write_path_breakdown(result_dir / "path_breakdown.txt", rows)
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

    metrics["viol"] = summary["violation_aligned"]
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
    head = ("{:<6} {:<5} {:<22} {:>6} {:>8} {:>8} {:>6} {:>7} {:>7} {:>9} {:>9} {:>9} {:>9}").format(
        "type", "mode", "corner", "paths", "GT_viol", "PT_viol", "hit", "missed", "false", "MAE_viol",
        "bias_viol", "MAE_met", "bias_met")
    out.extend(["", "VIOLATIONS (slack < 0; PT judged on period-aligned slack)", head, "-" * len(head)])
    for run, m in ordered:
        corner = "{} {}V {}C {}".format(run["process"], fmt(run["v"]), fmt(run["t"]), run["beol"])
        v = m["viol"]
        out.append("{:<6} {:<5} {:<22} {:>6} {:>8} {:>8} {:>6} {:>7} {:>7} {} {} {} {}".format(
            run["analysis"], run["mode"], corner, v["paths"], v["gt_viol"], v["pt_viol"], v["hit"],
            v["missed"], v["false_alarm"], num(v["viol"]["mae_ps"], 9), num(v["viol"]["bias_ps"], 9, True),
            num(v["met"]["mae_ps"], 9), num(v["met"]["bias_ps"], 9, True)))
    out.append("missed = GT fails but PT passes (optimistic); false = GT passes but PT fails (pessimistic).")
    if problems:
        out.extend(["", "NOT COMPARED"])
        for run, reason, candidates in problems:
            out.append("  {}: {}".format(run["name"], reason))
            for name in candidates[:5]:
                out.append("      candidate: {}".format(name))
    out.extend(["", "Per-corner details: <output-dir>/<setup|hold>/<scaled report name>/summary.txt",
                "Per-path error sources: same folder, path_breakdown.txt (one line per path)",
                "GT_mean = mean GT slack (signed). clock = CLOCK VALIDATION of the raw comparison;",
                "INVALID with a large capture-edge MAE means the corners' clock periods differ: read the aligned table."])
    return out


def parse_end_corner(spec):
    """'0.5:125:rcmax' or 'SSPG:0p5:m40:rcmax' -> dict; ValueError when malformed."""
    parts = [part.strip() for part in spec.split(":")]
    if len(parts) not in (3, 4) or not all(parts):
        raise ValueError("--end-corner needs V:T:BEOL or PROCESS:V:T:BEOL, got '{}'".format(spec))
    process = parts[0] if len(parts) == 4 else None
    v_text, t_text, beol = parts[-3:]
    v = float(re.sub(r"v$", "", v_text, flags=re.IGNORECASE).replace("p", "."))
    t_text = re.sub(r"c$", "", t_text, flags=re.IGNORECASE)
    t = -float(t_text[1:]) if t_text[:1] in ("m", "M") else float(t_text)
    return {"spec": spec, "process": process, "v": v, "t": t, "beol": canonical_beol(beol)}


def find_gt_corner(corner, analysis, gt_dir):
    """Return (path or None, reason, candidates) for one end corner."""
    folder = Path(gt_dir) / analysis
    if not folder.is_dir():
        return None, "no folder {}".format(folder), []
    matches = []
    for entry in sorted(os.listdir(str(folder))):
        if not entry.endswith(".rpt") or not (folder / entry).is_file():
            continue
        v, t, words = gt_tokens(entry)
        if v is None or t is None or abs(v - corner["v"]) > TOL or abs(t - corner["t"]) > TOL:
            continue
        if not gt_beol_matches(entry, corner["beol"]):
            continue
        if corner["process"] and corner["process"].lower() not in words:
            continue
        matches.append(folder / entry)
    if len(matches) == 1:
        return matches[0], "", []
    if matches:
        return None, "AMBIGUOUS (give PROCESS:V:T:BEOL)", [path.name for path in matches]
    return None, "NO_GT", []


def gt_only_stats(gt_path):
    """Paths, mean slack, WNS and violation count (ps) from one GT report."""
    slacks = [item.slack * CMP.NS_TO_PS for item in CMP.parse_report(gt_path).values()
              if item.slack is not None]
    return {"paths": len(slacks), "gt_mean": mean(slacks),
            "gt_wns": min(slacks) if slacks else None,
            "gt_viol": sum(1 for value in slacks if value < 0)}


def end_corner_lines(corners, gt_dir, analyses):
    head = "{:<6} {:<24} {:>6} {:>10} {:>10} {:>8}  {}".format(
        "type", "corner", "paths", "GT_mean", "GT_WNS", "GT_viol", "GT_file")
    out = ["END CORNERS (GT only; PT scaling cannot extrapolate here)", head, "-" * len(head)]
    for analysis in analyses:
        for corner in corners:
            label = "{}{}V {}C {}".format(corner["process"] + " " if corner["process"] else "",
                                          fmt(corner["v"]), fmt(corner["t"]), corner["beol"])
            path, reason, candidates = find_gt_corner(corner, analysis, gt_dir)
            if path is None:
                out.append("{:<6} {:<24} {}".format(analysis, label, reason))
                for name in candidates[:5]:
                    out.append("       candidate: {}".format(name))
                continue
            stats = gt_only_stats(path)
            out.append("{:<6} {:<24} {:>6} {} {} {:>8}  {}".format(
                analysis, label, stats["paths"], num(stats["gt_mean"], 10, True),
                num(stats["gt_wns"], 10, True), stats["gt_viol"], path.name))
    out.append("GT_mean = mean GT slack (ps, signed); GT_WNS = minimum GT slack; GT_viol = paths with slack < 0.")
    return out


def summary_path(output_dir, stem="summary_all"):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "{}.txt".format(stem)
    run = 2
    while path.exists():
        path = output_dir / "{}_run{}.txt".format(stem, run)
        run += 1
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare all scaling corners of one design with ground truth.")
    parser.add_argument("--scaled-dir", default=None, help="RESULT_FOLDER holding restored_scaled_*.rpt")
    parser.add_argument("--gt-dir", required=True, help="design GT folder holding setup/ and hold/")
    parser.add_argument("--analysis", choices=("setup", "hold"), default=None, help="default: both")
    parser.add_argument("--output-dir", default="pt_scaling_comparison", help="default: pt_scaling_comparison")
    parser.add_argument("--end-corner", action="append", default=[],
                        help="V:T:BEOL or PROCESS:V:T:BEOL of a corner PT cannot scale; repeatable")
    args = parser.parse_args(argv)
    if args.scaled_dir is None and not args.end_corner:
        parser.error("give --scaled-dir, or --end-corner for GT-only end-corner statistics")
    for label, folder in (("--scaled-dir", args.scaled_dir), ("--gt-dir", args.gt_dir)):
        if folder is not None and not os.path.isdir(folder):
            parser.error("{} is not a folder: {}".format(label, folder))
    try:
        corners = [parse_end_corner(spec) for spec in args.end_corner]
    except ValueError as error:
        parser.error(str(error))
    analyses = [args.analysis] if args.analysis else ["setup", "hold"]
    if args.scaled_dir is None:
        text = end_corner_lines(corners, args.gt_dir, analyses)
        path = summary_path(Path(args.output_dir), "end_corners")
        path.write_text("\n".join(text) + "\n")
        for line in text:
            print(line)
        print("")
        print("END CORNER FILE: {}".format(path.resolve()))
        return 0

    runs = find_runs(args.scaled_dir, args.analysis)
    if not runs:
        print("NO SCALED REPORTS: no restored_scaled_*.rpt in {} or its setup/ and hold/".format(
            os.path.abspath(args.scaled_dir)))
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
    if corners:
        if len({run["process"] for run in runs}) == 1:
            for corner in corners:
                corner["process"] = corner["process"] or runs[0]["process"]
        text += [""] + end_corner_lines(corners, args.gt_dir, analyses)
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
