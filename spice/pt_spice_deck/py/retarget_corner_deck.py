#!/usr/bin/env python3
"""Retarget an arc-align SPICE deck (stim + header/main .sp) from Vref to Vnew
WITHOUT re-running PrimeTime (no target-corner Liberty needed).

Scaling:
  - PWL voltage levels        : x (Vnew/Vref)              [logic levels 0..Vref -> 0..Vnew]
  - .param VDD / vVDD rails    : Vnew
  - (optional) aggressor+victim slew (ramp width) : x k     [b-2: k = victim_slew(new)/victim_slew(ref)]

Slew rescale keeps each PWL's first (anchor) transition time fixed and expands the ramp
by k relative to the ramp start. Alignment (shift_* offsets) is preserved.
Transistor V/T come from the modelcard via .param VDD (+ .temp) -> device physics is automatic.
"""
import argparse, re, os, glob

TIME = re.compile(r"([0-9]+(?:\.[0-9]+)?)ns")


def scale_voltage_line(line, vr):
    """Scale voltage tokens: the numeric that FOLLOWS a time token (or ')') in a pwl row."""
    # rows look like:  <t>ns <v>   or   'shift_0 + <t>ns' <v>   or   pwl(0.0ns <v>
    # Scale the trailing voltage number(s). Strategy: scale any standalone float that is a
    # PWL level (0 <= x <= vr+eps) appearing right after a 'ns' or a quote/paren.
    def repl(m):
        pre, num = m.group(1), float(m.group(2))
        return f"{pre}{num*vr:.6g}"
    # after "ns" + spaces  OR  after "ns'" + spaces  OR  after "pwl(" preceding a bare 0
    line = re.sub(r"(ns'?\s+)([0-9]+(?:\.[0-9]+)?)", repl, line)
    return line


def rescale_slew_pwl(stmt_lines, k):
    """Given a full PWL statement (list of lines), widen the ramp by k.
    Anchor = first time token; ramp-start = last time at the initial level.
    Only relative offsets after ramp-start are scaled by k."""
    # collect (line_idx, span, tval) for every time token
    toks = []
    for i, ln in enumerate(stmt_lines):
        for m in TIME.finditer(ln):
            toks.append((i, m.span(), float(m.group(1))))
    if len(toks) < 3:
        return stmt_lines
    # ramp start = the time of the 2nd point (first is 0.0 anchor at t=0; 2nd is hold-end)
    # write_spice_deck: pwl(0.0ns L0 , t_hold L0 , t_hold+dt L1 , ...). ramp starts at t_hold.
    times = [t for _, _, t in toks]
    # find hold-end index: first index (>=1) where the NEXT time increment is the small ramp step.
    # heuristic: ramp start = times[1] (the hold end), scale times[2:] relative to times[1].
    t0 = times[1]
    new_times = list(times)
    for j in range(2, len(times)):
        new_times[j] = t0 + (times[j] - t0) * k
    # rewrite lines back-to-front to keep spans valid
    out = list(stmt_lines)
    for (i, (s, e), _), nt in sorted(zip(toks, new_times), key=lambda x: (x[0][0], -x[0][1][0])):
        out[i] = out[i][:s] + f"{nt:.6f}ns" + out[i][e:]
    return out


def process_stim(path, vr, k):
    lines = open(path).read().splitlines()
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        # a pwl statement: starts with 'v...pwl(' and continues on '+' lines
        if re.match(r"^v\S+.*pwl\(", ln, re.I):
            stmt = [ln]
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("+"):
                stmt.append(lines[j]); j += 1
            if k != 1.0:
                stmt = rescale_slew_pwl(stmt, k)
            stmt = [scale_voltage_line(s, vr) for s in stmt]
            out.extend(stmt)
            i = j
            continue
        # DC-held source: "v... node 0 <val>"
        m = re.match(r"^(v\S+\s+\S+\s+0\s+)([0-9.]+)\s*$", ln, re.I)
        if m:
            out.append(f"{m.group(1)}{float(m.group(2))*vr:.6g}")
            i += 1; continue
        out.append(ln); i += 1
    open(path, "w").write("\n".join(out) + "\n")


def process_deck(path, vnew):
    txt = open(path).read()
    txt = re.sub(r"(\.param\s+VDD\s*=\s*)[0-9.]+", rf"\g<1>{vnew}", txt)
    txt = re.sub(r"(^v\S*VDD\S*\s+\S+\s+0\s+)[0-9.]+", rf"\g<1>{vnew}", txt, flags=re.M)
    open(path, "w").write(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="arc-align run dir (contains stage_*/)")
    ap.add_argument("--vref", type=float, default=0.8)
    ap.add_argument("--vnew", type=float, required=True)
    ap.add_argument("--k-slew", type=float, default=1.0, help="aggressor/victim slew ramp scale (b-2)")
    args = ap.parse_args()
    vr = args.vnew / args.vref
    ns = ng = 0
    for stim in glob.glob(os.path.join(args.dir, "stage_*", "*_stim.sp")):
        process_stim(stim, vr, args.k_slew); ns += 1
    for deck in glob.glob(os.path.join(args.dir, "stage_*", "*_align.sp")):
        process_deck(deck, args.vnew); ng += 1
    for deck in glob.glob(os.path.join(args.dir, "stage_*", "quiet", "*.sp")):
        process_deck(deck, args.vnew)
    # header
    for h in glob.glob(os.path.join(args.dir, "*header*.sp")):
        process_deck(h, args.vnew)
    print(f"retargeted {args.vref}V -> {args.vnew}V  (vratio={vr:.4f}, k_slew={args.k_slew})")
    print(f"  stim files: {ns}   deck files: {ng}")


if __name__ == "__main__":
    main()
