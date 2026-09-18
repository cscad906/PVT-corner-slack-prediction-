#!/usr/bin/env python3
# -*- coding: euc-kr -*-
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
    --design <회로>   그 회로의 hidden 코너를 config.yaml 에서 읽어 자동으로 뺀다.
                      --skip-corner 를 손으로 나열하는 것과 같은데, 빠뜨릴 수가 없다.
    --config <파일>   config.yaml 위치. 생략하면 si_corner_model_re/config.yaml.

hidden 코너를 자동으로 빼기
    python3 7a_select.py --root round2 --keep 3000 --design MIF_Timing_Report

    hidden 이 무엇인지는 **모델 쪽 코드에게 물어본다**(si_model.run.grid_split).
    여기서 규칙을 다시 구현하면 언젠가 모델과 답이 갈리고, 그러면 모델이 숨긴
    코너가 경로 선택에 참여하게 된다 -- holdout 이 막으려던 바로 그것이다.

    회로마다 전압 그리드도 hidden 도 다르므로 --design 은 반드시 정확해야 한다.
    한 회로의 **모든 온도**의 hidden 을 합쳐서 뺀다. 2회차 폴더에 125 와 m25 가
    섞여 있어도 되고, 그래야 목록 하나로 전 코너를 자를 수 있다.

    코너 폴더 이름은 전압/레벨/온도를 각각 따로 찾아 맞춘다(순서·구분자·대소문자
    무관). 못 읽는 폴더가 있으면 멈춘다 -- hidden 인지 아닌지 모르는 채로 뽑으면
    안 되기 때문이다.
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

# 코너 폴더 이름에서 전압/온도를 찾는 규칙. si_corner_model 의
# parsing/discovery.py 와 같은 것을 쓴다 -- 거기서 리포트 파일 이름을 읽는 방식과
# 여기서 폴더 이름을 읽는 방식이 달라지면 같은 코너를 다르게 부르게 된다.
# 전압: 0p5000 / 0.54 / v0p55 / 0p55v  (소수점 표시가 반드시 있어야 하므로 125 는
#       절대 전압으로 안 읽힌다).  온도: 125 / 125c / m25 / -25 / n40
_V_TOK_RE = re.compile(r"(?<!\d)v?(\d+)[p.](\d+)v?(?!\d)", re.IGNORECASE)
_T_TOK_RE = re.compile(r"(?<![\dA-Za-z])([mn]|-)?(\d+)c?(?![\dA-Za-z])", re.IGNORECASE)

# --design 이 쓰는 hidden 코너 표. si_corner_model_re/config.yaml 에서 베껴 왔다.
#   (회로, 온도토큰, 전압, 레벨).  2026-09-18 기준.
# 여기 적어 두면 pyyaml 없이도 돌아간다. 대신 config 가 바뀌면 이 표가 낡는데,
# 낡은 채로 돌면 새로 hidden 이 된 코너가 조용히 경로 선택에 참여한다. 그래서
# pyyaml 을 쓸 수 있을 때는 아래 표를 config 와 대조하고, 다르면 멈춘다.
HIDDEN = {
    "MIF_Timing_Report": [
        ("125", 0.54, "cmax"), ("125", 0.685, "rcmax"), ("125", 0.76, "cmax"),
        ("m25", 0.475, "rcmin"), ("m25", 0.6, "cmax"),
        ("m25", 0.855, "rcmin"), ("m25", 0.95, "cmax"),
    ],
    "MFC_Timing_Report": [
        ("125", 0.5, "cmax"), ("125", 0.54, "rcmax"),
        ("m25", 0.6, "cmax"), ("m25", 0.685, "rcmax"), ("m25", 0.76, "rcmin"),
    ],
    # 전역 temps 를 그대로 쓰는 회로
    "PERIC0_Timing_Report": [
        ("125", 0.54, "rcmax"), ("125", 0.6, "cmax"),
        ("m25", 0.5, "cmax"), ("m25", 0.685, "rcmin"),
    ],
}
# 폴더 이름에서 찾을 레벨 이름. 긴 것부터 봐야 rcmax 안의 cmax 를 잘못 안 잡는다.
LEVEL_NAMES = ("rcmax", "rcmin", "cmax")

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
    "E-SKIPNAME": ("--skip-corner named a corner that is not there",
                   "the name must match the corner folder exactly. a typo would "
                   "silently let that corner pick paths, which is the one thing "
                   "--skip-corner is for. check the spelling against the folder "
                   "names printed above."),
    "E-YAML":    ("config.yaml needs PyYAML, which this python cannot import",
                  "run with a python that has pyyaml, or drop --design and list "
                  "the hidden corners with --skip-corner instead."),
    "E-CONFIG":  ("config.yaml could not be read or expanded",
                  "the message above comes from si_model. fix the config, or "
                  "drop --design and use --skip-corner."),
    "E-DESIGN":  ("--design is not a design this script knows",
                  "use one of the names printed above. the name decides which "
                  "hidden corners apply, so it has to be exact."),
    "E-HIDDENDRIFT": ("config.yaml holds a different holdout than this script",
                      "config.yaml is what the model actually holds out, so the "
                      "table in 7a_select.py (HIDDEN) is stale. copy the corners "
                      "printed above into it, then run again. picking with a "
                      "stale table would let a held-out corner choose paths."),
    "E-CORNERNAME": ("a corner folder name cannot be read as voltage+level",
                     "--design has to tell hidden from seen by the folder name. "
                     "rename the folder so the voltage (0p54 / 0.54) and the "
                     "level (cmax / rcmax / rcmin) are both in it, or drop "
                     "--design and use --skip-corner."),
    "E-DUPCORNER": ("two corner folders read as the same corner",
                    "one of them would be picked and the other skipped by luck. "
                    "rename so each corner appears once."),
    "W-NOHIDDEN": ("a hidden corner has no folder under --root",
                   "nothing was picked from it, so the holdout still holds. it "
                   "just means that corner was never measured here."),
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


def parse_corner_name(name, levels):
    """폴더 이름 -> (전압, 레벨, 온도토큰). 못 읽으면 (None, ...) 로 돌려준다.

    순서대로 **잘라내며** 찾는다(discovery.py 와 같은 방식). 레벨을 먼저 떼야
    'rcmax' 안의 'cmax' 를 잘못 잡지 않고, 전압을 떼야 남은 숫자를 온도로 안전하게
    읽을 수 있다.
    """
    rest = name
    level = None
    # 긴 이름부터 -- 'rcmax' 가 'cmax' 보다 먼저 걸려야 한다
    for lv in sorted(levels, key=len, reverse=True):
        m = re.search(r"(?<![A-Za-z])" + re.escape(lv) + r"(?![A-Za-z])",
                      rest, re.IGNORECASE)
        if m:
            level = lv
            rest = rest[:m.start()] + "|" + rest[m.end():]
            break
    volt = None
    m = _V_TOK_RE.search(rest)
    if m:
        volt = float("%s.%s" % (m.group(1), m.group(2)))
        rest = rest[:m.start()] + "|" + rest[m.end():]
    temp = None
    m = _T_TOK_RE.search(rest)
    if m:
        temp = ("m" if m.group(1) else "") + m.group(2)
    return volt, level, temp


def hidden_from_config(cfg_path, design):
    """config.yaml -> ({(온도토큰, 전압, 레벨)}, 레벨이름들, 회로목록, 사유).

    위 HIDDEN 표가 아직 맞는지 **대조**하는 데만 쓴다. 판정 자체는 모델 쪽
    si_model.run.grid_split 이 한 것을 그대로 가져온다 -- 규칙을 여기서 다시
    쓰면 모델과 답이 갈린다.

    pyyaml 이 없거나 config 를 못 읽으면 (None, None, None, 사유) 를 돌려준다.
    그때는 대조를 건너뛰고 표를 그대로 쓴다(멈추지 않는다).
    """
    pkg = os.path.dirname(os.path.abspath(cfg_path))
    if not os.path.isdir(os.path.join(pkg, "si_model")):
        return None, None, None, "no si_model package next to %s" % cfg_path
    sys.path.insert(0, pkg)
    try:
        from si_model.run import load_project, expand, grid_split
        from si_model.parsing.keys import corner_label
    except ImportError as e:                         # noqa: BLE001
        return None, None, None, str(e)
    try:
        proj = load_project(cfg_path)
        models = expand(proj)
    except Exception as e:                           # noqa: BLE001
        return None, None, None, "%s: %s" % (type(e).__name__, e)

    designs = sorted({m["design"] for m in models})
    mine = [m for m in models if m["design"] == design]
    if not mine:
        return None, None, designs, None
    hidden, levels, labels = set(), set(), []
    for m in mine:
        seen, hid = grid_split(proj, m)
        token = str(m["cfg"]["data"]["temp"])
        proc = m["cfg"]["data"]["corner_prefix"]
        levels.update(m["cfg"]["data"]["rc_corners"])
        for v, lv in hid:
            hidden.add((token, float(v), str(lv)))
            labels.append("%s @%s" % (corner_label(v, lv, proc), token))
    return hidden, sorted(levels), designs, labels


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
    ap.add_argument("--design", metavar="NAME",
                    help="이 회로의 hidden 코너를 config.yaml 에서 읽어 자동으로 뺀다")
    ap.add_argument("--config", metavar="FILE",
                    help="config.yaml 위치 (기본: si_corner_model_re/config.yaml)")
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

    # ---- --design : hidden 코너를 config 에서 알아낸다 --------------------
    skip = set(args.skip_corner)
    auto_skip = []
    if args.design:
        if args.design not in HIDDEN:
            code("E-DESIGN", "[ FAILED ] no design %r." % args.design,
                 "           known: %s" % ", ".join(sorted(HIDDEN)))
        hidden = set(HIDDEN[args.design])
        levels = LEVEL_NAMES
        print("  design : %s   (%d hidden corner(s), they will not pick)"
              % (args.design, len(hidden)))
        for t, v, lv in sorted(hidden, key=lambda x: (x[0], x[1], x[2])):
            print("             %gV %-5s @%s" % (v, lv, t))

        # config 와 대조한다. 표가 낡으면 새로 hidden 이 된 코너가 조용히 뽑기에
        # 참여하므로, 다르면 멈춘다. pyyaml 이 없으면 대조만 건너뛴다.
        cfg_path = args.config or os.path.join(HERE, "si_corner_model_re",
                                               "config.yaml")
        from_cfg, _lv, designs, why = hidden_from_config(cfg_path, args.design)
        if from_cfg is None:
            print("  config : NOT checked -- %s" % (why or "design not in config"))
            print("           (the table above is used as is. if config.yaml "
                  "changed, re-check it.)")
        elif from_cfg != hidden:
            only_cfg = sorted(from_cfg - hidden)
            only_tbl = sorted(hidden - from_cfg)
            code("E-HIDDENDRIFT",
                 "[ FAILED ] the table in 7a_select.py no longer matches %s"
                 % cfg_path,
                 *(["           only in config : %s" % ", ".join(
                        "%gV %s @%s" % (v, lv, t) for t, v, lv in only_cfg)]
                   if only_cfg else [])
                 + (["           only in table  : %s" % ", ".join(
                        "%gV %s @%s" % (v, lv, t) for t, v, lv in only_tbl)]
                    if only_tbl else []))
        else:
            print("  config : checked, matches %s" % cfg_path)

        # 폴더 이름을 코너로 읽어 hidden 과 맞춘다. 못 읽는 폴더가 있으면 멈춘다 --
        # hidden 인지 모르는 채로 그 코너에 경로를 고르게 할 수는 없다.
        bad, byc = [], {}
        for name, _ in corner_dirs(args.root):
            v, lv, t = parse_corner_name(name, levels)
            if v is None or lv is None:
                bad.append(name)
                continue
            byc.setdefault((t, v, lv), []).append(name)
        if bad:
            code("E-CORNERNAME",
                 "[ FAILED ] cannot read %d corner folder name(s):" % len(bad),
                 *["           %s" % b for b in bad[:12]])
        dup = ["%s = %s" % (k, ", ".join(v)) for k, v in byc.items() if len(v) > 1]
        if dup:
            code("E-DUPCORNER",
                 "[ FAILED ] two folders read as the same corner:",
                 *["           %s" % d for d in dup[:12]])
        nofolder = []
        for key in sorted(hidden):
            hit = byc.get(key)
            if hit:
                auto_skip.extend(hit)
            else:
                nofolder.append("%sV %s @%s" % (key[1], key[2], key[0]))
        skip |= set(auto_skip)
        print("  matched: %d hidden corner(s) to a folder, %d with no folder"
              % (len(auto_skip), len(nofolder)))
        if nofolder:
            print("           (not measured here: %s)" % ", ".join(nofolder[:8]))
        print("")

    # ---- 읽을 파일 모으기 ------------------------------------------------
    jobs, missing, skipped = [], [], []
    for name, d in corner_dirs(args.root):
        f = annot_in(d)
        if f is None:
            missing.append(name)
            continue
        # 뺀 코너는 **열지도 않는다.** 그 코너를 모른다는 전제로 고르는 것이라,
        # 후보 교집합에 넣는 것조차 그 코너를 본 셈이 된다.
        if name in skip:
            skipped.append(name)
            continue
        jobs.append((name, f))
    if not jobs:
        code("E-NOTHING", "[ FAILED ] nothing to read under %s" % args.root)
    # 오타로 안 빠진 코너는 그대로 뽑기에 참여한다 -- 조용히 넘어가면 안 된다.
    # --design 으로 붙은 이름은 폴더에서 가져온 것이라 늘 맞는다. 손으로 준 것만 본다.
    unknown = sorted(set(args.skip_corner) - set(skipped))
    if unknown:
        have = [n for n, _ in corner_dirs(args.root)]
        code("E-SKIPNAME",
             "[ FAILED ] --skip-corner does not match any corner folder:",
             "           %s" % ", ".join(unknown),
             "",
             "           corner folders under %s :" % os.path.abspath(args.root),
             "           %s" % ", ".join(have))

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
        print("  skipped: %s" % ", ".join(skipped))
        print("           (--skip-corner: not read at all -- not even to check "
              "that a path exists there)")
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
    # 예전 방식에는 '누가 뽑았나' 가 없지만, 경로마다 **제일 나쁜 코너**는 있다.
    # 1_union 의 idx 순서가 그 worst slack 순서라, 이 개수가 곧 그 코너가 앞자리를
    # 얼마나 차지했는지다. 한 코너가 대부분을 먹고 있으면 그게 편향이다.
    worst_of = {}
    for i in naive:
        worst_of[i] = min(corners, key=lambda c, i=i: slack_of[c][i])

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
        n_worst = sum(1 for i in naive if worst_of[i] == c)
        print("  %-22s %6d %10d   %s"
              % (c[:22], n_worst, deep,
                 "  ".join("%-7d" % got[d] for d in DEPTHS)))
    print("")
    print("  'picks'    = paths the corner brought in. round-robin above; below, "
          "paths whose")
    print("               worst corner it is -- which is what the plain cut "
          "sorts by.")
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
        if skipped:
            fh.write("# not read (--skip-corner): %s\n" % ", ".join(skipped))
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
