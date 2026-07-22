#!/usr/bin/env python3
"""Multi-path PT vs SPICE summary (one row per path). ASCII-only for aligned monospace.

For each path dir p{P} under --root, reads:
  s1/path{P}_si_off.rpt, s1/path{P}_si_on.rpt      (PT cell/net)
  p{P}_base/pt_vs_native_stage_compare.csv          (SPICE full-path base cell/net)
  s3/ac.csv                                         (arc-align crosstalk delta, PT arc delta)

Columns: base cell (PT|SPICE|gap%), SI-on net (PT|SPICE re-attributed|repro%), total (PT|SPICE|%).
Writes summary_<name>.md and .csv; prints aligned table.
"""
import argparse, csv, re, os


def pt_cn(fn):
    cell = net = 0.0
    for ln in open(fn, errors="ignore"):
        m = re.match(r"\s+(\S+/\S+)\s+\(\S+\)\s+<-\s+([\d.]+)\s+([\d.]+)\s+&?\s*([\d.]+)\s+([rf])", ln)
        if m:
            pin = m.group(1); incr = float(m.group(3)) * 1000
            if re.search(r"/(X|Y|Z|Q|QN|CO|CON)$", pin): cell += incr
            elif re.search(r"/(A|A\d|B|B\d|C|D|D\d|I|SI|CI)\d*$", pin): net += incr
    return cell, net


def g(r, k):
    v = r.get(k, "")
    try: return float(v)
    except (TypeError, ValueError): return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--paths", required=True, help="comma list, e.g. 146,153,366")
    ap.add_argument("--labels", default="", help="comma list of ASCII labels (same order)")
    ap.add_argument("--name", default="summary")
    args = ap.parse_args()

    ids = args.paths.split(",")
    labs = args.labels.split(",") if args.labels else [""] * len(ids)
    labmap = {i: (l or f"path{i}") for i, l in zip(ids, labs)}

    rows = []
    for P in ids:
        d = os.path.join(args.root, f"p{P}")
        oc, on = pt_cn(f"{d}/s1/path{P}_si_off.rpt")
        nc, nn = pt_cn(f"{d}/s1/path{P}_si_on.rpt")
        fp = list(csv.DictReader(open(f"{d}/p{P}_base/pt_vs_native_stage_compare.csv")))
        fpc = sum(g(r, "spice_cell_ps") for r in fp)
        fpn = sum(g(r, "spice_net_ps") for r in fp)
        ar = list(csv.DictReader(open(f"{d}/s3/ac.csv")))
        ptd = sum(g(r, "pt_arc_delta_selected_ps") for r in ar)
        xt = sum(g(r, "stage_delta_worst_ps") for r in ar)
        sp_net = fpn + xt
        pt_tot, sp_tot = nc + nn, fpc + sp_net
        rows.append(dict(P=P, lab=labmap[P],
                         pt_cell=nc, sp_cell=fpc, cellg=100 * (fpc - oc) / oc if oc else 0,
                         pt_net=nn, sp_net=sp_net, repro=100 * xt / ptd if ptd else 0,
                         pt_tot=pt_tot, sp_tot=sp_tot, totp=100 * sp_tot / pt_tot if pt_tot else 0))

    W = max([len(r["lab"]) for r in rows] + [8])
    def fmt(r):
        return (f"{r['P']:<6}{r['lab']:<{W}} | {r['pt_cell']:>7.1f} {r['sp_cell']:>7.1f} {r['cellg']:>+4.0f}%"
                f" | {r['pt_net']:>7.1f} {r['sp_net']:>7.1f} {r['repro']:>4.0f}%"
                f" | {r['pt_tot']:>8.1f} {r['sp_tot']:>8.1f} {r['totp']:>4.0f}%")
    head = (f"{'path':<6}{'struct':<{W}} | {'PTcell':>7} {'SPcell':>7} {'gap':>5}"
            f" | {'PTnet':>7} {'SPnet':>7} {'repro':>5} | {'PTtot':>8} {'SPtot':>8} {'%':>5}")
    sep = "-" * len(head)
    title = "SPICE cell = full-path base | SPICE net = re-attributed SI-est   [ps]"
    foot = "gap=SPICE base cell vs PT-off cell | repro=SPICE xtalk vs PT-arc | %=SPtot vs PT SI-on"
    table_lines = [title, head, sep] + [fmt(r) for r in rows] + [sep, foot]
    for ln in table_lines: print(ln)

    # md: 정렬된 텍스트표 그대로 (코드블록으로 monospace 유지)
    with open(os.path.join(args.root, f"summary_{args.name}.md"), "w") as fo:
        fo.write("```text\n")
        fo.write("\n".join(table_lines))
        fo.write("\n```\n")
    # txt: 순수 정렬 텍스트
    with open(os.path.join(args.root, f"summary_{args.name}.txt"), "w") as fo:
        fo.write("\n".join(table_lines) + "\n")
    # csv
    with open(os.path.join(args.root, f"summary_{args.name}.csv"), "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["path", "struct", "pt_cell", "spice_cell", "cell_gap_pct",
                    "pt_net_sion", "spice_net_siest", "xtalk_repro_pct",
                    "pt_total", "spice_total", "total_pct"])
        for r in rows:
            w.writerow([r["P"], r["lab"], f"{r['pt_cell']:.2f}", f"{r['sp_cell']:.2f}", f"{r['cellg']:.1f}",
                        f"{r['pt_net']:.2f}", f"{r['sp_net']:.2f}", f"{r['repro']:.0f}",
                        f"{r['pt_tot']:.2f}", f"{r['sp_tot']:.2f}", f"{r['totp']:.1f}"])
    print(f"\nsaved: summary_{args.name}.md , summary_{args.name}.csv")


if __name__ == "__main__":
    main()
