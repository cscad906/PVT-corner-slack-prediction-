#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0단계 - 실행 환경과 입력 파일을 점검한다.

    python  0_check.py                     환경만 점검
    python3 0_check.py --dir ./work        그 폴더의 입력 파일까지 점검

**이 파일만은 파이썬 2.7 로도 돌아간다.** 현장에 파이썬 3 이 있는지 없는지
모르는 상태에서 제일 먼저 돌려야 하는 파일이라, 어느 파이썬으로 쳐도 돌아가야
한다. 그래서 여기서는 3 전용 문법을 쓰지 않는다(다른 파일은 3.6+ 필요).
    python 0_check.py    <- 2.7 이어도 이건 돈다. 쓸 수 있는 파이썬을 찾아 준다

무엇이 준비됐고 무엇이 없는지, 없으면 무엇을 해야 하는지를 한국어로 출력한다.
여기서 전부 OK 가 나온 뒤에 4_all_corners.py 로 넘어간다.
"""
from __future__ import print_function

import argparse
import io
import os
import subprocess
import sys


def ropen(path):
    """깨진 글자가 있어도 읽히게 연다. 파이썬 2/3 둘 다 동작한다.

    파이썬 2 의 내장 open 은 errors= 를 안 받는다.
    """
    return io.open(path, "r", encoding="utf-8", errors="ignore")


def as_text(b):
    """subprocess 출력 -> 글자. 2 에서는 이미 str 이라 그대로 둔다.

    2 에서 굳이 decode 하면 unicode 가 되어, 한글이 섞인 포맷 문자열과
    합칠 때 UnicodeDecodeError 로 죽는다.
    """
    if isinstance(b, str):
        return b
    return b.decode("utf-8", "replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()
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
    ("res_map.txt", "받은 Res 표 (2b 가 쓴다)",
     "코너 폴더마다 둔다. 2열: 넷 이름 / res.\n"
     "               Res 는 온도마다 다르므로 그 코너 온도의 표를 둔다."),
    ("dist_map.txt", "받은 Dist 표 (2b 가 쓴다)",
     "코너 폴더마다 둔다. 2열: 넷 이름 / dist. 코너가 달라도 값은 같다."),
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
        out = as_text(subprocess.check_output(
            [py, "-c", code], stderr=subprocess.STDOUT)).strip()
        ver, nx = out.split()
        return ver, (nx == "Y")
    except Exception:
        return None, False


def check_env():
    hr("1. 파이썬 점검")
    cands = find_pythons()
    if not cands:
        print("  파이썬 3 을 하나도 못 찾았습니다.")
        print("")
        print("  1) PrimeTime 환경을 먼저 source 한 뒤 다시 돌려 보세요.")
        print("     (PrimeTime / ICC2 설치본 안에 python3 이 들어 있습니다)")
        print("  2) 그래도 없으면 CAD 팀에 파이썬 3.6 이상을 요청하세요.")
        print("     이 패키지는 파이썬 3.6+ 가 있어야 돌아갑니다.")
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
        print("  찾은 파이썬이 전부 3.6 미만이라 쓸 수 없습니다.")
        print("")
        print("  1) PrimeTime 환경을 source 한 뒤 다시 돌려 보세요.")
        print("  2) 그래도 없으면 CAD 팀에 파이썬 3.6 이상을 요청하세요.")
        print("     이 패키지는 파이썬 3.6+ 가 있어야 돌아갑니다.")
        return None

    print("  >>> 이 파이썬을 쓰세요:")
    print("")
    print("      %s" % best)
    print("")
    if os.path.basename(best) == best or best == which("python3"):
        print("      PATH 에 있는 python3 이라 그냥 'python3' 로 쓰시면 됩니다.")
        print("        예)  python3 1_union.py --dir round1/corners")
    else:
        print("      시스템 python3 이 낡았거나 없어서, 위 **전체 경로**를 그대로")
        print("      명령 앞에 붙여 쓰세요.")
        print("        예)  %s 1_union.py --dir round1/corners" % best)
    print("")
    print("      이 뒤로 각 단계가 끝날 때마다 다음에 칠 명령이 화면에 그대로")
    print("      찍힙니다. 복사해서 쓰시면 됩니다.")
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
        with ropen(rpt) as f:
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
        with ropen(p) as f:
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
        with ropen(spef) as f:
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
        print("    %s 4_all_corners.py --root <상위폴더>            # 묶음 1 annotation"
              % sys.executable)
        print("    %s 4_all_corners.py --root <상위폴더> --phase 2  # 묶음 2 crosstalk"
              % sys.executable)
        print("")
        print("  코너 하나만 손으로 돌릴 때는:")
        print("    %s 2a_cpin.py           --dir %s" % (sys.executable, args.dir))
        print("    %s 2b_distres_table.py  --dir %s" % (sys.executable, args.dir))
        print("    %s 2c_merge.py          --dir %s" % (sys.executable, args.dir))
    else:
        print("  아직 준비가 안 됐습니다. 위에서 [ 없음 ] / [ 주의 ] 로 표시된 것을 먼저 해결하세요.")
    print("=" * 68)


if __name__ == "__main__":
    main()
