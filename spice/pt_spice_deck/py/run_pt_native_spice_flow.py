#!/usr/bin/env python3
"""Batch PrimeTime native SPICE deck generation, patching, and HSPICE runs.

The ML input CSV supplies per-path target boundary conditions.  For each row
this runner:

1. calls PrimeTime write_spice_deck for the fixed path index,
2. patches the generated deck with the ML slew/load/VDD/temp,
3. runs HSPICE, and
4. writes per-path status plus a batch CSV summary.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
NODE_ELEM_RE = re.compile(r"# nodes\s*=\s*(\d+)\s+# elements\s*=\s*(\d+)", re.IGNORECASE)
RES_CAP_RE = re.compile(r"# resistors\s*=\s*(\d+)\s+# capacitors\s*=\s*(\d+)", re.IGNORECASE)
MOS_RE = re.compile(r"# jfets\s*=\s*(\d+)\s+# mosfets\s*=\s*(\d+)", re.IGNORECASE)
MEM_RE = re.compile(r"peak memory used\s+([0-9.]+)\s+(\S+)", re.IGNORECASE)
CPU_RE = re.compile(r"total cpu time\s+([0-9.]+)\s+seconds", re.IGNORECASE)
ELAPSED_RE = re.compile(r"total elapsed time\s+([0-9.]+)\s+seconds", re.IGNORECASE)
HSPICE_FAIL_PATTERNS = [
    re.compile(r"\*\*error\*\*", re.IGNORECASE),
    re.compile(r"\*\*fatal\*\*", re.IGNORECASE),
    re.compile(r"\bfatal\b", re.IGNORECASE),
    re.compile(r"\bundefined\s+(subckt|model|parameter)\b", re.IGNORECASE),
    re.compile(r"\b(cannot|can't)\s+open\b", re.IGNORECASE),
    re.compile(r"\bno\s+such\s+file\b", re.IGNORECASE),
    re.compile(r"\blicense\b.*\b(fail|failed|denied|unavailable|cannot|error)\b", re.IGNORECASE),
    re.compile(r"\blic:\s+.*\bcheckout\b.*\b(fail|failed|unable)\b", re.IGNORECASE),
]
HSPICE_MEASURE_FAIL_PATTERN = re.compile(r"\bmeasure\b.*\b(fail|failed|error)\b|=\s*failed\b", re.IGNORECASE)
SCRIPT_DIR = Path(__file__).resolve().parent
CODE_ROOT = SCRIPT_DIR.parent


@dataclass(frozen=True)
class MlPathRow:
    row_number: int
    path_id: int
    fixed_index: int
    input_slew_ps: float
    output_load_ff: float
    target_vdd: float
    target_temp: float
    raw: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PrimeTime native SPICE deck batch flow from an ML path-condition CSV."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CODE_ROOT / "config" / "pt_native_spice_config.yaml",
        help="Flow config. The current file is JSON-formatted YAML.",
    )
    parser.add_argument("--ml-csv", required=True, type=Path, help="CSV with path_id/input_slew_ps/output_load_ff.")
    parser.add_argument("--run-name", help="Output batch directory name. Default: batch_YYYYmmdd_HHMMSS.")
    parser.add_argument("--output-root", type=Path, help="Override config project.output_root.")
    parser.add_argument("--limit", type=int, help="Run only the first N ML rows after filtering.")
    parser.add_argument("--path-id", type=int, action="append", help="Run only the selected path_id. Repeatable.")
    parser.add_argument("--timeout-pt-sec", type=int, default=900)
    parser.add_argument("--timeout-hspice-sec", type=int, default=600)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--pt-shell", default="pt_shell")
    parser.add_argument("--dry-run", action="store_true", help="Write commands/status without running tools.")
    parser.add_argument("--skip-pt", action="store_true", help="Reuse an existing generated deck in each path dir.")
    parser.add_argument("--skip-patch", action="store_true", help="Do not patch generated decks.")
    parser.add_argument("--skip-hspice", action="store_true", help="Stop after deck generation and patching.")
    parser.add_argument(
        "--post-process",
        dest="post_process",
        action="store_true",
        default=True,
        help="Run MT0 parser, HSPICE report formatter, PT SI report formatter, and PT-vs-HSPICE comparison after the batch. Default: enabled.",
    )
    parser.add_argument(
        "--skip-post-process",
        dest="post_process",
        action="store_false",
        help="Skip automatic report generation after the batch.",
    )
    parser.add_argument("--timeout-post-process-sec", type=int, default=300)
    parser.add_argument("--continue-on-error", action="store_true", help="Continue to the next row after failures.")
    parser.add_argument("--force", action="store_true", help="Allow overwriting files in an existing run directory.")
    return parser.parse_args()


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: config is not valid JSON/YAML subset: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: config root must be an object: {path}")
    return data


def require_path(path: str | Path, label: str, *, file: bool = True) -> Path:
    item = Path(path).expanduser()
    if file and not item.is_file():
        raise SystemExit(f"ERROR: missing {label}: {item}")
    if not file and not item.exists():
        raise SystemExit(f"ERROR: missing {label}: {item}")
    return item


def value_or_default(row: dict[str, str], key: str, default: float) -> float:
    text = (row.get(key) or "").strip()
    if text == "":
        return default
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{key}={text!r} is not a number") from exc


def required_float(row: dict[str, str], key: str) -> float:
    text = (row.get(key) or "").strip()
    if text == "":
        raise ValueError(f"missing required column {key}")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{key}={text!r} is not a number") from exc


def required_int(row: dict[str, str], key: str) -> int:
    text = (row.get(key) or "").strip()
    if text == "":
        raise ValueError(f"missing required column {key}")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{key}={text!r} is not an integer") from exc


def load_ml_rows(csv_path: Path, cfg: dict[str, Any], limit: int | None, selected_path_ids: set[int] | None) -> list[MlPathRow]:
    ml_cfg = cfg.get("ml_input") or {}
    defaults = cfg.get("target_corner_defaults") or {}
    path_col = ml_cfg.get("path_id_column", "path_id")
    required_cols = list(ml_cfg.get("required_columns") or ["path_id", "input_slew_ps", "output_load_ff"])
    index_base = int((cfg.get("path_registry") or {}).get("index_base", 1))
    default_vdd = float(defaults.get("vdd", 0.8))
    default_temp = float(defaults.get("temp", 25))

    rows: list[MlPathRow] = []
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SystemExit(f"ERROR: ML CSV has no header: {csv_path}")
        missing = [name for name in required_cols if name not in reader.fieldnames]
        if missing:
            raise SystemExit(f"ERROR: ML CSV missing required columns {missing}: {csv_path}")
        for row_number, row in enumerate(reader, 2):
            try:
                path_id = required_int(row, path_col)
                if selected_path_ids is not None and path_id not in selected_path_ids:
                    continue
                fixed_index = path_id if index_base == 1 else path_id + 1
                rows.append(
                    MlPathRow(
                        row_number=row_number,
                        path_id=path_id,
                        fixed_index=fixed_index,
                        input_slew_ps=required_float(row, "input_slew_ps"),
                        output_load_ff=required_float(row, "output_load_ff"),
                        target_vdd=value_or_default(row, "target_vdd", default_vdd),
                        target_temp=value_or_default(row, "target_temp", default_temp),
                        raw=dict(row),
                    )
                )
            except ValueError as exc:
                raise SystemExit(f"ERROR: {csv_path}:{row_number}: {exc}") from exc
            if limit is not None and len(rows) >= limit:
                break
    if not rows:
        raise SystemExit("ERROR: no ML rows selected")
    return rows


def q(value: str | Path) -> str:
    return shlex.quote(str(value))


def command_text(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_logged_command(
    command: list[str],
    *,
    cwd: Path,
    log_path: Path,
    timeout_sec: int,
    dry_run: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "command": command_text(command),
        "cwd": str(cwd),
        "log": str(log_path),
        "returncode": None,
        "timed_out": False,
        "elapsed_sec": 0.0,
    }
    if dry_run:
        result["returncode"] = 0
        result["dry_run"] = True
        log_path.write_text(result["command"] + "\n")
        return result

    started = time.monotonic()
    with log_path.open("w") as log:
        log.write("$ " + result["command"] + "\n\n")
        log.flush()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            result["returncode"] = completed.returncode
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            result["returncode"] = -1
            log.write(f"\nERROR: command timed out after {timeout_sec} seconds\n")
    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result


def build_sourced_shell_command(setup_script: Path, inner_command: str) -> list[str]:
    return ["bash", "-lc", f"source {q(setup_script)}; {inner_command}"]


def env_assignment(name: str, value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        value = "1" if value else "0"
    return f"{name}={q(str(value))}"


def deck_basename(cfg: dict[str, Any], row: MlPathRow) -> str:
    fmt = (cfg.get("deck_generation") or {}).get("output_basename_format", "path_{path_id:06d}")
    try:
        return fmt.format(path_id=row.path_id, fixed_index=row.fixed_index)
    except Exception:
        return f"path_{row.path_id:06d}"


def path_dir_name(row: MlPathRow) -> str:
    return f"path_{row.path_id:06d}"


def build_pt_command(cfg: dict[str, Any], row: MlPathRow, path_dir: Path, basename: str, pt_shell: str) -> list[str]:
    reference_pt = cfg["reference_pt"]
    path_registry = cfg["path_registry"]
    prime_time = cfg["prime_time"]
    spice_model = cfg["spice_model"]
    deck_generation = cfg.get("deck_generation") or {}
    target_defaults = cfg.get("target_corner_defaults") or {}
    setup_script = require_path(prime_time["setup_script"], "PrimeTime setup script")
    tcl = require_path(prime_time["tcl"], "PrimeTime Tcl")

    env_values: dict[str, str | int | float | bool] = {
        "TOP": reference_pt["top"],
        "VERILOG": reference_pt["verilog"],
        "SDC": reference_pt["sdc"],
        "SPEF": reference_pt["spef"],
        "LIB_DB": reference_pt["lib_db"],
        "FIXED_TCL": path_registry["fixed_tcl"],
        "CELL_SPF": spice_model["cell_spf"],
        "MODEL_CARD": spice_model["model_card"],
        "OUT_DIR": str(path_dir),
        "FIXED_INDEX": row.fixed_index,
        "DELAY_TYPE": reference_pt.get("delay_type", "max"),
        "VDD": target_defaults.get("vdd", 0.8),
        "VSS": 0.0,
        "INITIAL_DELAY_NS": deck_generation.get("initial_delay_ns", 1.0),
        "MIN_TRAN_NS": deck_generation.get("minimum_transition_ns", 0.001),
        "TRAN_STEP_NS": deck_generation.get("transient_step_ns", 0.001),
        "TRAN_SIZE_NS": deck_generation.get("transient_stop_ns", 5.0),
        "USE_THROUGHS": bool(reference_pt.get("use_throughs", True)),
        "GROUND_COUPLING": bool(deck_generation.get("ground_coupling_capacitors", True)),
        "OUTPUT_BASENAME": basename,
    }
    if reference_pt.get("extra_libs"):
        env_values["EXTRA_LIBS"] = reference_pt["extra_libs"]
    extra_spice_includes = spice_model.get("extra_spice_includes") or []
    if isinstance(extra_spice_includes, str):
        extra_spice_includes = [extra_spice_includes]
    if extra_spice_includes:
        env_values["EXTRA_SPICE_INCLUDES"] = " ".join(str(item) for item in extra_spice_includes)

    inner = "env " + " ".join(env_assignment(k, v) for k, v in env_values.items())
    inner += f" {q(pt_shell)} -f {q(tcl)}"
    return build_sourced_shell_command(setup_script, inner)


def build_patch_command(cfg: dict[str, Any], row: MlPathRow, path_dir: Path, basename: str, python_bin: str) -> list[str]:
    code_dir = Path((cfg.get("project") or {}).get("work_dir", "."))
    patcher = code_dir / "patch_pt_native_spice_deck.py"
    deck_patch = cfg.get("deck_patch") or {}
    deck_generation = cfg.get("deck_generation") or {}
    command = [
        python_bin,
        str(patcher),
        "--deck",
        str(path_dir / f"{basename}.sp"),
        "--stim",
        str(path_dir / f"{basename}_stim.sp"),
        "--summary",
        str(path_dir / "pt_native_smoke_summary.txt"),
        "--input-slew-ps",
        str(row.input_slew_ps),
        "--output-load-ff",
        str(row.output_load_ff),
        "--target-vdd",
        str(row.target_vdd),
        "--target-temp",
        str(row.target_temp),
        "--tran-stop-ns",
        str(deck_generation.get("transient_stop_ns", 5.0)),
        "--output-load-cap-name",
        str(deck_patch.get("output_load_cap_name", "C_ML_OUT_LOAD")),
        "--output-load-ground-node",
        str(deck_patch.get("output_load_ground_node", "VSS")),
        "--summary-out",
        str(path_dir / f"{basename}_patch_summary.json"),
    ]
    if not bool(deck_patch.get("keep_original_deck_backup", True)):
        command.append("--no-backup")
    return command


def build_hspice_command(cfg: dict[str, Any], path_dir: Path, basename: str, output_prefix: str) -> list[str]:
    hspice = cfg.get("hspice") or {}
    setup_script = require_path(hspice.get("setup_script", (cfg.get("prime_time") or {}).get("setup_script")), "HSPICE setup script")
    hspice_command = hspice.get("command", "hspice")
    inner = f"{q(hspice_command)} {q(path_dir / (basename + '.sp'))} -o {q(output_prefix)}"
    return build_sourced_shell_command(setup_script, inner)


def parse_key_value_summary(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def unit_to_mb(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("g"):
        return value * 1024.0
    if unit.startswith("k"):
        return value / 1024.0
    return value


def scan_hspice_lis(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.is_file(),
        "job_concluded": False,
        "error_lines": [],
        "measure_failed_lines": [],
        "nodes": None,
        "elements": None,
        "resistors": None,
        "capacitors": None,
        "mosfets": None,
        "peak_memory_mb": None,
        "total_cpu_sec": None,
        "total_elapsed_sec": None,
    }
    if not path.is_file():
        return result

    errors: list[str] = []
    measure_failed_lines: list[str] = []
    with path.open(errors="ignore") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.rstrip()
            lower = text.lower()
            if "job concluded" in lower:
                result["job_concluded"] = True
            if len(measure_failed_lines) < 20 and HSPICE_MEASURE_FAIL_PATTERN.search(text):
                measure_failed_lines.append(f"{line_no}: {text}")
            if len(errors) < 20 and any(pattern.search(text) for pattern in HSPICE_FAIL_PATTERNS):
                errors.append(f"{line_no}: {text}")
            if match := NODE_ELEM_RE.search(text):
                result["nodes"] = int(match.group(1))
                result["elements"] = int(match.group(2))
            if match := RES_CAP_RE.search(text):
                result["resistors"] = int(match.group(1))
                result["capacitors"] = int(match.group(2))
            if match := MOS_RE.search(text):
                result["mosfets"] = int(match.group(2))
            if match := MEM_RE.search(text):
                result["peak_memory_mb"] = round(unit_to_mb(float(match.group(1)), match.group(2)), 3)
            if match := CPU_RE.search(text):
                result["total_cpu_sec"] = float(match.group(1))
            if match := ELAPSED_RE.search(text):
                result["total_elapsed_sec"] = float(match.group(1))
    result["error_lines"] = errors
    result["measure_failed_lines"] = measure_failed_lines
    return result


def count_failed_measures(mt0_path: Path) -> int:
    if not mt0_path.is_file():
        return 0
    count = 0
    with mt0_path.open(errors="ignore") as handle:
        for line in handle:
            for token in line.split():
                if token.strip().lower() in {"failed", "fail"}:
                    count += 1
    return count


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def row_status(pt_ok: bool, patch_ok: bool, hspice_ok: bool, skip_hspice: bool, dry_run: bool) -> str:
    if dry_run:
        return "DRY_RUN"
    if not pt_ok:
        return "PT_FAIL"
    if not patch_ok:
        return "PATCH_FAIL"
    if skip_hspice:
        return "PATCHED"
    if not hspice_ok:
        return "HSPICE_FAIL"
    return "PASS"


def run_one_row(
    cfg: dict[str, Any],
    row: MlPathRow,
    batch_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    basename = deck_basename(cfg, row)
    path_dir = batch_dir / path_dir_name(row)
    if path_dir.exists() and any(path_dir.iterdir()) and not args.force:
        raise RuntimeError(f"{path_dir} already exists and is not empty. Use --force or a new --run-name.")
    path_dir.mkdir(parents=True, exist_ok=True)

    deck_path = path_dir / f"{basename}.sp"
    stim_path = path_dir / f"{basename}_stim.sp"
    summary_path = path_dir / "pt_native_smoke_summary.txt"
    patch_summary_path = path_dir / f"{basename}_patch_summary.json"
    hspice_suffix = (cfg.get("hspice") or {}).get("output_suffix", "_hspice")
    hspice_prefix = f"{basename}{hspice_suffix}"
    lis_path = path_dir / f"{hspice_prefix}.lis"
    mt0_path = path_dir / f"{hspice_prefix}.mt0"

    status: dict[str, Any] = {
        "path_id": row.path_id,
        "fixed_index": row.fixed_index,
        "row_number": row.row_number,
        "input_slew_ps": row.input_slew_ps,
        "output_load_ff": row.output_load_ff,
        "target_vdd": row.target_vdd,
        "target_temp": row.target_temp,
        "path_dir": str(path_dir),
        "basename": basename,
        "files": {
            "deck": str(deck_path),
            "stim": str(stim_path),
            "pt_summary": str(summary_path),
            "patch_summary": str(patch_summary_path),
            "hspice_lis": str(lis_path),
            "hspice_mt0": str(mt0_path),
        },
    }

    pt_ok = args.skip_pt and deck_path.is_file() and stim_path.is_file() and summary_path.is_file()
    if args.skip_pt:
        status["prime_time"] = {"skipped": True, "ok": pt_ok}
    else:
        pt_command = build_pt_command(cfg, row, path_dir, basename, args.pt_shell)
        pt_result = run_logged_command(
            pt_command,
            cwd=path_dir,
            log_path=path_dir / "pt.log",
            timeout_sec=args.timeout_pt_sec,
            dry_run=args.dry_run,
        )
        pt_ok = bool(pt_result["returncode"] == 0 and not pt_result["timed_out"] and (args.dry_run or (deck_path.is_file() and stim_path.is_file())))
        status["prime_time"] = {**pt_result, "ok": pt_ok}

    pt_summary = parse_key_value_summary(summary_path)
    status["pt_path"] = {
        "path_key": pt_summary.get("path_key"),
        "from_pin": pt_summary.get("from_pin"),
        "to_pin": pt_summary.get("to_pin"),
        "through_count": pt_summary.get("through_count"),
    }

    patch_ok = args.skip_patch and deck_path.is_file() and stim_path.is_file()
    if pt_ok and not args.skip_patch:
        patch_command = build_patch_command(cfg, row, path_dir, basename, args.python_bin)
        patch_result = run_logged_command(
            patch_command,
            cwd=Path((cfg.get("project") or {}).get("work_dir", ".")),
            log_path=path_dir / "patch.log",
            timeout_sec=120,
            dry_run=args.dry_run,
        )
        patch_ok = bool(patch_result["returncode"] == 0 and not patch_result["timed_out"] and (args.dry_run or patch_summary_path.is_file()))
        status["patch"] = {**patch_result, "ok": patch_ok}
    else:
        status["patch"] = {"skipped": True, "ok": patch_ok}

    hspice_ok = args.skip_hspice
    hspice_scan: dict[str, Any] = {}
    measure_failed_count = 0
    if pt_ok and patch_ok and not args.skip_hspice:
        hspice_command = build_hspice_command(cfg, path_dir, basename, hspice_prefix)
        hspice_result = run_logged_command(
            hspice_command,
            cwd=path_dir,
            log_path=path_dir / "hspice.log",
            timeout_sec=args.timeout_hspice_sec,
            dry_run=args.dry_run,
        )
        hspice_scan = scan_hspice_lis(lis_path) if not args.dry_run else {"job_concluded": True}
        measure_failed_count = count_failed_measures(mt0_path) if not args.dry_run else 0
        hspice_cfg = cfg.get("hspice") or {}
        error_lines = hspice_scan.get("error_lines") or []
        hspice_ok = bool(
            hspice_result["returncode"] == 0
            and not hspice_result["timed_out"]
            and (args.dry_run or bool(hspice_scan.get("job_concluded")))
            and (args.dry_run or mt0_path.is_file())
            and (not bool(hspice_cfg.get("fail_on_hspice_error", True)) or not error_lines)
            and (not bool(hspice_cfg.get("fail_on_measure_failed", False)) or measure_failed_count == 0)
        )
        status["hspice"] = {
            **hspice_result,
            "ok": hspice_ok,
            "scan": hspice_scan,
            "measure_failed_count": measure_failed_count,
        }
    else:
        status["hspice"] = {"skipped": True, "ok": hspice_ok}

    final_status = row_status(pt_ok, patch_ok, hspice_ok, args.skip_hspice, args.dry_run)
    status["status"] = final_status
    status["ok"] = final_status in {"PASS", "PATCHED", "DRY_RUN"}
    write_json(path_dir / "status.json", status)
    return status


def summary_row(status: dict[str, Any]) -> dict[str, Any]:
    hspice = status.get("hspice") or {}
    scan = hspice.get("scan") or {}
    pt_path = status.get("pt_path") or {}
    return {
        "path_id": status.get("path_id"),
        "fixed_index": status.get("fixed_index"),
        "status": status.get("status"),
        "pt_ok": bool((status.get("prime_time") or {}).get("ok")),
        "patch_ok": bool((status.get("patch") or {}).get("ok")),
        "hspice_ok": bool(hspice.get("ok")),
        "job_concluded": scan.get("job_concluded"),
        "mt0_exists": Path((status.get("files") or {}).get("hspice_mt0", "")).is_file(),
        "measure_failed_count": hspice.get("measure_failed_count", 0),
        "nodes": scan.get("nodes"),
        "elements": scan.get("elements"),
        "resistors": scan.get("resistors"),
        "capacitors": scan.get("capacitors"),
        "mosfets": scan.get("mosfets"),
        "peak_memory_mb": scan.get("peak_memory_mb"),
        "total_cpu_sec": scan.get("total_cpu_sec"),
        "total_elapsed_sec": scan.get("total_elapsed_sec"),
        "input_slew_ps": status.get("input_slew_ps"),
        "output_load_ff": status.get("output_load_ff"),
        "target_vdd": status.get("target_vdd"),
        "target_temp": status.get("target_temp"),
        "path_key": pt_path.get("path_key"),
        "from_pin": pt_path.get("from_pin"),
        "to_pin": pt_path.get("to_pin"),
        "through_count": pt_path.get("through_count"),
        "path_dir": status.get("path_dir"),
    }


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "path_id",
        "fixed_index",
        "status",
        "pt_ok",
        "patch_ok",
        "hspice_ok",
        "job_concluded",
        "mt0_exists",
        "measure_failed_count",
        "nodes",
        "elements",
        "resistors",
        "capacitors",
        "mosfets",
        "peak_memory_mb",
        "total_cpu_sec",
        "total_elapsed_sec",
        "input_slew_ps",
        "output_load_ff",
        "target_vdd",
        "target_temp",
        "path_key",
        "from_pin",
        "to_pin",
        "through_count",
        "path_dir",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def validate_config_paths(cfg: dict[str, Any]) -> None:
    project = cfg.get("project") or {}
    reference_pt = cfg.get("reference_pt") or {}
    prime_time = cfg.get("prime_time") or {}
    path_registry = cfg.get("path_registry") or {}
    spice_model = cfg.get("spice_model") or {}
    checks = [
        (reference_pt.get("verilog"), "reference_pt.verilog"),
        (reference_pt.get("sdc"), "reference_pt.sdc"),
        (reference_pt.get("spef"), "reference_pt.spef"),
        (reference_pt.get("lib_db"), "reference_pt.lib_db"),
        (path_registry.get("fixed_tcl"), "path_registry.fixed_tcl"),
        (prime_time.get("setup_script"), "prime_time.setup_script"),
        (prime_time.get("tcl"), "prime_time.tcl"),
        (spice_model.get("model_card"), "spice_model.model_card"),
        (spice_model.get("cell_spf"), "spice_model.cell_spf"),
    ]
    for value, label in checks:
        if not value:
            raise SystemExit(f"ERROR: config missing {label}")
        require_path(value, label)
    extra_spice_includes = spice_model.get("extra_spice_includes") or []
    if isinstance(extra_spice_includes, str):
        extra_spice_includes = [extra_spice_includes]
    for index, value in enumerate(extra_spice_includes, 1):
        require_path(value, f"spice_model.extra_spice_includes[{index}]")
    work_dir = project.get("work_dir")
    if work_dir:
        require_path(work_dir, "project.work_dir", file=False)


def run_post_process(batch_dir: Path, python_bin: str, timeout_sec: int, dry_run: bool) -> dict[str, Any]:
    parser = SCRIPT_DIR / "parse_pt_native_mt0.py"
    formatter = SCRIPT_DIR / "format_pt_native_report.py"
    pt_formatter = SCRIPT_DIR / "format_pt_si_report.py"
    result: dict[str, Any] = {
        "parser": None,
        "formatter": None,
        "pt_formatter": None,
        "ok": False,
    }

    parse_command = [python_bin, str(parser), "--batch-dir", str(batch_dir)]
    parse_result = run_logged_command(
        parse_command,
        cwd=SCRIPT_DIR,
        log_path=batch_dir / "post_process_parse.log",
        timeout_sec=timeout_sec,
        dry_run=dry_run,
    )
    result["parser"] = parse_result
    parse_ok = bool(parse_result["returncode"] == 0 and not parse_result["timed_out"])
    if not parse_ok:
        return result

    format_command = [python_bin, str(formatter), "--batch-dir", str(batch_dir)]
    format_result = run_logged_command(
        format_command,
        cwd=SCRIPT_DIR,
        log_path=batch_dir / "post_process_format.log",
        timeout_sec=timeout_sec,
        dry_run=dry_run,
    )
    result["formatter"] = format_result
    format_ok = bool(format_result["returncode"] == 0 and not format_result["timed_out"])
    if not format_ok:
        return result

    pt_format_command = [python_bin, str(pt_formatter), "--batch-dir", str(batch_dir)]
    pt_format_result = run_logged_command(
        pt_format_command,
        cwd=SCRIPT_DIR,
        log_path=batch_dir / "post_process_pt_compare.log",
        timeout_sec=timeout_sec,
        dry_run=dry_run,
    )
    result["pt_formatter"] = pt_format_result
    result["ok"] = bool(pt_format_result["returncode"] == 0 and not pt_format_result["timed_out"])
    return result


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    validate_config_paths(cfg)
    rows = load_ml_rows(args.ml_csv, cfg, args.limit, set(args.path_id) if args.path_id else None)

    output_root = args.output_root or Path((cfg.get("project") or {}).get("output_root", "output"))
    output_root = output_root.expanduser()
    run_name = args.run_name or f"batch_{timestamp()}"
    batch_dir = output_root / run_name
    if batch_dir.exists() and any(batch_dir.iterdir()) and not args.force:
        raise SystemExit(f"ERROR: batch dir already exists and is not empty: {batch_dir}. Use --force or another --run-name.")
    batch_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config": str(args.config),
        "ml_csv": str(args.ml_csv),
        "run_name": run_name,
        "batch_dir": str(batch_dir),
        "row_count": len(rows),
        "dry_run": args.dry_run,
        "skip_pt": args.skip_pt,
        "skip_patch": args.skip_patch,
        "skip_hspice": args.skip_hspice,
        "post_process": args.post_process,
    }
    write_json(batch_dir / "batch_manifest.json", meta)

    statuses: list[dict[str, Any]] = []
    for row in rows:
        print(f"[{path_dir_name(row)}] start path_id={row.path_id} fixed_index={row.fixed_index}", flush=True)
        try:
            status = run_one_row(cfg, row, batch_dir, args)
        except Exception as exc:  # noqa: BLE001 - batch runner must record per-row failures.
            path_dir = batch_dir / path_dir_name(row)
            path_dir.mkdir(parents=True, exist_ok=True)
            status = {
                "path_id": row.path_id,
                "fixed_index": row.fixed_index,
                "row_number": row.row_number,
                "input_slew_ps": row.input_slew_ps,
                "output_load_ff": row.output_load_ff,
                "target_vdd": row.target_vdd,
                "target_temp": row.target_temp,
                "path_dir": str(path_dir),
                "status": "FLOW_EXCEPTION",
                "ok": False,
                "exception": str(exc),
            }
            write_json(path_dir / "status.json", status)
        statuses.append(status)
        print(f"[{path_dir_name(row)}] {status.get('status')}", flush=True)
        if not status.get("ok") and not args.continue_on_error:
            break

    summary_rows = [summary_row(status) for status in statuses]
    write_summary_csv(batch_dir / "batch_summary.csv", summary_rows)
    batch_ok = all(status.get("ok") for status in statuses)
    post_process_status: dict[str, Any] | None = None
    if args.post_process:
        print("[post_process] start", flush=True)
        post_process_status = run_post_process(
            batch_dir=batch_dir,
            python_bin=args.python_bin,
            timeout_sec=args.timeout_post_process_sec,
            dry_run=args.dry_run,
        )
        write_json(batch_dir / "post_process_status.json", post_process_status)
        print(f"[post_process] {'PASS' if post_process_status.get('ok') else 'FAIL'}", flush=True)
        batch_ok = batch_ok and bool(post_process_status.get("ok"))

    write_json(
        batch_dir / "batch_status.json",
        {
            "ok": batch_ok,
            "rows": statuses,
            "post_process": post_process_status,
        },
    )

    passed = sum(1 for status in statuses if status.get("ok"))
    print(f"batch_dir={batch_dir}")
    print(f"rows={len(statuses)} pass={passed} failed={len(statuses) - passed}")
    return 0 if batch_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
