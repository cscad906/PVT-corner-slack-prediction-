#!/usr/bin/env python3
"""PrimeTime voltage scaling against this model, path by path.

    python3 scripts/compare_scaling.py --scaling <dir> --list     # look first
    python3 scripts/compare_scaling.py --scaling <dir>
    python3 scripts/compare_scaling.py --scaling <dir> --mode hold

PrimeTime can report a corner whose library does not exist by scaling one that
does. That is the other answer to the question this model answers, so the
comparison worth drawing is the two of them on the same paths:

    x = path index -- the n of `### FIXED_PATH idx=<n>`, the report's own
        numbering, so a point can be looked up by hand in either report
    y = slack in ps -- PT scaling and this model. No measurement: a corner
        reached by scaling has no library to have measured it with

Scatter, not a line: x is an identifier, not a quantity. Neighbouring path
numbers have nothing to do with each other and joining them would draw a trend
that does not exist. What a reader looks for is whether one series sits above
the other across the range, and whether the gap grows with the path's own
slack -- both of which are the vertical distance between the two series. The
summary of that distance is printed to the terminal.

FINDING THE CORNER
------------------
The scaling reports are named by hand, so the corner is read by looking for
TOKENS anywhere in the name, in any order and in any case:

    voltage      0p52V / 0.52V / 520mV
    temperature  125C / m25 / -40C / n40C
    BEOL level   rcmax rcmin cmax cmin cnom cworst cbest ctyp typical
    check        hold / setup

`restored_scaled_SSPG_0p52V_125C_RCMAX_V_hold.rpt` reads as
(0.52V, 125C, rcmax, hold); so does `SSPG-0.52v-RCmax-125c.hold.rpt`. This is
the same reading applied to the model's own corner labels, which have the same
shape (`SSPG_0p52V_RCMAX`), so the two sides cannot drift apart. A name it
cannot read is listed and skipped, never guessed at, and `--list` prints what
it made of every file without drawing -- run that first.

WHERE THE MODEL'S NUMBERS COME FROM
-----------------------------------
Whatever this repo has already written for that corner:

    runs/<mode>/<design>/<temp>/predictions_*.npz     base --save, train, predict
    runs/<mode>/_all/predict_<temp>_*.rpt             predict --at / --sweep

A scaled corner is usually one nobody has a library for, so it is usually NOT
in the measured grid and no predictions file will hold it until it is asked for
by name. When that is the case this prints the command:

    bash scripts/run.sh predict --at 0.52:rcmax --temp 125

and finds the resulting report on the next run.

JOINING
-------
By `idx` when both sides carry it, otherwise by path key, normalising the
`_#<n>` that distinguishes paths sharing a start and an end. Never by row
order: the two tools can report a different number of paths, and lining them up
by position compares different paths while looking like a model error. How many
joined, and on what, is printed every time.
"""
import argparse
import os
import re
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# Enough naming conventions that an unfamiliar deliverable is read rather than
# skipped. Longest first: `rcmax` must win over `cmax`, which is a substring of
# it, or every RC corner reads as a C corner.
LEVELS = ("rcworst", "rcbest", "rcmax", "rcmin", "rctyp", "cworst", "cbest",
          "typical", "cnom", "ctyp", "cmax", "cmin")

_V_P = re.compile(r"(\d)p(\d{1,3})\s*v", re.I)
_V_D = re.compile(r"(\d)\.(\d{1,3})\s*v", re.I)
_V_MV = re.compile(r"(\d{3,4})\s*mv", re.I)
_T = re.compile(r"(?:^|[^a-z0-9])(m|n|-)?(\d{1,3})\s*c(?:[^a-z]|$)", re.I)
_SUFFIX = re.compile(r"_#\d+$")

# What the second series is called on the figure. The comparison is against the
# OLS base by default -- `run.sh base --save` -- and saying "this model" of it
# would name the wrong thing: the base is the closed-form fit, the model is the
# base plus a trained residual, and they are different claims.
MINE = {"base": "base (OLS)", "hidden": "model (trained)",
        "all": "model (trained)"}


def tokens(name):
    """(voltage, temp, level, check) from a name. None for anything absent.

    Used on BOTH the scaling file names and the model's own corner labels --
    `SSPG_0p52V_RCMAX` and `restored_scaled_SSPG_0p52V_125C_RCMAX_V_hold.rpt`
    are the same convention, so one reader keeps the two sides from drifting.
    The caller reports what it could not read instead of guessing: a wrong
    guess here compares two different corners, and the plot then looks like a
    model error.
    """
    n = os.path.basename(str(name)).lower()
    v = None
    m = _V_P.search(n) or _V_D.search(n)
    if m:
        v = float("%s.%s" % (m.group(1), m.group(2)))
    else:
        m = _V_MV.search(n)
        if m:
            v = int(m.group(1)) / 1000.0
    t = None
    m = _T.search(n)
    if m:
        t = ("-" if m.group(1) in ("m", "n", "-") else "") + m.group(2)
    lv = next((l for l in LEVELS if l in n), None)
    check = "hold" if "hold" in n else ("setup" if "setup" in n else None)
    return v, t, lv, check


def same_corner(label, v, lv):
    """Does a model corner label name this (voltage, level)?"""
    lv2 = tokens(label)[0], tokens(label)[2]
    return (lv2[0] is not None and abs(lv2[0] - v) < 1e-5
            and (lv is None or lv2[1] == lv))


def _norm(key):
    """Path key as both sides spell it.

    The builder appends `_#<n>` to tell apart paths that share a startpoint and
    an endpoint. A plain report has no such suffix to offer, so it is dropped
    from both sides before joining -- at the cost that a start/end pair with
    several paths joins ambiguously, which `read_plain` refuses to do.
    """
    return _SUFFIX.sub("", str(key).strip())


# --------------------------------------------------------------------- reading
def read_pt(fp):
    """One PrimeTime report -> ({idx: ps}, {key: ps}, {key: idx}, how).

    Tries this repo's own parser first, which wants the `### FIXED_PATH idx=<n>
    key=<start>-><end>` headers that the fixed-path re-measurement flow emits.
    A scaling run done outside that flow is a plain concatenation of
    `report_timing` output with no headers at all, and gets read by
    `read_plain`. Which one was used is reported, because it decides what the x
    axis means.
    """
    from si_model.parsing.annotated import parse_annotated

    by_idx, by_key, k2i = {}, {}, {}
    try:
        paths = parse_annotated(fp)
    except Exception:                               # noqa: BLE001
        paths = {}
    for i, pa in paths.items():
        s = getattr(pa, "slack", float("nan"))
        if s != s:                                  # NaN: unresolved block
            continue
        by_idx[int(i)] = float(s) * 1000.0
        k = _norm(getattr(pa, "key", "") or "")
        if k:
            by_key[k] = float(s) * 1000.0
            k2i[k] = int(i)
    if by_idx or by_key:
        return by_idx, by_key, k2i, "FIXED_PATH"
    return {}, read_plain(fp), {}, "plain report_timing"


def read_plain(fp):
    """{start->end: ps} from a report with no FIXED_PATH headers.

    Keyed on the only identifier a plain report offers. A start/end pair that
    appears more than once cannot be told apart, so it is dropped rather than
    joined to whichever of its namesakes came last.
    """
    from si_model.parsing.annotated import ENDPOINT_RE, SLACK_RE, STARTPOINT_RE

    out, dup = {}, set()
    start = end = None
    with open(fp, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = STARTPOINT_RE.match(line)
            if m:
                start, end = m.group(1), None
                continue
            m = ENDPOINT_RE.match(line)
            if m:
                end = m.group(1)
                continue
            m = SLACK_RE.match(line)
            if m and start and end:
                k = "%s->%s" % (start, end)
                (dup.add(k) if k in out else None)
                out[k] = float(m.group(1)) * 1000.0
                start = end = None
    for k in dup:
        out.pop(k, None)
    return out


def read_npz(runs, design, temp, v, lv, tag="base"):
    """The OLS base's take on one corner, or None.

    Returns (base by idx, base by key, label, source). No measurement: a corner
    reached by scaling is one with no library, which is the whole reason it was
    scaled, so there is nothing to have measured it with.

    `tag` names the file -- predictions_base.npz by default, which is what
    `run.sh base --save` writes. It used to take whichever predictions_*.npz
    sorted first, so a directory holding both a base and a trained run compared
    PrimeTime against whichever one that happened to be, and the figure said
    only "this model". The two are different claims and the comparison is about
    the base.
    """
    if not os.path.isdir(runs):
        return None
    designs = [design] if design else sorted(os.listdir(runs))
    for dsg in designs:
        if dsg == "_all":
            continue
        d = os.path.join(runs, dsg, str(temp))
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f != "predictions_%s.npz" % tag:
                continue
            try:
                z = np.load(os.path.join(d, f), allow_pickle=False)
            except Exception:                       # noqa: BLE001
                continue
            if "corners" not in z.files or "model_ps" not in z.files:
                continue
            labels = [str(x) for x in z["corners"]]
            ci = next((i for i, lab in enumerate(labels)
                       if same_corner(lab, v, lv)), None)
            if ci is None:
                continue
            keys = [_norm(x) for x in z["path_keys"]]
            mod = np.asarray(z["model_ps"], float)[:, ci]
            ids = ([int(x) for x in np.asarray(z["path_idx"], np.int64)]
                   if "path_idx" in z.files else None)
            return (dict(zip(ids, mod)) if ids else {},
                    dict(zip(keys, mod)),
                    labels[ci], os.path.join(dsg, str(temp), f))
    return None


def _spans(rule):
    """Column spans of a `---- ------ ---` rule line, as (start, stop) pairs."""
    return [(m.start(), m.end()) for m in re.finditer(r"-+", rule)]


def read_predict_rpt(fp, design, v, lv):
    """({idx: ps}, {key: ps}, label) for one corner out of a predict report.

    `predict --at` writes a column-aligned text report and no array file, and
    an unmeasured scaling corner is exactly the case that needs `--at`, so the
    report has to be readable. Columns are cut on the rule line's dash groups
    rather than split on whitespace: a cell is blank where a model has no such
    corner, and splitting would then shift every later value one column left.
    """
    with open(fp, encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    cur, want = None, (design or None)
    label, col, spans, idx_s, key_s = None, None, None, None, None
    by_idx, by_key = {}, {}
    for i, line in enumerate(lines):
        if line.startswith("Design: ") or line.startswith("\nDesign: "):
            cur = line.split(":", 1)[1].strip()
            label = col = spans = None
            continue
        if re.match(r"^\s+-{3,} -{3,}", line) and i >= 2:
            head = lines[i - 2]
            spans = _spans(line)
            if len(spans) < 3:
                spans = None
                continue
            idx_s, key_s, val_s = spans[0], spans[1], spans[2:]
            col = None
            for j, (a, b) in enumerate(val_s):
                lab = head[a:b].strip() if a < len(head) else ""
                if lab and same_corner(lab, v, lv):
                    col, label = (a, b), lab
                    break
            if col is None:
                spans = None
            continue
        if spans is None or col is None:
            continue
        if want and cur != want:
            continue
        raw_i = line[idx_s[0]:idx_s[1]].strip()
        if not raw_i.lstrip("-").isdigit():
            continue                                 # summary rows, blanks
        txt = line[col[0]:col[1]].strip()
        if not txt:
            continue
        try:
            val = float(txt)
        except ValueError:
            continue
        by_idx[int(raw_i)] = val
        k = _norm(line[key_s[0]:key_s[1]])
        if k:
            by_key.setdefault(k, val)
    return by_idx, by_key, label


def find_predict_rpt(runs, temp, design, v, lv, tag="base"):
    """The newest report that carries this corner.

    `predict_<temp>_<tag>.rpt` first -- the one `base --save` writes -- then any
    other predict report, because a corner with no library is usually reachable
    only through `predict --at`, which names its own file.
    """
    d = os.path.join(runs, "_all")
    if not os.path.isdir(d):
        return None
    cands = [os.path.join(d, f) for f in os.listdir(d)
             if f.startswith("predict_") and f.endswith(".rpt")
             and (temp is None or ("_%s_" % temp) in f)]
    cands.sort(key=lambda f: (not f.endswith("_%s.rpt" % tag),
                              -os.path.getmtime(f)))
    for fp in cands:
        try:
            bi, bk, lab = read_predict_rpt(fp, design, v, lv)
        except Exception:                           # noqa: BLE001
            continue
        if bi or bk:
            return bi, bk, lab, os.path.relpath(fp, runs)
    return None


# ---------------------------------------------------------------------- joining
def join(pt, mod):
    """(x, pt, model, how) over the paths both sides have.

    By idx when both carry it, else by path key. Never by row order while a key
    is available: the two tools can report a different number of paths, and
    lining them up by position compares different paths while looking like a
    model error.
    """
    pt_idx, pt_key, k2i = pt
    m_idx, m_key = mod

    def _out(common, a, b, x, how):
        return (np.asarray(x, float),
                np.asarray([a[k] for k in common], float),
                np.asarray([b[k] for k in common], float), how)

    if pt_idx and m_idx:
        common = sorted(set(pt_idx) & set(m_idx))
        if common:
            return _out(common, pt_idx, m_idx, common, "idx")
    common = sorted(set(pt_key) & set(m_key))
    if not common:
        return None
    # keep the report's own path number on the x axis wherever the report gave
    # one, so a point is still something to grep for
    have_idx = all(k in k2i for k in common)
    if have_idx:
        common.sort(key=lambda k: k2i[k])
    x = [k2i[k] if have_idx else j for j, k in enumerate(common)]
    return _out(common, pt_key, m_key, x,
                "path key" if have_idx else "path key, no idx in the report")


# --------------------------------------------------------------------- drawing
def draw(plt, x, pt, mine, title, xlabel, fp, mine_label="base (OLS)"):
    """One panel, two series.

    The difference between them was its own panel for a while. It is one
    number per path and the eye already reads it as the vertical gap, so the
    panel only halved the axis the values are actually read on. Its summary
    -- mean, worst, spread -- is printed to the terminal instead, where it can
    be copied into a mail.
    """
    fig, a = plt.subplots(1, 1, figsize=(9.5, 5.2))
    a.scatter(x, pt, s=20, alpha=0.75, marker="^", label="PT scaling")
    a.scatter(x, mine, s=20, alpha=0.75, marker="o", label=mine_label)
    a.set_xlabel(xlabel)
    a.set_ylabel("Slack (ps)")
    a.set_title(title, fontsize=11)
    a.grid(True, lw=0.5, alpha=0.5)
    a.legend(fontsize=9, frameon=False)
    fig.tight_layout()
    fig.savefig(fp, dpi=150)
    plt.close(fig)


# ------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="PrimeTime voltage scaling against this model, path by path.")
    ap.add_argument("--scaling", required=True,
                    help="directory of PT scaling reports, searched "
                         "recursively -- hold/ and setup/ below it are fine")
    ap.add_argument("--runs", default=None,
                    help="this model's output tree (default runs/<mode>)")
    ap.add_argument("--mode", default=None, choices=["setup", "hold"],
                    help="only reports of this check (default: both)")
    ap.add_argument("--temp", default=None, help="only this temperature")
    ap.add_argument("--design", default=None,
                    help="circuit name (default: the last directory of "
                         "--scaling that names one in the runs tree)")
    ap.add_argument("--out", default=None,
                    help="where the .png go (default <runs>/_all/plots)")
    ap.add_argument("--source", default="base",
                    help="which of this repo's own numbers to compare against: "
                         "the tag in predictions_<tag>.npz / "
                         "predict_<temp>_<tag>.rpt. Default base -- the OLS "
                         "base, what `run.sh base --save` writes. Use hidden "
                         "for a trained run")
    ap.add_argument("--list", action="store_true", dest="list_only",
                    help="print what every name was read as and what was found "
                         "for it, and draw nothing. Run this first")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.scaling):
        print("no such directory: %s" % args.scaling, file=sys.stderr)
        return 1
    found = []
    for root, _, files in os.walk(args.scaling):
        for f in sorted(files):
            if f.lower().endswith((".rpt", ".txt", ".log", ".report")):
                found.append(os.path.join(root, f))
    if not found:
        print("no .rpt/.txt/.log under %s" % args.scaling, file=sys.stderr)
        return 1

    # the design usually names a directory on the scaling path
    design = args.design
    if design is None:
        parts = [x for x in os.path.abspath(args.scaling).split(os.sep) if x]
        for cand in reversed(parts[-3:]):
            if cand.lower() not in ("scaling", "setup", "hold"):
                design = cand
                break
        print("design  : %s   (from the --scaling path; override with --design)"
              % design)

    jobs, skipped = [], []
    for fp in found:
        v, t, lv, check = tokens(fp)
        # the check often names the parent directory, not the file
        if check is None:
            low = os.path.dirname(fp).lower()
            check = "hold" if "hold" in low else ("setup" if "setup" in low
                                                 else None)
        if args.mode and check and check != args.mode:
            continue
        if args.temp is not None and t is not None and t != str(args.temp):
            continue
        if v is None or lv is None:
            skipped.append((fp, "voltage" if v is None else "BEOL level"))
            continue
        jobs.append((fp, v, t, lv, check))

    print("%d report(s) under %s" % (len(found), args.scaling))
    for fp, v, t, lv, check in jobs:
        print("  %-54s -> %.3fV %-7s %-5s %s"
              % (os.path.basename(fp)[:54], v, lv,
                 (t + "C") if t else "?C", check or "?"))
    for fp, why in skipped:
        print("  %-54s -- no %s in the name, skipped"
              % (os.path.basename(fp)[:54], why))
    if not jobs:
        print("nothing to compare -- no name carried both a voltage and a "
              "BEOL level", file=sys.stderr)
        return 1

    pairs, missing = [], []
    for fp, v, t, lv, check in jobs:
        mode = args.mode or check or "setup"
        runs = args.runs or os.path.join("runs", mode)
        got = (read_npz(runs, design, t, v, lv, args.source)
               or find_predict_rpt(runs, t, design, v, lv, args.source))
        if got is None:
            missing.append((v, lv, t, mode))
            print("  [no %s] %.3fV %s %sC %s -- no predictions_%s.npz nor "
                  "predict_%s_%s.rpt under %s"
                  % (args.source, v, lv, t, mode, args.source, t,
                     args.source, runs))
            continue
        m_idx, m_key, label, src = got
        pt_idx, pt_key, k2i, how_read = read_pt(fp)
        if not (pt_idx or pt_key):
            print("  [unreadable] %s -- no slack lines found in it"
                  % os.path.basename(fp))
            continue
        j = join((pt_idx, pt_key, k2i), (m_idx, m_key))
        if j is None:
            print("  [no overlap] %.3fV %s %sC : %d PT paths, %d model paths, "
                  "none in common -- different path sets"
                  % (v, lv, t, max(len(pt_idx), len(pt_key)),
                     max(len(m_idx), len(m_key))))
            continue
        x, y_pt, y_me, how = j
        print("  [matched] %.3fV %-7s %sC %-5s : %d paths joined on %s "
              "(PT read as %s; %s %s <- %s)"
              % (v, lv, t, mode, len(x), how, how_read, args.source, label,
                 src))
        # the one number the difference panel used to carry
        d = y_pt - y_me
        d = d[np.isfinite(d)]
        if len(d):
            print("            PT scaling - %s: mean %+.1f ps, worst "
                  "%+.1f ps, spread %.1f ps"
                  % (args.source, d.mean(), d[np.argmax(np.abs(d))], d.std()))
        pairs.append((v, t, lv, mode, x, y_pt, y_me, how, len(x)))

    if missing:
        print("\nto produce the missing ones:")
        for v, lv, t, mode in sorted(set(missing)):
            md = "" if mode == "setup" else " --mode hold"
            if args.source == "base":
                # the base at a corner nobody measured: it is a fit, so it has
                # a value everywhere -- but only --at writes one out by name
                print("  bash scripts/run.sh base --save --temp %s%s"
                      "        # if %g:%s is in the measured grid" % (t, md, v, lv))
            print("  bash scripts/run.sh predict --at %g:%s --temp %s%s"
                  % (v, lv, t, md))
        print("  then run this again -- it reads what those write.")

    if args.list_only:
        return 0
    if not pairs:
        print("nothing could be drawn", file=sys.stderr)
        return 1

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:                          # noqa: BLE001
        print("drawing needs matplotlib: %s\n"
              "  --list works without it, and printed the numbers above."
              % e, file=sys.stderr)
        return 1

    made = []
    for v, t, lv, mode, x, y_pt, y_me, how, n in pairs:
        out_dir = args.out or os.path.join(args.runs or os.path.join("runs", mode),
                                           "_all", "plots")
        try:
            os.makedirs(out_dir)
        except OSError:
            if not os.path.isdir(out_dir):
                raise
        name = "ptscale_%s_%s_%s_%s_%gV_%s.png" % (
            design or "design", args.source, mode, t or "temp", v, lv)
        fp = os.path.join(out_dir, name)
        draw(plt, x, y_pt, y_me,
             "PT scaling vs %s -- %s  %.3fV %s %sC %s   (%d paths)"
             % (MINE.get(args.source, args.source), design or "", v, lv,
                t or "?", mode, n),
             "Path (report order)" if "no idx" in how else "Path index",
             fp, MINE.get(args.source, args.source))
        made.append(fp)
    for f in made:
        print("wrote %s" % f)
    print("%d figure(s)" % len(made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
