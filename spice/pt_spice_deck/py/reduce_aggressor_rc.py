#!/usr/bin/env python3
"""Collapse each aggressor net's detailed RC into a single lumped node.

For every net in the "Aggressor Nets" section: merge all its nodes (driver pin,
internal :N nodes, receiver pins) into the driver output pin; drop the net's
resistors (shorted); sum its ground caps into one cap on the driver node. Then
apply the node rename map to Aggressor Cells instance pins, Coupling Capacitors
(aggressor side only -- victim side untouched), Load Caps, and Grounded
Coupling Caps. Victim Nets / Victim Cells are left byte-identical.

Total capacitance to the victim and total ground capacitance per aggressor net
are conserved; only the intra-net wire resistance and internal nodes are
removed (lumped-C aggressor model).
"""
import re
import sys
from pathlib import Path

SECTIONS = [
    ("victim_nets", "* Start: Victim Nets", "* End: Victim Nets"),
    ("victim_cells", "* Start: Victim Cells", "* End: Victim Cells"),
    ("aggr_nets", "* Start: Aggressor Nets", "* End: Aggressor Nets"),
    ("aggr_cells", "* Start: Aggressor Cells", "* End: Aggressor Cells"),
    ("coupling", "* Start: Coupling Capacitors", "* End: Coupling Capacitors"),
    ("load", "* Start: Load Capacitors", "* End: Load Capacitors"),
    ("gnd_coupling", "* Start: Grounded Coupling Capacitors", "* End: Grounded Coupling Capacitors"),
]


def find_sections(lines):
    idx = {}
    for name, s, e in SECTIONS:
        si = ei = None
        for i, l in enumerate(lines):
            if l.rstrip("\n") == s:
                si = i
            elif l.rstrip("\n") == e:
                ei = i
                break
        idx[name] = (si, ei)
    return idx


def parse_aggr_nets(lines, s, e):
    """Return (rename_map, ground_cap_sum_per_rep, kept_header_lines_per_net).
    Rebuild the aggr_nets section body with R dropped and C summed."""
    rename = {}
    lumpC = {}       # rep -> summed ground cap
    new_body = []
    cur_rep = None
    cur_nodes = set()
    cur_cap = 0.0
    cur_header = []

    def flush():
        nonlocal cur_rep, cur_cap
        if cur_rep is None:
            return
        for n in cur_nodes:
            if n != cur_rep:
                rename[n] = cur_rep
        lumpC[cur_rep] = lumpC.get(cur_rep, 0.0) + cur_cap
        new_body.extend(cur_header)
        new_body.append(f"* lumped RC: net collapsed to {cur_rep}\n")

    i = s + 1
    while i < e:
        l = lines[i]
        m = re.match(r"^\* Timing arc net : \(aggressor\) (\S+)", l)
        if m:
            flush()
            cur_rep = None
            cur_nodes = set()
            cur_cap = 0.0
            cur_header = [l]
            i += 1
            continue
        md = re.match(r"^\* driver pin '(\S+)'\.", l)
        if md:
            cur_rep = md.group(1)
            cur_nodes.add(cur_rep)
            cur_header.append(l)
            i += 1
            continue
        if re.match(r"^r\S+\s", l):
            # resistor: collect both node names, drop the line
            toks = l.split()
            cur_nodes.add(toks[1])
            cur_nodes.add(toks[2])
            i += 1
            continue
        if re.match(r"^c\S+\s", l):
            toks = l.split()
            cur_nodes.add(toks[1])
            try:
                cur_cap += float(toks[3])
            except (IndexError, ValueError):
                pass
            i += 1
            continue
        # other comment lines inside a net block: keep in header
        if l.startswith("*"):
            cur_header.append(l)
        i += 1
    flush()
    return rename, lumpC, new_body


def apply_rename_token(tok, rename):
    return rename.get(tok, tok)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    lines = Path(src).read_text().splitlines(keepends=True)
    idx = find_sections(lines)

    an_s, an_e = idx["aggr_nets"]
    rename, lumpC, aggr_body = parse_aggr_nets(lines, an_s, an_e)
    print(f"aggressor nets collapsed; nodes renamed: {len(rename)}; lumped ground caps: {len(lumpC)}")

    out = []
    i = 0
    n = len(lines)
    while i < n:
        # Aggressor Nets: replace whole body
        if i == an_s:
            out.append(lines[i])              # Start marker
            out.extend(aggr_body)
            # emit one lumped ground cap per representative
            ci = 0
            for rep, cval in lumpC.items():
                if cval > 0:
                    out.append(f"clmp{ci:06d}\t{rep}\t0\t{cval:.6e}\n")
                    ci += 1
            out.append(lines[an_e])           # End marker
            i = an_e + 1
            continue

        l = lines[i]

        # Aggressor Cells: rename instance pin nodes (x-lines incl. continuation)
        c_s, c_e = idx["aggr_cells"]
        if c_s is not None and c_s < i < c_e:
            if l.startswith("x") or l.startswith("+"):
                toks = l.split()
                toks = [apply_rename_token(t, rename) for t in toks]
                out.append("\t".join(toks) + "\n" if not l.startswith("+")
                           else "+\t" + " ".join(toks[1:]) + "\n")
                i += 1
                continue

        # Coupling / Load / Grounded coupling caps: rename node terminals
        for sec in ("coupling", "load", "gnd_coupling"):
            ss, ee = idx[sec]
            if ss is not None and ss < i < ee and re.match(r"^c\S+\s", l):
                toks = l.split()
                toks[1] = apply_rename_token(toks[1], rename)
                toks[2] = apply_rename_token(toks[2], rename)
                out.append("\t".join(toks) + "\n")
                break
        else:
            out.append(l)
            i += 1
            continue
        i += 1

    Path(dst).write_text("".join(out))
    print(f"written: {dst}")


if __name__ == "__main__":
    main()
