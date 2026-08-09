#!/usr/bin/env python3

import csv
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ATTR_CHARS = set("ACEILNPSUX")


def is_float(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def looks_like_attr(text: str) -> bool:
    return bool(text) and all(ch in ATTR_CHARS for ch in text)


def parse_report_lines(lines: List[str]) -> Dict[str, object]:
    result: Dict[str, object] = {
        "num_aggressors": "",
        "num_effective": "",
        "rise_delta_delay": "",
        "rise_delta_mode": "",
        "fall_delta_delay": "",
        "fall_delta_mode": "",
        "rise": [],
        "fall": [],
        "attr_counts": Counter(),
    }

    section = None
    waiting_for_separator = False
    in_aggressor_table = False
    current = None

    for line in lines:
        stripped = line.strip()

        match = re.search(r"Number of aggressors:\s+(\d+)", line)
        if match:
            result["num_aggressors"] = match.group(1)
            continue

        match = re.search(r"Number of effective \(non-filtered\) aggressors:\s+(\d+)", line)
        if match:
            result["num_effective"] = match.group(1)
            continue

        match = re.search(r"Annotated (max|min) rise net delta delay:\s+([0-9.+\-Ee]+)", line)
        if match:
            result["rise_delta_mode"] = match.group(1)
            result["rise_delta_delay"] = match.group(2)
            continue

        match = re.search(r"Annotated (max|min) fall net delta delay:\s+([0-9.+\-Ee]+)", line)
        if match:
            result["fall_delta_mode"] = match.group(1)
            result["fall_delta_delay"] = match.group(2)
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


def read_raw_blocks(path: Path) -> Dict[str, Dict[str, object]]:
    blocks: Dict[str, Dict[str, object]] = {}
    meta: Optional[Dict[str, str]] = None
    lines: List[str] = []

    with path.open(errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line == "### PATH_CONTEXT_BEGIN":
                meta = {}
                lines = []
                continue
            if line == "### PATH_CONTEXT_END":
                if meta is not None:
                    parsed = parse_report_lines(lines) if meta.get("status") == "OK" else parse_report_lines([])
                    parsed["meta"] = meta
                    blocks[meta["context_id"]] = parsed
                meta = None
                lines = []
                continue
            if meta is not None and line.startswith("### "):
                payload = line[4:]
                if "=" in payload:
                    key, value = payload.split("=", 1)
                    meta[key] = value
                continue
            if meta is not None:
                lines.append(line)

    return blocks


def load_contexts(path: Path) -> Dict[Tuple[str, str, str], str]:
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return {
            (row["victim_net"], row["victim_driver_pin"], row["victim_load_pin"]): row["context_id"]
            for row in reader
        }


def write_summary(blocks: Dict[str, Dict[str, object]], out: Path) -> None:
    fieldnames = [
        "context_id",
        "victim_net",
        "victim_driver_pin",
        "victim_load_pin",
        "report_status",
        "message",
        "number_of_aggressors",
        "number_of_effective_aggressors",
        "rise_delta_delay",
        "fall_delta_delay",
        "rise_reported_count",
        "fall_reported_count",
        "rise_active_count",
        "fall_active_count",
    ]
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for context_id in sorted(blocks, key=lambda x: int(x)):
            block = blocks[context_id]
            meta = block["meta"]
            rise = block["rise"]
            fall = block["fall"]
            writer.writerow({
                "context_id": context_id,
                "victim_net": meta.get("victim_net", ""),
                "victim_driver_pin": meta.get("victim_driver_pin", ""),
                "victim_load_pin": meta.get("victim_load_pin", ""),
                "report_status": meta.get("status", ""),
                "message": meta.get("message", ""),
                "number_of_aggressors": block.get("num_aggressors", ""),
                "number_of_effective_aggressors": block.get("num_effective", ""),
                "rise_delta_delay": block.get("rise_delta_delay", ""),
                "fall_delta_delay": block.get("fall_delta_delay", ""),
                "rise_reported_count": len(rise),
                "fall_reported_count": len(fall),
                "rise_active_count": sum(1 for item in rise if "A" in item["attrs"]),
                "fall_active_count": sum(1 for item in fall if "A" in item["attrs"]),
            })


def edge_to_sense(edge: str) -> str:
    return {"r": "rise", "f": "fall"}.get(edge, "")


def expected_delta_mode(analysis_type: str) -> str:
    analysis = analysis_type.lower()
    if analysis == "setup":
        return "max"
    if analysis == "hold":
        return "min"
    return ""


def validate_delta_modes(blocks: Dict[str, Dict[str, object]], analysis_type: str) -> None:
    expected = expected_delta_mode(analysis_type)
    if not expected:
        return

    mismatches: List[str] = []
    missing: List[str] = []
    for context_id, block in blocks.items():
        meta = block.get("meta", {})
        if meta.get("status") != "OK":
            continue
        modes = []
        for sense in ("rise", "fall"):
            delay = block.get(f"{sense}_delta_delay", "")
            mode = block.get(f"{sense}_delta_mode", "")
            if not delay:
                continue
            if not mode:
                missing.append(str(context_id))
            elif mode != expected:
                modes.append(f"{sense}:{mode}")
        if modes:
            mismatches.append(f"context_id={context_id} modes={','.join(modes)}")

    if missing or mismatches:
        print(
            f"ERROR: report_delay_calculation delta mode mismatch for analysis_type={analysis_type}; "
            f"expected Annotated {expected} net delta delay.",
            file=sys.stderr,
        )
        for item in mismatches[:20]:
            print(f"  mismatch {item}", file=sys.stderr)
        if len(mismatches) > 20:
            print(f"  ... {len(mismatches) - 20} more mismatches", file=sys.stderr)
        if missing:
            print(f"  missing mode contexts: {', '.join(missing[:20])}", file=sys.stderr)
            if len(missing) > 20:
                print(f"  ... {len(missing) - 20} more missing-mode contexts", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "usage: parse_path_context_delay_calculation.py "
            "<path_victim_nets.tsv> <unique_contexts.tsv> <raw_report.rpt> "
            "<summary.tsv> <active_features.tsv>",
            file=sys.stderr,
        )
        return 2

    path_rows_file = Path(sys.argv[1])
    context_file = Path(sys.argv[2])
    raw_report = Path(sys.argv[3])
    summary_out = Path(sys.argv[4])
    active_out = Path(sys.argv[5])
    corner = os.environ.get("PT_FEATURE_CORNER", "")
    analysis_type = os.environ.get("PT_FEATURE_ANALYSIS_TYPE", "")
    voltage = os.environ.get("PT_FEATURE_VOLTAGE", "")
    temperature = os.environ.get("PT_FEATURE_TEMPERATURE", "")

    context_id_by_key = load_contexts(context_file)
    blocks = read_raw_blocks(raw_report)
    validate_delta_modes(blocks, analysis_type)
    write_summary(blocks, summary_out)

    fieldnames = [
        "corner",
        "analysis_type",
        "voltage",
        "temperature",
        "path_id",
        "path_key",
        "startpoint",
        "endpoint",
        "path_group",
        "path_type",
        "slack_status",
        "slack",
        "arc_idx",
        "context_id",
        "victim_net",
        "victim_driver_pin",
        "victim_driver_edge",
        "victim_load_pin",
        "victim_load_edge",
        "victim_sense",
        "fanout",
        "cap",
        "dist",
        "res",
        "cpin",
        "report_status",
        "number_of_aggressors",
        "number_of_effective_aggressors",
        "rise_delta_delay",
        "fall_delta_delay",
        "crosstalk_delta",
        "row_type",
        "aggressor_net",
        "aggressor_coupling_cap_pf",
        "aggressor_driver",
        "aggressor_clock",
        "aggressor_attrs",
        "aggressor_switching_bump_ratio_vdd",
    ]

    rows_in = 0
    rows_out = 0
    active_rows = 0
    victim_only_rows = 0
    missing_context = 0
    status_counts: Counter[str] = Counter()

    with path_rows_file.open(newline="") as pf, active_out.open("w", newline="") as of:
        reader = csv.DictReader(pf, delimiter="\t")
        writer = csv.DictWriter(of, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()

        for row in reader:
            rows_in += 1
            key = (row["victim_net"], row["victim_driver_pin"], row["victim_load_pin"])
            context_id = context_id_by_key.get(key, "")
            block = blocks.get(context_id, {})
            meta = block.get("meta", {})
            status = meta.get("status", "CONTEXT_MISSING")
            if status == "CONTEXT_MISSING":
                missing_context += 1
            status_counts[status] += 1

            victim_sense = edge_to_sense(row.get("victim_load_edge", ""))
            candidates = block.get(victim_sense, []) if victim_sense else []
            active = [item for item in candidates if "A" in item["attrs"]]
            crosstalk_delta = ""
            if victim_sense == "rise":
                crosstalk_delta = block.get("rise_delta_delay", "")
            elif victim_sense == "fall":
                crosstalk_delta = block.get("fall_delta_delay", "")

            base = {
                "corner": corner,
                "analysis_type": analysis_type,
                "voltage": voltage,
                "temperature": temperature,
                "path_id": row["path_id"],
                "path_key": row["path_key"],
                "startpoint": row["startpoint"],
                "endpoint": row["endpoint"],
                "path_group": row["path_group"],
                "path_type": row["path_type"],
                "slack_status": row["slack_status"],
                "slack": row["slack"],
                "arc_idx": row["arc_idx"],
                "context_id": context_id,
                "victim_net": row["victim_net"],
                "victim_driver_pin": row["victim_driver_pin"],
                "victim_driver_edge": row.get("victim_driver_edge", ""),
                "victim_load_pin": row["victim_load_pin"],
                "victim_load_edge": row.get("victim_load_edge", ""),
                "victim_sense": victim_sense,
                "fanout": row["fanout"],
                "cap": row["cap"],
                "dist": row["dist"],
                "res": row["res"],
                "cpin": row["cpin"],
                "report_status": status,
                "number_of_aggressors": block.get("num_aggressors", ""),
                "number_of_effective_aggressors": block.get("num_effective", ""),
                "rise_delta_delay": block.get("rise_delta_delay", ""),
                "fall_delta_delay": block.get("fall_delta_delay", ""),
                "crosstalk_delta": crosstalk_delta,
            }

            if not active:
                out = dict(base)
                out.update({
                    "row_type": "victim_only_no_active_aggressor",
                    "aggressor_net": "",
                    "aggressor_coupling_cap_pf": "",
                    "aggressor_driver": "",
                    "aggressor_clock": "",
                    "aggressor_attrs": "",
                    "aggressor_switching_bump_ratio_vdd": "",
                })
                writer.writerow(out)
                rows_out += 1
                victim_only_rows += 1
                continue

            for item in active:
                out = dict(base)
                out.update({
                    "row_type": "active_aggressor",
                    "aggressor_net": item["net"],
                    "aggressor_coupling_cap_pf": item["cap"],
                    "aggressor_driver": item["driver"],
                    "aggressor_clock": item["clock"],
                    "aggressor_attrs": item["attrs"],
                    "aggressor_switching_bump_ratio_vdd": item["bump"],
                })
                writer.writerow(out)
                rows_out += 1
                active_rows += 1

    print(f"path_victim_rows_in={rows_in}")
    print(f"rows_out={rows_out}")
    print(f"active_aggressor_rows={active_rows}")
    print(f"victim_only_no_active_rows={victim_only_rows}")
    print(f"missing_context_rows={missing_context}")
    print(f"status_counts={dict(status_counts)}")
    print(f"summary={summary_out}")
    print(f"active_features={active_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
