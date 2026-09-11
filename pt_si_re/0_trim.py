#!/usr/bin/env python3
# -*- coding: ascii -*-
# Keep this executable source ASCII-only. Some legacy EDA hosts transcode
# non-ASCII Python files during transfer. Korean UI text uses Unicode escapes
# below and is rendered normally when the script runs.
"""0 - \ucf54\ub108\ubcc4 \ub9ac\ud3ec\ud2b8\ub97c '\ub098\uc05c \uac83 N\uac1c\ub9cc' \ub0a8\uae34 \ub9ac\ud3ec\ud2b8\ub85c \uc904\uc778\ub2e4.  (1\ud68c\ucc28 -> 1_union)

    # setup: \uc785\ub825 report\uac00 -delay_type max\uc778 \uacbd\uc6b0
    python3 0_trim.py --dir round1/corners --keep 10000 --mode setup

    # hold: \uc785\ub825 report\uac00 -delay_type min\uc778 \uacbd\uc6b0
    python3 0_trim.py --dir round1/corners --keep 10000 --mode hold

    --mode\ub97c \uc0dd\ub7b5\ud558\uba74 setup\uc774 \uae30\ubcf8\uac12\uc774\ub2e4. hold\uc5d0\uc11c\ub294 \ubc18\ub4dc\uc2dc --mode hold\ub97c
    \ub123\ub294\ub2e4. \uc791\uc5c5\uc774 \ub05d\ub098\uba74 \uac19\uc740 --mode\uac00 \ub4e4\uc5b4\uac04 1_union.py \uba85\ub839\uc744 \ucd9c\ub825\ud55c\ub2e4.

\ubb34\uc5c7\uc744 \uc65c \ud558\ub098
    \ud604\uc5c5 \ub9ac\ud3ec\ud2b8\ub294 \ucf54\ub108 \ud558\ub098\uc5d0 \uacbd\ub85c\uac00 8\ub9cc \uac1c\uc529 \ub098\uc628\ub2e4. \uadf8\uac78 \uadf8\ub300\ub85c 1_union.py
    \uc5d0 \ub123\uc73c\uba74 \uba54\ubaa8\ub9ac\uac00 \uac10\ub2f9\uc774 \uc548 \ub41c\ub2e4. \uadf8\ub798\uc11c **\ud569\uce58\uae30 \uc804\uc5d0 \ud30c\uc77c \uc790\uccb4\ub97c**
    \ucf54\ub108\ub9c8\ub2e4 \ub098\uc05c \uac83 N\uac1c\ub9cc \ub0a8\uae34 \ub9ac\ud3ec\ud2b8\ub85c \uc904\uc5ec \ub454\ub2e4.

    \uc904\uc778 \ub9ac\ud3ec\ud2b8\ub294 \uc9c4\uc9dc report_timing \ucd9c\ub825\uc758 \ubd80\ubd84\uc9d1\ud569\uc774\ub2e4. \ud615\uc2dd\uc774 \uadf8\ub300\ub85c\ub77c
    1_union.py \ub4e0 vi \ub4e0 \uc6d0\ubcf8\uacfc \ub611\uac19\uc774 \uc4f8 \uc218 \uc788\uace0, \ud55c \ubc88 \ub9cc\ub4e4\uc5b4 \ub450\uba74 \ubb38\ud131\uac12\uc744
    \ubc14\uafd4 \uac00\uba70 \uba87 \ubc88\uc744 \ub2e4\uc2dc \ub3cc\ub824\ub3c4 \uc21c\uc2dd\uac04\uc774\ub2e4.

\ucf54\ub108\ubcc4\ub85c \uc798\ub77c\ub3c4 \ud569\uc9d1\ud569\uc740 \uba40\uca61\ud55c\uac00
    \uba40\uca61\ud558\ub2e4. \ucf54\ub108 A \uc5d0\uc11c \uc704\ubc18\uc778 \uacbd\ub85c\ub294 A \uc790\uc2e0\uc758 \uc0c1\uc704 N \ubaa9\ub85d\uc5d0 \ub4e4\uc5b4\uac00\ubbc0\ub85c,
    \ub2e4\ub978 \ucf54\ub108\uc5d0\uc11c \uc548 \uc7a1\ud788\ub294 \uacbd\ub85c\ub3c4 \ud569\uc9d1\ud569\uc5d0 \uadf8\ub300\ub85c \ub4e4\uc5b4\uc628\ub2e4. \ube60\uc9c0\ub294 \uac83\uc740
    **\uc5b4\ub290 \ucf54\ub108\uc5d0\uc11c\ub3c4 \uc0c1\uc704 N \uc5d0 \ubabb \ub4e0 \uacbd\ub85c**\ubfd0\uc774\uace0, \uadf8\uac74 \uc560\ucd08\uc5d0 \ubcfc \ud544\uc694\uac00 \uc5c6\ub2e4.

    \ub531 \ud558\ub098 \ub2ec\ub77c\uc9c0\ub294 \uac83: \uacbd\ub85c P \uac00 \ucf54\ub108 A \uc758 \uc0c1\uc704 N \uc5d0\ub294 \uc788\uace0 \ucf54\ub108 B \uc5d0\uc11c\ub294
    \ud55c\ucc38 \ubc00\ub824 \uc798\ub838\ub2e4\uba74, union_paths.tsv \uc758 slack__B \uc5f4\uc774 \ube48\uce78\uc774 \ub41c\ub2e4.
    \uacbd\ub85c \uc790\uccb4\ub294 \ud569\uc9d1\ud569\uc5d0 \ub4e4\uc5b4\uac00\uace0 fixed_paths.tcl \ub3c4 \uc815\uc0c1\uc774\ub2e4. \uc5b4\ucc28\ud53c 2\ud68c\ucc28\uc5d0
    **\ubaa8\ub4e0 \ucf54\ub108\uc5d0\uc11c \ub2e4\uc2dc \uce21\uc815**\ud558\ubbc0\ub85c, \ube48\uce78\uc740 1\ud68c\ucc28 \ucc38\uace0\uac12\uc774 \ube44\ub294 \uac83\ubfd0\uc774\ub2e4.

\uba54\ubaa8\ub9ac
    \ud30c\uc77c\uc744 \ub450 \ubc88 \ud758\ub824 \uc77d\ub294\ub2e4. \uacbd\ub85c\ub97c \uc313\uc544 \ub450\uc9c0 \uc54a\ub294\ub2e4.
      1\ubc88\uc9f8 : slack \uac12\ub9cc \uc77d\uc5b4 '\uc5b4\ub514\uc11c \uc790\ub97c\uc9c0' \uc815\ud55c\ub2e4   (\uacbd\ub85c\ub2f9 8\ubc14\uc774\ud2b8)
      2\ubc88\uc9f8 : \uadf8 \ubb38\ud131\uc744 \ub118\ub294 \uacbd\ub85c \ube14\ub85d\ub9cc \uadf8\ub300\ub85c \uc368\ub0b8\ub2e4  (\ud55c \ube14\ub85d\uc529 \ud758\ub824\ubcf4\ub0c4)
    \uadf8\ub798\uc11c \ub9ac\ud3ec\ud2b8\uac00 \uba87 GB \ub4e0 \uba54\ubaa8\ub9ac\ub294 \uc218\uc2ed MB \ub97c \uc548 \ub118\ub294\ub2e4.

\uc785\ub825
    <dir>/*.rpt      \ucf54\ub108\ub9c8\ub2e4 \ud558\ub098. \ud30c\uc77c \uc774\ub984\uc774 \uadf8\ub300\ub85c \ucf54\ub108 \uc774\ub984\uc774 \ub41c\ub2e4.

\ucd9c\ub825
    <out>/*.rpt      \uac19\uc740 \uc774\ub984, \uac19\uc740 \ud615\uc2dd. \uacbd\ub85c\ub9cc N\uac1c\ub85c \uc904\uc5b4 \uc788\ub2e4.
                     \uadf8\ub2e4\uc74c:  python3 1_union.py --dir <out> --mode setup|hold

\uc635\uc158
    --dir <\ud3f4\ub354>     \uc6d0\ubcf8 .rpt \uac00 \uc788\ub294 \ud3f4\ub354                  (\ud544\uc218)
    --keep N         \ucf54\ub108\ub9c8\ub2e4 \ub0a8\uae38 \uacbd\ub85c \uc218. slack \uc774 \ub098\uc05c \uac83\ubd80\ud130. (\uae30\ubcf8 10000)
    --out <\ud3f4\ub354>     \uacb0\uacfc\ub97c \uc4f8 \ud3f4\ub354. \uc0dd\ub7b5\ud558\uba74 <dir>_top<N>
    --mode setup|hold  setup \uc740 slack \uc774 \uc791\uc740 \uac83\uc774 \ub098\uc058\ub2e4. hold \ub3c4 \uac19\ub2e4.
                     \uae30\ubcf8\uc740 setup. \ubd84\uc11d \uc885\ub958\ub97c \ub9c8\uc9c0\ub9c9 1_union.py \uba85\ub839\uc5d0 \uc804\ub2ec\ud55c\ub2e4.
    --verify         \uc815\ub82c\ub3fc \uc788\ub294\uc9c0 \ub05d\uae4c\uc9c0 \ud655\uc778\ud55c\ub2e4. \ub9ac\ud3ec\ud2b8\ub97c -sort_by slack
                     \uc5c6\uc774 \ubf51\uc558\uc744 \uac00\ub2a5\uc131\uc774 \uc788\uc744 \ub54c\ub9cc \uc4f4\ub2e4. \uae30\ubcf8\uc740 \ud655\uc778\ud558\uc9c0 \uc54a\uace0
                     **\uc55e\uc5d0\uc11c N\uac1c\ub9cc \uc77d\uace0 \uba48\ucd98\ub2e4**(\uadf8\ub798\uc11c '\uc6d0\ub798' \uac1c\uc218\ub294 ? \ub85c \ub72c\ub2e4).

    --jobs N (-j N)  \ucf54\ub108\ub97c \ub3d9\uc2dc\uc5d0 \uba87 \uac1c \ucc98\ub9ac\ud560\uc9c0. **\uae30\ubcf8 1(\ud558\ub098\uc529)**.
                     \uc774 \ub2e8\uacc4\ub294 \uacbd\ub85c\ub97c \uc313\uc544 \ub450\uc9c0 \uc54a\uc544 \uba87 \uac1c\ub85c \ub098\ub220\ub3c4 \uba54\ubaa8\ub9ac\uac00
                     \uac70\uc758 \uc548 \ub298\uc5b4\ub09c\ub2e4(\ucf54\ub108 12\uac1c \uae30\uc900 34MB). \ucf54\ub108\uac00 \ub9ce\uc73c\uba74
                     -j 8 \uc815\ub3c4\ub85c \uc62c\ub9ac\uba74 \uadf8\ub9cc\ud07c \ube68\ub77c\uc9c4\ub2e4.
    --force          \uacb0\uacfc \ud3f4\ub354\uc5d0 \uc774\ubbf8 \ud30c\uc77c\uc774 \uc788\uc5b4\ub3c4 \ub36e\uc5b4\uc4f4\ub2e4

\uc790\uc8fc \uc4f0\ub294 \ud615\ud0dc
    python3 0_trim.py  --dir round1/corners --keep 10000 --mode setup
    python3 1_union.py --dir round1/corners_top10000 --mode setup --max-paths 2000

    python3 0_trim.py  --dir hold_round1/corners --keep 10000 --mode hold
    python3 1_union.py --dir hold_round1/corners_top10000 --mode hold --max-paths 2000
"""
import argparse
import glob
import multiprocessing
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()

START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
SLACK_RE = re.compile(r"^\s*slack\s*\(([^)]+)\)\s+(-?[\d.]+)")

# \ubc14\uc774\ud2b8\uc6a9 \uac19\uc740 \uc815\uaddc\uc2dd. \uc774 \uc2a4\ud06c\ub9bd\ud2b8\ub294 \ub9ac\ud3ec\ud2b8\uc5d0\uc11c \uc22b\uc790\ub9cc \uaebc\ub0b4\uace0 \ub098\uba38\uc9c0\ub294
# \uadf8\ub300\ub85c \ubcf5\uc0ac\ud558\ubbc0\ub85c, \ubb38\uc790\uc5f4\ub85c \ub514\ucf54\ub529\ud588\ub2e4\uac00 \ub2e4\uc2dc \uc778\ucf54\ub529\ud560 \uc774\uc720\uac00 \uc5c6\ub2e4.
# \ub514\ucf54\ub529\uc744 \uc548 \ud558\uba74 \ube60\ub974\uae30\ub3c4 \ud558\uace0, \uc774\uc0c1\ud55c \ubb38\uc790\uac00 \uc11e\uc5ec \uc788\uc5b4\ub3c4 \uc6d0\ubcf8\uc774 \uadf8\ub300\ub85c \ub098\uc628\ub2e4.
START_B_RE = re.compile(rb"^[ \t]*Startpoint:")
SLACK_B_RE = re.compile(rb"^[ \t]*slack\s*\([^)]*\)\s+(-?[\d.]+)")


# ---- \uacb0\uacfc \ucf54\ub4dc -------------------------------------------------------
# =====================================================================
# \uc804\uc555 \uc5f4  --  \uacbd\ub85c\uac00 \ucf54\ub108 \uc804\uc555 \ud558\ub098\ub85c\ub9cc \ub418\uc5b4 \uc788\ub294\uc9c0 \ubcf8\ub2e4
# =====================================================================
# \ub2f4\ub2f9\uc790\ubd84\uc774 \ubd99\uc5ec \uc8fc\uc2dc\ub294 \uc5f4 \uc774\ub984\uc774 \uc815\ud574\uc9c0\uba74 **\uc5ec\uae30\ub9cc** \uace0\uce58\uba74 \ub41c\ub2e4.
# \ub300\uc18c\ubb38\uc790\ub294 \uc548 \uac00\ub9b0\ub2e4. \uba38\ub9ac\ub9d0\uc5d0\uc11c \uc774 \uc774\ub984\uc744 \ucc3e\uc544 \uae00\uc790 \uc704\uce58\ub97c \uc5bb\uace0,
# \ud540 \uc904\uc758 \uadf8 \uc704\uce58\uc5d0\uc11c \uac12\uc744 \uc77d\ub294\ub2e4(2c_merge.py \uac00 \uc5f4\uc744 \ub9de\ucd94\ub294 \ubc29\uc2dd\uacfc \uac19\ub2e4).
VOLT_NAMES = ("Voltage", "Volt", "VDD")
# \uc704\uc5d0 \uc5b4\ub5bb\uac8c \uc801\uc73c\uc2dc\ub4e0 \ub300\uc18c\ubb38\uc790\ub97c \uc548 \uac00\ub9ac\uac8c \uc5ec\uae30\uc11c \uc18c\ubb38\uc790\ub85c \ub9de\ucdb0 \ub454\ub2e4.
# (\uc608\uc804\uc5d0\ub294 \uc801\ud78c \uadf8\ub300\ub85c \ube44\uad50\ud574\uc11c, "Voltage" \ub77c\uace0 \ub123\uc73c\uba74 \uc601\uc601 \uc548 \ub9de\uc558\ub2e4)
_VOLT_LC = tuple(n.strip().lower() for n in VOLT_NAMES if n.strip())

# \uba38\ub9ac\ub9d0 \uc904. report_timing \uc740 \uacbd\ub85c\ub9c8\ub2e4 \uc774 \uc904\uc744 \ub2e4\uc2dc \ucc0d\ub294\ub2e4(\uc2e4\uce21: \uacbd\ub85c \uc218\uc640 \uac19\uc74c).
HDR_B_RE = re.compile(rb"^\s*Point\b")
DIGIT_B_RE = re.compile(rb"[0-9]")
NETLINE_B_RE = re.compile(rb"\(net\)")
# \ud540 \uc904 : "  <\uc774\ub984> (<\uc140>)" \uaf34. \uc804\uc555\uc740 \uc5ec\uae30\uc5d0\ub9cc \ubd99\ub294\ub2e4.
PINLINE_B_RE = re.compile(rb"^\s+\S+\s+\([^)]*\)")
WORD_B_RE = re.compile(rb"[a-z_]+")
NUM_B_RE = re.compile(rb"-?\d+(?:\.\d+)?")

# \ucf54\ub108 \uc774\ub984\uc5d0\uc11c \uc804\uc555\uc744 \uc77d\ub294\ub2e4.  tt0p78v25c -> 0.78,  TT_0p7V_25C -> 0.7
CORNER_V_RE = re.compile(r"(\d+)p(\d+)\s*v", re.I)


def voltage_of_corner(name):
    """\ucf54\ub108(\ud30c\uc77c) \uc774\ub984\uc5d0\uc11c \uc804\uc555\uc744 \ubf51\ub294\ub2e4. \ubabb \uc77d\uc73c\uba74 None.

    0_trim \uc740 \ucf54\ub108\ub97c \uc5ec\ub7ec \uac1c \ud55c\uaebc\ubc88\uc5d0 \ub3cc\uae30 \ub54c\ubb38\uc5d0, \ubaa9\ud45c \uc804\uc555\uc744 \uc635\uc158 \ud558\ub098\ub85c
    \uace0\uc815\ud558\uba74 \uc548 \ub41c\ub2e4. \ucf54\ub108\ub9c8\ub2e4 \uc790\uae30 \uc774\ub984\uc758 \uc804\uc555\uc744 \uc4f4\ub2e4.
    """
    m = CORNER_V_RE.search(name)
    if not m:
        return None
    try:
        return float("%s.%s" % (m.group(1), m.group(2)))
    except ValueError:
        return None


def volt_span(header):
    """\uba38\ub9ac\ub9d0\uc5d0\uc11c \uc804\uc555 \uc5f4\uc774 \uc2dc\uc791\ud558\ub294 \uae00\uc790 \uc704\uce58. \ubabb \ucc3e\uc73c\uba74 None.

    \uc804\uc555\uc740 **\ub9e8 \uc624\ub978\ucabd \uc5f4**\uc774\ub77c, \uc774\ub984\uc774 \uc5ec\ub7ec \ubc88 \ub098\uc624\uba74 \ub9c8\uc9c0\ub9c9 \uac83\uc744 \uc4f4\ub2e4.

    \uacbd\uacc4\ub97c \uc5b4\ub5bb\uac8c \uc7a1\ub098
        **\ubc14\ub85c \uc55e \uc5f4 \uc774\ub984\uc774 \ub05d\ub09c \uc790\ub9ac**\ubd80\ud130\uac00 \uc804\uc555 \uc5f4\uc774\ub2e4. \uac70\uae30\uc11c\ubd80\ud130 \uc904 \ub05d\uae4c\uc9c0
        \ubcf8\ub2e4. \uc774\ub7ec\uba74 \uc606 \uc5f4(Path \ub4f1) \uac12\uc5d0\ub294 \uc808\ub300 \uc190\ub300\uc9c0 \uc54a\ub294\ub2e4 -- \uc55e \uc5f4\uc758 \uac12\uc740
        \uadf8 \uc5f4 \uc774\ub984 \ub05d\uc5d0 \ub9de\ucdb0 \uc815\ub82c\ub418\ubbc0\ub85c \uc774 \uc704\uce58\ubcf4\ub2e4 \uc55e\uc5d0\uc11c \ub05d\ub09c\ub2e4.

        \uc608\uc804\uc5d0\ub294 \uc774\ub984 \uc55e\ub4a4\ub85c \uc5ec\uc720\ub97c \ub450\uace0 \ubabb \uc77d\uc73c\uba74 \ub354 \ub113\ud600\uc11c \ucc3e\uc558\ub294\ub370, \uc804\uc555\uc774
        \uc548 \ucc0d\ud78c \uc904\uc5d0\uc11c \uc606 \uc5f4 \uc22b\uc790\ub97c \uc804\uc555\uc73c\ub85c \uc9d1\uc5c8\ub2e4. \uadf8\ub798\uc11c \uc5c6\uc574\ub2e4.
    """
    low = header.lower()
    hits = list(WORD_B_RE.finditer(low))
    idx = None
    for i, m in enumerate(hits):
        try:
            w = m.group(0).decode("ascii")
        except UnicodeDecodeError:
            continue
        if w in _VOLT_LC:
            idx = i
    if idx is None:
        return None
    # \uac12\uc740 \uc5f4 \uc774\ub984\uc758 **\uc624\ub978\ucabd \ub05d**\uc5d0 \ub9de\ucdb0 \uc815\ub82c\ub41c\ub2e4. \uc774\ub984\ubcf4\ub2e4 \uae38 \uc218 \uc788\uc73c\ub2c8
    # \uc67c\ucabd\uc73c\ub85c \uc870\uae08 \uc5ec\uc720\ub97c \ub450\ub418, **\uc55e \uc5f4 \uc774\ub984\uc774 \ub05d\ub09c \uc790\ub9ac\ubcf4\ub2e4\ub294 \uc67c\ucabd\uc73c\ub85c \uc548 \uac04\ub2e4.**
    # \uc55e \uc5f4\uc758 \uac12\ub3c4 \uadf8 \uc774\ub984 \ub05d\uc5d0 \ub9de\ucdb0 \uc815\ub82c\ub418\ubbc0\ub85c, \uc774 \uc120\uc744 \uc9c0\ud0a4\uba74 \uc606 \uc5f4 \uac12\uc5d0
    # \uc808\ub300 \ub2ff\uc9c0 \uc54a\ub294\ub2e4.
    lo = hits[idx].start() - 12
    if idx > 0 and lo < hits[idx - 1].end():
        lo = hits[idx - 1].end()        # \uc55e \uc5f4 \uc774\ub984 \ub05d\ubcf4\ub2e4 \uc67c\ucabd\uc73c\ub85c\ub294 \uc548 \uac04\ub2e4
    if lo < 0:
        lo = 0
    return lo                            # \uc5ec\uae30\uc11c **\uc904 \ub05d\uae4c\uc9c0**\uac00 \uc804\uc555 \uc5f4


def line_volt(line, lo):
    """\uc904\uc5d0\uc11c \uc804\uc555 \uac12\uc744 \uc77d\ub294\ub2e4. **\uc804\uc555 \uc5f4\uc5d0\uc11c\ub9cc** \uac00\uc838\uc628\ub2e4.

    \uc804\uc555\uc740 \ub9e8 \uc624\ub978\ucabd \uc5f4\uc774\ubbc0\ub85c lo \ubd80\ud130 **\uc904 \ub05d\uae4c\uc9c0**\uac00 \uc804\uc555 \uc5f4\uc774\ub2e4. \uadf8 \uc548\uc758
    **\ub9c8\uc9c0\ub9c9 \ub0b1\ub9d0**\uc744 \uc22b\uc790\ub85c \uc77d\ub294\ub2e4.

    \uc65c '\ub05d\uae4c\uc9c0' \uc778\uac00
        \uac12\uc774 \uc5f4 \uc774\ub984\ubcf4\ub2e4 \uae38 \uc218\ub3c4(0.780000), \uc774\ub984\ubcf4\ub2e4 \uc624\ub978\ucabd\uc73c\ub85c \ub354 \ub098\uac08 \uc218\ub3c4
        \uc788\ub2e4. \uc881\uac8c \uc7a1\uc73c\uba74 \uac12\uc774 \ubc94\uc704 \ubc16\uc73c\ub85c \ub098\uac00 **\uc804\ubd80 \ube48\uce78\uc73c\ub85c \ubcf4\uc778\ub2e4.**

    \uc65c \uc606 \uc5f4\uc774 \uc548 \uac78\ub9ac\ub098
        lo \ub294 \uc55e \uc5f4 \uc774\ub984\uc774 \ub05d\ub09c \uc790\ub9ac\ubcf4\ub2e4 \uc67c\ucabd\uc73c\ub85c \uc548 \uac04\ub2e4. \uc55e \uc5f4\uc758 \uac12\ub3c4 \uadf8
        \uc774\ub984 \ub05d\uc5d0 \ub9de\ucdb0 \uc815\ub82c\ub418\ubbc0\ub85c lo \uc55e\uc5d0\uc11c \ub05d\ub09c\ub2e4. \uadf8\ub798\uc11c lo \ub4a4\uc5d0 \ub0a8\ub294 \uac83\uc740
        rise/fall \ud45c\uc2dc(r/f)\uc640 \uc804\uc555\ubfd0\uc774\uace0, \ub9c8\uc9c0\ub9c9 \ub0b1\ub9d0\uc774 \uace7 \uc804\uc555\uc774\ub2e4.

    \ube48\uce78
        \uc804\uc555\uc774 \uc548 \ucc0d\ud78c \uc904\uc740 \ub9c8\uc9c0\ub9c9 \ub0b1\ub9d0\uc774 r/f \uc774\uac70\ub098 \uc544\ubb34\uac83\ub3c4 \uc5c6\ub2e4. \ub458 \ub2e4
        \uc22b\uc790\uac00 \uc544\ub2c8\ubbc0\ub85c None \uc774\uace0 \uadf8 \uc904\uc740 \uadf8\ub0e5 \ub118\uc5b4\uac04\ub2e4(\ud074\ub7ed \uc81c\ub108\ub808\uc774\ud130 \ub4f1).
    """
    if len(line) <= lo:
        return None                     # \uadf8 \uc5f4\uae4c\uc9c0 \uc624\uc9c0\ub3c4 \uc54a\ub294 \uc9e7\uc740 \uc904
    parts = line[lo:].split()
    if not parts:
        return None                     # \ube44\uc5b4 \uc788\ub2e4
    try:
        return float(parts[-1])
    except ValueError:
        return None                     # r/f \ub9cc \uc788\ub294 \ub4f1


class VoltCheck(object):
    """\uacbd\ub85c \ube14\ub85d \ud558\ub098\ub97c \ud6d1\uc5b4 '\ucf54\ub108 \uc804\uc555 \ud558\ub098\ubfd0\uc778\uac00' \ub97c \ud310\uc815\ud55c\ub2e4.

    target \uc774 None \uc774\uba74 \uc544\ubb34\uac83\ub3c4 \uc548 \ud55c\ub2e4(\uc61b \ub3d9\uc791 \uadf8\ub300\ub85c).
    """

    # \ud310\uc815\uac12
    PASS = 0      # \ubaa9\ud45c \uc804\uc555 \ud558\ub098\ubfd0
    MIXED = 1     # \ub450 \uac1c \uc774\uc0c1 -- macro \ub4f1\uc774 \ub2e4\ub978 \uc804\uc6d0
    NOVOLT = 2    # \uc804\uc555\uc744 \ud558\ub098\ub3c4 \ubabb \uc77d\uc74c -- \uc5f4 \uc774\ub984\uc774 \ub2e4\ub97c \uc218 \uc788\ub2e4
    OTHER = 3     # \uc804\uc555\uc740 \ud558\ub098\uc778\ub370 \ubaa9\ud45c\uc640 \ub2e4\ub984

    def __init__(self, target):
        self.target = target
        self.span = None          # \uba38\ub9ac\ub9d0\uc5d0\uc11c \uc5bb\uc740 \uc5f4 \uc704\uce58. \ud30c\uc77c \ub0b4\ub0b4 \uae30\uc5b5\ud55c\ub2e4
        self.seen = set()
        self.hdr = None           # \ucc98\uc74c \ub9cc\ub09c \uba38\ub9ac\ub9d0 \uc6d0\ubb38 (\uc5f4 \uc774\ub984\uc744 \ubabb \ucc3e\uc744 \ub54c \ubcf4\uc5ec\uc900\ub2e4)
        self.n_read = 0           # \uc804\uc555 \uac12\uc744 \uc2e4\uc81c\ub85c \uba87 \ubc88 \uc77d\uc5c8\ub098 (\uc9c4\ub2e8\uc6a9)
        self.first = None         # \ucc98\uc74c \uc77d\uc5b4\ub0b8 (\uac12, \uadf8 \uc904) -- \ud654\uba74\uc5d0 \ubc14\ub85c \ubcf4\uc5ec\uc900\ub2e4
        self.colname = None       # \uba38\ub9ac\ub9d0\uc5d0\uc11c \uc2e4\uc81c\ub85c \ub9de\uc740 \uc5f4 \uc774\ub984

    def on(self):
        return self.target is not None

    @staticmethod
    def is_header(line):
        """\uba38\ub9ac\ub9d0 \uc904\uc778\uac00.

        1) '  Point ...' \ub85c \uc2dc\uc791\ud558\uba74 \uba38\ub9ac\ub9d0\uc774\ub2e4 (PT \uae30\ubcf8 \ud615\uc2dd).
        2) \uc544\ub2c8\uc5b4\ub3c4, **\uc22b\uc790\uac00 \ud558\ub098\ub3c4 \uc5c6\uace0** \uc804\uc555 \uc5f4 \uc774\ub984\uc774 \ub0b1\ub9d0\ub85c \ub4e4\uc5b4 \uc788\uc73c\uba74
           \uba38\ub9ac\ub9d0\ub85c \ubcf8\ub2e4. \uccab \uc5f4 \uc774\ub984\uc774 Point \uac00 \uc544\ub2cc \ub9ac\ud3ec\ud2b8\ub3c4 \uc788\uae30 \ub54c\ubb38\uc774\ub2e4.
           \uac12 \uc904\uc5d0\ub294 \ubc18\ub4dc\uc2dc \uc22b\uc790\uac00 \uc788\uc73c\ubbc0\ub85c \uac12 \uc904\uc774 \uc798\ubabb \uac78\ub9ac\uc9c0 \uc54a\ub294\ub2e4.
        """
        if HDR_B_RE.match(line):
            return True
        if DIGIT_B_RE.search(line):
            return False
        return volt_span(line) is not None

    def feed(self, line):
        """\ube14\ub85d \uc548\uc758 \uc904\uc744 \ud558\ub098 \ub123\ub294\ub2e4."""
        if self.target is None:
            return
        # \uba38\ub9ac\ub9d0\uc740 **\uc5b8\uc81c\ub098** \ubcf8\ub2e4. \uc5f4 \uc704\uce58\uac00 \uacbd\ub85c\ub9c8\ub2e4 \ubc14\ub00c\ubbc0\ub85c, \uc5ec\uae30\uc11c
        # \uac74\ub108\ub6f0\uba74 \ub2e4\uc74c \ube14\ub85d\uc744 \uc55e \ube14\ub85d\uc758 \uc704\uce58\ub85c \uc77d\uac8c \ub41c\ub2e4.
        if VoltCheck.is_header(line):
            if self.hdr is None:
                self.hdr = line.rstrip()
            sp = volt_span(line)
            if sp is not None:
                self.span = sp
                if self.colname is None:
                    for m in WORD_B_RE.finditer(line.lower()):
                        try:
                            w = m.group(0).decode("ascii")
                        except UnicodeDecodeError:
                            continue
                        if w in _VOLT_LC:
                            self.colname = w
            return
        if self.span is None:
            return
        # \uc804\uc555\uc774 \uc774\ubbf8 \ub450 \uc885\ub958\uba74 \ud310\uc815\uc740 MIXED \ub85c \ub05d\ub0ac\ub2e4. \uadf8 \uacbd\ub85c\uc758 \ub0a8\uc740 \uc904\uc744
        # \ub354 \uc77d\uc5b4 \ubd10\uc57c \uacb0\uacfc\uac00 \uc548 \ubc14\ub00c\ubbc0\ub85c \uac74\ub108\ub6f4\ub2e4(\uacbd\ub85c\uac00 \uae38\uc218\ub85d \uc774\ub4dd\uc774 \ud06c\ub2e4).
        if len(self.seen) > 1:
            return
        # **\ud540 \uc904\ub9cc \ubcf8\ub2e4.**
        #
        # \uc694\uc57d \uc904(data arrival time, slack, clock uncertainty ...)\uc740 \uc22b\uc790\uac00
        # \uc5f4\uacfc \ubb34\uad00\ud558\uac8c \ub9e8 \uc624\ub978\ucabd\uc5d0 \ucc0d\ud78c\ub2e4. \uadf8\uac78 \uc804\uc555 \uc5f4 \uc704\uce58\uc5d0\uc11c \uc790\ub974\uba74
        # \uc22b\uc790 \uc911\uac04\uc774 \uc798\ub824 \uc5c9\ub6b1\ud55c \uac12\uc774 \ub098\uc628\ub2e4. \uc2e4\uce21: "-1.310492" \uc758 \ub05d\uc790\ub9ac\ub9cc
        # \uc798\ub824 2.0 \uc73c\ub85c \uc77d\ud614\uace0, \uadf8 \ud0d3\uc5d0 \ubaa8\ub4e0 \uacbd\ub85c\uac00 mixed \uac00 \ub410\ub2e4.
        #
        # \ub137 \uc904\ub3c4 \uc5f4 \uad6c\uc131\uc774 \ub2ec\ub77c\uc11c(Fanout/Cap \ubfd0) \ube80\ub2e4.
        if not PINLINE_B_RE.match(line):
            return
        if NETLINE_B_RE.search(line):
            return
        v = line_volt(line, self.span)
        if v is not None:
            self.n_read += 1
            if self.first is None:
                self.first = (v, line.rstrip()[-46:])
            self.seen.add(round(v, 6))

    def verdict(self):
        """\ube14\ub85d\uc774 \ub05d\ub0ac\uc744 \ub54c \ubd80\ub978\ub2e4. \ud310\uc815\uc744 \uc8fc\uace0 \ub2e4\uc74c \ube14\ub85d\uc744 \uc704\ud574 \ube44\uc6b4\ub2e4."""
        if self.target is None:
            return VoltCheck.PASS
        seen = self.seen
        self.seen = set()
        if not seen:
            return VoltCheck.NOVOLT
        if len(seen) > 1:
            return VoltCheck.MIXED
        only = next(iter(seen))
        return VoltCheck.PASS if abs(only - self.target) < 1e-6 else VoltCheck.OTHER


CODE_INFO = {
    "E-VNAME":    ("\ucf54\ub108 \uc774\ub984\uc5d0\uc11c \uc804\uc555\uc744 \ubabb \uc77d\uc5c8\uc2b5\ub2c8\ub2e4",
                   "--voltage auto \ub294 \uc774\ub984\uc5d0 0p78v \uac19\uc740 \ud45c\uae30\uac00 \uc788\uc5b4\uc57c \ud569\ub2c8\ub2e4. "
                   "\uc774\ub984\uc774 \uadf8\ub807\uc9c0 \uc54a\uc73c\uba74 --voltage 0.78 \ucc98\ub7fc \uac12\uc744 \uc9c1\uc811 \uc8fc\uc138\uc694."),
    "E-NORPT":   ("\ub9ac\ud3ec\ud2b8 \ud30c\uc77c(.rpt)\uc744 \ubabb \ucc3e\uc558\uc2b5\ub2c8\ub2e4",
                  "--dir \ub85c \uc900 \ud3f4\ub354\uc5d0 \ucf54\ub108\ubcc4 report_timing \uacb0\uacfc\ub97c \ub123\uc5b4 \uc8fc\uc138\uc694."),
    "E-OUTSAME": ("\uacb0\uacfc \ud3f4\ub354\uac00 \uc6d0\ubcf8 \ud3f4\ub354\uc640 \uac19\uc2b5\ub2c8\ub2e4",
                  "--out \uc73c\ub85c \ub2e4\ub978 \ud3f4\ub354\ub97c \uc8fc\uc138\uc694. \uc6d0\ubcf8\uc744 \ub36e\uc5b4\uc4f0\uba74 \ub418\ub3cc\ub9b4 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."),
    "E-OUTFULL": ("\uacb0\uacfc \ud3f4\ub354\uc5d0 \uc774\ubbf8 .rpt \uac00 \uc788\uc2b5\ub2c8\ub2e4",
                  "\ub2e4\ub978 --out \uc744 \uc8fc\uac70\ub098, \ub36e\uc5b4\uc4f8 \uc0dd\uac01\uc774\uba74 --force \ub97c \ubd99\uc774\uc138\uc694."),
    "E-NOPATH":  ("\ub9ac\ud3ec\ud2b8\uc5d0\uc11c \uacbd\ub85c\ub97c \ud558\ub098\ub3c4 \ubabb \uc77d\uc5c8\uc2b5\ub2c8\ub2e4",
                  "report_timing \ucd9c\ub825\uc774 \ub9de\ub294\uc9c0, \ud30c\uc77c\uc774 \ube44\uc9c0 \uc54a\uc558\ub294\uc9c0 \ud655\uc778\ud574 \uc8fc\uc138\uc694."),
    "W-NOCUT":   ("\uc790\ub97c \uac83\uc774 \uc5c6\uc5c8\uc2b5\ub2c8\ub2e4 (\uc6d0\ubcf8\uc774 \uc774\ubbf8 --keep \uc774\ud558)",
                  "\uadf8\ub300\ub85c \ubcf5\uc0ac\ub9cc \ud588\uc2b5\ub2c8\ub2e4. 1_union.py \ub97c \uc6d0\ubcf8\uc73c\ub85c \ub3cc\ub824\ub3c4 \uac19\uc2b5\ub2c8\ub2e4."),
}


def code(c, *msg):
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  \uc815\uc0c1 \uc885\ub8cc           [ %s ]" % c)
        print("=" * 66)
        return
    what, todo = CODE_INFO.get(c, ("", ""))
    print("  %s" % ("\ubb38\uc81c \ubc1c\uc0dd" if c.startswith("E-") else "\ud655\uc778 \ud544\uc694"))
    if what:
        print("    \ubb34\uc5c7\uc774   : %s" % what)
        print("    \ud558\uc2e4 \uc77c  : %s" % todo)
    print("")
    print("    \uc5d0\ub7ec \ucf54\ub4dc: %s" % c)
    print("    (\ud574\uacb0\uc774 \uc548 \ub418\uba74 \uc774 \ucf54\ub4dc\ub97c \uc54c\ub824\uc8fc\uc138\uc694)")
    print("=" * 66)
    sys.exit(1 if c.startswith("E-") else 0)


# ---- \uc790\ub974\uae30 \ubcf8\uccb4 -----------------------------------------------------
# \ud30c\uc77c\uc744 \ub450 \ubc88 \uc77d\ub294\ub2e4. \ud55c \ubc88\uc5d0 \ub05d\ub0b4\ub824\uba74 \ub0a8\uae38 \ube14\ub85d N\uac1c\ub97c \uba54\ubaa8\ub9ac\uc5d0 \ub4e4\uace0 \uc788\uc5b4\uc57c
# \ud558\ub294\ub370, \uadf8\ub7ec\uba74 "\uba54\ubaa8\ub9ac \ub54c\ubb38\uc5d0 \uc904\uc774\ub294 \uac83"\uc774 \ubaa9\uc801\uc778 \uc774 \uc2a4\ud06c\ub9bd\ud2b8\uac00 \uc2a4\uc2a4\ub85c
# \uba54\ubaa8\ub9ac\ub97c \uba39\ub294\ub2e4. \ub450 \ubc88 \uc77d\ub294 \ud3b8\uc774 \ud6e8\uc52c \uc2f8\ub2e4(\ub514\uc2a4\ud06c\ub294 \uc21c\ucc28 \uc77d\uae30\ub77c \ube60\ub974\ub2e4).

def scan_slacks(path, target=None):
    """1\ubc88\uc9f8 \uc77d\uae30 : slack \uac12\ub9cc \ubaa8\uc740\ub2e4. -> (slack \ubaa9\ub85d, Startpoint \uac1c\uc218)

    \uc904 \ub2e8\uc704\ub85c \ub3c8\ub2e4. \ub9ac\ud3ec\ud2b8\uc758 99% \ub294 \ud540 \uc904\uc774\uace0 \uadf8 \uc904\ub4e4\uc740 \uc5b4\ucc28\ud53c \uc544\ubb34\uac83\ub3c4 \uc548
    \uac78\ub9ac\ubbc0\ub85c, \uc815\uaddc\uc2dd\uc744 \uac78\uae30 \uc804\uc5d0 \ubb38\uc790\uc5f4 \uac80\uc0ac\ub85c \uba3c\uc800 \uccd0\ub0b8\ub2e4. `in` \uc740 \uc815\uaddc\uc2dd\ubcf4\ub2e4
    \ud6e8\uc52c \uc2f8\ub2e4.

    (\ub369\uc5b4\ub9ac\ub85c \uc77d\uc5b4 \ud55c \ubc88\uc5d0 \ud6d1\ub294 \ubc29\ubc95\ub3c4 \ud574 \ubd24\ub294\ub370, \ub369\uc5b4\ub9ac\ub97c \uc774\uc5b4 \ubd99\uc774\ub294 \ubcf5\uc0ac\uc640
     findall \uc774 \ub9cc\ub4dc\ub294 \ubaa9\ub85d \ub54c\ubb38\uc5d0 \uc624\ud788\ub824 \ub290\ub9ac\uace0 \uba54\ubaa8\ub9ac\ub3c4 7\ubc30\uc600\ub2e4. \ud30c\uc774\uc36c\uc758
     \uc904 \ub2e8\uc704 \uc77d\uae30\uac00 \uc774\ubbf8 C \ub85c \ucd5c\uc801\ud654\ub3fc \uc788\uc5b4 \uc774 \ud3b8\uc774 \ub0ab\ub2e4.)
    """
    vals = []
    n_start = 0
    vc = VoltCheck(target)
    stat = {"mixed": 0, "novolt": 0, "other": 0, "hdr": None, "read": 0}
    with open(path, "rb") as f:
        for line in f:
            if vc.on():
                vc.feed(line)             # \uc804\uc555\uc744 \ubcfc \ub54c\ub9cc \ud540 \uc904\uae4c\uc9c0 \ud6d1\ub294\ub2e4
            if b"slack" in line:
                m = SLACK_B_RE.match(line)
                if m:
                    v = vc.verdict()
                    if v == VoltCheck.PASS:
                        vals.append(float(m.group(1)))
                    elif v == VoltCheck.MIXED:
                        stat["mixed"] += 1
                    elif v == VoltCheck.NOVOLT:
                        stat["novolt"] += 1
                    else:
                        stat["other"] += 1
                    continue
            if b"Startpoint:" in line and START_B_RE.match(line):
                n_start += 1
    stat["hdr"] = vc.hdr
    stat["read"] = vc.n_read
    stat["first"] = vc.first
    stat["colname"] = vc.colname
    return vals, n_start, stat


def write_trimmed(src, dst, cut, n_keep, target=None):
    """2\ubc88\uc9f8 \uc77d\uae30 : slack \uc774 cut \uc774\ud558\uc778 \uacbd\ub85c \ube14\ub85d\ub9cc \uadf8\ub300\ub85c \uc368\ub0b8\ub2e4.

    \ube14\ub85d \ud558\ub098\ub97c buf \uc5d0 \ubaa8\uc558\ub2e4\uac00, slack \uc904\uc744 \ub9cc\ub098 \ub0a8\uae38 \uac83\uc73c\ub85c \ud310\uc815\ub418\uba74 \uc4f4\ub2e4.
    \uac19\uc740 slack \uc774 \uc5ec\ub7ec \uac1c\ub77c cut \uc5d0\uc11c \uac1c\uc218\uac00 \ub118\uce60 \uc218 \uc788\uc73c\ubbc0\ub85c n_keep \uc5d0\uc11c \uba48\ucd98\ub2e4.
    \ub9e8 \uc55e \uba38\ub9ac\ub9d0(Report : timing ... \uac19\uc740 \uc904)\uc740 \uadf8\ub300\ub85c \uc62e\uae34\ub2e4.
    """
    written = 0
    buf = []
    in_block = False
    vc = VoltCheck(target)
    # \ubc14\uc774\ud2b8 \uadf8\ub300\ub85c \uc62e\uae34\ub2e4. \uc6d0\ubcf8 \ub9ac\ud3ec\ud2b8\ub97c \ud55c \uae00\uc790\ub3c4 \uc548 \ubc14\uafb8\uae30 \uc704\ud574\uc11c\ub2e4
    # (\ub514\ucf54\ub529\ud588\ub2e4\uac00 \ub2e4\uc2dc \uc778\ucf54\ub529\ud558\uba74 \uc774\uc0c1\ud55c \ubb38\uc790\uac00 \uc788\uc744 \ub54c \ub0b4\uc6a9\uc774 \ub2ec\ub77c\uc9c4\ub2e4).
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for line in fi:
            if vc.on():
                vc.feed(line)
            # \uc815\uaddc\uc2dd\uc740 \ud6c4\ubcf4 \uc904\uc5d0\ub9cc \uac74\ub2e4. \ub9ac\ud3ec\ud2b8\uc758 99% \ub294 \ud540 \uc904\uc774\ub77c
            # \uc544\ub798 \ub450 \ubb38\uc790\uc5f4 \uac80\uc0ac\uc5d0\uc11c \ubc14\ub85c \uac78\ub7ec\uc9c4\ub2e4.
            if b"Startpoint:" in line and START_B_RE.match(line):
                if not in_block:
                    fo.write(b"".join(buf))   # \uccab \ube14\ub85d \uc55e = \uba38\ub9ac\ub9d0
                in_block = True
                buf = [line]
                continue
            buf.append(line)
            if not in_block:
                continue                      # \uc544\uc9c1 \uba38\ub9ac\ub9d0 \uad6c\uac04
            if b"slack" not in line:
                continue
            m = SLACK_B_RE.match(line)
            if m:
                ok = vc.verdict() == VoltCheck.PASS
                if ok and written < n_keep and float(m.group(1)) <= cut:
                    fo.write(b"".join(buf))
                    fo.write(b"\n\n")  # \ube14\ub85d \uc0ac\uc774 \ube48 \uc904. \uc6d0\ubcf8\ucc98\ub7fc \ubcf4\uc774\uac8c \ud55c\ub2e4
                    written += 1
                buf = []
    return written


VERIFY = [False]      # --verify \uc5ec\ubd80. \ud558\uc704 \ud504\ub85c\uc138\uc2a4\uc5d0\ub3c4 \ubcf4\uc774\uac8c \ub9ac\uc2a4\ud2b8\ub85c \ub454\ub2e4


def trim_head(src, dst, n_keep, target=None):
    """\ub9e8 \uc55e N\uac1c\ub9cc \uc4f0\uace0 **\uac70\uae30\uc11c \uc77d\uae30\ub97c \uba48\ucd98\ub2e4.** -> (\uc804\uccb4 \uac1c\uc218 or None, \ub0a8\uae34 \uac1c\uc218)

    report_timing \uc740 -sort_by slack \uc774 \uae30\ubcf8\uc774\ub77c \ub9ac\ud3ec\ud2b8\uac00 \uc774\ubbf8 \ub098\uc05c \uac83\ubd80\ud130
    \uc815\ub82c\ub3fc \uc788\ub2e4. \uadf8\ub7ec\uba74 \uc55e\uc5d0\uc11c N\uac1c\uac00 \uace7 \ucd5c\uc545 N\uac1c\ub2e4.

    N\uac1c\ub97c \ucc44\uc6b0\uba74 **\ud30c\uc77c \ub098\uba38\uc9c0\ub294 \uc544\uc608 \uc77d\uc9c0 \uc54a\ub294\ub2e4.** \uc218 GB \uc9dc\ub9ac\uc5d0\uc11c \uc55e\ubd80\ubd84\ub9cc
    \uc77d\uace0 \ub05d\ub098\ubbc0\ub85c \ud06c\uae30\uc640 \uc0c1\uad00\uc5c6\uc774 \ube60\ub974\ub2e4. \ub300\uc2e0 \uc804\uccb4 \uacbd\ub85c\uac00 \uba87 \uac1c\uc778\uc9c0\ub294
    \uc54c \uc218 \uc5c6\uc5b4 None \uc73c\ub85c \ub3cc\ub824\uc900\ub2e4(\ud654\uba74\uc5d0 '?' \ub85c \ud45c\uc2dc\ub41c\ub2e4).

    \uc815\ub82c\uc744 \ubabb \ubbff\uaca0\uc73c\uba74 --verify \ub97c \uc900\ub2e4. \uadf8\ub7ec\uba74 trim_verify() \uac00 \ub05d\uae4c\uc9c0
    \ud6d1\uc5b4 \ud655\uc778\ud558\uace0, \uc815\ub82c\uc774 \uc544\ub2c8\uba74 \ub450 \ubc88 \uc77d\uae30\ub85c \ub418\ub3cc\uc544\uac04\ub2e4.
    """
    written = 0
    buf = []
    in_block = False
    vc = VoltCheck(target)
    stat = {"mixed": 0, "novolt": 0, "other": 0, "hdr": None, "read": 0}
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for line in fi:
            if vc.on():
                vc.feed(line)
            if b"Startpoint:" in line and START_B_RE.match(line):
                if not in_block:
                    fo.write(b"".join(buf))   # \uccab \ube14\ub85d \uc55e = \uba38\ub9ac\ub9d0
                in_block = True
                buf = [line]
                continue
            buf.append(line)
            if not in_block:
                continue
            if b"slack" not in line:
                continue
            if not SLACK_B_RE.match(line):
                continue
            # \uc804\uc555\uc774 \uc5b4\uae0b\ub09c \uacbd\ub85c\ub294 **\uc138\uc9c0 \uc54a\uace0 \ubc84\ub9b0\ub2e4.** \uadf8\ub798\uc57c n_keep \uc774
            # "\uc4f8 \uc218 \uc788\ub294 \uacbd\ub85c N\uac1c" \ub97c \ub73b\ud55c\ub2e4. \uc138\uace0 \ub098\uc11c \uac70\ub974\uba74 N\uac1c\ubcf4\ub2e4 \uc801\uac8c \ub0a8\ub294\ub2e4.
            v = vc.verdict()
            if v != VoltCheck.PASS:
                if v == VoltCheck.MIXED:
                    stat["mixed"] += 1
                elif v == VoltCheck.NOVOLT:
                    stat["novolt"] += 1
                else:
                    stat["other"] += 1
                buf = []
                continue
            fo.write(b"".join(buf))
            fo.write(b"\n\n")
            written += 1
            buf = []
            if written >= n_keep:
                break                      # \ub098\uba38\uc9c0\ub294 \uc77d\uc9c0 \uc54a\ub294\ub2e4
    stat["hdr"] = vc.hdr
    stat["read"] = vc.n_read
    stat["first"] = vc.first
    stat["colname"] = vc.colname
    return None, written, stat


def trim_verify(src, dst, n_keep, target=None):
    """\ud55c \ubc88\ub9cc \uc77d\uace0 \uc790\ub974\ub418, \uc815\ub82c\uc774 \ub9de\ub294\uc9c0 \ub05d\uae4c\uc9c0 \ud655\uc778\ud55c\ub2e4. (--verify)

    -> (\uc804\uccb4 \uac1c\uc218, \ub0a8\uae34 \uac1c\uc218)  \ub610\ub294 \uc815\ub82c\uc774 \uc544\ub2c8\uba74 None.

    report_timing \uc744 -sort_by slack \uc73c\ub85c \ubf51\uc73c\uba74 \ub9ac\ud3ec\ud2b8\uac00 **\uc774\ubbf8 \ub098\uc05c \uac83\ubd80\ud130**
    \uc815\ub82c\ub3fc \uc788\ub2e4. \uadf8\ub7ec\uba74 \uc55e\uc5d0\uc11c N\uac1c\ub97c \uadf8\ub300\ub85c \uc4f0\uba74 \ub05d\uc774\uace0, slack \uc744 \ubaa8\uc544 \uc815\ub82c\ud560
    \ud544\uc694\ub3c4 \ud30c\uc77c\uc744 \ub450 \ubc88 \uc77d\uc744 \ud544\uc694\ub3c4 \uc5c6\ub2e4.

    \ub2e4\ub9cc \uc815\ub82c\ub3fc \uc788\ub2e4\uace0 \ubbff\uc5b4 \ubc84\ub9ac\uba74 \uc548 \ub41c\ub2e4. -sort_by \ub97c \uc548 \uc900 \ub9ac\ud3ec\ud2b8\ub3c4 \uc788\uace0,
    path group \ubcc4\ub85c \ub530\ub85c \uc815\ub82c\ub3fc \ubd99\uc740 \ub9ac\ud3ec\ud2b8\ub3c4 \uc788\ub2e4. \uadf8\ub7f0 \ud30c\uc77c\uc5d0\uc11c \uc55e N\uac1c\ub9cc
    \uc9d1\uc73c\uba74 \ub4a4\uc5d0 \uc788\ub294 \ub354 \ub098\uc05c \uacbd\ub85c\ub97c \ub193\uce5c\ub2e4.

    \uadf8\ub798\uc11c N\uac1c\ub97c \uc4f4 \ub4a4\uc5d0\ub3c4 **\ub05d\uae4c\uc9c0 slack \ub9cc \ud6d1\uc5b4\ubcf4\uba70** \ud655\uc778\ud55c\ub2e4.
      - \ub4a4\uc5d0 \ub354 \ub098\uc05c(\uc791\uc740) slack \uc774 \ud558\ub098\ub3c4 \uc5c6\ub2e4  -> \uc55e N\uac1c\uac00 \uc815\ub9d0 \ucd5c\uc545 N\uac1c\ub2e4
      - \ud558\ub098\ub77c\ub3c4 \uc788\ub2e4                           -> None. \ubd80\ub974\ub294 \ucabd\uc774 \ub450 \ubc88
                                                   \uc77d\uae30 \ubc29\uc2dd\uc73c\ub85c \ub2e4\uc2dc \ud55c\ub2e4
    \ub4a4\ucabd \ud6d1\uae30\ub294 \ube14\ub85d\uc744 \ubaa8\uc73c\uc9c0 \uc54a\uace0 \ubb38\uc790\uc5f4 \uac80\uc0ac\ub9cc \ud558\ubbc0\ub85c \uac70\uc758 \uacf5\uc9dc\ub2e4.
    \ub364\uc73c\ub85c \uc804\uccb4 \uacbd\ub85c \uac1c\uc218\ub3c4 \uc815\ud655\ud788 \uc138\uc5b4\uc9c4\ub2e4.
    """
    written = 0
    n_total = 0
    worst_kept = None      # \ub0a8\uae34 \uac83 \uc911 \uac00\uc7a5 \ub098\uc058\uc9c0 \uc54a\uc740(\uac00\uc7a5 \ud070) slack
    buf = []
    in_block = False
    vc = VoltCheck(target)
    stat = {"mixed": 0, "novolt": 0, "other": 0, "hdr": None, "read": 0}
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for line in fi:
            if vc.on():
                vc.feed(line)
            if written < n_keep:
                if b"Startpoint:" in line and START_B_RE.match(line):
                    if not in_block:
                        fo.write(b"".join(buf))   # \uccab \ube14\ub85d \uc55e = \uba38\ub9ac\ub9d0
                    in_block = True
                    buf = [line]
                    continue
                buf.append(line)
                if not in_block:
                    continue
            if b"slack" not in line:
                continue
            m = SLACK_B_RE.match(line)
            if not m:
                continue
            sl = float(m.group(1))
            n_total += 1
            v = vc.verdict()
            if v != VoltCheck.PASS:
                # \uc804\uc555\uc774 \uc5b4\uae0b\ub09c \uacbd\ub85c. \ub0a8\uae30\uc9c0\ub3c4, \uc815\ub82c \ud310\uc815\uc5d0 \uc4f0\uc9c0\ub3c4 \uc54a\ub294\ub2e4.
                if v == VoltCheck.MIXED:
                    stat["mixed"] += 1
                elif v == VoltCheck.NOVOLT:
                    stat["novolt"] += 1
                else:
                    stat["other"] += 1
                buf = []
                continue
            if written < n_keep:
                if worst_kept is None or sl > worst_kept:
                    worst_kept = sl
                fo.write(b"".join(buf))
                fo.write(b"\n\n")
                written += 1
                buf = []
            elif sl < worst_kept:
                return None            # \ub4a4\uc5d0 \ub354 \ub098\uc05c \uac83\uc774 \uc788\ub2e4. \uc815\ub82c \uc544\ub2d8
    stat["hdr"] = vc.hdr
    stat["read"] = vc.n_read
    stat["first"] = vc.first
    stat["colname"] = vc.colname
    return n_total, written, stat


def _trim_one(job):
    """\ucf54\ub108 \ud558\ub098\ub97c \uc904\uc778\ub2e4. -> (\ucf54\ub108, \uc6d0\ub798 \uac1c\uc218, \ub0a8\uae34 \uac1c\uc218, \ud30c\uc77c \ud06c\uae30, \ube44\uace0)"""
    src, dst, n_keep, target = job
    corner = os.path.splitext(os.path.basename(src))[0]

    if VERIFY[0]:
        r = trim_verify(src, dst, n_keep, target)
    else:
        r = trim_head(src, dst, n_keep, target)
    if r is not None:
        n_total, written, stat = r
        if not written:
            return corner, 0, 0, 0, "\uacbd\ub85c \uc5c6\uc74c", stat, target
        return corner, n_total, written, os.path.getsize(dst), "", stat, target

    # \uc815\ub82c\ub3fc \uc788\uc9c0 \uc54a\uc558\ub2e4. slack \uc744 \ub2e4 \ubaa8\uc544 \ubb38\ud131\uac12\uc744 \uad6c\ud55c \ub4a4 \ub2e4\uc2dc \uc4f4\ub2e4.
    vals, n_start, stat = scan_slacks(src, target)
    if not vals:
        return corner, n_start, 0, 0, "\uacbd\ub85c \uc5c6\uc74c", stat, target
    if len(vals) <= n_keep:
        cut = max(vals)                     # \uc804\ubd80 \ub0a8\uae34\ub2e4
    else:
        cut = sorted(vals)[n_keep - 1]
    written = write_trimmed(src, dst, cut, n_keep, target)
    return corner, len(vals), written, os.path.getsize(dst), "\uc815\ub82c \uc548 \ub428", stat, target


def resolve_jobs(want, n_files):
    if n_files <= 1:
        return 1
    if want and want > 0:
        return min(want, n_files)
    try:
        ncpu = multiprocessing.cpu_count()
    except NotImplementedError:
        ncpu = 1
    return max(1, min(ncpu, n_files, 8))


def run_jobs(jobs_list, jobs):
    """\ud30c\uc77c \uc21c\uc11c\ub97c \uc9c0\ud0a4\uba70 \ucc98\ub9ac\ud55c\ub2e4. \ud504\ub85c\uc138\uc2a4\ub97c \ubabb \ub744\uc6b0\uba74 1\uac1c\ub85c \ub418\ub3cc\uc544\uac04\ub2e4."""
    if jobs <= 1:
        for j in jobs_list:
            yield _trim_one(j)
        return
    try:
        pool = multiprocessing.Pool(processes=jobs)
    except Exception as e:
        print("  [ \uc54c\ub9bc ] \ud504\ub85c\uc138\uc2a4\ub97c \ubabb \ub744\uc6cc 1\uac1c\ub85c \ub3cc\ub9bd\ub2c8\ub2e4 (%s)" % e)
        for j in jobs_list:
            yield _trim_one(j)
        return
    try:
        for r in pool.imap(_trim_one, jobs_list, 1):
            yield r
        pool.close()
    finally:
        pool.terminate()
        pool.join()


def probe(path, target):
    """\uc804\uc555 \uc5f4\uc744 \uc5b4\ub5bb\uac8c \uc778\uc2dd\ud558\ub294\uc9c0 \ubcf4\uc5ec \uc900\ub2e4. (--probe)

    "\uc5f4 \uc774\ub984\uc744 \ub9de\ucdc4\ub294\ub370\ub3c4 \ub0a8\uae40\uc774 0" \uac19\uc740 \uc0c1\ud669\uc5d0\uc11c, \ubb34\uc5c7\uc774 \uc548 \ub9de\ub294\uc9c0\ub294 \ub9ac\ud3ec\ud2b8\ub97c
    \uc9c1\uc811 \ubd10\uc57c \uc548\ub2e4. \uadf8\ub7f0\ub370 \ub9ac\ud3ec\ud2b8\ub294 \ud604\uc7a5\uc5d0\ub9cc \uc788\ub2e4. \uadf8\ub798\uc11c \ub3c4\uad6c\uac00 \ub300\uc2e0 \ubcf4\uace0\ud55c\ub2e4.
    """
    print("")
    print("  \ud30c\uc77c : %s" % path)
    print("  \ubaa9\ud45c \uc804\uc555 : %s" % target)
    hdr = None
    hdr_no = 0
    n = 0
    shown = 0
    span = None
    with open(path, "rb") as f:
        for line in f:
            n += 1
            if hdr is None and VoltCheck.is_header(line):
                hdr = line.rstrip()
                hdr_no = n
                span = volt_span(hdr)
                print("")
                print("  \uba38\ub9ac\ub9d0 (%d\ubc88\uc9f8 \uc904):" % hdr_no)
                print("    |%s|" % hdr.decode("utf-8", "replace"))
                # \uba38\ub9ac\ub9d0\uc5d0\uc11c \uc54c\uc544\ubcf8 \ub0b1\ub9d0\ub4e4\uc744 \uc804\ubd80 \ubcf4\uc5ec \uc900\ub2e4 -> \uc774\ub984\uc744 \uc5ec\uae30\uc11c \uace0\ub978\ub2e4
                words = []
                for m in WORD_B_RE.finditer(hdr.lower()):
                    try:
                        words.append(m.group(0).decode("ascii"))
                    except UnicodeDecodeError:
                        pass
                print("  \uba38\ub9ac\ub9d0\uc5d0\uc11c \uc77d\uc740 \uc5f4 \uc774\ub984 : %s" % ", ".join(words))
                print("  VOLT_NAMES              : %s" % ", ".join(VOLT_NAMES))
                if span is None:
                    print("  -> \uacb9\uce58\ub294 \uc774\ub984\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \uc704 \ubaa9\ub85d\uc5d0\uc11c \uc804\uc555 \uc5f4\uc744 \uace8\ub77c")
                    print("     0_trim.py \ub9e8 \uc704 VOLT_NAMES \uc5d0 \ub123\uc5b4 \uc8fc\uc138\uc694.")
                    return
                print("  -> \uc804\uc555 \uc5f4\uc744 \ucc3e\uc558\uc2b5\ub2c8\ub2e4. %d\ubc88\uc9f8 \uae00\uc790\ubd80\ud130 \uc904 \ub05d\uae4c\uc9c0" % span)
                continue
            if span is None:
                continue
            v = line_volt(line, span)
            if v is not None and shown < 5:
                shown += 1
                txt = line.rstrip().decode("utf-8", "replace")
                print("    %-70s -> %s" % (txt[-70:], v))
    if hdr is None:
        print("")
        print("  \uba38\ub9ac\ub9d0('  Point ...' \ub85c \uc2dc\uc791\ud558\ub294 \uc904)\uc744 \ubabb \ucc3e\uc558\uc2b5\ub2c8\ub2e4.")
        print("  \uc774 \ub9ac\ud3ec\ud2b8\ub294 -nosplit \uc5c6\uc774 \ubf51\ud614\uac70\ub098 \ud615\uc2dd\uc774 \ub2e4\ub97c \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
        return
    if shown == 0:
        print("")
        print("  \uc5f4\uc740 \ucc3e\uc558\ub294\ub370 \uadf8 \uc790\ub9ac\uc5d0\uc11c \uc22b\uc790\ub97c \ud558\ub098\ub3c4 \ubabb \uc77d\uc5c8\uc2b5\ub2c8\ub2e4.")
        print("  \uac12\uc774 \ub2e4\ub978 \uc5f4\uc5d0 \uc788\uac70\ub098, \uc815\ub82c\uc774 \uba38\ub9ac\ub9d0\uacfc \uc5b4\uae0b\ub09c \uac83\uc785\ub2c8\ub2e4.")


def main():
    ap = argparse.ArgumentParser(
        description="\ucf54\ub108\ubcc4 \ub9ac\ud3ec\ud2b8\ub97c \ub098\uc05c \uac83 N\uac1c\ub9cc \ub0a8\uae34 \ub9ac\ud3ec\ud2b8\ub85c \uc904\uc778\ub2e4.")
    ap.add_argument("--dir", required=True,
                    help="\uc6d0\ubcf8 .rpt \uac00 \ub4e4\uc5b4 \uc788\ub294 \ud3f4\ub354")
    ap.add_argument("--keep", type=int, default=10000, metavar="N",
                    help="\ucf54\ub108\ub9c8\ub2e4 \ub0a8\uae38 \uacbd\ub85c \uc218. slack \uc774 \ub098\uc05c \uac83\ubd80\ud130. (\uae30\ubcf8 10000)")
    ap.add_argument("--out", default=None,
                    help="\uacb0\uacfc \ud3f4\ub354. \uc0dd\ub7b5\ud558\uba74 <dir>_top<N>")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup/hold \ubd84\uc11d \uc885\ub958. \uae30\ubcf8 setup. \uc790\ub974\ub294 \uae30\uc900\uc740 \uac19\uace0, "
                         "\uc644\ub8cc \ud6c4 \ucd9c\ub825\ud558\ub294 1_union.py \uba85\ub839\uc5d0 \uadf8\ub300\ub85c \uc804\ub2ec\ud55c\ub2e4")
    ap.add_argument("--jobs", "-j", type=int, default=1, metavar="N",
                    help="\ucf54\ub108\ub97c \ub3d9\uc2dc\uc5d0 \uba87 \uac1c \ucc98\ub9ac\ud560\uc9c0. **\uae30\ubcf8 1(\ud558\ub098\uc529)**. "
                         "0 \uc744 \uc8fc\uba74 \uc790\ub3d9(\ucf54\uc5b4 \uc218\uc640 \ucf54\ub108 \uc218 \uc911 \uc791\uc740 \ucabd, \ucd5c\ub300 8)")
    ap.add_argument("--verify", action="store_true",
                    help="\uc815\ub82c\ub3fc \uc788\ub294\uc9c0 \ub05d\uae4c\uc9c0 \ud655\uc778\ud55c\ub2e4. \ub9ac\ud3ec\ud2b8\ub97c -sort_by slack "
                         "\uc5c6\uc774 \ubf51\uc558\uc744 \uac00\ub2a5\uc131\uc774 \uc788\uc744 \ub54c\ub9cc. \uae30\ubcf8\uc740 \ud655\uc778 \uc548 \ud568 "
                         "(\uc815\ub82c\uc744 \ubbff\uace0 \uc55e\uc5d0\uc11c N\uac1c\ub9cc \uc77d\uace0 \uba48\ucd98\ub2e4)")
    ap.add_argument("--voltage", default=None, metavar="V",
                    help="\uc804\uc555\uc774 \ub2e4\ub978 \uc140(macro \ub4f1)\uc744 \uc9c0\ub098\ub294 \uacbd\ub85c\ub97c \ubc84\ub9b0\ub2e4. "
                         "\uac12\uc744 \uc8fc\uba74 \ubaa8\ub4e0 \ucf54\ub108\uc5d0 \uadf8 \uc804\uc555\uc744 \uc4f0\uace0, 'auto' \ub97c \uc8fc\uba74 "
                         "**\ucf54\ub108 \uc774\ub984\uc5d0\uc11c \ucf54\ub108\ub9c8\ub2e4 \ub530\ub85c** \uc77d\ub294\ub2e4(tt0p78v25c -> 0.78). "
                         "\uc0dd\ub7b5\ud558\uba74 \uc804\uc555\uc744 \uc544\uc608 \uc548 \ubcf8\ub2e4(\uc608\uc804 \ub3d9\uc791)")
    ap.add_argument("--probe", action="store_true",
                    help="\uc790\ub974\uc9c0 \uc54a\uace0, \uc804\uc555 \uc5f4\uc744 \uc5b4\ub5bb\uac8c \uc778\uc2dd\ud558\ub294\uc9c0\ub9cc \ubcf4\uc5ec\uc900\ub2e4. "
                         "'\uc5f4 \uc774\ub984\uc744 \ub9de\ucdc4\ub294\ub370 \ub0a8\uae40\uc774 0' \uc77c \ub54c \uc774\uac78\ub85c \ud655\uc778\ud55c\ub2e4")
    ap.add_argument("--force", action="store_true",
                    help="\uacb0\uacfc \ud3f4\ub354\uc5d0 \uc774\ubbf8 .rpt \uac00 \uc788\uc5b4\ub3c4 \ub36e\uc5b4\uc4f4\ub2e4")
    args = ap.parse_args()
    VERIFY[0] = args.verify

    d = args.dir.rstrip("/")
    out = args.out or ("%s_top%d" % (d, args.keep))

    print("=" * 68)
    print("0 - \ub9ac\ud3ec\ud2b8 \uc904\uc774\uae30  (\ucf54\ub108\ub9c8\ub2e4 \ub098\uc05c \uac83 %d\uac1c\ub9cc)" % args.keep)
    print("=" * 68)

    files = sorted(glob.glob(os.path.join(d, "*.rpt")))
    if not files:
        print("")
        code("E-NORPT",
             "[ \uc2e4\ud328 ] %s \uc548\uc5d0 .rpt \ud30c\uc77c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4." % d)

    # --probe \ub294 \uc790\ub974\uc9c0 \uc54a\uace0 \ud655\uc778\ub9cc \ud55c\ub2e4. \ucd9c\ub825 \ud3f4\ub354 \uac80\uc0ac\ubcf4\ub2e4 **\uba3c\uc800** \ub454\ub2e4
    # -- \uacb0\uacfc \ud3f4\ub354\uac00 \uc774\ubbf8 \ucc28 \uc788\uc5b4\ub3c4 \uc9c4\ub2e8\uc740 \ub418\uc5b4\uc57c \ud558\uae30 \ub54c\ubb38\uc774\ub2e4.
    if args.probe:
        print("=" * 68)
        print("  --probe : \uc790\ub974\uc9c0 \uc54a\uace0 \uc804\uc555 \uc5f4 \uc778\uc2dd\ub9cc \ud655\uc778\ud569\ub2c8\ub2e4")
        print("=" * 68)
        for f in files:
            nm = os.path.splitext(os.path.basename(f))[0]
            if args.voltage is None:
                tv = None
            elif str(args.voltage).lower() == "auto":
                tv = voltage_of_corner(nm)
            else:
                tv = float(args.voltage)
            probe(f, tv)
        print("")
        print("-" * 68)
        print("  \ud655\uc778\uc774 \ub05d\ub098\uba74 --probe \ub97c \ube7c\uace0 \ub2e4\uc2dc \ub3cc\ub9ac\uc138\uc694.")
        return

    if os.path.abspath(out) == os.path.abspath(d):
        print("")
        code("E-OUTSAME",
             "[ \uc2e4\ud328 ] --out \uc774 \uc6d0\ubcf8 \ud3f4\ub354\uc640 \uac19\uc2b5\ub2c8\ub2e4: %s" % out)

    if os.path.isdir(out) and glob.glob(os.path.join(out, "*.rpt")) \
            and not args.force:
        print("")
        code("E-OUTFULL",
             "[ \uc2e4\ud328 ] %s \uc5d0 \uc774\ubbf8 .rpt \uac00 \uc788\uc2b5\ub2c8\ub2e4." % out)

    if not os.path.isdir(out):
        os.makedirs(out)

    jobs = resolve_jobs(args.jobs, len(files))
    src_mb = sum(os.path.getsize(f) for f in files) / 1048576.0

    print("  \uc6d0\ubcf8   : %s   (%d\ucf54\ub108, \ud569\uacc4 %.0f MB)" % (d, len(files), src_mb))
    print("  \uacb0\uacfc   : %s" % out)
    print("  \ub0a8\uae38 \uac83: \ucf54\ub108\ub9c8\ub2e4 %d\uac1c  (slack \uc774 \ub098\uc05c \uac83\ubd80\ud130)" % args.keep)
    if jobs > 1:
        print("  \ub3d9\uc2dc   : %d\uac1c\uc529  (--jobs %d)" % (jobs, jobs))
    elif len(files) > 1:
        print("  \ub3d9\uc2dc   : 1\uac1c\uc529 (\uae30\ubcf8).  -j 8 \uc744 \uc8fc\uba74 \ucf54\ub108\ub97c \ub098\ub220 \ucc98\ub9ac\ud569\ub2c8\ub2e4")
    print("")

    # \ucf54\ub108\ub9c8\ub2e4 \ubaa9\ud45c \uc804\uc555\uc744 \uc815\ud55c\ub2e4. 0_trim \uc740 \ucf54\ub108\ub97c \uc5ec\ub7ec \uac1c \ud55c\uaebc\ubc88\uc5d0 \ub3cc\ubbc0\ub85c
    # \uac12 \ud558\ub098\ub85c \uace0\uc815\ud558\uba74 \uc548 \ub41c\ub2e4 -- \ucf54\ub108\uac00 \uace7 \uc804\uc555\uc774\ub2e4.
    targets = {}
    novolt_name = []
    for f in files:
        nm = os.path.splitext(os.path.basename(f))[0]
        if args.voltage is None:
            targets[f] = None
        elif str(args.voltage).lower() == "auto":
            v = voltage_of_corner(nm)
            targets[f] = v
            if v is None:
                novolt_name.append(nm)
        else:
            targets[f] = float(args.voltage)

    if novolt_name:
        print("")
        code("E-VNAME",
             "[ \uc2e4\ud328 ] \ucf54\ub108 \uc774\ub984\uc5d0\uc11c \uc804\uc555\uc744 \ubabb \uc77d\uc5c8\uc2b5\ub2c8\ub2e4:",
             *["      %s" % n for n in novolt_name[:10]],
             )

    if args.voltage is not None:
        print("  \uc804\uc555   : %s" % ("\ucf54\ub108 \uc774\ub984\uc5d0\uc11c (auto)"
                                 if str(args.voltage).lower() == "auto"
                                 else "%s V \uace0\uc815" % args.voltage))
        print("           \uc804\uc555\uc774 \uc11e\uc778 \uacbd\ub85c(macro \ub4f1)\ub294 **\uc138\uae30 \uc804\uc5d0** \ubc84\ub9bd\ub2c8\ub2e4.")
        print("           \uadf8\ub798\uc11c --keep %d \ub294 '\ub2e8\uc77c \uc804\uc555 %d\uac1c' \ub97c \ub73b\ud569\ub2c8\ub2e4."
              % (args.keep, args.keep))
        print("")

    jobs_list = [(f, os.path.join(out, os.path.basename(f)), args.keep,
                  targets[f]) for f in files]

    volt_on = args.voltage is not None
    if volt_on:
        print("  %-24s %6s %8s %8s %7s %8s %8s"
              % ("\ucf54\ub108", "\uc804\uc555", "\uc6d0\ub798", "\ub0a8\uae40", "mixed", "\uc804\uc555\uc5c6\uc74c", "\ub2e4\ub978\uc804\uc555"))
        print("  " + "-" * 76)
    else:
        print("  %-30s %10s %10s %10s" % ("\ucf54\ub108", "\uc6d0\ub798", "\ub0a8\uae40", "\ud30c\uc77c"))
        print("  " + "-" * 64)
    tot_before = tot_after = tot_bytes = 0
    n_uncut = 0
    tot_mixed = tot_novolt = tot_other = 0
    tot_read = 0
    diag_hdr = None
    # n_before \uac00 None \uc774\uba74 '\uc6d0\ub798 \uba87 \uac1c\uc778\uc9c0 \uc548 \uc14c\ub2e4'\ub294 \ub73b\uc774\ub2e4(\uae30\ubcf8 \ub3d9\uc791).
    # \uc55e\uc5d0\uc11c N\uac1c\ub9cc \uc77d\uace0 \uba48\ucd94\ubbc0\ub85c \uc804\uccb4 \uac1c\uc218\ub97c \uc54c \uc218\uac00 \uc5c6\ub2e4. --verify \ub97c \uc8fc\uba74 \uc13c\ub2e4.
    unknown_total = False
    for corner, n_before, n_after, nbytes, note, stat, tgt in run_jobs(jobs_list, jobs):
        if n_before is None:
            unknown_total = True
        else:
            tot_before += n_before
            if n_before and n_before <= args.keep:
                n_uncut += 1
        tot_after += n_after
        tot_bytes += nbytes
        tot_mixed += stat["mixed"]
        tot_novolt += stat["novolt"]
        tot_other += stat["other"]
        tot_read += stat.get("read", 0)
        if diag_hdr is None and stat.get("hdr") is not None:
            diag_hdr = stat["hdr"]
        if volt_on:
            print("  %-24s %6s %8s %8d %7d %8d %8d"
                  % (corner[:24], tgt if tgt is not None else "?",
                     "?" if n_before is None else n_before,
                     n_after, stat["mixed"], stat["novolt"], stat["other"]))
            # \uc804\uc555 \uc5f4\uc744 \uc2e4\uc81c\ub85c \ub9de\ucdc4\ub294\uc9c0 **\ubc14\ub85c** \ubcf4\uc5ec \uc900\ub2e4. \ud45c \uc22b\uc790\ub9cc\uc73c\ub85c\ub294
            # "\uc774\ub984\uc774 \uc548 \ub9de\uc558\ub098 \uac12\uc774 \uc774\uc0c1\ud55c\uac00" \ub97c \uc54c \uc218 \uc5c6\ub2e4.
            fst = stat.get("first")
            if fst is not None:
                print("      \uc5f4 '%s' \ub9de\uc74c -> \uccab \uac12 %s   |%s|"
                      % (stat.get("colname") or "?", fst[0],
                         fst[1].decode("utf-8", "replace")))
            elif stat.get("hdr") is None:
                print("      \uba38\ub9ac\ub9d0\uc744 \ubabb \ucc3e\uc74c")
            else:
                print("      \uc5f4\uc744 \ubabb \ub9de\ucda4 (\uc544\ub798 \uc9c4\ub2e8 \ucc38\uace0)")
        else:
            print("  %-30s %10s %10d %9.0fMB %s"
                  % (corner, "?" if n_before is None else n_before,
                     n_after, nbytes / 1048576.0, note))
    if volt_on:
        print("  " + "-" * 76)
        print("  %-24s %6s %8s %8d %7d %8d %8d"
              % ("\ud569\uacc4", "", "?" if unknown_total else tot_before,
                 tot_after, tot_mixed, tot_novolt, tot_other))
        print("")
        # \uc804\uc555\uc744 \ud558\ub098\ub3c4 \ubabb \uc77d\uc5c8\uc73c\uba74 \uadf8\ub0e5 \ub118\uc5b4\uac00\uc9c0 \uc54a\ub294\ub2e4. \ubb34\uc5c7\uc744 \ubd24\uace0 \ubb34\uc5c7\uc744
        # \ucc3e\uace0 \uc788\uc5c8\ub294\uc9c0 \uc5ec\uae30\uc11c \ubc14\ub85c \ubcf4\uc5ec \uc900\ub2e4. \ub9ac\ud3ec\ud2b8\ub294 \ud604\uc7a5\uc5d0\ub9cc \uc788\uc73c\ubbc0\ub85c,
        # \uc774 \ucd9c\ub825\uc774 \uc5c6\uc73c\uba74 \uc6d0\uc778\uc744 \uc54c \ubc29\ubc95\uc774 \uc5c6\ub2e4.
        if tot_read == 0 and diag_hdr is not None:
            print("")
            print("  " + "!" * 66)
            print("  \uc804\uc555 \uac12\uc744 \ud55c \uc904\ub3c4 \ubabb \uc77d\uc5c8\uc2b5\ub2c8\ub2e4. \uc544\ub798\ub97c \ud655\uc778\ud574 \uc8fc\uc138\uc694.")
            print("")
            print("  \ub9ac\ud3ec\ud2b8 \uba38\ub9ac\ub9d0:")
            print("    |%s|" % diag_hdr.decode("utf-8", "replace"))
            words = []
            for m in WORD_B_RE.finditer(diag_hdr.lower()):
                try:
                    words.append(m.group(0).decode("ascii"))
                except UnicodeDecodeError:
                    pass
            print("")
            print("  \ub9ac\ud3ec\ud2b8\uc5d0 \uc788\ub294 \uc5f4 \uc774\ub984 : %s" % ", ".join(words))
            print("  \ucc3e\uace0 \uc788\ub294 \uc774\ub984        : %s" % ", ".join(VOLT_NAMES))
            hit = [w for w in words if w in _VOLT_LC]
            if hit:
                print("  -> \uc774\ub984\uc740 '%s' \ub85c \ub9de\uc558\ub294\ub370 \uadf8 \uc790\ub9ac\uc5d0 \uc22b\uc790\uac00 \uc5c6\uc2b5\ub2c8\ub2e4."
                      % ", ".join(hit))
                print("     \uac12\uc774 \ub2e4\ub978 \uc5f4\uc5d0 \uc788\uac70\ub098 \uc815\ub82c\uc774 \uba38\ub9ac\ub9d0\uacfc \uc5b4\uae0b\ub09c \uac83\uc785\ub2c8\ub2e4.")
            else:
                print("  -> \uacb9\uce58\ub294 \uc774\ub984\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \uc704 \ubaa9\ub85d\uc5d0\uc11c \uc804\uc555 \uc5f4\uc744 \uace8\ub77c")
                print("     0_trim.py \ub9e8 \uc704 VOLT_NAMES \uc5d0 \ub123\uc5b4 \uc8fc\uc138\uc694.")
            print("  " + "!" * 66)
        elif tot_read == 0:
            print("")
            print("  " + "!" * 66)
            print("  \uc804\uc555 \uac12\uc744 \ud55c \uc904\ub3c4 \ubabb \uc77d\uc5c8\uace0, **\uba38\ub9ac\ub9d0\ub3c4 \ubabb \ucc3e\uc558\uc2b5\ub2c8\ub2e4.**")
            print("  \uc774 \ub9ac\ud3ec\ud2b8\ub294 \ud615\uc2dd\uc774 \ub2e4\ub97c \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
            print("")
            print("  \ub9ac\ud3ec\ud2b8 \uc55e\ubd80\ubd84\uc5d0\uc11c \uba38\ub9ac\ub9d0\ucc98\ub7fc \ubcf4\uc774\ub294 \uc904\ub4e4 (\uc22b\uc790 \uc5c6\ub294 \uc904):")
            shown = 0
            try:
                with open(files[0], "rb") as _f:
                    for _i, _l in enumerate(_f):
                        if _i > 400 or shown >= 8:
                            break
                        _t = _l.rstrip()
                        if len(_t) < 20 or DIGIT_B_RE.search(_t):
                            continue
                        if len(WORD_B_RE.findall(_t.lower())) < 3:
                            continue
                        shown += 1
                        print("    %3d| %s" % (_i + 1,
                              _t[:180].decode("utf-8", "replace")))
            except Exception as _e:                    # noqa: BLE001
                print("    (\uc77d\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4: %s)" % _e)
            if shown == 0:
                print("    (\uadf8\ub7f0 \uc904\uc774 \uc5c6\uc2b5\ub2c8\ub2e4)")
            print("")
            print("  \ucc3e\uace0 \uc788\ub294 \uc774\ub984 : %s" % ", ".join(VOLT_NAMES))
            print("  \uc704 \uc904\ub4e4 \uc911 \uc804\uc555 \uc5f4\uc774 \uc788\ub294 \uc904\uc744 \ubcf4\uace0, \uadf8 \uc774\ub984\uc744")
            print("  0_trim.py \ub9e8 \uc704 VOLT_NAMES \uc5d0 \ub123\uc5b4 \uc8fc\uc138\uc694.")
            print("  " + "!" * 66)

        print("  mixed    = \uc804\uc555\uc774 \ub450 \uac1c \uc774\uc0c1 \uc11e\uc778 \uacbd\ub85c. macro \ub4f1 \ub2e4\ub978 \uc804\uc6d0\uc744 \uc9c0\ub098\uac10")
        print("  \uc804\uc555\uc5c6\uc74c = \uadf8 \uacbd\ub85c\uc5d0\uc11c \uc804\uc555 \uac12\uc744 \ud558\ub098\ub3c4 \ubabb \uc77d\uc74c")
        print("             (\uc804\ubd80 \uc774 \uce78\uc774\uba74 VOLT_NAMES \uc758 \uc5f4 \uc774\ub984\uc774 \uc2e4\uc81c\uc640 \ub2e4\ub978 \uac83)")
        print("  \ub2e4\ub978\uc804\uc555 = \uc804\uc555\uc740 \ud558\ub098\uc778\ub370 \ucf54\ub108 \uc804\uc555\uc774 \uc544\ub2d8")
        print("  \uc704 \uc14b\uc740 **\uc138\uae30 \uc804\uc5d0** \ubc84\ub838\uc2b5\ub2c8\ub2e4. \ub0a8\uae40 = \ub2e8\uc77c \uc804\uc555 \uacbd\ub85c \uc218\uc785\ub2c8\ub2e4.")
    else:
        print("  " + "-" * 64)
        print("  %-30s %10s %10d %9.0fMB"
              % ("\ud569\uacc4", "?" if unknown_total else tot_before,
                 tot_after, tot_bytes / 1048576.0))
    if unknown_total:
        print("")
        print("  '\uc6d0\ub798' \uac00 ? \uc778 \uc774\uc720: \uc55e\uc5d0\uc11c N\uac1c\ub9cc \uc77d\uace0 \uba48\ucd94\uae30 \ub54c\ubb38\uc785\ub2c8\ub2e4.")
        print("  \ub9ac\ud3ec\ud2b8\uac00 -sort_by slack \uc73c\ub85c \uc815\ub82c\ub3fc \uc788\ub2e4\uace0 \ubcf4\uace0 \ub098\uba38\uc9c0\ub294 \uc548 \uc77d\uc2b5\ub2c8\ub2e4.")
        print("  \uc804\uccb4 \uac1c\uc218\uae4c\uc9c0 \uc138\uace0 \uc815\ub82c\ub3c4 \ud655\uc778\ud558\ub824\uba74 --verify \ub97c \uc8fc\uc138\uc694.")
    print("")

    if tot_after == 0:
        code("E-NOPATH",
             "[ \uc2e4\ud328 ] \ub9ac\ud3ec\ud2b8\uc5d0\uc11c \uacbd\ub85c\ub97c \ud558\ub098\ub3c4 \ubabb \uc77d\uc5c8\uc2b5\ub2c8\ub2e4.")

    shrink = (1.0 - tot_bytes / (src_mb * 1048576.0)) * 100.0
    print("-" * 68)
    print("  \uacbd\ub85c %s -> %d\uac1c,  \uc6a9\ub7c9 %.0f MB -> %.0f MB  (%.0f%% \uc904\uc5c8\uc2b5\ub2c8\ub2e4)"
          % ("?" if unknown_total else "%d\uac1c" % tot_before,
             tot_after, src_mb, tot_bytes / 1048576.0, shrink))
    print("")
    print("  \ub2e4\uc74c:")
    print("      python3 1_union.py --dir %s --mode %s" % (out, args.mode))
    print("")
    print("  \ub354 \uc904\uc774\uace0 \uc2f6\uc73c\uba74 --keep \uc744 \ub0ae\ucdb0 \ub2e4\uc2dc \ub3cc\ub9ac\uc138\uc694.")
    print("  \uc6d0\ubcf8\uc740 \uadf8\ub300\ub85c \uc788\uc73c\ub2c8 \uba87 \ubc88\uc774\ub4e0 \ub2e4\uc2dc \ub9cc\ub4e4 \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
    print("-" * 68)

    if n_uncut == len(files):
        code("W-NOCUT",
             "[ \uc8fc\uc758 ] \ubaa8\ub4e0 \ucf54\ub108\uac00 \uc774\ubbf8 %d\uac1c \uc774\ud558\ub77c \uc790\ub97c \uac83\uc774 \uc5c6\uc5c8\uc2b5\ub2c8\ub2e4."
             % args.keep)
    code("OK-TRIM",
         "[ \uc815\uc0c1 ] %d\uac1c \ucf54\ub108\ub97c \uc904\uc600\uc2b5\ub2c8\ub2e4." % len(files))


if __name__ == "__main__":
    main()
