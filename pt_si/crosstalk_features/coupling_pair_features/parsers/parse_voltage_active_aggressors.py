#!/usr/bin/env python3
import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


ATTR_CHARS = set("ACEILNPSUX")


def is_float(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def looks_like_attr(text):
    return bool(text) and all(ch in ATTR_CHARS for ch in text)


def parse_report(path):
    result = {
        "num_aggressors": "",
        "num_effective": "",
        "rise_delta_delay": "",
        "fall_delta_delay": "",
        "rise": [],
        "fall": [],
        "attr_counts": Counter(),
    }

    section = None
    waiting_for_separator = False
    in_aggressor_table = False
    current = None

    with path.open(errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()

            m = re.search(r"Number of aggressors:\s+(\d+)", line)
            if m:
                result["num_aggressors"] = m.group(1)
                continue

            m = re.search(r"Number of effective \(non-filtered\) aggressors:\s+(\d+)", line)
            if m:
                result["num_effective"] = m.group(1)
                continue

            m = re.search(r"Annotated max rise net delta delay:\s+([0-9.+\-Ee]+)", line)
            if m:
                result["rise_delta_delay"] = m.group(1)
                continue

            m = re.search(r"Annotated max fall net delta delay:\s+([0-9.+\-Ee]+)", line)
            if m:
                result["fall_delta_delay"] = m.group(1)
                continue

            if stripped.startswith("Victim is rising"):
                section = "rise"
                waiting_for_separator = False
                in_aggressor_table = False
                current = None
                continue

            if stripped.startswith("Victim is falling"):
                section = "fall"
                waiting_for_separator = False
                in_aggressor_table = False
                current = None
                continue

            if not section:
                continue

            if "Aggressor" in line and "Attributes" in line:
                waiting_for_separator = True
                in_aggressor_table = False
                current = None
                continue

            if waiting_for_separator:
                if stripped.startswith("--------------"):
                    waiting_for_separator = False
                    in_aggressor_table = True
                continue

            if not in_aggressor_table:
                continue

            if not stripped:
                in_aggressor_table = False
                current = None
                continue

            tokens = stripped.split()
            if len(tokens) >= 2 and looks_like_attr(tokens[-2]) and (tokens[-1] == "-" or is_float(tokens[-1])):
                if current is not None:
                    attrs = tokens[-2]
                    bump = tokens[-1]
                    current["attrs"] = attrs
                    current["bump"] = "" if bump == "-" else bump
                    current["clock"] = " ".join(tokens[:-2])
                    result[section].append(current)
                    result["attr_counts"][attrs] += 1
                    current = None
                continue

            if current is not None and tokens and is_float(tokens[0]):
                current["cap"] = tokens[0]
                current["driver"] = tokens[1] if len(tokens) > 1 else ""
                continue

            if not tokens:
                continue

            current = {
                "net": tokens[0],
                "cap": "",
                "driver": "",
                "clock": "",
                "attrs": "",
                "bump": "",
            }
            if len(tokens) >= 2 and is_float(tokens[1]):
                current["cap"] = tokens[1]
                current["driver"] = tokens[2] if len(tokens) > 2 else ""

    return result


def read_tsv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(path, fieldnames, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sorted_unique(items):
    return sorted(set(item for item in items if item))


def summarize(out_dir):
    arc_rows = [row for row in read_tsv(out_dir / "arc_reports.tsv") if row.get("status") == "OK"]
    path_rows = read_tsv(out_dir / "path_metrics.tsv")

    path_by_vtag = {row["vtag"]: row for row in path_rows}
    by_arc_rows = []
    detail_rows = []
    effective_by_arc_rows = []
    effective_detail_rows = []
    union_by_voltage = defaultdict(lambda: {"rise": set(), "fall": set(), "all": set()})
    active_pairs_by_voltage = defaultdict(set)
    active_pairs_sense_by_voltage = defaultdict(lambda: defaultdict(set))
    arc_active_by_voltage = defaultdict(set)
    report_count_by_voltage = Counter()
    total_aggr_by_voltage = Counter()
    total_eff_by_voltage = Counter()
    attr_counts_by_voltage = defaultdict(Counter)

    for row in arc_rows:
        report_file = Path(row["report_file"])
        parsed = parse_report(report_file)
        voltage = row["voltage"]
        vtag = row["vtag"]
        arc_idx = row["arc_idx"]
        victim = row["victim_net"]
        report_count_by_voltage[vtag] += 1
        if parsed["num_aggressors"]:
            total_aggr_by_voltage[vtag] += int(parsed["num_aggressors"])
        if parsed["num_effective"]:
            total_eff_by_voltage[vtag] += int(parsed["num_effective"])
        attr_counts_by_voltage[vtag].update(parsed["attr_counts"])

        active = {}
        reported = {}
        for sense in ("rise", "fall"):
            reported[sense] = parsed[sense]
            for entry in reported[sense]:
                effective_detail_rows.append({
                    "voltage": voltage,
                    "vtag": vtag,
                    "arc_idx": arc_idx,
                    "victim_net": victim,
                    "sense": sense,
                    "aggressor_net": entry["net"],
                    "coupling_cap_pf": entry["cap"],
                    "driver": entry["driver"],
                    "clock": entry["clock"],
                    "attrs": entry["attrs"],
                    "is_active_A": "1" if "A" in entry["attrs"] else "0",
                    "is_small_bump_screened_S": "1" if "S" in entry["attrs"] else "0",
                    "is_no_overlap_N": "1" if "N" in entry["attrs"] else "0",
                    "is_logical_screened_L": "1" if "L" in entry["attrs"] else "0",
                    "switching_bump_ratio_vdd": entry["bump"],
                    "from_pin": row["from_pin"],
                    "to_pin": row["to_pin"],
                    "report_file": row["report_file"],
                })

            active[sense] = [entry for entry in parsed[sense] if "A" in entry["attrs"]]
            for entry in active[sense]:
                key = (victim, entry["net"])
                union_by_voltage[vtag][sense].add(entry["net"])
                union_by_voltage[vtag]["all"].add(entry["net"])
                active_pairs_by_voltage[vtag].add(key)
                active_pairs_sense_by_voltage[vtag][sense].add(key)
                arc_active_by_voltage[vtag].add(arc_idx)
                detail_rows.append({
                    "voltage": voltage,
                    "vtag": vtag,
                    "arc_idx": arc_idx,
                    "victim_net": victim,
                    "sense": sense,
                    "aggressor_net": entry["net"],
                    "coupling_cap_pf": entry["cap"],
                    "driver": entry["driver"],
                    "clock": entry["clock"],
                    "attrs": entry["attrs"],
                    "switching_bump_ratio_vdd": entry["bump"],
                    "from_pin": row["from_pin"],
                    "to_pin": row["to_pin"],
                })

        rise_attrs = Counter(entry["attrs"] for entry in reported["rise"])
        fall_attrs = Counter(entry["attrs"] for entry in reported["fall"])
        effective_by_arc_rows.append({
            "voltage": voltage,
            "vtag": vtag,
            "arc_idx": arc_idx,
            "victim_net": victim,
            "from_pin": row["from_pin"],
            "to_pin": row["to_pin"],
            "num_aggressors": parsed["num_aggressors"],
            "num_effective": parsed["num_effective"],
            "rise_delta_delay": parsed["rise_delta_delay"],
            "fall_delta_delay": parsed["fall_delta_delay"],
            "rise_reported_table_count": len(reported["rise"]),
            "fall_reported_table_count": len(reported["fall"]),
            "rise_A_count": rise_attrs.get("A", 0),
            "rise_S_count": rise_attrs.get("S", 0),
            "rise_N_count": rise_attrs.get("N", 0),
            "rise_L_count": rise_attrs.get("L", 0),
            "fall_A_count": fall_attrs.get("A", 0),
            "fall_S_count": fall_attrs.get("S", 0),
            "fall_N_count": fall_attrs.get("N", 0),
            "fall_L_count": fall_attrs.get("L", 0),
            "rise_reported_nets": ";".join(entry["net"] for entry in reported["rise"]),
            "fall_reported_nets": ";".join(entry["net"] for entry in reported["fall"]),
            "rise_reported_attrs": ";".join(entry["attrs"] for entry in reported["rise"]),
            "fall_reported_attrs": ";".join(entry["attrs"] for entry in reported["fall"]),
        })

        by_arc_rows.append({
            "voltage": voltage,
            "vtag": vtag,
            "arc_idx": arc_idx,
            "victim_net": victim,
            "from_pin": row["from_pin"],
            "to_pin": row["to_pin"],
            "num_aggressors": parsed["num_aggressors"],
            "num_effective": parsed["num_effective"],
            "rise_delta_delay": parsed["rise_delta_delay"],
            "fall_delta_delay": parsed["fall_delta_delay"],
            "rise_active_count": len(active["rise"]),
            "fall_active_count": len(active["fall"]),
            "rise_active_nets": ";".join(entry["net"] for entry in active["rise"]),
            "fall_active_nets": ";".join(entry["net"] for entry in active["fall"]),
        })

    summary_rows = []
    union_rows = []
    for row in path_rows:
        vtag = row["vtag"]
        voltage = row["voltage"]
        attrs = attr_counts_by_voltage[vtag]
        summary_rows.append({
            "voltage": voltage,
            "vtag": vtag,
            "path_point_count": row["point_count"],
            "path_net_arc_count": row["net_arc_count"],
            "report_arc_count": report_count_by_voltage[vtag],
            "path_slack": row["slack"],
            "path_arrival": row["arrival"],
            "path_required": row["required"],
            "total_reported_aggressor_instances": total_aggr_by_voltage[vtag],
            "total_effective_aggressor_instances": total_eff_by_voltage[vtag],
            "active_arc_count": len(arc_active_by_voltage[vtag]),
            "rise_active_pair_count": len(active_pairs_sense_by_voltage[vtag]["rise"]),
            "fall_active_pair_count": len(active_pairs_sense_by_voltage[vtag]["fall"]),
            "all_active_pair_union_count": len(active_pairs_by_voltage[vtag]),
            "rise_active_aggressor_union_count": len(union_by_voltage[vtag]["rise"]),
            "fall_active_aggressor_union_count": len(union_by_voltage[vtag]["fall"]),
            "all_active_aggressor_union_count": len(union_by_voltage[vtag]["all"]),
            "attr_A_instances": attrs.get("A", 0),
            "attr_S_instances": attrs.get("S", 0),
            "attr_N_instances": attrs.get("N", 0),
            "attr_L_instances": attrs.get("L", 0),
            "attr_I_instances": attrs.get("I", 0),
            "attr_X_instances": attrs.get("X", 0),
            "attr_U_instances": attrs.get("U", 0),
            "attr_C_instances": attrs.get("C", 0),
            "attr_P_instances": attrs.get("P", 0),
            "attr_E_instances": attrs.get("E", 0),
        })
        union_rows.append({
            "voltage": voltage,
            "vtag": vtag,
            "rise_active_aggressor_nets": ";".join(sorted_unique(union_by_voltage[vtag]["rise"])),
            "fall_active_aggressor_nets": ";".join(sorted_unique(union_by_voltage[vtag]["fall"])),
            "all_active_aggressor_nets": ";".join(sorted_unique(union_by_voltage[vtag]["all"])),
        })

    ref_vtag = "0p8"
    ref_aggressors = union_by_voltage[ref_vtag]["all"]
    ref_pairs = active_pairs_by_voltage[ref_vtag]
    compare_rows = []
    for row in path_rows:
        vtag = row["vtag"]
        voltage = row["voltage"]
        aggr = union_by_voltage[vtag]["all"]
        pairs = active_pairs_by_voltage[vtag]
        aggr_union = aggr | ref_aggressors
        pair_union = pairs | ref_pairs
        aggr_only_this = sorted(aggr - ref_aggressors)
        aggr_missing = sorted(ref_aggressors - aggr)
        pair_only_this = sorted(pairs - ref_pairs)
        pair_missing = sorted(ref_pairs - pairs)
        compare_rows.append({
            "voltage": voltage,
            "vtag": vtag,
            "active_aggressor_union_count": len(aggr),
            "active_aggressor_common_with_0p8": len(aggr & ref_aggressors),
            "active_aggressor_only_this_vs_0p8": len(aggr_only_this),
            "active_aggressor_missing_vs_0p8": len(aggr_missing),
            "active_aggressor_jaccard_vs_0p8": f"{(len(aggr & ref_aggressors) / len(aggr_union)):.6f}" if aggr_union else "1.000000",
            "active_pair_union_count": len(pairs),
            "active_pair_common_with_0p8": len(pairs & ref_pairs),
            "active_pair_only_this_vs_0p8": len(pair_only_this),
            "active_pair_missing_vs_0p8": len(pair_missing),
            "active_pair_jaccard_vs_0p8": f"{(len(pairs & ref_pairs) / len(pair_union)):.6f}" if pair_union else "1.000000",
            "only_this_aggressor_nets": ";".join(aggr_only_this),
            "missing_0p8_aggressor_nets": ";".join(aggr_missing),
            "only_this_pairs": ";".join(f"{victim}->{aggr}" for victim, aggr in pair_only_this),
            "missing_0p8_pairs": ";".join(f"{victim}->{aggr}" for victim, aggr in pair_missing),
        })

    signature_rows = []
    ref_pins = None
    ref_nets = None
    ref_hash = ""
    ref_net_hash = ""
    for row in path_rows:
        vtag = row["vtag"]
        point_file = out_dir / vtag / "path_points.tsv"
        points = read_tsv(point_file)
        pins = [point["pin"] for point in points]
        nets = [point["net"] for point in points]
        digest = hashlib.sha1("\n".join(pins).encode()).hexdigest()
        net_digest = hashlib.sha1("\n".join(nets).encode()).hexdigest()
        if row["voltage"] == "0.800":
            ref_pins = pins
            ref_nets = nets
            ref_hash = digest
            ref_net_hash = net_digest
        signature_rows.append({
            "voltage": row["voltage"],
            "vtag": vtag,
            "point_count": len(pins),
            "pin_sequence_sha1": digest,
            "net_sequence_sha1": net_digest,
            "same_as_0p8": "",
            "same_net_sequence_as_0p8": "",
        })

    if ref_pins is None:
        ref_pins = []
    if ref_nets is None:
        ref_nets = []
    for row in signature_rows:
        point_file = out_dir / row["vtag"] / "path_points.tsv"
        points = read_tsv(point_file)
        pins = [point["pin"] for point in points]
        nets = [point["net"] for point in points]
        row["same_as_0p8"] = "1" if pins == ref_pins else "0"
        row["same_net_sequence_as_0p8"] = "1" if nets == ref_nets else "0"

    write_tsv(out_dir / "voltage_active_aggressor_summary.tsv", list(summary_rows[0].keys()), summary_rows)
    write_tsv(out_dir / "voltage_active_aggressor_by_arc.tsv", list(by_arc_rows[0].keys()), by_arc_rows)
    write_tsv(out_dir / "voltage_active_aggressor_detail.tsv", list(detail_rows[0].keys()), detail_rows)
    write_tsv(out_dir / "voltage_effective_aggressor_by_arc.tsv", list(effective_by_arc_rows[0].keys()), effective_by_arc_rows)
    write_tsv(out_dir / "voltage_effective_aggressor_detail.tsv", list(effective_detail_rows[0].keys()), effective_detail_rows)
    write_tsv(out_dir / "voltage_active_aggressor_union.tsv", list(union_rows[0].keys()), union_rows)
    write_tsv(out_dir / "voltage_active_aggressor_compare_vs_0p8.tsv", list(compare_rows[0].keys()), compare_rows)
    write_tsv(out_dir / "path_signature.tsv", list(signature_rows[0].keys()), signature_rows)

    print(f"parsed_reports={len(arc_rows)}")
    print(f"wrote={out_dir / 'voltage_active_aggressor_summary.tsv'}")
    print(f"wrote={out_dir / 'voltage_active_aggressor_by_arc.tsv'}")
    print(f"wrote={out_dir / 'voltage_active_aggressor_detail.tsv'}")
    print(f"wrote={out_dir / 'voltage_effective_aggressor_by_arc.tsv'}")
    print(f"wrote={out_dir / 'voltage_effective_aggressor_detail.tsv'}")
    print(f"wrote={out_dir / 'voltage_active_aggressor_union.tsv'}")
    print(f"wrote={out_dir / 'voltage_active_aggressor_compare_vs_0p8.tsv'}")
    print(f"wrote={out_dir / 'path_signature.tsv'}")


def main():
    if len(sys.argv) > 1:
        out_dir = Path(sys.argv[1])
    else:
        out_dir = Path(__file__).resolve().parent / "voltage_active_aggressor_path1"
    summarize(out_dir)


if __name__ == "__main__":
    main()
