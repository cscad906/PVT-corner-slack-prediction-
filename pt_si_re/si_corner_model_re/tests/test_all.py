"""\ud14c\uc2a4\ud2b8\ub294 \uc774 \ud30c\uc77c \ud558\ub098. \ub370\uc774\ud130 \uc5c6\uc774 numpy \ub9cc\uc73c\ub85c \ub3c8\ub2e4.

    python -m pytest tests/ -q

\uc138 \ub369\uc5b4\ub9ac:
  1. config.yaml \ud655\uc7a5   -- designs x temps \uac00 \ubaa8\ub378 \ub9e4\ud2b8\ub9ad\uc2a4\ub85c \ud3bc\uccd0\uc9c0\ub294\uac00
  2. \ucf54\ub108 \ud0d0\uc0c9          -- \ud30c\uc77c\uba85 -> \ucf54\ub108 \ub77c\ubca8, \uc628\ub3c4/\ub808\ubca8 \ud544\ud130
  3. \uc5d4\uc9c4 \uc218\ud559/\ud5ec\ud37c     -- \ub2e4\ud56d\uc2dd \uae30\uc800 \uc0dd\uc131, OLS base, \uacbd\ub85c\ud0a4/\uc140 \ud30c\uc2f1
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


# =============================================================== 1. config \ud655\uc7a5
@pytest.fixture
def tree(tmp_path):
    """\ud68c\uc0ac \ubc30\uce58: <root>/<\ud68c\ub85c>/ \ubc11\uc5d0 \ucf54\ub108\uac00 \ud30c\uc77c\uba85\uc5d0 \ub2e4 \ub4e4\uc5b4\uc788\ub294 \ub9ac\ud3ec\ud2b8\ub4e4."""
    for design in ("cpu", "gpu"):
        d = tmp_path / design / "setup"          # \ubc30\ud3ec \ubc30\uce58: <\ud68c\ub85c>/setup/
        d.mkdir(parents=True)
        for v in ("0p5000", "0p5400", "0p6000", "0p6850"):
            for lv in ("rcmax", "cmax"):
                (d / f"report.sspg_{v}_125c_{lv}.rpt").touch()
            for lv in ("rcmax", "cmax", "rcmin"):
                (d / f"report.sspg_{v}_m25c_{lv}.rpt").touch()
    return tmp_path


@pytest.fixture
def project(tree):
    """\uc2e4\uc81c config.yaml \uc744 \uc77d\uc5b4 root \ub9cc fixture \ud2b8\ub9ac\ub85c \ubc14\uafbc\ub2e4 -- \ubc30\ud3ec\ub418\ub294 \uadf8 \ud30c\uc77c\uc774
    \uc2a4\ud0a4\ub9c8\uc0c1 \uc720\ud6a8\ud55c\uc9c0\uae4c\uc9c0 \uac19\uc774 \uac80\uc99d\ub41c\ub2e4."""
    with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
        p = yaml.safe_load(f)
    p["root"] = str(tree)
    p["designs"] = "auto"
    return p


def _clear_temp_holdout(p):
    """temps[] \uc758 \uc628\ub3c4\ubcc4 \ud640\ub4dc\uc544\uc6c3\uc744 \uc9c0\uc6cc \uc804\uc5ed \uc124\uc815\ub9cc \ubcf4\uac8c \ud55c\ub2e4."""
    p["temps"] = [{k: v for k, v in t.items() if k not in
                   ("hidden_corners", "hidden_per_voltage", "hidden_voltages",
                    "seen_voltages", "hidden_levels")} for t in p["temps"]]
    return p


def _use_voltage_row_holdout(p):
    """\ubc30\ud3ec config \ub294 \uc628\ub3c4\ubcc4 hidden_corners \ub97c \uc4f4\ub2e4. \uc804\uc555 \ud589 \ud640\ub4dc\uc544\uc6c3\uc744 \uc804\uc81c\ub85c \ud55c
    \ud14c\uc2a4\ud2b8\ub294 \uadf8 \uc124\uc815\uc73c\ub85c \ub418\ub3cc\ub824 \ub193\uace0 \uac80\uc0ac\ud55c\ub2e4."""
    _clear_temp_holdout(p)
    p["corners"] = dict(p["corners"], hidden_voltages=[0.54], hidden_corners=[],
                        hidden_per_voltage=0)
    return p


def test_shipped_config_yaml_parses():
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["corners"]["process"] and p["temps"] and p["files"]["annotated_regex"]
    assert os.path.isabs(p["root"])


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "euc-kr", "cp949"])
def test_project_config_reads_legacy_korean_encoding(tmp_path, encoding):
    source = "root: auto\ndesigns: [cpu]\n# \ud55c\uad6d\uc5b4 \uc8fc\uc11d\n"
    path = tmp_path / "config.yaml"
    path.write_bytes(source.encode(encoding))
    p = load_project(str(path))
    assert p["designs"] == ["cpu"]


def test_shipped_config_defaults_to_the_deployed_layout():
    """\ubc30\ud3ec \ubc30\uce58\ub294 <root>/{si_corner_model, \ud68c\ub85c1, \ud68c\ub85c2, \ud68c\ub85c3} \uc774\ub2e4.
    \uadf8 \uacbd\uc6b0 root/designs \ub97c \uc190\ub300\uc9c0 \uc54a\uc544\ub3c4 \ub9de\uc544\uc57c \ud55c\ub2e4."""
    with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
        raw = yaml.safe_load(f)
    assert raw["root"] == "auto", "\uae30\ubcf8 root \ub294 auto \uc5ec\uc57c \ud55c\ub2e4 (repo \uc758 \ubd80\ubaa8 = \ud68c\ub85c\ub4e4\uc774 \uc788\ub294 \uacf3)"
    # root \uc5d0 \ube44\ud68c\ub85c \ud3f4\ub354\ub3c4 \uc788\uc73c\ubbc0\ub85c designs \ub294 \uba85\uc2dc \ubaa9\ub85d \ub610\ub294 \ud68c\ub85c\ubcc4 \ub9e4\ud551\uc774\ub2e4.
    assert isinstance(raw["designs"], (list, dict)) and raw["designs"]
    # auto \ub294 \uc774 checkout \uc758 \ubd80\ubaa8 \ub514\ub809\ud1a0\ub9ac\ub85c \ud480\ub9b0\ub2e4
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["root"] == os.path.dirname(REPO_ROOT)


def test_shipped_mif_mfc_peric0_grids_and_holdouts():
    """\ud68c\ub85c\ubcc4 \ucf54\ub108 \uad6c\uc131\uc774 \uacfc\uac70 \uacf5\ud1b5 PERIC0 \uadf8\ub9ac\ub4dc\ub85c \ub418\ub3cc\uc544\uac00\uc9c0 \uc54a\uac8c \ud55c\ub2e4."""
    from si_model.training.loo import make_split

    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    models = {m["name"]: m["cfg"] for m in expand(p)}
    expected = {
        "PERIC0_Timing_Report/125": (4, 2, 6),
        "PERIC0_Timing_Report/m25": (4, 2, 10),
        "MFC_Timing_Report/125": (5, 2, 8),
        "MFC_Timing_Report/m25": (5, 3, 12),
        "MIF_Timing_Report/125": (7, 3, 11),
        "MIF_Timing_Report/m25": (7, 4, 17),
    }
    assert set(models) == set(expected)
    for name, (n_v, n_hidden, n_seen) in expected.items():
        cfg = models[name]
        assert cfg["split"]["min_seen"] == n_seen
        assert len(cfg["split"]["hidden_corners"]) == n_hidden
        assert "seen_corners" not in cfg["split"]  # \ube48 \uc785\ub825\ub780 -> \uae30\uc874 \ubd84\ud560
        project = p["designs"].get(name.split("/")[0], {})
        volts = project.get("corners", {}).get("voltages", p["corners"]["voltages"])
        assert len(volts) == n_v
        levels = cfg["data"]["rc_corners"]
        labels = [corner_label(v, lv, "SSPG") for v in volts for lv in levels]
        coords = cfg["base"]["axes"][1]["levels"]
        vt = np.asarray([parse_corner(c, coords, "SSPG") for c in labels], np.float32)
        split = make_split(labels, vt, cfg)
        assert int(split.seen.sum()) == n_seen
        assert int(split.hidden.sum()) == n_hidden
        assert split.seen[split.ref_ci]


def test_auto_root_finds_mif_mfc_reports_above_nested_repo(tmp_path, monkeypatch):
    """A model copied under pt_si_re still finds sibling design reports."""
    data_root = tmp_path / "academy_experiment"
    nested_repo = data_root / "pt_si_re" / "si_corner_model_re"
    nested_repo.mkdir(parents=True)
    for design in ("MFC_Timing_Report", "MIF_Timing_Report"):
        (data_root / design).mkdir()
    monkeypatch.setattr("si_model.run.REPO_ROOT", str(nested_repo))
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["root"] == str(data_root)


def test_repo_itself_is_not_mistaken_for_a_design(tmp_path):
    """root \ubc11\uc5d0 \uc774 repo \uac00 \uac19\uc774 \uc788\uc5b4\ub3c4 \ud68c\ub85c\ub85c \uc7a1\ud788\uba74 \uc548 \ub41c\ub2e4."""
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
    assert m["cfg"]["data"]["rc_corners"] == ["rcmax", "cmax"]        # 125C \ub294 2\ub808\ubca8
    assert models[1]["cfg"]["data"]["rc_corners"] == ["rcmax", "cmax", "rcmin"]
    assert m["cfg"]["data"]["ref_corner"] == "SSPG_0p685V_cmax"
    assert m["cfg"]["data"]["cache"].endswith(os.path.join("cpu", "125", "dataset.npz"))
    assert m["cfg"]["train"]["out_dir"].endswith(os.path.join("cpu", "125"))


def test_expand_auto_order_matches_available_levels(project):
    _use_voltage_row_holdout(project)
    by = {m["name"]: m["cfg"]["base"]["axes"] for m in expand(project)}
    # seen V = 3 (0.54 \uc228\uae40) -> v order 2 ; 125C \ub294 \ub808\ubca8 2\uac1c -> level order 1
    assert by["cpu/125"][0]["order"] == 2 and by["cpu/125"][1]["order"] == 1
    # m25C \ub294 \ub808\ubca8 3\uac1c -> level order 2
    assert by["cpu/m25"][1]["order"] == 2


def test_expand_min_seen_is_full_grid(project):
    _use_voltage_row_holdout(project)
    by = {m["name"]: m["cfg"]["split"]["min_seen"] for m in expand(project)}
    assert by["cpu/125"] == 3 * 2      # seen V 3\uac1c x \ub808\ubca8 2\uac1c
    assert by["cpu/m25"] == 3 * 3      # \ub9ac\ud3ec\ud2b8\uac00 \ube60\uc9c0\uba74 \uc5ec\uae30\uc11c \uc5d0\ub7ec\uac00 \ub09c\ub2e4


def test_expand_si_on_when_crosstalk_declared(project):
    cfg = expand(project)[0]["cfg"]
    assert cfg["data"]["crosstalk_dir"].endswith(os.path.join("setup", "xtalk"))
    assert "crosstalk_regex" in cfg["data"]["patterns"]


def test_bundle_packs_every_temperature_into_one_file(project, tmp_path):
    """\ud68c\ub85c \ud558\ub098 = \ud30c\uc77c \ud558\ub098. \uc628\ub3c4\ubcc4\ub85c \uac08\ub77c\uc9c0\uba74 \uc548 \ub41c\ub2e4.

    torch \uac00 \uc5c6\ub294 \ud658\uacbd(\ud68c\uc0ac\uc5d0\uc11c \ud559\uc2b5 \uc804 \uc810\uac80)\uc5d0\uc11c\ub294 \uac74\ub108\ub6f4\ub2e4."""
    torch = pytest.importorskip("torch")
    from si_model.run import bundle_path, stage_bundle

    models = expand(project)
    for m in models:                       # \ud559\uc2b5\ub41c \uac83\ucc98\ub7fc \uac00\uc9dc \uccb4\ud06c\ud3ec\uc778\ud2b8\ub97c \uae54\uc544\ub454\ub2e4
        d = m["cfg"]["train"]["out_dir"] = str(tmp_path / m["design"] / str(m["temp"]))
        os.makedirs(d, exist_ok=True)
        torch.save({"model": {"w": torch.zeros(1)}, "enc": {"w": torch.zeros(1)},
                    "cfg": m["cfg"], "epoch": 7}, os.path.join(d, "best.pt"))

    stage_bundle(models)

    for design in {m["design"] for m in models}:
        ms = [m for m in models if m["design"] == design]
        b = torch.load(bundle_path(ms[0]), map_location="cpu")
        assert b["design"] == design
        # \uadf8 \ud68c\ub85c\uc758 \ubaa8\ub4e0 \uc628\ub3c4\uac00 \ud55c \ud30c\uc77c \uc548\uc5d0 \uc788\uc5b4\uc57c \ud55c\ub2e4
        assert set(b["temps"]) == {str(m["temp"]) for m in ms}
        assert all("model" in v and "enc" in v for v in b["temps"].values())


def test_bundle_skips_untrained_temperatures_instead_of_failing(project, tmp_path):
    """\uc628\ub3c4 \ud558\ub098\ub9cc \ud559\uc2b5\ud574\ub3c4 bundle \uc740 \uadf8 \ud558\ub098\ub85c \ub9cc\ub4e4\uc5b4\uc838\uc57c \ud55c\ub2e4 -- \ub098\uba38\uc9c0\ub97c
    \uae30\ub2e4\ub9ac\ub290\ub77c \ud1b5\uc9f8\ub85c \uc2e4\ud328\ud558\uba74 \ubd80\ubd84 \uc7ac\ud559\uc2b5\uc744 \ud560 \uc218\uac00 \uc5c6\ub2e4."""
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
    """\uc694\uc57d\uc740 '\ubaa8\ub378\ubcc4' \uc774 \uc544\ub2c8\ub77c '\ucf54\ub108\ubcc4' \uc774\uc5b4\uc57c \ud55c\ub2e4.

    \ubaa8\ub378(\ud68c\ub85cx\uc628\ub3c4)\uc740 \ub0b4\ubd80 \ubd84\ud560\uc77c \ubfd0\uc774\uace0, \ub118\uae38 \ub54c \uad81\uae08\ud55c \uac74 "\uc774 \ucf54\ub108\uac00 \uc5bc\ub9c8\ub098
    \uc798 \ub9de\uc558\ub098" \ub2e4. \uc815\ub2f5\uc774 \uc5c6\ub294 query \ucf54\ub108\ub294 \uacbd\ub85c \uc218\ub9cc \uc138\uace0 \uc624\ucc28\ub294 \ube44\uc6b4\ub2e4."""
    from si_model.run import _corner_table

    fp = tmp_path / "predictions_hidden.csv"
    fp.write_text(
        "design,temp,path_key,corner,truth_ps,model_ps,model_err_ps\n"
        "cpu,125,A,SSPG_0p54V_rcmax,10.0,12.0,2.0\n"
        "cpu,125,B,SSPG_0p54V_rcmax,10.0,6.0,-4.0\n"
        "cpu,m25,A,SSPG_0p5V_cmax,10.0,11.0,1.0\n"
        "cpu,m25,A,SSPG_0p57V_cmax,,11.0,\n")          # query \ucf54\ub108 (\uc815\ub2f5 \uc5c6\uc74c)

    rows = {(r["temp"], r["corner"]): r for r in _corner_table(str(fp))}
    assert len(rows) == 3
    assert rows[("125", "SSPG_0p54V_rcmax")]["mae_ps"] == 3.0      # (2+4)/2
    assert rows[("125", "SSPG_0p54V_rcmax")]["worst_ps"] == 4.0
    assert rows[("125", "SSPG_0p54V_rcmax")]["n_paths"] == 2
    # query \ucf54\ub108: \uacbd\ub85c\ub294 \uc138\uc9c0\ub9cc \uc624\ucc28\ub294 \uc5c6\ub2e4 -- 0.0 \uc73c\ub85c \uc138\uba74 \ud3c9\uade0\uc774 \uc88b\uc544 \ubcf4\uc778\ub2e4
    q = rows[("m25", "SSPG_0p57V_cmax")]
    assert q["n_paths"] == 1 and q["mae_ps"] is None and q["worst_ps"] is None


def test_merge_flags_a_summary_older_than_its_checkpoint(project, tmp_path, capsys):
    """\ud559\uc2b5\uc744 \uc911\uac04\uc5d0 \ub04a\uc73c\uba74 best.pt \ub9cc \uac31\uc2e0\ub418\uace0 summary.json \uc740 \uc774\uc804 \uc2e4\ud589 \uac83\uc774
    \ub0a8\ub294\ub2e4. \uadf8\uac8c \uc870\uc6a9\ud788 by_model \ub85c \uc2e4\ub824 \ub098\uac00\uba74 \uc548 \ub41c\ub2e4."""
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
    open(os.path.join(d, "best.pt"), "w").close()          # summary \ubcf4\ub2e4 \ub098\uc911
    os.utime(os.path.join(d, "summary.json"), (1, 1))

    project["out"] = {"runs": str(tmp_path / "out"), "cache": str(tmp_path / "c")}
    stage_merge(models, project, "hidden")
    assert "\uc624\ub798\ub428" in capsys.readouterr().out


def test_adaptive_downgrades_to_plain_on_a_grid_too_small_for_it(project):
    """adaptive \ub294 \uc774\uc6c3 adaptive_k \uac1c\ub85c \ub300\uc5ed\ud3ed\uc744 \uace0\ub978\ub2e4. seen \ucf54\ub108\uac00 \uadf8\ubcf4\ub2e4 \ub9ce\uc9c0
    \uc54a\uc73c\uba74 \uc774\uc6c3 = \uc804\uccb4\uac00 \ub418\uc5b4 \ud6c4\ubcf4\ub4e4\uc774 \uac19\uc740 \ub370\uc774\ud130\ub85c \ucc44\uc810\ub418\uace0, \uc2b9\uc790\ub294 \uc7a1\uc74c\uc774\ub2e4.

    \uc2e4\uce21(14nm, 125C: seen 6 / adaptive_k 6): adaptive 3.151 ps vs plain 2.148 ps.
    \ucf54\ub108 \uc218\ub9cc \ubcf4\uace0 \uc815\ud558\ubbc0\ub85c \ub77c\ubca8\uc744 \uc77d\uae30 \uc804\uc5d0 \uacb0\uc815\ub41c\ub2e4."""
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
    # \uba85\uc2dc\uc801\uc73c\ub85c \uace0\ub978 \ubaa8\ub4dc\ub294 \uac74\ub4dc\ub9ac\uc9c0 \uc54a\ub294\ub2e4
    cfg["base"]["weighting"] = "plain"
    assert _effective_mode(cfg, split_with(10)) == "plain"


def test_mode_switches_every_path_at_once(project):
    """`mode` \ud55c \uc904\uc774 \uc77d\uc744 \ud3f4\ub354\uc640 \uc4f8 \ud3f4\ub354\ub97c \uc804\ubd80 \uac08\ub77c\uc57c \ud55c\ub2e4.

    \uc608\uc804\uc5d0\ub294 files.subdir / files.crosstalk_subdir / out.cache / out.runs \ub97c \uac01\uac01
    \uace0\uccd0\uc57c \ud588\uace0, subdir \ub9cc hold \ub85c \ubc14\uafb8\uace0 out \uc744 \uc78a\uc73c\uba74 hold \uacb0\uacfc\uac00 setup \uce90\uc2dc\ub97c
    \uc870\uc6a9\ud788 \ub36e\uc5b4\uc37c\ub2e4. \ub137\uc774 \ud568\uaed8 \uc6c0\uc9c1\uc774\ub294\uc9c0 \uc5ec\uae30\uc11c \ubabb \ubc15\ub294\ub2e4."""
    project["mode"] = "hold"
    m = expand(project)[0]
    d = m["cfg"]["data"]
    assert d["annotated_dir"].endswith(os.sep + "hold")
    assert d["crosstalk_dir"].endswith(os.path.join("hold", "xtalk"))
    assert d["cache"].startswith(os.path.join("cache", "hold") + os.sep)
    assert m["cfg"]["train"]["out_dir"].startswith(os.path.join("runs", "hold") + os.sep)


def test_mode_does_not_override_an_explicit_subdir(project):
    """\ud3f4\ub354\uba85\uc774 setup/hold \uac00 \uc544\ub2cc \ubc30\uce58\ub3c4 \uc788\uc5b4\uc57c \ud55c\ub2e4 -- auto \uac00 \uc544\ub2cc \uac12\uc740 \uadf8\ub300\ub85c."""
    project["mode"] = "hold"
    project["files"]["subdir"] = "reports"
    d = expand(project)[0]["cfg"]["data"]
    assert d["annotated_dir"].endswith(os.sep + "reports")
    assert d["cache"].startswith(os.path.join("cache", "hold") + os.sep)


def test_expand_si_off_when_crosstalk_subdir_is_null(project):
    """\uc704\uce58\ub97c \ubaa8\ub97c \ub550 null \ub85c \ub450\uace0 SI \uc5c6\uc774 \uba3c\uc800 \ub3cc\ub9b4 \uc218 \uc788\uc5b4\uc57c \ud55c\ub2e4."""
    project["files"]["crosstalk_subdir"] = None
    assert "crosstalk_dir" not in expand(project)[0]["cfg"]["data"]


def test_expand_rejects_bad_anchor(project):
    _use_voltage_row_holdout(project)
    project["corners"]["ref_voltage"] = 0.54        # \uc228\uae34 \uc804\uc555
    with pytest.raises(AssertionError, match="ref_voltage"):
        expand(project)
    project["corners"]["ref_voltage"] = 0.685
    project["corners"]["ref_level"] = "nope"
    with pytest.raises(AssertionError, match="ref_level"):
        expand(project)


# ---- \ud68c\ub85c\ub9c8\ub2e4 \ub2e4\ub978 \uc124\uc815 ------------------------------------------------------
def test_all_designs_share_settings_by_default(project):
    """\uae30\ubcf8\uc740 '\ud68c\ub85c 3\uac1c, \ucf54\ub108\ub3c4 \ud640\ub4dc\uc544\uc6c3\ub3c4 \uc804\ubd80 \ub3d9\uc77c'. \ud68c\ub85c\ub97c \ub298\ub824\ub3c4 \uc124\uc815\uc740 \ud558\ub098."""
    models = expand(project)
    by_design = {}
    for m in models:
        by_design.setdefault(m["design"], {})[m["temp"]] = m["cfg"]
    assert set(by_design) == {"cpu", "gpu"}
    a, b = by_design["cpu"], by_design["gpu"]
    for tag in ("125", "m25"):
        assert a[tag]["split"] == b[tag]["split"], f"{tag}: \ud68c\ub85c\ubcc4 \ud640\ub4dc\uc544\uc6c3\uc774 \ub2ec\ub77c\uc84c\ub2e4"
        assert a[tag]["base"] == b[tag]["base"]
        assert a[tag]["data"]["rc_corners"] == b[tag]["data"]["rc_corners"]
    # \uc628\ub3c4\ub07c\ub9ac\ub294 \ub2ec\ub77c\uc57c \ud55c\ub2e4 (\ub808\ubca8 \uc218\uac00 \ub2e4\ub974\ubbc0\ub85c)
    assert a["125"]["data"]["rc_corners"] != a["m25"]["data"]["rc_corners"]


def test_designs_mapping_gives_per_circuit_overrides(project):
    """`designs:` \ub97c \ub9e4\ud551\uc73c\ub85c \uc4f0\uba74 \ud55c \ud68c\ub85c\ub9cc \ub2e4\ub974\uac8c \uc904 \uc218 \uc788\ub2e4 -- config \ub97c
    \ud68c\ub85c\ubcc4\ub85c \ubcf5\uc0ac\ud558\uc9c0 \uc54a\uace0 \ud55c \ud30c\uc77c\uc5d0\uc11c."""
    project["designs"] = {
        "cpu": {},                                        # \uc804\uc5ed \uadf8\ub300\ub85c
        "gpu": {"corners": {"voltages": [0.5, 0.6, 0.685]},
                "files": {"subdir": "reports"}},
    }
    by = {m["name"]: m["cfg"] for m in expand(project)}
    assert set(by) == {"cpu/125", "cpu/m25", "gpu/125", "gpu/m25"}
    # cpu \ub294 \uc804\uc555 4\uac1c, gpu \ub294 3\uac1c -> \ucf54\ub108 \uc218(min_seen)\uac00 \uac08\ub9b0\ub2e4
    assert by["cpu/125"]["split"]["min_seen"] == 4 * 2 - 2
    assert by["gpu/125"]["split"]["min_seen"] == 3 * 2 - 2
    # override \ud558\uc9c0 \uc54a\uc740 \ud0a4\ub294 \uc804\uc5ed\uc744 \uadf8\ub300\ub85c \ubb3c\ub824\ubc1b\ub294\ub2e4
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
    assert "gpu/m25" not in by, "override \ud55c temps \ubaa9\ub85d\uc774 \uadf8\ub300\ub85c \uc4f0\uc778\ub2e4(125 \ud558\ub098\ubfd0)"


# ---- \uc628\ub3c4\ub9c8\ub2e4 \ub2e4\ub978 \ud640\ub4dc\uc544\uc6c3 --------------------------------------------------
def test_holdout_can_differ_per_temperature(project):
    """125C \ub294 \ub808\ubca8\uc774 2\uac1c, m25C \ub294 3\uac1c\ub2e4. \uadf8\ub798\uc11c '\uc774 \ucf54\ub108\ub97c \uc228\uaca8\ub77c' \ub97c \uc804\uc5ed \ubaa9\ub85d
    \ud558\ub098\ub85c\ub294 \uc4f8 \uc218 \uc5c6\uace0, temps[] \uc548\uc5d0\uc11c \uc628\ub3c4\ubcc4\ub85c \uc801\uc744 \uc218 \uc788\uc5b4\uc57c \ud55c\ub2e4."""
    project["corners"]["hidden_voltages"] = []
    project["temps"][0]["hidden_corners"] = [[0.5, "rcmax"], [0.6, "cmax"]]
    project["temps"][1]["hidden_corners"] = [[0.54, "rcmin"], [0.685, "rcmax"]]
    by = {m["temp"]: m["cfg"]["split"] for m in expand(project) if m["design"] == "cpu"}
    assert by["125"]["hidden_corners"] == [[0.5, "rcmax"], [0.6, "cmax"]]
    assert by["m25"]["hidden_corners"] == [[0.54, "rcmin"], [0.685, "rcmax"]]
    # min_seen \ub3c4 \uc628\ub3c4\ubcc4 \ud640\ub4dc\uc544\uc6c3\uc744 \ubc18\uc601\ud574\uc57c \ud55c\ub2e4 (4V x 2\ub808\ubca8 - 2 = 6)
    assert by["125"]["min_seen"] == 4 * 2 - 2
    assert by["m25"]["min_seen"] == 4 * 3 - 2


def test_holdout_level_must_exist_at_that_temperature(project):
    """125C \uc5d0 \uc5c6\ub294 rcmin \uc744 125C \ud640\ub4dc\uc544\uc6c3\uc5d0 \uc801\uc73c\uba74 \uc870\uc6a9\ud788 \ubb34\uc2dc\ub418\uc9c0 \uc54a\uace0 \uc5d0\ub7ec."""
    project["corners"]["hidden_voltages"] = []
    project["temps"][0]["hidden_corners"] = [[0.5, "rcmin"]]      # 125C \uc5d4 rcmin \uc5c6\uc74c
    with pytest.raises(AssertionError, match="hidden_corners"):
        expand(project)


def test_hidden_per_voltage_spreads_one_corner_per_voltage(project):
    """\uc804\uc555 \ud589\uc744 \ud1b5\uc9f8\ub85c \ube7c\ub294 \ub300\uc2e0, \uc804\uc555\ub9c8\ub2e4 \ud55c \uce78\uc529 \ud769\uc5b4\uc11c \uc228\uae34\ub2e4."""
    _clear_temp_holdout(project)
    project["corners"]["hidden_voltages"] = []
    project["corners"]["hidden_per_voltage"] = 1
    by = {m["temp"]: m["cfg"]["split"] for m in expand(project) if m["design"] == "cpu"}
    for tag, n_lv in (("125", 2), ("m25", 3)):
        hc = by[tag]["hidden_corners"]
        vs = [v for v, _ in hc]
        assert len(hc) == 4, f"{tag}: \uc804\uc555 4\uac1c -> 4\uce78"
        assert sorted(vs) == [0.5, 0.54, 0.6, 0.685], f"{tag}: \ubaa8\ub4e0 \uc804\uc555\uc5d0 \ud558\ub098\uc529"
        assert (0.685, "cmax") not in [(v, l) for v, l in hc], "\uc575\ucee4\ub294 \uc228\uae30\uba74 \uc548 \ub428"
        assert len({l for _, l in hc}) > 1, f"{tag}: \ud55c \ub808\ubca8\uc5d0 \ubab0\ub9ac\uba74 \uc548 \ub428"
        assert by[tag]["min_seen"] == 4 * n_lv - 4


def test_hidden_per_voltage_cannot_take_every_level(project):
    _clear_temp_holdout(project)
    project["corners"]["hidden_voltages"] = []
    project["corners"]["hidden_per_voltage"] = 2      # 125C \ub294 \ub808\ubca8\uc774 2\uac1c\ubfd0
    with pytest.raises(AssertionError, match="hidden_per_voltage"):
        expand(project)


def test_expand_rejects_level_missing_from_values(project):
    project["temps"][0]["levels"] = ["rcmax", "cworst"]
    with pytest.raises(AssertionError, match="level_values"):
        expand(project)


# ---- \ucf54\ub108 \uc120\uc815: config \uc758 \ub124 \uac00\uc9c0 \ubc29\ubc95\uc774 \uc2e4\uc81c split \uc73c\ub85c \uc774\uc5b4\uc9c0\ub294\uac00 ----------
def _hidden_labels(project, corners_over):
    """project \ub97c \uc8fc\uc5b4\uc9c4 corners \uc624\ubc84\ub77c\uc774\ub4dc\ub85c \ud655\uc7a5\ud574 hidden \ucf54\ub108 \ub77c\ubca8\uc744 \ub3cc\ub824\uc900\ub2e4."""
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
    cfg["split"]["min_seen"] = 1                     # \uac00\ub4dc\ub294 \uc5ec\uae30\uc11c \uad00\uc2ec\uc0ac\uac00 \uc544\ub2d8
    sp = make_split(labels, vt, cfg)
    return {labels[i] for i in sp.hidden_idx}


def test_hidden_voltages_hides_whole_row(project):
    assert _hidden_labels(project, {"hidden_voltages": [0.54]}) == {
        "SSPG_0p54V_rcmax", "SSPG_0p54V_cmax", "SSPG_0p54V_rcmin"}


def test_hidden_voltages_survive_float32_roundtrip():
    """\uce90\uc2dc\ub294 vt \ub97c float32 \ub85c \uc800\uc7a5\ud55c\ub2e4 -> 0.54 \uac00 0.54000002 \ub85c \ub3cc\uc544\uc628\ub2e4.

    \ud5c8\uc6a9\uc624\ucc28\uac00 float32 \uc815\ubc00\ub3c4\ubcf4\ub2e4 \ube61\uc138\uba74 `hidden_voltages: [0.54]` \uac00 \uc544\ubb34\uac83\ub3c4
    \ubabb \uace0\ub974\uace0 split \uc5d0 hidden \uc774 \ud558\ub098\ub3c4 \uc548 \ub0a8\ub294\ub2e4 (\uc2e4\uc81c\ub85c \uadf8\ub807\uac8c \uae68\uc838 \uc788\uc5c8\ub2e4).
    npz \uc655\ubcf5\uc744 \uadf8\ub300\ub85c \uc7ac\ud604\ud574 \ub2e4\uc2dc\ub294 \uc548 \uae68\uc9c0\uac8c \ubabb\ubc15\ub294\ub2e4.
    """
    from si_model.parsing.keys import corner_label, parse_corner
    from si_model.training.loo import make_split
    lv = {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}
    labels = [corner_label(v, l, "SSPG")
              for v in (0.5, 0.54, 0.6, 0.685) for l in ("rcmax", "cmax")]
    vt64 = np.asarray([parse_corner(c, lv, "SSPG") for c in labels])
    vt = np.asarray(vt64, np.float32)                    # \u2190 \uce90\uc2dc\uac00 \ud558\ub294 \uc77c
    assert float(vt[2, 0]) != 0.54, "float32 \uc655\ubcf5\uc774 \uac12\uc744 \ubc14\uafb8\uc9c0 \uc54a\uc73c\uba74 \uc774 \ud14c\uc2a4\ud2b8\ub294 \ubb34\uc758\ubbf8"
    cfg = {"data": {"ref_corner": "SSPG_0p685V_cmax"},
           "split": {"hidden_voltages": [0.54], "min_seen": 1},
           "base": {"axes": [{"name": "v", "ref": 0.685, "order": 2},
                             {"name": "rc", "ref": 0.0, "order": 1, "levels": lv}]}}
    sp = make_split(labels, vt, cfg)
    assert {labels[i] for i in sp.hidden_idx} == {"SSPG_0p54V_rcmax", "SSPG_0p54V_cmax"}


def test_hidden_levels_hides_whole_column(project):
    """\ucee4\uc2a4\ud140 \ub808\ubca8 \uc774\ub984(rcmin/cmax/rcmax)\uc73c\ub85c\ub3c4 \ub3d9\uc791\ud574\uc57c \ud55c\ub2e4 -- \uc608\uc804\uc5d4 \ub0b4\uc7a5
    Cmin/Cnom/Cmax \ub9cc \ub418\uace0 \ub098\uba38\uc9c0\ub294 float() \ubcc0\ud658 \uc5d0\ub7ec\ub85c \uc8fd\uc5c8\ub2e4."""
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


def test_seen_corners_selects_individual_voltage_level_pairs(project):
    project["temps"][0]["seen_corners"] = [
        [0.5, "cmax"], [0.54, "cmax"], [0.6, "rcmax"], [0.685, "cmax"]]
    cfg = expand(project)[0]["cfg"]
    assert cfg["split"]["min_seen"] == 4
    assert len(cfg["data"]["selected_corners"]) == 6  # seen 4 + target 2
    assert "SSPG_0p5V_rcmax" not in cfg["data"]["selected_corners"]
    assert "SSPG_0p685V_cmax" in cfg["data"]["selected_corners"]


def test_seen_corners_rejects_hidden_overlap(project):
    project["temps"][0]["seen_corners"] = [
        [0.54, "rcmax"], [0.685, "cmax"]]
    with pytest.raises(AssertionError, match="\uacb9\uce5c\ub2e4"):
        expand(project)


def test_holdout_rules_combine(project):
    got = _hidden_labels(project, {"hidden_voltages": [0.54], "hidden_levels": ["rcmin"],
                                   "hidden_corners": [[0.6, "rcmax"]]})
    assert "SSPG_0p685V_rcmin" in got and "SSPG_0p6V_rcmax" in got
    assert "SSPG_0p685V_cmax" not in got


def test_seen_and_hidden_voltages_conflict_is_rejected(project):
    _use_voltage_row_holdout(project)
    project["corners"]["seen_voltages"] = [0.5]
    with pytest.raises(AssertionError, match="\ud558\ub098\ub9cc"):
        expand(project)


def test_anchor_may_not_be_hidden(project):
    project["corners"]["hidden_levels"] = ["cmax"]      # ref_level \uc774 cmax
    with pytest.raises(AssertionError, match="hidden_levels"):
        expand(project)


def test_anchor_must_exist_at_every_temp(project):
    project["corners"]["ref_level"] = "rcmin"           # 125C \uc5d0\ub294 rcmin \uc774 \uc5c6\ub2e4
    with pytest.raises(AssertionError, match="levels"):
        expand(project)


# ---- OLS / \ud30c\uc2f1 \ub178\ube0c\uac00 \uc5d4\uc9c4\uae4c\uc9c0 \uc804\ub2ec\ub418\ub294\uac00 -----------------------------------
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
    assert cfg["train"]["split_seed"] == 7          # \ud2b8\ub808\uc774\ub108\ub294 train \uc5d0\uc11c \uc77d\ub294\ub2e4


def test_select_filters(project):
    models = expand(project)
    assert [m["name"] for m in select(models, design="gpu")] == ["gpu/125", "gpu/m25"]
    assert [m["name"] for m in select(models, temp="125")] == ["cpu/125", "gpu/125"]
    with pytest.raises(AssertionError, match="no model matches"):
        select(models, design="nope")


# ================================================================ 2. \ucf54\ub108 \ud0d0\uc0c9
def _cfg(root, temp, levels):
    return {"data": {"annotated_dir": str(root), "temp": temp,
                     "corner_prefix": "SSPG", "rc_corners": levels,
                     "patterns": {"layout": "flat", "annotated_regex": FLAT_RE}},
            "base": {"axes": [{"name": "v", "ref": 0.685, "order": 2},
                              {"name": "rc", "ref": 0, "order": 2,
                               "levels": {"rcmin": -1, "cmax": 0, "rcmax": 1}}]}}


def test_discovery_filters_by_temp_and_level(tree):
    c125 = discover_annotated(_cfg(tree / "cpu", 125, ["rcmax", "cmax"]))
    assert len(c125) == 8                           # 4V x 2\ub808\ubca8, m25 \ud30c\uc77c\uc740 \ubb34\uc2dc
    cm25 = discover_annotated(_cfg(tree / "cpu", "m25", ["rcmax", "cmax", "rcmin"]))
    assert len(cm25) == 12
    assert set(c125).issubset(set(cm25))            # \uc628\ub3c4\ub294 \ub77c\ubca8\uc5d0 \uc548 \ub4e4\uc5b4\uac10(\ubd84\ub9ac \ucc28\uc6d0)


def test_discovery_label_and_sort(tree):
    corners, ann, xt = discover(_cfg(tree / "cpu", 125, ["rcmax", "cmax"]))
    assert corners[0] == "SSPG_0p5V_cmax"           # 0p5000 -> \uc815\uaddc\ud654 0p5
    assert corners[-1] == "SSPG_0p685V_rcmax"       # (\uc804\uc555, \ub808\ubca8\uac12) \uc21c \uc815\ub82c
    assert xt is None                               # crosstalk_dir \uc5c6\uc73c\uba74 SI \uc5c6\uc774
    assert os.path.basename(ann["SSPG_0p5V_cmax"]) == "report.sspg_0p5000_125c_cmax.rpt"


@pytest.mark.parametrize("fname,temp,want", [
    # \uae30\uc900 \ud615\uc2dd
    ("report.sspg_0p5000_125c_rcmax.rpt", "125", (0.5, "rcmax")),
    # \uc628\ub3c4 \ub4a4 c \uc720\ubb34
    ("report.sspg_0p5000_125_rcmax.rpt", "125", (0.5, "rcmax")),
    # \ud544\ub4dc \uc21c\uc11c\uac00 \ubc14\ub00c\uc5b4\ub3c4
    ("report.sspg_0p5000_rcmax_125c.rpt", "125", (0.5, "rcmax")),
    ("RCMAX.125.SSPG.0p5000.rpt", "125", (0.5, "rcmax")),
    # \ub300\uc18c\ubb38\uc790
    ("report.SSPG_0P5000_125C_RCMAX.rpt", "125", (0.5, "rcmax")),
    # \uc804\uc555 \ud45c\uae30: 0p5400 / 0.5400 / v0p54
    ("report.sspg_0.5400_125c_rcmax.rpt", "125", (0.54, "rcmax")),
    ("ibex_v0p54_rcmax_125.timing.rpt", "125", (0.54, "rcmax")),
    # \uad6c\ubd84\uc790\uac00 \ud558\uc774\ud508 -> \uc55e\uc758 '-' \ub294 \uc74c\uc218\ubd80\ud638\uac00 \uc544\ub2c8\ub2e4
    ("sspg-0p5000-125c-rcmax.rpt", "125", (0.5, "rcmax")),
    # \uc74c\uc218 \uc628\ub3c4: m25 / M25 / -25
    ("report.sspg_0p5000_m25c_rcmin.rpt", "m25", (0.5, "rcmin")),
    ("report.SSPG_0P5000_M25_RCMIN.rpt", "m25", (0.5, "rcmin")),
    ("report.sspg_0p5000_-25c_rcmin.rpt", "m25", (0.5, "rcmin")),
    # cmax \uac00 rcmax \uc548\uc5d0\uc11c \uc798\ubabb \uc7a1\ud788\uba74 \uc548 \ub41c\ub2e4
    ("report.sspg_0p6850_125c_cmax.rpt", "125", (0.685, "cmax")),
    # --- \uac78\ub7ec\uc838\uc57c \ud558\ub294 \uac83\ub4e4 ---
    ("report.sspg_0p5000_125c_rcmax.rpt", "m25", None),    # \ub2e4\ub978 \uc628\ub3c4
    ("report.sspg_0p5000_m25c_rcmax.rpt", "125", None),    # \ub2e4\ub978 \uc628\ub3c4(\ubc18\ub300)
    ("report.sspg_0p5000_125c_cworst.rpt", "125", None),   # \ubaa8\ub974\ub294 \ub808\ubca8
    ("report.sspg_125c_rcmax.rpt", "125", None),           # \uc804\uc555 \uc5c6\uc74c
    ("readme.txt", "125", None),                           # \ubb34\uad00\ud55c \ud30c\uc77c
])
def test_filename_matching_is_order_and_case_free(fname, temp, want):
    """\ud30c\uc77c\uba85 \ud615\uc2dd\uc740 \ubca4\ub354\ub9c8\ub2e4 \ub2e4\ub974\ub2e4: \uc21c\uc11c, \ub300\uc18c\ubb38\uc790, \uad6c\ubd84\uc790, \uc628\ub3c4\uc758 c \uc720\ubb34,
    \uc804\uc555 \ud45c\uae30(0p54 / 0.54)\uac00 \uc81c\uac01\uac01\uc774\uc5b4\ub3c4 \uac19\uc740 \ucf54\ub108\ub85c \uc77d\ud600\uc57c \ud55c\ub2e4.

    \uc804\uc555\uc740 \uc18c\uc218\uc810 \ud45c\uc2dc\uac00 \ubc18\ub4dc\uc2dc \uc788\uc5b4\uc57c \ud558\uace0 \uc628\ub3c4\ub294 \uc815\uc218\ub77c\ub294 \uc810\uc774 \ub458\uc744 \uac00\ub974\ub294
    \uc720\uc77c\ud55c \uadfc\uac70\uc774\ubbc0\ub85c, \uadf8 \uacbd\uacc4(\u2018.125.\u2019 \ub97c 0.125 \ub85c \uc77d\uc9c0 \uc54a\uae30)\uae4c\uc9c0 \uc5ec\uae30\uc11c \ubabb\ubc15\ub294\ub2e4.
    """
    from si_model.parsing.discovery import _match_tokens
    got = _match_tokens(fname, {"data": {}}, ["rcmax", "cmax", "rcmin"], "SSPG", temp)
    if want is None:
        assert got is None
    else:
        assert got is not None, "\ub9e4\uce6d \uc2e4\ud328"
        assert abs(got[0] - want[0]) < 1e-9 and got[1] == want[1]


def test_same_folder_annotated_and_crosstalk(tmp_path):
    """`pt_si_re` \ubc30\uce58: \ucf54\ub108 \ud3f4\ub354 \ud558\ub098\uc5d0 annotated \uc640 crosstalk \uc774 \ud568\uaed8 \uc788\ub2e4.

    \ub458 \ub2e4 \ucf54\ub108 \ud1a0\ud070\uc744 \uac16\uace0 \uc788\uc5b4 \uadf8\ub300\ub85c\ub294 \uac19\uc740 \ucf54\ub108\uc5d0 \ub450 \ud30c\uc77c\uc774 \ub9e4\uce6d\ub41c\ub2e4.
    (a) \uadf8 \uc0c1\ud669\uc774 '\uc774\ub807\uac8c \uace0\uccd0\ub77c' \ub294 \uc5d0\ub7ec\ub85c \uc7a1\ud788\uace0,
    (b) files.*_contains \ub97c \uc8fc\uba74 \uc815\uc0c1 \ub3d9\uc791\ud558\ub294\uc9c0 -- \ub458 \ub2e4 \ubabb\ubc15\ub294\ub2e4.
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
            (d / "corner_info.tcl").touch()          # \uc911\uac04 \ud30c\uc77c\uc740 \ubb34\uc2dc\ub3fc\uc57c

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

    with pytest.raises(AssertionError, match="\ud55c \ud3f4\ub354\uc5d0"):
        discover_annotated(cfg(False))

    corners, ann, xt = discover(cfg(True))
    assert len(corners) == 4 and xt is not None and len(xt) == 4
    assert all(a.endswith("_fixed_annotated.txt") for a in ann.values())
    assert all(x.endswith(".by_path.rpt") for x in xt.values())


def test_crosstalk_subdir_inside_design_is_excluded(tmp_path):
    """\ud06c\ub85c\uc2a4\ud1a0\ud06c\uac00 \ud68c\ub85c\ud3f4\ub354 '\ud558\uc704' \uc5d0 \uc788\uc73c\uba74 annotated \uc7ac\uadc0 \ud0d0\uc0c9\uc5d0\uc11c \ube60\uc838\uc57c \ud55c\ub2e4."""
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
    assert all("xtalk" not in a for a in ann.values()), "annotated \uac00 xtalk \uc744 \uc8fc\uc6e0\ub2e4"


def test_discovery_wrong_prefix_is_loud(tree):
    cfg = _cfg(tree / "cpu", 125, ["rcmax", "cmax"])
    cfg["data"]["corner_prefix"] = "FFPG"
    with pytest.raises(AssertionError, match="no annotated corners discovered"):
        discover_annotated(cfg)


def test_levels_layout_still_supported(tmp_path):
    """\ub808\ubca8 \ud558\uc704\ud3f4\ub354 \ubc30\uce58(<dir>/<LEVEL>/<\uc804\uc555\ub2f9 1\ud30c\uc77c>)\ub3c4 \uadf8\ub300\ub85c \ub41c\ub2e4."""
    root = tmp_path / "ann"
    for lv in ("Cmin", "Cnom", "Cmax"):
        (root / lv).mkdir(parents=True)
        for v in ("0p6", "0p8"):
            (root / lv / f"saed14rvt_tt{v}vm40c_x_fixed_annotated.txt").touch()
    cfg = {"data": {"annotated_dir": str(root), "temp": "m40",
                    "rc_corners": ["Cmin", "Cnom", "Cmax"]},
           "base": {"axes": [{"name": "v", "ref": 0.8, "order": 3},
                             {"name": "rc", "ref": 0.0, "order": 2}]}}
    got = discover_annotated(cfg)      # axes \uc5d0 levels: \uc5c6\uc74c -> \ub0b4\uc7a5 RC \ub9f5 \ud3f4\ubc31
    assert len(got) == 6 and "TT_0p8V_Cnom" in got


# ============================ 2.5 end-to-end: \ub9ac\ud3ec\ud2b8 -> npz -> base (torch \ubd88\ud544\uc694)
def _fake_report(v: float, lvv: float, n_paths: int = 12) -> str:
    """\ud30c\uc11c \ud615\uc2dd\uc5d0 \ub9de\ub294 \ucd5c\uc18c\ud55c\uc758 \uc9c4\uc9dc \ub9ac\ud3ec\ud2b8. \uc804\uc555/BEOL \uc758\uc874\uc131\uc744 \ubb3c\ub9ac\uc801\uc73c\ub85c
    \uadf8\ub7f4\ub4ef\ud558\uac8c(\ube44\uc120\ud615) \ub123\uc5b4, base \ub2e4\ud56d\uc2dd\uc774 \uc2e4\uc81c\ub85c \ub9de\ucdb0\uc57c \ud560 \uac8c \uc788\uac8c \ud55c\ub2e4."""
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
    """\ubc30\ud3ec \ubc30\uce58 \uadf8\ub300\ub85c: <root>/{si_corner_model, boomcore} + \ud30c\uc2f1 \uac00\ub2a5\ud55c \ub9ac\ud3ec\ud2b8."""
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
    """\ub9ac\ud3ec\ud2b8 -> dataset.npz -> seen/hidden \ubd84\ud560 -> OLS base \uae4c\uc9c0 \uc804 \uad6c\uac04.

    torch \uc5c6\uc774 \ub3c4\ub294 \uad6c\uac04 \uc804\uccb4\ub77c, \ud68c\uc0ac\uc5d0\uc11c \ud559\uc2b5 \uc804\uc5d0 \ud655\uc778\ud560 \uc218 \uc788\ub294 \ubc94\uc704\uc640 \uac19\ub2e4.
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.training.loo import build_design, fit_field, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)                       # cache \ub294 \uc5ec\uae30 \uc544\ub798\ub85c
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]                     # \ud53d\uc2a4\ucc98\uc758 \ud68c\ub85c \uc774\ub984
    p["files"]["crosstalk_subdir"] = None           # \uc774 \ud53d\uc2a4\ucc98\ub294 SI \uc5c6\uc774 \uac80\uc99d
    models = select(expand(p), design="boomcore")
    assert [m["name"] for m in models] == ["boomcore/125", "boomcore/m25"]

    for m, want_c in zip(models, (8, 12)):            # 4V x 2\ub808\ubca8, 4V x 3\ub808\ubca8
        n_hidden = len(m["cfg"]["split"]["hidden_corners"]) or want_c // 4
        build(m["cfg"])
        ds = dict(np.load(m["cfg"]["data"]["cache"]))
        assert ds["slack"].shape == (12, want_c), "\uacbd\ub85c 12\uac1c x \ucf54\ub108 want_c"
        assert np.isfinite(ds["slack"]).all()
        assert (ds["si_label"] == 0).all()            # \ud06c\ub85c\uc2a4\ud1a0\ud06c \uc5c6\uc74c -> 0
        assert ds["node_mask"].any() and len(ds["fam_vocab"]) > 1

        split = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
        assert split.hidden.sum() == n_hidden
        assert not split.hidden[split.ref_ci]

        # \uc2e4\uc81c \uacbd\ub85c\uc640 \ub3d9\uc77c\ud558\uac8c y \ub97c \ub118\uae34\ub2e4 -> \uae30\uc800\uac00 seen-LOO \ub85c \uc120\ud0dd\ub41c\ub2e4
        phi, coords, exps, _ = build_design(m["cfg"], split, y=ds["slack"])
        loo, _ = fit_field(ds["slack"], phi, split, coords, m["cfg"])
        assert np.isfinite(loo).all()
        # \ud569\uc131 \ub370\uc774\ud130\ub294 \ub9e4\ub044\ub7ec\uc6b0\ubbc0\ub85c base \uac00 hidden \ucf54\ub108\ub97c \uc798 \ub9de\ucdb0\uc57c \ud55c\ub2e4
        hid = split.hidden_idx
        mae_ps = np.abs(loo[:, hid] - ds["slack"][:, hid]).mean() * 1000
        assert mae_ps < 20, f"hidden base MAE \uac00 \ub108\ubb34 \ud06c\ub2e4: {mae_ps:.2f} ps"
        assert phi.shape[1] < split.seen.sum(), (
            "\uc120\ud0dd\ub41c \uae30\uc800\ub294 \uc790\uc720\ub3c4\ub97c \ucd5c\uc18c 1 \ub0a8\uaca8\uc57c \ud55c\ub2e4 (seen-LOO \uac00 \uc758\ubbf8\ub97c \uac00\uc9c0\ub824\uba74)")


def test_missing_unselected_corner_report_does_not_drop_paths(real_tree, tmp_path,
                                                                monkeypatch):
    """Absent whole-corner reports may be excluded, while selected reports are required."""
    from si_model.parsing.build_dataset import build
    from si_model.training.loo import make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]
    p["files"]["crosstalk_subdir"] = None
    p["temps"][0]["seen_corners"] = [
        [0.5, "cmax"], [0.54, "cmax"], [0.6, "rcmax"], [0.685, "cmax"]]
    m = select(expand(p), design="boomcore", temp="125")[0]
    reports = real_tree / "boomcore" / "setup"
    (reports / "report.sspg_0p5000_125c_rcmax.rpt").unlink()
    (reports / "report.sspg_0p6850_125c_rcmax.rpt").unlink()

    build(m["cfg"])
    ds = dict(np.load(m["cfg"]["data"]["cache"]))
    assert ds["slack"].shape == (12, 6)  # no paths lost to absent excluded reports
    sp = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
    assert sp.seen.sum() == 4 and sp.hidden.sum() == 2

    (reports / "report.sspg_0p5400_125c_cmax.rpt").unlink()
    with pytest.raises(AssertionError, match="selected corners lack reports"):
        build(m["cfg"])


def test_hidden_labels_never_reach_the_base(real_tree, tmp_path, monkeypatch):
    """hidden \ucf54\ub108\uc758 \ub77c\ubca8\uc740 \ud559\uc2b5\uc5d0 \uc808\ub300 \ub4e4\uc5b4\uac00\uba74 \uc548 \ub41c\ub2e4.

    \uc99d\uba85 \ubc29\uc2dd: hidden \uc5f4\uc758 \ub77c\ubca8\ub9cc \ub09c\uc218\ub85c \uc624\uc5fc\uc2dc\ud0a4\uace0 base \ub97c \ub2e4\uc2dc \uacc4\uc0b0\ud55c\ub2e4.
    hidden \ub77c\ubca8\uc774 \uc5b4\ub514\ub85c\ub4e0 \uc0c8\uba74 seen \ucabd \uc0b0\ucd9c\ubb3c\uc774 \ub2ec\ub77c\uc9c4\ub2e4. \uc5ec\uae30\uc11c \uac80\uc0ac\ud558\ub294
    base/resid \ub294 \uc2e0\uacbd\ub9dd\uc758 \ud559\uc2b5 \ud0c0\uae43\uc774\uc790 \ud1a0\ud070 \uc785\ub825\uc774\ubbc0\ub85c, \uc774\uac8c \uc548 \ubcc0\ud558\uba74
    \ub204\uc218 \uacbd\ub85c\uac00 \uc5c6\ub2e4\ub294 \ub73b\uc774\ub2e4.
    (torch \ub2e8\uae4c\uc9c0\uc758 \uac80\uc99d -- \uac00\uc911\uce58\u00b7\uc608\uce21\uc774 \ube44\ud2b8 \ub2e8\uc704\ub85c \ub3d9\uc77c -- \uc740 \ubcc4\ub3c4\ub85c \ud655\uc778\ud568)
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.training.loo import compute_base, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]                     # \ud53d\uc2a4\ucc98\uc758 \ud68c\ub85c \uc774\ub984
    p["files"]["crosstalk_subdir"] = None           # \uc774 \ud53d\uc2a4\ucc98\ub294 SI \uc5c6\uc774 \uac80\uc99d
    m = select(expand(p), design="boomcore", temp="m25")[0]
    build(m["cfg"])
    ds = dict(np.load(m["cfg"]["data"]["cache"]))

    split = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
    S, H = split.seen_idx, split.hidden_idx
    assert len(H) and len(S), "\uc774 \ud14c\uc2a4\ud2b8\ub294 hidden/seen \uc774 \ub458 \ub2e4 \uc788\uc5b4\uc57c \uc758\ubbf8\uac00 \uc788\ub2e4"

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
    # seen \uc740 \ud559\uc2b5 \ud0c0\uae43 / \ud1a0\ud070, hidden \uc740 \uc608\uce21 \uae30\uc900\uc120 -- \ub458 \ub2e4 hidden \ub77c\ubca8\uacfc \ubb34\uad00\ud574\uc57c
    assert np.array_equal(a.base_hat[:, S], b.base_hat[:, S])
    assert np.array_equal(a.base_hat[:, H], b.base_hat[:, H])
    assert np.array_equal(a.resid[:, S], b.resid[:, S])
    assert np.array_equal(a.si_smooth_hat[:, S], b.si_smooth_hat[:, S])

    # \ud1a0\ud070 \uc815\uaddc\ud654 \ud1b5\uacc4\ub3c4 seen \uc5d0\uc11c\ub9cc \ub098\uc640\uc57c \ud55c\ub2e4
    def stats(d, base):
        raw = np.stack([d["slack"], d["si_label"], d["arrival"], d["required"],
                        d["launch_clk"], d["capture_clk"], d["lib_check_time"],
                        base.resid], -1)
        return (np.nanmean(raw[:, S], axis=(0, 1)), np.nanstd(raw[:, S], axis=(0, 1)))
    (mu_a, sd_a), (mu_b, sd_b) = stats(ds, a), stats(poisoned, b)
    assert np.array_equal(mu_a, mu_b) and np.array_equal(sd_a, sd_b)


# ========================================================= 3. \uc5d4\uc9c4 \uc218\ud559 / \ud5ec\ud37c
def _basis(axes, cross_max_degree=3, cross_terms=True):
    return {"base": {"axes": axes, "cross_terms": cross_terms,
                     "cross_max_degree": cross_max_degree}}


def test_basis_generation():
    cfg = _basis([{"name": "v", "ref": 0.8, "order": 3},
                  {"name": "rc", "ref": 0.0, "order": 2}])
    _, names, _ = expand_terms(cfg)
    assert set(names) == {"dv", "dv2", "dv3", "drc", "drc2", "dvdrc", "dv2drc", "dvdrc2"}


def test_basis_drops_rank_deficient_terms():
    # \uc804\uc555 seen 4\ub808\ubca8 -> dv4 \ubd88\uac00, BEOL 3\ub808\ubca8 -> drc3 \ubd88\uac00
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
    """grid=[None] \uc774\uba74 adaptive base \uac00 \uc804\uc5ed closed-form LOO \uc640 \uc815\ud655\ud788 \uac19\ub2e4."""
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
    # _#idx \ub294 \ub9ac\ud3ec\ud2b8\ubcc4 \uc77c\ub828\ubc88\ud638\uc77c \ubfd0 \uacbd\ub85c \uc2dd\ubcc4\uc790\uac00 \uc544\ub2c8\ub2e4 -- \uc548 \ub5bc\uba74 \ucf54\ub108 \uac04 join \ubd95\uad34
    assert norm_path_key("A->B_#282") == "A->B"
    assert norm_path_key("A->B#5") == "A->B"
    assert norm_path_key("A->B") == "A->B"


def test_corner_label_roundtrip():
    lv = {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}
    assert corner_label(0.685, "cmax", prefix="SSPG") == "SSPG_0p685V_cmax"
    assert parse_corner("SSPG_0p685V_cmax", lv, prefix="SSPG") == (0.685, 0.0)
    assert parse_corner("SSPG_0p5V_rcmax", lv, prefix="SSPG") == (0.5, 1.0)
    # \uc628\ub3c4\ud615 \ub77c\ubca8(2\ubc88\uc9f8 \ucd95\uc774 \uc628\ub3c4\uc778 \ub370\uc774\ud130)\ub3c4 \uc9c0\uc6d0
    assert parse_corner("SSPG_0p9V_m25C", prefix="SSPG") == (0.9, -25.0)


def test_filename_voltage_and_xt_parsing():
    assert abs(parse_voltage_from_annotated("saed14rvt_tt0p605vm40c_x.txt") - 0.605) < 1e-9
    assert parse_xt_name("SSPG_0p55V_125C.foo.by_path.rpt", prefix="SSPG") == (0.55, "125")


def test_cell_taxonomy_defaults_are_safe():
    assert cell_family("SAEDRVT14_ND2_CDC_0P5") == "NAND"
    assert cell_family("SAEDRVT14_FDP_V2LP_2") == "DFF"
    assert cell_drive("SAEDRVT14_BUF_20") == 20.0
    assert cell_drive("SAEDRVT14_NR3B_1P5") == 1.5
    # \ubaa8\ub974\ub294 \ub77c\uc774\ube0c\ub7ec\ub9ac\uc5ec\ub3c4 \uc5d0\ub7ec\uac00 \uc544\ub2c8\ub77c <unk> + drive 1.0 \uc73c\ub85c \ud559\uc2b5\ub41c\ub2e4
    assert cell_family("SEC9T_WHATEVER_X4") == "<unk>"
    assert cell_drive("SEC9T_WHATEVER") == 1.0
