"""Prediction-only CLI: load a trained checkpoint and dump per-(path, corner)
slack predictions -- no training.

    python -m si_model.tasks.slack.predict --config configs/<ds>/<model>.yaml \
        [--ckpt runs/.../best.pt] [--corners hidden|seen|all] [--out-dir DIR]

Writes predictions_<corners>.csv / .npz next to the checkpoint (or --out-dir):
columns path_key, corner, truth_ps, base_ps, model_ps, base_err_ps,
model_err_ps. Corners without ground truth (pure-inference ``query_corners``)
get predictions with empty truth/err fields.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import torch

from si_model.config import load_config
from si_model.tasks.slack.train import Trainer


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
