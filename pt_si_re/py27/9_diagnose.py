#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""9 - N/A 가 왜 생겼는지 원인별로 분류한다.

    python3 9_diagnose.py --dir ./work

2_annotate.py 결과에 N/A 가 있을 때 돌린다. SPEF 를 한 번 훑어 실패한 넷마다
아래 중 어디서 막혔는지 판정하고, 원인별 개수와 조치를 출력한다.

  원인 A  넷이 SPEF 에 아예 없다
          -> SPEF 파일이 그 리포트와 짝이 맞는지 확인. 클럭 넷은 SPEF 에서
             빠지는 경우가 있다.
  원인 B  넷은 SPEF 에 있는데 이름 표기가 달라 못 찾았다
          -> 이름 변형 규칙을 넓혀야 한다. 이 출력을 그대로 가져오면 된다.
  원인 C  넷도 찾았는데 저항(*RES) 정보가 없거나 경로가 끊겼다
          -> SPEF 추출 설정 문제. R 을 포함해 다시 뽑아야 한다.
  원인 D  Cpin 만 비었다 (Dist/Res 는 정상)
          -> 리포트의 핀 이름이 pin_attr.txt 에 없다. get_pins * 범위 확인.
"""
from __future__ import division, print_function
import argparse
import io
import os
import re
import sys

OBJ_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")
MAX_SHOW = 8


def read_annotated(path):
    """annotated.txt 에서 (넷이름, 다음 핀이름, dist, res, cpin) 을 뽑는다."""
    rows = []
    pending = None
    with io.open(path, "r", errors="ignore") as f:
        for line in f:
            m = OBJ_RE.match(line)
            if not m:
                continue
            name, kind = m.group(1), m.group(2)
            if kind.lower() == "net":
                t = line.rstrip().split()
                if len(t) >= 3:
                    pending = (name, t[-3], t[-2], t[-1])
                continue
            if pending:
                net, d, r, c = pending
                rows.append((net, name, d, r, c))
                pending = None
    return rows


def normalize(n):
    """SPEF 쪽 표기 차이를 흡수한 대략적인 비교용 키."""
    n = n.replace("\\", "")
    n = re.sub(r"[\[\]]", "_", n)
    return n


def scan_spef(spef, want):
    """SPEF 를 1회 훑어 각 넷의 존재/RES 유무를 본다.

    want: 찾고 싶은 넷 이름 집합(정규화 키). NAME_MAP 의 이름과 D_NET 이름 모두 본다.
    """
    found_namemap = set()
    has_res = set()
    all_names = {}          # 정규화키 -> 원래 표기 (이름은 있는데 표기가 다른 경우 찾기용)
    cur = None
    in_res = False
    n_dnet = 0

    with io.open(spef, "r", errors="ignore") as f:
        for line in f:
            if line.startswith("*NAME_MAP") or line.startswith("*name_map"):
                continue
            if line.startswith("*") and " " in line:
                head = line.split()[0]
                if head.startswith("*D_NET"):
                    parts = line.split()
                    cur = parts[1] if len(parts) > 1 else None
                    n_dnet += 1
                    in_res = False
                    continue
                if head == "*RES":
                    in_res = True
                    if cur:
                        has_res.add(cur)
                    continue
                if head in ("*CAP", "*CONN", "*END", "*D_NET"):
                    in_res = False
                    continue
            # *NAME_MAP 항목: "*123 netname"
            m = re.match(r"^\*(\d+)\s+(\S+)\s*$", line)
            if m:
                nm = m.group(2)
                key = normalize(nm)
                all_names[key] = nm
                if key in want:
                    found_namemap.add(key)
    return found_namemap, has_res, all_names, n_dnet


def main():
    ap = argparse.ArgumentParser(description="N/A 원인을 분류한다.")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--annotated", default=None)
    ap.add_argument("--spef", default=None)
    ap.add_argument("--pin-attr", default=None)
    args = ap.parse_args()

    d = args.dir
    ann = args.annotated or os.path.join(d, "annotated.txt")
    spef = args.spef or os.path.join(d, "design.spef")
    pin_attr = args.pin_attr or os.path.join(d, "pin_attr.txt")

    print("=" * 68)
    print("9 - N/A 원인 진단")
    print("=" * 68)

    if not os.path.isfile(ann):
        print("[ 실패 ] annotated.txt 이 없습니다: %s" % ann)
        print("         2_annotate.py 를 먼저 돌리세요.")
        sys.exit(1)

    rows = read_annotated(ann)
    if not rows:
        print("[ 실패 ] annotated.txt 에서 (net) 줄을 못 읽었습니다.")
        sys.exit(1)

    na_dist = [r for r in rows if r[2] == "N/A"]
    na_res = [r for r in rows if r[3] == "N/A"]
    na_cpin = [r for r in rows if r[4] == "N/A"]
    both = [r for r in rows if r[2] == "N/A" and r[3] == "N/A"]

    print("  전체 (net) 줄 : %d" % len(rows))
    print("  Dist N/A      : %d" % len(na_dist))
    print("  Res  N/A      : %d" % len(na_res))
    print("  Cpin N/A      : %d" % len(na_cpin))
    print("")

    if not na_dist and not na_res and not na_cpin:
        print("[ 정상 ] N/A 가 없습니다. 진단할 것이 없습니다.")
        return

    # ---- Cpin 만의 문제인지 먼저 (SPEF 를 안 읽어도 판정 가능) --------
    if na_cpin:
        print("-" * 68)
        print("[원인 D] Cpin 이 빈 줄 : %d" % len(na_cpin))
        pins = set()
        if os.path.isfile(pin_attr):
            with io.open(pin_attr, "r", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and not line[:1].isspace():
                        pins.add(parts[1])
        missing = [r for r in na_cpin if r[1] not in pins]
        print("       그중 핀 이름이 pin_attr.txt 에 없는 것 : %d" % len(missing))
        for r in missing[:MAX_SHOW]:
            print("         리포트 핀: %s" % r[1])
        if missing:
            print("       -> report_attribute 를 [get_pins *] 로 뽑았는지,")
            print("          계층 이름 표기가 같은지 확인하세요.")
        elif na_cpin:
            print("       핀 이름은 있는데 값이 안 붙었습니다 -- pin_capacitance_max 가")
            print("       그 핀에 없는 경우입니다(출력 핀 등).")
        print("")

    if not both:
        print("[ 정보 ] Dist/Res 는 정상입니다. SPEF 는 문제없습니다.")
        return

    # ---- Dist/Res 둘 다 N/A 인 넷들: SPEF 를 훑어 원인 분류 ----------
    if not os.path.isfile(spef):
        print("[ 실패 ] SPEF 가 없어 원인 A/B/C 를 구분할 수 없습니다: %s" % spef)
        sys.exit(1)

    want = {}
    for r in both:
        want[normalize(r[0])] = r[0]
    print("-" * 68)
    print("Dist/Res 가 함께 N/A 인 넷 %d개를 SPEF 에서 확인합니다..." % len(want))
    found, has_res, all_names, n_dnet = scan_spef(spef, set(want))
    print("  SPEF 의 D_NET 수 : %d" % n_dnet)
    print("")

    cause_a, cause_b, cause_c = [], [], []
    for key, orig in want.items():
        if key in found:
            cause_c.append(orig)      # 이름은 찾았는데 값이 안 나옴
        else:
            # 표기만 다른 게 있는지: 마지막 토큰이 같은 이름 찾기
            leaf = key.split("/")[-1]
            near = [v for k, v in all_names.items() if k.split("/")[-1] == leaf]
            if near:
                cause_b.append((orig, near[0]))
            else:
                cause_a.append(orig)

    print("-" * 68)
    print("[원인 A] 넷이 SPEF 에 아예 없음        : %d" % len(cause_a))
    for n in cause_a[:MAX_SHOW]:
        print("           %s" % n)
    if cause_a:
        print("       -> SPEF 가 이 리포트와 같은 디자인/코너인지 확인하세요.")
        print("          클럭 넷은 SPEF 에서 빠지는 경우가 있습니다(정상일 수 있음).")
    print("")

    print("[원인 B] 이름 표기가 달라 못 찾음      : %d" % len(cause_b))
    for orig, near in cause_b[:MAX_SHOW]:
        print("           리포트: %-40s  SPEF: %s" % (orig, near))
    if cause_b:
        print("       -> 이름 변형 규칙을 넓혀야 합니다. **이 화면을 그대로 가져오세요.**")
    print("")

    print("[원인 C] 찾았지만 저항 경로가 없음     : %d" % len(cause_c))
    for n in cause_c[:MAX_SHOW]:
        print("           %s" % n)
    if cause_c:
        print("       -> 그 넷에 *RES 항목이 없거나 드라이버-리시버가 끊긴 경우입니다.")
        print("          SPEF 를 R 포함으로 다시 뽑아야 할 수 있습니다.")
    print("")
    print("=" * 68)


if __name__ == "__main__":
    main()
