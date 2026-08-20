#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4 - round2 아래 코너 폴더 전부에 같은 단계를 돌린다.

    python3 4_all_corners.py --root setup                    # 묶음 1 (annotation)
    python3 4_all_corners.py --root setup --phase 2          # 묶음 2 (crosstalk)
    python3 4_all_corners.py --root hold  --phase 2 --mode hold
    python3 4_all_corners.py --root setup --only 2b          # 한 단계만
    python3 4_all_corners.py --root setup --skip-done        # 이어서

Dist/Res 는 **받은 표**로 채운다(2b_distres_table.py). 표는 코너 폴더마다
resdist_map.txt 로 들어 있어야 한다. Res 는 온도에 따라 다르므로, 코너 폴더에
그 코너의 온도에 맞는 표를 두는 것이다.

SPEF 는 이제 묶음 1 에 필요 없다. --spef / --spef-root 는 2c 가 N/A 원인을
진단할 때만 쓰이는 선택 사항이다.

--spef-root 는 SPEF 가 여러 개 든 폴더다. --root 와 같은 폴더여도 된다
(코너 탐색은 .rpt 를 가진 하위 폴더만 보므로 .spef 와 섞이지 않는다).

코너가 10개 넘어가면 폴더 이름을 하나씩 치는 게 일이라 만든 것이다.
하는 일은 아래를 코너마다 반복하는 것뿐이고, 새로 계산하는 것은 없다.

  묶음 1 -- annotation
    2a_cpin.py            --dir <코너폴더>
    2b_distres_table.py   --dir <코너폴더>      <- 받은 표를 읽는다. SPEF 안 씀
    2c_merge.py           --dir <코너폴더>
  묶음 2 -- crosstalk (담당자분께 받은 xtalk/ 가 있어야 한다)
    5a_contexts.py --dir <코너폴더>
    5b_pairs.py    --dir <코너폴더>
    5c_report.py   --dir <코너폴더>

PT 는 두 묶음 사이가 아니라 둘 다보다 **앞**에 있다. 담당자분이 fixed_paths.tcl
과 xtalk_all.tcl 을 돌려 주신 결과를 받아서 이 둘을 돈다. 서로 독립이라 순서도
상관없다.

코너 이름은 폴더 이름을 그대로 쓴다(2회차에서 리포트 이름과 같게 지어진다).

SPEF 고르는 순서
    1) 코너 폴더 안의 design.spef 가 있으면 그것       <- 코너 하나만 다를 때
    2) --spef-root <폴더> 를 줬으면 코너 이름에 맞는 것을 그 폴더에서 고른다
    3) 없으면 --spef 로 준 파일 하나                   <- 전 코너 공용

    --spef-root 는 **온도와 RC 코너(BEOL)** 로만 맞춘다. 전압은 안 본다 --
    기생 RC 는 배선 형상과 온도로 정해지고 전원 전압과는 무관하다. 그래서
    tt0p6v25c_Cnom / tt0p7v25c_Cnom / tt0p8v25c_Cnom 은 같은 SPEF 를 쓴다.

        코너 이름  tt0p6v25c_Cnom          ->  25C, Cnom
        SPEF 이름  ....Cnom_model_25.spef  ->  25C, Cnom     ... 짝

    이름만으로 안 갈리면 SPEF 머리말을 읽는다(StarRC/ICC2 가 찍어 준다).
        // PARASITIC_TECH Cnom_model at 25.000 degree

    **한 코너라도 못 고르면 아무것도 돌리지 않고 멈춘다.** 반쯤 돌려 놓고
    실패하면 어느 코너가 어느 SPEF 로 만들어진 것인지 나중에 알 수 없고,
    틀린 SPEF 로 돌면 숫자가 그럴듯하게 나와 한참 뒤에야 드러난다.

Cpin 고르는 순서 (현장에서 pin_attr.txt 대신 Cpin 표를 받았을 때)
    1) 코너 폴더 안의 cpin_map.txt 가 있으면 그것      <- 코너마다 받았을 때
    2) 없으면 --cpin-map 으로 준 파일
    3) 둘 다 없으면 각 코너의 pin_attr.txt 를 쓴다(dump_attr.tcl 로 뽑던 방식)

    **`cpin_map.txt` 라는 이름은 우리가 정한 규약이다.** 이 이름으로 만들어
    주는 코드는 없다 -- 받은 파일을 코너 폴더에 그 이름으로 두면 배치가
    알아서 집는다는 뜻이다(SPEF 의 `design.spef` 와 같은 방식).
    다른 이름을 쓰려면 아래 CPIN_MAP_NAME 한 줄만 고치면 된다.
    코너를 하나씩 돌릴 때는 이름과 무관하다 -- `--cpin-map <경로>` 로 준다.

    **Cpin 은 코너마다 다르다.** 0.6V 와 0.8V 를 재 보면 중앙값 6%,
    최대 8% 차이가 난다. 한 파일을 --cpin-map 으로 전 코너에 돌려 쓰면
    그만큼 틀린다. 코너별로 받았으면 각 폴더에 cpin_map.txt 로 두는 게 맞다.

한 코너가 실패해도 멈추지 않고 끝까지 돈 뒤, 맨 아래에 코너별 결과를 표로
보여 준다. 실패가 하나라도 있으면 종료 코드 1.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8, wopen
force_utf8()
from find_rpt import find_rpt

# 코너 폴더에서 이 이름을 찾으면 그것을 Cpin 표로 쓴다.
# 현장에서 받는 파일 이름이 정해져 있으면 여기만 바꾸면 된다.
CPIN_MAP_NAME = "cpin_map.txt"

# 코드 -> 무슨 뜻인가. 맨 끝 '문제 있는 코너' 표에서 코드만 보고 코드표.md 를
# 뒤지지 않아도 되게, 한 줄 설명을 같이 찍는다.
CODE_MEANS = {
    "E-NOFILE":   "입력 파일이 없음",
    "E-NORPT":    "코너 폴더에 .rpt 가 없음",
    "E-RPTMANY":  ".rpt 가 여러 개라 어느 것인지 모름",
    "E-NONET":    "리포트에 (net) 줄이 없음 -- report_timing 에 -nets 누락",
    "E-NOATTR":   "Cpin 표에서 값을 못 읽음",
    "E-PINNAME":  "리포트의 핀 이름이 Cpin 표와 안 맞음",
    "E-RES0":     "SPEF 에서 Res 를 하나도 못 구함 -- SPEF 가 이 코너 것이 맞는지",
    "E-NOENGINE": "_engine/xtalk/ 가 없음 -- 폴더째 복사했는지",
    "E-NORAW":    "PT 출력(context_raw.rpt)이 없거나 빔 -- xtalk_all.tcl 먼저",
    "E-NO5A":     "5a 결과가 없거나 빔 -- 5a 를 먼저",
    "E-MODE":     "PT 출력의 setup/hold 가 --mode 와 반대",
    "E-PARSE":    "PT 출력을 읽다가 실패",
    "E-NOPAIR":   "victim-aggressor 쌍이 0개 -- SI 설정 확인",
    "W-CPIN":     "Cpin 이 비어 있는 줄이 많음",
    "W-RES":      "Dist/Res 가 비어 있는 줄이 많음",
    "W-NA":       "결과에 N/A 가 남아 있음",
    "W-NOACTIVE": "영향을 준 aggressor 가 0개",
    "W-CPINCOL":  "Cpin 열을 잘못 집었을 수 있음",
    "NOSPEF":     "SPEF 가 없어 건너뜀",
    "SKIP":       "--skip-done 으로 건너뜀",
    "-":          "앞 단계가 실패해 안 돎",
    "?":          "코드를 못 읽음 -- 그 단계를 직접 돌려 화면을 보세요",
}


def fmt_dur(sec):
    """초 -> '3분 12초' 처럼. 진행 상황에 쓰므로 대충이면 된다."""
    sec = int(sec)
    if sec < 60:
        return "%d초" % sec
    if sec < 3600:
        return "%d분 %d초" % (sec // 60, sec % 60)
    return "%d시간 %d분" % (sec // 3600, (sec % 3600) // 60)


def resolve_spefs(corners, args):
    """코너마다 쓸 SPEF 를 **한 코너도 돌리기 전에** 전부 정한다.

    -> ({코너: 경로}, [(코너, 왜 못 골랐나)])

    미리 정하는 이유가 두 가지다.
      - 코너 16개를 한참 돌린 뒤 마지막에서 'SPEF 를 못 골랐다' 가 나오면
        그때까지 돌린 것이 헛수고다.
      - SPEF 를 잘못 물리면 결과가 **그럴듯하게** 나온다. 숫자가 나오니까
        맞은 줄 알고 넘어가고, 한참 뒤 모델이 이상할 때야 알게 된다.
    """
    picker = None
    if args.spef_root:
        import spef_match
        spefs = spef_match.list_spefs(args.spef_root)
        picker = (spef_match, spefs)

    out, bad = {}, []
    for name, d in corners:
        local = os.path.join(d, "design.spef")
        if os.path.isfile(local):
            out[name] = local
            continue
        if picker is not None:
            mod, spefs = picker
            p, why = mod.pick(name, spefs)
            if p:
                out[name] = p
            else:
                bad.append((name, why))
            continue
        if args.spef:
            if os.path.isfile(args.spef):
                out[name] = args.spef
            else:
                bad.append((name, "--spef 파일이 없습니다: %s" % args.spef))
            continue
        bad.append((name, "design.spef / --spef-root / --spef 중 하나가 필요합니다"))
    return out, bad

# 단계는 PT 를 사이에 두고 두 묶음으로 나뉜다. PT 는 파이썬에서 못 부르므로
# 묶음 1 이 끝나면 pt_shell 로 한 번 갔다 와야 한다.
#
#   [PT: 담당자분] -> 묶음 1(annotation) / 묶음 2(crosstalk)
#
# 예전에는 PT 를 두 번(계산 -> 파이썬 -> 도착시각) 다녀와 묶음이 셋이었다.
# 지금은 tcl 이 자기가 받은 출력에서 aggressor 이름을 직접 긁으므로 한 번이다.
#
# (표시이름, 스크립트, SPEF 가 필요한가, 결과 파일)
PHASES = {
    # 묶음 1 = annotation, 묶음 2 = crosstalk. 갈래가 그대로 나뉜다.
    "1": [
        ("2a cpin",     "2a_cpin.py",     False, "cpin.tsv"),
        ("2b distres",  "2b_distres_table.py", False, "distres.tsv"),
        ("2c merge",    "2c_merge.py",    False, "*_fixed_annotated.txt"),
    ],
    "2": [
        ("5a contexts", "5a_contexts.py", False, "xtalk/path_victim_nets.tsv"),
        ("5b pairs",    "5b_pairs.py",    False, "xtalk/active_features.tsv"),
        ("5c report",   "5c_report.py",   False, "xtalk/compact_flat.tsv"),
    ],
}

# PT 를 위한 wrapper 는 만들지 않는다.
# PT 는 묶음 사이가 아니라 **둘 다보다 앞**에 있다. 담당자분이 fixed_paths.tcl 과
# xtalk_all.tcl 을 돌려 주시고, 우리는 그 결과를 받아 1과 2를 돈다. 우리 쪽에서
# pt_shell 을 열 일이 없으므로 "이걸 source 하세요" 라고 안내하면 안 된다.


NEXT_HINT = {
    "1": ("annotation 이 끝났습니다. 이어서 crosstalk 을 돌리세요:",
          "    %(py)s 4_all_corners.py --root %(root)s --phase 2",
          "(담당자분께 받은 xtalk/ 가 코너 폴더마다 있어야 합니다.",
          " 먼저 확인하려면 8_check_xtalk.py --root %(root)s)"),
    "2": ("끝입니다. 코너마다 아래 두 파일이 학습 입력입니다.",
          "    <코너>_fixed_annotated.txt",
          "    <코너>.path_context_si_compact.by_path.rpt",
          ""),
}


def corner_dirs(root):
    """root 아래에서 .rpt 를 가진 폴더만 코너로 본다."""
    out = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        rpt, _, _ = find_rpt(d)
        if rpt:
            out.append((name, d))
    return out


def step_done(work_dir, product):
    """그 단계 결과가 이미 있나. product 가 *로 시작하면 확장자 매칭."""
    if product.startswith("*"):
        suffix = product[1:]
        return any(n.endswith(suffix) for n in os.listdir(work_dir))
    return os.path.isfile(os.path.join(work_dir, product))


def show(line, sink=None):
    """하위 스크립트 출력 한 줄을 찍는다.

    sink 를 주면 화면에 바로 안 찍고 거기에 모은다. --jobs 로 코너를 동시에
    돌릴 때 여러 코너의 출력이 한 줄씩 뒤섞이면 못 읽기 때문이다. 코너가
    끝날 때 그 코너 것만 한 덩어리로 찍는다.

    python2 에서는 파이프로 읽은 줄이 unicode 라, 그대로 print 하면 터미널
    인코딩에 따라 한글에서 죽는다. 그래서 2 에서만 utf-8 로 되돌려 찍는다.
    """
    if sys.version_info[0] < 3:
        line = line.encode("utf-8")
    if sink is None:
        print("      " + line)
    else:
        sink.append("      " + line)


def run_step(script, args, quiet, sink=None):
    """하위 스크립트를 지금 python 으로 돌린다. (성공여부, 마지막코드) 반환."""
    cmd = [sys.executable, os.path.join(HERE, script)] + args
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail, last_code = [], ""
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if not quiet:
            show(line, sink)
        tail.append(line)
        # 정상은 "  정상 종료   [ OK-CPIN ]", 문제/주의는 "    에러 코드: W-NA"
        # 두 형식 다 잡아야 한다.
        for tok in ("OK-", "W-", "E-"):
            i = line.find("[ " + tok)
            if i >= 0:
                last_code = line[i + 2:].split("]")[0].strip()
        i = line.find(u"에러 코드:")
        if i >= 0:
            last_code = line[i + len(u"에러 코드:"):].strip()
    p.wait()
    if not last_code:
        # 코드가 안 찍혔으면 마지막 몇 줄이라도 보여 준다
        for line in tail[-3:]:
            show(line, sink)
    return p.returncode == 0, (last_code or "?")


def run_corner(name, d, steps, args, spef, cmap, sink, progress=None):
    """코너 하나를 단계 순서대로 돈다. -> (코드들, 걸린 것들, 걸린 시간)

    코너끼리는 서로 안 건드린다. 각자 자기 폴더에만 쓰고, SPEF 와 Cpin 표는
    읽기만 한다. 그래서 --jobs 로 동시에 돌려도 된다.

    sink 가 None 이면 그때그때 화면에 찍는다(하나씩 돌 때). 리스트를 주면
    거기에 모은다(동시에 돌 때 -- 뒤섞이면 못 읽으므로 코너가 끝날 때 한
    덩어리로 찍는다).

    progress 를 주면 **단계 하나가 끝날 때마다** (단계, 코드, 걸린시간) 로
    부른다. 동시에 돌 때 코너가 다 끝나기를 기다리지 않고 진행을 보여 주려는
    것이다. 여러 스레드가 같이 부르므로 부르는 쪽에서 lock 을 잡아야 한다.
    """
    def note(label, code, took):
        if progress is not None:
            progress(name, label, code, took)
    def say(line):
        if sink is None:
            print(line)
            sys.stdout.flush()      # 파이프로 넘길 때도 바로 보이게
        else:
            sink.append(line)

    t_corner = time.time()
    codes, trouble = [], []
    for label, script, need_spef, product in steps:
        if args.skip_done and step_done(d, product):
            say("  %-12s 건너뜀 (%s 이미 있음)" % (label, product))
            codes.append("SKIP")
            note(label, "SKIP", "-")
            continue
        if need_spef and not (spef and os.path.isfile(spef)):
            say("  %-12s 건너뜀 (SPEF 없음)" % label)
            codes.append("NOSPEF")
            note(label, "NOSPEF", "-")
            continue

        call = ["--dir", d]
        if need_spef:
            call += ["--spef", spef]
        if script == "2a_cpin.py" and cmap:
            call += ["--cpin-map", cmap]
        # 2c 는 SPEF 가 없어도 돌지만, N/A 가 나면 원인 진단에 쓴다.
        if script == "2c_merge.py" and spef and os.path.isfile(spef):
            call += ["--spef", spef]
        if script in ("2c_merge.py", "5b_pairs.py", "5c_report.py"):
            call += ["--corner", name]
        if script == "5b_pairs.py":
            call += ["--mode", args.mode]

        say("  %-12s 실행" % label)
        t0 = time.time()
        ok, c = run_step(script, call, args.quiet, sink)
        codes.append(c)
        took = fmt_dur(time.time() - t0)
        if not ok:
            say("  %-12s 실패 (%s) -> 이 코너의 남은 단계는 건너뜁니다"
                        % (label, took))
            note(label, c, took)
            trouble.append((name, label, c))
            codes += ["-"] * (len(steps) - len(codes))
            break
        say("  %-12s 끝 (%s) [ %s ]" % (label, took, c))
        note(label, c, took)
        if c.startswith("W-"):
            trouble.append((name, label, c))
    return codes, trouble, time.time() - t_corner


def main():
    ap = argparse.ArgumentParser(
        description="round2 아래 코너 폴더 전부에 2a/2b/2c/3 을 돌린다.")
    ap.add_argument("--root", required=True,
                    help="코너 폴더들이 **들어 있는 상위 폴더** (예: round2). 코너 폴더 하나가 아니다")
    ap.add_argument("--spef-root", "--spef-dir", default=None,
                    help="SPEF 들이 든 **폴더**. 코너 이름의 온도와 RC 코너"
                         "(BEOL)로 맞는 것을 고른다. 전압은 안 본다. 한 코너"
                         "라도 못 고르면 아무것도 돌리지 않고 멈춘다")
    ap.add_argument("--spef", default=None,
                    help="모든 코너가 함께 쓸 SPEF 파일 하나. 코너 폴더에 design.spef 가 "
                         "있으면 그쪽이 우선한다")
    ap.add_argument("--cpin-map", default=None,
                    help="모든 코너가 함께 쓸 Cpin 표(2열 이상). 코너 폴더에 "
                         "%s 가 있으면 그쪽이 우선한다. 안 주면 " % CPIN_MAP_NAME +
                         "각 코너의 pin_attr.txt 를 쓴다")
    ap.add_argument("--phase", default="1", choices=["1", "2"],
                    help="1=2a~5a(기본), 2=5b~5c. 사이에 pt_shell 을 한 번 다녀온다")
    ap.add_argument("--only", default=None,
                    help="그 묶음 안에서 일부만. 쉼표로 (예: 2a,2b)")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup / hold. 5b 에 넘긴다")
    ap.add_argument("--skip-done", action="store_true",
                    help="결과 파일이 이미 있으면 그 단계는 건너뛴다")
    ap.add_argument("--jobs", "-j", type=int, default=1, metavar="N",
                    help="코너를 동시에 몇 개 돌릴지. **기본 1(하나씩)**. "
                         "코너끼리는 자기 폴더에만 쓰므로 나눠도 결과가 같다. "
                         "다만 2b 가 코너마다 SPEF 를 따로 읽으므로 메모리가 "
                         "N배로 늘어난다. SPEF 가 크면 2~4 부터 올려 볼 것")
    ap.add_argument("--quiet", action="store_true",
                    help="각 단계의 화면 출력을 숨기고 결과 표만 본다")
    args = ap.parse_args()

    print("=" * 68)
    print("4 - 코너 폴더 전부 돌리기  (묶음 %s)" % args.phase)
    print("=" * 68)

    if not os.path.isdir(args.root):
        print("  폴더가 없습니다: %s" % args.root)
        sys.exit(1)

    corners = corner_dirs(args.root)
    if not corners:
        # 반대 착각: 코너들이 든 상위 폴더가 아니라 코너 폴더 하나를 준 경우
        here, _, _ = find_rpt(args.root)
        if here:
            print("  여기는 **코너 폴더 하나** 입니다: %s" % args.root)
            print("      (%s 이 바로 들어 있습니다)" % os.path.basename(here))
            print("")
            print("  --root 에는 코너 폴더들이 **들어 있는 상위 폴더**를 주세요:")
            print("      %s --root %s"
                  % (os.path.basename(__file__), os.path.dirname(args.root.rstrip("/")) or "."))
            print("")
            print("  이 코너 하나만 하려면 각 단계를 직접 돌리시면 됩니다:")
            print("      2a_cpin.py     --dir %s" % args.root)
            print("      2b_distres.py  --dir %s --spef <SPEF>" % args.root)
            print("      2c_merge.py    --dir %s" % args.root)
            print("      %s 5a_contexts.py --dir %s"
                  % (sys.executable, args.root))
            sys.exit(1)
        print("  %s 아래에 .rpt 를 가진 폴더가 없습니다." % args.root)
        print("  2회차(02_round2.tcl)를 먼저 돌리세요.")
        sys.exit(1)

    only = set(s.strip() for s in args.only.split(",")) if args.only else None
    steps = [s for s in PHASES[args.phase]
             if only is None or s[1].split("_")[0] in only]

    print("  대상 폴더 : %s" % args.root)
    print("  코너      : %d개" % len(corners))
    for name, _ in corners:
        print("      %s" % name)
    if args.spef_root:
        print("  SPEF 폴더 : %s" % args.spef_root)
    elif args.spef:
        print("  공용 SPEF : %s" % args.spef)
    print("")

    # ---- SPEF 를 **여기서 전부** 정한다. 하나라도 못 정하면 안 돌린다. ----
    spef_of, spef_bad = resolve_spefs(corners, args)
    need_spef = any(s[2] for s in steps)
    if need_spef and args.spef_root:
        print("  %-26s %-42s" % ("코너", "쓸 SPEF"))
        print("  " + "-" * 66)
        for name, _ in corners:
            print("  %-26s %-42s"
                  % (name, os.path.basename(spef_of[name])
                     if name in spef_of else "*** 못 고름 ***"))
        for name, why in spef_bad:
            print("  %-26s %s" % ("", why))
        print("  " + "-" * 66)
        print("")

    if need_spef and spef_bad:
        print("=" * 68)
        print("  문제 발생")
        print("    무엇이   : %d개 코너가 쓸 SPEF 를 못 정했습니다." % len(spef_bad))
        print("    하실 일  : 위 이유를 보고 셋 중 하나로 정해 주세요.")
        print("               1) 코너 폴더에 design.spef 를 둔다 (ln -s 로도 됩니다)")
        print("               2) --spef-root 폴더에 그 온도/RC 코너 SPEF 를 넣는다")
        print("               3) --spef 로 파일 하나를 직접 준다")
        print("")
        print("               폴더에 무엇이 있는지 보려면:")
        print("                 %s %s --spef-dir %s --dir %s"
              % (sys.executable,
                 os.path.join(HERE, "_engine", "spef_match.py"),
                 args.spef_root or "<SPEF폴더>", args.root))
        print("")
        print("    에러 코드: E-SPEFPICK")
        print("=" * 68)
        sys.exit(1)

    # 진행 상황을 눈으로 쫓을 수 있게 한다. 코너 16개 x 4단계면 화면이 길어져서,
    # 어디까지 왔고 어디서 걸렸는지가 스크롤에 묻힌다. 코너마다 걸린 시간을
    # 재서, 남은 시간도 대충 가늠할 수 있게 한다.
    # ---- 코너 돌리기 --------------------------------------------------
    # --jobs 로 코너를 동시에 돌린다. 코너끼리는 자기 폴더에만 쓰고 SPEF /
    # Cpin 표는 읽기만 하므로 서로 안 건드린다. 실제 계산은 하위 프로세스가
    # 하므로 스레드로 나눠도 GIL 에 안 걸린다.
    #
    # 동시에 돌릴 때는 코너 출력을 모아 뒀다가 그 코너가 끝날 때 한 덩어리로
    # 찍는다. 한 줄씩 뒤섞이면 어느 코너 것인지 알 수 없다.
    jobs = max(1, args.jobs)
    if jobs > len(corners):
        jobs = len(corners)
    results = []   # (코너, [코드...])
    trouble = []   # (코너, 단계, 코드)
    t_start = time.time()

    def prep(name, d):
        """그 코너가 쓸 SPEF 와 Cpin 표를 정한다."""
        spef = spef_of.get(name)
        # Cpin 표 고르는 순서 (SPEF 와 같은 방식)
        #   1) 코너 폴더 안의 cpin_map.txt        <- 코너마다 따로 받았을 때
        #   2) 없으면 --cpin-map 으로 준 파일
        #   3) 둘 다 없으면 안 준다 -> 2a 가 pin_attr.txt 를 쓴다
        # Cpin 은 코너마다 다르므로(0.6V<->0.8V 에서 중앙값 6% 차이)
        # 1) 이 있으면 그쪽이 맞다.
        cmap = os.path.join(d, CPIN_MAP_NAME)
        if not os.path.isfile(cmap):
            cmap = args.cpin_map
        return spef, cmap

    if jobs == 1:
        for idx, (name, d) in enumerate(corners, 1):
            done_n = idx - 1
            eta = ""
            if done_n:
                per = (time.time() - t_start) / done_n
                eta = "   남은 시간 약 %s" % fmt_dur(per * (len(corners) - done_n))
            print("-" * 68)
            print("[%d/%d] %s%s" % (idx, len(corners), name, eta))
            print("-" * 68)
            spef, cmap = prep(name, d)
            # 하나씩 돌 때는 **모아 두지 않고 그때그때 찍는다.** 모아 두면
            # 코너가 끝날 때까지 화면이 멈춰 있어, 2b 가 몇십 분 도는 동안
            # 살아 있는지조차 알 수 없다. 뒤섞일 걱정은 하나씩 돌 때는 없다.
            codes, tr, took = run_corner(name, d, steps, args, spef, cmap, None)
            results.append((name, codes))
            trouble += tr
            print("  -> %s 끝. 걸린 시간 %s" % (name, fmt_dur(took)))
            print("")
    else:
        import threading
        try:
            from concurrent.futures import ThreadPoolExecutor
        except ImportError:
            ThreadPoolExecutor = None
        if ThreadPoolExecutor is None:
            print("  [ 알림 ] 이 파이썬에는 concurrent.futures 가 없어 1개씩 돕니다.")
            jobs = 1

    if jobs > 1:
        from concurrent.futures import ThreadPoolExecutor
        print("  동시에 %d개 코너씩 돕니다." % jobs)
        print("  단계가 끝날 때마다 한 줄, 코너가 끝나면 그 코너 출력이 한 덩어리로 나옵니다.")
        print("")
        lock = threading.Lock()
        state = {"done": 0, "started": 0, "running": 0}

        def work(item):
            name, d = item
            # 코너가 **시작할 때도** 한 줄 찍는다. 안 그러면 첫 코너가 끝날
            # 때까지 화면이 완전히 멈춰 있어, 도는 중인지 죽었는지 알 수 없다.
            # 끝날 때 찍는 덩어리와 헷갈리지 않게 "시작" 을 앞에 붙인다.
            with lock:
                state["started"] += 1
                state["running"] += 1
                print("  시작 [%d/%d] %-28s (지금 %d개 도는 중)"
                      % (state["started"], len(corners), name, state["running"]))
                sys.stdout.flush()
            spef, cmap = prep(name, d)
            sink = []

            def step_done_line(cname, label, code, took):
                # 단계가 끝날 때마다 한 줄. 코너 이름을 앞에 둔다 -- 여러 코너가
                # 섞여 나오므로 어느 코너 것인지가 먼저 보여야 한다.
                with lock:
                    print("       %-24s %-12s %-10s %s"
                          % (cname, label, took, code))
                    sys.stdout.flush()

            codes, tr, took = run_corner(name, d, steps, args, spef, cmap, sink,
                                         progress=step_done_line)
            with lock:
                state["done"] += 1
                state["running"] -= 1
                n = state["done"]
                eta = ""
                if n < len(corners):
                    per = (time.time() - t_start) / n
                    eta = "   남은 시간 약 %s" % fmt_dur(per * (len(corners) - n))
                print("-" * 68)
                print("끝   [%d/%d] %s   (%s)%s"
                      % (n, len(corners), name, fmt_dur(took), eta))
                print("-" * 68)
                for line in sink:
                    print(line)
                print("")
                sys.stdout.flush()
            return name, codes, tr

        with ThreadPoolExecutor(max_workers=jobs) as ex:
            out = list(ex.map(work, corners))
        # 표는 항상 폴더 이름 순으로 낸다. 끝난 순서로 내면 돌릴 때마다 달라진다.
        order = {n: i for i, (n, _d) in enumerate(corners)}
        out.sort(key=lambda r: order[r[0]])
        for name, codes, tr in out:
            results.append((name, codes))
            trouble += tr

    # ---- 결과 표 ----------------------------------------------------
    print("=" * 68)
    print("코너별 결과   (전체 %s 걸림)" % fmt_dur(time.time() - t_start))
    print("-" * 68)
    head = "  %-24s" % "코너" + "".join("%-14s" % s[0] for s in steps)
    print(head)
    bad = []
    for name, codes in results:
        row = "  %-24s" % name
        for c in codes:
            row += "%-14s" % c
        print(row)
        if any(c.startswith("E-") or c in ("-", "?") for c in codes):
            bad.append(name)
    print("")
    print("  정상 %d / 문제 %d / 전체 %d 코너"
          % (len(results) - len(bad), len(bad), len(corners)))
    print("")

    # ---- 어느 코너 어느 단계에서 무엇이 걸렸나 -----------------------
    # 위 표는 코드만 있어 코드표.md 를 뒤져야 한다. 걸린 것만 모아서 뜻까지
    # 같이 찍는다. 화면이 길어도 여기만 보면 다음에 뭘 할지 정해진다.
    if trouble:
        print("=" * 68)
        print("걸린 곳  (%d건)" % len(trouble))
        print("-" * 68)
        for cname, label, cd in trouble:
            print("  %-24s %-12s %-12s %s"
                  % (cname, label, cd, CODE_MEANS.get(cd, "")))
        print("-" * 68)
        print("  그 코너만 따로 돌려 화면을 보려면:")
        c0, l0, _ = trouble[0]
        s0 = [s for s in steps if s[0] == l0]
        if s0:
            print("    %s %s --dir %s"
                  % (sys.executable, os.path.join(HERE, s0[0][1]),
                     os.path.join(args.root, c0)))
        print("")

    if bad:
        print("  실패한 코너 %d개: %s" % (len(bad), ", ".join(bad)))
        print("  그 폴더만 따로 돌려 화면을 보세요:")
        print("      %s 2a_cpin.py --dir %s" % (sys.executable, os.path.join(args.root, bad[0])))
        print("=" * 68)
        sys.exit(1)

    warn = [n for n, cs in results if any(c.startswith("W-") for c in cs)]
    if warn:
        print("  확인 필요한 코너 %d개: %s" % (len(warn), ", ".join(warn)))
        print("  파일은 만들어졌지만 데이터가 일부 비어 있습니다.")
        print("      2c 화면의 [원인 A/B/C/D] 줄을 보세요 (자동으로 붙습니다)")
        print("=" * 68)
        sys.exit(0)

    print("  묶음 %s 전부 정상입니다. 다음:" % args.phase)
    print("")
    fill = {"root": os.path.abspath(args.root), "pkg": HERE,
            "py": sys.executable}
    for line in NEXT_HINT[args.phase]:
        print("  " + (line % fill if "%(" in line else line))
    print("=" * 68)


if __name__ == "__main__":
    main()
