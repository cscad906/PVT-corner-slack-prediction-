"""Report-only regression tests; run with Python's unittest, no EDA tools needed."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "compare_scaling_mae.py"
SPEC = importlib.util.spec_from_file_location("scaling_comparison", str(SCRIPT))
COMPARISON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARISON)


def timing_report(analysis="setup", updates=None, capture_edge=None,
                  unknown_required=0.0, omit_uncertainty=False, rename_data=False,
                  capture_library="BUF", prefix="", extra_columns=False):
    """A small full-clock report with known physical delays and signed constraints."""
    values = {
        "launch_source": 0.010, "launch_net1": 0.002, "launch_cell": 0.010,
        "launch_net2": 0.003, "cq": 0.040, "data_net1": 0.020,
        "data_cell": 0.050, "data_net2": 0.030,
        "capture_source": 0.020, "capture_net1": 0.004,
        "capture_cell": 0.012, "capture_net2": 0.005,
        "cppr": 0.002, "uncertainty": -0.010 if analysis == "setup" else 0.010,
        "check": -0.020 if analysis == "setup" else 0.007,
    }
    values.update(updates or {})
    edge = (1.0 if analysis == "setup" else 0.0) if capture_edge is None else capture_edge
    rows = ["### FIXED_PATH idx=1 key=FF->END#1",
            "Startpoint: {}FF (rising edge-triggered flip-flop clocked by CLK)".format(prefix),
            "Endpoint: {}END (rising edge-triggered flip-flop clocked by CLK)".format(prefix),
            "Path Group: CLK", "Path Type: " + ("max" if analysis == "setup" else "min")]
    layout = "{:<64} {:>8} {:>10} {:>10} {:>10} {:>10} {:>10}"
    rows.append(layout.format("Point", "Fanout", "Cap", "Trans", "Incr", "Path", "Cpin"))

    def annotation(label, incr, total):
        rows.append("{:<100} {:>10.6f} {:>10.6f}".format(label, incr, total))

    def point(name, lib, incr, total, arrow=False):
        label = "{} ({}){}".format(name, lib, " <-" if arrow else "")
        rows.append(layout.format(label, "", "", "0.001000", "{:.6f}".format(incr),
                                  "{:.6f}".format(total), "0.456789" if extra_columns else "") + " r")

    annotation("clock CLK (rise edge)", 0, 0)
    annotation("clock source latency", values["launch_source"], values["launch_source"])
    total = values["launch_source"]
    point("CLK", "in", 0, total)
    for name, lib, key in [("L/A", "BUF", "launch_net1"), ("L/Y", "BUF", "launch_cell"),
                           ("FF/CLK", "DFF", "launch_net2"), ("FF/Q", "DFF", "cq"),
                           ("U/A" if not rename_data else "OTHER/A", "AND", "data_net1"),
                           ("U/Y" if not rename_data else "OTHER/Y", "AND", "data_cell"),
                           ("END/D", "DFF", "data_net2")]:
        total += values[key]
        point(prefix + name, lib, values[key], total, key in ("cq", "data_net1", "data_cell"))
    arrival = total
    rows.append("data arrival time {:.6f}".format(arrival))
    annotation("clock CLK (rise edge)", edge, edge)
    total = edge + values["capture_source"]
    annotation("clock source latency", values["capture_source"], total)
    point("CLK", "in", 0, total)
    for name, lib, key in [("C/A", capture_library, "capture_net1"),
                           ("C/Y", capture_library, "capture_cell"), ("END/CLK", "DFF", "capture_net2")]:
        total += values[key]
        point(prefix + name, lib, values[key], total)
    for label, key in [("clock reconvergence pessimism", "cppr"), ("clock uncertainty", "uncertainty"),
                       ("library setup time" if analysis == "setup" else "library hold time", "check")]:
        if key == "uncertainty" and omit_uncertainty:
            continue
        total += values[key]
        annotation(label, values[key], total)
    if unknown_required:
        total += unknown_required
        annotation("statistical adjustment", unknown_required, total)
    required = total
    rows.extend(["data required time {:.6f}".format(required),
                 "data required time {:.6f}".format(required),
                 "data arrival time {:.6f}".format(-arrival)])
    slack = required - arrival if analysis == "setup" else arrival - required
    rows.append("slack ({}) {:.6f}".format("MET" if slack >= 0 else "VIOLATED", slack))
    return "\n".join(rows) + "\n"


class ReportDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pt_path_diagnostics_")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def compare(self, scaled_text, truth_text, analysis=None):
        pred_path, gt_path = self.root / "scaled.rpt", self.root / "ground_truth.rpt"
        pred_path.write_text(scaled_text)
        gt_path.write_text(truth_text)
        scaled, truth = COMPARISON.parse_report(pred_path), COMPARISON.parse_report(gt_path)
        rows, summary = COMPARISON.evaluate(scaled, truth, 1000.0, analysis)
        summary["path_diagnostics"] = COMPARISON.diagnose_paths(rows, scaled, truth, analysis)
        return rows, summary

    def test_independent_setup_totals_and_constraints(self):
        updates = {"launch_cell": 0.016, "cq": 0.044, "data_net1": 0.031,
                   "capture_source": 0.023, "capture_cell": 0.016,
                   "cppr": 0.008, "uncertainty": -0.015, "check": -0.025}
        rows, summary = self.compare(timing_report(updates=updates, capture_edge=1.625), timing_report())
        row, diag = rows[0], rows[0]["diagnostic"]
        self.assertAlmostEqual(row["arrival_error_ps"], 21)
        self.assertAlmostEqual(row["required_error_ps"], 628)
        self.assertAlmostEqual(row["pt_scaling_err_ps"], 607)
        expected = {"launch_clock_cell": 6, "data_cell": 4, "data_net": 11,
                    "capture_clock_cell": 4, "capture_clock_source_latency": 3,
                    "clock_reconvergence_pessimism": 6, "clock_uncertainty": -5,
                    "library_setup_time": -5, "capture_edge": 625}
        for name, value in expected.items():
            self.assertAlmostEqual(diag["components"][name]["error_ps"], value)
        self.assertAlmostEqual(diag["launch_clock_delay_error_ps"], 6)
        self.assertAlmostEqual(diag["data_delay_error_ps"], 15)
        self.assertAlmostEqual(diag["capture_clock_delay_error_ps"], 7)
        self.assertAlmostEqual(diag["arrival_unexplained_error_ps"], 0)
        self.assertAlmostEqual(diag["required_unexplained_error_ps"], 0)
        self.assertEqual(diag["largest_known_slack_term"], "capture_edge")
        self.assertEqual(diag["status"], "EXPLAINED")
        self.assertEqual(summary["clock_validation_status"], "INVALID")

    def test_hold_slack_sign(self):
        rows, _ = self.compare(timing_report("hold", updates={"data_net1": 0.031, "check": 0.012}),
                               timing_report("hold"))
        diag = rows[0]["diagnostic"]
        self.assertAlmostEqual(rows[0]["pt_scaling_err_ps"], 6)
        self.assertAlmostEqual(diag["components"]["data_net"]["slack_contribution_ps"], 11)
        self.assertAlmostEqual(diag["components"]["library_hold_time"]["slack_contribution_ps"], -5)
        self.assertAlmostEqual(diag["slack_unexplained_error_ps"], 0)
        self.assertEqual(diag["status"], "EXPLAINED")

    def test_unknown_statistical_term_stays_unexplained(self):
        rows, _ = self.compare(timing_report(unknown_required=0.025), timing_report())
        diag = rows[0]["diagnostic"]
        self.assertAlmostEqual(diag["required_unexplained_error_ps"], 25)
        self.assertAlmostEqual(diag["scaled_required_residual_ps"], 25)
        self.assertAlmostEqual(diag["ground_truth_required_residual_ps"], 0)
        self.assertEqual(diag["status"], "REVIEW")
        self.assertIsNone(diag["largest_known_slack_term"])

    def test_common_slack_adjustment_does_not_hide_behind_zero_error(self):
        rpt = timing_report().replace("slack (MET) 0.848000", "slack (MET) 0.873000")
        rows, _ = self.compare(rpt, rpt)
        diag = rows[0]["diagnostic"]
        self.assertAlmostEqual(rows[0]["pt_scaling_err_ps"], 0)
        self.assertAlmostEqual(diag["scaled_slack_identity_residual_ps"], 25)
        self.assertAlmostEqual(diag["ground_truth_slack_identity_residual_ps"], 25)
        self.assertEqual(diag["status"], "REVIEW")

    def test_missing_constraint_is_not_zero(self):
        rows, _ = self.compare(timing_report(omit_uncertainty=True), timing_report())
        diag = rows[0]["diagnostic"]
        self.assertIsNone(diag["components"]["clock_uncertainty"]["scaled_ps"])
        self.assertIsNone(diag["components"]["clock_uncertainty"]["error_ps"])
        self.assertEqual(diag["status"], "REVIEW")
        self.assertIn("clock_uncertainty unavailable in one report", diag["reasons"])

    def test_point_or_library_mismatch_is_review(self):
        rows, _ = self.compare(timing_report(rename_data=True, capture_library="BUF_v2"), timing_report())
        reasons = rows[0]["diagnostic"]["reasons"]
        self.assertIn("data point sequence/transition mismatch", reasons)
        self.assertIn("capture_clock library-cell sequence mismatch", reasons)
        self.assertEqual(rows[0]["diagnostic"]["status"], "REVIEW")

    def test_extra_numeric_columns_and_hierarchical_names(self):
        rpt = timing_report(prefix="block[12]/part.3/", extra_columns=True)
        rows, _ = self.compare(rpt, rpt)
        diag = rows[0]["diagnostic"]
        self.assertAlmostEqual(diag["components"]["data_cell"]["scaled_ps"], 90)
        self.assertAlmostEqual(diag["components"]["data_net"]["scaled_ps"], 50)
        self.assertAlmostEqual(diag["scaled_arrival_residual_ps"], 0)
        self.assertAlmostEqual(diag["scaled_required_residual_ps"], 0)
        self.assertEqual(diag["status"], "EXPLAINED")

    def test_partial_point_row_is_visible(self):
        rpt = timing_report().replace("0.050000", "       -", 1)
        rows, _ = self.compare(rpt, timing_report())
        self.assertIn("point rows without a readable Incr column", rows[0]["diagnostic"]["reasons"])
        self.assertEqual(rows[0]["diagnostic"]["status"], "REVIEW")

    def test_sparse_and_missing_paths_preserve_wns(self):
        pred = "### FIXED_PATH idx=1 key=A\nslack (VIOLATED) -0.220\n"
        gt = "### FIXED_PATH idx=1 key=A\nslack (VIOLATED) -0.200\n"
        pred += "### FIXED_PATH idx=2 key=MISSING\nNo timing path found\n"
        rows, summary = self.compare(pred, gt, "setup")
        self.assertEqual(rows[0]["diagnostic"]["status"], "UNAVAILABLE")
        self.assertEqual(rows[1]["diagnostic"]["status"], "EXCLUDED")
        self.assertAlmostEqual(summary["mae_ps"], 20)
        self.assertAlmostEqual(summary["wns_error_percent"], 10)
        path = self.root / "details.txt"
        COMPARISON.write_path_diagnostics(path, rows)
        self.assertIn("N/A", path.read_text())

    def test_diagnostics_order_and_wns_on_different_paths(self):
        pred = ("### FIXED_PATH idx=3 key=A\nslack (VIOLATED) -0.220\n"
                "### FIXED_PATH idx=1 key=B\nslack (VIOLATED) -0.100\n"
                "### FIXED_PATH idx=2 key=C\nslack (MET) 0.050\n")
        gt = ("### FIXED_PATH idx=3 key=A\nslack (VIOLATED) -0.200\n"
              "### FIXED_PATH idx=1 key=B\nslack (VIOLATED) -0.500\n"
              "### FIXED_PATH idx=2 key=C\nslack (MET) 0.000\n")
        rows, summary = self.compare(pred, gt)
        self.assertEqual(summary["ground_truth_wns_path_key"], "B")
        self.assertEqual(summary["pt_scaling_wns_path_key"], "A")
        self.assertAlmostEqual(summary["wns_abs_error_ps"], 280)
        self.assertAlmostEqual(summary["wns_error_percent"], 56)
        path = self.root / "details.txt"
        COMPARISON.write_path_diagnostics(path, rows)
        markers = [line for line in path.read_text().splitlines() if line.startswith("### PATH")]
        self.assertEqual(markers, ["### PATH idx=1 key=B", "### PATH idx=2 key=C", "### PATH idx=3 key=A"])

    def test_zero_gt_wns_remains_na(self):
        rows, summary = self.compare("### FIXED_PATH idx=1 key=A\nslack (VIOLATED) -0.020\n",
                                     "### FIXED_PATH idx=1 key=A\nslack (MET) 0.000\n")
        self.assertIsNone(summary["wns_error_percent"])
        self.assertIn("N/A (GT WNS is zero)", "\n".join(COMPARISON.wns_lines(summary)))

    def test_cli_outputs_and_no_overwrite(self):
        self.compare(timing_report(updates={"data_net1": 0.031}), timing_report())
        cmd = [sys.executable, str(SCRIPT), str(self.root / "scaled.rpt"),
               str(self.root / "ground_truth.rpt"), "--output-dir", str(self.root / "out")]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        directory = self.root / "out" / "ground_truth"
        summary = json.loads((directory / "summary.json").read_text())
        self.assertEqual(summary["path_diagnostics"]["status_counts"], {"EXPLAINED": 1})
        self.assertIn("DELAY_SHARE", result.stdout)
        self.assertIn("Path delay reconstruction", (directory / "summary.txt").read_text())
        self.assertIn("data_net", (directory / "path_diagnostics.txt").read_text())
        rerun = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertTrue((self.root / "out" / "ground_truth_run2" / "path_diagnostics.txt").exists())
        self.assertEqual(json.loads((directory / "summary.json").read_text()), summary)

    def test_real_example_report_reconstructs_all_paths(self):
        example = SCRIPT.parents[1] / "example/final_output_example/TT_0p8V_25C_fixed_annotated.txt"
        parsed = COMPARISON.parse_report(example)
        rows, _ = COMPARISON.evaluate(parsed, parsed, 1000.0)
        diagnostics = COMPARISON.diagnose_paths(rows, parsed, parsed)
        self.assertEqual(diagnostics["status_counts"], {"EXPLAINED": len(rows)})
        self.assertEqual(len(rows), 294)
        for row in rows:
            detail = row["diagnostic"]
            self.assertLessEqual(abs(detail["scaled_arrival_residual_ps"]), detail["rounding_tolerance_ps"])
            self.assertLessEqual(abs(detail["scaled_required_residual_ps"]), detail["rounding_tolerance_ps"])


if __name__ == "__main__":
    unittest.main()
