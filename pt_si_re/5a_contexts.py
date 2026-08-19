#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5a - crosstalk 쌍(pair) 리포트 1단계: 어느 넷을 PT 에 물어볼지 목록을 만든다.

    python3 5a_contexts.py --dir <코너폴더>

setup / hold 공통이다. 이 단계는 경로 구조만 읽어 -delay_type 을 가리지 않으므로
mode 옵션이 없다. (가리는 곳은 1_union.py 와 5b_pairs.py 두 곳뿐이다)

넣는 것   <코너>_fixed_annotated.txt (2c_merge.py) 또는 원본 <코너>.rpt
          crosstalk 은 Dist/Res/Cpin 을 안 쓰므로 둘 중 아무거나 된다
나오는 것 xtalk/path_victim_nets.tsv     경로별 victim 넷 + 구간(launch/data/capture)

**unique_contexts.tsv 는 만들지 않는다.** 그건 담당자분 쪽 산출물이다.
xtalk_all.tcl 이 PT 안에서 만들고, 우리가 받는 것이다. 5a 가 같은 이름으로
덮어쓰면 "PT 가 실제로 무엇을 물어봤는지" 기록이 사라진다.

왜 필요한가
    PT 는 우리가 못 돌립니다. 담당자분이 fixed_paths.tcl 과 xtalk_all.tcl 을
    돌려 주시고, 우리는 그 결과를 받아 이어서 합니다. 그래서 PT 보다 먼저
    할 일은 없고, 이 단계는 **받은 뒤에** 돕니다.

    받은 폴더에 unique_contexts.tsv 가 이미 있는데도 5a 를 도는 이유는
    path_victim_nets.tsv 하나 때문입니다. 5c 가 그것을 쓰는데 PT 쪽 산출물에는
    없습니다(PT 는 경로 개념이 없어서 안 만듭니다). 같은 리포트에서 만드는
    것이라 결과는 같습니다.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()
XTALK = os.path.join(HERE, "_engine", "xtalk")
from names import find_annotated

CODE_INFO = {
    "E-NOENGINE": ("패키지 파일(_engine/xtalk/)이 없습니다",
                   "pt_si_re 폴더를 통째로 옮기세요. _engine/ 이 빠지면 "
                   "crosstalk 단계가 돌지 않습니다."),
    "E-NOANNOT":  ("읽을 리포트가 없습니다",
                   "2회차 리포트(.rpt)나 *_fixed_annotated.txt 가 그 폴더에 "
                   "있어야 합니다."),
    "E-PARSE":    ("annotated.txt 을 읽다가 실패했습니다",
                   "2c_merge.py 가 정상(OK-MERGE)으로 끝났는지 확인해 주세요."),
    "E-NOCTX":    ("리포트에서 victim 넷을 하나도 못 찾았습니다",
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



def need_parser(name):
    """_engine/xtalk/ 의 파서가 있는지 먼저 본다.

    없으면 '리포트 생성 실패' 같은 엉뚱한 안내가 나와 엉뚱한 데를 뒤지게 된다.
    패키지를 옮길 때 _engine/ 을 빠뜨리면 실제로 이렇게 된다.
    """
    p = os.path.join(XTALK, name)
    if not os.path.isfile(p):
        code("E-NOENGINE",
             "[ 실패 ] 패키지 파일이 없습니다: %s" % p,
             "         _engine/xtalk/ 폴더가 통째로 필요합니다.",
             "         패키지를 옮길 때 _engine/ 을 빠뜨리지 않았는지 보세요.")

def main():
    ap = argparse.ArgumentParser(
        description="crosstalk 쌍 리포트 1단계 - PT 에 물어볼 넷 목록을 만든다.")
    ap.add_argument("--dir", default=".",
                    help="**코너 폴더 하나** (annotated.txt 이 있는 폴더)")
    ap.add_argument("--annotated", default=None, help="annotated.txt 경로를 직접 줄 때")
    ap.add_argument("--xtalk", default=None,
                    help="xtalk 폴더 절대경로를 직접 줄 때. "
                         "주면 --dir 아래 xtalk/ 를 찾지 않는다")
    args = ap.parse_args()

    need_parser('parse_annotated_with_clock_segments.py')

    d = args.dir
    ann = args.annotated
    if not ann:
        # crosstalk 은 Dist/Res/Cpin 을 안 쓰므로 원본 .rpt 로도 된다.
        # 그래도 있으면 annotated 를 쓴다(같은 리포트에 열만 더 붙은 것).
        ann, _e = find_annotated(d)
        if not ann:
            from find_rpt import find_rpt
            ann, _e2, _c2 = find_rpt(d)
            if not ann:
                code("E-NOANNOT", "[ 실패 ] 읽을 리포트가 없습니다: %s" % d)
    work = args.xtalk or os.path.join(d, "xtalk")

    print("=" * 68)
    print("5a - path_victim_nets.tsv (경로별 victim 넷 + 구간)")
    print("=" * 68)

    if not os.path.isdir(work):
        os.makedirs(work)

    print("  입력 : %s" % ann)

    summary = os.path.join(work, "path_summary.tsv")
    victim = os.path.join(work, "path_victim_nets.tsv")
    ok, out = run("parse_annotated_with_clock_segments.py", ann, summary, victim)
    if not ok:
        code("E-PARSE", "[ 실패 ] annotated.txt 파싱 실패", out[-800:])

    # unique_contexts.tsv 는 만들지 않는다 -- 담당자분 쪽 산출물이다.

    n_path = count_rows(summary)
    n_victim = count_rows(victim)

    print("")
    print("-" * 68)
    print("  경로            : %d" % n_path)
    print("  victim 넷 줄    : %d  (경로마다 중복 포함)" % n_victim)
    print("  작업 폴더       : %s" % work)
    print("-" * 68)

    if n_victim == 0:
        code("E-NOCTX", "[ 실패 ] 리포트에서 victim 넷을 하나도 못 찾았습니다.")

    # PT 는 담당자분이 이미 돌려 주신 것이라, 그 결과가 이 폴더에 왔는지만 본다.
    # 여기서 "pt_shell 에서 돌리세요" 라고 안내하면 안 된다 -- 우리는 PT 를 못 돌린다.
    nxt = ("--xtalk %s" % os.path.abspath(work)) if args.xtalk \
        else ("--dir %s" % os.path.abspath(d))
    if os.path.exists(os.path.join(work, "context_raw.rpt")):
        print("[ 정상 ] victim 넷 %d줄. PT 출력도 와 있습니다(context_raw.rpt)." % n_victim)
        print("         다음은 셸에서:")
        print("           python3 %s %s" % (os.path.join(HERE, "5b_pairs.py"), nxt))
    else:
        print("[ 정상 ] victim 넷 %d줄." % n_victim)
        print("         다만 PT 출력(context_raw.rpt)이 이 폴더에 없습니다.")
        print("         담당자분께 받은 xtalk/ 를 이 폴더에 두셔야 5b 가 돕니다.")
        print("         받은 것이 맞는지 먼저 보려면:")
        print("           python3 %s --dir %s"
              % (os.path.join(HERE, "6_check_xtalk.py"), os.path.abspath(d)))
    code("OK-XCTX")


if __name__ == "__main__":
    main()
