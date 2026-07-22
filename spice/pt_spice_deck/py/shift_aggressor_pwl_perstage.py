#!/usr/bin/env python3
"""Per-stage drift-compensated aggressor shift.

Each aggressor PWL is shifted by -(cycle + drift(victim stage)) where drift(k)
= PT SI-off arrival - SPICE quiet arrival at stage k's receiver pin. Aggressors
coupling to multiple victim nets use the mean drift of those stages. Sources
whose driver net cannot be mapped fall back to --default-extra-ps.

Inputs:
  --stim         original (unshifted) stimulus
  --map-json     {'victim_stage': {net: stage}, 'aggr_victims': {aggnet: [vnets]}}
  --drift-json   {stage(str): drift_ps}
  --cycle-ns     base cycle shift (default 2.0)
  --default-extra-ps  fallback drift for unmapped sources (default 50)
  --min-first-ns only shift sources first switching at/after this (default 4.8)
"""
import argparse
import json
import re
from pathlib import Path

TIME_TOKEN = re.compile(r"(\d+(?:\.\d+)?)ns")
SRC_COMMENT = re.compile(r"^\* voltage source for (\S+) \((victim|aggressor)\)")
DRV_COMMENT = re.compile(r"^\* aggressor driver net is (\S+)")
ACTIVE_PWL = re.compile(r"^[vV]\S+\s+\S+\s+\S+\s+pwl\(", re.IGNORECASE)


def shift_statement(stmt, shift_ns):
    out = []
    first = [True]
    def repl(m):
        t = float(m.group(1))
        if first[0]:
            first[0] = False
            if t == 0.0:
                return m.group(0)
        nt = t - shift_ns
        assert nt > 0, f"negative time {nt}"
        return f"{nt:.6f}ns"
    for l in stmt:
        out.append(TIME_TOKEN.sub(repl, l))
    return out


def first_transition(stmt):
    ts = []
    for l in stmt:
        ts += [float(m.group(1)) for m in TIME_TOKEN.finditer(l)]
    ts = [t for t in ts if t > 0]
    return min(ts) if ts else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stim", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--map-json", required=True)
    ap.add_argument("--drift-json", required=True)
    ap.add_argument("--cycle-ns", type=float, default=2.0)
    ap.add_argument("--default-extra-ps", type=float, default=50.0)
    ap.add_argument("--min-first-ns", type=float, default=4.8)
    a = ap.parse_args()

    mp = json.load(open(a.map_json))
    victim_stage = mp["victim_stage"]
    aggr_victims = mp["aggr_victims"]
    drift = {int(k): v for k, v in json.load(open(a.drift_json)).items()}

    def extra_ps_for(aggnet):
        vs = aggr_victims.get(aggnet)
        if not vs:
            return None
        ds = [drift[victim_stage[v]] for v in vs if v in victim_stage and victim_stage[v] in drift]
        return sum(ds) / len(ds) if ds else None

    lines = Path(a.stim).read_text().splitlines(keepends=True)
    out = []
    i = 0
    in_aggr = False
    cur_drv = cur_src = None
    stats = {"mapped": 0, "fallback": 0, "early": 0, "kept": 0}
    shift_hist = {}
    while i < len(lines):
        l = lines[i]
        m = SRC_COMMENT.match(l)
        if m:
            in_aggr = m.group(2) == "aggressor"
            cur_src = m.group(1)
            cur_drv = None
        m = DRV_COMMENT.match(l)
        if m:
            cur_drv = m.group(1)
        if in_aggr and ACTIVE_PWL.match(l):
            stmt = [l]
            j = i + 1
            while j < len(lines) and lines[j].startswith("+"):
                stmt.append(lines[j])
                j += 1
            ft = first_transition(stmt)
            if ft is None or ft < a.min_first_ns:
                stats["early"] += 1
                out.extend(stmt)
                i = j
                continue
            node = stmt[0].split()[1]
            base = re.sub(r"_P_SPC\d+_P_SPC\d+$", "", node)
            extra = None
            for key in (cur_drv, cur_src, node, base):
                if key is not None:
                    extra = extra_ps_for(key)
                    if extra is not None:
                        break
            if extra is None:
                extra = a.default_extra_ps
                stats["fallback"] += 1
            else:
                stats["mapped"] += 1
            sh = a.cycle_ns + extra / 1000.0
            b = round(sh, 3)
            shift_hist[b] = shift_hist.get(b, 0) + 1
            out.extend(shift_statement(stmt, sh))
            i = j
            continue
        out.append(l)
        i += 1

    Path(a.out).write_text("".join(out))
    print(f"mapped={stats['mapped']} fallback={stats['fallback']} early(unshifted)={stats['early']}")
    lo, hi = min(shift_hist), max(shift_hist)
    print(f"shift range: -{hi}ns .. -{lo}ns  distinct values: {len(shift_hist)}")


if __name__ == "__main__":
    main()
