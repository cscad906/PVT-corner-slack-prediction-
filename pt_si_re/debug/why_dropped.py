#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""버려진 경로(핀 연결을 못 찾음)가 왜 버려졌는지 이유별로 세어 준다.

    python3 debug/why_dropped.py 어떤코너.rpt

1_union.py 는 '핀 연결을 못 찾음 N개' 라고만 알려 준다. 그 N개가 정상인지
(포트에서 시작/끝나는 경로) 아니면 놓치면 안 되는 경로인지 구분하려고 만들었다.
특히 홀드 리포트에서 버려지는 수가 크게 늘면 이걸로 원인을 본다.

이유는 다섯 가지로 나눈다.
    되먹임         시작 FF 와 끝 FF 가 같은 경로. enable 되먹임 mux 등.
                   **홀드에서 아주 흔하다.** 놓치면 안 되는 진짜 경로다.
    시작핀 없음    시작점 이름으로 된 핀 줄이 데이터 구간에 없음.
                   보통 입력 포트에서 시작하는 경로다(정상).
    끝핀 없음      끝점 이름으로 된 핀 줄이 없음. 출력 포트로 끝나는 경로(정상).
    순서 뒤집힘    끝핀이 시작핀보다 앞에 있음.
    핀줄 부족      핀 줄이 2개도 안 됨. -input_pins 가 빠졌을 때 이렇게 된다.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "_engine"))
from utf8 import force_utf8
force_utf8()

START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
END_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
SLACK_RE = re.compile(r"^\s*slack\s*\(([^)]+)\)\s+(-?[\d.]+)")
PIN_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")
STOP = ("data arrival time", "required time", "clock uncertainty",
        "library setup time", "library hold time", "slack ")

ORDER = ["되먹임", "시작핀 없음", "끝핀 없음", "순서 뒤집힘", "핀줄 부족"]
NOTE = {
    "되먹임":      "시작 FF == 끝 FF. **놓치면 안 되는 진짜 경로다.**",
    "시작핀 없음": "입력 포트에서 시작하는 경로면 정상.",
    "끝핀 없음":   "출력 포트로 끝나는 경로면 정상.",
    "순서 뒤집힘": "드물다. 예시를 보고 판단할 것.",
    "핀줄 부족":   "많으면 report_timing 에 -input_pins 가 빠진 것이다.",
}


def items_of(lines):
    """데이터 구간 후보 핀 이름들. 1_union.py 의 data_pin_chain 과 같은 규칙."""
    out = []
    for line in lines:
        low = line.strip().lower()
        if any(low.startswith(p) for p in STOP):
            break
        m = PIN_RE.match(line)
        if not m:
            continue
        if m.group(2).lower() == "net":
            continue
        out.append(m.group(1))
    return out


def classify(items, start_inst, end_inst):
    """왜 버려졌는지 한 마디로. 정상적으로 잡히면 None."""
    if len(items) < 2:
        return "핀줄 부족"
    start_at = None
    for i, name in enumerate(items):
        if name.rsplit("/", 1)[0] == start_inst:
            start_at = i
    end_at = None
    for i, name in enumerate(items):
        if name.rsplit("/", 1)[0] == end_inst:
            if start_at is None or i > start_at:
                end_at = i
                break
    if start_at is not None and end_at is not None and end_at > start_at:
        return None                       # 잘 잡힌 경로
    if start_inst == end_inst:
        return "되먹임"
    if start_at is None:
        return "시작핀 없음"
    if end_at is None:
        return "끝핀 없음"
    return "순서 뒤집힘"


def main():
    if len(sys.argv) < 2:
        print("쓰는 법: python3 debug/why_dropped.py <리포트.rpt>")
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.isfile(path):
        print("파일이 없습니다: %s" % path)
        sys.exit(1)

    counts = {k: 0 for k in ORDER}
    sample = {}
    n_ok = n_path = n_noslack = 0
    start = end = None
    buf = []

    with open(path, "r", errors="ignore") as f:
        for line in f:
            m = START_RE.match(line)
            if m:
                if start is not None:
                    n_noslack += 1
                start, end, buf = m.group(1), "", []
                continue
            if start is None:
                continue
            m = END_RE.match(line)
            if m:
                end = m.group(1)
                continue
            m = SLACK_RE.match(line)
            if m:
                n_path += 1
                why = classify(items_of(buf), start, end)
                if why is None:
                    n_ok += 1
                else:
                    counts[why] += 1
                    sample.setdefault(why, (start, end))
                start, end, buf = None, None, []
                continue
            buf.append(line)
    if start is not None:
        n_noslack += 1

    print("=" * 70)
    print("버려진 경로 원인")
    print("=" * 70)
    print("  파일 : %s" % path)
    print("  경로 : %d개 (그중 정상으로 잡힌 것 %d개)" % (n_path, n_ok))
    if n_noslack:
        print("  slack 줄 없이 끝난 경로 : %d개  (-nosplit 확인)" % n_noslack)
    print("")
    total_bad = sum(counts.values())
    if not total_bad:
        print("  버려진 경로가 없습니다.")
        print("=" * 70)
        return
    print("  %-14s %8s %7s   %s" % ("이유", "개수", "비율", "무슨 뜻인가"))
    print("  " + "-" * 66)
    for k in ORDER:
        if not counts[k]:
            continue
        print("  %-14s %8d %6.1f%%   %s"
              % (k, counts[k], 100.0 * counts[k] / n_path, NOTE[k]))
    print("  " + "-" * 66)
    print("  %-14s %8d %6.1f%%" % ("합계", total_bad, 100.0 * total_bad / n_path))
    print("")
    print("  [ 버려진 경로 예시 ]")
    for k in ORDER:
        if k in sample:
            s, e = sample[k]
            print("    %s" % k)
            print("      시작 %s" % s)
            print("      끝   %s" % e)
    print("=" * 70)
    if counts["되먹임"]:
        print("  되먹임 경로가 %d개 있습니다. 이건 정상 경로인데 버려진 것입니다."
              % counts["되먹임"])
        print("  홀드 분석에서 특히 많습니다(enable 되먹임 mux 등).")
        print("=" * 70)


if __name__ == "__main__":
    main()
