"""Memory trace, so a run that is Killed still says how it got there.

SIGKILL cannot be caught, so nothing can be written at the moment of death --
not by the OOM killer, not by a scheduler enforcing a limit. What CAN be done
is leave a trail up to it, and read what the kernel kept afterwards.

The trail is a periodic ``[MEM]`` line. The two numbers that matter are kept
apart, because only one of them can kill a run:

  anon  memory with no backing store. Nothing can reclaim it; when this hits
        the limit the process dies.
  file  mapped file pages (the memory-mapped caches this code uses). Backed by
        disk, so the kernel drops them under pressure and reads them again
        later. This number being large is not a problem.

After a kill, ``scripts/why_killed.sh`` reads the cgroup counters, which
outlive the process: a non-zero ``failcnt`` means the memory limit really was
hit, and ``max_usage`` says how high it got.
"""
import os
import threading
import time

_CG = "/sys/fs/cgroup/memory"
_GB = 1024.0 ** 3


def _read_int(path):
    try:
        with open(path) as f:
            v = int(f.read().split()[0])
        return None if v > (1 << 62) else v      # "unlimited" sentinel
    except Exception:
        return None


def limits() -> dict:
    """The ceilings this process is running under, as far as they are visible."""
    out = {"cgroup_limit": _read_int(os.path.join(_CG, "memory.limit_in_bytes"))}
    try:
        import resource
        v = resource.getrlimit(resource.RLIMIT_AS)[0]
        out["rlimit_as"] = None if v == resource.RLIM_INFINITY else v
    except Exception:
        out["rlimit_as"] = None
    return out


def snapshot() -> dict:
    """Current anon/file split, plus the cgroup counters if readable."""
    d = {"anon": 0.0, "file": 0.0}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("RssAnon:"):
                    d["anon"] = int(line.split()[1]) * 1024.0
                elif line.startswith("RssFile:"):
                    d["file"] = int(line.split()[1]) * 1024.0
    except Exception:
        pass
    d["cg_usage"] = _read_int(os.path.join(_CG, "memory.usage_in_bytes"))
    d["cg_limit"] = _read_int(os.path.join(_CG, "memory.limit_in_bytes"))
    d["cg_failcnt"] = _read_int(os.path.join(_CG, "memory.failcnt"))
    return d


def line(tag: str) -> str:
    s = snapshot()
    txt = "[MEM] %-22s anon %6.2f GB  file %6.2f GB" % (tag, s["anon"] / _GB,
                                                        s["file"] / _GB)
    if s["cg_limit"]:
        txt += "  cgroup %.1f/%.1f GB" % (s["cg_usage"] / _GB, s["cg_limit"] / _GB)
    if s["cg_failcnt"]:
        txt += "  (limit hit %d x)" % s["cg_failcnt"]
    return txt


def log(tag: str) -> None:
    print(line(tag), flush=True)


def report_limits() -> None:
    lim = limits()
    parts = []
    if lim["cgroup_limit"]:
        parts.append("cgroup %.1f GB" % (lim["cgroup_limit"] / _GB))
    if lim["rlimit_as"]:
        parts.append("ulimit -v %.1f GB" % (lim["rlimit_as"] / _GB))
    print("[MEM] limit: %s" % (", ".join(parts) if parts else "none visible"),
          flush=True)


_started = False


def start(interval: float = 60.0, step_gb: float = 0.5) -> None:
    """Trace in the background: print whenever anon has moved by step_gb.

    Quiet while nothing changes, so the log stays readable; the point is that
    the LAST line before a kill shows how far it had climbed.
    """
    global _started
    if _started or os.environ.get("SI_MEMLOG", "1") == "0":
        return
    _started = True

    def run():
        last = -1.0
        while True:
            try:
                s = snapshot()
                gb = s["anon"] / _GB
                if abs(gb - last) >= step_gb:
                    last = gb
                    print(line("watch"), flush=True)
            except Exception:
                return
            time.sleep(interval)

    t = threading.Thread(target=run, name="memlog", daemon=True)
    t.start()
