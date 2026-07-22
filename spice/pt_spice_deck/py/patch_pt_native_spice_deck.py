#!/usr/bin/env python3
"""Patch one PrimeTime native SPICE deck with ML-provided path conditions."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
TIME_RE = re.compile(rf"^\s*({FLOAT_RE})([a-zA-Z]*)\s*$")
VOLT_RE = re.compile(rf"^\s*({FLOAT_RE})(\)?)\s*$")


@dataclass
class PwlPoint:
    time_ns: float
    value: float


@dataclass
class PwlBlock:
    start: int
    end: int
    prefix: str
    source_name: str
    signal_node: str
    points: list[PwlPoint]
    direction: str
    comment_start: int
    comment_text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch one PrimeTime write_spice_deck output using ML slew/load/VDD/temp values."
    )
    parser.add_argument("--deck", required=True, type=Path, help="Main SPICE deck, e.g. path_000001.sp")
    parser.add_argument("--stim", required=True, type=Path, help="Stimulus deck, e.g. path_000001_stim.sp")
    parser.add_argument("--summary", type=Path, help="PrimeTime smoke summary with to_pin=...")
    parser.add_argument("--endpoint-node", help="Endpoint node for output load. Overrides --summary to_pin.")
    parser.add_argument("--input-slew-ps", required=True, type=float, help="Target 20-80/80-20 input slew in ps")
    parser.add_argument("--output-load-ff", required=True, type=float, help="Endpoint output load to add in fF")
    parser.add_argument("--target-vdd", required=True, type=float, help="Target VDD in volts")
    parser.add_argument("--target-temp", required=True, type=float, help="Target temperature in Celsius")
    parser.add_argument("--tran-stop-ns", type=float, default=5.0, help="Transient stop time in ns")
    parser.add_argument("--tran-step-ns", type=float, help="Transient step in ns. Keeps existing step if omitted.")
    parser.add_argument("--output-load-cap-name", default="C_ML_OUT_LOAD")
    parser.add_argument("--output-load-ground-node", default="VSS")
    parser.add_argument("--summary-out", type=Path, help="Patch summary JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report planned changes without writing files")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .orig backups before patching")
    return parser.parse_args()


def read_lines(path: Path) -> list[str]:
    return path.read_text().splitlines(keepends=True)


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines))


def backup_once(path: Path) -> Path:
    backup = path.with_name(path.name + ".orig")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def parse_key_value_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def endpoint_from_args(args: argparse.Namespace) -> str:
    if args.endpoint_node:
        return args.endpoint_node
    if not args.summary:
        raise SystemExit("ERROR: provide --endpoint-node or --summary containing to_pin=...")
    data = parse_key_value_file(args.summary)
    endpoint = data.get("to_pin")
    if not endpoint:
        raise SystemExit(f"ERROR: summary does not contain to_pin=: {args.summary}")
    return endpoint


def fmt(value: float) -> str:
    if abs(value) < 1e-18:
        return "0"
    text = f"{value:.12g}"
    return text


def fmt_time_ns(value: float) -> str:
    if value < 0 and abs(value) < 1e-12:
        value = 0.0
    return f"{fmt(value)}ns"


def parse_time_ns(token: str) -> float:
    match = TIME_RE.match(token)
    if not match:
        raise ValueError(f"not a time token: {token!r}")
    value = float(match.group(1))
    unit = match.group(2).lower() or "ns"
    if unit == "s":
        return value * 1e9
    if unit == "ms":
        return value * 1e6
    if unit == "us":
        return value * 1e3
    if unit == "ns":
        return value
    if unit == "ps":
        return value * 1e-3
    if unit == "fs":
        return value * 1e-6
    raise ValueError(f"unsupported time unit {unit!r} in {token!r}")


def parse_voltage_token(token: str) -> float:
    match = VOLT_RE.match(token)
    if not match:
        raise ValueError(f"not a voltage token: {token!r}")
    return float(match.group(1))


def parse_pwl_point_text(text: str) -> PwlPoint | None:
    text = text.strip()
    if not text:
        return None
    if text.endswith(")"):
        text = text[:-1].rstrip()
    parts = text.split()
    if len(parts) < 2:
        return None
    try:
        return PwlPoint(parse_time_ns(parts[0]), parse_voltage_token(parts[1]))
    except ValueError:
        return None


def parse_pwl_block(lines: list[str], start: int) -> tuple[int, str, list[PwlPoint]]:
    line = lines[start].rstrip("\n")
    marker = line.lower().find("pwl(")
    if marker < 0:
        raise ValueError("line is not a PWL source")
    prefix = line[: marker + 4]
    first_text = line[marker + 4 :]
    points: list[PwlPoint] = []
    first = parse_pwl_point_text(first_text)
    if first:
        points.append(first)

    end = start
    if ")" in first_text:
        return end, prefix, points

    for idx in range(start + 1, len(lines)):
        raw = lines[idx].strip()
        if not raw.startswith("+"):
            break
        point = parse_pwl_point_text(raw[1:])
        if point:
            points.append(point)
        end = idx
        if ")" in raw:
            break
    return end, prefix, points


def leading_comments(lines: list[str], source_idx: int, max_lines: int = 8) -> tuple[int, str]:
    start = source_idx
    comments: list[str] = []
    idx = source_idx - 1
    while idx >= 0 and source_idx - idx <= max_lines:
        stripped = lines[idx].lstrip()
        if stripped.startswith("*"):
            start = idx
            comments.append(lines[idx].rstrip("\n"))
            idx -= 1
            continue
        if stripped.startswith("+") or stripped == "":
            idx -= 1
            continue
        break
    comments.reverse()
    return start, "\n".join(comments)


def parse_source_header(line: str) -> tuple[str, str]:
    head = line.split("pwl(", 1)[0].strip()
    parts = head.split()
    if len(parts) < 2:
        return "", ""
    return parts[0], parts[1]


def find_victim_pwl(lines: list[str]) -> PwlBlock:
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("*"):
            continue
        if "pwl(" not in line.lower():
            continue
        comment_start, comment_text = leading_comments(lines, idx)
        if "(victim)" not in comment_text.lower():
            continue
        direction = "rise"
        if "fall slew" in comment_text.lower():
            direction = "fall"
        end, prefix, points = parse_pwl_block(lines, idx)
        if len(points) < 3:
            continue
        source_name, signal_node = parse_source_header(line)
        return PwlBlock(
            start=idx,
            end=end,
            prefix=prefix,
            source_name=source_name,
            signal_node=signal_node,
            points=points,
            direction=direction,
            comment_start=comment_start,
            comment_text=comment_text,
        )
    raise SystemExit("ERROR: could not find an active victim PWL block in stim deck")


def crossing_time(points: list[PwlPoint], threshold: float, direction: str) -> tuple[float, int]:
    for idx in range(len(points) - 1):
        p0 = points[idx]
        p1 = points[idx + 1]
        if p0.value == p1.value:
            continue
        if direction == "rise":
            crossed = p0.value <= threshold <= p1.value
        else:
            crossed = p0.value >= threshold >= p1.value
        if not crossed:
            continue
        ratio = (threshold - p0.value) / (p1.value - p0.value)
        return p0.time_ns + ratio * (p1.time_ns - p0.time_ns), idx
    raise SystemExit(f"ERROR: victim PWL never crosses {threshold:g} V on {direction} edge")


def active_edge_range(t20_idx: int, t80_idx: int, point_count: int) -> tuple[int, int]:
    start = max(0, min(t20_idx, t80_idx))
    end = min(point_count - 1, max(t20_idx, t80_idx) + 1)
    return start, end


def scale_victim_pwl(block: PwlBlock, original_vdd: float, target_vdd: float, target_slew_ps: float) -> dict[str, object]:
    low = original_vdd * 0.2
    mid = original_vdd * 0.5
    high = original_vdd * 0.8
    if block.direction == "rise":
        t20, t20_idx = crossing_time(block.points, low, block.direction)
        t50, cross_idx = crossing_time(block.points, mid, block.direction)
        t80, t80_idx = crossing_time(block.points, high, block.direction)
    else:
        t80, t80_idx = crossing_time(block.points, high, block.direction)
        t50, cross_idx = crossing_time(block.points, mid, block.direction)
        t20, t20_idx = crossing_time(block.points, low, block.direction)

    old_slew_ns = abs(t80 - t20)
    if old_slew_ns <= 0:
        raise SystemExit("ERROR: original victim slew is zero")

    scale = (target_slew_ps * 1e-3) / old_slew_ns
    voltage_scale = target_vdd / original_vdd
    start_idx, end_idx = active_edge_range(t20_idx, t80_idx, len(block.points))

    patched = [PwlPoint(p.time_ns, p.value * voltage_scale) for p in block.points]
    for idx in range(start_idx, end_idx + 1):
        patched[idx].time_ns = t50 + (block.points[idx].time_ns - t50) * scale

    min_gap = 1e-6
    if start_idx > 0 and patched[start_idx].time_ns <= patched[start_idx - 1].time_ns:
        delta = patched[start_idx - 1].time_ns + min_gap - patched[start_idx].time_ns
        for idx in range(start_idx, len(patched)):
            patched[idx].time_ns += delta

    for idx in range(1, len(patched)):
        if patched[idx].time_ns <= patched[idx - 1].time_ns:
            delta = patched[idx - 1].time_ns + min_gap - patched[idx].time_ns
            for j in range(idx, len(patched)):
                patched[j].time_ns += delta

    block.points = patched
    return {
        "victim_source": block.source_name,
        "victim_node": block.signal_node,
        "direction": block.direction,
        "old_slew_ps": old_slew_ns * 1000.0,
        "target_slew_ps": target_slew_ps,
        "time_scale": scale,
        "edge_start_index": start_idx,
        "edge_end_index": end_idx,
        "t50_segment_index": cross_idx,
        "old_t20_ns": t20,
        "old_t50_ns": t50,
        "old_t80_ns": t80,
    }


def render_pwl_block(block: PwlBlock) -> list[str]:
    rendered: list[str] = []
    if not block.points:
        return rendered
    first = block.points[0]
    rendered.append(f"{block.prefix}{fmt_time_ns(first.time_ns)}\t{fmt(first.value)}\n")
    for idx, point in enumerate(block.points[1:], start=1):
        suffix = ")" if idx == len(block.points) - 1 else ""
        rendered.append(f"+\t{fmt_time_ns(point.time_ns)}\t{fmt(point.value)}{suffix}\n")
    return rendered


def patch_param_and_sources(lines: list[str], original_vdd: float, target_vdd: float, target_temp: float) -> list[str]:
    voltage_scale = target_vdd / original_vdd
    patched: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if re.match(r"(?i)^\s*\.param\s+VDD\s*=", line):
            patched.append(re.sub(rf"(?i)(^\s*\.param\s+VDD\s*=\s*){FLOAT_RE}", rf"\g<1>{fmt(target_vdd)}", line))
            continue
        if re.match(r"(?i)^\s*\.temp\b", line):
            patched.append(re.sub(rf"(?i)(^\s*\.temp\s+){FLOAT_RE}", rf"\g<1>{fmt(target_temp)}", line))
            continue
        if stripped.startswith("*") or not stripped:
            patched.append(line)
            continue
        if stripped[0].lower() == "v" and "pwl(" not in stripped.lower():
            parts = line.rstrip("\n").split()
            if len(parts) >= 4:
                try:
                    value = float(parts[3])
                except ValueError:
                    patched.append(line)
                    continue
                parts[3] = fmt(value * voltage_scale)
                patched.append(" ".join(parts) + "\n")
                continue
        patched.append(line)
    return patched


def patch_measure_thresholds(lines: list[str], original_vdd: float, target_vdd: float) -> list[str]:
    voltage_scale = target_vdd / original_vdd

    def repl(match: re.Match[str]) -> str:
        value = float(match.group(2))
        return f"{match.group(1)}{fmt(value * voltage_scale)}"

    return [re.sub(rf"(?i)(\bval\s*=\s*)({FLOAT_RE})", repl, line) for line in lines]


def patch_tran(lines: list[str], tran_stop_ns: float, tran_step_ns: float | None) -> tuple[list[str], dict[str, object]]:
    info: dict[str, object] = {"patched": False}
    patched: list[str] = []
    pattern = re.compile(rf"(?i)^(\s*\.tran\s+)({FLOAT_RE})([a-zA-Z]*)(\s+)({FLOAT_RE})([a-zA-Z]*)(.*)$")
    for line in lines:
        match = pattern.match(line.rstrip("\n"))
        if not match:
            patched.append(line)
            continue
        old_step = parse_time_ns(match.group(2) + (match.group(3) or "ns"))
        old_stop = parse_time_ns(match.group(5) + (match.group(6) or "ns"))
        new_step = old_step if tran_step_ns is None else tran_step_ns
        patched.append(f"{match.group(1)}{fmt_time_ns(new_step)}{match.group(4)}{fmt_time_ns(tran_stop_ns)}{match.group(7)}\n")
        info = {
            "patched": True,
            "old_step_ns": old_step,
            "old_stop_ns": old_stop,
            "new_step_ns": new_step,
            "new_stop_ns": tran_stop_ns,
        }
    return patched, info


def patch_pwl_voltages(lines: list[str], original_vdd: float, target_vdd: float, skip_start: int | None = None, skip_end: int | None = None) -> list[str]:
    voltage_scale = target_vdd / original_vdd
    patched = list(lines)
    idx = 0
    while idx < len(patched):
        line = patched[idx]
        if idx == skip_start:
            idx = (skip_end or idx) + 1
            continue
        if line.lstrip().startswith("*") or "pwl(" not in line.lower():
            idx += 1
            continue
        end, prefix, points = parse_pwl_block(patched, idx)
        for point in points:
            point.value *= voltage_scale
        block = PwlBlock(idx, end, prefix, "", "", points, "rise", idx, "")
        rendered = render_pwl_block(block)
        patched[idx : end + 1] = rendered
        idx += len(rendered)
    return patched


def extract_original_vdd(lines: Iterable[str]) -> float:
    for line in lines:
        match = re.match(rf"(?i)^\s*vVDD\s+VDD\s+0\s+({FLOAT_RE})\b", line)
        if match:
            return float(match.group(1))
    for line in lines:
        match = re.match(rf"(?i)^\s*\.param\s+VDD\s*=\s*({FLOAT_RE})\b", line)
        if match:
            return float(match.group(1))
    raise SystemExit("ERROR: could not determine original VDD from deck")


def insert_output_load(lines: list[str], cap_name: str, endpoint_node: str, ground_node: str, output_load_ff: float) -> list[str]:
    cap_line = f"{cap_name} {endpoint_node} {ground_node} {fmt(output_load_ff)}f\n"
    filtered = [line for line in lines if not re.match(rf"(?i)^\s*{re.escape(cap_name)}\b", line)]
    for idx, line in enumerate(filtered):
        if re.match(r"(?i)^\s*\.end\b", line):
            insert = [
                "* ML patched endpoint output load\n",
                cap_line,
            ]
            return filtered[:idx] + insert + filtered[idx:]
    raise SystemExit("ERROR: could not find .end in main deck")


def patch_deck(
    deck_lines: list[str],
    endpoint_node: str,
    original_vdd: float,
    target_vdd: float,
    target_temp: float,
    output_load_ff: float,
    cap_name: str,
    ground_node: str,
) -> list[str]:
    lines = patch_param_and_sources(deck_lines, original_vdd, target_vdd, target_temp)
    lines = patch_measure_thresholds(lines, original_vdd, target_vdd)
    lines = insert_output_load(lines, cap_name, endpoint_node, ground_node, output_load_ff)
    return lines


def patch_stim(
    stim_lines: list[str],
    original_vdd: float,
    target_vdd: float,
    input_slew_ps: float,
    tran_stop_ns: float,
    tran_step_ns: float | None,
) -> tuple[list[str], dict[str, object]]:
    stim_lines = [
        line
        for line in stim_lines
        if not line.lstrip().startswith("* ML_PATCH input_slew_ps=")
    ]
    lines = patch_measure_thresholds(stim_lines, original_vdd, target_vdd)
    victim = find_victim_pwl(lines)
    victim_info = scale_victim_pwl(victim, original_vdd, target_vdd, input_slew_ps)
    victim_rendered = [
        f"* ML_PATCH input_slew_ps={fmt(input_slew_ps)} old_slew_ps={fmt(float(victim_info['old_slew_ps']))} target_vdd={fmt(target_vdd)}\n"
    ] + render_pwl_block(victim)
    lines[victim.start : victim.end + 1] = victim_rendered
    skip_start = victim.start
    skip_end = victim.start + len(victim_rendered) - 1
    lines = patch_pwl_voltages(lines, original_vdd, target_vdd, skip_start=skip_start, skip_end=skip_end)
    lines, tran_info = patch_tran(lines, tran_stop_ns, tran_step_ns)
    return lines, {"victim": victim_info, "tran": tran_info}


def main() -> None:
    args = parse_args()
    if args.input_slew_ps <= 0:
        raise SystemExit("ERROR: --input-slew-ps must be positive")
    if args.output_load_ff < 0:
        raise SystemExit("ERROR: --output-load-ff must be non-negative")
    if args.target_vdd <= 0:
        raise SystemExit("ERROR: --target-vdd must be positive")
    if args.tran_stop_ns <= 0:
        raise SystemExit("ERROR: --tran-stop-ns must be positive")

    endpoint_node = endpoint_from_args(args)
    deck_lines = read_lines(args.deck)
    stim_lines = read_lines(args.stim)
    original_vdd = extract_original_vdd(deck_lines)

    patched_deck = patch_deck(
        deck_lines,
        endpoint_node,
        original_vdd,
        args.target_vdd,
        args.target_temp,
        args.output_load_ff,
        args.output_load_cap_name,
        args.output_load_ground_node,
    )
    patched_stim, stim_info = patch_stim(
        stim_lines,
        original_vdd,
        args.target_vdd,
        args.input_slew_ps,
        args.tran_stop_ns,
        args.tran_step_ns,
    )

    summary = {
        "deck": str(args.deck),
        "stim": str(args.stim),
        "endpoint_node": endpoint_node,
        "original_vdd": original_vdd,
        "target_vdd": args.target_vdd,
        "target_temp": args.target_temp,
        "input_slew_ps": args.input_slew_ps,
        "output_load_ff": args.output_load_ff,
        "output_load_cap_name": args.output_load_cap_name,
        "output_load_ground_node": args.output_load_ground_node,
        **stim_info,
        "dry_run": args.dry_run,
    }

    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    backups: dict[str, str] = {}
    if not args.no_backup:
        backups["deck"] = str(backup_once(args.deck))
        backups["stim"] = str(backup_once(args.stim))
    write_lines(args.deck, patched_deck)
    write_lines(args.stim, patched_stim)

    summary["backups"] = backups
    summary_path = args.summary_out
    if summary_path is None:
        summary_path = args.deck.with_name(args.deck.stem + "_patch_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
