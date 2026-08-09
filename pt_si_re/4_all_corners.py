#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4 - round2 아래 코너 폴더 전부에 같은 단계를 돌린다.

    python3 4_all_corners.py --root round2 --spef /경로/design.spef

코너가 10개 넘어가면 폴더 이름을 하나씩 치는 게 일이라 만든 것이다.
하는 일은 아래를 코너마다 반복하는 것뿐이고, 새로 계산하는 것은 없다.

    2a_cpin.py     --dir <코너폴더>
    2b_distres.py  --dir <코너폴더> [--spef ...]
    2c_merge.py    --dir <코너폴더>
    5a_contexts.py --dir <코너폴더>
  [PT] all_xtalk_calc.tcl
    5b_pairs.py    --dir <코너폴더>
  [PT] all_xtalk_windows.tcl
    5c_report.py   --dir <코너폴더>

코너 이름은 폴더 이름을 그대로 쓴다(2회차에서 리포트 이름과 같게 지어진다).

SPEF 고르는 순서
    1) 코너 폴더 안의 design.spef 가 있으면 그것       <- RC 코너가 다를 때
    2) 없으면 --spef 로 준 파일                        <- 보통 이쪽
    3) 둘 다 없으면 그 코너는 2b/2c 를 건너뛴다(2a, 3 은 SPEF 가 필요 없다)

한 코너가 실패해도 멈추지 않고 끝까지 돈 뒤, 맨 아래에 코너별 결과를 표로
보여 준다. 실패가 하나라도 있으면 종료 코드 1.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from find_rpt import find_rpt

# 단계는 PT 를 사이에 두고 세 묶음으로 나뉜다. PT 는 파이썬에서 못 부르므로
# 묶음이 끝날 때마다 pt_shell 로 갔다 와야 한다.
#
#   묶음 1 -> [PT] all_xtalk_calc.tcl -> 묶음 2 -> [PT] all_xtalk_windows.tcl -> 묶음 3
#
# (표시이름, 스크립트, SPEF 가 필요한가, 결과 파일)
PHASES = {
    "1": [
        ("2a cpin",     "2a_cpin.py",     False, "cpin.tsv"),
        ("2b distres",  "2b_distres.py",  True,  "distres.tsv"),
        ("2c merge",    "2c_merge.py",    False, "annotated.txt"),
        ("5a contexts", "5a_contexts.py", False, "xtalk/unique_contexts.tsv"),
    ],
    "2": [
        ("5b pairs",    "5b_pairs.py",    False, "xtalk/active_features.tsv"),
    ],
    "3": [
        ("5c report",   "5c_report.py",   False, "xtalk/compact_flat.tsv"),
    ],
}

# 묶음이 끝나면 pt_shell 에서 그대로 source 할 tcl 을 만들어 준다.
# 경로를 손으로 고칠 일이 없고, 세션에 값이 남아 엉뚱한 폴더를 도는 일도 없다.
PT_WRAPPER = {
    "1": ("run_pt1_xtalk_calc.tcl", "all_xtalk_calc.tcl"),
    "2": ("run_pt2_xtalk_windows.tcl", "all_xtalk_windows.tcl"),
}


def write_pt_wrapper(phase, root, mode):
    if phase not in PT_WRAPPER:
        return None
    name, target = PT_WRAPPER[phase]
    path = os.path.join(root, name)
    with open(path, "w") as fh:
        fh.write("# 4_all_corners.py --phase %s 가 자동으로 만든 파일입니다.\n" % phase)
        fh.write("# pt_shell 에서 그대로 source 하세요. 고칠 것 없습니다.\n")
        fh.write("#     pt_shell> source %s\n\n" % os.path.abspath(path))
        fh.write('set XTALK_ROOT "%s"\n' % os.path.abspath(root))
        fh.write('set DELAY_TYPE "%s"\n' % ("min" if mode == "hold" else "max"))
        fh.write('source "%s"\n' % os.path.join(HERE, "pt", target))
    return path


NEXT_HINT = {
    "1": ("pt_shell 에서 PT 1차를 돌리세요 (디자인 로드된 상태로):",
          "    source %(wrap)s",
          "그다음 다시 셸에서:",
          "    $PY 4_all_corners.py --root %(root)s --phase 2"),
    "2": ("pt_shell 에서 PT 2차를 돌리세요:",
          "    source %(wrap)s",
          "그다음 다시 셸에서:",
          "    $PY 4_all_corners.py --root %(root)s --phase 3"),
    "3": ("끝입니다. 코너마다 아래 두 파일이 학습 입력입니다.",
          "    annotated.txt",
          "    <코너>.path_context_si_compact.by_path.rpt",
          ""),
}


def corner_dirs(root):
    """root 아래에서 .rpt 를 가진 폴더만 코너로 본다."""
    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        rpt, _, _ = find_rpt(d)
        if rpt:
            out.append((name, d))
    return out


def show(line):
    """하위 스크립트 출력 한 줄을 찍는다.

    python2 에서는 파이프로 읽은 줄이 unicode 라, 그대로 print 하면 터미널
    인코딩에 따라 한글에서 죽는다. 그래서 2 에서만 utf-8 로 되돌려 찍는다.
    """
    if sys.version_info[0] < 3:
        line = line.encode("utf-8")
    print("      " + line)


def run_step(script, args, quiet):
    """하위 스크립트를 지금 python 으로 돌린다. (성공여부, 마지막코드) 반환."""
    cmd = [sys.executable, os.path.join(HERE, script)] + args
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail, last_code = [], ""
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if not quiet:
            show(line)
        tail.append(line)
        # 정상은 "  정상 종료   [ OK-CPIN ]", 문제/주의는 "    에러 코드: W-NA"
        # 두 형식 다 잡아야 한다.
        for tok in ("OK-", "W-", "E-"):
            i = line.find("[ " + tok)
            if i >= 0:
                last_code = line[i + 2:].split("]")[0].strip()
        i = line.find(u"에러 코드:")
        if i >= 0:
            last_code = line[i + len(u"에러 코드:"):].strip()
    p.wait()
    if not last_code:
        # 코드가 안 찍혔으면 마지막 몇 줄이라도 보여 준다
        for line in tail[-3:]:
            show(line)
    return p.returncode == 0, (last_code or "?")


def main():
    ap = argparse.ArgumentParser(
        description="round2 아래 코너 폴더 전부에 2a/2b/2c/3 을 돌린다.")
    ap.add_argument("--root", required=True,
                    help="코너 폴더들이 **들어 있는 상위 폴더** (예: round2). 코너 폴더 하나가 아니다")
    ap.add_argument("--spef", default=None,
                    help="모든 코너가 함께 쓸 SPEF. 코너 폴더에 design.spef 가 "
                         "있으면 그쪽이 우선한다")
    ap.add_argument("--phase", default="1", choices=["1", "2", "3"],
                    help="1=2a~5a(기본), 2=5b, 3=5c. 사이사이 pt_shell 로 갔다 온다")
    ap.add_argument("--only", default=None,
                    help="그 묶음 안에서 일부만. 쉼표로 (예: 2a,2b)")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup / hold. 5b 에 넘긴다")
    ap.add_argument("--skip-done", action="store_true",
                    help="결과 파일이 이미 있으면 그 단계는 건너뛴다")
    ap.add_argument("--quiet", action="store_true",
                    help="각 단계의 화면 출력을 숨기고 결과 표만 본다")
    args = ap.parse_args()

    print("=" * 68)
    print("4 - 코너 폴더 전부 돌리기  (묶음 %s)" % args.phase)
    print("=" * 68)

    if not os.path.isdir(args.root):
        print("  폴더가 없습니다: %s" % args.root)
        sys.exit(1)

    corners = corner_dirs(args.root)
    if not corners:
        # 반대 착각: 코너들이 든 상위 폴더가 아니라 코너 폴더 하나를 준 경우
        here, _, _ = find_rpt(args.root)
        if here:
            print("  여기는 **코너 폴더 하나** 입니다: %s" % args.root)
            print("      (%s 이 바로 들어 있습니다)" % os.path.basename(here))
            print("")
            print("  --root 에는 코너 폴더들이 **들어 있는 상위 폴더**를 주세요:")
            print("      %s --root %s"
                  % (os.path.basename(__file__), os.path.dirname(args.root.rstrip("/")) or "."))
            print("")
            print("  이 코너 하나만 하려면 각 단계를 직접 돌리시면 됩니다:")
            print("      2a_cpin.py     --dir %s" % args.root)
            print("      2b_distres.py  --dir %s --spef <SPEF>" % args.root)
            print("      2c_merge.py    --dir %s" % args.root)
            print("      3_crosstalk.py --dir %s --corner %s"
                  % (args.root, os.path.basename(args.root.rstrip("/"))))
            sys.exit(1)
        print("  %s 아래에 .rpt 를 가진 폴더가 없습니다." % args.root)
        print("  2회차(02_round2.tcl)를 먼저 돌리세요.")
        sys.exit(1)

    only = set(s.strip() for s in args.only.split(",")) if args.only else None
    steps = [s for s in PHASES[args.phase]
             if only is None or s[1].split("_")[0] in only]

    print("  대상 폴더 : %s" % args.root)
    print("  코너      : %d개" % len(corners))
    for name, _ in corners:
        print("      %s" % name)
    if args.spef:
        print("  공용 SPEF : %s" % args.spef)
    print("")

    results = []   # (코너, [코드...])
    for idx, (name, d) in enumerate(corners, 1):
        print("-" * 68)
        print("[%d/%d] %s" % (idx, len(corners), name))
        print("-" * 68)

        spef = os.path.join(d, "design.spef")
        if not os.path.isfile(spef):
            spef = args.spef

        codes = []
        for label, script, need_spef, product in steps:
            if args.skip_done and os.path.isfile(os.path.join(d, product)):
                print("  %-12s 건너뜀 (%s 이미 있음)" % (label, product))
                codes.append("SKIP")
                continue
            if need_spef and not (spef and os.path.isfile(spef)):
                print("  %-12s 건너뜀 (SPEF 없음. --spef 로 주거나 "
                      "폴더에 design.spef 를 두세요)" % label)
                codes.append("NOSPEF")
                continue

            call = ["--dir", d]
            if need_spef:
                call += ["--spef", spef]
            if script in ("5b_pairs.py", "5c_report.py"):
                call += ["--corner", name]
            if script == "5b_pairs.py":
                call += ["--mode", args.mode]

            print("  %-12s 실행" % label)
            ok, c = run_step(script, call, args.quiet)
            codes.append(c)
            if not ok:
                print("  %-12s 실패 -> 이 코너의 남은 단계는 건너뜁니다" % label)
                codes += ["-"] * (len(steps) - len(codes))
                break
        results.append((name, codes))
        print("")

    # ---- 결과 표 ----------------------------------------------------
    print("=" * 68)
    print("코너별 결과")
    print("-" * 68)
    head = "  %-24s" % "코너" + "".join("%-14s" % s[0] for s in steps)
    print(head)
    bad = []
    for name, codes in results:
        row = "  %-24s" % name
        for c in codes:
            row += "%-14s" % c
        print(row)
        if any(c.startswith("E-") or c in ("-", "?") for c in codes):
            bad.append(name)
    print("")

    if bad:
        print("  실패한 코너 %d개: %s" % (len(bad), ", ".join(bad)))
        print("  그 폴더만 따로 돌려 화면을 보세요:")
        print("      $PY 2a_cpin.py --dir %s" % os.path.join(args.root, bad[0]))
        print("=" * 68)
        sys.exit(1)

    warn = [n for n, cs in results if any(c.startswith("W-") for c in cs)]
    if warn:
        print("  확인 필요한 코너 %d개: %s" % (len(warn), ", ".join(warn)))
        print("  파일은 만들어졌지만 데이터가 일부 비어 있습니다.")
        print("      $PY 9_diagnose.py --dir %s" % os.path.join(args.root, warn[0]))
        print("=" * 68)
        sys.exit(0)

    print("  묶음 %s 전부 정상입니다. 다음:" % args.phase)
    print("")
    wrap = write_pt_wrapper(args.phase, args.root, args.mode)
    fill = {"root": os.path.abspath(args.root), "pkg": HERE,
            "wrap": os.path.abspath(wrap) if wrap else ""}
    for line in NEXT_HINT[args.phase]:
        print("  " + (line % fill if "%(" in line else line))
    print("=" * 68)


if __name__ == "__main__":
    main()
