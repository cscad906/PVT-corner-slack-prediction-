"""Prediction-only CLI for the slew model: load a trained checkpoint and dump
per-(path, corner) slew predictions -- no training.

    python -m si_model.tasks.slew.predict --config configs/<ds>/slew_*.yaml \
        [--ckpt runs/.../best.pt] [--corners hidden|seen|all] [--out-dir DIR]

Writes predictions_<corners>.csv / .npz: path_key, corner, truth_ns, base_ns,
model_ns, base_ape_pct, model_ape_pct (empty truth/ape for pure-inference
``query_corners``).
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import torch

from si_model.config import load_config
from si_model.tasks.slew.train_slew import Trainer


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--ckpt", default=None,
                    help="checkpoint path (default: <train.out_dir>/best.pt)")
    ap.add_argument("--corners", default="hidden",
                    choices=["hidden", "seen", "all"],
                    help="which corners to predict (seen = LOO-style)")
    ap.add_argument("--out-dir", default=None,
                    help="output dir (default: the checkpoint's dir)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    tr = Trainer(cfg)
    ckpt = args.ckpt or os.path.join(cfg["train"]["out_dir"], "best.pt")
    ck = torch.load(ckpt, map_location=tr.dev, weights_only=False)
    tr.model.load_state_dict(ck["model"])
    tr.enc.load_state_dict(ck["enc"])
    print(f"loaded {ckpt} (epoch {ck.get('epoch', '?')})")

    idx = {"hidden": tr.split.hidden_idx, "seen": tr.split.seen_idx,
           "all": np.arange(tr.C)}[args.corners]
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(ckpt))
    os.makedirs(out_dir, exist_ok=True)
    tr.export_predictions(out_dir, idx, tag=args.corners)


if __name__ == "__main__":
    sys.exit(main())
