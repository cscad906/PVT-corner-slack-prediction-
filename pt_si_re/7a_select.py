#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""7a - 코너별로 고르게 경로 N개를 골라 **idx 목록**을 만든다. (7_cut.py 로 넘긴다)

    python3 7a_select.py --root round2 --keep 3000
    python3 7_cut.py     --root round2 --idx-file round2_select3000.idx
    python3 6_collect.py --root round2_sel3000 --out deliver --mode setup

무엇을 왜 하나
    1_union.py 가 매기는 idx 는 worst slack(그 경로의 전 코너 중 최소) 순이다.
    코너마다 slack 분포가 통째로 밀려 있으면 그 순서는 사실상 **제일 느린 코너의
    순위표**다. 그래서 7_cut.py --keep 으로 앞에서 N개를 자르면 그 코너 경로만
    남고, 빠른 코너에서만 빠듯한 경로는 하나도 안 들어온다. 1회차의
    -slack_lesser_than 이 코너마다 전혀 다른 의미가 되는 것도 같은 이유다.

    하지만 2회차는 **모든 경로를 모든 코너에서 다 쟀다.** 그 결과 파일에는 코너별
    slack 이 빠짐없이 들어 있다. 그러니 코너마다 자기 기준으로 줄을 세워 돌아가며
    뽑으면 코너 간 균형이 맞는다. 뽑은 목록은 전 코너에 똑같이 적용되므로 코너 간
    짝(같은 idx = 같은 경로)은 그대로 유지된다.

고르는 방법 (라운드로빈)
    코너마다 자기 slack 오름차순으로 줄을 세운 뒤, 1위부터 코너를 돌아가며
    하나씩 가져간다. 이미 뽑힌 경로는 건너뛴다.

        코너A: 1위 2위 3위 ...        A1 B1 C1 A2 B2 C2 ...
        코너B: 1위 2위 3위 ...   ->   (중복은 한 번만)
        코너C: 1위 2위 3위 ...

    코너가 C개면 각 코너는 최소 N/C 위까지 보장되고, 코너끼리 겹치는 경로가
    많을수록 더 깊이까지 들어간다.

후보
    **전 코너에서 실제로 측정된 idx** 만 후보로 쓴다. 어느 한 코너에서 PT 가 못
    잡은 경로(마커는 있는데 타이밍표가 없는 블록)를 넣으면 그 코너만 구멍이 나서
    코너 간 짝이 어긋난다.

무엇을 읽나
    <root>/<코너>/<코너>_fixed_annotated.txt   (2c 산출물)
    블록마다 `### FIXED_PATH idx=N` 과 그 안의 첫 `slack (...) <값>` 줄만 본다.
    한 줄씩 흘려 읽으므로 파일이 몇 GB 든 메모리는 (경로수 x 코너수) 뿐이다.

    union_paths.tsv 를 안 쓰는 이유: 거기 slack__<코너> 칸은 **1회차** 값이라,
    1회차에 아무것도 안 잡힌 코너는 통째로 빈칸이다. 지금 문제가 바로 그것이다.

한계
    2회차 풀 안에서만 다시 나눈다. 1회차에서 후보로 안 들어온 경로는 되살릴 수
    없다. 그건 1회차를 코너별 -max_paths 로 다시 뽑아야 한다.

옵션
    --root <폴더>     코너 폴더들이 들어 있는 상위 폴더 (2회차 작업 폴더)
    --keep N          고를 경로 수                                      (필수)
    --out <파일>      목록 파일 위치. 생략하면 <root>_select<N>.idx
    --jobs N (-j N)   동시에 읽을 코너 수 (기본 4)
    --force           목록 파일이 이미 있어도 덮어쓴다
    --skip-corner <이름>  이 코너는 뽑기에서 뺀다(측정은 그대로). 여러 번 줄 수 있다.
"""
import argparse
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8, wopen
force_utf8()

MARK = "### FIXED_PATH"
IDXTAG = "idx="
ANNOT_SUFFIX = "_fixed_annotated.txt"
# 2c 산출물의 slack 줄.  "  slack (VIOLATED)        -0.429594"
SLACK_RE = re.compile(r"^\s*slack\s*\(([^)]*)\)\s+(-?[\d.]+)")
# 커버리지 표에서 보여 줄 깊이
DEPTHS = (100, 500, 1000)

CODE_INFO = {
    "E-ARGS":    ("--root and --keep are required",
                  "give --root <folder of corner folders> and --keep <N>."),
    "E-NOROOT":  ("the folder does not exist",
                  "check --root."),
    "E-NOTHING": ("no corner holds a *_fixed_annotated.txt",
                  "run 4_all_corners.py --phase 1 first, or point --root at the "
                  "round-2 work folder."),
    "E-ONECORNER": ("only one corner was read",
                    "balancing needs at least two corners. with one corner the "
                    "plain 7_cut.py --keep is the same thing."),
    "E-NOCAND":  ("no path is measured in every corner",
                  "the corners share no idx at all. check the files with "
                  "7_cut.py first -- W-IDXDIFF tells which corner is missing what."),
    "E-EXISTS":  ("the list file already exists",
                  "give --force to overwrite, or pick another --out."),
    "W-FEWER":   ("fewer paths were picked than --keep",
                  "the shared candidate pool is smaller than asked. the list "
                  "still holds every candidate there is."),
    "W-DROPPED": ("some corner lost many paths from the candidate pool",
                  "those idx are missing from that corner's file, so they cannot "
                  "be used. run 7_cut.py to see the idx ranges per corner."),
}


def code(c, *msg):
    """무슨 일이 있었는지 설명하고 코드를 찍는다. (7_cut.py 와 같은 규약)"""
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
    print("  %-19s [ %s ]" % (kind, c))
    if what:
        print("    what   : %s" % what)
        print("    to do  : %s" % todo)
    print("=" * 66)
    sys.exit(1 if c.startswith("E-") else 0)


def idx_of(line):
    """'### FIXED_PATH idx=12 key=...' -> 12. 못 읽으면 None. (7_cut.py 와 같다)"""
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


def scan_annot(path, tick=None):
    """annotated 파일 하나 -> ({idx: slack}, 통계).

    블록 안의 **첫** slack 줄만 쓴다. 2회차는 경로마다 -max_paths 1 이라 한 줄이
    정상이고, 혹시 더 있어도 첫 줄이 그 경로의 값이다.

    마커는 있는데 slack 줄이 없는 블록 = PT 가 그 경로를 못 잡은 것. 후보에서
    빠져야 하므로 개수만 세어 돌려준다.
    """
    slacks = {}
    n_block = n_noslack = n_noidx = n_dup = 0
    cur = None
    have = False
    nbytes = 0
    with open(path, "r", errors="ignore") as fh:
        for line in fh:
            nbytes += len(line)
            if line.startswith(MARK):
                if tick is not None:
                    tick(n_block, nbytes)
                if cur is not None and not have:
                    n_noslack += 1
                n_block += 1
                cur = idx_of(line)
                have = False
                if cur is None:
                    n_noidx += 1
                continue
            if cur is None or have:
                continue
            m = SLACK_RE.match(line)
            if m:
                have = True
                if cur in slacks:
                    # 같은 idx 가 두 번 나오면 뒤엣것은 버린다. 코너 간 짝은
                    # idx 로 맞추므로 하나만 있어야 한다.
                    n_dup += 1
                else:
                    slacks[cur] = float(m.group(2))
    if cur is not None and not have:
        n_noslack += 1
    return slacks, {"block": n_block, "noslack": n_noslack,
                    "noidx": n_noidx, "dup": n_dup, "bytes": nbytes}


def corner_dirs(root):
    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if os.path.isdir(d) and name != "xtalk":
            out.append((name, d))
    return out


def annot_in(d):
    """코너 폴더에서 annotated 파일 하나. 없으면 None."""
    for n in sorted(os.listdir(d)):
        if n.endswith(ANNOT_SUFFIX):
            return os.path.join(d, n)
    return None


def fmt_dur(sec):
    sec = int(sec)
    if sec < 60:
        return "%ds" % sec
    if sec < 3600:
        return "%dm %ds" % (sec // 60, sec % 60)
    return "%dh %dm" % (sec // 3600, (sec % 3600) // 60)


def round_robin(corners, order, keep):
    """코너를 돌아가며 자기 순위 위에서부터 하나씩. 이미 뽑힌 것은 건너뛴다.

    돌려주는 것:
        picked  뽑힌 idx 목록 (뽑힌 순서 그대로 -- 앞쪽이 각 코너의 상위)
        owner   idx -> 그 경로를 처음 집어온 코너
    """
    picked = []
    owner = {}
    seen = set()
    ptr = dict((c, 0) for c in corners)
    while len(picked) < keep:
        moved = False
        for c in corners:
            lst = order[c]
            p = ptr[c]
            while p < len(lst) and lst[p] in seen:
                p += 1
            ptr[c] = p
            if p >= len(lst):
                continue
            i = lst[p]
            ptr[c] = p + 1
            seen.add(i)
            owner[i] = c
            picked.append(i)
            moved = True
            if len(picked) >= keep:
                break
        if not moved:            # 모든 코너의 줄이 동났다
            break
    return picked, owner


def coverage(order, chosen):
    """코너별로 '자기 순위 몇 위까지 담겼나' 를 센다.

    돌려주는 것: {코너: (deepest, {깊이: 담긴 수})}
        deepest  뽑힌 것 중 그 코너 기준 제일 낮은 순위 (클수록 깊이 내려간 것)
        깊이별   그 코너 top-K 중 몇 개가 목록에 들어갔나
    """
    out = {}
    for c, lst in order.items():
        deepest = 0
        got = dict((d, 0) for d in DEPTHS)
        for rank, i in enumerate(lst, 1):
            if i in chosen:
                deepest = rank
                for d in DEPTHS:
                    if rank <= d:
                        got[d] += 1
        out[c] = (deepest, got)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="2회차 결과에서 코너별로 고르게 경로를 골라 idx 목록을 만든다.")
    ap.add_argument("--root", help="코너 폴더들이 들어 있는 상위 폴더")
    ap.add_argument("--keep", type=int, metavar="N", help="고를 경로 수")
    ap.add_argument("--out", help="목록 파일. 생략하면 <root>_select<N>.idx")
    ap.add_argument("--jobs", "-j", type=int, default=4, metavar="N",
                    help="동시에 읽을 코너 수 (기본 4)")
    ap.add_argument("--force", action="store_true",
                    help="목록 파일이 이미 있어도 덮어쓴다")
    ap.add_argument("--skip-corner", action="append", default=[], metavar="NAME",
                    help="이 코너는 뽑기에서 뺀다 (여러 번 줄 수 있다)")
    args = ap.parse_args()

    print("=" * 68)
    print("7a - pick %s paths evenly across corners"
          % (args.keep if args.keep else "?"))
    print("=" * 68)

    if not args.root or not args.keep or args.keep < 1:
        code("E-ARGS", "[ FAILED ] give --root <folder> and --keep <N>.")
    if not os.path.isdir(args.root):
        code("E-NOROOT", "[ FAILED ] no such folder: %s" % args.root)

    out_path = args.out or (os.path.abspath(args.root.rstrip("/\\"))
                            + "_select%d.idx" % args.keep)
    if os.path.exists(out_path) and not args.force:
        code("E-EXISTS", "[ FAILED ] already there: %s" % out_path)

    # ---- 읽을 파일 모으기 ------------------------------------------------
    skip = set(args.skip_corner)
    jobs, missing, skipped = [], [], []
    for name, d in corner_dirs(args.root):
        f = annot_in(d)
        if f is None:
            missing.append(name)
            continue
        if name in skip:
            skipped.append(name)
            continue
        jobs.append((name, f))
    if not jobs:
        code("E-NOTHING", "[ FAILED ] nothing to read under %s" % args.root)

    total_mb = 0.0
    for _, f in jobs:
        try:
            total_mb += os.path.getsize(f) / (1024.0 * 1024.0)
        except OSError:
            pass

    print("  from   : %s" % os.path.abspath(args.root))
    print("  list   : %s" % out_path)
    print("  pick   : %d paths, round-robin over %d corner(s)" % (args.keep, len(jobs)))
    print("  files  : %d   (%.0f MB to read)" % (len(jobs), total_mb))
    if skipped:
        print("  skipped: %s   (--skip-corner)" % ", ".join(skipped))
    if missing:
        print("  [ CHECK ] %d corner(s) hold no %s -- not used here:"
              % (len(missing), ANNOT_SUFFIX))
        for m in missing[:10]:
            print("      %s" % m)
    print("")

    # ---- 코너별 slack 읽기 ----------------------------------------------
    lock = threading.Lock()
    t_start = time.time()
    state = {"done": 0}

    def one(job):
        name, path = job
        last = [time.time()]

        def tick(blocks, nbytes):
            now = time.time()
            if now - last[0] < 3.0:
                return
            last[0] = now
            with lock:
                print("        %-24s  reading %d blocks / %d MB"
                      % (name[:24], blocks, nbytes // (1024 * 1024)))
                sys.stdout.flush()

        t0 = time.time()
        err = None
        slacks, st = {}, {}
        try:
            slacks, st = scan_annot(path, tick)
        except Exception as e:                       # noqa: BLE001
            err = str(e)
        with lock:
            state["done"] += 1
            if err:
                print("  read  [%2d/%d] %-24s FAILED  %s"
                      % (state["done"], len(jobs), name[:24], err[:40]))
            else:
                print("  read  [%2d/%d] %-24s %6d paths  (%6d blocks, "
                      "%d without slack)   %s"
                      % (state["done"], len(jobs), name[:24], len(slacks),
                         st["block"], st["noslack"], fmt_dur(time.time() - t0)))
            sys.stdout.flush()
        return name, slacks, st, err

    n = max(1, min(args.jobs, len(jobs)))
    if n > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=n) as ex:
            done = list(ex.map(one, jobs))
    else:
        done = [one(j) for j in jobs]

    failed = [(name, err) for name, _, _, err in done if err]
    slack_of = {}
    corners = []
    for name, slacks, _, err in done:
        if err or not slacks:
            continue
        corners.append(name)
        slack_of[name] = slacks
    if failed:
        print("")
        for name, err in failed:
            print("  [ FAILED ] %s : %s" % (name, err))
    if len(corners) < 2:
        code("E-ONECORNER",
             "[ FAILED ] only %d corner(s) could be read." % len(corners))

    # ---- 후보 : 전 코너에서 측정된 idx 만 --------------------------------
    # 한 코너라도 빠진 idx 를 넣으면 그 코너만 구멍이 나서 짝이 어긋난다.
    cand = set(slack_of[corners[0]])
    for c in corners[1:]:
        cand &= set(slack_of[c])
    if not cand:
        code("E-NOCAND", "[ FAILED ] the corners share no idx.")

    print("")
    print("  candidate pool")
    print("  %-24s %10s %10s %10s" % ("corner", "measured", "dropped", "in pool"))
    print("  " + "-" * 58)
    heavy_drop = []
    for c in corners:
        have = len(slack_of[c])
        drop = have - len(cand)
        print("  %-24s %10d %10d %10d" % (c[:24], have, drop, len(cand)))
        # 자기만 갖고 있는 것이 많다 = 다른 코너에 그 idx 가 없다는 뜻이다.
        if have and drop > have * 0.1:
            heavy_drop.append("%s : %d of %d not measured everywhere"
                              % (c, drop, have))
    print("  " + "-" * 58)
    print("  %-24s %10s %10s %10d" % ("shared by all", "", "", len(cand)))

    # ---- 코너별 줄 세우기 + 라운드로빈 -----------------------------------
    # 같은 slack 이 여럿이면 idx 작은 쪽(= worst 기준 더 위험한 쪽)을 먼저 본다.
    order = dict((c, sorted(cand, key=lambda i, c=c: (slack_of[c][i], i)))
                 for c in corners)
    keep = min(args.keep, len(cand))
    picked, owner = round_robin(corners, order, keep)
    chosen = set(picked)

    # 비교용: 지금 방식(앞에서부터 N개 = idx 오름차순)이면 어떻게 되나
    naive = set(sorted(cand)[:keep])

    cov_new = coverage(order, chosen)
    cov_old = coverage(order, naive)

    print("")
    print("  picked %d path(s).  per-corner coverage (its own slack ranking):" % len(picked))
    print("")
    print("  %-22s %6s %10s   %s"
          % ("corner", "picks", "deepest", "  ".join("top%-4d" % d for d in DEPTHS)))
    print("  " + "-" * 74)
    for c in corners:
        deep, got = cov_new[c]
        mine = sum(1 for i in picked if owner[i] == c)
        print("  %-22s %6d %10d   %s"
              % (c[:22], mine, deep,
                 "  ".join("%-7d" % got[d] for d in DEPTHS)))
    print("")
    print("  same table for the plain '7_cut.py --keep %d' (first idx, no balancing):"
          % keep)
    print("  " + "-" * 74)
    for c in corners:
        deep, got = cov_old[c]
        print("  %-22s %6s %10d   %s"
              % (c[:22], "-", deep,
                 "  ".join("%-7d" % got[d] for d in DEPTHS)))
    print("")
    print("  'deepest'  = lowest rank that made it in, by that corner's own slack.")
    print("  'topK'     = how many of that corner's own worst K paths are in the list.")

    # ---- 목록 쓰기 -------------------------------------------------------
    # idx 오름차순으로 쓴다. 7_cut.py 는 집합으로 읽고 파일에 나온 순서를 지키므로
    # 목록의 순서 자체는 결과에 영향을 주지 않는다. 사람이 보기 좋으라고 정렬한다.
    with wopen(out_path) as fh:
        fh.write("# 7a_select.py  --root %s  --keep %d\n"
                 % (os.path.abspath(args.root), args.keep))
        fh.write("# picked %d of %d shared candidates, round-robin over %d corners\n"
                 % (len(picked), len(cand), len(corners)))
        fh.write("# corners: %s\n" % ", ".join(corners))
        fh.write("# use:  python3 7_cut.py --root <round2> --idx-file %s\n"
                 % os.path.basename(out_path))
        for i in sorted(picked):
            fh.write("%d\n" % i)

    print("")
    print("-" * 68)
    print("  picked        : %d of %d candidate(s)" % (len(picked), len(cand)))
    print("  list          : %s" % out_path)
    print("  total time    : %s" % fmt_dur(time.time() - t_start))
    shown = os.path.relpath(out_path)
    if shown.startswith(".."):
        shown = out_path
    print("")
    print("  next :  python3 7_cut.py --root %s --idx-file %s"
          % (os.path.relpath(args.root), shown))

    issues = []
    if len(picked) < args.keep:
        issues.append(("W-FEWER",
                       ["  [ CHECK ] asked %d, picked %d -- the pool shared by "
                        "all corners holds only %d." % (args.keep, len(picked),
                                                        len(cand))]))
    if heavy_drop:
        issues.append(("W-DROPPED",
                       ["  [ CHECK ] paths not measured in every corner:"]
                       + ["    %s" % s for s in heavy_drop[:12]]))
    if not issues:
        # code() 는 OK- 면 끝내지 않고 돌아온다. 여기서 직접 끝낸다
        # (안 그러면 아래 issues[0] 에서 죽는다).
        code("OK-SELECT")
        return
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
