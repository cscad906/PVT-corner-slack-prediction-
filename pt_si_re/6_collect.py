#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""6 - 다 돌린 결과에서 **최종 파일 2종만** 뽑아 넘길 형태로 모은다.

    python3 6_collect.py --root round2      --out deliver --mode setup
    python3 6_collect.py --root round2_hold --out deliver --mode hold

setup 과 hold 는 **작업 폴더가 따로**다(별개 2세트). --out 은 같은 곳을 주면
그 아래에 setup/ 과 hold/ 로 갈려 담긴다.

파이프라인은 코너마다 작업 폴더를 쓴다(cpin.tsv, distres.tsv, xtalk/... 등).
넘길 때는 그게 다 필요 없고 최종 2종만 있으면 된다. 그걸 아래 형태로 모은다.

    <out>/setup/
        report.<코너>_fixed_annotated.rpt          <- annotation
        xtalk/
            xt.<코너>.path_context_si_compact.by_path.rpt   <- crosstalk
    <out>/hold/
        (같은 구조. --mode hold 로 한 번 더 돌린다)

원본은 **건드리지 않는다.** 복사만 한다(기본). --move 를 주면 옮긴다.

코너 이름은 코너 폴더 이름을 그대로 쓴다. 파일 이름이 코너와 다르더라도
폴더 이름으로 맞춰 준다 -- 모아 놓고 보면 어느 코너인지가 이름뿐이라
여기서 통일해 두는 편이 낫다.
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()

# 찾을 것 (코너 폴더 기준) -> 모을 때 붙일 이름
ANNOT_SUFFIX = "_fixed_annotated.txt"
XTALK_SUFFIX = ".path_context_si_compact.by_path.rpt"

ANNOT_OUT = "report.%s_fixed_annotated.rpt"      # % 코너
XTALK_OUT = "xt.%s" + XTALK_SUFFIX               # % 코너

CODE_INFO = {
    "E-NOROOT":   ("코너 폴더를 못 찾았습니다",
                   "--root 에 코너 폴더들이 **들어 있는 상위 폴더**를 주세요."),
    "E-NOTHING":  ("모을 파일이 하나도 없습니다",
                   "4_all_corners.py 를 묶음 1, 2 까지 돌렸는지 확인해 주세요."),
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


def find_one(d, suffix):
    """폴더에서 그 꼬리를 가진 파일 하나. 여러 개면 제일 큰 것."""
    hits = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(suffix)]
    if not hits:
        return None
    hits.sort(key=lambda p: -os.path.getsize(p))
    return hits[0]


def corner_dirs(root):
    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if os.path.isdir(d) and name != "xtalk":
            out.append((name, d))
    return out


def put(src, dst, move):
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    if move:
        shutil.move(src, dst)
    else:
        shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser(
        description="최종 파일 2종만 넘길 형태로 모은다.")
    ap.add_argument("--root", required=True,
                    help="코너 폴더들이 들어 있는 상위 폴더 (예: round2)")
    ap.add_argument("--out", required=True,
                    help="모아 둘 폴더. 그 아래 setup/ 또는 hold/ 가 생긴다")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup / hold. 이 이름으로 하위 폴더를 만든다")
    ap.add_argument("--move", action="store_true",
                    help="복사 대신 옮긴다 (기본은 복사, 원본 보존)")
    args = ap.parse_args()

    print("=" * 68)
    print("7 - 최종 결과 모으기  (%s)" % args.mode)
    print("=" * 68)

    if not os.path.isdir(args.root):
        code("E-NOROOT", "[ 실패 ] 폴더가 없습니다: %s" % args.root)
    corners = corner_dirs(args.root)
    if not corners:
        code("E-NOROOT", "[ 실패 ] %s 아래에 코너 폴더가 없습니다." % args.root)

    base = os.path.join(args.out, args.mode)
    xdir = os.path.join(base, "xtalk")
    for p in (base, xdir):
        if not os.path.isdir(p):
            os.makedirs(p)

    print("  대상   : %s" % os.path.abspath(args.root))
    print("  모을 곳: %s" % os.path.abspath(base))
    print("  방식   : %s" % ("옮기기" if args.move else "복사"))
    print("")
    print("  %-26s %-38s %s" % ("코너", "annotation", "crosstalk"))
    print("  " + "-" * 76)

    n_a = n_x = 0
    missing = []
    for name, d in corners:
        a = find_one(d, ANNOT_SUFFIX)
        xd = os.path.join(d, "xtalk")
        x = find_one(d, XTALK_SUFFIX)
        if x is None and os.path.isdir(xd):
            x = find_one(xd, XTALK_SUFFIX)

        got_a = got_x = "-"
        if a:
            dst = os.path.join(base, ANNOT_OUT % name)
            put(a, dst, args.move)
            got_a = os.path.basename(dst)
            n_a += 1
        else:
            missing.append("%s : annotation 없음" % name)
        if x:
            dst = os.path.join(xdir, XTALK_OUT % name)
            put(x, dst, args.move)
            got_x = os.path.basename(dst)
            n_x += 1
        else:
            missing.append("%s : crosstalk 없음" % name)
        print("  %-26s %-38s %s" % (name[:26], got_a[:38], got_x[:40]))

    print("")
    print("-" * 68)
    print("  annotation : %d개" % n_a)
    print("  crosstalk  : %d개" % n_x)
    if missing:
        print("")
        print("  [ 없는 것 ]")
        for m in missing:
            print("    %s" % m)
    if n_a == 0 and n_x == 0:
        code("E-NOTHING", "")
    print("")
    print("  넘기실 것 : %s" % os.path.abspath(args.out))
    code("OK-COLLECT")


if __name__ == "__main__":
    main()
