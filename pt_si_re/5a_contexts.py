#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5a - crosstalk 쌍(pair) 리포트 1단계: 어느 넷을 PT 에 물어볼지 목록을 만든다.

    python3 5a_contexts.py --dir <코너폴더>

넣는 것   annotated.txt   (2c_merge.py 가 만든 것)
나오는 것 xtalk/path_victim_nets.tsv     경로별 victim 넷 + 구간(launch/data/capture)
          xtalk/unique_contexts.tsv      PT 에 물어볼 (넷, driver핀, load핀) 중복 제거

왜 필요한가
    3_crosstalk.py 는 넷 단위 **요약**(aggressor 몇 개, coupling cap 합계)만 줍니다.
    기존 14열 리포트는 **aggressor 하나하나**의 bump 와 coupling cap 을 담습니다.
    그건 report_attribute 로는 안 나오고 report_delay_calculation -crosstalk 을
    넷마다 돌려야 나옵니다. 그래서 먼저 "어느 넷을 물어볼지" 목록을 만듭니다.

같은 넷이 여러 경로에 나와도 PT 에는 한 번만 물어봅니다(중복 제거). 그래서
경로 수보다 훨씬 적습니다.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
XTALK = os.path.join(HERE, "_engine", "xtalk")

CODE_INFO = {
    "E-NOANNOT":  ("annotated.txt 이 없습니다",
                   "2c_merge.py 를 먼저 돌려 주세요."),
    "E-PARSE":    ("annotated.txt 을 읽다가 실패했습니다",
                   "2c_merge.py 가 정상(OK-MERGE)으로 끝났는지 확인해 주세요."),
    "E-NOCTX":    ("PT 에 물어볼 넷이 하나도 없습니다",
                   "annotated.txt 에 '(net)' 줄이 있는지 확인해 주세요. "
                   "report_timing 에 -nets 가 빠졌을 수 있습니다."),
}


def code(c, *msg):
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  정상 종료           [ %s ]" % c)
        print("=" * 66)
        return
    what, todo = CODE_INFO.get(c, ("", ""))
    print("  %s" % ("문제 발생" if c.startswith("E-") else "확인 필요"))
    if what:
        print("    무엇이   : %s" % what)
        print("    하실 일  : %s" % todo)
    print("")
    print("    에러 코드: %s" % c)
    print("    (해결이 안 되면 이 코드를 알려주세요)")
    print("=" * 66)
    sys.exit(1 if c.startswith("E-") else 0)


def run(script, *a):
    """검증된 기존 파서를 그대로 부른다."""
    cmd = [sys.executable, os.path.join(XTALK, script)] + list(a)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.communicate()[0].decode("utf-8", "replace")
    return p.returncode == 0, out


def count_rows(path):
    if not os.path.isfile(path):
        return 0
    with open(path, "r", errors="ignore") as f:
        return max(0, sum(1 for _ in f) - 1)


def main():
    ap = argparse.ArgumentParser(
        description="crosstalk 쌍 리포트 1단계 - PT 에 물어볼 넷 목록을 만든다.")
    ap.add_argument("--dir", default=".",
                    help="**코너 폴더 하나** (annotated.txt 이 있는 폴더)")
    ap.add_argument("--annotated", default=None, help="annotated.txt 경로를 직접 줄 때")
    args = ap.parse_args()

    d = args.dir
    ann = args.annotated or os.path.join(d, "annotated.txt")
    work = os.path.join(d, "xtalk")

    print("=" * 68)
    print("5a - crosstalk 쌍 리포트 1단계 (PT 에 물어볼 목록 만들기)")
    print("=" * 68)

    if not os.path.isfile(ann):
        code("E-NOANNOT", "[ 실패 ] annotated.txt 이 없습니다: %s" % ann)
    if not os.path.isdir(work):
        os.makedirs(work)

    print("  입력 : %s" % ann)

    summary = os.path.join(work, "path_summary.tsv")
    victim = os.path.join(work, "path_victim_nets.tsv")
    ok, out = run("parse_annotated_with_clock_segments.py", ann, summary, victim)
    if not ok:
        code("E-PARSE", "[ 실패 ] annotated.txt 파싱 실패", out[-800:])

    ctx = os.path.join(work, "unique_contexts.tsv")
    ok, out = run("make_unique_path_arc_contexts.py", victim, ctx)
    if not ok:
        code("E-PARSE", "[ 실패 ] 목록 만들기 실패", out[-800:])

    n_path = count_rows(summary)
    n_victim = count_rows(victim)
    n_ctx = count_rows(ctx)

    print("")
    print("-" * 68)
    print("  경로            : %d" % n_path)
    print("  victim 넷 줄    : %d  (경로마다 중복 포함)" % n_victim)
    print("  PT 에 물어볼 것 : %d  (중복 제거 후)" % n_ctx)
    print("  작업 폴더       : %s" % work)
    print("-" * 68)

    if n_ctx == 0:
        code("E-NOCTX", "[ 실패 ] PT 에 물어볼 넷이 0개입니다.")

    print("[ 정상 ] %d개 넷. 다음은 pt_shell 에서 (디자인 로드된 상태로):" % n_ctx)
    print("           cd %s" % os.path.abspath(d))
    print("           source %s" % os.path.join(HERE, "pt", "xtalk_calc.tcl"))
    code("OK-XCTX")


if __name__ == "__main__":
    main()
