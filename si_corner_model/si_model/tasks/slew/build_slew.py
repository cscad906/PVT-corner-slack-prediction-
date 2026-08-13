"""Build ``slew.npz`` for ONE model instance (``task: slew`` in config.yaml).

Targets, per (path, corner):
  - launch_slew    : Trans on the launch flop's first data pin (<startpoint>/QN|/Q)
  - endpoint_cap   : Cap of the (net) line just before the endpoint /D

Slew is analysis-independent (the same launch transition appears in setup and
hold reports), so it needs no separate setup/hold split -- one model per
(design, temperature), same as slack. Slew is PREDICTED (V-dependent); cap is
not trained but fetched from a same-level neighbour (V-independent) -- see the
trainer. No crosstalk is used.

    bash scripts/run.sh build            # when config.yaml has task: slew
"""
import argparse
import os
import sys

import numpy as np

from si_model.parsing.annotated import configure_pins, parse_annotated
from si_model.parsing.build_dataset import (EDGE_FEAT_NAMES, NODE_FEAT_NAMES,
                                            SIG_NAMES, _assert_parsed,
                                            choose_key_mode,
                                            autofit_cell_taxonomy,
                                            configure_cell_taxonomy,
                                            path_signature, stage_sequence)
from si_model.parsing.discovery import corner_levels, discover as _discover
from si_model.parsing.keys import corner_label, norm_path_key, parse_corner


def load_config(fp: str) -> dict:
    from si_model.config import load_config as _lc
    return _lc(fp)                       # engine-schema YAML (escape hatch)


def discover(cfg: dict):
    """Return (corners, ann_by_corner). Slew needs NO crosstalk, so discovery
    runs annotated-only under either directory layout (see parsing/discovery)."""
    corners, ann_by, _ = _discover(cfg, need_crosstalk=False)
    return corners, ann_by


def slew_cap_of(path) -> "tuple[float, float]":
    """(launch_slew, endpoint_cap) from a parsed path's stages."""
    data_cells = [s for s in path.stages if s.segment == "data" and s.kind == "cell"]
    data_nets = [s for s in path.stages if s.segment == "data" and s.kind == "net"]
    slew = data_cells[0].trans if data_cells else np.nan   # first data pin = FF /QN
    cap = data_nets[-1].cap if data_nets else np.nan       # net just before /D
    return float(slew), float(cap)


def build(cfg: dict) -> str:
    ref_corner = cfg["data"]["ref_corner"]
    out_fp = cfg["data"]["cache"]
    configure_cell_taxonomy(cfg)   # slack 빌더와 동일한 설정을 쓴다
    configure_pins(cfg)
    corners, ann_by = discover(cfg)
    assert ref_corner in corners, f"ref {ref_corner} not in {corners[:3]}..."
    C = len(corners)
    levels = corner_levels(cfg)
    prefix = cfg["data"].get("corner_prefix", "TT")
    vt = np.asarray([parse_corner(c, levels, prefix) for c in corners], dtype=np.float32)

    ref_keys = None
    strip_idx = None                 # decided once, from the first corner
    slew = cap = None
    idx_order = []
    stage_seqs = {}
    path_sig = None

    for ci, corner in enumerate(corners):
        # every corner needs full stages (launch slew + endpoint cap are per-corner)
        ann = parse_annotated(ann_by[corner], with_stages=True)
        _assert_parsed(ann, ann_by[corner])
        if ci == 0:
            autofit_cell_taxonomy(ann)   # same rule as the slack builder
        if strip_idx is None:
            strip_idx = choose_key_mode(ann, cfg)
        keyf = norm_path_key if strip_idx else (lambda k: k.strip())
        keys = {i: keyf(p.key) for i, p in ann.items()}
        if ref_keys is None:
            ref_keys = keys
            idx_order = sorted(ref_keys)
            N = len(idx_order)
            slew = np.full((N, C), np.nan, np.float64)
            cap = np.full((N, C), np.nan, np.float64)
            path_sig = np.zeros((N, len(SIG_NAMES)), np.float32)
        else:
            assert keys == ref_keys, f"key mismatch at {corner}"
        for r, idx in enumerate(idx_order):
            p = ann[idx]
            if p.slack != p.slack:       # unresolved at this corner -> leave NaN
                continue
            s, c = slew_cap_of(p)
            slew[r, ci] = s
            cap[r, ci] = c
            if corner == ref_corner:
                path_sig[r] = path_signature(p.stages)
                stage_seqs[r] = stage_sequence(p.stages)
        print(f"[{ci+1:2d}/{C}] {corner}: paths={len(ann)}", flush=True)

    # keep only paths measured at EVERY corner (see build_dataset's intersection pass)
    ok = ~np.isnan(slew).any(axis=1)
    if not ok.all():
        keep = np.where(ok)[0]
        assert len(keep) > 0, "not a single path was measured at every corner"
        print(f"[PATHS] keeping only paths measured at every corner: "
              f"{len(idx_order)} -> {len(keep)}", flush=True)
        slew, cap, path_sig = slew[keep], cap[keep], path_sig[keep]
        idx_order = [idx_order[r] for r in keep]
        stage_seqs = {new: stage_seqs[int(old)] for new, old in enumerate(keep)}

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

    # slew/cap should be finite everywhere; report coverage
    print(f"slew finite {np.isfinite(slew).mean():.3f}  cap finite {np.isfinite(cap).mean():.3f}")

    # optional PURE-INFERENCE corners (see build_dataset): NaN measurements,
    # measured=False, prediction-only output.
    measured = np.ones(C, bool)
    qcs = cfg["data"].get("query_corners", [])
    if qcs:
        qlabs = [q if isinstance(q, str) else corner_label(float(q[0]), q[1], prefix)
                 for q in qcs]
        qvt = np.asarray([parse_corner(l, levels, prefix) for l in qlabs], np.float32)
        Q = len(qlabs)
        slew = np.concatenate([slew, np.full((N, Q), np.nan, slew.dtype)], 1)
        cap = np.concatenate([cap, np.full((N, Q), np.nan, cap.dtype)], 1)
        corners = list(corners) + qlabs
        vt = np.concatenate([vt, qvt], 0)
        measured = np.concatenate([measured, np.zeros(Q, bool)])
        C += Q
        print(f"[QUERY] appended {Q} unmeasured query corners: {qlabs}", flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(out_fp)), exist_ok=True)
    np.savez_compressed(
        out_fp,
        measured=measured,
        corners=np.asarray(corners), vt=vt,
        path_keys=np.asarray([ref_keys[i] for i in idx_order]),
        path_idx=np.asarray(idx_order, np.int32),
        slew=slew, cap=cap,
        node_fam=node_fam, node_feat=node_feat, edge_feat=edge_feat,
        node_mask=node_mask, fam_vocab=np.asarray(vocab),
        node_feat_names=np.asarray(NODE_FEAT_NAMES),
        edge_feat_names=np.asarray(EDGE_FEAT_NAMES),
        path_sig=path_sig, sig_names=np.asarray(SIG_NAMES),
    )
    print(f"wrote {out_fp}: N={N} C={C}")
    return out_fp


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    args = ap.parse_args(argv)
    build(load_config(args.config))


if __name__ == "__main__":
    sys.exit(main())
