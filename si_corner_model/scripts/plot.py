#!/usr/bin/env python3
"""Scatter and rank-movement figures, from the prediction files on disk.

    python3 scripts/plot.py                 # runs/setup -> runs/setup/_all/plots
    python3 scripts/plot.py --runs runs/extrapolation/setup  # the experiment tree
    python3 scripts/plot.py --design MFC_Timing_Report --temp 125
    python3 scripts/plot.py --corners hidden --out plots

Reads ``<runs>/<circuit>/<temp>/predictions_<corners>.npz`` -- path_keys,
corners, truth_ps, model_ps, which is what train and predict write -- and
produces:

  scatter_<circuit>_<temp>_<corner>.png   one per held-out corner: true vs
                                          predicted slack, y = x, the MAE
  rank_<circuit>.png                      one per CIRCUIT, every temperature on
                                          one trajectory: where each tracked
                                          path sits in the slack ordering at
                                          every held-out corner, true beside
                                          predicted

The rank figure is the one that answers "would this model have picked the same
critical paths": slack error in ps says how close the numbers are, and says
nothing about whether the ORDER survives, which is what a designer acts on. A
path that moves from 54th to 63rd worst across corners is the interesting case,
and a model that reproduces the movement is useful even where its ps are off.

Needs matplotlib. Nothing else here imports it, so a machine without it runs
the whole pipeline and only loses this script, which says so and exits.
"""
import argparse
import os
import re
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(fp):
    """(path_keys, corners, seen[C], truth[N,C], model[N,C]) from a npz.

    `seen` marks the corners the model was fit on. Files written before it was
    recorded come back all-False, which is what predictions_hidden.npz is.
    """
    z = np.load(fp, allow_pickle=False)
    keys = [str(x) for x in z["path_keys"]]
    corners = [str(x) for x in z["corners"]]
    seen = (np.asarray(z["seen"], bool) if "seen" in z.files
            else np.zeros(len(corners), bool))
    if "truth_ps" in z:
        truth, model = np.asarray(z["truth_ps"], float), np.asarray(z["model_ps"], float)
    else:                                   # the slew task stores ns
        truth = np.asarray(z["truth_ns"], float) * 1000.0
        model = np.asarray(z["model_ns"], float) * 1000.0
    return keys, corners, seen, truth, model



_IDX = re.compile(r"_?#\d+$")


def temp_label(t):
    """`125` -> `125C`, `m25` -> `-25C`: how a temperature reads on an axis."""
    t = str(t)
    if t[:1] in ("m", "n") and t[1:].isdigit():
        return "-%sC" % t[1:]
    return t + "C" if t.lstrip("-").isdigit() else t


def combine_temps(loaded):
    """One rank matrix for a circuit over EVERY temperature it was run at.

    Asked for: one rank figure per circuit, not one per temperature. Each
    temperature is its own model and its own prediction file, so the paths are
    joined by KEY, with the trailing `_#<n>` taken off -- that is a per-report
    ordinal, not part of a path's identity, and it need not agree between two
    temperatures' reports. Only paths present at every temperature are kept
    (a rank is a position among the SAME set of paths, column to column), and a
    key that is ambiguous once the ordinal is gone is left out rather than
    joined to the wrong path.

    Corners are labelled with their temperature: two temperatures can hold out
    the same (voltage, level), and without it the axis would show the same name
    twice for two different measurements. Temperatures in the order given,
    each with its corners in grid order, so each temperature's sweep stays
    together.

    Returns (keys, corners, seen, truth, model, note) or None.
    """
    from collections import Counter

    if len(loaded) == 1:
        t, keys, corners, seen, truth, model = loaded[0]
        return (keys, ["%s %s" % (temp_label(t), c) for c in corners],
                np.asarray(seen, bool), truth, model, "")
    maps = []
    for t, keys, corners, seen, truth, model in loaded:
        nk = [_IDX.sub("", k) for k in keys]
        cnt = Counter(nk)
        maps.append({k: i for i, k in enumerate(nk) if cnt[k] == 1})
    common = [k for k in maps[0] if all(k in m for m in maps[1:])]
    if not common:
        return None
    cs, ss, T, M = [], [], [], []
    for (t, keys, corners, seen, truth, model), m in zip(loaded, maps):
        rows = [m[k] for k in common]
        T.append(np.asarray(truth)[rows])
        M.append(np.asarray(model)[rows])
        cs += ["%s %s" % (temp_label(t), c) for c in corners]
        ss += [bool(x) for x in seen]
    sizes = [len(x[1]) for x in loaded]
    note = ("" if all(n == len(common) for n in sizes) else
            "%d paths common to all temperatures (of %s)"
            % (len(common), "/".join(str(n) for n in sizes)))
    return common, cs, np.asarray(ss, bool), np.hstack(T), np.hstack(M), note

_TAIL = re.compile(r"(?:[_-]?timing)?(?:[_-]?reports?)$", re.I)


def short_name(name):
    """`PERIC0_Timing_Report` -> `PERIC0`, for titles and file names.

    The configured circuit name is the report directory's name, and on the
    company drop that carries a `_Timing_Report` tail which says nothing about
    the circuit and doubled the length of every title. Asked for: take it off.
    A name that is nothing BUT such a tail is left as it is.
    """
    s = _TAIL.sub("", str(name)).rstrip("_-")
    return s or str(name)


def same_design(want, have):
    """`PERIC0` names `PERIC0_Timing_Report`: a prefix match up to a
    separator, so --design takes the short name or the configured one."""
    if not want:
        return True
    a, b = str(want).lower(), str(have).lower()
    if a == b:
        return True
    return b.startswith(a) and len(b) > len(a) and not b[len(a)].isalnum()


def _find(runs, corners, design=None, temp=None):
    """[(circuit, temp, path)] for every prediction file under `runs`."""
    out = []
    if not os.path.isdir(runs):
        return out
    for d in sorted(os.listdir(runs)):
        if d == "_all" or not os.path.isdir(os.path.join(runs, d)):
            continue
        if design and not same_design(design, d):
            continue
        for t in sorted(os.listdir(os.path.join(runs, d))):
            if temp and t != str(temp):
                continue
            fp = os.path.join(runs, d, t, "predictions_%s.npz" % corners)
            if os.path.exists(fp):
                out.append((d, t, fp))
    return out


def scatter(plt, keys, corners, seen, truth, model, circuit, temp, out_dir,
            include_seen=False, tag=""):
    """One figure per HELD-OUT corner: predicted against measured, with y = x.

    Seen corners are skipped. The model was fit on them, so the scatter shows
    the fit against its own data and is tight by construction -- a page of
    those says nothing and buries the corners that do. `--include-seen` draws
    them anyway.

    The diagonal is the whole content of the plot -- distance from it is the
    error, and a cloud that bends away from it at one end is a model that is
    fine in the middle of the range and not at the edges, which no single MAE
    would show. Corners with no measurement are skipped rather than drawn
    against NaN.
    """
    made = []
    for ci, corner in enumerate(corners):
        if seen[ci] and not include_seen:
            continue
        t, md = truth[:, ci], model[:, ci]
        ok = np.isfinite(t) & np.isfinite(md)
        if not ok.any():
            continue
        t, md = t[ok], md[ok]
        mae = float(np.abs(md - t).mean())
        lo, hi = float(min(t.min(), md.min())), float(max(t.max(), md.max()))
        pad = 0.05 * (hi - lo or 1.0)
        fig, ax = plt.subplots(figsize=(5.2, 5.2))
        ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "r--", lw=1.2, zorder=1)
        ax.scatter(t, md, s=18, alpha=0.45, edgecolors="none", zorder=2)
        ax.set_title("%s  %s\nMAE=%.2f ps   N=%d" % (circuit, corner, mae, len(t)),
                     fontsize=11, fontweight="bold")
        ax.set_xlabel("True Slack (ps)")
        ax.set_ylabel("Prediction Slack (ps)")
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, lw=0.5, alpha=0.5)
        fig.tight_layout()
        fp = os.path.join(out_dir, "scatter_%s_%s_%s%s.png"
                          % (circuit, temp, corner.replace("/", "_"), tag))
        fig.savefig(fp, dpi=150)
        plt.close(fig)
        made.append(fp)
    return made


def _ranks(y):
    """[N, C] rank of each path at each corner: 1 = worst (smallest) slack.

    Ranked on the slack itself rather than on the error, because the ordering
    is what a designer reads: rank 1 is the path that closes last. NaN columns
    come back as NaN rather than sorting to one end.
    """
    r = np.full(y.shape, np.nan)
    for ci in range(y.shape[1]):
        col = y[:, ci]
        ok = np.isfinite(col)
        if not ok.any():
            continue
        order = np.argsort(np.argsort(col[ok], kind="stable"), kind="stable")
        r[np.where(ok)[0], ci] = order + 1
    return r


def rank_movement(plt, keys, corners, seen, truth, model, circuit, temp,
                  out_dir, n_track=5, include_seen=False, tag=""):
    """True and predicted rank trajectories, side by side.

    The tracked paths are the ones whose TRUE rank moves most, measured as the
    TOTAL VARIATION along the trajectory -- the sum of the step-to-step
    changes -- and not as the distance from the first corner to the last. The
    interesting path is the one that climbs and falls and crosses the others on
    the way; by endpoints alone that path scores zero, and what gets drawn is
    five flat lines. A path that holds its position says nothing about whether
    the model follows the ordering anyway, and with a few thousand paths those
    are nearly all of them.

    The two panels share a y axis so a difference in shape is the difference
    between the model and the measurement, not between two scalings.

    Seen corners are left off the axis like everywhere else. A rank is computed
    within one corner's ordering and does not depend on the other columns, so
    dropping them changes none of the ranks that remain -- the line simply
    joins the held-out corners directly. `--include-seen` puts them back, and
    then the tick labels say which is which.
    """
    ok_cols = [ci for ci in range(len(corners))
               if (include_seen or not seen[ci])
               and np.isfinite(truth[:, ci]).any()
               and np.isfinite(model[:, ci]).any()]
    if len(ok_cols) < 2:
        return []
    cn = [corners[ci] for ci in ok_cols]
    rt = _ranks(truth[:, ok_cols])
    rp = _ranks(model[:, ok_cols])
    step = np.abs(np.diff(rt, axis=1))
    move = np.nansum(step, axis=1)
    move[~np.isfinite(rt).all(axis=1)] = -1.0     # a path missing at a corner
    span = np.nanmax(rt, axis=1) - np.nanmin(rt, axis=1)   # ties: the wider one
    order = np.lexsort((-span, -move))
    track = [int(i) for i in order[:min(n_track, len(keys))] if move[i] > 0]
    if not track:                      # a grid where nothing reorders at all
        track = [int(i) for i in order[:min(n_track, len(keys))]]

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.6), sharey=True)
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for pi, p in enumerate(track):
        c = colors[pi % len(colors)]
        err = float(np.nanmean(np.abs(model[p, ok_cols] - truth[p, ok_cols])))
        # Rank summaries average over EVERY corner on the axis, not the last
        # one: the figure is about the whole trajectory, and a single end
        # point hides a path that wanders off and comes back.
        mean_true = float(np.nanmean(rt[p]))
        mean_pred = float(np.nanmean(rp[p]))
        rank_err = float(np.nanmean(np.abs(rp[p] - rt[p])))
        # "start", not "base": with --corners base the figure is OF the base,
        # and a legend saying "base 12" read as the OLS base's rank
        lab = ("p%d: start %d, mean rank True/Prediction %.1f/%.1f, "
               "mean |rank err| %.1f, |err| %.1f ps"
               % (pi + 1, rt[p, 0], mean_true, mean_pred, rank_err, err))
        axes[0].plot(range(len(cn)), rt[p], "-o", color=c, ms=5, label=lab)
        axes[1].plot(range(len(cn)), rp[p], "-o", color=c, ms=5)
        for ax, r in ((axes[0], rt), (axes[1], rp)):
            ax.annotate("p%d" % (pi + 1), (0, r[p, 0]), textcoords="offset points",
                        xytext=(-16, -4), color=c, fontsize=9)
    for ax, title in zip(axes, ("True rank trajectory", "Prediction rank trajectory")):
        ax.set_title(title, fontsize=12)
        ax.set_xticks(range(len(cn)))
        ax.set_xticklabels([c + (" (seen)" if seen[ok_cols[i]] else "")
                            for i, c in enumerate(cn)] if include_seen else cn,
                           rotation=45, ha="right", fontsize=8)
        ax.grid(True, lw=0.5, alpha=0.5)
    axes[0].set_ylabel("Rank position  (1 = worst slack)")
    who = " ".join(x for x in (circuit, temp) if x)
    fig.suptitle("%s - rank movement over %d corners (start %s)"
                 % (who, len(cn), cn[0]), fontsize=12)
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.93), ncol=2, fontsize=8,
               frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fp = os.path.join(out_dir, "rank_%s%s.png"
                      % ("_".join(x for x in (circuit, temp) if x), tag))
    fig.savefig(fp, dpi=150)
    plt.close(fig)
    return [fp]


def _say_where(args):
    """Nothing to draw: say where the files ARE, and what writes them.

    It used to tell everyone to run `predict` -- including someone drawing the
    base (`--corners base`), whose files `base --save` writes -- and to name
    only the one tree it had looked in. Files made earlier under runs/hold or
    runs/extrapolation/hold then looked missing, and the advice was to redo
    work that was already done.
    """
    want = "predictions_%s.npz" % args.corners
    print("no %s under %s%s." % (want, args.runs,
                                 "" if not args.design else " for " + args.design),
          file=sys.stderr)
    roots = []
    for base in (os.path.join(REPO, "runs"), "runs"):
        if not os.path.isdir(base):
            continue
        for d, _, files in os.walk(base):
            if want in files:
                # <runs tree>/<circuit>/<temp>/<file> -> the tree
                tree = os.path.dirname(os.path.dirname(d))
                rel = os.path.relpath(tree, REPO) if tree.startswith(REPO) else tree
                if rel not in roots:
                    roots.append(rel)
    if roots:
        print("  it IS here -- draw it with:", file=sys.stderr)
        for r in sorted(roots):
            parts = r.split(os.sep)
            flag = ("--mode %s" % parts[1] if len(parts) == 2 and parts[0] == "runs"
                    else "--tag %s --mode %s" % (parts[1], parts[2])
                    if len(parts) == 3 and parts[0] == "runs" else "--runs %s" % r)
            print("    python3 scripts/plot.py %s%s"
                  % ("" if args.corners == "hidden" else "--corners %s " % args.corners,
                     flag), file=sys.stderr)
        return
    mode = " --mode hold" if args.mode == "hold" else ""
    tag = " --config <that experiment's config>" if args.tag else ""
    if args.corners == "base":
        print("  write it with:  bash scripts/run.sh base --save%s%s"
              % (mode, tag), file=sys.stderr)
    else:
        print("  write it with:  bash scripts/run.sh predict%s%s"
              % (mode, tag), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", default=None,
                    help="the tree to read. Default runs/<mode>, or "
                         "runs/<tag>/<mode> with --tag -- the same place run.sh "
                         "writes to")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup (default) or hold, as for run.sh")
    ap.add_argument("--tag", default=None,
                    help="an experiment's out.tag, e.g. extrapolation -> "
                         "runs/extrapolation/<mode>")
    ap.add_argument("--corners", default="hidden",
                    help="which prediction file: hidden (default), seen, all, "
                         "or hidden_from_<circuit> for a borrowed model")
    ap.add_argument("--design", default=None,
                    help="this circuit only (PERIC0 or PERIC0_Timing_Report)")
    ap.add_argument("--temp", default=None, help="this temperature only")
    ap.add_argument("--out", default=None,
                    help="where the .png go (default <runs>/_all/plots, so the "
                         "figures sit with the run they came from and two "
                         "experiments cannot overwrite each other)")
    ap.add_argument("--track", type=int, default=5,
                    help="how many paths the rank figure follows (default 5)")
    ap.add_argument("--include-seen", action="store_true",
                    help="draw the corners the model was fit on too. Off: "
                         "those show the fit against its own data")
    ap.add_argument("--only", choices=["scatter", "rank"], default=None,
                    help="draw just one kind. --corners all gives one scatter "
                         "per corner, which is 14-21 files per model on a wide "
                         "grid; `--only rank` is usually what that run is for")
    args = ap.parse_args(argv)

    try:
        import matplotlib
        matplotlib.use("Agg")            # no display on a compute node
        import matplotlib.pyplot as plt
    except Exception as e:               # noqa: BLE001 -- any import failure
        print("this script needs matplotlib, and importing it failed: %s\n"
              "  Nothing else in the pipeline uses it, so everything else still\n"
              "  runs. Install it in the environment you run this from:\n"
              "    pip install matplotlib" % e, file=sys.stderr)
        return 1

    if args.runs is None:
        args.runs = os.path.join("runs", *([args.tag] if args.tag else []),
                                 args.mode)
    # run.sh writes under the project, whatever directory this is started from
    if not os.path.isdir(args.runs) and not os.path.isabs(args.runs) \
            and os.path.isdir(os.path.join(REPO, args.runs)):
        args.runs = os.path.join(REPO, args.runs)
    found = _find(args.runs, args.corners, args.design, args.temp)
    if not found:
        _say_where(args)
        return 1

    # Beside the predictions by default. With a fixed `plots/` in the working
    # directory, drawing setup and then the extrapolation experiment wrote the
    # same file names -- same circuit, same temperature, same corner -- and the
    # second quietly replaced the first.
    out_dir = args.out or os.path.join(args.runs, "_all", "plots")
    args.out = out_dir
    os.makedirs(out_dir, exist_ok=True)
    # Which prediction file these came from, in the name. A borrowed model
    # writes predictions_hidden_from_<circuit>.npz, and without this its
    # figures would land on the own-model ones -- same circuit, same
    # temperature, same corner -- and replace them.
    tag = "" if args.corners == "hidden" else "_" + args.corners
    # Short names on the figures and in their file names -- unless two
    # circuits would collapse to the same one, which would make one overwrite
    # the other; those keep the configured name.
    shorts = {}
    for circuit, _, _ in found:
        shorts.setdefault(short_name(circuit), set()).add(circuit)
    by_circuit = {}
    for circuit, temp, fp in found:
        by_circuit.setdefault(circuit, []).append((temp, fp))
    made = []
    for circuit, items in by_circuit.items():
        sn = short_name(circuit)
        name = sn if len(shorts[sn]) == 1 else circuit
        loaded = []
        for temp, fp in items:
            keys, corners, seen, truth, model = _load(fp)
            loaded.append((temp, keys, corners, seen, truth, model))
            # a scatter is one corner, so it stays per temperature
            if args.only != "rank":
                made += scatter(plt, keys, corners, seen, truth, model, name,
                                temp, out_dir, args.include_seen, tag)
        if args.only == "scatter":
            continue
        # ONE rank figure per circuit, across its temperatures
        comb = combine_temps(loaded)
        if comb is None:
            print("  (!) %s: no path is common to %s by key -- rank drawn per "
                  "temperature instead" % (name, ", ".join(t for t, _ in items)),
                  file=sys.stderr)
            for temp, keys, corners, seen, truth, model in loaded:
                made += rank_movement(plt, keys, corners, seen, truth, model,
                                      name, temp, out_dir, args.track,
                                      args.include_seen, tag)
            continue
        keys, corners, seen, truth, model, note = comb
        if note:
            print("  %s rank: %s" % (name, note))
        made += rank_movement(plt, keys, corners, seen, truth, model, name,
                              args.temp or "", out_dir, args.track,
                              args.include_seen, tag)
    for fp in made:
        print("wrote %s" % fp)
    print("%d figures in %s/" % (len(made), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
