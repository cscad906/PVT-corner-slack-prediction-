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
import time
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


def _read1(path):
    """/sys, /proc 의 짧은 파일 하나를 읽는다. 값은 전부 ASCII 다.

    ropen(io.open) 을 쓰면 파이썬 2 에서 unicode 가 나오는데, 그걸 한글이 섞인
    포맷 문자열과 합치면 UnicodeDecodeError 로 죽는다. 이 파일만은 2.7 로도
    돌아야 하므로 바이트로 읽고 as_text 로 넘긴다.
    """
    try:
        f = open(path, "rb")
        v = f.read().strip()
        f.close()
        return as_text(v)
    except Exception:
        return None


def disk_of(path):
    """그 경로가 어느 디스크에 있는지. -> (장치이름, 회전식인가)

    회전식(HDD)이면 여러 코너를 동시에 돌려도 헤드가 하나뿐이라 총 처리량이
    안 늘어난다. 그래서 --jobs 를 올릴지 말지가 여기서 갈린다.
    못 알아내면 (None, None) -- 네트워크 디스크(NFS 등)면 보통 여기 걸린다.
    """
    try:
        st = os.stat(path)
        maj, mino = os.major(st.st_dev), os.minor(st.st_dev)
        link = os.path.realpath("/sys/dev/block/%d:%d" % (maj, mino))
        dev = os.path.basename(link)
        parent = os.path.dirname(link)
        if os.path.basename(parent) != "block":   # 파티션이면 한 단계 위가 디스크
            dev = os.path.basename(parent)
        rot = _read1("/sys/block/%s/queue/rotational" % dev)
        if rot is None:
            return dev, None
        return dev, (rot == "1")
    except Exception:
        return None, None


def check_machine(work):
    """코어 / 메모리 / 스왑 / 디스크. --jobs 를 몇으로 줄지 여기서 정한다."""
    hr("1-2. 장비 점검")

    cores = None
    try:
        import multiprocessing
        cores = multiprocessing.cpu_count()
    except Exception:
        pass
    load = _read1("/proc/loadavg")
    if cores:
        print("  CPU 코어  : %d개" % cores)
    if load:
        p1 = load.split()[:3]
        print("  부하      : %s (1분/5분/15분)   <- 코어 수보다 크면 이미 붐빈다"
              % " ".join(p1))

    mem = _read1("/proc/meminfo")
    tot = avail = swtot = swfree = None
    if mem:
        for line in mem.split("\n"):
            if line.startswith("MemTotal:"):     tot = int(line.split()[1])
            elif line.startswith("MemAvailable:"): avail = int(line.split()[1])
            elif line.startswith("SwapTotal:"):  swtot = int(line.split()[1])
            elif line.startswith("SwapFree:"):   swfree = int(line.split()[1])
    if tot and avail is not None:
        print("  메모리    : 전체 %.0fGB, 지금 쓸 수 있는 것 %.0fGB"
              % (tot / 1048576.0, avail / 1048576.0))
    if swtot and swfree is not None and swtot > 0:
        used = (swtot - swfree) / 1048576.0
        mark = "   <- 스왑을 쓰고 있다. 메모리가 모자란 것이다" if used > 1 else ""
        print("  스왑      : %.0fGB 사용중%s" % (used, mark))

    dev, rot = disk_of(work if os.path.isdir(work) else ".")
    if dev is None:
        print("  디스크    : 알 수 없음 (네트워크 디스크일 수 있다)")
        print("              그러면 --jobs 를 올려도 이득이 없을 수 있다")
    else:
        kind = "알 수 없음" if rot is None else ("HDD (회전식)" if rot else "SSD/NVMe")
        print("  디스크    : %s  -  %s" % (dev, kind))

    print("")
    print("  --jobs 를 몇으로 줄까")
    if rot is True:
        print("    1 로 두세요. 이 폴더는 HDD 라 여러 코너를 동시에 돌려도")
        print("    헤드가 하나뿐이라 총 시간이 그대로입니다. 코너별로만 느려집니다.")
    else:
        # 2b/2c/5a 가 리포트를 통째로 메모리에 올린다. 실측으로 리포트의 약 5.5배.
        print("    2b/2c/5a 는 리포트를 통째로 메모리에 올립니다 (리포트의 약 5.5배).")
        rpt, _e, _c = find_rpt(work) if os.path.isdir(work) else (None, None, None)
        size = None
        if rpt:
            try:
                size = os.path.getsize(rpt)
            except OSError:
                pass
        if size and avail:
            per = size * 5.5
            cap = max(1, int(avail * 1024 * 0.7 / per))
            if cores:
                cap = min(cap, cores)
            print("")
            print("    이 폴더 리포트 %.0fMB -> 코너당 약 %.1fGB"
                  % (size / 1048576.0, per / 1073741824.0))
            print("    쓸 수 있는 메모리 %.0fGB 기준으로  --jobs %d  까지가 안전합니다."
                  % (avail / 1048576.0, cap))
            print("    (넘기면 스왑으로 가고, 그때는 코너마다 몇 배씩 느려집니다)")
        else:
            print("    리포트가 100MB 면 코너당 약 0.6GB, 400MB 면 약 2.4GB 입니다.")
            print("    쓸 수 있는 메모리를 그 값으로 나눈 수를 넘기지 마세요.")
        print("")
        print("    돌리는 중에 느려지면 다른 창에서 확인:")
        print("      vmstat 5      si/so 가 0 이 아니면 스왑 중 -- --jobs 를 낮추세요")
        print("      iostat -x 5   %util 이 100 에 붙어 있으면 디스크가 병목입니다")
    return None


def _proc_counters():
    """스왑/디스크/CPU 를 한 번 읽어 둔다. 두 번 읽어 차이를 본다."""
    out = {"swin": 0, "swout": 0, "iowait": 0, "total": 0}
    v = _read1("/proc/vmstat")
    if v:
        for line in v.split("\n"):
            if line.startswith("pswpin "):
                out["swin"] = int(line.split()[1])
            elif line.startswith("pswpout "):
                out["swout"] = int(line.split()[1])
    st = _read1("/proc/stat")
    if st:
        for line in st.split("\n"):
            if line.startswith("cpu "):
                f = [int(x) for x in line.split()[1:]]
                out["total"] = sum(f)
                if len(f) > 4:
                    out["iowait"] = f[4]
                break
    return out


def watch_run(seconds):
    """지금 도는 작업이 무엇 때문에 느린지 스스로 판정한다.

    현장에서 화면을 밖으로 내보낼 수 없으므로, 숫자를 보여 주는 대신 결론을
    말해 준다. 4_all_corners 를 돌리는 중에 다른 창에서 이걸 돌리면 된다.
    """
    hr("돌고 있는 작업 진단  (%d초 동안 지켜봅니다)" % seconds)
    print("  4_all_corners 가 도는 중에 돌리세요. 지금 시작합니다...")
    print("")

    first = _proc_counters()
    a = first
    step = 5
    n = max(1, seconds // step)
    for i in range(n):
        time.sleep(step)
        b = _proc_counters()
        d_sw = (b["swin"] - a["swin"]) + (b["swout"] - a["swout"])
        d_tot = b["total"] - a["total"]
        d_io = b["iowait"] - a["iowait"]
        pct = (100.0 * d_io / d_tot) if d_tot else 0.0
        print("    %2d/%d  스왑 %-8d  디스크 대기 %.0f%%" % (i + 1, n, d_sw, pct))
        a = b

    # 판정은 마지막 구간이 아니라 **전 구간 누적**으로 한다.
    # 한 구간만 보면 그때 마침 조용했다는 이유로 잘못 말할 수 있다.
    print("")
    tot_sw = (a["swin"] - first["swin"]) + (a["swout"] - first["swout"])
    tot = a["total"] - first["total"]
    io_pct = (100.0 * (a["iowait"] - first["iowait"]) / tot) if tot else 0.0
    load = _read1("/proc/loadavg")
    l1 = float(load.split()[0]) if load else 0.0
    try:
        import multiprocessing
        cores = multiprocessing.cpu_count()
    except Exception:
        cores = 4

    print("-" * 68)
    if tot_sw > 100:
        print("  [ 메모리 부족 ]  스왑을 쓰고 있습니다.")
        print("")
        print("    코너를 동시에 돌리면 리포트를 그 수만큼 메모리에 올립니다.")
        print("    남은 메모리를 넘겨서 디스크로 밀려나는 중입니다.")
        print("    이러면 코너마다 몇 배씩 느려져 병렬로 돌린 의미가 없습니다.")
        print("")
        print("    할 일 : --jobs 를 반으로 낮춰 다시 돌리세요.")
    elif io_pct > 30:
        print("  [ 디스크 병목 ]  CPU 는 놀고 디스크만 기다립니다.")
        print("")
        print("    --jobs 를 올려도 총 시간은 그대로입니다. 코너별로만 느려집니다.")
        print("    할 일 : --jobs 1 로 두세요. 화면도 실시간으로 나와 낫습니다.")
    elif l1 > cores * 1.5:
        print("  [ CPU 경합 ]  이 장비가 이미 붐빕니다 (부하 %.0f, 코어 %d)."
              % (l1, cores))
        print("")
        print("    다른 사람 작업과 겹치는 중입니다. --jobs 를 낮추거나")
        print("    한산할 때 돌리세요.")
    else:
        print("  [ 정상 ]  스왑도 디스크 대기도 없습니다.")
        print("")
        print("    자원이 병목은 아닙니다. 그런데도 느리면 리포트가 커서")
        print("    그만큼 걸리는 것입니다 (시간은 리포트 크기에 정비례합니다).")
        print("    --jobs 를 올려 볼 여지가 있습니다.")
    print("-" * 68)


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
    ap.add_argument("--watch", type=int, nargs="?", const=30, default=None,
                    metavar="초",
                    help="지금 도는 작업이 왜 느린지 판정한다. 4_all_corners 가 "
                         "도는 중에 다른 창에서 돌린다 (기본 30초)")
    args = ap.parse_args()

    # --watch 는 도는 중에 부르는 것이라, 파이썬/입력 점검은 건너뛴다.
    if args.watch is not None:
        watch_run(args.watch)
        return 0

    print("PVT 데이터 추출 - 0단계 점검")
    py = check_env()
    check_machine(args.dir)
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
