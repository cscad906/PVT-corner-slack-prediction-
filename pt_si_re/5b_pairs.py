#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5b - crosstalk 쌍 리포트 3단계: PT 출력에서 victim-aggressor 쌍을 뽑는다.

    python3 5b_pairs.py --dir <코너폴더>

넣는 것   xtalk/context_raw.rpt   (xtalk_all.tcl 이 만든 PT 원문)
나오는 것 xtalk/active_features.tsv         쌍 하나가 한 줄
          xtalk/victim_load_pins.txt        다음 PT 단계에서 물어볼 핀
          xtalk/aggressor_nets.txt          다음 PT 단계에서 물어볼 넷

여기까지 하면 aggressor 별 bump 와 coupling cap 이 나옵니다. 다만 aggressor 의
**driver 핀이 언제 도착하는지**(arrival window, slew)는 아직 없습니다. 그 핀들은
우리 경로에 없는 남의 넷이라 pin_attr.txt 에 안 들어 있기 때문입니다.
그래서 PT 를 한 번 더 돌려야 하고, 그 목록이 위 txt 두 개입니다.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()

HERE = os.path.dirname(os.path.abspath(__file__))
XTALK = os.path.join(HERE, "_engine", "xtalk")

CODE_INFO = {
    "E-NOENGINE": ("패키지 파일(_engine/xtalk/)이 없습니다",
                   "pt_si_re 폴더를 통째로 옮기세요. _engine/ 이 빠지면 "
                   "crosstalk 단계가 돌지 않습니다."),
    "E-NORAW":    ("PT 출력(context_raw.rpt)이 없습니다",
                   "pt_shell 에서 pt/xtalk_all.tcl (hold 면 xtalk_all_hold.tcl) 을 "
                   "먼저 돌려 주세요."),
    "E-PARSE":    ("PT 출력을 읽다가 실패했습니다",
                   "xtalk/context_raw.rpt 을 열어 앞부분이 정상인지 보세요."),
    "E-NOPAIR":   ("victim-aggressor 쌍이 하나도 안 나왔습니다",
                   "SI 가 꺼져 있거나 SPEF 에 coupling 이 없을 수 있습니다. "
                   "PT 에서 si_enable_analysis 와 read_parasitics "
                   "-keep_capacitive_coupling 을 확인해 주세요."),
    "W-NOACTIVE": ("실제로 영향을 준 aggressor 가 하나도 없습니다",
                   "값이 전부 0 인 리포트가 됩니다. SI 설정을 확인해 보세요."),
}


def code(c, *msg):
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  정상 종료           [ %s ]" % c)
        print("=" * 66)
        return
    what, todo = CODE_INFO.get(c, ("", ""))
    print("  %s" % ("문제 발생" if c.startswith("E-") else "확인 필요"))
    if what:
        print("    무엇이   : %s" % what)
        print("    하실 일  : %s" % todo)
    print("")
    print("    에러 코드: %s" % c)
    print("    (해결이 안 되면 이 코드를 알려주세요)")
    print("=" * 66)
    sys.exit(1 if c.startswith("E-") else 0)


def run(script, *a, **kw):
    cmd = [sys.executable, os.path.join(XTALK, script)] + list(a)
    env = dict(os.environ)
    env.update(kw.get("env", {}))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    out = p.communicate()[0].decode("utf-8", "replace")
    return p.returncode == 0, out


def count_rows(path):
    if not os.path.isfile(path):
        return 0
    with open(path, "r", errors="ignore") as f:
        return max(0, sum(1 for _ in f) - 1)


def count_lines(path):
    if not os.path.isfile(path):
        return 0
    with open(path, "r", errors="ignore") as f:
        return sum(1 for _ in f)



def need_parser(name):
    """_engine/xtalk/ 의 파서가 있는지 먼저 본다.

    없으면 '리포트 생성 실패' 같은 엉뚱한 안내가 나와 엉뚱한 데를 뒤지게 된다.
    패키지를 옮길 때 _engine/ 을 빠뜨리면 실제로 이렇게 된다.
    """
    p = os.path.join(XTALK, name)
    if not os.path.isfile(p):
        code("E-NOENGINE",
             "[ 실패 ] 패키지 파일이 없습니다: %s" % p,
             "         _engine/xtalk/ 폴더가 통째로 필요합니다.",
             "         패키지를 옮길 때 _engine/ 을 빠뜨리지 않았는지 보세요.")

def main():
    ap = argparse.ArgumentParser(
        description="crosstalk 쌍 리포트 3단계 - PT 출력에서 쌍을 뽑는다.")
    ap.add_argument("--dir", default=".",
                    help="**코너 폴더 하나** (안에 xtalk/ 이 있는 폴더)")
    ap.add_argument("--corner", default=None,
                    help="코너 이름. 안 주면 폴더 이름을 쓴다")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup(max) / hold(min). xtalk_all.tcl 쪽과 같아야 한다")
    ap.add_argument("--xtalk", default=None,
                    help="xtalk 폴더 절대경로를 직접 줄 때. "
                         "주면 --dir 아래 xtalk/ 를 찾지 않는다")
    args = ap.parse_args()

    for _p in ['parse_path_context_delay_calculation.py', 'prepare_compact_timing_window_requests.py']:
        need_parser(_p)

    d = args.dir
    work = args.xtalk or os.path.join(d, "xtalk")
    # --xtalk 로 폴더를 직접 줬으면 코너 이름은 그 폴더의 부모에서 뽑는다
    # (xtalk/ 의 부모가 코너 폴더라는 규약은 그대로다).
    _base = os.path.dirname(os.path.abspath(work)) if args.xtalk else os.path.abspath(d)
    corner = args.corner or os.path.basename(_base)

    print("=" * 68)
    print("5b - crosstalk 쌍 뽑기")
    print("=" * 68)

    victim = os.path.join(work, "path_victim_nets.tsv")
    ctx = os.path.join(work, "unique_contexts.tsv")
    raw = os.path.join(work, "context_raw.rpt")
    summary = os.path.join(work, "context_summary.tsv")
    feats = os.path.join(work, "active_features.tsv")

    if not os.path.isfile(raw):
        code("E-NORAW", "[ 실패 ] PT 출력이 없습니다: %s" % raw)

    print("  PT 출력 : %s  (%.1fMB)" % (raw, os.path.getsize(raw) / 1048576.0))

    ok, out = run("parse_path_context_delay_calculation.py",
                  victim, ctx, raw, summary, feats,
                  env={"PT_FEATURE_CORNER": corner,
                       "PT_FEATURE_ANALYSIS_TYPE": args.mode,
                       "PT_FEATURE_VOLTAGE": "",
                       "PT_FEATURE_TEMPERATURE": ""})
    if not ok:
        code("E-PARSE", "[ 실패 ] PT 출력 파싱 실패", out[-800:])

    vpins = os.path.join(work, "victim_load_pins.txt")
    anets = os.path.join(work, "aggressor_nets.txt")
    ok, out = run("prepare_compact_timing_window_requests.py", feats, vpins, anets)
    if not ok:
        code("E-PARSE", "[ 실패 ] 다음 단계 목록 만들기 실패", out[-800:])

    n_row = count_rows(feats)
    n_vp = count_lines(vpins)
    n_an = count_lines(anets)

    print("")
    print("-" * 68)
    print("  쌍(줄)              : %d" % n_row)
    print("  물어볼 victim 핀    : %d" % n_vp)
    print("  물어볼 aggressor 넷 : %d" % n_an)
    print("-" * 68)

    if n_row == 0:
        code("E-NOPAIR", "[ 실패 ] 쌍이 0개입니다.")
    if n_an == 0:
        code("W-NOACTIVE", "[ 주의 ] 실제로 영향을 준 aggressor 가 0개입니다.")

    # 도착시각 파일이 이미 있으면(xtalk_all.tcl 로 한 번에 돌린 경우) PT 는 끝이다.
    vw = os.path.join(work, "victim_windows.tsv")
    aw = os.path.join(work, "aggressor_windows.tsv")
    if os.path.exists(vw) and os.path.exists(aw):
        print("[ 정상 ] 쌍 %d줄. 도착시각 파일이 이미 있습니다 -- PT 는 끝났습니다." % n_row)
        print("         다음은 셸에서:")
        print("           python3 %s %s"
              % (os.path.join(HERE, "5c_report.py"),
                 ("--xtalk %s" % os.path.abspath(work)) if args.xtalk
                 else ("--dir %s" % os.path.abspath(d))))
    else:
        print("[ 주의 ] 쌍 %d줄. 그런데 도착시각 파일이 없습니다." % n_row)
        print("         xtalk/victim_windows.tsv 와 aggressor_windows.tsv 가")
        print("         있어야 5c 가 돕니다. xtalk_all.tcl 이 끝까지 돌았는지")
        print("         (화면에 [ OK-XTALK ]) 확인해 주세요.")
    code("OK-XPAIR")


if __name__ == "__main__":
    main()
