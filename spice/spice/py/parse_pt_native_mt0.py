#!/usr/bin/env python3
"""Parse PrimeTime native write_spice_deck HSPICE .mt0 files.

This parser is intentionally conservative:

* native_raw_measure.csv preserves every .mt0 measure in order;
* native_delay_breakdown.csv adds best-effort delay/slew classification;
* original measure names are never discarded, because PrimeTime native measure
  names are node based and do not include an explicit stage manifest.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PATH_DIR_RE = re.compile(r"^path_(\d+)$")
FLOAT_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$")

INPUT_PINS = {
    "a",
    "a1",
    "a2",
    "a3",
    "a4",
    "b",
    "b1",
    "b2",
    "b3",
    "b4",
    "c",
    "c1",
    "c2",
    "ci",
    "ck",
    "clk",
    "clkn",
    "d",
    "d0",
    "d1",
    "d2",
    "e",
    "en",
    "g",
    "i",
    "in",
    "rn",
    "s",
    "se",
    "si",
    "sn",
}
OUTPUT_PINS = {
    "co",
    "n",
    "out",
    "q",
    "qn",
    "x",
    "y",
    "z",
    "zn",
    "ckout",
    "ckoutb",
}
META_MEASURES = {"temper", "alter#"}


@dataclass(frozen=True)
class Mt0Measure:
    index: int
    name: str
    raw_value: str
    value: float | None
    is_failed: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse PrimeTime native HSPICE .mt0 files into raw and heuristic delay CSVs."
    )
    parser.add_argument("--batch-dir", required=True, type=Path, help="Batch output directory containing path_* dirs.")
    parser.add_argument("--raw-csv", type=Path, help="Output raw CSV. Default: batch-dir/native_raw_measure.csv")
    parser.add_argument(
        "--breakdown-csv",
        type=Path,
        help="Output heuristic breakdown CSV. Default: batch-dir/native_delay_breakdown.csv",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        help="Output parser summary JSON. Default: batch-dir/native_mt0_parse_summary.json",
    )
    parser.add_argument("--include-meta-breakdown", action="store_true", help="Include temper/alter# in breakdown CSV.")
    parser.add_argument("--fail-on-missing", action="store_true", help="Exit non-zero if any path has missing files.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def path_index(path_dir: Path) -> int | None:
    match = PATH_DIR_RE.match(path_dir.name)
    if not match:
        return None
    return int(match.group(1))


def find_path_dirs(batch_dir: Path) -> list[Path]:
    path_dirs: list[Path] = []
    for child in batch_dir.iterdir():
        if not child.is_dir():
            continue
        if path_index(child) is None:
            continue
        if (child / "status.json").is_file():
            path_dirs.append(child)
    return sorted(path_dirs, key=lambda item: path_index(item) or 0)


def parse_number(token: str) -> float | None:
    token = token.strip()
    if token.lower() in {"failed", "fail", "nan", "n/a"}:
        return None
    if not FLOAT_RE.match(token):
        return None
    value = float(token)
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def is_value_token(token: str) -> bool:
    return parse_number(token) is not None or token.strip().lower() in {"failed", "fail"}


def parse_mt0(path: Path) -> tuple[list[Mt0Measure], dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"missing mt0 file: {path}")

    headers: list[str] = []
    values: list[str] = []
    in_values = False
    with path.open(errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("$") or line.startswith("."):
                continue
            tokens = line.split()
            if not tokens:
                continue
            if not in_values and is_value_token(tokens[0]):
                in_values = True
            if in_values:
                values.extend(tokens)
            else:
                headers.extend(tokens)

    if not headers:
        raise ValueError(f"{path}: no .mt0 measure headers found")
    if not values:
        raise ValueError(f"{path}: no .mt0 measure values found")

    measures: list[Mt0Measure] = []
    for idx, name in enumerate(headers):
        raw_value = values[idx] if idx < len(values) else ""
        value = parse_number(raw_value)
        measures.append(
            Mt0Measure(
                index=idx,
                name=name.lower(),
                raw_value=raw_value,
                value=value,
                is_failed=raw_value.strip().lower() in {"failed", "fail"} or value is None,
            )
        )

    info = {
        "header_count": len(headers),
        "value_count": len(values),
        "missing_value_count": max(0, len(headers) - len(values)),
        "extra_value_count": max(0, len(values) - len(headers)),
    }
    return measures, info


def measure_type(name: str) -> str:
    if name.startswith("delay_"):
        return "delay"
    if name.startswith("slew_"):
        return "slew"
    if name in META_MEASURES:
        return "meta"
    return "unknown"


def pin_name(node: str | None) -> str:
    if not node or "/" not in node:
        return ""
    return node.rsplit("/", 1)[1].lower()


def inst_name(node: str | None) -> str:
    if not node or "/" not in node:
        return ""
    return node.rsplit("/", 1)[0].lower()


def pin_role(pin: str) -> str:
    pin = pin.lower()
    if pin in INPUT_PINS:
        return "input"
    if pin in OUTPUT_PINS:
        return "output"
    return "unknown"


def is_plausible_node(node: str) -> bool:
    return bool(node and "/" in node and pin_role(pin_name(node)) != "unknown")


def split_delay_nodes(name: str) -> tuple[str, str, str]:
    """Return from/to nodes plus split confidence.

    PrimeTime native names look like delay_<from_node>_<to_node>, but nodes
    themselves contain underscores.  The split is selected at an underscore
    where both sides look like hierarchical pin nodes with known pin suffixes.
    """

    if not name.startswith("delay_"):
        return "", "", "none"
    body = name[len("delay_") :]
    candidates: list[tuple[str, str]] = []
    for idx, ch in enumerate(body):
        if ch != "_":
            continue
        left = body[:idx]
        right = body[idx + 1 :]
        if is_plausible_node(left) and is_plausible_node(right):
            candidates.append((left, right))
    if not candidates:
        return "", "", "none"
    return candidates[0][0], candidates[0][1], "high"


def slew_node(name: str) -> str:
    if not name.startswith("slew_"):
        return ""
    return name[len("slew_") :]


def classify_delay(from_node: str, to_node: str, split_confidence: str) -> tuple[str, str]:
    if not from_node or not to_node:
        return "unknown_delay", "none"

    from_pin = pin_name(from_node)
    to_pin = pin_name(to_node)
    from_role = pin_role(from_pin)
    to_role = pin_role(to_pin)
    same_inst = inst_name(from_node) == inst_name(to_node)

    if same_inst and from_role == "input" and to_role == "output":
        return "cell_delay", split_confidence
    if same_inst:
        return "cell_delay", "medium"
    if from_role == "output" and to_role == "input":
        return "net_delay", split_confidence
    if from_role == "input" and to_role == "input":
        return "stage_or_cumulative_delay", "medium"
    if from_role == "output" and to_role == "output":
        return "output_to_output_delay", "low"
    return "unknown_delay", "low"


def seconds_to_ps(value: float | None, mtype: str) -> float | None:
    if value is None:
        return None
    if mtype not in {"delay", "slew"}:
        return None
    return value * 1.0e12


def fmt_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def status_metadata(status: dict[str, Any], path_dir: Path) -> dict[str, Any]:
    files = status.get("files") if isinstance(status.get("files"), dict) else {}
    pt_path = status.get("pt_path") if isinstance(status.get("pt_path"), dict) else {}
    hspice = status.get("hspice") if isinstance(status.get("hspice"), dict) else {}
    scan = hspice.get("scan") if isinstance(hspice.get("scan"), dict) else {}
    return {
        "path": path_dir.name,
        "path_dir": str(path_dir),
        "path_id": status.get("path_id"),
        "fixed_index": status.get("fixed_index"),
        "status": status.get("status"),
        "target_vdd": status.get("target_vdd"),
        "target_temp": status.get("target_temp"),
        "input_slew_ps": status.get("input_slew_ps"),
        "output_load_ff": status.get("output_load_ff"),
        "path_key": pt_path.get("path_key"),
        "pt_from_pin": pt_path.get("from_pin"),
        "pt_to_pin": pt_path.get("to_pin"),
        "through_count": pt_path.get("through_count"),
        "hspice_nodes": scan.get("nodes"),
        "hspice_elements": scan.get("elements"),
        "hspice_peak_memory_mb": scan.get("peak_memory_mb"),
        "mt0_file": files.get("hspice_mt0"),
    }


def raw_record(meta: dict[str, Any], measure: Mt0Measure) -> dict[str, Any]:
    mtype = measure_type(measure.name)
    from_node = ""
    to_node = ""
    node = ""
    split_confidence = ""
    if mtype == "delay":
        from_node, to_node, split_confidence = split_delay_nodes(measure.name)
    elif mtype == "slew":
        node = slew_node(measure.name)

    value_ps = seconds_to_ps(measure.value, mtype)
    return {
        **meta,
        "measure_index": measure.index,
        "measure_name": measure.name,
        "measure_type": mtype,
        "value_raw": measure.raw_value,
        "value_sec": fmt_value(measure.value if mtype in {"delay", "slew"} else None),
        "value_ps": fmt_value(value_ps),
        "is_failed": measure.is_failed,
        "node": node,
        "from_node": from_node,
        "to_node": to_node,
        "from_pin_name": pin_name(from_node),
        "to_pin_name": pin_name(to_node),
        "node_pin_name": pin_name(node),
        "split_confidence": split_confidence,
    }


def breakdown_records(meta: dict[str, Any], measures: list[Mt0Measure], include_meta: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    stage_idx = 0
    current_stage: int | None = None

    for measure in measures:
        mtype = measure_type(measure.name)
        if mtype == "meta" and not include_meta:
            continue
        from_node = ""
        to_node = ""
        node = ""
        kind = mtype
        confidence = ""

        if mtype == "delay":
            from_node, to_node, split_confidence = split_delay_nodes(measure.name)
            kind, confidence = classify_delay(from_node, to_node, split_confidence)
            if kind == "cell_delay":
                stage_idx += 1
                current_stage = stage_idx
        elif mtype == "slew":
            node = slew_node(measure.name)
            kind = "slew"
            confidence = "high" if is_plausible_node(node) else "low"
        elif mtype == "meta":
            kind = "meta"
            confidence = "high"
        else:
            kind = "unknown"
            confidence = "none"

        value_ps = seconds_to_ps(measure.value, mtype)
        records.append(
            {
                **meta,
                "stage_idx": current_stage or "",
                "measure_index": measure.index,
                "measure_name": measure.name,
                "measure_type": mtype,
                "kind": kind,
                "classification_confidence": confidence,
                "value_raw": measure.raw_value,
                "value_sec": fmt_value(measure.value if mtype in {"delay", "slew"} else None),
                "value_ps": fmt_value(value_ps),
                "is_failed": measure.is_failed,
                "node": node,
                "from_node": from_node,
                "to_node": to_node,
                "from_pin_name": pin_name(from_node),
                "to_pin_name": pin_name(to_node),
                "node_pin_name": pin_name(node),
                "from_pin_role": pin_role(pin_name(from_node)) if from_node else "",
                "to_pin_role": pin_role(pin_name(to_node)) if to_node else "",
                "node_pin_role": pin_role(pin_name(node)) if node else "",
            }
        )
    return records


RAW_FIELDS = [
    "path_id",
    "fixed_index",
    "path",
    "status",
    "measure_index",
    "measure_name",
    "measure_type",
    "value_raw",
    "value_sec",
    "value_ps",
    "is_failed",
    "node",
    "from_node",
    "to_node",
    "from_pin_name",
    "to_pin_name",
    "node_pin_name",
    "split_confidence",
    "target_vdd",
    "target_temp",
    "input_slew_ps",
    "output_load_ff",
    "path_key",
    "pt_from_pin",
    "pt_to_pin",
    "through_count",
    "hspice_nodes",
    "hspice_elements",
    "hspice_peak_memory_mb",
    "mt0_file",
    "path_dir",
]

BREAKDOWN_FIELDS = [
    "path_id",
    "fixed_index",
    "path",
    "status",
    "stage_idx",
    "measure_index",
    "measure_name",
    "measure_type",
    "kind",
    "classification_confidence",
    "value_raw",
    "value_sec",
    "value_ps",
    "is_failed",
    "node",
    "from_node",
    "to_node",
    "from_pin_name",
    "to_pin_name",
    "node_pin_name",
    "from_pin_role",
    "to_pin_role",
    "node_pin_role",
    "target_vdd",
    "target_temp",
    "input_slew_ps",
    "output_load_ff",
    "path_key",
    "pt_from_pin",
    "pt_to_pin",
    "through_count",
    "hspice_nodes",
    "hspice_elements",
    "hspice_peak_memory_mb",
    "mt0_file",
    "path_dir",
]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def summarize_path(path_dir: Path, measures: list[Mt0Measure], mt0_info: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", ""))
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "path": path_dir.name,
        "measure_count": len(measures),
        "failed_measure_count": sum(1 for measure in measures if measure.is_failed),
        "delay_count": sum(1 for measure in measures if measure_type(measure.name) == "delay"),
        "slew_count": sum(1 for measure in measures if measure_type(measure.name) == "slew"),
        "meta_count": sum(1 for measure in measures if measure_type(measure.name) == "meta"),
        "kind_counts": counts,
        **mt0_info,
    }


def main() -> int:
    args = parse_args()
    batch_dir = args.batch_dir.resolve()
    if not batch_dir.is_dir():
        raise SystemExit(f"ERROR: missing batch dir: {batch_dir}")

    raw_csv = args.raw_csv or (batch_dir / "native_raw_measure.csv")
    breakdown_csv = args.breakdown_csv or (batch_dir / "native_delay_breakdown.csv")
    summary_json = args.summary_json or (batch_dir / "native_mt0_parse_summary.json")

    raw_rows: list[dict[str, Any]] = []
    breakdown_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    errors: list[str] = []

    path_dirs = find_path_dirs(batch_dir)
    if not path_dirs:
        raise SystemExit(f"ERROR: no path_* dirs with status.json found in {batch_dir}")

    for path_dir in path_dirs:
        try:
            status = load_json(path_dir / "status.json")
            meta = status_metadata(status, path_dir)
            mt0_text = meta.get("mt0_file")
            mt0_path = Path(str(mt0_text)) if mt0_text else next(path_dir.glob("*_hspice.mt0"))
            measures, mt0_info = parse_mt0(mt0_path)
            path_raw_rows = [raw_record(meta, measure) for measure in measures]
            path_breakdown_rows = breakdown_records(meta, measures, args.include_meta_breakdown)
            raw_rows.extend(path_raw_rows)
            breakdown_rows.extend(path_breakdown_rows)
            summaries.append(summarize_path(path_dir, measures, mt0_info, path_breakdown_rows))
        except Exception as exc:  # noqa: BLE001 - parser should report all bad path dirs.
            errors.append(f"{path_dir}: {exc}")
            if args.fail_on_missing:
                break

    write_csv(raw_csv, raw_rows, RAW_FIELDS)
    write_csv(breakdown_csv, breakdown_rows, BREAKDOWN_FIELDS)

    summary = {
        "batch_dir": str(batch_dir),
        "raw_csv": str(raw_csv),
        "breakdown_csv": str(breakdown_csv),
        "path_count": len(path_dirs),
        "parsed_path_count": len(summaries),
        "raw_row_count": len(raw_rows),
        "breakdown_row_count": len(breakdown_rows),
        "errors": errors,
        "paths": summaries,
    }
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print(f"raw_csv={raw_csv}")
    print(f"breakdown_csv={breakdown_csv}")
    print(f"summary_json={summary_json}")
    print(f"paths={len(summaries)}/{len(path_dirs)} raw_rows={len(raw_rows)} breakdown_rows={len(breakdown_rows)}")
    return 1 if errors and args.fail_on_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
