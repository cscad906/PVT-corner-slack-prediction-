"""scripts/plot.py -- the scatter and rank-movement figures.

It runs on another machine than the pipeline does (a laptop, a login node), so
what is tested here is mostly the ways it can be run WRONG: a tree with no
predictions in it, a corner nobody measured, a grid too short to have a
trajectory. Each of those has to end in a sentence and a non-zero status, not a
traceback -- the script is the last thing in the chain and whoever runs it is
usually not the person who wrote the config.
"""
import os
import subprocess
import sys

import numpy as np
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


def _write(runs, design, temp, corners, truth, model, keys=None, seen=None):
    d = os.path.join(runs, design, str(temp))
    os.makedirs(d, exist_ok=True)
    n = len(truth)
    kw = {} if seen is None else {"seen": np.asarray(seen, bool)}
    np.savez_compressed(
        os.path.join(d, "predictions_hidden.npz"),
        path_keys=np.asarray(keys or ["p%d" % i for i in range(n)]),
        corners=np.asarray(corners),
        truth_ps=np.asarray(truth, float), model_ps=np.asarray(model, float),
        **kw)


def test_scatter_skips_the_corners_the_model_was_fit_on(tmp_path):
    """A seen corner's scatter is the fit against its own data -- tight by
    construction, and with --corners all there are more of those than of the
    held-out ones. They are skipped unless asked for; the rank figure still
    spans every corner, because a rank is a position within one ordering and
    dropping corners out of the middle draws a trajectory that never was."""
    pytest.importorskip("matplotlib")
    import plot

    runs = str(tmp_path / "runs" / "setup")
    rng = np.random.RandomState(1)
    truth = rng.rand(20, 4) * 300.0
    _write(runs, "cpu", "125", ["s1", "h1", "s2", "h2"], truth,
           truth + rng.randn(20, 4), seen=[True, False, True, False])

    out = str(tmp_path / "a")
    assert plot.main(["--runs", runs, "--out", out, "--only", "scatter"]) == 0
    assert sorted(os.listdir(out)) == ["scatter_cpu_125_h1.png",
                                       "scatter_cpu_125_h2.png"]

    out2 = str(tmp_path / "b")
    assert plot.main(["--runs", runs, "--out", out2, "--only", "scatter",
                      "--include-seen"]) == 0
    assert len(os.listdir(out2)) == 4

    # the rank figure keeps every corner and marks which were fit on
    out3 = str(tmp_path / "c")
    assert plot.main(["--runs", runs, "--out", out3, "--only", "rank"]) == 0
    assert os.listdir(out3) == ["rank_cpu_125.png"]


def test_plot_writes_a_scatter_per_corner_and_one_rank_figure(tmp_path):
    pytest.importorskip("matplotlib")
    import plot

    runs = str(tmp_path / "runs" / "setup")
    rng = np.random.RandomState(0)
    truth = rng.rand(40, 3) * 500.0
    _write(runs, "cpu", "125", ["A", "B", "C"], truth, truth + rng.randn(40, 3))

    out = str(tmp_path / "plots")
    assert plot.main(["--runs", runs, "--out", out]) == 0
    made = sorted(os.listdir(out))
    assert made == ["rank_cpu_125.png", "scatter_cpu_125_A.png",
                    "scatter_cpu_125_B.png", "scatter_cpu_125_C.png"], made
    assert all(os.path.getsize(os.path.join(out, f)) > 5000 for f in made)


def test_plot_skips_what_it_cannot_draw_instead_of_failing(tmp_path):
    """A corner with no measurement has nothing to scatter, and a grid of one
    corner has no trajectory. Both are ordinary -- query corners exist and a
    small holdout exists -- so both are skipped, and whatever CAN be drawn is."""
    pytest.importorskip("matplotlib")
    import plot

    runs = str(tmp_path / "runs" / "setup")
    truth = np.array([[10.0, np.nan], [20.0, np.nan], [30.0, np.nan]])
    model = np.array([[11.0, 5.0], [21.0, 6.0], [29.0, 7.0]])
    _write(runs, "cpu", "m25", ["measured", "query"], truth, model)

    out = str(tmp_path / "plots")
    assert plot.main(["--runs", runs, "--out", out]) == 0
    made = sorted(os.listdir(out))
    # the query corner gets no scatter, and with one usable corner there is no
    # rank trajectory to draw
    assert made == ["scatter_cpu_m25_measured.png"], made


def test_plot_says_what_is_missing_rather_than_raising(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    import plot

    assert plot.main(["--runs", str(tmp_path / "nothing"),
                      "--out", str(tmp_path / "p")]) == 1
    err = capsys.readouterr().err
    assert "predictions_hidden.npz" in err and "run.sh predict" in err

    runs = str(tmp_path / "runs" / "setup")
    _write(runs, "cpu", "125", ["A"], [[1.0], [2.0]], [[1.0], [2.0]])
    assert plot.main(["--runs", runs, "--design", "gpu",
                      "--out", str(tmp_path / "p")]) == 1
    assert "gpu" in capsys.readouterr().err


def test_plot_runs_as_a_script(tmp_path):
    """Invoked the way the instructions say to invoke it, with no package
    importable and no display attached -- the two things that differ between
    this machine and the one it gets run on."""
    pytest.importorskip("matplotlib")
    runs = str(tmp_path / "runs" / "setup")
    truth = np.arange(30, dtype=float).reshape(10, 3)
    _write(runs, "cpu", "125", ["A", "B", "C"], truth, truth + 0.5)
    env = dict(os.environ)
    env.pop("DISPLAY", None)
    env.pop("PYTHONPATH", None)
    r = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "scripts", "plot.py"),
         "--runs", runs, "--out", str(tmp_path / "plots")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    assert r.returncode == 0, r.stderr.decode()
    assert b"figures in" in r.stdout
    assert os.path.exists(str(tmp_path / "plots" / "rank_cpu_125.png"))
