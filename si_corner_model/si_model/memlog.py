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
import resource
import shutil
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


_T0 = time.time()
_WATCH_DIR = [None]          # filesystem the cache/spill lives on


def watch_dir(path: str) -> None:
    """Point the disk figure at the filesystem this run actually writes to."""
    _WATCH_DIR[0] = path


def line(tag: str) -> str:
    s = snapshot()
    txt = "[MEM] %-22s anon %6.2f GB  file %6.2f GB" % (tag, s["anon"] / _GB,
                                                        s["file"] / _GB)
    if s["cg_limit"]:
        txt += "  cgroup %.1f/%.1f GB" % (s["cg_usage"] / _GB, s["cg_limit"] / _GB)
    if s["cg_failcnt"]:
        txt += "  (limit hit %d x)" % s["cg_failcnt"]
    # Memory is only one of the ways a run is killed. Wall and CPU time are
    # what a scheduler enforces, and free disk is a risk this pipeline created
    # for itself by streaming the large arrays to files.
    cpu = resource.getrusage(resource.RUSAGE_SELF).ru_utime
    txt += "  | %.0fm wall %.0fm cpu" % ((time.time() - _T0) / 60.0, cpu / 60.0)
    d = _WATCH_DIR[0]
    if d:
        try:
            free = shutil.disk_usage(d).free / _GB
            txt += "  disk-free %.0f GB" % free
        except Exception:
            pass
    try:
        n = len(os.listdir("/proc/self/task"))
        if n > 64:
            txt += "  threads %d" % n
    except Exception:
        pass
    return txt


def log(tag: str) -> None:
    print(line(tag), flush=True)


# Scheduler identifiers, in the order they are worth reporting. Without the
# job id in the log there is no way back to the scheduler's own record of why
# a job ended -- and that record is the only place a wall-clock or admin kill
# is written down.
_JOB_VARS = (("LSF", "LSB_JOBID"), ("LSF", "LSB_BATCH_JID"),
             ("Slurm", "SLURM_JOB_ID"), ("PBS", "PBS_JOBID"),
             ("SGE", "JOB_ID"))


def report_job() -> None:
    """Host, pid and job id -- printed once, so a killed run can be looked up."""
    import socket
    bits = ["host %s" % socket.gethostname(), "pid %d" % os.getpid()]
    seen = set()
    for kind, var in _JOB_VARS:
        v = os.environ.get(var)
        if v and v not in seen:
            seen.add(v)
            bits.append("%s job %s" % (kind, v))
    for var, label in (("LSB_QUEUE", "queue"), ("LSB_JOBNAME", "name")):
        if os.environ.get(var):
            bits.append("%s %s" % (label, os.environ[var]))
    print("[JOB] %s" % "  ".join(bits), flush=True)
    if not seen:
        print("[JOB] no scheduler job id in the environment -- if this was "
              "submitted (ub_sub / bsub), run from inside that job so a kill "
              "can be traced back to it", flush=True)


def report_limits() -> None:
    """Print every ceiling that is visible, not just the memory one.

    A run killed for wall-clock or CPU time looks exactly like one killed for
    memory -- a bare "Killed" -- so the limits worth blaming are all listed up
    front, before anything has had a chance to hit one.
    """
    lim = limits()
    parts = []
    if lim["cgroup_limit"]:
        parts.append("memory cgroup %.1f GB" % (lim["cgroup_limit"] / _GB))
    if lim["rlimit_as"]:
        parts.append("ulimit -v %.1f GB" % (lim["rlimit_as"] / _GB))
    for label, attr, scale, unit in (("cpu-time", "RLIMIT_CPU", 3600.0, "h"),
                                     ("file-size", "RLIMIT_FSIZE", _GB, "GB")):
        try:
            v = resource.getrlimit(getattr(resource, attr))[0]
            if v != resource.RLIM_INFINITY:
                parts.append("%s %.1f%s" % (label, v / scale, unit))
        except Exception:
            pass
    d = _WATCH_DIR[0]
    if d:
        try:
            parts.append("disk-free %.0f GB" % (shutil.disk_usage(d).free / _GB))
        except Exception:
            pass
    print("[MEM] limits: %s" % (", ".join(parts) if parts else "none visible"),
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
