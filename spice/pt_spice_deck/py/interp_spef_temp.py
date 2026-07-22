#!/usr/bin/env python3
"""Interpolate wire resistance in a SPEF to a target temperature.

Motivation: SPEF R is extracted at a fixed temperature (StarRC model_25 / model_125
/ model_m40) and emitted as constant resistor values; HSPICE `.temp` does NOT scale
these (the deck resistors carry no temperature coefficient). To run a corner at an
unextracted temperature (e.g. 50C) with a *consistent* wire R, synthesize a SPEF whose
resistances are interpolated between two bracketing-temperature SPEFs:

    R(T) = R_lo + (R_hi - R_lo) * (T - T_lo)/(T_hi - T_lo)

Capacitance (*CAP, *cc coupling, *D_NET total) is temperature-independent (geometric),
so it is passed through verbatim from the --lo file.

The two input SPEFs must be the SAME extraction (design/version/RC-corner) differing
only in temperature, so they are structurally line-aligned; only the last field of each
*RES data line (the resistance) is interpolated. Node pairs are cross-checked and any
mismatch is reported (indicates the files are not aligned -> do not trust the output).
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo", required=True, help="lower-temperature SPEF (e.g. Cnom_model_25)")
    ap.add_argument("--hi", required=True, help="upper-temperature SPEF (e.g. Cnom_model_125)")
    ap.add_argument("--t-lo", type=float, default=25.0)
    ap.add_argument("--t-hi", type=float, default=125.0)
    ap.add_argument("--t", type=float, required=True, help="target temperature, e.g. 50")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.t_hi == args.t_lo:
        sys.exit("t-hi must differ from t-lo")
    frac = (args.t - args.t_lo) / (args.t_hi - args.t_lo)

    in_res = False
    n_res = 0          # resistors interpolated
    n_mismatch = 0     # node-pair disagreements between the two files
    r_ratio_min = float("inf")
    r_ratio_max = 0.0

    with open(args.lo) as fl, open(args.hi) as fh, open(args.out, "w") as fo:
        for llo, lhi in zip(fl, fh):
            s = llo.lstrip()
            if s.startswith("*"):
                # section header / directive -> RES section is active only for *RES
                in_res = s.startswith("*RES")
                fo.write(llo)
                continue
            if in_res and s.strip():
                tlo = llo.split()
                thi = lhi.split()
                # *RES data line: <id> <node1> <node2> <R>
                if len(tlo) >= 4 and len(thi) >= 4:
                    try:
                        rlo = float(tlo[-1])
                        rhi = float(thi[-1])
                    except ValueError:
                        fo.write(llo)
                        continue
                    if tlo[1:3] != thi[1:3]:
                        n_mismatch += 1
                    r = rlo + (rhi - rlo) * frac
                    if rlo > 0:
                        ratio = r / rlo
                        r_ratio_min = min(r_ratio_min, ratio)
                        r_ratio_max = max(r_ratio_max, ratio)
                    tlo[-1] = f"{r:.6g}"
                    fo.write(" ".join(tlo) + "\n")
                    n_res += 1
                    continue
            fo.write(llo)

    print(f"target T          : {args.t} C   (frac={frac:.4f} between {args.t_lo} and {args.t_hi})")
    print(f"resistors scaled  : {n_res}")
    print(f"R scale vs --lo   : {r_ratio_min:.4f} .. {r_ratio_max:.4f}  (should be ~uniform)")
    print(f"node-pair mismatch: {n_mismatch}   (>0 => files not aligned, DO NOT USE)")
    print(f"written           : {args.out}   (C/cc taken from --lo)")


if __name__ == "__main__":
    main()
