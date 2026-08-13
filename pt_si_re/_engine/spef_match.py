# -*- coding: utf-8 -*-
"""코너 이름에 맞는 SPEF 파일을 폴더에서 찾아 준다.

    python3 _engine/spef_match.py --spef-dir <SPEF폴더> --dir <코너들이 든 폴더>
        -> 어느 코너에 어느 SPEF 가 물리는지 표로 보여만 준다(아무것도 안 고침)

무엇을 왜 하나
    SPEF 는 보통 'RC 코너 x 온도' 로 여러 개가 한 폴더에 같이 있다.
    (Cnom/Cmax/Cmin) x (m40/25/125) = 9개 같은 식이다. 코너마다 어느 것을
    물려야 하는지 손으로 고르면 틀리기 쉽고, 틀려도 결과가 그럴듯하게 나온다.

무엇으로 맞추나
    **온도와 RC 코너, 이 둘뿐이다. 전압은 안 본다.**
    기생 RC 는 배선 형상과 온도로 정해지고 전원 전압과는 무관하다. 그래서
    tt0p6v25c / tt0p7v25c / tt0p8v25c 는 전부 같은 SPEF 를 쓴다.

        코너 이름  tt0p6v25c_Cnom
                        │    └── Cnom  -> RC 코너
                        └── 25c        -> 온도
                     0p6v (전압)       -> 안 본다

    SPEF 쪽은 **파일 이름이 아니라 머리말**을 본다. 이름은 사이트마다 다르지만
    머리말은 StarRC/ICC2 가 찍어 주므로 믿을 수 있다.

        // PARASITIC_TECH Cnom_model at 25.000 degree
                          └ RC 코너        └ 온도

    머리말이 없는 SPEF 면 파일 이름에서 읽는다(.Cnom_model_25.spef 같은 꼴).
"""
import os
import re
import sys

# 온도: 25c, 125c, m40c, _25C, _m40C ... m 은 영하를 뜻한다
TEMP_RE = re.compile(r"(m|neg)?(\d{1,3})\s*c(?![a-z0-9])", re.I)
# RC 코너: Cnom/Cmax/Cmin/RCmax/RCmin
RC_RE = re.compile(r"(rcmax|rcmin|cnom|cmax|cmin)", re.I)
# SPEF 머리말
TECH_RE = re.compile(r"PARASITIC_TECH\s+(\S+?)_model\s+at\s+(-?[\d.]+)\s*degree", re.I)
# SPEF 파일 이름에서 읽을 때
FNAME_RE = re.compile(r"\.(\w+?)_model_(m?\d+)\.spef$", re.I)

PLAUSIBLE = (-60.0, 200.0)      # 이 범위 밖 숫자는 온도로 안 본다


def _temp_from(text):
    """문자열에서 온도를 읽는다. 여러 개면 마지막 것(코너 이름은 뒤가 온도)."""
    best = None
    for m in TEMP_RE.finditer(text):
        v = float(m.group(2))
        if m.group(1):
            v = -v
        if PLAUSIBLE[0] <= v <= PLAUSIBLE[1]:
            best = v
    return best


def corner_key(name):
    """코너 이름 -> (RC코너 or None, 온도 or None).

    RC 코너가 이름에 없는 코너도 있다(TT_0p8V_25C 처럼). 그건 None 으로 두고,
    폴더에 RC 코너가 한 종류뿐이면 그걸 쓴다.
    """
    m = RC_RE.search(name)
    rc = m.group(1).lower() if m else None
    return rc, _temp_from(name)


def spef_key(path):
    """SPEF -> (RC코너, 온도).

    **파일 이름을 먼저 본다.** 리포트(코너) 이름과 같은 방식으로 읽어서
    이름끼리 맞추는 것이 눈으로 확인하기 쉽기 때문이다.

        boomcorev3_14nm.Cnom_model_25.spef  ->  (cnom, 25)

    이름에서 둘 다 안 나오면 머리말을 읽는다. 파일을 여는 비용이 들지만
    맨 앞 40줄만 보므로 몇 GB 짜리라도 순식간이다.

        // PARASITIC_TECH Cnom_model at 25.000 degree
    """
    base = os.path.basename(path)
    m = FNAME_RE.search(base)
    if m:
        rc = m.group(1).lower()
        t = m.group(2).lower()
        v = -float(t[1:]) if t.startswith("m") else float(t)
        return rc, v

    rc = RC_RE.search(base)
    t = _temp_from(base)
    if rc and t is not None:
        return rc.group(1).lower(), t

    try:
        with open(path, "r", errors="ignore") as f:
            for _ in range(40):            # 머리말은 맨 앞 몇 줄뿐이다
                line = f.readline()
                if not line:
                    break
                mm = TECH_RE.search(line)
                if mm:
                    return mm.group(1).lower(), float(mm.group(2))
    except IOError:
        pass
    return (rc.group(1).lower() if rc else None), t


def list_spefs(spef_dir):
    """폴더의 .spef 들 -> [(경로, RC코너, 온도)]"""
    out = []
    for n in sorted(os.listdir(spef_dir)):
        if not n.lower().endswith(".spef"):
            continue                       # .spef_scenario 같은 부산물 제외
        p = os.path.join(spef_dir, n)
        if not os.path.isfile(p):
            continue
        rc, t = spef_key(p)
        out.append((p, rc, t))
    return out


def pick(corner_name, spefs):
    """코너 하나에 맞는 SPEF 를 고른다. -> (경로 or None, 설명)

    고를 수 없으면 왜 못 골랐는지 사람이 읽을 수 있게 돌려준다. 애매하면
    아무거나 고르지 않는다 -- 틀린 SPEF 로 돌면 결과가 그럴듯하게 나와서
    한참 뒤에야 알게 된다.
    """
    want_rc, want_t = corner_key(corner_name)
    if want_t is None:
        return None, "코너 이름에서 온도를 못 읽음"

    cand = [s for s in spefs if s[2] is not None and abs(s[2] - want_t) < 0.01]
    if not cand:
        have = sorted(set("%g" % s[2] for s in spefs if s[2] is not None))
        return None, "온도 %gC 짜리 SPEF 가 없음 (있는 것: %s)" % (
            want_t, ", ".join(have) or "없음")

    if want_rc:
        rc_cand = [s for s in cand if s[1] == want_rc]
        if not rc_cand:
            have = sorted(set(s[1] or "?" for s in cand))
            return None, "RC 코너 %s 가 없음 (온도 %gC 에 있는 것: %s)" % (
                want_rc, want_t, ", ".join(have))
        cand = rc_cand
    elif len(set(s[1] for s in cand)) > 1:
        have = sorted(set(s[1] or "?" for s in cand))
        return None, ("코너 이름에 RC 코너가 없는데 폴더에는 %s 가 다 있어 "
                      "고를 수 없음" % "/".join(have))

    if len(cand) > 1:
        # 이름에 coupled 가 있으면 그쪽. crosstalk 에는 커플링 용량이 필요하다.
        coup = [s for s in cand if "coupled" in os.path.basename(s[0]).lower()]
        if len(coup) == 1:
            cand = coup
        else:
            names = ", ".join(os.path.basename(s[0]) for s in cand)
            return None, "같은 조건 SPEF 가 여러 개라 못 고름 (%s)" % names

    p, rc, t = cand[0]
    return p, "%s %gC" % (rc or "?", t)


def corner_names(root):
    """<root> 아래에서 코너 이름들을 찾는다.

    두 가지 모양을 다 받는다.
      round1/corners/<코너>.rpt   -> 파일 이름이 코너 이름
      round2/<코너>/*.rpt         -> 폴더 이름이 코너 이름
    """
    out = []
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n)
        if os.path.isdir(p):
            if any(x.endswith(".rpt") for x in os.listdir(p)):
                out.append((n, p))
        elif n.endswith(".rpt"):
            out.append((os.path.splitext(n)[0], p))
    return out


def main():
    import argparse
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    from utf8 import force_utf8
    force_utf8()

    ap = argparse.ArgumentParser(
        description="코너 이름에 맞는 SPEF 를 찾아 표로 보여 준다 (고치지는 않음).")
    ap.add_argument("--spef-dir", required=True, help="SPEF 들이 든 폴더")
    ap.add_argument("--dir", required=True,
                    help="코너 .rpt 가 든 폴더 (round1/corners 또는 round2)")
    args = ap.parse_args()

    print("=" * 76)
    print("코너 <-> SPEF 짝짓기  (온도와 RC 코너로만 맞춥니다. 전압은 안 봅니다)")
    print("=" * 76)

    spefs = list_spefs(args.spef_dir)
    print("  SPEF 폴더 : %s" % args.spef_dir)
    print("  찾은 SPEF : %d개" % len(spefs))
    for p, rc, t in spefs:
        print("      %-46s  %s %s" % (os.path.basename(p), rc or "?",
                                      ("%gC" % t) if t is not None else "?"))
    print("")

    corners = corner_names(args.dir)
    if not corners:
        print("  %s 아래에 .rpt 가 없습니다." % args.dir)
        sys.exit(1)

    print("  %-26s %-46s %s" % ("코너", "물릴 SPEF", "근거"))
    print("  " + "-" * 74)
    n_bad = 0
    for name, _p in corners:
        sp, why = pick(name, spefs)
        if sp:
            print("  %-26s %-46s %s" % (name, os.path.basename(sp), why))
        else:
            n_bad += 1
            print("  %-26s %-46s %s" % (name, "*** 못 고름 ***", why))
    print("  " + "-" * 74)
    if n_bad:
        print("  %d개 코너가 짝을 못 찾았습니다. 위 '근거' 를 보세요." % n_bad)
        sys.exit(1)
    print("  전부 짝이 맞습니다.")
    print("=" * 76)


if __name__ == "__main__":
    main()
