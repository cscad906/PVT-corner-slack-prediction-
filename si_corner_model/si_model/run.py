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
  sweep    lambda_si in {0, 0.1, 1, 10} -> runs/_sweep/... (slack 전용, 비교용)
  merge    all members    -> runs/_all/predictions_<corners>.csv + summary.json
  all      build, base, train, bundle, predict, merge  (sweep 은 명시할 때만)

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
si_corner_model — 명령은 `bash scripts/run.sh <단계>` 하나뿐이다.
설정은 config.yaml 하나뿐이다. 처음이면 docs/START.md 를 위에서 아래로.

  단계 (보통 이 순서)
    recon      데이터 정찰. 폴더/파일명/본문을 훑어 recon_out.txt 로 저장
               -> 여기 값을 config.yaml 에 옮겨 적는다
    check      리포트 한 개를 파서에 통과시켜 어느 줄이 잡히고 안 잡히는지 보고
               -> 본문 형식이 다를 때(SSTA 로 열/행이 늘었을 때) 여기부터
    list       config 를 펼쳐 "뭐가 어떤 설정으로 돌지" 출력. 파일 안 건드림
               -> 코너 수, seen/hidden, 다항식 파라미터 수까지 검산해줌
    build      리포트 -> cache/<회로>/<온도>/dataset.npz          (numpy만 필요)
    base       OLS base 오차만 출력. base 수치는 여기서만 나온다  (numpy만, 수 초)
               -> 학습 전에 데이터가 제대로 파싱됐는지 확인하는 단계
    train      학습 -> runs/<회로>/<온도>/best.pt + summary.json   (torch/GPU)
    bundle     온도별 가중치를 회로당 한 파일로 -> runs/<회로>/model.pt
    predict    저장된 가중치로 예측만 -> predictions_<corners>.csv
    merge      전 회로·전 온도 예측을 runs/_all/ 로 합침
    all        build -> base -> train -> bundle -> predict -> merge
    sweep      lambda_si {0, 0.1, 1, 10} 비교 -> runs/_sweep/ (slack 전용)

  옵션
    --design <회로>          그 회로만
    --temp <온도tag>         그 온도만
    --corners hidden|seen|all   predict/merge 대상 코너 (기본 hidden)
    --config <파일>          다른 프로젝트 config (기본 config.yaml)

  예시
    bash scripts/run.sh recon
    bash scripts/run.sh check                  # 형식이 의심스러우면 build 전에
    bash scripts/run.sh check --file <리포트>
    bash scripts/run.sh list
    bash scripts/run.sh all
    bash scripts/run.sh base --design cpu
    bash scripts/run.sh train --design cpu --temp 125
    bash scripts/run.sh predict --corners all

  파일 고치지 않고 경로만 바꾸기
    SI_ROOT=/real/path SI_DESIGNS=cpu,gpu bash scripts/run.sh list

  문서
    docs/START.md    도착해서 처음부터 (폴더 구조 케이스별)
    docs/CONFIG.md   config.yaml 키 전부 + 코너 선정 + 에러표
    docs/OLS.md      base 튜닝
    docs/PARSING.md  리포트 파싱 / FIXED_PATH 문제 / npz 직접 만들기
"""


# ------------------------------------------------------------------ expansion
def load_project(fp: str) -> dict:
    with open(fp) as f:
        p = yaml.safe_load(f) or {}
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
          chipA: {}                                  # 전역 그대로
          chipB:
            files: {subdir: reports}                 # 이 회로만 리포트 위치가 다름
          chipC:
            corners: {voltages: [0.5, 0.6, 0.685]}   # 이 회로만 전압이 3개
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
            f"  -> fix `root:` in config.yaml, or run with SI_ROOT=/real/path")
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
        f"corners.hidden_per_voltage={n} 는 1 이상, 레벨 수({len(levels)}) 미만이어야 한다 "
        f"-- 그 전압의 모든 레벨을 숨기면 앵커가 남지 않는다")
    out = []
    for i, v in enumerate(sorted(float(x) for x in volts)):
        picked, j = [], 0
        while len(picked) < n and j < 2 * len(levels):
            lv = levels[(i + j) % len(levels)]
            j += 1
            if lv in picked:
                continue
            if abs(v - ref_v) < 1e-9 and lv == ref_lv:
                continue                       # 앵커 코너는 숨기지 않는다
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
            if len(S) - phi.shape[1] < 1:            # 자유도 0 -> seen-LOO 가 무의미
                continue
            loo, _ = fit_field(y, phi, sp, coords, c)
            err = float(np.nanmean(np.abs(loo[:, S] - y[:, S])))
            tried.append((err, vo, cross, cmd, len(names) + 1))
            if best is None or err < best[0]:
                best = (err, vo, cross, cmd, names)
    assert best is not None, (
        "쓸 수 있는 기저가 없다 -- seen 코너가 너무 적다. 홀드아웃을 줄이거나 "
        "코너를 늘릴 것")
    err, vo, cross, cmd, names = best
    if verbose:
        print(f"[BASIS] seen-LOO 로 선택: v^{vo} cross={cross}"
              + (f"(deg{cmd})" if cross else "")
              + f" -> {len(names) + 1} 파라미터, seen-LOO {err * 1000:.2f} ps", flush=True)
        for e, v, cr, cd, k in sorted(tried):
            print(f"          v^{v} cross={str(cr):5s} {k}파라미터  {e * 1000:8.2f} ps", flush=True)
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

    # setup 과 hold 는 리포트 위치도 출력 위치도 갈라져야 한다. 예전에는 그 네
    # 군데(files.subdir / files.crosstalk_subdir / out.cache / out.runs)를 각각
    # 손으로 고쳐야 했고, subdir 만 바꾸고 out 을 잊으면 hold 결과가 setup 캐시와
    # run 을 조용히 덮어썼다. 이제 `mode` 한 줄이 넷 다 정한다.
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
                f"temp {tag}: corners.ref_level {ref_lv!r} 가 이 온도의 levels {levels} 에 없다 "
                f"-- 모든 온도에 존재하는 레벨을 앵커로 쓸 것")

            # ---- holdout, resolved PER TEMPERATURE ----------------------
            ho = holdout_for(co, t)
            seen_decl = [float(v) for v in ho.get("seen_voltages") or []]
            hidden_v = [float(v) for v in ho.get("hidden_voltages") or []]
            assert not (seen_decl and hidden_v), (
                f"temp {tag}: seen_voltages 와 hidden_voltages 중 하나만 쓸 것")
            seen_v = seen_decl or [v for v in volts
                                   if not any(abs(v - h) < 1e-9 for h in hidden_v)]
            assert any(abs(ref_v - v) < 1e-9 for v in seen_v), (
                f"temp {tag}: corners.ref_voltage {ref_v} 가 숨겨졌다 (seen = {seen_v}). "
                f"앵커 전압은 항상 seen 이어야 한다")
            hidden_lv = [str(x) for x in ho.get("hidden_levels") or []]
            assert ref_lv not in hidden_lv, (
                f"temp {tag}: ref_level {ref_lv!r} 는 hidden_levels 에 넣을 수 없다")
            for lv in hidden_lv:
                assert lv in levels, (
                    f"temp {tag}: hidden_levels 의 {lv!r} 가 이 온도의 levels {levels} 에 없다")
            hidden_corners = [list(x) for x in ho.get("hidden_corners") or []]
            if ho.get("hidden_per_voltage"):
                assert not hidden_corners, (
                    f"temp {tag}: hidden_per_voltage 와 hidden_corners 는 같이 쓰지 않는다")
                hidden_corners = spread_hidden(seen_v if seen_decl else volts,
                                               levels, int(ho["hidden_per_voltage"]),
                                               ref_v, ref_lv)
            for hv, hl in hidden_corners:
                assert str(hl) in levels, (
                    f"temp {tag}: hidden_corners 의 레벨 {hl!r} 가 이 온도의 "
                    f"levels {levels} 에 없다 -- 온도마다 레벨이 다르므로 "
                    f"holdout 도 temps[] 안에서 따로 적어야 한다")
                assert not (abs(float(hv) - ref_v) < 1e-9 and str(hl) == ref_lv), (
                    f"temp {tag}: 앵커 코너 ({ref_v}, {ref_lv}) 는 숨길 수 없다")

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
                     "order": _order(b.get("v_order"), len(seen_v), 3),
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
                assert b.get("bandwidth"), "base.weighting: local 이면 base.bandwidth 필요"
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
    """무엇이 어떤 설정으로 돌지 전부 찍는다 -- 실행 전 검산용 (파일은 안 건드림).

    특히 seen/hidden 코너를 실제로 세어 보여준다: 코너 선정이 config 의도대로
    되었는지, 다항식 파라미터 수보다 seen 이 충분한지가 여기서 바로 보인다.
    """
    m0 = models[0]
    co = project_for(p, m0["design"])["corners"]
    print(f"root    : {p['root']}")
    print(f"task    : {m0['task']}    models: {len(models)}    process: {co['process']}")
    print(f"voltages: {co['voltages']}    levels: {co['level_values']}")
    print(f"anchor  : {co['ref_voltage']}V x {co['ref_level']}  (항상 seen)")
    if isinstance(p.get("designs"), dict):
        print("(designs 가 회로별 override 로 선언됨 -- 아래 값은 회로마다 다를 수 있다)")
    for m in models:
        d, s, ax = m["cfg"]["data"], m["cfg"]["split"], m["cfg"]["base"]["axes"]
        si = "SI:on " if d.get("crosstalk_dir") else "SI:off"
        print(f"\n  ── {m['name']}  [{si}]")
        print(f"     reports : {d['annotated_dir']}")
        print(f"     levels  : {d['rc_corners']}   ref: {d['ref_corner']}   temp token: {d['temp']!r}")
        print(f"     out     : {d['cache']}  |  {m['cfg']['train']['out_dir']}")

        # 예상 코너 수 / 다항식 크기 -- 실제 파싱 전에 산수로 미리 검산
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
            print(f"     hidden  : {len(hid)}개 "
                  + ", ".join(_lab(v, lv, dco["process"]) for v, lv in hid[:6])
                  + (" ..." if len(hid) > 6 else ""))
        else:
            print("     hidden  : 없음 (query_corners 만 예측 대상)")
        from si_model.config import expand_terms
        n_lv = len({lv for _, lv in seen})
        n_v = len({v for v, _ in seen})
        exps, names, dropped = expand_terms(m["cfg"], [n_v, n_lv])
        npar = len(exps) + 1
        flag = "  ⚠ seen 이 파라미터 수 이하 -- 차수를 낮추거나 홀드아웃을 줄일 것" \
            if len(seen) <= npar else ""
        print(f"     corners : 전체 {total} = seen {len(seen)} + hidden {total - len(seen)}"
              f"   (min_seen 가드 {s['min_seen']})")
        print(f"     basis   : v^{ax[0]['order']} x level^{ax[1]['order']} 까지 "
              f"-> 최대 {npar} 파라미터 {names}{flag}")
        print("               (최종 기저는 build 때 seen-LOO 로 선택된다 -- run.sh base 로 확인)")
        if dropped:
            print(f"               (레벨 부족으로 자동 제거: {dropped})")
        print(f"     base    : weighting={m['cfg']['base']['weighting']}"
              f"  cross_max_degree={m['cfg']['base']['cross_max_degree']}")
        if os.path.isdir(d["annotated_dir"]):
            n = sum(len(f) for _, _, f in os.walk(d["annotated_dir"]))
            print(f"     files   : 디렉토리 존재, 파일 {n}개")
        else:
            print("     files   : (!) 디렉토리 없음 — root / designs / files.subdir 확인")


def stage_check(models: list, fp: "str | None" = None) -> int:
    """리포트 파일 하나를 파서에 통과시켜 '어느 정규식이 몇 줄을 잡았는지' 보고한다.

    본문 형식이 다를 때(SSTA 로 열이 늘었다든지) 무엇을 고쳐야 하는지 추측하지
    않아도 되게 하는 것이 목적이다. 못 잡은 정규식에 대해서는 그 키워드가 들어간
    실제 줄을 같이 찍어주므로, 기대 형식과 실제 형식을 나란히 놓고 볼 수 있다.
    """
    from si_model.parsing import annotated as A
    from si_model.parsing.discovery import discover_annotated

    if fp is None:
        for m in models:
            try:
                found = discover_annotated(m["cfg"])
            except Exception as e:
                print(f"  ({m['name']}: 탐색 실패 {e})")
                continue
            if found:
                fp = sorted(found.values())[0]
                break
    assert fp, "검사할 리포트를 찾지 못했다 -- 파일 경로를 직접 주거나 config 를 고칠 것"
    print(f"file : {fp}")
    with open(fp, errors="ignore") as f:
        lines = f.readlines()
    print(f"lines: {len(lines)}\n")

    # (이름, 정규식, 못 잡았을 때 보여줄 후보 줄을 고르는 키워드)
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
            print(f"  {name:14s} {len(hit):6d} 줄 ✓   예: {hit[0].strip()[:90]}")
        else:
            cand = [l.rstrip("\n") for l in lines if kw in l][:3]
            print(f"  {name:14s} {0:6d} 줄 ✗")
            for c in cand:
                print(f"                        실제: {c[:100]}")
            if not cand:
                print(f"                        ('{kw}' 가 들어간 줄 자체가 없음)")
            bad.append(name)

    blocks = A.parse_annotated(fp, with_stages=True)
    ok = A.resolved(blocks)
    print(f"\n  블록 {len(blocks)}개 중 slack 이 읽힌 경로 {len(ok)}개")
    if ok:
        p = next(iter(ok.values()))
        segs = {}
        for s in p.stages:
            segs[s.segment] = segs.get(s.segment, 0) + 1
        print(f"  예시 경로 idx={p.idx} key={p.key}")
        print(f"    slack={p.slack} arrival={p.arrival} required={p.required}")
        print(f"    launch_clk={p.launch_clk} capture_clk={p.capture_clk} "
              f"lib_check={p.lib_check_time}")
        print(f"    stages={len(p.stages)} {segs}")
        missing = [n for n, v in (("arrival", p.arrival), ("required", p.required),
                                  ("launch_clk", p.launch_clk),
                                  ("capture_clk", p.capture_clk),
                                  ("lib_check_time", p.lib_check_time)) if v != v]
        if missing:
            print(f"    (!) NaN 인 필드: {missing} -- 학습은 되지만 토큰 정보가 빈다")
        if not p.stages:
            print("    (!) stage 가 0개 -- 경로 인코더 입력이 비어 학습이 무의미해진다")

    print()
    if not ok:
        print("  판정: ✗ 경로를 하나도 못 읽었다.")
        print("        위에서 ✗ 인 정규식의 '실제' 줄을 보고")
        print("        si_model/parsing/annotated.py 상단을 그 형식에 맞춘다 (docs/PARSING.md §4).")
        return 1
    if bad:
        print(f"  판정: △ 경로는 읽히지만 못 잡은 항목이 있다: {bad}")
        return 0
    print("  판정: ✓ 전부 정상. build 로 진행해도 된다.")
    return 0


def stage_sweep(m: dict, lambdas=(0.0, 0.1, 1.0, 10.0)) -> None:
    """SI 보조손실 가중치 lambda_si 스윕 (slack 전용, 옛 sweep.sh).

    SI branch 를 얼마나 믿을지는 데이터마다 다르다. 같은 설정으로 lambda 만
    바꿔 학습해 hidden MAE 를 비교한다. 결과는 runs/_sweep/<모델>/lam_<v>/ 로
    따로 나가므로 본 run 을 덮어쓰지 않는다."""
    import copy
    import json

    if m["task"] != "slack":
        print("  (slew 모델은 SI branch 가 없어 sweep 대상이 아님 -- 건너뜀)")
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
    print(f"  wrote {fp}  (본 run 은 {base_out} 그대로)")


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
        print(f"    (정답 없어 건너뜀: {skipped})")


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
    """One circuit's single weight file: runs/<mode>/<회로>/model.pt."""
    return os.path.join(os.path.dirname(m["cfg"]["train"]["out_dir"]), BUNDLE_NAME)


def stage_bundle(models: list) -> None:
    """Pack every temperature's weights for a circuit into ONE file.

    Temperature is a split dimension -- 125C and m25C are fitted separately
    because their BEOL level sets differ and two temperatures cannot support an
    interpolating polynomial. But that is an internal detail: from the outside a
    circuit should be one model, one file, one command. So training still writes
    a per-temperature ``best.pt`` (it needs somewhere to checkpoint mid-run) and
    this stage collects them into ``runs/<mode>/<회로>/model.pt``, which is what
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
            print(f"  {design}: 학습된 온도가 없어 건너뜀 (train 먼저)", flush=True)
            continue
        out = bundle_path(ms[0])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        torch.save({"format": BUNDLE_FORMAT, "design": design,
                    "temps": temps}, out)
        note = f"  (미학습: {', '.join(missing)})" if missing else ""
        print(f"  {out}  <- 온도 {len(temps)}개 [{', '.join(sorted(temps))}]{note}",
              flush=True)


def stage_predict(m: dict, corners: str) -> None:
    import numpy as np

    from si_model.compat import load_checkpoint

    out_dir = m["cfg"]["train"]["out_dir"]
    tr = _trainer(m)
    # 배포되는 단일 파일(model.pt)이 있으면 그걸 쓴다. 없으면 학습 직후의
    # 온도별 체크포인트로 넘어간다 -- bundle 없이 train->predict 만 돌린 경우.
    bundle = bundle_path(m)
    if os.path.exists(bundle):
        b = load_checkpoint(bundle, map_location=tr.dev)
        key = str(m["temp"])
        assert key in b["temps"], (
            f"{bundle} 에 온도 {key} 가 없다 (있는 것: {sorted(b['temps'])}). "
            f"run.sh bundle 을 다시 돌릴 것")
        ck = b["temps"][key]
    else:
        ckpt = os.path.join(out_dir, "best.pt")
        assert os.path.exists(ckpt), f"no checkpoint yet: {ckpt} (train 먼저)"
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
        f"합칠 예측 파일이 없다 (predictions_{corners}.csv). predict 먼저 돌릴 것."
    if missing:
        print(f"  (!) 빠진 모델: {missing}")
    print(f"  wrote {out_fp}: {rows} rows, {len(models) - len(missing)}/{len(models)} models")

    summ = {}
    for m in models:
        sfp = os.path.join(m["cfg"]["train"]["out_dir"], "summary.json")
        if os.path.exists(sfp):
            with open(sfp) as f:
                summ[m["name"]] = json.load(f)
    if summ:
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump(summ, f, indent=2)
        print(f"  wrote {out_dir}/summary.json ({len(summ)} models)")
    return out_fp


# ----------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES, nargs="?", default="help")
    ap.add_argument("--config", default=DEFAULT_PROJECT, help="project config (default: config.yaml)")
    ap.add_argument("--design", default=None, help="이 회로만")
    ap.add_argument("--temp", default=None, help="이 온도만")
    ap.add_argument("--corners", default="hidden", choices=["hidden", "seen", "all"])
    ap.add_argument("--file", default=None,
                    help="check 단계에서 검사할 리포트 파일 (생략하면 config 에서 첫 파일)")
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
            print(f"\n===== bundle: 회로별 단일 가중치 파일 =====", flush=True)
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
                print(f"!!!!! FAILED {stage}: {m['name']} -- 계속 진행", flush=True)

    print("\n" + "=" * 60)
    if failed:
        print(f"완료, 단 실패 {len(failed)}건:")
        for what, err in failed:
            print(f"  - {what}: {err}")
        return 1
    print(f"전부 성공 ({len(models)} models, stages={list(stages)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
