#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2b - Dist / Res 표를 만든다.

    python3 2b_distres.py --dir ./work

입력   timing.rpt     어느 넷의 어느 구간인지
       design.spef    좌표와 저항
출력   distres.tsv    line_no / net / dist / res

이 단계만 SPEF 를 읽는다. SPEF 가 크면 수십 초 걸린다.

Dist / Res 가 뭔가:
    Dist  드라이버 핀과 리시버 핀의 맨해튼 거리. SPEF 의 좌표(*C)에서 계산.
    Res   그 두 핀 사이 배선 저항. SPEF 의 *RES 를 그물로 보고 최단경로 합.
    둘 다 PT 리포트에는 없는 값이라 SPEF 에서 직접 계산한다.

넷 이름이 리포트와 SPEF 에서 다를 수 있어, 이름 변형 5단계 + 핀 연결(CONN)
기반 매칭까지 시도한다. 그래도 못 찾으면 그 줄은 N/A 로 남고,
9_diagnose.py 가 원인을 분류해 준다.
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


def fmt(v, nd=12):
    """소수점 6자리로 반올림하고 뒤쪽 0 은 제거한다 (지수 표기 없음).

    단위:  Dist = um (SPEF 좌표),  Res = ohm (SPEF *R_UNIT)
    report_timing -significant_digits 6 과 자릿수를 맞춘다. 자릿수를 4로 두면
    Res 의 34%가 유효숫자 2자리 이하로 뭉개지고 일부는 0 으로 찍힌다.
      0.0000403769 -> 0.00004     (4자리로는 0.0000 이라 0 과 구분 불가)
      72.157       -> 72.157
    """
    if v is None:
        return ""
    s = "%.*f" % (nd, float(v))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def net_lines(rpt):
    """{줄번호: 넷이름} -- 리포트의 '(net)' 줄 위치."""
    out = {}
    with io.open(rpt, "r", errors="ignore") as f:
        for idx, line in enumerate(f):
            m = OBJ_RE.match(line)
            if m and m.group(2).lower() == "net":
                out[idx] = m.group(1)
    return out



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
    ap = argparse.ArgumentParser(description="Dist/Res 표를 만든다 (SPEF 사용).")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--rpt", default=None)
    ap.add_argument("--spef", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d = args.dir
    rpt, _err, _ec = find_rpt(d, args.rpt)   # 폴더 안의 .rpt 를 찾는다(이름 자유)
    if _err:
        print("")
        code(_ec, "[ 실패 ] " + _err)
    spef = args.spef or os.path.join(d, "design.spef")
    out = args.out or os.path.join(d, "distres.tsv")

    print("=" * 68)
    print("2b - Dist / Res 표  (SPEF 를 읽습니다)")
    print("=" * 68)

    for label, p in (("timing.rpt", rpt), ("SPEF", spef)):
        if not os.path.isfile(p):
            print("")
            code("E-NOFILE", "[ 실패 ] %s 이 없습니다: %s" % (label, p))
    print("  리포트 : %s" % rpt)
    print("  SPEF   : %s  (%.0fMB)" % (spef, os.path.getsize(spef) / 1048576.0))

    nets = net_lines(rpt)
    if not nets:
        print("")
        code("E-NONET",
             "[ 실패 ] '(net)' 줄이 없습니다.",
             "         report_timing 에 -nets -input_pins 가 빠졌습니다.")
    print("  (net) 줄: %d" % len(nets))
    print("")
    print("  SPEF 계산 중...")

    import res
    # output_path=None 이면 리포트를 쓰지 않고 계산 결과만 돌려준다.
    # 결과 키는 리포트 줄 번호, 값은 (Res, Dist, Cpin). 여기서는 Cpin 을 쓰지 않는다.
    results = res.annotate_timing_report(rpt, spef, None)

    n = hit_d = hit_r = 0
    with open(out, "w") as fh:
        fh.write("line_no\tnet\tdist\tres\n")
        for idx in sorted(nets):
            r_path, dist, _cpin = results.get(idx, (None, None, None))
            sd = fmt(dist)
            sr = fmt(r_path)
            if sd:
                hit_d += 1
            if sr:
                hit_r += 1
            n += 1
            fh.write("%d\t%s\t%s\t%s\n" % (idx, nets[idx], sd, sr))

    print("")
    print("-" * 68)
    print("  결과 파일 : %s" % out)
    print("  (net) 줄  : %d" % n)
    print("  Dist 있음 : %d   (없음 %d)" % (hit_d, n - hit_d))
    print("  Res  있음 : %d   (없음 %d)" % (hit_r, n - hit_r))
    print("-" * 68)

    if hit_r == 0:
        code("E-RES0",
             "[ 실패 ] Res 를 하나도 못 구했습니다.",
             "         SPEF 가 이 리포트와 같은 디자인/코너가 아닐 수 있습니다.")
    if hit_r < n * 0.9:
        code("W-RES",
             "[ 주의 ] Res 가 %d개 비었습니다 (%.0f%%)."
             % (n - hit_r, 100.0 * (n - hit_r) / n),
             "         원인:  $PY 9_diagnose.py --dir %s" % d)
    else:
        code("OK-DISTRES",
             "[ 정상 ] Dist/Res %d/%d." % (hit_r, n),
             "         다음 단계:  $PY 2c_merge.py --dir %s" % d)


if __name__ == "__main__":
    main()
