#!/usr/bin/env bash
# Why did the last run die?  A process killed by SIGKILL cannot write anything
# itself, so this reads what outlives it.
#
#   bash scripts/why_killed.sh [logfile]
#
# Run it in the SAME shell/job as the run that died: the cgroup counters below
# belong to that session, and starting a new one resets what you can see.
set -uo pipefail
LOG="${1:-}"
CG=/sys/fs/cgroup/memory
GB=$((1024*1024*1024))

say() { printf '%s\n' "$*"; }
num() { [ -r "$1" ] && cat "$1" 2>/dev/null || echo ""; }

say "=================================================================="
say " why was it killed"
say "=================================================================="

lim=$(num $CG/memory.limit_in_bytes)
peak=$(num $CG/memory.max_usage_in_bytes)
fail=$(num $CG/memory.failcnt)
if [ -n "$lim" ]; then
  if [ "$lim" -gt $((1<<62)) ] 2>/dev/null; then limtxt="unlimited";
  else limtxt="$((lim/GB)) GB"; fi
  say ""
  say " memory cgroup (survives the process)"
  say "   limit        : $limtxt"
  [ -n "$peak" ] && say "   peak usage   : $((peak/GB)) GB"
  [ -n "$fail" ] && say "   limit hit    : $fail times"
  if [ -n "$fail" ] && [ "$fail" != "0" ]; then
    say "   -> MEMORY. The limit was reached. Lower it: run one model at a"
    say "      time (--design/--temp), set crosstalk_subdir: null to drop SI,"
    say "      or reduce train.batch_paths / model.enc_dim."
  else
    say "   -> the memory limit was NOT hit; look below."
  fi
fi

say ""
say " kernel OOM killer (needs dmesg access)"
if dmesg 2>/dev/null | grep -qiE 'out of memory|oom-kill'; then
  dmesg 2>/dev/null | grep -iE 'out of memory|oom-kill|Killed process' | tail -5 | sed 's/^/   /'
else
  say "   nothing found (either no OOM, or dmesg is not readable here)"
fi

say ""
say " other limits (a run killed for these looks identical to an OOM)"
say "   wall/CPU time, file size, processes -- current shell:"
bash -c 'printf "     cpu-time  %s s\n     file-size %s blocks\n     nproc     %s\n     virtual   %s\n" \
         "$(ulimit -t)" "$(ulimit -f)" "$(ulimit -u)" "$(ulimit -v)"' 2>/dev/null

say ""
say " disk (this pipeline streams large arrays to files)"
for d in . /tmp "${TMPDIR:-/tmp}"; do
  [ -d "$d" ] && df -h "$d" 2>/dev/null | tail -1 | sed "s|^|   $d  |"
done
if command -v quota >/dev/null 2>&1; then
  q=$(quota -s 2>/dev/null | tail -2)
  [ -n "$q" ] && { say "   quota:"; printf '%s\n' "$q" | sed 's/^/     /'; }
fi

say ""
say " job scheduler"
# The id from the environment if we are still inside the job, else the one the
# run itself printed into the log -- that is the whole reason it is printed.
JID="${LSB_JOBID:-${SLURM_JOB_ID:-${PBS_JOBID:-}}}"
if [ -z "$JID" ] && [ -n "$LOG" ] && [ -r "$LOG" ]; then
  JID=$(grep -m1 '\[JOB\]' "$LOG" 2>/dev/null | sed -n 's/.*job \([0-9][0-9]*\).*/\1/p')
fi
[ -n "$JID" ] && say "   job id: $JID" || say "   job id: unknown (none in env, none in the log)"
if command -v bjobs >/dev/null 2>&1; then
  if [ -n "$JID" ]; then
    say "   --- bhist -l $JID (termination reason) ---"
    bhist -l "$JID" 2>&1 | grep -iE 'TERM_|Exited|Completed|MEM|Killed' | head -8 | sed 's/^/     /'
    say "   --- bjobs -l $JID ---"
    bjobs -l "$JID" 2>&1 | grep -iE 'TERM_|MEMLIMIT|RUNLIMIT|Status' | head -6 | sed 's/^/     /'
  fi
  say "   LSF present. A job killed for exceeding a limit shows it in:"
  say "     bjobs -l <jobid>     |  bhist -l <jobid>"
  say "   Look for TERM_* :  TERM_MEMLIMIT (memory) TERM_RUNLIMIT (wall clock)"
  say "                      TERM_CPULIMIT (cpu) TERM_OWNER/TERM_ADMIN (killed by hand)"
else
  say "   no LSF client on PATH"
fi

if [ -n "$LOG" ] && [ -r "$LOG" ]; then
  say ""
  say " last [MEM] lines of $LOG"
  grep '\[MEM\]' "$LOG" | tail -5 | sed 's/^/   /'
  say ""
  say " last 5 lines"
  tail -5 "$LOG" | sed 's/^/   /'
fi
say "=================================================================="
