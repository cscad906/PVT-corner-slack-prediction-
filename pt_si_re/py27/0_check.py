#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0단계 - 실행 환경과 입력 파일을 점검한다.

    python3 0_check.py                     환경만 점검
    python3 0_check.py --dir ./work        그 폴더의 입력 파일까지 점검

무엇이 준비됐고 무엇이 없는지, 없으면 무엇을 해야 하는지를 한국어로 출력한다.
여기서 전부 OK 가 나온 뒤에 2_annotate.py 로 넘어간다.
"""
from __future__ import division, print_function
import argparse
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from find_rpt import find_rpt

# 이 폴더에 있어야 하는 입력 파일들. (이름, 설명, 만드는 방법)
INPUTS = [
    # 리포트 파일 이름은 자유다(코너 이름으로 짓는다). 폴더 안의 .rpt 를 찾는다.
    ("*.rpt", "타이밍 리포트",
     "pt_shell: source fixed_paths.tcl   (2회차)\n"
     "               또는 report_timing -nets -input_pins -capacitance \\\n"
     "               -transition_time -path_type full_clock_expanded \\\n"
     "               -nosplit -significant_digits 6 ... 을 리다이렉트"),
    ("pin_attr.txt", "핀 attribute 덤프 (Cpin, arrival, slew)",
     "pt_shell: redirect -file pin_attr.txt { report_attribute -application [get_pins *] }"),
    ("net_attr.txt", "넷 attribute 덤프 (crosstalk)",
     "pt_shell: redirect -file net_attr.txt { report_attribute -application [get_nets *] }"),
    ("design.spef", "SPEF (Dist/Res 계산에 필요)",
     "이미 받은 SPEF 파일을 이 이름으로 복사하거나, --spef 로 경로를 직접 준다"),
]

OK = "[ OK ]"
NG = "[ 없음 ]"
WARN = "[ 주의 ]"


def hr(title=""):
    print("")
    print("=" * 68)
    if title:
        print(title)
        print("-" * 68)


def find_pythons():
    """이 패키지를 돌릴 수 있는 python 후보를 찾는다.

    시스템 python 이 2.7 이어도 상관없다. Synopsys 툴(PrimeTime/ICC2 등) 설치본이
    Python 3.6 + networkx 를 포함하므로, 그 툴이 깔린 곳이면 거의 항상 하나는 나온다.
    """
    cands = []

    # 1) PrimeTime 번들 -- 가장 확실
    ptbin = which("pt_shell")
    if ptbin:
        root = os.path.dirname(os.path.dirname(ptbin))
        for sub in ("etc/Python/bin/python3", "etc/cltPython/bin/python3"):
            p = os.path.join(root, sub)
            if os.access(p, os.X_OK):
                cands.append(p)

    # 2) 다른 Synopsys 툴 설치본 (구조가 같다)
    roots = ["/usr/synopsys", "/tools/synopsys", "/opt/synopsys",
             "/usr/local/synopsys", "/eda/synopsys", "/apps/synopsys"]
    for env in ("SYNOPSYS", "SNPS_ROOT", "SYNOPSYS_ROOT", "STARRC_ROOT"):
        if os.environ.get(env):
            roots.append(os.environ[env])
    for root in roots:
        if not os.path.isdir(root):
            continue
        for lvl1 in _listdir(root):
            for d in (lvl1,) + tuple(_listdir(lvl1)):
                for sub in ("etc/Python/bin/python3", "etc/cltPython/bin/python3"):
                    p = os.path.join(d, sub)
                    if os.access(p, os.X_OK):
                        cands.append(p)

    # 3) PATH 위의 python3
    for name in ("python3.11", "python3.10", "python3.9", "python3.8",
                 "python3.7", "python3.6", "python3"):
        p = which(name)
        if p:
            cands.append(p)

    # 중복 제거(실제 경로 기준)
    seen, uniq = set(), []
    for p in cands:
        try:
            real = os.path.realpath(p)
        except OSError:
            real = p
        if real in seen:
            continue
        seen.add(real)
        uniq.append(p)
    return uniq


def _listdir(d):
    try:
        return [os.path.join(d, x) for x in os.listdir(d)
                if os.path.isdir(os.path.join(d, x))]
    except OSError:
        return []


def which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    return None


def probe(py):
    """(버전문자열, networkx유무) 를 돌려준다. 못 돌리면 (None, False)."""
    code = ("import sys;"
            "v='%d.%d.%d'%sys.version_info[:3];"
            "\ntry:\n import networkx; n='Y'\nexcept Exception: n='N'\n"
            "print(v+' '+n)")
    try:
        out = subprocess.check_output([py, "-c", code],
                                      stderr=subprocess.STDOUT).decode().strip()
        ver, nx = out.split()
        return ver, (nx == "Y")
    except Exception:
        return None, False


def check_env():
    hr("1. 파이썬 점검")
    cands = find_pythons()
    if not cands:
        print("  python3 을 하나도 못 찾았습니다.")
        print("  -> PrimeTime 환경을 먼저 source 한 뒤 다시 실행해 보세요.")
        print("     (PrimeTime 설치본 안에 python3 이 들어 있습니다)")
        return None

    print("  %-56s %-8s %s" % ("경로", "버전", "networkx"))
    print("  " + "-" * 74)
    best, best_score = None, -1
    for p in cands:
        ver, has_nx = probe(p)
        if ver is None:
            continue
        major, minor = (int(x) for x in ver.split(".")[:2])
        usable = (major == 3 and minor >= 6)
        score = (2 if has_nx else 1) if usable else 0
        mark = "" if usable else "  <- 3.6 미만이라 사용 불가"
        print("  %-56s %-8s %-3s%s" % (p, ver, "있음" if has_nx else "없음", mark))
        if score > best_score:
            best, best_score = p, score

    print("")
    if best_score <= 0:
        print("  쓸 수 있는 python 이 없습니다. PrimeTime 환경을 source 한 뒤 다시 실행하세요.")
        return None

    print("  >>> 사용할 python:")
    print("      %s" % best)
    print("")
    print("      아래 한 줄을 복사해 두고, 이후 모든 명령에서 python3 대신 $PY 를 씁니다.")
    print("        bash:  export PY=%s" % best)
    print("        csh :  setenv PY %s" % best)
    if best_score == 1:
        print("")
        print("  %s networkx 가 없습니다. 2_annotate.py 가 실행되지 않습니다." % WARN)
        print("        위 표에서 networkx '있음' 인 python 을 대신 쓰세요.")
    return best


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024.0


def check_inputs(work, spef_override):
    hr("2. 입력 파일 점검  (폴더: %s)" % work)
    missing = []
    for name, desc, howto in INPUTS:
        if name == "*.rpt":
            # 리포트는 코너 이름으로 짓기 때문에 이름이 고정이 아니다
            path, _e, _c = find_rpt(work)
            if path:
                name = os.path.basename(path)
        elif name == "design.spef" and spef_override:
            path = spef_override
        else:
            path = os.path.join(work, name)
        if path and os.path.isfile(path):
            print("  %s %-22s %-30s %s" % (OK, name, desc, human_size(os.path.getsize(path))))
        else:
            print("  %s %-22s %-30s" % (NG, name, desc))
            missing.append((name, howto))

    if missing:
        print("")
        print("  없는 파일을 만드는 방법:")
        for name, howto in missing:
            print("    - %s" % name)
            print("        %s" % howto)
    return not missing


def check_content(work, spef_override):
    """파일이 있으면 내용이 쓸만한지까지 본다. 형식이 틀리면 여기서 걸린다."""
    hr("3. 입력 내용 점검")
    ok = True

    rpt, _, _ = find_rpt(work)   # 폴더 안의 .rpt 를 찾는다(이름 자유)
    rpt = rpt or os.path.join(work, "timing.rpt")
    if os.path.isfile(rpt):
        n_net = n_start = 0
        with io.open(rpt, "r", errors="ignore") as f:
            for line in f:
                if "(net)" in line:
                    n_net += 1
                elif "Startpoint:" in line:
                    n_start += 1
        print("  timing.rpt : 경로 %d개, (net) 줄 %d개" % (n_start, n_net))
        if n_net == 0:
            ok = False
            print("  %s (net) 줄이 없습니다. report_timing 에 아래 옵션이 빠졌습니다:" % WARN)
            print("        -nets -input_pins -capacitance -transition_time")
            print("        -path_type full_clock_expanded -nosplit")

    for name, attr in (("pin_attr.txt", "pin_capacitance_max"),
                       ("net_attr.txt", "annotated_delay_delta_max")):
        p = os.path.join(work, name)
        if not os.path.isfile(p):
            continue
        n = 0
        with io.open(p, "r", errors="ignore") as f:
            for line in f:
                if attr in line:
                    n += 1
        print("  %-13s: %s 가 %d줄" % (name, attr, n))
        if n == 0:
            ok = False
            print("  %s %s 가 하나도 없습니다." % (WARN, attr))
            print("        report_attribute 에 -application 을 빠뜨리지 않았는지 확인하세요.")

    spef = spef_override or os.path.join(work, "design.spef")
    if os.path.isfile(spef):
        units, coupled = [], False
        in_cap = False
        with io.open(spef, "r", errors="ignore") as f:
            for line in f:
                if line.startswith("*") and "_UNIT" in line:
                    units.append(line.strip())
                if line.startswith("*CAP"):
                    in_cap = True
                    continue
                if line.startswith("*"):
                    in_cap = False
                    continue
                if in_cap and not coupled:
                    t = line.split()
                    if len(t) == 4 and t[2].startswith("*"):
                        coupled = True
                if len(units) >= 4 and coupled:
                    break
        print("  SPEF 단위   : %s" % (", ".join(units) if units else "선언 없음"))
        print("  SPEF coupling: %s" % ("있음 (crosstalk 가능)" if coupled
                                       else "없음 (crosstalk 값이 0 으로 나옵니다)"))
    return ok


def main():
    ap = argparse.ArgumentParser(description="실행 환경과 입력 파일을 점검한다.")
    ap.add_argument("--dir", default=".", help="입력 파일이 있는 폴더")
    ap.add_argument("--spef", default=None, help="SPEF 경로를 직접 줄 때")
    args = ap.parse_args()

    print("PVT 데이터 추출 - 0단계 점검")
    py = check_env()
    have = check_inputs(args.dir, args.spef)
    if have:
        check_content(args.dir, args.spef)

    hr("결과")
    if py and have:
        print("  준비 완료. 다음 명령으로 넘어가세요:")
        print("")
        print("    $PY 2_annotate.py  --dir %s" % args.dir)
        print("    $PY 3_crosstalk.py --dir %s" % args.dir)
    else:
        print("  아직 준비가 안 됐습니다. 위에서 [ 없음 ] / [ 주의 ] 로 표시된 것을 먼저 해결하세요.")
    print("=" * 68)


if __name__ == "__main__":
    main()
