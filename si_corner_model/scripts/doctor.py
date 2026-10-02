#!/usr/bin/env python3
"""One file that answers "why is nothing happening". Run it and send the output.

    python3 scripts/doctor.py

Checks, in the order they can go wrong, and prints one line each:

    which copy of this project you are in, and whether it has today's code
    which python is running, and whether it can import what the pipeline needs
    whether the config parses and the report directories exist
    whether the cache carries what the fit needs
    and finally it RUNS `bash scripts/run.sh list` as a subprocess and reports
    how many bytes came back on stdout, on stderr, and the exit status

That last one is the point. "run.sh prints nothing" has three different causes
-- the command never started, it wrote to stderr and the redirect dropped it,
or it really produced nothing -- and they look identical from a terminal. This
tells them apart.

Nothing here writes, builds or trains. It imports nothing it is not reporting
on, and no failure stops the rest: every check is wrapped, so the report is
complete even on a machine where half of it is broken.
"""
import os
import subprocess
import sys

OK, BAD, WARN = "[ ok ]", "[FAIL]", "[warn]"
_problems = []


def say(mark, what, detail=""):
    print("%s %-34s %s" % (mark, what, detail))
    if mark == BAD:
        _problems.append(what)


def check(what, fn, optional=False):
    """Run one check. Any exception is a result, not a crash."""
    try:
        ok, detail = fn()
    except Exception as e:                      # noqa: BLE001
        say(WARN if optional else BAD, what, "%s: %s" % (type(e).__name__, e))
        return False
    say(OK if ok else (WARN if optional else BAD), what, detail)
    return ok


def _run(cmd, **kw):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    out, err = p.communicate()
    return p.returncode, out, err


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("si_corner_model doctor")
    print("=" * 72)
    print("project : %s" % here)
    print("cwd     : %s" % os.getcwd())
    print("python  : %s" % sys.executable)
    print("version : %s" % sys.version.split()[0])
    print("-" * 72)

    # ---------------------------------------------------------------- which copy
    def _which_copy():
        fp = os.path.join(here, "si_model", "run.py")
        if not os.path.exists(fp):
            return False, "si_model/run.py is missing -- wrong directory?"
        with open(fp, encoding="utf-8", errors="replace") as f:
            src = f.read()
        lines = src.count("\n")
        # One name per feature that was asked for and landed in run.py. The
        # point is to NAME what is missing: "unrecognized arguments: --save"
        # from an old copy reads as a bug in the flag, not as a copy that
        # predates it, and the two have completely different fixes.
        want = ("period_norm", "v_transform", "blind_hidden", "runtime.rpt",
                "_retime", '"--save"', "[per corner]", "[TIME]")
        missing = [n for n in want if n not in src]
        if missing:
            return False, ("%d lines, MISSING %s -- this is an OLDER copy. "
                           "Run `git pull` in %s (a flag this copy predates "
                           "shows up as `unrecognized arguments`, which looks "
                           "like a broken flag and is not one)"
                           % (lines, ", ".join(missing), here))
        return True, "%d lines, all %d expected features present" % (lines,
                                                                    len(want))
    check("this copy has today's code", _which_copy)

    def _script(name):
        def go():
            fp = os.path.join(here, "scripts", name)
            return os.path.exists(fp), fp if os.path.exists(fp) else "missing"
        return go
    for name in ("plot.py", "compare_scaling.py"):
        check("scripts/" + name, _script(name), optional=True)

    # ------------------------------------------------------------------- git
    def _git():
        rc, out, _ = _run(["git", "-C", here, "rev-parse", "--short", "HEAD"])
        if rc:
            return False, "not a git checkout (or git unavailable)"
        head = out.decode().strip()
        rc2, br, _ = _run(["git", "-C", here, "rev-parse", "--abbrev-ref", "HEAD"])
        rc3, st, _ = _run(["git", "-C", here, "status", "--porcelain"])
        dirty = len([l for l in st.decode().splitlines() if l.strip()])
        return True, "%s on %s%s" % (head, br.decode().strip(),
                                     "" if not dirty else
                                     "  (%d uncommitted file(s))" % dirty)
    check("git checkout", _git, optional=True)

    # --------------------------------------------------------------- environment
    def _env():
        keep = {k: v for k, v in os.environ.items()
                if k.startswith("SI_") or k in ("PY", "OMP_NUM_THREADS",
                                                "PYTHONPATH", "PYTHONHOME")}
        bad = []
        py = keep.get("PY")
        if py and not os.path.exists(py):
            bad.append("PY=%s does not exist -- run.sh will fail with it. "
                       "unsetenv PY" % py)
        if keep.get("SI_REBUILD", "0") not in ("0", ""):
            bad.append("SI_REBUILD is on: build will re-parse every time")
        if bad:
            return False, "; ".join(bad)
        return True, (", ".join("%s=%s" % kv for kv in sorted(keep.items()))
                      or "nothing set")
    check("environment variables", _env)

    # ------------------------------------------------------------------ imports
    for mod, optional in (("numpy", False), ("yaml", False),
                          ("torch", True), ("matplotlib", True)):
        def _imp(mod=mod):
            m = __import__(mod)
            return True, getattr(m, "__version__", "?")
        check("import %s" % mod, _imp, optional=optional)

    def _imp_pkg():
        sys.path.insert(0, here)
        import si_model.run as r
        return True, os.path.dirname(os.path.abspath(r.__file__))
    check("import si_model.run", _imp_pkg)

    def _which_module():
        """The file `python3 -m si_model.run` ACTUALLY loads.

        run.sh cds to the project and runs `-m si_model.run`, so the copy that
        executes is whichever one the interpreter resolves -- not necessarily
        the one that was just edited. With three checkouts on a machine, or a
        PYTHONPATH pointing at a fourth, editing the right file and running the
        wrong one looks exactly like an edit that did not take: the flag is in
        the file and still missing from the usage line.
        """
        rc, out, err = _run([sys.executable, "-c",
                             "import si_model.run as r; print(r.__file__)"],
                            cwd=here)
        if rc:
            return False, err.decode(errors="replace").strip().splitlines()[-1:]
        got = os.path.realpath(out.decode().strip())
        want = os.path.realpath(os.path.join(here, "si_model", "run.py"))
        if got != want:
            return False, ("`-m si_model.run` loads %s, NOT the %s you are "
                           "editing. Check PYTHONPATH and any installed copy"
                           % (got, want))
        has = "--save" in open(want, encoding="utf-8", errors="replace").read()
        return True, "%s%s" % (got, "" if has else "   (and it has no --save)")
    check("the copy that actually runs", _which_module)

    def _flags_live():
        """Every flag the SOURCE defines, asked of the RUNNING program.

        This is the only check that compares the file with what executes. The
        others read the file, and a file can be perfectly up to date while the
        program that runs is not: Python reuses a cached .pyc whenever the
        source's (mtime, size) are unchanged, so an edit that happens to land
        in the same second at the same length is simply not seen. That is not a
        hypothetical -- it cost half an hour in this project already, and it
        looks exactly like an edit that did not take: the flag is in the file,
        absent from the usage line, and every other check says OK.

        Asked through `-m si_model.run`, the way run.sh asks, so a shadowed
        copy fails here too.
        """
        import re as _re

        src_fp = os.path.join(here, "si_model", "run.py")
        src = open(src_fp, encoding="utf-8", errors="replace").read()
        want = sorted(set(_re.findall(r'add_argument\(\s*"(--[a-z-]+)"', src)))
        if not want:
            return False, "no flags found in %s -- is it the right file?" % src_fp
        rc, out, err = _run([sys.executable, "-m", "si_model.run", "--help"],
                            cwd=here)
        text = (out + err).decode(errors="replace")
        if rc:
            return False, ("`-m si_model.run --help` exited %d: %s" %
                           (rc, text.strip().splitlines()[-1:] or "no output"))
        missing = [f for f in want if f not in text]
        if missing:
            pyc = os.path.join(here, "si_model", "__pycache__")
            return False, ("the source defines %s but the running program does "
                           "NOT offer %s -- the file and what executes disagree."
                           "  Delete the cached bytecode and try again:  "
                           "find %s -name __pycache__ -prune -exec rm -rf {} +"
                           % (", ".join(want[:6]) + ("..." if len(want) > 6 else ""),
                              ", ".join(missing), here)
                           + ("" if os.path.isdir(pyc) else
                              "   (no %s here, so look for a shadowing copy "
                              "instead -- see the check above)" % pyc))
        return True, "all %d flags the source defines are offered, incl. %s" % (
            len(want), "--save" if "--save" in want else want[-1])
    check("the flags the program really offers", _flags_live)

    # ------------------------------------------------------------------- config
    def _config():
        import yaml
        fp = os.path.join(here, "config.yaml")
        with open(fp, encoding="utf-8") as f:
            c = yaml.safe_load(f)
        d = c.get("designs")
        n = len(d) if isinstance(d, (list, dict)) else "auto"
        return True, "mode=%s  designs=%s  temps=%d" % (
            c.get("mode"), n, len(c.get("temps") or []))
    check("config.yaml parses", _config)

    def _models():
        sys.path.insert(0, here)
        from si_model.run import expand, load_project, select
        p = load_project(os.path.join(here, "config.yaml"))
        ms = select(expand(p))
        if not ms:
            return False, "0 models -- designs/temps resolve to nothing"
        miss = [m["name"] for m in ms
                if not os.path.isdir(m["cfg"]["data"]["annotated_dir"])]
        return (not miss), ("%d models, reports found for all"
                            % len(ms) if not miss else
                            "%d models, NO report directory for: %s"
                            % (len(ms), ", ".join(miss[:4])))
    check("models and report directories", _models)

    # -------------------------------------------------------------------- cache
    def _cache():
        import numpy as np
        sys.path.insert(0, here)
        from si_model.run import expand, load_project, select
        p = load_project(os.path.join(here, "config.yaml"))
        ms = select(expand(p))
        have, nogap = [], []
        for m in ms:
            fp = m["cfg"]["data"]["cache"]
            if not os.path.exists(fp):
                continue
            have.append(m["name"])
            try:
                if "cycle_gap" not in np.load(fp, allow_pickle=False).files:
                    nogap.append(m["name"])
            except Exception:                   # noqa: BLE001
                nogap.append(m["name"] + "(unreadable)")
        if not have:
            return False, "no dataset.npz yet -- run `bash scripts/run.sh build`"
        if nogap:
            return False, ("%d/%d built, but no clock edges in: %s -- re-run "
                           "build, the period correction needs them"
                           % (len(have), len(ms), ", ".join(nogap[:4])))
        return True, "%d/%d built, all carry clock edges" % (len(have), len(ms))
    check("cache", _cache, optional=True)

    # ------------------------------------------------- the thing people report
    print("-" * 72)
    print("running `bash scripts/run.sh list` as a subprocess ...")
    try:
        rc, out, err = _run(["bash", os.path.join(here, "scripts", "run.sh"),
                             "list"], cwd=here)
        print("  exit status : %d" % rc)
        print("  stdout      : %d bytes, %d lines" % (len(out), out.count(b"\n")))
        print("  stderr      : %d bytes, %d lines" % (len(err), err.count(b"\n")))
        if out:
            print("  first line  : %s" % out.decode(errors="replace").splitlines()[0])
        if err:
            for l in err.decode(errors="replace").splitlines()[-6:]:
                print("  stderr> %s" % l)
        if rc == 0 and len(out) > 200:
            say(OK, "run.sh list", "works from here")
        elif len(out) + len(err) == 0:
            say(BAD, "run.sh list", "produced NOTHING -- bash could not start it")
        else:
            say(BAD, "run.sh list", "exit %d; read the stderr lines above" % rc)
    except Exception as e:                      # noqa: BLE001
        say(BAD, "run.sh list", "%s: %s" % (type(e).__name__, e))

    print("=" * 72)
    if _problems:
        print("%d problem(s): %s" % (len(_problems), ", ".join(_problems)))
        print("Send this whole output as it is.")
        return 1
    print("No problems found. If a command still does nothing in YOUR shell,")
    print("the difference is the shell, not this copy -- check `alias bash`,")
    print("a leftover PY, and whether output is being redirected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
