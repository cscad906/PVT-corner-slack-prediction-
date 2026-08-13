#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5b - crosstalk 쌍 리포트 3단계: PT 출력에서 victim-aggressor 쌍을 뽑는다.

    python3 5b_pairs.py --dir <코너폴더>

넣는 것   xtalk/context_raw.rpt   (xtalk_calc.tcl 이 만든 PT 원문)
나오는 것 xtalk/active_features.tsv         쌍 하나가 한 줄
          xtalk/victim_load_pins.txt        다음 PT 단계에서 물어볼 핀
          xtalk/aggressor_nets.txt          다음 PT 단계에서 물어볼 넷

여기까지 하면 aggressor 별 bump 와 coupling cap 이 나옵니다. 다만 aggressor 의
**driver 핀이 언제 도착하는지**(arrival window, slew)는 아직 없습니다. 그 핀들은
우리 경로에 없는 남의 넷이라 pin_attr.txt 에 안 들어 있기 때문입니다.
그래서 PT 를 한 번 더 돌려야 하고, 그 목록이 위 txt 두 개입니다.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()

HERE = os.path.dirname(os.path.abspath(__file__))
XTALK = os.path.join(HERE, "_engine", "xtalk")

# 화면에 나가는 문장은 영어로 쓴다. 현장 터미널이 한글을 깨뜨려서, 정작
# 필요할 때 진단문을 못 읽는다. 주석과 docstring 은 화면에 안 나오므로 한국어.
CODE_INFO = {
    "E-NOENGINE": ("Package files (_engine/xtalk/) are missing",
                   "Copy the whole pt_si_re folder. Without _engine/ the "
                   "crosstalk steps cannot run."),
    "E-NORAW":    ("PT output (context_raw.rpt) is missing",
                   "Run pt/xtalk_calc.tcl in pt_shell first."),
    "E-PARSE":    ("Failed while reading the PT output",
                   "Open xtalk/context_raw.rpt and check that the top of the "
                   "file looks normal."),
    "E-NOPAIR":   ("No victim-aggressor pair was produced",
                   "SI may be off, or the SPEF may carry no coupling. Check "
                   "si_enable_analysis and read_parasitics "
                   "-keep_capacitive_coupling in PT."),
    "W-NOACTIVE": ("No aggressor actually had any effect",
                   "The report will be all zeros. Check the SI settings."),
}


def code(c, *msg):
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  DONE                [ %s ]" % c)
        print("=" * 66)
        return
    what, todo = CODE_INFO.get(c, ("", ""))
    print("  %s" % ("PROBLEM" if c.startswith("E-") else "CHECK NEEDED"))
    if what:
        print("    What  : %s" % what)
        print("    To do : %s" % todo)
    print("")
    print("    Error code: %s" % c)
    print("    (If this does not help, tell us this code)")
    print("=" * 66)
    sys.exit(1 if c.startswith("E-") else 0)


def run(script, *a, **kw):
    cmd = [sys.executable, os.path.join(XTALK, script)] + list(a)
    env = dict(os.environ)
    env.update(kw.get("env", {}))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    out = p.communicate()[0].decode("utf-8", "replace")
    return p.returncode == 0, out


def count_rows(path):
    if not os.path.isfile(path):
        return 0
    with open(path, "r", errors="ignore") as f:
        return max(0, sum(1 for _ in f) - 1)


def count_lines(path):
    if not os.path.isfile(path):
        return 0
    with open(path, "r", errors="ignore") as f:
        return sum(1 for _ in f)



def need_parser(name):
    """_engine/xtalk/ 의 파서가 있는지 먼저 본다.

    없으면 '리포트 생성 실패' 같은 엉뚱한 안내가 나와 엉뚱한 데를 뒤지게 된다.
    패키지를 옮길 때 _engine/ 을 빠뜨리면 실제로 이렇게 된다.
    """
    p = os.path.join(XTALK, name)
    if not os.path.isfile(p):
        code("E-NOENGINE",
             "[ FAILED ] Package file not found: %s" % p,
             "           The whole _engine/xtalk/ folder is required.",
             "           _engine/ starts with an underscore, so copying with",
             "           'cp *.py' or 'scp *' silently leaves it behind.",
             "           Copy the folder itself:  cp -r <src>/_engine <dst>/")

def main():
    ap = argparse.ArgumentParser(
        description="crosstalk pair report, step 3 - extract pairs from the "
                    "PT output.")
    ap.add_argument("--dir", default=".",
                    help="ONE corner folder (the one that contains xtalk/)")
    ap.add_argument("--corner", default=None,
                    help="Corner name. Defaults to the folder name")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup(max) / hold(min). Must match xtalk_calc.tcl")
    args = ap.parse_args()

    for _p in ['parse_path_context_delay_calculation.py', 'prepare_compact_timing_window_requests.py']:
        need_parser(_p)

    d = args.dir
    work = os.path.join(d, "xtalk")
    corner = args.corner or os.path.basename(os.path.abspath(d))

    print("=" * 68)
    print("5b - extract crosstalk victim-aggressor pairs")
    print("=" * 68)

    victim = os.path.join(work, "path_victim_nets.tsv")
    ctx = os.path.join(work, "unique_contexts.tsv")
    raw = os.path.join(work, "context_raw.rpt")
    summary = os.path.join(work, "context_summary.tsv")
    feats = os.path.join(work, "active_features.tsv")

    if not os.path.isfile(raw):
        code("E-NORAW", "[ FAILED ] PT output not found: %s" % raw)

    print("  PT output : %s  (%.1fMB)" % (raw, os.path.getsize(raw) / 1048576.0))

    ok, out = run("parse_path_context_delay_calculation.py",
                  victim, ctx, raw, summary, feats,
                  env={"PT_FEATURE_CORNER": corner,
                       "PT_FEATURE_ANALYSIS_TYPE": args.mode,
                       "PT_FEATURE_VOLTAGE": "",
                       "PT_FEATURE_TEMPERATURE": ""})
    if not ok:
        code("E-PARSE", "[ FAILED ] Could not parse the PT output", out[-800:])

    vpins = os.path.join(work, "victim_load_pins.txt")
    anets = os.path.join(work, "aggressor_nets.txt")
    ok, out = run("prepare_compact_timing_window_requests.py", feats, vpins, anets)
    if not ok:
        code("E-PARSE",
             "[ FAILED ] Could not build the list for the next step", out[-800:])

    n_row = count_rows(feats)
    n_vp = count_lines(vpins)
    n_an = count_lines(anets)

    print("")
    print("-" * 68)
    print("  pairs (rows)          : %d" % n_row)
    print("  victim pins to ask PT : %d" % n_vp)
    print("  aggressor nets to ask : %d" % n_an)
    print("-" * 68)

    if n_row == 0:
        code("E-NOPAIR", "[ FAILED ] Zero pairs.")
    if n_an == 0:
        code("W-NOACTIVE", "[ WARNING ] Zero aggressors actually had an effect.")

    print("[ OK ] %d pair rows. Next, in pt_shell:" % n_row)
    print("           cd %s" % os.path.abspath(d))
    print("           source %s" % os.path.join(HERE, "pt", "xtalk_windows.tcl"))
    code("OK-XPAIR")


if __name__ == "__main__":
    main()
