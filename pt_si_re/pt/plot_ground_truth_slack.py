#!/usr/bin/env python3
"""Summarize and plot fixed-path ground-truth slack reports without extra packages."""

from __future__ import annotations

import argparse
import csv
import html
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from compare_scaling_mae import TO_PS, parse_report


@dataclass(frozen=True)
class ReportData:
    label: str
    path: Path
    total: int
    unresolved: int
    values_ps: list[float]


def percentile(values: list[float], percent: float) -> float:
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


def unique_labels(paths: list[Path]) -> list[str]:
    stems = [path.stem for path in paths]
    counts: dict[str, int] = {}
    labels: list[str] = []
    for path, stem in zip(paths, stems):
        counts[stem] = counts.get(stem, 0) + 1
        labels.append(stem if stems.count(stem) == 1 else f"{stem}_{counts[stem]}")
    return labels


def load_reports(paths: list[Path], factor: float) -> tuple[list[ReportData], list[dict]]:
    reports: list[ReportData] = []
    path_rows: list[dict] = []
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


def summary_row(report: ReportData) -> dict:
    values = report.values_ps
    return {
        "report": report.label,
        "source_report": str(report.path),
        "total_blocks": report.total,
        "resolved_paths": len(values),
        "unresolved_paths": report.unresolved,
        "mean_ps": statistics.fmean(values),
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


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: f"{value:.6f}" if isinstance(value, float) else
                "" if value is None else value
                for key, value in row.items()
            })


def svg_text(x: float, y: float, text: str, *, size: int = 13,
             anchor: str = "start", weight: str = "normal", color: str = "#172033") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}" fill="{color}">'
            f'{html.escape(text)}</text>')


def nice_ticks(low: float, high: float, count: int = 6) -> list[float]:
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


def histogram(values: list[float], low: float, high: float, bins: int) -> list[int]:
    counts = [0] * bins
    span = high - low
    for value in values:
        index = min(bins - 1, max(0, int((value - low) / span * bins)))
        counts[index] += 1
    return counts


def write_distribution_svg(path: Path, reports: list[ReportData], bins: int) -> None:
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

    def x_pos(value: float) -> float:
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


def write_boxplot_svg(path: Path, reports: list[ReportData]) -> None:
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

    def x_pos(value: float) -> float:
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


def main() -> None:
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

    write_csv(summary_path, summaries, list(summaries[0]))
    write_csv(paths_path, path_rows,
              ["report", "source_report", "idx", "path_key", "slack_ps", "status"])
    write_distribution_svg(distribution_path, reports, args.bins)
    write_boxplot_svg(boxplot_path, reports)

    print("=== Ground-truth slack statistics ===")
    for row in summaries:
        print(f"{row['report']}: resolved={row['resolved_paths']}/{row['total_blocks']} "
              f"mean={row['mean_ps']:.3f} ps median={row['median_ps']:.3f} ps "
              f"min={row['min_ps']:.3f} ps max={row['max_ps']:.3f} ps")
    print(f"summary CSV : {summary_path}")
    print(f"path CSV    : {paths_path}")
    print(f"histogram   : {distribution_path}")
    print(f"boxplot     : {boxplot_path}")


if __name__ == "__main__":
    main()
