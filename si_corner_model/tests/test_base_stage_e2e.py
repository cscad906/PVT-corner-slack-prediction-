"""End-to-end `run.sh base`: config file -> engine config -> printed numbers.

Every level-axis bug this session slipped through unit tests and landed in a
real run. All three lived in the seam between the config file and the fit:
`select` and `min_loo_dof` were spelled correctly and never forwarded into the
engine config; `level_values` was baked into the cache at build time, so
editing it changed nothing; and build_design dropped the cfg the level hooks
modified, so the run reported an axis it had not used. Nothing that tests a
function in isolation can see any of those. These go through load_project and
expand, the way a real invocation does.
"""
import json
import os
import sys

import numpy as np
import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from si_model.parsing.keys import corner_label      # noqa: E402
from si_model.run import expand, load_project, stage_base   # noqa: E402

VOLTS = [0.5, 0.54, 0.6, 0.685]
# The middle level does NOT sit halfway: it is at one end, which is the shape
# the company drop turned out to have (mean slack cmax < rcmin < rcmax).
TRUE = {"cmax": -1.0, "rcmin": -0.345, "rcmax": 1.0}


def _write_cache(fp, levels, unmeasured=()):
    pairs = [(v, l) for v in VOLTS for l in levels]
    rng = np.random.RandomState(0)
    y = np.asarray([[1.5 + 0.9 * (v - 0.685) + 1.2 * (v - 0.685) ** 2
                     - 0.035 * TRUE[l] * (1 + 2.5 * (v - 0.685))
                     for v, l in pairs]])
    slack = (y * np.ones((300, 1)) + rng.randn(300, 1) * 0.05
             + rng.randn(300, len(pairs)) * 0.0015).astype(np.float32)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    np.savez_compressed(
        fp,
        corners=np.asarray([corner_label(v, l, "SSPG") for v, l in pairs]),
        # declared coordinates, as build_dataset would have baked them in
        vt=np.asarray([[v, {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}[l]]
                       for v, l in pairs], np.float32),
        slack=slack, si_label=np.zeros_like(slack),
        measured=np.asarray([(v, l) not in unmeasured for v, l in pairs], bool),
        path_keys=np.asarray(["p%d" % i for i in range(300)]))


def _project(root, levels, hidden):
    return {
        "root": str(root), "mode": "setup",
        "designs": ["D_Timing_Report"],
        "temps": [{"tag": "t", "token": "m25", "levels": levels,
                   "hidden_corners": hidden}],
        "corners": {"process": "SSPG", "voltages": VOLTS,
                    "ref_voltage": 0.685, "ref_level": "cmax",
                    "level_values": {"rcmin": -1, "cmax": 0, "rcmax": 1}},
        "split": {"min_seen": 1},
        "files": {"layout": "flat", "annotated_regex": "auto",
                  "crosstalk_subdir": None, "subdir": "auto"},
        "base": {"weighting": "plain"},
        "model": {}, "train": {"epochs": 1},
    }


def _run(tmp_path, monkeypatch, levels, hidden, env=None, base=None,
         unmeasured=()):
    p = _project(tmp_path, levels, hidden)
    if base:
        p["base"].update(base)
    cfg_fp = tmp_path / "config.yaml"
    cfg_fp.write_text(yaml.safe_dump(p), encoding="utf-8")
    for k in ("SI_LEVEL_VALUES", "SI_LEVEL_COORDS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SI_STAGE", "base")
    monkeypatch.chdir(tmp_path)
    m = expand(load_project(str(cfg_fp)))[0]
    _write_cache(m["cfg"]["data"]["cache"], levels, unmeasured)
    stage_base(m)
    return m


def _hidden(capsys):
    out = capsys.readouterr().out
    for line in out.splitlines():
        if "[hidden mean]" in line:
            return float(line.split("]")[1].split()[0]), out
    raise AssertionError("no [hidden mean] line:\n" + out)


THREE = (["rcmax", "cmax", "rcmin"], [[0.5, "cmax"], [0.685, "rcmin"]])
TWO = (["rcmax", "cmax"], [[0.54, "rcmax"], [0.6, "cmax"]])


def test_level_values_env_reaches_the_fit(tmp_path, monkeypatch, capsys):
    """SI_LEVEL_VALUES must change the answer without a rebuild.

    The cache is written with the declared coordinates either way; only the
    config differs. If the override is dropped anywhere between the environment
    and the design matrix, both runs return the same number.
    """
    pin = {"level_coords": "declared", "select_on": "seen_loo"}
    _run(tmp_path, monkeypatch, *THREE, base=pin)
    declared, _ = _hidden(capsys)

    _run(tmp_path, monkeypatch, *THREE, base=pin,
         env={"SI_LEVEL_VALUES": "cmax=-1,rcmin=-0.345,rcmax=1"})
    fitted, out = _hidden(capsys)

    assert "[ENV] corners.level_values" in out
    assert "cmax=-1.000, rcmin=-0.345, rcmax=+1.000" in out
    # the planted coordinates are the true ones, so they must WIN, not merely differ
    assert fitted < declared * 0.6, (declared, fitted)


def test_measured_finds_the_planted_axis(tmp_path, monkeypatch, capsys):
    """`level_coords: measured` must reach the same answer on its own."""
    pin = {"level_coords": "declared", "select_on": "seen_loo"}
    _run(tmp_path, monkeypatch, *THREE, base=pin,
         env={"SI_LEVEL_VALUES": "cmax=-1,rcmin=-0.345,rcmax=1"})
    by_hand, _ = _hidden(capsys)

    _run(tmp_path, monkeypatch, *THREE, base={"select_on": "seen_loo"},
         env={"SI_LEVEL_COORDS": "measured"})
    measured, out = _hidden(capsys)

    assert "[LEVELS] level_coords: measured over" in out
    assert measured == pytest.approx(by_hand, rel=0.02), (by_hand, measured)


def test_two_level_grid_is_untouched(tmp_path, monkeypatch, capsys):
    """A 2-level axis is defined by its own endpoints: any coordinates are an
    affine map of any others, so the fit is identical. This is the 125C case,
    and 'no change' there is the correct outcome, not a broken switch."""
    _run(tmp_path, monkeypatch, *TWO)
    declared, _ = _hidden(capsys)

    _run(tmp_path, monkeypatch, *TWO, env={"SI_LEVEL_COORDS": "measured"})
    measured, out = _hidden(capsys)
    assert "2 levels in this grid, nothing to place" in out

    _run(tmp_path, monkeypatch, *TWO,
         env={"SI_LEVEL_VALUES": "cmax=-1,rcmin=-0.345,rcmax=1"})
    relabelled, _ = _hidden(capsys)

    assert measured == pytest.approx(declared, abs=1e-9)
    assert relabelled == pytest.approx(declared, abs=1e-9)


def test_base_switches_reach_the_engine(tmp_path, monkeypatch, capsys):
    """min_loo_dof must be able to exclude a candidate the default admits."""
    _run(tmp_path, monkeypatch, *THREE, base={"min_loo_dof": 1})
    lo = capsys.readouterr().out
    _run(tmp_path, monkeypatch, *THREE, base={"min_loo_dof": 4})
    hi = capsys.readouterr().out
    assert "skipped (< base.min_loo_dof=4)" in hi
    assert "skipped (< base.min_loo_dof=4)" not in lo


def _write_cache_with_clock(fp, levels, T_of):
    """The same field as _write_cache, but measured at one clock period per
    voltage: slack = T(V) - arrival, and cycle_gap carries T(V).

    This is what a DVFS grid looks like -- slower clock at lower voltage -- and
    what the company drop turned out to be.
    """
    pairs = [(v, l) for v in VOLTS for l in levels]
    rng = np.random.RandomState(0)
    arrival = np.asarray([[0.5 - 0.9 * (v - 0.685) - 1.2 * (v - 0.685) ** 2
                           + 0.035 * TRUE[l] * (1 + 2.5 * (v - 0.685))
                           for v, l in pairs]])
    T = np.asarray([[T_of[v] for v, _ in pairs]])
    slack = ((T - arrival) * np.ones((300, 1)) + rng.randn(300, 1) * 0.05
             + rng.randn(300, len(pairs)) * 0.0015).astype(np.float32)
    gap = (T * np.ones((300, 1))).astype(np.float32)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    np.savez_compressed(
        fp,
        corners=np.asarray([corner_label(v, l, "SSPG") for v, l in pairs]),
        vt=np.asarray([[v, {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}[l]]
                       for v, l in pairs], np.float32),
        slack=slack, si_label=np.zeros_like(slack), cycle_gap=gap,
        measured=np.ones(len(pairs), bool),
        path_keys=np.asarray(["p%d" % i for i in range(300)]))


def test_period_normalisation_makes_the_clock_plan_irrelevant(tmp_path, monkeypatch,
                                                              capsys):
    """A grid measured at one clock period per voltage must give the same base
    error as the same circuit measured at one period throughout.

    slack = T - (delays), and T is a design choice. Fitting slack directly fits
    T(V) - delay(V), so the frequency plan ends up inside the model: harmless
    between the measured voltages, fatal outside them, where extrapolating means
    extrapolating the plan. The fix is the identity slack(T') = slack(T) +
    N*(T'-T), applied per corner before the fit and undone after, so this test
    is an INVARIANCE: change only the plan and the error must not move.

    Measured here: the same circuit under a flat 2.0 ns plan and under
    3.0/2.1/2.0/2.0 gives the same held-out error to 0.2 ps with normalisation,
    and 100x worse without it. The reported values stay native -- the measured
    slack printed for a corner is the slack that corner has, not a rebased one.
    """
    levels, hidden = TWO
    flat = {v: 2.0 for v in VOLTS}
    dvfs = {0.5: 3.0, 0.54: 2.1, 0.6: 2.0, 0.685: 2.0}

    def run(T_of, base=None, hide=hidden):
        p = _project(tmp_path, levels, hide)
        p["base"].update(base or {})
        cfg_fp = tmp_path / "config.yaml"
        cfg_fp.write_text(yaml.safe_dump(p), encoding="utf-8")
        monkeypatch.setenv("SI_STAGE", "base")
        monkeypatch.chdir(tmp_path)
        m = expand(load_project(str(cfg_fp)))[0]
        _write_cache_with_clock(m["cfg"]["data"]["cache"], levels, T_of)
        stage_base(m)
        return _hidden(capsys)

    # hold out the LOWEST voltage row, which is where the plan matters
    low = [[0.5, l] for l in levels]
    e_flat, _ = run(flat, hide=low)
    e_dvfs, out = run(dvfs, hide=low)
    e_off, _ = run(dvfs, base={"period_norm": "off"}, hide=low)

    assert "[PERIOD]" in out, out
    assert abs(e_dvfs - e_flat) < 0.2, (e_flat, e_dvfs)
    assert e_off > 20 * max(e_dvfs, 1.0), (e_dvfs, e_off)

    # A config line copied from this key's own documentation says `off`, and
    # YAML 1.1 -- PyYAML -- makes a bare `off` the BOOLEAN false. So the value
    # arrives as False, not "off", and refusing it sends the reader back to ask
    # what to type. Both spellings must turn normalisation off.
    assert yaml.safe_load("period_norm: off")["period_norm"] is False
    e_bool, _ = run(dvfs, base={"period_norm": False}, hide=low)
    assert abs(e_bool - e_off) < 1e-6, (e_bool, e_off)
    # and the boolean true is the other one, not an error
    e_true, _ = run(dvfs, base={"period_norm": True}, hide=low)
    assert abs(e_true - e_dvfs) < 1e-6, (e_true, e_dvfs)

    # ONE story per screen. The candidate table refits every candidate, so it
    # has to refit the field that was actually fitted: it used to be handed the
    # measured field after the fit had normalised, and printed hidden errors
    # from a different problem -- ~1650 ps on the company drop -- directly under
    # a [hidden mean] of ~100. Whoever read the screen reported the big number,
    # and the correction looked broken when it was working.
    _, out2 = run(dvfs, hide=low)
    rows = [l for l in out2.splitlines()
            if l.strip().startswith("v^") and "hidden" in l]
    assert rows, out2
    hid_col = [float(l.split("hidden")[1].split("(")[0]) for l in rows]
    mean = [float(l.split("]")[1].split()[0]) for l in out2.splitlines()
            if "[hidden mean]" in l][0]
    chosen = [h for h, l in zip(hid_col, rows) if "<- chosen" in l]
    assert chosen and abs(chosen[0] - mean) < 0.05, (chosen, mean)
    assert max(hid_col) < 10 * max(mean, 1.0), (max(hid_col), mean)

    # and the numbers printed are the slack each corner really has: the 0.5 V
    # row was measured at 3.0 ns, so its mean measured slack must be ~1 ns
    # HIGHER than the flat-plan version, not normalised away
    hid_lines = [l.split() for l in out.splitlines()
                 if l.strip().startswith("SSPG") and " hidden " in l]
    assert hid_lines, out
    meas = [float(f[3]) for f in hid_lines]
    assert all(mv > 1000.0 for mv in meas), hid_lines
    assert "clock 3.0000 ns" in out and "clock 2.0000 ns" in out
    assert "NOT THE SAME AT EVERY VOLTAGE" in out


def test_compute_base_returns_native_slack_not_the_rebased_fit(tmp_path, monkeypatch):
    """The training path normalises to fit and must convert BACK.

    compute_base feeds two things forward: base_hat, which every prediction is
    built on, and resid, which is what the network is taught to correct. If the
    offset is not added back, both silently become "slack at the anchor's
    period" while every measurement, report and summary stays at each corner's
    own -- a whole-nanosecond error that no test of the base stage would see,
    because that stage adds it back separately.

    So this asserts on the numbers compute_base hands over, not on what is
    printed: at a corner measured with a 1 ns longer clock, base_hat has to sit
    ~1 ns higher, and the residual has to stay small.
    """
    from si_model.training.loo import compute_base, make_split

    levels, _ = TWO
    dvfs = {0.5: 3.0, 0.54: 2.1, 0.6: 2.0, 0.685: 2.0}
    p = _project(tmp_path, levels, [[0.5, l] for l in levels])
    cfg_fp = tmp_path / "config.yaml"
    cfg_fp.write_text(yaml.safe_dump(p), encoding="utf-8")
    monkeypatch.setenv("SI_STAGE", "base")
    monkeypatch.chdir(tmp_path)
    m = expand(load_project(str(cfg_fp)))[0]
    _write_cache_with_clock(m["cfg"]["data"]["cache"], levels, dvfs)

    ds = dict(np.load(m["cfg"]["data"]["cache"]))
    split = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
    art = compute_base(ds, split, m["cfg"])

    lo = [ci for ci in range(len(split.corners))
          if abs(float(split.vt[ci, 0]) - 0.5) < 1e-9]
    hi = [ci for ci in range(len(split.corners))
          if abs(float(split.vt[ci, 0]) - 0.685) < 1e-6]   # vt is float32
    assert lo and hi
    for ci in lo:
        meas = float(np.mean(ds["slack"][:, ci]))
        fit = float(np.mean(art.base_hat[:, ci]))
        # measured at 3.0 ns against the anchor's 2.0: the native value is a
        # whole nanosecond above the rebased one, and base_hat must be the
        # native one
        assert abs(fit - meas) < 0.05, (fit, meas)
        assert abs(fit - (meas - 1.0)) > 0.5, (fit, meas)
    assert float(np.max(np.abs(art.resid))) < 0.05, float(np.max(np.abs(art.resid)))
    # the anchor's own period needs no shift, so nothing moved there
    for ci in hi:
        assert abs(float(np.mean(art.base_hat[:, ci]))
                   - float(np.mean(ds["slack"][:, ci]))) < 0.05


def test_base_prints_the_curve_it_is_asked_to_follow(tmp_path, monkeypatch, capsys):
    """The base stage must print the base value and the measured value at EVERY
    corner, and the measured field against voltage.

    Without them an error is a dead end: 1490 ps at every candidate order could
    be a fit that misses a curve, a corner measured under different conditions
    (which shifts every path by a constant and makes every basis wrong by the
    same amount), or a corner that no smooth continuation can reach. Those need
    opposite fixes and the difference is visible only in the values.

    The planted field is monotone in voltage, so the printed rows must be too,
    and the held-out row must be marked and must carry a measurement.
    """
    levels, hidden = TWO
    _run(tmp_path, monkeypatch, levels, hidden)
    out = capsys.readouterr().out

    # one row per corner in the grid, seen and held-out alike -- the base is one
    # surface over the whole grid, and a seen corner's value is a number someone
    # asks for too
    rows = [l.split() for l in out.splitlines()
            if l.strip().startswith("SSPG") and len(l.split()) >= 5]
    assert len(rows) == len(VOLTS) * len(levels), rows
    assert {r[1] for r in rows} == {"seen", "hidden"}, rows
    hid = [r for r in rows if r[1] == "hidden"]
    assert len(hid) == len(hidden), hid
    for f in rows:
        # The error is the mean of the per-path gaps; the two printed numbers
        # are means. Per-path gaps of opposite sign cancel in the means, so the
        # gap between them can only be SMALLER -- never larger. A fitted value
        # further from the measured one than the reported error would mean the
        # three numbers do not come from the same corner.
        fit, meas, e = float(f[2]), float(f[3]), float(f[4])
        assert abs(fit - meas) <= e + 0.05, f
        assert meas > 0, f                 # the planted field is positive

    vrows = [l for l in out.splitlines()
             if l.strip()[:1].isdigit() and " V " in l]
    assert len(vrows) == len(VOLTS), vrows
    vals = [float(x.rstrip("*")) for l in vrows for x in l.split("V")[1].split()]
    assert all(v > 0 for v in vals), vrows
    # the planted curve rises with voltage, so the printed means must
    firsts = [float(l.split("V")[1].split()[0].rstrip("*")) for l in vrows]
    assert firsts == sorted(firsts), firsts
    # the held-out row is the one marked, and only it
    marked = [l for l in vrows if "*" in l]
    assert len(marked) == len({v for v, _ in hidden}), marked
    for l in marked:
        assert ("%.3f" % hidden[0][0]) in l or ("%.3f" % hidden[1][0]) in l, l


def test_unknown_base_key_is_an_error(tmp_path, monkeypatch):
    with pytest.raises(AssertionError, match="unknown base key"):
        _run(tmp_path, monkeypatch, *THREE, base={"min_loo_doff": 2})


def test_every_corner_shows_its_base_including_one_never_measured(
        tmp_path, monkeypatch, capsys):
    """A corner with no measurement still has a base, and that value is the
    answer to the only question such a corner can be asked -- "what does this
    say at a corner nobody ran". It used to be a name in a footnote: the one
    corner whose number cannot be got any other way was the one corner the
    stage declined to print.
    """
    levels = ["rcmax", "cmax"]
    _run(tmp_path, monkeypatch, levels, [[0.54, "rcmax"]],
         unmeasured=[(0.6, "cmax")])
    out = capsys.readouterr().out

    rows = {l.split()[0]: l.split() for l in out.splitlines()
            if l.strip().startswith("SSPG")}
    assert len(rows) == len(VOLTS) * len(levels), rows

    q = rows["SSPG_0p6V_cmax"]
    assert "no truth" in " ".join(q), q
    base_v = float(q[2])
    # it is a real prediction, on the same curve as the rest -- between the
    # neighbouring voltages' values, not a placeholder
    lo = float(rows["SSPG_0p54V_cmax"][2])
    hi = float(rows["SSPG_0p685V_cmax"][2])
    assert lo < base_v < hi, (lo, base_v, hi)

    # and it is excluded from the scores, which are errors against a
    # measurement it does not have
    assert "[hidden mean]" in out and "[seen-LOO   ]" in out


def test_base_predicts_a_corner_that_was_never_measured(tmp_path, monkeypatch,
                                                        capsys):
    """`base --at 0.52:rcmax`: the OLS base answers for a corner with no
    library.

    This is the deliverable case, not a convenience. A corner reached by
    PrimeTime voltage scaling has no library and therefore no measurement
    anywhere in the grid -- there is nothing to hold out, so `hidden_corners`
    cannot reach it and `predict --at` would need a trained model first. The
    base can answer, because a fit is defined wherever its coordinates are and
    fit_base already evaluates at every corner of the design matrix.

    It joins the grid exactly as a config `data.query_corners` entry does --
    NaN measurement, measured=False, forced hidden, out of every score -- but
    without a rebuild, which on this data is hours.
    """
    import numpy as np
    from si_model.run import stage_base

    levels = ["rcmax", "cmax"]
    m = _run(tmp_path, monkeypatch, levels, [[0.54, "rcmax"]])
    capsys.readouterr()
    stage_base(m, save=True, at=[(0.52, "rcmax")])
    out = capsys.readouterr().out

    assert "[AT] predicting 1 unmeasured corner(s): SSPG_0p52V_rcmax" in out
    row = [l.split() for l in out.splitlines()
           if l.strip().startswith("SSPG_0p52V_rcmax")]
    assert row and "no" in row[0] and "truth" in row[0], out
    base_v = float(row[0][2])
    # a real extrapolation below the measured grid, on the same curve: the
    # planted field rises with voltage, so 0.52 V must sit below 0.54 V
    at54 = [float(l.split()[2]) for l in out.splitlines()
            if l.strip().startswith("SSPG_0p54V_rcmax")][0]
    assert 0 < base_v < at54, (base_v, at54)

    z = np.load(os.path.join("runs", "setup", "D_Timing_Report", "t",
                             "predictions_base.npz"), allow_pickle=False)
    labels = [str(x) for x in z["corners"]]
    i = labels.index("SSPG_0p52V_rcmax")
    assert not z["measured"][i], "no measurement behind it"
    assert np.isfinite(z["model_ps"][:, i]).all(), "but a prediction for it"
    assert not np.isfinite(z["truth_ps"][:, i]).any()

    # a corner the grid already HAS is left alone -- replacing it with a NaN
    # column would throw away the data the fit is built on
    stage_base(m, at=[(0.54, "rcmax")])
    assert "already in the grid" in capsys.readouterr().out
