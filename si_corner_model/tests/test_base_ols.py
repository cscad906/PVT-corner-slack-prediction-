"""OLS base + basis-generator unit tests (numpy only).

    python -m pytest tests/test_base_ols.py -q
"""
import numpy as np

from si_model.config import expand_terms
from si_model.model.base_ols import design_matrix, fit_base, fit_base_adaptive


def _cfg(axes, cross_max_degree=3, cross_terms=True):
    return {"base": {"axes": axes, "cross_terms": cross_terms,
                     "cross_max_degree": cross_max_degree}}


def test_terms_reproduce_beol14_basis():
    # V cubic x RC quadratic -> the hand-tuned 14nm basis, exactly.
    cfg = _cfg([{"name": "v", "ref": 0.8, "order": 3},
                {"name": "rc", "ref": 0.0, "order": 2}])
    _, names, _ = expand_terms(cfg)
    assert set(names) == {"dv", "dv2", "dv3", "drc", "drc2", "dvdrc", "dv2drc", "dvdrc2"}


def test_terms_reproduce_gt3_basis():
    # V cubic x T quartic -> the hand-tuned 3nm basis, exactly.
    cfg = _cfg([{"name": "v", "ref": 0.7, "order": 3},
                {"name": "t", "ref": 25, "order": 4}])
    _, names, _ = expand_terms(cfg)
    assert set(names) == {"dv", "dv2", "dv3", "dt", "dt2", "dt3", "dt4",
                          "dvdt", "dv2dt", "dvdt2"}


def test_rank_deficiency_guard():
    # RC has only 3 distinct seen levels -> drc3 must be dropped;
    # V has only 4 seen levels -> dv4 must be dropped.
    cfg = _cfg([{"name": "v", "ref": 0.8, "order": 4},
                {"name": "rc", "ref": 0.0, "order": 3}])
    _, names, dropped = expand_terms(cfg, seen_levels=[4, 3])
    assert "drc3" in dropped and "dv4" in dropped
    assert "drc3" not in names and "dv4" not in names
    # estimable powers survive
    assert "dv3" in names and "drc2" in names


def test_no_cross_terms():
    cfg = _cfg([{"name": "v", "ref": 0.8, "order": 2},
                {"name": "rc", "ref": 0.0, "order": 2}], cross_terms=False)
    _, names, _ = expand_terms(cfg)
    assert set(names) == {"dv", "dv2", "drc", "drc2"}       # pure axes only


def test_adaptive_reduces_to_global():
    # With grid=[None] the adaptive base is exactly the global closed-form LOO fit.
    rng = np.random.RandomState(0)
    vs = np.array([0.6, 0.65, 0.7, 0.75, 0.8])
    rcs = np.array([-1.0, 0.0, 1.0])
    grid_v, grid_r = np.meshgrid(vs, rcs, indexing="ij")
    coords = np.stack([grid_v.ravel() - 0.8, grid_r.ravel()], 1)
    C = coords.shape[0]
    cfg = _cfg([{"name": "v", "ref": 0.8, "order": 3},
                {"name": "rc", "ref": 0.0, "order": 2}])
    exps, _, _ = expand_terms(cfg, seen_levels=[5, 3])
    phi = design_matrix(coords, exps)
    seen = np.ones(C, bool)
    seen[7] = seen[11] = False                              # a couple hidden
    beta = rng.randn(phi.shape[1])
    y = (phi @ beta)[None, :] + 0.01 * rng.randn(4, C)      # 4 paths, smooth + noise
    out, picks = fit_base_adaptive(y, phi, seen, coords, grid=[None])
    _, loo = fit_base(y, phi, seen)
    assert np.allclose(out, loo, atol=1e-6)
    assert list(picks.values())[0] == C                     # every corner picked global
