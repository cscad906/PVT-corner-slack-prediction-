#!/usr/bin/env python3
"""Generate per-stage ISOLATED HSPICE cell decks driven with PT's input slew + real load,
correct path pin, to compare SPICE cell delay vs PT CCS cell delay (pure model diff).

For each stage of a path:
  - drive the PATH input pin (cell_from) with a ramp of PT's input slew, correct edge
  - hold other inputs at the non-controlling DC (simple gates only: INV/BUF/ND/NR/AN/OR)
  - load output X with the net lumped cap
  - measure cell delay (input 50% -> output 50%)
Complex gates (MUX/AOI/OAI/AO/OA/B-input/flop) are SKIPPED (need manual sensitization).

Inputs: pt_vs_native_stage_compare.csv + annotated report (cell ref, net cap, out dir).
Outputs: <outdir>/stg_<N>.sp + manifest.csv
"""
import argparse, csv, re, os

MODELCARD = "/home/0Park/SAED14nm_PDK_12142021/SAED14_PDK/hspice/saed14nm.lib"
SPF = "/home/hyunss/thermal_aware_sta/primelib_tt0p7/saed14nm_rvt_with_clksplt_alias.spf"


def parse_spf_pins(spf):
    pins = {}
    for ln in open(spf, errors="ignore"):
        m = re.match(r"\.SUBCKT (SAEDRVT14_\S+)\s+(.*)", ln, re.I)
        if m:
            pins[m.group(1)] = m.group(2).split()
    return pins


def classify(cr):
    """Return (is_simple, invert, noncontrol_volt) or (False,...). noncontrol in {'VDD','VSS'}."""
    core = cr.replace("SAEDRVT14_", "")
    head = core.split("_")[0]
    # single-input gates first (BUF starts with 'B' but is NOT a B-input gate)
    if head.startswith("INV"):
        return (True, True, None)               # single input, inverting
    if head.startswith("BUF"):
        return (True, False, None)              # single input, non-inverting
    if head.endswith("B"):  # inverted input pin (AN2B/ND3B/OR2B ...) -> skip
        return (False, None, None)
    for c in ["MUX", "AOI", "OAI", "AO2", "AO3", "OA2", "OA3", "FDP", "FADD", "DFF", "LAT", "FA", "HA"]:
        if c in core:
            return (False, None, None)
    if head.startswith("ND"):                   # NAND: invert, others=VDD(1)
        return (True, True, "VDD")
    if head.startswith("NR"):                   # NOR: invert, others=VSS(0)
        return (True, True, "VSS")
    if head.startswith("AN"):                   # AND: non-invert, others=VDD(1)
        return (True, False, "VDD")
    if head.startswith("OR"):                   # OR: non-invert, others=VSS(0)
        return (True, False, "VSS")
    return (False, None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-csv", required=True)
    ap.add_argument("--anno", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--vdd", type=float, default=0.8)
    ap.add_argument("--spf", default=SPF)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    VDD = args.vdd

    pins = parse_spf_pins(args.spf)
    anno = open(args.anno, errors="ignore").read().splitlines()
    ref, cap, odir = {}, {}, {}
    for i, ln in enumerate(anno):
        m = re.match(r"\s+(\S+)/(X|Y|Z|Q|QN|CO|S|SO)\s+\((SAEDRVT14_\S+)\).*\s([rf])\s*$", ln)
        if m:
            inst = m.group(1).lower()
            ref[inst] = m.group(3)
            odir[inst] = m.group(4)             # output direction r/f
            if i + 1 < len(anno):
                t = anno[i + 1].split()
                if "(net)" in anno[i + 1] and len(t) >= 4:
                    try:
                        cap[inst] = float(t[3])   # pF
                    except ValueError:
                        pass

    rows = list(csv.DictReader(open(args.stage_csv)))
    man = []
    prev_slew = 5.0
    for x in rows:
        st = x["stage_idx"]
        cf = x.get("pt_cell_from", "")           # path input pin, e.g. U34114/A2
        cto = x.get("pt_cell_to", "")            # output pin, e.g. U34114/X
        inst = cto.rsplit("/", 1)[0]
        instl = inst.lower()
        cr = ref.get(instl, "?")
        in_slew = prev_slew
        prev_slew = float(x["pt_out_slew_ps"])
        pt_cell = float(x["pt_cell_ps"])
        load_ff = cap.get(instl, 0.002) * 1000   # pF -> fF
        outdir = odir.get(instl, "r")
        in_pin = cf.split("/")[-1]               # A2
        opin = cto.split("/")[-1]                # X

        simple, invert, ncv = classify(cr)
        if not simple or cr not in pins or in_slew < 1:
            man.append(dict(stg=st, cr=cr, pt=pt_cell, status="SKIP(complex/nodata)"))
            continue
        cellpins = pins[cr]                       # [VDD,VSS,X,A1,A2,...]
        inputs = cellpins[3:]
        if in_pin not in inputs:
            man.append(dict(stg=st, cr=cr, pt=pt_cell, status="SKIP(pin %s not in %s)" % (in_pin, inputs)))
            continue

        # input edge: inverting gate + output rise -> input falls ; else input rises
        in_rise = (outdir == "r") ^ invert       # XOR: inverting flips
        # input PWL: 20-80% transition = in_slew ; full 0-100% = in_slew/0.6
        Tful = in_slew / 0.6 / 1000.0             # ns
        t0 = 0.1                                  # start 0.1ns
        if in_rise:
            pwl = f"pwl(0 0  {t0}n 0  {t0+Tful:.6f}n {VDD})"
            trig = f"trig v({in_pin})={VDD*0.5} rise=1"
        else:
            pwl = f"pwl(0 {VDD}  {t0}n {VDD}  {t0+Tful:.6f}n 0)"
            trig = f"trig v({in_pin})={VDD*0.5} fall=1"
        # output edge = outdir
        targ = f"targ v({opin})={VDD*0.5} {'rise' if outdir=='r' else 'fall'}=1"

        # build instance line: X<inst> <pins in subckt order> <cellref>
        node = {"VDD": "VDD", "VSS": "VSS", opin: opin}
        for p in inputs:
            if p == in_pin:
                node[p] = in_pin
            else:
                node[p] = ncv or "VSS"           # non-controlling (single-input gates have none)
        inst_nodes = " ".join(node[p] for p in cellpins)

        sp = args.outdir + f"/stg_{st}.sp"
        with open(sp, "w") as f:
            f.write(f".title stage {st} {cr} isolated @ {VDD}V (PT slew {in_slew:.1f}ps)\n")
            f.write(f".param VDD={VDD}\n")
            f.write(f".lib '{MODELCARD}' TT\n")
            f.write(f".include '{args.spf}'\n")
            f.write("Vdd VDD 0 VDD\nVss VSS 0 0\n")
            f.write(f"V{in_pin} {in_pin} 0 {pwl}\n")
            # other input DC sources
            for p in inputs:
                if p != in_pin:
                    f.write(f"V{p} {p} 0 {'VDD' if ncv=='VDD' else '0'}\n")
            f.write(f"Xg {inst_nodes} {cr}\n")
            f.write(f"Cload {opin} 0 {load_ff:.4f}f\n")
            f.write(".tran 0.02p 400p\n")
            f.write(f".measure tran cell_delay {trig} {targ}\n")
            f.write(".option post\n.end\n")
        man.append(dict(stg=st, cr=cr, pt=pt_cell, status="OK", sp=sp, in_slew=in_slew, load=load_ff))

    with open(args.outdir + "/manifest.csv", "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["stage_idx", "cell_ref", "pt_cell_ps", "status", "in_slew_ps", "load_ff", "sp"])
        for m in man:
            w.writerow([m["stg"], m["cr"], f"{m['pt']:.3f}", m["status"],
                        f"{m.get('in_slew',0):.2f}", f"{m.get('load',0):.3f}", m.get("sp", "")])
    nok = sum(1 for m in man if m["status"] == "OK")
    print(f"generated {nok} simple-gate decks, {len(man)-nok} skipped -> {args.outdir}/manifest.csv")


if __name__ == "__main__":
    main()
