# -*- coding: utf-8 -*-
"""폴더 안에서 타이밍 리포트 파일 하나를 찾아 준다.

2회차 리포트 이름을 코너 이름으로 짓기 때문에(`tt0p7v25c_Cnom.rpt`) 스크립트가
`timing.rpt` 라는 고정 이름을 기대할 수 없다. 그래서 폴더 안의 `.rpt` 를 찾는다.

규칙
    1) --rpt 로 직접 준 게 있으면 그걸 쓴다
    2) 폴더에 .rpt 가 딱 하나면 그것
    3) 여러 개면 헷갈리므로 멈추고 목록을 보여 준다 (--rpt 로 고르라고)
       단 그중 timing.rpt 가 있으면 예전 방식으로 보고 그걸 쓴다
    4) 하나도 없으면 멈춘다

결과물로 만들어지는 파일(annotated*.rpt 등)은 후보에서 뺀다.
"""
import os

# 우리가 만들어 낸 파일은 입력 후보가 아니다
_SKIP_PREFIX = ("annotated", "union_")


def find_rpt(work_dir, explicit=None):
    """(경로, 에러메시지, 에러코드) 를 돌려준다. 찾았으면 뒤 두 개는 None."""
    if explicit:
        if os.path.isfile(explicit):
            return explicit, None, None
        return None, "지정한 리포트가 없습니다: %s" % explicit, "E-NORPT"

    if not os.path.isdir(work_dir):
        return None, "폴더가 없습니다: %s" % work_dir, "E-NORPT"

    names = [n for n in sorted(os.listdir(work_dir))
             if n.endswith(".rpt") and not n.startswith(_SKIP_PREFIX)]

    if len(names) == 1:
        return os.path.join(work_dir, names[0]), None, None

    if names:
        # 여러 개 -> 예전 이름이 있으면 그것, 없으면 골라 달라고 한다
        if "timing.rpt" in names:
            return os.path.join(work_dir, "timing.rpt"), None, None
        msg = ("폴더에 .rpt 가 %d개 있어 어느 것인지 알 수 없습니다: %s\n"
               "            %s\n"
               "            --rpt <파일> 로 하나를 지정해 주세요."
               % (len(names), work_dir, "  ".join(names)))
        return None, msg, "E-RPTMANY"

    # 흔한 착각: 코너 폴더 하나가 아니라 코너들이 든 상위 폴더를 준 경우.
    # (2a/2b/2c/3 은 --dir 에 코너 폴더 하나, 4_all_corners.py 는 --root 에 상위)
    subs = []
    for n in sorted(os.listdir(work_dir)):
        sub = os.path.join(work_dir, n)
        if os.path.isdir(sub) and any(x.endswith(".rpt") for x in os.listdir(sub)):
            subs.append(n)
    if subs:
        msg = ("여기는 코너 폴더가 아니라 **코너들이 들어 있는 폴더** 입니다: %s\n"
               "            안에 코너가 %d개 있습니다: %s\n"
               "            코너 하나만 하려면 그 폴더까지 지정하세요:\n"
               "              --dir %s\n"
               "            전부 한 번에 하려면:\n"
               "              4_all_corners.py --root %s"
               % (work_dir, len(subs), "  ".join(subs[:5]),
                  os.path.join(work_dir, subs[0]), work_dir))
        return None, msg, "E-ISPARENT"

    msg = ("폴더에 .rpt 파일이 없습니다: %s\n"
           "            2회차(fixed_paths.tcl)를 먼저 돌려 리포트를 만드세요."
           % work_dir)
    return None, msg, "E-NORPT"
