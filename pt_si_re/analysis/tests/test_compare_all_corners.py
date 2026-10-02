"""Batch comparison tests; run with Python's unittest, no EDA tools needed."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BATCH = load("compare_all_corners", HERE.parent / "compare_all_corners.py")
REPORTS = load("report_fixture", HERE / "test_compare_scaling_diagnostics.py")
timing_report = REPORTS.timing_report


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="compare_all_")
        root = Path(self.temp.name)
        self.scaled = root / "scaled"
        self.gt = root / "PERIC0"
        self.out = root / "out"
        for folder in (self.scaled, self.gt / "setup", self.gt / "hold"):
            folder.mkdir(parents=True)
        # Scaled run: link-corner SDC period 2.0 ns; GT: target period 2.3 ns.
        (self.scaled / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_setup.rpt").write_text(timing_report(capture_edge=2.0))
        (self.scaled / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_setup_net.rpt").write_text(
            timing_report(capture_edge=2.0, updates={"data_cell": 0.060}))
        (self.scaled / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_hold.rpt").write_text(
            timing_report("hold", updates={"data_net1": 0.031}))
        (self.scaled / "restored_scaled_SSPG_0p95V_125C_RCMAX_V_setup.rpt").write_text(timing_report())
        (self.gt / "setup" / "SSPG_0p60v_125c_rcmax.rpt").write_text(timing_report(capture_edge=2.3))
        (self.gt / "setup" / "SSPG_0p60v_125c_cmax.rpt").write_text(timing_report(capture_edge=9.9))
        (self.gt / "hold" / "SSPG_0p60v_125c_rcmax.rpt").write_text(timing_report("hold"))

    def tearDown(self):
        self.temp.cleanup()

    def run_batch(self, *extra):
        code = BATCH.main(["--scaled-dir", str(self.scaled), "--gt-dir", str(self.gt),
                           "--output-dir", str(self.out)] + list(extra))
        return code, (self.out / "summary_all.txt").read_text()

    def test_pairs_by_number_and_beol_and_reports_metrics(self):
        runs = {run["name"]: run for run in BATCH.find_runs(str(self.scaled), None)}
        setup = runs["restored_scaled_SSPG_0p6V_125C_RCMAX_V_setup.rpt"]
        path, reason, _ = BATCH.find_gt(setup, str(self.gt))
        self.assertEqual(path.name, "SSPG_0p60v_125c_rcmax.rpt", reason)  # 0p6 == 0p60, cmax not taken
        metrics = BATCH.compare_pair(setup, path, str(self.out))
        self.assertAlmostEqual(metrics["mae"], 300)
        self.assertAlmostEqual(metrics["a_mae"], 0)
        self.assertAlmostEqual(metrics["a_wns_err"], 0)
        gt_slack = metrics["gt_mean"]
        self.assertAlmostEqual(metrics["mae_pct"], 300 / abs(gt_slack) * 100)
        self.assertEqual(metrics["clock"], "INVALID")

    def test_batch_table_and_not_compared(self):
        code, text = self.run_batch()
        self.assertEqual(code, 0)
        self.assertIn("RAW (as compare_scaling_mae.py)", text)
        self.assertIn("PERIOD-ALIGNED", text)
        self.assertEqual(text.count(" p90 "), 2)  # one column in each table
        self.assertIn("VIOLATIONS (slack < 0; PT judged on period-aligned slack)", text)
        self.assertTrue((self.out / "setup" / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_setup" / "path_breakdown.txt").exists())
        self.assertEqual(text.count("SSPG 0.6V 125C RCMAX"), 9)  # setup path/net + hold, in three tables
        self.assertIn("restored_scaled_SSPG_0p95V_125C_RCMAX_V_setup.rpt: NO_GT", text)
        self.assertTrue((self.out / "setup" / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_setup" / "period_aligned.txt").exists())
        self.assertTrue((self.out / "hold" / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_hold" / "summary.txt").exists())
        # A rerun never overwrites the earlier summary.
        self.run_batch()
        self.assertTrue((self.out / "summary_all_run2.txt").exists())

    def test_ambiguous_and_missing_process_are_not_guessed(self):
        (self.gt / "hold" / "SSPG_0p60v_125c_rcmax_v2.rpt").write_text(timing_report("hold"))
        _, text = self.run_batch("--analysis", "hold")
        self.assertIn("restored_scaled_SSPG_0p6V_125C_RCMAX_V_hold.rpt: AMBIGUOUS", text)
        self.assertIn("candidate: SSPG_0p60v_125c_rcmax_v2.rpt", text)
        (self.gt / "setup" / "SSPG_0p60v_125c_rcmax.rpt").rename(self.gt / "setup" / "TT_0p60v_125c_rcmax.rpt")
        run = [r for r in BATCH.find_runs(str(self.scaled), "setup") if r["mode"] == "path" and r["v"] == 0.6][0]
        path, reason, candidates = BATCH.find_gt(run, str(self.gt))
        self.assertIsNone(path)
        self.assertIn("process 'SSPG' not in the name", reason)
        self.assertEqual(candidates, ["TT_0p60v_125c_rcmax.rpt"])

    def test_scaled_design_folder_with_setup_and_hold(self):
        design = Path(self.temp.name) / "scaled_design" / "PERIC0"
        for sub in ("setup", "hold"):
            (design / sub).mkdir(parents=True)
        (self.scaled / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_setup.rpt").rename(
            design / "setup" / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_setup.rpt")
        (self.scaled / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_hold.rpt").rename(
            design / "hold" / "restored_scaled_SSPG_0p6V_125C_RCMAX_V_hold.rpt")
        runs = BATCH.find_runs(str(design), None)
        self.assertEqual(sorted(run["analysis"] for run in runs), ["hold", "setup"])
        code = BATCH.main(["--scaled-dir", str(design), "--gt-dir", str(self.gt), "--output-dir", str(self.out)])
        self.assertEqual(code, 0)
        text = (self.out / "summary_all.txt").read_text()
        self.assertEqual(text.count("SSPG 0.6V 125C RCMAX"), 6)  # setup + hold in three tables

    def test_end_corner_spec(self):
        corner = BATCH.parse_end_corner("0p5:m40:RC_MAX")
        self.assertEqual((corner["process"], corner["v"], corner["t"], corner["beol"]), (None, 0.5, -40.0, "RCMAX"))
        corner = BATCH.parse_end_corner("SSPG:0.95V:125C:rcmax")
        self.assertEqual((corner["process"], corner["v"], corner["t"]), ("SSPG", 0.95, 125.0))
        with self.assertRaises(ValueError):
            BATCH.parse_end_corner("0.5:125")

    def test_end_corners_gt_only_without_scaled_dir(self):
        code = BATCH.main(["--gt-dir", str(self.gt), "--output-dir", str(self.out),
                           "--end-corner", "0.6:125:rcmax", "--end-corner", "0.5:125:rcmax"])
        self.assertEqual(code, 0)
        text = (self.out / "end_corners.txt").read_text()
        self.assertFalse((self.out / "summary_all.txt").exists())
        lines = [line for line in text.splitlines() if "0.6V 125C RCMAX" in line]
        self.assertEqual(len(lines), 2)  # setup and hold
        setup = lines[0].split()
        self.assertEqual(setup[0], "setup")
        self.assertEqual(setup[-1], "SSPG_0p60v_125c_rcmax.rpt")  # the cmax file is not taken
        self.assertEqual(setup[-2], "0")  # no violation in the fixture
        self.assertTrue(any("0.5V 125C RCMAX" in line and line.endswith("NO_GT") for line in text.splitlines()))
        with self.assertRaises(SystemExit):
            BATCH.main(["--gt-dir", str(self.gt)])

    def test_end_corners_added_to_full_run(self):
        code, text = self.run_batch("--end-corner", "0.6:125:rcmax")
        self.assertEqual(code, 0)
        self.assertIn("END CORNERS (GT only", text)
        self.assertIn("SSPG 0.6V 125C RCMAX", text.split("END CORNERS")[1])  # process taken from the runs

    def test_name_tokens(self):
        self.assertEqual(BATCH.gt_tokens("SSPG_0p60v_m40c_rcmax.rpt")[:2], (0.6, -40.0))
        self.assertEqual(BATCH.gt_tokens("SSPG_0p675v_125c_cworst.rpt")[:2], (0.675, 125.0))
        self.assertTrue(BATCH.gt_beol_matches("SSPG_0p60v_125c_rc_max.rpt", "RCMAX"))
        self.assertFalse(BATCH.gt_beol_matches("SSPG_0p60v_125c_rcmax.rpt", "CMAX"))
        self.assertTrue(BATCH.gt_beol_matches("SSPG_0p60v_125c_cworst.rpt", "CWORST"))


if __name__ == "__main__":
    unittest.main()
