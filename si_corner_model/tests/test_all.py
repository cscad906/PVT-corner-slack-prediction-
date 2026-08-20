"""One test file. Runs on numpy alone, with no data.

    python -m pytest tests/ -q

Three parts:
  1. config.yaml expansion -- does designs x temps expand into the model matrix
  2. corner discovery      -- filename -> corner label, temp/level filters
  3. engine math/helpers   -- basis construction, OLS base, path-key/cell parsing
"""
import os

import numpy as np
import pytest
import yaml

from si_model.config import expand_terms
from si_model.model.base_ols import design_matrix, fit_base, fit_base_adaptive
from si_model.parsing.build_dataset import cell_drive, cell_family
from si_model.parsing.discovery import discover, discover_annotated
from si_model.parsing.keys import (corner_label, norm_path_key, parse_corner,
                                   parse_voltage_from_annotated, parse_xt_name)
from si_model.run import REPO_ROOT, expand, list_designs, load_project, select

FLAT_RE = (r'report\.(?P<proc>[A-Za-z]+)_(?P<v>0p\d+)_(?P<temp>m?\d+)c'
           r'_(?P<level>[A-Za-z]+\d*)\.')


# ========================================================== 1. config expansion
@pytest.fixture
def tree(tmp_path):
    """On-site layout: <root>/<design>/ holding reports whose filenames carry
    the whole corner."""
    for design in ("cpu", "gpu"):
        d = tmp_path / design / "setup"          # shipped layout: <design>/setup/
        d.mkdir(parents=True)
        for v in ("0p5000", "0p5400", "0p6000", "0p6850"):
            for lv in ("rcmax", "cmax"):
                (d / f"report.sspg_{v}_125c_{lv}.rpt").touch()
            for lv in ("rcmax", "cmax", "rcmin"):
                (d / f"report.sspg_{v}_m25c_{lv}.rpt").touch()
    return tmp_path


@pytest.fixture
def project(tree):
    """Read the real config.yaml and repoint root at the fixture tree -- this
    also checks that the shipped file is schema-valid."""
    with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
        p = yaml.safe_load(f)
    p["root"] = str(tree)
    p["designs"] = "auto"
    return p


def _clear_temp_holdout(p):
    """Drop the per-temperature holdout in temps[] so only the globals apply."""
    p["temps"] = [{k: v for k, v in t.items() if k not in
                   ("hidden_corners", "hidden_per_voltage", "hidden_voltages",
                    "seen_voltages", "hidden_levels")} for t in p["temps"]]
    return p


def _use_voltage_row_holdout(p):
    """The shipped config uses per-temperature hidden_corners. Tests that assume
    a voltage-row holdout put that setting back first."""
    _clear_temp_holdout(p)
    p["corners"] = dict(p["corners"], hidden_voltages=[0.54], hidden_corners=[],
                        hidden_per_voltage=0)
    return p


def test_shipped_config_yaml_parses():
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["corners"]["process"] and p["temps"] and p["files"]["annotated_regex"]
    assert os.path.isabs(p["root"])


def test_shipped_config_defaults_to_the_deployed_layout():
    """The shipped layout is <root>/{si_corner_model, design1, design2, design3}.
    In that case root/designs must be right without being touched."""
    with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
        raw = yaml.safe_load(f)
    assert raw["root"] == "auto", \
        "default root must be auto (the repo's parent = where the designs live)"
    # designs must be stated explicitly -- root also holds non-design folders
    # (pr_si, spice), which auto would pick up as designs. Either form counts:
    # a list, or the mapping used when one circuit needs its own corners.
    assert isinstance(raw["designs"], (list, dict)) and raw["designs"], \
        "designs must be explicit, not auto"
    # auto resolves to this checkout's parent directory
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["root"] == os.path.dirname(REPO_ROOT)


def test_repo_itself_is_not_mistaken_for_a_design(tmp_path):
    """This repo sitting under root must not be picked up as a design."""
    (tmp_path / os.path.basename(REPO_ROOT)).mkdir()      # si_corner_model
    (tmp_path / "cache").mkdir()
    (tmp_path / ".hidden").mkdir()
    for d in ("boomcore", "fft", "aes"):
        (tmp_path / d).mkdir()
    assert list_designs({"root": str(tmp_path), "designs": "auto"}) == \
        ["aes", "boomcore", "fft"]


def test_designs_auto_finds_circuits(project):
    assert list_designs(project) == ["cpu", "gpu"]


def test_designs_explicit_list_wins(project):
    project["designs"] = ["gpu"]
    assert list_designs(project) == ["gpu"]


def test_env_overrides_root_and_designs(tree, monkeypatch):
    monkeypatch.setenv("SI_ROOT", str(tree))
    monkeypatch.setenv("SI_DESIGNS", "gpu")
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["root"] == str(tree)
    assert list_designs(p) == ["gpu"]


def test_expand_makes_design_x_temp_matrix(project):
    models = expand(project)
    assert [m["name"] for m in models] == ["cpu/125", "cpu/m25", "gpu/125", "gpu/m25"]
    m = models[0]
    assert m["cfg"]["data"]["rc_corners"] == ["rcmax", "cmax"]        # 125C has 2 levels
    assert models[1]["cfg"]["data"]["rc_corners"] == ["rcmax", "cmax", "rcmin"]
    assert m["cfg"]["data"]["ref_corner"] == "SSPG_0p685V_cmax"
    assert m["cfg"]["data"]["cache"].endswith(os.path.join("cpu", "125", "dataset.npz"))
    assert m["cfg"]["train"]["out_dir"].endswith(os.path.join("cpu", "125"))


def test_expand_auto_order_matches_available_levels(project):
    _use_voltage_row_holdout(project)
    by = {m["name"]: m["cfg"]["base"]["axes"] for m in expand(project)}
    # seen V = 3 (0.54 hidden) -> v order 2 ; 125C has 2 levels -> level order 1
    assert by["cpu/125"][0]["order"] == 2 and by["cpu/125"][1]["order"] == 1
    # m25C has 3 levels -> level order 2
    assert by["cpu/m25"][1]["order"] == 2


def test_expand_min_seen_is_full_grid(project):
    _use_voltage_row_holdout(project)
    by = {m["name"]: m["cfg"]["split"]["min_seen"] for m in expand(project)}
    assert by["cpu/125"] == 3 * 2      # 3 seen V x 2 levels
    assert by["cpu/m25"] == 3 * 3      # a missing report errors right here


def test_expand_si_on_when_crosstalk_declared(project):
    cfg = expand(project)[0]["cfg"]
    assert cfg["data"]["crosstalk_dir"].endswith(os.path.join("setup", "xtalk"))
    assert "crosstalk_regex" in cfg["data"]["patterns"]


def test_bundle_packs_every_temperature_into_one_file(project, tmp_path):
    """One circuit = one file. It must not split per temperature.

    Skipped where torch is absent (the pre-training check done on site)."""
    torch = pytest.importorskip("torch")
    from si_model.run import bundle_path, stage_bundle

    models = expand(project)
    for m in models:                       # lay down fake checkpoints as if trained
        d = m["cfg"]["train"]["out_dir"] = str(tmp_path / m["design"] / str(m["temp"]))
        os.makedirs(d, exist_ok=True)
        torch.save({"model": {"w": torch.zeros(1)}, "enc": {"w": torch.zeros(1)},
                    "cfg": m["cfg"], "epoch": 7}, os.path.join(d, "best.pt"))

    stage_bundle(models)

    for design in {m["design"] for m in models}:
        ms = [m for m in models if m["design"] == design]
        b = torch.load(bundle_path(ms[0]), map_location="cpu")
        assert b["design"] == design
        # every temperature of that circuit must be inside the one file
        assert set(b["temps"]) == {str(m["temp"]) for m in ms}
        assert all("model" in v and "enc" in v for v in b["temps"].values())


def test_bundle_skips_untrained_temperatures_instead_of_failing(project, tmp_path):
    """With only one temperature trained, bundle must still build from that one
    -- failing wholesale while waiting for the rest makes partial retraining
    impossible."""
    torch = pytest.importorskip("torch")
    from si_model.run import bundle_path, stage_bundle

    models = [m for m in expand(project) if m["design"] == expand(project)[0]["design"]]
    for m in models:
        m["cfg"]["train"]["out_dir"] = str(tmp_path / m["design"] / str(m["temp"]))
    d = models[0]["cfg"]["train"]["out_dir"]
    os.makedirs(d, exist_ok=True)
    torch.save({"model": {}, "enc": {}, "cfg": models[0]["cfg"], "epoch": 1},
               os.path.join(d, "best.pt"))

    stage_bundle(models)
    b = torch.load(bundle_path(models[0]), map_location="cpu")
    assert set(b["temps"]) == {str(models[0]["temp"])}


def test_corner_table_is_keyed_by_corner_not_by_model(tmp_path):
    """The summary must be keyed by CORNER, not by model.

    A model (circuit x temperature) is an internal split; what matters at handoff
    is "how well did this corner match". Query corners have no ground truth, so
    their paths are counted and their error left empty."""
    from si_model.run import _corner_table

    fp = tmp_path / "predictions_hidden.csv"
    fp.write_text(
        "design,temp,path_key,corner,truth_ps,model_ps,model_err_ps\n"
        "cpu,125,A,SSPG_0p54V_rcmax,10.0,12.0,2.0\n"
        "cpu,125,B,SSPG_0p54V_rcmax,10.0,6.0,-4.0\n"
        "cpu,m25,A,SSPG_0p5V_cmax,10.0,11.0,1.0\n"
        "cpu,m25,A,SSPG_0p57V_cmax,,11.0,\n")          # query corner (no ground truth)

    rows = {(r["temp"], r["corner"]): r for r in _corner_table(str(fp))}
    assert len(rows) == 3
    assert rows[("125", "SSPG_0p54V_rcmax")]["mae_ps"] == 3.0      # (2+4)/2
    assert rows[("125", "SSPG_0p54V_rcmax")]["worst_ps"] == 4.0
    assert rows[("125", "SSPG_0p54V_rcmax")]["n_paths"] == 2
    # query corner: paths counted, error absent -- counting it as 0.0 would
    # flatter the mean
    q = rows[("m25", "SSPG_0p57V_cmax")]
    assert q["n_paths"] == 1 and q["mae_ps"] is None and q["worst_ps"] is None


def test_merge_flags_a_summary_older_than_its_checkpoint(project, tmp_path, capsys):
    """An interrupted train updates best.pt only, leaving the previous run's
    summary.json behind. That must not ride out silently as by_model."""
    import json as _json

    from si_model.run import stage_merge

    models = expand(project)[:1]
    d = models[0]["cfg"]["train"]["out_dir"] = str(tmp_path / "m")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "predictions_hidden.csv"), "w") as f:
        f.write("path_key,corner,truth_ps,model_ps,model_err_ps\n"
                "A,SSPG_0p54V_rcmax,10.0,12.0,2.0\n")
    with open(os.path.join(d, "summary.json"), "w") as f:
        _json.dump({"all": {"hidden_mae_ps": 1.0}}, f)
    open(os.path.join(d, "best.pt"), "w").close()          # newer than summary
    os.utime(os.path.join(d, "summary.json"), (1, 1))

    project["out"] = {"runs": str(tmp_path / "out"), "cache": str(tmp_path / "c")}
    stage_merge(models, project, "hidden")
    assert "stale" in capsys.readouterr().out


def test_adaptive_downgrades_to_plain_on_a_grid_too_small_for_it(project):
    """adaptive picks a bandwidth using its adaptive_k nearest neighbours. With
    no more seen corners than that, the neighbourhood IS the whole grid, every
    candidate is scored on identical data, and the winner is noise.

    Measured (14nm, 125C: seen 6 / adaptive_k 6): adaptive 3.151 ps vs plain
    2.148 ps. It fires on the corner count alone, so it is decided before any
    label is read."""
    import numpy as np

    from si_model.training.loo import Split, _effective_mode

    cfg = expand(project)[0]["cfg"]
    cfg["base"]["weighting"] = "adaptive"
    cfg["base"]["adaptive_k"] = 6

    def split_with(n_seen):
        C = n_seen + 2
        seen = np.zeros(C, bool); seen[:n_seen] = True
        return Split([f"c{i}" for i in range(C)], np.zeros((C, 2)), seen, ~seen, 0)

    assert _effective_mode(cfg, split_with(6)) == "plain"     # 6 <= 6
    assert _effective_mode(cfg, split_with(10)) == "adaptive"  # 10 > 6
    # an explicitly chosen mode is left alone
    cfg["base"]["weighting"] = "plain"
    assert _effective_mode(cfg, split_with(10)) == "plain"


def test_mode_switches_every_path_at_once(project):
    """One `mode` line must split both the read and the write locations.

    files.subdir / files.crosstalk_subdir / out.cache / out.runs used to be
    edited separately, and switching subdir to hold while forgetting out let a
    hold run silently overwrite the setup cache. This pins all four moving
    together."""
    project["mode"] = "hold"
    m = expand(project)[0]
    d = m["cfg"]["data"]
    assert d["annotated_dir"].endswith(os.sep + "hold")
    assert d["crosstalk_dir"].endswith(os.path.join("hold", "xtalk"))
    assert d["cache"].startswith(os.path.join("cache", "hold") + os.sep)
    assert m["cfg"]["train"]["out_dir"].startswith(os.path.join("runs", "hold") + os.sep)


def test_mode_does_not_override_an_explicit_subdir(project):
    """Layouts whose folders are not named setup/hold must work too -- any
    value other than auto is used verbatim."""
    project["mode"] = "hold"
    project["files"]["subdir"] = "reports"
    d = expand(project)[0]["cfg"]["data"]
    assert d["annotated_dir"].endswith(os.sep + "reports")
    assert d["cache"].startswith(os.path.join("cache", "hold") + os.sep)


def test_expand_si_off_when_crosstalk_subdir_is_null(project):
    """When the location is unknown, null must allow a first run without SI."""
    project["files"]["crosstalk_subdir"] = None
    assert "crosstalk_dir" not in expand(project)[0]["cfg"]["data"]


def test_expand_rejects_bad_anchor(project):
    _use_voltage_row_holdout(project)
    project["corners"]["ref_voltage"] = 0.54        # a hidden voltage
    with pytest.raises(AssertionError, match="ref_voltage"):
        expand(project)
    project["corners"]["ref_voltage"] = 0.685
    project["corners"]["ref_level"] = "nope"
    with pytest.raises(AssertionError, match="ref_level"):
        expand(project)


# ---- per-circuit overrides ------------------------------------------------------
def test_all_designs_share_settings_by_default(project):
    """The default is three circuits sharing corners and holdout. Adding
    circuits must not add configs."""
    models = expand(project)
    by_design = {}
    for m in models:
        by_design.setdefault(m["design"], {})[m["temp"]] = m["cfg"]
    assert set(by_design) == {"cpu", "gpu"}
    a, b = by_design["cpu"], by_design["gpu"]
    for tag in ("125", "m25"):
        assert a[tag]["split"] == b[tag]["split"], f"{tag}: holdout differs per circuit"
        assert a[tag]["base"] == b[tag]["base"]
        assert a[tag]["data"]["rc_corners"] == b[tag]["data"]["rc_corners"]
    # temperatures must differ from each other (different level counts)
    assert a["125"]["data"]["rc_corners"] != a["m25"]["data"]["rc_corners"]


def test_designs_mapping_gives_per_circuit_overrides(project):
    """Written as a mapping, `designs:` can give one circuit different settings
    -- from one file, without copying the config per circuit."""
    project["designs"] = {
        "cpu": {},                                        # globals unchanged
        "gpu": {"corners": {"voltages": [0.5, 0.6, 0.685]},
                "files": {"subdir": "reports"}},
    }
    by = {m["name"]: m["cfg"] for m in expand(project)}
    assert set(by) == {"cpu/125", "cpu/m25", "gpu/125", "gpu/m25"}
    # cpu has 4 voltages, gpu 3 -> their corner counts (min_seen) diverge
    assert by["cpu/125"]["split"]["min_seen"] == 4 * 2 - 2
    assert by["gpu/125"]["split"]["min_seen"] == 3 * 2 - 2
    # keys that are not overridden inherit the globals
    assert by["gpu/125"]["data"]["corner_prefix"] == by["cpu/125"]["data"]["corner_prefix"]
    assert by["gpu/125"]["data"]["annotated_dir"].endswith("reports")
    assert not by["cpu/125"]["data"]["annotated_dir"].endswith("reports")


def test_designs_mapping_can_override_holdout_per_circuit(project):
    project["designs"] = {
        "cpu": {},
        "gpu": {"temps": [{"tag": "125", "token": 125, "levels": ["rcmax", "cmax"],
                           "hidden_corners": [[0.5, "cmax"]]}]},
    }
    by = {m["name"]: m["cfg"]["split"]["hidden_corners"] for m in expand(project)}
    assert by["gpu/125"] == [[0.5, "cmax"]]
    assert by["cpu/125"] != by["gpu/125"]
    assert "gpu/m25" not in by, "the overridden temps list is used as-is (125 only)"


# ---- per-temperature holdout --------------------------------------------------
def test_holdout_can_differ_per_temperature(project):
    """125C has 2 levels and m25C has 3, so "hide this corner" cannot be one
    global list -- it has to be writable per temperature inside temps[]."""
    project["corners"]["hidden_voltages"] = []
    project["temps"][0]["hidden_corners"] = [[0.5, "rcmax"], [0.6, "cmax"]]
    project["temps"][1]["hidden_corners"] = [[0.54, "rcmin"], [0.685, "rcmax"]]
    by = {m["temp"]: m["cfg"]["split"] for m in expand(project) if m["design"] == "cpu"}
    assert by["125"]["hidden_corners"] == [[0.5, "rcmax"], [0.6, "cmax"]]
    assert by["m25"]["hidden_corners"] == [[0.54, "rcmin"], [0.685, "rcmax"]]
    # min_seen must reflect the per-temperature holdout too (4V x 2 levels - 2 = 6)
    assert by["125"]["min_seen"] == 4 * 2 - 2
    assert by["m25"]["min_seen"] == 4 * 3 - 2


def test_holdout_level_must_exist_at_that_temperature(project):
    """rcmin, absent at 125C, must error rather than be ignored silently."""
    project["corners"]["hidden_voltages"] = []
    project["temps"][0]["hidden_corners"] = [[0.5, "rcmin"]]      # no rcmin at 125C
    with pytest.raises(AssertionError, match="hidden_corners"):
        expand(project)


def test_hidden_per_voltage_spreads_one_corner_per_voltage(project):
    """Instead of removing a whole voltage row, hide one cell per voltage."""
    _clear_temp_holdout(project)
    project["corners"]["hidden_voltages"] = []
    project["corners"]["hidden_per_voltage"] = 1
    by = {m["temp"]: m["cfg"]["split"] for m in expand(project) if m["design"] == "cpu"}
    for tag, n_lv in (("125", 2), ("m25", 3)):
        hc = by[tag]["hidden_corners"]
        vs = [v for v, _ in hc]
        assert len(hc) == 4, f"{tag}: 4 voltages -> 4 cells"
        assert sorted(vs) == [0.5, 0.54, 0.6, 0.685], f"{tag}: one per voltage"
        assert (0.685, "cmax") not in [(v, l) for v, l in hc], "the anchor must never be hidden"
        assert len({l for _, l in hc}) > 1, f"{tag}: must not pile onto one level"
        assert by[tag]["min_seen"] == 4 * n_lv - 4


def test_hidden_per_voltage_cannot_take_every_level(project):
    _clear_temp_holdout(project)
    project["corners"]["hidden_voltages"] = []
    project["corners"]["hidden_per_voltage"] = 2      # 125C has only 2 levels
    with pytest.raises(AssertionError, match="hidden_per_voltage"):
        expand(project)


def test_expand_rejects_level_missing_from_values(project):
    project["temps"][0]["levels"] = ["rcmax", "cworst"]
    with pytest.raises(AssertionError, match="level_values"):
        expand(project)


# ---- corner selection: do the config's four ways reach the actual split ----------
def _hidden_labels(project, corners_over):
    """Expand project with the given corners override; return hidden labels."""
    from si_model.parsing.keys import corner_label, parse_corner
    from si_model.training.loo import make_split
    q = {**project, "corners": {**project["corners"], **corners_over},
         "designs": ["cpu"],
         "temps": [{"tag": "m25", "token": "m25",
                    "levels": ["rcmax", "cmax", "rcmin"]}]}
    cfg = expand(q)[0]["cfg"]
    lv = cfg["base"]["axes"][1]["levels"]
    labels = [corner_label(v, l, "SSPG")
              for v in q["corners"]["voltages"] for l in cfg["data"]["rc_corners"]]
    vt = np.asarray([parse_corner(c, lv, "SSPG") for c in labels], np.float32)
    cfg["split"]["min_seen"] = 1                     # the guard is not the point here
    sp = make_split(labels, vt, cfg)
    return {labels[i] for i in sp.hidden_idx}


def test_hidden_voltages_hides_whole_row(project):
    assert _hidden_labels(project, {"hidden_voltages": [0.54]}) == {
        "SSPG_0p54V_rcmax", "SSPG_0p54V_cmax", "SSPG_0p54V_rcmin"}


def test_hidden_voltages_survive_float32_roundtrip():
    """The cache stores vt as float32 -> 0.54 comes back as 0.54000002.

    If the tolerance is tighter than float32 precision, `hidden_voltages: [0.54]`
    selects nothing and the split ends up with no hidden corners at all (which is
    exactly how this was once broken). The npz round-trip is reproduced here so
    it cannot break again.
    """
    from si_model.parsing.keys import corner_label, parse_corner
    from si_model.training.loo import make_split
    lv = {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}
    labels = [corner_label(v, l, "SSPG")
              for v in (0.5, 0.54, 0.6, 0.685) for l in ("rcmax", "cmax")]
    vt64 = np.asarray([parse_corner(c, lv, "SSPG") for c in labels])
    vt = np.asarray(vt64, np.float32)                    # what the cache does
    assert float(vt[2, 0]) != 0.54, "this test is pointless if the float32 round-trip does not change the value"
    cfg = {"data": {"ref_corner": "SSPG_0p685V_cmax"},
           "split": {"hidden_voltages": [0.54], "min_seen": 1},
           "base": {"axes": [{"name": "v", "ref": 0.685, "order": 2},
                             {"name": "rc", "ref": 0.0, "order": 1, "levels": lv}]}}
    sp = make_split(labels, vt, cfg)
    assert {labels[i] for i in sp.hidden_idx} == {"SSPG_0p54V_rcmax", "SSPG_0p54V_cmax"}


def test_hidden_levels_hides_whole_column(project):
    """Custom level names (rcmin/cmax/rcmax) must work -- only the built-in
    Cmin/Cnom/Cmax used to, and anything else died in a float() conversion."""
    got = _hidden_labels(project, {"hidden_voltages": [], "hidden_levels": ["rcmin"]})
    assert got == {f"SSPG_{v}V_rcmin" for v in ("0p5", "0p54", "0p6", "0p685")}


def test_hidden_corners_picks_single_cells(project):
    got = _hidden_labels(project, {"hidden_voltages": [],
                                   "hidden_corners": [[0.6, "rcmax"], [0.5, "rcmin"]]})
    assert got == {"SSPG_0p6V_rcmax", "SSPG_0p5V_rcmin"}


def test_seen_voltages_inverts_the_rule(project):
    got = _hidden_labels(project, {"hidden_voltages": [], "seen_voltages": [0.5, 0.685]})
    assert got == {f"SSPG_{v}V_{l}" for v in ("0p54", "0p6")
                   for l in ("rcmax", "cmax", "rcmin")}


def test_holdout_rules_combine(project):
    got = _hidden_labels(project, {"hidden_voltages": [0.54], "hidden_levels": ["rcmin"],
                                   "hidden_corners": [[0.6, "rcmax"]]})
    assert "SSPG_0p685V_rcmin" in got and "SSPG_0p6V_rcmax" in got
    assert "SSPG_0p685V_cmax" not in got


def test_seen_and_hidden_voltages_conflict_is_rejected(project):
    _use_voltage_row_holdout(project)
    project["corners"]["seen_voltages"] = [0.5]
    with pytest.raises(AssertionError, match="either seen_voltages"):
        expand(project)


def test_anchor_may_not_be_hidden(project):
    project["corners"]["hidden_levels"] = ["cmax"]      # ref_level is cmax
    with pytest.raises(AssertionError, match="hidden_levels"):
        expand(project)


def test_anchor_must_exist_at_every_temp(project):
    project["corners"]["ref_level"] = "rcmin"           # 125C has no rcmin
    with pytest.raises(AssertionError, match="levels"):
        expand(project)


# ---- do the OLS / parsing knobs reach the engine -----------------------------------
def test_base_knobs_reach_the_engine(project):
    project["base"].update(v_order=3, level_order=2, cross_max_degree=3,
                           v_fit_scale=100, v_token_scale=0.5, v_gap_cap=9.0)
    ax = expand(project)[0]["cfg"]["base"]["axes"][0]
    assert (ax["order"], ax["fit_scale"], ax["token_scale"], ax["gap_cap"]) == \
        (3, 100.0, 0.5, 9.0)
    assert expand(project)[0]["cfg"]["base"]["cross_max_degree"] == 3


def test_local_weighting_needs_bandwidth(project):
    project["base"]["weighting"] = "local"
    project["base"].pop("bandwidth", None)
    with pytest.raises(AssertionError, match="bandwidth"):
        expand(project)
    project["base"]["bandwidth"] = [0.05, 1.0]
    assert expand(project)[0]["cfg"]["base"]["bandwidth"] == [0.05, 1.0]


def test_cell_taxonomy_reaches_the_builder(project):
    project["parsing"] = {"cell_taxonomy": {"strip_prefixes": ["SEC9T_"],
                                            "family_rules": [["^ND", "NAND"]]}}
    assert expand(project)[0]["cfg"]["data"]["cell_taxonomy"]["strip_prefixes"] == ["SEC9T_"]


def test_levels_layout_knobs_reach_discovery(project):
    project["files"].update(layout="levels", annotated_suffix=".rpt",
                            voltage_regex=r"_v(0p\d+)_")
    pat = expand(project)[0]["cfg"]["data"]["patterns"]
    assert pat["layout"] == "levels" and pat["annotated_suffix"] == ".rpt"
    assert pat["voltage_regex"] == r"_v(0p\d+)_"


def test_split_overrides(project):
    project["split"] = {"min_seen": 4, "path_split_seed": 7}
    cfg = expand(project)[0]["cfg"]
    assert cfg["split"]["min_seen"] == 4
    assert cfg["train"]["split_seed"] == 7          # the trainer reads it from train


def test_select_filters(project):
    models = expand(project)
    assert [m["name"] for m in select(models, design="gpu")] == ["gpu/125", "gpu/m25"]
    assert [m["name"] for m in select(models, temp="125")] == ["cpu/125", "gpu/125"]
    with pytest.raises(AssertionError, match="no model matches"):
        select(models, design="nope")


# =========================================================== 2. corner discovery
def _cfg(root, temp, levels):
    return {"data": {"annotated_dir": str(root), "temp": temp,
                     "corner_prefix": "SSPG", "rc_corners": levels,
                     "patterns": {"layout": "flat", "annotated_regex": FLAT_RE}},
            "base": {"axes": [{"name": "v", "ref": 0.685, "order": 2},
                              {"name": "rc", "ref": 0, "order": 2,
                               "levels": {"rcmin": -1, "cmax": 0, "rcmax": 1}}]}}


def test_discovery_filters_by_temp_and_level(tree):
    c125 = discover_annotated(_cfg(tree / "cpu", 125, ["rcmax", "cmax"]))
    assert len(c125) == 8                           # 4V x 2 levels; m25 files ignored
    cm25 = discover_annotated(_cfg(tree / "cpu", "m25", ["rcmax", "cmax", "rcmin"]))
    assert len(cm25) == 12
    assert set(c125).issubset(set(cm25))            # temperature is not in the label (split dimension)


def test_discovery_label_and_sort(tree):
    corners, ann, xt = discover(_cfg(tree / "cpu", 125, ["rcmax", "cmax"]))
    assert corners[0] == "SSPG_0p5V_cmax"           # 0p5000 -> normalised to 0p5
    assert corners[-1] == "SSPG_0p685V_rcmax"       # sorted by (voltage, level value)
    assert xt is None                               # no crosstalk_dir -> no SI
    assert os.path.basename(ann["SSPG_0p5V_cmax"]) == "report.sspg_0p5000_125c_cmax.rpt"


@pytest.mark.parametrize("fname,temp,want", [
    # the reference format
    ("report.sspg_0p5000_125c_rcmax.rpt", "125", (0.5, "rcmax")),
    # with and without the trailing c on the temperature
    ("report.sspg_0p5000_125_rcmax.rpt", "125", (0.5, "rcmax")),
    # field order swapped
    ("report.sspg_0p5000_rcmax_125c.rpt", "125", (0.5, "rcmax")),
    ("RCMAX.125.SSPG.0p5000.rpt", "125", (0.5, "rcmax")),
    # letter case
    ("report.SSPG_0P5000_125C_RCMAX.rpt", "125", (0.5, "rcmax")),
    # voltage spellings: 0p5400 / 0.5400 / v0p54
    ("report.sspg_0.5400_125c_rcmax.rpt", "125", (0.54, "rcmax")),
    ("ibex_v0p54_rcmax_125.timing.rpt", "125", (0.54, "rcmax")),
    # hyphen separators -> a leading '-' is not a minus sign
    ("sspg-0p5000-125c-rcmax.rpt", "125", (0.5, "rcmax")),
    # negative temperatures: m25 / M25 / -25
    ("report.sspg_0p5000_m25c_rcmin.rpt", "m25", (0.5, "rcmin")),
    ("report.SSPG_0P5000_M25_RCMIN.rpt", "m25", (0.5, "rcmin")),
    ("report.sspg_0p5000_-25c_rcmin.rpt", "m25", (0.5, "rcmin")),
    # cmax must not match inside rcmax
    ("report.sspg_0p6850_125c_cmax.rpt", "125", (0.685, "cmax")),
    # --- these must be filtered out ---
    ("report.sspg_0p5000_125c_rcmax.rpt", "m25", None),    # different temperature
    ("report.sspg_0p5000_m25c_rcmax.rpt", "125", None),    # different temperature (other way)
    ("report.sspg_0p5000_125c_cworst.rpt", "125", None),   # unknown level
    ("report.sspg_125c_rcmax.rpt", "125", None),           # no voltage
    ("readme.txt", "125", None),                           # unrelated file
])
def test_filename_matching_is_order_and_case_free(fname, temp, want):
    """Filename formats differ per vendor: order, case, separators, the trailing
    c on the temperature, and the voltage spelling (0p54 / 0.54) all vary, and
    every one of them must read as the same corner.

    The only thing separating the two is that a voltage always carries a decimal
    marker while a temperature is an integer, so that boundary (not reading
    '.125.' as 0.125) is pinned here as well.
    """
    from si_model.parsing.discovery import _match_tokens
    got = _match_tokens(fname, {"data": {}}, ["rcmax", "cmax", "rcmin"], "SSPG", temp)
    if want is None:
        assert got is None
    else:
        assert got is not None, "no match"
        assert abs(got[0] - want[0]) < 1e-9 and got[1] == want[1]


def test_same_folder_annotated_and_crosstalk(tmp_path):
    """The `pt_si_re` layout: one corner folder holds annotated and crosstalk.

    Both carry the corner token, so as-is two files match the same corner. This
    pins both halves: (a) that situation is caught by an error that says how to
    fix it, and (b) supplying files.*_contains makes it work.
    """
    from si_model.parsing.discovery import discover, discover_annotated
    root = tmp_path / "boom" / "round2"
    for v in ("0p5", "0p6"):
        for lv in ("rcmax", "cmax"):
            c = f"SSPG_{v}V_125C_{lv}"
            d = root / c
            d.mkdir(parents=True)
            (d / f"{c}_fixed_annotated.txt").touch()
            (d / f"{c}.path_context_si_compact.by_path.rpt").touch()
            (d / "corner_info.tcl").touch()          # intermediate files must be ignored

    def cfg(contains=False):
        pat = {"layout": "flat", "annotated_regex": "auto", "crosstalk_regex": "auto"}
        if contains:
            pat["annotated_contains"] = "_fixed_annotated"
            pat["crosstalk_contains"] = "by_path"
        return {"data": {"annotated_dir": str(root), "crosstalk_dir": str(root),
                         "temp": 125, "corner_prefix": "SSPG",
                         "rc_corners": ["rcmax", "cmax"], "patterns": pat},
                "base": {"axes": [{"name": "v", "ref": 0.6, "order": 2},
                                  {"name": "rc", "ref": 0, "order": 1,
                                   "levels": {"cmax": 0, "rcmax": 1}}]}}

    with pytest.raises(AssertionError, match="same folder"):
        discover_annotated(cfg(False))

    corners, ann, xt = discover(cfg(True))
    assert len(corners) == 4 and xt is not None and len(xt) == 4
    assert all(a.endswith("_fixed_annotated.txt") for a in ann.values())
    assert all(x.endswith(".by_path.rpt") for x in xt.values())


def test_crosstalk_subdir_inside_design_is_excluded(tmp_path):
    """Crosstalk nested UNDER the design folder must stay out of the recursive
    annotated search."""
    from si_model.parsing.discovery import discover
    d = tmp_path / "boom"
    (d / "xtalk").mkdir(parents=True)
    for v in ("0p5", "0p6"):
        for lv in ("rcmax", "cmax"):
            (d / f"report.sspg_{v}_125c_{lv}.rpt").touch()
            (d / "xtalk" / f"xt.sspg_{v}_125c_{lv}.rpt").touch()
    cfg = {"data": {"annotated_dir": str(d), "crosstalk_dir": str(d / "xtalk"),
                    "temp": 125, "corner_prefix": "SSPG",
                    "rc_corners": ["rcmax", "cmax"],
                    "patterns": {"layout": "flat", "annotated_regex": "auto",
                                 "crosstalk_regex": "auto"}},
           "base": {"axes": [{"name": "v", "ref": 0.6, "order": 2},
                             {"name": "rc", "ref": 0, "order": 1,
                              "levels": {"cmax": 0, "rcmax": 1}}]}}
    corners, ann, xt = discover(cfg)
    assert len(corners) == 4
    assert all("xtalk" not in a for a in ann.values()), "annotated picked up xtalk"


def test_discovery_wrong_prefix_is_loud(tree):
    cfg = _cfg(tree / "cpu", 125, ["rcmax", "cmax"])
    cfg["data"]["corner_prefix"] = "FFPG"
    with pytest.raises(AssertionError, match="no annotated corners discovered"):
        discover_annotated(cfg)


def test_levels_layout_still_supported(tmp_path):
    """The level-subfolder layout (<dir>/<LEVEL>/<one file per voltage>) works
    unchanged."""
    root = tmp_path / "ann"
    for lv in ("Cmin", "Cnom", "Cmax"):
        (root / lv).mkdir(parents=True)
        for v in ("0p6", "0p8"):
            (root / lv / f"saed14rvt_tt{v}vm40c_x_fixed_annotated.txt").touch()
    cfg = {"data": {"annotated_dir": str(root), "temp": "m40",
                    "rc_corners": ["Cmin", "Cnom", "Cmax"]},
           "base": {"axes": [{"name": "v", "ref": 0.8, "order": 3},
                             {"name": "rc", "ref": 0.0, "order": 2}]}}
    got = discover_annotated(cfg)      # no levels: in axes -> built-in RC map
    assert len(got) == 6 and "TT_0p8V_Cnom" in got


# =================== 2.5 end-to-end: report -> npz -> base (no torch needed)
def _fake_report(v: float, lvv: float, n_paths: int = 12) -> str:
    """A minimal but real report in the parser's format. The voltage/BEOL
    dependence is physically plausible (non-linear) so the base polynomial has
    something real to fit."""
    L = []
    for i in range(n_paths):
        s, e = f"u_a/reg_{i}_", f"u_b/reg_{i}_"
        d = 0.30 * (0.8 / v) ** 1.8 + 0.02 * lvv + 0.004 * i + 0.01 * (0.8 / v) * lvv
        arr, req = 1.0 + d, 2.0
        L += [
            f"### FIXED_PATH idx={i} key={s}->{e}_#{i}",
            f"  Startpoint: {s}", f"  Endpoint: {e}",
            "  clock clk (rise edge)                    0.0000    0.0000",
            f"  {s}/CK (SAEDRVT14_FDP_1)            0.0100    0.0500    0.0500 r",
            f"  {s}/Q (SAEDRVT14_FDP_1)             0.0200 {d*0.4:9.4f} {1.0+d*0.4:9.4f} r",
            f"  n_{i}_0 (net)                      3    0.0120    1.2000    5.6000    0.0030",
            f"  u_c/g{i}/Y (SAEDRVT14_ND2_1) <-     0.0250 {d*0.6:9.4f} {arr:9.4f} f",
            "  clock clk (rise edge)                    2.0000    2.0000",
            f"  {e}/CK (SAEDRVT14_FDP_1)            0.0100    0.0500    2.0500 r",
            "  library setup time                     -0.0450    1.9550",
            f"  data arrival time                    {arr:9.4f}",
            f"  data required time                   {req:9.4f}",
            f"  slack (MET)                          {req-arr:9.4f}", "",
        ]
    return "\n".join(L)


@pytest.fixture
def real_tree(tmp_path):
    """The shipped layout exactly: <root>/{si_corner_model, boomcore} plus
    parseable reports."""
    (tmp_path / os.path.basename(REPO_ROOT)).mkdir()
    lev = {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}
    d = tmp_path / "boomcore" / "setup"
    d.mkdir(parents=True)
    for temp, levels in (("125", ["rcmax", "cmax"]),
                         ("m25", ["rcmax", "cmax", "rcmin"])):
        for lv in levels:
            for vf, vtok in ((0.5, "0p5000"), (0.54, "0p5400"),
                             (0.6, "0p6000"), (0.685, "0p6850")):
                (d / f"report.sspg_{vtok}_{temp}c_{lv}.rpt").write_text(
                    _fake_report(vf, lev[lv]))
    return tmp_path


def test_end_to_end_build_and_base(real_tree, tmp_path, monkeypatch):
    """The whole span: report -> dataset.npz -> seen/hidden split -> OLS base.

    This is everything that runs without torch, i.e. exactly what can be checked
    on site before training.
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.training.loo import build_design, fit_field, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)                       # cache lands under here
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]                     # the fixture's design name
    p["files"]["crosstalk_subdir"] = None           # this fixture verifies without SI
    models = select(expand(p), design="boomcore")
    assert [m["name"] for m in models] == ["boomcore/125", "boomcore/m25"]

    for m, want_c in zip(models, (8, 12)):            # 4V x 2 levels, 4V x 3 levels
        n_hidden = len(m["cfg"]["split"]["hidden_corners"]) or want_c // 4
        build(m["cfg"])
        ds = dict(np.load(m["cfg"]["data"]["cache"]))
        assert ds["slack"].shape == (12, want_c), "12 paths x want_c corners"
        assert np.isfinite(ds["slack"]).all()
        assert (ds["si_label"] == 0).all()            # no crosstalk -> 0
        assert ds["node_mask"].any() and len(ds["fam_vocab"]) > 1

        split = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
        assert split.hidden.sum() == n_hidden
        assert not split.hidden[split.ref_ci]

        # pass y exactly as the real path does -> the basis is picked by seen-LOO
        phi, coords, exps, _ = build_design(m["cfg"], split, y=ds["slack"])
        loo, _ = fit_field(ds["slack"], phi, split, coords, m["cfg"])
        assert np.isfinite(loo).all()
        # the synthetic data is smooth, so base must fit the hidden corners well
        hid = split.hidden_idx
        mae_ps = np.abs(loo[:, hid] - ds["slack"][:, hid]).mean() * 1000
        assert mae_ps < 20, f"hidden base MAE too large: {mae_ps:.2f} ps"
        assert phi.shape[1] < split.seen.sum(), (
            "the chosen basis must leave at least 1 dof (or seen-LOO means nothing)")


def test_hidden_labels_never_reach_the_base(real_tree, tmp_path, monkeypatch):
    """Hidden-corner labels must never enter training.

    Method: corrupt only the hidden columns' labels with noise and recompute the
    base. If a hidden label leaked anywhere, the seen-side outputs would change.
    What is checked here -- base/resid -- is both the network's training target
    and its token input, so leaving it unchanged means there is no leak path.
    (The torch-level check -- weights and predictions bit-identical -- is done
    separately.)
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.training.loo import compute_base, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]                     # the fixture's design name
    p["files"]["crosstalk_subdir"] = None           # this fixture verifies without SI
    m = select(expand(p), design="boomcore", temp="m25")[0]
    build(m["cfg"])
    ds = dict(np.load(m["cfg"]["data"]["cache"]))

    split = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
    S, H = split.seen_idx, split.hidden_idx
    assert len(H) and len(S), "this test needs both hidden and seen to mean anything"

    poisoned = dict(ds)
    rng = np.random.RandomState(0)
    for k in ("slack", "si_label", "arrival", "required",
              "launch_clk", "capture_clk", "lib_check_time"):
        poisoned[k] = ds[k].copy()
        poisoned[k][:, H] = rng.uniform(-1e3, 1e3, size=(ds[k].shape[0], len(H)))
    assert not np.array_equal(poisoned["slack"][:, H], ds["slack"][:, H])
    assert np.array_equal(poisoned["slack"][:, S], ds["slack"][:, S])

    a = compute_base(ds, split, m["cfg"])
    b = compute_base(poisoned, split, m["cfg"])
    # seen is the training target/tokens, hidden the prediction baseline --
    # neither may depend on hidden labels
    assert np.array_equal(a.base_hat[:, S], b.base_hat[:, S])
    assert np.array_equal(a.base_hat[:, H], b.base_hat[:, H])
    assert np.array_equal(a.resid[:, S], b.resid[:, S])
    assert np.array_equal(a.si_smooth_hat[:, S], b.si_smooth_hat[:, S])

    # the token normalisation statistics must also come from seen only
    def stats(d, base):
        raw = np.stack([d["slack"], d["si_label"], d["arrival"], d["required"],
                        d["launch_clk"], d["capture_clk"], d["lib_check_time"],
                        base.resid], -1)
        return (np.nanmean(raw[:, S], axis=(0, 1)), np.nanstd(raw[:, S], axis=(0, 1)))
    (mu_a, sd_a), (mu_b, sd_b) = stats(ds, a), stats(poisoned, b)
    assert np.array_equal(mu_a, mu_b) and np.array_equal(sd_a, sd_b)


# ==================================================== 3. engine math / helpers
def _basis(axes, cross_max_degree=3, cross_terms=True):
    return {"base": {"axes": axes, "cross_terms": cross_terms,
                     "cross_max_degree": cross_max_degree}}


def test_basis_generation():
    cfg = _basis([{"name": "v", "ref": 0.8, "order": 3},
                  {"name": "rc", "ref": 0.0, "order": 2}])
    _, names, _ = expand_terms(cfg)
    assert set(names) == {"dv", "dv2", "dv3", "drc", "drc2", "dvdrc", "dv2drc", "dvdrc2"}


def test_basis_drops_rank_deficient_terms():
    # 4 seen voltages -> no dv4; 3 BEOL levels -> no drc3
    cfg = _basis([{"name": "v", "ref": 0.8, "order": 4},
                  {"name": "rc", "ref": 0.0, "order": 3}])
    _, names, dropped = expand_terms(cfg, seen_levels=[4, 3])
    assert {"dv4", "drc3"} <= set(dropped)
    assert "dv4" not in names and "drc3" not in names
    assert "dv3" in names and "drc2" in names


def test_basis_cross_terms_off():
    cfg = _basis([{"name": "v", "ref": 0.8, "order": 2},
                  {"name": "rc", "ref": 0.0, "order": 2}], cross_terms=False)
    _, names, _ = expand_terms(cfg)
    assert set(names) == {"dv", "dv2", "drc", "drc2"}


def test_adaptive_base_reduces_to_global():
    """With grid=[None], the adaptive base equals the global closed-form LOO."""
    rng = np.random.RandomState(0)
    gv, gr = np.meshgrid(np.array([0.6, 0.65, 0.7, 0.75, 0.8]),
                         np.array([-1.0, 0.0, 1.0]), indexing="ij")
    coords = np.stack([gv.ravel() - 0.8, gr.ravel()], 1)
    C = coords.shape[0]
    cfg = _basis([{"name": "v", "ref": 0.8, "order": 3},
                  {"name": "rc", "ref": 0.0, "order": 2}])
    exps, _, _ = expand_terms(cfg, seen_levels=[5, 3])
    phi = design_matrix(coords, exps)
    seen = np.ones(C, bool)
    seen[7] = seen[11] = False
    y = (phi @ rng.randn(phi.shape[1]))[None, :] + 0.01 * rng.randn(4, C)
    out, picks = fit_base_adaptive(y, phi, seen, coords, grid=[None])
    _, loo = fit_base(y, phi, seen)
    assert np.allclose(out, loo, atol=1e-6)
    assert list(picks.values())[0] == C


def test_path_key_normalization():
    # _#idx is a per-report ordinal, not a path identifier -- keeping it breaks
    # the join across corners
    assert norm_path_key("A->B_#282") == "A->B"
    assert norm_path_key("A->B#5") == "A->B"
    assert norm_path_key("A->B") == "A->B"


def test_corner_label_roundtrip():
    lv = {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}
    assert corner_label(0.685, "cmax", prefix="SSPG") == "SSPG_0p685V_cmax"
    assert parse_corner("SSPG_0p685V_cmax", lv, prefix="SSPG") == (0.685, 0.0)
    assert parse_corner("SSPG_0p5V_rcmax", lv, prefix="SSPG") == (0.5, 1.0)
    # temperature-style labels (data whose second axis is temperature) too
    assert parse_corner("SSPG_0p9V_m25C", prefix="SSPG") == (0.9, -25.0)


def test_filename_voltage_and_xt_parsing():
    assert abs(parse_voltage_from_annotated("saed14rvt_tt0p605vm40c_x.txt") - 0.605) < 1e-9
    assert parse_xt_name("SSPG_0p55V_125C.foo.by_path.rpt", prefix="SSPG") == (0.55, "125")


def test_cell_taxonomy_defaults_are_safe():
    assert cell_family("SAEDRVT14_ND2_CDC_0P5") == "NAND"
    assert cell_family("SAEDRVT14_FDP_V2LP_2") == "DFF"
    assert cell_drive("SAEDRVT14_BUF_20") == 20.0
    assert cell_drive("SAEDRVT14_NR3B_1P5") == 1.5
    # an unknown library is not an error: it trains as <unk> + drive 1.0
    assert cell_family("SEC9T_WHATEVER_X4") == "<unk>"
    assert cell_drive("SEC9T_WHATEVER") == 1.0
