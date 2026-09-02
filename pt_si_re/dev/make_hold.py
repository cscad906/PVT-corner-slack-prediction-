#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xtalk_all.tcl -> xtalk_all_hold.tcl 을 다시 만든다.

    python3 dev/make_hold.py

두 파일은 DELAY_TYPE 한 줄만 다르다. xtalk_all.tcl 을 고쳤으면 이걸 돌려
hold 판을 맞춰 준다. 안 그러면 두 파일이 조용히 어긋난다.
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, os.pardir, "pt", "xtalk_all.tcl")
DST = os.path.join(HERE, os.pardir, "pt", "xtalk_all_hold.tcl")

OLD = 'set DELAY_TYPE "max"      ;# setup=max, hold=min'
NEW = 'set DELAY_TYPE "min"      ;# ★ hold 판. setup 은 xtalk_all.tcl 을 쓴다'
# 리포트 기본 이름도 setup/hold 가 다르다. 한 줄만 다른 사본이라는 약속을
# 지키려면 여기서 같이 바꿔 줘야 한다.
RPT_OLD = 'set RPT_FILE   "fix_setup.rpt"'
RPT_NEW = 'set RPT_FILE   "fix_hold.rpt" '

HDR_OLD = "# xtalk_all.tcl  --  crosstalk PT 작업을 **한 번에** (PT 1차 + 2차 합침)"
HDR_NEW = ("# xtalk_all_hold.tcl  --  crosstalk PT 작업을 **한 번에** (hold 판)\n"
           "#\n"
           "# xtalk_all.tcl 과 두 줄(DELAY_TYPE, RPT_FILE)만 다른 사본이다.\n"
           "# 고칠 일이 있으면 xtalk_all.tcl 을 고치고 dev/make_hold.py 로 다시 만든다.\n"
           "# 결과는 <db이름>_hold/xtalk/ 에 들어가므로 setup 과 안 섞인다.")


def main():
    s = io.open(SRC, encoding="utf-8").read()
    for pat in (OLD, HDR_OLD, RPT_OLD):
        if s.count(pat) != 1:
            print("[ 실패 ] xtalk_all.tcl 에서 이 줄을 못 찾았습니다:")
            print("         %s" % pat)
            print("         그 줄을 고쳤다면 이 스크립트의 OLD/HDR_OLD 도 맞춰 주세요.")
            return 1
    s = s.replace(OLD, NEW).replace(HDR_OLD, HDR_NEW).replace(RPT_OLD, RPT_NEW)
    io.open(DST, "w", encoding="utf-8").write(s)
    print("[ 정상 ] %s 을(를) 다시 만들었습니다." % DST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
