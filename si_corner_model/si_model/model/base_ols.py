"""Per-path OLS base over the continuous corner axes, with closed-form
leave-one-out.

The corner axes are whatever the config declares under ``base.axes`` -- e.g.
**voltage + BEOL/RC** (14nm) or **voltage + temperature** (3nm). Temperature /
process / setup-vs-hold are NOT axes here; they select separate models (see
``config.py`` and the README). The polynomial basis (its per-axis order, the
3rd-vs-4th-order choice, cross terms) is generated in ``config.expand_terms`` and
passed in as exponent tuples, so this module is axis-count- and axis-name-
agnostic.

The base carries the smooth corner dependence of TOTAL slack (SI included); the
neural pieces only learn residuals. Scheme = "all-seen leave-one-out":

  - training target at seen corner c: residual vs the base fit on seen-{c}
    -- computed in closed form from the single all-seen fit via the hat
    matrix: e_loo = (y - yhat) / (1 - h)
  - inference at hidden corner h: base fit on ALL seen corners (h is
    unmeasured, hence naturally excluded -- no leakage).

Three fit modes, selected by ``base.weighting`` in the config:
  - ``plain``    : one global OLS fit               -> fit_base
  - ``local``    : fixed-bandwidth locally-weighted -> fit_base_local  (weighted OLS)
  - ``adaptive`` : per-corner bandwidth selection   -> fit_base_adaptive (best)

Anchor = fitted intercept (Method B). Method A (measured ref anchor) is a
one-line ablation: subtract y_ref before fitting and drop the "1" term.
"""
import numpy as np


# --------------------------------------------------------------- design matrix
def design_matrix(coords: np.ndarray, exps: "list[tuple[int, ...]]") -> np.ndarray:
    """[C, K+1] polynomial design matrix (column 0 = constant).

    ``coords`` is [C, A] and is ALREADY scaled to fit units (each axis = the
    reference-subtracted coordinate divided by its ``fit_scale`` -- e.g. dt/100
    for a temperature axis). ``exps`` is the list of per-axis exponent tuples
    from ``config.expand_terms`` (the constant is added here, not listed there).
    """
    C = coords.shape[0]
    cols = [np.ones(C)]
    for t in exps:
        col = np.ones(C)
        for a, e in enumerate(t):
            if e:
                col = col * coords[:, a] ** e
        cols.append(col)
    return np.stack(cols, axis=1)


# ------------------------------------------------------------------- fit modes
def fit_base(
    y: np.ndarray,           # [N, C] targets (slack, or any per-corner scalar)
    phi: np.ndarray,         # [C, K] design matrix
    seen: np.ndarray,        # [C] bool mask of seen corners
) -> "tuple[np.ndarray, np.ndarray]":
    """Vectorized over paths. Returns (pred, loo_pred), both [N, C]:

    pred[n, c]     = all-seen fit evaluated at every corner c
    loo_pred[n, c] = for seen c, the fit on seen-{c} evaluated at c
                     (closed form); for hidden c, equals pred[n, c].
    NaN-safe: paths with NaN at some seen corner are fit on their non-NaN
    subset (not expected in this dataset; kept for robustness).
    """
    N, C = y.shape
    ps = phi[seen]                                   # [Cs, K]
    ys = y[:, seen]                                  # [N, Cs]
    if not np.isnan(ys).any():
        gram_inv = np.linalg.pinv(ps.T @ ps)         # [K, K]
        beta = ys @ ps @ gram_inv.T                  # [N, K]
        pred = beta @ phi.T                          # [N, C]
        h = np.einsum("ck,kj,cj->c", ps, gram_inv, ps)   # leverage, [Cs]
        resid = ys - beta @ ps.T
        loo_resid = resid / np.clip(1.0 - h, 1e-6, None)
        loo_pred = pred.copy()
        loo_pred[:, seen] = ys - loo_resid
        return pred, loo_pred

    pred = np.full_like(y, np.nan)
    loo_pred = np.full_like(y, np.nan)
    for n in range(N):
        ok = ~np.isnan(ys[n])
        p, yv = ps[ok], ys[n, ok]
        gram_inv = np.linalg.pinv(p.T @ p)
        beta = gram_inv @ p.T @ yv
        pred[n] = phi @ beta
        h = np.einsum("ck,kj,cj->c", p, gram_inv, p)
        loo = yv - (yv - p @ beta) / np.clip(1.0 - h, 1e-6, None)
        full = np.full(seen.sum(), np.nan)
        full[ok] = loo
        loo_pred[n] = pred[n]
        loo_pred[n, np.where(seen)[0]] = full
    return pred, loo_pred


def fit_base_local(
    y: np.ndarray,           # [N, C] targets
    phi: np.ndarray,         # [C, K] design matrix
    seen: np.ndarray,        # [C] bool
    coords: np.ndarray,      # [C, A] scaled axis coords
    bw: "tuple[float, ...]",   # per-axis Gaussian kernel bandwidths
) -> np.ndarray:
    """Locally-weighted variant of fit_base (weighted OLS): each query corner
    fits its own weighted OLS with Gaussian weights over the seen corners, so
    nearby corners dominate and a global-misfit region cannot pollute the fit.

    Returns loo_pred [N, C]: weighted-LOO at seen corners (the query's own
    measurement excluded via the weighted hat matrix), all-seen weighted fit at
    hidden corners. bw -> (inf, ...) recovers plain fit_base.
    """
    N, C = y.shape
    A = coords.shape[1]
    seen_idx = np.where(seen)[0]
    ps = phi[seen]                                   # [Cs, K]
    ys = y[:, seen]                                  # [N, Cs]
    out = np.full_like(y, np.nan, dtype=np.float64)
    bw = np.asarray(bw, dtype=np.float64)
    for q in range(C):
        d = coords[seen] - coords[q]                 # [Cs, A]
        w = np.exp(-0.5 * ((d / bw[None, :]) ** 2).sum(axis=1))
        wp = ps * w[:, None]
        gram_inv = np.linalg.pinv(ps.T @ wp)
        proj = wp @ gram_inv                         # [Cs, K]
        beta = ys @ proj                             # [N, K]
        if seen[q]:
            j = int(np.where(seen_idx == q)[0][0])
            h = float(w[j] * ps[j] @ gram_inv @ ps[j])
            resid = ys[:, j] - beta @ ps[j]
            out[:, q] = ys[:, j] - resid / np.clip(1.0 - h, 1e-6, None)
        else:
            out[:, q] = beta @ phi[q]
    return out


def default_adaptive_grid(coords: np.ndarray, seen: np.ndarray) -> list:
    """Label-free per-axis bandwidth grid derived from the seen-grid spacing:
    for each axis, {1x, 2x, 4x} its median seen step; the Cartesian product plus
    the global fit (None). Used when the config gives no explicit grid, so the
    engine adapts to unknown vendor grids without hand-tuning."""
    A = coords.shape[1]
    steps = []
    for a in range(A):
        u = np.unique(coords[seen, a])
        dif = np.diff(np.sort(u))
        dif = dif[dif > 1e-9]
        s = float(np.median(dif)) if dif.size else 1.0
        steps.append([s, 2 * s, 4 * s])
    grid = [None]

    def rec(a, cur):
        if a == A:
            grid.append(tuple(cur))
            return
        for s in steps[a]:
            rec(a + 1, cur + [s])
    rec(0, [])
    return grid


def fit_base_adaptive(
    y: np.ndarray,           # [N, C]
    phi: np.ndarray,         # [C, K]
    seen: np.ndarray,        # [C] bool
    coords: np.ndarray,      # [C, A] scaled axis coords
    grid=None,
    k: int = 6,
    amp_ratio: float = 1.5,
    clip_frac: float = 0.3,
    return_choice: bool = False,
):
    """Adaptive locally-weighted OLS: each query corner picks its OWN kernel
    bandwidth (the "level-3" base -- the best-performing mode).

    Merges the two reference implementations:
      * **isotropic kNN selection** -- the neighbour metric scales each axis by
        its median seen spacing, so an edge corner's nearest anchors are its
        genuine grid neighbours (without this, a wide-range axis like RC in
        {-1,0,1} vs V in [0.6,0.8] dominates the metric and edge corners inherit
        interior bandwidths -- observed 86.8 -> 3.4 ps LOO fix);
      * **extrapolation-variance guard** (``amp_ratio``) -- forbid any bandwidth
        whose prediction variance at the query exceeds amp_ratio x the global
        fit's; narrow kernels outside the seen hull explode and the neighbour
        LOO criterion (interpolated neighbours) cannot see it;
      * **measured-range clip** (``clip_frac``) -- clip every candidate LOO field
        to [min, max] of the seen targets +/- clip_frac*range, so a tight kernel
        cannot corrupt the base with a wild extrapolation.

    For each query corner q, choose the bandwidth minimizing the seen-LOO MAE
    over its k nearest SEEN corners (q excluded) -- a purely label-free,
    neighbourhood-local criterion. Flat regions pick a narrow/sharp kernel,
    steep regions a wide/robust one (or the global fit). Returns (base [N,C],
    picks) or (base, choice) with return_choice.

    Leakage safety: a seen corner's own label enters only its own LOO error,
    excluded from its own bandwidth selection; hidden corners are never measured,
    so their selection uses seen neighbours only.
    """
    N, C = y.shape
    A = coords.shape[1]
    seen_idx = np.where(seen)[0]
    if grid is None:
        grid = default_adaptive_grid(coords, seen)

    # measured-range clip bounds
    ys = y[:, seen_idx]
    lo, hi = float(np.nanmin(ys)), float(np.nanmax(ys))
    m = clip_frac * (hi - lo)

    ps = phi[seen]                                   # [Cs, K]
    preds, errs = [], []
    amp = np.empty((len(grid), C))                   # noise amplification factor
    for gi, bw in enumerate(grid):
        if bw is None:
            _, p = fit_base(y, phi, seen)
            w_all = np.ones((C, ps.shape[0]))
        else:
            p = fit_base_local(y, phi, seen, coords, bw)
            d = coords[seen][None] - coords[:, None]                 # [C, Cs, A]
            bwv = np.asarray(bw, dtype=np.float64)
            w_all = np.exp(-0.5 * ((d / bwv[None, None, :]) ** 2).sum(axis=2))
        p = np.clip(p, lo - m, hi + m)
        for q in range(C):
            wp = ps * w_all[q][:, None]
            g_inv = np.linalg.pinv(ps.T @ wp)
            ell = phi[q] @ g_inv @ wp.T                              # equivalent kernel [Cs]
            amp[gi, q] = float((ell ** 2).sum())                    # Var(pred)/sigma^2
        preds.append(p)
        errs.append(np.abs(y[:, seen_idx] - p[:, seen_idx]).mean(axis=0))  # [Cs]
    preds = np.stack(preds)      # [G, N, C]
    errs = np.stack(errs)        # [G, Cs]
    gi_global = next((i for i, b in enumerate(grid) if b is None), None)
    amp_ref = amp[gi_global] if gi_global is not None else amp.min(axis=0)

    # per-axis scale = median seen spacing -> isotropic kNN metric
    scale = np.empty(A)
    for a in range(A):
        dif = np.diff(np.sort(np.unique(coords[seen_idx, a])))
        dif = dif[dif > 1e-9]
        scale[a] = np.median(dif) if dif.size else 1.0
    sco = coords / scale

    out = np.empty((N, C))
    choice = np.empty(C, dtype=int)
    picks: dict = {}
    for q in range(C):
        allowed = np.where(amp[:, q] <= amp_ratio * max(amp_ref[q], 1e-9))[0]
        if allowed.size == 0:
            allowed = np.array([int(np.argmin(amp[:, q]))])
        dist = np.linalg.norm(sco[seen_idx] - sco[q], axis=1)
        nb = np.where(dist > 1e-9)[0]
        nb = nb[np.argsort(dist[nb])[:k]]
        g = int(allowed[np.argmin(errs[np.ix_(allowed, nb)].mean(axis=1))])
        choice[q] = g
        out[:, q] = preds[g][:, q]
        key = grid[g] if grid[g] is None else tuple(round(float(x), 4) for x in grid[g])
        picks[key] = picks.get(key, 0) + 1
    return (out, choice) if return_choice else (out, picks)
