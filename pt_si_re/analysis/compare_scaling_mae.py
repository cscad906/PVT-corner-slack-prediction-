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
            --output-dir mfc_scaling_comparison

입력 파일 순서
    첫 번째 파일: run_scaling_after_restore.tcl이 만든 PT scaling 결과 .rpt
    두 번째 파일: 실제 target DB/lib session에서 만든 ground-truth .rpt

    순서를 바꾸면 signed error와 bias 부호가 반대로 나오므로 바꾸지 않는다.
    두 report는 반드시 같은 fixed_paths.tcl로 만들고 setup끼리 또는 hold끼리
    비교해야 한다. 각 path 앞에는 다음 marker가 있어야 한다.

        ### FIXED_PATH idx=... key=...

실행이 끝난 뒤 확인 방법
    결과는 출력 폴더 / setup 또는 hold / GT 파일명(확장자 제외) 아래에 저장된다.
    같은 코너 이름이어도 setup과 hold 결과는 각각의 분석 타입 폴더에 저장된다.

        mfc_scaling_comparison/setup/<코너이름>/summary.txt
        mfc_scaling_comparison/hold/<코너이름>/summary.txt

        cat  mfc_scaling_comparison/*/*/summary.txt
        less -S mfc_scaling_comparison/setup/*/path_errors.txt
        less -S mfc_scaling_comparison/setup/*/path_diagnostics.txt

    Hold 결과를 볼 때는 위 경로의 setup을 hold로 바꾼다.
    --analysis를 생략하면 report의 Path Type: max/min에서 setup/hold를 자동 판별한다.
    Path Type이 없거나 두 타입이 섞여 있으면 --analysis setup 또는 hold를 명시해야 한다.

    summary.txt
        MAE/RMSE/bias, 최대 절대오차, fixed-path WNS와 WNS 오차율,
        비교 및 제외 path 수, arrival/required 진단, 실제 scaling 입력 P/V/T/DB
        정보를 보여 준다. WNS 지표는 터미널과 summary.json에도 함께 출력된다.

    별도 grep 없이 터미널과 summary.txt의 CLOCK VALIDATION을 확인한다.
        PASS    : 두 report의 clock 이름/edge/cycle 및 path 조건이 일치함
        INVALID : 서로 다른 clock 조건을 비교했으므로 현재 MAE를 scaling 오차로 쓰면 안 됨
        REVIEW  : generated-clock 후보가 여러 개이거나 clock 정보가 없어 원문 확인 필요
    worst launch/capture edge에는 차이가 가장 큰 path, 양쪽 clock 이름과 edge가 나온다.

    path_errors.txt
        path별 GT slack, scaling slack, signed/absolute error,
        arrival/required error를 absolute error가 큰 순서로 보여 준다.


    path_diagnostics.txt
        같은 실행으로 자동 생성되는 경로별 상세 진단이다. GT 세션 접근이나
        PrimeTime 재실행은 필요 없으며, 기존 두 timing report만 사용한다.
        launch clock/data/capture clock의 Incr 누적값과 uncertainty, CPPR,
        setup/hold 항목을 GT, scaling, signed error 순서로 표시한다.
        slack absolute error가 큰 경로부터 정렬하며, 양쪽 WNS 경로는 summary의
        idx/key로 찾는다. 리포트에 없는 항목은 N/A이며 측정된 0과 구분한다.
        launch/capture 구분에는 full_clock_expanded 및 input pin 정보가 필요하다.

        EXPLAINED   : 리포트 항목 합산으로 arrival/required를 반올림 범위 내 설명함
        REVIEW      : 핀 순서/전이/셀 구성 차이, 미해석 행 또는 잔여 오차가 있음
        UNAVAILABLE : timing point의 Incr를 읽을 수 없어 상세 분해 불가
        EXCLUDED    : 양쪽에서 slack을 읽을 수 없어 기존 비교에서 제외됨

        EXPLAINED는 GT와 scaling 세션 설정이 같다는 뜻이 아니다. 기존
        CLOCK VALIDATION도 함께 확인한다. *_unexplained_error_ps는 알려진
        항목으로 설명하지 못한 차이이며, POCV나 SDC 문제라고 단정하지 않는다.
        *_residual_ps는 각각의 리포트 자체에서 합산되지 않은 나머지다.
        수치는 6자리 ns 보고서의 반올림 오차를 고려하되 원시 잔여값도 표시한다.

결과 해석
    error = PT scaling slack - ground-truth slack
    MAE   = path별 absolute error 평균
    p50/p90/p95/p99 = 경로의 50/90/95/99% 가 |error| 가 이 값 이하 (nearest-rank)
    bias  = signed error 평균. 양수면 scaling slack이 GT보다 크게 나온 것이다.

    Fixed-path WNS는 양쪽 report에서 slack을 읽을 수 있는 동일 path 집합의
    최소 slack이다. 디자인 전체 WNS가 아니며, 모든 slack이 양수이면 양수의
    최소값을 그대로 표시한다. 누락/미해결 path는 양쪽 WNS 계산에서 제외한다.
    PT와 GT의 최악 path는 서로 다를 수 있으므로 각각의 idx/key도 표시한다.

        WNS error          = PT scaling WNS - GT WNS
        WNS absolute error = |WNS error|
        WNS error (%)      = |WNS error| / |GT WNS| * 100

    GT WNS가 0이면 오차율은 N/A이며 summary.json에서는 null이다.
    제외 path가 있으면 WNS도 비교 가능한 부분 집합의 결과로 해석해야 한다.
    CLOCK VALIDATION의 INVALID/REVIEW 상태는 WNS 비교에도 동일하게 적용된다.
    실행 명령은 기존과 같고, 저장된 report만 있으면 PT를 다시 돌릴 필요가 없다.

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
    최신 run_scaling_after_restore.tcl 부산물은 결과 폴더의 details/에 저장된다.

        details/<scaling-result>.rpt.inputs.txt

    compare script가 이 파일을 찾으면 내용을 summary.txt 아래에 자동 복사한다.
    예전처럼 report 옆에 저장된 inputs.txt도 자동으로 찾는다.
    예전 scaling 결과에는 이 파일이 없으므로 input plan만 unavailable로 표시된다.

단위와 재실행
    입력 report의 slack/arrival/required 단위는 항상 ns로 읽고 결과는 ps로 쓴다.
    같은 명령을 다시 실행해도 기존 결과를 덮어쓰지 않고 _run2, _run3 폴더를
    만든다. Python 3.6 이상에서 동작하며 외부 package는 필요하지 않다.
"""

import argparse
import hashlib
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


# Report-only diagnostics. No PrimeTime session or external package is required.
STARTPOINT_RE = re.compile(r"^\s*Startpoint:\s*(.+?)(?:\s+\(|\s*$)")
DIAG_POINT_RE = re.compile(r"^\s*(.*?)\s+\(([^()]*)\)\s*(?:<-)?\s*(.*)$")
DIAG_SECTIONS = ("launch_clock", "data", "capture_clock")
DIAG_TERMS = (
    "launch_clock_cell", "launch_clock_net", "launch_clock_port",
    "launch_clock_source_latency", "launch_clock_network_delay",
    "data_cell", "data_net", "data_port", "input_external_delay",
    "capture_clock_cell", "capture_clock_net", "capture_clock_port",
    "capture_clock_source_latency", "capture_clock_network_delay",
    "clock_reconvergence_pessimism", "clock_uncertainty",
    "library_setup_time", "library_hold_time", "output_external_delay",
)
DIAG_ADJUSTMENTS = (
    (re.compile(r"^\s*clock source latency\b(.*)$", re.I), "source_latency"),
    (re.compile(r"^\s*clock network delay(?:\s*\([^)]*\))?\s+(.*)$", re.I), "network_delay"),
    (re.compile(r"^\s*input external delay\b(.*)$", re.I), "input_external_delay"),
    (re.compile(r"^\s*output external delay\b(.*)$", re.I), "output_external_delay"),
    (re.compile(r"^\s*clock reconvergence pessimism\b(.*)$", re.I), "clock_reconvergence_pessimism"),
    (re.compile(r"^\s*clock uncertainty\b(.*)$", re.I), "clock_uncertainty"),
    (re.compile(r"^\s*library setup time\b(.*)$", re.I), "library_setup_time"),
    (re.compile(r"^\s*library hold time\b(.*)$", re.I), "library_hold_time"),
)
DIAG_ARRIVAL_TERMS = DIAG_TERMS[:9]
DIAG_REQUIRED_TERMS = DIAG_TERMS[9:]


class ReportBreakdown(object):
    """Accumulate Incr sums and sequence fingerprints, without storing every point."""

    def __init__(self):
        self.section = "launch_clock"
        self.startpoint = None
        self.previous_instance = None
        self.arrival_seen = False
        self.finished = False
        self.incr_bounds = None
        self.components = {}
        self.point_counts = dict.fromkeys(DIAG_SECTIONS, 0)
        self.point_hashes = {key: hashlib.sha256() for key in DIAG_SECTIONS}
        self.library_hashes = {key: hashlib.sha256() for key in DIAG_SECTIONS}
        self.unparsed_point_rows = 0
        self.adjustment_rows = 0
        self.data_boundary_seen = False

    def add(self, name, value):
        self.components[name] = self.components.get(name, 0.0) + value

    def consume(self, raw_line):
        line = raw_line.expandtabs()
        match = STARTPOINT_RE.match(line)
        if match:
            self.startpoint = match.group(1).strip()
        if ARRIVAL_RE.match(line) and not self.arrival_seen:
            self.arrival_seen = True
            self.section = "capture_clock"
            self.previous_instance = None
            return
        if REQUIRED_RE.match(line):
            self.finished = True
        if self.finished:
            return
        if "Point" in line and "Incr" in line and "Path" in line:
            labels = list(re.finditer(r"\b[A-Za-z][A-Za-z0-9_]*\b", line))
            pos = next(i for i, label in enumerate(labels) if label.group() == "Incr")
            center = lambda label: (label.start() + label.end()) / 2.0
            self.incr_bounds = (
                (center(labels[pos - 1]) + center(labels[pos])) / 2.0,
                (center(labels[pos]) + center(labels[pos + 1])) / 2.0)
            return
        if CLOCK_EDGE_RE.match(line):
            # Ideal edge/cycle is a separate term, not a cell/net increment.
            return
        for pattern, name in DIAG_ADJUSTMENTS:
            match = pattern.match(line)
            if match:
                value = labeled_number(match)
                if value is not None:
                    if name in ("source_latency", "network_delay"):
                        name = self.section + "_" + name
                    if name == "input_external_delay":
                        self.section = "data"
                        self.data_boundary_seen = True
                    self.add(name, value)
                    self.adjustment_rows += 1
                return
        match = DIAG_POINT_RE.match(line)
        if match is None or self.incr_bounds is None:
            return
        point, library_cell, tail = match.groups()
        point = point.strip()
        library_kind = library_cell.lower()
        if library_kind == "net":
            self.previous_instance = None
        numbers = [m for m in NUMBER_RE.finditer(line, match.start(3))
                   if self.incr_bounds[0] <= (m.start() + m.end()) / 2.0 < self.incr_bounds[1]]
        if len(numbers) != 1:
            # Net-only rows normally have Cap/RC columns and no Incr; do not read RC as delay.
            if library_kind not in ("net", "in", "out"):
                self.unparsed_point_rows += 1
            return
        increment = float(numbers[0].group())
        instance = point.rsplit("/", 1)[0] if "/" in point else point
        if self.section != "capture_clock" and (
                "<-" in line or
                (self.startpoint is not None and instance == self.startpoint and
                 (self.previous_instance == instance or library_kind in ("in", "out")))):
            self.section = "data"
            self.data_boundary_seen = True
        kind = ("port" if library_kind in ("in", "out") else
                "net" if library_kind == "net" or self.previous_instance != instance else "cell")
        self.add(self.section + "_" + kind, increment)
        transition = re.search(r"(?:^|\s)([rf])\s*$", tail)
        identity = (point, kind, None if transition is None else transition.group(1))
        self.point_hashes[self.section].update(json.dumps(identity).encode("utf-8") + b"\n")
        self.library_hashes[self.section].update(json.dumps(library_cell).encode("utf-8") + b"\n")
        self.point_counts[self.section] += 1
        self.previous_instance = instance if library_kind != "net" else None

    def result(self):
        return {
            "components_ns": self.components,
            "point_counts": self.point_counts,
            "point_signatures": {key: value.hexdigest() for key, value in self.point_hashes.items()},
            "library_signatures": {key: value.hexdigest() for key, value in self.library_hashes.items()},
            "unparsed_point_rows": self.unparsed_point_rows,
            "adjustment_rows": self.adjustment_rows,
            "data_boundary_seen": self.data_boundary_seen,
        }


def diagnostic_metric(values):
    if not values:
        return {"count": 0, "mae_ps": None, "bias_ps": None, "max_abs_ps": None}
    return {"count": len(values), "mae_ps": sum(abs(v) for v in values) / len(values),
            "bias_ps": sum(values) / len(values), "max_abs_ps": max(abs(v) for v in values)}


def diagnose_paths(rows, scaled, truth, requested_analysis=None):
    """Explain reported errors using signed per-path sums, keeping unknown terms visible."""
    status_counts = {}
    for row in rows:
        if row["status"] != "compared":
            row["diagnostic"] = {"status": "EXCLUDED", "reasons": [row["status"]]}
            status_counts["EXCLUDED"] = status_counts.get("EXCLUDED", 0) + 1
            continue
        pred, gt = scaled[row["path_key"]], truth[row["path_key"]]
        pd, gd = pred.breakdown, gt.breakdown
        components = {}
        for term in DIAG_TERMS:
            values = [d["components_ns"].get(term) for d in (pd, gd)]
            pt_value, gt_value = [None if value is None else value * NS_TO_PS for value in values]
            components[term] = {"scaled_ps": pt_value, "ground_truth_ps": gt_value,
                                "error_ps": None if None in (pt_value, gt_value) else pt_value - gt_value}
        for name in ("launch", "capture"):
            clocks = (getattr(pred, name + "_clock"), getattr(gt, name + "_clock"))
            pt_value, gt_value = [None if clock is None else clock[2] * NS_TO_PS for clock in clocks]
            components[name + "_edge"] = {
                "scaled_ps": pt_value, "ground_truth_ps": gt_value,
                "error_ps": row[name + "_edge_error_ps"]}
        # Missing terms are N/A. A known-terms sum is partial and its remainder is explicit.
        known = {}
        for section, terms, edge in (("arrival", DIAG_ARRIVAL_TERMS, "launch_edge"),
                                     ("required", DIAG_REQUIRED_TERMS, "capture_edge")):
            known[section] = {}
            for side in ("scaled_ps", "ground_truth_ps"):
                edge_value = components[edge][side]
                known[section][side] = (None if edge_value is None else edge_value +
                    sum(components[term][side] for term in terms if components[term][side] is not None))
        path_types = {item.path_type for item in (pred, gt) if item.path_type is not None}
        analysis = requested_analysis
        if analysis is None and len(path_types) == 1:
            analysis = "setup" if next(iter(path_types)) == "max" else "hold"
        diagnostics = {"components": components, "reasons": [], "analysis": analysis,
                       "scaled_point_counts": pd["point_counts"], "ground_truth_point_counts": gd["point_counts"]}
        reasons = diagnostics["reasons"]
        for term, component in components.items():
            if (component["scaled_ps"] is None) != (component["ground_truth_ps"] is None):
                reasons.append(term + " unavailable in one report")
        all_points = sum(pd["point_counts"].values()) + sum(gd["point_counts"].values())
        # The scaling report prints 6 decimal places in ns (0.001 ps per row).
        # Include both reports' rows and adjustment rows; raw remainders are always output.
        tolerance = max(0.05, 0.001 * (all_points + pd["adjustment_rows"] + gd["adjustment_rows"] + 8))
        diagnostics["rounding_tolerance_ps"] = tolerance
        for section in DIAG_SECTIONS:
            if pd["point_signatures"][section] != gd["point_signatures"][section]:
                reasons.append(section + " point sequence/transition mismatch")
            if pd["library_signatures"][section] != gd["library_signatures"][section]:
                reasons.append(section + " library-cell sequence mismatch")
        if pd["unparsed_point_rows"] or gd["unparsed_point_rows"]:
            reasons.append("point rows without a readable Incr column")
        for side, item, detail in (("scaled_ps", pred, pd), ("ground_truth_ps", gt, gd)):
            if not detail["data_boundary_seen"]:
                reasons.append(side + " data boundary unavailable")
            for section in ("arrival", "required"):
                actual = getattr(item, section)
                if actual is None and section == "required" and item.arrival is not None and item.slack is not None:
                    if analysis == "setup":
                        actual = item.arrival + item.slack
                    elif analysis == "hold":
                        actual = item.arrival - item.slack
                observed = None if actual is None else actual * NS_TO_PS
                expected = known[section][side]
                residual = None if observed is None or expected is None else observed - expected
                diagnostics[side.replace("_ps", "") + "_" + section + "_residual_ps"] = residual
                if residual is not None and abs(residual) > tolerance:
                    reasons.append(side + " " + section + " has unexplained terms")
        for side, item in (("scaled", pred), ("ground_truth", gt)):
            residual = None
            if (item.arrival is not None and item.required is not None and item.slack is not None
                    and analysis in ("setup", "hold")):
                identity = item.required - item.arrival if analysis == "setup" else item.arrival - item.required
                residual = (item.slack - identity) * NS_TO_PS
                if abs(residual) > tolerance:
                    reasons.append(side + " slack has unexplained terms")
            diagnostics[side + "_slack_identity_residual_ps"] = residual
        for section in ("arrival", "required"):
            values = known[section]
            error = (None if None in values.values() else values["scaled_ps"] - values["ground_truth_ps"])
            observed_error = row[section + "_error_ps"]
            diagnostics[section + "_known_error_ps"] = error
            diagnostics[section + "_unexplained_error_ps"] = (
                None if error is None or observed_error is None else observed_error - error)
        for section in DIAG_SECTIONS:
            terms = [section + "_" + kind for kind in ("cell", "net", "port")]
            if section != "data":
                terms += [section + "_source_latency", section + "_network_delay"]
            values = []
            for side in ("scaled_ps", "ground_truth_ps"):
                values.append(sum(components[term][side] for term in terms if components[term][side] is not None))
            diagnostics[section + "_delay_error_ps"] = (
                values[0] - values[1] if pd["point_counts"][section] and gd["point_counts"][section] else None)
        arrival_known, required_known = diagnostics["arrival_known_error_ps"], diagnostics["required_known_error_ps"]
        slack_known = None
        if analysis in ("setup", "hold") and arrival_known is not None and required_known is not None:
            slack_known = required_known - arrival_known if analysis == "setup" else arrival_known - required_known
        diagnostics["slack_unexplained_error_ps"] = (
            None if slack_known is None else row["pt_scaling_err_ps"] - slack_known)
        diagnostics["slack_identity_residual_ps"] = None
        if analysis in ("setup", "hold") and row["arrival_error_ps"] is not None and row["required_error_ps"] is not None:
            identity = row["required_error_ps"] - row["arrival_error_ps"]
            if analysis == "hold":
                identity = -identity
            diagnostics["slack_identity_residual_ps"] = row["pt_scaling_err_ps"] - identity
            if abs(diagnostics["slack_identity_residual_ps"]) > tolerance:
                reasons.append("reported slack differs from arrival/required identity")
        for term, component in components.items():
            contribution = component["error_ps"]
            if contribution is not None and analysis in ("setup", "hold"):
                on_arrival = term in DIAG_ARRIVAL_TERMS or term == "launch_edge"
                contribution *= -1 if (on_arrival == (analysis == "setup")) else 1
            else:
                contribution = None
            component["slack_contribution_ps"] = contribution
        available = [term for term in components
                     if components[term]["slack_contribution_ps"] not in (None, 0.0)]
        diagnostics["largest_known_slack_term"] = (
            max(available, key=lambda term: abs(components[term]["slack_contribution_ps"])) if available else None)
        if pred.launch_clock_rows > 1 or pred.capture_clock_rows > 1 or gt.launch_clock_rows > 1 or gt.capture_clock_rows > 1:
            reasons.append("multiple ideal clock edges; generated-clock detail needs review")
        if row["clock_status"] == "mismatch" or row["path_type_mismatch"] or row["path_group_mismatch"]:
            reasons.append("clock/path identity mismatch")
        if slack_known is None:
            reasons.append("clock edges or analysis unavailable for full reconstruction")
        has_points = sum(pd["point_counts"].values()) and sum(gd["point_counts"].values())
        diagnostics["status"] = "UNAVAILABLE" if not has_points else "REVIEW" if reasons else "EXPLAINED"
        row["diagnostic"] = diagnostics
        status = diagnostics["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    compared = [row["diagnostic"] for row in rows if row["status"] == "compared"]
    fields = ("launch_clock_delay_error_ps", "data_delay_error_ps", "capture_clock_delay_error_ps",
              "arrival_unexplained_error_ps", "required_unexplained_error_ps", "slack_unexplained_error_ps")
    return {"status_counts": status_counts,
            "metrics": {field: diagnostic_metric([d[field] for d in compared if d[field] is not None]) for field in fields},
            "component_metrics": {term: diagnostic_metric([d["components"][term]["error_ps"] for d in compared
                if d["components"][term]["error_ps"] is not None]) for term in DIAG_TERMS}}


def diagnostic_share_line(detail):
    metrics = detail["metrics"]
    return (
        "DELAY_SHARE launch_sum_mae={}ps data_sum_mae={}ps capture_sum_mae={}ps "
        "arrival_unexplained_mae={}ps required_unexplained_mae={}ps review={} unavailable={}".format(
            compact_number(metrics["launch_clock_delay_error_ps"]["mae_ps"]),
            compact_number(metrics["data_delay_error_ps"]["mae_ps"]),
            compact_number(metrics["capture_clock_delay_error_ps"]["mae_ps"]),
            compact_number(metrics["arrival_unexplained_error_ps"]["mae_ps"]),
            compact_number(metrics["required_unexplained_error_ps"]["mae_ps"]),
            detail["status_counts"].get("REVIEW", 0), detail["status_counts"].get("UNAVAILABLE", 0)))


def diagnostic_summary_lines(summary):
    detail = summary.get("path_diagnostics")
    if detail is None:
        return ["Path delay reconstruction: unavailable"]
    lines = ["Path delay reconstruction (signed sums of reported Incr)",
             "Arithmetic closure is not proof of matching sessions; see CLOCK VALIDATION.",
             "diagnostic counts   : " + ", ".join("{}={}".format(k, v) for k, v in sorted(detail["status_counts"].items()))]
    labels = (("launch_clock_delay_error_ps", "launch clock sum"), ("data_delay_error_ps", "data path sum"),
              ("capture_clock_delay_error_ps", "capture clock sum"),
              ("arrival_unexplained_error_ps", "arrival unexplained"), ("required_unexplained_error_ps", "required unexplained"))
    for field, label in labels:
        value = detail["metrics"][field]
        lines.append("{:<21}: paths={} MAE={} ps max={} ps".format(
            label, value["count"], format_number(value["mae_ps"]), format_number(value["max_abs_ps"])))
    return lines


def write_path_diagnostics(path, rows):
    """Write detailed blocks by descending slack absolute error; preserve unavailable paths."""
    ordered = sorted(rows, key=lambda row: (row["abs_error_ps"] is None, -(row["abs_error_ps"] or 0.0), row["path_key"]))
    with path.open("w", encoding="ascii", errors="backslashreplace") as output:
        output.write("# All numbers: ps; error = scaling - GT. Order: slack absolute error descending.\n")
        output.write("# N/A: absent/unreadable term, never a measured zero. Net: report sink increment, not raw SPEF RC.\n")
        output.write("# EXPLAINED means arithmetic closes within rounding tolerance, not validated scaling accuracy.\n")
        output.write("# Residuals include unreported/unparsed terms, statistical adjustments and rounding; do not name a cause from residual alone.\n\n")
        for row in ordered:
            detail = row["diagnostic"]
            output.write("### PATH idx={} key={}\n".format(row["idx"], row["path_key"]))
            output.write("status={} slack_error={} ps arrival_error={} ps required_error={} ps\n".format(
                detail["status"], format_number(row["pt_scaling_err_ps"]), format_number(row["arrival_error_ps"]), format_number(row["required_error_ps"])))
            if "components" not in detail:
                output.write("reason={}\n\n".format("; ".join(detail["reasons"])))
                continue
            output.write("analysis={} rounding_tolerance={} ps\n".format(detail["analysis"], format_number(detail["rounding_tolerance_ps"])))
            driver = detail["largest_known_slack_term"]
            if driver is not None:
                output.write("largest_known_slack_term={} contribution={} ps\n".format(driver, format_number(detail["components"][driver]["slack_contribution_ps"])))
            output.write("{:<36} {:>15} {:>15} {:>15}\n".format("term", "GT", "scaling", "error"))
            terms = ("launch_edge",) + DIAG_ARRIVAL_TERMS + ("capture_edge",) + DIAG_REQUIRED_TERMS
            for term in terms:
                values = detail["components"][term]
                output.write("{:<36} {:>15} {:>15} {:>15}\n".format(term, *(
                    "N/A" if values[key] is None else "{:+.6f}".format(values[key])
                    for key in ("ground_truth_ps", "scaled_ps", "error_ps"))))
            for field in ("arrival_unexplained_error_ps", "required_unexplained_error_ps", "slack_unexplained_error_ps",
                          "scaled_arrival_residual_ps", "ground_truth_arrival_residual_ps", "scaled_required_residual_ps",
                          "ground_truth_required_residual_ps", "slack_identity_residual_ps",
                          "scaled_slack_identity_residual_ps", "ground_truth_slack_identity_residual_ps"):
                value = detail[field]
                output.write("{:<36}: {} ps\n".format(field, "N/A" if value is None else "{:+.6f}".format(value)))
            output.write("points GT={} scaling={}\n".format(detail["ground_truth_point_counts"], detail["scaled_point_counts"]))
            output.write("reason={}\n\n".format("; ".join(detail["reasons"]) or "reported terms reconstruct arrival/required within rounding tolerance"))


class PathResult(object):
    """One fixed-path result; kept simple for Synopsys Python 3.6."""

    __slots__ = (
        "idx", "key", "slack", "arrival", "required", "path_type",
        "path_group", "launch_clock", "capture_clock",
        "launch_clock_rows", "capture_clock_rows", "breakdown")

    def __init__(self, idx, key, slack, arrival=None, required=None, path_type=None,
                 path_group=None, launch_clock=None, capture_clock=None,
                 launch_clock_rows=0, capture_clock_rows=0, breakdown=None):
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
        self.breakdown = breakdown if breakdown is not None else ReportBreakdown().result()


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
    current_breakdown = ReportBreakdown()

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
            current_launch_clock_rows, current_capture_clock_rows, current_breakdown.result())

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
                current_breakdown = ReportBreakdown()
                continue
            if current_key is not None:
                current_breakdown.consume(line)
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


DIST_PERCENTILES = (50, 90, 95, 99)


def abs_error_percentiles(values):
    """Nearest-rank percentiles of |error|: pNN = NN% of paths have |error| <= value."""
    ordered = sorted(abs(value) for value in values)
    result = {}
    for percent in DIST_PERCENTILES:
        key = "p%d" % percent
        if not ordered:
            result[key] = None
        else:
            result[key] = ordered[max(0, int(math.ceil(percent / 100.0 * len(ordered))) - 1)]
    return result


def percentile_text(dist):
    """'p50 / p90 / p95 / p99' values in ps, NA when unavailable."""
    parts = []
    for percent in DIST_PERCENTILES:
        value = None if dist is None else dist.get("p%d" % percent)
        parts.append("NA" if value is None else "%.3f" % value)
    return " / ".join(parts)


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
    # Use the same resolved path set for both minima, even if the worst paths differ.
    gt_wns_row = min(compared_rows, key=lambda row: row["ground_truth_ps"])
    pt_wns_row = min(compared_rows, key=lambda row: row["pt_scaling_ps"])
    gt_wns = gt_wns_row["ground_truth_ps"]
    pt_wns = pt_wns_row["pt_scaling_ps"]
    wns_error = pt_wns - gt_wns
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
        "abs_error_percentiles_ps": abs_error_percentiles(abs_errors),
        "worst_path_key": worst_row["path_key"],
        "wns_scope": "shared_resolved_fixed_paths",
        "wns_definition": "minimum slack without clamping to zero",
        "ground_truth_wns_ps": gt_wns,
        "pt_scaling_wns_ps": pt_wns,
        "wns_error_ps": wns_error,
        "wns_abs_error_ps": abs(wns_error),
        "wns_error_percent": (
            abs(wns_error) / abs(gt_wns) * 100.0 if gt_wns != 0.0 else None),
        "ground_truth_wns_path_idx": truth[gt_wns_row["path_key"]].idx,
        "ground_truth_wns_path_key": gt_wns_row["path_key"],
        "pt_scaling_wns_path_idx": scaled[pt_wns_row["path_key"]].idx,
        "pt_scaling_wns_path_key": pt_wns_row["path_key"],
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
        f"analysis            : {summary.get('analysis', 'unavailable')}",
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
        f"|error| p50/p90/p95/p99: {percentile_text(summary.get('abs_error_percentiles_ps'))} ps",
        f"worst path key      : {summary['worst_path_key']}",
        component_line("arrival", summary),
        component_line("required", summary),
        "",
    ] + violation_lines(summary.get("violation_raw")) + wns_lines(summary) + [""] + diagnostic_summary_lines(summary) + period_alignment_lines(summary) + [
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
            "unavailable: <scaled-report>.inputs.txt was not found in details/ or beside the report",
        ])
    path.write_text("\n".join(lines) + "\n")


def wns_lines(summary):
    """Format minimum-slack metrics over the same compared fixed paths."""
    percent = summary["wns_error_percent"]
    percent_text = (
        "N/A (GT WNS is zero)" if percent is None else f"{percent:.6f} %")
    return [
        "Fixed-path WNS (minimum slack; not clamped to zero)",
        "WNS scope           : same compared fixed paths; not design-wide WNS",
        f"WNS coverage        : {summary['compared_paths']} compared, "
        f"{summary['excluded_paths']} excluded",
        f"PT scaling WNS      : {summary['pt_scaling_wns_ps']:+.6f} ps",
        f"GT WNS              : {summary['ground_truth_wns_ps']:+.6f} ps",
        f"WNS error (PT - GT) : {summary['wns_error_ps']:+.6f} ps",
        f"WNS absolute error  : {summary['wns_abs_error_ps']:.6f} ps",
        f"WNS error (%)       : {percent_text}",
        f"PT WNS path         : idx={summary['pt_scaling_wns_path_idx']} "
        f"key={summary['pt_scaling_wns_path_key']}",
        f"GT WNS path         : idx={summary['ground_truth_wns_path_idx']} "
        f"key={summary['ground_truth_wns_path_key']}",
    ]


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
            f"DIST_SHARE p50/p90/p95/p99={percentile_text(summary.get('abs_error_percentiles_ps')).replace(' ', '')}ps "
            f"paths={summary['compared_paths']}"),
        (
            f"ERROR_SHARE slack_mae={compact_number(summary['mae_ps'])}ps "
            f"arrival_mae={compact_number(summary['arrival_mae_ps'])}ps "
            f"required_mae={compact_number(summary['required_mae_ps'])}ps "
            f"paths={summary['compared_paths']} excluded={summary['excluded_paths']}"),
        (
            f"WNS_SHARE scope=fixed_paths "
            f"pt={compact_number(summary['pt_scaling_wns_ps'])}ps "
            f"gt={compact_number(summary['ground_truth_wns_ps'])}ps "
            f"abs_error={compact_number(summary['wns_abs_error_ps'])}ps "
            f"error_percent={compact_number(summary['wns_error_percent'])} "
            f"paths={summary['compared_paths']} excluded={summary['excluded_paths']}"),
    ] + ([diagnostic_share_line(summary["path_diagnostics"])] if "path_diagnostics" in summary else []) + (
        [f"ALIGNED_SHARE mae={compact_number(summary['period_alignment']['mae_ps'])}ps "
         f"bias={compact_number(summary['period_alignment']['bias_ps'])}ps "
         f"p90={compact_number(summary['period_alignment']['abs_error_percentiles_ps']['p90'])}ps "
         f"p99={compact_number(summary['period_alignment']['abs_error_percentiles_ps']['p99'])}ps "
         f"aligned={summary['period_alignment']['counts']['aligned']} "
         f"clock_mismatch={summary['period_alignment']['counts']['clock_mismatch']}"]
        if summary.get("period_alignment") else []) + [
        f"VIOL_SHARE basis={item['basis']} gt={item['gt_viol']} pt={item['pt_viol']} hit={item['hit']} "
        f"missed={item['missed']} false_alarm={item['false_alarm']} "
        f"mae_viol={compact_number(item['viol']['mae_ps'])}ps mae_met={compact_number(item['met']['mae_ps'])}ps"
        for item in (summary.get("violation_raw"), summary.get("violation_aligned")) if item]


def safe_corner_name(report_path):
    """Return a filesystem-safe target-corner name from the GT report name."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", report_path.stem).strip("._")
    return name or "target_corner"


def resolve_output_analysis(scaled, truth, requested_analysis):
    """Choose the setup/hold output directory without guessing from report names."""
    if requested_analysis is not None:
        return requested_analysis
    # 명령행 지정이 없으면 양쪽 report에서 읽은 Path Type으로 폴더를 결정한다.
    # 정보가 없거나 max/min이 섞인 경우 setup을 임의의 기본값으로 선택하지 않는다.
    path_types = {item.path_type for report in (scaled, truth) for item in report.values()
                  if item.path_type is not None}
    if path_types == {"max"}:
        return "setup"
    if path_types == {"min"}:
        return "hold"
    raise ValueError(
        "Cannot determine one analysis type from Path Type rows. "
        "Pass --analysis setup or --analysis hold explicitly.")


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


def period_alignment(rows, analysis):
    """Remove each path's ideal clock-edge difference from its slack error.

    The scaled run keeps the restored (link-corner) SDC while the ground truth
    uses the target corner's SDC, so clock periods can differ. Each path uses
    its OWN launch/capture edge times from both reports, so several clocks,
    generated clocks and multicycle paths need no global period. Paths whose
    clock name, edge type, path group or path type differ, or with several
    ideal edges, are not aligned and are counted instead.
    """
    counts = {"aligned": 0, "clock_mismatch": 0, "multi_edge": 0, "edge_unavailable": 0}
    aligned = []
    shifts_by_pair = {}
    for row in rows:
        row["period_shift_ps"] = None
        row["aligned_err_ps"] = None
        row["alignment_status"] = None
        if row["pt_scaling_err_ps"] is None:
            continue
        if (analysis not in ("setup", "hold") or row["launch_edge_error_ps"] is None or
                row["capture_edge_error_ps"] is None):
            row["alignment_status"] = "edge_unavailable"
        elif row["clock_status"] != "match":
            row["alignment_status"] = "clock_mismatch"
        elif row["launch_clock_ambiguous"] or row["capture_clock_ambiguous"]:
            row["alignment_status"] = "multi_edge"
        else:
            row["alignment_status"] = "aligned"
        counts[row["alignment_status"]] += 1
        if row["alignment_status"] != "aligned":
            continue
        if analysis == "setup":
            # setup slack = required - arrival
            shift = row["capture_edge_error_ps"] - row["launch_edge_error_ps"]
        else:
            # hold slack = arrival - required
            shift = row["launch_edge_error_ps"] - row["capture_edge_error_ps"]
        row["period_shift_ps"] = shift
        row["aligned_err_ps"] = row["pt_scaling_err_ps"] - shift
        aligned.append(row)
        pair = "{}->{}".format(row["scaled_launch_clock"][0], row["scaled_capture_clock"][0])
        shifts_by_pair.setdefault(pair, []).append(shift)
    result = {"analysis": analysis, "counts": counts, "paths": len(aligned),
              "mae_ps": None, "rmse_ps": None, "bias_ps": None,
              "worst_abs_error_ps": None, "worst_idx": None, "worst_path_key": None,
              "abs_error_percentiles_ps": abs_error_percentiles([]),
              "shift_by_clock_pair": []}
    if aligned:
        errors = [row["aligned_err_ps"] for row in aligned]
        worst = max(aligned, key=lambda row: abs(row["aligned_err_ps"]))
        result.update({
            "mae_ps": sum(abs(e) for e in errors) / len(errors),
            "rmse_ps": (sum(e * e for e in errors) / len(errors)) ** 0.5,
            "bias_ps": sum(errors) / len(errors),
            "worst_abs_error_ps": abs(worst["aligned_err_ps"]),
            "abs_error_percentiles_ps": abs_error_percentiles(errors),
            "worst_idx": worst["idx"], "worst_path_key": worst["path_key"]})
    for pair in sorted(shifts_by_pair, key=lambda name: -len(shifts_by_pair[name])):
        values = shifts_by_pair[pair]
        result["shift_by_clock_pair"].append({
            "clocks": pair, "paths": len(values), "mean_ps": sum(values) / len(values),
            "min_ps": min(values), "max_ps": max(values)})
    return result


def period_alignment_lines(summary):
    """Text block for --align-period; empty when the option was not used."""
    detail = summary.get("period_alignment")
    if detail is None:
        return []
    counts = detail["counts"]
    lines = ["", "=== PERIOD-ALIGNED (--align-period) ===",
             "slack error minus each path's own clock-edge difference (scaled SDC vs GT SDC);",
             "this is the scaling-only error when the two corners differ only in clock period.",
             f"aligned paths       : {counts['aligned']} (not aligned: clock_mismatch={counts['clock_mismatch']} "
             f"multi_edge={counts['multi_edge']} edge_unavailable={counts['edge_unavailable']})"]
    if detail["mae_ps"] is None:
        lines.append("aligned MAE         : unavailable (no path could be aligned)")
        return lines + violation_lines(summary.get("violation_aligned"))
    lines.extend([
        f"aligned MAE         : {detail['mae_ps']:.3f} ps",
        f"aligned RMSE        : {detail['rmse_ps']:.3f} ps",
        f"aligned bias        : {detail['bias_ps']:+.3f} ps",
        f"aligned worst       : {detail['worst_abs_error_ps']:.3f} ps idx={detail['worst_idx']}",
        f"aligned p50/p90/p95/p99: {percentile_text(detail['abs_error_percentiles_ps'])} ps",
        "edge shift removed by clock pair (scaled - GT):"])
    for item in detail["shift_by_clock_pair"][:10]:
        lines.append(f"  {item['clocks']:<40} paths={item['paths']} mean={item['mean_ps']:+.3f} ps "
                     f"range=[{item['min_ps']:+.3f},{item['max_ps']:+.3f}] ps")
    if len(detail["shift_by_clock_pair"]) > 10:
        lines.append(f"  ... {len(detail['shift_by_clock_pair']) - 10} more clock pair(s) in summary.json")
    return lines + [""] + violation_lines(summary.get("violation_aligned"))


def write_period_aligned(path, rows):
    """Per-path raw error, removed edge shift and aligned error (|aligned| descending)."""
    ordered = sorted(
        [row for row in rows if row.get("alignment_status")],
        key=lambda row: (row["aligned_err_ps"] is None, -abs(row["aligned_err_ps"] or 0.0), row["path_key"]))
    with path.open("w") as output:
        output.write("# All values: ps. aligned_err = slack_err - edge_shift (scaled - GT).\n")
        output.write(f"{'idx':>7} {'slack_err':>13} {'edge_shift':>13} {'aligned_err':>13} "
                     f"{'status':<17} path_key\n")
        for row in ordered:
            output.write(f"{row['idx']:>7} {format_number(row['pt_scaling_err_ps']):>13} "
                         f"{format_number(row['period_shift_ps']):>13} "
                         f"{format_number(row['aligned_err_ps']):>13} "
                         f"{row['alignment_status']:<17} {row['path_key']}\n")


def violation_summary(rows, use_aligned):
    """Pass/fail agreement (slack < 0 = violated) and error split by the GT verdict.

    use_aligned: judge PT on its period-aligned slack (PT slack - edge shift) and
    use the aligned error; only paths that could be aligned are counted.
    """
    counts = {"paths": 0, "gt_viol": 0, "pt_viol": 0, "hit": 0, "missed": 0,
              "false_alarm": 0, "ok": 0}
    errors = {"viol": [], "met": []}
    missed, false_alarm = [], []
    for row in rows:
        if row["abs_error_ps"] is None:
            continue
        if use_aligned:
            if row.get("aligned_err_ps") is None:
                continue
            error = row["aligned_err_ps"]
        else:
            error = row["pt_scaling_err_ps"]
        gt = row["ground_truth_ps"]
        pt = gt + error
        gt_viol, pt_viol = gt < 0, pt < 0
        counts["paths"] += 1
        counts["gt_viol"] += gt_viol
        counts["pt_viol"] += pt_viol
        if gt_viol and pt_viol:
            counts["hit"] += 1
        elif gt_viol:
            counts["missed"] += 1
            missed.append((gt, row["idx"]))
        elif pt_viol:
            counts["false_alarm"] += 1
            false_alarm.append((gt, row["idx"]))
        else:
            counts["ok"] += 1
        errors["viol" if gt_viol else "met"].append(error)
    result = dict(counts, basis="aligned" if use_aligned else "raw")
    for name, values in errors.items():
        result[name] = {"paths": len(values),
                        "mae_ps": sum(abs(v) for v in values) / len(values) if values else None,
                        "bias_ps": sum(values) / len(values) if values else None}
    # Most-violating GT first for missed; closest-to-zero GT first for false alarms.
    result["missed_idx"] = [idx for _, idx in sorted(missed)][:20]
    result["false_alarm_idx"] = [idx for _, idx in sorted(false_alarm, key=lambda item: item[0])][:20]
    return result


def violation_lines(detail):
    """Text block for one violation_summary; empty when absent."""
    if not detail:
        return []
    label = "aligned " if detail["basis"] == "aligned" else ""
    viol, met = detail["viol"], detail["met"]
    lines = [
        f"{label}violations (slack<0) GT -> PT: {detail['gt_viol']} -> {detail['pt_viol']}  "
        f"hit={detail['hit']} missed={detail['missed']} false_alarm={detail['false_alarm']} "
        f"(of {detail['paths']} paths)",
        f"{label}GT violated paths : {viol['paths']:>6}  MAE={compact_number(viol['mae_ps'])} ps "
        f"bias={compact_number(viol['bias_ps'])} ps",
        f"{label}GT met paths      : {met['paths']:>6}  MAE={compact_number(met['mae_ps'])} ps "
        f"bias={compact_number(met['bias_ps'])} ps"]
    if detail["missed_idx"]:
        lines.append(f"{label}missed idx (GT fails, PT passes; first 20): " + " ".join(str(i) for i in detail["missed_idx"]))
    if detail["false_alarm_idx"]:
        lines.append(f"{label}false-alarm idx (GT passes, PT fails; first 20): " +
                     " ".join(str(i) for i in detail["false_alarm_idx"]))
    return lines + [""]


BREAKDOWN_GROUPS = (
    ("edge", ("launch_edge", "capture_edge")),
    ("launch_clk", ("launch_clock_cell", "launch_clock_net", "launch_clock_port",
                    "launch_clock_source_latency", "launch_clock_network_delay")),
    ("data", ("data_cell", "data_net", "data_port", "input_external_delay")),
    ("capture_clk", ("capture_clock_cell", "capture_clock_net", "capture_clock_port",
                     "capture_clock_source_latency", "capture_clock_network_delay")),
    ("constraint", ("clock_reconvergence_pessimism", "clock_uncertainty", "library_setup_time",
                    "library_hold_time", "output_external_delay")),
)


def breakdown_values(row):
    """Slack contribution (ps) of each term group; the groups plus 'unexplained' sum to the slack error."""
    detail = row.get("diagnostic") or {}
    components = detail.get("components")
    if not components:
        return None
    values = {}
    for name, terms in BREAKDOWN_GROUPS:
        parts = [components[term]["slack_contribution_ps"] for term in terms
                 if term in components and components[term].get("slack_contribution_ps") is not None]
        values[name] = sum(parts) if parts else None
    values["unexplained"] = detail.get("slack_unexplained_error_ps")
    # The edge is the clock-period gap, not a delay source: pick the largest of the rest.
    sources = [name for name in ("launch_clk", "data", "capture_clk", "constraint", "unexplained")
               if values.get(name) not in (None, 0.0)]
    values["main_source"] = max(sources, key=lambda name: abs(values[name])) if sources else None
    return values


def write_path_breakdown(path, rows):
    """One line per compared path showing where its slack error comes from.

    Columns are slack contributions in ps (scaled - GT, signed as they move the
    slack), so edge + launch_clk + data + capture_clk + constraint + unexplained
    = slack_err. main_source = the largest group other than the clock edge.
    Order: |aligned_err| (or |slack_err|) descending.
    """
    compared = [row for row in rows if row["abs_error_ps"] is not None]

    def size(row):
        value = row.get("aligned_err_ps")
        return abs(value) if value is not None else row["abs_error_ps"]

    with path.open("w") as output:
        output.write("# Slack contributions in ps (scaled - GT). edge+launch_clk+data+capture_clk+constraint+unexplained = slack_err.\n")
        output.write("# aligned = slack_err - edge (NA without a usable clock edge). Order: |aligned| (or |slack_err|) descending.\n")
        output.write(f"{'idx':>7} {'gt_slack':>11} {'slack_err':>10} {'edge':>10} {'aligned':>10} "
                     f"{'launch_clk':>10} {'data':>10} {'capture_clk':>11} {'constraint':>10} "
                     f"{'unexplained':>11} {'main_source':<12} path_key\n")
        for row in sorted(compared, key=lambda item: (-size(item), item["path_key"])):
            values = breakdown_values(row) or {}

            def cell(name, width):
                value = values.get(name)
                return ("NA" if value is None else "%+.3f" % value).rjust(width)
            aligned = row.get("aligned_err_ps")
            output.write(f"{row['idx']:>7} {format_number(row['ground_truth_ps']):>11} "
                         f"{format_number(row['pt_scaling_err_ps']):>10} {cell('edge', 10)} "
                         f"{('NA' if aligned is None else '%+.3f' % aligned):>10} "
                         f"{cell('launch_clk', 10)} {cell('data', 10)} {cell('capture_clk', 11)} "
                         f"{cell('constraint', 10)} {cell('unexplained', 11)} "
                         f"{str(values.get('main_source') or 'NA'):<12} {row['path_key']}\n")


def main():
    parser = argparse.ArgumentParser(
        description="PrimeTime scaling slack\uc640 \uc2e4\uc81c target-corner slack\uc758 path\ubcc4 MAE\ub97c \uacc4\uc0b0\ud569\ub2c8\ub2e4.")
    parser.add_argument("scaled_rpt", type=Path, help="run_scaling_after_restore.tcl \uacb0\uacfc .rpt")
    parser.add_argument("ground_truth_rpt", type=Path, help="\uc2e4\uc81c target library\ub85c \uce21\uc815\ud55c fixed-path .rpt")
    parser.add_argument("--output-dir", type=Path, default=Path("pt_scaling_comparison"),
                        help="\ucf54\ub108\ubcc4 \uacb0\uacfc\ub97c \uc800\uc7a5\ud560 \uc0c1\uc704 \ud3f4\ub354 (\uae30\ubcf8\uac12: pt_scaling_comparison)")
    parser.add_argument("--analysis", choices=("setup", "hold"), default=None,
                        help="Setup/hold analysis and output subdirectory; infer from Path Type when omitted")
    parser.add_argument("--align-period", action="store_true",
                        help="Also report MAE after removing each path's clock-edge (period) difference "
                             "between the scaled and ground-truth reports")
    args = parser.parse_args()

    for path in (args.scaled_rpt, args.ground_truth_rpt):
        if not path.is_file():
            parser.error(f"file not found: {path}")

    scaled = parse_report(args.scaled_rpt)
    truth = parse_report(args.ground_truth_rpt)
    try:
        analysis_type = resolve_output_analysis(scaled, truth, args.analysis)
    except ValueError as error:
        parser.error(str(error))
    rows, summary = evaluate(scaled, truth, NS_TO_PS, args.analysis)
    summary["path_diagnostics"] = diagnose_paths(rows, scaled, truth, args.analysis)
    summary.update({
        "input_unit": "ns",
        "output_unit": "ps",
        "analysis": analysis_type,
        "analysis_source": "command_line" if args.analysis is not None else "report_path_type",
        "scaled_report": str(args.scaled_rpt.resolve()),
        "ground_truth_report": str(args.ground_truth_rpt.resolve()),
    })
    scaling_inputs_path = args.scaled_rpt.parent / "details" / (args.scaled_rpt.name + ".inputs.txt")
    if not scaling_inputs_path.is_file():
        scaling_inputs_path = Path(str(args.scaled_rpt) + ".inputs.txt")
    if scaling_inputs_path.is_file():
        summary["scaling_input_plan_path"] = str(scaling_inputs_path.resolve())
        summary["scaling_input_plan"] = scaling_inputs_path.read_text(errors="ignore")
    else:
        summary["scaling_input_plan_path"] = None
        summary["scaling_input_plan"] = None
    if args.align_period:
        summary["period_alignment"] = period_alignment(rows, analysis_type)
        summary["violation_aligned"] = violation_summary(rows, True)
    summary["violation_raw"] = violation_summary(rows, False)

    corner_name = safe_corner_name(args.ground_truth_rpt)
    # 출력 폴더 -> setup/hold -> 코너 순서로 저장하고 재실행은 해당 타입 안에서 _run2를 만든다.
    result_dir = create_result_dir(args.output_dir / analysis_type, corner_name)
    path_text_path = result_dir / "path_errors.txt"
    diagnostics_path = result_dir / "path_diagnostics.txt"
    summary_text_path = result_dir / "summary.txt"
    json_path = result_dir / "summary.json"
    write_path_text(path_text_path, rows)
    write_path_diagnostics(diagnostics_path, rows)
    write_summary_text(summary_text_path, summary)
    aligned_path = result_dir / "period_aligned.txt"
    if args.align_period:
        write_period_aligned(aligned_path, rows)
    breakdown_path = result_dir / "path_breakdown.txt"
    write_path_breakdown(breakdown_path, rows)
    with json_path.open("w") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False)

    print("=== PrimeTime scaling vs ground truth ===")
    print(f"analysis       : {analysis_type}")
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
    print(f"p50/p90/p95/p99: {percentile_text(summary.get('abs_error_percentiles_ps'))} ps")
    print(component_line("arrival", summary))
    print(component_line("required", summary))
    print("")
    for line in violation_lines(summary.get("violation_raw")):
        print(line)
    for line in wns_lines(summary):
        print(line)
    print("")
    for line in diagnostic_summary_lines(summary):
        print(line)
    for line in period_alignment_lines(summary):
        print(line)
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
    print(f"diagnostics txt: {diagnostics_path}")
    print(f"summary text   : {summary_text_path}")
    print(f"summary JSON   : {json_path}")
    if args.align_period:
        print(f"period aligned : {aligned_path}")
    print(f"path breakdown : {breakdown_path}")
    print("")
    print("=== COPY THIS RESULT ===")
    for line in share_lines(summary):
        print(line)


if __name__ == "__main__":
    main()
