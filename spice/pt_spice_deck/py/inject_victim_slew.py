#!/usr/bin/env python3
"""Method (3): inject physically-measured unseen-corner victim INPUT slew into
arc-align decks, harvested from the self-propagating full-path base decks.

For each arc-align stage N (from manifest), the victim driver input pin = cell_from.
The input slew arriving at that pin = the OUTPUT slew of base stage (N-1)
(base stage i's net_to == arc-align stage i+1's cell_from).

  k_N = spice_out_slew(0.7V base, stage N-1) / spice_out_slew(0.8V base, stage N-1)

Only the VICTIM input PWL ramp is widened by k_N (per stage). Aggressor PWLs are
left at reference (this is the key difference vs b-2, which scaled everything global).
Anchor (ramp-start time) fixed; downstream times scaled -> alignment shift_* preserved.
"""
import argparse, csv, re, os, glob

TIME = re.compile(r"([0-9]+(?:\.[0-9]+)?)ns")


def base_slew(fn):
    d = {}
    for r in csv.DictReader(open(fn)):
        try:
            d[int(r["stage_idx"])] = float(r["spice_out_slew_ps"])
        except (KeyError, ValueError):
            pass
    return d


def rescale_pwl_lines(stmt_lines, k):
    """Widen a single PWL ramp by k. Anchor=times[1] (hold-end); scale times[2:] relative."""
    toks = []
    for i, ln in enumerate(stmt_lines):
        for m in TIME.finditer(ln):
            toks.append((i, m.span(), float(m.group(1))))
    if len(toks) < 3:
        return stmt_lines
    times = [t for _, _, t in toks]
    t0 = times[1]
    new_times = [t0 + (t - t0) * k if j >= 2 else t for j, t in enumerate(times)]
    out = list(stmt_lines)
    for (i, (s, e), _), nt in sorted(zip(toks, new_times), key=lambda x: (x[0][0], -x[0][1][0])):
        out[i] = out[i][:s] + f"{nt:.6f}ns" + out[i][e:]
    return out


def _ramps(stmt_lines, thr=0.4):
    """True if this PWL rises to > thr (a real transitioning input, not DC-held-0)."""
    vmax = 0.0
    for ln in stmt_lines:
        for m in re.finditer(r"ns'?\s+([0-9]+(?:\.[0-9]+)?)", ln):
            vmax = max(vmax, float(m.group(1)))
    return vmax > thr


def inject_stage(stim_path, victim_pin, k):
    """Rescale the transitioning victim-input PWL by k. Match by DRIVER CELL prefix
    (not exact pin) because surrogate decks drive the default pin (A1), not the path pin."""
    if k == 1.0:
        return False
    victim_cell = victim_pin.rsplit("/", 1)[0]      # e.g. mem_issue_unit/U377
    lines = open(stim_path).read().splitlines()
    cell_re = re.compile(r"^v\S+\s+" + re.escape(victim_cell) + r"/\S+\s+0\s+pwl\(", re.I)
    out, i, hit = [], 0, False
    while i < len(lines):
        if cell_re.match(lines[i]):
            stmt = [lines[i]]
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("+"):
                stmt.append(lines[j]); j += 1
            if _ramps(stmt):                          # only the transitioning input
                stmt = rescale_pwl_lines(stmt, k); hit = True
            out.extend(stmt); i = j
            continue
        out.append(lines[i]); i += 1
    if hit:
        open(stim_path, "w").write("\n".join(out) + "\n")
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="m3 arc-align dir (stage_*/)")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--base07", required=True)
    ap.add_argument("--base08", required=True)
    args = ap.parse_args()

    s7, s8 = base_slew(args.base07), base_slew(args.base08)
    man = list(csv.DictReader(open(args.manifest)))
    print(f"{'arcN':>4} {'victim_pin':<38} {'from_base':>9} {'k':>6}  {'applied'}")
    nhit = 0
    for r in man:
        N = int(r["stage_idx"])
        pin = r["cell_from"]
        b = N - 1  # base stage feeding this pin
        k = 1.0
        if b in s7 and b in s8 and s8[b] > 1.0:
            k = s7[b] / s8[b]
        # locate this stage's stim file
        sd = r["stage_dir"]
        stims = glob.glob(os.path.join(sd, "*_stim.sp"))
        hit = False
        for st in stims:
            if inject_stage(st, pin, k):
                hit = True
        nhit += hit
        print(f"{N:>4} {pin[:38]:<38} {('s%d'%b) if b>=1 else '(clk)':>9} {k:>6.3f}  {'yes' if hit else '-'}")
    print(f"\ninjected victim-slew widening into {nhit} stages")


if __name__ == "__main__":
    main()
