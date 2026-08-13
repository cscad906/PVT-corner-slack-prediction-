#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5b - crosstalk 쌍 리포트 3단계: PT 출력에서 victim-aggressor 쌍을 뽑는다.

    python3 5b_pairs.py --dir <코너폴더>                  # setup
    python3 5b_pairs.py --dir <코너폴더> --mode hold      # hold

**hold 데이터면 --mode hold 를 반드시 준다.** 이 값이 결과의 analysis_type
열에 그대로 들어간다. 빼먹어도 에러가 안 나고 setup 으로 찍히기만 하므로,
나중에 setup/hold 를 섞어 학습하게 된다. 어느 쪽인지 모르겠으면
`6_check_xtalk.py` 가 PT 원문을 보고 알려 준다(원문의 Annotated max/min).

넣는 것   xtalk/context_raw.rpt   (xtalk_all.tcl / xtalk_all_hold.tcl 의 PT 원문)
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
                   "Run pt/xtalk_all.tcl (xtalk_all_hold.tcl for hold) in "
                   "pt_shell first."),
    "E-NO5A":     ("An input made by 5a_contexts.py is missing or empty",
                   "Run 5a_contexts.py for this corner first. 5b needs "
                   "path_victim_nets.tsv and unique_contexts.tsv, not just "
                   "the PT output."),
    "E-MODE":     ("The PT output was made with setup/hold the other way round",
                   "Re-run 5b with the other --mode, or re-make the PT output "
                   "with the delay type you want. See above."),
    "E-PARSE":    ("Failed while reading the PT output",
                   "The parser's own message is printed above -- read that "
                   "first. If it says nothing useful, open "
                   "xtalk/context_raw.rpt and check the top of the file for "
                   "PT error lines."),
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
                    help="setup(max) / hold(min). Must match the xtalk_all "
                         "run that made the PT output")
    ap.add_argument("--xtalk", default=None,
                    help="Absolute path of the xtalk folder. If given, "
                         "<dir>/xtalk is not looked up")
    args = ap.parse_args()

    for _p in ['parse_path_context_delay_calculation.py', 'prepare_compact_timing_window_requests.py']:
        need_parser(_p)

    d = args.dir
    work = args.xtalk or os.path.join(d, "xtalk")
    # --xtalk 로 폴더를 직접 줬으면 코너 이름은 그 폴더의 부모에서 뽑는다
    # (xtalk/ 의 부모가 코너 폴더라는 규약은 그대로다).
    _base = os.path.dirname(os.path.abspath(work)) if args.xtalk else os.path.abspath(d)
    corner = args.corner or os.path.basename(_base)

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

    # 5a 가 만든 두 파일도 파서에 넘어간다. 예전에는 이걸 확인하지 않아서,
    # 5a 를 안 돌렸을 때도 "PT 출력 앞부분을 보라"는 엉뚱한 안내가 나왔다.
    for p in (victim, ctx):
        if not os.path.isfile(p):
            code("E-NO5A",
                 "[ FAILED ] 5a output not found: %s" % p,
                 "           5b reads this together with the PT output.")
        if os.path.getsize(p) == 0:
            code("E-NO5A",
                 "[ FAILED ] 5a output is empty: %s" % p,
                 "           5a ran but produced nothing.")

    if os.path.getsize(raw) == 0:
        code("E-NORAW",
             "[ FAILED ] PT output is empty: %s" % raw,
             "           The tcl created the file but wrote nothing.",
             "           Usually the design was not loaded in that pt_shell.")

    print("  PT output : %s  (%.1fMB)" % (raw, os.path.getsize(raw) / 1048576.0))
    print("  5a input  : %s (%d rows), %s (%d rows)"
          % (os.path.basename(victim), count_rows(victim),
             os.path.basename(ctx), count_rows(ctx)))
    print("  mode      : %s   (must match the xtalk_all run)" % args.mode)

    ok, out = run("parse_path_context_delay_calculation.py",
                  victim, ctx, raw, summary, feats,
                  env={"PT_FEATURE_CORNER": corner,
                       "PT_FEATURE_ANALYSIS_TYPE": args.mode,
                       "PT_FEATURE_VOLTAGE": "",
                       "PT_FEATURE_TEMPERATURE": ""})
    if not ok:
        # 파서가 알려 주는 실패 중 하나는 원인이 딱 정해져 있다. 그건 일반
        # "파싱 실패" 로 뭉뚱그리지 말고 무엇을 고치면 되는지 바로 말한다.
        if "delta mode mismatch" in out:
            other = "hold" if args.mode == "setup" else "setup"
            code("E-MODE",
                 "[ FAILED ] The PT output was made with a different mode.",
                 "",
                 "           5b was told  --mode %s" % args.mode,
                 "           but %s holds the other kind of delta delay."
                 % os.path.basename(raw),
                 "",
                 "           Either re-run 5b with:   --mode %s" % other,
                 "           or re-make the PT output with the mode you want",
                 "           (xtalk_all.tcl for setup, xtalk_all_hold.tcl for",
                 "            hold) and then run 5b again.",
                 "",
                 "           Parser said:",
                 out[-500:])
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

    # 도착시각 파일이 이미 있으면(xtalk_all.tcl 로 한 번에 돌린 경우) PT 는 끝이다.
    vw = os.path.join(work, "victim_windows.tsv")
    aw = os.path.join(work, "aggressor_windows.tsv")
    if os.path.exists(vw) and os.path.exists(aw):
        print("[ OK ] %d pair rows. The arrival-window files are already "
              "here -- PT is done." % n_row)
        print("       Next, in the shell:")
        print("         python3 %s %s"
              % (os.path.join(HERE, "5c_report.py"),
                 ("--xtalk %s" % os.path.abspath(work)) if args.xtalk
                 else ("--dir %s" % os.path.abspath(d))))
    else:
        print("[ WARNING ] %d pair rows, but the arrival-window files are "
              "missing." % n_row)
        print("            5c needs xtalk/victim_windows.tsv and")
        print("            aggressor_windows.tsv. Check that xtalk_all.tcl")
        print("            ran to the end (it prints [ OK-XTALK ]).")
    code("OK-XPAIR")


if __name__ == "__main__":
    main()
