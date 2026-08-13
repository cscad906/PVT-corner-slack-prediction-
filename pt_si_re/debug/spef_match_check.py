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
    # 문턱값은 실측으로 잡았다. 한 자리에서 재 보면 값이 두 무리로 갈린다.
    #   맞는 SPEF  : 48%   (BoomCoreV3 의 Cmax/Cmin/Cnom x 25C/125C 여섯 개
    #                      모두 정확히 같은 값이 나온다)
    #   딴 SPEF    :  0%   (NAME_MAP 을 다른 디자인 것으로 바꿔 재 봄)
    # 그 사이는 사실상 안 나온다. 그래서 "30% 넘으면 맞는 것" 으로 본다.
    #
    # 맞는 SPEF 인데도 절반뿐인 이유는, 리포트의 계층 이름을 SPEF 가 평탄화해
    # 적기 때문이다(a/b/c -> a/b_c). 나머지는 2b 가 이름 변형과 CONN 으로
    # 찾아낸다. 즉 절반쯤 못 찾는 것이 이 흐름의 정상이다.
    if pct >= 30:
        print("  OK -- this SPEF belongs to this report.")
        print("      Half the names not matching directly is normal here:")
        print("      the report keeps the hierarchy (a/b/c) while the SPEF")
        print("      flattens it (a/b_c). 2b finds the rest by name variants")
        print("      and by connection.")
        print("      A correct SPEF measures about 48% on this design, and a")
        print("      wrong one measures 0%. So this is fine -- if 2b is slow,")
        print("      it is the size and the fallback, not the wrong file.")
    elif pct > 0:
        print("  ODD. Some names line up but far fewer than expected")
        print("      (a correct SPEF measures about 48% here, a wrong one 0%).")
        print("      Check that the design and the extraction run match.")
    else:
        print("  MISMATCH. Nothing lines up. This SPEF is for another design")
        print("      or another extraction. 2b will run for a long time and")
        print("      still end with E-RES0.")
        print("      Stop it and pick the right SPEF:")
        print("        python3 _engine/spef_match.py --spef-dir <folder> --dir <root>")
    print("")
    print("  report net examples : %s" % ", ".join(nets[:3]))
    print("  SPEF name examples  : %s" % ", ".join(sorted(names)[:3]))
    print("=" * 66)


if __name__ == "__main__":
    main()
