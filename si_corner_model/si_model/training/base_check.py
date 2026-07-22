"""Standalone OLS-base quality check -- the ONLY place base-only numbers exist.

Training logs, summaries, and prediction exports report the MODEL only; when you
want to sanity-check the polynomial base by itself (e.g. right after building a
new dataset, before spending GPU time), run this. Needs only numpy (no torch).

    python -m si_model.training.base_check --config configs/<ds>/<model>.yaml

Prints per-hidden-corner base-only error (MAE in ps for slack, MAPE % for slew)
and the seen-corner LOO error, computed with the exact same split/basis/weighting
the trainer would use. Metrics cover measured corners only; pure-inference
``query_corners`` are skipped (no truth to compare).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np

from si_model.config import load_config
from si_model.training.loo import build_design, fit_field, make_split

PS = 1000.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    ds = dict(np.load(cfg["data"]["cache"]))
    field = "slack" if "slack" in ds else "slew"
    y = ds[field]
    measured = (np.asarray(ds["measured"], bool) if "measured" in ds
                else np.ones(ds["vt"].shape[0], bool))
    split = make_split(ds["corners"].tolist(), ds["vt"], cfg, measured=measured)
    phi, coords, _, _ = build_design(cfg, split)
    loo, picks = fit_field(y, phi, split, coords, cfg)
    if picks:
        print("[BASE-ADAPTIVE] picks: "
              + ", ".join(f"{k}:{v}" for k, v in sorted(picks.items(), key=str)))

    def err(ci: int) -> float:
        t, p = y[:, ci], loo[:, ci]
        if field == "slack":
            return float(np.nanmean(np.abs(p - t)) * PS)          # ps
        return float(np.nanmean(np.abs(p - t) / np.clip(np.abs(t), 1e-9, None)) * 100)

    unit = "ps" if field == "slack" else "%"
    print(f"\n=== base-only {field} error ({'MAE' if field == 'slack' else 'MAPE'}) ===")
    hid = [int(i) for i in split.hidden_idx if measured[i]]
    for ci in hid:
        print(f"  hidden {split.corners[ci]:16s} {err(ci):8.3f} {unit}")
    if hid:
        vals = np.array([err(ci) for ci in hid])
        print(f"  [hidden mean] {vals.mean():8.3f} {unit}   (worst {vals.max():.3f})")
    svals = np.array([err(int(ci)) for ci in split.seen_idx])
    print(f"  [seen-LOO mean] {svals.mean():8.3f} {unit}   (worst {svals.max():.3f})")
    skipped = [split.corners[int(i)] for i in split.hidden_idx if not measured[i]]
    if skipped:
        print(f"  (skipped, no truth: {skipped})")


if __name__ == "__main__":
    sys.exit(main())
