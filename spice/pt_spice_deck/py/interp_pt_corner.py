#!/usr/bin/env python3
"""Interpolate per-stage PT quantities (cell delay / net delay / out slew) to an
unseen target voltage from TWO bracketing characterized corners.

Physics model (per stage, per quantity):
    y(V) = A / (V - Vth)^alpha        (near-threshold convexity aware)
    alpha = ln(y_lo/y_hi) / ln((V_hi-Vth)/(V_lo-Vth));  y_t = y_hi*((V_hi-Vth)/(V_t-Vth))^alpha
Fallback to linear-in-V when a value is ~0 (e.g. zero net delay).

Validated on 0.8V+0.6V -> 0.7V (p146): cell-delay SUM error -0.3% (Vth=0.45),
per-stage slew mean ~+1.6%.  NOTE: naive linear interpolation is +14~15% off.

Inputs are the flow's pt_vs_native_stage_compare.csv from each corner run.
Output: CSV with interpolated pt_cell_ps / pt_net_ps / pt_out_slew_ps per stage
(usable as a predicted-PT reference when the target-corner Liberty is absent).
Optionally compare a target-corner SPICE base run against this reference.
"""
import argparse, csv, math, os


def load(fn):
    return {int(r["stage_idx"]): r for r in csv.DictReader(open(fn))}


def fnum(r, k):
    try:
        return float(r.get(k) or 0)
    except ValueError:
        return 0.0


def interp(y_hi, y_lo, v_hi, v_lo, v_t, vth):
    """y at v_t from (v_hi,y_hi),(v_lo,y_lo) via A/(V-Vth)^a; linear fallback for ~0."""
    if y_hi <= 0.01 or y_lo <= 0.01:
        # linear in V
        return y_hi + (y_lo - y_hi) * (v_hi - v_t) / (v_hi - v_lo)
    alpha = math.log(y_lo / y_hi) / math.log((v_hi - vth) / (v_lo - vth))
    return y_hi * ((v_hi - vth) / (v_t - vth)) ** alpha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hi-csv", required=True, help="pt_vs_native_stage_compare.csv @ higher V")
    ap.add_argument("--hi-vdd", type=float, required=True)
    ap.add_argument("--lo-csv", required=True, help="pt_vs_native_stage_compare.csv @ lower V")
    ap.add_argument("--lo-vdd", type=float, required=True)
    ap.add_argument("--target-vdd", type=float, required=True)
    ap.add_argument("--vth", type=float, default=0.45,
                    help="threshold-voltage anchor for the model (0.8/0.6->0.7 검증서 0.45 최적; ±0.05 -> ±1~2%%)")
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--spice-csv", help="(옵션) 목표전압 SPICE base run의 CSV — interp reference와 비교 출력")
    args = ap.parse_args()

    vh, vl, vt, vth = args.hi_vdd, args.lo_vdd, args.target_vdd, args.vth
    if not (min(vl, vh) <= vt <= max(vl, vh)):
        print(f"WARNING: target {vt}V is OUTSIDE [{vl},{vh}] -> extrapolation (정확도 저하)")
    hi, lo = load(args.hi_csv), load(args.lo_csv)

    cols = ["pt_cell_ps", "pt_net_ps", "pt_out_slew_ps"]
    rows = []
    for i in sorted(hi):
        if i not in lo:
            continue
        r = {"stage_idx": i,
             "pt_cell_to": hi[i].get("pt_cell_to", ""),
             "pt_cell_from": hi[i].get("pt_cell_from", "")}
        for c in cols:
            r[c] = interp(fnum(hi[i], c), fnum(lo[i], c), vh, vl, vt, vth)
        rows.append(r)

    with open(args.out_csv, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["stage_idx", "pt_cell_from", "pt_cell_to"] + cols)
        for r in rows:
            w.writerow([r["stage_idx"], r["pt_cell_from"], r["pt_cell_to"]] +
                       [f"{r[c]:.3f}" for c in cols])

    sp = load(args.spice_csv) if args.spice_csv and os.path.exists(args.spice_csv) else {}

    # per-stage table (ASCII only, aligned). With --spice-csv adds SPICE base cell + d.
    tc = sum(r["pt_cell_ps"] for r in rows)
    tn = sum(r["pt_net_ps"] for r in rows)
    ts = sum(r["pt_out_slew_ps"] for r in rows)
    print(f"interp PT reference @ {vt}V (from {vh}V+{vl}V, Vth={vth})  [ps]")
    hdr = f"{'stg':>3} {'to_pin':<20} {'cell':>7} {'net':>7} {'slew':>7}"
    if sp:
        hdr += f"  {'SPcell':>7} {'cell_d':>7}"
    print(hdr)
    line = "-" * len(hdr)
    print(line)
    for r in rows:
        to = "/".join(r["pt_cell_to"].split("/")[-2:])[:20]
        ln = (f"{r['stage_idx']:>3} {to:<20} {r['pt_cell_ps']:>7.1f} "
              f"{r['pt_net_ps']:>7.1f} {r['pt_out_slew_ps']:>7.1f}")
        s = sp.get(r["stage_idx"])
        if sp and s:
            sc1 = fnum(s, "spice_cell_ps")
            ln += f"  {sc1:>7.1f} {sc1 - r['pt_cell_ps']:>+7.1f}"
        print(ln)
    print(line)
    sums = f"{'SUM':>3} {'(%d stg)' % len(rows):<20} {tc:>7.1f} {tn:>7.1f} {ts:>7.1f}"
    if sp:
        sc = sum(fnum(sp[i], "spice_cell_ps") for i in sp)
        sums += f"  {sc:>7.1f} {sc - tc:>+7.1f}"
    print(sums)
    print(f"    interp total(cell+net) = {tc+tn:.1f} ps -> {args.out_csv}")
    if sp:
        print(f"    SPICE cell vs interp-PT cell : {100*(sc-tc)/tc:+.1f}%  (목표 Liberty 없이 예측한 PT 기준 대비)")
        print(f"    net 비교는 재귀속 필요 -> stage_detail_interp 표 참고 (raw SPICE net은 비교 불가)")


if __name__ == "__main__":
    main()
