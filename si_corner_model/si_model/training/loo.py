"""Seen/hidden corner split and precomputed leave-one-out base artifacts.

The corner grid is (voltage, second-axis); the second axis is RC or temperature
(see parsing/keys.py). The OLS basis and its fit mode come from the config via
``config.expand_terms`` and ``base.weighting`` -- this module is axis-agnostic.
"""
import os
from dataclasses import dataclass

import numpy as np

from si_model.config import axes, axis_coords, expand_terms, fit_scales
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


def relabel_levels(corners, vt: np.ndarray, cfg: dict) -> np.ndarray:
    """Re-derive the second-axis column from the corner NAMES and the CURRENT
    ``corners.level_values``, instead of trusting what the cache was built with.

    The level coordinate is baked into ``vt`` by build_dataset, so editing
    ``level_values`` in config.yaml used to change nothing at all until the
    dataset was rebuilt -- a knob that silently did not move. The names carry
    the level (``SSPG_0P5000V_cmax``), so the coordinate is derivable at every
    load and does not need to be stored.

    This matters because the level coordinates are a hypothesis worth testing
    by hand. On the company drop the measured order is cmax < rcmin < rcmax,
    not the declared rcmin < cmax < rcmax, and a reader may reasonably want to
    try, say, ``{cmax: -1, rcmin: 0, rcmax: 1}`` -- the measured ORDER with even
    spacing -- and read the hidden error off it. That is a one-line config edit
    and a seconds-long `run.sh base`, but only if the edit takes effect.

    Corners that do not parse are left exactly as the cache had them, so a
    voltage x temperature grid (no level names at all) is untouched.
    """
    from si_model.parsing.keys import parse_corner

    lv = _level_map(cfg)
    prefix = str((cfg.get("data") or {}).get("corner_prefix") or "TT")
    out = np.array(vt, dtype=float, copy=True)
    changed = []
    for i, name in enumerate(corners):
        try:
            _, a1 = parse_corner(str(name), lv, prefix)
        except (ValueError, KeyError):
            continue
        if abs(float(a1) - float(out[i, 1])) > 1e-9:
            changed.append(str(name))
        out[i, 1] = float(a1)
    # Under `measured` a difference is expected and means nothing: an earlier
    # stage in the same process already wrote its measured coordinates into
    # this cfg, and the next thing that happens is measuring them again from
    # the same data. Saying "the cache was built with different level_values"
    # there reads as a config problem in the middle of a training run, which is
    # how it got reported. Only `declared` can differ for a reason worth
    # hearing: someone edited level_values since the cache was built.
    # Nor when predict has pinned the trained base: those coordinates differ
    # from the cache's by design, and the message would read as a config edit
    # nobody made -- which is exactly how it was reported.
    if (changed and str(cfg["base"].get("level_coords", "measured")) != "measured"
            and not cfg["base"].get("_pinned")):
        print(f"[LEVELS] level coordinates re-derived from config for "
              f"{len(changed)} corner(s): corners.level_values differs from "
              f"what the cache was built with. Using the config; no rebuild "
              f"needed.", flush=True)
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
    vt = relabel_levels(corners, vt, cfg)
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
    # A holdout is what training and `base` are scored on, so those need one.
    # `predict --at/--sweep` does not: it is asked for corners by coordinate,
    # and a circuit that has just arrived -- everything it measured is seen,
    # the point is to predict what it did not -- has no holdout to give. That
    # is the deployment case, and it used to be refused here.
    if os.environ.get("SI_STAGE") != "predict":
        assert hidden.any(), (
            "degenerate split: no hidden corners -- give split a holdout "
            "(hidden_voltages / seen_voltages) or add data.query_corners for "
            "pure inference. (Only `predict` runs without one, by naming the "
            "corners it wants: predict --at / --sweep.)")
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
    the same basis and the model matches the base it was trained against.

    The second-axis COORDINATES are chosen the same way and for the same
    reason, before the basis is -- see ``run.fit_level_coords``. Both hooks are
    here rather than in the callers so that base, train and predict cannot
    disagree about the grid the model was fit on."""
    # Both level hooks return a MODIFIED COPY, and the caller holds the
    # original. Whatever they resolve has to be published back into it, or the
    # caller reports the axis it asked for rather than the axis that was used
    # -- which is indistinguishable from the switch not working.
    caller_cfg = cfg
    if y is not None and str(cfg["base"].get("level_coords", "measured")) == "measured":
        from si_model.run import measured_level_coords
        cfg = measured_level_coords(y, split, cfg)
    if y is not None and cfg["base"].get("fit_level_values", False):
        from si_model.run import fit_level_coords
        cfg = fit_level_coords(y, split, cfg)
    if cfg is not caller_cfg:
        ax = caller_cfg["base"]["axes"][1]
        ax["levels"] = dict(cfg["base"]["axes"][1].get("levels") or {})
        ax["order"] = cfg["base"]["axes"][1]["order"]
    # The axis VARIABLE is chosen before the coordinates are built, since it
    # is what they are built from; the basis is chosen after, on those
    # coordinates. Both write into cfg, so predict replays one decision.
    if y is not None and str(cfg["base"].get("v_transform", "none")) == "auto":
        from si_model.run import select_v_transform
        cfg = select_v_transform(y, split, cfg)
        caller_cfg["base"]["v_transform"] = cfg["base"]["v_transform"]
        caller_cfg["base"]["axes"][0]["transform"] = \
            cfg["base"]["axes"][0]["transform"]
    coords = axis_coords(cfg, split.vt, split.vt[split.ref_ci])
    seen_levels = [int(np.unique(np.round(split.vt[split.seen_idx, a], 9)).size)
                   for a in range(split.vt.shape[1])]
    if y is not None and cfg["base"].get("select", True):
        from si_model.run import select_basis
        cfg = select_basis(y, split, coords, cfg)
    exps, names, dropped = expand_terms(cfg, seen_levels)
    if dropped and not _base_quiet():
        print(f"[BASIS] dropped rank-deficient terms {dropped} "
              f"(seen levels per axis = {seen_levels})", flush=True)
    if not _base_quiet():
        print(f"[BASIS] {len(exps)} terms: {names}", flush=True)
    phi = design_matrix(coords, exps)
    if y is not None and str(cfg["base"].get("weighting", "plain")) == "auto":
        from si_model.run import select_weighting
        cfg = select_weighting(y, split, phi, coords, cfg)
        caller_cfg["base"]["weighting"] = cfg["base"]["weighting"]
    # Everything the three selections decided, in one place, so the checkpoint
    # carries it and predict can reproduce THIS base instead of choosing again.
    # Re-choosing at predict time is how a trained correction ends up on top of
    # a base it never saw: a code or config change between train and predict --
    # files copied across by hand, a default flipped -- re-selects silently.
    # Measured: switching the base settings before predict moved predictions by
    # 0.069 ps and mean error 0.123 -> 0.167 ps, with no error and no warning.
    caller_cfg["base"]["_resolved"] = {
        "v_order": int(cfg["base"]["axes"][0]["order"]),
        "cross_terms": bool(cfg["base"].get("cross_terms", True)),
        "cross_max_degree": int(cfg["base"].get("cross_max_degree", 3)),
        "levels": {str(k): float(v) for k, v in
                   (cfg["base"]["axes"][1].get("levels") or {}).items()},
        "level_order": int(cfg["base"]["axes"][1]["order"]),
        "weighting": str(cfg["base"].get("weighting", "plain")),
        "v_transform": str(cfg["base"]["axes"][0].get("transform", "none")),
    }
    return phi, coords, exps, names


def _adaptive_kwargs(cfg: dict) -> dict:
    b = cfg["base"]
    return dict(grid=b.get("adaptive_grid"),
                k=int(b.get("adaptive_k", 6)),
                amp_ratio=float(b.get("adaptive_amp_ratio", 1.5)),
                clip_frac=float(b.get("adaptive_clip_frac", 0.3)))


def _mode(cfg: dict) -> str:
    return cfg["base"].get("weighting", cfg["base"].get("local_bandwidth", "adaptive"))


def _base_quiet() -> bool:
    """True when base diagnostics should stay silent.

    They are printed only when `base` was asked for by name. Under `all` that
    stage still runs, between build and train, where every line of it sits
    between the reader and the epochs they are waiting for. Nothing about the
    computation changes -- `run.sh base` prints all of it.
    """
    import os
    if os.environ.get("SI_VERBOSE", "0") != "0":
        return False                      # one switch turns everything back on
    return os.environ.get("SI_STAGE", "base") != "base"


_ADAPTIVE_WARNED = set()


def _effective_mode(cfg: dict, split: Split) -> str:
    """base.weighting, downgraded to ``plain`` when the grid is too small for
    ``adaptive`` to mean anything.

    ``adaptive`` picks a per-corner bandwidth by scoring candidates against the
    ``adaptive_k`` nearest seen corners. When there are no more seen corners than
    that, the "neighbourhood" IS the whole grid, so every candidate is scored on
    identical data and the winner is noise. Measured on the real 14nm drop at
    125C (6 seen, adaptive_k=6): adaptive gave 3.151 ps at the hidden corners
    where plain gave 2.148 (worst 5.269 vs 2.555).

    This is a structural rule, not a fit to held-out error: it fires on the
    corner count alone, which is known before any label is read.

    It is also no longer the main reason plain is used -- ``base.weighting``
    now defaults to plain outright, because base quality alone turned out to
    be the wrong thing to select on. The base is not used by itself; a network
    learns a residual on top of it, and on an adaptive base that learning did
    not happen at all: 125C stalled at 3.08 ps (its E2 value) for the whole
    run, and m25 sat at 11.19 ps for 30 epochs, while the same setups on a
    plain base reached 0.94 ps and 10.25 ps. At m25 adaptive is the better
    base on its own (worst 13.5 vs 19.6 ps) and still loses end to end. The
    downgrade below stays for anyone who sets adaptive explicitly."""
    mode = cfg["base"].get("weighting", cfg["base"].get("local_bandwidth", "adaptive"))
    if mode != "adaptive":
        return mode
    n_seen = int(split.seen.sum())
    k = int(cfg["base"].get("adaptive_k", 6))
    if n_seen > k:
        return mode
    key = (n_seen, k, tuple(split.corners[:2]))
    if key not in _ADAPTIVE_WARNED and not _base_quiet():
        _ADAPTIVE_WARNED.add(key)
        print(f"[BASE] {n_seen} seen corners <= adaptive_k {k} -- the neighbourhood "
              f"becomes the whole grid, so adaptive cannot select a bandwidth. "
              f"Fitting plain instead.", flush=True)
    return "plain"


def fit_field(y, phi, split, coords, cfg, force_mode: "str | None" = None):
    """Fit one per-corner field (slack / SI / slew) under base.weighting.
    Returns (loo_field [N,C], picks-or-None).

    ``force_mode`` bypasses ``_effective_mode`` so a caller can measure what a
    mode WOULD have produced -- used by the comparison print in ``run.stage_base``,
    which must show adaptive's real numbers even where the rule downgrades it."""
    mode = force_mode or _effective_mode(cfg, split)
    if mode == "adaptive":
        return fit_base_adaptive(y, phi, split.seen, coords, **_adaptive_kwargs(cfg))
    if mode == "local":
        bw = tuple(cfg["base"]["bandwidth"])
        return fit_base_local(y, phi, split.seen, coords, bw), None
    _, loo = fit_base(y, phi, split.seen)             # plain
    return loo, None


def _mode_gap(col):
    """The clock period a corner was measured at: the most common positive
    capture-minus-launch gap over paths. Multicycle paths carry k*T, so the
    mode is T for any grid where single-cycle paths are not the minority."""
    v = np.asarray(col, float)
    v = v[np.isfinite(v) & (v > 1e-12)]
    if not len(v):
        return None                      # hold: both edges are the same edge
    vals, cnt = np.unique(np.round(v, 6), return_counts=True)
    return float(vals[int(np.argmax(cnt))])


def period_offset(ds, split: Split, cfg: dict):
    """[N, C] the part of slack that is the CLOCK PLAN rather than the circuit,
    to subtract before fitting and add back to any fitted value. None when
    there is nothing to do.

    setup slack = T - (sum of delays) + skew - U. T is a design choice, so a
    grid measured at one period per voltage -- which is what DVFS does, slower
    clock at lower voltage -- is a grid where the field being fitted is
    T(V) - delay(V). Only the second term is a smooth function of the corner.
    Inside the measured range a polynomial absorbs the first one silently;
    outside it, extrapolating means extrapolating somebody's frequency plan,
    and every candidate basis then misses by the SAME constant. Measured on the
    company drop: ~1490 ps at every order, and the lowest voltage's measured
    slack came out HIGHER than the next one up -- slack improving as voltage
    falls, which only a relaxed clock can do.

    The correction is exact, not a model::

        slack(T') = slack(T) + N * (T' - T)          N = that path's cycles

    so every corner is moved to the reference corner's period, the fit sees the
    circuit alone, and the offset is added back afterwards so that every number
    reported is still the slack at that corner's own period.

    This reads the clock EDGES, not the slack: the period is an input to the
    timing run, known before any measurement, so using a held-out corner's
    period is not using its label. A corner with no report at all (a pure query
    coordinate) has no period to read, and is reported at the reference period
    unless --period / --freq says otherwise.

    Off by ``base.period_norm: off``. Requires cycle_gap in the cache, which
    needs a build with a parser that reads the clock edge lines.
    """
    # Every way out of here SAYS SO. This returned None down five different
    # paths without a word, and on the company machine one of them fired: the
    # numbers came out identical with period_norm auto and off, which is exactly
    # what "silently did nothing" looks like from outside, and nothing on screen
    # could tell which path it was.
    def _no(why):
        if not _base_quiet():
            print("[PERIOD] not normalising: %s" % why, flush=True)
        return None

    if str(cfg["base"].get("period_norm", "auto")) == "off":
        return _no("base.period_norm is off")
    gap = ds.get("cycle_gap") if hasattr(ds, "get") else None
    if gap is None:
        return _no("this cache has no cycle_gap -- it was built before the "
                   "parser read the clock edge lines. Re-run build.")
    gap = np.asarray(gap, float)
    C = split.vt.shape[0]
    if gap.ndim != 2:
        return _no("cycle_gap has shape %r, expected [paths, corners]"
                   % (gap.shape,))
    if gap.shape[1] < C:
        return _no("cycle_gap has %d corner columns but this grid has %d "
                   "corners -- the cache does not match the config. Re-run build."
                   % (gap.shape[1], C))
    if gap.shape[1] > C:
        # build pads the corner axis; the extra columns are not corners here
        if not _base_quiet():
            print("[PERIOD] cycle_gap carries %d columns for %d corners -- "
                  "using the first %d" % (gap.shape[1], C, C), flush=True)
        gap = gap[:, :C]
    if not np.isfinite(gap).any():
        return _no("every cycle_gap is NaN -- the parser found no clock edge "
                   "lines in these reports. Check `run.sh check --file <report>`.")
    T = [_mode_gap(gap[:, c]) for c in range(gap.shape[1])]
    T_ref = T[split.ref_ci]
    if T_ref is None:
        return _no("the anchor corner %s has no positive launch-to-capture gap "
                   "(a hold check, or its edge lines were not parsed)"
                   % split.corners[split.ref_ci])
    have = [t for t in T if t is not None]
    if max(have) - min(have) <= 1e-9:
        return _no("every corner was measured at the same period (%.4f ns) -- "
                   "nothing to normalise" % T_ref)
    off = np.zeros_like(gap)
    for c, t in enumerate(T):
        if t is None:
            continue                     # hold column: period-independent
        n = np.where(np.isfinite(gap[:, c]), gap[:, c] / t, 0.0)
        off[:, c] = n * (t - T_ref)
    if not _base_quiet():
        print("[PERIOD] the grid is not measured at one clock period "
              "(%.4f .. %.4f ns). Fitting the slack every corner WOULD have at "
              "%.4f ns (the anchor's period) and adding each corner's own "
              "N*(T-Tref) back afterwards -- exact, so reported slacks are "
              "unchanged. base.period_norm: off disables it."
              % (min(have), max(have), T_ref), flush=True)
    return off


def compute_base(ds, split: Split, cfg: dict) -> BaseArtifacts:
    off = period_offset(ds, split, cfg)
    y = ds["slack"] if off is None else ds["slack"] - off
    phi, coords, exps, _ = build_design(cfg, split, y=y)
    slack_loo, picks = fit_field(y, phi, split, coords, cfg)
    si_loo, _ = fit_field(ds["si_label"], phi, split, coords, cfg)
    if picks and not _base_quiet():
        print("[BASE-ADAPTIVE] per-corner bandwidth picks: "
              + ", ".join(f"{k}:{v}" for k, v in sorted(picks.items(), key=str)),
              flush=True)
    if off is not None:
        # back to the slack each corner actually has, so everything downstream
        # -- the residual the network learns, the predictions, the reports --
        # is in the same units as the measurements, with no flag to remember
        slack_loo = slack_loo + off
    resid = ds["slack"] - slack_loo
    return BaseArtifacts(phi, coords, exps, slack_loo, resid, si_loo)
