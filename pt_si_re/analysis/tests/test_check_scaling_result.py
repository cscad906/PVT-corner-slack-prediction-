"""Result-checker regression tests; run with Python's unittest, no EDA tools needed."""

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check_scaling_result.py"
SPEC = importlib.util.spec_from_file_location("check_scaling_result", str(SCRIPT))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

DB = "/lib/db/saed14rvt_tt{}v25c_ccs_mono.db"
NAME = "restored_scaled_TT_0p65V_25C_RCMAX_V_setup.rpt"
NET_NAME = "restored_scaled_TT_0p65V_25C_RCMAX_V_setup_net.rpt"

GOOD_LOG = """OUTPUT MODE: overwrite | previous_files_removed=0
SCALING POWER NETS: count=2 names=VDD_A VDD_B
AUTO-FIXED POWER NETS (unchanged): count=2 names=VDD_F VSS
LOO CHECK TL-001: PASSED | target_dbs_loaded=1 design_libraries=1 linked_to_target=0
LOO CHECK TL-003: PASSED | active_groups_checked=1 groups_with_target_db=0 | evidence=/x.loo_check.txt
FIXED-PATH CELL SCOPE: all=4 scalable_library=4 target_voltage=3 static_library=0
FIXED PATHS RESULT: requested=10 measured=10 missing=0
SCALING VERIFICATION: PASSED | evidence=/x.dcalc
RUN END: status=SUCCESS | phase=VERIFY_SCALING_RESULT | section=0.00 min | total=0.01 min
"""

GOOD_LOO = """LOO_CHECK target process=TT voltage=0.65 V temperature=25.0 C
TARGET_CORNER_DBS_LOADED: 1
  TARGET_DB lib=tt0p65 family=f
    DB={target}
TL-001 DESIGN_LINKED_LIBRARIES: 1 LINKED_TO_TARGET_DB: 0
TL-003 ACTIVE_GROUPS_CHECKED: 1 GROUPS_WITH_TARGET_DB: 0
LOO_CHECK_STATUS: PASSED
""".format(target=DB.format("0p65"))

GOOD_INPUTS = """PrimeTime scaling input plan
FAMILY saed_pvt mode=V
  INPUT 1 process=TT voltage=0.6 V temperature=25.0 C lib=tt0p6
    DB={lo}
  INPUT 2 process=TT voltage=0.7 V temperature=25.0 C lib=tt0p7
    DB={hi}
  EXCLUDED_TARGET process=TT voltage=0.65 V temperature=25.0 C lib=tt0p65
""".format(lo=DB.format("0p6"), hi=DB.format("0p7"))


def dcalc(dbs, status="SCALING_VERIFICATION_STATUS: PASSED", indent=""):
    rows = [status, "ANALYSIS_DELAY_TYPE: max", "Rise delay = 0.03", "",
            indent + "Scaling libraries used for driver model :      "]
    rows += ["\t{}:lib      ".format(db) for db in dbs]
    rows += ["", "Scaling libraries used:      "]
    rows += ["\t{}:lib ".format(db) for db in dbs]
    rows += ["", "Units:  1ns"]
    return "\n".join(rows) + "\n"


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="scalecheck_")
        os.makedirs(os.path.join(self.folder, "details"))

    def tearDown(self):
        shutil.rmtree(self.folder)

    def write(self, name, suffix, text, details=True):
        base = os.path.join(self.folder, "details") if details else self.folder
        with open(os.path.join(base, name + suffix), "w") as handle:
            handle.write(text)

    def good_run(self, name=NAME, log=GOOD_LOG, dbs=None, inputs=GOOD_INPUTS, loo=GOOD_LOO):
        with open(os.path.join(self.folder, name), "w") as handle:
            handle.write("### SCALING TARGET process=TT voltage=0.65 temperature=25.0 beol=RCMAX axis=V\n")
        self.write(name, ".log", log)
        self.write(name, ".loo_check.txt", loo)
        self.write(name, ".inputs.txt", inputs)
        self.write(name, ".dcalc", dcalc(dbs or [DB.format("0p6"), DB.format("0p7")], indent="   "))

    def run_one(self):
        runs = CHECK.check_folder(self.folder)
        self.assertEqual(len(runs), 1)
        return runs[0]

    def messages(self, run, level):
        return [message for lvl, _, message in run.findings if lvl == level]

    def test_clean_run_passes_and_reads_indented_driver_model_block(self):
        self.good_run()
        run = self.run_one()
        self.assertEqual(run.verdict(), "PASS", run.findings)
        self.assertEqual(run.used_voltages, {0.6, 0.7})
        self.assertEqual(run.target_dbs_loaded, 1)
        text = "\n".join(CHECK.render(self.folder, [run]))
        self.assertIn("WHAT THE ITEMS MEAN", text)

    def test_target_db_in_dcalc_fails_by_path_and_by_name(self):
        self.good_run(dbs=[DB.format("0p6"), DB.format("0p65")])
        run = self.run_one()
        self.assertEqual(run.verdict(), "FAIL")
        self.assertTrue(any("target-corner DB" in m for m in self.messages(run, "FAIL")))
        # Not listed in loo_check.txt (not loaded per TL), but the name carries 0.65 V.
        self.tearDown(); self.setUp()
        self.good_run(dbs=[DB.format("0p6"), "/other/mem_0p650v_25c.db"])
        run = self.run_one()
        self.assertTrue(any("carries the target voltage" in m for m in self.messages(run, "FAIL")))

    def test_old_script_without_loo_lines_fails(self):
        log = "\n".join(l for l in GOOD_LOG.splitlines() if not l.startswith("LOO CHECK")) + "\n"
        self.good_run(log=log)
        os.remove(os.path.join(self.folder, "details", NAME + ".loo_check.txt"))
        run = self.run_one()
        fails = self.messages(run, "FAIL")
        self.assertTrue(any("predates the LOO guards" in m for m in fails))
        self.assertTrue(any("loo_check.txt" in m for m in fails))

    def test_input_at_target_or_one_sided_fails(self):
        self.good_run(inputs=GOOD_INPUTS.replace("voltage=0.7 V", "voltage=0.65 V"))
        self.assertTrue(any("AT the target" in m for m in self.messages(self.run_one(), "FAIL")))
        self.tearDown(); self.setUp()
        self.good_run(inputs=GOOD_INPUTS.replace("voltage=0.7 V", "voltage=0.55 V"))
        self.assertTrue(any("do not bracket" in m for m in self.messages(self.run_one(), "FAIL")))

    def test_stopped_run_is_found_by_log_alone(self):
        self.write(NAME, ".log", "LOO CHECK TL-001: PASSED | x\nRUN END: status=FAILED | phase=PLAN\n"
                   "RUN ERROR: TL-003: 1 active scaling group(s) used by the design contain the target-corner DB\n")
        run = self.run_one()
        self.assertEqual(run.verdict(), "FAIL")
        self.assertTrue(any(m.startswith("run stopped: TL-003") for m in self.messages(run, "FAIL")))

    def test_unscaled_cells_and_missing_paths_warn(self):
        log = GOOD_LOG.replace("static_library=0", "static_library=12").replace(
            "measured=10 missing=0", "measured=8 missing=2")
        log += "UNCLASSIFIED FIXED-PATH LIBRARIES (not scaled): io_lib\n"
        self.good_run(log=log)
        run = self.run_one()
        self.assertEqual(run.verdict(), "WARN")
        self.assertEqual((run.static, run.missing), (12, 2))
        self.assertEqual(len(self.messages(run, "WARN")), 3)

    def test_net_mode_requires_net_checks_and_warns_on_skipped_clock(self):
        log = GOOD_LOG + ("NET CHECK NET-001: PASSED | libraries=1\nNET POWER VERIFICATION: PASSED | x\n"
                          "CLOCK SCALING VERIFICATION: SKIPPED (no clock-network cell)\n")
        self.good_run(name=NET_NAME, log=log)
        self.write(NET_NAME, ".clock.dcalc", "CLOCK_SCALING_VERIFICATION_STATUS: SKIPPED\nREASON: none\n")
        run = self.run_one()
        self.assertEqual((run.mode, run.verdict()), ("net", "WARN"))
        self.tearDown(); self.setUp()
        self.good_run(name=NET_NAME, log=GOOD_LOG)
        self.assertTrue(any("NET-001 line missing" in m for m in self.messages(self.run_one(), "FAIL")))

    def test_old_adjacent_detail_files_are_read(self):
        self.good_run()
        for suffix in (".log", ".loo_check.txt", ".inputs.txt", ".dcalc"):
            os.rename(os.path.join(self.folder, "details", NAME + suffix),
                      os.path.join(self.folder, NAME + suffix))
        self.assertEqual(self.run_one().verdict(), "PASS")

    def test_main_codes(self):
        self.assertEqual(CHECK.main([self.folder]), 1)  # E-NORUN
        self.good_run()
        self.assertEqual(CHECK.main([self.folder]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "check_summary.txt")))

    def test_voltage_tokens_ignore_non_voltage_numbers(self):
        self.assertEqual(CHECK.voltage_tokens("/a/saed14rvt_tt0p605v25c_ccs_rth0p01_full385_3ns250fj_mono.db"), [0.605])
        self.assertEqual(CHECK.voltage_tokens("/a/mem_ssgnp_0p675v_0p75v_m40c.db"), [0.675, 0.75])


if __name__ == "__main__":
    unittest.main()
