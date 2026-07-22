#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path


MARKER_RE = re.compile(r"^### FIXED_PATH idx=(?P<idx>\d+) key=(?P<key>.*)$")
VOLT_RE = re.compile(r"tt0p(?P<tag>[0-9]+)v(?:m?\d+)c")
PIN_ROW_RE = re.compile(
    r"^\s*(?P<point>.+?)\s+\((?P<cell>SAEDRVT14_[^)]+)\)\s+<-\s+"
    r"(?P<trans>[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s+"
    r"(?P<incr>[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s+&?\s+"
    r"(?P<path>[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s+(?P<dir>[rf])\s*$",
    re.IGNORECASE,
)


def voltage_from_name(name: str) -> float:
    if "tt0p8v25c_ccs_vendor" in name:
        return 0.800
    m = VOLT_RE.search(name)
    if not m:
        raise ValueError(f"Cannot parse voltage from {name}")
    return float("0." + m.group("tag"))


def split_inst_pin(point: str):
    if "/" not in point:
        return point.strip(), ""
    inst, pin = point.strip().rsplit("/", 1)
    return inst, pin


def parse_report(path: Path):
    paths = {}
    cur = None

    def finish():
        if cur is not None:
            paths[cur["idx"]] = cur

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = MARKER_RE.match(line)
            if m:
                finish()
                cur = {
                    "idx": int(m.group("idx")),
                    "key": m.group("key"),
                    "arrival": None,
                    "slack": None,
                    "pin_rows": [],
                }
                continue
            if cur is None:
                continue

            if "data arrival time" in line:
                nums = re.findall(r"[-+]?\d+\.\d+", line)
                if nums and cur["arrival"] is None:
                    cur["arrival"] = float(nums[-1])
                continue
            if "slack" in line:
                nums = re.findall(r"[-+]?\d+\.\d+", line)
                if nums:
                    cur["slack"] = float(nums[-1])
                continue

            pm = PIN_ROW_RE.match(line)
            if pm:
                inst, pin = split_inst_pin(pm.group("point"))
                cur["pin_rows"].append(
                    {
                        "point": pm.group("point").strip(),
                        "inst": inst,
                        "pin": pin,
                        "cell": pm.group("cell"),
                        "trans": float(pm.group("trans")),
                        "incr": float(pm.group("incr")),
                        "path": float(pm.group("path")),
                        "dir": pm.group("dir").lower(),
                    }
                )
    finish()
    return paths


def arc_rows(path_data):
    rows = []
    pins = path_data["pin_rows"]
    seq = 0
    for i in range(1, len(pins)):
        prev = pins[i - 1]
        cur = pins[i]
        if prev["inst"] != cur["inst"]:
            continue
        if prev["pin"] == cur["pin"]:
            continue
        seq += 1
        rows.append(
            {
                "arc_seq": seq,
                "inst": cur["inst"],
                "cell": cur["cell"],
                "from_pin": prev["pin"],
                "to_pin": cur["pin"],
                "arc": f"{prev['pin']}->{cur['pin']}",
                "input_dir": prev["dir"],
                "output_dir": cur["dir"],
                "input_transition": prev["trans"],
                "output_transition": cur["trans"],
                "cell_incr": cur["incr"],
            }
        )
    return rows


def arc_identity(arc):
    return (arc["arc_seq"], arc["inst"], arc["cell"], arc["from_pin"], arc["to_pin"])


def arc_edge(arc):
    return (arc["input_dir"], arc["output_dir"])


def compare_arcs(arcs0, arcs1):
    if len(arcs0) != len(arcs1):
        return False, "arc_count", min(len(arcs0), len(arcs1)), None, None

    for a0, a1 in zip(arcs0, arcs1):
        if arc_identity(a0) != arc_identity(a1):
            return False, "arc_identity", a0["arc_seq"], a0, a1
        if arc_edge(a0) != arc_edge(a1):
            return False, "edge_direction", a0["arc_seq"], a0, a1
    return True, "", "", None, None


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def main():
    ap = argparse.ArgumentParser(
        description="Check whether fixed-path reports keep the same stage identity and rise/fall edge directions across voltages."
    )
    ap.add_argument("--reports-dir", required=True, type=Path)
    ap.add_argument("--outdir", required=True, type=Path)
    ap.add_argument("--abs-tol-ns", type=float, default=1e-6)
    ap.add_argument("--spike-frac", type=float, default=0.001)
    args = ap.parse_args()

    report_files = sorted(args.reports_dir.glob("*_fixed.rpt"), key=lambda p: voltage_from_name(p.name))
    if len(report_files) < 2:
        raise SystemExit(f"Need at least two *_fixed.rpt files under {args.reports_dir}")

    parsed = [(voltage_from_name(p.name), p, parse_report(p)) for p in report_files]
    all_ids = sorted(set().union(*(set(paths) for _, _, paths in parsed)))

    pair_rows = []
    mismatch_rows = []
    positive_delta_rows = []
    ref_mismatch_rows = []

    checks = 0
    comparable = 0
    edge_consistent_pairs = 0
    mismatch_pairs = 0
    positive_delta = 0
    positive_delta_edge_consistent = 0
    positive_delta_edge_mismatch = 0
    spike_delta = 0
    spike_delta_edge_consistent = 0
    spike_delta_edge_mismatch = 0

    for (v0, rpt0, paths0), (v1, rpt1, paths1) in zip(parsed, parsed[1:]):
        for pid in all_ids:
            p0 = paths0.get(pid)
            p1 = paths1.get(pid)
            if not p0 or not p1:
                continue
            checks += 1
            arcs0 = arc_rows(p0)
            arcs1 = arc_rows(p1)
            ok, reason, seq, a0, a1 = compare_arcs(arcs0, arcs1)
            if p0["arrival"] is not None and p1["arrival"] is not None:
                comparable += 1
                delta = p1["arrival"] - p0["arrival"]
                tol = max(args.abs_tol_ns, abs(p0["arrival"]) * args.spike_frac)
                is_positive = delta > args.abs_tol_ns
                is_spike = delta > tol
                if is_positive:
                    positive_delta += 1
                    if ok:
                        positive_delta_edge_consistent += 1
                    else:
                        positive_delta_edge_mismatch += 1
                    positive_delta_rows.append(
                        {
                            "path_id": pid,
                            "path_key": p0["key"],
                            "from_voltage": f"{v0:.3f}",
                            "to_voltage": f"{v1:.3f}",
                            "arrival_from_ns": p0["arrival"],
                            "arrival_to_ns": p1["arrival"],
                            "arrival_delta_ns": delta,
                            "edge_consistent": int(ok),
                            "mismatch_reason": reason,
                            "first_mismatch_arc_seq": seq,
                        }
                    )
                if is_spike:
                    spike_delta += 1
                    if ok:
                        spike_delta_edge_consistent += 1
                    else:
                        spike_delta_edge_mismatch += 1
            else:
                delta = ""

            if ok:
                edge_consistent_pairs += 1
            else:
                mismatch_pairs += 1
                row = {
                    "path_id": pid,
                    "path_key": p0["key"],
                    "from_voltage": f"{v0:.3f}",
                    "to_voltage": f"{v1:.3f}",
                    "mismatch_reason": reason,
                    "first_mismatch_arc_seq": seq,
                    "arrival_delta_ns": delta,
                }
                if a0:
                    row.update(
                        {
                            "from_inst": a0["inst"],
                            "from_cell": a0["cell"],
                            "from_arc": a0["arc"],
                            "from_input_dir": a0["input_dir"],
                            "from_output_dir": a0["output_dir"],
                        }
                    )
                if a1:
                    row.update(
                        {
                            "to_inst": a1["inst"],
                            "to_cell": a1["cell"],
                            "to_arc": a1["arc"],
                            "to_input_dir": a1["input_dir"],
                            "to_output_dir": a1["output_dir"],
                        }
                    )
                mismatch_rows.append(row)

            pair_rows.append(
                {
                    "path_id": pid,
                    "path_key": p0["key"],
                    "from_voltage": f"{v0:.3f}",
                    "to_voltage": f"{v1:.3f}",
                    "edge_consistent": int(ok),
                    "mismatch_reason": reason,
                    "first_mismatch_arc_seq": seq,
                    "arrival_from_ns": p0["arrival"],
                    "arrival_to_ns": p1["arrival"],
                    "arrival_delta_ns": delta,
                    "arc_count_from": len(arcs0),
                    "arc_count_to": len(arcs1),
                    "from_report": rpt0.name,
                    "to_report": rpt1.name,
                }
            )

    ref_v, ref_rpt, ref_paths = parsed[-1]
    for v, rpt, paths in parsed[:-1]:
        for pid in all_ids:
            pref = ref_paths.get(pid)
            cur = paths.get(pid)
            if not pref or not cur:
                continue
            ok, reason, seq, a_ref, a_cur = compare_arcs(arc_rows(pref), arc_rows(cur))
            if ok:
                continue
            row = {
                "path_id": pid,
                "path_key": pref["key"],
                "reference_voltage": f"{ref_v:.3f}",
                "compare_voltage": f"{v:.3f}",
                "mismatch_reason": reason,
                "first_mismatch_arc_seq": seq,
                "reference_report": ref_rpt.name,
                "compare_report": rpt.name,
            }
            if a_ref:
                row.update(
                    {
                        "reference_inst": a_ref["inst"],
                        "reference_cell": a_ref["cell"],
                        "reference_arc": a_ref["arc"],
                        "reference_input_dir": a_ref["input_dir"],
                        "reference_output_dir": a_ref["output_dir"],
                    }
                )
            if a_cur:
                row.update(
                    {
                        "compare_inst": a_cur["inst"],
                        "compare_cell": a_cur["cell"],
                        "compare_arc": a_cur["arc"],
                        "compare_input_dir": a_cur["input_dir"],
                        "compare_output_dir": a_cur["output_dir"],
                    }
                )
            ref_mismatch_rows.append(row)

    out = args.outdir
    write_csv(
        out / "edge_consistency_by_adjacent_voltage.csv",
        pair_rows,
        [
            "path_id",
            "path_key",
            "from_voltage",
            "to_voltage",
            "edge_consistent",
            "mismatch_reason",
            "first_mismatch_arc_seq",
            "arrival_from_ns",
            "arrival_to_ns",
            "arrival_delta_ns",
            "arc_count_from",
            "arc_count_to",
            "from_report",
            "to_report",
        ],
    )
    write_csv(
        out / "edge_mismatch_details.csv",
        mismatch_rows,
        [
            "path_id",
            "path_key",
            "from_voltage",
            "to_voltage",
            "mismatch_reason",
            "first_mismatch_arc_seq",
            "arrival_delta_ns",
            "from_inst",
            "from_cell",
            "from_arc",
            "from_input_dir",
            "from_output_dir",
            "to_inst",
            "to_cell",
            "to_arc",
            "to_input_dir",
            "to_output_dir",
        ],
    )
    write_csv(
        out / "positive_delta_edge_breakdown.csv",
        positive_delta_rows,
        [
            "path_id",
            "path_key",
            "from_voltage",
            "to_voltage",
            "arrival_from_ns",
            "arrival_to_ns",
            "arrival_delta_ns",
            "edge_consistent",
            "mismatch_reason",
            "first_mismatch_arc_seq",
        ],
    )
    write_csv(
        out / "edge_mismatch_vs_reference.csv",
        ref_mismatch_rows,
        [
            "path_id",
            "path_key",
            "reference_voltage",
            "compare_voltage",
            "mismatch_reason",
            "first_mismatch_arc_seq",
            "reference_inst",
            "reference_cell",
            "reference_arc",
            "reference_input_dir",
            "reference_output_dir",
            "compare_inst",
            "compare_cell",
            "compare_arc",
            "compare_input_dir",
            "compare_output_dir",
            "reference_report",
            "compare_report",
        ],
    )

    summary = {
        "reports": len(report_files),
        "paths": len(all_ids),
        "adjacent_path_checks": checks,
        "adjacent_arrival_comparable_checks": comparable,
        "edge_consistent_pairs": edge_consistent_pairs,
        "edge_mismatch_pairs": mismatch_pairs,
        "edge_mismatch_pair_pct": (mismatch_pairs / checks * 100.0) if checks else 0.0,
        "positive_arrival_delta_checks": positive_delta,
        "positive_arrival_delta_edge_consistent": positive_delta_edge_consistent,
        "positive_arrival_delta_edge_mismatch": positive_delta_edge_mismatch,
        "spike_arrival_delta_checks": spike_delta,
        "spike_arrival_delta_edge_consistent": spike_delta_edge_consistent,
        "spike_arrival_delta_edge_mismatch": spike_delta_edge_mismatch,
        "reference_voltage": f"{ref_v:.3f}",
        "reference_mismatch_records": len(ref_mismatch_rows),
    }
    with (out / "summary.md").open("w", encoding="utf-8") as f:
        f.write("# Fixed-Path Edge Consistency QA\n\n")
        for k, v in summary.items():
            f.write(f"- {k}: {v}\n")
        f.write("\n## Interpretation\n\n")
        f.write("- edge_consistent_pairs means stage identity and input/output rise/fall directions match between adjacent voltage reports.\n")
        f.write("- positive_arrival_delta_edge_consistent is the monotonic-fail subset that cannot be explained by rise/fall edge switching.\n")
        f.write("- edge_mismatch_vs_reference compares every voltage against the highest-voltage report used as reference.\n")

    for k, v in summary.items():
        print(f"{k}={v}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
