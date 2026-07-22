#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path

HEADER_RE = re.compile(r"^### FIXED_PATH idx=(\d+) key=(.*)$")
PIN_RE = re.compile(r"^\s*(\S+/\S+)\s+\(([^)]+)\)")
PIN_DIR_RE = re.compile(
    r"^\s*(?P<point>\S+/\S+)\s+\((?P<cell>[^)]+)\).*?"
    r"\s(?P<dir>[rf])\s*$",
    re.IGNORECASE,
)
NET_RE = re.compile(r"^\s*\S+\s+\(net\)\s+(\d+)\s+")
STOP_PREFIXES = (
    "data arrival time",
    "required time",
    "clock uncertainty",
    "library setup time",
    "library hold time",
    "slack ",
)


def parse_blocks(path: Path):
    blocks = []
    cur = None
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = HEADER_RE.match(line)
            if m:
                if cur is not None:
                    blocks.append(cur)
                cur = {"idx": int(m.group(1)), "key": m.group(2), "lines": []}
                continue
            if cur is not None:
                cur["lines"].append(line)
    if cur is not None:
        blocks.append(cur)
    return blocks


def extract_data_pin_chain(lines):
    data_started = False
    pins = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        lower = s.lower()
        if any(lower.startswith(p) for p in STOP_PREFIXES):
            break
        if not data_started:
            if "<-" in line:
                m = PIN_RE.match(line)
                if m and m.group(2).lower() != "net":
                    pins.append(m.group(1))
                    data_started = True
            continue
        m = PIN_RE.match(line)
        if m and m.group(2).lower() != "net":
            pins.append(m.group(1))
    return pins


def extract_data_pin_chain_with_dirs(lines):
    data_started = False
    pins = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        lower = s.lower()
        if any(lower.startswith(p) for p in STOP_PREFIXES):
            break
        if not data_started:
            if "<-" not in line:
                continue
            m = PIN_RE.match(line)
            dm = PIN_DIR_RE.match(line)
            if m and m.group(2).lower() != "net" and dm:
                pins.append((m.group(1), dm.group("dir").lower()))
                data_started = True
            continue
        m = PIN_RE.match(line)
        dm = PIN_DIR_RE.match(line)
        if m and m.group(2).lower() != "net" and dm:
            pins.append((m.group(1), dm.group("dir").lower()))
    return pins


def max_net_fanout(lines, scope):
    max_fo = 0
    data_started = scope == "all"
    for line in lines:
        s = line.strip()
        lower = s.lower()
        if scope == "data":
            if any(lower.startswith(p) for p in STOP_PREFIXES):
                break
            if not data_started:
                if "<-" in line and PIN_RE.match(line):
                    data_started = True
                continue

        m = NET_RE.match(line)
        if data_started and m:
            max_fo = max(max_fo, int(m.group(1)))
    return max_fo


def main():
    ap = argparse.ArgumentParser(description="Generate strict fixed-path Tcl from an annotated/reference report.")
    ap.add_argument("--ref-annotated", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="Optional max number of paths to emit (0 = all).")
    ap.add_argument(
        "--max-fanout",
        type=int,
        default=0,
        help="Skip any timing path containing a net with fanout greater than this value (0 = disabled).",
    )
    ap.add_argument(
        "--fanout-scope",
        choices=("data", "all"),
        default="data",
        help="Apply max-fanout to data-path nets only, or to all full_clock_expanded nets.",
    )
    ap.add_argument("--reject-csv", default="", help="Optional CSV listing skipped paths and max fanout.")
    ap.add_argument(
        "--edge-aware",
        action="store_true",
        help="Emit rise/fall direction metadata so report_fixed_paths.tcl can use -rise/-fall from/through/to constraints.",
    )
    args = ap.parse_args()

    blocks = parse_blocks(Path(args.ref_annotated))
    emitted = 0
    skipped_short = 0
    skipped_fanout = 0
    rejects = []

    with Path(args.out).open("w", encoding="utf-8") as f:
        f.write("# Auto-generated strict fixed paths (all internal data pins as ordered through constraints)\n")
        if args.edge_aware:
            f.write("# Edge-aware mode: each entry includes an edge list aligned to {from, through..., to}\n")
        if args.max_fanout:
            f.write(f"# Filter: skipped paths with {args.fanout_scope} net fanout > {args.max_fanout}\n")
        f.write("set FIXED_PATHS {\n")
        for blk in blocks:
            blk_max_fo = max_net_fanout(blk["lines"], args.fanout_scope)
            if args.max_fanout and blk_max_fo > args.max_fanout:
                skipped_fanout += 1
                rejects.append((blk["idx"], blk["key"], blk_max_fo))
                continue

            pin_dirs = extract_data_pin_chain_with_dirs(blk["lines"]) if args.edge_aware else []
            pins = [p for p, _ in pin_dirs] if args.edge_aware else extract_data_pin_chain(blk["lines"])
            if len(pins) < 2:
                skipped_short += 1
                continue

            from_pin = pins[0]
            to_pin = pins[-1]
            through_pins = pins[1:-1]
            thr_list = " ".join(f"{{{p}}}" for p in through_pins)
            if args.edge_aware:
                edge_list = " ".join(f"{{{d}}}" for _, d in pin_dirs)
                f.write(f"  {{{{{blk['key']}}} {{{from_pin}}} {{{to_pin}}} {{{thr_list}}} {{{edge_list}}}}}\n")
            else:
                f.write(f"  {{{{{blk['key']}}} {{{from_pin}}} {{{to_pin}}} {{{thr_list}}}}}\n")
            emitted += 1
            if args.limit and emitted >= args.limit:
                break
        f.write("}\n\n")
        if args.edge_aware:
            f.write("# each entry: {path_key {from_pin} {to_pin} { {through1} {through2} ... } {from_dir through_dir... to_dir}}\n")
        else:
            f.write("# each entry: {path_key {from_pin} {to_pin} { {through1} {through2} ... }}\n")

    if args.reject_csv:
        with Path(args.reject_csv).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["idx", "key", "max_fanout"])
            w.writerows(rejects)

    print(f"[OK] wrote {emitted} strict paths to {args.out}")
    print(
        f"[STATS] blocks={len(blocks)} skipped_short={skipped_short} "
        f"skipped_fanout={skipped_fanout} max_fanout={args.max_fanout} fanout_scope={args.fanout_scope}"
    )
    if args.reject_csv:
        print(f"[REJECT_CSV] {args.reject_csv}")


if __name__ == "__main__":
    main()
