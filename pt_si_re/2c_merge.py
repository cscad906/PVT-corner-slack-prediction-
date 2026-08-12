#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1c - 앞의 두 표를 리포트에 붙여 annotated.txt 를 만든다.

    python3 2c_merge.py --dir ./work

입력   timing.rpt    원본 리포트
       cpin.tsv      1a 결과
       distres.tsv   1b 결과
출력   <코너>_fixed_annotated.txt   '(net)' 줄 끝에 Dist / Res / Cpin 3열이 붙은 리포트

N/A 가 남으면 **원인 진단(9_diagnose.py)이 자동으로 이어 붙는다.** 명령을 한 번
더 칠 필요가 없다. --spef 를 같이 주면 SPEF 쪽 원인(A/B/C)까지 보고, 안 주면
Cpin 쪽(원인 D)만 본다. --no-diagnose 로 끌 수 있다.
       (기존 운영 산출물과 같은 이름 규약. 코너 이름은 폴더 이름을 쓴다)

계산은 하지 않는다. 줄 번호로 값을 찾아 붙이기만 하므로 즉시 끝난다.
둘 중 하나가 없어도 있는 것만 붙인다(없는 열은 N/A).
"""
import argparse
import os
import subprocess
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8, wopen
force_utf8()
from find_rpt import find_rpt
from names import annotated_path, find_annotated

OBJ_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")

# annotated.txt 의 숫자 자릿수. 기존 산출물과 **형식이 같아야 하므로** 소수점 4자리
# 고정이다. 중간 파일(cpin.tsv, distres.tsv)에는 더 정밀한 값이 그대로 남아 있으므로,
# 정밀도가 필요하면 그쪽을 쓰면 된다.
DECIMALS = 4


def fmt4(v):
    """문자열로 들어온 값을 기존 형식(소수점 4자리)으로 맞춘다."""
    if not v:
        return ""
    try:
        return "%.*f" % (DECIMALS, float(v))
    except ValueError:
        return v
# '(net) <fanout> <cap>' 로 끝나는 줄. 이 형태면 빈 칸을 맞춰 넣어 표를 정렬한다.
NET_ROW_RE = re.compile(
    r'^(?P<prefix>.*\(net\)\s+\d+\s+[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$')


def load_tsv(path, cols):
    """{line_no: (값들)} 로 읽는다. 파일이 없으면 빈 dict."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, "r", errors="ignore") as f:
        head = f.readline().rstrip("\n").split("\t")
        try:
            idx_i = head.index("line_no")
            take = [head.index(c) for c in cols]
        except ValueError:
            return out
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) <= max([idx_i] + take):
                continue
            try:
                out[int(p[idx_i])] = tuple(p[i] for i in take)
            except ValueError:
                continue
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
    "W-CPIN":     ("Cpin 이 비어 있는 줄이 많습니다",
                   "지금 리포트로 dump_attr.tcl 을 다시 돌려 보세요."),
    "W-RES":      ("Dist/Res 가 비어 있는 줄이 많습니다",
                   "위에 붙은 [원인 A/B/C] 줄을 보세요. SPEF 쪽 문제입니다."),
    "W-NA":       ("결과에 N/A 가 남아 있습니다",
                   "위에 붙은 [원인 X] 줄을 보세요. 원인별 조치가 같이 적혀 "
                   "있습니다. (진단은 자동으로 돌아갑니다)"),
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
    ap = argparse.ArgumentParser(description="Dist/Res/Cpin 을 리포트에 붙인다.")
    ap.add_argument("--dir", default=".",
                    help="**코너 폴더 하나** (그 안에 .rpt 가 있는 폴더). 여러 코너를 한 번에 하려면 4_all_corners.py --root")
    ap.add_argument("--rpt", default=None)
    ap.add_argument("--cpin", default=None)
    ap.add_argument("--distres", default=None)
    ap.add_argument("--corner", default=None,
                    help="결과 파일 이름에 쓸 코너 이름. 안 주면 폴더 이름")
    ap.add_argument("--out", default=None)
    ap.add_argument("--spef", default=None,
                    help="N/A 가 나면 이 SPEF 로 원인까지 진단한다. 없으면 "
                         "Cpin 쪽(원인 D)만 본다")
    ap.add_argument("--no-diagnose", action="store_true",
                    help="N/A 가 나도 원인 진단을 돌리지 않는다")
    args = ap.parse_args()

    d = args.dir
    rpt, _err, _ec = find_rpt(d, args.rpt)   # 폴더 안의 .rpt 를 찾는다(이름 자유)
    if _err:
        print("")
        code(_ec, "[ 실패 ] " + _err)
    cpin_f = args.cpin or os.path.join(d, "cpin.tsv")
    dr_f = args.distres or os.path.join(d, "distres.tsv")
    out = args.out or annotated_path(d, args.corner)

    print("=" * 68)
    print("2c - 합치기")
    print("=" * 68)

    if not os.path.isfile(rpt):
        print("")
        code("E-NOFILE", "[ 실패 ] timing.rpt 이 없습니다: %s" % rpt)

    cpin = load_tsv(cpin_f, ["cpin"])
    dr = load_tsv(dr_f, ["dist", "res"])
    print("  리포트   : %s" % rpt)
    print("  cpin.tsv : %s" % ("%d줄" % len(cpin) if cpin else "없음 -> Cpin 은 N/A"))
    print("  distres  : %s" % ("%d줄" % len(dr) if dr else "없음 -> Dist/Res 는 N/A"))

    if not cpin and not dr:
        print("")
        code("E-NOINPUT",
             "[ 실패 ] 붙일 값이 하나도 없습니다.",
             "         2a_cpin.py / 2b_distres.py 를 먼저 돌리세요.")

    with open(rpt, "r", errors="ignore") as f:
        lines = f.read().split("\n")

    header_len = 80
    n_net = n_full = 0
    outlines = []
    for idx, line in enumerate(lines):
        clean = line.rstrip("\r")

        # 표 헤더와 점선을 늘려 3열 자리를 만든다
        if "Point" in clean and "Path" in clean and "(" not in clean:
            header_len = len(clean)
            outlines.append(clean + "       Dist        Res       Cpin")
            continue
        if clean.strip() and set(clean.strip()) == set("-"):
            outlines.append(clean + "---------------------------------")
            continue

        m = OBJ_RE.match(clean)
        is_net = bool(m and m.group(2).lower() == "net")
        if not is_net:
            outlines.append(clean)
            continue

        n_net += 1
        sd, sr = dr.get(idx, ("", ""))
        (sc,) = cpin.get(idx, ("",))
        sd = fmt4(sd) or "N/A"
        sr = fmt4(sr) or "N/A"
        sc = fmt4(sc) or "N/A"
        if "N/A" not in (sd, sr, sc):
            n_full += 1

        m_net = NET_ROW_RE.match(clean)
        if m_net:
            outlines.append("%s %10s %10s %10s %10s %10s %10s"
                            % (m_net.group("prefix"), "", "", "", sd, sr, sc))
        else:
            outlines.append("%s %10s %10s %10s" % (clean.ljust(header_len), sd, sr, sc))

    with wopen(out) as f:
        f.write("\n".join(outlines))

    print("")
    print("-" * 68)
    print("  결과 파일  : %s" % out)
    print("  (net) 줄   : %d" % n_net)
    print("  3열 다 있음: %d" % n_full)
    print("  일부 N/A   : %d" % (n_net - n_full))
    print("-" * 68)
    if n_full == n_net:
        code("OK-MERGE",
             "[ 정상 ] 3열 %d/%d. 다음:  %s 5a_contexts.py --dir %s"
             % (n_full, n_net, sys.executable, d))
    else:
        # N/A 가 나면 **여기서 바로 원인까지** 본다. 예전에는 화면에
        # "9_diagnose.py 를 돌려 보세요" 라고만 하고 끝냈는데, 현장에서
        # 명령을 한 번 더 치는 것 자체가 부담이라 자동으로 이어 붙였다.
        # (SPEF 를 한 번 훑으므로 N/A 가 있을 때만 돈다)
        if not args.no_diagnose:
            print("")
            print("-" * 68)
            print("  N/A 가 있어 원인을 진단합니다 (9_diagnose.py)")
            print("-" * 68)
            cmd = [sys.executable, os.path.join(HERE, "9_diagnose.py"), "--dir", d]
            if args.spef:
                cmd += ["--spef", args.spef]
            try:
                pr = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT)
                out = pr.communicate()[0].decode("utf-8", "replace")
                # 진단기의 머리말은 빼고 본문만 이어 붙인다
                for ln in out.splitlines():
                    if ln.startswith("=") or ln.startswith("9 - "):
                        continue
                    print("  " + ln)
            except Exception as e:
                print("  (진단을 돌리지 못했습니다: %s)" % e)
                print("  직접:  %s 9_diagnose.py --dir %s" % (sys.executable, d))
        code("W-NA",
             "[ 주의 ] N/A 가 %d개 있습니다 (전체 %d)." % (n_net - n_full, n_net),
             "         위 [원인 X] 줄을 보세요.")


if __name__ == "__main__":
    main()
