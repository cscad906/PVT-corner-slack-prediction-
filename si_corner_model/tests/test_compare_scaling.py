"""scripts/compare_scaling.py -- PT voltage scaling against this model.

Every test here is about reading data this machine has never seen. The scaling
reports come from a hand-driven PrimeTime run on another site: the file names
are typed by a person, the reports may or may not carry the fixed-path headers
this project's own flow emits, and the corner is usually one with no library and
therefore no measurement. So what is tested is the reading, not the arithmetic
-- a wrong corner read out of a file name, or a join that falls back to row
order, produces a plausible picture of nothing.
"""
import os
import subprocess
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import compare_scaling as cs                                    # noqa: E402


def _fixed_path_report(slacks, keys=None):
    """A report in the shape the fixed-path re-measurement flow emits."""
    L = []
    for i, s in enumerate(slacks):
        a, b = "u_a/reg_%d_" % i, "u_b/reg_%d_" % i
        k = keys[i] if keys else "%s->%s_#%d" % (a, b, i)
        L += ["### FIXED_PATH idx=%d key=%s" % (i, k),
              "  Startpoint: %s" % a, "  Endpoint: %s" % b,
              "  data arrival time                     1.0000",
              "  data required time                    2.0000",
              "  slack (MET)                        %9.4f" % (s / 1000.0), ""]
    return "\n".join(L)


def _plain_report(slacks):
    """What report_timing prints when nobody wrapped it: no idx, no key."""
    L = []
    for i, s in enumerate(slacks):
        L += ["  Startpoint: u_a/reg_%d_" % i,
              "  Endpoint: u_b/reg_%d_" % i,
              "  data arrival time                     1.0000",
              "  slack (VIOLATED)                   %9.4f" % (s / 1000.0), ""]
    return "\n".join(L)


def _npz(runs, design, temp, labels, model, truth=None, idx=True, n=8):
    d = os.path.join(runs, design, str(temp))
    os.makedirs(d, exist_ok=True)
    keys = ["u_a/reg_%d_->u_b/reg_%d__#%d" % (i, i, i) for i in range(n)]
    kw = {"path_idx": np.arange(n)} if idx else {}
    np.savez_compressed(
        os.path.join(d, "predictions_base.npz"),
        path_keys=np.asarray(keys), corners=np.asarray(labels),
        seen=np.zeros(len(labels), bool),
        model_ps=np.asarray(model, float),
        truth_ps=np.asarray(truth if truth is not None
                            else np.full_like(np.asarray(model, float), np.nan)),
        **kw)


# ----------------------------------------------------------------- name reading
@pytest.mark.parametrize("name,want", [
    ("restored_scaled_SSPG_0p52V_125C_RCMAX_V_hold.rpt",
     (0.52, "125", "rcmax", "hold")),
    ("SSPG-0.52v-RCmax-125c.setup.rpt", (0.52, "125", "rcmax", "setup")),
    ("scaled_520mV_m25C_cmin_hold.rpt", (0.52, "-25", "cmin", "hold")),
    ("TT_0p6V_n40C_rcmin.rpt", (0.6, "-40", "rcmin", None)),
    # rcmax must not read as cmax: one is a substring of the other, and the
    # wrong one silently compares a different corner
    ("x_0p52V_RCMAX_125C.rpt", (0.52, "125", "rcmax", None)),
    ("no_corner_here.rpt", (None, None, None, None)),
])
def test_a_corner_is_read_out_of_any_of_the_namings(name, want):
    assert cs.tokens(name) == want


def test_the_models_own_corner_labels_read_the_same_way():
    """`SSPG_0p52V_RCMAX` and the file name above are one convention, so one
    reader serves both sides and they cannot drift apart."""
    assert cs.same_corner("SSPG_0p52V_RCMAX", 0.52, "rcmax")
    assert cs.same_corner("0.520V_rcmax", 0.52, "rcmax")      # report column
    assert not cs.same_corner("SSPG_0p52V_RCMIN", 0.52, "rcmax")
    assert not cs.same_corner("SSPG_0p54V_RCMAX", 0.52, "rcmax")


# -------------------------------------------------------------- report reading
def test_a_fixed_path_report_is_joined_on_the_reports_own_idx(tmp_path):
    sc = tmp_path / "scaling" / "PERIC0" / "hold"
    sc.mkdir(parents=True)
    pt = [100.0 + 10 * i for i in range(8)]
    (sc / "restored_scaled_SSPG_0p52V_125C_RCMAX_V_hold.rpt").write_text(
        _fixed_path_report(pt))

    runs = str(tmp_path / "runs" / "hold")
    mine = np.asarray(pt, float)[:, None] - 25.0
    _npz(runs, "PERIC0", 125, ["SSPG_0p52V_RCMAX"], mine)

    out = str(tmp_path / "p")
    rc = cs.main(["--scaling", str(tmp_path / "scaling" / "PERIC0"),
                  "--runs", runs, "--mode", "hold", "--out", out])
    assert rc == 0
    assert os.listdir(out) == ["ptscale_PERIC0_base_hold_125_0.52V_rcmax.png"]


def test_a_plain_report_falls_back_to_the_path_key_not_to_row_order(tmp_path):
    """A scaling run done outside this project's flow has no idx to join on.
    The path key is the only identifier left; row order is not one, because the
    two tools need not report the same paths -- so the model's extra paths must
    drop out rather than shift every pairing by one."""
    sc = tmp_path / "scaling" / "PERIC0" / "setup"
    sc.mkdir(parents=True)
    pt = [50.0, 60.0, 70.0, 80.0]            # only the first four paths
    (sc / "scaled_SSPG_0p52V_125C_rcmax_setup.rpt").write_text(_plain_report(pt))

    runs = str(tmp_path / "runs" / "setup")
    mine = (np.arange(8, dtype=float) * 10.0 + 45.0)[:, None]
    _npz(runs, "PERIC0", 125, ["SSPG_0p52V_RCMAX"], mine, idx=False)

    got = cs.read_pt(str(sc / "scaled_SSPG_0p52V_125C_rcmax_setup.rpt"))
    assert got[3] == "plain report_timing" and not got[0]
    assert got[1]["u_a/reg_0_->u_b/reg_0_"] == 50.0

    m = cs.read_npz(runs, "PERIC0", 125, 0.52, "rcmax")
    j = cs.join((got[0], got[1], got[2]), m[:2])
    x, y_pt, y_me, how = j
    assert len(x) == 4, "only the paths both reported"
    assert "no idx" in how
    assert list(y_pt) == pt
    assert list(y_me) == [45.0, 55.0, 65.0, 75.0], "paired by key, not shifted"


def test_nothing_measured_is_drawn_even_when_the_file_carries_a_column(tmp_path):
    """A corner reached by scaling has no library, so nothing measured it --
    that is the whole reason it was scaled. A predictions file still carries a
    truth column (NaN, or a real measurement at some other corner that happens
    to share the name), and drawing it would put a third series on the figure
    that is not an answer to the question being asked."""
    sc = tmp_path / "s" / "PERIC0" / "setup"
    sc.mkdir(parents=True)
    truth = np.arange(8, dtype=float) * 12.0
    (sc / "SSPG_0p5V_125C_rcmax_setup.rpt").write_text(
        _fixed_path_report(list(truth + 40.0)))
    runs = str(tmp_path / "runs" / "setup")
    _npz(runs, "PERIC0", 125, ["SSPG_0p5V_RCMAX"], truth[:, None] + 5.0,
         truth=truth[:, None])

    m = cs.read_npz(runs, "PERIC0", 125, 0.5, "rcmax")
    assert len(m) == 4, "model by idx, model by key, label, source -- no truth"
    pt = cs.read_pt(str(sc / "SSPG_0p5V_125C_rcmax_setup.rpt"))
    out = cs.join(pt[:3], m[:2])
    assert len(out) == 4, "x, pt, model, how"
    x, y_pt, y_me, how = out
    assert how == "idx"
    assert np.allclose(y_me, truth + 5.0) and np.allclose(y_pt, truth + 40.0)


def test_one_panel_with_two_series(tmp_path):
    """One axes, not two. The difference was its own panel for a while; it is
    the vertical gap the eye already reads, and the panel only halved the axis
    the values are read on. Its summary goes to the terminal instead."""
    plt = pytest.importorskip("matplotlib.pyplot")
    fig_fp = str(tmp_path / "f.png")
    cs.draw(plt, np.arange(5), np.arange(5) + 10.0, np.arange(5) + 4.0,
            "t", "Path index", fig_fp)
    assert os.path.getsize(fig_fp) > 5000


def test_the_difference_summary_is_printed(tmp_path, capsys):
    sc = tmp_path / "s" / "PERIC0" / "setup"
    sc.mkdir(parents=True)
    (sc / "SSPG_0p52V_125C_rcmax_setup.rpt").write_text(
        _fixed_path_report([100.0] * 8))
    runs = str(tmp_path / "runs" / "setup")
    _npz(runs, "PERIC0", 125, ["SSPG_0p52V_RCMAX"], np.full((8, 1), 80.0))
    assert cs.main(["--scaling", str(tmp_path / "s" / "PERIC0"), "--runs", runs,
                    "--list"]) == 0
    o = capsys.readouterr().out
    assert "PT scaling - base: mean +20.0 ps" in o
    assert "measurement" not in o


def test_an_unmeasured_corner_is_read_out_of_the_predict_report(tmp_path):
    """0.52V has no library, so it is in no measured grid and in no predictions
    file -- it exists only once `predict --at 0.52:rcmax` has written a report.
    That report is text with blank cells, so its columns are cut on the rule
    line: splitting on whitespace would shift every value after a blank one."""
    runs = str(tmp_path / "runs" / "setup")
    alld = os.path.join(runs, "_all")
    os.makedirs(alld)
    body = [
        "*" * 72,
        "Report      : predicted slack",
        "Temperature : 125",
        "Corners     : 0.520V_rcmax, 0.520V_cmax",
        "*" * 72,
        "",
        "Design: PERIC0",
        "",
        "   idx path                    0.520V_rcmax    0.520V_cmax",
        "                                 slack (ps)     slack (ps)",
        "  ---- --------------------- -------------- --------------",
        "     0 u_a/reg_0_->u_b/reg_0_         111.0          222.0",
        "     1 u_a/reg_1_->u_b/reg_1_         121.0               ",
        "     2 u_a/reg_2_->u_b/reg_2_         131.0          242.0",
        "",
        "  Summary",
        "  smallest slack                     111.0          222.0",
    ]
    with open(os.path.join(alld, "predict_125_at.rpt"), "w") as f:
        f.write("\n".join(body) + "\n")

    bi, bk, lab = cs.read_predict_rpt(os.path.join(alld, "predict_125_at.rpt"),
                                      "PERIC0", 0.52, "rcmax")
    assert lab == "0.520V_rcmax"
    assert bi == {0: 111.0, 1: 121.0, 2: 131.0}
    # the blank cell belongs to the OTHER column and must not pull 242.0 left
    bi2, _, lab2 = cs.read_predict_rpt(os.path.join(alld, "predict_125_at.rpt"),
                                       "PERIC0", 0.52, "cmax")
    assert lab2 == "0.520V_cmax" and bi2 == {0: 222.0, 2: 242.0}

    got = cs.find_predict_rpt(runs, "125", "PERIC0", 0.52, "rcmax")
    assert got is not None and got[0] == {0: 111.0, 1: 121.0, 2: 131.0}


def test_it_says_what_to_run_when_the_corner_is_nowhere(tmp_path, capsys):
    """The usual first run: a scaled corner nobody has predicted yet. That is
    not an error in the script, so it prints the command that fixes it."""
    sc = tmp_path / "s" / "PERIC0" / "hold"
    sc.mkdir(parents=True)
    (sc / "restored_scaled_SSPG_0p52V_125C_RCMAX_V_hold.rpt").write_text(
        _fixed_path_report([1.0, 2.0]))
    rc = cs.main(["--scaling", str(tmp_path / "s" / "PERIC0"),
                  "--runs", str(tmp_path / "runs" / "hold"),
                  "--mode", "hold", "--out", str(tmp_path / "p")])
    assert rc == 1
    o = capsys.readouterr().out
    assert "predict --at 0.52:rcmax --temp 125 --mode hold" in o
    assert "[no base]" in o


def test_an_unreadable_name_is_listed_and_skipped_not_guessed(tmp_path, capsys):
    sc = tmp_path / "s" / "PERIC0" / "setup"
    sc.mkdir(parents=True)
    (sc / "whatever.rpt").write_text(_fixed_path_report([1.0]))
    rc = cs.main(["--scaling", str(tmp_path / "s" / "PERIC0"), "--list"])
    assert rc == 1
    o = capsys.readouterr()
    assert "no voltage in the name, skipped" in o.out
    assert "voltage and a BEOL level" in o.err


def test_list_reports_without_drawing_and_without_matplotlib(tmp_path, capsys):
    sc = tmp_path / "s" / "PERIC0" / "hold"
    sc.mkdir(parents=True)
    (sc / "restored_scaled_SSPG_0p52V_125C_RCMAX_V_hold.rpt").write_text(
        _fixed_path_report([100.0] * 8))
    runs = str(tmp_path / "runs" / "hold")
    _npz(runs, "PERIC0", 125, ["SSPG_0p52V_RCMAX"], np.full((8, 1), 90.0))
    out = str(tmp_path / "p")
    assert cs.main(["--scaling", str(tmp_path / "s" / "PERIC0"), "--runs", runs,
                    "--mode", "hold", "--out", out, "--list"]) == 0
    assert not os.path.isdir(out), "--list draws nothing"
    assert "[matched]" in capsys.readouterr().out


def test_disjoint_path_sets_are_reported_not_plotted(tmp_path, capsys):
    sc = tmp_path / "s" / "PERIC0" / "setup"
    sc.mkdir(parents=True)
    (sc / "SSPG_0p52V_125C_rcmax_setup.rpt").write_text(
        _fixed_path_report([1.0, 2.0], keys=["x/a->x/b", "y/a->y/b"]))
    runs = str(tmp_path / "runs" / "setup")
    _npz(runs, "PERIC0", 125, ["SSPG_0p52V_RCMAX"], np.full((8, 1), 9.0),
         idx=False)
    rc = cs.main(["--scaling", str(tmp_path / "s" / "PERIC0"), "--runs", runs,
                  "--out", str(tmp_path / "p")])
    assert rc == 1
    assert "[no overlap]" in capsys.readouterr().out


def test_it_runs_as_a_script_with_no_package_on_the_path(tmp_path):
    """Invoked the way the instructions say, with no PYTHONPATH and no display
    -- the two things that differ on the machine this gets run on."""
    pytest.importorskip("matplotlib")
    sc = tmp_path / "s" / "PERIC0" / "setup"
    sc.mkdir(parents=True)
    (sc / "restored_scaled_SSPG_0p52V_125C_RCMAX_V_setup.rpt").write_text(
        _fixed_path_report([100.0 + 7 * i for i in range(8)]))
    runs = str(tmp_path / "runs" / "setup")
    _npz(runs, "PERIC0", 125, ["SSPG_0p52V_RCMAX"],
         (np.arange(8, dtype=float) * 7.0 + 80.0)[:, None])
    env = dict(os.environ)
    env.pop("DISPLAY", None)
    env.pop("PYTHONPATH", None)
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "compare_scaling.py"),
         "--scaling", str(tmp_path / "s" / "PERIC0"), "--runs", runs,
         "--out", str(tmp_path / "p")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    assert r.returncode == 0, r.stderr.decode()
    assert b"1 figure(s)" in r.stdout
    assert os.path.getsize(str(tmp_path / "p" /
                               "ptscale_PERIC0_base_setup_125_0.52V_rcmax.png")) > 5000
