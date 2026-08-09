#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1단계 - 타이밍 리포트에 Dist / Res / Cpin 을 붙인다.

    python3 2_annotate.py --dir ./work

입력 (--dir 폴더 안)
    timing.rpt     PT report_timing 출력
    design.spef    SPEF          (--spef 로 다른 경로 지정 가능)
    pin_attr.txt   PT 핀 attribute 덤프   -> Cpin 을 여기서 읽는다
                   (Liberty 가 있으면 --lib 로 대신 줄 수도 있다)

출력
    annotated.txt  timing.rpt 의 '(net)' 줄 끝에 3개 컬럼이 붙은 파일

각 컬럼의 출처
    Dist  SPEF 의 좌표     드라이버-리시버 맨해튼 거리
    Res   SPEF 의 *RES     그 구간 배선 저항 (RC 그물의 최단경로 합)
    Cpin  PT 핀 attribute  리시버 핀의 입력 capacitance

PT 는 이 세 값을 리포트에 찍어주지 않는다. 그래서 SPEF 와 attribute 덤프에서
읽어다 붙이는 것이 이 단계의 전부다.
"""
from __future__ import division, print_function
import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from find_rpt import find_rpt
from names import annotated_path

ATTR_NAME = "pin_capacitance_max"


def load_pin_caps(path, attr=ATTR_NAME):
    """report_attribute 덤프에서 {핀이름: capacitance} 를 만든다.

    PT 출력은 인스턴스 이름 길이에 따라 세 가지 모양으로 나온다. 한 가지만
    처리하면 일부(우리 3nm 데이터에서 약 7%)를 조용히 놓치므로 전부 받는다.

      (A) <design> <pin> float <attr> <value>       한 줄
      (B) <design> <pin>                            객체 이름이 접힘
                  float <attr> <value>
      (C)         float <attr>                      값이 접힘
                              <value>
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
                # PT 출력 문자열을 그대로 보관한다(뒤쪽 0 까지 보존).
                caps[last_obj] = parts[i + 1]
            else:
                awaiting = last_obj
    return caps


def die(msg, *hints):
    print("")
    print("[ 실패 ] " + msg)
    for h in hints:
        print("         " + h)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(
        description="타이밍 리포트에 Dist/Res/Cpin 을 붙인다.")
    ap.add_argument("--dir", default=".", help="입력/출력 폴더")
    ap.add_argument("--rpt", default=None, help="timing.rpt 경로를 직접 줄 때")
    ap.add_argument("--spef", default=None, help="SPEF 경로를 직접 줄 때")
    ap.add_argument("--pin-attr", default=None, help="핀 attribute 덤프 경로")
    ap.add_argument("--lib", default=None,
                    help="Liberty(.lib). 있으면 Cpin 을 여기서 읽는다. "
                         "없으면 pin_attr.txt 를 쓴다.")
    ap.add_argument("--out", default=None, help="출력 경로")
    args = ap.parse_args()

    d = args.dir
    rpt, _err, _ec = find_rpt(d, args.rpt)   # 폴더 안의 .rpt 를 찾는다(이름 자유)
    if _err:
        die(_err, "2회차(fixed_paths.tcl)를 먼저 돌리세요.")
    spef = args.spef or os.path.join(d, "design.spef")
    pin_attr = args.pin_attr or os.path.join(d, "pin_attr.txt")
    out = args.out or annotated_path(d)

    print("=" * 68)
    print("2단계 - annotation (Dist / Res / Cpin)")
    print("=" * 68)

    for label, p in (("timing.rpt", rpt), ("SPEF", spef)):
        if not os.path.isfile(p):
            die("%s 파일이 없습니다: %s" % (label, p),
                "0_check.py 를 먼저 돌려 무엇이 없는지 확인하세요.")
    print("  리포트 : %s" % rpt)
    print("  SPEF   : %s" % spef)

    # (net) 줄이 없으면 붙일 자리가 없다. report_timing 옵션 누락을 여기서 잡는다.
    with io.open(rpt, "r", errors="ignore") as f:
        if not any("(net)" in line for line in f):
            die("timing.rpt 에 '(net)' 줄이 없습니다.",
                "report_timing 을 아래 옵션으로 다시 뽑아야 합니다:",
                "  -nets -input_pins -capacitance -transition_time",
                "  -path_type full_clock_expanded -nosplit")

    pin_caps = {}
    if args.lib:
        if not os.path.isfile(args.lib):
            die("Liberty 파일이 없습니다: %s" % args.lib)
        print("  Cpin   : Liberty 에서 (%s)" % args.lib)
    elif os.path.isfile(pin_attr):
        pin_caps = load_pin_caps(pin_attr)
        if not pin_caps:
            die("pin_attr.txt 에서 %s 를 하나도 못 읽었습니다." % ATTR_NAME,
                "pt_shell 에서 아래로 다시 뽑아야 합니다:",
                "  redirect -file pin_attr.txt "
                "{ report_attribute -application [get_pins *] }")
        print("  Cpin   : PT attribute 에서 (핀 %d개)" % len(pin_caps))
    else:
        print("  Cpin   : 없음 -- pin_attr.txt 도 --lib 도 없어 Cpin 컬럼이 빕니다")

    print("")
    print("  계산 중... (SPEF 가 크면 수십 초 걸립니다)")
    import res
    res.annotate_timing_report(rpt, spef, out,
                               lib_path=args.lib,
                               pin_cap_map=pin_caps)

    # ---- 자가 점검 -------------------------------------------------
    n_net = n_ok = n_na = n_cpin = 0
    with io.open(out, "r", errors="ignore") as f:
        for line in f:
            if "(net)" not in line:
                continue
            n_net += 1
            tail = line.rstrip("\n").split()[-3:]
            if len(tail) != 3:
                continue
            if any("N/A" in t for t in tail):
                n_na += 1
            else:
                n_ok += 1
            try:
                if float(tail[-1]) != 0:
                    n_cpin += 1
            except ValueError:
                pass

    print("")
    print("-" * 68)
    print("  결과 파일 : %s" % out)
    print("  (net) 줄  : %d" % n_net)
    print("  값이 붙음 : %d" % n_ok)
    print("  N/A       : %d" % n_na)
    print("  Cpin 있음 : %d" % n_cpin)
    print("-" * 68)

    if n_net == 0:
        die("(net) 줄이 하나도 없습니다.")
    na_ratio = float(n_na) / n_net
    if na_ratio > 0.1:
        print("[ 주의 ] N/A 가 %.0f%% 입니다." % (na_ratio * 100))
        print("         SPEF 의 넷/인스턴스 이름 표기가 리포트와 다를 때 이렇게 됩니다.")
        print("         3_collect_debug.sh 를 돌려 나온 파일을 가지고 오세요.")
    elif n_cpin == 0 and (pin_caps or args.lib):
        print("[ 주의 ] Cpin 이 전부 비었습니다.")
        print("         pin_attr.txt 의 핀 이름이 리포트의 핀 이름과 다를 수 있습니다.")
    else:
        print("[ 정상 ] 다음 단계로 넘어가세요:")
        print("         $PY 3_crosstalk.py --dir %s" % d)
    print("")


if __name__ == "__main__":
    main()
