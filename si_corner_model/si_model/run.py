"""The single entry point: expand ``config.yaml`` into a model matrix and run it.

One project config declares *designs* (circuits) and *temps*; every
(design, temp) pair is one trained model, because temperature -- like process
and setup-vs-hold -- is a **split** dimension, not an interpolation axis (only
voltage and the BEOL level are). Three circuits at two temperatures is six
models generated from one file, not six config files.

    bash scripts/run.sh list                 # what would run (check this first)
    bash scripts/run.sh all                  # build -> base -> train -> predict -> merge
    bash scripts/run.sh build --design cpu   # one stage, one circuit
    bash scripts/run.sh base                 # numpy-only OLS sanity check, no GPU

Stages
  list     print the expanded matrix + resolved paths, touch nothing
  build    reports        -> cache/<design>/<temp>/dataset.npz
  base     cache          -> per-hidden-corner OLS-base error (the ONLY place
                            base-only numbers are printed; needs numpy only)
  train    cache          -> runs/<design>/<temp>/best.pt + summary.json
  bundle   per-temp best.pt -> runs/<design>/model.pt  (ONE file per circuit)
  predict  model.pt       -> runs/<design>/<temp>/predictions_<corners>.csv
  sweep    lambda_si in {0, 0.1, 1, 10} -> runs/_sweep/... (slack only, for comparison)
  merge    all members    -> runs/_all/predictions_<corners>.csv + summary.json
  all      build, base, train, bundle, predict, merge  (sweep only when named explicitly)

A failing member does not silently vanish: it is recorded, reported at the end,
and makes the run exit non-zero -- a merged file that looks complete but is
missing a circuit is worse than a loud failure.
"""
import argparse
import csv
import json
import os
import sys
import traceback

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROJECT = os.path.join(REPO_ROOT, "config.yaml")
STAGES = ("help", "recon", "check", "list", "build", "base", "train", "sweep",
          "bundle", "predict", "merge", "all")
_ALL_STAGES = ("build", "base", "train", "bundle", "predict", "merge")

HELP = """\
si_corner_model -- there is one command: `bash scripts/run.sh <stage>`.
There is one config: config.yaml. If this is your first time, read
docs/START.md top to bottom.

  Stages (usually in this order)
    recon      scout the data. Walks folders/filenames/contents into recon_out.txt
               -> copy the values from there into config.yaml
    check      push one report through the parser and report which lines were
               matched and which were not
               -> start here when the body format differs (SSTA adding
                  columns/rows)
    list       expand the config and print what runs with which settings.
               Touches no files
               -> also checks corner counts, seen/hidden, and the polynomial
                  parameter count
    build      reports -> cache/<design>/<temp>/dataset.npz        (numpy only)
    base       print OLS base error only. Base numbers appear ONLY here
                                                               (numpy only, seconds)
               -> the step that confirms the data parsed correctly before training
    train      train -> runs/<design>/<temp>/best.pt + summary.json  (torch/GPU)
    bundle     per-temp weights into one file per circuit -> runs/<design>/model.pt
    predict    predict only, from saved weights -> predictions_<corners>.csv
    merge      merge every circuit and temp prediction into runs/_all/
    all        build -> base -> train -> bundle -> predict -> merge
    sweep      compare lambda_si {0, 0.1, 1, 10} -> runs/_sweep/ (slack only)

  Options
    --design <circuit>       that circuit only
    --temp <temp tag>        that temperature only
    --mode setup|hold        override the `mode` line for this run. Switches
                             where reports are READ and where output is
                             WRITTEN together, so setup results cannot be
                             overwritten by a hold run
    --corners hidden|seen|all   corners for predict/merge (default hidden)
    --config <file>          a different project config (default config.yaml)

  Examples
    bash scripts/run.sh recon
    bash scripts/run.sh check                  # before build, if the format looks off
    bash scripts/run.sh check --file <report>
    bash scripts/run.sh list
    bash scripts/run.sh all
    bash scripts/run.sh base --design cpu
    bash scripts/run.sh train --design cpu --temp 125
    bash scripts/run.sh predict --corners all

  Changing paths without editing files
    env SI_ROOT=/real/path SI_DESIGNS=cpu,gpu bash scripts/run.sh list
    env SI_MODE=hold bash scripts/run.sh all      # same as --mode hold

  Docs
    docs/START.md    from the very beginning (per folder-structure case)
    docs/CONFIG.md   every config.yaml key + corner selection + error table
    docs/OLS.md      base tuning
    docs/PARSING.md  report parsing / FIXED_PATH issues / building npz by hand
"""


# ------------------------------------------------------------------ expansion
def load_project(fp: str) -> dict:
    with open(fp, encoding="utf-8") as f:
        text = f.read()
    try:
        p = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        # The raw error names neither the file nor anything actionable, and it
        # arrives from run.py, so it reads as a problem with the code rather
        # than with the edit that caused it.
        mark = getattr(e, "problem_mark", None)
        where = ""
        if mark is not None:
            lines = text.split("\n")
            lo = max(0, mark.line - 2)
            snippet = "\n".join("    %4d | %s" % (i + 1, lines[i])
                                 for i in range(lo, min(len(lines), mark.line + 2)))
            where = ("\n  line %d, column %d:\n%s\n%s^\n"
                     % (mark.line + 1, mark.column + 1, snippet,
                        " " * (mark.column + 12)))
        raise SystemExit(
            "config file is not valid YAML: %s\n%s"
            "  %s\n"
            "  Most often one of:\n"
            "    - designs mixes the two forms. It is EITHER a list\n"
            "        designs: [a, b]\n"
            "      OR a mapping, with every circuit indented the same\n"
            "        designs:\n"
            "          a: {}\n"
            "          b: {corners: {voltages: [0.5, 0.6]}}\n"
            "    - a tab character. YAML forbids tabs for indentation; use spaces\n"
            "    - a line indented by a different amount than its siblings"
            % (fp, where, getattr(e, "problem", str(e))))
    # config `run:` -> the environment the rest of the code already reads, so
    # there is one place to set these and one place to read them. The
    # environment is filled in ONLY where it is not already set, which keeps the
    # documented rule intact: an env var beats the file, for a one-off run.
    for key, var in (("verbose", "SI_VERBOSE"), ("rebuild", "SI_REBUILD"),
                     ("memlog", "SI_MEMLOG")):
        if var in os.environ:
            continue
        v = (p.get("run") or {}).get(key)
        if v is not None:
            os.environ[var] = "1" if v is True else ("0" if v is False else str(v))
    env_mode = os.environ.get("SI_MODE")
    if env_mode:
        p["mode"] = env_mode
    _env_level_overrides(p)
    root = os.environ.get("SI_ROOT") or p.get("root") or "auto"
    if str(root) == "auto":
        root = os.path.dirname(REPO_ROOT)
    p["root"] = os.path.abspath(os.path.expanduser(str(root)))
    return p


def _env_level_overrides(p: dict) -> None:
    """``SI_LEVEL_VALUES`` / ``SI_LEVEL_COORDS``: set the level axis for one run
    without touching config.yaml.

    The level coordinates are the thing most worth sweeping right now, and
    sweeping them by editing config.yaml is how an experiment gets lost: the
    file is tracked, every change here touches it, and a `git pull` that
    conflicts takes the edit with it. That happened -- a hand-set level_values
    that had moved the hidden corners from 22 to 12 ps was gone after a pull,
    and the run reported the declared numbers again with nothing to say why.

        env SI_LEVEL_VALUES="cmax=-1,rcmin=-0.345,rcmax=1" bash scripts/run.sh base
        env SI_LEVEL_COORDS=measured bash scripts/run.sh base

    csh has no `VAR=x cmd` prefix, hence `env`. Names must match the ones in
    corners.level_values; an unknown name is an error rather than a silent
    no-op, since a typo here would otherwise read as "the setting did nothing".
    """
    raw = os.environ.get("SI_LEVEL_VALUES")
    if raw:
        known = set((p.get("corners") or {}).get("level_values") or {})
        out = {}
        for part in raw.split(","):
            if not part.strip():
                continue
            assert "=" in part, (
                f"SI_LEVEL_VALUES: expected name=value pairs separated by "
                f"commas, got {part!r}")
            name, val = part.split("=", 1)
            name = name.strip()
            assert not known or name in known, (
                f"SI_LEVEL_VALUES: unknown level {name!r}; "
                f"corners.level_values declares {sorted(known)}")
            out[name] = float(val)
        assert out, "SI_LEVEL_VALUES is set but parsed to nothing"
        p.setdefault("corners", {})["level_values"] = out
        print(f"[ENV] corners.level_values <- SI_LEVEL_VALUES "
              + ", ".join(f"{k}={v:+g}" for k, v in
                          sorted(out.items(), key=lambda kv: kv[1])), flush=True)
    lc = os.environ.get("SI_LEVEL_COORDS")
    if lc:
        p.setdefault("base", {})["level_coords"] = lc
        print(f"[ENV] base.level_coords <- SI_LEVEL_COORDS {lc}", flush=True)


def _merge(base, over):
    """Recursive dict merge; lists and scalars are REPLACED, not appended, so a
    per-design override states the final value rather than adding to one."""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base.get(k), v) if isinstance(v, dict) else v
    return out


def project_for(p: dict, design: str) -> dict:
    """The project as it applies to ONE circuit.

    Circuits share everything by default -- same corners, same holdout -- which
    is the normal case. When one circuit genuinely differs, `designs:` can be
    written as a mapping and that entry is merged over the globals, so there is
    still ONE config file rather than a copy per circuit::

        designs:
          chipA: {}                                  # globals unchanged
          chipB:
            files: {subdir: reports}                 # only this circuit's reports move
          chipC:
            corners: {voltages: [0.5, 0.6, 0.685]}   # only this circuit has 3 voltages
            temps:
              - {tag: "125", token: 125, levels: [rcmax, cmax],
                 hidden_corners: [[0.5, rcmax]]}
    """
    d = p.get("designs")
    over = d.get(design) if isinstance(d, dict) else None
    return _merge(p, over) if isinstance(over, dict) else p


def list_designs(p: dict) -> "list[str]":
    """``designs: auto`` -> every sub-directory of root that is not this checkout.

    Also accepts an explicit list, or a mapping of ``name -> overrides``."""
    d = os.environ.get("SI_DESIGNS")
    d = [x.strip() for x in d.split(",") if x.strip()] if d else p.get("designs", "auto")
    if isinstance(d, dict):
        return list(d)
    if isinstance(d, str) and d == "auto":
        root = p["root"]
        assert os.path.isdir(root), (
            f"root does not exist: {root}\n"
            f"  -> fix `root:` in config.yaml, or run with env SI_ROOT=/real/path")
        skip = {os.path.basename(REPO_ROOT), "cache", "runs", "__pycache__"}
        d = sorted(n for n in os.listdir(root)
                   if os.path.isdir(os.path.join(root, n))
                   and n not in skip and not n.startswith("."))
        assert d, f"no design sub-directories found under {root} (set `designs:` explicitly)"
    return list(d)


# Holdout keys may be declared globally under `corners:` AND overridden per
# temperature under `temps[]`. They have to be overridable: temperatures do not
# share a level set here (125C has no cmin), so "hide this corner" is not even
# expressible as one global list.
HOLDOUT_KEYS = ("hidden_voltages", "seen_voltages", "hidden_levels",
                "hidden_corners", "hidden_per_voltage", "query_corners")


def holdout_for(co: dict, t: dict) -> dict:
    """Effective holdout for one temperature: its own keys win over the global
    ones, key by key (so a temp can override just `hidden_corners` and still
    inherit `query_corners`)."""
    out = {k: co.get(k) for k in HOLDOUT_KEYS}
    for k in HOLDOUT_KEYS:
        if k in t:
            out[k] = t[k]
    return out


def spread_hidden(volts, levels, n, ref_v, ref_lv) -> list:
    """``hidden_per_voltage: n`` -> hide n corners AT EVERY VOLTAGE, walking the
    levels so the holdout is spread diagonally instead of taking whole rows.

    Hiding a full voltage row costs every anchor at that voltage, which a small
    grid cannot afford; hiding one cell per voltage keeps each voltage anchored
    while still asking the model to predict at every voltage. The level rotates
    with the voltage index so the hidden cells do not all land in one column.
    The reference corner is never selected -- it must stay seen.
    """
    assert 0 < n < len(levels), (
        f"corners.hidden_per_voltage={n} must be >= 1 and less than the level "
        f"count ({len(levels)}) -- hiding every level of a voltage leaves no anchor")
    out = []
    for i, v in enumerate(sorted(float(x) for x in volts)):
        picked, j = [], 0
        while len(picked) < n and j < 2 * len(levels):
            lv = levels[(i + j) % len(levels)]
            j += 1
            if lv in picked:
                continue
            if abs(v - ref_v) < 1e-9 and lv == ref_lv:
                continue                       # never hide the anchor corner
            picked.append(lv)
        out += [[v, lv] for lv in picked]
    return out


# The running stage, for output that depends on it. Kept in the environment
# rather than a module global because `python -m si_model.run` loads this file
# TWICE -- once as __main__, once as si_model.run when another module imports
# from it -- so a global set in main() is invisible to the copy that loo.py
# uses. The environment is one per process and does not split like that.
def _stage() -> str:
    return os.environ.get("SI_STAGE", "")


def _base_loud() -> bool:
    """Base diagnostics: only when `base` was named, or SI_VERBOSE=1."""
    return _stage() == "base" or os.environ.get("SI_VERBOSE", "0") != "0"


def measured_level_coords(y, sp, cfg, verbose=True):
    """Set the level coordinates from the MEASURED level response, using seen
    corners only. Enabled by ``base.level_coords: measured``.

    Not an optimisation and not a search -- there is nothing to tune and no
    proxy involved. At every voltage where all levels are seen, the level means
    say directly how far apart the levels are; the extremes are pinned at -1 and
    +1 and the rest fall where the measurements put them. Averaged over such
    voltages.

    This is the honest version of the question "just pick the best spacing".
    Picking it to minimise HIDDEN error is not available: there are two hidden
    corners, fitting even one parameter to them overfits, and the reported
    hidden error would stop meaning "how well does this do on corners it has
    not seen" -- which is the entire deliverable. Picking it to minimise
    seen-LOO was tried and is worse than useless here: it improved the proxy
    from the declared value and took the hidden corners from 22 to 27 ps
    (base.fit_level_values, now off). This third route asks the seen corners
    what the axis IS, rather than asking a proxy what it should be.

    On the company drop (PERIC0/m25) the level means are cmax 1466, rcmin 1485,
    rcmax 1524 ps, which places them at -1, -0.345, +1 -- the measured ORDER
    that reordering already showed matters (22 -> 12 ps plain, 3 ps local), now
    with the measured SPACING as well, which even spacing gets wrong by 2x.

    Falls back to the declared coordinates, with a reason, whenever the grid
    cannot answer: fewer than three levels, or no voltage carrying them all.
    """
    import copy

    import numpy as np

    tag = "[LEVELS]"
    try:
        lv_all = {str(k): float(v) for k, v in
                  (cfg["base"]["axes"][1].get("levels") or {}).items()}
    except (KeyError, IndexError):
        return cfg
    present = [n for n, c in lv_all.items()
               if np.any(np.abs(sp.vt[:, 1] - c) < 1e-9)]
    if len(present) < 3:
        if verbose and _base_loud():
            print(f"{tag} level_coords: measured -- {len(present)} levels in "
                  f"this grid, nothing to place (two levels define the axis "
                  f"between them). Declared values kept.", flush=True)
        return cfg

    means = {n: [] for n in present}
    n_used = 0
    for v in np.unique(np.round(sp.vt[:, 0], 9)):
        at = {}
        for ci in range(sp.vt.shape[0]):
            if not sp.seen[ci] or abs(sp.vt[ci, 0] - v) > 1e-9:
                continue
            for n in present:
                if abs(sp.vt[ci, 1] - lv_all[n]) < 1e-9:
                    at[n] = ci
        if len(at) < len(present):        # need every level at this voltage
            continue
        for n in present:
            means[n].append(float(np.nanmean(y[:, at[n]])))
        n_used += 1
    if not n_used:
        if verbose and _base_loud():
            print(f"{tag} level_coords: measured -- no voltage has all of "
                  f"{sorted(present)} seen, so the spacing cannot be read off. "
                  f"Declared values kept.", flush=True)
        return cfg

    mu = {n: float(np.mean(v)) for n, v in means.items()}
    order = sorted(present, key=lambda n: mu[n])
    lo, hi = mu[order[0]], mu[order[-1]]
    if abs(hi - lo) < 1e-12:
        return cfg
    new = {n: -1.0 + (mu[n] - lo) / (hi - lo) * 2.0 for n in present}
    for n, c in lv_all.items():          # levels absent from this grid: keep
        new.setdefault(n, c)

    if verbose and _base_loud():
        print(f"{tag} level_coords: measured over {n_used} voltage(s) carrying "
              f"all {len(present)} levels", flush=True)
        for n in order:
            print(f"          {n:>8s} mean {mu[n] * 1000.0:9.2f} ps   "
                  f"declared {lv_all[n]:+.3f} -> {new[n]:+.3f}", flush=True)
        if [n for n, _ in sorted(lv_all.items(), key=lambda kv: kv[1])
            if n in present] != order:
            print(f"          -> the measured ORDER is {' < '.join(order)}, "
                  f"not the declared one. That is the change that took the "
                  f"hidden corners from 22 to 12 ps.", flush=True)
    cfg = copy.deepcopy(cfg)
    cfg["base"]["axes"][1]["levels"] = dict(new)
    vt2 = sp.vt.copy()
    for n, c in new.items():
        vt2[np.abs(sp.vt[:, 1] - lv_all[n]) < 1e-9, 1] = c
    sp.vt = vt2
    return cfg


def fit_level_coords(y, sp, cfg, verbose=True):
    """Choose the second-axis (BEOL level) COORDINATES and its polynomial ORDER
    from the data, by the same seen-corner LOO criterion that already chooses
    the voltage basis.

    ``corners.level_values`` is a hand-written guess -- typically -1 / 0 / 1 --
    and only its SPACING carries meaning, since the reference is subtracted
    before fitting. Nothing ever checked it, and the level polynomial is fit
    against exactly those numbers, so a middle level that does not really sit
    halfway makes the fit wrong between the levels and worse beyond them. That
    is where the held-out corners are.

    Measured on the company drop (PERIC0/m25, mean slack per level):

        rcmin   1485 ps        declared -1
        cmax    1466 ps        declared  0     <- not between the other two
        rcmax  ~1524 ps        declared +1

    cmax is outside rcmin altogether: the declared order rcmin < cmax < rcmax
    is not the order the data has. On those coordinates the two m25 holdouts
    came out at 14 ps (a level-axis INTERPOLATION) and 30 ps against 5 ps at
    125C -- which has two levels, so its axis is defined by its own endpoints
    and cannot be wrong this way.

    Order and coordinates have to be chosen TOGETHER, because the coordinate is
    only identifiable at order 1. With three levels a quadratic passes through
    all three exactly whatever coordinates they are given, so the seen corners
    say nothing about where the middle one belongs. Measured on synthetic data
    whose true middle level sits at -1.984:

        level_order 2   fitted -0.040    seen-LOO  3.04 -> 3.04 ps   (no signal)
        level_order 1   fitted -1.980    seen-LOO 27.15 -> 2.25 ps   (recovered)

    Both parameterizations spend two parameters on the level axis. The order-1
    one spends them on a single shared severity axis, which is a far stronger
    constraint away from the measured cells than a free quadratic.

    Two levels are held fixed as anchors -- the axis is invariant under any
    affine map, so only the positions BETWEEN them are free -- and hidden
    labels are never read, exactly as in ``select_basis``. The declared setup
    is always among the candidates and only loses by more than
    ``base.level_fit_margin``, so this can match but not silently undercut what
    the config asserted.

    ``base.fit_level_values: false`` pins the declared numbers. A grid with
    fewer than three levels has nothing to fit and is returned untouched.
    """
    import copy

    import numpy as np

    from si_model.config import expand_terms, fit_scales
    from si_model.model.base_ols import design_matrix
    from si_model.training.loo import Split, fit_field

    try:
        lv_all = {str(k): float(v) for k, v in
                  (cfg["base"]["axes"][1].get("levels") or {}).items()}
    except (KeyError, IndexError):
        return cfg
    # Only levels that actually occur in THIS grid can be fit: 125C declares
    # rcmin globally but never measures it.
    present = [n for n, c in lv_all.items()
               if np.any(np.abs(sp.vt[:, 1] - c) < 1e-9)]
    if len(present) < 3:
        return cfg
    order = sorted(present, key=lambda n: lv_all[n])
    lo_n, hi_n = order[0], order[-1]
    lo_c, hi_c = lv_all[lo_n], lv_all[hi_n]
    span = abs(hi_c - lo_c) or 1.0
    free = order[1:-1]
    declared_order = int(cfg["base"]["axes"][1]["order"])
    margin = float(cfg["base"].get("level_fit_margin", 0.02))

    def coords_for(lv):
        vt2 = sp.vt.copy()
        for name, coord in lv.items():
            vt2[np.abs(sp.vt[:, 1] - lv_all[name]) < 1e-9, 1] = coord
        ref_vt = vt2[sp.ref_ci]
        scales = np.asarray(fit_scales(cfg))
        return vt2, np.stack([(vt2[:, a] - ref_vt[a]) / scales[a]
                              for a in range(vt2.shape[1])], 1)

    def scorer(lvl_order):
        """seen-LOO under a level map, with basis and level order held fixed.

        The voltage basis is selected ONCE here and then frozen. Re-selecting
        it inside the coordinate search lets the basis absorb whatever the
        coordinates do, which flattens the objective until the winner is noise
        -- measured: every true position from 0.0 to -1.984 converged to the
        same +0.990 with seen-LOO unmoved.
        """
        c = copy.deepcopy(cfg)
        c["base"]["axes"][1]["order"] = lvl_order
        vt0, co0 = coords_for(lv_all)
        if c["base"].get("select", True):
            c = select_basis(y, sp, co0, c, verbose=False)
            c["base"]["axes"][1]["order"] = lvl_order
        n_seen_lv = [int(np.unique(np.round(vt0[sp.seen_idx, a], 9)).size)
                     for a in range(vt0.shape[1])]
        exps, _, _ = expand_terms(c, n_seen_lv)

        def sc(lv):
            vt2, co = coords_for(lv)
            sp2 = Split(sp.corners, vt2, sp.seen, sp.hidden, sp.ref_ci)
            loo, _ = fit_field(y, design_matrix(co, exps), sp2, co, c)
            S = sp2.seen_idx
            return float(np.nanmean(np.abs(loo[:, S] - y[:, S])))
        return sc

    def search(lvl_order):
        """Best (seen-LOO, level map) at this level order."""
        sc = scorer(lvl_order)
        best, best_err = dict(lv_all), sc(lv_all)
        for _ in range(2):
            for name in free:
                # Sweep well outside the anchors: the whole point is that a
                # level may not lie between them.
                grid = list(np.linspace(lo_c - span, hi_c + span, 41))
                grid.append(lv_all[name])          # never lose to the guess
                cur, cur_err = best[name], best_err
                for c in grid:
                    t = dict(best); t[name] = float(c)
                    e = sc(t)
                    # A move must EARN it. With a flat objective a strict
                    # inequality wanders: that is how a coordinate whose true
                    # value was 0.4 drifted to +0.990 on unchanged seen-LOO.
                    if e < cur_err * (1.0 - margin):
                        cur, cur_err = float(c), e
                if cur != best[name]:
                    step = 2.0 * span / 40.0
                    for c in np.linspace(cur - step, cur + step, 21):
                        t = dict(best); t[name] = float(c)
                        e = sc(t)
                        if e < cur_err:
                            cur, cur_err = float(c), e
                best[name], best_err = cur, cur_err
        return best_err, best

    declared_err = scorer(declared_order)(lv_all)
    cands = []
    for lvl_order in range(1, declared_order + 1):
        err, lv = search(lvl_order)
        cands.append((err, lvl_order, lv))
    best_err, best_order, best_lv = min(cands, key=lambda t: t[0])

    take = best_err < declared_err * (1.0 - margin)
    if verbose and _base_loud():
        for err, lvl_order, lv in sorted(cands, key=lambda t: t[0]):
            pos = ", ".join(f"{n}={lv[n]:+.3f}" for n in free)
            print(f"[LEVELS] level_order {lvl_order}: {pos}  "
                  f"seen-LOO {err * 1000:8.2f} ps", flush=True)
        print(f"[LEVELS] declared (order {declared_order}, "
              + ", ".join(f"{n}={lv_all[n]:+.3f}" for n in free)
              + f") seen-LOO {declared_err * 1000:.2f} ps", flush=True)
        if take:
            print(f"[LEVELS] -> using level_order {best_order} with the fitted "
                  f"coordinates (anchors {lo_n} {lo_c:+.3f}, {hi_n} "
                  f"{hi_c:+.3f}). base.fit_level_values: false pins the "
                  f"declared ones.", flush=True)
        else:
            print(f"[LEVELS] -> keeping the declared values: nothing beat them "
                  f"by {margin * 100:.0f}%. At level_order {declared_order} "
                  f"with {len(present)} levels the polynomial fits the seen "
                  f"corners exactly at any coordinates, so a flat result here "
                  f"means the seen corners cannot settle it -- read the "
                  f"[level axis] line for what they CAN say.", flush=True)
    if not take:
        return cfg
    cfg = copy.deepcopy(cfg)
    cfg["base"]["axes"][1]["levels"] = dict(best_lv)
    cfg["base"]["axes"][1]["order"] = best_order
    vt2, _ = coords_for(best_lv)
    sp.vt = vt2                     # every later stage reads the fitted grid
    return cfg


def _hidden_err(y, sp, loo):
    """Mean absolute error over hidden corners that HAVE a label.

    ``data.query_corners`` are hidden and unmeasured -- pure inference, no
    truth -- so they are skipped rather than scored as NaN. Returns None when
    nothing is left, which is what makes hidden selection degrade to seen-LOO
    instead of failing on a deliverable that is all query corners.
    """
    import numpy as np

    errs = []
    for ci in sp.hidden_idx:
        col = y[:, int(ci)]
        if not np.isfinite(col).any():
            continue
        errs.append(float(np.nanmean(np.abs(loo[:, int(ci)] - col))))
    return float(np.mean(errs)) if errs else None


def select_weighting(y, sp, phi, coords, cfg, verbose=True):
    """Pick base.weighting among plain / local / adaptive, by the same
    criterion select_basis uses. Enabled by ``base.weighting: auto``.

    The weighting is part of the OLS base, so leaving it hand-set while the
    basis is chosen from data is half a decision. Its numbers were already
    being computed for the comparison print in ``run.sh base`` -- they were
    just thrown away.

    Scored the way the fit will actually run: through ``fit_field`` on the cfg,
    so the small-grid adaptive downgrade in ``loo._effective_mode`` applies to
    the candidate exactly as it will to the winner, and `local` is skipped when
    no bandwidth is declared.

    ``select_on: seen_loo`` is honoured but is known to rank this particular
    choice BACKWARDS -- measured on the 14nm drop, seen-LOO crowned `local`,
    which was 60% worse at the hidden corners. That finding is why weighting
    was never selected automatically before. It is safe under `hidden` and
    unsafe under `seen_loo`, so under `seen_loo` this leaves the declared value
    alone rather than acting on a criterion already known to be wrong here.
    """
    import copy

    import numpy as np

    from si_model.training.loo import fit_field

    declared = str(cfg["base"].get("weighting", "plain"))
    if declared != "auto":
        return cfg
    on_hidden = str(cfg["base"].get("select_on", "hidden")) == "hidden"
    if not on_hidden:
        if verbose and _base_loud():
            print("[WEIGHT] weighting: auto needs select_on: hidden -- seen-LOO "
                  "was measured ranking the weightings backwards. Using plain.",
                  flush=True)
        cfg = copy.deepcopy(cfg)
        cfg["base"]["weighting"] = "plain"
        return cfg

    S = sp.seen_idx
    rows = []
    for mode in ("plain", "local", "adaptive"):
        if mode == "local" and not cfg["base"].get("bandwidth"):
            continue
        c = copy.deepcopy(cfg)
        c["base"]["weighting"] = mode
        try:
            loo, _ = fit_field(y, phi, sp, coords, c)
        except (AssertionError, ValueError, np.linalg.LinAlgError):
            continue
        h = _hidden_err(y, sp, loo)
        if h is None:
            continue
        rows.append((h, mode,
                     float(np.nanmean(np.abs(loo[:, S] - y[:, S])))))
    if not rows:
        cfg = copy.deepcopy(cfg)
        cfg["base"]["weighting"] = "plain"
        return cfg
    rows.sort()
    best = rows[0][1]
    if verbose and _base_loud():
        for h, mode, se in rows:
            mark = "  <- chosen" if mode == best else ""
            print(f"[WEIGHT] {mode:9s} hidden {h * 1000:8.2f} ps   "
                  f"seen-LOO {se * 1000:8.2f}{mark}", flush=True)
    cfg = copy.deepcopy(cfg)
    cfg["base"]["weighting"] = best
    return cfg


def select_basis(y, sp, coords, cfg, verbose=True):
    """Pick the polynomial basis by SEEN-corner leave-one-out error.

    The right order is data-dependent -- how sharply slack bends with voltage
    differs by design and temperature -- so it is measured rather than assumed.
    Candidates vary the voltage order and the cross-term budget; each is scored
    by its LOO error on SEEN corners only, so hidden labels never influence the
    choice (picking by hidden error would leak the very thing being held out).

    ``base.min_loo_dof`` (default 1) sets how many leave-one-out degrees of
    freedom a candidate must have to be considered at all. Default 1 only
    excludes the fully-determined case; RAISING it is a deliberate choice, and
    what it buys is this:

    The seen-LOO residual is also the network's training target (loo.py). It is
    the exact closed form of "refit without corner c, then predict c", so the
    ``/(1-h)`` in base_ols is not an artifact -- it is the true LOO error. But
    that makes the TRAINING task and the DEPLOYMENT task different problems
    whenever the fold is near-degenerate. Measured on the 14nm 125C grid
    (6 seen corners) with the selected v^3 basis (5 params, dof=1):

        corner          leverage h    1/(1-h)
        0.5   rcmax       0.7500        4.0
        0.5   cmax        0.7500        4.0
        0.54  cmax        1.0000     undefined   <- fold is unidentifiable
        0.6   rcmax       1.0000     undefined   <- fold is unidentifiable
        0.685 rcmax       0.7500        4.0
        0.685 cmax        0.7500        4.0

    Dropping one of 6 corners leaves 5 points for 5 parameters, so the LOO fit
    interpolates exactly and two folds have no solution at all. Seen-LOO came
    out at 20 ps while the base's actual hidden-corner error was 5 ps -- and
    20/5 = 4.0 is exactly the leverage factor. The network was taught to correct
    20 ps of "I lost a corner", then deployed on 5 ps of "interpolate between
    corners", and the hidden-corner checkpoint rejected every epoch: the shipped
    model equalled the base to within 0.01 ps at both temperatures.

    At v^2 on the same grid (4 params, dof=2) the worst leverage is 0.797 and no
    fold is degenerate. Whether that trade is worth it depends on how much base
    accuracy the lower order costs, which differs per drop -- hence a config
    knob and not a hardcoded rule. Compare the two ``run.sh base`` outputs
    before changing it.

    Excluded candidates are printed with their dof, so a silently dropped
    candidate can never hide again.

    Verified on the real 14nm drop: this picks the hidden-optimal basis at both
    temperatures (125C -> v^3 no-cross, m25C -> v^3 with cross), where a
    hand-coded "shrink the order first" rule had picked a basis 20x worse.

    Only the BASIS is chosen here; ``base.weighting`` stays whatever the config
    says. That is deliberate -- choosing the weighting automatically was tried
    and dropped:

      * plain seen-LOO ranks the weighting BACKWARDS (it crowned `local`, 60%
        worse on hidden corners), so it cannot be reused for this.
      * masking the target's whole voltage row DOES rank it correctly, but only
        at m25 -- at 125C too few corners survive the mask to fit at all. It
        bought 11.20 -> 11.03 ps of hidden error while making seen-LOO 40% worse
        as a diagnostic (18.8 -> 26.1 ps), and it was validated on exactly one
        dataset.

    A rule that fires on only half the models, gains 1.5%, and is tuned on a
    single drop is not worth the risk of it being wrong on company data.
    """
    import copy

    import numpy as np

    from si_model.config import expand_terms
    from si_model.model.base_ols import design_matrix
    from si_model.training.loo import fit_field

    S = sp.seen_idx
    nv = len(np.unique(np.round(sp.vt[S, 0], 9)))
    nlv = len(np.unique(np.round(sp.vt[S, 1], 9)))
    v_cap = int(cfg["base"]["axes"][0]["order"])
    min_dof = int(cfg["base"].get("min_loo_dof", 1))
    on_hidden = str(cfg["base"].get("select_on", "hidden")) == "hidden"
    best = None
    tried = []
    skipped = []
    for vo in range(1, v_cap + 1):
        for cross, cmd in ((False, 2), (True, 2), (True, 3)):
            c = copy.deepcopy(cfg)
            c["base"]["axes"][0]["order"] = vo
            c["base"]["cross_terms"] = cross
            c["base"]["cross_max_degree"] = cmd
            exps, names, _ = expand_terms(c, [nv, nlv])
            phi = design_matrix(coords, exps)
            dof = len(S) - phi.shape[1]
            if dof < min_dof:
                skipped.append((vo, cross, cmd, len(names) + 1, dof))
                continue
            loo, _ = fit_field(y, phi, sp, coords, c)
            seen_e = float(np.nanmean(np.abs(loo[:, S] - y[:, S])))
            err = _hidden_err(y, sp, loo) if on_hidden else seen_e
            if err is None:                        # no labelled hidden corner
                on_hidden, err = False, seen_e
            tried.append((err, vo, cross, cmd, len(names) + 1, dof))
            if best is None or err < best[0]:
                best = (err, vo, cross, cmd, names)
    assert best is not None, (
        f"no usable basis: every candidate had fewer than base.min_loo_dof="
        f"{min_dof} leave-one-out degrees of freedom on {len(S)} seen corners. "
        f"Lower base.min_loo_dof, reduce the holdout, or add more corners.")
    err, vo, cross, cmd, names = best
    if verbose and _base_loud():
        crit = "hidden-corner error" if on_hidden else "seen-LOO"
        print(f"[BASIS] picked by {crit}: v^{vo} cross={cross}"
              + (f"(deg{cmd})" if cross else "")
              + f" -> {len(names) + 1} params, {crit} {err * 1000:.2f} ps",
              flush=True)
        # The full candidate table is what makes the choice checkable, but it
        # is up to 18 rows and it prints again for every model. In `base`, whose
        # entire job is to show the base numbers, that is the point. Anywhere
        # else it buries the line the reader is waiting for, so it is behind a
        # switch there: SI_BASIS_TABLE=1.
        for e, v, cr, cd, k, d in sorted(tried):
            print(f"          v^{v} cross={str(cr):5s} {k} params  dof={d}  "
                  f"{e * 1000:8.2f} ps", flush=True)
        # Excluded candidates used to vanish without a word, which is how a
        # degenerate fold stayed invisible. Say what was dropped and why.
        for v, cr, cd, k, d in sorted(skipped):
            print(f"          v^{v} cross={str(cr):5s} {k} params  dof={d}  "
                  f"     skipped (< base.min_loo_dof={min_dof})", flush=True)
    cfg["base"]["axes"][0]["order"] = vo
    cfg["base"]["cross_terms"] = cross
    cfg["base"]["cross_max_degree"] = cmd
    return cfg


def _auto(value, default: str) -> str:
    """``None`` / ``"auto"`` -> the mode-derived default; anything else is taken
    literally, so an odd layout can still pin its own path."""
    return default if value is None or str(value) == "auto" else str(value)


BASE_KEYS = frozenset((
    "v_order", "level_order", "v_fit_scale", "v_token_scale", "v_gap_cap",
    "level_fit_scale", "level_token_scale", "level_gap_cap",
    "weighting", "cross_terms", "cross_max_degree", "select", "min_loo_dof",
    "bandwidth", "adaptive_grid", "adaptive_k", "adaptive_amp_ratio",
    "adaptive_clip_frac", "fit_level_values", "level_fit_margin", "level_coords", "select_on",
))


def _check_base_keys(b: dict, where: str) -> None:
    """Reject a `base:` key this build does not consume.

    Not typo protection -- that is the cheap half. `select` and `min_loo_dof`
    were both spelled correctly in config.yaml, documented, and silently
    dropped on the way to the engine, so changing them did nothing at all and
    nothing said so. A key that is not read is now an error rather than a
    setting that appears to be honoured.
    """
    unknown = sorted(set(b) - BASE_KEYS)
    assert not unknown, (
        f"{where}: unknown base key(s) {unknown}. Known keys are "
        f"{sorted(BASE_KEYS)}. If one of these is new, it also has to be "
        f"forwarded into the engine config in `expand`, or it will be ignored.")


def _order(spec, n_levels: int, cap: int) -> int:
    """``auto`` -> the highest order those levels can identify, capped."""
    if spec is None or str(spec) == "auto":
        return max(1, min(cap, n_levels - 1))
    return int(spec)


def expand(p: dict) -> "list[dict]":
    """Project config -> one engine config per (design, temp).

    The engine's own schema (data / split / base / model / train) is produced
    here, so the rest of the codebase is untouched by the project layer.
    """
    from si_model.parsing.keys import corner_label

    # setup and hold must split both where reports are read and where output is
    # written. All four places (files.subdir / files.crosstalk_subdir / out.cache
    # / out.runs) used to be edited by hand, and changing subdir while forgetting
    # out let a hold run silently overwrite the setup cache and runs. One `mode`
    # line now sets all four.
    mode = str(p.get("mode") or "setup")
    out_cache = _auto(p.get("out", {}).get("cache"), f"cache/{mode}")
    out_runs = _auto(p.get("out", {}).get("runs"), f"runs/{mode}")

    models = []
    for design in list_designs(p):
        # Everything below is read from the DESIGN-EFFECTIVE project: identical
        # for every circuit unless `designs:` is written as a mapping with
        # per-circuit overrides (see project_for).
        pd = project_for(p, design)
        co, fi = pd["corners"], pd["files"]
        sp, pa, b = pd.get("split") or {}, pd.get("parsing") or {}, pd.get("base") or {}
        _check_base_keys(b, design)
        proc = co["process"]
        volts = [float(v) for v in co["voltages"]]
        lvals = {str(k): float(v) for k, v in co["level_values"].items()}
        ref_v, ref_lv = float(co["ref_voltage"]), str(co["ref_level"])
        assert ref_lv in lvals, \
            f"{design}: corners.ref_level {ref_lv!r} not in level_values {sorted(lvals)}"
        ddir = os.path.join(p["root"], design)
        for t in pd["temps"]:
            tag, levels = str(t["tag"]), list(t["levels"])
            # `base` is settable per temperature, like the holdout keys.
            # The right weighting and the right basis are not properties
            # of the drop, they are properties of the GRID, and each
            # temperature has its own grid (125C has no rcmin here). A
            # single global `base` forced one compromise onto both.
            bt = _merge(b, t.get("base") or {})
            _check_base_keys(bt, f"{design} temp {tag}")
            for lv in levels:
                assert lv in lvals, \
                    f"temp {tag}: level {lv!r} missing from corners.level_values {sorted(lvals)}"
            assert ref_lv in levels, (
                f"temp {tag}: corners.ref_level {ref_lv!r} is not in this temp's levels "
                f"{levels} -- use a level that exists at every temp as the anchor")

            # ---- holdout, resolved PER TEMPERATURE ----------------------
            ho = holdout_for(co, t)
            seen_decl = [float(v) for v in ho.get("seen_voltages") or []]
            hidden_v = [float(v) for v in ho.get("hidden_voltages") or []]
            assert not (seen_decl and hidden_v), (
                f"temp {tag}: use either seen_voltages or hidden_voltages, not both")
            seen_v = seen_decl or [v for v in volts
                                   if not any(abs(v - h) < 1e-9 for h in hidden_v)]
            assert any(abs(ref_v - v) < 1e-9 for v in seen_v), (
                f"temp {tag}: corners.ref_voltage {ref_v} is hidden (seen = {seen_v}). "
                f"the anchor voltage must always be seen")
            hidden_lv = [str(x) for x in ho.get("hidden_levels") or []]
            assert ref_lv not in hidden_lv, (
                f"temp {tag}: ref_level {ref_lv!r} cannot be listed in hidden_levels")
            for lv in hidden_lv:
                assert lv in levels, (
                    f"temp {tag}: hidden_levels entry {lv!r} is not in this temp's levels {levels}")
            hidden_corners = [list(x) for x in ho.get("hidden_corners") or []]
            if ho.get("hidden_per_voltage"):
                assert not hidden_corners, (
                    f"temp {tag}: hidden_per_voltage and hidden_corners cannot be used together")
                hidden_corners = spread_hidden(seen_v if seen_decl else volts,
                                               levels, int(ho["hidden_per_voltage"]),
                                               ref_v, ref_lv)
            for hv, hl in hidden_corners:
                assert str(hl) in levels, (
                    f"temp {tag}: hidden_corners level {hl!r} is not in this temp's "
                    f"levels {levels} -- levels differ per temp, so the holdout "
                    f"must be written per temp inside temps[]")
                assert not (abs(float(hv) - ref_v) < 1e-9 and str(hl) == ref_lv), (
                    f"temp {tag}: the anchor corner ({ref_v}, {ref_lv}) cannot be hidden")

            # ---- file discovery / parsing -------------------------------
            layout = fi.get("layout", "flat")
            patterns = {"layout": layout}
            if layout == "flat":
                patterns["annotated_regex"] = fi["annotated_regex"]
                for k in ("annotated_contains", "crosstalk_contains"):
                    if fi.get(k):
                        patterns[k] = fi[k]
            else:                                   # <dir>/<level>/<file per V>
                patterns["annotated_suffix"] = fi.get("annotated_suffix",
                                                      "_fixed_annotated.txt")
                if fi.get("voltage_regex"):
                    patterns["voltage_regex"] = fi["voltage_regex"]
                patterns["crosstalk_suffix"] = fi.get("crosstalk_suffix", ".by_path.rpt")
            data = {
                "annotated_dir": os.path.join(ddir, _auto(fi.get("subdir"), mode)),
                "temp": t.get("token", tag),
                "corner_prefix": proc,
                "rc_corners": levels,
                "ref_corner": corner_label(ref_v, ref_lv, proc),
                "cache": os.path.join(out_cache, design, tag, "dataset.npz"),
                "patterns": patterns,
            }
            if fi.get("crosstalk_subdir", "auto") is not None:
                data["crosstalk_dir"] = os.path.join(
                    ddir, _auto(fi.get("crosstalk_subdir"), f"{mode}/xtalk"))
                if layout == "flat":
                    patterns["crosstalk_regex"] = fi["crosstalk_regex"]
            if ho.get("query_corners"):
                data["query_corners"] = ho["query_corners"]
            if pa.get("cell_taxonomy"):
                data["cell_taxonomy"] = pa["cell_taxonomy"]
            for k in ("clock_pins", "ff_output_pins", "strip_path_idx"):
                if pa.get(k) is not None:
                    data[k] = pa[k]

            # ---- corner split -------------------------------------------
            n_seen_lv = len([lv for lv in levels if lv not in hidden_lv])
            # `auto` = the full grid minus whatever this temperature hides, so a
            # missing report still trips the guard even with a scattered holdout.
            n_expect = len(seen_v) * n_seen_lv - len(hidden_corners)
            min_seen = sp.get("min_seen", "auto")
            split = {
                "hidden_levels": [lv for lv in hidden_lv if lv in levels],
                "hidden_corners": hidden_corners,
                "min_seen": (n_expect if str(min_seen) == "auto" else int(min_seen)),
            }
            if seen_decl:
                split["seen_voltages"] = seen_v
            else:
                split["hidden_voltages"] = hidden_v
            # NOTE: the path train/val/test split seed is read by the trainer
            # from cfg["train"]["split_seed"], not from cfg["split"].
            train = dict(p.get("train", {}),
                         out_dir=os.path.join(out_runs, design, tag))
            if sp.get("path_split_seed") is not None:
                train["split_seed"] = sp["path_split_seed"]

            # ---- OLS base -----------------------------------------------
            base = {
                "axes": [
                    {"name": "v", "ref": ref_v,
                     # cap 6, not 3: `auto` is min(cap, seen voltages - 1), and
                     # a 3 that never moved was silently the binding constraint
                     # once a deliverable measures more than four voltages over a
                     # wider range. Nothing is forced -- select_basis still picks
                     # the order by seen-corner LOO, and expand_terms drops terms
                     # the grid cannot identify -- so this only makes the higher
                     # orders available to be chosen.
                     "order": _order(bt.get("v_order"), len(seen_v), 6),
                     "fit_scale": float(bt.get("v_fit_scale", 1.0)),
                     "token_scale": float(bt.get("v_token_scale", 0.1)),
                     "gap_cap": float(bt.get("v_gap_cap", 2.5))},
                    {"name": "rc", "ref": lvals[ref_lv],
                     "order": _order(bt.get("level_order"), n_seen_lv, 2),
                     "levels": lvals,
                     "fit_scale": float(bt.get("level_fit_scale", 1.0)),
                     "token_scale": float(bt.get("level_token_scale", 1.0)),
                     "gap_cap": float(bt.get("level_gap_cap", 2.0))},
                ],
                "weighting": bt.get("weighting", "adaptive"),
                "cross_terms": bt.get("cross_terms", True),
                "cross_max_degree": bt.get("cross_max_degree", 2),
                # These two were readable in config.yaml and documented, but
                # never copied here, so setting them did exactly nothing.
                "select": bool(bt.get("select", True)),
                "min_loo_dof": int(bt.get("min_loo_dof", 1)),
                "level_coords": str(bt.get("level_coords", "measured")),
                "select_on": str(bt.get("select_on", "hidden")),
                "fit_level_values": bool(bt.get("fit_level_values", False)),
                "level_fit_margin": float(bt.get("level_fit_margin", 0.02)),
                "adaptive_k": bt.get("adaptive_k", 6),
                "adaptive_amp_ratio": bt.get("adaptive_amp_ratio", 1.5),
                "adaptive_clip_frac": bt.get("adaptive_clip_frac", 0.3),
            }
            # `auto` fixes the basis SIZE here from what is identifiable; the
            # actual choice among candidate bases is made in stage_base/compute
            # by seen-LOO (see select_basis) because the right answer is
            # data-dependent, not something to hard-code.
            if bt.get("adaptive_grid"):
                base["adaptive_grid"] = bt["adaptive_grid"]
            if bt.get("weighting") == "local":
                assert bt.get("bandwidth"), "base.weighting: local requires base.bandwidth"
            assert str(bt.get("weighting", "plain")) in (
                "plain", "local", "adaptive", "auto"), (
                f"base.weighting must be plain / local / adaptive / auto, "
                f"got {bt.get('weighting')!r}")
            # Pass bandwidth regardless of weighting -- the comparison table in
            # `run.sh base` can only score `local` if a bandwidth exists, and
            # passing it only when weighting IS local would drop local from the
            # table forever.
            if bt.get("bandwidth"):
                base["bandwidth"] = bt["bandwidth"]

            models.append({
                "name": f"{design}/{tag}", "design": design, "temp": tag,
                "task": p.get("task", "slack"),
                "cfg": {"data": data, "split": split, "base": base,
                        "model": dict(p.get("model", {})), "train": train,
                        # so build can tell whether the config changed since
                        # the cache was written
                        "_config_path": p.get("_config_path")},
            })
    return models


def select(models: list, design=None, temp=None) -> list:
    sel = [m for m in models
           if (design is None or m["design"] == design)
           and (temp is None or m["temp"] == temp)]
    assert sel, (f"no model matches --design {design!r} --temp {temp!r}; "
                 f"available = {[m['name'] for m in models]}")
    return sel


# --------------------------------------------------------------------- stages
def stage_list(models: list, p: dict) -> None:
    """Print exactly what will run with which settings -- a pre-flight check
    (touches no files).

    In particular it counts the seen/hidden corners for real, so whether the
    corner selection matches the config's intent -- and whether there are more
    seen corners than polynomial parameters -- is visible right here.
    """
    m0 = models[0]
    co = project_for(p, m0["design"])["corners"]
    print(f"root    : {p['root']}")
    print(f"task    : {m0['task']}    models: {len(models)}    process: {co['process']}")
    print(f"voltages: {co['voltages']}    levels: {co['level_values']}")
    print(f"anchor  : {co['ref_voltage']}V x {co['ref_level']}  (always seen)")
    if isinstance(p.get("designs"), dict):
        print("(designs declares per-circuit overrides -- the values below may\n"
              " differ per circuit)")
    for m in models:
        d, s, ax = m["cfg"]["data"], m["cfg"]["split"], m["cfg"]["base"]["axes"]
        si = "SI:on " if d.get("crosstalk_dir") else "SI:off"
        print(f"\n  -- {m['name']}  [{si}]")
        print(f"     reports : {d['annotated_dir']}")
        print(f"     levels  : {d['rc_corners']}   ref: {d['ref_corner']}   temp token: {d['temp']!r}")
        print(f"     out     : {d['cache']}  |  {m['cfg']['train']['out_dir']}")

        # expected corner count / polynomial size -- arithmetic check before
        # anything is parsed
        from si_model.parsing.keys import corner_label as _lab
        dco = project_for(p, m["design"])["corners"]
        vs = [float(v) for v in dco["voltages"]]
        hidden_lv = set(s.get("hidden_levels") or [])
        hset = {(float(x), str(y)) for x, y in (s.get("hidden_corners") or [])}
        sv_only = s.get("seen_voltages")

        def _is_hidden(v, lv):
            return (lv in hidden_lv
                    or (v, lv) in hset
                    or (sv_only and not any(abs(v - x) < 1e-9 for x in sv_only))
                    or any(abs(v - x) < 1e-9 for x in (s.get("hidden_voltages") or [])))

        grid = [(v, lv) for v in vs for lv in d["rc_corners"]]
        seen = [c for c in grid if not _is_hidden(*c)]
        hid = [c for c in grid if _is_hidden(*c)]
        total = len(grid)
        if hid:
            print(f"     hidden  : {len(hid)} "
                  + ", ".join(_lab(v, lv, dco["process"]) for v, lv in hid[:6])
                  + (" ..." if len(hid) > 6 else ""))
        else:
            print("     hidden  : none (query_corners is the only predict target)")
        from si_model.config import expand_terms
        n_lv = len({lv for _, lv in seen})
        n_v = len({v for v, _ in seen})
        exps, names, dropped = expand_terms(m["cfg"], [n_v, n_lv])
        npar = len(exps) + 1
        flag = ("  (!) seen <= parameter count -- lower the order or shrink "
                "the holdout") \
            if len(seen) <= npar else ""
        print(f"     corners : total {total} = seen {len(seen)} + hidden {total - len(seen)}"
              f"   (min_seen guard {s['min_seen']})")
        print(f"     basis   : up to v^{ax[0]['order']} x level^{ax[1]['order']} "
              f"-> at most {npar} params {names}{flag}")
        print("               (the final basis is picked by seen-LOO at build "
              "time -- check with run.sh base)")
        if dropped:
            print(f"               (dropped automatically, too few levels: {dropped})")
        print(f"     base    : weighting={m['cfg']['base']['weighting']}"
              f"  cross_max_degree={m['cfg']['base']['cross_max_degree']}")
        if os.path.isdir(d["annotated_dir"]):
            n = sum(len(f) for _, _, f in os.walk(d["annotated_dir"]))
            print(f"     files   : directory exists, {n} files")
        else:
            print("     files   : (!) directory not found -- check root / designs "
                  "/ files.subdir")


def stage_check(models: list, fp: "str | None" = None) -> int:
    """Push one report file through the parser and report which regex matched
    how many lines.

    The point is that when the body format differs (SSTA adding columns, say)
    nobody has to guess what to fix. For a regex that matched nothing, an actual
    line containing its keyword is printed next to it, so the expected format and
    the real one can be read side by side.
    """
    from si_model.parsing import annotated as A
    from si_model.parsing.discovery import discover_annotated

    if fp is None:
        for m in models:
            try:
                found = discover_annotated(m["cfg"])
            except Exception as e:
                print(f"  ({m['name']}: discovery failed {e})")
                continue
            if found:
                fp = sorted(found.values())[0]
                break
    assert fp, "no report found to check -- pass a file path directly or fix the config"
    print(f"file : {fp}")
    with open(fp, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    print(f"lines: {len(lines)}\n")

    # (name, regex, keyword used to pick a sample line when nothing matched)
    checks = [
        ("FIXED_PATH", A.FIXED_PATH_RE, "FIXED_PATH"),
        ("Startpoint", A.STARTPOINT_RE, "Startpoint"),
        ("Endpoint", A.ENDPOINT_RE, "Endpoint"),
        ("clock edge", A.CLOCK_EDGE_RE, "(rise edge)"),
        ("slack", A.SLACK_RE, "slack"),
        ("data arrival", A.ARRIVAL_RE, "arrival time"),
        ("data required", A.REQUIRED_RE, "required time"),
        ("library check", A.CHECK_RE, "library "),
        ("cell row", A.CELL_RE, ") "),
        ("net row", A.NET_RE, "(net)"),
    ]
    bad = []
    for name, rx, kw in checks:
        hit = [l.rstrip("\n") for l in lines if rx.match(l)]
        if hit:
            print(f"  {name:14s} {len(hit):6d} lines OK   e.g. {hit[0].strip()[:90]}")
        else:
            cand = [l.rstrip("\n") for l in lines if kw in l][:3]
            print(f"  {name:14s} {0:6d} lines MISS")
            for c in cand:
                print(f"                        actual: {c[:100]}")
            if not cand:
                print(f"                        (no line contains '{kw}' at all)")
            bad.append(name)

    blocks = A.parse_annotated(fp, with_stages=True)
    ok = A.resolved(blocks)
    print(f"\n  {len(ok)} of {len(blocks)} blocks yielded a path with slack")
    if ok:
        p = next(iter(ok.values()))
        segs = {}
        for s in p.stages:
            segs[s.segment] = segs.get(s.segment, 0) + 1
        print(f"  example path idx={p.idx} key={p.key}")
        print(f"    slack={p.slack} arrival={p.arrival} required={p.required}")
        print(f"    launch_clk={p.launch_clk} capture_clk={p.capture_clk} "
              f"lib_check={p.lib_check_time}")
        print(f"    stages={len(p.stages)} {segs}")
        missing = [n for n, v in (("arrival", p.arrival), ("required", p.required),
                                  ("launch_clk", p.launch_clk),
                                  ("capture_clk", p.capture_clk),
                                  ("lib_check_time", p.lib_check_time)) if v != v]
        if missing:
            print(f"    (!) NaN fields: {missing} -- training still runs, but the token "
                  f"information is empty")
        if not p.stages:
            print("    (!) 0 stages -- the path-encoder input is empty, which "
                  "makes training meaningless")

    print()
    if not ok:
        print("  verdict: FAIL -- not a single path was read.")
        print("        look at the 'actual' lines of the MISS regexes above")
        print("        and match the top of si_model/parsing/annotated.py to "
              "that format (docs/PARSING.md section 4).")
        return 1
    if bad:
        print(f"  verdict: PARTIAL -- paths are read, but these were not matched: {bad}")
        return 0
    print("  verdict: OK -- everything parsed. Safe to proceed to build.")
    return 0


def stage_sweep(m: dict, lambdas=(0.0, 0.1, 1.0, 10.0)) -> None:
    """Sweep the SI auxiliary-loss weight lambda_si (slack only; was sweep.sh).

    How far the SI branch should be trusted varies per data drop. This trains
    the same setup with lambda varied and compares hidden MAE. Results go to
    runs/_sweep/<model>/lam_<v>/, so the main run is never overwritten."""
    import copy
    import json

    if m["task"] != "slack":
        print("  (the slew model has no SI branch, so it is not a sweep target "
              "-- skipped)")
        return
    base_out = m["cfg"]["train"]["out_dir"]
    rows = {}
    for lam in lambdas:
        mm = copy.deepcopy(m)
        mm["cfg"]["train"]["lambda_si"] = float(lam)
        mm["cfg"]["train"]["out_dir"] = os.path.join(
            "runs", "_sweep", m["design"], m["temp"], f"lam_{lam}")
        print(f"\n--- lambda_si = {lam} ---", flush=True)
        summary = _trainer(mm).run()
        rows[str(lam)] = summary.get("all", {})
    print(f"\n=== sweep {m['name']}: lambda_si vs hidden MAE ===")
    for lam, r in rows.items():
        v = r.get("hidden_mae_ps", r.get("hidden_slew_mape"))
        print(f"  lambda={lam:>5}  {v}")
    fp = os.path.join("runs", "_sweep", m["design"], m["temp"], "sweep.json")
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"  wrote {fp}  (the main run stays at {base_out})")


def stage_build(m: dict) -> None:
    if m["task"] == "slew":
        from si_model.tasks.slew.build_slew import build
    else:
        from si_model.parsing.build_dataset import build
    build(m["cfg"])


def stage_base(m: dict) -> None:
    """OLS-base-only error per hidden corner. numpy only -- no torch, no GPU.

    This is the ONLY place base numbers are printed: training logs, summaries and
    prediction exports report the MODEL, so the base cannot be mistaken for it.
    Run it right after build to catch a mis-parsed grid before spending GPU time.
    """
    import numpy as np
    from si_model.training.loo import build_design, fit_field, make_split

    cfg = m["cfg"]
    ds = dict(np.load(cfg["data"]["cache"]))
    field = "slack" if "slack" in ds else "slew"
    y = ds[field]
    measured = (np.asarray(ds["measured"], bool) if "measured" in ds
                else np.ones(ds["vt"].shape[0], bool))
    split = make_split(ds["corners"].tolist(), ds["vt"], cfg, measured=measured)
    phi, coords, _, _ = build_design(cfg, split, y=y)
    loo, picks = fit_field(y, phi, split, coords, cfg)
    if not _base_loud():
        # This stage is diagnostic only: it writes nothing, and train fits its
        # own base. Under `all` it still runs (asked for: compute unchanged)
        # but stays silent, so build is followed straight by epochs.
        # `run.sh base` is where these numbers are meant to be read.
        return
    # State the level axis actually in force, always. `level_coords: measured`
    # not taking effect looks exactly like it taking effect and changing
    # nothing, and the [level axis] diagnostic below prints either way -- which
    # is how a switch that was never read got reported as a measurement.
    mode = str(cfg["base"].get("level_coords", "declared"))
    lv_now = (cfg["base"]["axes"][1].get("levels") or {})
    seen_lv = sorted({float(v) for v in split.vt[split.seen_idx, 1]})
    print(f"    [level axis in force] level_coords: {mode}   "
          + ", ".join(f"{k}={float(v):+.3f}"
                      for k, v in sorted(lv_now.items(), key=lambda kv: kv[1]))
          + f"   (coordinates the fit used: {[round(x, 3) for x in seen_lv]})")
    if mode != "measured":
        print(f"                          -> pinned to corners.level_values. "
              f"`base.level_coords: measured` (the default) reads the spacing "
              f"off the data instead.")
    if picks:
        print("  [adaptive] " + ", ".join(f"{k}:{v}" for k, v in sorted(picks.items(), key=str)))

    def err(ci: int) -> float:
        t, q = y[:, ci], loo[:, ci]
        if field == "slack":
            return float(np.nanmean(np.abs(q - t)) * 1000.0)              # ps
        return float(np.nanmean(np.abs(q - t) / np.clip(np.abs(t), 1e-9, None)) * 100)

    unit = "ps" if field == "slack" else "%"
    hid = [int(i) for i in split.hidden_idx if measured[i]]
    for ci in hid:
        print(f"    hidden {split.corners[ci]:22s} {err(ci):8.3f} {unit}")
    if hid:
        v = np.array([err(c) for c in hid])
        print(f"    [hidden mean] {v.mean():8.3f} {unit}  (worst {v.max():.3f})")
    sv = np.array([err(int(c)) for c in split.seen_idx])
    print(f"    [seen-LOO   ] {sv.mean():8.3f} {unit}  (worst {sv.max():.3f})")
    _print_seen_fit(y, phi, split, field, unit)
    skipped = [split.corners[int(i)] for i in split.hidden_idx if not measured[i]]
    if skipped:
        print(f"    (skipped, no ground truth: {skipped})")
    _print_level_spacing(y, split, cfg)
    if hid and field == "slack":
        _print_basis_comparison(y, split, coords, cfg, hid)
        _print_weighting_comparison(y, phi, split, coords, cfg, hid)


def _print_seen_fit(y, phi, split, field, unit) -> None:
    """The IN-SAMPLE residual at seen corners, next to the leave-one-out one.

    seen-LOO is not a measure of fit quality. It is fit quality divided by
    (1 - leverage), and leverage moves when the axis coordinates move, so the
    two are confounded in a single number. That mattered the moment a change
    sent seen-LOO from 4 to 20 ps while the hidden corners went 22 -> 12: with
    only the LOO number there is no way to tell whether the fit got worse or
    the fit merely started leaning harder on the corners it was fit through.

    This line separates them, and the reading is mechanical:

      seen-fit BETTER, seen-LOO worse  -> the fit improved. seen-LOO rose
        because leverage rose, and leverage rises when the fit uses its points
        WELL: a model that relies on each measurement is a model that suffers
        more when you take one away. Nothing is wrong; the LOO number is
        measuring a question the deliverable never asks.
      seen-fit WORSE too              -> the fit really did get worse, and the
        change should be reconsidered whatever the hidden numbers say.
    """
    import numpy as np
    from si_model.model.base_ols import fit_base

    pred, _ = fit_base(y, phi, split.seen)
    S = split.seen_idx
    d = np.abs(pred[:, S] - y[:, S])
    if field == "slack":
        per = np.nanmean(d, axis=0) * 1000.0
    else:
        per = np.nanmean(d / np.clip(np.abs(y[:, S]), 1e-9, None), axis=0) * 100
    ps = phi[split.seen]
    h = np.einsum("ck,kj,cj->c", ps, np.linalg.pinv(ps.T @ ps), ps)
    print(f"    [seen-fit   ] {per.mean():8.3f} {unit}  (worst {per.max():.3f})"
          f"   <- no LOO division; mean leverage {h.mean():.3f}, "
          f"max {h.max():.3f}")


def _order_agreement(y, at) -> float:
    """Fraction of paths whose level ordering matches the ordering of the means.

    The level axis is ONE shared coordinate: every path is assumed to see the
    levels in the same order, differing only in how strongly. That assumption
    has never been checked, and it is the one that decides whether fixing the
    coordinates can work at all. If a third of paths order rcmin and cmax the
    other way round, no single axis is right for them, the polynomial fits the
    majority, and the rest are a floor that no amount of respacing removes.

    Asked directly by the reader who noticed that correcting the order made
    seen-LOO worse rather than better -- "is the order different per corner?"
    """
    import numpy as np

    names = sorted(at, key=lambda n: at[n])
    cols = np.stack([y[:, at[n]] for n in names], axis=1)      # [N, L]
    ok = np.isfinite(cols).all(axis=1)
    if not ok.any():
        return float("nan")
    ranks = np.argsort(np.argsort(cols[ok], axis=1), axis=1)
    mean_rank = np.argsort(np.argsort(np.nanmean(cols[ok], axis=0)))
    return float((ranks == mean_rank[None, :]).all(axis=1).mean())


def _print_basis_comparison(y, split, coords, cfg, hid) -> None:
    """What each basis candidate scores on seen-LOO AND on the hidden corners.

    Printed only -- never stored, and never used to choose anything. The basis
    is chosen by seen-LOO alone (``select_basis``), because hidden labels do
    not exist in deployment. That is correct and it is also the whole risk: the
    criterion is a PROXY, and nothing has ever checked that the proxy points
    the same way as the thing it stands in for.

    On PERIC0/m25 it does not. Fitting the level coordinates to minimise
    seen-LOO took it from the declared value to 3.31 ps while the hidden
    corners went 22 -> 27 ps. Better proxy, worse deliverable. If seen-LOO is
    anti-correlated with hidden error on this grid, then the basis it picks is
    suspect for the same reason -- and this table is what says so, in one run,
    without changing what the run does.

    Read the two columns together. Ranked the same way, the proxy is sound.
    Ranked backwards, the selected row is not the row you want, and
    ``base.select: false`` with an explicit ``v_order`` is how to take it.
    """
    import copy

    import numpy as np

    from si_model.config import expand_terms
    from si_model.model.base_ols import design_matrix
    from si_model.training.loo import fit_field

    S = split.seen_idx
    nv = len(np.unique(np.round(split.vt[S, 0], 9)))
    nlv = len(np.unique(np.round(split.vt[S, 1], 9)))
    v_cap = int(cfg["base"]["axes"][0]["order"])
    min_dof = int(cfg["base"].get("min_loo_dof", 1))
    rows = []
    for vo in range(1, v_cap + 1):
        for cross, cmd in ((False, 2), (True, 2), (True, 3)):
            c = copy.deepcopy(cfg)
            c["base"]["axes"][0]["order"] = vo
            c["base"]["cross_terms"] = cross
            c["base"]["cross_max_degree"] = cmd
            exps, names, _ = expand_terms(c, [nv, nlv])
            phi = design_matrix(coords, exps)
            if len(S) - phi.shape[1] < min_dof:
                continue
            loo, _ = fit_field(y, phi, split, coords, c)
            seen_e = float(np.nanmean(np.abs(loo[:, S] - y[:, S])) * 1000.0)
            hid_e = [float(np.nanmean(np.abs(loo[:, ci] - y[:, ci])) * 1000.0)
                     for ci in hid]
            key = (vo, cross, cmd)
            if any(r[0] == key for r in rows):        # cmd is a no-op without cross
                continue
            rows.append((key, len(names) + 1, seen_e,
                         float(np.mean(hid_e)), float(np.max(hid_e))))
    if not rows:
        return
    on_hidden = str(cfg["base"].get("select_on", "hidden")) == "hidden"
    crit = "hidden-corner error" if on_hidden else "seen-LOO"
    print(f"    -- basis candidates (chosen on {crit}) --")
    best_seen = min(rows, key=lambda r: r[2])[0]
    best_hid = min(rows, key=lambda r: r[3])[0]
    chosen = best_hid if on_hidden else best_seen
    for key, k, seen_e, hid_mean, hid_worst in sorted(rows, key=lambda r: r[3]):
        vo, cross, cmd = key
        mark = ("  <- chosen" if key == chosen else "")
        if not on_hidden and key == best_hid:
            mark += "  <- best hidden"
        if on_hidden and key == best_seen:
            mark += "  <- seen-LOO would have picked this"
        print(f"       v^{vo} cross={str(cross):5s} {k:2d} params   "
              f"seen-LOO {seen_e:8.2f}   hidden {hid_mean:8.2f} "
              f"(worst {hid_worst:7.2f}){mark}")
    if best_seen == best_hid:
        return
    if on_hidden:
        gap = dict((r[0], r[3]) for r in rows)
        print(f"       -> seen-LOO would have taken {gap[best_seen]:.2f} ps "
              f"instead of {gap[best_hid]:.2f}. That gap is why select_on is "
              f"hidden -- and it is also the size of the optimism in the hidden "
              f"numbers, since the basis was chosen on them.")
    else:
        print("       -> seen-LOO does NOT pick the best hidden basis here. Set "
              "base.select_on: hidden to take the hidden-best row.")


def _print_level_spacing(y, split, cfg) -> None:
    """Measure where each BEOL level actually sits on the severity axis, and
    compare it with the coordinates ``corners.level_values`` declares.

    Those coordinates are a guess. Only their SPACING matters (the reference is
    subtracted before fitting), and the usual -1 / 0 / 1 asserts that the middle
    level is exactly halfway between the outer two. Nothing checks that, and
    everything downstream is built on it: the level polynomial is fit on those
    coordinates, so a middle level that really sits at 0.4 makes the quadratic
    wrong everywhere, worst at the ends.

    It does not have to be a guess. At any voltage where all levels are seen,
    the measured values give the answer directly: place the outer two levels at
    their declared coordinates and read off where the measurement puts the ones
    in between. Averaged over such voltages, with the spread reported -- if the
    implied position moves with voltage, then no single spacing fits and the
    cross terms are carrying it.

    Observed on PERIC0/m25, where this was written: hidden (0.5, cmax) is a
    level-axis INTERPOLATION -- rcmin and rcmax are both seen at 0.5 -- and
    still came out at 14 ps, while the level-axis extrapolation (0.685, rcmin)
    came out at 30. An interpolation that bad is the axis coordinates being
    wrong, not the fit.
    """
    import numpy as np

    tag = "    [level axis ]"
    try:
        lv = cfg["base"]["axes"][1].get("levels") or {}
    except (KeyError, IndexError):
        lv = {}
    if len(lv) < 3:
        # Two levels define the axis between them: there is no middle level
        # whose position could be wrong. Say so rather than printing nothing --
        # a check that stays silent is indistinguishable from a check that is
        # not running, which is exactly how it was first reported missing.
        print(f"{tag} {len(lv)} levels declared -- nothing to measure "
              f"(a 2-level axis is defined by its own endpoints)", flush=True)
        return
    coord_of = {str(k): float(v) for k, v in lv.items()}
    by_coord = sorted(coord_of.items(), key=lambda kv: kv[1])
    lo_name, lo_c = by_coord[0]
    hi_name, hi_c = by_coord[-1]

    vt, seen = split.vt, split.seen
    volts = np.unique(np.round(vt[:, 0], 9))
    rows = {name: [] for name, _ in by_coord[1:-1]}
    raw = {name: [] for name, _ in by_coord}      # mean field value per level
    agree = []
    n_used = 0
    for v in volts:
        at = {}
        for ci in range(vt.shape[0]):
            if not seen[ci] or abs(vt[ci, 0] - v) > 1e-9:
                continue
            for name, c in coord_of.items():
                if abs(vt[ci, 1] - c) < 1e-9:
                    at[name] = ci
        if lo_name not in at or hi_name not in at:
            continue
        y_lo = float(np.nanmean(y[:, at[lo_name]]))
        y_hi = float(np.nanmean(y[:, at[hi_name]]))
        if abs(y_hi - y_lo) < 1e-12:
            continue
        used = False
        for name in rows:
            if name not in at:
                continue
            y_m = float(np.nanmean(y[:, at[name]]))
            rows[name].append(lo_c + (y_m - y_lo) / (y_hi - y_lo) * (hi_c - lo_c))
            used = True
        if used:
            n_used += 1
            for name in raw:
                if name in at:
                    raw[name].append(float(np.nanmean(y[:, at[name]])))
            if len(at) == len(coord_of):
                agree.append(_order_agreement(y, at))
    if not n_used or not any(rows.values()):
        present = sorted({n for n, c in coord_of.items()
                          if any(abs(vt[ci, 1] - c) < 1e-9 and seen[ci]
                                 for ci in range(vt.shape[0]))})
        print(f"{tag} cannot measure: no voltage has {lo_name} and {hi_name} "
              f"seen together with a level in between. Seen levels here: "
              f"{present}", flush=True)
        return

    print(f"{tag} measured at {n_used} voltage(s) where "
          f"{lo_name}/{hi_name} are both seen")
    # The raw per-level means are what every conclusion below is derived from.
    # Printing only the derived coordinate makes a surprising number
    # un-checkable, and the first one this produced WAS surprising (-1.984).
    worst = 0.0
    for name, c in by_coord:
        r = np.asarray(raw[name]) if raw[name] else None
        mean_s = f"mean {r.mean() * 1000.0:10.2f} ps" if r is not None else " " * 18
        if name in (lo_name, hi_name):
            print(f"                  {name:>8s} {c:7.3f} (anchor)          "
                  f"{mean_s}")
            continue
        vals = rows.get(name)
        if not vals:
            continue
        a = np.asarray(vals)
        span = abs(hi_c - lo_c)
        worst = max(worst, abs(float(a.mean()) - c) / span if span else 0.0)
        print(f"                  {name:>8s} {c:7.3f} declared -> "
              f"{a.mean():7.3f} measured  {mean_s}  (spread "
              f"{a.max() - a.min():.3f})")
    if agree:
        a = float(np.mean(agree)) * 100.0
        print(f"                  per-path agreement with this order: {a:.1f}% "
              f"of paths rank the levels the same way as the mean does")
        if a < 90.0:
            print(f"                  -> {100.0 - a:.1f}% of paths order the "
                  f"levels differently, so NO single coordinate is right for "
                  f"all of them. A shared axis fits the majority and misfits "
                  f"the rest; that misfit is a floor no spacing can remove, "
                  f"and it is what the neural residual would have to carry.")
    # Order is the blunt statement of the same thing, and the one that says
    # whether this is a spacing problem or an ordering problem.
    dec = [n for n, _ in by_coord]
    got = sorted(dec, key=lambda n: (float(np.mean(rows[n])) if rows.get(n)
                                     else coord_of[n]))
    if dec != got:
        print(f"                  -> ORDER DISAGREES. declared "
              f"{' < '.join(dec)}, measured {' < '.join(got)}.")
        print(f"                     level_values assumes an order the data "
              f"does not have, so the level polynomial is fit on the wrong "
              f"axis. Either the coordinates are wrong, or these levels are "
              f"not one severity axis at all -- check the mean column above "
              f"against what each corner is supposed to mean, and check that "
              f"the level token in the filenames maps to the corner you "
              f"think it does (run.sh check).")
    elif worst > 0.05:
        print(f"                  -> spacing is off by {worst * 100:.0f}% of "
              f"the axis (order is right). Put the measured value in "
              f"corners.level_values and re-run; the level polynomial is fit "
              f"on these coordinates.")


def _print_weighting_comparison(y, phi, split, coords, cfg, hid) -> None:
    """What each base.weighting would have scored at the hidden corners.

    Printed only -- never written to summary.json or any file. The mode in
    effect is already chosen (config, plus the small-grid downgrade in
    ``loo._effective_mode``); this is here so the choice can be sanity-checked
    at a glance instead of taken on faith.

    Do NOT turn it into an automatic selector. Picking by these numbers is
    selection against held-out data over very few corners, and the label-free
    alternatives were measured and found unreliable: plain seen-LOO ranks the
    modes backwards, and the row-masked variant cannot be computed at all when a
    voltage has a single seen corner."""
    import copy

    import numpy as np

    from si_model.training.loo import _effective_mode, fit_field

    cur = _effective_mode(cfg, split)
    print(f"    -- hidden error per weighting (for reference, not stored) --")
    for w in ("plain", "local", "adaptive"):
        c = copy.deepcopy(cfg)
        c["base"]["weighting"] = w
        if w == "local" and not c["base"].get("bandwidth"):
            print(f"       {w:9s} (bandwidth not set)")
            continue
        try:
            loo, _ = fit_field(y, phi, split, coords, c, force_mode=w)
        except Exception as e:
            print(f"       {w:9s} (could not measure: {repr(e)[:40]})")
            continue
        e = np.array([float(np.nanmean(np.abs(loo[:, ci] - y[:, ci])) * 1000.0)
                      for ci in hid])
        print(f"       {w:9s} {e.mean():8.3f} ps  (worst {e.max():7.3f})"
              f"{'  <- in effect' if w == cur else ''}")
def _trainer(m: dict):
    if m["task"] == "slew":
        from si_model.tasks.slew.train_slew import Trainer
    else:
        from si_model.tasks.slack.train import Trainer
    return Trainer(m["cfg"])


def stage_train(m: dict) -> None:
    _trainer(m).run()


BUNDLE_NAME = "model.pt"
BUNDLE_FORMAT = "si_corner_model/bundle/1"


def bundle_path(m: dict) -> str:
    """One circuit's single weight file: runs/<mode>/<design>/model.pt."""
    return os.path.join(os.path.dirname(m["cfg"]["train"]["out_dir"]), BUNDLE_NAME)


def stage_bundle(models: list) -> None:
    """Pack every temperature's weights for a circuit into ONE file.

    Temperature is a split dimension -- 125C and m25C are fitted separately
    because their BEOL level sets differ and two temperatures cannot support an
    interpolating polynomial. But that is an internal detail: from the outside a
    circuit should be one model, one file, one command. So training still writes
    a per-temperature ``best.pt`` (it needs somewhere to checkpoint mid-run) and
    this stage collects them into ``runs/<mode>/<design>/model.pt``, which is what
    predict loads and what gets handed over.
    """
    import torch

    from si_model.compat import load_checkpoint

    by_design = {}
    for m in models:
        by_design.setdefault(m["design"], []).append(m)

    for design, ms in sorted(by_design.items()):
        temps, missing = {}, []
        for m in sorted(ms, key=lambda x: str(x["temp"])):
            ck_path = os.path.join(m["cfg"]["train"]["out_dir"], "best.pt")
            if not os.path.exists(ck_path):
                missing.append(str(m["temp"]))
                continue
            ck = load_checkpoint(ck_path, map_location="cpu")
            temps[str(m["temp"])] = {"model": ck["model"], "enc": ck["enc"],
                                     "cfg": ck["cfg"], "epoch": ck["epoch"]}
        if not temps:
            print(f"  {design}: no trained temperature, skipped (run train first)", flush=True)
            continue
        out = bundle_path(ms[0])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        torch.save({"format": BUNDLE_FORMAT, "design": design,
                    "temps": temps}, out)
        note = f"  (not trained: {', '.join(missing)})" if missing else ""
        print(f"  {out}  <- {len(temps)} temps [{', '.join(sorted(temps))}]{note}",
              flush=True)


def stage_predict(m: dict, corners: str) -> None:
    import numpy as np

    from si_model.compat import load_checkpoint

    out_dir = m["cfg"]["train"]["out_dir"]
    tr = _trainer(m)
    # Prefer the single shipped file (model.pt) when it exists; otherwise fall
    # back to the per-temperature checkpoint left by training -- the case where
    # train->predict was run without bundle.
    bundle = bundle_path(m)
    if os.path.exists(bundle):
        b = load_checkpoint(bundle, map_location=tr.dev)
        key = str(m["temp"])
        assert key in b["temps"], (
            f"{bundle} has no temperature {key} (it has: {sorted(b['temps'])}). "
            f"Re-run run.sh bundle")
        ck = b["temps"][key]
    else:
        ckpt = os.path.join(out_dir, "best.pt")
        assert os.path.exists(ckpt), f"no checkpoint yet: {ckpt} (run train first)"
        ck = load_checkpoint(ckpt, map_location=tr.dev)
    try:
        tr.model.load_state_dict(ck["model"])
        tr.enc.load_state_dict(ck["enc"])
    except RuntimeError as e:
        # Shape mismatches here mean the weights were trained against a
        # different dataset -- most often a different cell-family count, which
        # changes the embedding. The torch message names tensor sizes and not
        # the cause, so say what it is and what to do.
        raise RuntimeError(
            "the saved weights do not fit this dataset: %s\n"
            "  This happens when the cache was rebuilt after training -- a\n"
            "  different path or corner count, or a cell library that yields a\n"
            "  different number of families, changes the model shape.\n"
            "  Re-run train for this model (its weights are stale), or restore\n"
            "  the dataset the weights were trained on." % (str(e).split("\n")[0],))
    idx = {"hidden": tr.split.hidden_idx, "seen": tr.split.seen_idx,
           "all": np.arange(tr.C)}[corners]
    tr.export_predictions(out_dir, idx, tag=corners)


def stage_merge(models: list, p: dict, corners: str) -> str:
    """Every member's predictions into ONE file, with design/temp columns.

    The corner label carries voltage and BEOL level but NOT the temperature or
    the circuit -- those are the split dimensions -- so they become columns.
    """
    out_dir = os.path.join(
        _auto(p.get("out", {}).get("runs"),
              f"runs/{p.get('mode') or 'setup'}"), "_all")
    os.makedirs(out_dir, exist_ok=True)
    out_fp = os.path.join(out_dir, f"predictions_{corners}.csv")
    header = None
    rows = 0
    missing = []
    with open(out_fp, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        for m in models:
            fp = os.path.join(m["cfg"]["train"]["out_dir"], f"predictions_{corners}.csv")
            if not os.path.exists(fp):
                missing.append(m["name"])
                continue
            with open(fp, newline="", encoding="utf-8") as f:
                r = csv.reader(f)
                head = next(r)
                if header is None:
                    header = ["design", "temp"] + head
                    w.writerow(header)
                assert ["design", "temp"] + head == header, f"{fp}: column mismatch"
                for row in r:
                    w.writerow([m["design"], m["temp"]] + row)
                    rows += 1
    assert header is not None, \
        f"nothing to merge (predictions_{corners}.csv). Run predict first."
    if missing:
        print(f"  (!) missing models: {missing}")
    print(f"  wrote {out_fp}: {rows} rows, {len(models) - len(missing)}/{len(models)} models")

    # Corners only. A model per (circuit, temperature) is how this is trained,
    # not how it is delivered -- the deliverable is one predictor, and splitting
    # the summary by model invited reading the split as a result. Each model
    # still writes its own summary.json in its own directory; what is merged
    # here is the corner table, which is what the numbers are about. The
    # by_model copy also went stale silently when a training was interrupted,
    # since a checkpoint updates and its summary does not.
    # The merged numbers come from the prediction files. If a model was
    # retrained and predict was not re-run, they describe the PREVIOUS weights
    # -- the same silent mixing the old by_model check guarded against, moved
    # to where the numbers now actually come from.
    stale = []
    for m in models:
        d = m["cfg"]["train"]["out_dir"]
        pred = os.path.join(d, f"predictions_{corners}.csv")
        ckpt = os.path.join(d, "best.pt")
        if (os.path.exists(pred) and os.path.exists(ckpt)
                and os.path.getmtime(pred) < os.path.getmtime(ckpt)):
            stale.append(m["name"])
    if stale:
        print(f"  (!) predictions older than the weights for: {stale}\n"
              f"      these were trained again after predicting, so the numbers "
              f"below are the previous model's. Re-run predict.", flush=True)
    summ = {"by_corner": _corner_table(out_fp)}
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summ, f, indent=2)
    print(f"  wrote {out_dir}/summary.json ({len(summ['by_corner'])} corners)")
    _print_corner_table(summ["by_corner"])
    return out_fp


def _corner_table(csv_fp: str) -> list:
    """One row per CORNER, read back from the merged predictions.

    The per-model summaries answer "how did model X do"; this answers "how well
    is each corner predicted", which is the question the deliverable is actually
    about -- a corner is a corner regardless of which circuit/temperature model
    happened to produce it. Rows with no truth (query corners) are counted but
    carry no error.
    """
    acc = {}
    with open(csv_fp, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            key = (row["design"], row["temp"], row["corner"])
            a = acc.setdefault(key, {"n": 0, "n_truth": 0, "sum": 0.0, "worst": 0.0})
            a["n"] += 1
            if row.get("truth_ps") in (None, ""):
                continue
            e = abs(float(row["model_err_ps"]))
            a["n_truth"] += 1
            a["sum"] += e
            a["worst"] = max(a["worst"], e)
    out = []
    for (design, temp, corner), a in sorted(acc.items()):
        out.append({
            "design": design, "temp": temp, "corner": corner,
            "n_paths": a["n"],
            "mae_ps": round(a["sum"] / a["n_truth"], 3) if a["n_truth"] else None,
            "worst_ps": round(a["worst"], 3) if a["n_truth"] else None,
        })
    return out


def _print_corner_table(rows: list) -> None:
    if not rows:
        return
    print("\n  Per-corner scores")
    print(f"    {'circuit':<22}{'corner':<26}"
          f"{'paths':>7}{'MAE':>10}{'worst':>10}")
    for r in rows:
        mae = "-" if r["mae_ps"] is None else f"{r['mae_ps']:.2f}ps"
        wst = "-" if r["worst_ps"] is None else f"{r['worst_ps']:.2f}ps"
        # Temperature is part of which corner this is, not a separate axis of
        # the result: one line per corner, whatever produced it.
        corner = f"{r['temp']}C {r['corner']}" if r.get("temp") else r["corner"]
        print(f"    {r['design']:<22}{corner:<26}"
              f"{r['n_paths']:>7}{mae:>10}{wst:>10}")
    scored = [r for r in rows if r["mae_ps"] is not None]
    if scored:
        print(f"    {'total':<48}{sum(r['n_paths'] for r in rows):>7}"
              f"{sum(r['mae_ps'] for r in scored) / len(scored):>8.2f}ps"
              f"{max(r['worst_ps'] for r in scored):>8.2f}ps")
        # The caveat that belongs with these numbers -- the stopping epoch was
        # chosen on these same corners, so they are best-case rather than
        # held-out -- is not printed, by request. It stays in each model's
        # summary.json as selected_on, which is the record that outlives the
        # terminal.


# ----------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES, nargs="?", default="help")
    ap.add_argument("--config", default=DEFAULT_PROJECT, help="project config (default: config.yaml)")
    ap.add_argument("--design", default=None, help="this circuit only")
    ap.add_argument("--temp", default=None, help="this temperature only")
    ap.add_argument("--corners", default="hidden", choices=["hidden", "seen", "all"])
    ap.add_argument("--mode", default=None, choices=["setup", "hold"],
                    help="setup or hold for this run, overriding config `mode`. "
                         "Sets where reports are read AND where output is "
                         "written, so the two cannot drift apart")
    ap.add_argument("--file", default=None,
                    help="report file to inspect in the check stage "
                         "(omit to use the first file from the config)")
    args = ap.parse_args(argv)
    os.environ["SI_STAGE"] = args.stage

    os.chdir(REPO_ROOT)
    if args.stage == "help":
        print(HELP)
        return 0
    from si_model import memlog
    memlog.report_job()
    memlog.report_limits()
    memlog.start()
    p = load_project(args.config)
    p["_config_path"] = os.path.abspath(args.config)
    if args.mode:
        # Overriding here rather than editing the file keeps a hold run from
        # being left switched on by accident -- `mode` drives the cache and runs
        # directories too, so a forgotten flip would have a later setup run read
        # and write the hold tree.
        p["mode"] = args.mode
    models = select(expand(p), args.design, args.temp)

    if args.stage == "list":
        stage_list(models, p)
        return 0
    if args.stage == "check":
        return stage_check(models, args.file)

    stages = _ALL_STAGES if args.stage == "all" else (args.stage,)
    failed = []
    for stage in stages:
        if stage == "bundle":
            print(f"\n===== bundle: one weight file per circuit =====", flush=True)
            try:
                stage_bundle(models)
            except Exception as e:
                failed.append(("bundle", repr(e)))
                traceback.print_exc()
            continue
        if stage == "merge":
            try:
                stage_merge(models, p, args.corners)
            except Exception as e:
                failed.append(("merge", repr(e)))
                traceback.print_exc()
            continue
        for m in models:
            print(f"\n===== {stage}: {m['name']} =====", flush=True)
            try:
                if stage == "build":
                    stage_build(m)
                elif stage == "base":
                    stage_base(m)
                elif stage == "train":
                    stage_train(m)
                elif stage == "sweep":
                    stage_sweep(m)
                elif stage == "predict":
                    stage_predict(m, args.corners)
            except Exception as e:
                failed.append((f"{stage}:{m['name']}", repr(e)))
                traceback.print_exc()
                print(f"!!!!! FAILED {stage}: {m['name']} -- continuing", flush=True)

    print("\n" + "=" * 60)
    if failed:
        print(f"done, but {len(failed)} failed:")
        for what, err in failed:
            print(f"  - {what}: {err}")
        return 1
    print(f"all succeeded ({len(models)} models, stages={list(stages)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
