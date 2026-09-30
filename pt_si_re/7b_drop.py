#!/usr/bin/env python3
# -*- coding: euc-kr -*-
"""7b - 모아 둔 결과(6_collect.py 산출물)에서 **어떤 이름이 들어간 경로**를 뺀다.

    # 1) 먼저 세기만 한다. 아무 파일도 안 만든다.
    python3 7b_drop.py --root deliver --mode setup --pattern u_mem

    # 2) 뺀 사본을 만든다. 원본은 안 건드린다.
    python3 7b_drop.py --root deliver --mode setup --pattern u_mem --out deliver_nomem

읽는 것 (6_collect.py 가 만든 모양 그대로)
    <root>/<mode>/report.<코너>_fixed_annotated.rpt
    <root>/<mode>/xtalk/xt.<코너>.path_context_si_compact.by_path.rpt

만드는 것 (--out 을 줬을 때만)
    <out>/<mode>/report.<코너>_fixed_annotated.rpt                    같은 이름
    <out>/<mode>/xtalk/xt.<코너>.path_context_si_compact.by_path.rpt  같은 이름
    <out>/dropped_<mode>.idx                                          뺀 idx 목록

    모양이 입력과 같으므로 모델 쪽에서는 읽는 위치만 <out> 으로 바꾸면 된다.

어떤 경로를 빼는가
    **annotation 파일만 보고 정한다.** crosstalk 파일로는 정하지 않는다.
    crosstalk 에는 aggressor_net / aggressor_driver_pin 열이 있어서, u_mem 을
    지나지 않는 경로에도 u_mem 쪽 넷이 aggressor 로 적힐 수 있다. 그걸로 정하면
    상관없는 경로까지 빠진다. 남는 경로의 그런 aggressor 줄은 실제 커플링이라
    그대로 둔다(세기 결과의 xt-only 열이 그 경로 수다).

    --by path   (기본) 경로 블록 안 **어디든** 나오면 뺀다. Startpoint/Endpoint,
                클럭 트리, 데이터 경로의 핀/넷 이름 전부.
    --by ends   Startpoint: / Endpoint: 줄에 나올 때만 뺀다.

    세기 결과에는 둘 다 찍힌다. 세어 보고 고르면 된다.

    마커 줄(### FIXED_PATH ... key=...)은 보지 않는다. key 는 '/' 를 '_' 로
    바꾼 이름이라, u_mem/ 은 안 걸리고 u_mem_ 은 엉뚱한 데 걸린다.

    --pattern 은 그냥 글자열이다(정규식 아님, 대소문자 구분). 여러 번 주면
    하나라도 걸리면 뺀다. u_mem 은 u_mem_ctrl 에도 걸린다. 실제로 무엇에
    걸렸는지는 세기 결과의 matched names 표에 나온다. 원치 않는 이름이 섞였으면
    --pattern u_mem/ 처럼 좁힌다.

코너끼리 같은 경로가 빠지게
    같은 idx 는 모든 코너에서 같은 경로다(fixed_paths.tcl). 그래서 **한 코너라도
    걸린 idx 는 모든 코너에서 뺀다**(합집합). 원래는 코너마다 같은 목록이
    나와야 한다. 다르면 대개 PT 가 어느 코너에서 그 경로를 못 잡은 경우다.
    그 블록은 마커만 있고 타이밍 표가 없어서 글자가 안 보인다(empty 열).
    다르면 W-DROPDIFF 로 알린다.

    annotation 과 crosstalk 에 **같은 idx 목록**을 적용하므로 두 파일의 짝도
    그대로 유지된다.

파일은 바이트 그대로 옮긴다
    남기는 블록은 한 글자도 바꾸지 않는다(바이너리로 읽고 쓴다). 첫 블록 앞의
    머리말도 그대로 옮긴다. 줄 단위로 흘려 읽으므로 파일이 몇 GB 든 메모리는
    거의 안 쓴다. 쓰기는 <이름>.part 에 쓰고 다 끝난 뒤 이름을 바꾼다.
    중간에 끊기면 .part 만 남는다.

옵션
    --root <폴더>     6_collect.py 에 --out 으로 줬던 폴더 (그 아래 <mode>/ 가 있다)
    --mode setup|hold (기본 setup)
    --pattern <글자>  뺄 이름. 여러 번 줄 수 있다
    --by path|ends    판정 범위 (기본 path)
    --out <폴더>      주면 뺀 사본을 만든다. 안 주면 세기만 한다
    --force           --out 에 이미 결과가 있어도 덮어쓴다
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()

MARK = b"### FIXED_PATH"
IDXTAG = b"idx="
# 블록에 진짜 타이밍 표가 들었는지 보는 표시 (7_cut.py 와 같다)
MEASURED = b"Startpoint:"
ENDS = (b"Startpoint:", b"Endpoint:")

# 6_collect.py 가 붙이는 이름
ANNOT_PRE, ANNOT_SUF = "report.", "_fixed_annotated.rpt"
XTALK_PRE, XTALK_SUF = "xt.", ".path_context_si_compact.by_path.rpt"

# 이름 표에서 이름이 끝나는 글자
NAME_STOP = b"/ \t\r\n()"

CODE_INFO = {
    "E-ARGS":     ("--pattern is empty",
                   "give the name to drop, e.g. --pattern u_mem"),
    "E-NOROOT":   ("<root>/<mode> does not exist",
                   "give the folder you passed to 6_collect.py --out "
                   "(the one ABOVE setup/ or hold/), and the right --mode."),
    "E-NOTHING":  ("no report.*_fixed_annotated.rpt in <root>/<mode>",
                   "run 6_collect.py first, or check --root / --mode."),
    "E-NOMARK":   ("an annotation file has no '### FIXED_PATH' block",
                   "this tool drops whole path blocks, so the file must come "
                   "from fixed_paths.tcl. Check the file named above."),
    "E-SAMEDIR":  ("--out points at the input",
                   "this tool never edits its input. Give another --out folder."),
    "E-EXISTS":   ("the output already exists",
                   "give --force to overwrite, or pick another --out."),
    "W-NOMATCH":  ("the pattern matched no path",
                   "nothing to drop, so nothing was written. Check the spelling "
                   "(case matters) and --by."),
    "W-DROPDIFF": ("corners did not match the same paths",
                   "usually a block PT left empty in one corner (see the 'empty' "
                   "column). The union is dropped in every corner, so the "
                   "corners stay paired."),
    "W-NOIDX":    ("a matching block has no readable idx",
                   "without idx it cannot be paired across corners, so it was "
                   "KEPT. Check the file named above."),
    "W-PAIRDIFF": ("the INPUT annotation and crosstalk hold different idx sets",
                   "the corner was already unpaired before this tool ran. "
                   "Check it with 4_check_results.py / 6_collect.py."),
    "W-NOFINAL":  ("a corner has only one of the two files",
                   "only the file that exists is handled. Re-run 6_collect.py "
                   "once that corner is complete."),
    "W-IDXDIFF":  ("output files do not hold the same idx set",
                   "corners (or annotation vs crosstalk) are no longer paired. "
                   "Compare the result table before using the data."),
    "W-LEFT":     ("a kept annotation block still contains the pattern",
                   "only a block without idx can do that (see W-NOIDX). "
                   "Check the file named above."),
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


def show(b):
    return b.decode("utf-8", "backslashreplace")


def idx_of(line):
    """b'### FIXED_PATH idx=12 key=...' -> 12. 못 읽으면 None."""
    p = line.find(IDXTAG)
    if p < 0:
        return None
    n = 0
    got = False
    for ch in bytearray(line[p + len(IDXTAG):]):
        if 48 <= ch <= 57:
            n = n * 10 + (ch - 48)
            got = True
        else:
            break
    return n if got else None


def names_in(line, pat):
    """줄에서 pat 이 든 이름 조각. 'a/u_mem/b/Q' 에서 u_mem -> 'u_mem'.

    계층 구분자 '/' 사이 한 칸을 잘라 낸다. u_mem_ctrl 처럼 다른 이름에
    걸렸는지 보려는 것이라 이 정도면 충분하다.
    """
    out = set()
    start = 0
    n = len(line)
    while True:
        k = line.find(pat, start)
        if k < 0:
            return out
        a = max(line.rfind(b"/", 0, k), line.rfind(b" ", 0, k),
                line.rfind(b"\t", 0, k)) + 1
        j = k + len(pat)
        while j < n and line[j:j + 1] not in (b"/", b" ", b"\t", b"\r", b"\n",
                                               b"(", b")"):
            j += 1
        out.add(line[a:j])
        start = k + len(pat)


def scan_annot(path, pats):
    """annotation 파일 하나를 센다. 아무것도 안 쓴다.

    돌려주는 것 (dict)
        total     블록 수
        idxs      블록 idx 집합 (못 읽은 것 제외)
        empty     타이밍 표가 없는 블록 수 (Startpoint: 줄이 없음)
        hit_path  어디든 걸린 idx 집합
        hit_ends  Startpoint:/Endpoint: 줄에 걸린 idx 집합
        noidx_hit 걸렸는데 idx 를 못 읽은 블록 수 (path 기준, ends 기준)
        names     {이름 조각: 걸린 idx 집합}
    """
    total = empty = 0
    idxs = set()
    hit_path, hit_ends = set(), set()
    noidx_hit = [0, 0]
    names = {}
    cur = None
    in_block = False
    has_sp = False
    got_path = got_ends = False

    def close():
        if not in_block:
            return 0
        if cur is None:
            if got_path:
                noidx_hit[0] += 1
            if got_ends:
                noidx_hit[1] += 1
        return 0 if has_sp else 1

    with open(path, "rb") as fh:
        for line in fh:
            if line.startswith(MARK):
                empty += close()
                total += 1
                cur = idx_of(line)
                if cur is not None:
                    idxs.add(cur)
                in_block = True
                has_sp = got_path = got_ends = False
                continue
            if not in_block:
                continue                       # 첫 블록 앞 머리말
            if not has_sp and MEASURED in line:
                has_sp = True
            for p in pats:
                if p in line:
                    got_path = True
                    if cur is not None:
                        hit_path.add(cur)
                        for nm in names_in(line, p):
                            names.setdefault(nm, set()).add(cur)
                    if line.lstrip().startswith(ENDS):
                        got_ends = True
                        if cur is not None:
                            hit_ends.add(cur)
        empty += close()
    return {"total": total, "idxs": idxs, "empty": empty,
            "hit_path": hit_path, "hit_ends": hit_ends,
            "noidx_hit": noidx_hit, "names": names}


def scan_xtalk(path, pats):
    """crosstalk 파일 하나를 센다. (블록 수, idx 집합, 글자가 나온 idx 집합)"""
    total = 0
    idxs, hits = set(), set()
    cur = None
    with open(path, "rb") as fh:
        for line in fh:
            if line.startswith(MARK):
                total += 1
                cur = idx_of(line)
                if cur is not None:
                    idxs.add(cur)
                continue
            if cur is not None:
                for p in pats:
                    if p in line:
                        hits.add(cur)
                        break
    return total, idxs, hits


def cut(src, dst, drop, pats=None, ends_only=False):
    """drop 에 든 idx 블록을 빼고 나머지를 바이트 그대로 dst 에 쓴다.

    pats 를 주면(annotation) 남긴 블록에 패턴이 남았는지도 센다 -- 따로 한 번
    더 확인하는 것이다. 합집합으로 뺐으니 idx 가 있는 블록에는 남을 수 없다.

    돌려주는 것: (남긴 수, 원래 수, 남긴 idx 집합, 패턴이 남은 블록 수)
    """
    total = kept = left = 0
    kept_idx = set()
    writing = True           # 첫 블록 앞 머리말은 그대로 옮긴다
    this_left = False
    tmp = dst + ".part"
    ok = False
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            for line in fi:
                if line.startswith(MARK):
                    if writing and this_left:
                        left += 1
                    this_left = False
                    total += 1
                    i = idx_of(line)
                    writing = i not in drop    # idx 가 없으면(None) 남긴다
                    if writing:
                        kept += 1
                        if i is not None:
                            kept_idx.add(i)
                elif writing and pats and total and not this_left:
                    if ends_only and not line.lstrip().startswith(ENDS):
                        pass
                    else:
                        for p in pats:
                            if p in line:
                                this_left = True
                                break
                if writing:
                    fo.write(line)
            if writing and this_left:
                left += 1
        ok = True
    finally:
        if ok:
            os.rename(tmp, dst)
        else:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return kept, total, kept_idx, left


def list_corners(mdir):
    """{코너: (annotation 경로 또는 None, crosstalk 경로 또는 None)}"""
    found = {}
    for n in sorted(os.listdir(mdir)):
        p = os.path.join(mdir, n)
        if (os.path.isfile(p) and n.startswith(ANNOT_PRE) and n.endswith(ANNOT_SUF)
                and len(n) > len(ANNOT_PRE) + len(ANNOT_SUF)):
            c = n[len(ANNOT_PRE):-len(ANNOT_SUF)]
            found.setdefault(c, [None, None])[0] = p
    xdir = os.path.join(mdir, "xtalk")
    if os.path.isdir(xdir):
        for n in sorted(os.listdir(xdir)):
            p = os.path.join(xdir, n)
            if (os.path.isfile(p) and n.startswith(XTALK_PRE) and n.endswith(XTALK_SUF)
                    and len(n) > len(XTALK_PRE) + len(XTALK_SUF)):
                c = n[len(XTALK_PRE):-len(XTALK_SUF)]
                found.setdefault(c, [None, None])[1] = p
    return dict((c, tuple(v)) for c, v in found.items())


def fmt_dur(sec):
    sec = int(sec + 0.5)
    if sec < 60:
        return "%ds" % sec
    return "%dm%02ds" % (sec // 60, sec % 60)


def rng(idxs):
    if not idxs:
        return "-"
    return "%d..%d" % (min(idxs), max(idxs))


def main():
    ap = argparse.ArgumentParser(
        description="Drop the paths whose annotation mentions a name, from the "
                    "files 6_collect.py gathered. Counts only, unless --out is given.")
    ap.add_argument("--root", required=True,
                    help="the folder given to 6_collect.py --out (holds <mode>/)")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"])
    ap.add_argument("--pattern", action="append", default=[], metavar="TEXT",
                    help="name to drop (plain text, case-sensitive). Repeatable")
    ap.add_argument("--by", default="path", choices=["path", "ends"],
                    help="path = anywhere in the path block (default), "
                         "ends = Startpoint:/Endpoint: lines only")
    ap.add_argument("--out", help="write the copy without those paths here. "
                                  "Without it, nothing is written")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing output")
    args = ap.parse_args()
    t_start = time.time()

    pats = [p.encode("utf-8") for p in args.pattern if p]
    print("=" * 68)
    print("7b - drop paths by name  (%s)" % args.mode)
    print("=" * 68)
    if not pats:
        code("E-ARGS", "  [ FAILED ] no --pattern given.")

    mdir = os.path.join(args.root, args.mode)
    if not os.path.isdir(mdir):
        code("E-NOROOT", "  [ FAILED ] not a folder: %s" % os.path.abspath(mdir))
    corners = list_corners(mdir)
    if not any(a for a, _ in corners.values()):
        code("E-NOTHING", "  [ FAILED ] nothing matching %s*%s in %s"
             % (ANNOT_PRE, ANNOT_SUF, os.path.abspath(mdir)))

    out_mdir = None
    if args.out:
        out_mdir = os.path.join(args.out, args.mode)
        if os.path.realpath(out_mdir) == os.path.realpath(mdir):
            code("E-SAMEDIR", "  [ FAILED ] --out resolves to the input: %s"
                 % os.path.abspath(out_mdir))
        if not args.force:
            exists = []
            for c, (a, x) in sorted(corners.items()):
                for src, sub in ((a, ""), (x, "xtalk")):
                    if src:
                        dst = os.path.join(out_mdir, sub, os.path.basename(src))
                        if os.path.exists(dst):
                            exists.append(dst)
            if exists:
                code("E-EXISTS", "  [ FAILED ] %d output file(s) already exist, e.g. %s"
                     % (len(exists), exists[0]))

    print("  input   : %s" % os.path.abspath(mdir))
    print("  pattern : %s   (plain text, case-sensitive)"
          % ", ".join(show(p) for p in pats))
    print("  drop by : %s" % ("anywhere in the path block" if args.by == "path"
                              else "Startpoint:/Endpoint: lines only"))
    print("  output  : %s" % (os.path.abspath(out_mdir) if out_mdir
                              else "(none -- counting only)"))
    print("  corners : %d" % len(corners))
    print("")

    # ---- 1. 센다 ----------------------------------------------------------
    print("  -- 1/2  counting (reads every file once, writes nothing) ----------")
    scans = {}
    for c, (a, x) in sorted(corners.items()):
        t0 = time.time()
        s = scan_annot(a, pats) if a else None
        xs = scan_xtalk(x, pats) if x else None
        scans[c] = (s, xs)
        if s is not None and s["total"] == 0:
            code("E-NOMARK", "  [ FAILED ] no '### FIXED_PATH' in %s" % a)
        print("    %-30s %s  (%s)" % (c[:30], "counted" if s else "no annotation",
                                      fmt_dur(time.time() - t0)))
        sys.stdout.flush()

    union_path, union_ends = set(), set()
    for s, _ in scans.values():
        if s:
            union_path |= s["hit_path"]
            union_ends |= s["hit_ends"]
    drop = union_path if args.by == "path" else union_ends

    print("")
    print("  %-30s %6s %6s %6s %9s %9s %8s"
          % ("corner", "paths", "xtalk", "empty", "anywhere", "start/end", "xt-only"))
    print("  " + "-" * 80)
    for c, (s, xs) in sorted(scans.items()):
        xt = "%6d" % xs[0] if xs else "%6s" % "-"
        xonly = "%8d" % len(xs[2] - drop) if xs else "%8s" % "-"
        if s:
            print("  %-30s %6d %s %6d %9d %9d %s"
                  % (c[:30], s["total"], xt, s["empty"], len(s["hit_path"]),
                     len(s["hit_ends"]), xonly))
        else:
            print("  %-30s %6s %s %6s %9s %9s %s"
                  % (c[:30], "-", xt, "-", "-", "-", xonly))
    print("  " + "-" * 80)
    print("  %-30s %6s %6s %6s %9d %9d"
          % ("union over corners", "", "", "", len(union_path), len(union_ends)))
    print("")
    print("    paths     : path blocks in the annotation")
    print("    empty     : blocks PT left without a timing table (text cannot match)")
    print("    anywhere  : paths whose block mentions the pattern anywhere   (--by path)")
    print("    start/end : paths whose Startpoint:/Endpoint: line mentions it (--by ends)")
    print("    xt-only   : paths KEPT whose crosstalk still mentions it (aggressor nets;")
    print("                left as they are)")

    # 이름 표: 어디에 걸렸는지 (u_mem 이 u_mem_ctrl 에도 걸렸는지 보려는 것)
    names = {}
    for s, _ in scans.values():
        if s:
            for nm, ids in s["names"].items():
                names.setdefault(nm, set()).update(ids)
    if names:
        print("")
        print("  matched names (the hierarchy level holding the pattern, all corners)")
        rows = sorted(names.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for nm, ids in rows[:20]:
            print("    %-40s %6d paths" % (show(nm)[:40], len(ids)))
        if len(rows) > 20:
            print("    ... %d more names" % (len(rows) - 20))

    total_paths = max([s["total"] for s, _ in scans.values() if s] or [0])
    print("")
    print("  to drop (--by %s) : %d of %d paths  ->  %d remain"
          % (args.by, len(drop), total_paths, total_paths - len(drop)))
    sys.stdout.flush()

    # 세면서 본 것 중 확인할 것
    issues = []
    diff = []
    for c, (s, _) in sorted(scans.items()):
        if s:
            mine = s["hit_path"] if args.by == "path" else s["hit_ends"]
            if mine != drop:
                diff.append("%s : matched %d, union %d, empty blocks %d"
                            % (c, len(mine), len(drop), s["empty"]))
    if diff:
        issues.append(("W-DROPDIFF",
                       ["  [ CHECK ] corners matched different paths "
                        "(the union is dropped everywhere):"]
                       + ["    %s" % d for d in diff[:12]]))
    noidx = []
    for c, (s, _) in sorted(scans.items()):
        n = s["noidx_hit"][0 if args.by == "path" else 1] if s else 0
        if n:
            noidx.append("%s : %d block(s)" % (c, n))
    if noidx:
        issues.append(("W-NOIDX",
                       ["  [ CHECK ] matching blocks without a readable idx (kept):"]
                       + ["    %s" % d for d in noidx[:12]]))
    pair = []
    for c, (s, xs) in sorted(scans.items()):
        if s and xs and s["idxs"] != xs[1]:
            pair.append("%s : annotation %d idx, crosstalk %d idx, differ in %d"
                        % (c, len(s["idxs"]), len(xs[1]),
                           len(s["idxs"] ^ xs[1])))
    if pair:
        issues.append(("W-PAIRDIFF",
                       ["  [ CHECK ] input annotation/crosstalk not paired:"]
                       + ["    %s" % d for d in pair[:12]]))
    nofinal = ["%s : %s missing" % (c, "crosstalk" if s else "annotation")
               for c, (s, xs) in sorted(scans.items()) if not (s and xs)]
    if nofinal:
        issues.append(("W-NOFINAL",
                       ["  [ CHECK ] corners with only one of the two files:"]
                       + ["    %s" % d for d in nofinal[:12]]))

    if not drop:
        issues.insert(0, ("W-NOMATCH", ["  [ CHECK ] nothing to drop."]))
        finish(issues, "OK-DROPCOUNT")
        return

    if not out_mdir:
        print("")
        print("  nothing was written. To write the copy without these paths:")
        print("    python3 7b_drop.py --root %s --mode %s %s%s --out <folder>"
              % (args.root, args.mode,
                 " ".join("--pattern %s" % show(p) for p in pats),
                 "" if args.by == "path" else " --by ends"))
        finish(issues, "OK-DROPCOUNT")
        return

    # ---- 2. 뺀 사본을 쓴다 -----------------------------------------------
    print("")
    print("  -- 2/2  writing the copy (same names, same layout) ----------------")
    for d in (out_mdir, os.path.join(out_mdir, "xtalk")):
        if not os.path.isdir(d):
            os.makedirs(d)
    results = []
    for c, (a, x) in sorted(corners.items()):
        t0 = time.time()
        ra = rx = None
        if a:
            ra = cut(a, os.path.join(out_mdir, os.path.basename(a)), drop,
                     pats, args.by == "ends")
        if x:
            rx = cut(x, os.path.join(out_mdir, "xtalk", os.path.basename(x)), drop)
        results.append((c, ra, rx))
        print("    %-30s written  (%s)" % (c[:30], fmt_dur(time.time() - t0)))
        sys.stdout.flush()

    idx_fp = os.path.join(args.out, "dropped_%s.idx" % args.mode)
    tmp = idx_fp + ".part"
    with open(tmp, "w") as fh:
        fh.write("# 7b_drop.py  %s\n" % time.strftime("%Y-%m-%d %H:%M"))
        fh.write("# input   : %s\n" % os.path.abspath(mdir))
        fh.write("# pattern : %s\n" % ", ".join(show(p) for p in pats))
        fh.write("# by      : %s\n" % args.by)
        fh.write("# dropped : %d of %d paths\n" % (len(drop), total_paths))
        for i in sorted(drop):
            fh.write("%d\n" % i)
    os.rename(tmp, idx_fp)

    print("")
    print("  result")
    print("  %-30s %15s %15s %12s %5s"
          % ("corner", "annotation", "crosstalk", "idx kept", "left"))
    print("  " + "-" * 82)
    idxsets = {}
    left = []
    for c, ra, rx in results:
        cells = []
        for r, kind in ((ra, "annotation"), (rx, "crosstalk")):
            if r is None:
                cells.append("%15s" % "-")
                continue
            kept, total, kidx, lft = r
            cells.append("%6d -> %6d" % (total, kept))
            idxsets.setdefault(tuple(sorted(kidx)), []).append("%s/%s" % (c, kind))
        lft = ra[3] if ra else 0
        if lft:
            left.append("%s : %d block(s)" % (c, lft))
        kidx = (ra or rx)[2]
        print("  %-30s %s %s %12s %5s"
              % (c[:30], cells[0], cells[1], rng(kidx), lft if ra else "-"))

    if len(idxsets) > 1:
        issues.append(("W-IDXDIFF",
                       ["  [ CHECK ] %d different idx sets among the output files:"
                        % len(idxsets)]
                       + ["    %s ..." % ", ".join(v[:2]) for v in idxsets.values()]))
    if left:
        issues.append(("W-LEFT",
                       ["  [ CHECK ] kept annotation blocks that still hold the pattern:"]
                       + ["    %s" % d for d in left[:12]]))

    print("")
    print("-" * 68)
    print("  dropped idx list : %s" % os.path.abspath(idx_fp))
    print("  output           : %s" % os.path.abspath(out_mdir))
    print("  total time       : %s" % fmt_dur(time.time() - t_start))
    finish(issues, "OK-DROP")


def finish(issues, ok):
    """확인할 것은 **전부** 찍고, 코드는 제일 앞의 것 하나만 낸다."""
    if not issues:
        code(ok)
        return
    for c, lines in issues:
        print("")
        for ln in lines:
            print(ln)
        if c != issues[0][0]:
            what, _ = CODE_INFO.get(c, ("", ""))
            print("    (%s -- %s)" % (c, what))
    code(issues[0][0])


if __name__ == "__main__":
    main()
