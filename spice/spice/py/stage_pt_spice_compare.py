#!/usr/bin/env python3
"""Stage-level PT vs SPICE cell/net comparison for a full-flow path.

Joins two per-stage sources by stage_idx (verified same physical stage via to-pin):
  - full-path base:  pt_vs_native_stage_compare.csv  (pt_cell/net, spice base cell/net)
  - arc-align:       ac.csv                            (stage crosstalk delta, PT arc delta)

Columns per stage:
  Cell        : PT (base, delay-only) | SPICE base | Δ = SPICE-PT
  Net (SI-on) : PT SI-on (base+xtalk) | SPICE SI-est (base+re-attributed xtalk) | Δ
  xtalk       : PT arc crosstalk on that stage (reference)

Prints a screen table (top-N by |cell Δ|+|net Δ| + Σ) and writes a full-stage CSV.
"""
import argparse, csv, sys


def f(r, k):
    v = r.get(k, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def pctf(d, base, tiny=0.5):
    """d/base as % WITH the % sign, guarded: '-' when the PT base is ~0 (percent meaningless)."""
    if abs(base) < tiny:
        return "-"
    v = 100.0 * d / base
    if abs(v) >= 999.5:
        return ("+999+%" if v > 0 else "-999+%")
    return f"{v:+.1f}%"


def pctv(d, base, tiny=0.5):
    """Numeric % for CSV ('' when base ~0)."""
    return "" if abs(base) < tiny else f"{100.0*d/base:.1f}"


def load(fullpath_csv, arc_csv, interp_csv=None):
    fp = {r["stage_idx"]: r for r in csv.DictReader(open(fullpath_csv))}
    ar = {r["stage_idx"]: r for r in csv.DictReader(open(arc_csv))}
    # optional: replace the PT reference with an interpolated one (unseen corner,
    # from interp_pt_corner.py) — SPICE columns stay from the target run
    it = {r["stage_idx"]: r for r in csv.DictReader(open(interp_csv))} if interp_csv else {}
    rows = []
    for k in sorted(fp, key=lambda x: int(x)):
        a = ar.get(k, {})
        ref = it.get(k, fp[k]) if it else fp[k]
        pt_cell = f(ref, "pt_cell_ps")
        sp_cell = f(fp[k], "spice_cell_ps")
        pt_net_on = f(ref, "pt_net_ps")            # PT SI-on net (base+xtalk)
        sp_net_base = f(fp[k], "spice_net_ps")     # SPICE base net (quiet)
        xtalk_sp = f(a, "stage_delta_worst_ps")    # SPICE crosstalk (worst)
        xtalk_pt = f(a, "pt_arc_delta_selected_ps")
        sp_net_est = sp_net_base + xtalk_sp         # re-attributed SI-est net
        to = (fp[k].get("pt_cell_to") or fp[k].get("spice_cell_to") or "")
        rows.append(dict(stg=k, to="/".join(to.split("/")[-2:]),
                         pt_cell=pt_cell, sp_cell=sp_cell, cell_d=sp_cell - pt_cell,
                         pt_net=pt_net_on, sp_net=sp_net_est, net_d=sp_net_est - pt_net_on,
                         xtalk_pt=xtalk_pt, xtalk_sp=xtalk_sp))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fullpath", required=True)
    ap.add_argument("--arc", required=True)
    ap.add_argument("--interp", help="(옵션) interp_pt_corner.py의 보간 reference CSV — PT 컬럼을 보간값으로 교체")
    ap.add_argument("--title", default="")
    ap.add_argument("--out-csv")
    ap.add_argument("--top", type=int, default=15, help="screen: show top-N stages by |cellΔ|+|netΔ| (0=all)")
    args = ap.parse_args()

    rows = load(args.fullpath, args.arc, args.interp)

    # full CSV
    if args.out_csv:
        with open(args.out_csv, "w", newline="") as fo:
            w = csv.writer(fo)
            w.writerow(["stage_idx", "to_pin",
                        "pt_cell_ps", "spice_cell_ps", "cell_delta_ps",
                        "pt_net_sion_ps", "spice_net_siest_ps", "net_delta_ps",
                        "stage_delta_ps"])
            for r in rows:
                sd = r["cell_d"] + r["net_d"]
                w.writerow([r["stg"], r["to"],
                            f"{r['pt_cell']:.3f}", f"{r['sp_cell']:.3f}", f"{r['cell_d']:.3f}",
                            f"{r['pt_net']:.3f}", f"{r['sp_net']:.3f}", f"{r['net_d']:.3f}",
                            f"{sd:.3f}"])

    # ASCII-only aligned table (both screen and file). CJK/arrows break monospace width.
    L = []
    L.append(f"{args.title} -- stage cell/net  [ps]")
    # group header hugging the visible (right-aligned) numbers of each block:
    #   Cell bracket ends at cell-d col(46), Net bracket ends at net-d col(70), stage label over d(SP-PT)/d%
    L.append(" " * 29 + "|----- Cell -----|" + " " * 6 + "|-- Net(SI-on) --|" + "  " + "stage(cell+net)")
    L.append(f"{'stg':>3} {'to_pin':<20} {'PT':>7} {'SPICE':>7} {'d':>6}  "
             f"{'PT':>7} {'SPICE':>7} {'d':>6} {'d(SP-PT)':>9} {'d%':>8}")
    line = "-" * 90
    L.append(line)
    show = rows if args.top == 0 else sorted(rows, key=lambda r: abs(r["cell_d"]) + abs(r["net_d"]), reverse=True)[:args.top]
    show = sorted(show, key=lambda r: int(r["stg"]))
    for r in show:
        stage_d = r["cell_d"] + r["net_d"]          # per-stage total (cell+net) delay diff, SPICE-PT
        # d% is reported only on the SUM row (per-stage % is noisy on small bases)
        L.append(f"{r['stg']:>3} {r['to'][:20]:<20} {r['pt_cell']:>7.1f} {r['sp_cell']:>7.1f} {r['cell_d']:>+6.1f}  "
                 f"{r['pt_net']:>7.1f} {r['sp_net']:>7.1f} {r['net_d']:>+6.1f} "
                 f"{stage_d:>+9.1f}")
    L.append(line)
    S = lambda k: sum(r[k] for r in rows)
    tot_d = S('cell_d') + S('net_d')
    tot_pt = S('pt_cell') + S('pt_net')
    L.append(f"{'SUM':>3} {'(all %d stg)'%len(rows):<20} {S('pt_cell'):>7.1f} {S('sp_cell'):>7.1f} {S('cell_d'):>+6.1f}  "
             f"{S('pt_net'):>7.1f} {S('sp_net'):>7.1f} {S('net_d'):>+6.1f} "
             f"{tot_d:>+9.1f} {pctf(tot_d, tot_pt):>8}")
    L.append(f"    d% = d(SP-PT) / PT stage total (cell+net) x100  |  path total: PT {tot_pt:.1f} -> SPICE {tot_pt+tot_d:.1f} ps")
    if args.top and len(rows) > args.top:
        L.append(f"    (screen = top {args.top} by |d|; SUM/CSV = all {len(rows)} stages)")

    for ln in L:
        print(ln)

    if args.out_csv:
        base = args.out_csv.rsplit(".", 1)[0]
        with open(base + ".md", "w") as fo:
            fo.write("```text\n" + "\n".join(L) + "\n```\n")
        with open(base + ".txt", "w") as fo:
            fo.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
