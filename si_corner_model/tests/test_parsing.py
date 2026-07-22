"""Parser unit tests. Run:  python -m pytest tests/ -q

The pure-helper tests need only numpy. The real-file tests read a couple of real
reports and are skipped automatically when the data drop is not present.
"""
import os

import pytest

from si_model.parsing.annotated import parse_annotated
from si_model.parsing.build_dataset import cell_drive, cell_family
from si_model.parsing.crosstalk import parse_crosstalk
from si_model.parsing.keys import (corner_label, norm_path_key, parse_corner,
                                    parse_voltage_from_annotated, parse_xt_name)

BASE = "/home/hyunss/PVT_prediction/14nm/iter51"
ANN = f"{BASE}/annotation/hold_sion/temp_m40/annotated/Cnom"
XT = f"{BASE}/crosstalk/newhold/Cnom"
_have_data = os.path.isdir(ANN) and os.path.isdir(XT)
needs_data = pytest.mark.skipif(not _have_data, reason="iter51 data not present")


# -- pure helpers ------------------------------------------------------------
def test_norm_path_key():
    assert norm_path_key("A->B_#282") == "A->B"
    assert norm_path_key("A->B#5") == "A->B"
    assert norm_path_key("A->B") == "A->B"


def test_corner_roundtrip_rc():
    for v, rc, rcval in [(0.605, "Cmin", -1.0), (0.8, "Cnom", 0.0), (0.75, "Cmax", 1.0)]:
        lab = corner_label(v, rc)
        gv, grc = parse_corner(lab)
        assert abs(gv - v) < 1e-9 and grc == rcval


def test_corner_roundtrip_temp():
    # the second axis can also be temperature (V x T datasets)
    for v, temp in [(0.65, -40.0), (0.7, 25.0), (0.75, 125.0)]:
        lab = corner_label(v, temp)
        gv, gt = parse_corner(lab)
        assert abs(gv - v) < 1e-9 and abs(gt - temp) < 1e-9


def test_corner_roundtrip_foreign_vendor():
    # everything different: FFPG process prefix + non-RC BEOL names + other V range;
    # all supplied from config (data.corner_prefix + axes[1].levels), no code edits.
    lv = {"Cbest": -1.0, "Ctyp": 0.0, "Cworst": 1.0}
    lab = corner_label(0.55, "Cworst", prefix="FFPG")
    assert lab == "FFPG_0p55V_Cworst"
    assert parse_corner(lab, lv, prefix="FFPG") == (0.55, 1.0)
    # temperature form with a foreign prefix too
    assert parse_corner("SSPG_0p9V_m25C", prefix="SSPG") == (0.9, -25.0)
    # crosstalk filename with a foreign prefix
    assert parse_xt_name("FFPG_0p55V_125C.foo.by_path.rpt", prefix="FFPG") == (0.55, "125")


def test_voltage_parsing():
    assert abs(parse_voltage_from_annotated("saed14rvt_tt0p605vm40c_x.txt") - 0.605) < 1e-9
    assert abs(parse_voltage_from_annotated("saed14rvt_tt0p8vm40c_x.txt") - 0.8) < 1e-9
    assert parse_xt_name("TT_0p605V_m40C.path_context_si_compact.by_path.rpt") == (0.605, "m40")
    assert parse_xt_name("TT_0p62V_125C.foo.by_path.rpt") == (0.62, "125")


def test_saed14_taxonomy():
    assert cell_family("SAEDRVT14_ND2_CDC_0P5") == "NAND"
    assert cell_family("SAEDRVT14_AOI222_1") == "AOI"
    assert cell_family("SAEDRVT14_FDP_V2LP_2") == "DFF"
    assert cell_family("SAEDRVT14_INV_0P75") == "INV"
    assert cell_family("SAEDRVT14_BUF_20") == "BUF"
    assert cell_drive("SAEDRVT14_BUF_20") == 20.0
    assert cell_drive("SAEDRVT14_NR3B_1P5") == 1.5
    assert cell_drive("SAEDRVT14_AOI222_1") == 1.0


# -- real-file parsing -------------------------------------------------------
def _one_file(d):
    f = sorted(x for x in os.listdir(d) if "0p8v" in x or "0p8V" in x)
    return os.path.join(d, f[0]) if f else os.path.join(d, sorted(os.listdir(d))[0])


@needs_data
def test_annotated_parse():
    ann = parse_annotated(_one_file(ANN), with_stages=True)
    assert len(ann) > 100
    p = next(iter(ann.values()))
    assert p.slack == p.slack                      # not NaN
    assert p.arrival == p.arrival
    segs = {s.segment for s in p.stages}
    assert "data" in segs
    assert any(s.kind == "net" and s.dist > 0 for s in p.stages)


@needs_data
def test_crosstalk_parse_and_alignment():
    xf = os.path.join(XT, "TT_0p8V_m40C.path_context_si_compact.by_path.rpt")
    if not os.path.exists(xf):
        pytest.skip("0p8 m40 crosstalk file absent")
    xt = parse_crosstalk(xf)
    assert len(xt) > 100
    px = next(iter(xt.values()))
    assert isinstance(px.si_total(), float)
    ann = parse_annotated(os.path.join(ANN, [f for f in os.listdir(ANN) if "0p8v" in f][0]))
    ka = {i: norm_path_key(p.key) for i, p in ann.items()}
    kx = {i: norm_path_key(p.key) for i, p in xt.items()}
    assert ka == kx
    for i in list(ka)[:50]:
        assert abs(ann[i].slack - xt[i].slack) < 5e-5
