#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ground-truth fixed-path slack의 통계와 분포 그림을 만든다.

가장 자주 쓰는 명령
    pt_si_re 디렉터리에서 ground truth report 여러 개를 한꺼번에 지정한다.

    python3 analysis/plot_ground_truth_slack.py \
        ground_truth/*.rpt \
        --input-unit ns \
        --output-dir results/ground_truth_slack

    report 하나만 볼 때도 사용법은 같다.

    python3 analysis/plot_ground_truth_slack.py \
        ground_truth/SSPG_0p5V_25C_rcmax_hold.rpt \
        --output-dir results/one_corner

입력
    fixed_paths.tcl로 측정한 ground-truth .rpt 파일을 하나 이상 준다. 각 경로
    앞에 다음 마커가 있어야 한다.

        ### FIXED_PATH idx=... key=...

    여러 report가 완전히 같은 path 집합일 필요는 없다. 이 스크립트는 각
    report의 분포를 독립적으로 계산한다. 다만 코너끼리 공정하게 비교하려면
    같은 fixed_paths.tcl로 만든 report를 넣는 것이 좋다.

시간 단위와 포함 기준
    --input-unit은 report slack 숫자의 단위이며 기본값은 ns다. 모든 CSV,
    터미널 표와 SVG의 값은 ps로 변환된다. slack을 읽지 못한 path block은
    unresolved로 세지만 평균과 분포 계산에서는 제외한다.

통계 의미
    mean    평균 slack
    median  정렬했을 때 중앙값
    stddev  모집단 표준편차
    min/max 최솟값/최댓값
    p05/p95 하위 5%/95% 위치
    q1/q3   하위 25%/75% 위치
    violated_paths  slack < 0인 path 수

출력
    --output-dir results/ground_truth_slack을 주면 아래 다섯 파일을 만든다.
    폴더가 없으면 자동 생성하며, 같은 이름의 기존 파일은 덮어쓴다.

    ground_truth_slack_summary.csv
        report별 평균, median, 표준편차, min/q1/q3/max, 위반 path 수

    ground_truth_path_slacks.csv
        report와 path별 slack(ps), resolved/unresolved 상태

    ground_truth_slack_distribution.svg
        모든 report에 동일한 slack 구간을 적용한 histogram

    ground_truth_slack_boxplot.svg
        min, Q1, median, Q3, max와 평균을 비교하는 box plot

    ground_truth_slack_terminal.txt
        GUI나 VS Code 없이 less로 확인할 수 있는 텍스트 histogram

결과 확인
    column -s, -t results/ground_truth_slack/ground_truth_slack_summary.csv | less -S
    less -S results/ground_truth_slack/ground_truth_slack_terminal.txt

histogram 막대가 너무 거칠거나 촘촘하면 --bins를 바꾼다. 기본값은 30이며
2 이상이어야 한다.

필요 환경
    Python 3.6 이상. matplotlib 등 외부 패키지는 필요 없다. SVG 파일도
    Python 표준 라이브러리만으로 생성한다.
"""

import argparse
import csv
import html
import math
import statistics
from pathlib import Path

from compare_scaling_mae import TO_PS, parse_report


class ReportData(object):
    """Resolved values and counts for one report; compatible with Python 3.6."""

    __slots__ = ("label", "path", "total", "unresolved", "values_ps")

    def __init__(self, label, path, total, unresolved, values_ps):
        self.label = label
        self.path = path
        self.total = total
        self.unresolved = unresolved
        self.values_ps = values_ps


def percentile(values, percent):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def unique_labels(paths):
    stems = [path.stem for path in paths]
    counts = {}
    labels = []
    for path, stem in zip(paths, stems):
        counts[stem] = counts.get(stem, 0) + 1
        labels.append(stem if stems.count(stem) == 1 else f"{stem}_{counts[stem]}")
    return labels


def load_reports(paths, factor):
    reports = []
    path_rows = []
    for label, path in zip(unique_labels(paths), paths):
        parsed = parse_report(path)
        values = []
        for item in sorted(parsed.values(), key=lambda result: result.idx):
            slack_ps = None if item.slack is None else item.slack * factor
            if slack_ps is not None:
                values.append(slack_ps)
            path_rows.append({
                "report": label,
                "source_report": str(path.resolve()),
                "idx": item.idx,
                "path_key": item.key,
                "slack_ps": slack_ps,
                "status": "resolved" if slack_ps is not None else "unresolved",
            })
        if not values:
            raise ValueError(f"no resolved slack values: {path}")
        reports.append(ReportData(
            label=label,
            path=path.resolve(),
            total=len(parsed),
            unresolved=len(parsed) - len(values),
            values_ps=values,
        ))
    return reports, path_rows


def summary_row(report):
    values = report.values_ps
    return {
        "report": report.label,
        "source_report": str(report.path),
        "total_blocks": report.total,
        "resolved_paths": len(values),
        "unresolved_paths": report.unresolved,
        "mean_ps": sum(values) / len(values),
        "median_ps": statistics.median(values),
        "stddev_ps": statistics.pstdev(values),
        "min_ps": min(values),
        "p05_ps": percentile(values, 5),
        "q1_ps": percentile(values, 25),
        "q3_ps": percentile(values, 75),
        "p95_ps": percentile(values, 95),
        "max_ps": max(values),
        "violated_paths": sum(value < 0.0 for value in values),
    }


def write_csv(path, rows, columns):
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: f"{value:.6f}" if isinstance(value, float) else
                "" if value is None else value
                for key, value in row.items()
            })


def svg_text(x, y, text, size=13, anchor="start", weight="normal", color="#172033"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}" fill="{color}">'
            f'{html.escape(text)}</text>')


def nice_ticks(low, high, count=6):
    if low == high:
        return [low]
    raw = (high - low) / max(count - 1, 1)
    power = 10 ** math.floor(math.log10(raw))
    normalized = raw / power
    step = (1 if normalized <= 1 else 2 if normalized <= 2 else
            5 if normalized <= 5 else 10) * power
    start = math.ceil(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 1e-9:
        ticks.append(value)
        value += step
    return ticks


def histogram(values, low, high, bins):
    counts = [0] * bins
    span = high - low
    for value in values:
        index = min(bins - 1, max(0, int((value - low) / span * bins)))
        counts[index] += 1
    return counts


def write_terminal_histogram(path, reports, bins):
    """Write a fixed-width ASCII histogram that can be read with cat/less."""
    all_values = [value for report in reports for value in report.values_ps]
    low, high = min(all_values), max(all_values)
    if low == high:
        margin = max(abs(low) * 0.05, 1.0)
        low, high = low - margin, high + margin
    bin_width = (high - low) / bins
    bar_width = 42
    lines = [
        "GROUND-TRUTH FIXED-PATH SLACK DISTRIBUTIONS",
        "All reports use the same Slack(ps) bins. Resolved paths only.",
        "A '<0>' marker means that the bin contains 0 ps.",
        "",
    ]
    for report in reports:
        row = summary_row(report)
        counts = histogram(report.values_ps, low, high, bins)
        max_count = max(counts)
        lines.extend([
            "=" * 100,
            f"REPORT     : {report.label}",
            f"SOURCE     : {report.path}",
            f"PATHS      : resolved {len(report.values_ps)} / total {report.total}; "
            f"unresolved {report.unresolved}; violated {row['violated_paths']}",
            f"MEAN       : {row['mean_ps']:.3f} ps",
            f"MEDIAN     : {row['median_ps']:.3f} ps",
            f"STDDEV     : {row['stddev_ps']:.3f} ps",
            f"MIN/P05    : {row['min_ps']:.3f} / {row['p05_ps']:.3f} ps",
            f"Q1/Q3      : {row['q1_ps']:.3f} / {row['q3_ps']:.3f} ps",
            f"P95/MAX    : {row['p95_ps']:.3f} / {row['max_ps']:.3f} ps",
            "",
            "Slack range (ps)                 count   ratio   distribution",
            "-" * 100,
        ])
        for index, count in enumerate(counts):
            bin_low = low + index * bin_width
            bin_high = low + (index + 1) * bin_width
            closing = "]" if index == bins - 1 else ")"
            zero_marker = "<0>" if bin_low <= 0.0 < bin_high or (
                index == bins - 1 and bin_low <= 0.0 <= bin_high) else "   "
            length = 0 if max_count == 0 else round(count / max_count * bar_width)
            if count and length == 0:
                length = 1
            ratio = count / len(report.values_ps) * 100.0
            lines.append(
                f"{zero_marker} [{bin_low:10.3f}, {bin_high:10.3f}{closing} "
                f"{count:6d} {ratio:6.2f}%  {'#' * length}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_distribution_svg(path, reports, bins):
    all_values = [value for report in reports for value in report.values_ps]
    low, high = min(all_values), max(all_values)
    if low == high:
        margin = max(abs(low) * 0.05, 1.0)
        low, high = low - margin, high + margin
    else:
        margin = (high - low) * 0.03
        low, high = low - margin, high + margin

    width = 1120
    left, right = 110, 35
    panel_height, top, bottom = 215, 75, 65
    plot_width = width - left - right
    height = top + panel_height * len(reports) + bottom
    ticks = nice_ticks(low, high)
    colors = ["#3678c8", "#e36b3d", "#2f9e72", "#8b5cc7", "#c18b28", "#d14d72"]

    def x_pos(value):
        return left + (value - low) / (high - low) * plot_width

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text { font-family: DejaVu Sans, Arial, sans-serif; }</style>',
        svg_text(width / 2, 32, "Ground-truth fixed-path slack distributions",
                 size=20, anchor="middle", weight="bold"),
        svg_text(width / 2, 55, "Histogram: resolved paths only; dashed line: mean; red line: 0 ps",
                 size=12, anchor="middle", color="#566175"),
    ]

    for report_index, report in enumerate(reports):
        panel_top = top + report_index * panel_height
        axis_y = panel_top + 155
        chart_top = panel_top + 28
        chart_height = axis_y - chart_top
        counts = histogram(report.values_ps, low, high, bins)
        max_count = max(counts)
        color = colors[report_index % len(colors)]
        bar_width = plot_width / bins

        elements.append(svg_text(12, panel_top + 14, report.label, size=14, weight="bold"))
        stat = summary_row(report)
        elements.append(svg_text(
            12, panel_top + 34,
            f"n={len(report.values_ps)}, unresolved={report.unresolved}, mean={stat['mean_ps']:.3f} ps",
            size=11, color="#566175"))

        for tick in ticks:
            x = x_pos(tick)
            elements.append(f'<line x1="{x:.1f}" y1="{chart_top}" x2="{x:.1f}" y2="{axis_y}" '
                            'stroke="#e1e6ed" stroke-width="1"/>')
            elements.append(svg_text(x, axis_y + 21, f"{tick:g}", size=11, anchor="middle"))

        if low <= 0.0 <= high:
            zero_x = x_pos(0.0)
            elements.append(f'<line x1="{zero_x:.1f}" y1="{chart_top}" x2="{zero_x:.1f}" '
                            f'y2="{axis_y}" stroke="#c83349" stroke-width="2"/>')

        for index, count in enumerate(counts):
            bar_height = 0 if max_count == 0 else count / max_count * chart_height
            x = left + index * bar_width + 0.6
            y = axis_y - bar_height
            elements.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bar_width - 1.2, 0.5):.1f}" '
                            f'height="{bar_height:.1f}" fill="{color}" opacity="0.82"/>')

        mean_x = x_pos(stat["mean_ps"])
        elements.append(f'<line x1="{mean_x:.1f}" y1="{chart_top}" x2="{mean_x:.1f}" y2="{axis_y}" '
                        'stroke="#172033" stroke-width="2" stroke-dasharray="6 4"/>')
        elements.append(f'<line x1="{left}" y1="{axis_y}" x2="{width-right}" y2="{axis_y}" '
                        'stroke="#667085" stroke-width="1"/>')

    elements.append(svg_text(width / 2, height - 20, "Slack (ps)", size=14, anchor="middle"))
    elements.append("</svg>")
    path.write_text("\n".join(elements), encoding="utf-8")


def write_boxplot_svg(path, reports):
    all_values = [value for report in reports for value in report.values_ps]
    low, high = min(all_values), max(all_values)
    if low == high:
        margin = max(abs(low) * 0.05, 1.0)
        low, high = low - margin, high + margin
    else:
        margin = (high - low) * 0.05
        low, high = low - margin, high + margin

    width = 1120
    left, right, top, bottom = 220, 35, 70, 65
    row_height = 75
    plot_width = width - left - right
    height = top + row_height * len(reports) + bottom
    ticks = nice_ticks(low, high)

    def x_pos(value):
        return left + (value - low) / (high - low) * plot_width

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text { font-family: DejaVu Sans, Arial, sans-serif; }</style>',
        svg_text(width / 2, 32, "Ground-truth slack comparison", size=20,
                 anchor="middle", weight="bold"),
    ]
    plot_bottom = top + row_height * len(reports)
    for tick in ticks:
        x = x_pos(tick)
        elements.append(f'<line x1="{x:.1f}" y1="{top-15}" x2="{x:.1f}" y2="{plot_bottom}" '
                        'stroke="#e1e6ed" stroke-width="1"/>')
        elements.append(svg_text(x, plot_bottom + 24, f"{tick:g}", size=11, anchor="middle"))
    if low <= 0.0 <= high:
        zero_x = x_pos(0.0)
        elements.append(f'<line x1="{zero_x:.1f}" y1="{top-15}" x2="{zero_x:.1f}" '
                        f'y2="{plot_bottom}" stroke="#c83349" stroke-width="2"/>')

    for index, report in enumerate(reports):
        y = top + index * row_height + row_height / 2
        row = summary_row(report)
        x_min, x_q1 = x_pos(row["min_ps"]), x_pos(row["q1_ps"])
        x_med, x_q3 = x_pos(row["median_ps"]), x_pos(row["q3_ps"])
        x_max, x_mean = x_pos(row["max_ps"]), x_pos(row["mean_ps"])
        elements.append(svg_text(left - 12, y + 5, report.label, size=12, anchor="end"))
        elements.append(f'<line x1="{x_min:.1f}" y1="{y:.1f}" x2="{x_max:.1f}" y2="{y:.1f}" '
                        'stroke="#526173" stroke-width="2"/>')
        elements.append(f'<line x1="{x_min:.1f}" y1="{y-9:.1f}" x2="{x_min:.1f}" y2="{y+9:.1f}" '
                        'stroke="#526173" stroke-width="2"/>')
        elements.append(f'<line x1="{x_max:.1f}" y1="{y-9:.1f}" x2="{x_max:.1f}" y2="{y+9:.1f}" '
                        'stroke="#526173" stroke-width="2"/>')
        elements.append(f'<rect x="{x_q1:.1f}" y="{y-17:.1f}" width="{max(x_q3-x_q1, 1):.1f}" '
                        'height="34" fill="#8db9e8" stroke="#3678c8" stroke-width="2"/>')
        elements.append(f'<line x1="{x_med:.1f}" y1="{y-17:.1f}" x2="{x_med:.1f}" y2="{y+17:.1f}" '
                        'stroke="#172033" stroke-width="3"/>')
        elements.append(f'<circle cx="{x_mean:.1f}" cy="{y:.1f}" r="5" fill="#e36b3d"/>')

    elements.append(svg_text(width / 2, height - 18, "Slack (ps); orange dot: mean",
                             size=14, anchor="middle"))
    elements.append("</svg>")
    path.write_text("\n".join(elements), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Ground-truth fixed-path report별 slack 통계와 분포 그래프를 생성합니다.")
    parser.add_argument("reports", type=Path, nargs="+",
                        help="fixed_paths.tcl로 생성한 ground-truth .rpt 파일들")
    parser.add_argument("--input-unit", choices=TO_PS, default="ns",
                        help="report slack 단위 (기본값: ns; 출력은 ps)")
    parser.add_argument("--output-dir", type=Path, default=Path("ground_truth_slack_stats"),
                        help="결과 폴더 (기본값: ground_truth_slack_stats)")
    parser.add_argument("--bins", type=int, default=30,
                        help="histogram bin 개수 (기본값: 30)")
    args = parser.parse_args()

    if args.bins < 2:
        parser.error("--bins must be at least 2")
    for report in args.reports:
        if not report.is_file():
            parser.error(f"file not found: {report}")

    reports, path_rows = load_reports(args.reports, TO_PS[args.input_unit])
    summaries = [summary_row(report) for report in reports]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "ground_truth_slack_summary.csv"
    paths_path = args.output_dir / "ground_truth_path_slacks.csv"
    distribution_path = args.output_dir / "ground_truth_slack_distribution.svg"
    boxplot_path = args.output_dir / "ground_truth_slack_boxplot.svg"
    terminal_path = args.output_dir / "ground_truth_slack_terminal.txt"

    write_csv(summary_path, summaries, list(summaries[0]))
    write_csv(paths_path, path_rows,
              ["report", "source_report", "idx", "path_key", "slack_ps", "status"])
    write_distribution_svg(distribution_path, reports, args.bins)
    write_boxplot_svg(boxplot_path, reports)
    write_terminal_histogram(terminal_path, reports, args.bins)

    print("=== Ground-truth slack statistics ===")
    for row in summaries:
        print(f"{row['report']}: resolved={row['resolved_paths']}/{row['total_blocks']} "
              f"mean={row['mean_ps']:.3f} ps median={row['median_ps']:.3f} ps "
              f"min={row['min_ps']:.3f} ps max={row['max_ps']:.3f} ps")
    print(f"summary CSV : {summary_path}")
    print(f"path CSV    : {paths_path}")
    print(f"histogram   : {distribution_path}")
    print(f"boxplot     : {boxplot_path}")
    print(f"terminal    : {terminal_path}")
    print(f"view command: less -S {terminal_path}")


if __name__ == "__main__":
    main()
