"""Seen/hidden corner split and precomputed leave-one-out base artifacts.

The corner grid is (voltage, second-axis); the second axis is RC or temperature
(see parsing/keys.py). The OLS basis and its fit mode come from the config via
``config.expand_terms`` and ``base.weighting`` -- this module is axis-agnostic.
"""
from dataclasses import dataclass

import numpy as np

from si_model.config import axes, expand_terms, fit_scales
from si_model.model.base_ols import (design_matrix, fit_base, fit_base_adaptive,
                                      fit_base_local)
from si_model.parsing.keys import RC_VAL


@dataclass
class Split:
    corners: "list[str]"
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


def _level_map(cfg: dict) -> dict:
    """Level NAME -> axis coordinate, from ``base.axes[1].levels`` when the
    config declares one (any vendor naming), else the built-in RC map."""
    try:
        lv = axes(cfg)[1].get("levels")
    except (KeyError, IndexError):
        lv = None
    return {str(k): float(v) for k, v in lv.items()} if lv else dict(RC_VAL)


# Corner coordinates are stored in the cache as float32, so a declared 0.54 comes
# back as 0.54000002. Any tolerance tighter than float32 resolution (~1.2e-7 near
# 0.5) can therefore NEVER match, which is how `hidden_voltages: [0.54]` used to
# select nothing at all and leave the split with no hidden corners. Grid spacings
# here are ~1e-2 V and ~1 level, so 1e-5 is far below any real gap while sitting
# comfortably above float32 noise.
_TOL = 1e-5


def _near(a, b) -> bool:
    return abs(float(a) - float(b)) < _TOL


def _hidden_axis1_values(cfg: dict) -> set:
    """Second-axis levels to hold out, from any of ``hidden_axis1``,
    ``hidden_rc``/``hidden_levels`` (level NAMES or raw values), or
    ``hidden_temps`` (temperatures).

    Names are resolved through the config's own ``levels`` map, so a vendor
    naming like ``cmin``/``rcmax`` works -- previously only the built-in
    ``Cmin``/``Cnom``/``Cmax`` did, and anything else raised a bare
    ``could not convert string to float``.
    """
    lv = _level_map(cfg)
    out = set()
    for key in ("hidden_axis1", "hidden_rc", "hidden_levels", "hidden_temps"):
        for r in cfg["split"].get(key) or []:
            if isinstance(r, str):
                assert r in lv, (
                    f"split.{key}: unknown level {r!r}; known levels = {sorted(lv)} "
                    f"(declare it in the config's level map)")
                out.add(lv[r])
            else:
                out.add(float(r))
    return out


def _hidden_corner_pairs(cfg: dict) -> list:
    """Individually named corners to hold out: ``[[0.6, cmax], [0.54, rcmax]]``.

    Lets a specific (voltage, level) cell be hidden without hiding its whole row
    or column -- the finest-grained holdout, useful when the grid is small and
    dropping an entire voltage would cost too many anchors."""
    lv = _level_map(cfg)
    out = []
    for pair in cfg["split"].get("hidden_corners") or []:
        assert len(pair) == 2, f"split.hidden_corners entry must be [voltage, level]: {pair!r}"
        v, a = pair
        if isinstance(a, str):
            assert a in lv, f"split.hidden_corners: unknown level {a!r}; known = {sorted(lv)}"
            a = lv[a]
        out.append((float(v), float(a)))
    return out


def make_split(corners, vt: np.ndarray, cfg: dict,
               measured: "np.ndarray | None" = None) -> Split:
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
    hv = set(cfg["split"].get("hidden_voltages") or [])
    h1 = _hidden_axis1_values(cfg)
    hc = _hidden_corner_pairs(cfg)

    def v_hidden(v: float) -> bool:
        if sv:                                   # hidden = off the seen V grid
            return not any(_near(v, x) for x in sv)
        return any(_near(v, x) for x in hv)

    hidden = np.array([
        v_hidden(v)
        or any(_near(a, x) for x in h1)
        or any(_near(v, hvv) and _near(a, hav) for hvv, hav in hc)
        for v, a in vt
    ])
    if measured is not None:
        hidden |= ~np.asarray(measured, bool)    # query corners: never seen
    ref = cfg["data"]["ref_corner"]
    names = list(corners)
    assert ref in names, (f"ref corner {ref} not in the discovered grid; "
                          f"first few = {names[:4]}")
    ref_ci = names.index(ref)
    assert not hidden[ref_ci], f"ref corner {ref} must be seen"
    # `min_seen` guards against fitting a polynomial on too few anchors. The
    # default (8) suits the dense reference grids; a small deliverable (e.g.
    # 4 V x 2 BEOL = 8 corners) must lower it CONSCIOUSLY in config and shrink
    # the basis order to match -- see docs/COMPANY.md.
    min_seen = int(cfg["split"].get("min_seen", 8))
    n_seen = int((~hidden).sum())
    assert hidden.any(), ("degenerate split: no hidden corners -- give split a "
                          "holdout (hidden_voltages / seen_voltages) or add "
                          "data.query_corners for pure inference")
    assert n_seen >= min_seen, (
        f"degenerate split: {n_seen} seen corners < min_seen={min_seen}. "
        f"Widen the split, or lower split.min_seen if the deliverable really is "
        f"this small (then also lower base.axes[*].order).")
    return Split(names, vt, ~hidden, hidden, ref_ci)


@dataclass
class BaseArtifacts:
    phi: np.ndarray           # [C, K] design matrix (col0 = constant)
    coords: np.ndarray        # [C, A] scaled axis coords
    exps: list                # per-axis exponent tuples of the basis
    base_hat: np.ndarray      # [N, C] slack base: LOO at seen, all-seen at hidden
    resid: np.ndarray         # [N, C] slack - base_hat
    si_smooth_hat: np.ndarray # [N, C] same treatment for the SI label


def build_design(cfg: dict, split: Split, y=None):
    """Return (phi, coords, exps, names): scaled coords + polynomial design
    matrix, with rank-deficient terms auto-dropped and logged.

    When ``base.select`` is on (the default) and ``y`` is given, the basis is
    CHOSEN by seen-corner LOO rather than assumed -- see ``run.select_basis``.
    Every stage (base / train / predict) passes the same y, so they all land on
    the same basis and the model matches the base it was trained against."""
    ref_vt = split.vt[split.ref_ci]
    scales = np.asarray(fit_scales(cfg))
    A = split.vt.shape[1]
    coords = np.stack([(split.vt[:, a] - ref_vt[a]) / scales[a] for a in range(A)], 1)
    seen_levels = [int(np.unique(np.round(split.vt[split.seen_idx, a], 9)).size)
                   for a in range(A)]
    if y is not None and cfg["base"].get("select", True):
        from si_model.run import select_basis
        cfg = select_basis(y, split, coords, cfg)
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


_ADAPTIVE_WARNED = set()


def _effective_mode(cfg: dict, split: Split) -> str:
    """base.weighting, downgraded to ``plain`` when the grid is too small for
    ``adaptive`` to mean anything.

    ``adaptive`` picks a per-corner bandwidth by scoring candidates against the
    ``adaptive_k`` nearest seen corners. When there are no more seen corners than
    that, the "neighbourhood" IS the whole grid, so every candidate is scored on
    identical data and the winner is noise. Measured on the real 14nm drop at
    125C (6 seen, adaptive_k=6): adaptive gave 3.151 ps at the hidden corners
    where plain gave 2.148 (worst 5.269 vs 2.555). At m25 (10 seen) the
    neighbourhood is a real subset and adaptive holds its own -- better worst
    case (13.5 vs 19.6 ps) at a slightly worse mean -- so it is kept there.

    This is a structural rule, not a fit to held-out error: it fires on the
    corner count alone, which is known before any label is read."""
    mode = cfg["base"].get("weighting", cfg["base"].get("local_bandwidth", "adaptive"))
    if mode != "adaptive":
        return mode
    n_seen = int(split.seen.sum())
    k = int(cfg["base"].get("adaptive_k", 6))
    if n_seen > k:
        return mode
    key = (n_seen, k, tuple(split.corners[:2]))
    if key not in _ADAPTIVE_WARNED:
        _ADAPTIVE_WARNED.add(key)
        print(f"[BASE] seen 코너 {n_seen}개 <= adaptive_k {k} -- adaptive 는 이웃이 "
              f"전체와 같아져 대역폭을 고를 수 없다. plain 으로 적합한다.", flush=True)
    return "plain"


def fit_field(y, phi, split, coords, cfg):
    """Fit one per-corner field (slack / SI / slew) under base.weighting.
    Returns (loo_field [N,C], picks-or-None)."""
    mode = _effective_mode(cfg, split)
    if mode == "adaptive":
        return fit_base_adaptive(y, phi, split.seen, coords, **_adaptive_kwargs(cfg))
    if mode == "local":
        bw = tuple(cfg["base"]["bandwidth"])
        return fit_base_local(y, phi, split.seen, coords, bw), None
    _, loo = fit_base(y, phi, split.seen)             # plain
    return loo, None


def compute_base(ds, split: Split, cfg: dict) -> BaseArtifacts:
    phi, coords, exps, _ = build_design(cfg, split, y=ds["slack"])
    slack_loo, picks = fit_field(ds["slack"], phi, split, coords, cfg)
    si_loo, _ = fit_field(ds["si_label"], phi, split, coords, cfg)
    if picks:
        print("[BASE-ADAPTIVE] per-corner bandwidth picks: "
              + ", ".join(f"{k}:{v}" for k, v in sorted(picks.items(), key=str)),
              flush=True)
    resid = ds["slack"] - slack_loo
    return BaseArtifacts(phi, coords, exps, slack_loo, resid, si_loo)
