#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from collections import OrderedDict
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: make_unique_path_arc_contexts.py <path_victim_nets.tsv> <out.tsv>", file=sys.stderr)
        return 2

    in_file = Path(sys.argv[1])
    out_file = Path(sys.argv[2])

    contexts: OrderedDict[tuple[str, str, str], dict[str, str]] = OrderedDict()
    with in_file.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            key = (row["victim_net"], row["victim_driver_pin"], row["victim_load_pin"])
            if key not in contexts:
                contexts[key] = {
                    "context_id": str(len(contexts) + 1),
                    "victim_net": row["victim_net"],
                    "victim_driver_pin": row["victim_driver_pin"],
                    "victim_load_pin": row["victim_load_pin"],
                    "first_path_id": row["path_id"],
                    "first_arc_idx": row["arc_idx"],
                    "occurrence_count": "0",
                }
            contexts[key]["occurrence_count"] = str(int(contexts[key]["occurrence_count"]) + 1)

    fieldnames = [
        "context_id",
        "victim_net",
        "victim_driver_pin",
        "victim_load_pin",
        "first_path_id",
        "first_arc_idx",
        "occurrence_count",
    ]
    with out_file.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(contexts.values())

    print(f"unique_contexts={len(contexts)}")
    print(f"out={out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
