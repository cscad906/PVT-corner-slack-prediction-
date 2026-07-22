#!/usr/bin/env python3
import csv
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


def read_tsv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(path, fieldnames, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def vtag_to_voltage(vtag):
    match = re.fullmatch(r"0p(\d+)", vtag)
    if not match:
        return vtag
    digits = match.group(1)
    if len(digits) == 1:
        return f"0.{digits}00"
    return f"0.{digits}"


def safe_float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def export_union_from_corner_files(out_active):
    index_file = out_active / "index.tsv"
    index_rows = read_tsv(index_file)
    file_to_voltage = {row["file"]: row["voltage"] for row in index_rows}
    union_by_victim = defaultdict(dict)
    victim_order = {}

    for index_row in index_rows:
        voltage = index_row["voltage"]
        corner_file = Path(index_row["file"])
        for arc_order, row in enumerate(read_tsv(corner_file), start=1):
            victim = row["victim_net"]
            victim_order.setdefault(victim, arc_order)
            items = row["active_aggressors_by_noise_bump"].split(";")
            for item in items:
                if not item:
                    continue
                match = re.fullmatch(r"(rise|fall):(.+)\(bump=([0-9.+\-Ee]+)\)", item)
                if not match:
                    continue
                sense, aggressor, bump = match.groups()
                entry = union_by_victim[victim].setdefault(aggressor, {
                    "max_bump": 0.0,
                    "voltages": set(),
                    "senses": set(),
                })
                entry["max_bump"] = max(entry["max_bump"], safe_float(bump))
                entry["voltages"].add(voltage)
                entry["senses"].add(sense)

    union_rows = []
    union_name_only_rows = []
    for victim, aggressors in union_by_victim.items():
        formatted = []
        name_only = []
        for aggressor, data in sorted(
            aggressors.items(),
            key=lambda item: (-item[1]["max_bump"], item[0]),
        ):
            senses = ",".join(sorted(data["senses"]))
            voltages = ",".join(sorted(data["voltages"], key=safe_float))
            formatted.append(
                f"{aggressor}(max_bump={data['max_bump']:.6f},senses={senses},voltages={voltages})"
            )
            name_only.append(aggressor)
        union_rows.append({
            "victim_net": victim,
            "union_active_aggressors_by_max_bump": ";".join(formatted),
            "_arc_idx": victim_order.get(victim, 10**9),
        })
        union_name_only_rows.append({
            "victim_net": victim,
            "union_active_aggressor_nets": ";".join(name_only),
            "_arc_idx": victim_order.get(victim, 10**9),
        })

    union_rows.sort(key=lambda row: (row["_arc_idx"], row["victim_net"]))
    union_name_only_rows.sort(key=lambda row: (row["_arc_idx"], row["victim_net"]))
    for row in union_rows:
        row.pop("_arc_idx", None)
    for row in union_name_only_rows:
        row.pop("_arc_idx", None)

    union_file = out_active / "all_voltage_union.active_aggressors.tsv"
    union_name_only_file = out_active / "all_voltage_union.active_aggressor_names.tsv"
    write_tsv(union_file, ["victim_net", "union_active_aggressors_by_max_bump"], union_rows)
    write_tsv(union_name_only_file, ["victim_net", "union_active_aggressor_nets"], union_name_only_rows)
    print(f"union_victim_rows={len(union_rows)}")
    print(f"union_file={union_file}")
    print(f"union_name_only_file={union_name_only_file}")


def export_by_corner(out_dir):
    detail_file = out_dir / "voltage_effective_aggressor_detail.tsv"
    arc_file = out_dir / "voltage_effective_aggressor_by_arc.tsv"
    out_active = out_dir / "active_only_by_corner"
    if not detail_file.exists() or not arc_file.exists():
        export_union_from_corner_files(out_active)
        return

    rows = [row for row in read_tsv(detail_file) if row.get("is_active_A") == "1"]
    arc_rows = read_tsv(arc_file)

    victim_order = {}
    global_victim_order = {}
    for row in arc_rows:
        key = (row["vtag"], row["victim_net"])
        arc_idx = int(row["arc_idx"])
        victim_order.setdefault(key, arc_idx)
        if row["victim_net"] not in global_victim_order:
            global_victim_order[row["victim_net"]] = arc_idx
        else:
            global_victim_order[row["victim_net"]] = min(global_victim_order[row["victim_net"]], arc_idx)

    grouped = defaultdict(list)
    for row in rows:
        key = (row["vtag"], row["victim_net"])
        grouped[key].append(row)

    by_vtag = defaultdict(list)
    for (vtag, victim), entries in grouped.items():
        entries.sort(
            key=lambda item: (
                -safe_float(item["switching_bump_ratio_vdd"]),
                item["sense"],
                item["aggressor_net"],
            )
        )
        formatted = []
        for entry in entries:
            bump = entry["switching_bump_ratio_vdd"]
            formatted.append(f"{entry['sense']}:{entry['aggressor_net']}(bump={bump})")
        by_vtag[vtag].append({
            "victim_net": victim,
            "active_aggressors_by_noise_bump": ";".join(formatted),
            "_arc_idx": victim_order.get((vtag, victim), 10**9),
        })

    out_active.mkdir(exist_ok=True)

    union_by_victim = defaultdict(dict)
    for row in rows:
        victim = row["victim_net"]
        aggressor = row["aggressor_net"]
        entry = union_by_victim[victim].setdefault(aggressor, {
            "max_bump": 0.0,
            "voltages": set(),
            "senses": set(),
        })
        entry["max_bump"] = max(entry["max_bump"], safe_float(row["switching_bump_ratio_vdd"]))
        entry["voltages"].add(vtag_to_voltage(row["vtag"]))
        entry["senses"].add(row["sense"])

    union_rows = []
    union_name_only_rows = []
    for victim, aggressors in union_by_victim.items():
        formatted = []
        name_only = []
        for aggressor, data in sorted(
            aggressors.items(),
            key=lambda item: (-item[1]["max_bump"], item[0]),
        ):
            voltages = ",".join(sorted(data["voltages"], key=safe_float))
            senses = ",".join(sorted(data["senses"]))
            formatted.append(
                f"{aggressor}(max_bump={data['max_bump']:.6f},senses={senses},voltages={voltages})"
            )
            name_only.append(aggressor)
        union_rows.append({
            "victim_net": victim,
            "union_active_aggressors_by_max_bump": ";".join(formatted),
            "_arc_idx": global_victim_order.get(victim, 10**9),
        })
        union_name_only_rows.append({
            "victim_net": victim,
            "union_active_aggressor_nets": ";".join(name_only),
            "_arc_idx": global_victim_order.get(victim, 10**9),
        })

    union_rows.sort(key=lambda row: (row["_arc_idx"], row["victim_net"]))
    union_name_only_rows.sort(key=lambda row: (row["_arc_idx"], row["victim_net"]))
    for row in union_rows:
        row.pop("_arc_idx", None)
    for row in union_name_only_rows:
        row.pop("_arc_idx", None)
    union_file = out_active / "all_voltage_union.active_aggressors.tsv"
    union_name_only_file = out_active / "all_voltage_union.active_aggressor_names.tsv"
    write_tsv(union_file, ["victim_net", "union_active_aggressors_by_max_bump"], union_rows)
    write_tsv(union_name_only_file, ["victim_net", "union_active_aggressor_nets"], union_name_only_rows)

    index_rows = []
    temp_label = os.environ.get("SI_FEATURE_CORNER_TEMP_LABEL", "25c")
    spef_corner = os.environ.get("SI_FEATURE_SPEF_CORNER", "Cnom")
    for vtag in sorted(by_vtag, key=lambda tag: safe_float(vtag_to_voltage(tag))):
        voltage = vtag_to_voltage(vtag)
        corner_name = f"tt{voltage}v{temp_label}_{spef_corner}"
        out_file = out_active / f"{corner_name}.active_aggressors.tsv"
        corner_rows = sorted(by_vtag[vtag], key=lambda row: (row["_arc_idx"], row["victim_net"]))
        for row in corner_rows:
            row.pop("_arc_idx", None)
        write_tsv(out_file, ["victim_net", "active_aggressors_by_noise_bump"], corner_rows)
        index_rows.append({
            "voltage": voltage,
            "vtag": vtag,
            "corner": corner_name,
            "victim_net_count_with_active_aggressor": len(corner_rows),
            "file": str(out_file),
        })

    write_tsv(out_active / "index.tsv", ["voltage", "vtag", "corner", "victim_net_count_with_active_aggressor", "file"], index_rows)
    print(f"active_rows={len(rows)}")
    print(f"union_victim_rows={len(union_rows)}")
    print(f"union_file={union_file}")
    print(f"union_name_only_file={union_name_only_file}")
    print(f"corner_files={len(index_rows)}")
    print(f"out_dir={out_active}")


def main():
    if len(sys.argv) > 1:
        out_dir = Path(sys.argv[1])
    else:
        out_dir = Path(__file__).resolve().parent / "voltage_active_aggressor_path1"
    export_by_corner(out_dir)


if __name__ == "__main__":
    main()
