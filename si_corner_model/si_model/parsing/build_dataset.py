"""Build ``dataset.npz`` for ONE model instance from annotation (+ crosstalk).

A model instance = one (design, temperature) pair -- and one process, one
setup/hold check. Those are *split* dimensions, fixed here; the corner grid this
builds spans only the two continuous axes, voltage x BEOL level. ``si_model.run``
expands ``config.yaml`` into one call of ``build()`` per instance:

    bash scripts/run.sh build            # the normal path (config.yaml expands the models)
    python -m si_model.parsing.build_dataset --config <engine-schema.yaml>   # escape hatch

Report discovery (both directory layouts) lives in ``parsing/discovery.py``.
Crosstalk is OPTIONAL: with no ``data.crosstalk_dir`` the dataset is built
SI-free (si_label = 0, no SI stages) and the trainer forces ``lambda_si`` to 0.

Integrity invariants (hard asserts -- if a data drop violates one, find out why
before training):
  I1  same corner set in annotation and crosstalk        (discovery.discover)
  I2  identical idx -> norm_path_key mapping across all corners & both sources
  I3  annotated slack == crosstalk header slack per (path, corner)
  I4  victim-only rows have delta == 0; duplicate (segment, net) rows agree
      (enforced inside the crosstalk parser)
"""
import argparse
import os
import re
import sys

import numpy as np

from .annotated import configure_pins, parse_annotated
from .crosstalk import parse_crosstalk, SEGMENTS
from .discovery import corner_levels, discover
from .keys import corner_label, norm_path_key, parse_corner

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
_CUSTOM_TAX: "dict | None" = None


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
        # IGNORECASE: cell_drive matches against the UPPER-CASED name, so a rule
        # written in the library's own lower-case spelling would never fire.
        "drive": (re.compile(t["drive_regex"], re.IGNORECASE)
                  if t.get("drive_regex") else None),
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
    return _lc(fp)                       # engine-schema YAML (escape hatch; see config.load_config)


# Corner discovery (both directory layouts) lives in parsing/discovery.py and is
# shared with the slew builder; `corner_levels` and `discover` are re-exported
# above so existing imports of this module keep working.


def choose_key_mode(ann: dict, cfg: dict) -> bool:
    """Decide whether to strip the ``#<idx>`` ordinal from path keys.

    Two incompatible conventions exist, and picking wrong silently corrupts the
    dataset in opposite directions:

    * per-corner ``report_timing`` dumps enumerate paths independently, so the
      ordinal differs between corners and MUST be stripped -- otherwise the
      cross-corner join collapses (the 14nm case: ~2758 common paths -> ~8).
    * a fixed-path re-measurement run (union list -> re-measure everywhere, as
      produced by ``1_union.py``) assigns the ordinal ONCE and reuses it at
      every corner. There the ordinal is part of path identity: the same
      start/end flop pair can carry several distinct paths through different
      pins, and stripping merges them into one row.

    ``auto`` (default) tells them apart by the only observable that matters:
    if stripping creates duplicate keys, the ordinal is carrying identity, so
    keep it. Override with ``data.strip_path_idx: true|false``.
    """
    mode = (cfg.get("data") or {}).get("strip_path_idx", "auto")
    if mode is not True and mode is not False and str(mode) != "auto":
        raise ValueError(f"data.strip_path_idx must be true|false|auto, got {mode!r}")
    if mode is True or mode is False:
        return bool(mode)
    stripped = {norm_path_key(p.key) for p in ann.values()}
    if len(stripped) == len(ann):
        return True
    print(f"[KEYS] dropping '#idx' collapses {len(ann)} paths into {len(stripped)} "
          f"-> treating it as the identifier that distinguishes different paths "
          f"between the same FF pair, so it is kept. (Normal for a fixed-path "
          f"re-measurement report. Override with data.strip_path_idx)",
          flush=True)
    return False


def _assert_parsed(ann: dict, fp: str) -> None:
    """Zero paths parsed means the report BODY does not match the parser -- the
    single most likely failure on a new deliverable. Say so here, where the file
    is known, instead of letting it surface later as an empty-sequence error."""
    if ann:
        return
    head = ""
    try:
        with open(fp, errors="ignore") as f:
            head = "".join(next(f, "") for _ in range(4)).rstrip()
    except OSError:
        pass
    raise AssertionError(
        f"0 paths parsed: {fp}\n"
        f"  The file was found, but its body does not match the parser format.\n"
        f"  The parser assumes each path starts with a header:\n"
        f"  '### FIXED_PATH idx=<i> key=<start>-><end>'\n"
        f"  - No header: first check whether every corner has the same path set\n"
        f"    (README 'caveats' 1). If it does, add a header-less mode to the\n"
        f"    parser; if it does not, the fixed paths must be re-annotated --\n"
        f"    that is not something the parser can work around.\n"
        f"  - Header present but slack/column format differs: see the regexes at\n"
        f"    the top of si_model/parsing/annotated.py (docs/PARSING.md section 4).\n"
        f"  Head of the file:\n    " + head.replace("\n", "\n    "))


# per-segment aggregate path signature (ref corner) --------------------------
def path_signature(stages) -> np.ndarray:
    seg = {s: [st for st in stages if st.segment == s] for s in SEGMENTS}
    feats: "list[float]" = []
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
    fams: "list[str]" = []
    nodes: "list[list[float]]" = []
    edges: "list[list[float]]" = []
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
    configure_cell_taxonomy(cfg)   # 비-SAED 셀 이름 규칙 (data.cell_taxonomy)
    configure_pins(cfg)            # FF 클럭/출력 핀 이름 (data.clock_pins 등)

    corners, ann_by_corner, xt_by_corner = discover(cfg)
    if xt_by_corner is None:
        print("[SI] no data.crosstalk_dir -- building WITHOUT crosstalk: si_label=0, "
              "no SI branch inputs. Train with lambda_si=0 (the trainer forces it).",
              flush=True)
    assert ref_corner in corners, f"ref corner {ref_corner} not in data ({corners[:3]}...)"
    C = len(corners)
    levels = corner_levels(cfg)
    prefix = cfg["data"].get("corner_prefix", "TT")
    vt = np.asarray([parse_corner(c, levels, prefix) for c in corners],
                    dtype=np.float32)  # (V, level_value)

    ref_keys: "dict[int, str] | None" = None
    strip_idx: "bool | None" = None        # decided once, from the first corner
    slack = arrival = required = si_label = None
    stage_id: "dict[tuple[int, int, str], int]" = {}
    stage_meta: "list[tuple[int, int, str]]" = []
    aggr_id: "dict[tuple[int, str], int]" = {}
    aggr_meta: "list[list[str]]" = []
    vwin_c: "list[dict]" = []
    adata_c: "list[dict]" = []
    arc_delta_c: "list[dict]" = []

    idx_order: "list[int]" = []
    stage_seqs: "dict[int, tuple]" = {}

    for ci, corner in enumerate(corners):
        ann_all = parse_annotated(ann_by_corner[corner], with_stages=(corner == ref_corner))
        _assert_parsed(ann_all, ann_by_corner[corner])
        # Blocks with no timing result at this corner stay in `ann_all` with
        # slack = NaN; they are dropped after the loop (see the intersection
        # pass below), not here, so the same path list can be walked everywhere.
        ann = ann_all
        xt = parse_crosstalk(xt_by_corner[corner]) if xt_by_corner else None
        if strip_idx is None:
            strip_idx = choose_key_mode(ann, cfg)
        keyf = norm_path_key if strip_idx else (lambda k: k.strip())

        keys_ann = {i: keyf(p.key) for i, p in ann.items()}
        if xt is not None:
            keys_xt = {i: keyf(p.key) for i, p in xt.items()}
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

        vw: "dict[tuple[int, int, str], tuple[float, float]]" = {}
        ad: "dict[tuple[int, int], tuple]" = {}
        dl: "dict[tuple[int, int, str], float]" = {}
        for r, idx in enumerate(idx_order):
            pa = ann[idx]
            if pa.slack != pa.slack:      # unresolved at this corner -> leave NaN
                continue
            px = xt[idx] if xt is not None else None
            if px is not None:
                assert abs(pa.slack - px.slack) < 5e-5, \
                    f"I3: {corner} idx={idx}: slack {pa.slack} vs {px.slack}"
            slack[r, ci] = pa.slack
            arrival[r, ci] = pa.arrival
            required[r, ci] = pa.required
            launch_clk[r, ci] = pa.launch_clk
            capture_clk[r, ci] = pa.capture_clk
            lib_check_time[r, ci] = pa.lib_check_time
            si_label[r, ci] = px.si_total() if px is not None else 0.0
            if corner == ref_corner:
                path_sig[r] = path_signature(pa.stages)
                stage_seqs[r] = stage_sequence(pa.stages)

            for arc in (px.arcs if px is not None else ()):
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

    # ---- INTERSECTION PASS ---------------------------------------------------
    # A union-then-re-measure flow asks every corner for the SAME path list, but
    # `report_timing` may return nothing for a given path at a given corner. The
    # model needs each path measured at EVERY corner (it fits a polynomial per
    # path over the corner grid), so keep the intersection and say exactly what
    # was dropped -- silently training on a thinner set is the failure mode to
    # avoid here.
    resolved = ~np.isnan(slack).any(axis=1)
    if not resolved.all():
        keep = np.where(resolved)[0]
        n_before = len(idx_order)
        per_corner = np.isnan(slack).sum(axis=0)
        worst = int(np.argmax(per_corner))
        examples = [ref_keys[idx_order[r]] for r in np.where(~resolved)[0][:3]]
        print(f"[PATHS] keeping only paths measured at every corner: "
              f"{n_before} -> {len(keep)} (dropped {n_before - len(keep)}). "
              f"Worst corner = {corners[worst]} with {int(per_corner[worst])} "
              f"unresolved. e.g. {examples}", flush=True)
        assert len(keep) > 0, (
            "not a single path was measured at every corner.\n"
            "  That means the fixed-path list resolved differently per corner --\n"
            "  check that the second-pass re-measurement ran over every corner\n"
            "  with the same fixed_paths list.")

        old2new = np.full(len(idx_order), -1, np.int64)
        old2new[keep] = np.arange(len(keep))
        slack, arrival, required = slack[keep], arrival[keep], required[keep]
        launch_clk, capture_clk = launch_clk[keep], capture_clk[keep]
        lib_check_time, si_label = lib_check_time[keep], si_label[keep]
        path_sig = path_sig[keep]
        idx_order = [idx_order[r] for r in keep]
        stage_seqs = {new: stage_seqs[int(old)] for new, old in enumerate(keep)}

        # SI stages point at path rows -- subset and renumber them too
        sk = np.where(old2new[stage_path] >= 0)[0] if S else np.array([], int)
        stage_path = old2new[stage_path[sk]].astype(np.int32)
        stage_seg, n_aggr = stage_seg[sk], n_aggr[sk]
        vwin, arc_delta = vwin[sk], arc_delta[sk]
        abump, awin, aslew, acc = abump[sk], awin[sk], aslew[sk], acc[sk]
        S = len(sk)

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
