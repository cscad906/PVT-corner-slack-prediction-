"""Slack training CLI (setup / hold).

    bash scripts/run.sh train [--design <circuit>] [--temp <temp>]

Scheme: all-seen leave-one-out. A training sample is (path, seen corner c); the
model sees the other seen corners as tokens (LOO fold) and predicts the residual
of the precomputed OLS base at c. Hidden corners are never touched during
training or model selection.

Recipe carried over from the inherited boomcore_si_slack package: corner-token
dropout + whole-axis dropout + input noise augmentation (ref token never
dropped), EMA of weights, AdamW + warmup/cosine, grad clip, early stopping on
mean + 0.3*worst per-corner val MAE. Path-level train/val/test split (80/10/10)
guards the neural parts against memorizing paths; the OLS base is per-path and
unaffected.

There is no per-stage cell/net delay head (dropped in the unified engine): the
model is OLS base + gated (attention correction + SI-deviation branch).
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import torch

from si_model.compat import load_checkpoint
from si_model.config import gap_caps, load_config, token_scales
from si_model.features.si_features import build_si_features
from si_model.model.path_encoder import PathEncoder
from si_model.tasks.slack.full_model import SlackModel
from si_model.training.loo import compute_base, make_split
from si_model.training.losses import total_loss

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


def standardize(x: np.ndarray, axis=None, eps=1e-8):
    mu = np.nanmean(x, axis=axis, keepdims=True)
    sd = np.nanstd(x, axis=axis, keepdims=True) + eps
    return ((x - mu) / sd).astype(np.float32)


class Trainer:
    def __init__(self, cfg: dict, lambda_si: "float | None" = None):
        self.cfg = cfg
        if lambda_si is not None:
            cfg["train"]["lambda_si"] = lambda_si
        self.dev = torch.device(cfg["train"].get("device", "cuda")
                                if torch.cuda.is_available() else "cpu")
        ds = np.load(cfg["data"]["cache"])
        self.ds = ds
        # measured=False marks pure-inference query corners (no data behind
        # them): forced hidden, excluded from every metric, prediction-only.
        self.measured = (np.asarray(ds["measured"], bool) if "measured" in ds
                         else np.ones(ds["vt"].shape[0], bool))
        self.split = make_split(ds["corners"].tolist(), ds["vt"], cfg,
                                measured=self.measured)
        # metric corners = hidden AND measured (truth exists)
        self.eval_hidden_idx = np.where(self.split.hidden & self.measured)[0]
        self.A = ds["vt"].shape[1]                      # number of continuous axes
        self.ax_tscale = np.asarray(token_scales(cfg))  # token/query coord units
        self.ax_gapcap = gap_caps(cfg)                  # extrapolation-gap clamps
        self.base = compute_base(ds, self.split, cfg)
        sf_fp = cfg["data"]["cache"].replace("dataset", "si_features")
        if os.path.exists(sf_fp):
            sf = dict(np.load(sf_fp))
        else:
            sf = build_si_features(ds, self.base.phi, self.split.seen)
            np.savez_compressed(sf_fp, **sf)
        self.N, self.C = ds["slack"].shape
        self._prep_tensors(sf)
        # Seed BEFORE building the model: weight init draws from the torch RNG,
        # so seeding only inside run() left every run with different initial
        # weights -- two identical-input runs then reported different losses,
        # which makes any A/B comparison (leakage checks, ablations, ensembles
        # sharing a path split) meaningless.
        torch.manual_seed(int(cfg["train"].get("seed", 42)))
        self._prep_model()
        self._prep_splits()

    # ---------------------------------------------------------------- data
    def _prep_tensors(self, sf):
        ds, sp, dev = self.ds, self.split, self.dev
        t = lambda x, dt=torch.float32: torch.as_tensor(np.asarray(x), dtype=dt, device=dev)

        vt = ds["vt"]
        ref = vt[sp.ref_ci]
        # normalized query coords, per-axis token_scale (e.g. dv/0.1 for V,
        # d(axis1)/1.0 for RC). Config-driven so a temperature axis can use /100.
        self.dvdt = t((vt - ref) / self.ax_tscale[None, :])          # [C,A]

        # corner tokens: measured per-corner scalars (incl. launch/capture
        # clock latencies + library setup/hold check time) + the base-LOO
        # residual (lets attention interpolate the residual field it must
        # predict; leakage-safe: residuals are LOO and the target corner's token
        # is masked) + corner coords
        raw = np.stack([ds["slack"], ds["si_label"], ds["arrival"],
                        ds["required"], ds["launch_clk"], ds["capture_clk"],
                        ds["lib_check_time"], self.base.resid], -1)       # [N,C,8]
        # nan-safe: a deliverable may not report some field at all (e.g. no
        # 'library setup time' row). That channel stays NaN and is zeroed below;
        # using plain mean/std would make ITS statistics NaN and silently zero
        # the channel for every path instead of just the missing entries.
        self.tok_mu = np.nanmean(raw[:, sp.seen_idx], axis=(0, 1))
        self.tok_sd = np.nanstd(raw[:, sp.seen_idx], axis=(0, 1)) + 1e-8
        self.tok_mu = np.nan_to_num(self.tok_mu)
        self.tok_sd = np.where(np.isfinite(self.tok_sd), self.tok_sd, 1.0)
        tok = (raw - self.tok_mu) / self.tok_sd
        tok = np.concatenate([tok, np.broadcast_to(
            self.dvdt.cpu().numpy()[None], (self.N, self.C, self.A))], -1)
        # query corners have NaN measurements; their tokens are always masked,
        # but NaN would still poison attention (0 * NaN = NaN) -- zero them.
        tok = np.nan_to_num(tok)
        self.tokens = t(tok)                                          # [N,C,8+A]

        self.sig = t(standardize(ds["path_sig"], axis=0))
        # stage sequences (the path-encoder chain -- NOT a cell/net head)
        self.node_fam = t(ds["node_fam"], torch.long)
        self.node_feat = t(standardize(ds["node_feat"].reshape(-1, ds["node_feat"].shape[-1]),
                                       axis=0).reshape(ds["node_feat"].shape))
        self.edge_feat = t(standardize(ds["edge_feat"].reshape(-1, ds["edge_feat"].shape[-1]),
                                       axis=0).reshape(ds["edge_feat"].shape))
        self.node_mask = t(ds["node_mask"])
        self.critical = t(ds["node_feat"][:, :, 5])                   # raw 0/1

        # labels/targets (ps)
        self.resid = t(self.base.resid * PS)                          # [N,C]
        self.si_label = t(ds["si_label"] * PS)
        self.si_smooth = t(self.base.si_smooth_hat * PS)
        self.base_hat = t(self.base.base_hat * PS)
        self.slack_ps = t(ds["slack"] * PS)

        # SI stage tensors grouped per path (launch_clock+data only, seg<2)
        keep = ds["stage_seg"] < 2
        s_idx = np.where(keep)[0]
        s_path = ds["stage_path"][s_idx]
        order = np.argsort(s_path, kind="stable")
        s_idx, s_path = s_idx[order], s_path[order]
        counts = np.bincount(s_path, minlength=self.N)
        self.Smax = int(counts.max())
        pad = np.zeros((self.N, self.Smax), np.int64)
        smask = np.zeros((self.N, self.Smax), bool)
        pos = np.zeros(self.N, np.int64)
        for si, p in zip(s_idx, s_path):
            pad[p, pos[p]] = si
            smask[p, pos[p]] = True
            pos[p] += 1
        self.stage_pad = t(pad, torch.long)                           # [N,Smax]
        self.stage_mask = t(smask, torch.bool)

        vw_width = sf["vwin_hat"][:, :, 1] - sf["vwin_hat"][:, :, 0]  # [S,C]
        feats = np.stack([
            np.broadcast_to(np.nan_to_num(ds["acc"])[:, :, None], sf["overlap"].shape),
            sf["bump_hat"], sf["overlap"], sf["aslew_hat"],
            np.broadcast_to(vw_width[:, None, :], sf["overlap"].shape),
        ], -1).astype(np.float32)                                     # [S,A_agg,C,5]
        feats = np.nan_to_num(feats)
        pres = sf["present"]
        m = feats[:, :, self.split.seen_idx][pres].reshape(-1, 5)
        # an SI-free dataset (no crosstalk drop) has zero stages -> nothing to
        # standardize against; leave the (empty) features untouched.
        self.has_si = m.size > 0
        if not self.has_si:
            print("[SI] dataset has no crosstalk stages -- SI branch disabled "
                  "(lambda_si forced to 0); model = OLS base + attention.", flush=True)
        mu, sd = ((m.mean(0), m.std(0) + 1e-8) if self.has_si
                  else (np.zeros(5, np.float32), np.ones(5, np.float32)))
        self.si_x = t((feats - mu) / sd)                              # [S,A_agg,C,5]
        self.si_awin = t(sf["awin_hat"])                              # [S,A_agg,C,2]
        self.si_vwin = t(sf["vwin_hat"])                              # [S,C,2]
        self.si_bump = t(np.nan_to_num(sf["bump_hat"]))               # [S,A_agg,C]
        self.si_present = t(np.broadcast_to(pres[:, :, None], sf["overlap"].shape).copy(),
                            torch.bool)

    def _prep_model(self):
        cfg = self.cfg["model"]
        self.enc = PathEncoder(
            n_families=len(self.ds["fam_vocab"]),
            node_dim=self.ds["node_feat"].shape[-1],
            edge_dim=self.ds["edge_feat"].shape[-1],
            d=cfg.get("enc_dim", 128), num_blocks=cfg.get("enc_blocks", 3),
            dropout=cfg["dropout"]).to(self.dev)
        n_sig = self.sig.shape[1] + self.enc.out_dim
        self.model = SlackModel(
            n_token_feat=self.tokens.shape[-1],
            n_sig=n_sig, d=cfg["d_model"], heads=cfg["n_heads"],
            dropout=cfg["dropout"], n_query=3 * self.A,
            si_n_time=cfg.get("si_n_time", 16),
            si_w_ns=cfg.get("si_w_ns0", 0.05),
            si_tau_ps=cfg.get("si_tau_ps0", 8.0),
            si_elec_thresh=cfg.get("si_elec_thresh", 0.01),
            si_w_elec=cfg.get("si_w_elec0", 0.004)).to(self.dev)

    def _prep_splits(self):
        # path split is ALWAYS derived from split_seed (fixed), never from the
        # training seed -- ensemble members must share identical splits
        rng = np.random.RandomState(self.cfg["train"].get("split_seed", 42))
        perm = rng.permutation(self.N)
        n_va, n_te = self.N // 10, self.N // 10
        self.va_paths = np.sort(perm[:n_va])
        self.te_paths = np.sort(perm[n_va:n_va + n_te])
        self.tr_paths = np.sort(perm[n_va + n_te:])

    # ------------------------------------------------------------- batches
    def make_batch(self, paths: np.ndarray, ci: int, train: bool,
                   drop_axes: tuple = ()):
        """drop_axes: also mask every seen corner sharing the target's level on
        that axis -- used by the validation monitor to measure at hidden
        difficulty (a whole grid row unmeasured)."""
        dev = self.dev
        P = torch.as_tensor(paths, dtype=torch.long, device=dev)
        seen = torch.as_tensor(self.split.seen, device=dev)
        token_mask = seen.clone()
        token_mask[ci] = False                       # anti-leakage (no-op if hidden)
        tmask = token_mask[None, :].expand(len(paths), -1).clone()
        for axis in drop_axes:
            kill = torch.as_tensor(
                (self.ds["vt"][:, axis] == self.ds["vt"][ci, axis]) & self.split.seen,
                device=dev)
            kill[self.split.ref_ci] = False
            tmask = tmask & ~kill[None, :]
        tokens = self.tokens[P]

        if train:
            B, C = tmask.shape
            # single-corner dropout (never the ref corner)
            drop = torch.rand(B, device=dev) < 0.08
            cand = torch.randint(0, C, (B,), device=dev)
            rows = torch.arange(B, device=dev)
            ok = (cand != self.split.ref_ci) & tmask[rows, cand]
            tmask[rows[drop & ok], cand[drop & ok]] = False
            # axis dropout biased to the TARGET's own level: rehearses the hidden
            # scenario (an entire grid row unmeasured) instead of a random row.
            vt = self.ds["vt"]
            for axis in range(self.A):
                if torch.rand(1).item() < 0.30:
                    kill = torch.as_tensor(
                        (vt[:, axis] == vt[ci, axis]) & self.split.seen, device=dev)
                    kill[self.split.ref_ci] = False
                    tmask = tmask & ~kill[None, :]
            # occasional random-row dropout for generality
            if torch.rand(1).item() < 0.10:
                axis = int(torch.randint(0, self.A, (1,)).item())
                vals = sorted(set(vt[self.split.seen_idx, axis]))
                sel = vals[int(torch.randint(0, len(vals), (1,)).item())]
                kill = torch.as_tensor(
                    (vt[:, axis] == sel) & self.split.seen, device=dev)
                kill[self.split.ref_ci] = False
                tmask = tmask & ~kill[None, :]
            tmask[:, self.split.ref_ci] = True
            # measured-scalar noise: 6 ps in raw units, per-channel normalized
            n_meas = len(self.tok_sd)
            scale = torch.as_tensor(0.006 / self.tok_sd, dtype=torch.float32, device=dev)
            tokens = tokens.clone()
            tokens[..., :n_meas] += torch.randn_like(tokens[..., :n_meas]) * scale

        # one-sided neighbor gaps per axis, computed AFTER masking/augmentation
        # (axis dropout thus teaches the gate what one-sided extrapolation looks
        # like). Distinguishes edge queries (no seen corner beyond -> gap = cap)
        # from interior ones -- a plain min-distance confidence cannot separate
        # them on this grid.
        B = len(paths)
        vt_t = torch.as_tensor(self.ds["vt"], dtype=torch.float32, device=dev)
        ref = self.ds["vt"][self.split.ref_ci]
        q = self.dvdt[ci]                                 # normalized coords [A]
        if train:
            # query-coordinate jitter (the inherited model's pvt noise): training
            # queries only ever sit on the discrete seen grid, so without jitter
            # the MLPs can key on exact coordinates and behave arbitrarily at
            # hidden ones (observed: gate collapsed to 0 there).
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
        query = torch.cat([q[None].expand(B, -1), torch.stack(gaps, -1)], -1)  # [B,3A]

        sp = self.stage_pad[P]                        # [B,Smax]
        return {
            "tokens": tokens, "token_mask": tmask,
            "query_vt": query,
            "fam": self.node_fam[P], "node": self.node_feat[P],
            "edge": self.edge_feat[P], "nmask": self.node_mask[P],
            "crit": self.critical[P],
            "sig_feats": self.sig[P],
            "si_x_raw": self.si_x[sp][:, :, :, ci, :],       # [B,Smax,A_agg,5]
            "si_awin": self.si_awin[sp][:, :, :, ci, :],      # [B,Smax,A_agg,2] (ns)
            "si_vwin": self.si_vwin[sp][:, :, ci, :],         # [B,Smax,2]   (ns)
            "si_bump": self.si_bump[sp][..., ci],             # [B,Smax,A_agg] ratio
            "si_present": self.si_present[sp][..., ci] & self.stage_mask[P][:, :, None],
            "si_stage_mask": self.stage_mask[P],
            "resid_target": self.resid[P, ci],
            # SI aux target = the residual of the per-path SI smooth fit.
            "si_target": self.si_label[P, ci] - self.si_smooth[P, ci],
            "paths": P, "ci": ci,
        }

    def forward(self, b: dict) -> dict:
        path_emb = self.enc(b["fam"], b["node"], b["edge"], b["nmask"], b["crit"])
        sig = torch.cat([b["sig_feats"], path_emb], -1)
        B, S, Aa, Fdim = b["si_x_raw"].shape
        q = b["query_vt"][:, None, None, :self.A].expand(B, S, Aa, self.A)
        si_x = torch.cat([b["si_x_raw"], q], -1)
        return self.model({
            "tokens": b["tokens"], "token_mask": b["token_mask"],
            "query_vt": b["query_vt"], "sig": sig,
            "si_x": si_x, "si_awin": b["si_awin"], "si_vwin": b["si_vwin"],
            "si_bump": b["si_bump"],
            "si_present": b["si_present"], "si_stage_mask": b["si_stage_mask"],
        })

    # --------------------------------------------------------------- train
    def run(self):
        tcfg = self.cfg["train"]
        out_dir = tcfg["out_dir"]
        os.makedirs(out_dir, exist_ok=True)
        params = list(self.model.parameters()) + list(self.enc.parameters())
        opt = torch.optim.AdamW(params, lr=tcfg["lr"], weight_decay=tcfg["weight_decay"])
        epochs = tcfg["epochs"]
        warm = max(3, epochs // 15)
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda e: (e + 1) / warm if e < warm
            else max(0.5 * (1 + math.cos(math.pi * (e - warm) / max(epochs - warm, 1))), 0.02))
        ema_m, ema_e = EMA(self.model), EMA(self.enc)
        torch.manual_seed(tcfg["seed"])
        rng = np.random.RandomState(tcfg["seed"])
        bs = tcfg["batch_paths"]
        lam = tcfg["lambda_si"] if self.has_si else 0.0
        best = (float("inf"), -1)

        # SI worst-instant sweep annealing: soft->hard over training.
        w0 = tcfg.get("si_w_ns0", 0.05); w1 = tcfg.get("si_w_ns1", 0.005)
        tau0 = tcfg.get("si_tau_ps0", 8.0); tau1 = tcfg.get("si_tau_ps1", 0.5)
        we0 = tcfg.get("si_w_elec0", 0.004); we1 = tcfg.get("si_w_elec1", 0.001)

        for ep in range(epochs):
            frac = ep / max(epochs - 1, 1)
            self.model.si.set_anneal(w0 * (1 - frac) + w1 * frac,
                                     tau0 * (1 - frac) + tau1 * frac, hard=False,
                                     w_elec=we0 * (1 - frac) + we1 * frac)
            self.model.train(); self.enc.train()
            losses = []
            corner_order = rng.permutation(self.split.seen_idx)
            for ci in corner_order:
                pperm = rng.permutation(self.tr_paths)
                for i in range(0, len(pperm), bs):
                    b = self.make_batch(pperm[i:i + bs], int(ci), train=True)
                    out = self.forward(b)
                    loss, parts = total_loss(out, b, lam)
                    opt.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(params, 1.0)
                    opt.step()
                    ema_m.update(self.model); ema_e.update(self.enc)
                    losses.append(parts)
            sched.step()

            if (ep + 1) % 2 == 0 or ep == epochs - 1:
                ema_m.apply(self.model); ema_e.apply(self.enc)
                # monitor at HIDDEN difficulty: seen-corner LOO with the target's
                # V row (resp. axis-1 row) additionally masked -- plain seen-LOO
                # kept improving long after hidden quality peaked.
                vs = [self.evaluate(self.va_paths, self.split.seen_idx, drop_axes=(a,))
                      for a in range(self.A)]
                val = {"mae": np.mean([v["mae"] for v in vs], axis=0)}
                mon = val["mae"].mean() + 0.3 * val["mae"].max()
                hid = self.evaluate(self.va_paths, self.eval_hidden_idx)
                tag = ""
                if mon < best[0]:
                    best = (mon, ep)
                    torch.save({"model": self.model.state_dict(),
                                "enc": self.enc.state_dict(),
                                "cfg": self.cfg, "epoch": ep}, f"{out_dir}/best.pt")
                    tag = " *"
                ema_m.restore(self.model); ema_e.restore(self.enc)
                lr_ = sched.get_last_lr()[0]
                print(f"E{ep+1:3d} loss={np.mean([l['resid'] for l in losses]):8.2f} "
                      f"si={np.mean([l['si'] for l in losses]):8.2f} "
                      f"| val-seen {val['mae'].mean():6.2f}ps "
                      f"| val-hidden {hid['mae'].mean():6.2f}ps"
                      f" lr={lr_:.1e}{tag}", flush=True)

        ck = load_checkpoint(f"{out_dir}/best.pt", map_location=self.dev)
        self.model.load_state_dict(ck["model"]); self.enc.load_state_dict(ck["enc"])
        return self.report(out_dir, ck["epoch"])

    @torch.no_grad()
    def evaluate(self, paths: np.ndarray, corner_idx: np.ndarray, bs: int = 512,
                 drop_axes: tuple = ()):
        self.model.eval(); self.enc.eval()
        prev_hard = self.model.si.hard
        self.model.si.hard = True   # inference = exact PT worst-instant (hard max)
        mae, si_mae = [], []
        for ci in corner_idx:
            errs, serrs = [], []
            for i in range(0, len(paths), bs):
                b = self.make_batch(paths[i:i + bs], int(ci), train=False,
                                    drop_axes=drop_axes)
                out = self.forward(b)
                pred = self.base_hat[b["paths"], ci] + out["resid"]
                truth = self.slack_ps[b["paths"], ci]
                errs.append((pred - truth).abs())
                serrs.append((out["si_pred"] - b["si_target"]).abs())
            mae.append(torch.cat(errs).mean().item())
            si_mae.append(torch.cat(serrs).mean().item())
        self.model.si.hard = prev_hard
        return {"mae": np.array(mae), "si_mae": np.array(si_mae)}

    @torch.no_grad()
    def export_predictions(self, out_dir: str, corner_idx=None, bs: int = 512,
                           tag: str = "hidden") -> np.ndarray:
        """Dump per-(path, corner) MODEL predictions in ps (+ truth comparison
        when a measurement exists; pure-inference corners get predictions only).

        Writes ``predictions_<tag>.csv`` and ``.npz`` (path_keys, corners,
        truth_ps, model_ps). The OLS base is never reported anywhere -- to
        inspect base-only quality use the standalone
        ``bash scripts/run.sh base``. Default corners = hidden;
        at SEEN corners the target's own token is masked (LOO-style).
        """
        self.model.eval(); self.enc.eval()
        prev_hard = self.model.si.hard
        self.model.si.hard = True   # exact PT worst-instant at inference
        idx = self.split.hidden_idx if corner_idx is None else np.asarray(corner_idx)
        paths = np.arange(self.N)
        pred = np.empty((self.N, len(idx)))
        for k, ci in enumerate(idx):
            outs = []
            for i in range(0, self.N, bs):
                b = self.make_batch(paths[i:i + bs], int(ci), train=False)
                out = self.forward(b)
                outs.append((self.base_hat[b["paths"], ci] + out["resid"])
                            .cpu().numpy())
            pred[:, k] = np.concatenate(outs)
        self.model.si.hard = prev_hard

        truth = self.slack_ps.cpu().numpy()[:, idx]
        keys = [str(x) for x in self.ds["path_keys"]]
        corners = [self.split.corners[int(i)] for i in idx]
        np.savez_compressed(
            f"{out_dir}/predictions_{tag}.npz",
            path_keys=np.asarray(keys), corners=np.asarray(corners),
            truth_ps=truth, model_ps=pred)
        with open(f"{out_dir}/predictions_{tag}.csv", "w") as f:
            f.write("path_key,corner,truth_ps,model_ps,model_err_ps\n")
            for k, cn in enumerate(corners):
                for p in range(self.N):
                    t, md = truth[p, k], pred[p, k]
                    if np.isfinite(t):        # truth available -> comparison too
                        f.write(f"{keys[p]},{cn},{t:.3f},{md:.3f},{md - t:.3f}\n")
                    else:                     # pure inference -> prediction only
                        f.write(f"{keys[p]},{cn},,{md:.3f},\n")
        print(f"[PRED] wrote {out_dir}/predictions_{tag}.csv (+.npz): "
              f"{self.N} paths x {len(idx)} corners", flush=True)
        return pred

    def report(self, out_dir: str, best_ep: int) -> dict:
        rows = {}
        for name, paths in (("train", self.tr_paths), ("val", self.va_paths),
                            ("test", self.te_paths), ("all", np.arange(self.N))):
            rows[name] = self.evaluate(paths, self.eval_hidden_idx)
        print(f"\n=== hidden-corner results (best epoch {best_ep + 1}) ===")
        hnames = [self.split.corners[i] for i in self.eval_hidden_idx]
        r = rows["all"]
        for i, cn in enumerate(hnames):
            print(f"  {cn:16s} model={r['mae'][i]:7.2f}ps  si={r['si_mae'][i]:6.2f}ps")
        summary = {
            name: {"hidden_mae_ps": float(r["mae"].mean()),
                   "hidden_worst_ps": float(r["mae"].max())}
            for name, r in rows.items()}
        summary["lambda_si"] = (self.cfg["train"]["lambda_si"] if self.has_si else 0.0)
        summary["si_branch"] = bool(self.has_si)
        summary["enc_blocks"] = self.cfg["model"].get("enc_blocks", 3)
        summary["best_epoch"] = best_ep + 1
        # 히든 코너 성적은 전체 경로 기준 하나만 찍는다. train/val/test 는 경로를
        # 쪼갠 것일 뿐 히든 코너는 어차피 다 같아서, 네 줄을 늘어놓으면 "test 가
        # 진짜 성적" 처럼 읽히기 쉽다. 네 값 모두 summary.json 에는 그대로 남는다.
        s = summary["all"]
        print(f"  [all paths] model {s['hidden_mae_ps']:.2f} ps "
              f"(worst {s['hidden_worst_ps']:.2f})")
        with open(f"{out_dir}/summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        # per-(path, corner) prediction dump: truth vs base vs model
        self.export_predictions(out_dir)
        return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--lambda-si", type=float, default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--seed", type=int, default=None,
                    help="training seed (path split stays on split_seed)")
    ap.add_argument("--enc-blocks", type=int, default=None,
                    help="number of ChainMP+BiGRU blocks (GNN hops)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.out_dir:
        cfg["train"]["out_dir"] = args.out_dir
    if args.seed is not None:
        cfg["train"]["seed"] = args.seed
    if args.enc_blocks is not None:
        cfg["model"]["enc_blocks"] = args.enc_blocks
    Trainer(cfg, args.lambda_si).run()


if __name__ == "__main__":
    sys.exit(main())
