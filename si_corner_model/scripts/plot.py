#!/usr/bin/env python3
"""Scatter and rank-movement figures, from the prediction files on disk.

    python3 scripts/plot.py                                  # everything under runs/setup
    python3 scripts/plot.py --runs runs/extrapolation/setup  # the experiment tree
    python3 scripts/plot.py --design MFC_Timing_Report --temp 125
    python3 scripts/plot.py --corners hidden --out plots

Reads ``<runs>/<circuit>/<temp>/predictions_<corners>.npz`` -- path_keys,
corners, truth_ps, model_ps, which is what train and predict write -- and
produces, per model:

  scatter_<circuit>_<temp>_<corner>.png   true vs predicted slack at one corner,
                                          with y = x and the corner's MAE
  rank_<circuit>_<temp>.png               where each tracked path sits in the
                                          slack ordering at every corner, true
                                          beside predicted

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
import sys

import numpy as np


def _load(fp):
    """(path_keys, corners, truth[N,C], model[N,C]) from a predictions npz."""
    z = np.load(fp, allow_pickle=False)
    keys = [str(x) for x in z["path_keys"]]
    corners = [str(x) for x in z["corners"]]
    if "truth_ps" in z:
        truth, model = np.asarray(z["truth_ps"], float), np.asarray(z["model_ps"], float)
    else:                                   # the slew task stores ns
        truth = np.asarray(z["truth_ns"], float) * 1000.0
        model = np.asarray(z["model_ns"], float) * 1000.0
    return keys, corners, truth, model


def _find(runs, corners, design=None, temp=None):
    """[(circuit, temp, path)] for every prediction file under `runs`."""
    out = []
    if not os.path.isdir(runs):
        return out
    for d in sorted(os.listdir(runs)):
        if d == "_all" or not os.path.isdir(os.path.join(runs, d)):
            continue
        if design and d != design:
            continue
        for t in sorted(os.listdir(os.path.join(runs, d))):
            if temp and t != str(temp):
                continue
            fp = os.path.join(runs, d, t, "predictions_%s.npz" % corners)
            if os.path.exists(fp):
                out.append((d, t, fp))
    return out


def scatter(plt, keys, corners, truth, model, circuit, temp, out_dir):
    """One figure per corner: predicted against measured, with y = x.

    The diagonal is the whole content of the plot -- distance from it is the
    error, and a cloud that bends away from it at one end is a model that is
    fine in the middle of the range and not at the edges, which no single MAE
    would show. Corners with no measurement are skipped rather than drawn
    against NaN.
    """
    made = []
    for ci, corner in enumerate(corners):
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
        ax.set_ylabel("Pred Slack (ps)")
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, lw=0.5, alpha=0.5)
        fig.tight_layout()
        fp = os.path.join(out_dir, "scatter_%s_%s_%s.png"
                          % (circuit, temp, corner.replace("/", "_")))
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


def rank_movement(plt, keys, corners, truth, model, circuit, temp, out_dir,
                  n_track=5):
    """True and predicted rank trajectories, side by side.

    The tracked paths are the ones whose TRUE rank moves most from the first
    corner to the last: a path that holds its position says nothing about
    whether the model follows the ordering, and with a few thousand paths the
    ones that stay put are nearly all of them.

    The two panels share a y axis so a difference in shape is the difference
    between the model and the measurement, not between two scalings.
    """
    ok_cols = [ci for ci in range(len(corners))
               if np.isfinite(truth[:, ci]).any() and np.isfinite(model[:, ci]).any()]
    if len(ok_cols) < 2:
        return []
    cn = [corners[ci] for ci in ok_cols]
    rt = _ranks(truth[:, ok_cols])
    rp = _ranks(model[:, ok_cols])
    move = np.abs(rt[:, -1] - rt[:, 0])
    move[~np.isfinite(move)] = -1
    track = list(np.argsort(-move)[:min(n_track, len(keys))])

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.6), sharey=True)
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    for pi, p in enumerate(track):
        c = colors[pi % len(colors)]
        err = float(np.nanmean(np.abs(model[p, ok_cols] - truth[p, ok_cols])))
        lab = ("p%d: base %d, end T/P %d/%d, |err| %.1f ps"
               % (pi + 1, rt[p, 0], rt[p, -1], rp[p, -1], err))
        axes[0].plot(range(len(cn)), rt[p], "-o", color=c, ms=5, label=lab)
        axes[1].plot(range(len(cn)), rp[p], "-o", color=c, ms=5)
        for ax, r in ((axes[0], rt), (axes[1], rp)):
            ax.annotate("p%d" % (pi + 1), (0, r[p, 0]), textcoords="offset points",
                        xytext=(-16, -4), color=c, fontsize=9)
    for ax, title in zip(axes, ("True rank trajectory", "Predicted rank trajectory")):
        ax.set_title(title, fontsize=12)
        ax.set_xticks(range(len(cn)))
        ax.set_xticklabels(cn, rotation=45, ha="right", fontsize=8)
        ax.grid(True, lw=0.5, alpha=0.5)
    axes[0].set_ylabel("Rank position  (1 = worst slack)")
    fig.suptitle("%s %s - rank movement over %d corners (baseline %s)"
                 % (circuit, temp, len(cn), cn[0]), fontsize=12)
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.93), ncol=2, fontsize=8,
               frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fp = os.path.join(out_dir, "rank_%s_%s.png" % (circuit, temp))
    fig.savefig(fp, dpi=150)
    plt.close(fig)
    return [fp]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", default="runs/setup",
                    help="the tree to read (default runs/setup; an experiment "
                         "is runs/<tag>/<mode>)")
    ap.add_argument("--corners", default="hidden",
                    help="which prediction file: hidden (default), seen, all, "
                         "or hidden_from_<circuit> for a borrowed model")
    ap.add_argument("--design", default=None, help="this circuit only")
    ap.add_argument("--temp", default=None, help="this temperature only")
    ap.add_argument("--out", default="plots", help="where the .png go")
    ap.add_argument("--track", type=int, default=5,
                    help="how many paths the rank figure follows (default 5)")
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

    found = _find(args.runs, args.corners, args.design, args.temp)
    if not found:
        print("no predictions_%s.npz under %s%s.\n"
              "  Run `bash scripts/run.sh predict` first, or point --runs at the\n"
              "  right tree (an experiment writes to runs/<tag>/<mode>)."
              % (args.corners, args.runs,
                 "" if not args.design else " for " + args.design),
              file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    made = []
    for circuit, temp, fp in found:
        keys, corners, truth, model = _load(fp)
        made += scatter(plt, keys, corners, truth, model, circuit, temp, args.out)
        made += rank_movement(plt, keys, corners, truth, model, circuit, temp,
                              args.out, args.track)
    for fp in made:
        print("wrote %s" % fp)
    print("%d figures in %s/" % (len(made), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
