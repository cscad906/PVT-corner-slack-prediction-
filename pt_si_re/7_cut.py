#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""7 - 다 만든 산출물을 **앞에서부터 경로 N개**만 남긴 사본으로 만든다.

    python3 7_cut.py --root round2 --keep 300
    python3 7_cut.py --file round2/tt0p6v25c_Cnom/tt0p6v25c_Cnom_fixed_annotated.txt --keep 300

무엇을 왜 하나
    1_union.py --max-paths 는 **2회차를 돌리기 전에** 개수를 정하는 것이다.
    이미 PT 를 다 돌려 최종 파일까지 나온 뒤에 "역시 300개면 충분하다" 가 되면
    PT 를 다시 부탁드릴 수는 없다. 그때 **나온 파일을 그대로 자른다.**

    자르는 단위는 `### FIXED_PATH` 블록이고, 순서는 파일에 나온 순서 그대로다.
    그 순서는 1회차 worst_slack 나쁜 것부터라, "앞에서부터 N개" = "제일 위험한
    N개" 다. slack 으로 다시 정렬해 자르지 않는다 -- 그러면 코너마다 다른 경로가
    남아 코너 간 짝이 깨진다.

왜 'idx <= N' 이 아니라 '앞에서 N개' 인가
    현장 리포트는 idx 가 1부터 시작하지 않거나 중간이 비는 경우가 있다. PT 가
    그 경로를 못 잡으면 그 idx 가 통째로 빠지기 때문이다. 그런 파일에
    `idx <= N` 을 걸면 N개보다 적게 남는다. 그래서 **번호를 안 보고 순서로**
    센다. idx 가 어떻게 생겼든 항상 N개가 나온다.

    대신 실제로 남은 idx 범위를 화면에 찍는다. 코너끼리 남은 idx 집합이 다르면
    W-IDXDIFF 로 알린다 -- 구멍 위치가 코너마다 다르면 코너 간 짝이 어긋난다.

경로가 안 잡힌 블록
    fixed_paths.tcl 은 report_timing 이 실패해도 **마커를 먼저 찍는다**
    (`puts "### FIXED_PATH idx=$idx key=$key"` 다음에 eval). 그래서 마커는
    있는데 아래에 타이밍표 대신 PT 에러/경고만 든 블록이 있을 수 있다.
    그런 블록도 하나로 세어 남긴다. 몇 개인지는 measured 열에 찍고, 있으면
    W-EMPTY 로 알린다. fixed_paths.tcl 이 끝에 찍는 "paths measured" 와 같은
    숫자다.

무엇을 자를 수 있나
    ### FIXED_PATH 로 블록이 갈리는 파일이면 다 된다. 지금 해당하는 것:

        <코너>_fixed_annotated.txt                        (2c 산출물 1)
        <코너>.path_context_si_compact.by_path.rpt        (5c 산출물 2)
        <코너>.rpt                                        (PT 2회차 원본)

    fixed_paths.tcl 도 된다(.tcl 로 끝나면 알아서 그쪽으로 간다). 이건 안의
    FIXED_PATHS 목록을 앞 N개만 남긴다. 1회차 리포트가 없어 1_union.py 를 다시
    못 돌릴 때 쓴다.

원본은 건드리지 않는다
    항상 **다른 폴더에** 쓴다. 이름은 그대로 두므로 자른 폴더를 그대로
    6_collect.py 에 넣으면 된다.

        python3 7_cut.py     --root round2 --keep 300
        python3 6_collect.py --root round2_top300 --out deliver --mode setup

    --root 를 주면 결과는 <root>_top<N>/ 에, 코너 폴더 구조를 그대로 만든다.
    --file 을 주면 그 파일 옆 top<N>/ 안에 같은 이름으로 만든다.
    --out 으로 직접 정할 수도 있다.

메모리
    한 줄씩 흘려 읽고 흘려 쓴다. 파일이 몇 GB 든 메모리는 거의 안 쓴다.

옵션
    --root <폴더>    코너 폴더들이 들어 있는 상위 폴더
    --file <파일>    파일 하나만 자를 때
    --keep N         남길 경로 수                                    (필수)
    --out <경로>     결과 위치. 생략하면 위 규칙대로 정한다
    --jobs N (-j N)  동시에 처리할 코너 수 (기본 4)
    --force          결과가 이미 있어도 덮어쓴다
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8, wopen
force_utf8()

MARK = "### FIXED_PATH"
IDXTAG = "idx="
TCL_LIST = "set FIXED_PATHS"
# 그 블록에 진짜 타이밍 경로가 담겼는지 보는 표시. fixed_paths.tcl 이 끝에
# "paths measured" 를 셀 때 쓰는 것과 같은 표시라 숫자가 서로 맞는다.
MEASURED = "Startpoint:"

# 코너 폴더에서 찾을 것. 파일 이름은 그대로 유지한다(6_collect.py 가 꼬리로 찾는다).
WANTED = (
    "_fixed_annotated.txt",
    ".path_context_si_compact.by_path.rpt",
)

CODE_INFO = {
    "E-ARGS":    ("--root or --file is required (exactly one)",
                  "give --root <folder of corner folders>, or --file <one file>."),
    "E-KEEP":    ("--keep must be 1 or more",
                  "give the number of paths to keep, e.g. --keep 300."),
    "E-NOROOT":  ("the folder or file does not exist",
                  "check the path."),
    "E-NOTHING": ("no file to cut was found",
                  "corner folders must hold *_fixed_annotated.txt or "
                  "*.path_context_si_compact.by_path.rpt. Run 4_all_corners.py first."),
    "E-EXISTS":  ("the output already exists",
                  "give --force to overwrite, or pick another --out."),
    "E-NOMARK":  ("the file has no '### FIXED_PATH' block at all",
                  "this tool cuts by path block, so it only takes files that carry "
                  "that marker (or a fixed_paths.tcl)."),
    "W-EMPTY":   ("some kept blocks hold no path -- only a PT message",
                  "that is what fixed_paths.tcl reports as 'paths measured'. "
                  "The block is still counted as one path, so the file holds fewer "
                  "usable paths than --keep. Raise --keep if you need more."),
    "W-SHORT":   ("some file holds fewer paths than --keep",
                  "nothing was lost -- the file simply had fewer."),
    "W-UNEVEN":  ("files did not end up with the same number of paths",
                  "cross-corner pairing needs the same paths everywhere. "
                  "Lower --keep to the smallest count shown above."),
    "W-IDXDIFF": ("files kept the same count but NOT the same idx numbers",
                  "a corner is missing an idx the others have, so row 7 of one "
                  "corner is not row 7 of another. Compare the idx ranges above "
                  "before handing the data over."),
    "W-NOIDX":   ("some marker lines carry no readable idx",
                  "the block was still kept -- cutting goes by order, not by "
                  "number. But idx is how corners are paired, so check the file."),
}


def code(c, *msg):
    """무슨 일이 있었는지 설명하고 코드를 찍는다. (2b/2c 와 같은 규약)"""
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  DONE                [ %s ]" % c)
        print("=" * 66)
        return
    what, todo = CODE_INFO.get(c, ("", ""))
    kind = "FAILED" if c.startswith("E-") else "CHECK"
    # 코드는 반드시 "[ CODE ]" 형태로 한 번 찍는다 -- 4_all_corners.py 가 이 형태로
    # 읽는다. 안 그러면 코너별 결과표에 "?" 로 남는다.
    print("  %-19s [ %s ]" % (kind, c))
    if what:
        print("    what   : %s" % what)
        print("    to do  : %s" % todo)
    print("=" * 66)
    sys.exit(1 if c.startswith("E-") else 0)


def idx_of(line):
    """'### FIXED_PATH idx=12 key=...' -> 12. 못 읽으면 None.

    idx 가 없거나 이상해도 블록은 그대로 센다. 자르는 것은 순서로 하고,
    idx 는 보고용으로만 읽는다.
    """
    p = line.find(IDXTAG)
    if p < 0:
        return None
    n = 0
    got = False
    for ch in line[p + len(IDXTAG):]:
        if ch.isdigit():
            n = n * 10 + (ord(ch) - 48)
            got = True
        else:
            break
    return n if got else None


def cut_blocks(src, dst, keep):
    """앞에서부터 블록 N개만 남긴다. 한 줄씩 흘려 보낸다.

    첫 블록 앞의 머리말은 그대로 옮긴다. 지금 산출물에는 머리말이 없지만,
    있어도 잃지 않게 해 둔다.

    돌려주는 것:
        kept     남긴 블록 수
        total    원래 블록 수
        measured 남긴 것 중 진짜 경로가 담긴 수
        noidx    남긴 것 중 idx 를 못 읽은 수
        idxs     남긴 블록의 idx 목록 (못 읽은 것은 None)
    """
    total = kept = measured = noidx = 0
    idxs = []
    this_ok = False
    writing = True
    with open(src, "r", errors="ignore") as fi, wopen(dst) as fo:
        for line in fi:
            if line.startswith(MARK):
                if writing and this_ok:
                    measured += 1
                this_ok = False
                total += 1
                writing = kept < keep          # 번호가 아니라 순서로 자른다
                if writing:
                    kept += 1
                    i = idx_of(line)
                    idxs.append(i)
                    if i is None:
                        noidx += 1
            elif writing and not this_ok and MEASURED in line:
                this_ok = True
            if writing:
                fo.write(line)
    if writing and this_ok:
        measured += 1
    return kept, total, measured, noidx, idxs


def cut_tcl(src, dst, keep):
    """fixed_paths.tcl 의 FIXED_PATHS 목록을 앞 N개만 남긴다.

    항목은 한 줄에 하나다(1_union.py 가 그렇게 쓴다). 목록 밖의 줄 -- 머리말,
    proc, 리포트 루프 -- 은 하나도 안 건드린다.
    """
    total = kept = 0
    state = 0          # 0=목록 전, 1=목록 안, 2=목록 후
    with open(src, "r", errors="ignore") as fi, wopen(dst) as fo:
        for line in fi:
            if state == 0:
                fo.write(line)
                if line.startswith(TCL_LIST) and "{" in line:
                    state = 1
                continue
            if state == 1:
                if line.startswith("}"):
                    state = 2
                    fo.write(line)
                    continue
                if line.lstrip().startswith("{"):
                    total += 1
                    if total <= keep:
                        kept += 1
                        fo.write(line)
                    continue
                fo.write(line)       # 목록 안의 주석/빈 줄은 그대로
                continue
            fo.write(line)
    # tcl 에는 '경로가 잡혔나' 라는 개념이 없다. 목록 순서가 곧 idx 라 1..kept.
    return kept, total, kept, 0, list(range(1, kept + 1))


def cut_one(src, dst, keep):
    """확장자를 보고 알맞은 방식으로 자른다."""
    d = os.path.dirname(os.path.abspath(dst))
    if not os.path.isdir(d):
        # 코너 하나에 파일이 둘이라 --jobs 로 동시에 돌면 같은 폴더를 둘이 만든다.
        # 진 쪽이 FileExistsError 로 죽으므로, 이미 생겼으면 넘어간다.
        try:
            os.makedirs(d)
        except OSError:
            if not os.path.isdir(d):
                raise
    if src.endswith(".tcl"):
        return cut_tcl(src, dst, keep)
    return cut_blocks(src, dst, keep)


def corner_dirs(root):
    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if os.path.isdir(d) and name != "xtalk":
            out.append((name, d))
    return out


def targets_in(d):
    """코너 폴더에서 자를 파일들. 코너 폴더와 xtalk/ 둘 다 본다.
    (root 기준 상대 위치를 그대로 살려야 6_collect.py 가 다시 찾는다)"""
    hits = []
    for sub in ("", "xtalk"):
        p = os.path.join(d, sub) if sub else d
        if not os.path.isdir(p):
            continue
        for n in sorted(os.listdir(p)):
            if any(n.endswith(s) for s in WANTED):
                hits.append((os.path.join(p, n), os.path.join(sub, n) if sub else n))
    return hits


def rng(idxs):
    """남은 idx 를 'first..last' 로. 구멍이 있으면 개수를 덧붙인다."""
    got = [i for i in idxs if i is not None]
    if not got:
        return "-"
    lo, hi = min(got), max(got)
    holes = (hi - lo + 1) - len(set(got))
    s = "%d..%d" % (lo, hi)
    if holes > 0:
        s += " (-%d)" % holes
    return s


def main():
    ap = argparse.ArgumentParser(
        description="최종 산출물을 앞에서부터 경로 N개만 남긴 사본으로 만든다.")
    ap.add_argument("--root", help="코너 폴더들이 들어 있는 상위 폴더")
    ap.add_argument("--file", help="파일 하나만 자를 때")
    ap.add_argument("--keep", type=int, required=True, metavar="N",
                    help="남길 경로 수 (앞에서부터)")
    ap.add_argument("--out", help="결과 위치. 생략하면 <root>_top<N> / <폴더>/top<N>")
    ap.add_argument("--jobs", "-j", type=int, default=4, metavar="N",
                    help="동시에 처리할 코너 수 (기본 4)")
    ap.add_argument("--force", action="store_true",
                    help="결과가 이미 있어도 덮어쓴다")
    args = ap.parse_args()

    print("=" * 68)
    print("7 - cut to the first %d paths" % args.keep)
    print("=" * 68)

    if bool(args.root) == bool(args.file):
        code("E-ARGS", "[ FAILED ] give exactly one of --root / --file.")
    if args.keep < 1:
        code("E-KEEP", "[ FAILED ] --keep %d" % args.keep)

    # ---- 자를 것 모으기 : (코너이름, 원본, 결과) ------------------------
    jobs = []
    if args.file:
        if not os.path.isfile(args.file):
            code("E-NOROOT", "[ FAILED ] no such file: %s" % args.file)
        base = os.path.basename(args.file)
        if args.out:
            dst = args.out
            if os.path.isdir(dst):
                dst = os.path.join(dst, base)
        else:
            dst = os.path.join(os.path.dirname(os.path.abspath(args.file)),
                               "top%d" % args.keep, base)
        jobs.append(("(file)", args.file, dst))
        out_root = os.path.dirname(os.path.abspath(dst))
    else:
        if not os.path.isdir(args.root):
            code("E-NOROOT", "[ FAILED ] no such folder: %s" % args.root)
        corners = corner_dirs(args.root)
        if not corners:
            code("E-NOROOT", "[ FAILED ] no corner folder under %s" % args.root)
        out_root = args.out or (os.path.abspath(args.root.rstrip("/\\"))
                                + "_top%d" % args.keep)
        for name, d in corners:
            for src, rel in targets_in(d):
                jobs.append((name, src, os.path.join(out_root, name, rel)))
        if not jobs:
            code("E-NOTHING", "[ FAILED ] nothing to cut under %s" % args.root)

    exists = [j[2] for j in jobs if os.path.exists(j[2])]
    if exists and not args.force:
        code("E-EXISTS",
             "[ FAILED ] %d output file(s) already there, e.g." % len(exists),
             "           %s" % exists[0])

    print("  from   : %s" % os.path.abspath(args.root or args.file))
    print("  to     : %s" % os.path.abspath(out_root))
    print("  files  : %d" % len(jobs))
    print("")
    print("  %-20s %-40s %10s %-16s %8s"
          % ("corner", "file", "kept", "idx kept", "measured"))
    print("  " + "-" * 100)

    def one(job):
        name, src, dst = job
        try:
            return (name, src) + cut_one(src, dst, args.keep) + (None,)
        except Exception as e:                       # noqa: BLE001
            return name, src, None, None, None, None, None, str(e)

    n = max(1, min(args.jobs, len(jobs)))
    if n > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=n) as ex:
            done = list(ex.map(one, jobs))
    else:
        done = [one(j) for j in jobs]

    # 표는 항상 같은 순서로 낸다. 끝난 순서로 내면 돌릴 때마다 달라진다.
    counts = set()
    idxsets = {}
    short, failed, empties = [], [], []
    noidx_all = n_block_files = 0
    for name, src, kept, total, meas, noidx, idxs, err in done:
        base = os.path.basename(src)
        if err:
            failed.append("%s : %s" % (base, err))
            print("  %-20s %-40s %10s %-16s %8s"
                  % (name[:20], base[:40], "FAILED", "-", "-"))
            continue
        if total == 0:
            print("  %-20s %-40s %10s %-16s %8s"
                  % (name[:20], base[:40], "no marker", "-", "-"))
            continue
        n_block_files += (0 if src.endswith(".tcl") else 1)
        noidx_all += noidx
        if total < args.keep:
            short.append("%s / %s : has %d, asked %d" % (name, base, total, args.keep))
        if not src.endswith(".tcl"):
            counts.add(kept)
            idxsets.setdefault(
                tuple(i for i in idxs if i is not None), []).append("%s/%s" % (name, base))
            if meas < kept:
                empties.append("%s / %s : %d of %d kept blocks hold no path"
                               % (name, base, kept - meas, kept))
        print("  %-20s %-40s %5d /%4d %-16s %8d"
              % (name[:20], base[:40], kept, total, rng(idxs), meas))

    print("")
    print("-" * 68)
    for f in failed:
        print("  [ FAILED ] %s" % f)
    if n_block_files == 0 and not failed:
        code("E-NOMARK", "")

    print("  kept per file : %s" % (", ".join(str(c) for c in sorted(counts)) or "-"))
    print("  output        : %s" % os.path.abspath(out_root))
    if args.root:
        # 결과가 딴 데 있으면 상대경로가 ../../.. 로 길어진다. 그럴 땐 절대경로로.
        shown = os.path.relpath(out_root)
        if shown.startswith(".."):
            shown = os.path.abspath(out_root)
        print("")
        print("  next :  python3 6_collect.py --root %s --out deliver --mode setup"
              % shown)

    # 확인할 것은 **전부** 찍고, 코드는 제일 무거운 것 하나만 낸다.
    # (code() 는 코드를 찍고 바로 끝내므로, 먼저 부르면 나머지가 묻힌다)
    issues = []
    if len(counts) > 1:
        issues.append(("W-UNEVEN",
                       ["  [ CHECK ] files kept different numbers of paths."]
                       + ["    %s" % s for s in short]))
    if len(idxsets) > 1:
        issues.append(("W-IDXDIFF",
                       ["  [ CHECK ] %d different idx sets among the files:"
                        % len(idxsets)]
                       + ["    %s ..." % ", ".join(v[:2]) for v in idxsets.values()]))
    if noidx_all:
        issues.append(("W-NOIDX",
                       ["  [ CHECK ] %d kept block(s) had no readable idx."
                        % noidx_all]))
    if empties:
        issues.append(("W-EMPTY",
                       ["  [ CHECK ] kept blocks that hold no path:"]
                       + ["    %s" % s for s in empties[:12]]))
    if short:
        issues.append(("W-SHORT",
                       ["  [ CHECK ] fewer paths than asked:"]
                       + ["    %s" % s for s in short]))

    if not issues:
        code("OK-CUT")
    for c, lines in issues:
        print("")
        for ln in lines:
            print(ln)
        if c != issues[0][0]:
            what, todo = CODE_INFO.get(c, ("", ""))
            print("    (%s -- %s)" % (c, what))
    code(issues[0][0])


if __name__ == "__main__":
    main()
