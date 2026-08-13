#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SPEF 가 이 리포트와 맞는 것인지 10초 안에 판정한다.

    python3 debug/spef_match_check.py <코너>.rpt <design.spef>

무엇을 왜 하나
    2b 가 오래 걸릴 때, 원래 느린 것인지 SPEF 가 안 맞아 헤매는 것인지
    구분이 안 된다. 안 맞으면 몇 시간을 돌고도 결국 E-RES0 로 끝난다.

    이 검사는 리포트의 넷 이름 몇 개를 뽑아, SPEF 의 *NAME_MAP 에 그 이름이
    있는지만 본다. SPEF 앞부분(NAME_MAP)만 읽으므로 파일이 몇 GB 든 몇 초다.
"""
import os
import re
import sys

NET_RE = re.compile(r"^\s{2,}(\S+)\s+\(net\)")
SAMPLE = 300


def report_nets(path):
    out = []
    with open(path, "r", errors="ignore") as f:
        for line in f:
            m = NET_RE.match(line)
            if m:
                out.append(m.group(1))
                if len(out) >= SAMPLE:
                    break
    return out


def spef_names(path):
    """*NAME_MAP 구간만 읽는다. 거기가 끝나면 바로 멈춘다."""
    names = set()
    started = False
    with open(path, "r", errors="ignore") as f:
        for line in f:
            if line.startswith("*NAME_MAP"):
                started = True
                continue
            if not started:
                continue
            if line.startswith("*PORTS") or line.startswith("*D_NET"):
                break
            p = line.split()
            if len(p) >= 2 and p[0].startswith("*"):
                names.add(p[1])
    return names


def main():
    if len(sys.argv) < 3:
        print("usage: python3 debug/spef_match_check.py <report.rpt> <design.spef>")
        sys.exit(1)
    rpt, spef = sys.argv[1], sys.argv[2]
    for p in (rpt, spef):
        if not os.path.isfile(p):
            print("not found: %s" % p)
            sys.exit(1)

    nets = report_nets(rpt)
    if not nets:
        print("The report has no '(net)' line -- report_timing needs -nets.")
        sys.exit(1)
    names = spef_names(spef)

    hit = sum(1 for n in nets if n in names)
    pct = 100.0 * hit / len(nets)

    print("=" * 66)
    print("does this SPEF belong to this report?")
    print("=" * 66)
    print("  report : %s" % os.path.basename(rpt))
    print("  spef   : %s   (%.0f MB)"
          % (os.path.basename(spef), os.path.getsize(spef) / 1048576.0))
    print("  checked %d net names from the report against the SPEF NAME_MAP"
          % len(nets))
    print("  NAME_MAP holds %d names" % len(names))
    print("")
    print("  found in the SPEF : %d / %d   (%.0f%%)" % (hit, len(nets), pct))
    print("")
    # 이 숫자만으로 "맞다" 고 단정하면 안 된다. 실측에서 이름이 48% 맞는
    # SPEF 로 2b 를 끝까지 돌렸더니 Res 가 8930개 중 0개였다. 같은 디자인의
    # 다른 추출본이면 상위 계층 이름은 그대로이고 CTS 넷 이름만 달라지는데,
    # 2b 가 필요로 하는 것이 주로 그쪽이기 때문이다.
    #
    # 그래서 이 검사는 **아니라는 것만** 확실히 말한다.
    #   0%   -> 확실히 다른 SPEF. 더 볼 것 없이 끊는다.
    #   그 외 -> 아직 모른다. 2b 를 끝까지 돌려 'Res 있음' 을 봐야 안다.
    if pct == 0:
        print("  DEFINITELY WRONG. Not one name lines up. Stop 2b now -- it")
        print("      will grind for a long time and still end at E-RES0.")
        print("      Pick the SPEF for this corner:")
        print("        python3 _engine/spef_match.py --spef-dir <folder> --dir <root>")
    else:
        print("  NOT DECIDED. A high percentage here does NOT prove the SPEF")
        print("      is the right one. Measured on this design: names matched")
        print("      48% and the finished 2b run still produced Res for 0 of")
        print("      8930 nets. Two extractions of the same design share the")
        print("      upper hierarchy but differ in the clock-tree net names,")
        print("      and those are most of what 2b needs.")
        print("")
        print("      What decides it is the end of the 2b run:")
        print("          Res  있음 : <n>   (없음 <m>)")
        print("      If it says 0, the SPEF is wrong no matter how good this")
        print("      percentage looked.")
    print("")
    print("  report net examples : %s" % ", ".join(nets[:3]))
    print("  SPEF name examples  : %s" % ", ".join(sorted(names)[:3]))
    print("=" * 66)


if __name__ == "__main__":
    main()
