#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2a - Cpin (리시버 핀 capacitance) 표를 만든다.

    python3 2a_cpin.py --dir ./work
    python3 2a_cpin.py --dir ./work --cpin-map <받은표>   # pin_attr.txt 대신

입력   timing.rpt     어느 넷을 누가 받는지
       pin_attr.txt   PT 핀 attribute 덤프
       (또는 --cpin-map 으로 받은 2열 표. 아래 참조)
출력   cpin.tsv       line_no / net / recv_pin / cpin

--cpin-map : 현장에서 "이름 <탭/쉼표/공백> Cpin" 2열로 받은 표를 쓸 때 준다.
1열이 무엇인지는 리포트와 대조해 **알아서 판별**한다.

    inst/pin      U123/A                       설계 핀   -> 그대로
    cell/pin      gt3_6t_and2_x1_rvt/A         셀의 핀   -> 리포트로 펼침
    lib/cell/pin  op_cond_all/..._x1_rvt/A     get_lib_pins 출력 -> 앞을 떼고 펼침
    cell          gt3_6t_and2_x1_rvt           셀만      -> 핀 구분 없음, 중단
    net           ZCTSNET_4157                 넷 이름   -> Cpin 이 아님, 중단

뒤의 둘은 **멈춘다.** 그대로 쓰면 조용히 틀린 값이 들어가기 때문이다.
Cpin 은 핀마다 다르므로 핀 단위 값을 받아야 한다.

**값 열도 알아서 고른다.** pin cap 과 wire cap 이 같이 있는 표여도,
순서가 어느 쪽이어도 된다. 리포트의 '(net)' 줄에 그 넷의 전체 cap 이
찍혀 있는데, Cpin 은 리시버 하나의 값이라 그보다 작아야 한다. 열마다
그 비율을 재서 제일 높은 열을 쓴다. 화면에 어느 열을 왜 골랐는지 찍는다.

    값 열 : 2번째 (자동 선택, 넷 전체 cap 보다 작은 비율 100%)
        3번째 열은 12% -- 안 씀

먼저 앞 300개만 보고, 열이 확연히 안 갈리면 전체로 다시 센다. 사이트
데이터가 우리 예제처럼 깔끔하게 갈리지 않을 수 있어서다.

--cpin-col 로 직접 지정할 수도 있다(이름 열이 1).

담당자분께 부탁드릴 때 쓸 수 있는 두 가지 (PT 로 실측 확인):

    # (가) 설계 핀 -- 제일 정확. 핀 수만큼 나온다
    foreach_in_collection p [get_pins -hierarchical *] {
        puts "[get_object_name $p]\t[get_attribute -quiet $p pin_capacitance_max]"
    }

    # (나) 라이브러리 핀 -- 훨씬 작다(셀 종류 수). 값은 (가)와 같다
    foreach_in_collection p [get_lib_pins *] {
        puts "[get_object_name $p]\t[get_attribute -quiet $p pin_capacitance]"
    }

주의: lib_pin 에서는 attribute 이름이 `pin_capacitance` 다.
`capacitance` 나 `pin_capacitance_max` 는 빈 값으로 나온다(실측).

앞의 둘은 pin_attr.txt 로 만든 것과 **byte 단위로 같은** cpin.tsv 가 나온다
(BoomCoreV3 로 확인). 셋째는 핀 구분이 없어 값이 어긋난다 -- 화면에 경고가
뜬다. 실측하면 80%는 그대로였지만 상위 10%가 1.6%, 최악은 146% 틀렸다.

이 단계는 **SPEF 를 읽지 않는다.** 그래서 몇 초면 끝나고, SPEF 에 문제가 있어도
Cpin 은 정상적으로 나온다. 핀 이름이 안 맞는 문제를 여기서 먼저 걸러낸다.

Cpin 이 뭔가:
    리포트의 '(net)' 줄 바로 다음에 오는 핀이 그 넷의 리시버다. 그 핀의 입력
    capacitance 가 Cpin 이다. PT 는 리포트에 이 값을 찍어주지 않으므로
    report_attribute 로 따로 뽑아 이름으로 붙인다.
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
ATTR = "pin_capacitance_max"



# ---------------------------------------------------------------------------
# 현장에서 "cell 이름 / cpin 값" 2열 파일을 받는 경우
# ---------------------------------------------------------------------------
# pin_attr.txt 를 못 받고 담당자분이 PT 로 따로 뽑아 주신 표를 쓸 때 쓴다.
# 1열이 무엇인지 사이트마다 달라서 **파일을 보고 알아서 판별**한다.
#
#   (1) inst/pin      U123/A                    설계 핀. 제일 정확하다
#   (2) libcell/pin   gt3_6t_and2_x1_rvt/A      라이브러리 셀의 핀
#   (3) libcell       gt3_6t_and2_x1_rvt        셀만. 핀 구분이 없다
#
# (2)(3)은 리포트에서 "핀 -> 셀" 을 읽어 설계 핀으로 펼친다. 리포트가
#   U123/A (gt3_6t_and2_x1_rvt)
# 형태로 셀 이름을 같이 적어 주기 때문에 가능하다.
#
# (3)은 **정보가 준다.** 한 셀 안에서도 핀마다 Cpin 이 다르기 때문이다
# (실측: gt3_6t_and2_x1_rvt 의 A=0.000378, B=0.000371 -- 약 2% 차이).
# 그래서 (3)으로 판별되면 화면에 경고를 띄운다.

CELL_RE = re.compile(r"^\s+(\S+/\S+)\s+\(([^)]+)\)")



NUMS_RE = re.compile(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?")


def scan_report(rpt):
    """리포트를 **한 번만** 읽어 세 가지를 함께 만든다.

        recv     [(줄번호, 넷, 리시버핀)]   '(net)' 줄 다음 첫 핀 줄
        netcap   {줄번호: 넷 전체 cap}      '(net)' 줄 끝의 마지막 숫자
        pin2cell {설계핀: 라이브러리셀}     'U123/A (cell)' 의 괄호 안

    예전에는 이 셋을 따로 만들어 같은 파일을 세 번 훑었다. 셋 다 같은
    줄에서 같은 정규식으로 뽑는 것이라 한 번에 끝난다.
    """
    recv = []
    netcap = {}
    pin2cell = {}
    pending = None
    with open(rpt, "r", errors="ignore") as f:
        for idx, line in enumerate(f):
            m = OBJ_RE.match(line)
            if not m:
                continue
            name, kind = m.group(1), m.group(2)
            if kind.lower() == "net":
                pending = (idx, name)
                nums = NUMS_RE.findall(line[m.end():])
                if nums:
                    try:
                        netcap[idx] = float(nums[-1])
                    except ValueError:
                        pass
                continue
            if "/" in name:
                pin2cell[name] = kind
            if pending is not None:
                recv.append((pending[0], pending[1], name))
                pending = None
    if pending is not None:
        recv.append((pending[0], pending[1], ""))
    return recv, netcap, pin2cell

def load_pin_to_cell(rpt):
    """리포트에서 {설계핀: 라이브러리셀}. 같은 핀이 여러 번 나와도 값은 같다."""
    out = {}
    with open(rpt, "r", errors="ignore") as f:
        for line in f:
            m = CELL_RE.match(line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def read_name_value_rows(path):
    """받은 표를 읽어 [(이름, [열값들])] 로 돌려준다.

    구분자는 탭/쉼표/콜론/공백 아무거나. 주석(#)·빈 줄·헤더는 건너뛴다.
    숫자 열이 몇 개든 **전부 담는다.** 어느 열이 Cpin 인지는 나중에
    리포트와 대조해 고른다(pin cap 과 wire cap 이 같이 오는 경우가 있다).

    값은 원문 문자열 그대로 담는다. float 로 바꿔 담으면 0.000520 이
    0.00052 로 바뀌어 pin_attr.txt 경로와 표기가 어긋난다.
    """
    NUM = re.compile(r"^([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"
                     r"\s*[a-zA-Z]{0,3}$")

    def num(tok):
        # 숫자 뒤에 단위가 붙어 있어도 받는다(0.0012pF). 이름 같은 토큰은 뺀다.
        m = NUM.match(tok.strip("{}\"'"))
        return m.group(1) if m else None

    rows = []
    ncol = 0
    with open(path, "r", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("*"):
                continue
            if "\t" in line:
                parts = line.split("\t")
            elif "," in line:
                parts = line.split(",")
            elif ":" in line:
                parts = line.split(":")
            else:
                parts = line.split()
            parts = [q.strip() for q in parts if q.strip() != ""]
            if len(parts) < 2:
                continue
            # Tcl 로 뽑으면 이름에 중괄호/따옴표가 붙는다.
            #   foreach p [get_pins *] { puts "$p [get_attribute $p ...]" }
            key = parts[0].strip("{}\"'")
            vals = [num(t) for t in parts[1:]]
            if not any(v is not None for v in vals):
                continue            # 헤더 줄 등
            rows.append((key, vals))
            if len(vals) > ncol:
                ncol = len(vals)
    return rows, ncol


def load_cpin_map(path, rpt, col=None, recv=None, netcap=None, pin2cell=None):
    """받은 표 -> {설계핀: 값}. (dict, 판별한 종류, 안내문들) 반환."""
    rows, ncol = read_name_value_rows(path)
    if not rows:
        return {}, "none", ["파일에서 '이름 값' 을 하나도 못 읽었습니다."]

    if pin2cell is None:
        pin2cell = load_pin_to_cell(rpt)
    design_pins = set(pin2cell)
    cells = set(pin2cell.values())
    cell_pins = set()          # 'cell/pin' 형태로 만들어 둔 것
    for pin, cell in pin2cell.items():
        cell_pins.add("%s/%s" % (cell, pin.rsplit("/", 1)[1]))

    # get_lib_pins 로 뽑으면 이름이 '라이브러리/셀/핀' 3단으로 나온다.
    #   op_cond_all/gt3_6t_buf_x12_rvt/A
    # 앞의 라이브러리 이름을 떼면 'cell/pin' 이 된다. 값은 설계 핀의
    # pin_capacitance_max 와 같다(실측 확인).
    def drop_lib(k):
        parts = k.split("/")
        if len(parts) == 3:
            return "/".join(parts[1:])
        return k

    # 리포트에 나오는 넷 이름도 모아 둔다. 받은 표가 넷 단위면
    # 그건 Cpin 이 아니라 넷의 wire cap 일 가능성이 크다.
    if recv is None or netcap is None:
        recv, netcap, _pc = scan_report(rpt)
    nets = set(net for _i, net, _p in recv)

    keys = [k for k, _ in rows]
    n = float(len(keys))
    hit_net = sum(1 for k in keys if k in nets) / n
    hit_design = sum(1 for k in keys if k in design_pins) / n
    hit_cellpin = sum(1 for k in keys if k in cell_pins) / n
    hit_cell = sum(1 for k in keys if k in cells) / n
    hit_libpin = sum(1 for k in keys if drop_lib(k) in cell_pins) / n

    note = []
    # 동점이면 앞쪽을 고른다. 2단(cell/pin)은 drop_lib 가 그대로 두므로
    # lib_cell_pin 과 점수가 같아지는데, 그때는 cell_pin 이라고 불러야 맞다.
    cand = [(hit_design, "design_pin"), (hit_cellpin, "cell_pin"),
            (hit_libpin, "lib_cell_pin"), (hit_cell, "cell"),
            (hit_net, "net")]
    best = cand[0]
    for c in cand[1:]:
        if c[0] > best[0]:
            best = c
    if best[1] == "cell" and best[0] >= 0.05:
        note.append("1열이 **셀 이름만** 입니다(핀 구분이 없습니다).")
        note.append("  Cpin 은 핀마다 다릅니다. 한 셀 안에서도 A/B/CLK 이 다르고,")
        note.append("  BoomCoreV3 로 재 보니 최악 146% 어긋났습니다.")
        note.append("  그대로 쓰면 조용히 틀린 값으로 annotation 되므로 멈춥니다.")
        note.append("  담당자분께 **핀 단위**로 부탁드려야 합니다:")
        note.append("    get_attribute <pin> pin_capacitance_max        (설계 핀)")
        note.append("    get_attribute <lib_pin> pin_capacitance        (라이브러리 핀)")
        return {}, "cell", note

    if best[1] == "net" and best[0] >= 0.05:
        note.append("1열이 **넷 이름**입니다. Cpin(리시버 핀의 입력 capacitance)이")
        note.append("  아니라 넷 쪽 값(wire cap 등)으로 보입니다.")
        note.append("  Cpin 은 핀마다 다르므로 넷 단위 값으로는 못 만듭니다.")
        note.append("  담당자분께 **핀 단위**로 부탁드려야 합니다:")
        note.append("    get_attribute <pin> pin_capacitance_max        (설계 핀)")
        note.append("    get_attribute <lib_pin> pin_capacitance        (라이브러리 핀)")
        note.append("  이미 받은 표에 핀 열이 따로 있으면 --cpin-col 로 고르세요.")
        return {}, "net", note

    if best[0] < 0.05:
        note.append("1열이 리포트의 핀 이름과도, 셀 이름과도 안 맞습니다.")
        note.append("  읽은 예: %s" % ", ".join(keys[:3]))
        note.append("  리포트 핀 예: %s" % ", ".join(sorted(design_pins)[:2]))
        note.append("  리포트 셀 예: %s" % ", ".join(sorted(cells)[:2]))
        return {}, "unknown", note

    kind = best[1]

    # --- 어느 열이 Cpin 인지 고른다 -------------------------------------
    # 표에 pin cap 과 wire cap 이 같이 오는 경우가 있어 열 순서를 믿을 수 없다.
    # 리포트의 '(net)' 줄에 그 넷의 **전체 cap** 이 찍혀 있으므로, 그것보다
    # 작은 값이 나오는 열이 pin cap 이다. 열마다 그 비율을 재서 제일 높은
    # 열을 쓴다. --cpin-col 을 주면 그것을 그대로 따른다.
    def expand(vi):
        """vi 번째 열로 {설계핀: 값} 을 만든다."""
        out = {}
        for k, vals in rows:
            if vi >= len(vals) or vals[vi] is None:
                continue
            kk = (k if kind == "design_pin"
                  else drop_lib(k) if kind == "lib_cell_pin" else k)
            out[kk] = vals[vi]
        if kind == "design_pin":
            return out
        res = {}
        for pin, cell in pin2cell.items():
            leaf = pin.rsplit("/", 1)[1]
            v = (out.get("%s/%s" % (cell, leaf)) if kind in ("cell_pin", "lib_cell_pin")
                 else out.get(cell))
            if v is not None:
                res[pin] = v
        return res

    # 판정용 표본. 전부 볼 필요가 없다 -- wire cap 열과 pin cap 열은
    # 12% 대 100% 로 확연히 갈려서 몇백 개만 봐도 결론이 같다.
    # (전부 보면 리포트만큼 도는 루프가 열 개수만큼 반복된다)
    SAMPLE = 300
    allrows = [(i, p) for i, _n, p in recv if netcap.get(i)]
    sample = allrows[:SAMPLE]

    def score(cand, rows_):
        """넷 전체 cap 보다 작은 비율. Cpin 이면 1 에 가깝다."""
        ok = tot = 0
        for idx, pin in rows_:
            v = cand.get(pin)
            if v is None:
                continue
            try:
                fv = float(v)
            except ValueError:
                continue
            tot += 1
            if 0 < fv < netcap[idx]:
                ok += 1
        return (float(ok) / tot) if tot else 0.0

    if col:
        vi = col - 2                      # 이름 열이 1 이므로 값 열은 2부터
        if vi < 0:
            vi = 0
        caps = expand(vi)
        note.append("값 열 : %d번째 (직접 지정)" % (vi + 2))
    else:
        cols = [(vi, expand(vi)) for vi in range(ncol)]
        cols = [(vi, c) for vi, c in cols if c]
        if not cols:
            return {}, kind, note + ["숫자 열을 하나도 못 읽었습니다."]

        # 먼저 표본으로만 본다. 열이 확연히 갈리면 그걸로 끝낸다.
        cands = sorted(((score(c, sample), -vi, vi, c) for vi, c in cols),
                       reverse=True)
        top = cands[0][0]
        second = cands[1][0] if len(cands) > 1 else 0.0
        # 애매하면(1등이 낮거나 2등과 가깝거나) 전수로 다시 센다.
        # 사이트 데이터가 우리처럼 깔끔하게 안 갈릴 수 있다.
        if len(cands) > 1 and (top < 0.9 or top - second < 0.2):
            note.append("표본 %d개로는 열이 안 갈려 전체로 다시 셌습니다."
                        % len(sample))
            cands = sorted(((score(c, allrows), -vi, vi, c) for vi, c in cols),
                           reverse=True)
        sc, _, vi, caps = cands[0]
        if ncol > 1:
            note.append("값 열 : %d번째 (자동 선택, 넷 전체 cap 보다 작은 비율 %.0f%%)"
                        % (vi + 2, sc * 100))
            for s2, _n, v2, _c in sorted(cands, key=lambda x: x[2]):
                if v2 != vi:
                    note.append("    %d번째 열은 %.0f%% -- 안 씀" % (v2 + 2, s2 * 100))
        if sc < 0.5:
            note.append("어느 열도 Cpin 처럼 보이지 않습니다(제일 나은 것이 %.0f%%)." % (sc * 100))
            note.append("  wire cap 만 있는 표일 수 있습니다. 핀 cap 을 받아야 합니다.")
    return caps, kind, note


def load_pin_caps(path, attr=ATTR):
    """report_attribute 덤프 -> {핀이름: 값}

    PT 는 이름이 길면 줄을 접는다. 세 형태를 모두 받는다:
      (A) <design> <pin> float <attr> <value>
      (B) <design> <pin>  /  (다음 줄) float <attr> <value>
      (C) float <attr>    /  (다음 줄) <value>
    """
    caps = {}
    last_obj = None
    awaiting = None
    with open(path, "r", errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            # 구분선(----, ====)과 배너(***)만 건너뛴다.
            # 예전에 s[0] 로만 판단했더니 "-0.000274" 같은 **음수 값**이 구분선으로
            # 오인돼 통째로 사라졌다. 그 줄이 없어지면 대기 상태가 남아 다음 줄까지
            # 잘못 먹어, attribute 하나가 더 사라진다.
            if not s or s[0] == "*" or set(s) <= set("-=") :
                continue
            parts = s.split()
            if awaiting is not None:
                try:
                    caps[awaiting] = parts[0]
                except IndexError:
                    pass
                awaiting = None
                continue
            if not raw[:1].isspace() and len(parts) >= 2:
                last_obj = parts[1]
            if attr not in parts:
                continue
            i = parts.index(attr)
            if i + 1 < len(parts):
                caps[last_obj] = parts[i + 1]
            else:
                awaiting = last_obj
    return caps


def iter_net_receiver(rpt):
    """(줄번호, 넷이름, 리시버핀) 를 내놓는다.

    '(net)' 줄 다음에 처음 나오는 핀 줄이 그 넷의 리시버다.
    """
    pending = None
    with open(rpt, "r", errors="ignore") as f:
        for idx, line in enumerate(f):
            m = OBJ_RE.match(line)
            if not m:
                continue
            name, kind = m.group(1), m.group(2)
            if kind.lower() == "net":
                pending = (idx, name)
                continue
            if pending is not None:
                yield pending[0], pending[1], name
                pending = None
    if pending is not None:
        yield pending[0], pending[1], ""



def net_line_caps(rpt):
    """{줄번호: 넷 전체 cap}. '(net)' 줄 끝의 마지막 숫자가 그 넷의 cap 이다.

        ZCTSNET_6904 (net)      12 0.023539
                                ^^ fanout  ^^^^^^^^ cap

    Cpin(리시버 한 개의 입력 capacitance)은 이 값보다 작아야 한다.
    받은 표에서 엉뚱한 열(wire cap 등)을 집었는지 확인하는 데 쓴다.
    """
    out = {}
    for idx, line in enumerate(open(rpt, "r", errors="ignore")):
        m = OBJ_RE.match(line)
        if not m or m.group(2).lower() != "net":
            continue
        nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?",
                          line[m.end():])
        if nums:
            try:
                out[idx] = float(nums[-1])
            except ValueError:
                pass
    return out

# ---- 결과 코드 -------------------------------------------------------
# 마지막에 "무슨 문제인지 + 어떻게 하면 되는지 + 코드" 를 함께 찍는다.
# 현장에서 화면을 복사하기 어려우므로, 읽고 바로 이해할 수 있어야 하고
# 코드는 원격으로 물어볼 때 쓴다. 코드 목록은 코드표.md 에 있다.
CODE_INFO = {
    # 코드            (한 줄 설명,                          무엇을 하면 되는지)
    "E-NORPT":    ("리포트 파일(.rpt)을 못 찾았습니다",
                   "--dir 로 준 폴더에 코너별 report_timing 결과를 넣어 주세요."),
    "E-ISPARENT": ("코너 폴더가 아니라 코너들이 든 상위 폴더를 주셨습니다",
                   "코너 폴더까지 지정하거나, 4_all_corners.py --root 를 쓰세요."),
    "E-RPTMANY":  ("폴더에 .rpt 가 여러 개라 어느 것인지 모르겠습니다",
                   "--rpt <파일> 로 하나를 지정하거나, 코너마다 폴더를 나눠 주세요."),
    "E-NOFILE":   ("필요한 입력 파일이 없습니다",
                   "0_check.py 를 돌리면 무엇이 없는지 알려줍니다."),
    "E-NOPATH":   ("리포트에서 경로를 하나도 못 읽었습니다",
                   "report_timing 에 -input_pins 를 넣어 다시 뽑아 주세요."),
    "E-NONET":    ("리포트에 '(net)' 줄이 없습니다",
                   "report_timing 에 -nets 를 넣어 다시 뽑아 주세요."),
    "E-NOATTR":   ("속성 덤프에서 값을 하나도 못 읽었습니다",
                   "report_attribute 에 -application 을 넣어 다시 뽑아 주세요."),
    "E-PINNAME":  ("리포트의 핀 이름이 속성 덤프와 하나도 안 맞습니다",
                   "지금 쓰는 리포트로 dump_attr.tcl 을 다시 돌려 주세요."),
    "E-RES0":     ("SPEF 에서 저항(Res)을 하나도 못 구했습니다",
                   "SPEF 가 이 리포트와 같은 디자인/코너인지 확인해 주세요."),
    "E-NOINPUT":  ("붙일 값(cpin/distres)이 하나도 없습니다",
                   "2a_cpin.py 와 2b_distres.py 를 먼저 돌려 주세요."),
    "E-NOROW":    ("결과 표에 줄이 하나도 없습니다",
                   "timing.rpt 이 report_timing 출력이 맞는지 확인해 주세요."),
    "W-DROP":     ("합집합에서 버린 경로가 많습니다",
                   "report_timing 옵션 4개(-nets -input_pins -nosplit "
                   "-path_type full_clock_expanded)를 확인해 주세요."),
    "W-CPINCOL": ("고른 값이 넷 전체 cap 과 같습니다",
                   "pin cap 이 아니라 wire cap 열을 집었을 수 있습니다. "
                   "--cpin-col 로 다른 열을 골라 보세요."),
    "W-CPIN":     ("Cpin 이 비어 있는 줄이 많습니다",
                   "지금 리포트로 dump_attr.tcl 을 다시 돌려 보세요."),
    "W-RES":      ("Dist/Res 가 비어 있는 줄이 많습니다",
                   "2c_merge.py 를 돌리면 원인을 A/B/C 로 나눠 줍니다(자동)."),
    "W-NA":       ("결과에 N/A 가 남아 있습니다",
                   "2c_merge.py 를 돌리면 원인이 자동으로 나옵니다."),
}


def code(c, *msg):
    """무슨 일이 있었는지 설명하고 코드를 찍는다.

    E- 로 시작하면 실패라 여기서 멈춘다. W- 는 결과는 나왔지만 확인이 필요한 경우.
    """
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  정상 종료           [ %s ]" % c)
        print("=" * 66)
        return
    what, todo = CODE_INFO.get(c, ("", ""))
    kind = "문제 발생" if c.startswith("E-") else "확인 필요"
    print("  %s" % kind)
    if what:
        print("    무엇이   : %s" % what)
        print("    하실 일  : %s" % todo)
    print("")
    print("    에러 코드: %s" % c)
    print("    (해결이 안 되면 이 코드를 알려주세요)")
    print("=" * 66)
    # 코드는 항상 마지막에 한 번만 나와야 한다. 경고(W-)에서 멈추지 않으면
    # 뒤이어 정상(OK-)까지 찍혀 어느 쪽인지 헷갈린다.
    sys.exit(1 if c.startswith("E-") else 0)


def main():
    ap = argparse.ArgumentParser(description="Cpin 표를 만든다 (SPEF 불필요).")
    ap.add_argument("--dir", default=".",
                    help="**코너 폴더 하나** (그 안에 .rpt 가 있는 폴더). 여러 코너를 한 번에 하려면 4_all_corners.py --root")
    ap.add_argument("--rpt", default=None)
    ap.add_argument("--pin-attr", default=None)
    ap.add_argument("--cpin-map", default=None,
                    help="현장에서 받은 '이름  Cpin' 표. 주면 pin_attr.txt "
                         "대신 이걸 쓴다. 1열이 설계핀/셀핀/lib핀/셀/넷 "
                         "어느 것인지는 알아서 판별한다")
    ap.add_argument("--cpin-col", type=int, default=None,
                    help="값으로 쓸 열 번호(이름 열이 1). 숫자 열이 여럿일 때 "
                         "쓴다. 예: 'pin  pincap  wirecap' 이면 --cpin-col 2")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d = args.dir
    rpt, _err, _ec = find_rpt(d, args.rpt)   # 폴더 안의 .rpt 를 찾는다(이름 자유)
    if _err:
        print("")
        code(_ec, "[ 실패 ] " + _err)
    pin_attr = args.pin_attr or os.path.join(d, "pin_attr.txt")
    out = args.out or os.path.join(d, "cpin.tsv")

    print("=" * 68)
    print("2a - Cpin 표  (SPEF 를 읽지 않습니다)")
    print("=" * 68)

    need = [("timing.rpt", rpt)]
    if args.cpin_map:
        need.append(("cpin-map", args.cpin_map))
    else:
        need.append(("pin_attr.txt", pin_attr))
    for label, p in need:
        if not os.path.isfile(p):
            print("")
            msg = ["[ 실패 ] %s 이 없습니다: %s" % (label, p)]
            if label == "pin_attr.txt":
                # 현장에서 Cpin 표를 받아 쓰는 경우가 많다. pin_attr.txt 는
                # dump_attr.tcl 로 뽑는 것이라 없을 수 있으니 대안을 알려준다.
                msg += ["",
                        "         Cpin 을 얻는 길은 둘입니다.",
                        "         (1) 받은 Cpin 표를 쓴다  <- 보통 이쪽",
                        "               --cpin-map <받은파일>",
                        "         (2) PT 에서 직접 뽑는다",
                        "               pt_shell> source <패키지>/dev/dump_attr.tcl",
                        "               -> 이 폴더에 pin_attr.txt 가 생깁니다"]
            else:
                msg.append("         0_check.py 로 무엇이 없는지 확인하세요.")
            code("E-NOFILE", *msg)
    print("  리포트    : %s" % rpt)

    if args.cpin_map:
        # 현장에서 받은 2열 표를 쓴다. 1열이 무엇인지는 알아서 판별한다.
        print("  Cpin 표   : %s" % args.cpin_map)
        # 리포트는 여기서 한 번만 훑고, 그 결과를 아래까지 돌려 쓴다.
        _recv, _netcap, _p2c = scan_report(rpt)
        caps, kind, note = load_cpin_map(args.cpin_map, rpt, args.cpin_col,
                                         _recv, _netcap, _p2c)
        label = {"design_pin":   "설계 핀 (inst/pin)",
                 "cell_pin":     "셀의 핀 (cell/pin)",
                 "lib_cell_pin": "라이브러리 핀 (lib/cell/pin) -- get_lib_pins",
                 "cell":         "셀 이름만 (핀 구분 없음)"}.get(kind, kind)
        print("  1열 판별  : %s" % label)
        for m in note:
            print("    %s" % m)
        if not caps:
            print("")
            code("E-NOATTR",
                 "[ 실패 ] Cpin 표에서 쓸 수 있는 값을 못 만들었습니다.")
    else:
        print("  핀 속성   : %s" % pin_attr)
        caps = load_pin_caps(pin_attr)
        if not caps:
            print("")
            code("E-NOATTR",
                 "[ 실패 ] pin_attr.txt 에서 %s 를 하나도 못 읽었습니다." % ATTR,
                 "         report_attribute 에 -application 이 필요합니다.")
    print("  읽은 핀   : %d개" % len(caps))

    # 받은 표를 쓸 때만: 고른 값이 넷 전체 cap 과 같지 않은지 본다.
    # 같으면 pin cap 이 아니라 wire cap 열을 집었을 가능성이 크다.
    netcap = _netcap if args.cpin_map else {}
    n_same = n_over = n_cmp = 0

    n = hit = 0
    miss_examples = []
    with wopen(out) as fh:
        fh.write("line_no\tnet\trecv_pin\tcpin\n")
        for idx, net, pin in (_recv if args.cpin_map
                              else iter_net_receiver(rpt)):
            v = caps.get(pin, "")
            if v:
                hit += 1
                nc = netcap.get(idx)
                if nc:
                    try:
                        fv = float(v)
                        n_cmp += 1
                        if abs(fv - nc) <= abs(nc) * 1e-9:
                            n_same += 1
                        elif fv > nc:
                            n_over += 1
                    except ValueError:
                        pass
            elif len(miss_examples) < 8:
                miss_examples.append(pin)
            n += 1
            fh.write("%d\t%s\t%s\t%s\n" % (idx, net, pin, v))

    print("")
    print("-" * 68)
    print("  결과 파일 : %s" % out)
    print("  (net) 줄  : %d" % n)
    print("  Cpin 있음 : %d" % hit)
    print("  Cpin 없음 : %d" % (n - hit))
    print("-" * 68)

    if n == 0:
        code("E-NONET",
             "[ 실패 ] '(net)' 줄이 없습니다.",
             "         report_timing 에 -nets -input_pins 가 빠졌습니다.")
    if hit == 0:
        code("E-PINNAME",
             "[ 실패 ] 핀 이름이 하나도 안 맞습니다.",
             "         리포트의 핀 이름 예: %s" % ", ".join(miss_examples[:3]))
    if n_cmp and (n_same + n_over) * 2 > n_cmp:
        code("W-CPINCOL",
             "[ 주의 ] 고른 값이 넷 전체 cap 과 같거나 더 큽니다 (%d/%d)."
             % (n_same + n_over, n_cmp),
             "         Cpin 은 리시버 핀 하나의 값이라 넷 전체 cap 보다 작아야",
             "         합니다. pin cap 이 아니라 wire cap 열을 집었을 수 있습니다.",
             "         --cpin-col 로 다른 열을 골라 보세요 (이름 열이 1).",
             "         지금 값 예: %s" % ", ".join(
                 "%s=%s" % (p, caps.get(p)) for p in list(caps)[:2]))

    if hit < n * 0.9:
        code("W-CPIN",
             "[ 주의 ] %d개는 Cpin 이 비었습니다 (전체 %d)." % (n - hit, n),
             "         예: %s" % ", ".join(miss_examples[:3]))
    else:
        code("OK-CPIN",
             "[ 정상 ] Cpin %d/%d." % (hit, n),
             "         다음 단계:  %s 2b_distres.py --dir %s" % (sys.executable, d))


if __name__ == "__main__":
    main()
