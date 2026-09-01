"""테스트는 이 파일 하나. 데이터 없이 numpy 만으로 돈다.

    python -m pytest tests/ -q

세 덩어리:
  1. config.yaml 확장   -- designs x temps 가 모델 매트릭스로 펼쳐지는가
  2. 코너 탐색          -- 파일명 -> 코너 라벨, 온도/레벨 필터
  3. 엔진 수학/헬퍼     -- 다항식 기저 생성, OLS base, 경로키/셀 파싱
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


# =============================================================== 1. config 확장
@pytest.fixture
def tree(tmp_path):
    """회사 배치: <root>/<회로>/ 밑에 코너가 파일명에 다 들어있는 리포트들."""
    for design in ("cpu", "gpu"):
        d = tmp_path / design / "setup"          # 배포 배치: <회로>/setup/
        d.mkdir(parents=True)
        for v in ("0p5000", "0p5400", "0p6000", "0p6850"):
            for lv in ("rcmax", "cmax"):
                (d / f"report.sspg_{v}_125c_{lv}.rpt").touch()
            for lv in ("rcmax", "cmax", "rcmin"):
                (d / f"report.sspg_{v}_m25c_{lv}.rpt").touch()
    return tmp_path


@pytest.fixture
def project(tree):
    """실제 config.yaml 을 읽어 root 만 fixture 트리로 바꾼다 -- 배포되는 그 파일이
    스키마상 유효한지까지 같이 검증된다."""
    with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
        p = yaml.safe_load(f)
    p["root"] = str(tree)
    p["designs"] = "auto"
    return p


def _clear_temp_holdout(p):
    """temps[] 의 온도별 홀드아웃을 지워 전역 설정만 보게 한다."""
    p["temps"] = [{k: v for k, v in t.items() if k not in
                   ("hidden_corners", "hidden_per_voltage", "hidden_voltages",
                    "seen_voltages", "hidden_levels")} for t in p["temps"]]
    return p


def _use_voltage_row_holdout(p):
    """배포 config 는 온도별 hidden_corners 를 쓴다. 전압 행 홀드아웃을 전제로 한
    테스트는 그 설정으로 되돌려 놓고 검사한다."""
    _clear_temp_holdout(p)
    p["corners"] = dict(p["corners"], hidden_voltages=[0.54], hidden_corners=[],
                        hidden_per_voltage=0)
    return p


def test_shipped_config_yaml_parses():
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["corners"]["process"] and p["temps"] and p["files"]["annotated_regex"]
    assert os.path.isabs(p["root"])


def test_shipped_config_defaults_to_the_deployed_layout():
    """배포 배치는 <root>/{si_corner_model, 회로1, 회로2, 회로3} 이다.
    그 경우 root/designs 를 손대지 않아도 맞아야 한다."""
    with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
        raw = yaml.safe_load(f)
    assert raw["root"] == "auto", "기본 root 는 auto 여야 한다 (repo 의 부모 = 회로들이 있는 곳)"
    # designs 는 명시 목록이어야 한다: root 에 회로가 아닌 폴더(pr_si, spice)가
    # 같이 있어서 auto 로 두면 그것들까지 회로로 잡힌다.
    assert isinstance(raw["designs"], list) and raw["designs"]
    # auto 는 이 checkout 의 부모 디렉토리로 풀린다
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    assert p["root"] == os.path.dirname(REPO_ROOT)


def test_repo_itself_is_not_mistaken_for_a_design(tmp_path):
    """root 밑에 이 repo 가 같이 있어도 회로로 잡히면 안 된다."""
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
    assert m["cfg"]["data"]["rc_corners"] == ["rcmax", "cmax"]        # 125C 는 2레벨
    assert models[1]["cfg"]["data"]["rc_corners"] == ["rcmax", "cmax", "rcmin"]
    assert m["cfg"]["data"]["ref_corner"] == "SSPG_0p685V_cmax"
    assert m["cfg"]["data"]["cache"].endswith(os.path.join("cpu", "125", "dataset.npz"))
    assert m["cfg"]["train"]["out_dir"].endswith(os.path.join("cpu", "125"))


def test_expand_auto_order_matches_available_levels(project):
    _use_voltage_row_holdout(project)
    by = {m["name"]: m["cfg"]["base"]["axes"] for m in expand(project)}
    # seen V = 3 (0.54 숨김) -> v order 2 ; 125C 는 레벨 2개 -> level order 1
    assert by["cpu/125"][0]["order"] == 2 and by["cpu/125"][1]["order"] == 1
    # m25C 는 레벨 3개 -> level order 2
    assert by["cpu/m25"][1]["order"] == 2


def test_expand_min_seen_is_full_grid(project):
    _use_voltage_row_holdout(project)
    by = {m["name"]: m["cfg"]["split"]["min_seen"] for m in expand(project)}
    assert by["cpu/125"] == 3 * 2      # seen V 3개 x 레벨 2개
    assert by["cpu/m25"] == 3 * 3      # 리포트가 빠지면 여기서 에러가 난다


def test_expand_si_on_when_crosstalk_declared(project):
    cfg = expand(project)[0]["cfg"]
    assert cfg["data"]["crosstalk_dir"].endswith(os.path.join("setup", "xtalk"))
    assert "crosstalk_regex" in cfg["data"]["patterns"]


def test_bundle_packs_every_temperature_into_one_file(project, tmp_path):
    """회로 하나 = 파일 하나. 온도별로 갈라지면 안 된다.

    torch 가 없는 환경(회사에서 학습 전 점검)에서는 건너뛴다."""
    torch = pytest.importorskip("torch")
    from si_model.run import bundle_path, stage_bundle

    models = expand(project)
    for m in models:                       # 학습된 것처럼 가짜 체크포인트를 깔아둔다
        d = m["cfg"]["train"]["out_dir"] = str(tmp_path / m["design"] / str(m["temp"]))
        os.makedirs(d, exist_ok=True)
        torch.save({"model": {"w": torch.zeros(1)}, "enc": {"w": torch.zeros(1)},
                    "cfg": m["cfg"], "epoch": 7}, os.path.join(d, "best.pt"))

    stage_bundle(models)

    for design in {m["design"] for m in models}:
        ms = [m for m in models if m["design"] == design]
        b = torch.load(bundle_path(ms[0]), map_location="cpu")
        assert b["design"] == design
        # 그 회로의 모든 온도가 한 파일 안에 있어야 한다
        assert set(b["temps"]) == {str(m["temp"]) for m in ms}
        assert all("model" in v and "enc" in v for v in b["temps"].values())


def test_bundle_skips_untrained_temperatures_instead_of_failing(project, tmp_path):
    """온도 하나만 학습해도 bundle 은 그 하나로 만들어져야 한다 -- 나머지를
    기다리느라 통째로 실패하면 부분 재학습을 할 수가 없다."""
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
    """요약은 '모델별' 이 아니라 '코너별' 이어야 한다.

    모델(회로x온도)은 내부 분할일 뿐이고, 넘길 때 궁금한 건 "이 코너가 얼마나
    잘 맞았나" 다. 정답이 없는 query 코너는 경로 수만 세고 오차는 비운다."""
    from si_model.run import _corner_table

    fp = tmp_path / "predictions_hidden.csv"
    fp.write_text(
        "design,temp,path_key,corner,truth_ps,model_ps,model_err_ps\n"
        "cpu,125,A,SSPG_0p54V_rcmax,10.0,12.0,2.0\n"
        "cpu,125,B,SSPG_0p54V_rcmax,10.0,6.0,-4.0\n"
        "cpu,m25,A,SSPG_0p5V_cmax,10.0,11.0,1.0\n"
        "cpu,m25,A,SSPG_0p57V_cmax,,11.0,\n")          # query 코너 (정답 없음)

    rows = {(r["temp"], r["corner"]): r for r in _corner_table(str(fp))}
    assert len(rows) == 3
    assert rows[("125", "SSPG_0p54V_rcmax")]["mae_ps"] == 3.0      # (2+4)/2
    assert rows[("125", "SSPG_0p54V_rcmax")]["worst_ps"] == 4.0
    assert rows[("125", "SSPG_0p54V_rcmax")]["n_paths"] == 2
    # query 코너: 경로는 세지만 오차는 없다 -- 0.0 으로 세면 평균이 좋아 보인다
    q = rows[("m25", "SSPG_0p57V_cmax")]
    assert q["n_paths"] == 1 and q["mae_ps"] is None and q["worst_ps"] is None


def test_merge_flags_a_summary_older_than_its_checkpoint(project, tmp_path, capsys):
    """학습을 중간에 끊으면 best.pt 만 갱신되고 summary.json 은 이전 실행 것이
    남는다. 그게 조용히 by_model 로 실려 나가면 안 된다."""
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
    open(os.path.join(d, "best.pt"), "w").close()          # summary 보다 나중
    os.utime(os.path.join(d, "summary.json"), (1, 1))

    project["out"] = {"runs": str(tmp_path / "out"), "cache": str(tmp_path / "c")}
    stage_merge(models, project, "hidden")
    assert "오래됨" in capsys.readouterr().out


def test_adaptive_downgrades_to_plain_on_a_grid_too_small_for_it(project):
    """adaptive 는 이웃 adaptive_k 개로 대역폭을 고른다. seen 코너가 그보다 많지
    않으면 이웃 = 전체가 되어 후보들이 같은 데이터로 채점되고, 승자는 잡음이다.

    실측(14nm, 125C: seen 6 / adaptive_k 6): adaptive 3.151 ps vs plain 2.148 ps.
    코너 수만 보고 정하므로 라벨을 읽기 전에 결정된다."""
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
    # 명시적으로 고른 모드는 건드리지 않는다
    cfg["base"]["weighting"] = "plain"
    assert _effective_mode(cfg, split_with(10)) == "plain"


def test_mode_switches_every_path_at_once(project):
    """`mode` 한 줄이 읽을 폴더와 쓸 폴더를 전부 갈라야 한다.

    예전에는 files.subdir / files.crosstalk_subdir / out.cache / out.runs 를 각각
    고쳐야 했고, subdir 만 hold 로 바꾸고 out 을 잊으면 hold 결과가 setup 캐시를
    조용히 덮어썼다. 넷이 함께 움직이는지 여기서 못 박는다."""
    project["mode"] = "hold"
    m = expand(project)[0]
    d = m["cfg"]["data"]
    assert d["annotated_dir"].endswith(os.sep + "hold")
    assert d["crosstalk_dir"].endswith(os.path.join("hold", "xtalk"))
    assert d["cache"].startswith(os.path.join("cache", "hold") + os.sep)
    assert m["cfg"]["train"]["out_dir"].startswith(os.path.join("runs", "hold") + os.sep)


def test_mode_does_not_override_an_explicit_subdir(project):
    """폴더명이 setup/hold 가 아닌 배치도 있어야 한다 -- auto 가 아닌 값은 그대로."""
    project["mode"] = "hold"
    project["files"]["subdir"] = "reports"
    d = expand(project)[0]["cfg"]["data"]
    assert d["annotated_dir"].endswith(os.sep + "reports")
    assert d["cache"].startswith(os.path.join("cache", "hold") + os.sep)


def test_expand_si_off_when_crosstalk_subdir_is_null(project):
    """위치를 모를 땐 null 로 두고 SI 없이 먼저 돌릴 수 있어야 한다."""
    project["files"]["crosstalk_subdir"] = None
    assert "crosstalk_dir" not in expand(project)[0]["cfg"]["data"]


def test_expand_rejects_bad_anchor(project):
    _use_voltage_row_holdout(project)
    project["corners"]["ref_voltage"] = 0.54        # 숨긴 전압
    with pytest.raises(AssertionError, match="ref_voltage"):
        expand(project)
    project["corners"]["ref_voltage"] = 0.685
    project["corners"]["ref_level"] = "nope"
    with pytest.raises(AssertionError, match="ref_level"):
        expand(project)


# ---- 회로마다 다른 설정 ------------------------------------------------------
def test_all_designs_share_settings_by_default(project):
    """기본은 '회로 3개, 코너도 홀드아웃도 전부 동일'. 회로를 늘려도 설정은 하나."""
    models = expand(project)
    by_design = {}
    for m in models:
        by_design.setdefault(m["design"], {})[m["temp"]] = m["cfg"]
    assert set(by_design) == {"cpu", "gpu"}
    a, b = by_design["cpu"], by_design["gpu"]
    for tag in ("125", "m25"):
        assert a[tag]["split"] == b[tag]["split"], f"{tag}: 회로별 홀드아웃이 달라졌다"
        assert a[tag]["base"] == b[tag]["base"]
        assert a[tag]["data"]["rc_corners"] == b[tag]["data"]["rc_corners"]
    # 온도끼리는 달라야 한다 (레벨 수가 다르므로)
    assert a["125"]["data"]["rc_corners"] != a["m25"]["data"]["rc_corners"]


def test_designs_mapping_gives_per_circuit_overrides(project):
    """`designs:` 를 매핑으로 쓰면 한 회로만 다르게 줄 수 있다 -- config 를
    회로별로 복사하지 않고 한 파일에서."""
    project["designs"] = {
        "cpu": {},                                        # 전역 그대로
        "gpu": {"corners": {"voltages": [0.5, 0.6, 0.685]},
                "files": {"subdir": "reports"}},
    }
    by = {m["name"]: m["cfg"] for m in expand(project)}
    assert set(by) == {"cpu/125", "cpu/m25", "gpu/125", "gpu/m25"}
    # cpu 는 전압 4개, gpu 는 3개 -> 코너 수(min_seen)가 갈린다
    assert by["cpu/125"]["split"]["min_seen"] == 4 * 2 - 2
    assert by["gpu/125"]["split"]["min_seen"] == 3 * 2 - 2
    # override 하지 않은 키는 전역을 그대로 물려받는다
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
    assert "gpu/m25" not in by, "override 한 temps 목록이 그대로 쓰인다(125 하나뿐)"


# ---- 온도마다 다른 홀드아웃 --------------------------------------------------
def test_holdout_can_differ_per_temperature(project):
    """125C 는 레벨이 2개, m25C 는 3개다. 그래서 '이 코너를 숨겨라' 를 전역 목록
    하나로는 쓸 수 없고, temps[] 안에서 온도별로 적을 수 있어야 한다."""
    project["corners"]["hidden_voltages"] = []
    project["temps"][0]["hidden_corners"] = [[0.5, "rcmax"], [0.6, "cmax"]]
    project["temps"][1]["hidden_corners"] = [[0.54, "rcmin"], [0.685, "rcmax"]]
    by = {m["temp"]: m["cfg"]["split"] for m in expand(project) if m["design"] == "cpu"}
    assert by["125"]["hidden_corners"] == [[0.5, "rcmax"], [0.6, "cmax"]]
    assert by["m25"]["hidden_corners"] == [[0.54, "rcmin"], [0.685, "rcmax"]]
    # min_seen 도 온도별 홀드아웃을 반영해야 한다 (4V x 2레벨 - 2 = 6)
    assert by["125"]["min_seen"] == 4 * 2 - 2
    assert by["m25"]["min_seen"] == 4 * 3 - 2


def test_holdout_level_must_exist_at_that_temperature(project):
    """125C 에 없는 rcmin 을 125C 홀드아웃에 적으면 조용히 무시되지 않고 에러."""
    project["corners"]["hidden_voltages"] = []
    project["temps"][0]["hidden_corners"] = [[0.5, "rcmin"]]      # 125C 엔 rcmin 없음
    with pytest.raises(AssertionError, match="hidden_corners"):
        expand(project)


def test_hidden_per_voltage_spreads_one_corner_per_voltage(project):
    """전압 행을 통째로 빼는 대신, 전압마다 한 칸씩 흩어서 숨긴다."""
    _clear_temp_holdout(project)
    project["corners"]["hidden_voltages"] = []
    project["corners"]["hidden_per_voltage"] = 1
    by = {m["temp"]: m["cfg"]["split"] for m in expand(project) if m["design"] == "cpu"}
    for tag, n_lv in (("125", 2), ("m25", 3)):
        hc = by[tag]["hidden_corners"]
        vs = [v for v, _ in hc]
        assert len(hc) == 4, f"{tag}: 전압 4개 -> 4칸"
        assert sorted(vs) == [0.5, 0.54, 0.6, 0.685], f"{tag}: 모든 전압에 하나씩"
        assert (0.685, "cmax") not in [(v, l) for v, l in hc], "앵커는 숨기면 안 됨"
        assert len({l for _, l in hc}) > 1, f"{tag}: 한 레벨에 몰리면 안 됨"
        assert by[tag]["min_seen"] == 4 * n_lv - 4


def test_hidden_per_voltage_cannot_take_every_level(project):
    _clear_temp_holdout(project)
    project["corners"]["hidden_voltages"] = []
    project["corners"]["hidden_per_voltage"] = 2      # 125C 는 레벨이 2개뿐
    with pytest.raises(AssertionError, match="hidden_per_voltage"):
        expand(project)


def test_expand_rejects_level_missing_from_values(project):
    project["temps"][0]["levels"] = ["rcmax", "cworst"]
    with pytest.raises(AssertionError, match="level_values"):
        expand(project)


# ---- 코너 선정: config 의 네 가지 방법이 실제 split 으로 이어지는가 ----------
def _hidden_labels(project, corners_over):
    """project 를 주어진 corners 오버라이드로 확장해 hidden 코너 라벨을 돌려준다."""
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
    cfg["split"]["min_seen"] = 1                     # 가드는 여기서 관심사가 아님
    sp = make_split(labels, vt, cfg)
    return {labels[i] for i in sp.hidden_idx}


def test_hidden_voltages_hides_whole_row(project):
    assert _hidden_labels(project, {"hidden_voltages": [0.54]}) == {
        "SSPG_0p54V_rcmax", "SSPG_0p54V_cmax", "SSPG_0p54V_rcmin"}


def test_hidden_voltages_survive_float32_roundtrip():
    """캐시는 vt 를 float32 로 저장한다 -> 0.54 가 0.54000002 로 돌아온다.

    허용오차가 float32 정밀도보다 빡세면 `hidden_voltages: [0.54]` 가 아무것도
    못 고르고 split 에 hidden 이 하나도 안 남는다 (실제로 그렇게 깨져 있었다).
    npz 왕복을 그대로 재현해 다시는 안 깨지게 못박는다.
    """
    from si_model.parsing.keys import corner_label, parse_corner
    from si_model.training.loo import make_split
    lv = {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}
    labels = [corner_label(v, l, "SSPG")
              for v in (0.5, 0.54, 0.6, 0.685) for l in ("rcmax", "cmax")]
    vt64 = np.asarray([parse_corner(c, lv, "SSPG") for c in labels])
    vt = np.asarray(vt64, np.float32)                    # ← 캐시가 하는 일
    assert float(vt[2, 0]) != 0.54, "float32 왕복이 값을 바꾸지 않으면 이 테스트는 무의미"
    cfg = {"data": {"ref_corner": "SSPG_0p685V_cmax"},
           "split": {"hidden_voltages": [0.54], "min_seen": 1},
           "base": {"axes": [{"name": "v", "ref": 0.685, "order": 2},
                             {"name": "rc", "ref": 0.0, "order": 1, "levels": lv}]}}
    sp = make_split(labels, vt, cfg)
    assert {labels[i] for i in sp.hidden_idx} == {"SSPG_0p54V_rcmax", "SSPG_0p54V_cmax"}


def test_hidden_levels_hides_whole_column(project):
    """커스텀 레벨 이름(rcmin/cmax/rcmax)으로도 동작해야 한다 -- 예전엔 내장
    Cmin/Cnom/Cmax 만 되고 나머지는 float() 변환 에러로 죽었다."""
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
    with pytest.raises(AssertionError, match="하나만"):
        expand(project)


def test_anchor_may_not_be_hidden(project):
    project["corners"]["hidden_levels"] = ["cmax"]      # ref_level 이 cmax
    with pytest.raises(AssertionError, match="hidden_levels"):
        expand(project)


def test_anchor_must_exist_at_every_temp(project):
    project["corners"]["ref_level"] = "rcmin"           # 125C 에는 rcmin 이 없다
    with pytest.raises(AssertionError, match="levels"):
        expand(project)


# ---- OLS / 파싱 노브가 엔진까지 전달되는가 -----------------------------------
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
    assert cfg["train"]["split_seed"] == 7          # 트레이너는 train 에서 읽는다


def test_select_filters(project):
    models = expand(project)
    assert [m["name"] for m in select(models, design="gpu")] == ["gpu/125", "gpu/m25"]
    assert [m["name"] for m in select(models, temp="125")] == ["cpu/125", "gpu/125"]
    with pytest.raises(AssertionError, match="no model matches"):
        select(models, design="nope")


# ================================================================ 2. 코너 탐색
def _cfg(root, temp, levels):
    return {"data": {"annotated_dir": str(root), "temp": temp,
                     "corner_prefix": "SSPG", "rc_corners": levels,
                     "patterns": {"layout": "flat", "annotated_regex": FLAT_RE}},
            "base": {"axes": [{"name": "v", "ref": 0.685, "order": 2},
                              {"name": "rc", "ref": 0, "order": 2,
                               "levels": {"rcmin": -1, "cmax": 0, "rcmax": 1}}]}}


def test_discovery_filters_by_temp_and_level(tree):
    c125 = discover_annotated(_cfg(tree / "cpu", 125, ["rcmax", "cmax"]))
    assert len(c125) == 8                           # 4V x 2레벨, m25 파일은 무시
    cm25 = discover_annotated(_cfg(tree / "cpu", "m25", ["rcmax", "cmax", "rcmin"]))
    assert len(cm25) == 12
    assert set(c125).issubset(set(cm25))            # 온도는 라벨에 안 들어감(분리 차원)


def test_discovery_label_and_sort(tree):
    corners, ann, xt = discover(_cfg(tree / "cpu", 125, ["rcmax", "cmax"]))
    assert corners[0] == "SSPG_0p5V_cmax"           # 0p5000 -> 정규화 0p5
    assert corners[-1] == "SSPG_0p685V_rcmax"       # (전압, 레벨값) 순 정렬
    assert xt is None                               # crosstalk_dir 없으면 SI 없이
    assert os.path.basename(ann["SSPG_0p5V_cmax"]) == "report.sspg_0p5000_125c_cmax.rpt"


@pytest.mark.parametrize("fname,temp,want", [
    # 기준 형식
    ("report.sspg_0p5000_125c_rcmax.rpt", "125", (0.5, "rcmax")),
    # 온도 뒤 c 유무
    ("report.sspg_0p5000_125_rcmax.rpt", "125", (0.5, "rcmax")),
    # 필드 순서가 바뀌어도
    ("report.sspg_0p5000_rcmax_125c.rpt", "125", (0.5, "rcmax")),
    ("RCMAX.125.SSPG.0p5000.rpt", "125", (0.5, "rcmax")),
    # 대소문자
    ("report.SSPG_0P5000_125C_RCMAX.rpt", "125", (0.5, "rcmax")),
    # 전압 표기: 0p5400 / 0.5400 / v0p54
    ("report.sspg_0.5400_125c_rcmax.rpt", "125", (0.54, "rcmax")),
    ("ibex_v0p54_rcmax_125.timing.rpt", "125", (0.54, "rcmax")),
    # 구분자가 하이픈 -> 앞의 '-' 는 음수부호가 아니다
    ("sspg-0p5000-125c-rcmax.rpt", "125", (0.5, "rcmax")),
    # 음수 온도: m25 / M25 / -25
    ("report.sspg_0p5000_m25c_rcmin.rpt", "m25", (0.5, "rcmin")),
    ("report.SSPG_0P5000_M25_RCMIN.rpt", "m25", (0.5, "rcmin")),
    ("report.sspg_0p5000_-25c_rcmin.rpt", "m25", (0.5, "rcmin")),
    # cmax 가 rcmax 안에서 잘못 잡히면 안 된다
    ("report.sspg_0p6850_125c_cmax.rpt", "125", (0.685, "cmax")),
    # --- 걸러져야 하는 것들 ---
    ("report.sspg_0p5000_125c_rcmax.rpt", "m25", None),    # 다른 온도
    ("report.sspg_0p5000_m25c_rcmax.rpt", "125", None),    # 다른 온도(반대)
    ("report.sspg_0p5000_125c_cworst.rpt", "125", None),   # 모르는 레벨
    ("report.sspg_125c_rcmax.rpt", "125", None),           # 전압 없음
    ("readme.txt", "125", None),                           # 무관한 파일
])
def test_filename_matching_is_order_and_case_free(fname, temp, want):
    """파일명 형식은 벤더마다 다르다: 순서, 대소문자, 구분자, 온도의 c 유무,
    전압 표기(0p54 / 0.54)가 제각각이어도 같은 코너로 읽혀야 한다.

    전압은 소수점 표시가 반드시 있어야 하고 온도는 정수라는 점이 둘을 가르는
    유일한 근거이므로, 그 경계(‘.125.’ 를 0.125 로 읽지 않기)까지 여기서 못박는다.
    """
    from si_model.parsing.discovery import _match_tokens
    got = _match_tokens(fname, {"data": {}}, ["rcmax", "cmax", "rcmin"], "SSPG", temp)
    if want is None:
        assert got is None
    else:
        assert got is not None, "매칭 실패"
        assert abs(got[0] - want[0]) < 1e-9 and got[1] == want[1]


def test_same_folder_annotated_and_crosstalk(tmp_path):
    """`pt_si_re` 배치: 코너 폴더 하나에 annotated 와 crosstalk 이 함께 있다.

    둘 다 코너 토큰을 갖고 있어 그대로는 같은 코너에 두 파일이 매칭된다.
    (a) 그 상황이 '이렇게 고쳐라' 는 에러로 잡히고,
    (b) files.*_contains 를 주면 정상 동작하는지 -- 둘 다 못박는다.
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
            (d / "corner_info.tcl").touch()          # 중간 파일은 무시돼야

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

    with pytest.raises(AssertionError, match="한 폴더에"):
        discover_annotated(cfg(False))

    corners, ann, xt = discover(cfg(True))
    assert len(corners) == 4 and xt is not None and len(xt) == 4
    assert all(a.endswith("_fixed_annotated.txt") for a in ann.values())
    assert all(x.endswith(".by_path.rpt") for x in xt.values())


def test_crosstalk_subdir_inside_design_is_excluded(tmp_path):
    """크로스토크가 회로폴더 '하위' 에 있으면 annotated 재귀 탐색에서 빠져야 한다."""
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
    assert all("xtalk" not in a for a in ann.values()), "annotated 가 xtalk 을 주웠다"


def test_discovery_wrong_prefix_is_loud(tree):
    cfg = _cfg(tree / "cpu", 125, ["rcmax", "cmax"])
    cfg["data"]["corner_prefix"] = "FFPG"
    with pytest.raises(AssertionError, match="no annotated corners discovered"):
        discover_annotated(cfg)


def test_levels_layout_still_supported(tmp_path):
    """레벨 하위폴더 배치(<dir>/<LEVEL>/<전압당 1파일>)도 그대로 된다."""
    root = tmp_path / "ann"
    for lv in ("Cmin", "Cnom", "Cmax"):
        (root / lv).mkdir(parents=True)
        for v in ("0p6", "0p8"):
            (root / lv / f"saed14rvt_tt{v}vm40c_x_fixed_annotated.txt").touch()
    cfg = {"data": {"annotated_dir": str(root), "temp": "m40",
                    "rc_corners": ["Cmin", "Cnom", "Cmax"]},
           "base": {"axes": [{"name": "v", "ref": 0.8, "order": 3},
                             {"name": "rc", "ref": 0.0, "order": 2}]}}
    got = discover_annotated(cfg)      # axes 에 levels: 없음 -> 내장 RC 맵 폴백
    assert len(got) == 6 and "TT_0p8V_Cnom" in got


# ============================ 2.5 end-to-end: 리포트 -> npz -> base (torch 불필요)
def _fake_report(v: float, lvv: float, n_paths: int = 12) -> str:
    """파서 형식에 맞는 최소한의 진짜 리포트. 전압/BEOL 의존성을 물리적으로
    그럴듯하게(비선형) 넣어, base 다항식이 실제로 맞춰야 할 게 있게 한다."""
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
    """배포 배치 그대로: <root>/{si_corner_model, boomcore} + 파싱 가능한 리포트."""
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
    """리포트 -> dataset.npz -> seen/hidden 분할 -> OLS base 까지 전 구간.

    torch 없이 도는 구간 전체라, 회사에서 학습 전에 확인할 수 있는 범위와 같다.
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.training.loo import build_design, fit_field, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)                       # cache 는 여기 아래로
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]                     # 픽스처의 회로 이름
    p["files"]["crosstalk_subdir"] = None           # 이 픽스처는 SI 없이 검증
    models = select(expand(p), design="boomcore")
    assert [m["name"] for m in models] == ["boomcore/125", "boomcore/m25"]

    for m, want_c in zip(models, (8, 12)):            # 4V x 2레벨, 4V x 3레벨
        n_hidden = len(m["cfg"]["split"]["hidden_corners"]) or want_c // 4
        build(m["cfg"])
        ds = dict(np.load(m["cfg"]["data"]["cache"]))
        assert ds["slack"].shape == (12, want_c), "경로 12개 x 코너 want_c"
        assert np.isfinite(ds["slack"]).all()
        assert (ds["si_label"] == 0).all()            # 크로스토크 없음 -> 0
        assert ds["node_mask"].any() and len(ds["fam_vocab"]) > 1

        split = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
        assert split.hidden.sum() == n_hidden
        assert not split.hidden[split.ref_ci]

        # 실제 경로와 동일하게 y 를 넘긴다 -> 기저가 seen-LOO 로 선택된다
        phi, coords, exps, _ = build_design(m["cfg"], split, y=ds["slack"])
        loo, _ = fit_field(ds["slack"], phi, split, coords, m["cfg"])
        assert np.isfinite(loo).all()
        # 합성 데이터는 매끄러우므로 base 가 hidden 코너를 잘 맞춰야 한다
        hid = split.hidden_idx
        mae_ps = np.abs(loo[:, hid] - ds["slack"][:, hid]).mean() * 1000
        assert mae_ps < 20, f"hidden base MAE 가 너무 크다: {mae_ps:.2f} ps"
        assert phi.shape[1] < split.seen.sum(), (
            "선택된 기저는 자유도를 최소 1 남겨야 한다 (seen-LOO 가 의미를 가지려면)")


def test_hidden_labels_never_reach_the_base(real_tree, tmp_path, monkeypatch):
    """hidden 코너의 라벨은 학습에 절대 들어가면 안 된다.

    증명 방식: hidden 열의 라벨만 난수로 오염시키고 base 를 다시 계산한다.
    hidden 라벨이 어디로든 새면 seen 쪽 산출물이 달라진다. 여기서 검사하는
    base/resid 는 신경망의 학습 타깃이자 토큰 입력이므로, 이게 안 변하면
    누수 경로가 없다는 뜻이다.
    (torch 단까지의 검증 -- 가중치·예측이 비트 단위로 동일 -- 은 별도로 확인함)
    """
    from si_model.parsing.build_dataset import build
    from si_model.run import expand, load_project, select
    from si_model.training.loo import compute_base, make_split

    monkeypatch.setenv("SI_ROOT", str(real_tree))
    monkeypatch.chdir(tmp_path)
    p = load_project(os.path.join(REPO_ROOT, "config.yaml"))
    p["designs"] = ["boomcore"]                     # 픽스처의 회로 이름
    p["files"]["crosstalk_subdir"] = None           # 이 픽스처는 SI 없이 검증
    m = select(expand(p), design="boomcore", temp="m25")[0]
    build(m["cfg"])
    ds = dict(np.load(m["cfg"]["data"]["cache"]))

    split = make_split(ds["corners"].tolist(), ds["vt"], m["cfg"])
    S, H = split.seen_idx, split.hidden_idx
    assert len(H) and len(S), "이 테스트는 hidden/seen 이 둘 다 있어야 의미가 있다"

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
    # seen 은 학습 타깃 / 토큰, hidden 은 예측 기준선 -- 둘 다 hidden 라벨과 무관해야
    assert np.array_equal(a.base_hat[:, S], b.base_hat[:, S])
    assert np.array_equal(a.base_hat[:, H], b.base_hat[:, H])
    assert np.array_equal(a.resid[:, S], b.resid[:, S])
    assert np.array_equal(a.si_smooth_hat[:, S], b.si_smooth_hat[:, S])

    # 토큰 정규화 통계도 seen 에서만 나와야 한다
    def stats(d, base):
        raw = np.stack([d["slack"], d["si_label"], d["arrival"], d["required"],
                        d["launch_clk"], d["capture_clk"], d["lib_check_time"],
                        base.resid], -1)
        return (np.nanmean(raw[:, S], axis=(0, 1)), np.nanstd(raw[:, S], axis=(0, 1)))
    (mu_a, sd_a), (mu_b, sd_b) = stats(ds, a), stats(poisoned, b)
    assert np.array_equal(mu_a, mu_b) and np.array_equal(sd_a, sd_b)


# ========================================================= 3. 엔진 수학 / 헬퍼
def _basis(axes, cross_max_degree=3, cross_terms=True):
    return {"base": {"axes": axes, "cross_terms": cross_terms,
                     "cross_max_degree": cross_max_degree}}


def test_basis_generation():
    cfg = _basis([{"name": "v", "ref": 0.8, "order": 3},
                  {"name": "rc", "ref": 0.0, "order": 2}])
    _, names, _ = expand_terms(cfg)
    assert set(names) == {"dv", "dv2", "dv3", "drc", "drc2", "dvdrc", "dv2drc", "dvdrc2"}


def test_basis_drops_rank_deficient_terms():
    # 전압 seen 4레벨 -> dv4 불가, BEOL 3레벨 -> drc3 불가
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
    """grid=[None] 이면 adaptive base 가 전역 closed-form LOO 와 정확히 같다."""
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
    # _#idx 는 리포트별 일련번호일 뿐 경로 식별자가 아니다 -- 안 떼면 코너 간 join 붕괴
    assert norm_path_key("A->B_#282") == "A->B"
    assert norm_path_key("A->B#5") == "A->B"
    assert norm_path_key("A->B") == "A->B"


def test_corner_label_roundtrip():
    lv = {"rcmin": -1.0, "cmax": 0.0, "rcmax": 1.0}
    assert corner_label(0.685, "cmax", prefix="SSPG") == "SSPG_0p685V_cmax"
    assert parse_corner("SSPG_0p685V_cmax", lv, prefix="SSPG") == (0.685, 0.0)
    assert parse_corner("SSPG_0p5V_rcmax", lv, prefix="SSPG") == (0.5, 1.0)
    # 온도형 라벨(2번째 축이 온도인 데이터)도 지원
    assert parse_corner("SSPG_0p9V_m25C", prefix="SSPG") == (0.9, -25.0)


def test_filename_voltage_and_xt_parsing():
    assert abs(parse_voltage_from_annotated("saed14rvt_tt0p605vm40c_x.txt") - 0.605) < 1e-9
    assert parse_xt_name("SSPG_0p55V_125C.foo.by_path.rpt", prefix="SSPG") == (0.55, "125")


def test_cell_taxonomy_defaults_are_safe():
    assert cell_family("SAEDRVT14_ND2_CDC_0P5") == "NAND"
    assert cell_family("SAEDRVT14_FDP_V2LP_2") == "DFF"
    assert cell_drive("SAEDRVT14_BUF_20") == 20.0
    assert cell_drive("SAEDRVT14_NR3B_1P5") == 1.5
    # 모르는 라이브러리여도 에러가 아니라 <unk> + drive 1.0 으로 학습된다
    assert cell_family("SEC9T_WHATEVER_X4") == "<unk>"
    assert cell_drive("SEC9T_WHATEVER") == 1.0
