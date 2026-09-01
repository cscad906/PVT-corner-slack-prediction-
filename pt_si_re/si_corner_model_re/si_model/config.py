"""Config schema, loader, and the OLS polynomial-basis generator.

One YAML config describes one trainable model instance. The engine is
data-agnostic: what makes a corner grid is declared under ``base.axes`` (the
*continuous* OLS axes, e.g. voltage + BEOL/RC), while everything that separates
one model from another -- setup vs hold, temperature, process -- is a *split*
dimension selected by the data paths, never an OLS axis (see README).

Polynomial order is a config option (the "3rd- vs 4th-order" question): each axis
declares an ``order`` and the basis is generated here, so nobody hand-maintains a
``terms:`` list. The generator reproduces the two hand-tuned reference bases
exactly (see ``expand_terms``) and drops rank-deficient monomials automatically.
"""
import copy
import os
import re

import yaml

_DEFAULTS_NAME = "_defaults.yaml"
_VAR_RE = re.compile(r"\$\{(\w+)\}")

#: repo root = the directory containing the ``si_model`` package.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------- loading
def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _builtin_vars() -> dict:
    """``${repo}`` = this checkout; ``${root}`` = its PARENT directory.

    The deployment layout this targets is a data root that holds the checkout
    next to the design folders::

        <root>/si_corner_model/     <- ${repo}
        <root>/<design>/            <- reports live here

    so ``${root}`` is correct with NO edit at all when the checkout sits where
    the data is. Override it when it does not (see ``resolve_vars``).
    """
    return {"repo": REPO_ROOT, "root": os.path.dirname(REPO_ROOT)}


def resolve_vars(cfg: dict) -> dict:
    """Substitute ``${name}`` placeholders throughout the config.

    Names resolve in this order (first wins), so a whole deliverable can be
    re-pointed from ONE place:

      1. environment ``SI_<NAME>``  -- e.g. ``SI_ROOT=/user/xxx/academy bash scripts/run.sh list``
      2. the config's own ``vars:`` block
      3. built-ins ``${repo}`` / ``${root}`` (see ``_builtin_vars``)

    Vars may reference other vars. The resolved map is stored back under
    ``cfg['vars']`` so runs are self-documenting.
    """
    vs = _builtin_vars()
    for k, v in (cfg.get("vars") or {}).items():
        vs[str(k)] = str(v)
    for k in list(vs):
        env = os.environ.get("SI_" + k.upper())
        if env:
            vs[k] = env

    def sub(s: str) -> str:
        return _VAR_RE.sub(lambda m: vs.get(m.group(1), m.group(0)), s)

    for _ in range(8):                       # vars referring to vars
        nxt = {k: sub(v) for k, v in vs.items()}
        if nxt == vs:
            break
        vs = nxt
    left = {m.group(1) for v in vs.values() for m in _VAR_RE.finditer(v)}
    assert not left, f"unresolved config vars: {sorted(left)} (declare them under `vars:` or set SI_<NAME>)"

    def walk(x):
        if isinstance(x, str):
            return sub(x)
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    out = walk(cfg)
    out["vars"] = vs
    return out


def load_config(path: str) -> dict:
    """Load a hand-written ENGINE-schema config (data / split / base / model /
    train) from a YAML file, then expand ``${var}`` placeholders.

    Normal use never calls this: ``config.yaml`` is the project config and
    ``si_model.run`` expands it into engine configs in memory. This is the
    escape hatch for driving one model instance from a YAML you wrote yourself
    (``python -m si_model.parsing.build_dataset --config mine.yaml``). A
    ``_defaults.yaml`` sitting next to the file, or one directory up, is
    deep-merged underneath it if present."""
    with open(path) as f:
        cfg = yaml.safe_load(f)
    here = os.path.dirname(os.path.abspath(path))
    for cand in (os.path.join(here, _DEFAULTS_NAME),
                 os.path.join(os.path.dirname(here), _DEFAULTS_NAME)):
        if os.path.exists(cand) and os.path.abspath(cand) != os.path.abspath(path):
            with open(cand) as f:
                defaults = yaml.safe_load(f) or {}
            cfg = _deep_merge(defaults, cfg)
            break
    return resolve_vars(cfg)


# --------------------------------------------------------------- axis metadata
def axes(cfg: dict) -> "list[dict]":
    """The continuous OLS axes, in grid order (axis 0 = voltage by convention).

    Each axis dict: ``name`` (str), ``ref`` (float, the reference-corner value),
    ``order`` (int, polynomial order on this axis), and optionally
    ``fit_scale`` (divide the axis coordinate by this before fitting; e.g. 100
    for a temperature axis so dt is O(1)), ``token_scale`` (coordinate unit for
    the neural query/token features), ``gap_cap`` (extrapolation-gap clamp).
    """
    ax = cfg["base"]["axes"]
    assert len(ax) >= 1, "need at least one continuous OLS axis"
    return ax


def fit_scales(cfg: dict) -> "list[float]":
    return [float(a.get("fit_scale", 1.0)) for a in axes(cfg)]


def axis_levels(cfg: dict) -> "dict | None":
    """Name->value map for a CATEGORICAL second axis (BEOL/RC, process, ...),
    declared as ``levels:`` on axis 1 in the config -- e.g.
    ``{Cbest: -1, Ctyp: 0, Cworst: 1}``. Returns None for a purely numeric second
    axis (temperature) or when no map is given (the built-in RC map is used)."""
    ax = axes(cfg)
    if len(ax) < 2:
        return None
    lv = ax[1].get("levels")
    return {str(k): float(v) for k, v in lv.items()} if lv else None


def token_scales(cfg: dict) -> "list[float]":
    """Coordinate unit for the neural token/query features (defaults: 0.1 for a
    voltage axis, 1.0 otherwise -- matches the original beol14/gt3 models)."""
    out = []
    for i, a in enumerate(axes(cfg)):
        default = 0.1 if i == 0 else 1.0
        out.append(float(a.get("token_scale", default)))
    return out


def gap_caps(cfg: dict) -> "list[float]":
    out = []
    for i, a in enumerate(axes(cfg)):
        default = 2.5 if i == 0 else 2.0
        out.append(float(a.get("gap_cap", default)))
    return out


# ------------------------------------------------------------ basis generation
def _term_name(exps: "tuple[int, ...]", names: "list[str]") -> str:
    parts = []
    for e, nm in zip(exps, names):
        if e == 1:
            parts.append(f"d{nm}")
        elif e > 1:
            parts.append(f"d{nm}{e}")
    return "".join(parts) or "1"


def expand_terms(cfg: dict, seen_levels: "list[int] | None" = None):
    """Generate the polynomial basis (excluding the constant) from the axis
    orders. Returns ``(exps, names, dropped)`` where ``exps`` is a list of
    per-axis exponent tuples.

    Rule (reproduces both reference bases exactly):
      - pure-axis terms:  exponent 1..order on each axis independently;
      - cross terms:      every mix of >=2 axes with total degree
        <= ``base.cross_max_degree`` (default 3) and each exponent within
        its axis order -- unless ``base.cross_terms`` is false.

    Verified: with V.order=3, RC.order=2 this yields exactly
    [dv, dv2, dv3, drc, drc2, dvdrc, dv2drc, dvdrc2]; with V.order=3, T.order=4
    it yields [dv, dv2, dv3, dt, dt2, dt3, dt4, dvdt, dv2dt, dvdt2].

    Rank-deficiency guard: if ``seen_levels[a]`` (the number of DISTINCT seen
    coordinate values on axis a) is given, any monomial whose exponent on some
    axis a exceeds ``seen_levels[a] - 1`` is dropped (that axis cannot identify
    that power) -- this is the general form of the "dv4 rank-deficient with 4
    seen V levels" / "drc3 with 3 RC levels" notes. Dropped terms are returned.
    """
    ax = axes(cfg)
    A = len(ax)
    names = [a["name"] for a in ax]
    orders = [int(a["order"]) for a in ax]
    cross = bool(cfg["base"].get("cross_terms", True))
    cross_max = int(cfg["base"].get("cross_max_degree", 3))

    exps: "list[tuple[int, ...]]" = []
    # pure-axis terms, exponent 1..order on each axis independently
    for a in range(A):
        for e in range(1, orders[a] + 1):
            t = [0] * A
            t[a] = e
            exps.append(tuple(t))
    # cross terms: >=2 axes nonzero, total degree <= cross_max
    if cross and A >= 2:
        def rec(a, cur):
            if a == A:
                if sum(1 for e in cur if e > 0) >= 2 and sum(cur) <= cross_max:
                    exps.append(tuple(cur))
                return
            for e in range(0, orders[a] + 1):
                rec(a + 1, cur + [e])
        rec(0, [])
    # Order by TOTAL DEGREE (then lexicographically). This is not cosmetic: the
    # SI feature interpolation (features/si_features.py) selects the FIRST few
    # design-matrix columns by index for its low-anchor linear/quadratic backoff,
    # so the leading columns must be the low-degree terms. The OLS base fit itself
    # is column-order invariant.
    exps = sorted(set(exps), key=lambda t: (sum(t), t))

    dropped = []
    if seen_levels is not None:
        kept = []
        for t in exps:
            if any(t[a] > max(seen_levels[a] - 1, 0) for a in range(A)):
                dropped.append(_term_name(t, names))
            else:
                kept.append(t)
        exps = kept

    return exps, [_term_name(t, names) for t in exps], dropped
