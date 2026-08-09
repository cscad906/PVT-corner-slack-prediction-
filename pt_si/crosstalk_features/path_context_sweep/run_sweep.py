#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
PARSER_SCRIPTS = SCRIPT_DIR / "parsers"
TCL_DIR = SCRIPT_DIR / "tcl"

# Data layout root (annotation/, db/, implementation/ live under here).
# Set via --data-root or XTALK_DATA_ROOT. Layout is the same as the internal
# iter51 tree; see README.md.
DATA_ROOT = Path(os.environ.get("XTALK_DATA_ROOT", str(Path.cwd())))
CROSSTALK = DATA_ROOT / "crosstalk"

# PrimeTime environment: PT_SOURCE (optional csh setup script that puts
# pt_shell on PATH) and PT_LICENSE (optional LM_LICENSE_FILE value).
PT_SOURCE = os.environ.get("PT_SOURCE", "")
LICENSE = os.environ.get("PT_LICENSE", "")

# Design-specific naming (env-overridable so new designs need no code edit).
# Defaults preserve the internal smallboom_14nm iter51 layout.
VERILOG = Path(os.environ.get("XTALK_VERILOG", str(DATA_ROOT / "implementation/netlist/smallboom_14nm_icc2.v")))
SDC = Path(os.environ.get("XTALK_SDC", str(DATA_ROOT / "implementation/sdc/smallboom_14nm_icc2.sdc")))
SPEF_DIR = Path(os.environ.get("XTALK_SPEF_DIR", str(DATA_ROOT / "implementation/spef")))
SPEF_PREFIX = os.environ.get("XTALK_SPEF_PREFIX", "smallboom_14nm")
# Process prefix used only in the output corner LABEL (feature_corner), e.g.
# "tt"/"ss"/"ff". Does not affect db lookup (that is XTALK_DB_STEM_FORMAT).
PROCESS = os.environ.get("XTALK_PROCESS", "tt")
# db/lib/annotated stem; {vtag}/{db_temp}/{style} placeholders. {style}=TEMPS[t]["style"].
DB_STEM_FORMAT = os.environ.get(
    "XTALK_DB_STEM_FORMAT",
    "saed14rvt_tt{vtag}v{db_temp}_ccs_rth0p01_{style}_3ns250fj_mono")

ANALYSES = {
    "setup": "setup_sion",
    "hold": "hold_sion",
}

CORNERS = ("Cmin", "Cnom", "Cmax")

TEMPS = {
    "m40": {"db_temp": "m40c", "spef_temp": "m40", "file_temp": "m40C", "style": "smallboom_stylemon2_pos"},
    "25": {"db_temp": "25c", "spef_temp": "25", "file_temp": "25C", "style": "full385"},
    "125": {"db_temp": "125c", "spef_temp": "125", "file_temp": "125C", "style": "smallboom_stylemon2_pos"},
}

VOLTAGES = (
    ("0.600", "0p6"),
    ("0.605", "0p605"),
    ("0.610", "0p610"),
    ("0.615", "0p615"),
    ("0.620", "0p620"),
    ("0.625", "0p625"),
    ("0.650", "0p65"),
    ("0.675", "0p675"),
    ("0.700", "0p7"),
    ("0.725", "0p725"),
    ("0.750", "0p75"),
    ("0.775", "0p775"),
    ("0.780", "0p780"),
    ("0.785", "0p785"),
    ("0.790", "0p790"),
    ("0.795", "0p795"),
    ("0.800", "0p8"),
)


@dataclass(frozen=True)
class Job:
    final_analysis: str
    annotation_analysis: str
    corner: str
    temp: str
    voltage: str
    vtag: str

    @property
    def temp_info(self) -> Dict[str, str]:
        return TEMPS[self.temp]

    @property
    def final_dir(self) -> Path:
        return CROSSTALK / self.final_analysis / self.corner

    @property
    def final_rpt(self) -> Path:
        return self.final_dir / f"TT_{self.vtag}V_{self.temp_info['file_temp']}.path_context_si_compact.by_path.rpt"

    @property
    def work_dir(self) -> Path:
        return CROSSTALK / "work" / self.final_analysis / self.corner / f"temp_{self.temp}" / self.vtag

    @property
    def log_prefix(self) -> str:
        return f"{self.final_analysis}_{self.corner}_temp_{self.temp}_{self.vtag}"

    @property
    def db_stem(self) -> str:
        info = self.temp_info
        return DB_STEM_FORMAT.format(vtag=self.vtag, db_temp=info["db_temp"], style=info.get("style", ""))

    @property
    def annotated_report(self) -> Path:
        name = f"{self.db_stem}_fixed_annotated.txt"
        return DATA_ROOT / "annotation" / self.annotation_analysis / f"temp_{self.temp}" / "annotated" / self.corner / name

    @property
    def db(self) -> Path:
        return DATA_ROOT / "db" / f"{self.db_stem}.db"

    @property
    def spef(self) -> Path:
        return SPEF_DIR / f"{SPEF_PREFIX}.{self.corner}_model_{self.temp_info['spef_temp']}.spef"

    @property
    def feature_corner(self) -> str:
        return f"{PROCESS}{self.voltage}v{self.temp_info['db_temp']}_{self.corner}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 14nm real-crosstalk path-context SI sweep.")
    parser.add_argument("--data-root", default=None,
                        help="Root dir containing annotation/, db/, implementation/ (default: $XTALK_DATA_ROOT or cwd).")
    parser.add_argument("--analysis", choices=["all", "setup", "hold"], default="all")
    parser.add_argument("--corner", action="append", choices=CORNERS, help="Repeatable. Default: all corners.")
    parser.add_argument("--temp", action="append", choices=tuple(TEMPS), help="Repeatable. Default: all temperatures.")
    parser.add_argument("--vtag", action="append", choices=[vtag for _, vtag in VOLTAGES], help="Repeatable. Default: all voltages.")
    parser.add_argument("--limit-jobs", type=int, default=0, help="Run at most N selected jobs.")
    parser.add_argument("--max-contexts", type=int, default=0, help="Forward PT_CONTEXT_MAX_CONTEXTS for smoke tests.")
    parser.add_argument("--force", action="store_true", help="Regenerate final RPT even when it already exists.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected jobs and missing inputs only.")
    parser.add_argument("--keep-work", action="store_true", help="Keep heavy intermediate work files after successful jobs.")
    parser.add_argument("--jobs", type=int, default=1, help="Maximum number of corner jobs to run in parallel.")
    return parser.parse_args()


def selected_jobs(args: argparse.Namespace) -> List[Job]:
    analyses = ("setup", "hold") if args.analysis == "all" else (args.analysis,)
    corners = tuple(args.corner) if args.corner else CORNERS
    temps = tuple(args.temp) if args.temp else tuple(TEMPS)
    vtags = set(args.vtag) if args.vtag else None

    jobs: List[Job] = []
    for final_analysis in analyses:
        annotation_analysis = ANALYSES[final_analysis]
        for corner in corners:
            for temp in temps:
                for voltage, vtag in VOLTAGES:
                    if vtags is not None and vtag not in vtags:
                        continue
                    jobs.append(Job(final_analysis, annotation_analysis, corner, temp, voltage, vtag))

    if args.limit_jobs and args.limit_jobs > 0:
        jobs = jobs[: args.limit_jobs]
    return jobs


def validate_job(job: Job) -> List[Path]:
    required = [VERILOG, SDC, job.annotated_report, job.db, job.spef]
    return [path for path in required if not path.exists()]


def run_logged(cmd: List[str], log: Path, env: Optional[Dict[str, str]] = None) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    with log.open("w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=merged_env, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {' '.join(cmd)} log={log}")


def run_pt(tcl: Path, log: Path, env: Dict[str, str]) -> None:
    parts = []
    if PT_SOURCE:
        parts.append(f"source {PT_SOURCE}")
    if LICENSE:
        parts.append(f"setenv LM_LICENSE_FILE {LICENSE}")
        parts.append(f"setenv SNPSLMD_LICENSE_FILE {LICENSE}")
    parts.append(f"pt_shell -file {tcl}")
    cmd = ["tcsh", "-c", "; ".join(parts)]
    run_logged(cmd, log, env=env)


def remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_summary(path: Path, lines: List[str]) -> None:
    with path.open("w") as fh:
        for line in lines:
            fh.write(line.rstrip("\n") + "\n")


def cleanup_work(job: Job, keep_work: bool) -> None:
    if keep_work:
        return
    for name in [
        "path_summary.tsv",
        "path_victim_nets.tsv",
        "unique_path_arc_contexts.tsv",
        "path_context_report_delay_calculation.raw.rpt",
        "path_context_report_delay_calculation_manifest.tsv",
        "path_context_delay_calculation_summary.tsv",
        "path_context_active_aggressor_features.tsv",
        "compact_victim_load_pins.txt",
        "compact_aggressor_nets.txt",
        "compact_victim_load_pin_windows.tsv",
        "compact_aggressor_driver_windows.tsv",
        "compact_path_context_features.flat.tsv",
        "compact_path_context_features.by_path.rpt",
    ]:
        remove_if_exists(job.work_dir / name)


def run_job(job: Job, args: argparse.Namespace) -> None:
    missing = validate_job(job)
    if missing:
        raise FileNotFoundError("missing inputs: " + ", ".join(str(path) for path in missing))

    if job.final_rpt.exists() and not args.force:
        print(f"SKIP existing {job.final_rpt}", flush=True)
        return

    job.work_dir.mkdir(parents=True, exist_ok=True)
    job.final_dir.mkdir(parents=True, exist_ok=True)
    log_dir = CROSSTALK / "logs"

    path_summary = job.work_dir / "path_summary.tsv"
    path_victim = job.work_dir / "path_victim_nets.tsv"
    unique_contexts = job.work_dir / "unique_path_arc_contexts.tsv"
    context_raw = job.work_dir / "path_context_report_delay_calculation.raw.rpt"
    context_summary = job.work_dir / "path_context_delay_calculation_summary.tsv"
    active_features = job.work_dir / "path_context_active_aggressor_features.tsv"
    victim_pins = job.work_dir / "compact_victim_load_pins.txt"
    aggressor_nets = job.work_dir / "compact_aggressor_nets.txt"
    victim_windows = job.work_dir / "compact_victim_load_pin_windows.tsv"
    aggressor_windows = job.work_dir / "compact_aggressor_driver_windows.tsv"
    flat_out = job.work_dir / "compact_path_context_features.flat.tsv"
    by_path_work = job.work_dir / "compact_path_context_features.by_path.rpt"
    job_summary = job.work_dir / "job_summary.txt"

    start = time.time()
    print(f"RUN {job.final_analysis} {job.corner} temp_{job.temp} {job.vtag}", flush=True)

    run_logged(
        [
            sys.executable,
            str(PARSER_SCRIPTS / "parse_annotated_with_clock_segments.py"),
            str(job.annotated_report),
            str(path_summary),
            str(path_victim),
        ],
        log_dir / f"{job.log_prefix}.01_parse_annotated.log",
    )
    run_logged(
        [
            sys.executable,
            str(PARSER_SCRIPTS / "make_unique_path_arc_contexts.py"),
            str(path_victim),
            str(unique_contexts),
        ],
        log_dir / f"{job.log_prefix}.02_unique_contexts.log",
    )

    pt_env = {
        "PT_VERILOG": str(VERILOG),
        "PT_SDC": str(SDC),
        "PT_DB": str(job.db),
        "PT_SPEF": str(job.spef),
        "PT_CONTEXT_OUT_DIR": str(job.work_dir),
        "PT_DELAY_TYPE": "min" if job.final_analysis == "hold" else "max",
    }
    if args.max_contexts > 0:
        pt_env["PT_CONTEXT_MAX_CONTEXTS"] = str(args.max_contexts)
    run_pt(
        TCL_DIR / "dump_path_context_delay_calculation.tcl",
        log_dir / f"{job.log_prefix}.03_pt_context.log",
        pt_env,
    )

    parse_env = {
        "PT_FEATURE_CORNER": job.feature_corner,
        "PT_FEATURE_ANALYSIS_TYPE": job.final_analysis,
        "PT_FEATURE_VOLTAGE": job.voltage,
        "PT_FEATURE_TEMPERATURE": job.temp_info["file_temp"].removesuffix("C"),
    }
    run_logged(
        [
            sys.executable,
            str(PARSER_SCRIPTS / "parse_path_context_delay_calculation.py"),
            str(path_victim),
            str(unique_contexts),
            str(context_raw),
            str(context_summary),
            str(active_features),
        ],
        log_dir / f"{job.log_prefix}.04_parse_context.log",
        env=parse_env,
    )
    run_logged(
        [
            sys.executable,
            str(PARSER_SCRIPTS / "prepare_compact_timing_window_requests.py"),
            str(active_features),
            str(victim_pins),
            str(aggressor_nets),
        ],
        log_dir / f"{job.log_prefix}.05_prepare_windows.log",
    )
    pt_window_env = {
        "PT_VERILOG": str(VERILOG),
        "PT_SDC": str(SDC),
        "PT_DB": str(job.db),
        "PT_SPEF": str(job.spef),
        "PT_COMPACT_OUT_DIR": str(job.work_dir),
    }
    run_pt(
        TCL_DIR / "dump_compact_timing_windows.tcl",
        log_dir / f"{job.log_prefix}.06_pt_windows.log",
        pt_window_env,
    )
    run_logged(
        [
            sys.executable,
            str(PARSER_SCRIPTS / "make_compact_path_context_report.py"),
            str(active_features),
            str(path_victim),
            str(victim_windows),
            str(aggressor_windows),
            str(flat_out),
            str(by_path_work),
        ],
        log_dir / f"{job.log_prefix}.07_make_rpt.log",
    )

    tmp_final = job.final_rpt.with_suffix(job.final_rpt.suffix + ".tmp")
    shutil.copy2(by_path_work, tmp_final)
    tmp_final.replace(job.final_rpt)

    elapsed = time.time() - start
    write_summary(
        job_summary,
        [
            f"status=OK",
            f"elapsed_seconds={elapsed:.1f}",
            f"analysis={job.final_analysis}",
            f"corner={job.corner}",
            f"temp={job.temp}",
            f"voltage={job.voltage}",
            f"vtag={job.vtag}",
            f"annotated={job.annotated_report}",
            f"db={job.db}",
            f"spef={job.spef}",
            f"final_rpt={job.final_rpt}",
            f"max_contexts={args.max_contexts}",
            f"pt_delay_type={'min' if job.final_analysis == 'hold' else 'max'}",
        ],
    )
    cleanup_work(job, args.keep_work)
    print(f"DONE {job.final_rpt} elapsed={elapsed:.1f}s", flush=True)


def run_indexed_job(idx: int, total: int, job: Job, args: argparse.Namespace) -> None:
    print(f"JOB {idx}/{total}", flush=True)
    run_job(job, args)


def main() -> int:
    args = parse_args()
    if args.data_root:
        global DATA_ROOT, CROSSTALK, VERILOG, SDC, SPEF_DIR
        DATA_ROOT = Path(args.data_root).resolve()
        CROSSTALK = DATA_ROOT / "crosstalk"
        # Only re-derive paths not explicitly pinned via XTALK_* env vars.
        if "XTALK_VERILOG" not in os.environ:
            VERILOG = DATA_ROOT / "implementation/netlist/smallboom_14nm_icc2.v"
        if "XTALK_SDC" not in os.environ:
            SDC = DATA_ROOT / "implementation/sdc/smallboom_14nm_icc2.sdc"
        if "XTALK_SPEF_DIR" not in os.environ:
            SPEF_DIR = DATA_ROOT / "implementation/spef"
    if args.jobs < 1:
        print(f"ERROR: --jobs must be >= 1, got {args.jobs}", file=sys.stderr)
        return 2

    jobs = selected_jobs(args)
    missing_total = 0
    print(f"selected_jobs={len(jobs)}")
    for job in jobs:
        missing = validate_job(job)
        if args.dry_run:
            status = "MISSING" if missing else "OK"
            print(f"{status}\t{job.final_analysis}\t{job.corner}\ttemp_{job.temp}\t{job.vtag}\t{job.final_rpt}")
            for path in missing:
                print(f"  missing: {path}")
        if missing:
            missing_total += len(missing)

    if args.dry_run:
        print(f"missing_inputs={missing_total}")
        return 1 if missing_total else 0
    if missing_total:
        print(f"ERROR: missing input count={missing_total}", file=sys.stderr)
        return 1

    failures = 0
    if args.jobs == 1:
        for idx, job in enumerate(jobs, 1):
            try:
                run_indexed_job(idx, len(jobs), job, args)
            except Exception as exc:
                failures += 1
                print(f"FAIL {job.final_analysis} {job.corner} temp_{job.temp} {job.vtag}: {exc}", file=sys.stderr, flush=True)
                # Keep work files for failed jobs.
                break
    else:
        print(f"parallel_jobs={args.jobs}", flush=True)
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = {
                executor.submit(run_indexed_job, idx, len(jobs), job, args): job
                for idx, job in enumerate(jobs, 1)
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    failures += 1
                    print(
                        f"FAIL {job.final_analysis} {job.corner} temp_{job.temp} {job.vtag}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    for pending in futures:
                        pending.cancel()
                    break

    if failures:
        print(f"completed_with_failures={failures}", file=sys.stderr)
        return 1
    print("all_selected_jobs_completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
