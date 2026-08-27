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
    root = os.environ.get("SI_ROOT") or p.get("root") or "auto"
    if str(root) == "auto":
        root = os.path.dirname(REPO_ROOT)
    p["root"] = os.path.abspath(os.path.expanduser(str(root)))
    return p


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


def select_basis(y, sp, coords, cfg, verbose=True):
    """Pick the polynomial basis by SEEN-corner leave-one-out error.

    The right order is data-dependent -- how sharply slack bends with voltage
    differs by design and temperature -- so it is measured rather than assumed.
    Candidates vary the voltage order and the cross-term budget; each is scored
    by its LOO error on SEEN corners only, so hidden labels never influence the
    choice (picking by hidden error would leak the very thing being held out).

    Candidates with fewer than 1 degree of freedom are excluded: their fit
    passes through every seen point, driving seen-LOO to ~0 and winning for the
    wrong reason.

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
    best = None
    tried = []
    for vo in range(1, v_cap + 1):
        for cross, cmd in ((False, 2), (True, 2), (True, 3)):
            c = copy.deepcopy(cfg)
            c["base"]["axes"][0]["order"] = vo
            c["base"]["cross_terms"] = cross
            c["base"]["cross_max_degree"] = cmd
            exps, names, _ = expand_terms(c, [nv, nlv])
            phi = design_matrix(coords, exps)
            if len(S) - phi.shape[1] < 1:            # 0 dof -> seen-LOO is meaningless
                continue
            loo, _ = fit_field(y, phi, sp, coords, c)
            err = float(np.nanmean(np.abs(loo[:, S] - y[:, S])))
            tried.append((err, vo, cross, cmd, len(names) + 1))
            if best is None or err < best[0]:
                best = (err, vo, cross, cmd, names)
    assert best is not None, (
        "no usable basis -- too few seen corners. Reduce the holdout or add "
        "more corners")
    err, vo, cross, cmd, names = best
    if verbose and _base_loud():
        print(f"[BASIS] picked by seen-LOO: v^{vo} cross={cross}"
              + (f"(deg{cmd})" if cross else "")
              + f" -> {len(names) + 1} params, seen-LOO {err * 1000:.2f} ps", flush=True)
        # The full candidate table is what makes the choice checkable, but it
        # is up to 18 rows and it prints again for every model. In `base`, whose
        # entire job is to show the base numbers, that is the point. Anywhere
        # else it buries the line the reader is waiting for, so it is behind a
        # switch there: SI_BASIS_TABLE=1.
        for e, v, cr, cd, k in sorted(tried):
            print(f"          v^{v} cross={str(cr):5s} {k} params  {e * 1000:8.2f} ps",
                  flush=True)
    cfg["base"]["axes"][0]["order"] = vo
    cfg["base"]["cross_terms"] = cross
    cfg["base"]["cross_max_degree"] = cmd
    return cfg


def _auto(value, default: str) -> str:
    """``None`` / ``"auto"`` -> the mode-derived default; anything else is taken
    literally, so an odd layout can still pin its own path."""
    return default if value is None or str(value) == "auto" else str(value)


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
        proc = co["process"]
        volts = [float(v) for v in co["voltages"]]
        lvals = {str(k): float(v) for k, v in co["level_values"].items()}
        ref_v, ref_lv = float(co["ref_voltage"]), str(co["ref_level"])
        assert ref_lv in lvals, \
            f"{design}: corners.ref_level {ref_lv!r} not in level_values {sorted(lvals)}"
        ddir = os.path.join(p["root"], design)
        for t in pd["temps"]:
            tag, levels = str(t["tag"]), list(t["levels"])
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
                     "order": _order(b.get("v_order"), len(seen_v), 6),
                     "fit_scale": float(b.get("v_fit_scale", 1.0)),
                     "token_scale": float(b.get("v_token_scale", 0.1)),
                     "gap_cap": float(b.get("v_gap_cap", 2.5))},
                    {"name": "rc", "ref": lvals[ref_lv],
                     "order": _order(b.get("level_order"), n_seen_lv, 2),
                     "levels": lvals,
                     "fit_scale": float(b.get("level_fit_scale", 1.0)),
                     "token_scale": float(b.get("level_token_scale", 1.0)),
                     "gap_cap": float(b.get("level_gap_cap", 2.0))},
                ],
                "weighting": b.get("weighting", "adaptive"),
                "cross_terms": b.get("cross_terms", True),
                "cross_max_degree": b.get("cross_max_degree", 2),
                "adaptive_k": b.get("adaptive_k", 6),
                "adaptive_amp_ratio": b.get("adaptive_amp_ratio", 1.5),
                "adaptive_clip_frac": b.get("adaptive_clip_frac", 0.3),
            }
            # `auto` fixes the basis SIZE here from what is identifiable; the
            # actual choice among candidate bases is made in stage_base/compute
            # by seen-LOO (see select_basis) because the right answer is
            # data-dependent, not something to hard-code.
            if b.get("adaptive_grid"):
                base["adaptive_grid"] = b["adaptive_grid"]
            if b.get("weighting") == "local":
                assert b.get("bandwidth"), "base.weighting: local requires base.bandwidth"
            # Pass bandwidth regardless of weighting -- the comparison table in
            # `run.sh base` can only score `local` if a bandwidth exists, and
            # passing it only when weighting IS local would drop local from the
            # table forever.
            if b.get("bandwidth"):
                base["bandwidth"] = b["bandwidth"]

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
    skipped = [split.corners[int(i)] for i in split.hidden_idx if not measured[i]]
    if skipped:
        print(f"    (skipped, no ground truth: {skipped})")
    if hid and field == "slack":
        _print_weighting_comparison(y, phi, split, coords, cfg, hid)


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
        # Said once, here, because the per-model blocks that used to carry it
        # are gone: the epoch was chosen on these same corners.
        print("\n    NOTE: training picked its stopping epoch on these corners,"
              "\n          so these are best-case figures, not held-out ones.")


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
