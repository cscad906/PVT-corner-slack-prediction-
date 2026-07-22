#!/usr/bin/env python3
"""Shift aggressor PWL sources earlier in time in a PT write_spice_deck stimulus file.

Motivation: PT aligns aggressor switching to a victim edge one clock cycle
after the edge our measures target. Shifting aggressor PWLs back by one clock
period re-aligns them with the measured victim edge without touching the
victim/clock sources, measures, or .tran.

Only ACTIVE (non-commented) pwl sources inside "* voltage source for X
(aggressor)" blocks are modified, and only when their first transition time is
at or after --min-first-ns (so already-early aggressors are left alone). All
time points except the initial 0.0ns anchor are shifted by --shift-ns.
"""
import argparse
import re
import sys

TIME_TOKEN = re.compile(r"(\d+(?:\.\d+)?)ns")
AGGR_COMMENT = re.compile(r"^\* voltage source for \S+ \(aggressor\)")
SRC_COMMENT = re.compile(r"^\* voltage source for \S+ \((victim|aggressor)\)")
ACTIVE_PWL_START = re.compile(r"^[vV]\S+\s+\S+\s+\S+\s+pwl\(", re.IGNORECASE)


def shift_statement(lines, shift_ns):
    """Shift all time tokens except the leading 0.0ns anchor. Returns new lines."""
    out = []
    first_token_seen = False
    for line in lines:
        def repl(m):
            nonlocal first_token_seen
            t = float(m.group(1))
            if not first_token_seen:
                first_token_seen = True
                if t == 0.0:
                    return m.group(0)
                # no 0.0 anchor: shift it too
            new_t = t - shift_ns
            if new_t < 0:
                raise ValueError(f"shift makes time negative: {t}ns -> {new_t}ns")
            return f"{new_t:.6f}ns"
        out.append(TIME_TOKEN.sub(repl, line))
    return out


def first_transition_ns(lines):
    """First time token after the 0.0 anchor across the statement."""
    times = []
    for line in lines:
        times.extend(float(m.group(1)) for m in TIME_TOKEN.finditer(line))
    times = [t for t in times if t > 0.0]
    return min(times) if times else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--shift-ns", type=float, default=2.0)
    ap.add_argument("--min-first-ns", type=float, default=4.8,
                    help="only shift sources whose first transition is >= this")
    args = ap.parse_args()

    with open(args.src) as f:
        lines = f.readlines()

    out = []
    i = 0
    in_aggr_block = False
    n_aggr = n_shifted = 0
    new_first = []
    while i < len(lines):
        line = lines[i]
        if SRC_COMMENT.match(line):
            in_aggr_block = bool(AGGR_COMMENT.match(line))
            if in_aggr_block:
                n_aggr += 1
            out.append(line)
            i += 1
            continue
        if in_aggr_block and ACTIVE_PWL_START.match(line):
            stmt = [line]
            j = i + 1
            while j < len(lines) and lines[j].startswith("+"):
                stmt.append(lines[j])
                j += 1
            ft = first_transition_ns(stmt)
            if ft is not None and ft >= args.min_first_ns:
                stmt = shift_statement(stmt, args.shift_ns)
                n_shifted += 1
                new_first.append(ft - args.shift_ns)
            out.extend(stmt)
            i = j
            continue
        out.append(line)
        i += 1

    with open(args.dst, "w") as f:
        f.writelines(out)

    print(f"aggressor blocks : {n_aggr}")
    print(f"sources shifted  : {n_shifted} (first transition >= {args.min_first_ns}ns, shift -{args.shift_ns}ns)")
    if new_first:
        print(f"new first-transition range: {min(new_first):.4f} .. {max(new_first):.4f} ns")


if __name__ == "__main__":
    main()
