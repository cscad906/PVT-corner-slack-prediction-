#!/usr/bin/env python3
# Fixed-path voltage-sweep runner + Dist/Res/Cpin annotation (SAED14 RVT CCS).
#
# 설계:
#   - 코너 축 = "전압 N종 @ 고정 온도" (--db-root 의 *.db 가 전압 코너 목록).
#   - SPEF 는 RC 코너(Cmax/Cnom/Cmin)로 구분되며, 같은 RC 코너면 전압에
#     무관하게 동일 SPEF 1개를 공유한다.
#   => "그룹 = RC 코너". 그룹 안에서 전압들을 순차 처리하며 Dist/Res
#      annotation 캐시를 100% 재사용하고, RC 코너 3개는 병렬 실행된다.
#
# 흐름:
#   1) ref 코너 + ref RC(기본 Cnom) 에서 topK 경로 추출  (tcl/run_ref_topk.tcl)
#   2) fixed-path tcl 생성 -> ref 재타이밍 + annotate -> strict fixed-path tcl 생성
#   3) RC 코너별(Cmax/Cnom/Cmin) 로 전압 스윕 재타이밍 + cached annotate
#
# SI: --si 를 주면 동일 TCL 이 SI=1 환경변수로 PrimeTime SI 분석
#     (si_enable_analysis + read_parasitics -keep_capacitive_coupling)을 켠다.
# PT 환경: pt_shell 이 PATH 에 없으면 PT_SOURCE 환경변수에 셋업 스크립트 지정.
import argparse
import contextlib
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import os
import subprocess
import sys
import traceback

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_SCRIPT_DIR = SCRIPT_DIR
BASE = SCRIPT_DIR.parent
# Default only. For another server, pass explicit --verilog/--sdc/--spef-root/
# --db-root/--lib-root/--ref-db/--out-dir, or set PVT_PREDICTION_ROOT.
DATA_ROOT = Path(os.environ.get("PVT_PREDICTION_ROOT", str(Path.cwd())))
sys.path.insert(0, str(SCRIPT_DIR))

import res
import ptann_lib as lib


RC_CORNERS = ("Cmax", "Cnom", "Cmin")
# Voltage token = "<V>v<T>c" (e.g. 0p8v25c, 0p72v125c, 0p88vm40c). The v<temp>c
# suffix anchors the match, so any process prefix (tt / ss / ff / ssg / ...) works
# and lookalike tokens such as rth0p01 (no trailing v..c) are not matched.
# NOTE: assumes exactly one "<V>v<T>c" token per db filename.
VOLT_RE = re.compile(r"(\d+p\d+)v(?:m?\d+)c")


def now():
    return datetime.now().isoformat(timespec="seconds")


def volt_token(db_name: str) -> str:
    """saed14rvt_tt0p7v25c_ccs_pvt.db -> '0p7'"""
    m = VOLT_RE.search(db_name)
    if not m:
        raise RuntimeError(f"No voltage token (ttXpYvNNc or ttXpYvmNNc) in {db_name}")
    return m.group(1)


def volt_value(db_name: str) -> float:
    """saed14rvt_tt0p795v25c_*.db -> 0.795"""
    return float(volt_token(db_name).replace("p", "."))


DEFAULT_SPEF_NAME_FORMAT = "{prefix}.starrc.{rc}_model_{temp}.spef"


def spef_for_rc(spef_root: Path, spef_prefix: str, rc: str,
                name_format: str = DEFAULT_SPEF_NAME_FORMAT, temp: str = "25") -> Path:
    """SPEF filename = name_format.format(prefix=, rc=, temp=).
    기본값은 <prefix>.starrc.<RC>_model_25.spef (RC in Cmax/Cnom/Cmin)."""
    spef = spef_root / name_format.format(prefix=spef_prefix, rc=rc, temp=temp)
    if not spef.exists():
        raise RuntimeError(f"missing SPEF for RC={rc}: {spef}")
    return spef


def lib_for_db(db_path: Path, lib_root: Path) -> Path:
    lib_path = lib_root / db_path.with_suffix(".lib").name
    if not lib_path.exists():
        raise RuntimeError(f"missing LIB for {db_path.name}: {lib_path}")
    return lib_path


def spef_has_coupling(spef: Path) -> bool:
    """SPEF *CAP 섹션에 coupling cap('idx *netA:n *netB:m val', 노드 2개, 두번째도 net 노드)이
    하나라도 있으면 True. 첫 coupling 발견 즉시 종료하므로 coupled SPEF면 매우 빠름.
    grounded cap 은 'idx *net:n val' (노드 1개) 형태라 제외된다."""
    in_cap = False
    with open(spef, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("*CAP"):
                in_cap = True
                continue
            if line.startswith("*"):  # 다른 섹션 헤더(*RES/*CONN/*END/*D_NET/...) 만나면 CAP 종료
                in_cap = False
                continue
            if in_cap:
                parts = line.split()
                # coupling: "idx nodeA nodeB val" 이고 세번째 토큰이 net 노드(*로 시작)
                if len(parts) == 4 and parts[2].startswith("*"):
                    return True
    return False


def process_group(
    rc: str,
    spef: str,
    db_paths,
    fixed_tcl: str,
    report_dir: str,
    ann_dir: str,
    log_dir: str,
    top: str,
    verilog: str,
    sdc: str,
    lib_root: str,
    delay_type: str,
    extra_libs: str,
    corner_tcl: str,
    force_basic_rc: str,
    si: str,
):
    """한 RC 코너에 대해 전압 17종을 순차 처리. SPEF 가 동일하므로 annotation 캐시 100% 재사용."""
    dbs = [Path(p) for p in db_paths]
    fixed_tcl = Path(fixed_tcl)
    report_dir = Path(report_dir) / rc
    ann_dir = Path(ann_dir) / rc
    report_dir.mkdir(parents=True, exist_ok=True)
    ann_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / f"{rc}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    spef = Path(spef)
    lib_root = Path(lib_root)

    summary = []
    dist_res_cache = None

    for idx, db in enumerate(dbs):
        lib_path = lib_for_db(db, lib_root)
        stem = db.stem
        rpt = report_dir / f"{stem}_fixed.rpt"
        ann = ann_dir / f"{stem}_fixed_annotated.txt"

        lib.run_pt(
            Path(corner_tcl),
            {
                "TOP": top,
                "VERILOG": verilog,
                "SDC": sdc,
                "SPEF": spef,
                "LIB_DB": db,
                "FIXED_TCL": fixed_tcl,
                "OUT_RPT": rpt,
                "DELAY_TYPE": delay_type,
                "EXTRA_LIBS": extra_libs,
                "PBA_MODE": "",
                "FORCE_BASIC_RC": force_basic_rc,
                "SI": si,
            },
            log_path,
        )

        mode = "full"
        if idx == 0 or dist_res_cache is None:
            with log_path.open("a", encoding="utf-8") as lf, contextlib.redirect_stdout(lf):
                res.annotate_timing_report(str(rpt), str(spef), str(ann), lib_path=str(lib_path))
            dist_res_cache = lib.extract_dist_res_cache(ann)
        else:
            _, queries, _ = lib.parse_report(rpt)
            miss = sum(1 for q in queries if lib.lookup_dist_res(dist_res_cache, q) == (None, None))
            if miss:
                mode = f"fallback_full_miss_{miss}"
                with log_path.open("a", encoding="utf-8") as lf, contextlib.redirect_stdout(lf):
                    print(f"[{now()}] cache_miss={miss}, fallback full annotate: {rpt}")
                    res.annotate_timing_report(str(rpt), str(spef), str(ann), lib_path=str(lib_path))
                dist_res_cache.update(lib.extract_dist_res_cache(ann))
            else:
                mode = "fast_cached"
                lib.apply_fast_annotation(rpt, ann, dist_res_cache, lib_path)

        na_tokens, na_lines = lib.count_na(ann)
        summary.append(
            {
                "rc": rc,
                "corner": stem,
                "voltage": volt_token(db.name),
                "mode": mode,
                "na_tokens": na_tokens,
                "na_lines": na_lines,
                "annotated": str(ann),
                "report": str(rpt),
                "log": str(log_path),
            }
        )
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(f"[CHECK] rc={rc} {stem} mode={mode} na_tokens={na_tokens} na_lines={na_lines} ann={ann}\n")

    return {"group": rc, "summary": summary, "log": str(log_path)}


def parse_args():
    dataset_root = DATA_ROOT / "inputs" / "14nm_ccs"
    pdk_root = dataset_root / "lib_db_pdk"

    p = argparse.ArgumentParser(
        description="14nm_ccs voltage-sweep strict fixed-path batch across 3 SPEF RC corners (Cmax/Cnom/Cmin), cached annotation."
    )
    p.add_argument("--design", default="BoomCoreV3")
    p.add_argument("--top", default="BoomCore")
    p.add_argument("--spef-prefix", default="boomcorev3_14nm",
                   help="SPEF/SDC/Verilog basename prefix, e.g. boomcorev3_14nm")
    p.add_argument("--mode", choices=["setup", "hold"], default="setup",
                   help="setup -> DELAY_TYPE=max, hold -> DELAY_TYPE=min")
    p.add_argument("--si", action="store_true",
                   help="Enable SI/crosstalk (si_enable_analysis true): uses *_si.tcl and tags out-dir with _si.")
    p.add_argument("--rc-corners", default="Cmax,Cnom,Cmin",
                   help="Comma list of SPEF RC corners to sweep.")
    p.add_argument("--ref-rc", default="Cnom",
                   help="RC corner used for reference path extraction.")
    p.add_argument("--verilog", default=None)
    p.add_argument("--sdc", default=None)
    p.add_argument("--spef-root", default=None,
                   help="Dir containing the .spef files (default: <design>/deliver).")
    p.add_argument("--spef-name-format", default=DEFAULT_SPEF_NAME_FORMAT,
                   help="SPEF filename pattern with {prefix}/{rc}/{temp} placeholders.")
    p.add_argument("--spef-temp", default="25",
                   help="Temperature token substituted into --spef-name-format.")
    p.add_argument("--db-root", default=str(pdk_root / "db"))
    p.add_argument("--lib-root", default=str(pdk_root / "lib"))
    p.add_argument("--out-dir", default=None)
    p.add_argument("--ref-db", default=str(pdk_root / "db" / "saed14rvt_tt0p8v25c_ccs_vendor.db"))
    p.add_argument("--max-paths", type=int, default=3000)
    p.add_argument("--nworst", type=int, default=1)
    p.add_argument("--n-through", type=int, default=8)
    p.add_argument(
        "--max-fanout",
        type=int,
        default=0,
        help="Skip strict fixed paths containing data-path net fanout greater than this value (0 = disabled).",
    )
    p.add_argument("--max-workers", type=int, default=3)
    p.add_argument("--extra-libs", default="")
    p.add_argument(
        "--force-basic-rc",
        action="store_true",
        help="Set PrimeTime rc_driver_model_mode/rc_receiver_model_mode to basic for ref and corner runs.",
    )
    p.add_argument(
        "--reuse-strict-tcl", default=None,
        help="Skip ref topK extraction and reuse an existing strict fixed-path tcl "
             "(use to share one path definition across temperature runs).")
    p.add_argument(
        "--edge-aware-fixed-paths",
        action="store_true",
        help="Generate strict fixed paths with reference rise/fall directions and use edge-specific report_timing constraints.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    dataset_root = DATA_ROOT / "inputs" / "14nm_ccs"
    deliver_root = dataset_root / "processors" / args.design / "deliver"

    verilog = Path(args.verilog) if args.verilog else deliver_root / f"{args.spef_prefix}_icc2.v"
    sdc = Path(args.sdc) if args.sdc else deliver_root / f"{args.spef_prefix}.sdc"
    spef_root = Path(args.spef_root) if args.spef_root else deliver_root
    db_root = Path(args.db_root)
    lib_root = Path(args.lib_root)
    delay_type = "max" if args.mode == "setup" else "min"
    force_basic_rc = "1" if args.force_basic_rc else "0"

    # SI on/off 는 동일 TCL 에 SI 환경변수로 전달된다.
    ref_topk_tcl = SCRIPT_DIR / "tcl" / "run_ref_topk.tcl"
    corner_tcl = SCRIPT_DIR / "tcl" / "run_corner_fixed.tcl"
    si_tag = "_si_keepcc" if args.si else ""
    si_env = "1" if args.si else "0"
    make_strict_tcl = LOCAL_SCRIPT_DIR / "make_strict_fixed_paths_tcl.py"

    out = Path(args.out_dir) if args.out_dir else DATA_ROOT / "results" / (
        f"14nm_ccs_{args.design}_{args.mode}{si_tag}_vsweep{args.max_paths}_strict_cached_parallel"
    )
    ref_db = Path(args.ref_db)
    ref_lib = lib_for_db(ref_db, lib_root)
    rc_list = [rc.strip() for rc in args.rc_corners.split(",") if rc.strip()]
    for rc in rc_list + [args.ref_rc]:
        if rc not in RC_CORNERS:
            raise SystemExit(f"unknown RC corner: {rc} (expected one of {RC_CORNERS})")
    ref_spef = spef_for_rc(spef_root, args.spef_prefix, args.ref_rc,
                           args.spef_name_format, args.spef_temp)

    required = [
        verilog, sdc, spef_root, db_root, lib_root, ref_db, ref_lib, ref_spef,
        ref_topk_tcl,
        corner_tcl,
        make_strict_tcl,
    ]
    for path in required:
        if not Path(path).exists():
            raise SystemExit(f"missing file: {path}")

    # SI pre-flight: --si 인데 SPEF 에 coupling cap 이 없으면 crosstalk 가 무의미하므로 즉시 중단.
    if args.si:
        spefs_to_check = {str(ref_spef)}
        for rc in rc_list:
            spefs_to_check.add(str(spef_for_rc(spef_root, args.spef_prefix, rc,
                                               args.spef_name_format, args.spef_temp)))
        for sp in sorted(spefs_to_check):
            if not spef_has_coupling(Path(sp)):
                raise SystemExit(
                    "SI requested (--si) but SPEF has NO coupling capacitance "
                    f"(grounded/reduced SPEF): {sp}\n"
                    "  -> crosstalk analysis would produce non-SI-equivalent results.\n"
                    "  -> Re-extract a coupled SPEF (StarRC COUPLING_CAP: YES) at the same path, "
                    "or drop --si."
                )
        print("[SI pre-flight] coupling caps present in all SPEFs -> SI analysis is meaningful.")

    out.mkdir(parents=True, exist_ok=True)
    report_dir = out / "reports"
    ann_dir = out / "annotated"
    log_dir = out / "logs"
    for d in (report_dir, ann_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)
    run_log = out / "run.log"

    ref_topk_rpt = out / f"ref_{args.mode}_top{args.max_paths}_{ref_db.stem}_{args.ref_rc}.rpt"
    fixed_tcl = out / f"{args.spef_prefix}_{args.mode}_fixed_paths_{args.max_paths}.tcl"
    ref_fixed_rpt = report_dir / f"{ref_db.stem}_{args.ref_rc}_fixed.rpt"
    ref_fixed_ann = ann_dir / f"{ref_db.stem}_{args.ref_rc}_fixed_annotated.txt"
    strict_fixed_tcl = out / f"{args.spef_prefix}_{args.mode}_strict_fixed_paths_{args.max_paths}.tcl"

    python_env = dict(os.environ)
    python_env["PYTHONPATH"] = (
        str(SCRIPT_DIR)
        if not python_env.get("PYTHONPATH")
        else f"{SCRIPT_DIR}:{python_env['PYTHONPATH']}"
    )

    with run_log.open("w", encoding="utf-8") as log:
        log.write(f"[START] {now()}\n")
        log.write("[MODE] 14nm_ccs_voltage_sweep_strict_cached_parallel\n")
        log.write(f"[DESIGN] {args.design}\n")
        log.write(f"[STA_MODE] {args.mode} (DELAY_TYPE={delay_type})\n")
        log.write(f"[RC_CORNERS] {rc_list}  [REF_RC] {args.ref_rc}\n")
        log.write(f"[TOP] {args.top}\n")
        log.write(f"[VERILOG] {verilog}\n")
        log.write(f"[SDC] {sdc}\n")
        log.write(f"[SPEF_ROOT] {spef_root}\n")
        log.write(f"[SPEF_PREFIX] {args.spef_prefix}\n")
        log.write(f"[DB_ROOT] {db_root}\n")
        log.write(f"[LIB_ROOT] {lib_root}\n")
        log.write(f"[REF_DB] {ref_db}\n")
        log.write(f"[REF_SPEF] {ref_spef}\n")
        log.write(f"[SI] {'ON' if args.si else 'OFF'}\n")
        log.write(f"[FORCE_BASIC_RC] {force_basic_rc}\n")
        log.write(f"[EDGE_AWARE_FIXED_PATHS] {1 if args.edge_aware_fixed_paths else 0}\n")
        log.write(f"[REF_TOPK_TCL] {ref_topk_tcl}\n")
        log.write(f"[CORNER_TCL] {corner_tcl}\n")
        log.write(f"[MAX_FANOUT] {args.max_fanout}\n")
        log.write("[FANOUT_SCOPE] data\n")

    if args.reuse_strict_tcl:
        strict_fixed_tcl = Path(args.reuse_strict_tcl)
        if not strict_fixed_tcl.exists():
            raise SystemExit(f"missing --reuse-strict-tcl file: {strict_fixed_tcl}")
        with run_log.open("a", encoding="utf-8") as lf:
            lf.write(f"[REUSE_STRICT_TCL] {strict_fixed_tcl}\n")
    else:
        # 1) ref topK 경로 추출
        lib.run_pt(
            ref_topk_tcl,
            {
                "TOP": args.top, "VERILOG": verilog, "SDC": sdc, "SPEF": ref_spef,
                "LIB_DB": ref_db, "OUT_RPT": ref_topk_rpt,
                "MAX_PATHS": str(args.max_paths), "NWORST": str(args.nworst),
                "SLACK_TH": "100.0", "DELAY_TYPE": delay_type,
                "EXTRA_LIBS": args.extra_libs, "PBA_MODE": "",
                "FORCE_BASIC_RC": force_basic_rc, "SI": si_env,
            },
            run_log,
        )

        # 2) fixed-path tcl
        with run_log.open("a", encoding="utf-8") as lf:
            emitted, skipped, total_blocks = lib.write_fixed_tcl_from_ref_report(
                ref_topk_rpt, fixed_tcl, args.n_through, args.max_paths,
            )
            lf.write(f"[FIXED_TCL] emitted={emitted} skipped={skipped} total_blocks={total_blocks} out={fixed_tcl}\n")

        # ref 재타이밍 + annotate
        lib.run_pt(
            corner_tcl,
            {
                "TOP": args.top, "VERILOG": verilog, "SDC": sdc, "SPEF": ref_spef,
                "LIB_DB": ref_db, "FIXED_TCL": fixed_tcl, "OUT_RPT": ref_fixed_rpt,
                "DELAY_TYPE": delay_type, "EXTRA_LIBS": args.extra_libs, "PBA_MODE": "",
                "FORCE_BASIC_RC": force_basic_rc, "SI": si_env,
            },
            run_log,
        )
        with run_log.open("a", encoding="utf-8") as lf, contextlib.redirect_stdout(lf):
            res.annotate_timing_report(str(ref_fixed_rpt), str(ref_spef), str(ref_fixed_ann), lib_path=str(ref_lib))

        # strict fixed-path tcl (SPEF 무관, 경로 정의이므로 3개 RC 코너가 공유)
        reject_csv = out / f"{args.spef_prefix}_{args.mode}_strict_fixed_paths_rejected_fanout.csv"
        cmd = [
            sys.executable, str(make_strict_tcl),
            "--ref-annotated", str(ref_fixed_ann),
            "--out", str(strict_fixed_tcl),
            "--limit", str(args.max_paths),
        ]
        if args.max_fanout:
            cmd.extend([
                "--max-fanout", str(args.max_fanout),
                "--fanout-scope", "data",
                "--reject-csv", str(reject_csv),
            ])
        if args.edge_aware_fixed_paths:
            cmd.append("--edge-aware")
        with run_log.open("a", encoding="utf-8") as lf:
            subprocess.run(cmd, check=True, stdout=lf, stderr=subprocess.STDOUT, env=python_env)

    # 3) 전압 17종 (정렬: 전압 숫자 기준)
    corners = sorted(db_root.glob("*.db"), key=lambda p: (volt_value(p.name), p.name))
    db_paths = [str(p) for p in corners]

    with run_log.open("a", encoding="utf-8") as log:
        log.write(f"[STRICT_FIXED_TCL] {strict_fixed_tcl}\n")
        log.write(f"[CORNERS] count={len(db_paths)}\n")
        for db in db_paths:
            log.write(f"  - {db}\n")

    workers = min(args.max_workers, len(rc_list))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        future_map = {}
        for rc in rc_list:
            spef = spef_for_rc(spef_root, args.spef_prefix, rc,
                               args.spef_name_format, args.spef_temp)
            fut = ex.submit(
                process_group,
                rc, str(spef), db_paths, str(strict_fixed_tcl),
                str(report_dir), str(ann_dir), str(log_dir),
                args.top, str(verilog), str(sdc), str(lib_root),
                delay_type, args.extra_libs, str(corner_tcl), force_basic_rc,
                si_env,
            )
            future_map[fut] = rc

        for fut in as_completed(future_map):
            rc = future_map[fut]
            try:
                result = fut.result()
                results.append(result)
                with run_log.open("a", encoding="utf-8") as log:
                    log.write(f"[DONE_GROUP] rc={rc} log={result['log']}\n")
                    for item in result["summary"]:
                        log.write(
                            f"[RESULT] rc={item['rc']} {item['corner']} v={item['voltage']} "
                            f"mode={item['mode']} na_tokens={item['na_tokens']} na_lines={item['na_lines']} "
                            f"ann={item['annotated']}\n"
                        )
            except Exception:
                tb = traceback.format_exc()
                with run_log.open("a", encoding="utf-8") as log:
                    log.write(f"[FAIL_GROUP] rc={rc}\n{tb}\n")
                raise

    summary_path = out / "summary.txt"
    total = 0
    with summary_path.open("w", encoding="utf-8") as sf:
        sf.write(f"OUT_DIR={out}\n")
        sf.write(f"DESIGN={args.design}\n")
        sf.write(f"STA_MODE={args.mode} DELAY_TYPE={delay_type}\n")
        sf.write(f"SI={'ON' if args.si else 'OFF'}\n")
        sf.write(f"FORCE_BASIC_RC={force_basic_rc}\n")
        sf.write(f"RC_CORNERS={rc_list} REF_RC={args.ref_rc}\n")
        sf.write(f"WORKERS={workers}\n")
        sf.write(f"TOP={args.top}\n")
        sf.write(f"VERILOG={verilog}\n")
        sf.write(f"SDC={sdc}\n")
        sf.write(f"SPEF_ROOT={spef_root}\n")
        sf.write(f"DB_ROOT={db_root}\n")
        sf.write(f"LIB_ROOT={lib_root}\n")
        sf.write(f"REF_DB={ref_db}\n")
        sf.write(f"REF_SPEF={ref_spef}\n")
        sf.write(f"STRICT_FIXED_TCL={strict_fixed_tcl}\n")
        sf.write(f"MAX_FANOUT={args.max_fanout}\n")
        sf.write(f"EDGE_AWARE_FIXED_PATHS={1 if args.edge_aware_fixed_paths else 0}\n")
        sf.write("FANOUT_SCOPE=data\n")
        for result in sorted(results, key=lambda x: x["group"]):
            sf.write(f"GROUP(rc)={result['group']} log={result['log']}\n")
            for row in sorted(result["summary"], key=lambda r: r["corner"]):
                total += 1
                sf.write(
                    f"{row['rc']} {row['corner']} v={row['voltage']} mode={row['mode']} "
                    f"na_tokens={row['na_tokens']} na_lines={row['na_lines']} ann={row['annotated']}\n"
                )
        sf.write(f"TOTAL={total}\n")

    with run_log.open("a", encoding="utf-8") as log:
        log.write(f"[END] {now()}\n")

    print(f"OUT_DIR={out}")
    print(f"STA_MODE={args.mode} (DELAY_TYPE={delay_type})")
    print(f"RC_CORNERS={rc_list}")
    print(f"WORKERS={workers}")
    print(f"STRICT_FIXED_TCL={strict_fixed_tcl}")
    print(f"SUMMARY={summary_path}")


if __name__ == "__main__":
    main()
