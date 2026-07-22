#!/usr/bin/env python3.11
"""Format PT SI and quiet/aligned HSPICE results as cell/net breakdowns."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path-id", type=int, required=True)
    parser.add_argument("--si-off-rpt", type=Path, required=True)
    parser.add_argument("--si-on-rpt", type=Path, required=True)
    parser.add_argument("--arc-csv", type=Path, required=True)
    parser.add_argument("--out-rpt", type=Path, required=True)
    return parser.parse_args()


def fnum(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def sum_field(rows: list[dict[str, Any]], field: str) -> float:
    return sum(fnum(row.get(field)) for row in rows)


def compact(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def main() -> int:
    args = parse_args()
    native_flow_dir = Path(__file__).resolve().parents[1] / "native_flow"
    sys.path.insert(0, str(native_flow_dir))
    from format_pt_si_report import build_stages, parse_pt_report

    parsed_off = parse_pt_report(args.si_off_rpt)
    parsed_on = parse_pt_report(args.si_on_rpt)
    pt_off, _ = build_stages(parsed_off, {}, args.path_id, args.si_off_rpt.parent)
    pt_on, _ = build_stages(parsed_on, {}, args.path_id, args.si_on_rpt.parent)
    arc_rows = [row for row in read_csv(args.arc_csv) if row.get("status") == "PASS"]

    off_by_stage = {int(row["stage_idx"]): row for row in pt_off}
    on_by_stage = {int(row["stage_idx"]): row for row in pt_on}
    arc_by_stage = {int(row["stage_idx"]): row for row in arc_rows}
    stage_ids = sorted(set(off_by_stage) & set(on_by_stage) & set(arc_by_stage))

    pt_off_cell = sum_field(pt_off, "cell_ps")
    pt_off_net = sum_field(pt_off, "net_ps")
    pt_on_cell = sum_field(pt_on, "cell_ps")
    pt_on_net = sum_field(pt_on, "net_ps")

    hsp_quiet_cell = sum_field(arc_rows, "quiet_cell_ps")
    hsp_quiet_net = sum_field(arc_rows, "quiet_net_ps")
    hsp_center_cell = sum_field(arc_rows, "align_cell_center_ps")
    hsp_center_net = sum_field(arc_rows, "align_net_center_ps")
    hsp_center_stage = sum_field(arc_rows, "align_stage_center_ps")
    hsp_worst_cell = sum_field(arc_rows, "align_cell_at_stage_worst_ps")
    hsp_worst_net = sum_field(arc_rows, "align_net_at_stage_worst_ps")
    hsp_worst_stage = sum_field(arc_rows, "align_stage_at_stage_worst_ps")
    hsp_quiet_stage = sum_field(arc_rows, "quiet_stage_ps")

    args.out_rpt.parent.mkdir(parents=True, exist_ok=True)
    with args.out_rpt.open("w") as f:
        f.write(f"Path {args.path_id} cell/net delay breakdown\n")
        f.write(f"Startpoint: {parsed_on.get('startpoint', '')}\n")
        f.write(f"Endpoint:   {parsed_on.get('endpoint', '')}\n")
        f.write(f"Stages:     {len(stage_ids)}\n\n")

        f.write("PrimeTime coherent full-path breakdown (ps)\n")
        f.write("Mode             Cell sum     Net sum    Total sum\n")
        f.write("---------------  ---------  ----------  -----------\n")
        f.write(f"SI off           {pt_off_cell:9.3f}  {pt_off_net:10.3f}  {pt_off_cell + pt_off_net:11.3f}\n")
        f.write(f"SI on            {pt_on_cell:9.3f}  {pt_on_net:10.3f}  {pt_on_cell + pt_on_net:11.3f}\n")
        f.write(
            f"SI on - off      {pt_on_cell - pt_off_cell:9.3f}  "
            f"{pt_on_net - pt_off_net:10.3f}  "
            f"{(pt_on_cell + pt_on_net) - (pt_off_cell + pt_off_net):11.3f}\n\n"
        )

        f.write("HSPICE independent local-arc sum (ps)\n")
        f.write("Mode             Cell sum     Net sum   Stage sum\n")
        f.write("---------------  ---------  ----------  ----------\n")
        f.write(f"Quiet            {hsp_quiet_cell:9.3f}  {hsp_quiet_net:10.3f}  {hsp_quiet_stage:10.3f}\n")
        f.write(f"Aligned center   {hsp_center_cell:9.3f}  {hsp_center_net:10.3f}  {hsp_center_stage:10.3f}\n")
        f.write(f"Aligned worst    {hsp_worst_cell:9.3f}  {hsp_worst_net:10.3f}  {hsp_worst_stage:10.3f}\n")
        f.write(
            f"Center - quiet   {hsp_center_cell - hsp_quiet_cell:9.3f}  "
            f"{hsp_center_net - hsp_quiet_net:10.3f}  "
            f"{hsp_center_stage - hsp_quiet_stage:10.3f}\n"
        )
        f.write(
            f"Worst - quiet    {hsp_worst_cell - hsp_quiet_cell:9.3f}  "
            f"{hsp_worst_net - hsp_quiet_net:10.3f}  "
            f"{hsp_worst_stage - hsp_quiet_stage:10.3f}\n\n"
        )

        f.write("Important attribution note\n")
        f.write(
            "PT records crosstalk slowdown on the victim net arc. In the SPICE deck, "
            "the cell measure starts at the selected driver input and ends at the victim "
            "driver output. Coupled loading can therefore move the driver output crossing "
            "and appear in HSPICE cell delay, while driver-output and receiver-input "
            "crossings move together and leave little net-only delay. The columns are "
            "measurement attribution, not different crosstalk physics.\n\n"
        )

        f.write(
            "Stg  PTonCell PTonNet  PTdCell  PTdNet  PTarcD  "
            "HSPqCell HSPqNet HSPaCell HSPaNet  HSPdCell HSPdNet HSPdStage  Mode                    Arc\n"
        )
        f.write(
            "---  -------- -------  -------  ------  ------  "
            "-------- ------- -------- -------  -------- ------- ---------  ----------------------  ----------------------------------------\n"
        )
        for stage_id in stage_ids:
            off = off_by_stage[stage_id]
            on = on_by_stage[stage_id]
            arc = arc_by_stage[stage_id]
            qcell = fnum(arc.get("quiet_cell_ps"))
            qnet = fnum(arc.get("quiet_net_ps"))
            acell = fnum(arc.get("align_cell_at_stage_worst_ps"))
            anet = fnum(arc.get("align_net_at_stage_worst_ps"))
            f.write(
                f"{stage_id:3d}  "
                f"{fnum(on.get('cell_ps')):8.3f} {fnum(on.get('net_ps')):7.3f}  "
                f"{fnum(on.get('cell_ps')) - fnum(off.get('cell_ps')):7.3f}  "
                f"{fnum(on.get('net_ps')) - fnum(off.get('net_ps')):6.3f}  "
                f"{fnum(arc.get('pt_arc_delta_selected_ps')):6.3f}  "
                f"{qcell:8.3f} {qnet:7.3f} {acell:8.3f} {anet:7.3f}  "
                f"{acell - qcell:8.3f} {anet - qnet:7.3f} "
                f"{fnum(arc.get('stage_delta_worst_ps')):9.3f}  "
                f"{str(arc.get('stage_measure_mode', ''))[:22]:22s}  "
                f"{compact(str(arc.get('stage_arc', '')), 90)}\n"
            )

    print(f"Wrote {args.out_rpt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
