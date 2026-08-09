#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5c - crosstalk 쌍 리포트 마지막 단계: 14열 리포트를 만든다.

    python3 5c_report.py --dir <코너폴더>

넣는 것   xtalk/active_features.tsv     쌍 (5b)
          xtalk/path_victim_nets.tsv    경로/구간 (5a)
          xtalk/victim_windows.tsv      victim 도착시각 (PT 2차)
          xtalk/aggressor_windows.tsv   aggressor driver 도착시각 (PT 2차)

나오는 것 <코너>.path_context_si_compact.by_path.rpt   ★ 기존과 같은 14열
          xtalk/compact_flat.tsv                      같은 내용 평평한 TSV

**형식은 기존 것과 똑같습니다.** 모델 쪽이 읽던 파일이라 열 이름/순서/구분자가
바뀌면 안 됩니다. 그래서 만드는 코드도 기존 것을 그대로 씁니다.
"""
from __future__ import division, print_function
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8, wopen
force_utf8()

HERE = os.path.dirname(os.path.abspath(__file__))
XTALK = os.path.join(HERE, "_engine", "xtalk")

CODE_INFO = {
    "E-NOINPUT":  ("앞 단계 결과가 없습니다",
                   "5a -> xtalk_calc.tcl -> 5b -> xtalk_windows.tcl 순서로 "
                   "먼저 돌려 주세요."),
    "E-BUILD":    ("리포트를 만들다가 실패했습니다",
                   "xtalk/ 안의 tsv 들이 정상인지 보세요. 앞 단계가 [ 정상 ] 로 "
                   "끝났는지 확인해 주세요."),
    "E-NOROW":    ("리포트에 줄이 하나도 없습니다",
                   "5b 화면의 '쌍(줄)' 숫자를 확인해 주세요."),
}


def as_text(b):
    """subprocess 출력 -> 글자. 2 에서는 이미 str 이라 그대로 둔다.

    2 에서 굳이 decode 하면 unicode 가 되어, 한글이 섞인 포맷 문자열과
    합칠 때 UnicodeDecodeError 로 죽는다.
    """
    if isinstance(b, str):
        return b
    return b.decode("utf-8", "replace")


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


def main():
    ap = argparse.ArgumentParser(
        description="crosstalk 쌍 리포트 마지막 단계 - 14열 리포트를 만든다.")
    ap.add_argument("--dir", default=".",
                    help="**코너 폴더 하나** (안에 xtalk/ 이 있는 폴더)")
    ap.add_argument("--corner", default=None,
                    help="결과 파일 이름에 쓸 코너 이름. 안 주면 폴더 이름")
    ap.add_argument("--out", default=None, help="결과 파일 경로를 직접 줄 때")
    args = ap.parse_args()

    d = args.dir
    work = os.path.join(d, "xtalk")
    corner = args.corner or os.path.basename(os.path.abspath(d))

    print("=" * 68)
    print("5c - 14열 crosstalk 리포트 만들기")
    print("=" * 68)

    feats = os.path.join(work, "active_features.tsv")
    victim = os.path.join(work, "path_victim_nets.tsv")
    vwin = os.path.join(work, "victim_windows.tsv")
    awin = os.path.join(work, "aggressor_windows.tsv")

    missing = [p for p in (feats, victim, vwin, awin) if not os.path.isfile(p)]
    if missing:
        code("E-NOINPUT",
             "[ 실패 ] 앞 단계 결과가 없습니다:",
             *["           %s" % p for p in missing])

    flat = os.path.join(work, "compact_flat.tsv")
    out = args.out or os.path.join(
        d, "%s.path_context_si_compact.by_path.rpt" % corner)

    cmd = [sys.executable,
           os.path.join(XTALK, "make_compact_path_context_report.py"),
           feats, victim, vwin, awin, flat, out]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = as_text(p.communicate()[0])
    if p.returncode != 0:
        code("E-BUILD", "[ 실패 ] 리포트 생성 실패", text[-800:])

    info = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()

    n_path = int(info.get("paths", 0))
    n_row = int(info.get("rows", 0))

    print("")
    print("-" * 68)
    print("  경로     : %d" % n_path)
    print("  쌍(줄)   : %d" % n_row)
    print("  컬럼     : %s" % info.get("columns", "?"))
    print("  결과 파일: %s" % out)
    print("  평평한 것: %s" % flat)
    print("-" * 68)

    if n_row == 0:
        code("E-NOROW", "[ 실패 ] 줄이 0개입니다.")

    print("[ 정상 ] %d경로 %d줄 14열. 기존 by_path.rpt 와 같은 형식입니다."
          % (n_path, n_row))
    code("OK-XRPT")


if __name__ == "__main__":
    main()
