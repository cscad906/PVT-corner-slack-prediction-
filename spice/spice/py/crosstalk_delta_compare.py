#!/usr/bin/env python3
"""Per-stage CROSSTALK DELTA comparison: PT (SI-off vs SI-on) vs HSPICE (quiet vs align-aggressor).

This is the crosstalk-focused view (complements stage_pt_spice_compare.py which shows absolute cell/net):
  PT   crosstalk delta = SI-on stage - SI-off stage        (= pt_arc_delta_selected_ps)
  SPICE crosstalk delta = align(worst) stage - quiet stage (aggressors aligned worst-case)

Reads ac.csv (arc-align compare) which carries both PT SI values and HSPICE quiet/align per stage.
Optional --fullpath (pt_vs_native_stage_compare.csv) only for nicer to_pin labels.

Columns per stage:
  PT     : SIoff  SIon  dPT      (dPT = SIon - SIoff = PT crosstalk)
  HSPICE : quiet  align dSP      (dSP = align - quiet = SPICE crosstalk, worst-aligned)
  dSP-dPT: how much SPICE over/under-reproduces the crosstalk that stage
SUM row also prints repro% = total dSP / total dPT.
"""
import argparse, csv


def f(r, k):
    v = r.get(k, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load(arc_csv, fullpath_csv, use_center):
    fp = {}
    if fullpath_csv:
        try:
            fp = {r["stage_idx"]: r for r in csv.DictReader(open(fullpath_csv))}
        except OSError:
            fp = {}
    rows = []
    for a in csv.DictReader(open(arc_csv)):
        k = a["stage_idx"]
        si_on = f(a, "pt_si_stage_ps")               # PT SI-on stage delay
        d_pt = f(a, "pt_arc_delta_selected_ps")      # PT crosstalk delta (SI-on - SI-off)
        si_off = si_on - d_pt                        # PT SI-off = SI-on - crosstalk
        quiet = f(a, "quiet_stage_ps")               # HSPICE quiet
        align = f(a, "align_stage_center_ps" if use_center else "align_stage_worst_ps")
        d_sp = align - quiet                         # SPICE crosstalk delta
        # to_pin label
        to = ""
        if k in fp:
            to = (fp[k].get("pt_cell_to") or fp[k].get("spice_cell_to") or "")
            to = "/".join(to.split("/")[-2:])
        if not to:
            to = (a.get("victim_net") or "")[:20]
        rows.append(dict(stg=k, to=to, si_off=si_off, si_on=si_on, d_pt=d_pt,
                         quiet=quiet, align=align, d_sp=d_sp, dd=d_sp - d_pt))
    rows.sort(key=lambda r: int(r["stg"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arc", required=True, help="ac.csv (arc-align compare)")
    ap.add_argument("--fullpath", help="pt_vs_native_stage_compare.csv (for to_pin labels)")
    ap.add_argument("--title", default="")
    ap.add_argument("--out-csv")
    ap.add_argument("--center", action="store_true", help="use align CENTER instead of WORST")
    args = ap.parse_args()

    rows = load(args.arc, args.fullpath, args.center)
    aligntag = "center" if args.center else "worst"

    if args.out_csv:
        with open(args.out_csv, "w", newline="") as fo:
            w = csv.writer(fo)
            w.writerow(["stage_idx", "to_pin",
                        "pt_si_off_ps", "pt_si_on_ps", "pt_xtalk_delta_ps",
                        "hspice_quiet_ps", f"hspice_align_{aligntag}_ps", "hspice_xtalk_delta_ps",
                        "xtalk_delta_diff_ps"])
            for r in rows:
                w.writerow([r["stg"], r["to"],
                            f"{r['si_off']:.3f}", f"{r['si_on']:.3f}", f"{r['d_pt']:.3f}",
                            f"{r['quiet']:.3f}", f"{r['align']:.3f}", f"{r['d_sp']:.3f}",
                            f"{r['dd']:.3f}"])

    L = []
    L.append(f"{args.title} -- crosstalk delta: PT(SIon-SIoff) vs HSPICE(align_{aligntag}-quiet)  [ps]")
    L.append(" " * 25 + "|------- PT -------|      |----- HSPICE -----|")
    L.append(f"{'stg':>3} {'to_pin':<20} {'SIoff':>7} {'SIon':>7} {'dPT':>6}  "
             f"{'quiet':>7} {'align':>7} {'dSP':>6} {'dSP-dPT':>8}")
    line = "-" * 84
    L.append(line)
    for r in rows:
        flag = "  <-xt" if r["d_pt"] > 5 else ""
        L.append(f"{r['stg']:>3} {r['to'][:20]:<20} {r['si_off']:>7.1f} {r['si_on']:>7.1f} {r['d_pt']:>+6.1f}  "
                 f"{r['quiet']:>7.1f} {r['align']:>7.1f} {r['d_sp']:>+6.1f} {r['dd']:>+8.1f}{flag}")
    L.append(line)
    S = lambda k: sum(r[k] for r in rows)
    tdpt, tdsp = S("d_pt"), S("d_sp")
    repro = 100 * tdsp / tdpt if tdpt else 0
    L.append(f"{'SUM':>3} {'(all %d stg)'%len(rows):<20} {S('si_off'):>7.1f} {S('si_on'):>7.1f} {tdpt:>+6.1f}  "
             f"{S('quiet'):>7.1f} {S('align'):>7.1f} {tdsp:>+6.1f} {tdsp-tdpt:>+8.1f}")
    L.append(f"    crosstalk repro = HSPICE dSP / PT dPT = {tdsp:.1f} / {tdpt:.1f} = {repro:.0f}%")

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
