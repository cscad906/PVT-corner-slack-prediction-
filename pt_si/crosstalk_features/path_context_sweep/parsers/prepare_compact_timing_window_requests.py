#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from pathlib import Path


def write_lines(path: Path, values: set[str]) -> None:
    with path.open("w") as fh:
        for value in sorted(values):
            if value:
                fh.write(value + "\n")


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: prepare_compact_timing_window_requests.py "
            "<path_context_active_aggressor_features.tsv> <victim_load_pins.txt> <aggressor_nets.txt>",
            file=sys.stderr,
        )
        return 2

    feature_file = Path(sys.argv[1])
    victim_pin_out = Path(sys.argv[2])
    aggressor_net_out = Path(sys.argv[3])

    victim_load_pins: set[str] = set()
    aggressor_nets: set[str] = set()
    rows = 0

    with feature_file.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            rows += 1
            victim_load_pins.add(row.get("victim_load_pin", ""))
            if row.get("row_type") == "active_aggressor":
                aggressor_nets.add(row.get("aggressor_net", ""))

    write_lines(victim_pin_out, victim_load_pins)
    write_lines(aggressor_net_out, aggressor_nets)

    print(f"rows={rows}")
    print(f"victim_load_pins={len(victim_load_pins)}")
    print(f"aggressor_nets={len(aggressor_nets)}")
    print(f"victim_pin_out={victim_pin_out}")
    print(f"aggressor_net_out={aggressor_net_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
