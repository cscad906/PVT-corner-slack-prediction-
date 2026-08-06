#!/usr/bin/env python3
# 위반/위험 경로 전수 추출 러너 (SAED14 RVT CCS, PrimeTime).
#
# run_sweep.py 와의 차이 (추출 정책):
#   - run_sweep.py : ref 코너 한 곳에서 top-N(nworst/max_paths) worst 경로를 뽑아
#                    그 경로를 "박제"하고 전 코너에서 동일 경로를 재측정한다.
#   - 이 도구      : hidden corner 를 제외한 "모든 측정 코너 각각"에서 slack 이
#                    임계값(TH) 미만인 path 를 전부 뽑아 union 한다. 코너마다 critical
#                    path 가 다를 수 있으므로, 코너별 추출 결과를 (startpoint,endpoint)
#                    페어 단위로 합집합한 것이 최종 산출물이다.
#
# 코너 축 = "전압 N종 @ 고정 온도" (--db-root 의 *.db 가 전압 코너 목록).
# SPEF 는 RC 코너(Cmax/Cnom/Cmin)로 구분되며, 같은 RC 코너면 전압에 무관하게
# 동일 SPEF 1개를 공유한다. 따라서 측정 코너 = (RC × 전압) 조합이다.
#
# 각 (RC, 전압) 조합마다 기존 tcl/run_ref_topk.tcl 을 pt_shell 로 실행한다.
# 그 tcl 은 report_timing -nworst NWORST -max_paths MAX_PATHS
# -slack_lesser_than SLACK_TH 로 "slack < TH 인 path 전부"를 리포트한다.
#
# SI: --si 를 주면 동일 TCL 이 SI=1 환경변수로 PrimeTime SI 분석
#     (si_enable_analysis + read_parasitics -keep_capacitive_coupling)을 켠다.
# PT 환경: pt_shell 이 PATH 에 없으면 PT_SOURCE 환경변수에 셋업 스크립트 지정.
import argparse
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import os
import traceback

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import ptann_lib as lib
# run_sweep.py 의 전압 토큰 파싱/SPEF·LIB 해석/coupling 검사를 그대로 재사용
# (규약 일치 보장; 코드 중복 방지). run_sweep 는 import 시 부작용이 없다(main 가드).
from run_sweep import (
    RC_CORNERS,
    DEFAULT_SPEF_NAME_FORMAT,
    volt_token,
    volt_value,
    spef_for_rc,
    lib_for_db,
    spef_has_coupling,
)


def now():
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------ rpt 파싱
# report_timing -path_type full_clock_expanded 출력에서 (start,end,slack,arrival)을 뽑는다.
STARTPOINT_RE = re.compile(r"^\s*Startpoint:\s*(\S+)")
ENDPOINT_RE = re.compile(r"^\s*Endpoint:\s*(\S+)")
ARRIVAL_RE = re.compile(r"^\s*data arrival time\s+(-?\d+(?:\.\d+)?)")
SLACK_RE = re.compile(r"^\s*slack\s*\((VIOLATED|MET)\)\s+(-?\d+(?:\.\d+)?)")


def _finalize_path_chain(cur):
    """path 블록의 데이터-핀 체인(through 시퀀스)을 붙이고 signature 를 만든다.

    코너 간 "같은 물리 경로" 식별 기준(signature):
      (startpoint, endpoint, 데이터 경로의 핀 튜플)
    같은 FF 쌍(start,end) 사이에도 through 가 다른 별개 물리 경로가 있으므로,
    (start,end) 만으로는 경로 정체성이 부족하다. through 시퀀스까지 넣어 구분한다.

    핀 체인 추출은 기존 파이프라인과 동일 로직(ptann_lib.extract_data_pin_chain)을
    재사용한다 -- run_ref_topk.tcl 리포트 포맷(full_clock_expanded, -input_pins -nets ...)
    을 그 함수가 이미 파싱하며, 여기서 뽑은 through 로 만든 FIXED_PATHS 가 곧
    run_sweep --reuse-strict-tcl 이 소비하는 형식과 일치한다.

    체인 추출 실패(포트 시작/끝 등 FF-Q..FF-D 가 아닌 경로)면 chain_ok=False 로 두고
    sig 를 (start,end,()) 로 둔다 -> 같은 (start,end) 의 no-chain 경로들은 한 행으로
    합쳐지며 FIXED_PATHS tcl 에는 실리지 않는다(기존 파이프라인도 이런 경로는 skip).
    """
    block = {
        "startpoint": cur["startpoint"],
        "endpoint": cur["endpoint"],
        "lines": cur.pop("_lines"),
    }
    # 핀 선택 규칙은 extract_data_pin_chain 과 동일하고, 각 핀의 전이 방향(r/f)을
    # 함께 받는다(edge-aware FIXED_PATHS emission 용). 방향은 sig 에 넣지 않는다 --
    # 경로 정체성은 핀 체인이고, 방향은 그 경로를 PT 에서 다시 집을 때의 제약이다.
    pin_dirs = lib.extract_data_pin_chain_with_dirs(block)
    pins = [p for p, _ in pin_dirs]
    if len(pins) >= 2:
        cur["chain_ok"] = True
        cur["from_pin"] = pins[0]
        cur["to_pin"] = pins[-1]
        cur["through"] = tuple(pins[1:-1])
        cur["pins"] = tuple(pins)
        cur["dirs"] = tuple(d for _, d in pin_dirs)
        cur["sig"] = (cur["startpoint"], cur["endpoint"], tuple(pins))
    else:
        cur["chain_ok"] = False
        cur["from_pin"] = None
        cur["to_pin"] = None
        cur["through"] = ()
        cur["pins"] = ()
        cur["dirs"] = ()
        cur["sig"] = (cur["startpoint"], cur["endpoint"], ())


def parse_violation_rpt(rpt_path: Path):
    """report_timing 리포트 1개를 파싱해 path 레코드 리스트를 반환.

    각 레코드: {startpoint, endpoint, slack, arrival, status,
               from_pin, to_pin, through, pins, sig, chain_ok}
    - status: 'VIOLATED' | 'MET'
    - 한 path 블록은 'Startpoint:' 로 시작하고 'slack (...)' 라인에서 완결된다.
    - 파일 등장 순서(= report_timing 정렬 순서, slack 오름차순)를 유지한다.
    - sig = 코너 간 물리 경로 매칭 키(_finalize_path_chain 참조).
    """
    records = []
    cur = None
    with rpt_path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m_start = STARTPOINT_RE.match(line)
            if m_start:
                # 이전 블록이 slack 없이 새 Startpoint 를 만나면(비정상) 버린다.
                cur = {
                    "startpoint": m_start.group(1),
                    "endpoint": None,
                    "arrival": None,
                    "slack": None,
                    "status": None,
                    "_lines": [],
                }
                continue
            if cur is None:
                continue
            m_end = ENDPOINT_RE.match(line)
            if m_end and cur["endpoint"] is None:
                cur["endpoint"] = m_end.group(1)
                continue
            m_arr = ARRIVAL_RE.match(line)
            if m_arr:
                cur["arrival"] = float(m_arr.group(1))
                cur["_lines"].append(line)
                continue
            m_slack = SLACK_RE.match(line)
            if m_slack:
                cur["status"] = m_slack.group(1)
                cur["slack"] = float(m_slack.group(2))
                if cur["endpoint"] is not None:
                    _finalize_path_chain(cur)
                    records.append(cur)
                cur = None
                continue
            # 데이터-핀 체인 파싱용으로 본문 라인을 모아둔다.
            cur["_lines"].append(line)
    return records


# ------------------------------------------------------------ 코너 1개 처리 (worker)
def process_corner(
    rc: str,
    vtag: str,
    spef: str,
    db: str,
    lib_root: str,
    top: str,
    verilog: str,
    sdc: str,
    ref_topk_tcl: str,
    out_rpt: str,
    log_path: str,
    delay_type: str,
    nworst: int,
    max_paths: int,
    slack_th: float,
    extra_libs: str,
    force_basic_rc: str,
    si: str,
):
    """(RC, 전압) 코너 1개에서 slack<TH path 전부를 리포트하고 파싱한다.

    ProcessPoolExecutor 로 코너들을 병렬 실행한다(= 동시 PT 라이선스 소비 수).
    """
    db = Path(db)
    out_rpt = Path(out_rpt)
    out_rpt.parent.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path = lib_for_db(db, Path(lib_root))

    lib.run_pt(
        Path(ref_topk_tcl),
        {
            "TOP": top,
            "VERILOG": verilog,
            "SDC": sdc,
            "SPEF": spef,
            "LIB_DB": str(db),
            "OUT_RPT": str(out_rpt),
            "MAX_PATHS": str(max_paths),
            "NWORST": str(nworst),
            "SLACK_TH": f"{slack_th}",
            "DELAY_TYPE": delay_type,
            "EXTRA_LIBS": extra_libs,
            "PBA_MODE": "",
            "FORCE_BASIC_RC": force_basic_rc,
            "SI": si,
        },
        log_path,
    )

    records = parse_violation_rpt(out_rpt)
    truncated = len(records) >= max_paths
    with log_path.open("a", encoding="utf-8") as lf:
        lf.write(
            f"[CHECK] rc={rc} corner={db.stem} vtag={vtag} paths={len(records)} "
            f"violating={sum(1 for r in records if r['slack'] < 0.0)} "
            f"max_paths={max_paths} truncated={truncated}\n"
        )
    return {
        "rc": rc,
        "vtag": vtag,
        "corner": db.stem,
        "lib": str(lib_path),
        "rpt": str(out_rpt),
        "records": records,
        "truncated": truncated,
    }


# ------------------------------------------------------------ nworst 충분성 자가진단
def endpoint_nworst_diag(records, nworst: int, slack_th: float):
    """endpoint 단위로 nworst 상한이 부족한지 판정한다.

    report_timing -nworst N 은 endpoint 마다 최대 N 개 path 를 리포트한다. 어떤
    endpoint 가 N 개를 꽉 채웠고(마지막 순위 rank==N 의 path 도 여전히 slack<TH),
    그 아래 순위에 TH 안쪽 후보가 더 있을 수 있으므로 "possibly truncated" 로 본다.
    N 개 미만이면 그 endpoint 는 TH 안쪽 path 를 모두 소진한 것이므로 truncated 아님.

    (이는 코너 전체 상한인 --max-paths TRUNCATED 와는 별개 항목: 이건 endpoint 단위
     nworst 상한이다.)

    반환: endpoint -> {n, worst_rank_slack, truncated}
    """
    by_ep = {}
    for r in records:
        by_ep.setdefault(r["endpoint"], []).append(r["slack"])
    diag = {}
    for ep, slks in by_ep.items():
        n = len(slks)
        # rank==n (마지막 순위) = 그 endpoint 에서 가장 덜 나쁜(=slack 최대) path
        worst_rank_slack = max(slks)
        truncated = (n >= nworst) and (worst_rank_slack < slack_th)
        diag[ep] = {"n": n, "worst_rank_slack": worst_rank_slack, "truncated": truncated}
    return diag


# ------------------------------------------------------------ CSV/summary 작성
def corner_col(rc: str, vtag: str) -> str:
    """union_paths.csv 의 코너별 slack 와이드 컬럼 헤더."""
    return f"slack__{rc}__{vtag}"


def write_per_corner_csv(csv_path: Path, corner_results, corner_order, diags):
    """코너별 원본(모든 occurrence). 같은 (start,end)가 nworst 로 여러 번 나오면
    코너 내부에서 slack 오름차순 rank(1..k)를 부여하고 전부 기록한다.
    endpoint_truncated = 그 endpoint 가 nworst 상한에 걸려 잘렸을 수 있는지(자가진단)."""
    import csv

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["corner", "rc", "vtag", "startpoint", "endpoint", "slack",
                    "arrival", "status", "rank", "endpoint_truncated"])
        for key in corner_order:
            res = corner_results[key]
            rc, vtag = res["rc"], res["vtag"]
            diag = diags[key]
            # (start,end) 페어별 occurrence 를 slack 오름차순으로 rank
            pair_seen = {}
            # 파일 순서(slack 오름차순)를 유지하되, 페어별 등장 카운트로 rank
            for r in res["records"]:
                pair = (r["startpoint"], r["endpoint"])
                rank = pair_seen.get(pair, 0) + 1
                pair_seen[pair] = rank
                ep_trunc = 1 if diag.get(r["endpoint"], {}).get("truncated") else 0
                w.writerow([
                    res["corner"], rc, vtag,
                    r["startpoint"], r["endpoint"],
                    f"{r['slack']:.4f}",
                    "" if r["arrival"] is None else f"{r['arrival']:.4f}",
                    r["status"], rank, ep_trunc,
                ])


def write_truncated_endpoints_csv(csv_path: Path, corner_results, corner_order, diags, nworst):
    """nworst 상한에 걸렸을 수 있는 endpoint 만 별도로 모은다(자가진단 상세)."""
    import csv

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rc", "vtag", "corner", "endpoint", "n_paths",
                    "worst_rank_slack", "nworst"])
        for key in corner_order:
            res = corner_results[key]
            diag = diags[key]
            for ep, d in sorted(diag.items()):
                if not d["truncated"]:
                    continue
                w.writerow([res["rc"], res["vtag"], res["corner"], ep,
                            d["n"], f"{d['worst_rank_slack']:.4f}", nworst])


def build_union(corner_results, corner_order, slack_th):
    """(start,end) 페어 단위 union. 코너별 worst(최소) slack 만 취한다."""
    union = {}  # pair -> {corner_col: worst_slack}
    for key in corner_order:
        res = corner_results[key]
        col = corner_col(res["rc"], res["vtag"])
        for r in res["records"]:
            pair = (r["startpoint"], r["endpoint"])
            entry = union.setdefault(pair, {})
            s = r["slack"]
            if col not in entry or s < entry[col]:
                entry[col] = s
    rows = []
    for pair, cols in union.items():
        slacks = cols  # corner_col -> worst slack in that corner
        n_viol = sum(1 for v in slacks.values() if v < 0.0)
        n_risky = sum(1 for v in slacks.values() if v < slack_th)
        worst_col = min(slacks, key=lambda c: slacks[c])
        worst_slack = slacks[worst_col]
        rows.append({
            "startpoint": pair[0],
            "endpoint": pair[1],
            "n_corners_violating": n_viol,
            "n_corners_risky": n_risky,
            "worst_slack": worst_slack,
            "worst_corner": worst_col,
            "slacks": slacks,
        })
    # worst_slack 오름차순(가장 나쁜 경로가 위로)
    rows.sort(key=lambda x: (x["worst_slack"], x["startpoint"], x["endpoint"]))
    return rows


def write_union_csv(csv_path: Path, union_rows, corner_results, corner_order):
    import csv

    corner_cols = [corner_col(corner_results[k]["rc"], corner_results[k]["vtag"]) for k in corner_order]
    header = [
        "startpoint", "endpoint",
        "n_corners_violating", "n_corners_risky",
        "worst_slack", "worst_corner",
    ] + corner_cols
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in union_rows:
            base = [
                row["startpoint"], row["endpoint"],
                row["n_corners_violating"], row["n_corners_risky"],
                f"{row['worst_slack']:.4f}", row["worst_corner"],
            ]
            slacks = row["slacks"]
            wide = [(f"{slacks[c]:.4f}" if c in slacks else "") for c in corner_cols]
            w.writerow(base + wide)


# ------------------------------------------------------- path-level union
def build_union_bypath(corner_results, corner_order, slack_th):
    """signature(=start,end,through 시퀀스) 단위 union.

    pair 단위 build_union 과 달리, 같은 (start,end) 라도 through 가 다르면 별도 행이다
    (별개 물리 경로). 코너 간 같은 signature = 같은 물리 경로로 매칭한다.
    코너별로 worst(최소) slack 을 취하고, worst corner 의 핀 체인을 FIXED_PATHS tcl
    emission 용으로 보관한다(요구사항: through 는 worst corner rpt 에서 뽑는다).
    """
    union = {}  # sig -> entry
    for key in corner_order:
        res = corner_results[key]
        col = corner_col(res["rc"], res["vtag"])
        for r in res["records"]:
            sig = r["sig"]
            e = union.setdefault(sig, {
                "startpoint": r["startpoint"],
                "endpoint": r["endpoint"],
                "n_through": len(r["through"]),
                "chain_ok": r["chain_ok"],
                "cols": {},          # corner_col -> worst slack
                "from_by_col": {},
                "to_by_col": {},
                "through_by_col": {},
                "dirs_by_col": {},
            })
            s = r["slack"]
            if col not in e["cols"] or s < e["cols"][col]:
                e["cols"][col] = s
                e["from_by_col"][col] = r["from_pin"]
                e["to_by_col"][col] = r["to_pin"]
                e["through_by_col"][col] = r["through"]
                e["dirs_by_col"][col] = r.get("dirs", ())
    rows = []
    for sig, e in union.items():
        cols = e["cols"]
        n_viol = sum(1 for v in cols.values() if v < 0.0)
        n_risky = sum(1 for v in cols.values() if v < slack_th)
        worst_col = min(cols, key=lambda c: cols[c])
        rows.append({
            "sig": sig,
            "startpoint": e["startpoint"],
            "endpoint": e["endpoint"],
            "n_through": e["n_through"],
            "chain_ok": e["chain_ok"],
            "n_corners_violating": n_viol,
            "n_corners_risky": n_risky,
            "worst_slack": cols[worst_col],
            "worst_corner": worst_col,
            "slacks": cols,
            "worst_from": e["from_by_col"][worst_col],
            "worst_to": e["to_by_col"][worst_col],
            "worst_through": e["through_by_col"][worst_col],
            "worst_dirs": e["dirs_by_col"].get(worst_col, ()),
        })
    # worst_slack 오름차순 후 path_idx(1..N) 부여
    rows.sort(key=lambda x: (x["worst_slack"], x["startpoint"], x["endpoint"], x["sig"]))
    for i, row in enumerate(rows, start=1):
        row["path_idx"] = i
    return rows


def write_union_bypath_csv(csv_path: Path, bypath_rows, corner_results, corner_order):
    import csv

    corner_cols = [corner_col(corner_results[k]["rc"], corner_results[k]["vtag"]) for k in corner_order]
    header = [
        "path_idx", "startpoint", "endpoint", "n_through",
        "n_corners_violating", "n_corners_risky",
        "worst_slack", "worst_corner",
    ] + corner_cols
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in bypath_rows:
            base = [
                row["path_idx"], row["startpoint"], row["endpoint"], row["n_through"],
                row["n_corners_violating"], row["n_corners_risky"],
                f"{row['worst_slack']:.4f}", row["worst_corner"],
            ]
            slacks = row["slacks"]
            wide = [(f"{slacks[c]:.4f}" if c in slacks else "") for c in corner_cols]
            w.writerow(base + wide)


def write_fixed_paths_tcl(tcl_path: Path, bypath_rows, n_through: int, edge_aware: bool):
    """path-level union 을 FIXED_PATHS 형식으로 쓴다 (make_strict 와 동일 등급).

    형식은 make_strict_fixed_paths_tcl.py 와 동일:
      legacy:     {path_key {from_pin} {to_pin} { {thr1} {thr2} ... }}
      edge-aware: {path_key {from_pin} {to_pin} { {thr1} ... } {from_dir thr_dir... to_dir}}
    -> tcl/report_fixed_paths.tcl 이 소비하고 run_sweep --reuse-strict-tcl 이 받는다.

    **through 는 기본적으로 worst corner 핀 체인의 내부 핀 전부(pins[1:-1])** 다 --
    make_strict_fixed_paths_tcl.py 와 같은 "strict" 정책. union signature 는 전체 핀
    체인인데 -through 제약만 일부라면, 같은 (start,end) 를 공유하는 쌍둥이 경로들이
    PT 에서 같은 경로로 수렴해(-max_paths 1 -sort_by slack) 한쪽이 중복 측정되고
    다른 쪽이 통째로 누락된다. 전체 체인을 걸면 그 붕괴가 원천 차단된다.
    n_through > 0 을 명시하면 예전처럼 샘플링한다(하위 호환; 권장하지 않음).

    edge_aware=True 면 각 핀의 전이 방향(r/f)을 5번째 필드로 함께 실어
    -rise_from/-fall_through 로 엣지까지 고정한다. 코너(전압)가 바뀔 때 같은
    핀 체인의 rise/fall 중 worst 가 뒤바뀌어 같은 idx 에 다른 물리 측정이 들어가는
    것을 막는다. 방향을 모르는 핀이 하나라도 있으면 그 경로만 legacy 로 떨어진다.

    체인이 없는 경로(chain_ok=False)는 기존 파이프라인처럼 skip 한다.
    """
    emitted = 0
    skipped = 0
    edge_emitted = 0
    edge_fallback = 0
    with tcl_path.open("w", encoding="utf-8") as f:
        f.write("# Auto-generated fixed paths (from violation-path union)\n")
        f.write("# through = all internal data pins of the worst-corner chain (strict)\n")
        if edge_aware:
            f.write("# Edge-aware mode: each entry includes an edge list aligned to {from, through..., to}\n")
        f.write("set FIXED_PATHS {\n")
        for row in bypath_rows:
            if not row["chain_ok"]:
                skipped += 1
                continue
            from_pin = row["worst_from"]
            to_pin = row["worst_to"]
            pins = [from_pin] + list(row["worst_through"]) + [to_pin]
            if n_through > 0:
                through_pins = lib.sample_through_pins(pins, n_through)
            else:
                through_pins = pins[1:-1]
            path_key = "{}->{}#{}".format(row["startpoint"], row["endpoint"], row["path_idx"])
            thr_list = " ".join("{{{}}}".format(pin) for pin in through_pins)

            dirs = list(row.get("worst_dirs", ()))
            # 엣지 리스트는 {from, through..., to} 와 길이가 정확히 맞아야 tcl 이 쓴다
            # (report_fixed_paths.tcl 의 use_edges 조건). 샘플링을 켠 경우 through 가
            # 부분집합이 되어 정렬이 깨지므로 edge-aware 는 전체 체인일 때만 적용한다.
            use_edges = (
                edge_aware
                and n_through <= 0
                and len(dirs) == len(pins)
                and all(d in ("r", "f") for d in dirs)
            )
            if use_edges:
                edge_list = " ".join("{{{}}}".format(d) for d in dirs)
                f.write("  {{{{{}}} {{{}}} {{{}}} {{{}}} {{{}}}}}\n".format(
                    path_key, from_pin, to_pin, thr_list, edge_list))
                edge_emitted += 1
            else:
                if edge_aware:
                    edge_fallback += 1
                f.write("  {{{{{}}} {{{}}} {{{}}} {{{}}}}}\n".format(
                    path_key, from_pin, to_pin, thr_list))
            emitted += 1
        f.write("}\n\n")
        if edge_aware:
            f.write("# each entry: {path_key {from_pin} {to_pin} { {through1} ... } {from_dir through_dir... to_dir}}\n")
        else:
            f.write("# each entry: {path_key {from_pin} {to_pin} { {through1} {through2} ... }}\n")
    return emitted, skipped, edge_emitted, edge_fallback


# ------------------------------------------------------------ argparse
def parse_args():
    p = argparse.ArgumentParser(
        description="hidden corner 를 제외한 모든 측정 코너에서 slack<TH path 를 전수 추출해 union 한다 "
                    "(run_sweep.py 의 top-N 추출과 다른 정책).",
    )
    # --- run_sweep.py 와 동일 관례 ---
    p.add_argument("--design", default="BoomCoreV3")
    p.add_argument("--top", default="BoomCore")
    p.add_argument("--spef-prefix", default="boomcorev3_14nm",
                   help="SPEF/SDC/Verilog basename prefix, 예: boomcorev3_14nm")
    p.add_argument("--mode", choices=["setup", "hold"], default="setup",
                   help="setup -> DELAY_TYPE=max, hold -> DELAY_TYPE=min")
    p.add_argument("--si", action="store_true",
                   help="PrimeTime SI/crosstalk 활성화(si_enable_analysis true, coupling 유지). "
                        "coupling 없는 SPEF 면 pre-flight 에서 중단.")
    p.add_argument("--verilog", default=None)
    p.add_argument("--sdc", default=None)
    p.add_argument("--spef-root", default=None,
                   help=".spef 파일이 있는 디렉토리")
    p.add_argument("--spef-name-format", default=DEFAULT_SPEF_NAME_FORMAT,
                   help="SPEF 파일명 패턴 {prefix}/{rc}/{temp} placeholder")
    p.add_argument("--spef-temp", default="25",
                   help="--spef-name-format 의 {temp} 토큰")
    p.add_argument("--db-root", default=None,
                   help="전압 코너 .db 들이 있는 디렉토리(측정 코너 목록의 원천)")
    p.add_argument("--lib-root", default=None,
                   help="db 와 짝을 이루는 .lib 디렉토리")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--extra-libs", default="",
                   help="매크로/IO 등 추가 라이브러리(link_path 에 append)")
    # --- 이 도구의 새 인자 ---
    p.add_argument("--slack-threshold", type=float, default=0.05,
                   help="slack < TH 인 path 만 추출. **단위는 SDC 시간 단위**(통상 ns) -- "
                        "기본 0.05 = 50ps 마진, 즉 '진짜 위반(slack<0) + 위반 위험' 을 함께 뽑는다. "
                        "0.0 을 주면 violation 만. TH 밖의 path 는 리포트에 아예 안 남아 "
                        "사후 복구가 안 되므로(재실행 필요) 넉넉히 주는 편이 안전하다. "
                        "위반/위험 구분은 union CSV 의 n_corners_violating/n_corners_risky 로 한다.")
    p.add_argument("--nworst", type=int, default=None,
                   help="endpoint 당 최대 리포트 path 수. 기본은 mode 분기(setup 3 / hold 10).")
    p.add_argument("--max-paths", type=int, default=50000,
                   help="코너당 리포트 path 안전 상한. 리포트 path 수가 이 값과 같으면 TRUNCATED 경고.")
    p.add_argument("--rc-corners", default="Cmax,Cnom,Cmin",
                   help="스윕할 SPEF RC 코너 콤마 목록.")
    p.add_argument("--exclude-vtags", default="",
                   help="제외할 전압 태그 콤마 목록(hidden corner). 예: 0p75,0p795")
    p.add_argument("--max-workers", type=int, default=3,
                   help="병렬 실행 코너 수(= 동시 PT 라이선스 소비 수).")
    p.add_argument("--force-basic-rc", action="store_true",
                   help="rc_driver/receiver_model_mode 를 basic 으로 강제.")
    # --- path-level(경로 단위) 옵션 ---
    p.add_argument("--emit-fixed-paths-tcl", action="store_true",
                   help="path-level union 전체를 기존 FIXED_PATHS 형식 tcl 로 내보낸다 "
                        "(run_sweep --reuse-strict-tcl 이 소비). "
                        "<out-dir>/<design>_<mode>_violation_fixed_paths_<N>.tcl")
    p.add_argument("--fixed-through-count", type=int, default=0,
                   help="--emit-fixed-paths-tcl 의 경로당 through 핀 수. "
                        "기본 0 = 내부 데이터 핀 **전부**(make_strict 와 동일한 strict 정책, 권장). "
                        "양수를 주면 그 개수만 균등 샘플링한다(하위 호환) -- 같은 (start,end) 의 "
                        "쌍둥이 경로가 PT 에서 같은 경로로 수렴해 중복/누락이 생길 수 있으므로 권장하지 않는다. "
                        "샘플링을 켜면 --edge-aware-fixed-paths 는 자동 무시된다.")
    p.add_argument("--edge-aware-fixed-paths", action="store_true",
                   help="--emit-fixed-paths-tcl 에서 각 핀의 전이 방향(r/f)을 함께 실어 "
                        "-rise_from/-fall_through 로 엣지까지 고정한다 "
                        "(run_sweep 의 동명 옵션과 같은 효과; 전압 간 rise/fall worst 뒤바뀜 방지). "
                        "전체 체인(--fixed-through-count 0)일 때만 적용된다.")
    return p.parse_args()


def main():
    args = parse_args()

    if args.db_root is None or args.lib_root is None:
        raise SystemExit("--db-root 와 --lib-root 는 필수입니다.")
    if args.verilog is None or args.sdc is None or args.spef_root is None:
        raise SystemExit("--verilog / --sdc / --spef-root 는 필수입니다.")
    if args.out_dir is None:
        raise SystemExit("--out-dir 는 필수입니다.")

    verilog = Path(args.verilog)
    sdc = Path(args.sdc)
    spef_root = Path(args.spef_root)
    db_root = Path(args.db_root)
    lib_root = Path(args.lib_root)
    out = Path(args.out_dir)
    delay_type = "max" if args.mode == "setup" else "min"
    force_basic_rc = "1" if args.force_basic_rc else "0"
    si_env = "1" if args.si else "0"

    # nworst 기본: setup 3 / hold 10 (hidden corner 에서 endpoint 내 순위 교체 대비; hold 값은 시작점 - 자가진단으로 조정)
    if args.nworst is None:
        nworst = 3 if args.mode == "setup" else 10
    else:
        nworst = args.nworst

    ref_topk_tcl = SCRIPT_DIR / "tcl" / "run_ref_topk.tcl"

    rc_list = [rc.strip() for rc in args.rc_corners.split(",") if rc.strip()]
    for rc in rc_list:
        if rc not in RC_CORNERS:
            raise SystemExit(f"unknown RC corner: {rc} (expected one of {RC_CORNERS})")

    exclude = {v.strip() for v in args.exclude_vtags.split(",") if v.strip()}

    required = [verilog, sdc, spef_root, db_root, lib_root, ref_topk_tcl]
    for path in required:
        if not Path(path).exists():
            raise SystemExit(f"missing file: {path}")

    # 전압 코너 스캔 + hidden 제외 + 전압 정렬
    all_dbs = sorted(db_root.glob("*.db"), key=lambda p: (volt_value(p.name), p.name))
    if not all_dbs:
        raise SystemExit(f"no *.db under --db-root: {db_root}")
    corner_dbs = []
    excluded = []
    seen_vtags = {}
    temp_re = re.compile(r"\d+p\d+v(m?\d+)c")
    for db in all_dbs:
        vt = volt_token(db.name)
        if vt in exclude:
            excluded.append((db.stem, vt))
            continue
        # 같은 전압 태그의 db 가 2개면(대개 온도 혼재) 코너 키 (RC,vtag) 가 충돌해
        # 한쪽이 조용히 덮어써진다 -> 명시적으로 중단. 온도 축은 db-root 를 분리해서 돌린다.
        if vt in seen_vtags:
            raise SystemExit(
                f"--db-root 에 같은 전압 태그({vt})의 db 가 2개 이상 있습니다:\n"
                f"  {seen_vtags[vt]}\n  {db.name}\n"
                "온도(또는 스타일) 혼재로 보입니다. 이 도구의 코너 키는 (RC x 전압)이므로\n"
                "온도별로 db-root 를 분리해 각각 실행하세요."
            )
        seen_vtags[vt] = db.name
        # db 이름의 온도 토큰과 --spef-temp 불일치 경고 (예: v125c db + 25C SPEF)
        m_temp = temp_re.search(db.name)
        if m_temp and m_temp.group(1) != str(args.spef_temp):
            print(f"WARNING: db 온도 토큰({m_temp.group(1)}) != --spef-temp({args.spef_temp}): "
                  f"{db.name} — db 와 SPEF 온도가 어긋나면 결과가 물리적으로 비일관됩니다.",
                  file=sys.stderr)
        corner_dbs.append((db, vt))
    if not corner_dbs:
        raise SystemExit("모든 전압 코너가 --exclude-vtags 로 제외되었습니다.")

    # SPEF 경로 확인
    spefs = {}
    for rc in rc_list:
        spefs[rc] = spef_for_rc(spef_root, args.spef_prefix, rc,
                                args.spef_name_format, args.spef_temp)

    # SI pre-flight: coupling cap 없는 SPEF 로 SI 돌리면 무의미하므로 중단.
    if args.si:
        for rc in rc_list:
            sp = spefs[rc]
            if not spef_has_coupling(Path(sp)):
                raise SystemExit(
                    "SI requested (--si) but SPEF has NO coupling capacitance "
                    f"(grounded/reduced SPEF): {sp}\n"
                    "  -> crosstalk analysis would produce non-SI-equivalent results.\n"
                    "  -> Re-extract a coupled SPEF (StarRC COUPLING_CAP: YES), or drop --si."
                )
        print("[SI pre-flight] coupling caps present in all SPEFs -> SI analysis is meaningful.")

    out.mkdir(parents=True, exist_ok=True)
    rpt_dir = out / "rpts"
    csv_dir = out / "csv"
    log_dir = out / "logs"
    for d in (rpt_dir, csv_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)
    run_log = out / "run.log"

    with run_log.open("w", encoding="utf-8") as log:
        log.write(f"[START] {now()}\n")
        log.write("[MODE] violation_path_union_extraction\n")
        log.write(f"[DESIGN] {args.design}\n")
        log.write(f"[STA_MODE] {args.mode} (DELAY_TYPE={delay_type})\n")
        log.write(f"[SLACK_TH] {args.slack_threshold}\n")
        log.write(f"[NWORST] {nworst} [MAX_PATHS] {args.max_paths}\n")
        log.write(f"[RC_CORNERS] {rc_list}\n")
        log.write(f"[SI] {'ON' if args.si else 'OFF'}\n")
        log.write(f"[FORCE_BASIC_RC] {force_basic_rc}\n")
        log.write(f"[EXCLUDE_VTAGS] {sorted(exclude)}\n")
        log.write(f"[EXCLUDED_CORNERS] {excluded}\n")
        log.write(f"[TOP] {args.top}\n")
        log.write(f"[VERILOG] {verilog}\n")
        log.write(f"[SDC] {sdc}\n")
        log.write(f"[SPEF_ROOT] {spef_root}\n")
        log.write(f"[DB_ROOT] {db_root}\n")
        log.write(f"[LIB_ROOT] {lib_root}\n")
        log.write(f"[REF_TOPK_TCL] {ref_topk_tcl}\n")
        log.write(f"[INCLUDED_CORNERS] count={len(corner_dbs)}\n")
        for db, vt in corner_dbs:
            log.write(f"  - vtag={vt} {db.name}\n")

    # (RC × 전압) 조합 = 측정 코너 목록. corner_order 는 결정적 순서(RC, 전압).
    jobs = []
    corner_order = []  # (rc, vtag) 키 순서
    for rc in rc_list:
        for db, vt in corner_dbs:
            key = (rc, vt)
            corner_order.append(key)
            out_rpt = rpt_dir / rc / f"{db.stem}.rpt"
            log_path = log_dir / f"{rc}.log"
            jobs.append((key, rc, vt, str(spefs[rc]), str(db), out_rpt, log_path))

    workers = max(1, min(args.max_workers, len(jobs)))
    corner_results = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        fut_map = {}
        for key, rc, vt, spef, db, out_rpt, log_path in jobs:
            fut = ex.submit(
                process_corner,
                rc, vt, spef, db, str(lib_root),
                args.top, str(verilog), str(sdc),
                str(ref_topk_tcl), str(out_rpt), str(log_path),
                delay_type, nworst, args.max_paths, args.slack_threshold,
                args.extra_libs, force_basic_rc, si_env,
            )
            fut_map[fut] = key
        failed_corners = {}  # key -> 짧은 에러 요약. 한 코너 실패(라이선스 등)가 전체를 죽이지 않게.
        for fut in as_completed(fut_map):
            key = fut_map[fut]
            try:
                corner_results[key] = fut.result()
                with run_log.open("a", encoding="utf-8") as log:
                    r = corner_results[key]
                    log.write(
                        f"[DONE] rc={r['rc']} vtag={r['vtag']} corner={r['corner']} "
                        f"paths={len(r['records'])} truncated={r['truncated']}\n"
                    )
            except Exception as e:
                tb = traceback.format_exc()
                failed_corners[key] = f"{type(e).__name__}: {e}"
                with run_log.open("a", encoding="utf-8") as log:
                    log.write(f"[FAIL] key={key}\n{tb}\n")
                print(f"WARNING: corner FAILED rc={key[0]} vtag={key[1]} -> {failed_corners[key]} "
                      f"(계속 진행, 상세: {run_log})", file=sys.stderr)

    # 실패 코너는 이후 집계에서 제외 (union 은 성공 코너 기준의 부분 결과가 됨)
    corner_order = [k for k in corner_order if k in corner_results]
    if not corner_order:
        raise SystemExit("모든 코너가 실패했습니다. logs/ 와 run.log 를 확인하세요.")

    # nworst 충분성 자가진단(endpoint 단위)
    diags = {
        key: endpoint_nworst_diag(corner_results[key]["records"], nworst, args.slack_threshold)
        for key in corner_order
    }
    corner_trunc_eps = {
        key: sum(1 for d in diags[key].values() if d["truncated"]) for key in corner_order
    }
    total_trunc_eps = sum(corner_trunc_eps.values())

    # CSV + union
    per_corner_csv = csv_dir / "per_corner.csv"
    union_csv = csv_dir / "union_paths.csv"
    trunc_ep_csv = csv_dir / "truncated_endpoints.csv"
    write_per_corner_csv(per_corner_csv, corner_results, corner_order, diags)
    write_truncated_endpoints_csv(trunc_ep_csv, corner_results, corner_order, diags, nworst)
    union_rows = build_union(corner_results, corner_order, args.slack_threshold)
    write_union_csv(union_csv, union_rows, corner_results, corner_order)

    # path-level(경로 단위) union: 같은 (start,end)라도 through 가 다르면 별도 행.
    union_bypath_csv = csv_dir / "union_paths_bypath.csv"
    bypath_rows = build_union_bypath(corner_results, corner_order, args.slack_threshold)
    write_union_bypath_csv(union_bypath_csv, bypath_rows, corner_results, corner_order)

    # path-level 진단: 매칭·체인 상태
    n_bypath = len(bypath_rows)
    n_nochain = sum(1 for r in bypath_rows if not r["chain_ok"])
    n_multi_corner = sum(1 for r in bypath_rows if len(r["slacks"]) >= 2)
    max_corner_span = max((len(r["slacks"]) for r in bypath_rows), default=0)
    # 같은 (start,end)에 through 다른 경로가 몇 페어에서 나오는지
    sig_per_pair = {}
    for r in bypath_rows:
        sig_per_pair.setdefault((r["startpoint"], r["endpoint"]), 0)
        sig_per_pair[(r["startpoint"], r["endpoint"])] += 1
    n_pairs_multipath = sum(1 for c in sig_per_pair.values() if c >= 2)

    # (선택) FIXED_PATHS tcl emission
    fixed_tcl_path = None
    fixed_emitted = fixed_skipped = 0
    fixed_edge_emitted = fixed_edge_fallback = 0
    if args.emit_fixed_paths_tcl:
        n_emit = sum(1 for r in bypath_rows if r["chain_ok"])
        fixed_tcl_path = out / f"{args.design}_{args.mode}_violation_fixed_paths_{n_emit}.tcl"
        fixed_emitted, fixed_skipped, fixed_edge_emitted, fixed_edge_fallback = write_fixed_paths_tcl(
            fixed_tcl_path, bypath_rows, args.fixed_through_count,
            args.edge_aware_fixed_paths)
        if args.fixed_through_count > 0:
            print(f"[WARN] --fixed-through-count={args.fixed_through_count} (샘플링 모드): "
                  "같은 (start,end) 의 쌍둥이 경로가 PT 에서 같은 경로로 수렴해 "
                  "중복 측정/누락이 발생할 수 있다. 0(전체 체인) 권장.")
        if args.edge_aware_fixed_paths and fixed_edge_fallback:
            print(f"[WARN] edge-aware: {fixed_edge_fallback} 경로는 방향 정보가 불완전해 "
                  "legacy(엣지 없음) 포맷으로 내보냈다.")

    # summary
    summary_path = out / "summary.txt"
    with summary_path.open("w", encoding="utf-8") as sf:
        sf.write("# 위반/위험 경로 전수 추출 (extract_violation_paths.py)\n")
        sf.write(f"OUT_DIR={out}\n")
        sf.write(f"DESIGN={args.design}\n")
        sf.write(f"STA_MODE={args.mode} DELAY_TYPE={delay_type}\n")
        sf.write(f"SLACK_THRESHOLD={args.slack_threshold}  "
                 f"(SDC 시간 단위; 0.0=violation only, +margin=violation+risky. 기본 0.05=50ps@ns)\n")
        sf.write(f"NWORST={nworst}  MAX_PATHS={args.max_paths}\n")
        sf.write(f"SI={'ON' if args.si else 'OFF'}  FORCE_BASIC_RC={force_basic_rc}\n")
        sf.write(f"RC_CORNERS={rc_list}\n")
        sf.write(f"EXCLUDE_VTAGS(hidden)={sorted(exclude)}\n")
        sf.write(f"EXCLUDED_CORNERS={excluded}\n")
        sf.write(f"INCLUDED_VTAGS={[vt for _, vt in corner_dbs]}\n")
        sf.write(f"MEASURED_CORNERS(RC x V)={len(corner_order)}\n")
        sf.write(f"TOP={args.top}\n")
        sf.write(f"VERILOG={verilog}\n")
        sf.write(f"SDC={sdc}\n")
        sf.write(f"SPEF_ROOT={spef_root}\n")
        sf.write(f"DB_ROOT={db_root}\n")
        sf.write(f"LIB_ROOT={lib_root}\n")
        sf.write(f"PER_CORNER_CSV={per_corner_csv}\n")
        sf.write(f"UNION_CSV(pair)={union_csv}\n")
        sf.write(f"UNION_BYPATH_CSV(path)={union_bypath_csv}\n")
        if fixed_tcl_path is not None:
            sf.write(f"FIXED_PATHS_TCL={fixed_tcl_path}  (emitted={fixed_emitted} skipped_nochain={fixed_skipped})\n")
        sf.write(f"TRUNCATED_ENDPOINTS_CSV={trunc_ep_csv}\n")
        sf.write("\n# per-corner (paths=all occurrences, pairs=distinct start->end,\n")
        sf.write("#   nworst_trunc_eps=nworst 상한에 걸렸을 수 있는 endpoint 수[자가진단],\n")
        sf.write("#   max_rank=실제 관측된 endpoint 내 최대 순위 -- nworst 보다 작으면 nworst 를 내려도 됨)\n")
        any_trunc = False
        max_rank_overall = 0
        for key in corner_order:
            r = corner_results[key]
            recs = r["records"]
            pairs = {(x["startpoint"], x["endpoint"]) for x in recs}
            viol_pairs = {(x["startpoint"], x["endpoint"]) for x in recs if x["slack"] < 0.0}
            # endpoint 당 실제 관측된 최대 path 수(=최대 순위). diags 의 n 재사용.
            max_rank = max((d["n"] for d in diags[key].values()), default=0)
            max_rank_overall = max(max_rank_overall, max_rank)
            trunc = r["truncated"]
            any_trunc = any_trunc or trunc
            warn = "  *** TRUNCATED?(paths==max_paths) ***" if trunc else ""
            sf.write(
                f"rc={r['rc']} vtag={r['vtag']} corner={r['corner']} "
                f"paths={len(recs)} pairs={len(pairs)} "
                f"violating_pairs={len(viol_pairs)} risky_pairs={len(pairs)} "
                f"nworst_trunc_eps={corner_trunc_eps[key]} max_rank={max_rank}{warn}\n"
            )
        sf.write(f"\nUNION_PAIRS={len(union_rows)}\n")
        union_viol = sum(1 for row in union_rows if row["n_corners_violating"] > 0)
        sf.write(f"UNION_PAIRS_VIOLATING(>=1 corner slack<0)={union_viol}\n")
        # path-level union 요약 (pair <= path 관계 성립해야 정상)
        sf.write(f"\n# path-level union (signature=start,end,through 시퀀스)\n")
        sf.write(f"UNION_PATHS_BYPATH={n_bypath}   (>= UNION_PAIRS={len(union_rows)} 이어야 정상)\n")
        sf.write(f"PAIRS_WITH_MULTIPLE_PATHS={n_pairs_multipath}   "
                 f"(같은 start,end 인데 through 다른 경로가 있는 페어 수)\n")
        sf.write(f"PATHS_MATCHED_ACROSS_CORNERS(>=2 corner)={n_multi_corner}  "
                 f"MAX_CORNER_SPAN={max_corner_span}\n")
        if n_nochain:
            sf.write(f"PATHS_NO_DATA_CHAIN(sig=start,end,() 로 병합, tcl 미포함)={n_nochain}\n")
        if fixed_tcl_path is not None:
            through_policy = ("ALL_INTERNAL_PINS(strict)" if args.fixed_through_count <= 0
                              else f"SAMPLED({args.fixed_through_count})")
            sf.write(f"FIXED_PATHS_TCL_EMITTED={fixed_emitted} SKIPPED_NOCHAIN={fixed_skipped} "
                     f"THROUGH_POLICY={through_policy}\n")
            sf.write(f"FIXED_PATHS_TCL_EDGE_AWARE={1 if args.edge_aware_fixed_paths else 0} "
                     f"EDGE_EMITTED={fixed_edge_emitted} EDGE_FALLBACK_LEGACY={fixed_edge_fallback}\n")
        sf.write(f"\n# nworst 충분성 자가진단 (endpoint 단위, --max-paths 상한과는 별개)\n")
        sf.write(f"NWORST={nworst}\n")
        sf.write(f"NWORST_TRUNCATED_ENDPOINTS_TOTAL={total_trunc_eps}\n")
        sf.write(f"MAX_RANK_OBSERVED={max_rank_overall}\n")
        if total_trunc_eps > 0:
            sf.write(
                f"INFO: endpoint {total_trunc_eps}개가 nworst({nworst}) 깊이 상한까지 채워짐.\n"
                "      위반이 많은 데이터에서는 정상이다. nworst 는 endpoint 당 상위 후보만 담는\n"
                "      '고정 정책값'이다 -- 올리면 --max-paths 예산을 소수 endpoint 가 깊이로 잠식해\n"
                "      endpoint 커버리지(폭)가 줄어든다. endpoint 별 '전체' 열거가 꼭 필요한\n"
                "      경우에만 --max-paths 와 함께 올릴 것.\n"
            )
        elif max_rank_overall < nworst:
            sf.write(
                f"INFO: nworst 상한에 걸린 endpoint 없음. 실제 최대 순위={max_rank_overall} < nworst={nworst}.\n"
            )
        else:
            sf.write("INFO: nworst 상한에 걸린 endpoint 없음.\n")
        if any_trunc:
            sf.write("\nWARNING: 일부 코너에서 path 수 == max_paths -> 잘렸을 수 있음. --max-paths 를 키우세요.\n")
        if failed_corners:
            sf.write(f"\n# 실패 코너 ({len(failed_corners)}개) -- 이 union 은 성공 코너만의 부분 결과\n")
            for key, msg in sorted(failed_corners.items()):
                sf.write(f"FAILED rc={key[0]} vtag={key[1]}: {msg}\n")
            sf.write("logs/<RC>.log 와 run.log 에서 원인 확인 후 재실행하세요 (라이선스 부족이면 --max-workers 축소).\n")

    with run_log.open("a", encoding="utf-8") as log:
        log.write(f"[END] {now()}\n")

    print(f"OUT_DIR={out}")
    print(f"STA_MODE={args.mode} (DELAY_TYPE={delay_type})  SLACK_TH={args.slack_threshold}")
    print(f"NWORST={nworst}  RC_CORNERS={rc_list}  MEASURED_CORNERS={len(corner_order)}")
    print(f"EXCLUDED(hidden)={excluded}")
    print(f"PER_CORNER_CSV={per_corner_csv}")
    print(f"UNION_CSV(pair)={union_csv}  UNION_PAIRS={len(union_rows)}")
    print(f"UNION_BYPATH_CSV(path)={union_bypath_csv}  UNION_PATHS={n_bypath} "
          f"(pairs_with_multipath={n_pairs_multipath}, matched_across_corners={n_multi_corner})")
    if fixed_tcl_path is not None:
        print(f"FIXED_PATHS_TCL={fixed_tcl_path}  emitted={fixed_emitted} skipped_nochain={fixed_skipped}")
    print(f"NWORST_TRUNCATED_ENDPOINTS_TOTAL={total_trunc_eps} (nworst={nworst})")
    for key in corner_order:
        if corner_trunc_eps[key]:
            r = corner_results[key]
            print(f"  rc={r['rc']} vtag={r['vtag']} nworst_trunc_eps={corner_trunc_eps[key]}")
    print(f"MAX_RANK_OBSERVED={max_rank_overall}")
    if total_trunc_eps > 0:
        print(f"INFO: endpoint {total_trunc_eps}개가 nworst({nworst}) 깊이 상한 도달 — 위반 많은 데이터에선 정상. "
              f"nworst 는 고정 정책값(endpoint 당 상위 후보)이며 올리면 endpoint 커버리지가 줄어든다 "
              f"(상세: {trunc_ep_csv})")
    else:
        print("INFO: nworst 상한에 걸린 endpoint 없음.")
    if failed_corners:
        print(f"WARNING: 실패 코너 {len(failed_corners)}개 -> union 은 부분 결과. summary 의 FAILED 목록 확인.")
    print(f"SUMMARY={summary_path}")
    if failed_corners:
        sys.exit(2)


if __name__ == "__main__":
    main()
