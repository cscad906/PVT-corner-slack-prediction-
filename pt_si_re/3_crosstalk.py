#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3단계 - crosstalk / timing window 표를 만든다.

    python3 3_crosstalk.py --dir ./work

입력 (--dir 폴더 안)
    timing.rpt     PT report_timing 출력   -> 경로 순서와 핀/넷 연결을 여기서 읽는다
    net_attr.txt   PT 넷 attribute 덤프    -> crosstalk delta, aggressor, coupling cap
    pin_attr.txt   PT 핀 attribute 덤프    -> arrival window, slew

출력
    crosstalk.tsv  한 줄 = 경로의 한 구간(arc). 탭 구분.

왜 두 파일을 합쳐야 하나
    attribute 덤프에는 '어느 경로의 넷인지' 정보가 없다 (넷/핀 단위로만 나온다).
    반대로 timing.rpt 에는 crosstalk 값이 없다.
    이 단계가 리포트에서 경로->핀->넷 순서를 뽑아 attribute 를 이름으로 붙인다.
"""
import argparse
import csv
import os
import re
import sys

START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
END_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
GROUP_RE = re.compile(r"^\s*Path Group:\s+(.+?)\s*$")
TYPE_RE = re.compile(r"^\s*Path Type:\s+(.+?)\s*$")
SLACK_RE = re.compile(r"^\s*slack\s*\(([^)]+)\)\s+(-?[\d.]+)")
OBJ_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")
EDGE_RE = re.compile(r"\s([rf])\s*$")

NULL = ("", "-", "N/A", "n/a", "NULL", "null", "{}", "UNINIT")

# 넷에서 뽑을 것 / 핀에서 뽑을 것. 없으면 빈 칸으로 남는다(에러 아님).
NET_ATTRS = [
    "annotated_delay_delta_max", "annotated_delay_delta_min",
    "number_of_aggressors", "number_of_effective_aggressors",
    "total_coupling_capacitance", "total_effective_coupling_capacitance",
    "effective_aggressors", "si_xtalk_bumps",
    "net_resistance_max", "total_capacitance",
]
PIN_ATTRS = [
    "pin_capacitance_max",
    "min_rise_arrival", "max_rise_arrival",
    "min_fall_arrival", "max_fall_arrival",
    "actual_rise_transition_max", "actual_fall_transition_max",
]


def load_attr_dump(path, wanted):
    """report_attribute 출력 -> {객체이름: {attr: 값}}.

    PT 는 이름 길이에 따라 줄을 접는다. 세 형태를 모두 처리한다
    (2_annotate.py 의 load_pin_caps 와 같은 규칙).
    """
    table = {}
    seen = set()
    last_obj = None
    awaiting = None
    want = set(wanted)
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
                obj, attr = awaiting
                v = parts[0]
                if v not in NULL:
                    table.setdefault(obj, {})[attr] = v
                    seen.add(attr)
                awaiting = None
                continue
            if not raw[:1].isspace() and len(parts) >= 2:
                last_obj = parts[1]
            hit = None
            for a in parts:
                if a in want:
                    hit = a
                    break
            if hit is None or last_obj is None:
                continue
            i = parts.index(hit)
            if i + 1 < len(parts):
                v = " ".join(parts[i + 1:])
                if v not in NULL:
                    table.setdefault(last_obj, {})[hit] = v
                    seen.add(hit)
            else:
                awaiting = (last_obj, hit)
    return table, seen


def iter_arcs(rpt):
    """리포트를 훑어 (경로번호, 경로정보, 구간번호, 핀, 셀, 엣지, 넷) 을 내놓는다.

    한 구간 = '핀 줄 + 바로 뒤의 (net) 줄'. 신호가 그 핀을 지나 그 넷으로 나간다.
    """
    path_idx = 0
    meta = None
    pending = None
    arc_idx = 0
    with open(rpt, "r", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = START_RE.match(line)
            if m:
                path_idx += 1
                arc_idx = 0
                pending = None
                meta = {"startpoint": m.group(1), "endpoint": "",
                        "path_group": "", "path_type": "",
                        "slack": "", "slack_status": ""}
                continue
            if meta is None:
                continue
            m = END_RE.match(line)
            if m:
                meta["endpoint"] = m.group(1)
                continue
            m = GROUP_RE.match(line)
            if m:
                meta["path_group"] = m.group(1)
                continue
            m = TYPE_RE.match(line)
            if m:
                meta["path_type"] = m.group(1)
                continue
            m = SLACK_RE.match(line)
            if m:
                meta["slack_status"] = m.group(1)
                meta["slack"] = m.group(2)
                if pending:
                    yield (path_idx, meta) + pending + ("",)
                    pending = None
                continue
            m = OBJ_RE.match(line)
            if not m:
                continue
            name, kind = m.group(1), m.group(2)
            if kind.lower() == "net":
                if pending:
                    yield (path_idx, meta) + pending + (name,)
                    pending = None
                continue
            if pending:
                yield (path_idx, meta) + pending + ("",)
            arc_idx += 1
            e = EDGE_RE.search(line)
            pending = (arc_idx, name, kind, e.group(1) if e else "")
    if pending and meta is not None:
        yield (path_idx, meta) + pending + ("",)



# ---- 결과 코드 -------------------------------------------------------
# 마지막에 "무슨 문제인지 + 어떻게 하면 되는지 + 코드" 를 함께 찍는다.
# 현장에서 화면을 복사하기 어려우므로, 읽고 바로 이해할 수 있어야 하고
# 코드는 원격으로 물어볼 때 쓴다. 코드 목록은 코드표.md 에 있다.
CODE_INFO = {
    # 코드            (한 줄 설명,                          무엇을 하면 되는지)
    "E-NORPT":    ("리포트 파일(.rpt)을 못 찾았습니다",
                   "--dir 로 준 폴더에 코너별 report_timing 결과를 넣어 주세요."),
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
    "E-NETNAME":  ("리포트의 넷 이름이 속성 덤프와 하나도 안 맞습니다",
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
    "W-CPIN":     ("Cpin 이 비어 있는 줄이 많습니다",
                   "지금 리포트로 dump_attr.tcl 을 다시 돌려 보세요."),
    "W-RES":      ("Dist/Res 가 비어 있는 줄이 많습니다",
                   "9_diagnose.py 를 돌리면 원인을 A/B/C 로 나눠 줍니다."),
    "W-NA":       ("결과에 N/A 가 남아 있습니다",
                   "9_diagnose.py 를 돌리면 원인을 알려줍니다."),
    "W-XT0":      ("crosstalk 값이 전부 0 입니다",
                   "PT 에서 si_enable_analysis 가 true 인지, SPEF 에 coupling 이 "
                   "있는지 확인해 주세요."),
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
    if c.startswith("E-"):
        sys.exit(1)


def die(msg, *hints):
    print("")
    print("[ 실패 ] " + msg)
    for h in hints:
        print("         " + h)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="crosstalk / timing window 표를 만든다.")
    ap.add_argument("--dir", default=".", help="입력/출력 폴더")
    ap.add_argument("--rpt", default=None)
    ap.add_argument("--net-attr", default=None)
    ap.add_argument("--pin-attr", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--corner", default=None,
                    help="모든 줄에 붙일 코너 이름. 여러 코너를 나중에 합칠 때 쓴다.")
    args = ap.parse_args()

    d = args.dir
    rpt = args.rpt or os.path.join(d, "timing.rpt")
    net_attr = args.net_attr or os.path.join(d, "net_attr.txt")
    pin_attr = args.pin_attr or os.path.join(d, "pin_attr.txt")
    out = args.out or os.path.join(d, "crosstalk.tsv")

    print("=" * 68)
    print("3단계 - crosstalk / timing window 표")
    print("=" * 68)

    if not os.path.isfile(rpt):
        code("E-NOFILE", "[ 실패 ] timing.rpt 이 없습니다: %s" % rpt)
    print("  리포트   : %s" % rpt)

    net_tab, net_seen = ({}, set())
    pin_tab, pin_seen = ({}, set())
    if os.path.isfile(net_attr):
        net_tab, net_seen = load_attr_dump(net_attr, NET_ATTRS)
        print("  넷 속성  : %s  (넷 %d개)" % (net_attr, len(net_tab)))
    else:
        print("  넷 속성  : 없음 -- crosstalk 컬럼이 빕니다")
    if os.path.isfile(pin_attr):
        pin_tab, pin_seen = load_attr_dump(pin_attr, PIN_ATTRS)
        print("  핀 속성  : %s  (핀 %d개)" % (pin_attr, len(pin_tab)))
    else:
        print("  핀 속성  : 없음 -- arrival/slew 컬럼이 빕니다")

    net_cols = [a for a in NET_ATTRS if a in net_seen]
    pin_cols = [a for a in PIN_ATTRS if a in pin_seen]

    header = (["corner"] if args.corner else []) + [
        "path_idx", "startpoint", "endpoint", "path_group", "path_type",
        "slack_status", "slack", "arc_idx", "pin", "cell", "edge", "net",
    ] + ["net." + c for c in net_cols] + ["pin." + c for c in pin_cols]

    n_rows = n_paths = 0
    n_net_hit = n_net_miss = n_pin_hit = 0
    n_delta = 0
    last = 0
    outdir = os.path.dirname(os.path.abspath(out))
    if outdir and not os.path.isdir(outdir):
        os.makedirs(outdir)

    with open(out, "w") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        for path_idx, meta, arc_idx, pin, cell, edge, net in iter_arcs(rpt):
            if path_idx != last:
                n_paths += 1
                last = path_idx
            na = net_tab.get(net, {})
            pa = pin_tab.get(pin, {})
            if net:
                if na:
                    n_net_hit += 1
                else:
                    n_net_miss += 1
            if pa:
                n_pin_hit += 1
            v = na.get("annotated_delay_delta_max", "")
            try:
                if v and float(v) != 0:
                    n_delta += 1
            except ValueError:
                pass
            row = ([args.corner] if args.corner else []) + [
                path_idx, meta["startpoint"], meta["endpoint"],
                meta["path_group"], meta["path_type"],
                meta["slack_status"], meta["slack"],
                arc_idx, pin, cell, edge, net,
            ] + [na.get(c, "") for c in net_cols] + [pa.get(c, "") for c in pin_cols]
            w.writerow(row)
            n_rows += 1

    print("")
    print("-" * 68)
    print("  결과 파일   : %s" % out)
    print("  경로        : %d" % n_paths)
    print("  줄(구간)    : %d" % n_rows)
    print("  컬럼        : 기본 %d + 넷 %d + 핀 %d"
          % (len(header) - len(net_cols) - len(pin_cols), len(net_cols), len(pin_cols)))
    print("  넷 속성 매칭: %d  (못 찾음 %d)" % (n_net_hit, n_net_miss))
    print("  핀 속성 매칭: %d" % n_pin_hit)
    print("  crosstalk 값이 0 이 아닌 줄: %d" % n_delta)
    print("-" * 68)

    if n_rows == 0:
        code("E-NOROW",
             "[ 실패 ] 줄이 하나도 없습니다.",
             "         timing.rpt 이 report_timing 출력이 맞는지 확인하세요.")
    if net_tab and n_net_hit == 0:
        code("E-NETNAME",
             "[ 실패 ] 넷 속성이 하나도 안 붙었습니다.",
             "         리포트의 넷 이름과 net_attr.txt 의 표기가 다릅니다.")
    if net_tab and n_delta == 0:
        code("W-XT0",
             "[ 주의 ] crosstalk 값이 전부 0 입니다.",
             "         SI 가 꺼졌거나 SPEF 에 coupling 이 없습니다.")
    else:
        code("OK-XTALK",
             "[ 정상 ] %d줄 %d열. 결과: crosstalk.tsv" % (n_rows, len(header)))


if __name__ == "__main__":
    main()
