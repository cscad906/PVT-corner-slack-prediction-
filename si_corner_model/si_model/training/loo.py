"""Seen/hidden corner split and precomputed leave-one-out base artifacts.

The corner grid is (voltage, second-axis); the second axis is RC or temperature
(see parsing/keys.py). The OLS basis and its fit mode come from the config via
``config.expand_terms`` and ``base.weighting`` -- this module is axis-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from si_model.config import axes, expand_terms, fit_scales
from si_model.model.base_ols import (design_matrix, fit_base, fit_base_adaptive,
                                      fit_base_local)
from si_model.parsing.keys import RC_VAL


@dataclass
class Split:
    corners: list[str]
    vt: np.ndarray            # [C, 2] = (voltage, axis1_val)
    seen: np.ndarray          # [C] bool
    hidden: np.ndarray        # [C] bool
    ref_ci: int

    @property
    def seen_idx(self) -> np.ndarray:
        return np.where(self.seen)[0]

    @property
    def hidden_idx(self) -> np.ndarray:
        return np.where(self.hidden)[0]


def _hidden_axis1_values(cfg: dict) -> set:
    """Second-axis levels to hold out, from any of ``hidden_axis1`` (values or
    RC names), ``hidden_rc`` (RC names), or ``hidden_temps`` (temperatures)."""
    out = set()
    for key in ("hidden_axis1", "hidden_rc", "hidden_temps"):
        for r in cfg["split"].get(key, []):
            out.add(RC_VAL[r] if isinstance(r, str) and r in RC_VAL else float(r))
    return out


def make_split(corners, vt: np.ndarray, cfg: dict,
               measured: np.ndarray | None = None) -> Split:
    """Seen/hidden corner split.

    Voltage rule (pick one):
      - ``seen_voltages``: the measured V grid (e.g. a coarse grid); every
        voltage NOT on it is hidden -> predict the fine in-between corners.
      - ``hidden_voltages``: the explicit list of hidden voltages.
    Additionally any second-axis level named in ``hidden_axis1`` / ``hidden_rc``
    / ``hidden_temps`` is hidden, and any UNMEASURED corner (``measured=False``,
    i.e. a pure-inference ``data.query_corners`` entry with no data behind it)
    is always hidden -- it can never be an input.
    """
    sv = cfg["split"].get("seen_voltages")
    hv = set(cfg["split"].get("hidden_voltages", []))
    h1 = _hidden_axis1_values(cfg)

    def v_hidden(v: float) -> bool:
        if sv is not None:                       # hidden = off the seen V grid
            return not any(abs(v - x) < 1e-6 for x in sv)
        return any(abs(v - x) < 1e-9 for x in hv)

    hidden = np.array([
        v_hidden(v) or any(abs(a - x) < 1e-9 for x in h1)
        for v, a in vt
    ])
    if measured is not None:
        hidden |= ~np.asarray(measured, bool)    # query corners: never seen
    ref = cfg["data"]["ref_corner"]
    names = list(corners)
    ref_ci = names.index(ref)
    assert not hidden[ref_ci], f"ref corner {ref} must be seen"
    assert hidden.any() and (~hidden).sum() >= 8, "degenerate split"
    return Split(names, vt, ~hidden, hidden, ref_ci)


@dataclass
class BaseArtifacts:
    phi: np.ndarray           # [C, K] design matrix (col0 = constant)
    coords: np.ndarray        # [C, A] scaled axis coords
    exps: list                # per-axis exponent tuples of the basis
    base_hat: np.ndarray      # [N, C] slack base: LOO at seen, all-seen at hidden
    resid: np.ndarray         # [N, C] slack - base_hat
    si_smooth_hat: np.ndarray # [N, C] same treatment for the SI label


def build_design(cfg: dict, split: Split):
    """Return (phi, coords, exps, names): scaled coords + polynomial design
    matrix, with rank-deficient terms auto-dropped and logged."""
    ref_vt = split.vt[split.ref_ci]
    scales = np.asarray(fit_scales(cfg))
    A = split.vt.shape[1]
    coords = np.stack([(split.vt[:, a] - ref_vt[a]) / scales[a] for a in range(A)], 1)
    seen_levels = [int(np.unique(np.round(split.vt[split.seen_idx, a], 9)).size)
                   for a in range(A)]
    exps, names, dropped = expand_terms(cfg, seen_levels)
    if dropped:
        print(f"[BASIS] dropped rank-deficient terms {dropped} "
              f"(seen levels per axis = {seen_levels})", flush=True)
    print(f"[BASIS] {len(exps)} terms: {names}", flush=True)
    phi = design_matrix(coords, exps)
    return phi, coords, exps, names


def _adaptive_kwargs(cfg: dict) -> dict:
    b = cfg["base"]
    return dict(grid=b.get("adaptive_grid"),
                k=int(b.get("adaptive_k", 6)),
                amp_ratio=float(b.get("adaptive_amp_ratio", 1.5)),
                clip_frac=float(b.get("adaptive_clip_frac", 0.3)))


def _mode(cfg: dict) -> str:
    return cfg["base"].get("weighting", cfg["base"].get("local_bandwidth", "adaptive"))


def fit_field(y, phi, split, coords, cfg):
    """Fit one per-corner field (slack / SI / slew) under base.weighting.
    Returns (loo_field [N,C], picks-or-None)."""
    mode = _mode(cfg)
    if mode == "adaptive":
        return fit_base_adaptive(y, phi, split.seen, coords, **_adaptive_kwargs(cfg))
    if mode == "local":
        bw = tuple(cfg["base"]["bandwidth"])
        return fit_base_local(y, phi, split.seen, coords, bw), None
    _, loo = fit_base(y, phi, split.seen)             # plain
    return loo, None


def compute_base(ds, split: Split, cfg: dict) -> BaseArtifacts:
    phi, coords, exps, _ = build_design(cfg, split)
    slack_loo, picks = fit_field(ds["slack"], phi, split, coords, cfg)
    si_loo, _ = fit_field(ds["si_label"], phi, split, coords, cfg)
    if picks:
        print("[BASE-ADAPTIVE] per-corner bandwidth picks: "
              + ", ".join(f"{k}:{v}" for k, v in sorted(picks.items(), key=str)),
              flush=True)
    resid = ds["slack"] - slack_loo
    return BaseArtifacts(phi, coords, exps, slack_loo, resid, si_loo)
