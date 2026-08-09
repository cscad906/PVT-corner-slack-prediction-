#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""8 - 문제가 생겼을 때 상황을 한 화면으로 요약한다. (원격 문의용)

    python3 8_snapshot.py --dir <폴더>

막혔을 때 이것만 돌려서 **화면 전체를 복사해 보내면** 원인을 파악할 수 있다.
파일을 통째로 보낼 필요가 없다. 핸드폰으로 붙여넣을 수 있는 분량으로 맞춰 두었다.

담는 것
    - 파이썬/PT 환경
    - 폴더 안 파일들의 크기와 줄 수
    - 리포트의 형식 지문 (헤더 줄, 핀 줄, 넷 줄 각 1개)
    - attribute 덤프의 형식 지문
    - 각 단계 결과 파일의 상태와 실패 줄 몇 개
민감한 설계 정보가 걱정되면 --mask 를 주면 인스턴스 이름을 가린다.
"""
from __future__ import division, print_function
import argparse
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from find_rpt import find_rpt

W = 72
OBJ_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")


def line(c="-"):
    print(c * W)


def head(t):
    print("")
    line("=")
    print(t)
    line("=")


def masker(on):
    """인스턴스 이름을 길이만 남기고 가린다(--mask)."""
    if not on:
        return lambda s: s

    def f(s):
        return re.sub(r"[A-Za-z_][A-Za-z_0-9/\[\]]{6,}",
                      lambda m: "<name:%d>" % len(m.group(0)), s)
    return f


def count_lines(p, limit=None):
    n = 0
    with io.open(p, "r", errors="ignore") as f:
        for _ in f:
            n += 1
            if limit and n >= limit:
                break
    return n


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.1f%s" % (n, u)
        n /= 1024.0


def show_env():
    head("1. 환경")
    print("  python  : %s" % sys.executable)
    print("  version : %s" % sys.version.split()[0])
    pt = None
    for d in os.environ.get("PATH", "").split(os.pathsep):
        q = os.path.join(d, "pt_shell")
        if os.access(q, os.X_OK):
            pt = q
            break
    print("  pt_shell: %s" % (pt or "PATH 에 없음"))
    print("  cwd     : %s" % os.getcwd())


def show_files(d, mask):
    head("2. 폴더 안 파일  (%s)" % d)
    if not os.path.isdir(d):
        print("  폴더가 없습니다.")
        return []
    names = sorted(os.listdir(d))
    if not names:
        print("  비어 있습니다.")
    for n in names:
        p = os.path.join(d, n)
        if os.path.isdir(p):
            print("  %-26s <폴더>" % n)
            continue
        size = os.path.getsize(p)
        extra = ""
        if size < 400 * 1024 * 1024 and n.endswith((".rpt", ".txt", ".tsv", ".tcl")):
            extra = "  %s줄" % format(count_lines(p), ",")
        print("  %-26s %9s%s" % (n, human(size), extra))
    return names


def fingerprint_report(p, mask):
    """리포트의 형식을 알 수 있는 줄만 뽑는다."""
    hdr = pin = net = slack = start = None
    n_start = n_net = n_pin = 0
    with io.open(p, "r", errors="ignore") as f:
        for raw in f:
            s = raw.rstrip("\n")
            if start is None and "Startpoint:" in s:
                start = s
            if "Startpoint:" in s:
                n_start += 1
            if hdr is None and "Point" in s and "Path" in s and "(" not in s:
                hdr = s
            m = OBJ_RE.match(s)
            if m:
                if m.group(2).lower() == "net":
                    n_net += 1
                    if net is None:
                        net = s
                else:
                    n_pin += 1
                    if pin is None:
                        pin = s
            if slack is None and re.match(r"^\s*slack\s*\(", s):
                slack = s
    print("  경로(Startpoint) : %s" % format(n_start, ","))
    print("  핀 줄            : %s" % format(n_pin, ","))
    print("  (net) 줄         : %s" % format(n_net, ","))
    print("")
    for label, v in (("헤더  ", hdr), ("핀 줄 ", pin), ("넷 줄 ", net),
                     ("slack ", slack), ("경로  ", start)):
        if v is None:
            print("  %s: 없음" % label)
        else:
            print("  %s: %s" % (label, mask(v)[:W + 40]))
    # 옵션 누락 자동 판정
    print("")
    if n_net == 0:
        print("  >> (net) 줄이 없습니다. report_timing 에 -nets 가 빠졌습니다.")
    if n_pin == 0:
        print("  >> 핀 줄이 없습니다. -input_pins 가 빠졌습니다.")
    if hdr and "Fanout" not in hdr:
        print("  >> 헤더에 Fanout 이 없습니다. -capacitance 가 빠졌을 수 있습니다.")
    if hdr and ("Mean" in hdr or "Sensit" in hdr):
        print("  >> POCV(-variation) 형식입니다. Mean/Sensit 열이 있습니다.")


def fingerprint_attr(p, mask):
    """attribute 덤프의 형식과 어떤 속성이 있는지."""
    attrs = {}
    sample = []
    n = 0
    with io.open(p, "r", errors="ignore") as f:
        for raw in f:
            n += 1
            s = raw.strip()
            if not s or s[0] == "*" or set(s) <= set("-="):
                continue
            parts = s.split()
            if len(parts) >= 4 and parts[2] in ("float", "int", "string", "boolean"):
                attrs[parts[3]] = attrs.get(parts[3], 0) + 1
                if len(sample) < 3:
                    sample.append(s)
            if n > 200000:
                break
    print("  (앞부분 %s줄 기준)" % format(min(n, 200000), ","))
    print("  속성 종류 %d개" % len(attrs))
    for a in sorted(attrs, key=lambda x: -attrs[x])[:12]:
        print("    %-40s %s" % (a, format(attrs[a], ",")))
    print("")
    for s in sample:
        print("  예: %s" % mask(s)[:W + 30])


def check_result(d, mask):
    head("4. 결과 파일 상태")
    checks = [
        ("cpin.tsv", "cpin", 3),
        ("distres.tsv", "dist/res", None),
    ]
    for name, label, _ in checks:
        p = os.path.join(d, name)
        if not os.path.isfile(p):
            print("  %-14s 없음" % name)
            continue
        total = empty = 0
        with io.open(p, "r", errors="ignore") as f:
            f.readline()
            for l in f:
                c = l.rstrip("\n").split("\t")
                total += 1
                if not c[-1].strip():
                    empty += 1
        print("  %-14s %s줄, 값 없음 %s줄" % (name, format(total, ","), format(empty, ",")))

    p = os.path.join(d, "annotated.txt")
    if os.path.isfile(p):
        n_net = n_na = 0
        first_na = []
        for l in io.open(p, "r", errors="ignore"):
            if "(net)" not in l:
                continue
            n_net += 1
            t = l.rstrip("\n").split()[-3:]
            if len(t) == 3 and any("N/A" in x for x in t):
                n_na += 1
                if len(first_na) < 3:
                    first_na.append(l.rstrip("\n"))
        print("  %-14s (net) %s줄, N/A %s줄" % ("annotated.txt", format(n_net, ","), format(n_na, ",")))
        for l in first_na:
            print("      N/A 예: %s" % mask(l)[-70:])
    else:
        print("  %-14s 없음" % "annotated.txt")

    p = os.path.join(d, "crosstalk.tsv")
    if os.path.isfile(p):
        with io.open(p, "r", errors="ignore") as f:
            hdr = f.readline().rstrip("\n").split("\t")
            rows = sum(1 for _ in f)
        print("  %-14s %s줄, %d열" % ("crosstalk.tsv", format(rows, ","), len(hdr)))
        print("      열: %s" % ", ".join(hdr[:6]))
        print("          %s" % ", ".join(hdr[12:18]) if len(hdr) > 12 else "")
    else:
        print("  %-14s 없음" % "crosstalk.tsv")


def main():
    ap = argparse.ArgumentParser(description="문제 상황을 한 화면으로 요약한다.")
    ap.add_argument("--dir", default=".")
    ap.add_argument("--spef", default=None)
    ap.add_argument("--mask", action="store_true",
                    help="인스턴스 이름을 가린다 (설계 정보 노출이 걱정될 때)")
    ap.add_argument("--out", default="debug/snapshot.txt",
                    help="결과를 저장할 파일. 이 파일을 git push 하면 된다.")
    args = ap.parse_args()

    # 화면과 파일에 동시에 쓴다. 파일은 git 으로 넘기는 용도.
    outdir = os.path.dirname(os.path.abspath(args.out))
    if outdir and not os.path.isdir(outdir):
        os.makedirs(outdir)
    _fh = open(args.out, "w")
    _stdout = sys.stdout

    class _Tee(object):
        def write(self, x):
            _stdout.write(x)
            _fh.write(x)

        def flush(self):
            _stdout.flush()
            _fh.flush()

    sys.stdout = _Tee()
    mask = masker(args.mask)
    d = args.dir

    print("=" * W)
    print("상황 요약  (이 화면 전체를 복사해서 보내세요)")
    print("=" * W)

    show_env()
    show_files(d, mask)

    rpt, _, _ = find_rpt(d)     # 폴더 안의 .rpt 를 찾는다(이름 자유)
    rpt = rpt or os.path.join(d, "timing.rpt")
    if os.path.isfile(rpt):
        head("3-1. %s 형식" % os.path.basename(rpt))
        fingerprint_report(rpt, mask)
    else:
        head("3-1. 타이밍 리포트")
        print("  폴더에서 .rpt 를 못 찾았습니다: %s" % d)

    for name in ("pin_attr.txt", "net_attr.txt"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            head("3-2. %s 형식" % name)
            fingerprint_attr(p, mask)

    spef = args.spef or os.path.join(d, "design.spef")
    if os.path.isfile(spef):
        head("3-3. SPEF 헤더")
        units, coupled, prog = [], False, "?"
        in_cap = False
        with io.open(spef, "r", errors="ignore") as f:
            for i, l in enumerate(f):
                if l.startswith("*PROGRAM"):
                    prog = l.strip()
                if "_UNIT" in l and l.startswith("*"):
                    units.append(l.strip())
                if l.startswith("*CAP"):
                    in_cap = True
                    continue
                if l.startswith("*"):
                    in_cap = False
                    continue
                if in_cap and not coupled and len(l.split()) == 4 and l.split()[2].startswith("*"):
                    coupled = True
                if i > 400000 and units:
                    break
        print("  %s" % prog)
        for u in units[:4]:
            print("  %s" % u)
        print("  coupling : %s" % ("있음" if coupled else "없음 <- crosstalk 이 전부 0 이 됩니다"))

    check_result(d, mask)

    head("끝")
    sys.stdout = _stdout
    _fh.close()
    print("  저장했습니다: %s" % args.out)
    print("")
    print("  이 파일을 git 으로 보내면 됩니다:")
    print("    git add %s" % args.out)
    print('    git commit -m "debug"')
    print("    git push")
    print("")


if __name__ == "__main__":
    main()
