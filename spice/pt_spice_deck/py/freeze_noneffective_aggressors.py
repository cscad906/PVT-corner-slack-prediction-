#!/usr/bin/env python3
"""Freeze non-effective aggressor PWL sources in a PT write_spice_deck stimulus.

Effective aggressors are read from PT report_delay_calculation -crosstalk
reports (attribute 'A' rows, rise or fall section). Every aggressor source
whose driver net is NOT in that set gets its PWL replaced by a DC source at
the PWL's initial value -- circuit/loading untouched, stimulus quiet.
"""
import argparse
import re
import sys
from pathlib import Path

ATTR_LETTERS = {"A", "C", "E", "I", "L", "N", "P", "S", "U", "X"}


def effective_nets_from_reports(report_dir):
    """Parse aggressor tables (rows may wrap across lines). A logical row
    starts at 2-space indent; continuations are more-indented. Active rows
    carry a standalone 'A' attribute token."""
    nets = set()
    for rpt in sorted(Path(report_dir).glob("arc_*_delaycalc.rpt")):
        in_table = False
        await_dashes = False
        row_toks = []

        def flush():
            if row_toks:
                attrs = [t for t in row_toks[1:] if len(t) == 1 and t in ATTR_LETTERS]
                if "A" in attrs and not set(row_toks[0]) <= {"-"}:
                    nets.add(row_toks[0])

        for line in rpt.read_text().splitlines():
            if "Aggressor" in line and "Coupling" in line:
                await_dashes = True
                in_table = False
                continue
            if await_dashes:
                if re.match(r"^\s*-{5,}", line):
                    await_dashes = False
                    in_table = True
                continue
            if in_table:
                if not line.strip() or not line.startswith(" "):
                    flush()
                    row_toks = []
                    in_table = False
                    continue
                if re.match(r"^  \S", line):
                    flush()
                    row_toks = line.split()
                else:
                    row_toks.extend(line.split())
        flush()
    return nets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--reports", required=True, help="dir with arc_*_delaycalc.rpt")
    args = ap.parse_args()

    eff = effective_nets_from_reports(args.reports)
    print(f"effective aggressor nets (union over arcs): {len(eff)}")

    lines = Path(args.src).read_text().splitlines(keepends=True)
    out = []
    i = 0
    cur_driver_net = None
    cur_src_name = None
    in_aggr = False
    n_aggr = n_frozen = n_kept = 0
    while i < len(lines):
        l = lines[i]
        m = re.match(r"^\* voltage source for \S+ \((victim|aggressor)\)", l)
        if m:
            in_aggr = m.group(1) == "aggressor"
            cur_driver_net = None
            if in_aggr:
                n_aggr += 1
        m = re.match(r"^\* aggressor driver net is (\S+)", l)
        if m:
            cur_driver_net = m.group(1)
        mv = re.match(r"^\* voltage source for (\S+) \(aggressor\)", l)
        if mv:
            cur_src_name = mv.group(1)
        if in_aggr and re.match(r"^[vV]\S+\s+\S+\s+\S+\s+pwl\(", l, re.IGNORECASE):
            j = i + 1
            stmt = [l]
            while j < len(lines) and lines[j].startswith("+"):
                stmt.append(lines[j])
                j += 1
            # Match by driver-net comment, or fall back to the source node name
            # (some aggressor blocks omit the "driver net is" comment; the node
            # carries a _P_SPC..._P_SPC... suffix over the effective PT net name).
            node = stmt[0].split()[1]
            names = {cur_driver_net, cur_src_name, node,
                     re.sub(r"_P_SPC\d+_P_SPC\d+$", "", node)}
            if names & eff:
                n_kept += 1
                out.extend(stmt)
            else:
                n_frozen += 1
                head = re.match(r"^([vV]\S+)\s+(\S+)\s+(\S+)\s+pwl\(\s*[\d.]+ns\s+([\d.]+)", l)
                name, node, ref, v0 = head.group(1), head.group(2), head.group(3), head.group(4)
                out.append(f"* frozen (non-effective aggressor, was pwl)\n")
                out.append(f"{name} {node} {ref} {v0}\n")
            i = j
            continue
        out.append(l)
        i += 1

    Path(args.dst).write_text("".join(out))
    print(f"aggressor sources: {n_aggr}  kept(driven): {n_kept}  frozen(DC): {n_frozen}")


if __name__ == "__main__":
    main()
