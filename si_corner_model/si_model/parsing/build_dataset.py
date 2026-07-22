"""Build the training cache for one 14nm (sta, temp) model from raw
annotation + crosstalk deliverables.

A model instance is a single (setup|hold) x (m40|125) combination; its corner
grid is 17 V x 3 RC = 51 corners (temperature is fixed, NOT a corner axis --
see keys.py / README). Run as a CLI:

    python -m si_model.parsing.build_dataset --config configs/beol14/setup_m40.yaml

Discovery walks the RC sub-folders:
  annotated:  <annotated_dir>/<RC>/saed14rvt_tt<v>v<t>c_..._fixed_annotated.txt
  crosstalk:  <crosstalk_dir>/<RC>/TT_<v>V_<temp>C.path_context_si_compact.by_path.rpt
The corner label is ``TT_<v>V_<RC>`` (temp implied by the model).

Integrity invariants (hard asserts -- if a data drop violates one, find out why
before training):
  I1  same (V, RC) corner set in annotation and crosstalk
  I2  identical idx -> norm_path_key mapping across all corners & both sources
  I3  annotated slack == crosstalk header slack per (path, corner)
  I4  victim-only rows have delta == 0; duplicate (segment, net) rows agree
      (enforced inside the crosstalk parser)
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import numpy as np
import yaml

from .annotated import parse_annotated
from .crosstalk import parse_crosstalk, SEGMENTS
from .keys import (RC_NAMES, corner_label, norm_path_key, parse_corner,
                   parse_voltage_from_annotated, parse_xt_name)

SEG_CODE = {s: i for i, s in enumerate(SEGMENTS)}


# ---------------------------------------------------------------------------
# SAED14 cell taxonomy (self-contained; the gt3 model used gt3_6t_* names).
# Maps a SAED14 lib-cell to a coarse function family string (for the encoder's
# family embedding) and a numeric drive strength.
# ---------------------------------------------------------------------------
_SAED_FUNC = [
    ("AOI", "AOI"), ("OAI", "OAI"), ("AO", "AO"), ("OA", "OA"),
    ("ND", "NAND"), ("NR", "NOR"), ("AN", "AND"), ("OR", "OR"),
    ("XOR", "XOR"), ("XNR", "XNOR"), ("EN", "XNOR"),
    ("INV", "INV"), ("IBUFF", "BUF"), ("BUF", "BUF"), ("DEL", "BUF"),
    ("MUXI", "MUX"), ("MUX", "MUX"),
    ("FDPQB", "DFF"), ("FDPQ", "DFF"), ("FDPB", "DFF"), ("FDP", "DFF"),
    ("FDN", "DFF"), ("FD", "DFF"), ("LH", "DFF"), ("SDF", "DFF"),
    ("ADDF", "FA"), ("FA", "FA"), ("ADDH", "HA"), ("HA", "HA"),
    ("TIE", "BUF"), ("AOBUF", "BUF"), ("DCAP", "BUF"), ("ANTENNA", "BUF"),
]
_VT_PREFIXES = ("SAEDRVT14_", "SAED14RVT_", "SAEDLVT14_", "SAEDHVT14_")
_HEAD_RE = re.compile(r"^([A-Z]+B?)(\d*)$")

# Custom cell taxonomy (any non-SAED library, e.g. Samsung std cells), supplied
# from config -- see configure_cell_taxonomy(). None = use the SAED14 default.
_CUSTOM_TAX: dict | None = None


def configure_cell_taxonomy(cfg: dict) -> None:
    """Install a config-driven cell-name taxonomy (``data.cell_taxonomy``), so a
    non-SAED library needs NO code edit:

        data:
          cell_taxonomy:
            strip_prefixes: [SEC9T_, LN08LPP_]        # dropped from the name start
            family_rules:                             # first regex match wins
              - ['^ND|^NAND', NAND]
              - ['^NR|^NOR',  NOR]
              - ['^INV|^IV',  INV]
              - ['DFF|SDFF|FF', DFF]
            drive_regex: '_X(\\d+P?\\d*)$'            # group 1 = drive, P = decimal

    Families are dataset-internal labels (the vocab is built from the data), so
    the rule set only needs to be *consistent*, not complete: anything unmatched
    becomes '<unk>' and still trains. Called by build()/build_slew before parsing;
    an empty/missing block restores the SAED14 default."""
    global _CUSTOM_TAX
    t = (cfg.get("data") or {}).get("cell_taxonomy")
    if not t:
        _CUSTOM_TAX = None
        return
    _CUSTOM_TAX = {
        "strip": tuple(str(p).upper() for p in t.get("strip_prefixes", [])),
        "rules": [(re.compile(r, re.IGNORECASE), fam)
                  for r, fam in t.get("family_rules", [])],
        "drive": re.compile(t["drive_regex"]) if t.get("drive_regex") else None,
    }


def cell_family(cell: str) -> str:
    """Lib-cell name -> coarse function family; unknowns -> '<unk>' (still
    trains). Uses the config taxonomy when installed, else the SAED14 default
    (``SAEDRVT14_ND2_CDC_0P5`` -> 'NAND')."""
    if not cell:
        return "<unk>"
    ct = cell.upper()
    if _CUSTOM_TAX is not None:
        for pre in _CUSTOM_TAX["strip"]:
            if ct.startswith(pre):
                ct = ct[len(pre):]
        for pat, fam in _CUSTOM_TAX["rules"]:
            if pat.search(ct):
                return fam
        return "<unk>"
    for pre in _VT_PREFIXES:
        ct = ct.replace(pre, "")
    head = ct.split("_")[0]
    m = _HEAD_RE.match(head)
    fl = m.group(1) if m else head
    if fl.endswith("B") and len(fl) > 1:
        fl = fl[:-1]
    for pre, fam in _SAED_FUNC:
        if fl.startswith(pre):
            return fam
    return "<unk>"


def cell_drive(cell: str) -> float:
    """Numeric drive strength. Config taxonomy: ``drive_regex`` group 1
    ('X0P5' -> 0.5). SAED default: trailing token (``BUF_20`` -> 20,
    ``NR3B_1P5`` -> 1.5). Unknown -> 1.0."""
    if not cell:
        return 1.0
    if _CUSTOM_TAX is not None:
        if _CUSTOM_TAX["drive"] is None:
            return 1.0
        m = _CUSTOM_TAX["drive"].search(cell.upper())
        if not m:
            return 1.0
        try:
            return max(0.5, float(m.group(1).replace("P", ".")))
        except ValueError:
            return 1.0
    tok = cell.upper().split("_")[-1]
    try:
        return max(0.5, float(tok.replace("P", ".")))
    except ValueError:
        return 1.0


def load_config(fp: str) -> dict:
    from si_model.config import load_config as _lc
    return _lc(fp)                       # merge configs/_defaults.yaml


def corner_levels(cfg: dict) -> dict:
    """Second-axis level name->value map for this dataset (config-driven, so a
    non-RC BEOL/process naming needs no code change). Falls back to the RC map."""
    from si_model.config import axis_levels
    return axis_levels(cfg) or dict(RC_VAL)


def discover(cfg: dict):
    """Return (corners, ann_by_corner, xt_by_corner) for one (sta, temp) model.

    corners: labels ``TT_<v>V_<level>`` sorted by (V, level_value). The level
    subdir names come from ``data.rc_corners`` (any names), their coordinates
    from the axis ``levels`` map, and the filename patterns from ``data.patterns``
    (defaults are the SAED14 / PrimeTime reference format).
    """
    ann_root = cfg["data"]["annotated_dir"]
    xt_root = cfg["data"]["crosstalk_dir"]
    temp = str(cfg["data"]["temp"])
    levels = corner_levels(cfg)
    prefix = cfg["data"].get("corner_prefix", "TT")   # process token, e.g. FFPG
    rc_list = cfg["data"].get("rc_corners", list(levels) or list(RC_NAMES))
    pat = cfg["data"].get("patterns", {})
    ann_suffix = pat.get("annotated_suffix", "_fixed_annotated.txt")
    xt_suffix = pat.get("crosstalk_suffix", ".by_path.rpt")
    volt_re = re.compile(pat["voltage_regex"]) if pat.get("voltage_regex") else None

    ann_by: dict[str, str] = {}
    xt_by: dict[str, str] = {}
    for rc in rc_list:
        adir = os.path.join(ann_root, rc)
        assert os.path.isdir(adir), f"missing annotated level dir: {adir}"
        for fn in sorted(os.listdir(adir)):
            if not fn.endswith(ann_suffix):
                continue
            v = parse_voltage_from_annotated(fn, volt_re)
            if v is None:
                continue
            ann_by[corner_label(v, rc, prefix)] = os.path.join(adir, fn)
        xdir = os.path.join(xt_root, rc)
        assert os.path.isdir(xdir), f"missing crosstalk level dir: {xdir}"
        for fn in sorted(os.listdir(xdir)):
            if not fn.endswith(xt_suffix):
                continue
            pv = parse_xt_name(fn, prefix)
            if pv is None:
                continue
            v, tk = pv
            if tk != temp:
                continue
            xt_by[corner_label(v, rc, prefix)] = os.path.join(xdir, fn)

    only_a, only_x = set(ann_by) - set(xt_by), set(xt_by) - set(ann_by)
    assert not only_a and not only_x, \
        f"I1: corner sets differ: only-ann={only_a} only-xt={only_x}"
    assert ann_by, f"no corners discovered under {ann_root} (temp={temp})"
    corners = sorted(ann_by, key=lambda c: parse_corner(c, levels, prefix))
    return corners, ann_by, xt_by


# per-segment aggregate path signature (ref corner) --------------------------
def path_signature(stages) -> np.ndarray:
    seg = {s: [st for st in stages if st.segment == s] for s in SEGMENTS}
    feats: list[float] = []
    for s in SEGMENTS:
        cells = [st for st in seg[s] if st.kind == "cell"]
        nets = [st for st in seg[s] if st.kind == "net"]
        feats += [
            float(len(cells)),
            float(len(nets)),
            float(sum(st.incr for st in cells)),
            float(max((st.trans for st in cells), default=0.0)),
            float(sum(st.cap for st in nets)),
            float(sum(st.res for st in nets)),
            float(sum(st.dist for st in nets)),
            float(sum(st.fanout for st in nets)),
            float(max((st.fanout for st in nets), default=0.0)),
        ]
    return np.asarray(feats, dtype=np.float32)


SIG_NAMES = [
    f"{s}_{n}" for s in SEGMENTS
    for n in ("n_cells", "n_nets", "sum_incr", "max_trans", "sum_cap",
              "sum_res", "sum_dist", "sum_fanout", "max_fanout")
]

# per-node numeric features for the stage-sequence encoder (ref corner)
NODE_FEAT_NAMES = [
    "trans", "incr", "drive_x", "is_output", "edge_rise", "critical",
    "seg_launch", "seg_data", "seg_capture",
]
EDGE_FEAT_NAMES = ["cap", "fanout", "res", "dist", "cpin"]


def stage_sequence(stages):
    """Ref-corner stage chain for the ChainMP/BiGRU encoder.

    Nodes = cell-pin rows in path order; the net row between two cell rows
    becomes that link's edge feature vector (zeros for same-cell input->output
    arcs). ``is_output`` is detected structurally: a cell row immediately
    followed by a net row drives that net (robust to SAED14 output-pin names
    /X, /Q, /QN, ...).
    Returns (families, node_feat [L, F], edge_feat [L-1, E]).
    """
    fams: list[str] = []
    nodes: list[list[float]] = []
    edges: list[list[float]] = []
    pending_net = None
    seg_onehot = {"launch_clock": (1, 0, 0), "data": (0, 1, 0), "capture_clock": (0, 0, 1)}
    n = len(stages)
    for i, st in enumerate(stages):
        if st.kind == "net":
            pending_net = st
            continue
        if nodes:  # edge from previous cell row to this one
            if pending_net is not None:
                edges.append([pending_net.cap, float(pending_net.fanout),
                              pending_net.res, pending_net.dist, pending_net.cpin])
            else:
                edges.append([0.0] * len(EDGE_FEAT_NAMES))
        pending_net = None
        is_out = 1.0 if (i + 1 < n and stages[i + 1].kind == "net") else 0.0
        fams.append(cell_family(st.cell))
        nodes.append([
            st.trans, st.incr, cell_drive(st.cell), is_out,
            1.0 if st.edge == "r" else 0.0,
            1.0 if st.critical else 0.0,
            *seg_onehot[st.segment],
        ])
    return fams, nodes, edges


def build(cfg: dict) -> str:
    ref_corner = cfg["data"]["ref_corner"]
    out_fp = cfg["data"]["cache"]
    configure_cell_taxonomy(cfg)     # non-SAED (e.g. Samsung) cell naming, from config

    corners, ann_by_corner, xt_by_corner = discover(cfg)
    assert ref_corner in corners, f"ref corner {ref_corner} not in data ({corners[:3]}...)"
    C = len(corners)
    levels = corner_levels(cfg)
    prefix = cfg["data"].get("corner_prefix", "TT")
    vt = np.asarray([parse_corner(c, levels, prefix) for c in corners],
                    dtype=np.float32)  # (V, level_value)

    ref_keys: dict[int, str] | None = None
    slack = arrival = required = si_label = None
    stage_id: dict[tuple[int, int, str], int] = {}
    stage_meta: list[tuple[int, int, str]] = []
    aggr_id: dict[tuple[int, str], int] = {}
    aggr_meta: list[list[str]] = []
    vwin_c: list[dict] = []
    adata_c: list[dict] = []
    arc_delta_c: list[dict] = []

    idx_order: list[int] = []
    stage_seqs: dict[int, tuple] = {}

    for ci, corner in enumerate(corners):
        ann = parse_annotated(ann_by_corner[corner], with_stages=(corner == ref_corner))
        xt = parse_crosstalk(xt_by_corner[corner])

        keys_ann = {i: norm_path_key(p.key) for i, p in ann.items()}
        keys_xt = {i: norm_path_key(p.key) for i, p in xt.items()}
        assert keys_ann == keys_xt, f"I2: {corner}: annotation vs crosstalk key mismatch"
        if ref_keys is None:
            ref_keys = keys_ann
            idx_order = sorted(ref_keys)
            N = len(idx_order)
            slack = np.full((N, C), np.nan, np.float64)
            arrival = np.full((N, C), np.nan, np.float64)
            required = np.full((N, C), np.nan, np.float64)
            launch_clk = np.full((N, C), np.nan, np.float64)
            capture_clk = np.full((N, C), np.nan, np.float64)
            lib_check_time = np.full((N, C), np.nan, np.float64)
            si_label = np.full((N, C), np.nan, np.float64)
            path_sig = np.zeros((N, len(SIG_NAMES)), np.float32)
        else:
            assert keys_ann == ref_keys, f"I2: {corner}: keys differ from reference corner"

        vw: dict[tuple[int, int, str], tuple[float, float]] = {}
        ad: dict[tuple[int, int], tuple] = {}
        dl: dict[tuple[int, int, str], float] = {}
        for r, idx in enumerate(idx_order):
            pa, px = ann[idx], xt[idx]
            assert abs(pa.slack - px.slack) < 5e-5, \
                f"I3: {corner} idx={idx}: slack {pa.slack} vs {px.slack}"
            slack[r, ci] = pa.slack
            arrival[r, ci] = pa.arrival
            required[r, ci] = pa.required
            launch_clk[r, ci] = pa.launch_clk
            capture_clk[r, ci] = pa.capture_clk
            lib_check_time[r, ci] = pa.lib_check_time
            si_label[r, ci] = px.si_total()
            if corner == ref_corner:
                path_sig[r] = path_signature(pa.stages)
                stage_seqs[r] = stage_sequence(pa.stages)

            for arc in px.arcs:
                skey = (r, SEG_CODE[arc.segment], arc.net)
                vw[skey] = (arc.min_arrival, arc.max_arrival)
                dl[skey] = arc.delta
                if not arc.aggressors:
                    continue
                s = stage_id.get(skey)
                if s is None:
                    s = len(stage_meta)
                    stage_id[skey] = s
                    stage_meta.append(skey)
                    aggr_meta.append([])
                for ag in arc.aggressors:
                    akey = (s, ag.net)
                    a = aggr_id.get(akey)
                    if a is None:
                        a = len(aggr_meta[s])
                        aggr_id[akey] = a
                        aggr_meta[s].append(ag.net)
                    ad[(s, a)] = (ag.bump, ag.min_arrival, ag.max_arrival, ag.slew, ag.cc_ff)
        vwin_c.append(vw)
        adata_c.append(ad)
        arc_delta_c.append(dl)
        print(f"[{ci + 1:2d}/{C}] {corner}: paths={len(ann)} si_stages={len(stage_meta)}", flush=True)

    # densify SI tensors
    S = len(stage_meta)
    A = max((len(m) for m in aggr_meta), default=1)
    stage_path = np.asarray([m[0] for m in stage_meta], np.int32)
    stage_seg = np.asarray([m[1] for m in stage_meta], np.int8)
    n_aggr = np.asarray([len(m) for m in aggr_meta], np.int16)
    vwin = np.full((S, C, 2), np.nan, np.float32)
    arc_delta = np.full((S, C), np.nan, np.float32)
    abump = np.full((S, A, C), np.nan, np.float32)
    awin = np.full((S, A, C, 2), np.nan, np.float32)
    aslew = np.full((S, A, C), np.nan, np.float32)
    acc = np.full((S, A), np.nan, np.float32)
    for ci in range(C):
        for skey, (lo, hi) in vwin_c[ci].items():
            s = stage_id.get(skey)
            if s is not None:
                vwin[s, ci] = (lo, hi)
        for skey, d in arc_delta_c[ci].items():
            s = stage_id.get(skey)
            if s is not None:
                arc_delta[s, ci] = d
        for (s, a), (bump, lo, hi, slew, cc) in adata_c[ci].items():
            abump[s, a, ci] = bump
            awin[s, a, ci] = (lo, hi)
            aslew[s, a, ci] = slew
            acc[s, a] = cc  # Cc is V/RC-independent (SPEF); last write wins

    # densify stage sequences (ref corner)
    N = len(idx_order)
    vocab = ["<pad>"] + sorted({f for fams, _, _ in stage_seqs.values() for f in fams})
    fam_id = {f: i for i, f in enumerate(vocab)}
    Lmax = max(len(fams) for fams, _, _ in stage_seqs.values())
    node_fam = np.zeros((N, Lmax), np.int16)
    node_feat = np.zeros((N, Lmax, len(NODE_FEAT_NAMES)), np.float32)
    edge_feat = np.zeros((N, Lmax - 1, len(EDGE_FEAT_NAMES)), np.float32)
    node_mask = np.zeros((N, Lmax), bool)
    for r in range(N):
        fams, nodes, edges = stage_seqs[r]
        L = len(fams)
        node_fam[r, :L] = [fam_id[f] for f in fams]
        node_feat[r, :L] = nodes
        if edges:
            edge_feat[r, :len(edges)] = edges
        node_mask[r, :L] = True

    # ---- optional PURE-INFERENCE corners (deployment): no measurement files,
    # prediction targets only. Declared in config as labels or [v, level] pairs:
    #   data.query_corners: [TT_0p71V_Cnom, [0.66, Cmax]]
    # They join the grid with NaN measurements and measured=False, are forced
    # hidden by make_split, excluded from all metrics, and get model predictions
    # (with empty truth columns) in the exported predictions files.
    measured = np.ones(C, bool)
    qcs = cfg["data"].get("query_corners", [])
    if qcs:
        qlabs = [q if isinstance(q, str) else corner_label(float(q[0]), q[1], prefix)
                 for q in qcs]
        qvt = np.asarray([parse_corner(l, levels, prefix) for l in qlabs], np.float32)
        Q = len(qlabs)

        def _pad(a: np.ndarray, axis: int) -> np.ndarray:
            shp = list(a.shape)
            shp[axis] = Q
            return np.concatenate([a, np.full(shp, np.nan, a.dtype)], axis=axis)

        slack, arrival, required, si_label = (
            _pad(x, 1) for x in (slack, arrival, required, si_label))
        launch_clk, capture_clk, lib_check_time = (
            _pad(x, 1) for x in (launch_clk, capture_clk, lib_check_time))
        arc_delta, vwin = _pad(arc_delta, 1), _pad(vwin, 1)
        abump, aslew, awin = _pad(abump, 2), _pad(aslew, 2), _pad(awin, 2)
        corners = list(corners) + qlabs
        vt = np.concatenate([vt, qvt], 0)
        measured = np.concatenate([measured, np.zeros(Q, bool)])
        C += Q
        print(f"[QUERY] appended {Q} unmeasured query corners: {qlabs}", flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(out_fp)), exist_ok=True)
    np.savez_compressed(
        out_fp,
        measured=measured,
        node_fam=node_fam, node_feat=node_feat, edge_feat=edge_feat,
        node_mask=node_mask, fam_vocab=np.asarray(vocab),
        node_feat_names=np.asarray(NODE_FEAT_NAMES),
        edge_feat_names=np.asarray(EDGE_FEAT_NAMES),
        corners=np.asarray(corners),
        vt=vt,
        path_keys=np.asarray([ref_keys[i] for i in idx_order]),
        path_idx=np.asarray(idx_order, np.int32),
        slack=slack, arrival=arrival, required=required, si_label=si_label,
        launch_clk=launch_clk, capture_clk=capture_clk, lib_check_time=lib_check_time,
        path_sig=path_sig, sig_names=np.asarray(SIG_NAMES),
        stage_path=stage_path, stage_seg=stage_seg, n_aggr=n_aggr,
        vwin=vwin, arc_delta=arc_delta,
        abump=abump, awin=awin, aslew=aslew, acc=acc,
    )
    print(f"wrote {out_fp}: N={len(idx_order)} C={C} S={S} A={A}")
    return out_fp


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    args = ap.parse_args(argv)
    build(load_config(args.config))


if __name__ == "__main__":
    sys.exit(main())
