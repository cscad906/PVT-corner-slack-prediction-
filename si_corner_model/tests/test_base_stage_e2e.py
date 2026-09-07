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


def _write_cache(fp, levels):
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
        measured=np.ones(len(pairs), bool),
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


def _run(tmp_path, monkeypatch, levels, hidden, env=None, base=None):
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
    _write_cache(m["cfg"]["data"]["cache"], levels)
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
    _run(tmp_path, monkeypatch, *THREE)
    declared, _ = _hidden(capsys)

    _run(tmp_path, monkeypatch, *THREE,
         env={"SI_LEVEL_VALUES": "cmax=-1,rcmin=-0.345,rcmax=1"})
    fitted, out = _hidden(capsys)

    assert "[ENV] corners.level_values" in out
    assert "cmax=-1.000, rcmin=-0.345, rcmax=+1.000" in out
    # the planted coordinates are the true ones, so they must WIN, not merely differ
    assert fitted < declared * 0.6, (declared, fitted)


def test_measured_finds_the_planted_axis(tmp_path, monkeypatch, capsys):
    """`level_coords: measured` must reach the same answer on its own."""
    _run(tmp_path, monkeypatch, *THREE,
         env={"SI_LEVEL_VALUES": "cmax=-1,rcmin=-0.345,rcmax=1"})
    by_hand, _ = _hidden(capsys)

    _run(tmp_path, monkeypatch, *THREE, env={"SI_LEVEL_COORDS": "measured"})
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


def test_unknown_base_key_is_an_error(tmp_path, monkeypatch):
    with pytest.raises(AssertionError, match="unknown base key"):
        _run(tmp_path, monkeypatch, *THREE, base={"min_loo_doff": 2})
