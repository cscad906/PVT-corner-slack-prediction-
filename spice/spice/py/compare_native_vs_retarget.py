#!/usr/bin/env python3
"""Validate the b-1 retarget (reference-slew reuse) against a NATIVE target-corner deck.

NATIVE   = PT generated the arc-align deck with the TARGET-corner Liberty
           -> true target-corner aggressor slew + true alignment + true PT crosstalk (dPT)
RETARGET = reference(0.8V) arc-align deck, voltage-only retarget (k_slew=1)
           -> reference aggressor slew reused; its ac.csv PT column is STALE (reference corner)

So the PT reference (dPT) must come from the NATIVE ac.csv for BOTH, otherwise repro% is
computed against the reference-corner PT and comes out inflated.

Usage:
  compare_native_vs_retarget.py --native <native>/s3/ac.csv --retarget <ret>/s3/ac.csv \
      --title "p146 @ 0.78V" --out-csv <dir>/native_vs_retarget_p146.csv
"""
import argparse, csv


def load(fn):
    d = {}
    for x in csv.DictReader(open(fn)):
        if (x.get("status", "") or "").upper() not in ("PASS", "OK", ""):
            continue
        num = lambda k: (float(x.get(k) or 0) if x.get(k) not in (None, "") else 0.0)
        q, a = num("quiet_stage_ps"), num("align_stage_worst_ps")
        d[x["stage_idx"]] = dict(pt=num("pt_arc_delta_selected_ps"), q=q, a=a, d=a - q,
                                 net=(x.get("victim_net") or "")[:18])
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", required=True, help="native target-corner ac.csv (true PT + true slew)")
    ap.add_argument("--retarget", required=True, help="b-1 retarget ac.csv (reference slew reused)")
    ap.add_argument("--title", default="")
    ap.add_argument("--out-csv")
    args = ap.parse_args()

    nat, ret = load(args.native), load(args.retarget)
    ks = sorted([k for k in nat if k in ret], key=int)

    L = []
    L.append(f"{args.title}  --  aggressor slew: NATIVE(true corner) vs RETARGET(reference reuse)  [ps]")
    L.append("  PT dPT = TRUE target-corner PT crosstalk (from the native deck) -- the corrected reference")
    L.append(f"{'stg':>3} {'victim':<18} {'PT dPT':>7} | {'NAT dSP':>8} {'RET dSP':>8} {'RET-NAT':>8} | {'NAT%':>6} {'RET%':>6}")
    line = "-" * 88
    L.append(line)
    pf = lambda v, b: (f"{100*v/b:.0f}%" if b > 0.5 else "-")
    sp = sn = sr = 0.0
    for k in ks:
        n, r = nat[k], ret[k]
        sp += n["pt"]; sn += n["d"]; sr += r["d"]
        L.append(f"{k:>3} {n['net']:<18} {n['pt']:>7.1f} | {n['d']:>8.1f} {r['d']:>8.1f} "
                 f"{r['d']-n['d']:>+8.1f} | {pf(n['d'], n['pt']):>6} {pf(r['d'], n['pt']):>6}")
    L.append(line)
    L.append(f"{'SUM':>3} {'(%d stg)'%len(ks):<18} {sp:>7.1f} | {sn:>8.1f} {sr:>8.1f} {sr-sn:>+8.1f} | "
             f"{100*sn/sp:>5.0f}% {100*sr/sp:>5.0f}%")
    L.append("")
    L.append(f"  NATIVE   (true corner slew) : crosstalk {sn:.1f} ps,  repro = {sn:.1f}/{sp:.1f} = {100*sn/sp:.0f}%")
    L.append(f"  RETARGET (reference reuse)  : crosstalk {sr:.1f} ps,  repro = {sr:.1f}/{sp:.1f} = {100*sr/sp:.0f}%  <- corrected")
    L.append(f"  b-1 reuse error             : {sr-sn:+.1f} ps = {100*(sr-sn)/sn:+.1f}%")
    L.append("")
    L.append("  NOTE: the retarget run's own ac.csv PT column is the REFERENCE-corner value (stale);")
    L.append("        using it as the denominator inflates repro%. This table divides by the native PT.")

    for ln in L:
        print(ln)

    if args.out_csv:
        with open(args.out_csv, "w", newline="") as fo:
            w = csv.writer(fo)
            w.writerow(["stage_idx", "victim_net", "pt_xtalk_true_ps",
                        "native_xtalk_ps", "retarget_xtalk_ps", "retarget_minus_native_ps",
                        "native_repro_pct", "retarget_repro_pct"])
            for k in ks:
                n, r = nat[k], ret[k]
                w.writerow([k, n["net"], f"{n['pt']:.3f}", f"{n['d']:.3f}", f"{r['d']:.3f}",
                            f"{r['d']-n['d']:.3f}",
                            (f"{100*n['d']/n['pt']:.1f}" if n["pt"] > 0.5 else ""),
                            (f"{100*r['d']/n['pt']:.1f}" if n["pt"] > 0.5 else "")])
        base = args.out_csv.rsplit(".", 1)[0]
        with open(base + ".txt", "w") as fo:
            fo.write("\n".join(L) + "\n")
        with open(base + ".md", "w") as fo:
            fo.write("```text\n" + "\n".join(L) + "\n```\n")


if __name__ == "__main__":
    main()
