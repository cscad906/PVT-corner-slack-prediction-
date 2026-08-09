#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2a - Cpin (리시버 핀 capacitance) 표를 만든다.

    python3 2a_cpin.py --dir ./work

입력   timing.rpt     어느 넷을 누가 받는지
       pin_attr.txt   PT 핀 attribute 덤프
출력   cpin.tsv       line_no / net / recv_pin / cpin

이 단계는 **SPEF 를 읽지 않는다.** 그래서 몇 초면 끝나고, SPEF 에 문제가 있어도
Cpin 은 정상적으로 나온다. 핀 이름이 안 맞는 문제를 여기서 먼저 걸러낸다.

Cpin 이 뭔가:
    리포트의 '(net)' 줄 바로 다음에 오는 핀이 그 넷의 리시버다. 그 핀의 입력
    capacitance 가 Cpin 이다. PT 는 리포트에 이 값을 찍어주지 않으므로
    report_attribute 로 따로 뽑아 이름으로 붙인다.
"""
from __future__ import division, print_function
import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from find_rpt import find_rpt

OBJ_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")
ATTR = "pin_capacitance_max"


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
    with io.open(path, "r", errors="ignore") as f:
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
    with io.open(rpt, "r", errors="ignore") as f:
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



# ---- 결과 코드 -------------------------------------------------------
# 마지막에 "무슨 문제인지 + 어떻게 하면 되는지 + 코드" 를 함께 찍는다.
# 현장에서 화면을 복사하기 어려우므로, 읽고 바로 이해할 수 있어야 하고
# 코드는 원격으로 물어볼 때 쓴다. 코드 목록은 코드표.md 에 있다.
CODE_INFO = {
    # 코드            (한 줄 설명,                          무엇을 하면 되는지)
    "E-NORPT":    ("리포트 파일(.rpt)을 못 찾았습니다",
                   "--dir 로 준 폴더에 코너별 report_timing 결과를 넣어 주세요."),
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
    # 코드는 항상 마지막에 한 번만 나와야 한다. 경고(W-)에서 멈추지 않으면
    # 뒤이어 정상(OK-)까지 찍혀 어느 쪽인지 헷갈린다.
    sys.exit(1 if c.startswith("E-") else 0)


def main():
    ap = argparse.ArgumentParser(description="Cpin 표를 만든다 (SPEF 불필요).")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--rpt", default=None)
    ap.add_argument("--pin-attr", default=None)
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

    for label, p in (("timing.rpt", rpt), ("pin_attr.txt", pin_attr)):
        if not os.path.isfile(p):
            print("")
            code("E-NOFILE",
                 "[ 실패 ] %s 이 없습니다: %s" % (label, p),
                 "         0_check.py 로 무엇이 없는지 확인하세요.")
    print("  리포트    : %s" % rpt)
    print("  핀 속성   : %s" % pin_attr)

    caps = load_pin_caps(pin_attr)
    if not caps:
        print("")
        code("E-NOATTR",
             "[ 실패 ] pin_attr.txt 에서 %s 를 하나도 못 읽었습니다." % ATTR,
             "         report_attribute 에 -application 이 필요합니다.")
    print("  읽은 핀   : %d개" % len(caps))

    n = hit = 0
    miss_examples = []
    with open(out, "w") as fh:
        fh.write("line_no\tnet\trecv_pin\tcpin\n")
        for idx, net, pin in iter_net_receiver(rpt):
            v = caps.get(pin, "")
            if v:
                hit += 1
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
    if hit < n * 0.9:
        code("W-CPIN",
             "[ 주의 ] %d개는 Cpin 이 비었습니다 (전체 %d)." % (n - hit, n),
             "         예: %s" % ", ".join(miss_examples[:3]))
    else:
        code("OK-CPIN",
             "[ 정상 ] Cpin %d/%d." % (hit, n),
             "         다음 단계:  $PY 2b_distres.py --dir %s" % d)


if __name__ == "__main__":
    main()
