#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2b (표 방식) - Dist / Res 를 받은 표에서 읽어 만든다. SPEF 를 안 쓴다.

    python3 2b_distres_table.py --dir <코너폴더>

표는 코너 폴더 안에 둔다. 받은 모양에 따라 둘 중 하나다.

    resdist_map.txt              한 파일로 받았을 때.  net / res / dist
    res_map.txt + dist_map.txt   따로 받았을 때.       각각 net / 값

    따로 받으면 넷 이름으로 합쳐서 쓴다. 한쪽에만 있는 넷은 그쪽 값만 채우고
    나머지는 N/A 로 둔다 -- 조용히 0 을 넣지 않는다.
    합본이 있으면 합본을 먼저 쓴다. 2a 의 cpin_map.txt 와 같은
규약이다. Res 는 온도에 따라 다르므로, 코너마다 그 코너 온도의 표를 둔다.
(--table 로 다른 경로를 줄 수도 있으나 보통 쓸 일이 없다)

2b_distres.py / 2b_distres2.py 를 대체한다. 셋 다 출력이 같은
`distres.tsv (line_no / net / dist / res)` 라서 다음 단계 2c_merge.py 는
어느 것으로 만들었든 그대로 받는다.

언제 쓰나
    SPEF 를 직접 못 뽑는 사이트에서 **상대(기업 등)가 계산해 준 표**를 받아 쓸 때.
    SPEF 가 있으면 2b_distres2.py 쪽이 정확하다(아래 "정확도" 참조).

표 형식
    **헤더 없이 열 3개.  net 이름 / res / dist  이 순서다.**
        n57401      11.1137     7.3315
        clock       51.5246   131.1135

    순서가 곧 의미이므로 res 와 dist 를 바꿔 넣으면 그대로 뒤바뀐 채 들어간다
    (둘 다 숫자라 에러가 안 난다). 파일 이름을 resdist_map.txt 로 둔 것이 그
    순서를 상기시키려는 것이다.

    헤더가 붙어 와도 알아본다(그때는 열 순서가 달라도 이름으로 찾는다).
    구분자는 공백/탭/쉼표/세미콜론/파이프 중에서 알아서 고른다.
    '#' 이나 '//' 로 시작하는 줄과 빈 줄은 건너뛴다.

정확도 -- 열 3개면 절반이 부정확하다
    Dist/Res 는 **드라이버 핀에서 그 리시버 핀까지**의 값인데, 넷 이름만 키로
    쓰면 넷 하나에 값이 하나뿐이다. 리시버가 여럿인 넷은 그 줄들이 전부 같은
    값을 받는다. BoomCoreV3 실측(82,472 (net) 줄)으로:

        열 구성                                        SPEF 계산값과 일치
        net_name res dist                                    69.4%
        net_name driver_pin receiver_pin res dist           100.0%

    그래서 상대에게 **드라이버/리시버 핀 열 2개를 더** 달라고 하는 게 좋다.
    열 이름에 driver/receiver(또는 drv/recv/load/sink)가 들어 있으면 이 스크립트가
    자동으로 핀 쌍 키로 바꿔 쓴다. 핀 표기는 리포트와 같은 `인스턴스/핀` 형식.
    3열로 받아도 돌아가긴 한다 -- 대신 영향 받는 줄 수를 W-NETKEY 로 알려준다.

코너별로 표가 몇 개 필요한가
    Dist 는 배치 좌표라 코너가 바뀌어도 안 변한다. 표 1개면 된다.
    Res 는 온도에 따라 크게 변한다(실측 25C->125C 전 넷 +39%, -40C->125C +86%).
    **온도마다 표가 따로 있어야 한다.** 전압으로는 안 변하니 전압별로는 필요 없다.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8, wopen
force_utf8()
from find_rpt import find_rpt

OBJ_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")

# 받은 표를 코너 폴더에 둘 때 쓰는 이름. 2a 의 cpin_map.txt 와 같은 규약이다.
# 이름 순서가 곧 열 순서다: net / res / dist. 결과 파일 distres.tsv 는 dist 가
# 먼저라 반대인데, 그건 기존 2b 형식이라 못 바꾼다. 그래서 입력 쪽 이름을
# resdist 로 두어 헷갈리지 않게 한다.
# (--table 로 직접 주면 이름은 상관없다)
TABLE_NAME = "resdist_map.txt"

# res 와 dist 를 따로 받았을 때 쓰는 이름. 둘 다 있으면 합쳐서 쓴다.
# 한 파일로 받으면 위 resdist_map.txt 하나만 두면 된다.
RES_NAME = "res_map.txt"
DIST_NAME = "dist_map.txt"

NA = ("", "n/a", "na", "nan", "null", "-", "none")

# 헤더가 있을 때 열을 알아보는 데 쓰는 이름 후보 (소문자 비교)
COL_NET = ("net", "net_name", "netname", "name")
COL_RES = ("res", "resistance", "r", "dr_res", "path_res", "net_res")
COL_DIST = ("dist", "distance", "length", "len", "dr_length", "wl", "wirelength")
COL_DRV = ("driver", "drv", "driver_pin", "drv_pin", "source", "src")
COL_RECV = ("receiver", "recv", "receiver_pin", "recv_pin", "load", "sink", "target")

# 화면 출력은 영어로 둔다 (한글이 깨지는 터미널이 있다).
# 설명이 필요하면 이 파일 맨 위 설명글과 코드표.md 를 본다.
CODE_INFO = {
    "E-NOTABLE":  ("this corner folder has no resdist_map.txt",
                   "every corner folder needs its own. Res differs per "
                   "temperature, so the table does too."),
    "E-TABLE":    ("the supplied table could not be read",
                   "check it has net/res/dist columns, and the header/delimiter."),
    "E-TABLE0":   ("not one net name in the table matches the report",
                   "check the table is for this design, and how net names are written."),
    "W-RES":      ("many rows have no Dist/Res",
                   "run 2c_merge.py -- it splits the cause into A/B/C for you."),
    "W-NETKEY":   ("the table is keyed by net name only, so multi-receiver nets squash",
                   "ask them to add two more columns: driver pin and receiver pin."),
}


def code(c, *msg):
    """무슨 일이 있었는지 설명하고 코드를 찍는다. (2b_distres.py 와 같은 규약)"""
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
    # 읽는다. 안 그러면 코너별 결과표에 "?" 로 남고 문제로 집계된다.
    print("  %-19s [ %s ]" % (kind, c))
    if what:
        print("    what   : %s" % what)
        print("    to do  : %s" % todo)
    print("=" * 66)
    sys.exit(1 if c.startswith("E-") else 0)


def fmt(v, nd=12):
    """2b_distres.py 와 같은 자릿수 규칙. 소수점 6자리 반올림 후 뒤 0 제거."""
    if v is None:
        return ""
    s = "%.*f" % (nd, float(v))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def scan_report(rpt):
    """리포트 -> [(줄번호, 넷, 드라이버핀, 리시버핀)]

    '(net)' 줄 바로 앞 핀이 드라이버, 바로 뒤 핀이 리시버. 2a/2b 와 같은 규칙이다.
    """
    out = []
    prev_pin = None
    pending = None
    with open(rpt, "r", errors="ignore") as f:
        for idx, line in enumerate(f):
            m = OBJ_RE.match(line)
            if not m:
                continue
            name, tag = m.group(1), m.group(2).lower()
            if tag == "net":
                pending = (idx, name, prev_pin)
                continue
            if pending is not None:
                out.append((pending[0], pending[1], pending[2], name))
                pending = None
            prev_pin = name
    return out


# ------------------------------------------------------------------ 이름 변형

def name_variants(name):
    """표와 리포트의 이름 표기가 갈리는 경우를 흡수한다."""
    base = name.strip().lstrip("/")
    out = [base]
    for b in list(out):
        esc = b.replace("\\[", "[").replace("\\]", "]")
        if esc != b:
            out.append(esc)
    for b in list(out):
        flat = re.sub(r"\[(\d+)\]", r"_\1_", b)
        if flat != b:
            out.append(flat)
        unflat = re.sub(r"_(\d+)_", r"[\1]", b)
        if unflat != b:
            out.append(unflat)
    for b in list(out):
        if "/" in b:
            out.append(b.replace("/", "."))
        if "." in b:
            out.append(b.replace(".", "/"))
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen


# ------------------------------------------------------------------ 표 읽기

def sniff(sample):
    for d in (",", "\t", ";", "|"):
        if all(d in ln for ln in sample):
            return d
    return None          # None = 공백으로 나눈다


def find_col(header, cands):
    low = [h.strip().lower().lstrip("#").strip() for h in header]
    for i, h in enumerate(low):
        if h in cands:
            return i
    for i, h in enumerate(low):
        if any(h.startswith(c) or c in h for c in cands):
            return i
    return None


def num(tok, scale):
    t = tok.strip()
    if t.lower() in NA:
        return None
    try:
        return float(t) * scale
    except ValueError:
        return None


def load_value_table(path, kind, scale=1.0):
    """값 한 종류만 든 표를 읽는다. kind 는 "res" 또는 "dist".

    보통 2열(넷 이름, 값)로 온다. 열이 더 있으면 헤더 이름으로 값 열을 찾고,
    헤더가 없으면 두 번째 열을 값으로 본다. driver/receiver 핀 열이 있으면
    핀 쌍 키로 잡는 것은 합본과 같다.

    반환: ({키: 값}, 핀쌍키인가, 통계)
    """
    with open(path, "r", errors="ignore") as f:
        raw = [ln.rstrip("\n\r") for ln in f]
    lines = [ln for ln in raw
             if ln.strip() and not ln.lstrip().startswith(("#", "//"))]
    if not lines:
        return {}, False, {"rows": 0, "bad": 0, "keys": 0,
                           "delim": "?", "header": False, "pair": False}

    delim = sniff(lines[:20])
    if delim:
        split = lambda x: [c.strip() for c in x.split(delim)]
    else:
        split = lambda x: x.split()

    first = split(lines[0])
    numeric = 0
    for tok in first[1:3]:
        try:
            float(tok)
            numeric += 1
        except ValueError:
            pass
    known = set(COL_NET) | set(COL_RES) | set(COL_DIST) | set(COL_DRV) | set(COL_RECV)
    looks_named = any(t.strip().lower().lstrip("#").strip() in known for t in first)
    has_header = numeric < 1 and looks_named

    want = COL_RES if kind == "res" else COL_DIST
    if has_header:
        i_net = find_col(first, COL_NET)
        i_val = find_col(first, want)
        i_drv = find_col(first, COL_DRV)
        i_recv = find_col(first, COL_RECV)
        body = lines[1:]
        if i_net is None:
            i_net = 0
        if i_val is None:
            code("E-TABLE",
                 "[ FAILED ] cannot find the %s column in: %s" % (kind, path),
                 "           header was: %s" % first)
    else:
        i_net, i_drv, i_recv = 0, None, None
        i_val = 1                      # 헤더가 없으면 두 번째 열이 값
        body = lines

    pair = i_drv is not None and i_recv is not None
    need = max(x for x in (i_net, i_val, i_drv, i_recv) if x is not None) + 1

    tab = {}
    bad = 0
    for ln in body:
        c = split(ln)
        if len(c) < need or not c[i_net].strip():
            bad += 1
            continue
        v = num(c[i_val], scale)
        for nv in name_variants(c[i_net]):
            k = (nv, c[i_drv].strip(), c[i_recv].strip()) if pair else nv
            if k not in tab:
                tab[k] = v

    st = {"rows": len(body), "bad": bad, "keys": len(tab),
          "delim": {None: "whitespace", ",": "comma", "\t": "tab",
                    ";": "semicolon", "|": "pipe"}[delim],
          "header": has_header, "pair": pair}
    return tab, pair, st


def merge_value_tables(res_tab, res_pair, dist_tab, dist_pair):
    """res 표와 dist 표를 하나로 합친다 -> ({키: (dist, res)}, 핀쌍키인가)

    한쪽에만 있는 넷은 그쪽 값만 채우고 나머지는 None 으로 둔다. 그 줄은
    annotated 에서 N/A 로 남는다 -- 조용히 0 을 넣지 않는다.
    """
    pair = res_pair and dist_pair          # 둘 다 핀 쌍일 때만 핀 쌍으로 본다
    if res_pair != dist_pair:
        # 키 모양이 다르면 합칠 수가 없다. 넷 이름 쪽으로 낮춘다.
        def flatten(t, is_pair):
            if not is_pair:
                return t
            out = {}
            for k, v in t.items():
                out.setdefault(k[0], v)
            return out
        res_tab = flatten(res_tab, res_pair)
        dist_tab = flatten(dist_tab, dist_pair)
        pair = False

    out = {}
    for k, v in dist_tab.items():
        out[k] = (v, res_tab.get(k))
    for k, v in res_tab.items():
        if k not in out:
            out[k] = (None, v)
    return out, pair


def load_table(path, res_scale=1.0, dist_scale=1.0):
    """표 -> ({키: (dist, res)}, 핀쌍키인가, 통계)"""
    with open(path, "r", errors="ignore") as f:
        raw = [ln.rstrip("\n\r") for ln in f]
    lines = [ln for ln in raw
             if ln.strip() and not ln.lstrip().startswith(("#", "//"))]
    if not lines:
        return {}, False, {"rows": 0, "bad": 0, "keys": 0,
                           "delim": "?", "header": False, "pair": False}

    delim = sniff(lines[:20])
    if delim:
        split = lambda s: [c.strip() for c in s.split(delim)]
    else:
        split = lambda s: s.split()

    first = split(lines[0])
    numeric = 0
    for tok in first[1:3]:
        try:
            float(tok)
            numeric += 1
        except ValueError:
            pass
    # 헤더 판별. 숫자가 하나도 없다는 것만으로는 부족하다 -- 첫 줄의 res/dist 가
    # 둘 다 N/A 인 데이터 줄일 수도 있고, 그러면 그 줄을 헤더로 먹어 버린다.
    # 그래서 아는 열 이름이 실제로 보일 때만 헤더로 본다.
    known = set(COL_NET) | set(COL_RES) | set(COL_DIST) | set(COL_DRV) | set(COL_RECV)
    looks_named = any(t.strip().lower().lstrip("#").strip() in known for t in first)
    has_header = numeric < 1 and looks_named

    if has_header:
        i_net = find_col(first, COL_NET)
        i_res = find_col(first, COL_RES)
        i_dist = find_col(first, COL_DIST)
        i_drv = find_col(first, COL_DRV)
        i_recv = find_col(first, COL_RECV)
        body = lines[1:]
        if i_net is None or i_res is None or i_dist is None:
            code("E-TABLE",
                 "[ FAILED ] cannot tell which column is which.",
                 "           header was: %s" % first,
                 "           rename the header, or drop it (then: net res dist)")
    else:
        i_net, i_res, i_dist, i_drv, i_recv = 0, 1, 2, None, None
        body = lines

    pair = i_drv is not None and i_recv is not None
    need = max(x for x in (i_net, i_res, i_dist, i_drv, i_recv) if x is not None) + 1

    tab = {}
    bad = 0
    conflict = 0
    for ln in body:
        c = split(ln)
        if len(c) < need or not c[i_net].strip():
            bad += 1
            continue
        val = (num(c[i_dist], dist_scale), num(c[i_res], res_scale))
        for v in name_variants(c[i_net]):
            k = (v, c[i_drv].strip(), c[i_recv].strip()) if pair else v
            if k in tab:
                if tab[k] != val:
                    conflict += 1
                continue
            tab[k] = val

    st = {"rows": len(body), "bad": bad, "keys": len(tab), "conflict": conflict,
          "delim": {None: "whitespace", ",": "comma", "\t": "tab",
                    ";": "semicolon", "|": "pipe"}[delim],
          "header": has_header, "pair": pair}
    return tab, pair, st


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(
        description="Dist/Res from a supplied table instead of the SPEF.")
    ap.add_argument("--dir", default=".",
                    help="corner folder that holds timing.rpt")
    ap.add_argument("--rpt", default=None)
    ap.add_argument("--table", default=None,
                    help="combined table, if it is not <dir>/" + TABLE_NAME)
    ap.add_argument("--res-table", default=None,
                    help="res-only table, if it is not <dir>/" + RES_NAME)
    ap.add_argument("--dist-table", default=None,
                    help="dist-only table, if it is not <dir>/" + DIST_NAME)
    ap.add_argument("--out", default=None,
                    help="default <dir>/distres.tsv, so 2c_merge.py picks it up")
    ap.add_argument("--res-scale", type=float, default=1.0,
                    help="multiply every table res by this (unit alignment)")
    ap.add_argument("--dist-scale", type=float, default=1.0,
                    help="multiply every table dist by this (unit alignment)")
    args = ap.parse_args()

    d = args.dir
    rpt, err, _ = find_rpt(d, args.rpt)
    if err:
        print("[ FAILED ] %s" % err)
        sys.exit(1)
    # 표를 찾는 순서
    #   1) --table (합본)                    2) 코너 폴더의 resdist_map.txt
    #   3) --res-table / --dist-table (따로)  4) 코너 폴더의 res_map.txt + dist_map.txt
    # res 와 dist 를 따로 받는 경우가 있어서 둘 다 받는다.
    combined = args.table or os.path.join(d, TABLE_NAME)
    res_p = args.res_table or os.path.join(d, RES_NAME)
    dist_p = args.dist_table or os.path.join(d, DIST_NAME)

    use_combined = bool(args.table) or os.path.isfile(combined)
    use_split = (not use_combined) and os.path.isfile(res_p) and os.path.isfile(dist_p)

    if not use_combined and not use_split:
        # code() 로 끝내야 한다. 그냥 exit 하면 4_all_corners 의 결과표에 "?" 로
        # 남아서 무엇 때문에 걸렸는지 표만 봐서는 알 수 없다.
        miss = []
        if not os.path.isfile(res_p):
            miss.append(os.path.basename(res_p))
        if not os.path.isfile(dist_p):
            miss.append(os.path.basename(dist_p))
        code("E-NOTABLE",
             "[ FAILED ] no table in %s" % d,
             "           looked for : %s" % os.path.basename(combined),
             "                  or  : %s + %s"
             % (os.path.basename(res_p), os.path.basename(dist_p)),
             "           missing    : %s" % ", ".join(miss))

    out = args.out or os.path.join(d, "distres.tsv")

    print("=" * 68)
    print("2b (table) - Dist / Res    [no SPEF]")
    print("=" * 68)
    print("  report : %s" % rpt)

    if use_combined:
        print("  table  : %s" % combined)
        tab, pair, st = load_table(combined, args.res_scale, args.dist_scale)
        print("  parsed : rows=%d keys=%d bad=%d  delim=%s header=%s"
              % (st["rows"], st["keys"], st["bad"], st["delim"], st["header"]))
        if st.get("conflict"):
            print("  note   : %d duplicate names with different values, first kept"
                  % st["conflict"])
    else:
        print("  res    : %s" % res_p)
        print("  dist   : %s" % dist_p)
        rt, rp, rst = load_value_table(res_p, "res", args.res_scale)
        dt, dp, dst = load_value_table(dist_p, "dist", args.dist_scale)
        print("  parsed : res  rows=%d keys=%d bad=%d  delim=%s header=%s"
              % (rst["rows"], rst["keys"], rst["bad"], rst["delim"], rst["header"]))
        print("           dist rows=%d keys=%d bad=%d  delim=%s header=%s"
              % (dst["rows"], dst["keys"], dst["bad"], dst["delim"], dst["header"]))
        tab, pair = merge_value_tables(rt, rp, dt, dp)
        only_res = len([k for k in rt if k not in dt])
        only_dist = len([k for k in dt if k not in rt])
        if only_res or only_dist:
            print("  note   : res 에만 있는 넷 %d개, dist 에만 있는 넷 %d개 "
                  "-> 그 줄은 한쪽만 채워집니다" % (only_res, only_dist))
    print("  key    : %s" % ("net + driver pin + receiver pin"
                             if pair else "net name only"))
    if not tab:
        code("E-TABLE",
             "[ FAILED ] no usable rows in the table.")

    rows = scan_report(rpt)
    print("  (net) lines : %d" % len(rows))
    print("")

    # 넷 이름만으로 키를 잡을 때, 리시버가 여럿인 넷이 몇 줄이나 되는지 센다.
    # 그 줄들은 전부 같은 값을 받게 되므로 조용히 넘기지 않는다.
    recv_of = {}
    for _idx, net, _drv, rcv in rows:
        recv_of.setdefault(net, set()).add(rcv)
    many = set(n for n, r in recv_of.items() if len(r) > 1)

    n = hit_d = hit_r = 0
    squashed = 0
    tmp = []
    for idx, net, drv, rcv in rows:
        n += 1
        if net in many:
            squashed += 1
        dist = res = None
        for v in name_variants(net):
            k = (v, drv or "", rcv or "") if pair else v
            if k in tab:
                dist, res = tab[k]
                break
        if dist is not None:
            hit_d += 1
        if res is not None:
            hit_r += 1
        tmp.append((idx, net, dist, res))

    with wopen(out) as fh:
        fh.write("line_no\tnet\tdist\tres\n")
        for idx, net, dist, res in tmp:
            fh.write("%d\t%s\t%s\t%s\n" % (idx, net, fmt(dist), fmt(res)))

    print("-" * 68)
    print("  out       : %s" % out)
    print("  rows      : %d" % n)
    print("  Dist found: %d   (miss %d)" % (hit_d, n - hit_d))
    print("  Res  found: %d   (miss %d)" % (hit_r, n - hit_r))
    if not pair:
        print("  squashed  : %d rows (%.1f%%) sit on a net with >1 receiver"
              % (squashed, 100.0 * squashed / n if n else 0.0))
    print("-" * 68)

    if n == 0:
        code("E-NOROW", "[ FAILED ] the report has no (net) lines.")
    if hit_r == 0 and hit_d == 0:
        code("E-TABLE0",
             "[ FAILED ] not one net name in the table matched the report.")
    if hit_r < n * 0.9:
        code("W-RES",
             "[ CHECK ] Res is empty on %d rows (%.0f%%)."
             % (n - hit_r, 100.0 * (n - hit_r) / n))
    if not pair and squashed:
        code("W-NETKEY",
             "[ CHECK ] %d rows (%.1f%%) share a net with other receivers,"
             % (squashed, 100.0 * squashed / n),
             "          so they all got the same value from the table.",
             "          measured on BoomCoreV3: 3 columns -> 69.4% correct,",
             "          adding driver/receiver pin columns -> 100%.")
    code("OK-DISTRES",
         "[ OK ] Dist/Res %d/%d." % (hit_r, n),
         "       next:  %s 2c_merge.py --dir %s" % (sys.executable, d))


if __name__ == "__main__":
    main()
