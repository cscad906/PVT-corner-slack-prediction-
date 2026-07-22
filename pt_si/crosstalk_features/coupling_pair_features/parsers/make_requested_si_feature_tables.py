#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)


# All inputs come from SI_FEATURE_* environment variables (the unified TCL
# sets every one of them before invoking this script). BASE is only a
# standalone-run fallback root.
BASE = Path(os.environ.get("SI_FEATURE_BASE", str(Path.cwd())))
ANALYSIS = Path(os.environ.get("SI_FEATURE_ANALYSIS", str(BASE / "analysis/coupling_counts")))
OUT_DIR = Path(os.environ.get("SI_FEATURE_OUT_DIR", str(ANALYSIS / "requested_si_features_path1")))
ACTIVE_DIR = Path(os.environ.get("SI_FEATURE_ACTIVE_DIR", str(ANALYSIS / "voltage_active_aggressor_path1/active_only_by_corner")))
ACTIVE_INDEX = Path(os.environ.get("SI_FEATURE_ACTIVE_INDEX", str(ACTIVE_DIR / "index.tsv")))
DRIVER_WINDOW_FILE = Path(
    os.environ.get("SI_FEATURE_WINDOW_FILE", str(ANALYSIS / "timing_windows_by_voltage_from_union/all_voltages_net_driver_timing_windows.tsv"))
)
VICTIM_LOAD_WINDOW_FILE = Path(
    os.environ.get("SI_FEATURE_VICTIM_LOAD_WINDOW_FILE", str(ANALYSIS / "timing_windows_by_voltage_from_union/all_voltages_victim_path_load_windows.tsv"))
)
RAW_ATTR_FILE = Path(os.environ.get("SI_FEATURE_RAW_ATTR_FILE", str(OUT_DIR / "requested_si_attrs.raw_net_attrs.tsv")))
SPEF = Path(os.environ.get("SI_FEATURE_SPEF", str(BASE / "implementation/spef/smallboom_14nm.Cnom_model_25.spef")))

PAIR_OUT = OUT_DIR / "requested_si_features.active_pairs.tsv"
VICTIM_OUT = OUT_DIR / "requested_si_features.victims.tsv"
SUMMARY_OUT = OUT_DIR / "requested_si_features.summary.tsv"
PAIR_BY_VOLTAGE_DIR = OUT_DIR / "active_pairs_by_voltage"

ACTIVE_RE = re.compile(r"^(rise|fall):(.+)\(bump=([0-9.+\-Ee]+)\)$")
PT_COUPLING_CAP_RE = re.compile(
    r"\{\s*(\S+)\s+\(([^)]+)\)\s+(\S+)\s+\(([^)]+)\)\s+([0-9.+\-Ee]+)\s+(\S+)\s*\}"
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in fieldnames})


def parse_active_items(text: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for item in text.split(";"):
        item = item.strip()
        if not item:
            continue
        match = ACTIVE_RE.match(item)
        if match:
            out.append((match.group(1), match.group(2), match.group(3)))
    return out


def load_active_index() -> dict[str, dict[str, str]]:
    rows = read_tsv(ACTIVE_INDEX)
    return {row["vtag"]: row for row in rows}


def load_active_pairs(active_index: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str, str], dict[str, str]] = {}
    for vtag, idx_row in active_index.items():
        active_file = Path(idx_row["file"])
        for row in read_tsv(active_file):
            victim = row["victim_net"]
            for sense, aggressor, bump in parse_active_items(row["active_aggressors_by_noise_bump"]):
                key = (vtag, victim, aggressor)
                existing = merged.get(key)
                if existing is None:
                    merged[key] = {
                        "voltage": idx_row["voltage"],
                        "vtag": vtag,
                        "corner": idx_row["corner"],
                        "victim_net": victim,
                        "aggressor_net": aggressor,
                        "active_bump_max": bump,
                    }
                    continue
                current = finite_float(existing.get("active_bump_max", ""))
                candidate = finite_float(bump)
                if candidate is not None and (current is None or abs(candidate) > abs(current)):
                    existing["active_bump_max"] = bump
    return list(merged.values())


def load_driver_windows() -> dict[tuple[str, str], dict[str, str]]:
    rows = read_tsv(DRIVER_WINDOW_FILE)
    return {(row["vtag"], row["net"]): row for row in rows}


def load_victim_load_windows() -> dict[tuple[str, str], dict[str, str]]:
    rows = read_tsv(VICTIM_LOAD_WINDOW_FILE)
    return {(row["vtag"], row["victim_net"]): row for row in rows}


def victim_load_pin(vwin: dict[str, str]) -> str:
    return vwin.get("victim_load_pin", vwin.get("path_to_pin", ""))


def load_raw_attrs() -> dict[tuple[str, str], dict[str, str]]:
    rows = read_tsv(RAW_ATTR_FILE)
    return {(row["vtag"], row["victim_net"]): row for row in rows}


def endpoint_net_id(token: str) -> str:
    return token.split(":", 1)[0]


def endpoint_key(token: str) -> str:
    return token


def maybe_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def build_requested_pair_set(active_pairs: list[dict[str, str]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in active_pairs:
        pair = tuple(sorted((row["victim_net"], row["aggressor_net"])))
        out.add(pair)
    return out


def parse_spef_for_pairs(target_pairs: set[tuple[str, str]], target_nets: set[str]) -> tuple[dict[tuple[str, str], float], dict[str, str]]:
    name_by_id: dict[str, str] = {}
    total_cap_by_net: dict[str, str] = {}
    pair_caps: dict[tuple[str, str], float] = defaultdict(float)
    seen_segments: set[tuple[str, str, str]] = set()

    in_name_map = False
    in_cap = False
    current_net_id = ""

    with SPEF.open(errors="replace") as f:
      for raw in f:
        line = raw.strip()
        if not line:
            continue

        if line == "*NAME_MAP":
            in_name_map = True
            continue
        if in_name_map:
            if line.startswith("*D_NET") or line.startswith("*PORTS") or line.startswith("*CONN"):
                in_name_map = False
            elif line.startswith("*"):
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[0][1:].isdigit():
                    name_by_id[parts[0]] = parts[1]
                continue

        if line.startswith("*D_NET"):
            parts = line.split()
            current_net_id = parts[1] if len(parts) > 1 else ""
            current_net_name = name_by_id.get(current_net_id, current_net_id)
            if len(parts) > 2 and current_net_name in target_nets:
                total_cap_by_net[current_net_name] = parts[2]
            in_cap = False
            continue

        if line == "*CAP":
            in_cap = True
            continue
        if line.startswith("*RES") or line.startswith("*END"):
            in_cap = False
            if line.startswith("*END"):
                current_net_id = ""
            continue
        if not in_cap or not current_net_id:
            continue

        parts = line.split()
        if len(parts) < 4:
            continue
        cap = maybe_float(parts[-1])
        if cap is None:
            continue
        ep1, ep2 = parts[1], parts[2]
        net1_id = endpoint_net_id(ep1)
        net2_id = endpoint_net_id(ep2)
        if net1_id == net2_id:
            continue
        net1 = name_by_id.get(net1_id, net1_id)
        net2 = name_by_id.get(net2_id, net2_id)
        pair = tuple(sorted((net1, net2)))
        if pair not in target_pairs:
            continue
        seg_key = tuple(sorted((endpoint_key(ep1), endpoint_key(ep2)))) + (parts[-1],)
        if seg_key in seen_segments:
            continue
        seen_segments.add(seg_key)
        pair_caps[pair] += cap

    return dict(pair_caps), total_cap_by_net


def finite_float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def overlap_width(vmin: str, vmax: str, amin: str, amax: str) -> str:
    vals = [finite_float(x) for x in (vmin, vmax, amin, amax)]
    if any(v is None for v in vals):
        return ""
    lo = max(vals[0], vals[2])
    hi = min(vals[1], vals[3])
    return f"{max(0.0, hi - lo):.6f}"


def pt_coupling_cap_ff(raw_caps: str, victim_net: str, aggressor_net: str) -> float | None:
    cap_pf = 0.0
    found = False
    wanted = {victim_net, aggressor_net}
    for match in PT_COUPLING_CAP_RE.finditer(raw_caps):
        net1 = match.group(2)
        net2 = match.group(4)
        status = match.group(6)
        if status != "not_filtered" or {net1, net2} != wanted:
            continue
        cap = finite_float(match.group(5))
        if cap is None:
            continue
        cap_pf += cap
        found = True
    return cap_pf * 1000.0 if found else None


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    active_index = load_active_index()
    active_pairs = load_active_pairs(active_index)
    driver_windows = load_driver_windows()
    victim_load_windows = load_victim_load_windows()
    raw_attrs = load_raw_attrs()

    target_pairs = build_requested_pair_set(active_pairs)
    target_nets = {row["victim_net"] for row in active_pairs} | {row["aggressor_net"] for row in active_pairs}
    pair_caps, total_cap_by_net = parse_spef_for_pairs(target_pairs, target_nets)

    pair_rows: list[dict[str, object]] = []
    summary: dict[str, dict[str, object]] = {}
    for row in active_pairs:
        key = (row["vtag"], row["victim_net"])
        attrs = raw_attrs.get(key, {})
        vwin = victim_load_windows.get((row["vtag"], row["victim_net"]), {})
        awin = driver_windows.get((row["vtag"], row["aggressor_net"]), {})
        pair = tuple(sorted((row["victim_net"], row["aggressor_net"])))
        cap = pair_caps.get(pair)
        if cap is None:
            cap = pt_coupling_cap_ff(attrs.get("coupling_capacitors", ""), row["victim_net"], row["aggressor_net"])

        out = {
            **row,
            "crosstalk_delta": attrs.get("annotated_delay_delta_max", ""),
            "aggressor_bump": row.get("active_bump_max", ""),
            "victim_load_pin": victim_load_pin(vwin),
            "victim_load_min_arrival": vwin.get("overall_min", ""),
            "victim_load_max_arrival": vwin.get("overall_max", ""),
            "aggressor_driver_pin": awin.get("driver_pin", ""),
            "aggressor_driver_min_arrival": awin.get("overall_min", ""),
            "aggressor_driver_max_arrival": awin.get("overall_max", ""),
            "aggressor_driver_slew_max": awin.get("slew_max", ""),
            "coupling_cap_ff": f"{cap:.9g}" if cap is not None else "",
            "victim_total_cap_ff": total_cap_by_net.get(row["victim_net"], ""),
            "aggressor_total_cap_ff": total_cap_by_net.get(row["aggressor_net"], ""),
            "si_xtalk_bumps_max_rise_raw": attrs.get("si_xtalk_bumps_max_rise", ""),
            "coupling_capacitors_raw": attrs.get("coupling_capacitors", ""),
            "effective_coupling_capacitors_raw": attrs.get("effective_coupling_capacitors", ""),
        }
        pair_rows.append(out)

        s = summary.setdefault(
            row["vtag"],
            {
                "voltage": row["voltage"],
                "vtag": row["vtag"],
                "active_pair_rows": 0,
                "unique_victims": set(),
                "unique_aggressors": set(),
                "missing_coupling_cap_rows": 0,
                "missing_victim_window_rows": 0,
                "missing_aggressor_window_rows": 0,
                "missing_delta_rows": 0,
            },
        )
        s["active_pair_rows"] += 1
        s["unique_victims"].add(row["victim_net"])
        s["unique_aggressors"].add(row["aggressor_net"])
        if cap is None:
            s["missing_coupling_cap_rows"] += 1
        if not vwin:
            s["missing_victim_window_rows"] += 1
        if not awin:
            s["missing_aggressor_window_rows"] += 1
        if not attrs.get("annotated_delay_delta_max") and not attrs.get("annotated_delay_delta_min"):
            s["missing_delta_rows"] += 1

    victim_rows: list[dict[str, object]] = []
    for (vtag, victim), attrs in sorted(raw_attrs.items(), key=lambda item: (item[1].get("voltage", ""), item[0][1])):
        vwin = victim_load_windows.get((vtag, victim), {})
        victim_rows.append(
            {
                "voltage": attrs.get("voltage", ""),
                "vtag": vtag,
                "victim_net": victim,
                "crosstalk_delta": attrs.get("annotated_delay_delta_max", ""),
                "victim_load_pin": victim_load_pin(vwin),
                "victim_load_min_arrival": vwin.get("overall_min", ""),
                "victim_load_max_arrival": vwin.get("overall_max", ""),
                "total_coupling_capacitance": attrs.get("total_coupling_capacitance", ""),
                "total_effective_coupling_capacitance": attrs.get("total_effective_coupling_capacitance", ""),
                "aggressors": attrs.get("aggressors", ""),
                "effective_aggressors": attrs.get("effective_aggressors", ""),
                "si_xtalk_bumps_max_rise_raw": attrs.get("si_xtalk_bumps_max_rise", ""),
                "coupling_capacitors_raw": attrs.get("coupling_capacitors", ""),
                "effective_coupling_capacitors_raw": attrs.get("effective_coupling_capacitors", ""),
                "status": attrs.get("status", ""),
            }
        )

    summary_rows: list[dict[str, object]] = []
    for key in sorted(summary, key=lambda k: float(summary[k]["voltage"])):
        row = summary[key]
        summary_rows.append(
            {
                "voltage": row["voltage"],
                "vtag": row["vtag"],
                "active_pair_rows": row["active_pair_rows"],
                "unique_victim_count": len(row["unique_victims"]),
                "unique_aggressor_count": len(row["unique_aggressors"]),
                "missing_coupling_cap_rows": row["missing_coupling_cap_rows"],
                "missing_victim_window_rows": row["missing_victim_window_rows"],
                "missing_aggressor_window_rows": row["missing_aggressor_window_rows"],
                "missing_delta_rows": row["missing_delta_rows"],
            }
        )

    pair_fields = [
        "voltage",
        "vtag",
        "corner",
        "victim_net",
        "aggressor_net",
        "crosstalk_delta",
        "aggressor_bump",
        "victim_load_pin",
        "victim_load_min_arrival",
        "victim_load_max_arrival",
        "aggressor_driver_pin",
        "aggressor_driver_min_arrival",
        "aggressor_driver_max_arrival",
        "aggressor_driver_slew_max",
        "coupling_cap_ff",
    ]
    victim_fields = [
        "voltage",
        "vtag",
        "victim_net",
        "crosstalk_delta",
        "victim_load_pin",
        "victim_load_min_arrival",
        "victim_load_max_arrival",
        "status",
    ]
    summary_fields = [
        "voltage",
        "vtag",
        "active_pair_rows",
        "unique_victim_count",
        "unique_aggressor_count",
        "missing_coupling_cap_rows",
        "missing_victim_window_rows",
        "missing_aggressor_window_rows",
        "missing_delta_rows",
    ]

    write_tsv(PAIR_OUT, pair_fields, pair_rows)
    write_tsv(VICTIM_OUT, victim_fields, victim_rows)
    write_tsv(SUMMARY_OUT, summary_fields, summary_rows)

    PAIR_BY_VOLTAGE_DIR.mkdir(parents=True, exist_ok=True)
    pair_by_voltage_fields = [field for field in pair_fields if field not in {"voltage", "vtag"}]
    for vtag in sorted({str(row["vtag"]) for row in pair_rows}, key=lambda x: float(active_index[x]["voltage"])):
        voltage_rows = [row for row in pair_rows if row["vtag"] == vtag]
        write_tsv(PAIR_BY_VOLTAGE_DIR / f"{vtag}.active_pairs.tsv", pair_by_voltage_fields, voltage_rows)

    print(f"Wrote {PAIR_OUT} ({len(pair_rows)} rows)")
    print(f"Wrote {VICTIM_OUT} ({len(victim_rows)} rows)")
    print(f"Wrote {SUMMARY_OUT} ({len(summary_rows)} rows)")
    print(f"Wrote {PAIR_BY_VOLTAGE_DIR} ({len({row['vtag'] for row in pair_rows})} files)")


if __name__ == "__main__":
    main()
