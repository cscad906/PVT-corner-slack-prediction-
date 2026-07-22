"""SI branch inputs: interpolate per-aggressor bump/window/slew across the
corner grid and recompute the overlap gate analytically at the query corner.

Design (see docs/PARSING.md for the SI arrays this consumes):

  - candidate set = union of ACTIVE aggressors across all corners (the dump
    emits only active rows; union mean 2.5, max 11 per victim)
  - bump/windows/slew exist only at corners where the aggressor is active
    ("anchors"); we fit a low-order poly in (dv, dt) on anchors within SEEN
    corners and evaluate anywhere
  - overlap is NEVER interpolated directly: interpolate window endpoints,
    then overlap = min(maxes) - max(mins)
  - anti-leakage: at a seen target corner the poly prediction is replaced by
    its closed-form leave-one-out value, so a corner never sees its own
    measured windows/bumps (matches how hidden corners are predicted).

Poly order backs off with anchor count: >=8 quadratic, >=4 linear, else mean.
Rows sharing an anchor mask are solved as one batched OLS (the 69% of
aggressor pairs active at all corners collapse into a handful of groups).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def _interp_rows(flat: np.ndarray, seen: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """flat: [M, C] observed-with-NaN. Returns [M, C] poly predictions with
    LOO substitution at observed seen corners."""
    M, C = flat.shape
    obs = ~np.isnan(flat)
    anchors = obs & seen[None, :]
    n_anchor = anchors.sum(axis=1)
    rank = np.where(n_anchor >= 8, 2, np.where(n_anchor >= 4, 1, 0))
    cols_by_rank = [np.array([0]), np.array([0, 1, 2]),
                    np.arange(min(6, phi.shape[1]))]

    out = np.full((M, C), np.nan, np.float64)
    groups: dict[tuple[bytes, int], list[int]] = defaultdict(list)
    for i in range(M):
        if n_anchor[i] == 0:
            continue
        groups[(anchors[i].tobytes(), int(rank[i]))].append(i)

    for (mbytes, rk), rows in groups.items():
        mask = np.frombuffer(mbytes, dtype=bool)
        cols = cols_by_rank[rk]
        p = phi[np.ix_(mask, cols)]                    # [n, k]
        gram_inv = np.linalg.pinv(p.T @ p)
        proj = p @ gram_inv                            # [n, k]
        h = np.einsum("nk,nk->n", proj, p)             # leverage diag
        y = flat[np.ix_(rows, np.where(mask)[0])]      # [R, n]
        beta = y @ proj                                # [R, k]
        pred = beta @ phi[:, cols].T                   # [R, C]
        loo = y - (y - beta @ p.T) / np.clip(1.0 - h, 1e-6, None)[None, :]
        pred[:, mask] = loo
        out[rows] = pred
    return out


def build_si_features(ds, phi: np.ndarray, seen: np.ndarray) -> dict:
    """Interpolated, leakage-safe SI features at every corner.

    ds: arrays from dataset.npz. phi: [C, K] design matrix from
    base_ols.design_matrix (col 0 intercept, 1 dv, 2 dt, then quadratics).
    seen: [C] bool.

    Returns float32 arrays:
      vwin_hat [S, C, 2], bump_hat/aslew_hat [S, A, C], awin_hat [S, A, C, 2],
      overlap [S, A, C] (>=0), present [S, A] bool.
    """
    vwin, abump, awin, aslew = ds["vwin"], ds["abump"], ds["awin"], ds["aslew"]
    S, A, C = abump.shape

    def interp(y) -> np.ndarray:
        return _interp_rows(y.reshape(-1, C).astype(np.float64), seen, phi) \
            .reshape(y.shape).astype(np.float32)

    present = ~np.isnan(abump).all(axis=2)             # [S, A]
    vwin_hat = np.stack([interp(vwin[..., 0]), interp(vwin[..., 1])], axis=-1)
    bump_hat = interp(abump)
    aslew_hat = interp(aslew)
    awin_hat = np.stack([interp(awin[..., 0]), interp(awin[..., 1])], axis=-1)

    lo = np.maximum(vwin_hat[:, None, :, 0], awin_hat[..., 0])   # [S, A, C]
    hi = np.minimum(vwin_hat[:, None, :, 1], awin_hat[..., 1])
    overlap = np.clip(hi - lo, 0.0, None)
    overlap = np.where(present[:, :, None], overlap, 0.0)

    return {
        "vwin_hat": np.nan_to_num(vwin_hat),
        "bump_hat": np.nan_to_num(bump_hat),
        "aslew_hat": np.nan_to_num(aslew_hat),
        "awin_hat": np.nan_to_num(awin_hat),
        "overlap": np.nan_to_num(overlap).astype(np.float32),
        "present": present,
    }
