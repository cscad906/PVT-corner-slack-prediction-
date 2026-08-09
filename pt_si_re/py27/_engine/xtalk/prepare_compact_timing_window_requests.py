#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import division, print_function

import csv
import sys


def write_lines(path, values):
    with open(path, "w") as fh:
        for value in sorted(values):
            if value:
                fh.write(value + "\n")


def main():
    if len(sys.argv) != 4:
        print(
            "usage: prepare_compact_timing_window_requests.py "
            "<path_context_active_aggressor_features.tsv> <victim_load_pins.txt> <aggressor_nets.txt>",
            file=sys.stderr,
        )
        return 2

    feature_file = sys.argv[1]
    victim_pin_out = sys.argv[2]
    aggressor_net_out = sys.argv[3]

    victim_load_pins = set()
    aggressor_nets = set()
    rows = 0

    with open(feature_file, "rb") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            rows += 1
            victim_load_pins.add(row.get("victim_load_pin", ""))
            if row.get("row_type") == "active_aggressor":
                aggressor_nets.add(row.get("aggressor_net", ""))

    write_lines(victim_pin_out, victim_load_pins)
    write_lines(aggressor_net_out, aggressor_nets)

    print("rows={0}".format(rows))
    print("victim_load_pins={0}".format(len(victim_load_pins)))
    print("aggressor_nets={0}".format(len(aggressor_nets)))
    print("victim_pin_out={0}".format(victim_pin_out))
    print("aggressor_net_out={0}".format(aggressor_net_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
