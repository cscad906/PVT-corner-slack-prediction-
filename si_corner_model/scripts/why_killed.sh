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
say " job scheduler"
if command -v bjobs >/dev/null 2>&1; then
  say "   LSF present. A job killed for exceeding a limit shows it in:"
  say "     bjobs -l <jobid>     |  bhist -l <jobid>"
  say "   TERM_MEMLIMIT / TERM_RUNLIMIT there means the scheduler killed it."
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
