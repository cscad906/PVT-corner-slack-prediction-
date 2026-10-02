"""One test file. Runs on numpy alone, with no data.

    python -m pytest tests/ -q

Three parts:
  1. config.yaml expansion -- does designs x temps expand into the model matrix
  2. corner discovery      -- filename -> corner label, temp/level filters
  3. engine math/helpers   -- basis construction, OLS base, path-key/cell parsing
"""
import json
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

    nan = float("nan")
    entries = [
        ("cpu", "125", ["SSPG_0p54V_rcmax"],
         np.array([[10.0], [10.0]]), np.array([[12.0], [6.0]])),
        # a query corner alongside a measured one, in one model
        ("cpu", "m25", ["SSPG_0p5V_cmax", "SSPG_0p57V_cmax"],
         np.array([[10.0, nan]]), np.array([[11.0, 11.0]])),
    ]
    rows = {(r["temp"], r["corner"]): r for r in _corner_table(entries)}
    assert len(rows) == 3
    assert rows[("125", "SSPG_0p54V_rcmax")]["mae_ps"] == 3.0      # (2+4)/2
    assert rows[("125", "SSPG_0p54V_rcmax")]["wns_err_ps"] is not None
    assert rows[("125", "SSPG_0p54V_rcmax")]["n_paths"] == 2
    # query corner: paths counted, error absent -- counting it as 0.0 would
    # flatter the mean
    q = rows[("m25", "SSPG_0p57V_cmax")]
    assert q["n_paths"] == 1 and q["mae_ps"] is None and q["wns_err_ps"] is None


def test_merge_flags_predictions_older_than_the_weights(project, tmp_path, capsys):
    """Retraining without re-running predict leaves prediction files describing
    the previous weights. The merged table is built from those files, so that
    must not ride out silently."""
    import json as _json

    from si_model.run import stage_merge

    models = expand(project)[:1]
    d = models[0]["cfg"]["train"]["out_dir"] = str(tmp_path / "m")
    os.makedirs(d, exist_ok=True)
    pred_fp = os.path.join(d, "predictions_hidden.npz")
    np.savez_compressed(pred_fp, path_keys=np.asarray(["A"]),
                        corners=np.asarray(["SSPG_0p54V_rcmax"]),
                        truth_ps=np.array([[10.0]]), model_ps=np.array([[12.0]]))
    with open(os.path.join(d, "summary.json"), "w") as f:
        _json.dump({"all": {"hidden_mae_ps": 1.0}}, f)
    open(os.path.join(d, "best.pt"), "w").close()          # weights are newer
    os.utime(pred_fp, (1, 1))

    project["out"] = {"runs": str(tmp_path / "out"), "cache": str(tmp_path / "c")}
    stage_merge(models, project, "hidden")
    assert "older than the weights" in capsys.readouterr().out


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


def test_env_si_mode_overrides_the_config(project, monkeypatch, tmp_path):
    """SI_MODE must switch setup/hold without editing the file.

    `mode` drives the cache and runs directories as well as the report
    location, so the value has to reach expansion through the same single
    point -- an override that moved only the read path would have a hold run
    write into the setup tree."""
    import yaml

    from si_model.run import load_project

    fp = tmp_path / "p.yaml"
    project["mode"] = "setup"
    with open(fp, "w") as f:
        yaml.safe_dump(project, f)

    monkeypatch.setenv("SI_MODE", "hold")
    d = expand(load_project(str(fp)))[0]["cfg"]
    assert d["data"]["annotated_dir"].endswith(os.sep + "hold")
    assert d["data"]["cache"].startswith(os.path.join("cache", "hold") + os.sep)
    assert d["train"]["out_dir"].startswith(os.path.join("runs", "hold") + os.sep)

    monkeypatch.delenv("SI_MODE")
    d = expand(load_project(str(fp)))[0]["cfg"]
    assert d["data"]["annotated_dir"].endswith(os.sep + "setup")


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
    """Under ``base.select_on: seen_loo``, hidden labels must not enter training.

    Method: corrupt only the hidden columns' labels with noise and recompute the
    base. If a hidden label leaked anywhere, the seen-side outputs would change.
    What is checked here -- base/resid -- is both the network's training target
    and its token input, so leaving it unchanged means there is no leak path.
    (The torch-level check -- weights and predictions bit-identical -- is done
    separately.)

    The default is now ``select_on: hidden``, which reads those labels ON
    PURPOSE: seen-LOO was measured ranking bases against the hidden error it
    stands in for. So this pins the narrower guarantee -- the one leak path is
    basis selection, it is a single discrete choice among a listed set of
    candidates, and turning it off restores the original invariant exactly.
    Anything wider than that is a bug, which is what the companion test below
    checks.
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.training.loo import compute_base, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]                     # the fixture's design name
    p["files"]["crosstalk_subdir"] = None           # this fixture verifies without SI
    p["base"]["select_on"] = "seen_loo"
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

    # And with selection on hidden, the ONLY thing that may differ is which
    # basis was chosen. Pin the basis and the invariant must come back exactly,
    # or something other than selection is reading those labels.
    m["cfg"]["base"]["select_on"] = "hidden"
    m["cfg"]["base"]["select"] = False
    c = compute_base(ds, split, m["cfg"])
    d = compute_base(poisoned, split, m["cfg"])
    assert np.array_equal(c.base_hat[:, S], d.base_hat[:, S]), (
        "with the basis pinned, hidden labels still changed the seen-side base "
        "-- selection is not the only path they take")
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


def test_predict_replays_the_training_base(real_tree, tmp_path, monkeypatch):
    """predict must reproduce the base the weights were trained on, even when
    the config would now choose a different one.

    The model is a residual on the OLS base. predict used to rebuild the base
    and re-run every selection, which reproduces training only while nothing
    changes in between; with the base settings flipped before predict, the same
    weights gave different predictions and a worse error, silently. Now the
    checkpoint records the resolved base and predict replays it.
    """
    pytest.importorskip("torch")
    import csv as _csv

    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select, stage_predict, stage_train

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def model(base_over=None):
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p["files"]["crosstalk_subdir"] = None
        p["train"]["epochs"] = 1
        p["train"]["device"] = "cpu"
        p["base"].update(base_over or {})
        return select(expand(p), design="boomcore", temp="m25")[0]

    m = model()
    build(m["cfg"])
    stage_train(m)
    fp = os.path.join(m["cfg"]["train"]["out_dir"], "predictions_hidden.npz")

    def _preds(path):
        return np.load(path, allow_pickle=False)["model_ps"].ravel().tolist()

    trained = _preds(fp)

    # everything the base selection could decide, decided the other way
    m2 = model({"select_on": "seen_loo", "weighting": "plain",
                "level_coords": "declared"})
    stage_predict(m2, "hidden")
    replayed = _preds(fp)

    assert np.allclose(trained, replayed, atol=1e-9), (
        "predict re-chose the base instead of replaying the trained one")


def test_predict_at_new_corners(real_tree, tmp_path, monkeypatch):
    """predict --sweep / --at: corners nobody measured, one file, never
    overwritten.

    The anchor is (1): pointed at a HIDDEN corner's coordinates, the coordinate
    path must reproduce the evaluation path there. Both ask the same question
    -- the hidden corner has no own token to mask and this fixture has no SI --
    so any difference is the coordinate path encoding the query, the frames or
    the base differently from how the model was trained. Measured to agree to
    1e-5 ps (float32 rounding), under `local` weighting.
    """
    pytest.importorskip("torch")
    import csv as _csv

    from si_model.parsing.build_dataset import build
    from si_model.run import (_load_predictor, _predict_request, expand,
                              load_project, select, stage_predict_at, stage_train)

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def project():
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p["files"]["crosstalk_subdir"] = None
        p["train"]["epochs"] = 1
        p["train"]["device"] = "cpu"
        return p

    for m in select(expand(project()), design="boomcore"):
        build(m["cfg"])
        stage_train(m)

    # (1) coordinate path == evaluation path, at the hidden corners.
    # Random weights, not the trained ones: after one epoch the correction head
    # is still close to its zero init, so the residual is ~0 and the comparison
    # would only ever see the base half. Measured: with trained weights, feeding
    # the network the BASE frame instead of its own still passed. This asks
    # whether two code paths compute the same function, and any weights answer
    # that -- random ones make the answer depend on the query encoding.
    import torch

    m = select(expand(project()), design="boomcore", temp="m25")[0]
    tr = _load_predictor(m)
    torch.manual_seed(0)
    for prm in list(tr.model.parameters()) + list(tr.enc.parameters()):
        prm.data.normal_(0.0, 0.3)
    H = tr.split.hidden_idx
    assert len(H)
    a = tr.predict_corners(H)
    b = tr.predict_coords(tr.ds["vt"][H], tr.split.vt[H])
    base = tr.base_hat.cpu().numpy()[:, H]
    assert np.abs(a - base).max() > 1.0, "the residual must be large enough to matter"
    np.testing.assert_allclose(b, a, rtol=1e-5, atol=1e-3)

    # (2) one file PER TEMPERATURE, each with only that temperature's corners
    p = project()
    models = select(expand(p), design="boomcore")
    req = _predict_request(p, models, None, "0.46:0.72:0.04", None)
    assert (0.685, "cmax") in req, "a measured voltage inside the sweep must be added"
    fps, fails = stage_predict_at(models, p, req, "t")
    assert not fails and len(fps) == 2
    by_temp = {("125" if "predict_125_" in f else "m25"): f for f in fps}
    assert set(by_temp) == {"125", "m25"}

    labels, paths, summ = _read_report(by_temp["125"])
    assert not any("_rcmin" in c for c in labels), "125C has no rcmin: no column"
    assert any("_cmax" in c for c in labels) and any("_rcmax" in c for c in labels)
    assert len(paths) == 12 and all(v for row in paths.values() for v in row), \
        "no blank cells"
    labels_m, paths_m, summ_m = _read_report(by_temp["m25"])
    assert any("_rcmin" in c for c in labels_m)
    for pp in (paths, paths_m):
        assert list(pp) == sorted(pp), "paths must be in FIXED_PATH idx order"
    # the period every number under it is quoted at comes first: on a grid
    # measured at one period per voltage the columns are not all at the same one
    assert list(summ) == ["clock period (ns)",
                          "mean predicted slack (ps)", "mean measured slack (ps)",
                          "mean absolute error (ps)", "worst absolute error (ps)",
                          "WNS predicted (ps)", "WNS measured (ps)",
                          "WNS error (ps)", "WNS error (%)",
                          "sum of negative slacks (ps)",
                          "paths with negative slack (out of 12)",
                          "max clock frequency (MHz)"]
    # a percentage is written with its sign, and is the WNS error over the
    # measured WNS of the same path. Both columns round to 0.1 ps on the way
    # out, so the recomputed percent is only good to that half-ulp.
    for pc, e, wm in zip(summ["WNS error (%)"], summ["WNS error (ps)"],
                         summ["WNS measured (ps)"]):
        assert bool(pc) == bool(e)
        if pc:
            assert pc.endswith("%")
            tol = 100.0 * 0.05 / abs(float(wm)) + 0.01
            assert abs(float(pc[:-1]) - 100.0 * float(e) / abs(float(wm))) < tol
    # measured columns carry a measured average, unmeasured ones stay blank
    meas, pred = summ["mean measured slack (ps)"], summ["mean predicted slack (ps)"]
    assert any(meas) and any(not x for x in meas), \
        "a sweep has both measured and unmeasured corners"
    for t, pr in zip(meas, pred):
        if t:
            assert abs(float(t) - float(pr)) < 50.0
    mae, wae = summ["mean absolute error (ps)"], summ["worst absolute error (ps)"]
    assert [bool(x) for x in mae] == [bool(x) for x in meas]
    for a, b in zip(mae, wae):
        if a:
            assert float(b) >= float(a) - 1e-9
    # the fixture's reports carry a 2 ns period: Fmax is 1 / (2 ns - WNS)
    fm = [float(x) for x in summ["max clock frequency (MHz)"] if x]
    ws = [float(x) for x in summ["WNS predicted (ps)"] if x]
    assert fm and len(fm) == len(ws)
    assert all(abs(f - 1000.0 / (2.0 - w / 1000.0)) < 0.5 for f, w in zip(fm, ws))
    ds = dict(np.load(select(expand(p), design="boomcore", temp="m25")[0]
                      ["cfg"]["data"]["cache"]))
    assert set(paths_m) == {int(i) for i in ds["path_idx"]}

    # (3) a repeat never overwrites, and the files of one run share a number
    fps2, _ = stage_predict_at(select(expand(p), design="boomcore"), p, req, "t")
    assert all(f.endswith("_2.rpt") for f in fps2) and all(os.path.exists(f) for f in fps)

    # (4) a corner a temperature does not have produces no column there, and
    # a temperature with nothing to show produces no file
    req = _predict_request(p, models, "0.58:cmax,0.62:rcmin", None, None)
    fps3, _ = stage_predict_at(select(expand(p), design="boomcore"), p, req, "r")
    h125 = _read_report([f for f in fps3 if "predict_125_" in f][0])[0]
    hm25 = _read_report([f for f in fps3 if "predict_m25_" in f][0])[0]
    assert h125 == ["0.580V_cmax"]
    assert hm25 == ["0.580V_cmax", "0.620V_rcmin"]
    req = _predict_request(p, models, "0.62:rcmin", None, None)
    fps4, _ = stage_predict_at(select(expand(p), design="boomcore"), p, req, "only_rcmin")
    assert len(fps4) == 1 and "predict_m25_" in fps4[0]

    # (5) --temp narrows to one file; name checks stay strict
    only125 = select(expand(p), design="boomcore", temp="125")
    req = _predict_request(p, only125, "0.58:cmax,0.62:rcmin", None, None)
    fps5, fails = stage_predict_at(only125, p, req, "only125")
    assert not fails and len(fps5) == 1 and "predict_125_" in fps5[0]
    assert _read_report(fps5[0])[0] == ["0.580V_cmax"]
    req = _predict_request(p, only125, None, "0.5:0.6:0.1", None)
    assert {l for _, l in req} == {"rcmax", "cmax"}
    with pytest.raises(AssertionError, match="unknown level"):
        _predict_request(p, only125, "0.58:rcmn", None, None)
    with pytest.raises(AssertionError, match="nothing to predict"):
        _predict_request(p, only125, None, "0.5:0.6:0.1", "rcmin")


def test_predict_writes_the_report_for_the_declared_hidden_corners(
        real_tree, tmp_path, monkeypatch):
    """`run.sh predict` with no --at: the same report, for the corners the
    config already holds out.

    Two things have to hold, and neither is visible from the file alone.
    (1) The columns are THIS model's hidden corners -- not the union with the
    other temperature's, and no seen corner smuggled in, which is what a single
    shared request list would have produced. (2) Every cell is the number
    predictions_hidden.csv carries for that path at that corner, matched by
    path key so a permutation cannot pass. Both were measured to fail:
    dropping the per-model mask puts 0.500V_cmax in the 125C file, and reading
    the seen set instead of the hidden one changes every column.
    """
    pytest.importorskip("torch")
    import csv as _csv

    import si_model.run as run
    from si_model.parsing.build_dataset import build
    from si_model.run import (_split_request, expand, load_project, select,
                              stage_train)

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def project():
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p["files"]["crosstalk_subdir"] = None
        p["train"]["epochs"] = 1
        p["train"]["device"] = "cpu"
        return p

    models = select(expand(project()), design="boomcore")
    for m in models:
        build(m["cfg"])
        stage_train(m)

    # the whole CLI path, including the dispatch: `predict` with no --at
    monkeypatch.setenv("SI_STAGE", "")            # restored on teardown
    monkeypatch.setattr(run, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "load_project", lambda *a, **k: project())
    assert run.main(["predict"]) == 0

    req, only = _split_request(models, "hidden")
    for m in models:
        temp = str(m["temp"])
        fp = os.path.join("runs", "setup", "_all", "predict_%s_hidden.rpt" % temp)
        assert os.path.exists(fp), fp
        labels, paths, summ = _read_report(fp)
        # (1) this model's own holdout, in grid order
        want = ["%.3fV_%s" % vl for vl in req if vl in only[m["name"]]]
        assert labels == want, (labels, want)
        assert len(paths) == 12

        # (2) the same numbers as the file the trainer wrote
        npz_fp = os.path.join(m["cfg"]["train"]["out_dir"], "predictions_hidden.npz")
        z = np.load(npz_fp, allow_pickle=False)
        want_ps = {}
        for ci, corner in enumerate([str(x) for x in z["corners"]]):
            for pi, key in enumerate([str(x) for x in z["path_keys"]]):
                want_ps[(key, corner)] = float(z["model_ps"][pi, ci])
        assert want_ps, npz_fp
        by_v = {}
        for (key, corner), ps in want_ps.items():
            by_v.setdefault(corner, {})[key] = ps
        assert len(by_v) == len(labels), (sorted(by_v), labels)
        # corner NAMES differ (SSPG_0p5V_cmax vs 0.500V_cmax), so match on the
        # level and the voltage the label states
        keys = _report_keys(fp)
        for ci, lab in enumerate(labels):
            v, lv = float(lab.split("V_")[0]), lab.split("V_")[1]
            hit = [c for c in by_v if c.endswith("_" + lv)
                   and abs(float(c.split("_")[1].rstrip("V").replace("p", ".")) - v) < 1e-6]
            assert len(hit) == 1, (lab, sorted(by_v))
            col = by_v[hit[0]]
            for i, row in paths.items():
                # path by path, not as a set: a permutation would pass that
                assert abs(float(row[ci]) - col[keys[i]]) <= 0.05, (lab, keys[i])

        # the summary is the same block the --at report carries
        assert summ["WNS predicted (ps)"] and summ["WNS measured (ps)"]
        assert all(c.endswith("%") for c in summ["WNS error (%)"])


def _report_keys(fp):
    """{idx: path key} from a predict report -- the column _read_report drops."""
    lines = open(fp, encoding="utf-8").read().splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith("  ----"))
    a = lines[i].index("- ") + 2                  # past the idx column
    b = lines[i].index(" ", a)
    out = {}
    for l in lines[i + 1:]:
        if not l.strip():
            break
        out[int(l[:a].strip())] = l[a:b].strip()
    return out


def _base_project(real_tree, **base):
    """The real config, pointed at the fixture, with base keys overridden."""
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]
    p["files"]["crosstalk_subdir"] = None
    p["train"]["epochs"] = 1
    p["train"]["device"] = "cpu"
    p.setdefault("base", {}).update(base)
    return p


def test_v_transform_auto_recovers_the_generating_variable(real_tree, tmp_path,
                                                           monkeypatch):
    """base.v_transform: auto picks the axis variable by measurement.

    The fixture's slack is 1 - (0.30*(0.8/v)**1.8 + ... + 0.01*(0.8/v)*level),
    i.e. exactly a function of 1/v -- so the RIGHT answer here is known in
    advance: `inv`. That is what makes this a test and not an observation. It
    says nothing about which variable wins on silicon, where the curve is a sum
    of cell and net delays and the answer is whatever the [VAXIS] table says.

    A transform that was parsed but never applied to the coordinates would score
    all three variables identically, which is the failure this pins down.
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import _hidden_err, expand, select
    from si_model.training.loo import build_design, fit_field, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def base_err(**base):
        m = select(expand(_base_project(real_tree, **base)),
                   design="boomcore", temp="m25")[0]
        build(m["cfg"])
        ds = dict(np.load(m["cfg"]["data"]["cache"]))
        sp = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
        y = ds["slack"]
        phi, coords, _, _ = build_design(m["cfg"], sp, y=y)
        loo, _ = fit_field(y, phi, sp, coords, m["cfg"])
        return m["cfg"]["base"]["axes"][0]["transform"], _hidden_err(y, sp, loo)

    chosen, err_auto = base_err(v_transform="auto")
    assert chosen == "inv", chosen
    raw, err_raw = base_err(v_transform="none")
    assert raw == "none"
    inv, err_inv = base_err(v_transform="inv")
    assert inv == "inv"
    # the transform reaches the numbers, and `auto` landed on the better one
    assert err_inv < err_raw / 2, (err_inv, err_raw)
    assert abs(err_auto - err_inv) < 1e-9
    # log is offered and is NOT silently the same as inv
    _, err_log = base_err(v_transform="log")
    assert abs(err_log - err_inv) > 1e-9


def test_edge_criterion_cannot_see_the_hidden_corners(real_tree, tmp_path,
                                                      monkeypatch):
    """select_on: edge scores on SEEN corners only.

    The point of the criterion is to rank candidates where the hidden corners
    are the deliverable -- predicting below the measured range -- so it must be
    computable without their labels. Corrupting every hidden label must leave it
    bit-identical; the hidden criterion on the same data must move, or this test
    would pass on a criterion that ignores its input.
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import _edge_err, _hidden_err, expand, select
    from si_model.training.loo import build_design, fit_field, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    # A small basis on purpose: holding a whole voltage row out costs 2 of the
    # 10 seen corners, and the config's own 9-parameter basis does not fit in
    # the 8 that are left -- which the criterion reports as "cannot score", not
    # as a number. That path is checked at the end.
    m = select(expand(_base_project(real_tree, v_order=1, cross_terms=False,
                                    select=False)),
               design="boomcore", temp="m25")[0]
    build(m["cfg"])
    ds = dict(np.load(m["cfg"]["data"]["cache"]))
    sp = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
    y = np.asarray(ds["slack"], float)
    phi, coords, _, _ = build_design(m["cfg"], sp, y=y)
    assert phi.shape[1] == 4, phi.shape        # 1 + dv + drc + drc2

    y2 = y.copy()
    y2[:, sp.hidden_idx] = 1e6
    e1 = _edge_err(y, sp, phi, coords, m["cfg"])
    e2 = _edge_err(y2, sp, phi, coords, m["cfg"])
    assert e1 is not None and e1 == e2

    loo1, _ = fit_field(y, phi, sp, coords, m["cfg"])
    loo2, _ = fit_field(y2, phi, sp, coords, m["cfg"])
    assert _hidden_err(y, sp, loo1) != _hidden_err(y2, sp, loo2)

    # two seen voltages cannot give a fold back: the criterion says so instead
    # of scoring on whatever is left
    sp2 = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
    keep = np.round(sp2.vt[:, 0], 9) >= 0.6 - 1e-9
    sp2.seen = np.asarray(sp2.seen, bool) & keep
    sp2.hidden = ~sp2.seen
    assert len(np.unique(np.round(sp2.vt[sp2.seen_idx, 0], 9))) == 2
    assert _edge_err(y, sp2, phi, coords, m["cfg"]) is None

    # and a basis the fold cannot identify is not scored either
    big = select(expand(_base_project(real_tree)), design="boomcore", temp="m25")[0]
    phi_big, co_big, _, _ = build_design(big["cfg"], sp, y=y)
    assert phi_big.shape[1] > int(np.asarray(sp.seen, bool).sum()) - 2
    assert _edge_err(y, sp, phi_big, co_big, big["cfg"]) is None


def test_si_base_sets_any_base_key_for_one_run(real_tree, monkeypatch):
    """SI_BASE=key=value,...: sweep the base without editing a tracked file.

    Values arrive as strings and have to land as the type the key already has,
    or `cross_terms=false` is a non-empty string and reads as true. An unknown
    key is an error: the whole reason this path exists is that a setting which
    silently does nothing is indistinguishable from one that does nothing
    useful.
    """
    from si_model.run import expand, select

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.setenv("SI_BASE", "v_order=1,cross_terms=false,v_transform=inv,"
                                  "min_loo_dof=2,level_fit_margin=0.5")
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["base"]["v_order"] == 1 and isinstance(p["base"]["v_order"], int)
    assert p["base"]["cross_terms"] is False
    assert p["base"]["v_transform"] == "inv"
    assert p["base"]["min_loo_dof"] == 2
    assert p["base"]["level_fit_margin"] == 0.5
    # and it reaches the model, not just the project dict
    p["designs"] = ["boomcore"]
    m = select(expand(p), design="boomcore", temp="m25")[0]
    assert m["cfg"]["base"]["axes"][0]["transform"] == "inv"
    assert m["cfg"]["base"]["axes"][0]["order"] == 1
    assert m["cfg"]["base"]["cross_terms"] is False
    assert m["cfg"]["base"]["min_loo_dof"] == 2

    monkeypatch.setenv("SI_BASE", "v_orderr=1")
    with pytest.raises(AssertionError, match="unknown base key"):
        load_project(os.path.join(REPO_ROOT, "config.yaml"))
    monkeypatch.setenv("SI_BASE", "v_transform=quadratic")
    with pytest.raises(AssertionError, match="v_transform must be one of"):
        expand(_base_project(real_tree))


def test_transformed_axis_survives_predict_and_the_checkpoint(real_tree, tmp_path,
                                                              monkeypatch):
    """A transformed axis has to be the SAME axis everywhere, and it has to be
    replayed from the checkpoint.

    Two failures this pins down, both of which produce plausible numbers rather
    than an error:

    (1) The coordinate query path (`predict --at`) encodes the target itself. If
    it built coordinates in V while the model was fit in 1/V, the answer would
    still look like a slack. So a query AT a hidden corner's coordinates must
    reproduce the evaluation path there, under the transform. Random weights,
    not the trained ones: after one epoch the correction is near its zero init
    and the comparison would only exercise the base.

    (2) The variable is part of the base the correction was trained on. predict
    must take it from the checkpoint, not from whatever the config now says --
    the same reason the order and the level coordinates are pinned.
    """
    pytest.importorskip("torch")
    import torch

    from si_model.parsing.build_dataset import build
    from si_model.run import _load_predictor, expand, select, stage_train

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    m = select(expand(_base_project(real_tree, v_transform="inv")),
               design="boomcore", temp="m25")[0]
    build(m["cfg"])
    stage_train(m)

    tr = _load_predictor(m)
    assert tr.cfg["base"]["axes"][0]["transform"] == "inv"
    torch.manual_seed(0)
    for prm in list(tr.model.parameters()) + list(tr.enc.parameters()):
        prm.data.normal_(0.0, 0.3)
    H = tr.split.hidden_idx
    assert len(H)
    a = tr.predict_corners(H)
    b = tr.predict_coords(tr.ds["vt"][H], tr.split.vt[H])
    base = tr.base_hat.cpu().numpy()[:, H]
    assert np.abs(a - base).max() > 1.0, "the residual must be large enough to matter"
    np.testing.assert_allclose(b, a, rtol=1e-5, atol=1e-3)

    # (2) the config now says `none`; the checkpoint says `inv` and wins
    m2 = select(expand(_base_project(real_tree, v_transform="none")),
                design="boomcore", temp="m25")[0]
    tr2 = _load_predictor(m2)
    assert tr2.cfg["base"]["axes"][0]["transform"] == "inv"
    np.testing.assert_allclose(tr2.predict_corners(H),
                               _load_predictor(m).predict_corners(H),
                               rtol=1e-6, atol=1e-6)
    # the record that makes the replay possible is in the file, not inferred
    ck = torch.load(os.path.join(m["cfg"]["train"]["out_dir"], "best.pt"),
                    map_location="cpu")
    assert ck["cfg"]["base"]["_resolved"]["v_transform"] == "inv"
    # (that this is not vacuous -- that the transform moves the base at all --
    # is test_v_transform_auto_recovers_the_generating_variable above)


def test_base_save_gives_the_report_and_the_arrays_without_training(
        real_tree, tmp_path, monkeypatch):
    """`run.sh base --save`: the per-corner block and the plot input, from the
    OLS base alone.

    base takes seconds and no GPU, so it is where a setting gets changed and
    looked at -- but it only printed, which left the quick loop (change
    something, read the WNS, look at a scatter) behind a training. The arrays
    it writes are the shape predict writes, so the report writer and
    scripts/plot.py take them unchanged.

    Off without the flag: a diagnostic that leaves files behind surprises
    whoever runs it twice.
    """
    import si_model.run as run
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, select

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def project():
        return _base_project(real_tree)

    for m in select(expand(project()), design="boomcore"):
        build(m["cfg"])

    monkeypatch.setenv("SI_STAGE", "")
    monkeypatch.setattr(run, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "load_project", lambda *a, **k: project())

    assert run.main(["base", "--design", "boomcore"]) == 0
    out = os.path.join("runs", "setup", "boomcore", "125")
    assert not os.path.exists(os.path.join(out, "predictions_base.npz"))

    assert run.main(["base", "--design", "boomcore", "--save"]) == 0
    z = np.load(os.path.join(out, "predictions_base.npz"), allow_pickle=False)
    # held-out corners only: a seen corner's leave-one-out fit is not what the
    # base is judged on, and mixing them invites reading the easy columns
    assert len(z["corners"]) == 2 and int(z["seen"].sum()) == 0
    assert z["truth_ps"].shape == z["model_ps"].shape == (12, 2)
    assert np.isfinite(z["clock_ns"]).all() and (z["n_cycles"] > 0).all()

    fp = os.path.join("runs", "setup", "_all", "predict_125_base.rpt")
    labels, paths, summ = _read_report(fp)
    assert len(labels) == 2 and len(paths) == 12
    for row in ("mean measured slack (ps)", "mean absolute error (ps)",
                "WNS measured (ps)", "WNS error (ps)", "WNS error (%)"):
        assert row in summ, sorted(summ)
    # the numbers are the base's, not a model's -- they match the arrays
    i = [k for k, c in enumerate([str(x) for x in z["corners"]])
         if not z["seen"][k]][0]
    want = float(np.abs(z["model_ps"][:, i] - z["truth_ps"][:, i]).mean())
    assert abs(float(summ["mean absolute error (ps)"][i]) - want) < 0.05


def test_save_survives_the_quiet_gate_under_all(real_tree, tmp_path, monkeypatch,
                                               capsys):
    """`all --save` must write the files too.

    base prints its diagnostics only when it was named, so that `all` goes from
    build straight to epochs. That gate used to return BEFORE the writing, so
    `--save` under `all` wrote nothing and said nothing -- the one combination
    where a silent no-op is indistinguishable from the stage having run. --save
    is an explicit request for files, not a diagnostic, and is now honoured
    whatever the stage is called.
    """
    import si_model.run as run
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, select, stage_base

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = _base_project(real_tree)
    models = select(expand(p), design="boomcore", temp="125")
    for m in models:
        build(m["cfg"])

    monkeypatch.delenv("SI_VERBOSE", raising=False)
    monkeypatch.setenv("SI_STAGE", "all")
    assert not run._base_loud(), "the diagnostics are off under `all`"
    stage_base(models[0], save=True)

    out = capsys.readouterr().out
    assert "[per corner]" not in out, "diagnostics stay off"
    assert "[SAVE]" in out, "but the file it was asked for is reported"
    fp_npz = os.path.join("runs", "setup", "boomcore", "125",
                          "predictions_base.npz")
    assert os.path.exists(fp_npz), out

    # and without --save it still writes nothing, under `all` as anywhere else
    os.remove(fp_npz)
    stage_base(models[0])
    assert not os.path.exists(fp_npz)


def test_every_stage_records_how_long_it_took(real_tree, tmp_path, monkeypatch,
                                             capsys):
    """runs/<mode>/_all/runtime.rpt: one line per stage, appended.

    The question is "how long does this pipeline take on this drop", and it
    only has an answer across runs -- a build killed after four hours is
    exactly the case the number is wanted for, so the line is written as each
    stage ends rather than collected at the end. Hence: appended, never
    rewritten, and present even for the stages that write no summary.json
    (build, base, predict), which are most of them.

    A duration alone is not a measurement, so the line carries the scale (paths
    and corners) and the machine (threads, host) beside it: the same build is
    three hours on sixteen threads and most of a day on four.
    """
    import si_model.run as run
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, select

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    monkeypatch.chdir(tmp_path)

    def project():
        return _base_project(real_tree)

    for m in select(expand(project()), design="boomcore"):
        build(m["cfg"])

    monkeypatch.setenv("SI_STAGE", "")
    monkeypatch.setattr(run, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "load_project", lambda *a, **k: project())
    assert run.main(["build", "--design", "boomcore"]) == 0

    fp = os.path.join("runs", "setup", "_all", "runtime.rpt")
    # it says it recorded, and where. Writing the line in silence made a run
    # that recorded its timing look exactly like one that did not, and the path
    # is relative to the working directory -- the other half of "nothing was
    # created"
    said = [l for l in capsys.readouterr().out.splitlines() if "[TIME]" in l]
    assert len(said) == 1 and fp in said[0] and "boomcore" in said[0], said
    first = open(fp).read().splitlines()
    assert first[0].startswith("#")
    assert first[1].split()[:4] == ["date", "stage", "circuit", "mode"]
    row = first[2].split()
    # ONE line for the circuit, both temperatures summed into it -- a
    # temperature is an internal split, and the question is how long setup took
    assert row[2] == "build" and row[3] == "boomcore" and row[4] == "setup"
    assert int(row[5]) == 2                                     # temperatures
    # the scale, so the duration can be compared with another drop's
    assert int(row[6]) == 12 and int(row[7]) == 8 + 12          # paths, corners
    assert row[8].endswith("s") and row[9].endswith("s")        # wall, cpu
    assert row[10] == "3", row                                  # threads
    assert len(first) == 3, first

    # a second run APPENDS -- the previous timing is the thing being compared
    assert run.main(["build", "--design", "boomcore", "--temp", "125"]) == 0
    again = open(fp).read().splitlines()
    assert again[:3] == first
    assert len(again) == 4 and again[3].split()[2] == "build"
    assert int(again[3].split()[5]) == 1                        # just the one

    # only build, train and inference are recorded. `base` is a diagnostic
    # measured in seconds, and a line per internal stage buried the two that
    # are measured in hours among four that are not.
    capsys.readouterr()                             # the second build's line
    assert run.main(["base", "--design", "boomcore"]) == 0
    assert open(fp).read().splitlines() == again
    assert "[TIME]" not in capsys.readouterr().out, "base is not a timed stage"


def test_blind_hidden_keeps_every_choice_off_the_held_out_corners(
        real_tree, tmp_path, monkeypatch):
    """split.blind_hidden: the held-out corners are measured and reported, but
    no DECISION reads them.

    Tested the only way that means anything -- by changing what those corners
    say. Shift every held-out label by 5 ns and train again from the same seed:
    under blind_hidden the chosen epoch and every weight must come out
    bit-identical, because nothing consulted them. With blind_hidden off the
    same shift must change the result, or the test would pass on a run that
    ignores its input anyway.

    The basis, the axis variable and the weighting are covered by
    test_edge_criterion_cannot_see_the_hidden_corners; what is left, and what
    this pins down, is the training epoch -- the last place a held-out label was
    still steering a choice.
    """
    pytest.importorskip("torch")
    import torch

    from si_model.parsing.build_dataset import build
    from si_model.run import expand, select, stage_train
    from si_model.training.loo import make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def model_for(blind):
        p = _base_project(real_tree, select_on="edge" if blind else "hidden")
        p["train"]["epochs"] = 4
        p["split"]["blind_hidden"] = blind
        return select(expand(p), design="boomcore", temp="m25")[0]

    base = model_for(False)
    build(base["cfg"])
    clean = base["cfg"]["data"]["cache"]
    ds = dict(np.load(clean))
    sp = make_split(ds["corners"].tolist(), ds["vt"], base["cfg"])
    assert len(sp.hidden_idx)
    ds["slack"][:, sp.hidden_idx] += 5000.0          # 5 ns off, at the holdout
    dirty = os.path.join(os.path.dirname(clean), "dirty.npz")
    np.savez(dirty, **ds)

    def train(blind, cache, tag):
        m = model_for(blind)
        m["cfg"]["data"]["cache"] = cache
        m["cfg"]["train"]["out_dir"] = os.path.join("runs", tag)
        stage_train(m)
        ck = torch.load(os.path.join("runs", tag, "best.pt"), map_location="cpu")
        with open(os.path.join("runs", tag, "summary.json")) as f:
            summ = json.load(f)
        return ck["epoch"], ck["model"], summ

    def same(a, b):
        return (sorted(a) == sorted(b)
                and all(torch.equal(a[k], b[k]) for k in a))

    e1, w1, s1 = train(True, clean, "blind_clean")
    e2, w2, _ = train(True, dirty, "blind_dirty")
    assert s1["selected_on"] == "seen_only (blind_hidden)"
    assert s1["blind_hidden"] is True
    assert e1 == e2 and same(w1, w2), (e1, e2)

    e3, w3, s3 = train(False, clean, "open_clean")
    e4, w4, _ = train(False, dirty, "open_dirty")
    assert s3["selected_on"] == "hidden_corners"
    assert e3 != e4 or not same(w3, w4), "the shift must matter when not blind"

    # and the switch cannot be half-set: selecting ON the held-out corners
    # while claiming not to see them is refused rather than resolved
    p = _base_project(real_tree, select_on="hidden")
    p["split"]["blind_hidden"] = True
    with pytest.raises(AssertionError, match="blind_hidden"):
        expand(p)


def _deep_diff(a, b, at=""):
    """Dotted paths where two parsed configs differ. Lists compare by index."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            for d in _deep_diff(a.get(k, KeyError), b.get(k, KeyError),
                                "%s.%s" % (at, k) if at else str(k)):
                yield d
    elif (isinstance(a, list) and isinstance(b, list)
          and len(a) == len(b) and any(isinstance(x, dict) for x in a)):
        for i, (x, y) in enumerate(zip(a, b)):
            for d in _deep_diff(x, y, "%s.%d" % (at, i)):
                yield d
    elif a != b:
        yield at


def test_out_tag_puts_the_experiment_above_the_mode(real_tree, tmp_path, monkeypatch):
    """out.tag: a second config writes to runs/<tag>/<mode>/ instead of
    runs/<mode>/.

    Above the mode, not beside it: setup and hold still split underneath, so an
    experiment cannot be half-overwritten by a later `--mode hold` run. The
    cache is deliberately NOT tagged -- dataset.npz does not depend on the
    seen/hidden split, so two experiments share one parse instead of costing a
    second full build.
    """
    from si_model.run import _predict_files, expand, load_project, select

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def project(**over):
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p.update(over)
        return p

    plain = select(expand(project()), design="boomcore", temp="125")[0]
    assert plain["cfg"]["train"]["out_dir"] == os.path.join("runs", "setup",
                                                            "boomcore", "125")

    tagged = select(expand(project(out={"tag": "extrapolation"})),
                    design="boomcore", temp="125")[0]
    assert tagged["cfg"]["train"]["out_dir"] == os.path.join(
        "runs", "extrapolation", "setup", "boomcore", "125")
    # same cache: nothing to rebuild for the second experiment
    assert tagged["cfg"]["data"]["cache"] == plain["cfg"]["data"]["cache"]

    hold = select(expand(project(out={"tag": "extrapolation"}, mode="hold")),
                  design="boomcore", temp="125")[0]
    assert hold["cfg"]["train"]["out_dir"] == os.path.join(
        "runs", "extrapolation", "hold", "boomcore", "125")

    # the _all/ files (predict reports, merge) follow the tag too
    p = project(out={"tag": "extrapolation"})
    fp = _predict_files(p, "t", ["125"])["125"]
    assert fp.startswith(os.path.join("runs", "extrapolation", "setup", "_all")), fp

    # two ways of saying where output goes cannot both be set: out.runs
    # replaces the whole runs/<tag>/<mode> path and would freeze the mode
    with pytest.raises(AssertionError, match="out.tag and out.runs"):
        expand(project(out={"tag": "extrapolation", "runs": "runs/elsewhere"}))
    with pytest.raises(AssertionError, match="ONE directory name"):
        expand(project(out={"tag": "runs/extrapolation"}))


def test_extrapolation_config_is_config_yaml_plus_the_holdout():
    """config_extrapolation.yaml is a COPY of config.yaml, so this pins down
    exactly how much of a copy it is allowed to be.

    A copy drifts: a fix to config.yaml that belongs in both quietly lands in
    one, and then the experiment differs from the baseline for a reason nobody
    chose. Every difference is listed here by key. A new one fails this test,
    which is the signal to copy it across (or to list it here on purpose).

    It also states the experiment itself: every circuit holds out its OWN
    lowest voltage row and nothing else. The grids differ -- PERIC0 and MFC
    start at 0.5 V, MIF at 0.475 -- so one global list carries both numbers and
    a voltage that is not in a grid simply matches nothing there.
    """
    from si_model.run import expand, project_for

    with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
        main = yaml.safe_load(f)
    with open(os.path.join(REPO_ROOT, "config_extrapolation.yaml")) as f:
        exp = yaml.safe_load(f)

    assert sorted(_deep_diff(main, exp)) == [
        "base.select_on",
        "base.v_transform",
        "corners.hidden_voltages",
        "designs.MFC_Timing_Report.temps.0.hidden_corners",
        "designs.MFC_Timing_Report.temps.1.hidden_corners",
        "designs.MIF_Timing_Report.temps.0.hidden_corners",
        "designs.MIF_Timing_Report.temps.1.hidden_corners",
        "out.tag",
        "split.blind_hidden",
        "temps.0.hidden_corners",
        "temps.1.hidden_corners",
    ]
    assert exp["out"]["tag"] == "extrapolation"
    assert exp["corners"]["hidden_voltages"] == [0.5, 0.475]
    # the two extrapolation-specific choices: measure the axis variable, and
    # rank candidates WITHOUT the held-out row, which is this run's deliverable
    assert exp["base"]["v_transform"] == "auto"
    assert exp["base"]["select_on"] == "edge"
    # nothing in this experiment may be chosen by looking at the held-out row
    assert exp["split"]["blind_hidden"] is True
    assert main["split"]["blind_hidden"] is False
    assert main["base"]["v_transform"] == "none"
    assert main["base"]["select_on"] == "hidden"
    assert exp["corners"]["hidden_corners"] == []          # unchanged, already empty
    for t in exp["temps"]:
        assert t["hidden_corners"] == []
    for d in ("MFC_Timing_Report", "MIF_Timing_Report"):
        for t in exp["designs"][d]["temps"]:
            assert t["hidden_corners"] == []

    # resolved: each circuit loses exactly its lowest voltage, at both temps
    for m in expand(dict(exp)):
        vs = [float(v) for v in project_for(exp, m["design"])["corners"]["voltages"]]
        sp = m["cfg"]["split"]
        hid = [v for v in vs
               if any(abs(v - h) < 1e-9 for h in sp.get("hidden_voltages") or [])]
        assert hid == [min(vs)], (m["name"], hid)
        assert not sp["hidden_corners"] and not sp["hidden_levels"]
        assert m["cfg"]["train"]["out_dir"].startswith(
            os.path.join("runs", "extrapolation", "setup")), m["name"]


def _read_report(fp):
    """Read a predict report back: (corner labels, {idx: [values]}, {label: [values]}).

    The files are fixed-width text now, not CSV, so the tests read them the way
    a person does -- by the rule line, which states every column's span.
    """
    lines = open(fp, encoding="utf-8").read().splitlines()
    heads = [i for i, l in enumerate(lines) if l.startswith("  ----")]
    assert len(heads) >= 2, fp

    def spans(rule):
        out, i = [], 0
        while i < len(rule):
            if rule[i] == "-":
                j = i
                while j < len(rule) and rule[j] == "-":
                    j += 1
                out.append((i, j))
                i = j
            else:
                i += 1
        return out

    def cells(line, sp):
        return [line[a:b].strip() if a < len(line) else "" for a, b in sp]

    psp = spans(lines[heads[0]])
    labels = cells(lines[heads[0] - 2], psp)[2:]
    paths = {}
    for l in lines[heads[0] + 1:]:
        if not l.strip():
            break
        c = cells(l, psp)
        paths[int(c[0])] = c[2:]
    ssp = spans(lines[heads[1]])
    summ = {}
    for l in lines[heads[1] + 1:]:
        if not l.strip():
            break
        c = cells(l, ssp)
        summ[c[0]] = c[1:]
    return labels, paths, summ


def _with_synthetic_si(cache: str, out: str, seed: int = 0) -> str:
    """Copy a built dataset and give it crosstalk, so the SI branch is live.

    The report fixture produces no stage rows at all (stages are parsed only
    alongside crosstalk), so every test above runs with the SI branch disabled
    -- which is how a bug in the SI half of predict --at reached a real run.
    Rather than inventing a crosstalk report format, this fills the SI arrays
    the build would have produced: two aggressors per stage, bumps and windows
    varying smoothly with the corner, and one aggressor inactive at two corners
    so the anchor-subset path is taken as well.
    """
    d = dict(np.load(cache))
    N, C = d["slack"].shape
    A, K = 2, 2
    S = N * K
    rng = np.random.RandomState(seed)
    vt = d["vt"]
    dv = (vt[:, 0] - 0.685)[None, None, :]
    dl = vt[:, 1][None, None, :]
    d["stage_path"] = np.repeat(np.arange(N, dtype=np.int32), K)
    d["stage_seg"] = np.zeros(S, np.int8)
    d["n_aggr"] = np.full(S, A, np.int16)
    d["acc"] = np.full((S, A), 0.30, np.float32)
    d["abump"] = (rng.uniform(0.02, 0.08, (S, A, 1))
                  * (1 - 1.5 * dv + 0.2 * dl)).astype(np.float32)
    d["aslew"] = (rng.uniform(0.02, 0.05, (S, A, 1)) * (1 - 1.2 * dv)).astype(np.float32)
    lo = rng.uniform(0.0, 0.2, (S, A, 1)) + 0.1 * dv
    d["awin"] = np.stack([lo, lo + 0.15], -1).astype(np.float32)
    vlo = rng.uniform(0.05, 0.15, (S, 1)) + 0.1 * dv[0]
    d["vwin"] = np.stack([vlo, vlo + 0.2], -1).astype(np.float32)
    d["arc_delta"] = np.zeros((S, C), np.float32)
    d["abump"][0, 0, [1, 5]] = np.nan
    os.makedirs(os.path.dirname(out), exist_ok=True)
    np.savez_compressed(out, **d)
    return out


def test_predict_at_new_corners_carries_si(real_tree, tmp_path, monkeypatch):
    """With crosstalk present, a coordinate query must reproduce the evaluation
    path at a hidden corner -- SI included.

    No corner uses its own crosstalk report for these inputs: si_features fits
    the windows, bumps and slews on anchors within the SEEN corners and
    evaluates that fit at the target, leave-one-out at a seen corner. A corner
    with no report is therefore the same evaluation at another coordinate, not
    a special case, and --at must get it too. The first version zeroed the SI
    branch instead, and then passed the coordinates where the design matrix was
    expected -- neither of which any SI-free fixture could notice.
    """
    pytest.importorskip("torch")
    import torch

    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.tasks.slack.train import Trainer

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]
    p["files"]["crosstalk_subdir"] = None
    p["train"]["device"] = "cpu"
    m = select(expand(p), design="boomcore", temp="m25")[0]
    build(m["cfg"])
    m["cfg"]["data"]["cache"] = _with_synthetic_si(
        m["cfg"]["data"]["cache"], str(tmp_path / "si" / "dataset.npz"))

    tr = Trainer(m["cfg"])
    assert tr.has_si, "this test is pointless without the SI branch live"
    torch.manual_seed(0)
    for prm in list(tr.model.parameters()) + list(tr.enc.parameters()):
        prm.data.normal_(0.0, 0.3)

    H = tr.split.hidden_idx
    assert len(H) >= 2
    a = tr.predict_corners(H)
    assert np.abs(a - tr.base_hat.cpu().numpy()[:, H]).max() > 1.0, \
        "the residual must be large enough for a mismatch to show"
    for chunk in (4, 1):            # one chunk, then several
        b = tr.predict_coords(tr.ds["vt"][H], tr.split.vt[H], corner_chunk=chunk)
        np.testing.assert_allclose(b, a, rtol=1e-5, atol=1e-3)


def test_model_carries_to_another_circuit(real_tree, tmp_path, monkeypatch):
    """--weights: another circuit's model, this circuit's base.

    The family vocabulary is ["<pad>"] + sorted(the families THIS circuit
    has), so two circuits number their cells differently and have a different
    number of them. Carrying a model therefore has to translate by name. The
    check plants exactly that: a second dataset identical to the first except
    that its vocabulary gained a family that sorts first, which shifts every
    other index by one. Translated correctly, the borrowed model must return
    what it returned on the original -- the underlying cells are the same.

    It also pins what does NOT travel: the base is refitted here, and the
    input scales come from the source, so carrying a model to the circuit it
    was trained on must reproduce that circuit's own prediction exactly.
    """
    pytest.importorskip("torch")

    from si_model.parsing.build_dataset import build
    from si_model.run import _load_predictor, expand, load_project, select, stage_train

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def model():
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p["files"]["crosstalk_subdir"] = None
        p["train"]["epochs"] = 1
        p["train"]["device"] = "cpu"
        return select(expand(p), design="boomcore", temp="m25")[0]

    m = model()
    build(m["cfg"])
    stage_train(m)
    ckpt = os.path.join(m["cfg"]["train"]["out_dir"], "best.pt")
    H = _load_predictor(model()).split.hidden_idx

    own = _load_predictor(model()).predict_corners(H)
    same = _load_predictor(model(), weights=ckpt).predict_corners(H)
    np.testing.assert_allclose(same, own, rtol=1e-6, atol=1e-6)

    # A borrowed run must not overwrite this circuit's own result.
    # predictions_<corners>.csv is what `merge` reads, so a transfer tagged the
    # same way would have the merged table report another circuit's correction
    # as this one's -- with nothing in the file to say so.
    from si_model.run import stage_predict

    out = m["cfg"]["train"]["out_dir"]
    own_fp = os.path.join(out, "predictions_hidden.npz")
    stage_predict(model(), "hidden")
    before = open(own_fp, "rb").read()
    stage_predict(model(), "hidden", weights=ckpt)
    assert open(own_fp, "rb").read() == before, "the transfer overwrote the own-model file"
    src = os.path.basename(os.path.dirname(os.path.abspath(ckpt)))
    assert os.path.exists(os.path.join(out, "predictions_hidden_from_%s.npz" % src)), \
        sorted(os.listdir(out))

    # a second circuit that numbers its cells differently
    d = dict(np.load(model()["cfg"]["data"]["cache"]))
    vocab = [str(x) for x in d["fam_vocab"]]
    assert vocab[0] == "<pad>" and len(vocab) > 2
    d["fam_vocab"] = np.asarray([vocab[0], "AAA_only_here"] + vocab[1:])
    fam = np.asarray(d["node_fam"])
    d["node_fam"] = np.where(fam > 0, fam + 1, 0).astype(fam.dtype)
    other = str(tmp_path / "other" / "dataset.npz")
    os.makedirs(os.path.dirname(other), exist_ok=True)
    np.savez_compressed(other, **d)

    m2 = model()
    m2["cfg"]["data"]["cache"] = other
    carried = _load_predictor(m2, weights=ckpt).predict_corners(H)
    np.testing.assert_allclose(carried, own, rtol=1e-6, atol=1e-6)

    # the input scales come from the SOURCE, not measured on the target. A
    # circuit whose slacks sit somewhere else entirely would otherwise be fed
    # to the network through a different ruler than it was trained with, and
    # on identical data (above) re-measuring is indistinguishable from
    # borrowing -- so the target here is deliberately offset.
    import torch

    from si_model.run import _trainer

    d2 = dict(np.load(model()["cfg"]["data"]["cache"]))
    d2["slack"] = d2["slack"] + 5.0                      # ns: a far larger circuit
    shifted = str(tmp_path / "shifted" / "dataset.npz")
    os.makedirs(os.path.dirname(shifted), exist_ok=True)
    np.savez_compressed(shifted, **d2)
    src_tok = np.asarray(torch.load(ckpt, map_location="cpu")["norm"]["tok"][0])

    m3 = model()
    m3["cfg"]["data"]["cache"] = shifted
    borrowed = _load_predictor(m3, weights=ckpt).tok_mu
    m4 = model()
    m4["cfg"]["data"]["cache"] = shifted
    measured = _trainer(m4).tok_mu
    np.testing.assert_allclose(np.asarray(borrowed), src_tok, rtol=1e-6, atol=1e-6)
    assert not np.allclose(np.asarray(measured), src_tok), \
        "this target must have different statistics, or the check proves nothing"

    # a checkpoint from before this existed cannot be carried, and says so
    old = str(tmp_path / "old.pt")
    ck = torch.load(ckpt, map_location="cpu")
    torch.save({k: v for k, v in ck.items() if k not in ("fam_vocab", "norm")}, old)
    with pytest.raises(AssertionError, match="carried between circuits"):
        _load_predictor(model(), weights=old)


def test_model_carries_to_a_different_corner_set(real_tree, tmp_path, monkeypatch):
    """The target circuit may have a different seen-corner set entirely.

    Nothing in the model's shape depends on how many corners there are: the
    correction head cross-attends over the corner tokens with a mask, and
    training already varies the count every batch through corner and axis
    dropout. This plants the case anyway -- a target built on three voltages
    where the model was trained on four -- because "should be fine by
    construction" is not a measurement.

    What is NOT free is the coordinate RANGE. Corner coordinates are measured
    from the reference corner, so a target asking about voltages the source
    never covered is extrapolation for the correction, whatever the counts are.
    """
    pytest.importorskip("torch")

    from si_model.parsing.build_dataset import build
    from si_model.run import _load_predictor, expand, load_project, select, stage_train
    from si_model.training.loo import make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def model(voltages=None, min_seen=None):
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p["files"]["crosstalk_subdir"] = None
        p["train"]["epochs"] = 1
        p["train"]["device"] = "cpu"
        if voltages:
            p["corners"]["voltages"] = voltages
        if min_seen:
            p["split"]["min_seen"] = min_seen
        return select(expand(p), design="boomcore", temp="m25")[0]

    m = model()
    build(m["cfg"])
    stage_train(m)
    ckpt = os.path.join(m["cfg"]["train"]["out_dir"], "best.pt")
    trained_on = len(_load_predictor(model()).split.corners)

    # a target with one voltage fewer: 3 x 3 corners against the model's 4 x 3
    d = dict(np.load(model()["cfg"]["data"]["cache"]))
    keep = np.array([i for i, c in enumerate(d["corners"]) if "0p54V" not in str(c)])
    assert 0 < len(keep) < len(d["corners"])
    for k, ax in (("corners", 0), ("vt", 0), ("measured", 0), ("slack", 1),
                  ("si_label", 1), ("arrival", 1), ("required", 1),
                  ("launch_clk", 1), ("capture_clk", 1), ("lib_check_time", 1),
                  ("arc_delta", 1), ("vwin", 1), ("abump", 2), ("awin", 2),
                  ("aslew", 2)):
        if k in d and d[k].ndim > ax:
            d[k] = np.take(d[k], keep, axis=ax)
    fewer = str(tmp_path / "fewer" / "dataset.npz")
    os.makedirs(os.path.dirname(fewer), exist_ok=True)
    np.savez_compressed(fewer, **d)

    m2 = model(voltages=[0.5, 0.6, 0.685], min_seen=1)
    m2["cfg"]["data"]["cache"] = fewer
    tr = _load_predictor(m2, weights=ckpt)
    assert len(tr.split.corners) == len(keep) < trained_on, \
        "the target must really have a different corner set"
    H = tr.split.hidden_idx
    assert len(H)

    # Random weights from here on. One epoch on twelve paths leaves the
    # correction head at ~1e-4 of its zero init, so the trained correction is
    # 3e-5 ps and every output equals the base to float32 -- which would make
    # this pass whatever the attention did with the mismatched corner count.
    import torch

    torch.manual_seed(0)
    for prm in list(tr.model.parameters()) + list(tr.enc.parameters()):
        prm.data.normal_(0.0, 0.3)
    pred = tr.predict_corners(H)
    assert np.isfinite(pred).all()
    assert np.abs(pred - tr.base_hat.cpu().numpy()[:, H]).max() > 1.0, \
        "the correction must reach the output, on this corner set too"


def test_predict_runs_on_a_circuit_with_no_holdout(real_tree, tmp_path, monkeypatch):
    """A circuit that has just arrived has no hidden corners to give.

    Everything it measured is seen; the point is to predict what it did not
    measure. make_split refused that -- the holdout assert is what training and
    `base` are scored on, and it fired for every stage -- so the deployment
    case could not run at all. predict names the corners it wants, so it does
    not need one; the other stages still do.
    """
    pytest.importorskip("torch")

    from si_model.parsing.build_dataset import build
    from si_model.run import (_predict_request, expand, load_project, select,
                              stage_predict_at, stage_train)
    from si_model.training.loo import make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def project(holdout=True):
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p["files"]["crosstalk_subdir"] = None
        p["train"]["epochs"] = 1
        p["train"]["device"] = "cpu"
        if not holdout:
            for t in p["temps"]:
                t["hidden_corners"] = []
        return p

    m = select(expand(project()), design="boomcore", temp="m25")[0]
    build(m["cfg"])
    monkeypatch.setenv("SI_STAGE", "train")
    stage_train(m)

    p = project(holdout=False)
    fresh = select(expand(p), design="boomcore", temp="m25")
    ds = dict(np.load(fresh[0]["cfg"]["data"]["cache"]))

    monkeypatch.setenv("SI_STAGE", "base")
    with pytest.raises(AssertionError, match="degenerate split"):
        make_split(ds["corners"].tolist(), ds["vt"], fresh[0]["cfg"])

    monkeypatch.setenv("SI_STAGE", "predict")
    sp = make_split(ds["corners"].tolist(), ds["vt"], fresh[0]["cfg"])
    assert not sp.hidden.any() and sp.seen.all()
    req = _predict_request(p, fresh, "0.57:cmax", None, None)
    fps, fails = stage_predict_at(fresh, p, req, "fresh")
    assert not fails and len(fps) == 1
    _, paths, _ = _read_report(fps[0])
    assert len(paths) == 12 and all(v for row in paths.values() for v in row)


def test_predict_at_another_clock_period(real_tree, tmp_path, monkeypatch):
    """--period: exact shift, and a frequency limit that does not move.

    T enters the slack equation once, as the capture edge's time, and nothing
    in the path depends on it -- cells do not know the clock. So changing the
    period shifts every setup slack by N*(T'-T) exactly, and the frequency a
    corner can run at is a property of the corner, not of the period the
    numbers happen to be quoted at. The second one was wrong first: Fmax came
    out 626 / 557 / 716 MHz for the same corner asked at 2.0 / 1.8 / 2.2 ns,
    because N and the zero crossing were both read against the base period.
    """
    pytest.importorskip("torch")
    import csv as _csv

    from si_model.parsing.build_dataset import build
    from si_model.run import (_predict_request, expand, load_project, select,
                              stage_predict_at, stage_train)

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)

    def project():
        p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
        p["designs"] = ["boomcore"]
        p["files"]["crosstalk_subdir"] = None
        p["train"]["epochs"] = 1
        p["train"]["device"] = "cpu"
        return p

    m = select(expand(project()), design="boomcore", temp="m25")[0]
    build(m["cfg"])
    stage_train(m)
    assert np.nanmedian(np.load(m["cfg"]["data"]["cache"])["cycle_gap"]) == 2.0

    def run(period, tag):
        p = project()
        models = select(expand(p), design="boomcore", temp="m25")
        req = _predict_request(p, models, "0.57:cmax", None, None)
        fps, fails = stage_predict_at(models, p, req, tag, None, period)
        assert not fails and len(fps) == 1
        _, paths, summ = _read_report(fps[0])
        slack = [float(paths[i][0]) for i in sorted(paths)]
        return slack, float(summ["max clock frequency (MHz)"][0])

    base, f0 = run(None, "base")
    for period in (1.8, 2.2, 1.5):
        shifted, f = run(period, "T%g" % period)
        # single-cycle paths: the shift is exactly the period change
        np.testing.assert_allclose(
            np.asarray(shifted), np.asarray(base) + (period - 2.0) * 1000.0,
            rtol=0, atol=0.06)                       # the file writes 1 decimal
        assert abs(f - f0) < 0.05, "a frequency limit cannot depend on the period asked for"
    assert abs(f0 - 1000.0 / (2.0 - base[0] / 1000.0)) < 0.5 or base[0] != min(base)

    # A MULTICYCLE path moves by N times the period change. Without it every
    # gap is one period and gap*(T'/T - 1) is indistinguishable from (T'-T),
    # so dropping the cycle count passes unnoticed -- it did.
    cache = m["cfg"]["data"]["cache"]
    d = dict(np.load(cache))
    d["cycle_gap"] = np.array(d["cycle_gap"])
    d["cycle_gap"][0, :] = 4.0                       # this path captures 2 cycles later
    np.savez_compressed(cache, **d)
    two, _ = run(1.8, "multicycle")
    assert abs((two[0] - base[0]) - 2 * (1.8 - 2.0) * 1000.0) < 0.06, \
        "a 2-cycle path must move by twice the period change"
    assert abs((two[1] - base[1]) - (1.8 - 2.0) * 1000.0) < 0.06


def test_freq_is_the_same_knob_as_period():
    """--freq (MHz) and --period (ns) are one knob said two ways."""
    from si_model.run import _default_predict_name, main

    req = [(0.57, "cmax")]
    assert "F950MHz" in _default_predict_name(None, None, "0.57:cmax", None, None,
                                              req, None, 1000.0 / 950.0, 950.0)
    assert "T3.8ns" in _default_predict_name(None, None, "0.57:cmax", None, None,
                                             req, None, 3.8, None)
    for argv in (["predict", "--at", "0.57:cmax", "--freq", "500", "--period", "2"],
                 ["predict", "--at", "0.57:cmax", "--freq", "0"],
                 ["base", "--freq", "500"]):
        with pytest.raises(SystemExit):
            main(argv)


def test_clock_edge_row_column_layouts():
    """The edge time is the LAST number on the row, however many precede it.

    The deliverable is SSTA, which puts extra statistical columns on the rows,
    and a row may carry only the Path. Reading the second number -- which the
    first version did -- picks a sigma the moment a third column appears. The
    cell rows in this parser already take the last value for the same reason.
    """
    from si_model.parsing.annotated import CLOCK_EDGE_RE, _NUM_RE

    cases = [
        ("  clock clk (rise edge)                 4.0000    4.0000", "4.0000"),
        ("  clock clk (rise edge) (mean)   4.0000  0.0123   4.0000", "4.0000"),
        ("  clock clk (fall edge)                           2.5000", "2.5000"),
        ("  clock CLK' (rise edge)  4.0000  0.0100  0.0050  4.0000", "4.0000"),
    ]
    for row, want in cases:
        m = CLOCK_EDGE_RE.match(row)
        assert m, row
        assert _NUM_RE.findall(m.group(1))[-1] == want, row
    m = CLOCK_EDGE_RE.match("  clock clk (rise edge)")
    assert m and not _NUM_RE.findall(m.group(1)), "a row with no number is not an edge time"

    # and through the parser, on a report whose clock rows carry a statistical
    # column in the middle -- checking the regex alone let a parser that takes
    # the second number pass
    import re as _re
    import tempfile

    from si_model.parsing.annotated import parse_annotated

    txt = _fake_report(0.6, 0.0)
    txt = _re.sub(r"^(\s+clock \S+ \(rise edge\))(\s+)(-?\d+\.\d+)(\s+)(-?\d+\.\d+)",
                  r"\1\2\3\4 0.0123 \5", txt, flags=_re.M)
    assert "0.0123" in txt
    fp = os.path.join(tempfile.mkdtemp(), "ssta.rpt")
    with open(fp, "w") as f:
        f.write(txt)
    p0 = next(iter(parse_annotated(fp).values()))
    assert (p0.launch_edge, p0.capture_edge) == (0.0, 2.0), \
        (p0.launch_edge, p0.capture_edge)

    # Spellings that must not cost the clock period, each through the parser.
    # The period is what makes a grid measured at one clock per voltage usable
    # at all, so a row this misses disables that correction silently -- and the
    # value is a vendor formatting choice, not information.
    for name, sub in (
            ("integer edge times",
             lambda t: _re.sub(r"^(\s+clock \S+ \(rise edge\))\s+2\.0000\s+2\.0000",
                               r"\1        2        2", t, flags=_re.M)),
            ("a clock name with a space",
             lambda t: t.replace("clock clk (rise edge)", "clock my clk (rise edge)")),
            ("signed exponent times",
             lambda t: _re.sub(r"^(\s+clock \S+ \(rise edge\))\s+2\.0000\s+2\.0000",
                               r"\1  +2.0e+00  +2.0e+00", t, flags=_re.M)),
    ):
        txt2 = sub(_fake_report(0.6, 0.0))
        fp2 = os.path.join(tempfile.mkdtemp(), "v.rpt")
        with open(fp2, "w") as f:
            f.write(txt2)
        q = next(iter(parse_annotated(fp2).values()))
        assert (q.launch_edge, q.capture_edge) == (0.0, 2.0), (name, q.launch_edge,
                                                              q.capture_edge)


def test_merge_summary_agrees_with_the_per_model_arrays(real_tree, tmp_path,
                                                         monkeypatch):
    """What merge reports per corner must be what the per-model files contain.

    The prediction hand-off is `.npz` only -- path_keys, corners, truth_ps,
    model_ps -- and the summary is DERIVED from it rather than written beside
    it. There used to be a CSV of the same numbers with a per-corner block
    appended under a blank line, which merge had to know to skip: two files and
    a parsing rule where an array and a derivation do.

    So this recomputes the summary by hand from the arrays and demands the same
    answer, which is the property that matters -- nobody reads the npz, and a
    derived table that drifts from it drifts invisibly.
    """
    pytest.importorskip("torch")
    import json as _json

    from si_model.parsing.build_dataset import build
    from si_model.run import (expand, load_project, select, stage_merge,
                              stage_train)

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]
    p["files"]["crosstalk_subdir"] = None
    p["train"]["epochs"] = 1
    p["train"]["device"] = "cpu"
    m = select(expand(p), design="boomcore", temp="m25")[0]
    build(m["cfg"])
    stage_train(m)

    out = m["cfg"]["train"]["out_dir"]
    assert not [f for f in os.listdir(out) if f.endswith(".csv")], \
        sorted(os.listdir(out))
    z = np.load(os.path.join(out, "predictions_hidden.npz"), allow_pickle=False)
    corners = [str(x) for x in z["corners"]]
    truth, model = z["truth_ps"], z["model_ps"]
    assert truth.shape == model.shape == (len(z["path_keys"]), len(corners))

    stage_merge([m], p, "hidden")
    with open("runs/setup/_all/summary.json") as f:
        by = {r["corner"]: r for r in _json.load(f)["by_corner"]}
    assert sorted(by) == sorted(corners)
    for ci, cn in enumerate(corners):
        t, md = truth[:, ci], model[:, ci]
        r = by[cn]
        assert r["n_paths"] == len(t)
        assert abs(r["mean_truth_ps"] - float(t.mean())) < 1e-3
        assert abs(r["mae_ps"] - float(np.abs(md - t).mean())) < 1e-3
        # WNS is the worst MEASURED path against its OWN prediction -- not the
        # two minima taken apart, which can be different paths
        w = int(np.argmin(t))
        assert abs(r["wns_truth_ps"] - float(t[w])) < 1e-3
        assert abs(r["wns_model_ps"] - float(md[w])) < 1e-3
        assert abs(r["wns_err_ps"] - float(md[w] - t[w])) < 1e-3

    # the merged file is one long table, design and temp as columns, so
    # circuits and temperatures trained separately read as one thing
    g = np.load("runs/setup/_all/predictions_hidden.npz", allow_pickle=False)
    assert len(g["truth_ps"]) == truth.size
    assert set(str(x) for x in g["design"]) == {"boomcore"}
    assert set(str(x) for x in g["temp"]) == {"m25"}
    assert sorted(set(str(x) for x in g["corner"])) == sorted(corners)
    assert not os.path.exists("runs/setup/_all/predictions_hidden.csv")


def test_the_base_report_uses_each_circuits_own_hidden_corners(tmp_path,
                                                               monkeypatch):
    """`hidden_corners` is declared PER temperature and circuits need not
    agree, so the base report's columns are the union of what each circuit held
    out -- and a circuit that did not hold a corner out leaves that cell empty.

    It used to take the FIRST circuit's corner list as the header for every
    circuit at that temperature. Every other circuit's numbers were then
    printed under labels belonging to that first one: a corner one circuit held
    out can be a seen corner for another, and the two are not the same number.
    """
    import si_model.run as run

    monkeypatch.chdir(tmp_path)
    keys = ["a->b_#%d" % i for i in range(5)]
    models, want = [], {}
    # two circuits at one temperature, holding out DIFFERENT corners
    for design, corners, val in (("cpuA", ["V1_rcmax", "V2_cmax"], 10.0),
                                 ("cpuB", ["V2_cmax", "V3_rcmin"], 20.0)):
        out = os.path.join("runs", "setup", design, "125")
        os.makedirs(out)
        np.savez_compressed(
            os.path.join(out, "predictions_base.npz"),
            path_keys=np.asarray(keys), path_idx=np.arange(5),
            corners=np.asarray(corners), seen=np.zeros(len(corners), bool),
            measured=np.ones(len(corners), bool),
            truth_ps=np.full((5, len(corners)), val),
            model_ps=np.full((5, len(corners)), val + 1.0),
            clock_ns=np.full(len(corners), 2.0), n_cycles=np.ones(5))
        models.append({"design": design, "temp": "125",
                       "cfg": {"train": {"out_dir": out}}})
        want[design] = (corners, val + 1.0)

    p = {"mode": "setup", "out": {"runs": "runs"}}
    written = run._report_from_saved(p, models, "base")
    assert len(written) == 1
    txt = open(written[0]).read()

    # every corner either circuit held out is a column, each named once
    hdr = [l for l in txt.splitlines() if l.startswith("Corners")][0]
    assert hdr.split(":", 1)[1].split() == \
        ["V1_rcmax,", "V2_cmax,", "V3_rcmin"], hdr

    # and each circuit's block fills only its own
    for design, (corners, v) in want.items():
        blk = txt.split("Design: " + design, 1)[1].split("Design: ")[0]
        row = [l for l in blk.splitlines()
               if "mean predicted slack" in l][0].split()
        cells = [x for x in row if x.replace(".", "").replace("-", "").isdigit()]
        assert len(cells) == len(corners), (design, row)
        assert all(abs(float(x) - v) < 0.05 for x in cells), (design, row)


def test_the_base_report_is_one_file_rewritten_in_order(tmp_path, monkeypatch,
                                                        capsys):
    """runs/<mode>/_all/predict_<temp>_base.rpt: one file, rewritten each run,
    columns in voltage-then-level order, held-out corners only.

    Each of these was a way the _all folder looked wrong on real data:
      * it went through predict's never-overwrite naming, so every run added a
        _2, _3 -- and the plainest name, the file anybody opens, was the
        OLDEST, from whatever code ran first;
      * columns came in order of first appearance across circuits, so 0.76 V
        sat before 0.6 V;
      * an array written by an earlier version carried seen corners too, and
        they came back as report columns.
    """
    import si_model.run as run

    monkeypatch.chdir(tmp_path)
    cfg_common = {"data": {"corner_prefix": "SSPG"},
                  "base": {"axes": [{"name": "v"},
                                    {"name": "lv", "levels": {
                                        "rcmin": -1, "cmax": 0, "rcmax": 1}}]}}
    keys = ["a->b_#%d" % i for i in range(4)]
    models = []
    for design, corners, seen in (
            ("MFC", ["SSPG_0p76V_cmax", "SSPG_0p5V_cmax"], [False, False]),
            # an old-format array: every corner, seen ones included
            ("PERIC0", ["SSPG_0p6V_cmax", "SSPG_0p685V_cmax", "SSPG_0p54V_rcmax"],
             [False, True, False])):
        out = os.path.join("runs", "setup", design, "125")
        os.makedirs(out)
        C = len(corners)
        np.savez_compressed(
            os.path.join(out, "predictions_base.npz"),
            path_keys=np.asarray(keys), path_idx=np.arange(4),
            corners=np.asarray(corners), seen=np.asarray(seen),
            measured=np.ones(C, bool), truth_ps=np.full((4, C), 5.0),
            model_ps=np.full((4, C), 6.0), clock_ns=np.full(C, 2.0),
            n_cycles=np.ones(4))
        cfg = dict(cfg_common, train={"out_dir": out})
        models.append({"design": design, "temp": "125", "cfg": cfg})

    p = {"mode": "setup", "out": {"runs": "runs"}}
    all_dir = os.path.join(run._runs_root(p), "_all")
    first = run._report_from_saved(p, models, "base")
    again = run._report_from_saved(p, models, "base")
    assert first == again == [os.path.join(all_dir, "predict_125_base.rpt")]
    assert sorted(os.listdir(all_dir)) == ["predict_125_base.rpt"], \
        "rewritten in place, no _2"

    hdr = [l for l in open(first[0]).read().splitlines()
           if l.startswith("Corners")][0].split(":", 1)[1]
    assert [c.strip() for c in hdr.split(",")] == [
        "SSPG_0p5V_cmax", "SSPG_0p54V_rcmax", "SSPG_0p6V_cmax",
        "SSPG_0p76V_cmax"], hdr                  # sorted; 0p685V (seen) gone

    # copies left by the old naming are named, not silently kept
    open(first[0][:-4] + "_2.rpt", "w").write("old")
    capsys.readouterr()
    run._report_from_saved(p, models, "base")
    assert "predict_125_base_2.rpt are older copies" in capsys.readouterr().out
