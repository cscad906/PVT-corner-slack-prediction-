#!/usr/bin/env python3
# -*- coding: euc-kr -*-
"""PrimeTime scaling 결과를 실제 target-corner ground truth와 비교한다.

가장 먼저 할 일
    이 파일이 들어 있는 pt_si_re 디렉토리로 이동한다.

        cd /home/KNUEEhdd1/sogang1/hyunss/PVT/PVT_prediction/pt_si_re

Setup 결과 실행 방법
    아래 두 경로만 실제 파일의 절대경로로 바꿔서 실행한다.

        python3 analysis/compare_scaling_mae.py \
            /절대경로/restored_scaled_MFC_target.rpt \
            /절대경로/MFC_ground_truth_target.rpt \
            --analysis setup \
            --output-dir mfc_scaling_comparison

Hold 결과 실행 방법

        python3 analysis/compare_scaling_mae.py \
            /절대경로/restored_scaled_MFC_target_hold.rpt \
            /절대경로/MFC_ground_truth_target_hold.rpt \
            --analysis hold \
            --output-dir mfc_scaling_comparison_hold

입력 파일 순서
    첫 번째 파일: run_scaling_after_restore.tcl이 만든 PT scaling 결과 .rpt
    두 번째 파일: 실제 target DB/lib session에서 만든 ground-truth .rpt

    순서를 바꾸면 signed error와 bias 부호가 반대로 나오므로 바꾸지 않는다.
    두 report는 반드시 같은 fixed_paths.tcl로 만들고 setup끼리 또는 hold끼리
    비교해야 한다. 각 path 앞에는 다음 marker가 있어야 한다.

        ### FIXED_PATH idx=... key=...

실행이 끝난 뒤 확인 방법
    ground-truth 파일명을 기준으로 결과 하위 폴더가 자동 생성된다.

        cat  mfc_scaling_comparison/*/summary.txt
        less -S mfc_scaling_comparison/*/path_errors.txt

    summary.txt
        MAE/RMSE/bias, 비교 및 제외 path 수, arrival/required 진단,
        실제 scaling 입력 P/V/T/DB 정보를 보여 준다.

    path_errors.txt
        path별 GT slack, scaling slack, signed/absolute error,
        arrival/required error를 absolute error가 큰 순서로 보여 준다.

결과 해석
    error = PT scaling slack - ground-truth slack
    MAE   = path별 absolute error 평균
    bias  = signed error 평균. 양수면 scaling slack이 GT보다 크게 나온 것이다.

    arrival diagnostic이 크면 launch clock, data path, SI 조건을 확인한다.
    required diagnostic이 크면 capture clock, uncertainty, derate, constraint를
    확인한다. req_source가 direct면 report 값을 직접 읽었고,
    derived_setup/derived_hold면 slack과 arrival 관계식으로 계산한 것이다.

required diagnostic이 unavailable일 때
    report에 Path Type 또는 data required time 줄이 없을 수 있다. Setup이면
    --analysis setup, hold면 --analysis hold를 붙여 다시 실행한다. 기존 PT report를
    그대로 사용하므로 이 진단 때문에 PrimeTime scaling을 다시 돌릴 필요는 없다.

Scaling에 사용한 입력 DB 확인
    최신 run_scaling_after_restore.tcl 결과 옆에는 다음 파일이 생긴다.

        <scaling-result>.rpt.inputs.txt

    compare script가 이 파일을 찾으면 내용을 summary.txt 아래에 자동 복사한다.
    예전 scaling 결과에는 이 파일이 없으므로 input plan만 unavailable로 표시된다.

단위와 재실행
    입력 report의 slack/arrival/required 단위는 항상 ns로 읽고 결과는 ps로 쓴다.
    같은 명령을 다시 실행해도 기존 결과를 덮어쓰지 않고 _run2, _run3 폴더를
    만든다. Python 3.6 이상에서 동작하며 외부 package는 필요하지 않다.
"""

import argparse
import json
import math
import re
from pathlib import Path


PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+)\s+key=(.*)$")
SLACK_RE = re.compile(
    r"^\s*slack\s+\((?:MET|VIOLATED)[^)]*\)\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
ARRIVAL_RE = re.compile(r"^\s*data\s+arrival\s+time\b(.*)$", re.IGNORECASE)
REQUIRED_RE = re.compile(r"^\s*data\s+required\s+time\b(.*)$", re.IGNORECASE)
PATH_TYPE_RE = re.compile(r"^\s*Path\s+Type\s*:\s*(max|min)\b", re.IGNORECASE)
NS_TO_PS = 1000.0


class PathResult(object):
    """One fixed-path result; kept simple for Synopsys Python 3.6."""

    __slots__ = ("idx", "key", "slack", "arrival", "required", "path_type")

    def __init__(self, idx, key, slack, arrival=None, required=None, path_type=None):
        self.idx = idx
        self.key = key
        self.slack = slack
        self.arrival = arrival
        self.required = required
        self.path_type = path_type


def labeled_number(match):
    """Return the first number after a matched timing-report row label."""
    if not match:
        return None
    number = NUMBER_RE.search(match.group(1))
    return None if number is None else float(number.group(0))


def parse_report(path):
    """Read ### FIXED_PATH blocks and the slack in each successfully measured block."""
    results = {}
    current_idx = None
    current_key = None
    current_slack = None
    current_arrival = None
    current_required = None
    current_path_type = None

    def finish():
        nonlocal current_idx, current_key, current_slack
        nonlocal current_arrival, current_required
        nonlocal current_path_type
        if current_key is None or current_idx is None:
            return
        if current_key in results:
            raise ValueError(f"duplicate path key in {path}: {current_key}")
        results[current_key] = PathResult(
            current_idx, current_key, current_slack,
            current_arrival, current_required, current_path_type)

    with path.open(errors="ignore") as report:
        for line in report:
            match = PATH_RE.match(line.rstrip("\n"))
            if match:
                finish()
                current_idx = int(match.group(1))
                current_key = match.group(2).strip()
                current_slack = None
                current_arrival = None
                current_required = None
                current_path_type = None
                continue
            if current_key is not None:
                match = PATH_TYPE_RE.match(line)
                if match:
                    current_path_type = match.group(1).lower()
                    continue
                match = SLACK_RE.match(line)
                if match:
                    current_slack = float(match.group(1))
                    continue
                match = ARRIVAL_RE.match(line)
                value = labeled_number(match)
                # A full-clock report repeats arrival later with a negated value
                # while forming slack. The first row is the real arrival time.
                if value is not None and current_arrival is None:
                    current_arrival = value
                    continue
                match = REQUIRED_RE.match(line)
                value = labeled_number(match)
                if value is not None and current_required is None:
                    current_required = value
    finish()
    if not results:
        raise ValueError(f"no '### FIXED_PATH idx=... key=...' blocks: {path}")
    return results


def evaluate(scaled, truth, factor, requested_analysis=None):
    rows = []
    errors = []
    scaled_resolved = sum(item.slack is not None for item in scaled.values())
    truth_resolved = sum(item.slack is not None for item in truth.values())

    for key in sorted(set(scaled) | set(truth)):
        pred = scaled.get(key)
        gt = truth.get(key)
        pred_ps = None if pred is None or pred.slack is None else pred.slack * factor
        truth_ps = None if gt is None or gt.slack is None else gt.slack * factor
        pred_arrival_ps = (
            None if pred is None or pred.arrival is None else pred.arrival * factor)
        truth_arrival_ps = (
            None if gt is None or gt.arrival is None else gt.arrival * factor)
        pred_required_ps = (
            None if pred is None or pred.required is None else pred.required * factor)
        truth_required_ps = (
            None if gt is None or gt.required is None else gt.required * factor)
        arrival_error = (
            None if pred_arrival_ps is None or truth_arrival_ps is None
            else pred_arrival_ps - truth_arrival_ps)
        required_error = (
            None if pred_required_ps is None or truth_required_ps is None
            else pred_required_ps - truth_required_ps)
        required_source = "direct" if required_error is not None else "unavailable"
        if pred_ps is not None and truth_ps is not None:
            error = pred_ps - truth_ps
            errors.append(error)
            status = "compared"
        elif pred is None:
            error = None
            status = "missing_scaling_block"
        elif gt is None:
            error = None
            status = "missing_ground_truth_block"
        elif pred_ps is None and truth_ps is None:
            error = None
            status = "unresolved_both_paths"
        elif pred_ps is None:
            error = None
            status = "unresolved_scaling_path"
        else:
            error = None
            status = "unresolved_ground_truth_path"
        analysis = requested_analysis
        if analysis is None:
            path_types = {
                item.path_type for item in (pred, gt)
                if item is not None and item.path_type is not None}
            if len(path_types) == 1:
                analysis = "setup" if next(iter(path_types)) == "max" else "hold"
        if (required_error is None and error is not None and
                arrival_error is not None and analysis in ("setup", "hold")):
            if analysis == "setup":
                # setup slack = required - arrival
                required_error = error + arrival_error
            else:
                # hold slack = arrival - required
                required_error = arrival_error - error
            required_source = "derived_" + analysis
        rows.append({
            "idx": gt.idx if gt is not None else pred.idx,
            "path_key": key,
            "ground_truth_ps": truth_ps,
            "pt_scaling_ps": pred_ps,
            "pt_scaling_err_ps": error,
            "abs_error_ps": None if error is None else abs(error),
            "ground_truth_arrival_ps": truth_arrival_ps,
            "pt_scaling_arrival_ps": pred_arrival_ps,
            "arrival_error_ps": arrival_error,
            "ground_truth_required_ps": truth_required_ps,
            "pt_scaling_required_ps": pred_required_ps,
            "required_error_ps": required_error,
            "required_error_source": required_source,
            "status": status,
        })

    if not errors:
        raise ValueError("no path has a resolved slack in both reports")
    abs_errors = [abs(value) for value in errors]
    compared_rows = [row for row in rows if row["abs_error_ps"] is not None]
    worst_row = max(compared_rows, key=lambda row: row["abs_error_ps"])
    arrival_errors = [
        row["arrival_error_ps"] for row in compared_rows
        if row["arrival_error_ps"] is not None]
    required_errors = [
        row["required_error_ps"] for row in compared_rows
        if row["required_error_ps"] is not None]
    required_source_counts = {}
    for row in compared_rows:
        source = row["required_error_source"]
        required_source_counts[source] = required_source_counts.get(source, 0) + 1
    status_counts = {}
    for row in rows:
        status = row["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    scaled_keys = set(scaled)
    truth_keys = set(truth)
    summary = {
        "scaled_blocks": len(scaled),
        "scaled_resolved": scaled_resolved,
        "ground_truth_blocks": len(truth),
        "ground_truth_resolved": truth_resolved,
        "shared_path_keys": len(scaled_keys & truth_keys),
        "scaled_only_blocks": len(scaled_keys - truth_keys),
        "ground_truth_only_blocks": len(truth_keys - scaled_keys),
        "compared_paths": len(errors),
        "status_counts": status_counts,
        "mae_ps": sum(abs_errors) / len(abs_errors),
        "rmse_ps": math.sqrt(sum(value * value for value in errors) / len(errors)),
        "bias_ps": sum(errors) / len(errors),
        "worst_abs_error_ps": max(abs_errors),
        "worst_path_key": worst_row["path_key"],
        "excluded_paths": len(rows) - len(errors),
        "required_source_counts": required_source_counts,
    }
    for name, values in (("arrival", arrival_errors), ("required", required_errors)):
        summary[f"{name}_compared_paths"] = len(values)
        summary[f"{name}_mae_ps"] = (
            sum(abs(value) for value in values) / len(values) if values else None)
        summary[f"{name}_bias_ps"] = (
            sum(values) / len(values) if values else None)
    return rows, summary


def format_number(value):
    return "-" if value is None else f"{value:.6f}"


def write_path_text(path, rows):
    """Write paths by descending absolute error; unresolved paths come last."""
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            row["abs_error_ps"] is None,
            -(row["abs_error_ps"] or 0.0),
            row["path_key"],
        ),
    )
    with path.open("w") as output:
        output.write("# Input slack unit: ns; all values below: ps\n")
        output.write("# Order: abs_error descending; unresolved/missing paths last\n")
        output.write(
            f"{'idx':>7} {'gt_slack':>15} {'pt_slack':>15} "
            f"{'slack_err':>15} {'abs_err':>15} "
            f"{'arrival_err':>13} {'required_err':>13} "
            f"{'req_source':<13} {'status':<29} path_key\n"
        )
        for row in ordered_rows:
            output.write(
                f"{row['idx']:>7} "
                f"{format_number(row['ground_truth_ps']):>15} "
                f"{format_number(row['pt_scaling_ps']):>15} "
                f"{format_number(row['pt_scaling_err_ps']):>15} "
                f"{format_number(row['abs_error_ps']):>15} "
                f"{format_number(row['arrival_error_ps']):>13} "
                f"{format_number(row['required_error_ps']):>13} "
                f"{row['required_error_source']:<13} "
                f"{row['status']:<29} {row['path_key']}\n"
            )


def write_summary_text(path, summary):
    """Write the complete metric summary as plain text for a Linux terminal."""
    lines = [
        "PrimeTime scaling vs ground truth",
        f"scaled report       : {summary['scaled_report']}",
        f"ground truth report : {summary['ground_truth_report']}",
        f"input/output unit   : {summary['input_unit']} / {summary['output_unit']}",
        f"scaled blocks       : {summary['scaled_blocks']}",
        f"scaled resolved     : {summary['scaled_resolved']}",
        f"ground truth blocks : {summary['ground_truth_blocks']}",
        f"ground truth resolved: {summary['ground_truth_resolved']}",
        f"shared path keys    : {summary['shared_path_keys']}",
        f"compared paths      : {summary['compared_paths']}",
        f"excluded paths      : {summary['excluded_paths']}",
        f"MAE                 : {summary['mae_ps']:.6f} ps",
        f"RMSE                : {summary['rmse_ps']:.6f} ps",
        f"bias                : {summary['bias_ps']:+.6f} ps",
        f"worst absolute error: {summary['worst_abs_error_ps']:.6f} ps",
        f"worst path key      : {summary['worst_path_key']}",
        component_line("arrival", summary),
        component_line("required", summary),
        "status counts:",
    ]
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"  {status:<29} {count}")
    if summary.get("scaling_input_plan"):
        lines.extend([
            "",
            "Scaling inputs used by PrimeTime",
            summary["scaling_input_plan"].rstrip("\n"),
        ])
    else:
        lines.extend([
            "",
            "Scaling inputs used by PrimeTime",
            "unavailable: adjacent <scaled-report>.inputs.txt was not found",
        ])
    path.write_text("\n".join(lines) + "\n")


def component_line(name, summary):
    """Format arrival/required diagnostics when both reports contain them."""
    count = summary[f"{name}_compared_paths"]
    mae = summary[f"{name}_mae_ps"]
    bias = summary[f"{name}_bias_ps"]
    if not count:
        return f"{name + ' diagnostic':<21}: unavailable in timing report"
    suffix = ""
    if name == "required":
        sources = ", ".join(
            f"{key}={value}" for key, value in
            sorted(summary["required_source_counts"].items()))
        suffix = f" ({sources})"
    return (
        f"{name + ' diagnostic':<21}: paths={count} "
        f"MAE={mae:.6f} ps bias={bias:+.6f} ps{suffix}")


def safe_corner_name(report_path):
    """Return a filesystem-safe target-corner name from the GT report name."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", report_path.stem).strip("._")
    return name or "target_corner"


def create_result_dir(output_root, corner_name):
    """Atomically create a new corner directory without overwriting a run."""
    output_root.mkdir(parents=True, exist_ok=True)
    run_number = 1
    while True:
        directory_name = corner_name if run_number == 1 else f"{corner_name}_run{run_number}"
        result_dir = output_root / directory_name
        try:
            result_dir.mkdir()
            return result_dir
        except FileExistsError:
            run_number += 1


def main():
    parser = argparse.ArgumentParser(
        description="PrimeTime scaling slack\uc640 \uc2e4\uc81c target-corner slack\uc758 path\ubcc4 MAE\ub97c \uacc4\uc0b0\ud569\ub2c8\ub2e4.")
    parser.add_argument("scaled_rpt", type=Path, help="run_scaling_after_restore.tcl \uacb0\uacfc .rpt")
    parser.add_argument("ground_truth_rpt", type=Path, help="\uc2e4\uc81c target library\ub85c \uce21\uc815\ud55c fixed-path .rpt")
    parser.add_argument("--output-dir", type=Path, default=Path("pt_scaling_comparison"),
                        help="\ucf54\ub108\ubcc4 \uacb0\uacfc\ub97c \uc800\uc7a5\ud560 \uc0c1\uc704 \ud3f4\ub354 (\uae30\ubcf8\uac12: pt_scaling_comparison)")
    parser.add_argument("--analysis", choices=("setup", "hold"), default=None,
                        help="Path Type row\uac00 \uc5c6\uc744 \ub54c required-time \uc624\ucc28 \uc720\ub3c4\uc5d0 \uc0ac\uc6a9")
    args = parser.parse_args()

    for path in (args.scaled_rpt, args.ground_truth_rpt):
        if not path.is_file():
            parser.error(f"file not found: {path}")

    scaled = parse_report(args.scaled_rpt)
    truth = parse_report(args.ground_truth_rpt)
    rows, summary = evaluate(scaled, truth, NS_TO_PS, args.analysis)
    summary.update({
        "input_unit": "ns",
        "output_unit": "ps",
        "scaled_report": str(args.scaled_rpt.resolve()),
        "ground_truth_report": str(args.ground_truth_rpt.resolve()),
    })
    scaling_inputs_path = Path(str(args.scaled_rpt) + ".inputs.txt")
    if scaling_inputs_path.is_file():
        summary["scaling_input_plan_path"] = str(scaling_inputs_path.resolve())
        summary["scaling_input_plan"] = scaling_inputs_path.read_text(errors="ignore")
    else:
        summary["scaling_input_plan_path"] = None
        summary["scaling_input_plan"] = None

    corner_name = safe_corner_name(args.ground_truth_rpt)
    result_dir = create_result_dir(args.output_dir, corner_name)
    path_text_path = result_dir / "path_errors.txt"
    summary_text_path = result_dir / "summary.txt"
    json_path = result_dir / "summary.json"
    write_path_text(path_text_path, rows)
    write_summary_text(summary_text_path, summary)
    with json_path.open("w") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False)

    print("=== PrimeTime scaling vs ground truth ===")
    print(f"compared paths : {summary['compared_paths']}")
    print(f"excluded paths : {summary['excluded_paths']}")
    print(f"shared keys    : {summary['shared_path_keys']}")
    print("status counts  :")
    for status, count in sorted(summary["status_counts"].items()):
        print(f"  {status:<29} {count}")
    print(f"MAE            : {summary['mae_ps']:.3f} ps")
    print(f"RMSE           : {summary['rmse_ps']:.3f} ps")
    print(f"bias           : {summary['bias_ps']:+.3f} ps")
    print(f"worst          : {summary['worst_abs_error_ps']:.3f} ps")
    print(component_line("arrival", summary))
    print(component_line("required", summary))
    if summary["scaling_input_plan_path"]:
        print(f"scaling inputs : {summary['scaling_input_plan_path']}")
    else:
        print("scaling inputs : unavailable (older scaling report)")
    print("worst paths    :")
    compared_rows = [row for row in rows if row["abs_error_ps"] is not None]
    for rank, row in enumerate(
            sorted(compared_rows, key=lambda item: item["abs_error_ps"], reverse=True)[:10], 1):
        print(
            f"  {rank:>2}. idx={row['idx']} abs={row['abs_error_ps']:.3f} ps "
            f"err={row['pt_scaling_err_ps']:+.3f} ps key={row['path_key']}"
        )
    print(f"path details   : {path_text_path}")
    print(f"summary text   : {summary_text_path}")
    print(f"summary JSON   : {json_path}")


if __name__ == "__main__":
    main()
