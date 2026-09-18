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
  sweep    lambda_si in {0, 0.1, 1, 10} -> runs/_sweep/... (slack \uc804\uc6a9, \ube44\uad50\uc6a9)
  merge    all members    -> runs/_all/predictions_<corners>.csv + summary.json
  all      build, base, train, bundle, predict, merge  (sweep \uc740 \uba85\uc2dc\ud560 \ub54c\ub9cc)

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
si_corner_model \u2014 \uba85\ub839\uc740 `bash scripts/run.sh <\ub2e8\uacc4>` \ud558\ub098\ubfd0\uc774\ub2e4.
\uc124\uc815\uc740 config.yaml \ud558\ub098\ubfd0\uc774\ub2e4. \ucc98\uc74c\uc774\uba74 docs/START.md \ub97c \uc704\uc5d0\uc11c \uc544\ub798\ub85c.

  \ub2e8\uacc4 (\ubcf4\ud1b5 \uc774 \uc21c\uc11c)
    recon      \ub370\uc774\ud130 \uc815\ucc30. \ud3f4\ub354/\ud30c\uc77c\uba85/\ubcf8\ubb38\uc744 \ud6d1\uc5b4 recon_out.txt \ub85c \uc800\uc7a5
               -> \uc5ec\uae30 \uac12\uc744 config.yaml \uc5d0 \uc62e\uaca8 \uc801\ub294\ub2e4
    check      \ub9ac\ud3ec\ud2b8 \ud55c \uac1c\ub97c \ud30c\uc11c\uc5d0 \ud1b5\uacfc\uc2dc\ucf1c \uc5b4\ub290 \uc904\uc774 \uc7a1\ud788\uace0 \uc548 \uc7a1\ud788\ub294\uc9c0 \ubcf4\uace0
               -> \ubcf8\ubb38 \ud615\uc2dd\uc774 \ub2e4\ub97c \ub54c(SSTA \ub85c \uc5f4/\ud589\uc774 \ub298\uc5c8\uc744 \ub54c) \uc5ec\uae30\ubd80\ud130
    list       config \ub97c \ud3bc\uccd0 "\ubb50\uac00 \uc5b4\ub5a4 \uc124\uc815\uc73c\ub85c \ub3cc\uc9c0" \ucd9c\ub825. \ud30c\uc77c \uc548 \uac74\ub4dc\ub9bc
               -> \ucf54\ub108 \uc218, seen/hidden, \ub2e4\ud56d\uc2dd \ud30c\ub77c\ubbf8\ud130 \uc218\uae4c\uc9c0 \uac80\uc0b0\ud574\uc90c
    build      \ub9ac\ud3ec\ud2b8 -> cache/<\ud68c\ub85c>/<\uc628\ub3c4>/dataset.npz          (numpy\ub9cc \ud544\uc694)
    base       OLS base \uc624\ucc28\ub9cc \ucd9c\ub825. base \uc218\uce58\ub294 \uc5ec\uae30\uc11c\ub9cc \ub098\uc628\ub2e4  (numpy\ub9cc, \uc218 \ucd08)
               -> \ud559\uc2b5 \uc804\uc5d0 \ub370\uc774\ud130\uac00 \uc81c\ub300\ub85c \ud30c\uc2f1\ub410\ub294\uc9c0 \ud655\uc778\ud558\ub294 \ub2e8\uacc4
    train      \ud559\uc2b5 -> runs/<\ud68c\ub85c>/<\uc628\ub3c4>/best.pt + summary.json   (torch/GPU)
    bundle     \uc628\ub3c4\ubcc4 \uac00\uc911\uce58\ub97c \ud68c\ub85c\ub2f9 \ud55c \ud30c\uc77c\ub85c -> runs/<\ud68c\ub85c>/model.pt
    predict    \uc800\uc7a5\ub41c \uac00\uc911\uce58\ub85c \uc608\uce21\ub9cc -> predictions_<corners>.csv
    merge      \uc804 \ud68c\ub85c\u00b7\uc804 \uc628\ub3c4 \uc608\uce21\uc744 runs/_all/ \ub85c \ud569\uce68
    all        build -> base -> train -> bundle -> predict -> merge
    sweep      lambda_si {0, 0.1, 1, 10} \ube44\uad50 -> runs/_sweep/ (slack \uc804\uc6a9)

  \uc635\uc158
    --design <\ud68c\ub85c>          \uadf8 \ud68c\ub85c\ub9cc
    --temp <\uc628\ub3c4tag>         \uadf8 \uc628\ub3c4\ub9cc
    --corners hidden|seen|all   predict/merge \ub300\uc0c1 \ucf54\ub108 (\uae30\ubcf8 hidden)
    --config <\ud30c\uc77c>          \ub2e4\ub978 \ud504\ub85c\uc81d\ud2b8 config (\uae30\ubcf8 config.yaml)

  \uc608\uc2dc
    bash scripts/run.sh recon
    bash scripts/run.sh check                  # \ud615\uc2dd\uc774 \uc758\uc2ec\uc2a4\ub7ec\uc6b0\uba74 build \uc804\uc5d0
    bash scripts/run.sh check --file <\ub9ac\ud3ec\ud2b8>
    bash scripts/run.sh list
    bash scripts/run.sh all
    bash scripts/run.sh base --design cpu
    bash scripts/run.sh train --design cpu --temp 125
    bash scripts/run.sh predict --corners all

  \ud30c\uc77c \uace0\uce58\uc9c0 \uc54a\uace0 \uacbd\ub85c\ub9cc \ubc14\uafb8\uae30
    env SI_ROOT=/real/path SI_DESIGNS=cpu,gpu bash scripts/run.sh list

  \ubb38\uc11c
    docs/START.md    \ub3c4\ucc29\ud574\uc11c \ucc98\uc74c\ubd80\ud130 (\ud3f4\ub354 \uad6c\uc870 \ucf00\uc774\uc2a4\ubcc4)
    docs/CONFIG.md   config.yaml \ud0a4 \uc804\ubd80 + \ucf54\ub108 \uc120\uc815 + \uc5d0\ub7ec\ud45c
    docs/OLS.md      base \ud29c\ub2dd
    docs/PARSING.md  \ub9ac\ud3ec\ud2b8 \ud30c\uc2f1 / FIXED_PATH \ubb38\uc81c / npz \uc9c1\uc811 \ub9cc\ub4e4\uae30
"""


# ------------------------------------------------------------------ expansion
def load_project(fp: str) -> dict:
    with open(fp) as f:
        p = yaml.safe_load(f) or {}
    root = os.environ.get("SI_ROOT") or p.get("root") or "auto"
    if str(root) == "auto":
        # The same model can live beside the design reports or one directory
        # deeper under pt_si_re/. Prefer the nearby directory that actually
        # contains the configured designs; retain the old parent default when
        # the reports are not present in this checkout.
        parent = os.path.dirname(REPO_ROOT)
        names = os.environ.get("SI_DESIGNS")
        names = ([x.strip() for x in names.split(",") if x.strip()] if names else
                 p.get("designs"))
        if isinstance(names, dict):
            names = list(names)
        if isinstance(names, list) and names:
            candidates = (parent, os.path.dirname(parent))
            root = max(candidates, key=lambda path: sum(
                os.path.isdir(os.path.join(path, name)) for name in names))
        else:
            root = parent
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
          chipA: {}                                  # \uc804\uc5ed \uadf8\ub300\ub85c
          chipB:
            files: {subdir: reports}                 # \uc774 \ud68c\ub85c\ub9cc \ub9ac\ud3ec\ud2b8 \uc704\uce58\uac00 \ub2e4\ub984
          chipC:
            corners: {voltages: [0.5, 0.6, 0.685]}   # \uc774 \ud68c\ub85c\ub9cc \uc804\uc555\uc774 3\uac1c
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
HOLDOUT_KEYS = ("hidden_voltages", "seen_voltages", "seen_corners", "hidden_levels",
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
        f"corners.hidden_per_voltage={n} \ub294 1 \uc774\uc0c1, \ub808\ubca8 \uc218({len(levels)}) \ubbf8\ub9cc\uc774\uc5b4\uc57c \ud55c\ub2e4 "
        f"-- \uadf8 \uc804\uc555\uc758 \ubaa8\ub4e0 \ub808\ubca8\uc744 \uc228\uae30\uba74 \uc575\ucee4\uac00 \ub0a8\uc9c0 \uc54a\ub294\ub2e4")
    out = []
    for i, v in enumerate(sorted(float(x) for x in volts)):
        picked, j = [], 0
        while len(picked) < n and j < 2 * len(levels):
            lv = levels[(i + j) % len(levels)]
            j += 1
            if lv in picked:
                continue
            if abs(v - ref_v) < 1e-9 and lv == ref_lv:
                continue                       # \uc575\ucee4 \ucf54\ub108\ub294 \uc228\uae30\uc9c0 \uc54a\ub294\ub2e4
            picked.append(lv)
        out += [[v, lv] for lv in picked]
    return out


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
            if len(S) - phi.shape[1] < 1:            # \uc790\uc720\ub3c4 0 -> seen-LOO \uac00 \ubb34\uc758\ubbf8
                continue
            loo, _ = fit_field(y, phi, sp, coords, c)
            err = float(np.nanmean(np.abs(loo[:, S] - y[:, S])))
            tried.append((err, vo, cross, cmd, len(names) + 1))
            if best is None or err < best[0]:
                best = (err, vo, cross, cmd, names)
    assert best is not None, (
        "\uc4f8 \uc218 \uc788\ub294 \uae30\uc800\uac00 \uc5c6\ub2e4 -- seen \ucf54\ub108\uac00 \ub108\ubb34 \uc801\ub2e4. \ud640\ub4dc\uc544\uc6c3\uc744 \uc904\uc774\uac70\ub098 "
        "\ucf54\ub108\ub97c \ub298\ub9b4 \uac83")
    err, vo, cross, cmd, names = best
    if verbose:
        print(f"[BASIS] seen-LOO \ub85c \uc120\ud0dd: v^{vo} cross={cross}"
              + (f"(deg{cmd})" if cross else "")
              + f" -> {len(names) + 1} \ud30c\ub77c\ubbf8\ud130, seen-LOO {err * 1000:.2f} ps", flush=True)
        for e, v, cr, cd, k in sorted(tried):
            print(f"          v^{v} cross={str(cr):5s} {k}\ud30c\ub77c\ubbf8\ud130  {e * 1000:8.2f} ps", flush=True)
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

    # setup \uacfc hold \ub294 \ub9ac\ud3ec\ud2b8 \uc704\uce58\ub3c4 \ucd9c\ub825 \uc704\uce58\ub3c4 \uac08\ub77c\uc838\uc57c \ud55c\ub2e4. \uc608\uc804\uc5d0\ub294 \uadf8 \ub124
    # \uad70\ub370(files.subdir / files.crosstalk_subdir / out.cache / out.runs)\ub97c \uac01\uac01
    # \uc190\uc73c\ub85c \uace0\uccd0\uc57c \ud588\uace0, subdir \ub9cc \ubc14\uafb8\uace0 out \uc744 \uc78a\uc73c\uba74 hold \uacb0\uacfc\uac00 setup \uce90\uc2dc\uc640
    # run \uc744 \uc870\uc6a9\ud788 \ub36e\uc5b4\uc37c\ub2e4. \uc774\uc81c `mode` \ud55c \uc904\uc774 \ub137 \ub2e4 \uc815\ud55c\ub2e4.
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
                f"temp {tag}: corners.ref_level {ref_lv!r} \uac00 \uc774 \uc628\ub3c4\uc758 levels {levels} \uc5d0 \uc5c6\ub2e4 "
                f"-- \ubaa8\ub4e0 \uc628\ub3c4\uc5d0 \uc874\uc7ac\ud558\ub294 \ub808\ubca8\uc744 \uc575\ucee4\ub85c \uc4f8 \uac83")

            # ---- holdout, resolved PER TEMPERATURE ----------------------
            ho = holdout_for(co, t)
            seen_decl = [float(v) for v in ho.get("seen_voltages") or []]
            hidden_v = [float(v) for v in ho.get("hidden_voltages") or []]
            assert not (seen_decl and hidden_v), (
                f"temp {tag}: seen_voltages \uc640 hidden_voltages \uc911 \ud558\ub098\ub9cc \uc4f8 \uac83")
            seen_v = seen_decl or [v for v in volts
                                   if not any(abs(v - h) < 1e-9 for h in hidden_v)]
            assert any(abs(ref_v - v) < 1e-9 for v in seen_v), (
                f"temp {tag}: corners.ref_voltage {ref_v} \uac00 \uc228\uaca8\uc84c\ub2e4 (seen = {seen_v}). "
                f"\uc575\ucee4 \uc804\uc555\uc740 \ud56d\uc0c1 seen \uc774\uc5b4\uc57c \ud55c\ub2e4")
            hidden_lv = [str(x) for x in ho.get("hidden_levels") or []]
            assert ref_lv not in hidden_lv, (
                f"temp {tag}: ref_level {ref_lv!r} \ub294 hidden_levels \uc5d0 \ub123\uc744 \uc218 \uc5c6\ub2e4")
            for lv in hidden_lv:
                assert lv in levels, (
                    f"temp {tag}: hidden_levels \uc758 {lv!r} \uac00 \uc774 \uc628\ub3c4\uc758 levels {levels} \uc5d0 \uc5c6\ub2e4")
            hidden_corners = [list(x) for x in ho.get("hidden_corners") or []]
            seen_corners = [list(x) for x in ho.get("seen_corners") or []]
            if seen_corners:
                incompatible = [k for k in ("seen_voltages", "hidden_voltages",
                                            "hidden_levels", "hidden_per_voltage")
                                if ho.get(k)]
                assert not incompatible, (
                    f"temp {tag}: seen_corners \uc640 {incompatible} \ub294 \uac19\uc774 \uc4f8 \uc218 \uc5c6\ub2e4. "
                    "\ud3c9\uac00 \ub300\uc0c1\uc740 hidden_corners \uc5d0\ub9cc \uc801\uc744 \uac83")
                allowed = {(v, lv) for v in volts for lv in levels}
                for key, pairs in (("seen_corners", seen_corners),
                                   ("hidden_corners", hidden_corners)):
                    for pair in pairs:
                        assert len(pair) == 2 and (float(pair[0]), str(pair[1])) in allowed, (
                            f"temp {tag}: {key} \uc758 {pair!r} \uac00 voltages x levels \uc5d0 \uc5c6\ub2e4")
                    assert len({(float(v), str(lv)) for v, lv in pairs}) == len(pairs), (
                        f"temp {tag}: {key} \uc5d0 \uc911\ubcf5 \ucf54\ub108\uac00 \uc788\ub2e4")
                seen_set = {(float(v), str(lv)) for v, lv in seen_corners}
                hidden_set = {(float(v), str(lv)) for v, lv in hidden_corners}
                assert not (seen_set & hidden_set), (
                    f"temp {tag}: seen_corners \uc640 hidden_corners \uac00 \uacb9\uce5c\ub2e4: "
                    f"{sorted(seen_set & hidden_set)}")
                assert (ref_v, ref_lv) in seen_set, (
                    f"temp {tag}: \uc575\ucee4 ({ref_v}, {ref_lv}) \ub294 seen_corners \uc5d0 \uc788\uc5b4\uc57c \ud55c\ub2e4")
            if ho.get("hidden_per_voltage"):
                assert not hidden_corners, (
                    f"temp {tag}: hidden_per_voltage \uc640 hidden_corners \ub294 \uac19\uc774 \uc4f0\uc9c0 \uc54a\ub294\ub2e4")
                hidden_corners = spread_hidden(seen_v if seen_decl else volts,
                                               levels, int(ho["hidden_per_voltage"]),
                                               ref_v, ref_lv)
            for hv, hl in hidden_corners:
                assert str(hl) in levels, (
                    f"temp {tag}: hidden_corners \uc758 \ub808\ubca8 {hl!r} \uac00 \uc774 \uc628\ub3c4\uc758 "
                    f"levels {levels} \uc5d0 \uc5c6\ub2e4 -- \uc628\ub3c4\ub9c8\ub2e4 \ub808\ubca8\uc774 \ub2e4\ub974\ubbc0\ub85c "
                    f"holdout \ub3c4 temps[] \uc548\uc5d0\uc11c \ub530\ub85c \uc801\uc5b4\uc57c \ud55c\ub2e4")
                assert not (abs(float(hv) - ref_v) < 1e-9 and str(hl) == ref_lv), (
                    f"temp {tag}: \uc575\ucee4 \ucf54\ub108 ({ref_v}, {ref_lv}) \ub294 \uc228\uae38 \uc218 \uc5c6\ub2e4")

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
            if seen_corners:
                data["selected_corners"] = [corner_label(float(v), str(lv), proc)
                                            for v, lv in seen_corners + hidden_corners]
            if pa.get("cell_taxonomy"):
                data["cell_taxonomy"] = pa["cell_taxonomy"]
            for k in ("clock_pins", "ff_output_pins", "strip_path_idx"):
                if pa.get(k) is not None:
                    data[k] = pa[k]

            # ---- corner split -------------------------------------------
            n_seen_lv = len([lv for lv in levels if lv not in hidden_lv])
            # `auto` expects exactly the selected seen set, or the full grid
            # minus holdouts in the default mode. Missing required reports
            # remain errors in both modes.
            n_expect = (len(seen_corners) if seen_corners else
                        len(seen_v) * n_seen_lv - len(hidden_corners))
            min_seen = sp.get("min_seen", "auto")
            split = {
                "hidden_levels": [lv for lv in hidden_lv if lv in levels],
                "hidden_corners": hidden_corners,
                "min_seen": (n_expect if str(min_seen) == "auto" else int(min_seen)),
            }
            if seen_corners:
                split["seen_corners"] = seen_corners
            elif seen_decl:
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
                     "order": _order(b.get("v_order"),
                                     len({float(v) for v, _ in seen_corners})
                                     if seen_corners else len(seen_v), 3),
                     "fit_scale": float(b.get("v_fit_scale", 1.0)),
                     "token_scale": float(b.get("v_token_scale", 0.1)),
                     "gap_cap": float(b.get("v_gap_cap", 2.5))},
                    {"name": "rc", "ref": lvals[ref_lv],
                     "order": _order(b.get("level_order"),
                                     len({str(lv) for _, lv in seen_corners})
                                     if seen_corners else n_seen_lv, 2),
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
                assert b.get("bandwidth"), "base.weighting: local \uc774\uba74 base.bandwidth \ud544\uc694"
            # bandwidth \ub294 weighting \uacfc \ubb34\uad00\ud558\uac8c \ub118\uae34\ub2e4 -- run.sh base \uc758 weighting
            # \ube44\uad50\ud45c\uac00 local \ub3c4 \uc7ac\ub824\uba74 \ub300\uc5ed\ud3ed\uc774 \uc788\uc5b4\uc57c \ud558\ub294\ub370, local \uc77c \ub54c\ub9cc \ub118\uae30\uba74
            # local \uc740 \uc601\uc601 \ud45c\uc5d0\uc11c \ube60\uc9c4\ub2e4.
            if b.get("bandwidth"):
                base["bandwidth"] = b["bandwidth"]

            models.append({
                "name": f"{design}/{tag}", "design": design, "temp": tag,
                "task": p.get("task", "slack"),
                "cfg": {"data": data, "split": split, "base": base,
                        "model": dict(p.get("model", {})), "train": train},
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
    """\ubb34\uc5c7\uc774 \uc5b4\ub5a4 \uc124\uc815\uc73c\ub85c \ub3cc\uc9c0 \uc804\ubd80 \ucc0d\ub294\ub2e4 -- \uc2e4\ud589 \uc804 \uac80\uc0b0\uc6a9 (\ud30c\uc77c\uc740 \uc548 \uac74\ub4dc\ub9bc).

    \ud2b9\ud788 seen/hidden \ucf54\ub108\ub97c \uc2e4\uc81c\ub85c \uc138\uc5b4 \ubcf4\uc5ec\uc900\ub2e4: \ucf54\ub108 \uc120\uc815\uc774 config \uc758\ub3c4\ub300\ub85c
    \ub418\uc5c8\ub294\uc9c0, \ub2e4\ud56d\uc2dd \ud30c\ub77c\ubbf8\ud130 \uc218\ubcf4\ub2e4 seen \uc774 \ucda9\ubd84\ud55c\uc9c0\uac00 \uc5ec\uae30\uc11c \ubc14\ub85c \ubcf4\uc778\ub2e4.
    """
    m0 = models[0]
    co = project_for(p, m0["design"])["corners"]
    print(f"root    : {p['root']}")
    print(f"task    : {m0['task']}    models: {len(models)}    process: {co['process']}")
    print(f"voltages: {co['voltages']}    levels: {co['level_values']}")
    print(f"anchor  : {co['ref_voltage']}V x {co['ref_level']}  (\ud56d\uc0c1 seen)")
    if isinstance(p.get("designs"), dict):
        print("(designs \uac00 \ud68c\ub85c\ubcc4 override \ub85c \uc120\uc5b8\ub428 -- \uc544\ub798 \uac12\uc740 \ud68c\ub85c\ub9c8\ub2e4 \ub2e4\ub97c \uc218 \uc788\ub2e4)")
    for m in models:
        d, s, ax = m["cfg"]["data"], m["cfg"]["split"], m["cfg"]["base"]["axes"]
        si = "SI:on " if d.get("crosstalk_dir") else "SI:off"
        print(f"\n  \u2500\u2500 {m['name']}  [{si}]")
        print(f"     reports : {d['annotated_dir']}")
        print(f"     levels  : {d['rc_corners']}   ref: {d['ref_corner']}   temp token: {d['temp']!r}")
        print(f"     out     : {d['cache']}  |  {m['cfg']['train']['out_dir']}")

        # \uc608\uc0c1 \ucf54\ub108 \uc218 / \ub2e4\ud56d\uc2dd \ud06c\uae30 -- \uc2e4\uc81c \ud30c\uc2f1 \uc804\uc5d0 \uc0b0\uc218\ub85c \ubbf8\ub9ac \uac80\uc0b0
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

        full_grid = [(v, lv) for v in vs for lv in d["rc_corners"]]
        if s.get("seen_corners"):
            seen = [(float(v), str(lv)) for v, lv in s["seen_corners"]]
            hid = [(float(v), str(lv)) for v, lv in s["hidden_corners"]]
            grid = seen + hid
            ignored = len(full_grid) - len(grid)
            print(f"     selected: seen {len(seen)} + \ud3c9\uac00 target {len(hid)}; "
                  f"\uc81c\uc678 {ignored}\uac1c (\ub9ac\ud3ec\ud2b8 \ubd88\ud544\uc694)")
        else:
            grid = full_grid
            seen = [c for c in grid if not _is_hidden(*c)]
            hid = [c for c in grid if _is_hidden(*c)]
        total = len(grid)
        if hid:
            print(f"     hidden  : {len(hid)}\uac1c "
                  + ", ".join(_lab(v, lv, dco["process"]) for v, lv in hid[:6])
                  + (" ..." if len(hid) > 6 else ""))
        else:
            print("     hidden  : \uc5c6\uc74c (query_corners \ub9cc \uc608\uce21 \ub300\uc0c1)")
        if d.get("query_corners"):
            print(f"     query   : {len(d['query_corners'])}\uac1c (\uc815\ub2f5 \uc5c6\uc774 \uc608\uce21\ub9cc)")
        from si_model.config import expand_terms
        n_lv = len({lv for _, lv in seen})
        n_v = len({v for v, _ in seen})
        exps, names, dropped = expand_terms(m["cfg"], [n_v, n_lv])
        npar = len(exps) + 1
        flag = "  \u26a0 seen \uc774 \ud30c\ub77c\ubbf8\ud130 \uc218 \uc774\ud558 -- \ucc28\uc218\ub97c \ub0ae\ucd94\uac70\ub098 \ud640\ub4dc\uc544\uc6c3\uc744 \uc904\uc77c \uac83" \
            if len(seen) <= npar else ""
        print(f"     corners : \uc804\uccb4 {total} = seen {len(seen)} + hidden {total - len(seen)}"
              f"   (min_seen \uac00\ub4dc {s['min_seen']})")
        print(f"     basis   : v^{ax[0]['order']} x level^{ax[1]['order']} \uae4c\uc9c0 "
              f"-> \ucd5c\ub300 {npar} \ud30c\ub77c\ubbf8\ud130 {names}{flag}")
        print("               (\ucd5c\uc885 \uae30\uc800\ub294 build \ub54c seen-LOO \ub85c \uc120\ud0dd\ub41c\ub2e4 -- run.sh base \ub85c \ud655\uc778)")
        if dropped:
            print(f"               (\ub808\ubca8 \ubd80\uc871\uc73c\ub85c \uc790\ub3d9 \uc81c\uac70: {dropped})")
        print(f"     base    : weighting={m['cfg']['base']['weighting']}"
              f"  cross_max_degree={m['cfg']['base']['cross_max_degree']}")
        if os.path.isdir(d["annotated_dir"]):
            n = sum(len(f) for _, _, f in os.walk(d["annotated_dir"]))
            print(f"     files   : \ub514\ub809\ud1a0\ub9ac \uc874\uc7ac, \ud30c\uc77c {n}\uac1c")
        else:
            print("     files   : (!) \ub514\ub809\ud1a0\ub9ac \uc5c6\uc74c \u2014 root / designs / files.subdir \ud655\uc778")


def stage_check(models: list, fp: "str | None" = None) -> int:
    """\ub9ac\ud3ec\ud2b8 \ud30c\uc77c \ud558\ub098\ub97c \ud30c\uc11c\uc5d0 \ud1b5\uacfc\uc2dc\ucf1c '\uc5b4\ub290 \uc815\uaddc\uc2dd\uc774 \uba87 \uc904\uc744 \uc7a1\uc558\ub294\uc9c0' \ubcf4\uace0\ud55c\ub2e4.

    \ubcf8\ubb38 \ud615\uc2dd\uc774 \ub2e4\ub97c \ub54c(SSTA \ub85c \uc5f4\uc774 \ub298\uc5c8\ub2e4\ub4e0\uc9c0) \ubb34\uc5c7\uc744 \uace0\uccd0\uc57c \ud558\ub294\uc9c0 \ucd94\uce21\ud558\uc9c0
    \uc54a\uc544\ub3c4 \ub418\uac8c \ud558\ub294 \uac83\uc774 \ubaa9\uc801\uc774\ub2e4. \ubabb \uc7a1\uc740 \uc815\uaddc\uc2dd\uc5d0 \ub300\ud574\uc11c\ub294 \uadf8 \ud0a4\uc6cc\ub4dc\uac00 \ub4e4\uc5b4\uac04
    \uc2e4\uc81c \uc904\uc744 \uac19\uc774 \ucc0d\uc5b4\uc8fc\ubbc0\ub85c, \uae30\ub300 \ud615\uc2dd\uacfc \uc2e4\uc81c \ud615\uc2dd\uc744 \ub098\ub780\ud788 \ub193\uace0 \ubcfc \uc218 \uc788\ub2e4.
    """
    from si_model.parsing import annotated as A
    from si_model.parsing.discovery import discover_annotated

    if fp is None:
        for m in models:
            try:
                found = discover_annotated(m["cfg"])
            except Exception as e:
                print(f"  ({m['name']}: \ud0d0\uc0c9 \uc2e4\ud328 {e})")
                continue
            if found:
                fp = sorted(found.values())[0]
                break
    assert fp, "\uac80\uc0ac\ud560 \ub9ac\ud3ec\ud2b8\ub97c \ucc3e\uc9c0 \ubabb\ud588\ub2e4 -- \ud30c\uc77c \uacbd\ub85c\ub97c \uc9c1\uc811 \uc8fc\uac70\ub098 config \ub97c \uace0\uce60 \uac83"
    print(f"file : {fp}")
    with open(fp, errors="ignore") as f:
        lines = f.readlines()
    print(f"lines: {len(lines)}\n")

    # (\uc774\ub984, \uc815\uaddc\uc2dd, \ubabb \uc7a1\uc558\uc744 \ub54c \ubcf4\uc5ec\uc904 \ud6c4\ubcf4 \uc904\uc744 \uace0\ub974\ub294 \ud0a4\uc6cc\ub4dc)
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
            print(f"  {name:14s} {len(hit):6d} \uc904 \u2713   \uc608: {hit[0].strip()[:90]}")
        else:
            cand = [l.rstrip("\n") for l in lines if kw in l][:3]
            print(f"  {name:14s} {0:6d} \uc904 \u2717")
            for c in cand:
                print(f"                        \uc2e4\uc81c: {c[:100]}")
            if not cand:
                print(f"                        ('{kw}' \uac00 \ub4e4\uc5b4\uac04 \uc904 \uc790\uccb4\uac00 \uc5c6\uc74c)")
            bad.append(name)

    blocks = A.parse_annotated(fp, with_stages=True)
    ok = A.resolved(blocks)
    print(f"\n  \ube14\ub85d {len(blocks)}\uac1c \uc911 slack \uc774 \uc77d\ud78c \uacbd\ub85c {len(ok)}\uac1c")
    if ok:
        p = next(iter(ok.values()))
        segs = {}
        for s in p.stages:
            segs[s.segment] = segs.get(s.segment, 0) + 1
        print(f"  \uc608\uc2dc \uacbd\ub85c idx={p.idx} key={p.key}")
        print(f"    slack={p.slack} arrival={p.arrival} required={p.required}")
        print(f"    launch_clk={p.launch_clk} capture_clk={p.capture_clk} "
              f"lib_check={p.lib_check_time}")
        print(f"    stages={len(p.stages)} {segs}")
        missing = [n for n, v in (("arrival", p.arrival), ("required", p.required),
                                  ("launch_clk", p.launch_clk),
                                  ("capture_clk", p.capture_clk),
                                  ("lib_check_time", p.lib_check_time)) if v != v]
        if missing:
            print(f"    (!) NaN \uc778 \ud544\ub4dc: {missing} -- \ud559\uc2b5\uc740 \ub418\uc9c0\ub9cc \ud1a0\ud070 \uc815\ubcf4\uac00 \ube48\ub2e4")
        if not p.stages:
            print("    (!) stage \uac00 0\uac1c -- \uacbd\ub85c \uc778\ucf54\ub354 \uc785\ub825\uc774 \ube44\uc5b4 \ud559\uc2b5\uc774 \ubb34\uc758\ubbf8\ud574\uc9c4\ub2e4")

    print()
    if not ok:
        print("  \ud310\uc815: \u2717 \uacbd\ub85c\ub97c \ud558\ub098\ub3c4 \ubabb \uc77d\uc5c8\ub2e4.")
        print("        \uc704\uc5d0\uc11c \u2717 \uc778 \uc815\uaddc\uc2dd\uc758 '\uc2e4\uc81c' \uc904\uc744 \ubcf4\uace0")
        print("        si_model/parsing/annotated.py \uc0c1\ub2e8\uc744 \uadf8 \ud615\uc2dd\uc5d0 \ub9de\ucd98\ub2e4 (docs/PARSING.md \u00a74).")
        return 1
    if bad:
        print(f"  \ud310\uc815: \u25b3 \uacbd\ub85c\ub294 \uc77d\ud788\uc9c0\ub9cc \ubabb \uc7a1\uc740 \ud56d\ubaa9\uc774 \uc788\ub2e4: {bad}")
        return 0
    print("  \ud310\uc815: \u2713 \uc804\ubd80 \uc815\uc0c1. build \ub85c \uc9c4\ud589\ud574\ub3c4 \ub41c\ub2e4.")
    return 0


def stage_sweep(m: dict, lambdas=(0.0, 0.1, 1.0, 10.0)) -> None:
    """SI \ubcf4\uc870\uc190\uc2e4 \uac00\uc911\uce58 lambda_si \uc2a4\uc715 (slack \uc804\uc6a9, \uc61b sweep.sh).

    SI branch \ub97c \uc5bc\ub9c8\ub098 \ubbff\uc744\uc9c0\ub294 \ub370\uc774\ud130\ub9c8\ub2e4 \ub2e4\ub974\ub2e4. \uac19\uc740 \uc124\uc815\uc73c\ub85c lambda \ub9cc
    \ubc14\uafd4 \ud559\uc2b5\ud574 hidden MAE \ub97c \ube44\uad50\ud55c\ub2e4. \uacb0\uacfc\ub294 runs/_sweep/<\ubaa8\ub378>/lam_<v>/ \ub85c
    \ub530\ub85c \ub098\uac00\ubbc0\ub85c \ubcf8 run \uc744 \ub36e\uc5b4\uc4f0\uc9c0 \uc54a\ub294\ub2e4."""
    import copy
    import json

    if m["task"] != "slack":
        print("  (slew \ubaa8\ub378\uc740 SI branch \uac00 \uc5c6\uc5b4 sweep \ub300\uc0c1\uc774 \uc544\ub2d8 -- \uac74\ub108\ub700)")
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
    with open(fp, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"  wrote {fp}  (\ubcf8 run \uc740 {base_out} \uadf8\ub300\ub85c)")


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
        print(f"    (\uc815\ub2f5 \uc5c6\uc5b4 \uac74\ub108\ub700: {skipped})")
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
    print(f"    \u2500\u2500 weighting \ubcc4 \ud788\ub4e0 (\ucc38\uace0\uc6a9, \uc800\uc7a5 \uc548 \ud568) \u2500\u2500")
    for w in ("plain", "local", "adaptive"):
        c = copy.deepcopy(cfg)
        c["base"]["weighting"] = w
        if w == "local" and not c["base"].get("bandwidth"):
            print(f"       {w:9s} (bandwidth \ubbf8\uc124\uc815)")
            continue
        try:
            loo, _ = fit_field(y, phi, split, coords, c, force_mode=w)
        except Exception as e:
            print(f"       {w:9s} (\ubabb \uc7bc: {repr(e)[:40]})")
            continue
        e = np.array([float(np.nanmean(np.abs(loo[:, ci] - y[:, ci])) * 1000.0)
                      for ci in hid])
        current_label = "  <- \uc9c0\uae08 \uc774\uac83" if w == cur else ""
        print(f"       {w:9s} {e.mean():8.3f} ps  (worst {e.max():7.3f})"
              f"{current_label}")
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
    """One circuit's single weight file: runs/<mode>/<\ud68c\ub85c>/model.pt."""
    return os.path.join(os.path.dirname(m["cfg"]["train"]["out_dir"]), BUNDLE_NAME)


def stage_bundle(models: list) -> None:
    """Pack every temperature's weights for a circuit into ONE file.

    Temperature is a split dimension -- 125C and m25C are fitted separately
    because their BEOL level sets differ and two temperatures cannot support an
    interpolating polynomial. But that is an internal detail: from the outside a
    circuit should be one model, one file, one command. So training still writes
    a per-temperature ``best.pt`` (it needs somewhere to checkpoint mid-run) and
    this stage collects them into ``runs/<mode>/<\ud68c\ub85c>/model.pt``, which is what
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
            print(f"  {design}: \ud559\uc2b5\ub41c \uc628\ub3c4\uac00 \uc5c6\uc5b4 \uac74\ub108\ub700 (train \uba3c\uc800)", flush=True)
            continue
        out = bundle_path(ms[0])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        torch.save({"format": BUNDLE_FORMAT, "design": design,
                    "temps": temps}, out)
        note = f"  (\ubbf8\ud559\uc2b5: {', '.join(missing)})" if missing else ""
        print(f"  {out}  <- \uc628\ub3c4 {len(temps)}\uac1c [{', '.join(sorted(temps))}]{note}",
              flush=True)


def stage_predict(m: dict, corners: str) -> None:
    import numpy as np

    from si_model.compat import load_checkpoint

    out_dir = m["cfg"]["train"]["out_dir"]
    tr = _trainer(m)
    # \ubc30\ud3ec\ub418\ub294 \ub2e8\uc77c \ud30c\uc77c(model.pt)\uc774 \uc788\uc73c\uba74 \uadf8\uac78 \uc4f4\ub2e4. \uc5c6\uc73c\uba74 \ud559\uc2b5 \uc9c1\ud6c4\uc758
    # \uc628\ub3c4\ubcc4 \uccb4\ud06c\ud3ec\uc778\ud2b8\ub85c \ub118\uc5b4\uac04\ub2e4 -- bundle \uc5c6\uc774 train->predict \ub9cc \ub3cc\ub9b0 \uacbd\uc6b0.
    bundle = bundle_path(m)
    if os.path.exists(bundle):
        b = load_checkpoint(bundle, map_location=tr.dev)
        key = str(m["temp"])
        assert key in b["temps"], (
            f"{bundle} \uc5d0 \uc628\ub3c4 {key} \uac00 \uc5c6\ub2e4 (\uc788\ub294 \uac83: {sorted(b['temps'])}). "
            f"run.sh bundle \uc744 \ub2e4\uc2dc \ub3cc\ub9b4 \uac83")
        ck = b["temps"][key]
    else:
        ckpt = os.path.join(out_dir, "best.pt")
        assert os.path.exists(ckpt), f"no checkpoint yet: {ckpt} (train \uba3c\uc800)"
        ck = load_checkpoint(ckpt, map_location=tr.dev)
    tr.model.load_state_dict(ck["model"])
    tr.enc.load_state_dict(ck["enc"])
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
    with open(out_fp, "w", newline="") as out:
        w = csv.writer(out)
        for m in models:
            fp = os.path.join(m["cfg"]["train"]["out_dir"], f"predictions_{corners}.csv")
            if not os.path.exists(fp):
                missing.append(m["name"])
                continue
            with open(fp, newline="") as f:
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
        f"\ud569\uce60 \uc608\uce21 \ud30c\uc77c\uc774 \uc5c6\ub2e4 (predictions_{corners}.csv). predict \uba3c\uc800 \ub3cc\ub9b4 \uac83."
    if missing:
        print(f"  (!) \ube60\uc9c4 \ubaa8\ub378: {missing}")
    print(f"  wrote {out_fp}: {rows} rows, {len(models) - len(missing)}/{len(models)} models")

    summ = {"by_corner": _corner_table(out_fp), "by_model": {}}
    stale = []
    for m in models:
        d = m["cfg"]["train"]["out_dir"]
        sfp, ckpt = os.path.join(d, "summary.json"), os.path.join(d, "best.pt")
        if not os.path.exists(sfp):
            continue
        # train \uc774 \uc911\uac04\uc5d0 \ub04a\uae30\uba74 best.pt \ub294 \uac31\uc2e0\ub418\uc9c0\ub9cc summary.json \uc740 \ud559\uc2b5\uc774
        # \ub05d\uae4c\uc9c0 \uac14\uc744 \ub54c\ub9cc \uc4f0\uc778\ub2e4. \uadf8\ub798\uc11c \uc774\uc804 \uc2e4\ud589\uc758 \uc694\uc57d\uc774 \uc0c8 \uccb4\ud06c\ud3ec\uc778\ud2b8 \uc606\uc5d0
        # \ub0a8\uc544 \uc870\uc6a9\ud788 \uc11e\uc77c \uc218 \uc788\ub2e4. by_corner \ub294 \ubc29\uae08 \ub9cc\ub4e0 \uc608\uce21\uc5d0\uc11c \ubf51\uc73c\ubbc0\ub85c
        # \ud56d\uc0c1 \ub9de\uc9c0\ub9cc, by_model \uc740 \uadf8 \uc61b \ud30c\uc77c\uc774\ub77c \uc9da\uc5b4\uc900\ub2e4.
        if os.path.exists(ckpt) and os.path.getmtime(sfp) < os.path.getmtime(ckpt):
            stale.append(m["name"])
        with open(sfp) as f:
            summ["by_model"][m["name"]] = json.load(f)
    if stale:
        print(f"  (!) by_model \uc774 \uc624\ub798\ub428 (best.pt \ubcf4\ub2e4 \uc774\uc804): {stale}\n"
              f"      \ud559\uc2b5\uc744 \uc911\uac04\uc5d0 \ub04a\uc5c8\uc73c\uba74 \uadf8 \ubaa8\ub378\uc758 by_model \uc218\uce58\ub294 \uc774\uc804 \uc2e4\ud589 \uac83\uc774\ub2e4. "
              f"\ucf54\ub108\ubcc4 \uc131\uc801(by_corner)\uc740 \ubc29\uae08 \uc608\uce21\uc5d0\uc11c \ubf51\uc740 \uac12\uc774\ub77c \uc815\ud655\ud558\ub2e4.")
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summ, f, indent=2)
    print(f"  wrote {out_dir}/summary.json "
          f"(\ucf54\ub108 {len(summ['by_corner'])}\uac1c, \ubaa8\ub378 {len(summ['by_model'])}\uac1c)")
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
    with open(csv_fp, newline="") as f:
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
    print("\n  \ucf54\ub108\ubcc4 \uc131\uc801 (\ubaa8\ub378\uc774 \uc544\ub2c8\ub77c \ucf54\ub108 \uae30\uc900)")
    headers = ("\ud68c\ub85c", "\uc628\ub3c4", "\ucf54\ub108", "\uacbd\ub85c")
    print(f"    {headers[0]:<22}{headers[1]:<6}{headers[2]:<20}"
          f"{headers[3]:>7}{'MAE':>10}{'worst':>10}")
    for r in rows:
        mae = "-" if r["mae_ps"] is None else f"{r['mae_ps']:.2f}ps"
        wst = "-" if r["worst_ps"] is None else f"{r['worst_ps']:.2f}ps"
        print(f"    {r['design']:<22}{r['temp']:<6}{r['corner']:<20}"
              f"{r['n_paths']:>7}{mae:>10}{wst:>10}")
    scored = [r for r in rows if r["mae_ps"] is not None]
    if scored:
        total_label = "\uc804\uccb4"
        print(f"    {total_label:<48}{sum(r['n_paths'] for r in rows):>7}"
              f"{sum(r['mae_ps'] for r in scored) / len(scored):>8.2f}ps"
              f"{max(r['worst_ps'] for r in scored):>8.2f}ps")


# ----------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES, nargs="?", default="help")
    ap.add_argument("--config", default=DEFAULT_PROJECT, help="project config (default: config.yaml)")
    ap.add_argument("--design", default=None, help="\uc774 \ud68c\ub85c\ub9cc")
    ap.add_argument("--temp", default=None, help="\uc774 \uc628\ub3c4\ub9cc")
    ap.add_argument("--corners", default="hidden", choices=["hidden", "seen", "all"])
    ap.add_argument("--file", default=None,
                    help="check \ub2e8\uacc4\uc5d0\uc11c \uac80\uc0ac\ud560 \ub9ac\ud3ec\ud2b8 \ud30c\uc77c (\uc0dd\ub7b5\ud558\uba74 config \uc5d0\uc11c \uccab \ud30c\uc77c)")
    args = ap.parse_args(argv)

    os.chdir(REPO_ROOT)
    if args.stage == "help":
        print(HELP)
        return 0
    p = load_project(args.config)
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
            print(f"\n===== bundle: \ud68c\ub85c\ubcc4 \ub2e8\uc77c \uac00\uc911\uce58 \ud30c\uc77c =====", flush=True)
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
                print(f"!!!!! FAILED {stage}: {m['name']} -- \uacc4\uc18d \uc9c4\ud589", flush=True)

    print("\n" + "=" * 60)
    if failed:
        print(f"\uc644\ub8cc, \ub2e8 \uc2e4\ud328 {len(failed)}\uac74:")
        for what, err in failed:
            print(f"  - {what}: {err}")
        return 1
    print(f"\uc804\ubd80 \uc131\uacf5 ({len(models)} models, stages={list(stages)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
