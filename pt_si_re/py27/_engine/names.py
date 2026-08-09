# -*- coding: utf-8 -*-
"""산출물 파일 이름을 한 곳에서 정한다.

기존 운영 산출물과 **이름 규약이 같아야** 모델 쪽에서 그대로 읽는다.
운영 쪽 실제 파일:

    .../annotation/setup_sion/temp_25/annotated/Cnom/
        saed14rvt_tt0p6v25c_ccs_full387_nldmrx_fixed_annotated.txt
        └────────────── 코너 이름 ──────────────┘└─ 고정 ─┘

    .../crosstalk/setup/Cnom/
        TT_0p6V_25C.path_context_si_compact.by_path.rpt
        └─ 코너 이름 ┘└──────────── 고정 ────────────┘

두 규약이 서로 다르다(하나는 db 파일명, 하나는 코너 표기). 우리는 코너 폴더
이름 하나를 양쪽에 넣는다. 운영 파일과 **정확히 같은 이름**이 필요하면 코너
폴더를 그 이름으로 지으면 된다.
    round2/saed14rvt_tt0p6v25c_ccs_full387_nldmrx/  -> annotation 쪽 이름과 일치
    round2/TT_0p6V_25C/                             -> crosstalk 쪽 이름과 일치
"""
import os

ANNOTATED_SUFFIX = "_fixed_annotated.txt"
XTALK_SUFFIX = ".path_context_si_compact.by_path.rpt"


def corner_of(work_dir):
    """코너 이름 = 그 폴더 이름."""
    return os.path.basename(os.path.abspath(work_dir))


def annotated_name(corner):
    return corner + ANNOTATED_SUFFIX


def xtalk_name(corner):
    return corner + XTALK_SUFFIX


def annotated_path(work_dir, corner=None):
    return os.path.join(work_dir,
                        annotated_name(corner or corner_of(work_dir)))


def xtalk_path(work_dir, corner=None):
    return os.path.join(work_dir,
                        xtalk_name(corner or corner_of(work_dir)))


def find_annotated(work_dir):
    """폴더에서 *_fixed_annotated.txt 를 찾는다. (경로, 에러메시지)

    예전 이름(annotated.txt)도 받아 준다.
    """
    if not os.path.isdir(work_dir):
        return None, "폴더가 없습니다: %s" % work_dir
    names = sorted(n for n in os.listdir(work_dir)
                   if n.endswith(ANNOTATED_SUFFIX))
    if len(names) == 1:
        return os.path.join(work_dir, names[0]), None
    if len(names) > 1:
        return None, ("폴더에 *%s 이 %d개 있습니다: %s\n"
                      "            %s"
                      % (ANNOTATED_SUFFIX, len(names), work_dir,
                         "  ".join(names)))
    old = os.path.join(work_dir, "annotated.txt")
    if os.path.isfile(old):
        return old, None
    return None, ("폴더에 *%s 이 없습니다: %s\n"
                  "            2c_merge.py 를 먼저 돌려 주세요."
                  % (ANNOTATED_SUFFIX, work_dir))
