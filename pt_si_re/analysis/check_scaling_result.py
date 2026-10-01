#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Check restored-session scaling results (LOO and scaling evidence) in one go.

Usage
    python3 analysis/check_scaling_result.py <RESULT_FOLDER> [<RESULT_FOLDER> ...]
    python3 analysis/check_scaling_result.py            # current directory

Every run in the folder is checked: path mode (run_scaling_after_restore.tcl)
and net mode (run_scaling_after_restore_net.tcl, report name ending _net.rpt).
A run is found by its report or by its log, so a run that stopped early is
still listed.

Reads (read-only), per run <name> = restored_scaled_..._<analysis>[_net].rpt
    <RESULT_FOLDER>/<name>                          report header
    <RESULT_FOLDER>/details/<name>.log              run log
    <RESULT_FOLDER>/details/<name>.loo_check.txt    LOO guard evidence
    <RESULT_FOLDER>/details/<name>.inputs.txt       interpolation inputs
    <RESULT_FOLDER>/details/<name>.dcalc            PT "Scaling libraries used"
    (.clock.dcalc and .umem.dcalc too when present)
    Old runs that kept these files next to the report are read as well.

Writes
    <RESULT_FOLDER>/check_summary.txt   the same text as the screen
    Nothing else is written or changed.

Verdict per run
    FAIL  the run did not finish, a LOO guard did not pass (or is missing:
          the run used a script older than the guards), PT used a DB at the
          target voltage, the inputs do not bracket the target, or a
          verification step did not pass.
    WARN  finished and LOO-clean, but some fixed-path cells were left unscaled
          (static_library > 0, unclassified libraries), some fixed paths were
          missing, or net-mode clock evidence was skipped.
    PASS  everything above is clean.

The last line is a result code (see the code table in this folder's README):
    OK-SCALECHECK / W-SCALECHECK / E-SCALECHECK
Python 3.6 compatible; standard library only.
"""

import argparse
import os
import re
import sys


TOL = 1e-6
LEVELS = ("FAIL", "WARN", "PASS", "INFO")

NAME_RE = re.compile(
    r"^restored_scaled_(?P<process>.+?)_(?P<v>m?[0-9]+(?:p[0-9]+)?)V_"
    r"(?P<t>m?[0-9]+(?:p[0-9]+)?)C_(?P<beol>[^_]+)_(?P<axis>V|T|VT)_"
    r"(?P<analysis>setup|hold)(?P<net>_net)?\.rpt$")
HEADER_RE = re.compile(
    r"^### SCALING TARGET process=(\S+) voltage=(\S+) temperature=(\S+) beol=(\S+) axis=(\S+)")
# Voltage tokens in a DB or library name: 0p6v, 0p605v, 0.75v. A token must
# not continue a longer number on its left (so "14rvt" or "385_3ns" never match).
VOLT_TOKEN_RE = re.compile(r"(?<![0-9.])([0-9]+)(?:[p.]([0-9]+))?v", re.IGNORECASE)

# What each item proves. Printed once after the runs (and in check_summary.txt).
MEANINGS = (
    ("run", "Did the PT run finish (RUN END status=SUCCESS)? A FAIL run's numbers are unusable."),
    ("loo TL-001", "No cell in the design is linked to a target-corner DB (hold min-library mapping included). "
                   "So no cell reads target-corner data directly."),
    ("loo TL-003", "No scaling group used by the design contains a target-corner DB (compared by DB file path). "
                   "So interpolation cannot mix in target-corner data."),
    ("loo LOO_CHECK", "File record of TL-001 + TL-003. target-corner DB 'not even loaded' is the strongest case; "
                      "'loaded, none linked or grouped' is still LOO."),
    ("loo .dcalc", "PrimeTime itself lists the DBs it used for a real cell delay ('Scaling libraries used'). "
                   "None may be the target DB or carry the target voltage in its name. Independent of the script."),
    ("inputs", "The DBs planned for interpolation lie below AND above the target. An input AT the target is a leak; "
               "one-sided inputs would be extrapolation."),
    ("coverage", "WARN = fixed-path cells ON A SCALING NET whose library has no scaling group; they keep the "
                 "restored (link-corner) timing, so the result is partly unscaled. INFO = such cells on auto-fixed "
                 "nets, expected. Unclassified = P/V/T unreadable."),
    ("paths", "Fixed paths PT could not time in this run. They drop out of the MAE comparison."),
    ("evidence", "SCALING VERIFICATION: PT shows scaling on a real cell arc of a fixed path, with no extrapolation."),
    ("net", "Net mode only. NET-001: every library on the scaled net has a scaling group. net power: every PG pin "
            "on the net reached the target voltage. clock: a clock-tree cell was scaled too."),
    ("nets", "Listed vs auto-fixed supply nets. An auto-fixed net that should scale leaves its cells unscaled "
             "WITHOUT an error, so read this line."),
    ("SUMMARY", "target_dbs = target-corner DBs loaded in the session (0 is best); used_dbs_V = voltages of the DBs "
                "PT used; static = unscaled fixed-path cells on scaling nets; missing = untimed fixed paths."),
)

CODE_INFO = {
    "W-SCALECHECK": (
        "Every run finished and is LOO-clean, but at least one run has a WARN.",
        "Read the WARN lines above (unscaled cells, missing paths, skipped clock evidence)."),
    "E-SCALECHECK": (
        "At least one run FAILED a check; do not use that run's numbers.",
        "Read the FAIL lines above. A missing LOO line means an old script: pull and rerun."),
    "E-NORUN": (
        "No restored_scaled_*.rpt or its log was found in the given folder(s).",
        "Give RESULT_FOLDER (the folder that holds restored_*.rpt and details/)."),
}


def code(c, *msg):
    """Print the final result code (same layout as the other pt_si_re scripts)."""
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  DONE                [ %s ]" % c)
        print("=" * 66)
        return 0
    what, todo = CODE_INFO.get(c, ("", ""))
    kind = "FAILED" if c.startswith("E-") else "CHECK"
    print("  %-19s [ %s ]" % (kind, c))
    if what:
        print("    what   : %s" % what)
        print("    to do  : %s" % todo)
    print("=" * 66)
    return 1 if c.startswith("E-") else 0


def tag_number(tag):
    """'0p65' -> 0.65, 'm40' -> -40.0 (the original's file-name encoding)."""
    return float(tag.replace("p", ".").replace("m", "-"))


def to_float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def same(a, b):
    return a is not None and b is not None and abs(a - b) < TOL


def read_lines(path):
    if path is None or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read().splitlines()


def detail_path(folder, name, suffix):
    """details/<name><suffix>, or the old adjacent <name><suffix>."""
    new = os.path.join(folder, "details", name + suffix)
    if os.path.isfile(new):
        return new
    old = os.path.join(folder, name + suffix)
    if os.path.isfile(old):
        return old
    return None


def voltage_tokens(text):
    values = []
    for whole, frac in VOLT_TOKEN_RE.findall(os.path.basename(text)):
        values.append(float(whole + ("." + frac if frac else "")))
    return values


def fmt_v(value):
    return "%g" % value


class Run(object):
    """Findings for one scaling run."""

    def __init__(self, folder, name):
        self.folder = folder
        self.name = name
        self.findings = []
        self.mode = "net" if name.endswith("_net.rpt") else "path"
        self.target_v = None
        self.target_t = None
        self.axis = None
        self.target_dbs_loaded = None
        self.target_db_paths = set()
        self.used_voltages = set()
        self.static = None
        self.missing = None

    def add(self, level, item, message):
        self.findings.append((level, item, message))

    def verdict(self):
        levels = [level for level, _, _ in self.findings]
        if "FAIL" in levels:
            return "FAIL"
        if "WARN" in levels:
            return "WARN"
        return "PASS"


def last_match(lines, pattern):
    found = None
    for line in lines:
        match = pattern.match(line)
        if match:
            found = match
    return found


def first_match(lines, pattern):
    for line in lines:
        match = pattern.match(line)
        if match:
            return match
    return None


def check_target(run):
    match = NAME_RE.match(run.name)
    if match:
        run.target_v = tag_number(match.group("v"))
        run.target_t = tag_number(match.group("t"))
        run.axis = match.group("axis")
    report = read_lines(os.path.join(run.folder, run.name))
    if report is None:
        return False
    header = first_match(report[:5], HEADER_RE)
    if header:
        v, t = to_float(header.group(2)), to_float(header.group(3))
        if run.target_v is not None and not same(v, run.target_v):
            run.add("WARN", "target", "report header voltage %s differs from the file name (%s V)"
                    % (header.group(2), fmt_v(run.target_v)))
        run.target_v, run.target_t, run.axis = v, t, header.group(5)
    return True


def check_log(run, report_exists):
    lines = read_lines(detail_path(run.folder, run.name, ".log"))
    if lines is None:
        run.add("FAIL", "run", "no log (details/%s.log)" % run.name)
        return
    end = last_match(lines, re.compile(r"^RUN END: status=(\S+)"))
    error = last_match(lines, re.compile(r"^RUN ERROR: (.*)$"))
    if end and end.group(1) == "SUCCESS" and not error:
        run.add("PASS", "run", "RUN END status=SUCCESS")
        if not report_exists:
            run.add("FAIL", "run", "the run says SUCCESS but the report file is missing")
    elif error:
        run.add("FAIL", "run", "run stopped: %s" % error.group(1)[:300])
    else:
        run.add("FAIL", "run", "no RUN END line: the run is still going or was killed")

    for guard in ("TL-001", "TL-003"):
        match = last_match(lines, re.compile(r"^LOO CHECK %s: (\S+)(.*)$" % guard))
        if match and match.group(1) == "PASSED":
            run.add("PASS", "loo", "%s PASSED%s" % (guard, match.group(2).split("| evidence=")[0].rstrip(" |")))
        elif match:
            run.add("FAIL", "loo", "%s %s" % (guard, match.group(1)))
        else:
            run.add("FAIL", "loo", "no 'LOO CHECK %s' line: the script predates the LOO guards "
                    "(pull pt_si_re and rerun) or the run stopped before it" % guard)

    nets = first_match(lines, re.compile(r"^SCALING POWER NETS: count=(\d+) names=(.*)$"))
    if nets:
        run.add("INFO", "nets", "scaling nets (%s): %s" % (nets.group(1), nets.group(2).strip()))
    fixed = last_match(lines, re.compile(r"^AUTO-FIXED POWER NETS \(unchanged\): count=(\d+) names=(.*)$"))
    if fixed:
        run.add("INFO", "nets", "auto-fixed nets (%s): %s   <- no net that should scale may be here"
                % (fixed.group(1), fixed.group(2).strip()))

    # static_library mixes two kinds of unscaled fixed-path cells:
    #   on a scaling net but without a scaling group -> a real gap (WARN)
    #   on an auto-fixed net                         -> expected, its rail never changes (INFO)
    # Scaling-net cells = target_rail (supply scope); scaled ones = target_voltage.
    supply = last_match(lines, re.compile(r"^FIXED-PATH SUPPLY SCOPE: all=(\d+) target_rail=(\d+) fixed_rail=(\d+)"))
    scope = last_match(lines, re.compile(
        r"^FIXED-PATH CELL SCOPE: all=(\d+) scalable_library=(\d+) target_voltage=(\d+) static_library=(\d+)"))
    if scope:
        total, static = scope.group(1), int(scope.group(4))
        if supply:
            on_rail = max(0, int(supply.group(2)) - int(scope.group(3)))
            on_fixed = max(0, static - on_rail)
        else:
            on_rail, on_fixed = static, 0
        run.static = on_rail
        if on_rail:
            run.add("WARN", "coverage", "%d of %s fixed-path cells are on a scaling net but their library has "
                    "no active scaling group; they keep the restored (link-corner) timing" % (on_rail, total))
        else:
            run.add("PASS", "coverage", "every fixed-path cell on a scaling net is scaled (%s cells)" % total)
        if on_fixed:
            run.add("INFO", "coverage", "%d of %s fixed-path cells are on auto-fixed nets with an ungrouped "
                    "library; expected, their rail does not change" % (on_fixed, total))
    unclassified = last_match(lines, re.compile(r"^UNCLASSIFIED FIXED-PATH LIBRARIES \(not scaled\): (.*)$"))
    if unclassified:
        run.add("WARN", "coverage", "unclassified fixed-path libraries (not scaled): %s"
                % unclassified.group(1).strip()[:300])
    ignored = last_match(lines, re.compile(r"^IGNORED NON-PVT LIBRARIES: (\d+)"))
    if ignored and int(ignored.group(1)):
        run.add("INFO", "coverage", "%s loaded libraries had no readable P/V/T; the LOO guards "
                "cannot recognize them, the .dcalc voltage check below still applies" % ignored.group(1))

    paths = last_match(lines, re.compile(r"^FIXED PATHS RESULT: requested=(\d+) measured=(\d+) missing=(\d+)"))
    if paths:
        requested, measured, run.missing = (int(paths.group(i)) for i in (1, 2, 3))
        if measured == 0:
            run.add("FAIL", "paths", "no fixed path was measured (requested=%d)" % requested)
        elif run.missing:
            run.add("WARN", "paths", "requested=%d measured=%d missing=%d (see details/%s.missing)"
                    % (requested, measured, run.missing, run.name))
        else:
            run.add("PASS", "paths", "requested=%d measured=%d missing=0" % (requested, measured))

    verifications = [m for m in (re.match(r"^SCALING VERIFICATION: (\S+)", line) for line in lines) if m]
    if verifications and all(m.group(1) == "PASSED" for m in verifications):
        run.add("PASS", "evidence", "SCALING VERIFICATION PASSED (%d)" % len(verifications))
    elif verifications:
        run.add("FAIL", "evidence", "SCALING VERIFICATION: %s" % ", ".join(m.group(1) for m in verifications))

    if run.mode == "net":
        for label, pattern in (("NET-001", r"^NET CHECK NET-001: (\S+)"),
                               ("net power", r"^NET POWER VERIFICATION: (\S+)")):
            match = last_match(lines, re.compile(pattern))
            if match and match.group(1) == "PASSED":
                run.add("PASS", "net", "%s PASSED" % label)
            else:
                run.add("FAIL", "net", "%s %s" % (label, match.group(1) if match else "line missing"))
        clock = last_match(lines, re.compile(r"^CLOCK SCALING VERIFICATION: (\S+)"))
        if clock and clock.group(1) == "PASSED":
            run.add("PASS", "net", "clock-cell scaling evidence PASSED")
        elif clock and clock.group(1) == "SKIPPED":
            run.add("WARN", "net", "clock-cell scaling evidence SKIPPED (no clock cell on the net for the evidence path)")
        elif clock:
            run.add("FAIL", "net", "clock-cell scaling evidence %s" % clock.group(1))

    if last_match(lines, re.compile(r"^U_MEM NATIVE SCALING:")):
        umem = last_match(lines, re.compile(r"^U_MEM POWER VERIFICATION: (\S+)"))
        if umem and umem.group(1) == "PASSED":
            run.add("PASS", "u_mem", "U_MEM POWER VERIFICATION PASSED")
        else:
            run.add("FAIL", "u_mem", "u_mem was scaled but its power verification did not pass")


def check_loo_file(run):
    lines = read_lines(detail_path(run.folder, run.name, ".loo_check.txt"))
    if lines is None:
        run.add("FAIL", "loo", "no %s.loo_check.txt (old script, or the run stopped before TL-001)" % run.name)
        return
    for line in lines:
        match = re.match(r"^TARGET_CORNER_DBS_LOADED: (\d+)", line)
        if match:
            run.target_dbs_loaded = int(match.group(1))
        match = re.match(r"^\s+DB=(\S+)", line)
        if match:
            run.target_db_paths.add(os.path.normpath(match.group(1)))
    status = [line for line in lines if line.startswith("LOO_CHECK_STATUS:")]
    if status and status[-1].strip() == "LOO_CHECK_STATUS: PASSED":
        if run.target_dbs_loaded == 0:
            note = "target-corner DB not even loaded in the session"
        else:
            note = "%s target-corner DB(s) loaded, none linked or grouped" % run.target_dbs_loaded
        run.add("PASS", "loo", "LOO_CHECK_STATUS PASSED (%s)" % note)
    elif status:
        run.add("FAIL", "loo", status[-1].strip())
    else:
        run.add("FAIL", "loo", "loo_check.txt has no LOO_CHECK_STATUS line (the run stopped between TL-001 and TL-003)")


def scaling_libraries(lines):
    """DB paths listed under every 'Scaling libraries used ...:' block.

    PT prints both 'Scaling libraries used:' and an indented
    'Scaling libraries used for driver model :'; each is followed by one
    '<db>:<library>' line per DB and ends at a blank line.
    """
    dbs = []
    inside = False
    for line in lines:
        if line.strip().startswith("Scaling libraries used"):
            inside = True
            continue
        if inside:
            text = line.strip()
            if not text:
                inside = False
                continue
            db = text.rsplit(":", 1)[0] if ":" in text else text
            dbs.append(db)
    return dbs


def check_dcalc(run):
    found_main = False
    for suffix in (".dcalc", ".clock.dcalc", ".umem.dcalc"):
        lines = read_lines(detail_path(run.folder, run.name, suffix))
        if lines is None:
            continue
        found_main = found_main or suffix == ".dcalc"
        status = lines[0].strip() if lines else ""
        if status.endswith("SKIPPED"):
            continue
        if not status.endswith(": PASSED"):
            run.add("FAIL", "evidence", "%s: %s" % (suffix, status or "empty file"))
            continue
        dbs = scaling_libraries(lines)
        if not dbs:
            run.add("FAIL", "evidence", "%s has no 'Scaling libraries used' entry" % suffix)
            continue
        bad = []
        for db in sorted(set(dbs)):
            tokens = voltage_tokens(db)
            run.used_voltages.update(tokens)
            if os.path.normpath(db) in run.target_db_paths:
                bad.append("%s (is the target-corner DB)" % db)
            elif run.target_v is not None and any(same(v, run.target_v) for v in tokens):
                bad.append("%s (name carries the target voltage %s V)" % (db, fmt_v(run.target_v)))
        if bad:
            run.add("FAIL", "loo", "PT used a target-voltage DB in %s: %s" % (suffix, "; ".join(bad)))
        else:
            volts = sorted(set(v for db in dbs for v in voltage_tokens(db)))
            run.add("PASS", "loo", "%s: PT used %d DB(s), voltages %s V, none at the target"
                    % (suffix, len(set(dbs)), ", ".join(fmt_v(v) for v in volts) or "unknown"))
    if not found_main:
        run.add("FAIL", "evidence", "no %s.dcalc (PT scaling evidence)" % run.name)


def check_inputs(run):
    lines = read_lines(detail_path(run.folder, run.name, ".inputs.txt"))
    if lines is None:
        run.add("FAIL", "inputs", "no %s.inputs.txt" % run.name)
        return
    families = []
    for line in lines:
        match = re.match(r"^FAMILY (\S+)", line)
        if match:
            families.append({"name": match.group(1), "inputs": []})
            continue
        match = re.match(r"^\s+INPUT \d+ process=\S+ voltage=(\S+) V temperature=(\S+) C", line)
        if match and families:
            families[-1]["inputs"].append((to_float(match.group(1)), to_float(match.group(2))))
    if not families:
        run.add("INFO", "inputs", "no scalar library family planned (native u_mem group only)")
        return
    if run.target_v is None or run.target_t is None:
        run.add("WARN", "inputs", "target V/T unknown; bracketing not checked")
        return
    for family in families:
        points = family["inputs"]
        if run.axis in ("V", "VT"):
            values, target, unit = [v for v, t in points], run.target_v, "V"
        else:
            values, target, unit = [t for v, t in points], run.target_t, "C"
        if any(same(v, target) for v in values):
            run.add("FAIL", "inputs", "%s: an input is AT the target %s %s" % (family["name"], fmt_v(target), unit))
        elif any(v < target for v in values) and any(v > target for v in values):
            run.add("PASS", "inputs", "%s: inputs %s %s bracket the target %s %s" % (
                family["name"], ", ".join(fmt_v(v) for v in sorted(set(values))), unit, fmt_v(target), unit))
        else:
            run.add("FAIL", "inputs", "%s: inputs %s %s do not bracket the target %s %s" % (
                family["name"], ", ".join(fmt_v(v) for v in sorted(set(values))), unit, fmt_v(target), unit))


def find_runs(folder):
    names = set()
    for directory in (folder, os.path.join(folder, "details")):
        if not os.path.isdir(directory):
            continue
        for entry in os.listdir(directory):
            if not entry.startswith("restored_"):
                continue
            if entry.endswith(".rpt") and directory == folder:
                names.add(entry)
            elif entry.endswith(".rpt.log"):
                names.add(entry[:-len(".log")])
    return sorted(names)


def check_folder(folder):
    runs = []
    for name in find_runs(folder):
        run = Run(folder, name)
        report_exists = check_target(run)
        check_log(run, report_exists)
        check_loo_file(run)
        check_dcalc(run)
        check_inputs(run)
        runs.append(run)
    return runs


def render(folder, runs):
    out = ["SCALING RESULT CHECK: folder=%s runs=%d" % (os.path.abspath(folder), len(runs)), ""]
    for run in runs:
        target = "?" if run.target_v is None else "%s V / %s C" % (fmt_v(run.target_v), fmt_v(run.target_t))
        out.append("=== %s  [%s]  mode=%s  target=%s" % (run.name, run.verdict(), run.mode, target))
        for level in LEVELS:
            for lvl, item, message in run.findings:
                if lvl == level:
                    out.append("  %-4s %-9s %s" % (lvl, item, message))
        out.append("")
    out.append("SUMMARY")
    row = "%-6s %-5s %-14s %-10s %-14s %-7s %-7s %s"
    out.append(row % ("verdict", "mode", "target", "target_dbs", "used_dbs_V", "static", "missing", "run"))
    for run in runs:
        target = "?" if run.target_v is None else "%sV/%sC" % (fmt_v(run.target_v), fmt_v(run.target_t))
        used = ",".join(fmt_v(v) for v in sorted(run.used_voltages)) or "-"
        out.append(row % (run.verdict(), run.mode, target,
                          "-" if run.target_dbs_loaded is None else run.target_dbs_loaded,
                          used, "-" if run.static is None else run.static,
                          "-" if run.missing is None else run.missing, run.name))
    out.append("")
    out.append("WHAT THE ITEMS MEAN")
    for item, meaning in MEANINGS:
        out.append("  %-13s %s" % (item, meaning))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check restored-session scaling results (read-only).")
    parser.add_argument("folders", nargs="*", default=["."], help="RESULT_FOLDER(s); default: current directory")
    args = parser.parse_args(argv)

    all_runs = []
    for folder in args.folders:
        runs = check_folder(folder)
        if not runs:
            print("NO RUNS: %s (no restored_*.rpt or details/restored_*.rpt.log)" % os.path.abspath(folder))
            continue
        text = render(folder, runs)
        for line in text:
            print(line)
        summary = os.path.join(folder, "check_summary.txt")
        with open(summary, "w", encoding="ascii", errors="backslashreplace") as handle:
            handle.write("\n".join(text) + "\n")
        print("")
        print("SUMMARY FILE: %s" % os.path.abspath(summary))
        all_runs.extend(runs)

    if not all_runs:
        return code("E-NORUN")
    verdicts = [run.verdict() for run in all_runs]
    counts = "runs=%d pass=%d warn=%d fail=%d" % (
        len(verdicts), verdicts.count("PASS"), verdicts.count("WARN"), verdicts.count("FAIL"))
    if "FAIL" in verdicts:
        return code("E-SCALECHECK", counts)
    if "WARN" in verdicts:
        return code("W-SCALECHECK", counts)
    return code("OK-SCALECHECK", counts)


if __name__ == "__main__":
    sys.exit(main())
