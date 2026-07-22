#!/usr/bin/env python3
"""Retarget PrimeTime native SPICE measures to a specific path edge.

PrimeTime native decks use many ``rise=last``/``fall=last`` measurements.
That is safe for long transient windows, but full-aggressor decks can become
too expensive when the stop time is extended only to satisfy those ``last``
queries. This patcher makes the generated stimulus deck measure the intended
path edge directly:

* replace victim measure ``last`` events with the first crossing after a local
  search window;
* add direct CK->D and Q->D endpoint measurements when the needed events can be
  inferred; and
* optionally shorten ``.tran`` to endpoint event time plus margin.

The script operates on the generated ``*_stim.sp`` file after the normal deck
patching step.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
TIME_RE = re.compile(rf"^\s*({FLOAT_RE})([a-zA-Z]*)\s*$")
EVENT_RE = re.compile(
    rf"(?i)\b(?P<kind>trig|targ)\s+v\((?P<node>[^)]+)\)"
    rf"(?P<body>.*?)(?P<edge>rise|fall)\s*=\s*(?P<count>last|\d+)\b"
)
VAL_RE = re.compile(rf"(?i)\bval\s*=\s*(?P<val>{FLOAT_RE})")
TD_RE = re.compile(rf"(?i)\btd\s*=\s*(?P<td>{FLOAT_RE})(?P<unit>[a-zA-Z]*)")
EDGE_RE = re.compile(r"(?i)\b(?P<edge>rise|fall)\s*=\s*(?P<count>last|\d+)\b")
TRAN_RE = re.compile(
    rf"(?i)^(?P<prefix>\s*\.tran\s+)"
    rf"(?P<step>{FLOAT_RE})(?P<step_unit>[a-zA-Z]*)"
    rf"(?P<sep>\s+)"
    rf"(?P<stop>{FLOAT_RE})(?P<stop_unit>[a-zA-Z]*)"
    rf"(?P<suffix>.*)$"
)


@dataclass(frozen=True)
class Event:
    measure_name: str
    kind: str
    node: str
    val: float
    td_ns: float
    edge: str
    count: str
    line_index: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch a native SPICE stimulus deck for targeted endpoint measurements."
    )
    parser.add_argument("--stim", required=True, type=Path, help="Stimulus deck to patch, e.g. path_000001_stim.sp")
    parser.add_argument("--summary", type=Path, help="pt_native_smoke_summary.txt with from_pin/to_pin")
    parser.add_argument("--from-node", help="Launch data node, usually the startpoint Q pin")
    parser.add_argument("--to-node", help="Endpoint node, usually the endpoint D pin")
    parser.add_argument("--output", type=Path, help="Write patched stimulus here. Default: patch --stim in place")
    parser.add_argument("--summary-out", type=Path, help="Write JSON patch summary here")
    parser.add_argument(
        "--search-margin-ns",
        type=float,
        default=0.2,
        help="Move each inferred td earlier by this much before using rise=1/fall=1",
    )
    parser.add_argument(
        "--stop-margin-ns",
        type=float,
        default=0.5,
        help="Transient stop margin after endpoint td when --tran-stop-ns is not provided",
    )
    parser.add_argument("--tran-stop-ns", type=float, help="Explicit transient stop time in ns")
    parser.add_argument("--tran-step-ns", type=float, help="Explicit transient step in ns. Keeps existing step if omitted")
    parser.add_argument(
        "--measure-prefix",
        default="targeted",
        help="Prefix for added direct measures",
    )
    parser.add_argument("--no-replace-last", action="store_true", help="Do not rewrite rise/fall=last events")
    parser.add_argument("--no-add-direct", action="store_true", help="Do not add direct CK->D and Q->D measures")
    parser.add_argument("--no-patch-tran", action="store_true", help="Do not patch .tran stop time")
    parser.add_argument("--no-backup", action="store_true", help="Do not create a .orig backup for in-place patching")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing files")
    return parser.parse_args()


def read_lines(path: Path) -> list[str]:
    return path.read_text(errors="ignore").splitlines(keepends=True)


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines))


def backup_once(path: Path) -> Path:
    backup = path.with_name(path.name + ".orig")
    if not backup.exists():
        shutil.copy2(path, backup)
    return backup


def fmt(value: float) -> str:
    if abs(value) < 1e-18:
        return "0"
    return f"{value:.12g}"


def fmt_time_ns(value: float) -> str:
    if value < 0 and abs(value) < 1e-12:
        value = 0.0
    return f"{fmt(value)}ns"


def parse_time_ns(token: str) -> float:
    match = TIME_RE.match(token)
    if not match:
        raise ValueError(f"not a time token: {token!r}")
    value = float(match.group(1))
    unit = (match.group(2) or "ns").lower()
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


def parse_key_value_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_nodes(args: argparse.Namespace) -> tuple[str, str]:
    from_node = args.from_node
    to_node = args.to_node
    if args.summary:
        summary = parse_key_value_file(args.summary)
        from_node = from_node or summary.get("from_pin")
        to_node = to_node or summary.get("to_pin")
    if not from_node or not to_node:
        raise SystemExit("ERROR: provide --summary or both --from-node and --to-node")
    return from_node, to_node


def norm_node(node: str) -> str:
    return node.strip().lower()


def measure_name_from_line(line: str) -> str | None:
    parts = line.strip().split()
    if len(parts) >= 3 and parts[0].lower() == ".measure":
        return parts[2]
    return None


def parse_event(line: str, measure_name: str, line_index: int) -> Event | None:
    match = EVENT_RE.search(line)
    if not match:
        return None
    val_match = VAL_RE.search(line)
    td_match = TD_RE.search(line)
    if not val_match or not td_match:
        return None
    td_token = td_match.group("td") + (td_match.group("unit") or "ns")
    try:
        val = float(val_match.group("val"))
        td_ns = parse_time_ns(td_token)
    except ValueError:
        return None
    return Event(
        measure_name=measure_name,
        kind=match.group("kind").lower(),
        node=match.group("node"),
        val=val,
        td_ns=td_ns,
        edge=match.group("edge").lower(),
        count=match.group("count").lower(),
        line_index=line_index,
    )


def collect_events(lines: Iterable[str]) -> list[Event]:
    events: list[Event] = []
    current_measure = ""
    for idx, line in enumerate(lines):
        measure_name = measure_name_from_line(line)
        if measure_name:
            current_measure = measure_name
            continue
        if not current_measure:
            continue
        event = parse_event(line, current_measure, idx)
        if event:
            events.append(event)
    return events


def is_delay_measure(name: str) -> bool:
    return name.lower().startswith("delay_")


def event_to_dict(event: Event | None) -> dict[str, object] | None:
    if event is None:
        return None
    return {
        "measure_name": event.measure_name,
        "kind": event.kind,
        "node": event.node,
        "val": event.val,
        "td_ns": event.td_ns,
        "edge": event.edge,
        "count": event.count,
        "line_index": event.line_index,
    }


def find_launch_q_event(events: list[Event], from_node: str) -> Event:
    target = norm_node(from_node)
    candidates = [
        event
        for event in events
        if event.kind == "trig"
        and is_delay_measure(event.measure_name)
        and norm_node(event.node) == target
    ]
    if candidates:
        return min(candidates, key=lambda event: event.td_ns)
    raise SystemExit(f"ERROR: could not infer launch Q event for {from_node}")


def find_endpoint_event(events: list[Event], to_node: str) -> Event:
    target = norm_node(to_node)
    candidates = [
        event
        for event in events
        if event.kind == "targ"
        and is_delay_measure(event.measure_name)
        and norm_node(event.node) == target
    ]
    if candidates:
        return max(candidates, key=lambda event: event.td_ns)
    raise SystemExit(f"ERROR: could not infer endpoint event for {to_node}")


def find_launch_ck_event(events: list[Event], from_node: str) -> Event | None:
    target = norm_node(from_node)
    for idx, event in enumerate(events):
        if event.kind != "targ" or not is_delay_measure(event.measure_name):
            continue
        if norm_node(event.node) != target:
            continue
        for prior in reversed(events[:idx]):
            if prior.measure_name != event.measure_name or prior.kind != "trig":
                continue
            if prior.node.rsplit("/", 1)[-1].lower() in {"ck", "clk", "cp"}:
                return prior
            return prior
    return None


def event_td_for_search(event: Event, search_margin_ns: float) -> float:
    return max(0.0, event.td_ns - search_margin_ns)


def render_measure(name: str, trig: Event, targ: Event, search_margin_ns: float) -> list[str]:
    trig_td = event_td_for_search(trig, search_margin_ns)
    targ_td = event_td_for_search(targ, search_margin_ns)
    return [
        f".measure tran {name}\n",
        f"+ trig v({trig.node}) val = {fmt(trig.val)} td = {fmt_time_ns(trig_td)} {trig.edge} = 1\n",
        f"+ targ v({targ.node}) val = {fmt(targ.val)} td = {fmt_time_ns(targ_td)} {targ.edge} = 1\n",
    ]


def insertion_index_before_tran(lines: list[str]) -> int:
    for idx, line in enumerate(lines):
        if line.lstrip().lower().startswith(".tran"):
            return idx
    raise SystemExit("ERROR: could not find .tran in stimulus deck")


def remove_existing_targeted_measures(lines: list[str], prefix: str) -> tuple[list[str], int]:
    kept: list[str] = []
    removed = 0
    idx = 0
    marker = f".measure tran {prefix}_"
    while idx < len(lines):
        line = lines[idx]
        if line.strip().lower().startswith(marker.lower()):
            removed += 1
            idx += 1
            while idx < len(lines) and lines[idx].lstrip().startswith("+"):
                idx += 1
            continue
        kept.append(line)
        idx += 1
    return kept, removed


def add_direct_measures(
    lines: list[str],
    prefix: str,
    ck_event: Event | None,
    q_event: Event,
    endpoint_event: Event,
    search_margin_ns: float,
) -> tuple[list[str], list[str], int]:
    lines, removed = remove_existing_targeted_measures(lines, prefix)
    measures: list[str] = []
    added_names: list[str] = []
    if ck_event is not None:
        name = f"{prefix}_delay_ck_to_d"
        measures.extend(render_measure(name, ck_event, endpoint_event, search_margin_ns))
        added_names.append(name)
    name = f"{prefix}_delay_q_to_d"
    measures.extend(render_measure(name, q_event, endpoint_event, search_margin_ns))
    added_names.append(name)

    insert_at = insertion_index_before_tran(lines)
    block = [
        "******************************************\n",
        "* Targeted endpoint measure statements\n",
        "******************************************\n",
    ] + measures
    return lines[:insert_at] + block + lines[insert_at:], added_names, removed


def patch_last_event_line(line: str, search_margin_ns: float) -> tuple[str, bool]:
    if "last" not in line.lower() or not EVENT_RE.search(line):
        return line, False

    td_match = TD_RE.search(line)
    if not td_match:
        return EDGE_RE.sub(lambda match: f"{match.group('edge')} = 1", line), True

    old_td = parse_time_ns(td_match.group("td") + (td_match.group("unit") or "ns"))
    new_td = event_td_for_search(
        Event("", "", "", 0.0, old_td, "", "", 0),
        search_margin_ns,
    )
    line = TD_RE.sub(f"td = {fmt_time_ns(new_td)}", line, count=1)
    line = EDGE_RE.sub(lambda match: f"{match.group('edge')} = 1", line, count=1)
    return line, True


def replace_last_events(lines: list[str], search_margin_ns: float) -> tuple[list[str], int]:
    patched: list[str] = []
    changed = 0
    for line in lines:
        new_line, did_change = patch_last_event_line(line, search_margin_ns)
        patched.append(new_line)
        changed += int(did_change)
    return patched, changed


def patch_tran(lines: list[str], stop_ns: float, step_ns: float | None) -> tuple[list[str], dict[str, object]]:
    patched: list[str] = []
    info: dict[str, object] = {"patched": False}
    for line in lines:
        match = TRAN_RE.match(line.rstrip("\n"))
        if not match:
            patched.append(line)
            continue
        old_step = parse_time_ns(match.group("step") + (match.group("step_unit") or "ns"))
        old_stop = parse_time_ns(match.group("stop") + (match.group("stop_unit") or "ns"))
        new_step = old_step if step_ns is None else step_ns
        patched.append(
            f"{match.group('prefix')}{fmt_time_ns(new_step)}"
            f"{match.group('sep')}{fmt_time_ns(stop_ns)}{match.group('suffix')}\n"
        )
        info = {
            "patched": True,
            "old_step_ns": old_step,
            "old_stop_ns": old_stop,
            "new_step_ns": new_step,
            "new_stop_ns": stop_ns,
        }
    return patched, info


def build_patch(lines: list[str], args: argparse.Namespace, from_node: str, to_node: str) -> tuple[list[str], dict[str, object]]:
    events = collect_events(lines)
    q_event = find_launch_q_event(events, from_node)
    endpoint_event = find_endpoint_event(events, to_node)
    ck_event = find_launch_ck_event(events, from_node)

    stop_ns = args.tran_stop_ns
    if stop_ns is None:
        stop_ns = endpoint_event.td_ns + args.stop_margin_ns
    if stop_ns <= endpoint_event.td_ns:
        raise SystemExit(
            f"ERROR: transient stop {stop_ns:g} ns is not after endpoint td {endpoint_event.td_ns:g} ns"
        )

    patched = list(lines)
    replaced_last_count = 0
    if not args.no_replace_last:
        patched, replaced_last_count = replace_last_events(patched, args.search_margin_ns)

    added_direct_measures: list[str] = []
    removed_existing_direct = 0
    if not args.no_add_direct:
        patched, added_direct_measures, removed_existing_direct = add_direct_measures(
            patched,
            args.measure_prefix,
            ck_event,
            q_event,
            endpoint_event,
            args.search_margin_ns,
        )

    tran_info: dict[str, object] = {"patched": False}
    if not args.no_patch_tran:
        patched, tran_info = patch_tran(patched, stop_ns, args.tran_step_ns)

    summary: dict[str, object] = {
        "stim": str(args.stim),
        "output": str(args.output or args.stim),
        "from_node": from_node,
        "to_node": to_node,
        "search_margin_ns": args.search_margin_ns,
        "stop_margin_ns": args.stop_margin_ns,
        "chosen_stop_ns": stop_ns,
        "replace_last": not args.no_replace_last,
        "replaced_last_event_count": replaced_last_count,
        "add_direct": not args.no_add_direct,
        "added_direct_measures": added_direct_measures,
        "removed_existing_direct_measure_count": removed_existing_direct,
        "launch_ck_event": event_to_dict(ck_event),
        "launch_q_event": event_to_dict(q_event),
        "endpoint_event": event_to_dict(endpoint_event),
        "tran": tran_info,
        "dry_run": args.dry_run,
    }
    return patched, summary


def main() -> None:
    args = parse_args()
    if args.search_margin_ns < 0:
        raise SystemExit("ERROR: --search-margin-ns must be non-negative")
    if args.stop_margin_ns < 0:
        raise SystemExit("ERROR: --stop-margin-ns must be non-negative")
    if args.tran_stop_ns is not None and args.tran_stop_ns <= 0:
        raise SystemExit("ERROR: --tran-stop-ns must be positive")
    if args.tran_step_ns is not None and args.tran_step_ns <= 0:
        raise SystemExit("ERROR: --tran-step-ns must be positive")

    from_node, to_node = resolve_nodes(args)
    lines = read_lines(args.stim)
    patched, summary = build_patch(lines, args, from_node, to_node)

    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    output = args.output or args.stim
    backups: dict[str, str] = {}
    if output == args.stim and not args.no_backup:
        backups["stim"] = str(backup_once(args.stim))
    write_lines(output, patched)

    summary["backups"] = backups
    summary_path = args.summary_out
    if summary_path is None:
        summary_path = output.with_name(output.stem + "_targeted_measure_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
