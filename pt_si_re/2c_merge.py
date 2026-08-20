#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1c - 앞의 두 표를 리포트에 붙여 annotated.txt 를 만든다.

    python3 2c_merge.py --dir ./work

입력   timing.rpt    원본 리포트
       cpin.tsv      1a 결과
       distres.tsv   1b 결과
출력   <코너>_fixed_annotated.txt   '(net)' 줄 끝에 Dist / Res / Cpin 3열이 붙은 리포트

N/A 가 남으면 **어느 쪽이 빈 것인지 여기서 바로 갈라 준다.**
    [Cpin]      Cpin 표에 그 핀이 없다     -> 받은 표 / get_pins 범위
    [Dist/Res]  SPEF 에서 못 찾았다        -> SPEF 짝, *RES 포함 여부
조치할 곳이 다르므로 이것만 알면 대개 끝난다. SPEF 를 다시 훑지 않아 빠르다.
SPEF 쪽을 넷 단위로 더 잘게 보고 싶을 때만 9_diagnose.py 를 따로 돌린다.
       (기존 운영 산출물과 같은 이름 규약. 코너 이름은 폴더 이름을 쓴다)

계산은 하지 않는다. 줄 번호로 값을 찾아 붙이기만 하므로 즉시 끝난다.
둘 중 하나가 없어도 있는 것만 붙인다(없는 열은 N/A).
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
                   "2a_cpin.py 와 2b_distres_table.py 를 먼저 돌려 주세요."),
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
                   "위의 [Cpin] / [Dist/Res] 줄을 보세요. 어느 쪽이 빈 것인지와 "
                   "조치가 같이 적혀 있습니다."),
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
                    help="지금은 안 쓴다(호환용). 4_all_corners 가 넘겨도 무시")
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
    # Cpin 이 빈 줄이 어떤 핀인지 알려주려고 리시버 핀 이름도 같이 읽는다.
    # (cpin.tsv 에 line_no / net / recv_pin / cpin 이 들어 있다)
    recv_pin = dict((k, v[0]) for k, v in
                    load_tsv(cpin_f, ["recv_pin"]).items())
    print("  리포트   : %s" % rpt)
    print("  cpin.tsv : %s" % ("%d줄" % len(cpin) if cpin else "없음 -> Cpin 은 N/A"))
    print("  distres  : %s" % ("%d줄" % len(dr) if dr else "없음 -> Dist/Res 는 N/A"))

    if not cpin and not dr:
        print("")
        code("E-NOINPUT",
             "[ 실패 ] 붙일 값이 하나도 없습니다.",
             "         2a_cpin.py / 2b_distres.py 를 먼저 돌리세요.")

    # 리포트를 통째로 올리지 않고 **한 줄씩 흘려 쓴다.**
    # 예전에는 lines(원본 전체) + outlines(결과 전체) 두 벌을 들고 있어서
    # 446MB 리포트에 2.4GB 를 썼다. 코너를 여러 개 동시에 돌리면 그만큼 곱해져
    # 스왑으로 넘어가고, 그러면 병렬로 돌린 의미가 없어진다.
    # 줄마다 하는 일이 앞뒤 줄과 무관해서 흘려 써도 결과는 같다.
    header_len = 80
    n_net = n_full = 0
    na_dr = na_cpin = 0     # N/A 가 SPEF 쪽인지 Cpin 쪽인지
    na_pins = []            # Cpin 이 빈 리시버 핀 예시

    with open(rpt, "r", errors="ignore") as fin, wopen(out) as fout:
        # 원본은 "\n".join(outlines) 였다 -- 줄 **사이**에만 개행이 들어가고
        # 마지막 줄 뒤에는 없다. 흘려 쓸 때도 그 형식을 그대로 지킨다.
        first = True
        ended_nl = False
        for idx, line in enumerate(fin):
            ended_nl = line.endswith("\n")
            clean = line.rstrip("\n").rstrip("\r")
            if first:
                first = False
            else:
                fout.write("\n")

            # 표 헤더와 점선을 늘려 3열 자리를 만든다
            if "Point" in clean and "Path" in clean and "(" not in clean:
                header_len = len(clean)
                fout.write(clean + "       Dist        Res       Cpin")
                continue
            if clean.strip() and set(clean.strip()) == set("-"):
                fout.write(clean + "---------------------------------")
                continue

            m = OBJ_RE.match(clean)
            is_net = bool(m and m.group(2).lower() == "net")
            if not is_net:
                fout.write(clean)
                continue

            n_net += 1
            sd, sr = dr.get(idx, ("", ""))
            (sc,) = cpin.get(idx, ("",))
            sd = fmt4(sd) or "N/A"
            sr = fmt4(sr) or "N/A"
            sc = fmt4(sc) or "N/A"
            if "N/A" not in (sd, sr, sc):
                n_full += 1
            else:
                # 어느 쪽이 빈 것인지 나눠 센다. Dist/Res 는 받은 표에서,
                # Cpin 은 Cpin 표에서 오므로 조치할 곳이 완전히 다르다.
                if sd == "N/A" or sr == "N/A":
                    na_dr += 1
                if sc == "N/A":
                    na_cpin += 1
                    if len(na_pins) < 6:
                        pin = recv_pin.get(idx)
                        if pin and pin not in na_pins:
                            na_pins.append(pin)

            m_net = NET_ROW_RE.match(clean)
            if m_net:
                fout.write("%s %10s %10s %10s %10s %10s %10s"
                           % (m_net.group("prefix"), "", "", "", sd, sr, sc))
            else:
                fout.write("%s %10s %10s %10s"
                           % (clean.ljust(header_len), sd, sr, sc))

        # 원본이 개행으로 끝났으면 예전 코드에서는 split 이 만든 마지막 빈
        # 원소 때문에 개행이 하나 더 붙었다. 그 형식을 그대로 지킨다.
        if ended_nl:
            fout.write("\n")


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
        # N/A 가 어느 쪽에서 왔는지 여기서 바로 갈라 준다. 조치할 곳이
        # 완전히 다르기 때문이다 -- Dist/Res 는 SPEF, Cpin 은 Cpin 표.
        # SPEF 를 다시 훑지 않는다(이미 있는 두 tsv 만 보면 알 수 있다).
        msg = ["[ 주의 ] N/A 가 %d개 있습니다 (전체 %d)."
               % (n_net - n_full, n_net), ""]
        if na_cpin:
            msg.append("  [Cpin] %d줄 -- 리시버 핀이 Cpin 표에 없습니다." % na_cpin)
            for pn in na_pins[:4]:
                msg.append("           예: %s" % pn)
            msg.append("         -> 받은 Cpin 표에 이 핀들이 있는지 보세요.")
            msg.append("            2a 화면의 '1열 판별' 과 'Cpin N/M' 도 함께.")
            msg.append("            get_pins 범위가 좁았거나 이름 규약이 다릅니다.")
        if na_dr:
            msg.append("  [Dist/Res] %d줄 -- SPEF 에서 못 찾았습니다." % na_dr)
            msg.append("         -> SPEF 가 이 리포트와 같은 디자인/코너인지,")
            msg.append("            저항(*RES)을 포함해 뽑았는지 보세요.")
            msg.append("            넷 단위로 더 잘게 나누려면:")
            msg.append("              %s 9_diagnose.py --dir %s"
                       % (sys.executable, d))
        code("W-NA", *msg)

if __name__ == "__main__":
    main()
