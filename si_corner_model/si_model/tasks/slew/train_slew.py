"""Slew training CLI -- adaptive-bandwidth OLS base + neural residual (no SI).

    python -m si_model.tasks.slew.train_slew --config configs/beol14/slew_m40.yaml

Target = launch slew (ns). Base = per-corner weighted OLS (base.weighting); the
neural CornerSetHead learns the base residual (all-seen leave-one-out). CAP is
not trained: at report time it is fetched from the nearest same-axis1 seen corner
(cap is V-independent) and its MAPE is printed alongside slew. Metric = MAPE (%),
matching the P4 slewcap model.

This mirrors the slack trainer minus the SI branch and the cell/net stage head.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F

from si_model.config import gap_caps, load_config, token_scales
from si_model.model.path_encoder import PathEncoder
from si_model.tasks.slew.slew_model import SlewModel
from si_model.training.loo import build_design, fit_field, make_split

PS = 1000.0  # ns -> ps


class EMA:
    def __init__(self, model, decay=0.998):
        self.decay = decay
        self.shadow = {k: v.detach().clone() for k, v in model.state_dict().items()}
        self.backup = {}

    def update(self, model):
        for k, v in model.state_dict().items():
            if v.dtype.is_floating_point:
                self.shadow[k].mul_(self.decay).add_(v.detach(), alpha=1 - self.decay)
            else:
                self.shadow[k] = v.detach().clone()

    def apply(self, model):
        self.backup = {k: v.detach().clone() for k, v in model.state_dict().items()}
        model.load_state_dict(self.shadow)

    def restore(self, model):
        model.load_state_dict(self.backup)


def standardize(x, axis=None, eps=1e-8):
    mu = np.nanmean(x, axis=axis, keepdims=True)
    sd = np.nanstd(x, axis=axis, keepdims=True) + eps
    return ((x - mu) / sd).astype(np.float32)


class Trainer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dev = torch.device(cfg["train"].get("device", "cuda")
                                if torch.cuda.is_available() else "cpu")
        ds = dict(np.load(cfg["data"]["cache"]))
        self.ds = ds
        self.measured = (np.asarray(ds["measured"], bool) if "measured" in ds
                         else np.ones(ds["vt"].shape[0], bool))
        self.split = make_split(ds["corners"].tolist(), ds["vt"], cfg,
                                measured=self.measured)
        self.eval_hidden_idx = np.where(self.split.hidden & self.measured)[0]
        self.N, self.C = ds["slew"].shape
        self.A = ds["vt"].shape[1]
        self.ax_tscale = np.asarray(token_scales(cfg))
        self.ax_gapcap = gap_caps(cfg)
        self._prep_base()
        self._prep_tensors()
        self._prep_model()
        self._prep_splits()

    def _prep_base(self):
        sp = self.split
        self.phi, self.coords, _, _ = build_design(self.cfg, sp)
        base, picks = fit_field(self.ds["slew"], self.phi, sp, self.coords, self.cfg)
        self.base_hat = base                                    # [N,C] ns (LOO/all-seen)
        if picks:
            print("[BASE-ADAPTIVE] bandwidth picks: "
                  + ", ".join(f"{k}:{v}" for k, v in sorted(picks.items(), key=str)),
                  flush=True)

    def _prep_tensors(self):
        ds, sp, dev = self.ds, self.split, self.dev
        t = lambda x, dt=torch.float32: torch.as_tensor(np.asarray(x), dtype=dt, device=dev)
        vt = ds["vt"]; ref = vt[sp.ref_ci]
        self.dvdt = t((vt - ref) / self.ax_tscale[None, :])          # [C,A]

        resid = ds["slew"] - self.base_hat                      # [N,C] ns
        raw = np.stack([ds["slew"], resid], -1)                 # [N,C,2]
        self.tok_mu = raw[:, sp.seen_idx].mean((0, 1))
        self.tok_sd = raw[:, sp.seen_idx].std((0, 1)) + 1e-8
        tok = (raw - self.tok_mu) / self.tok_sd
        tok = np.concatenate([tok, np.broadcast_to(self.dvdt.cpu().numpy()[None],
                                                   (self.N, self.C, self.A))], -1)
        tok = np.nan_to_num(tok)   # query corners: NaN tokens (always masked)
        self.tokens = t(tok)                                    # [N,C,2+A]

        self.sig = t(standardize(ds["path_sig"], axis=0))
        self.node_fam = t(ds["node_fam"], torch.long)
        self.node_feat = t(standardize(ds["node_feat"].reshape(-1, ds["node_feat"].shape[-1]),
                                       axis=0).reshape(ds["node_feat"].shape))
        self.edge_feat = t(standardize(ds["edge_feat"].reshape(-1, ds["edge_feat"].shape[-1]),
                                       axis=0).reshape(ds["edge_feat"].shape))
        self.node_mask = t(ds["node_mask"])
        self.critical = t(ds["node_feat"][:, :, 5])

        self.resid_ps = t(resid * PS)                           # [N,C] target (ps)
        self.slew_ns = t(ds["slew"])                            # [N,C] ns (for MAPE)
        self.base_ns = t(self.base_hat)                         # [N,C] ns

    def _prep_model(self):
        cfg = self.cfg["model"]
        self.enc = PathEncoder(
            n_families=len(self.ds["fam_vocab"]), node_dim=self.ds["node_feat"].shape[-1],
            edge_dim=self.ds["edge_feat"].shape[-1], d=cfg.get("enc_dim", 128),
            num_blocks=cfg.get("enc_blocks", 3), dropout=cfg["dropout"]).to(self.dev)
        n_sig = self.sig.shape[1] + self.enc.out_dim
        self.model = SlewModel(n_token_feat=self.tokens.shape[-1], n_sig=n_sig,
                               d=cfg["d_model"], heads=cfg["n_heads"],
                               dropout=cfg["dropout"], n_query=3 * self.A).to(self.dev)

    def _prep_splits(self):
        rng = np.random.RandomState(self.cfg["train"].get("split_seed", 42))
        perm = rng.permutation(self.N)
        n_va = n_te = self.N // 10
        self.va_paths = np.sort(perm[:n_va])
        self.te_paths = np.sort(perm[n_va:n_va + n_te])
        self.tr_paths = np.sort(perm[n_va + n_te:])

    def make_batch(self, paths, ci, train, drop_axes=()):
        dev = self.dev
        P = torch.as_tensor(paths, dtype=torch.long, device=dev)
        seen = torch.as_tensor(self.split.seen, device=dev)
        cmask = seen.clone(); cmask[ci] = False
        tmask = cmask[None, :].expand(len(paths), -1).clone()
        for axis in drop_axes:
            kill = torch.as_tensor((self.ds["vt"][:, axis] == self.ds["vt"][ci, axis]) & self.split.seen, device=dev)
            kill[self.split.ref_ci] = False
            tmask = tmask & ~kill[None, :]
        tokens = self.tokens[P]
        B = len(paths)
        if train:
            C = tmask.shape[1]
            drop = torch.rand(B, device=dev) < 0.08
            cand = torch.randint(0, C, (B,), device=dev); rows = torch.arange(B, device=dev)
            ok = (cand != self.split.ref_ci) & tmask[rows, cand]
            tmask[rows[drop & ok], cand[drop & ok]] = False
            vt = self.ds["vt"]
            for axis in range(self.A):
                if torch.rand(1).item() < 0.30:
                    kill = torch.as_tensor((vt[:, axis] == vt[ci, axis]) & self.split.seen, device=dev)
                    kill[self.split.ref_ci] = False
                    tmask = tmask & ~kill[None, :]
            tmask[:, self.split.ref_ci] = True
            scale = torch.as_tensor(0.02 / self.tok_sd, dtype=torch.float32, device=dev)
            tokens = tokens.clone()
            tokens[..., :2] += torch.randn_like(tokens[..., :2]) * scale
        vt_t = torch.as_tensor(self.ds["vt"], dtype=torch.float32, device=dev)
        ref = self.ds["vt"][self.split.ref_ci]
        q = self.dvdt[ci]
        if train:
            q = q + torch.randn(self.A, device=dev) * 0.08
        tok_dvdt = torch.stack([
            (vt_t[:, a] - float(ref[a])) / self.ax_tscale[a] for a in range(self.A)
        ], 1)
        gaps = []
        for ax in range(self.A):
            cap = self.ax_gapcap[ax]
            d = (tok_dvdt[None, :, ax] - q[ax]).expand(B, -1)
            below = torch.where(tmask & (d < -1e-6), -d, torch.full_like(d, cap)).amin(1)
            above = torch.where(tmask & (d > 1e-6), d, torch.full_like(d, cap)).amin(1)
            gaps += [below.clamp(max=cap), above.clamp(max=cap)]
        query = torch.cat([q[None].expand(B, -1), torch.stack(gaps, -1)], -1)
        return {"tokens": tokens, "token_mask": tmask, "query_vt": query,
                "fam": self.node_fam[P], "node": self.node_feat[P], "edge": self.edge_feat[P],
                "nmask": self.node_mask[P], "crit": self.critical[P], "sig_feats": self.sig[P],
                "target": self.resid_ps[P, ci], "paths": P, "ci": ci}

    def forward(self, b):
        path_emb = self.enc(b["fam"], b["node"], b["edge"], b["nmask"], b["crit"])
        sig = torch.cat([b["sig_feats"], path_emb], -1)
        return self.model({"tokens": b["tokens"], "token_mask": b["token_mask"],
                           "query_vt": b["query_vt"], "sig": sig})

    def loss(self, out, b):
        l = F.mse_loss(out["resid"], b["target"])
        l_raw = F.mse_loss(out["resid_raw"], b["target"])
        l_gate = (1.0 - out["gate"]).pow(2).mean()
        return l + 0.3 * l_raw + 0.02 * l_gate, {"resid": l.item()}

    def run(self):
        tcfg = self.cfg["train"]; out_dir = tcfg["out_dir"]; os.makedirs(out_dir, exist_ok=True)
        params = list(self.model.parameters()) + list(self.enc.parameters())
        opt = torch.optim.AdamW(params, lr=tcfg["lr"], weight_decay=tcfg["weight_decay"])
        epochs = tcfg["epochs"]; warm = max(3, epochs // 15)
        sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda e: (e + 1) / warm if e < warm
            else max(0.5 * (1 + math.cos(math.pi * (e - warm) / max(epochs - warm, 1))), 0.02))
        ema_m, ema_e = EMA(self.model), EMA(self.enc)
        torch.manual_seed(tcfg["seed"]); rng = np.random.RandomState(tcfg["seed"])
        bs = tcfg["batch_paths"]; best = (float("inf"), -1)
        for ep in range(epochs):
            self.model.train(); self.enc.train(); losses = []
            for ci in rng.permutation(self.split.seen_idx):
                pp = rng.permutation(self.tr_paths)
                for i in range(0, len(pp), bs):
                    b = self.make_batch(pp[i:i + bs], int(ci), True)
                    out = self.forward(b); loss, parts = self.loss(out, b)
                    opt.zero_grad(); loss.backward()
                    torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step()
                    ema_m.update(self.model); ema_e.update(self.enc); losses.append(parts)
            sched.step()
            if (ep + 1) % 2 == 0 or ep == epochs - 1:
                ema_m.apply(self.model); ema_e.apply(self.enc)
                val = self.evaluate(self.va_paths, self.split.seen_idx)
                mon = val["mape"].mean() + 0.3 * val["mape"].max()
                hid = self.evaluate(self.va_paths, self.eval_hidden_idx)
                tag = ""
                if mon < best[0]:
                    best = (mon, ep)
                    torch.save({"model": self.model.state_dict(), "enc": self.enc.state_dict(),
                                "cfg": self.cfg, "epoch": ep}, f"{out_dir}/best.pt"); tag = " *"
                ema_m.restore(self.model); ema_e.restore(self.enc)
                print(f"E{ep+1:3d} loss={np.mean([l['resid'] for l in losses]):7.2f} "
                      f"| valSeen slewMAPE={val['mape'].mean():5.2f}% "
                      f"| valHidden slewMAPE={hid['mape'].mean():5.2f}%{tag}",
                      flush=True)
        ck = torch.load(f"{out_dir}/best.pt", map_location=self.dev, weights_only=False)
        self.model.load_state_dict(ck["model"]); self.enc.load_state_dict(ck["enc"])
        return self.report(out_dir, ck["epoch"])

    @torch.no_grad()
    def evaluate(self, paths, corner_idx, bs=512, drop_axes=()):
        self.model.eval(); self.enc.eval()
        mape = []
        for ci in corner_idx:
            e = []
            for i in range(0, len(paths), bs):
                b = self.make_batch(paths[i:i + bs], int(ci), False, drop_axes)
                out = self.forward(b)
                truth = self.slew_ns[b["paths"], ci]
                pred = self.base_ns[b["paths"], ci] + out["resid"] / PS
                denom = truth.abs().clamp(min=1e-6)
                e.append(((pred - truth).abs() / denom))
            mape.append(torch.cat(e).mean().item() * 100)
        return {"mape": np.array(mape)}

    def cap_fetch_mape(self, paths, corner_idx):
        """Cap predicted by the nearest same-axis1 seen corner (V-independent)."""
        vt = self.ds["vt"]; cap = self.ds["cap"]
        rows = []
        for ci in corner_idx:
            v, a1 = vt[ci]
            cands = [j for j in self.split.seen_idx if abs(vt[j, 1] - a1) < 1e-9]
            j = min(cands, key=lambda j: abs(vt[j, 0] - v))
            pred = cap[paths, j]; truth = cap[paths, ci]
            rows.append(np.mean(np.abs(pred - truth) / np.clip(np.abs(truth), 1e-9, None)) * 100)
        return float(np.mean(rows))

    @torch.no_grad()
    def export_predictions(self, out_dir, corner_idx=None, bs=512, tag="hidden"):
        """Dump per-(path, corner) MODEL slew predictions (ns) + truth comparison
        when a measurement exists. The OLS base is never reported -- use
        ``python -m si_model.training.base_check`` for base-only inspection."""
        self.model.eval(); self.enc.eval()
        idx = self.split.hidden_idx if corner_idx is None else np.asarray(corner_idx)
        paths = np.arange(self.N)
        pred = np.empty((self.N, len(idx)))
        for k, ci in enumerate(idx):
            outs = []
            for i in range(0, self.N, bs):
                b = self.make_batch(paths[i:i + bs], int(ci), False)
                out = self.forward(b)
                outs.append((self.base_ns[b["paths"], ci] + out["resid"] / PS)
                            .cpu().numpy())
            pred[:, k] = np.concatenate(outs)
        truth = self.slew_ns.cpu().numpy()[:, idx]
        keys = [str(x) for x in self.ds["path_keys"]]
        corners = [self.split.corners[int(i)] for i in idx]
        np.savez_compressed(
            f"{out_dir}/predictions_{tag}.npz",
            path_keys=np.asarray(keys), corners=np.asarray(corners),
            truth_ns=truth, model_ns=pred)
        denom = np.clip(np.abs(truth), 1e-9, None)
        with open(f"{out_dir}/predictions_{tag}.csv", "w") as f:
            f.write("path_key,corner,truth_ns,model_ns,model_ape_pct\n")
            for k, cn in enumerate(corners):
                for p in range(self.N):
                    t, md = truth[p, k], pred[p, k]
                    if np.isfinite(t):        # truth available -> comparison too
                        f.write(f"{keys[p]},{cn},{t:.6f},{md:.6f},"
                                f"{abs(md - t) / denom[p, k] * 100:.3f}\n")
                    else:                     # pure inference -> prediction only
                        f.write(f"{keys[p]},{cn},,{md:.6f},\n")
        print(f"[PRED] wrote {out_dir}/predictions_{tag}.csv (+.npz): "
              f"{self.N} paths x {len(idx)} corners", flush=True)
        return pred

    def report(self, out_dir, best_ep):
        rows = {n: self.evaluate(p, self.eval_hidden_idx)
                for n, p in (("train", self.tr_paths), ("val", self.va_paths),
                             ("test", self.te_paths), ("all", np.arange(self.N)))}
        r = rows["all"]
        print(f"\n=== hidden-corner SLEW MAPE (best epoch {best_ep+1}) ===")
        for i, cn in enumerate([self.split.corners[j] for j in self.eval_hidden_idx]):
            print(f"  {cn:16s} model={r['mape'][i]:6.2f}%")
        cap_mape = self.cap_fetch_mape(np.arange(self.N), self.eval_hidden_idx)
        summary = {n: {"hidden_slew_mape": float(rr["mape"].mean())}
                   for n, rr in rows.items()}
        summary["hidden_cap_fetch_mape"] = cap_mape
        summary["best_epoch"] = best_ep + 1
        for n in ("train", "val", "test", "all"):
            print(f"  [{n:5s}] SLEW model {summary[n]['hidden_slew_mape']:.2f}%")
        print(f"  CAP (same-axis1 neighbour fetch) hidden MAPE = {cap_mape:.3f}%")
        with open(f"{out_dir}/summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        # per-(path, corner) prediction dump (all hidden incl. query corners)
        self.export_predictions(out_dir)
        return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--enc-blocks", type=int, default=None)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.out_dir:
        cfg["train"]["out_dir"] = args.out_dir
    if args.enc_blocks is not None:
        cfg["model"]["enc_blocks"] = args.enc_blocks
    Trainer(cfg).run()


if __name__ == "__main__":
    sys.exit(main())
