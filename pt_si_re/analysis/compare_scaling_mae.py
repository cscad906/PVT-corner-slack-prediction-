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

    별도 grep 없이 터미널과 summary.txt의 CLOCK VALIDATION을 확인한다.
        PASS    : 두 report의 clock 이름/edge/cycle 및 path 조건이 일치함
        INVALID : 서로 다른 clock 조건을 비교했으므로 현재 MAE를 scaling 오차로 쓰면 안 됨
        REVIEW  : generated-clock 후보가 여러 개이거나 clock 정보가 없어 원문 확인 필요
    worst launch/capture edge에는 차이가 가장 큰 path, 양쪽 clock 이름과 edge가 나온다.

    path_errors.txt
        path별 GT slack, scaling slack, signed/absolute error,
        arrival/required error를 absolute error가 큰 순서로 보여 준다.

결과 해석
    error = PT scaling slack - ground-truth slack
    MAE   = path별 absolute error 평균
    bias  = signed error 평균. 양수면 scaling slack이 GT보다 크게 나온 것이다.

    Setup에서는 path마다 다음 관계가 성립한다.

        slack error = required error - arrival error

    따라서 arrival/required MAE가 각각 커도 두 signed error가 path별로 같은
    방향과 비슷한 크기로 이동하면 slack에서는 상쇄된다. 예를 들어 arrival
    MAE=283 ps, required MAE=268 ps, slack MAE=15 ps는 가능한 정상 조합이다.
    이때 개별 MAE만 보고 scaling 실패로 판정하면 안 되고 path_errors.txt에서
    arrival_err와 required_err의 부호와 차이를 함께 확인한다.

    arrival과 required가 비슷하게 움직이지 않으면서 slack MAE도 크면 launch/data
    또는 capture/constraint 조건 차이를 조사한다. req_source가 direct면 report 값을 직접 읽었고,
    derived_setup/derived_hold면 slack과 arrival 관계식으로 계산한 것이다.

    launch/capture clock edge MAE가 clock period에 가까우면 두 report가 서로 다른
    clock cycle/edge를 선택했거나 constraint/session이 다르다는 뜻이다. clock
    identity 또는 path-group mismatch가 1개라도 있으면 PT scaling 정확도를 판단하기
    전에 두 report 생성 조건부터 맞춘다. Clock edge와 group이 모두 같은데 required
    오차만 크면 capture clock-tree scaling 범위를 우선 확인한다. Parser는
    data arrival time 앞 구간의 첫 clock edge를 launch, 뒤 구간의 첫 edge를
    capture로 사용한다. multi_edge_blocks가 0이 아니면 generated-clock 원문을
    path_errors.txt의 worst path부터 직접 대조한다.

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
PATH_GROUP_RE = re.compile(r"^\s*Path\s+Group\s*:\s*(.*?)\s*$", re.IGNORECASE)
CLOCK_EDGE_RE = re.compile(
    r"^\s*clock\s+(.+?)\s+\((rise|fall)\s+edge\)\s+(.*)$", re.IGNORECASE)
NS_TO_PS = 1000.0
CLOCK_EDGE_TOLERANCE_PS = 0.001


class PathResult(object):
    """One fixed-path result; kept simple for Synopsys Python 3.6."""

    __slots__ = (
        "idx", "key", "slack", "arrival", "required", "path_type",
        "path_group", "launch_clock", "capture_clock",
        "launch_clock_rows", "capture_clock_rows")

    def __init__(self, idx, key, slack, arrival=None, required=None, path_type=None,
                 path_group=None, launch_clock=None, capture_clock=None,
                 launch_clock_rows=0, capture_clock_rows=0):
        self.idx = idx
        self.key = key
        self.slack = slack
        self.arrival = arrival
        self.required = required
        self.path_type = path_type
        self.path_group = path_group
        self.launch_clock = launch_clock
        self.capture_clock = capture_clock
        self.launch_clock_rows = launch_clock_rows
        self.capture_clock_rows = capture_clock_rows


def labeled_number(match):
    """Return the first number after a matched timing-report row label."""
    if not match:
        return None
    number = NUMBER_RE.search(match.group(1))
    return None if number is None else float(number.group(0))


def clock_edge(match):
    """Return (clock name, rise/fall, edge time) from a full-clock row."""
    if not match:
        return None
    numbers = NUMBER_RE.findall(match.group(3))
    if not numbers:
        return None
    return (match.group(1).strip(), match.group(2).lower(), float(numbers[-1]))


def parse_report(path):
    """Read ### FIXED_PATH blocks and the slack in each successfully measured block."""
    results = {}
    current_idx = None
    current_key = None
    current_slack = None
    current_arrival = None
    current_required = None
    current_path_type = None
    current_path_group = None
    current_launch_clock = None
    current_capture_clock = None
    current_launch_clock_rows = 0
    current_capture_clock_rows = 0

    def finish():
        nonlocal current_idx, current_key, current_slack
        nonlocal current_arrival, current_required
        nonlocal current_path_type
        nonlocal current_path_group
        nonlocal current_launch_clock, current_capture_clock
        nonlocal current_launch_clock_rows, current_capture_clock_rows
        if current_key is None or current_idx is None:
            return
        if current_key in results:
            raise ValueError(f"duplicate path key in {path}: {current_key}")
        results[current_key] = PathResult(
            current_idx, current_key, current_slack,
            current_arrival, current_required, current_path_type,
            current_path_group, current_launch_clock, current_capture_clock,
            current_launch_clock_rows, current_capture_clock_rows)

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
                current_path_group = None
                current_launch_clock = None
                current_capture_clock = None
                current_launch_clock_rows = 0
                current_capture_clock_rows = 0
                continue
            if current_key is not None:
                match = PATH_GROUP_RE.match(line)
                if match:
                    current_path_group = match.group(1).strip()
                    continue
                match = PATH_TYPE_RE.match(line)
                if match:
                    current_path_type = match.group(1).lower()
                    continue
                edge = clock_edge(CLOCK_EDGE_RE.match(line))
                if edge is not None:
                    # full_clock_expanded prints the launch section before the
                    # first data-arrival row and the capture section after it.
                    if current_arrival is None:
                        current_launch_clock_rows += 1
                        if current_launch_clock is None:
                            current_launch_clock = edge
                    else:
                        current_capture_clock_rows += 1
                        if current_capture_clock is None:
                            current_capture_clock = edge
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
        path_group_mismatch = bool(
            pred is not None and gt is not None and
            pred.path_group is not None and gt.path_group is not None and
            pred.path_group != gt.path_group)
        path_type_mismatch = bool(
            pred is not None and gt is not None and
            pred.path_type is not None and gt.path_type is not None and
            pred.path_type != gt.path_type)
        clock_status = "unavailable"
        launch_edge_error = None
        capture_edge_error = None
        launch_clock_mismatch = False
        capture_clock_mismatch = False
        launch_clock_ambiguous = False
        capture_clock_ambiguous = False
        if pred is not None and gt is not None:
            launch_clock_ambiguous = (
                pred.launch_clock_rows > 1 or gt.launch_clock_rows > 1)
            capture_clock_ambiguous = (
                pred.capture_clock_rows > 1 or gt.capture_clock_rows > 1)
            if pred.launch_clock is not None and gt.launch_clock is not None:
                launch_clock_mismatch = pred.launch_clock[:2] != gt.launch_clock[:2]
                launch_edge_error = (pred.launch_clock[2] - gt.launch_clock[2]) * factor
            if pred.capture_clock is not None and gt.capture_clock is not None:
                capture_clock_mismatch = pred.capture_clock[:2] != gt.capture_clock[:2]
                capture_edge_error = (pred.capture_clock[2] - gt.capture_clock[2]) * factor
            if (pred.launch_clock is not None and gt.launch_clock is not None and
                    pred.capture_clock is not None and gt.capture_clock is not None):
                clock_status = "mismatch" if (
                    path_group_mismatch or path_type_mismatch or
                    launch_clock_mismatch or capture_clock_mismatch) else "match"
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
            "launch_edge_error_ps": launch_edge_error,
            "capture_edge_error_ps": capture_edge_error,
            "scaled_launch_clock": None if pred is None else pred.launch_clock,
            "ground_truth_launch_clock": None if gt is None else gt.launch_clock,
            "scaled_capture_clock": None if pred is None else pred.capture_clock,
            "ground_truth_capture_clock": None if gt is None else gt.capture_clock,
            "path_group_mismatch": path_group_mismatch,
            "path_type_mismatch": path_type_mismatch,
            "launch_clock_mismatch": launch_clock_mismatch,
            "capture_clock_mismatch": capture_clock_mismatch,
            "launch_clock_ambiguous": launch_clock_ambiguous,
            "capture_clock_ambiguous": capture_clock_ambiguous,
            "clock_status": clock_status,
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
    launch_edge_errors = [
        row["launch_edge_error_ps"] for row in compared_rows
        if row["launch_edge_error_ps"] is not None]
    capture_edge_errors = [
        row["capture_edge_error_ps"] for row in compared_rows
        if row["capture_edge_error_ps"] is not None]
    launch_edge_rows = [
        row for row in compared_rows if row["launch_edge_error_ps"] is not None]
    capture_edge_rows = [
        row for row in compared_rows if row["capture_edge_error_ps"] is not None]
    worst_launch_edge_row = (
        max(launch_edge_rows, key=lambda row: abs(row["launch_edge_error_ps"]))
        if launch_edge_rows else None)
    worst_capture_edge_row = (
        max(capture_edge_rows, key=lambda row: abs(row["capture_edge_error_ps"]))
        if capture_edge_rows else None)
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
        "path_group_mismatches": sum(row["path_group_mismatch"] for row in compared_rows),
        "path_type_mismatches": sum(row["path_type_mismatch"] for row in compared_rows),
        "launch_clock_mismatches": sum(row["launch_clock_mismatch"] for row in compared_rows),
        "capture_clock_mismatches": sum(row["capture_clock_mismatch"] for row in compared_rows),
        "launch_clock_ambiguous": sum(row["launch_clock_ambiguous"] for row in compared_rows),
        "capture_clock_ambiguous": sum(row["capture_clock_ambiguous"] for row in compared_rows),
        "clock_relation_unavailable": sum(
            row["clock_status"] == "unavailable" for row in compared_rows),
        "launch_edge_mae_ps": (
            sum(abs(value) for value in launch_edge_errors) / len(launch_edge_errors)
            if launch_edge_errors else None),
        "capture_edge_mae_ps": (
            sum(abs(value) for value in capture_edge_errors) / len(capture_edge_errors)
            if capture_edge_errors else None),
        "launch_edge_bias_ps": (
            sum(launch_edge_errors) / len(launch_edge_errors)
            if launch_edge_errors else None),
        "capture_edge_bias_ps": (
            sum(capture_edge_errors) / len(capture_edge_errors)
            if capture_edge_errors else None),
        "launch_edge_min_ps": min(launch_edge_errors) if launch_edge_errors else None,
        "launch_edge_max_ps": max(launch_edge_errors) if launch_edge_errors else None,
        "capture_edge_min_ps": min(capture_edge_errors) if capture_edge_errors else None,
        "capture_edge_max_ps": max(capture_edge_errors) if capture_edge_errors else None,
        "worst_launch_edge": edge_summary(worst_launch_edge_row, "launch"),
        "worst_capture_edge": edge_summary(worst_capture_edge_row, "capture"),
    }
    for name, values in (("arrival", arrival_errors), ("required", required_errors)):
        summary[f"{name}_compared_paths"] = len(values)
        summary[f"{name}_mae_ps"] = (
            sum(abs(value) for value in values) / len(values) if values else None)
        summary[f"{name}_bias_ps"] = (
            sum(values) / len(values) if values else None)
    status, reasons, action = clock_validation(summary)
    summary["clock_validation_status"] = status
    summary["clock_validation_reasons"] = reasons
    summary["clock_validation_action"] = action
    return rows, summary


def edge_summary(row, name):
    """Return JSON-safe details for the path with the largest clock-edge error."""
    if row is None:
        return None
    scaled = row[f"scaled_{name}_clock"]
    truth = row[f"ground_truth_{name}_clock"]
    return {
        "idx": row["idx"],
        "path_key": row["path_key"],
        "error_ps": row[f"{name}_edge_error_ps"],
        "scaled_clock": None if scaled is None else scaled[0],
        "scaled_transition": None if scaled is None else scaled[1],
        "scaled_edge_ps": None if scaled is None else scaled[2] * NS_TO_PS,
        "ground_truth_clock": None if truth is None else truth[0],
        "ground_truth_transition": None if truth is None else truth[1],
        "ground_truth_edge_ps": None if truth is None else truth[2] * NS_TO_PS,
    }


def clock_validation(summary):
    """Classify whether slack MAE is based on the same clock relationship."""
    reasons = []
    identity_mismatches = (
        summary["path_group_mismatches"] + summary["path_type_mismatches"] +
        summary["launch_clock_mismatches"] + summary["capture_clock_mismatches"])
    ambiguous = (
        summary["launch_clock_ambiguous"] + summary["capture_clock_ambiguous"])
    edge_differences = []
    for name in ("launch", "capture"):
        mae = summary[f"{name}_edge_mae_ps"]
        if mae is not None and mae > CLOCK_EDGE_TOLERANCE_PS:
            edge_differences.append(f"{name} edge MAE={mae:.6f} ps")

    if identity_mismatches:
        reasons.append(
            "Clock/path identity mismatch: the two reports use different analysis conditions.")
    if edge_differences:
        reasons.append(
            ", ".join(edge_differences) +
            ": the two reports do not use the same ideal edge/cycle.")
    if ambiguous:
        reasons.append(
            f"{ambiguous} multi-edge block(s): inspect the generated-clock report text.")
    if summary["clock_relation_unavailable"]:
        reasons.append(
            f"Clock relation unavailable for "
            f"{summary['clock_relation_unavailable']} path(s).")

    if ambiguous or summary["clock_relation_unavailable"]:
        status = "REVIEW"
        action = (
            "Inspect the worst-edge path in the PrimeTime reports and compare "
            "launch/capture edges and generated-clock relationships.")
    elif identity_mismatches or edge_differences:
        status = "INVALID"
        action = (
            "Do not use this MAE as scaling error. First align clock definitions, "
            "selected cycles, path groups, and path types between the reports.")
    else:
        status = "PASS"
        reasons.append(
            "Clock names, edges, path groups, and path types match for all compared paths.")
        action = (
            "Clock conditions match. Continue with slack/arrival/required scaling analysis.")
    return status, reasons, action


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
            f"{'capture_edge':>13} {'clock':<11} "
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
                f"{format_number(row['capture_edge_error_ps']):>13} "
                f"{row['clock_status']:<11} "
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
        "",
        "Clock validation",
        f"status              : {summary['clock_validation_status']}",
    ]
    for reason in summary["clock_validation_reasons"]:
        lines.append(f"reason              : {reason}")
    lines.extend([
        clock_line("launch", summary),
        clock_line("capture", summary),
        f"path-group mismatches : {summary['path_group_mismatches']}",
        f"path-type mismatches  : {summary['path_type_mismatches']}",
        f"clock info unavailable: {summary['clock_relation_unavailable']}",
        edge_detail_line("worst launch edge", summary["worst_launch_edge"]),
        edge_detail_line("worst capture edge", summary["worst_capture_edge"]),
        f"action              : {summary['clock_validation_action']}",
        "",
        "status counts:",
    ])
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"  {status:<29} {count}")
    lines.extend(["", "COPY THIS RESULT"] + share_lines(summary))
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


def clock_line(name, summary):
    """Format clock identity and edge-time comparison."""
    mae = summary[f"{name}_edge_mae_ps"]
    mismatch = summary[f"{name}_clock_mismatches"]
    ambiguous = summary[f"{name}_clock_ambiguous"]
    if mae is None:
        detail = "MAE=unavailable"
    else:
        detail = (
            f"MAE={mae:.6f} ps bias={summary[name + '_edge_bias_ps']:+.6f} ps "
            f"range=[{summary[name + '_edge_min_ps']:+.6f},"
            f"{summary[name + '_edge_max_ps']:+.6f}] ps")
    return (
        f"{name + ' clock edge':<21}: {detail} "
        f"identity_mismatches={mismatch} multi_edge_blocks={ambiguous}")


def edge_detail_line(label, detail):
    """Format the scaled and GT clocks of the largest edge-error path."""
    if detail is None:
        return f"{label:<21}: unavailable"
    return (
        f"{label:<21}: idx={detail['idx']} error={detail['error_ps']:+.6f} ps "
        f"scaled={detail['scaled_clock']}/{detail['scaled_transition']}@"
        f"{detail['scaled_edge_ps']:.6f} ps "
        f"GT={detail['ground_truth_clock']}/{detail['ground_truth_transition']}@"
        f"{detail['ground_truth_edge_ps']:.6f} ps key={detail['path_key']}")


def compact_number(value):
    return "NA" if value is None else f"{value:.3f}"


def share_lines(summary):
    """Return a short, path-name-free diagnostic that is safe to copy."""
    identity_mismatches = (
        summary["path_group_mismatches"] + summary["path_type_mismatches"] +
        summary["launch_clock_mismatches"] + summary["capture_clock_mismatches"])
    multi_edge_blocks = (
        summary["launch_clock_ambiguous"] + summary["capture_clock_ambiguous"])
    worst_capture = summary["worst_capture_edge"]
    if worst_capture is None:
        worst_line = "WORST_CAPTURE error=NA scaled_edge=NA gt_edge=NA"
    else:
        worst_line = (
            f"WORST_CAPTURE error={compact_number(worst_capture['error_ps'])}ps "
            f"scaled_edge={compact_number(worst_capture['scaled_edge_ps'])}ps "
            f"gt_edge={compact_number(worst_capture['ground_truth_edge_ps'])}ps")
    return [
        (
            f"CLOCK_SHARE status={summary['clock_validation_status']} "
            f"launch_mae={compact_number(summary['launch_edge_mae_ps'])}ps "
            f"capture_mae={compact_number(summary['capture_edge_mae_ps'])}ps "
            f"capture_bias={compact_number(summary['capture_edge_bias_ps'])}ps "
            f"capture_range={compact_number(summary['capture_edge_min_ps'])},"
            f"{compact_number(summary['capture_edge_max_ps'])}ps "
            f"identity_mismatches={identity_mismatches} "
            f"multi_edge_blocks={multi_edge_blocks} "
            f"unavailable={summary['clock_relation_unavailable']}"),
        worst_line,
        (
            f"ERROR_SHARE slack_mae={compact_number(summary['mae_ps'])}ps "
            f"arrival_mae={compact_number(summary['arrival_mae_ps'])}ps "
            f"required_mae={compact_number(summary['required_mae_ps'])}ps "
            f"paths={summary['compared_paths']} excluded={summary['excluded_paths']}")
    ]


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
    print("")
    print("=== CLOCK VALIDATION ===")
    print(f"status         : {summary['clock_validation_status']}")
    for reason in summary["clock_validation_reasons"]:
        print(f"reason         : {reason}")
    print(clock_line("launch", summary))
    print(clock_line("capture", summary))
    print(f"path-group mismatches: {summary['path_group_mismatches']}")
    print(f"path-type mismatches : {summary['path_type_mismatches']}")
    print(f"clock info unavailable: {summary['clock_relation_unavailable']}")
    print(edge_detail_line("worst launch edge", summary["worst_launch_edge"]))
    print(edge_detail_line("worst capture edge", summary["worst_capture_edge"]))
    print(f"action         : {summary['clock_validation_action']}")
    print("")
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
    print("")
    print("=== COPY THIS RESULT ===")
    for line in share_lines(summary):
        print(line)


if __name__ == "__main__":
    main()
