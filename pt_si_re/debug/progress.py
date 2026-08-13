#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""지금 돌고 있는 단계가 어디까지 갔는지 밖에서 본다.

    python3 debug/progress.py            한 번 보고 끝
    python3 debug/progress.py --watch    5초마다 다시 (Ctrl-C 로 중단)

무엇을 왜 하나
    2b 는 1GB 짜리 SPEF 를 읽어 몇 분씩 돈다. 화면에는 "SPEF 계산 중..." 만
    떠 있어서, 도는 중인지 멈춘 건지 알 수가 없다. 돌리는 창을 건드리지 않고
    다른 창에서 확인하려고 만들었다.

    리눅스는 열려 있는 파일마다 **어디까지 읽었는지**를 /proc 에 적어 둔다.
    그걸 파일 크기로 나누면 진행률이 된다. 프로세스에 아무 영향이 없다.

읽는 법
    % 가 오른다        -> 정상. 파일을 읽는 중이다
    % 가 100 인데 안 끝난다 -> 다 읽고 계산 중. 여기가 길면 SPEF 가 이 코너와
                          안 맞아 이름 매칭이 헤매는 경우다(res.py fuzzy)
    CPU 가 0~1%        -> 멈춰 있다. 저장소(NFS) 대기이거나 스왑
    메모리가 계속 는다  -> 스왑 직전. 위험
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "_engine"))
try:
    from utf8 import force_utf8
    force_utf8()
except ImportError:
    pass

# 이 파이프라인의 단계들. 이름으로 골라내 남의 파이썬은 안 본다.
STEP = re.compile(r"(\d[a-z]?_[a-z_]+)\.py")
WATCH_EXT = (".spef", ".rpt", ".txt", ".tsv")


def procs():
    """이 사용자의 파이썬 중 파이프라인 단계인 것 -> [(pid, 명령줄)]"""
    out = []
    try:
        raw = subprocess.check_output(
            ["ps", "-u", str(os.getuid()), "-o", "pid=,args="]).decode(
                "utf-8", "replace")
    except Exception as e:
        print("ps 를 못 돌렸습니다: %s" % e)
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, args = line.partition(" ")
        args = args.strip()
        # **첫 토큰이** python 이어야 한다. 이걸 안 보면 그 명령을 띄운 셸
        # (bash -c "... python3 2b_distres.py ...")까지 같이 잡혀서, 일도 안
        # 하는 프로세스가 'cpu 0% -- 멈춤?' 으로 뜬다.
        head = args.split(" ", 1)[0]
        if "python" not in os.path.basename(head):
            continue
        m = STEP.search(args)
        if not m:
            continue
        try:
            out.append((int(pid), args.strip(), m.group(1)))
        except ValueError:
            pass
    return out


def stat_of(pid):
    """(경과초, CPU 누적초, 메모리MB). 못 읽으면 (None, None, None)."""
    try:
        with open("/proc/%d/stat" % pid) as f:
            f.read()
    except IOError:
        return None, None, None
    try:
        etime = subprocess.check_output(
            ["ps", "-o", "etimes=,cputimes=,rss=", "-p", str(pid)]).decode()
        a = etime.split()
        return int(a[0]), int(a[1]), int(a[2]) // 1024
    except Exception:
        return None, None, None


def open_files(pid):
    """[(파일이름, 읽은 위치, 크기)] -- 크기를 아는 것만."""
    out = []
    d = "/proc/%d/fd" % pid
    try:
        fds = os.listdir(d)
    except OSError:
        return out                      # 남의 프로세스이거나 방금 끝났다
    for n in fds:
        try:
            tgt = os.readlink(os.path.join(d, n))
        except OSError:
            continue
        if not tgt.endswith(WATCH_EXT):
            continue
        pos = None
        try:
            with open("/proc/%d/fdinfo/%s" % (pid, n)) as f:
                for line in f:
                    if line.startswith("pos:"):
                        pos = int(line.split()[1])
                        break
        except (IOError, ValueError):
            continue
        try:
            sz = os.path.getsize(tgt)
        except OSError:
            continue
        if pos is None or sz <= 0:
            continue
        out.append((os.path.basename(tgt), pos, sz))
    return out


def mb(n):
    return n / 1048576.0


def dur(sec):
    if sec is None:
        return "?"
    if sec < 60:
        return "%ds" % sec
    if sec < 3600:
        return "%dm %ds" % (sec // 60, sec % 60)
    return "%dh %dm" % (sec // 3600, (sec % 3600) // 60)


def once():
    ps = procs()
    print("=" * 70)
    print("running steps  (%s)" % time.strftime("%H:%M:%S"))
    print("=" * 70)
    if not ps:
        print("  Nothing from this pipeline is running.")
        print("  It finished, or the work is in pt_shell (this cannot see that).")
        print("=" * 70)
        return
    for pid, args, step in ps:
        el, cpu, rss = stat_of(pid)
        busy = ""
        if el and cpu is not None:
            pct = 100.0 * cpu / el if el else 0.0
            busy = "   cpu %3.0f%% of wall" % pct
            if pct < 5:
                busy += "   <- stalled? (disk wait or swap)"
        print("  %-14s pid %-7d  running %s   %dMB%s"
              % (step, pid, dur(el), rss or 0, busy))
        d = ""
        m = re.search(r"--dir\s+(\S+)", args)
        if m:
            d = os.path.basename(m.group(1).rstrip("/"))
            print("      corner : %s" % d)
        files = open_files(pid)
        if not files:
            print("      (no tracked file open -- computing, not reading)")
        for name, pos, sz in sorted(files, key=lambda x: -x[2]):
            bar = int(20.0 * pos / sz)
            print("      %-34s [%s%s] %3d%%  %.0f/%.0fMB"
                  % (name[:34], "#" * bar, "." * (20 - bar),
                     100 * pos // sz, mb(pos), mb(sz)))
    print("=" * 70)


def main():
    watch = "--watch" in sys.argv or "-w" in sys.argv
    if not watch:
        once()
        return
    try:
        while True:
            once()
            print("")
            time.sleep(5)
    except KeyboardInterrupt:
        print("")


if __name__ == "__main__":
    main()
