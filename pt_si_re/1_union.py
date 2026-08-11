#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1 - 코너별 리포트를 합쳐 '측정할 경로 목록' 을 만든다.  (1회차 -> 2회차)

    python3 1_union.py --dir round1/corners --max-paths 2000

가장 많이 쓰는 옵션 두 개
    --max-paths N   합친 뒤 **가장 나쁜 slack 부터** N개만 남긴다. 개수로 바로
                    자르는 것이라 문턱값을 계산할 필요가 없다.
                    2회차가 경로당 약 0.1초/코너라 **N이 그대로 시간이 된다.**
                    (2000개면 코너당 약 3분)
                    화면에 "몇 개로 줄일까" 표가 나오니 그걸 보고 정하면 되고,
                    바꿔 가며 여러 번 돌려도 **1회차를 다시 뽑을 필요는 없다.**

    --jobs N        리포트를 **코너 단위로** N개씩 동시에 읽는다. 코너끼리는
                    서로 독립이라 몇으로 나누든 결과 파일은 완전히 같다.
                    **기본은 1(하나씩)** 이다. 올리면 그만큼 빨라지지만
                    메모리도 같이 늘어나므로, 먼저 1로 돌려 보고 여유가 있으면
                    올린다. 실측: 279MB 16코너 -> -j 1 은 6.3초, -j 16 은 0.8초.

    --max-paths 는 생략해도 되지만, 코너당 경로가 수만 개면 생략하지 말 것.
    메모리가 남길 경로 수에 비례한다.

리포트가 너무 커서 이 단계에서 메모리가 터지면
    먼저 0_trim.py 로 리포트 자체를 줄인 뒤 그걸로 합치면 된다.
        python3 0_trim.py  --dir round1/corners --keep 5000
        python3 1_union.py --dir round1/corners_top5000 --max-paths 2000
    0_trim.py 는 경로를 쌓아 두지 않아 리포트가 몇 GB 든 34MB 면 끝난다.
    코너별로 잘라도 합집합은 멀쩡하다(0_trim.py 헤더에 이유가 적혀 있다).

무엇을 왜 하나
    코너마다 위반하는 경로가 다르다. 0.8V 에서만 위반인 경로와 0.6V 에서만
    위반인 경로가 따로 있어서, 어느 한 코너 기준으로 고르면 나머지를 놓친다.
    그래서 전 코너의 위반/위험 경로를 **합집합** 한 뒤, 그 전체를 모든 코너에서
    똑같이 재측정해야 코너 간 비교가 가능하다.

입력
    <dir>/*.rpt      코너마다 하나. 파일 이름이 그대로 코너 이름이 된다.
                     (report_timing -slack_lesser_than ... 로 만든 것)

출력
    union_paths.tsv  합집합 경로 목록. 어느 코너에서 위반이었는지까지 들어 있다.
    union_summary.txt  같은 내용을 폭 맞춰 정렬한 것. vi 로 그냥 열어 보면 된다.
    fixed_paths.tcl  2회차에 pt_shell 에서 source 할 파일.
                     경로마다 report_timing 을 걸어 같은 경로를 다시 뽑는다.

옵션
  꼭 봐야 하는 것
    --dir <폴더>        코너별 .rpt 가 들어 있는 폴더. (기본 round1/corners)
    --mode setup|hold   **1회차 리포트를 뽑을 때 쓴 것과 같아야 한다.**
                        2회차 tcl 의 -delay_type 에 그대로 들어간다.
                        setup -> max, hold -> min. (기본 setup)

  경로가 너무 많을 때 줄이는 세 가지 (전부 생략 가능)
    화면에 "몇 개로 줄일까" 표가 나온다. 그걸 보고 고르면 되고, 어느 것을
    쓰든 **1회차를 다시 돌릴 필요는 없다.** 리포트는 그대로 두고 이 명령만
    다시 돌리면 된다.

    --slack-max <값>    slack 이 이 값보다 큰(=여유 있는) 경로는 뺀다.
                        예: --slack-max 0.1 -> slack 0.1ns 이하만.
    --max-paths <N>     합친 뒤 **가장 나쁜 slack 부터** N개만 남긴다.
                        문턱값을 계산할 필요 없이 개수로 바로 정할 때.
                        --slack-max 와 같이 주면 둘 다 걸린다.
    --per-corner-max <N>  **합치기 전에** 코너마다 N개로 먼저 자른다.
                        주의: 그 코너에서 밀려난 경로는 다른 코너에서
                        위험했더라도 합집합에 못 들어온다. 리포트가 너무 커서
                        읽는 것 자체가 부담일 때만 쓴다.

  속도
    --jobs N  (-j N)    리포트를 **코너 단위로** 동시에 읽을 프로세스 수.
                        코너끼리는 독립이라 나눠도 결과가 완전히 같다.
                        **기본 1(하나씩)**. 0 을 주면 자동(최대 8).
                        코너 수보다 크게 줘도 코너 수로 잘린다.
                        예: 코너 16개 279MB 를 -j 1 은 6.3초, -j 16 은 0.8초.
                        빨라지는 만큼 메모리도 늘어난다. 터진 적이 있으면
                        1 로 두고 대신 --max-paths 로 개수를 줄인다.

  나머지
    --no-edge           rise/fall 고정을 끈다. 기본은 켜짐.
                        켜져 있으면 2회차에서 -rise_from/-fall_through 로
                        엣지까지 못박아, 코너가 바뀌어도 같은 엣지로 측정된다.
    --out-tsv / --out-tcl / --out-txt   출력 파일 위치를 직접 정한다.
                        생략하면 --dir 안에 위 이름으로 만든다.

자주 쓰는 형태
    python3 1_union.py --dir round1/corners --max-paths 2000   # 보통 이것
    python3 1_union.py --dir round1/corners                    # 경로 전부
    python3 1_union.py --dir round1/corners --max-paths 2000 -j 8   # 코너 많을 때
    python3 1_union.py --dir round1/corners --mode hold        # 홀드 분석

경로를 같다고 보는 기준
    (시작 FF, 끝 FF, 그 사이를 지나는 핀 전부).
    같은 FF 쌍 사이에도 지나는 길이 다른 별개 경로가 있으므로, 핀 목록까지
    같아야 같은 경로로 친다.
"""
import argparse
import glob
import hashlib
import multiprocessing
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8, wopen
force_utf8()

START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
END_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
GROUP_RE = re.compile(r"^\s*Path Group:\s+(.+?)\s*$")
SLACK_RE = re.compile(r"^\s*slack\s*\(([^)]+)\)\s+(-?[\d.]+)")
PIN_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")
EDGE_RE = re.compile(r"\s([rf])\s*$")
STOP = ("data arrival time", "required time", "clock uncertainty",
        "library setup time", "library hold time", "slack ")


def data_pin_chain(lines, start_inst, end_inst):
    """경로의 데이터 구간 핀 목록을 [(핀, 방향)] 으로 뽑는다.

    데이터 구간이란 '시작 플립플롭에서 신호가 나온 뒤부터 끝 플립플롭에 들어갈
    때까지' 이다. 그 앞뒤는 클럭 구간이라 경로를 구분하는 데 쓰지 않는다.

    구간을 찾는 방법 (핀 이름에 의존하지 않는다)
      시작 : 인스턴스 이름이 start_inst 인 핀 중 **마지막** 것
             (FF 의 출력 핀. Q, QN, QB, Z 등 라이브러리마다 이름이 다르다)
      끝   : 인스턴스 이름이 end_inst 인 핀 중 **처음** 것
             (FF 의 입력 핀. D, DIN 등)
    예전에는 이름을 "/Q", "/QN", "/D" 로 못 박아서, 다른 라이브러리를 쓰면
    경로가 100% 버려졌다. 이름 대신 위치로 찾으면 그런 일이 없다.
    """
    # 1) 데이터 구간 후보 핀들을 순서대로 모은다
    items = []          # (핀이름, 방향)
    for line in lines:
        low = line.strip().lower()
        if any(low.startswith(p) for p in STOP):
            break
        m = PIN_RE.match(line)
        if not m:
            continue
        name, tag = m.group(1), m.group(2)
        if tag.lower() == "net":
            continue
        e = EDGE_RE.search(line.rstrip())
        items.append((name, e.group(1) if e else ""))

    if len(items) < 2:
        return []

    # 2) 시작 인스턴스의 마지막 핀 = FF 출력. 여기서부터 데이터 구간이다.
    #    (클럭 구간에도 같은 인스턴스의 클럭 핀이 나오므로 '마지막'을 쓴다)
    start_at = None
    for i, (name, _) in enumerate(items):
        if name.rsplit("/", 1)[0] == start_inst:
            start_at = i
    # 3) 끝 인스턴스의 첫 핀 = FF 입력. 여기까지가 데이터 구간이다.
    end_at = None
    for i, (name, _) in enumerate(items):
        if name.rsplit("/", 1)[0] == end_inst:
            if start_at is None or i > start_at:
                end_at = i
                break

    if start_at is None or end_at is None or end_at <= start_at:
        return []
    return items[start_at:end_at + 1]


def walk_report(path, stat):
    """리포트를 훑으며 경로를 하나씩 내놓는다. (시작FF, 끝FF, 핀들, 방향들, slack)

    **한 번에 하나씩만 내놓는다.** 예전에는 리포트 하나의 경로를 전부 리스트에
    담아 돌려줬는데, 코너당 8만 경로가 나오는 현업 리포트에서 그 리스트만으로
    수 GB 가 됐다. 부르는 쪽이 필요한 것만 골라 담을 수 있어야 한다.

    stat 은 부르는 쪽이 만들어 넘긴다(제너레이터라 return 으로는 못 준다).
    '리포트에 Startpoint 가 몇 개인데 몇 개를 실제로 썼는가' 를 센다.
    경로가 조용히 빠지면 합집합이 불완전해지므로, 버린 개수와 이유를 화면에 알린다.
      no_chain  : 시작 FF 의 Q 부터 끝 FF 의 D 까지 이어지는 핀 줄을 못 찾음
                  (포트에서 시작/끝나는 경로이거나 -input_pins 가 빠진 경우)
      no_slack  : slack 줄을 못 만남 (파일이 중간에 잘린 경우)
    """
    start = end = None
    buf = []
    with open(path, "r", errors="ignore") as f:
        for line in f:
            m = START_RE.match(line)
            if m:
                if start is not None:
                    stat["no_slack"] += 1      # 앞 경로가 slack 없이 끝났다
                stat["startpoint"] += 1
                start, end, buf = m.group(1), "", []
                continue
            if start is None:
                continue
            m = END_RE.match(line)
            if m:
                end = m.group(1)
                continue
            m = SLACK_RE.match(line)
            if m:
                slack = float(m.group(2))
                pd = data_pin_chain(buf, start, end)
                if pd:
                    yield (start, end,
                           tuple(p for p, _ in pd), tuple(d for _, d in pd),
                           slack)
                else:
                    stat["no_chain"] += 1
                start, end, buf = None, None, []
                continue
            buf.append(line)
    if start is not None:
        stat["no_slack"] += 1


def new_stat():
    return {"startpoint": 0, "no_chain": 0, "no_slack": 0, "npin": 0}


def sig_key(start, end, pins):
    """경로의 신원을 16바이트로 줄인다.

    경로를 같다고 보는 기준은 (시작 FF, 끝 FF, 지나는 핀 전부) 인데, 이걸
    그대로 dict 열쇠로 쓰면 경로 하나가 4~10 KB 다. 코너 17개 × 8만 경로면
    열쇠만으로 10 GB 가 넘어 죽는다.

    1차에서는 '어느 경로가 어느 slack 이었나' 만 알면 되고 핀 이름 자체는
    필요 없다. 그래서 16바이트로 줄여서 센다. 128비트라 서로 다른 경로가
    같은 값이 될 일은 사실상 없다(수십억 경로에서도 확률이 무시할 수준).
    """
    h = hashlib.blake2b(digest_size=16)
    h.update(start.encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(end.encode("utf-8", "replace"))
    for p in pins:
        h.update(b"\x00")
        h.update(p.encode("utf-8", "replace"))
    return h.digest()


def parse_report(path):
    """리포트 하나 -> (경로 목록, 통계). 예전 형태 그대로.

    지금 본체는 walk_report 를 쓴다. 이건 밖에서 부르던 코드와 시험용으로 남긴다.
    """
    stat = new_stat()
    out = []
    for start, end, pins, dirs, slack in walk_report(path, stat):
        out.append({"start": start, "end": end, "pins": pins, "dirs": dirs,
                    "slack": slack, "sig": (start, end, pins)})
    return out, stat


# ---- 두 번 나눠 읽기 : 메모리가 터지지 않게 --------------------------
# 예전에는 한 번에 다 읽어 들고 있었다. 코너마다 8만 경로가 나오는 현업
# 리포트에서 이게 죽는다. 이유는 두 가지였다.
#
#   1) best_slack 이 **모든 코너의 모든 고유 경로**를 핀 목록째로 붙잡았다.
#      --slack-max 로 걸러도 이건 안 줄었다. 걸러진 경로까지 세고 있었기 때문.
#   2) union 도 남길 경로가 정해지기 전에 미리 다 담았다.
#
# 그래서 두 번에 나눈다. 리포트를 두 번 읽지만, 읽는 것은 원래도 병렬이고
# 1차는 담는 게 거의 없어 빠르다. 메모리는 수십 배 줄어든다.
#
#   1차(scan)    : 경로당 16바이트 열쇠 + slack 만. 핀 이름은 버린다.
#                  -> 어디서 자를지, 몇 개가 남는지 여기서 정확히 정해진다.
#   [자를 곳 결정]  남길 경로의 열쇠만 모은다(--max-paths 2000 이면 2000개).
#   2차(collect) : 다시 읽되 **남길 열쇠에 해당하는 경로의 핀만** 담는다.
#
# 스레드가 아니라 프로세스로 나누는 이유: 여기서 하는 일은 순수 파이썬
# 정규식이라 GIL 을 놓지 않는다. 스레드로는 하나도 안 빨라진다.

def _scan_one(fp):
    """1차. -> (코너, [(열쇠, slack)...], 통계).  핀 이름은 안 넘긴다.

    핀 개수만 stat["npin"] 에 세어 둔다. 2차에서 메모리가 얼마나 필요할지
    미리 알려 주려는 것이다(핀이 많은 경로일수록 무겁다).
    """
    corner = os.path.splitext(os.path.basename(fp))[0]
    stat = new_stat()
    rows = []
    for s, e, pins, dirs, sl in walk_report(fp, stat):
        rows.append((sig_key(s, e, pins), sl))
        stat["npin"] += len(pins)
    return corner, rows, stat


# 2차 워커가 볼 값들. 태스크마다 pickle 로 실어 보내면 낭비라, 프로세스를
# 띄울 때 한 번만 넘긴다(fork 라 자식은 그냥 물려받는다).
_KEEP = None            # 남길 경로의 열쇠 집합
_SLACK_MAX = None
_PER_CORNER_MAX = None


def _init_collect(keep, slack_max, per_corner_max):
    global _KEEP, _SLACK_MAX, _PER_CORNER_MAX
    _KEEP, _SLACK_MAX, _PER_CORNER_MAX = keep, slack_max, per_corner_max


def _collect_one(fp):
    """2차. -> (코너, [(열쇠, 시작, 끝, 핀들, 방향들, slack)...])

    남길 열쇠에 해당하는 경로만 담는다. --per-corner-max 는 1차와 **같은
    기준**으로 잘라야 하므로, 코너 전체를 slack 순으로 세운 뒤 앞에서 N개를
    고르는 것까지 여기서 똑같이 한다. 이때도 핀은 남길 것만 들고 있는다.
    """
    corner = os.path.splitext(os.path.basename(fp))[0]
    stat = new_stat()
    rows = []
    for s, e, pins, dirs, sl in walk_report(fp, stat):
        k = sig_key(s, e, pins)
        keep_it = k in _KEEP
        if _PER_CORNER_MAX is None:
            # 자를 게 없으면 남길 것만 담고 나머지는 그 자리에서 버린다.
            if keep_it:
                rows.append((sl, k, (k, s, e, pins, dirs, sl)))
            continue
        # --per-corner-max 가 있으면 순위를 매겨야 해서 전부 세어는 둔다.
        # 단 핀까지 들고 있는 것은 남길 것뿐이라 무겁지 않다.
        rows.append((sl, k, (k, s, e, pins, dirs, sl) if keep_it else None))

    if _PER_CORNER_MAX is not None and len(rows) > _PER_CORNER_MAX:
        # 1차와 같은 정렬(slack 오름차순, 같으면 파일에 나온 순서)
        rows = sorted(rows, key=lambda r: r[0])[:_PER_CORNER_MAX]

    out = []
    for sl, k, rec in rows:
        if rec is None:
            continue
        if _SLACK_MAX is not None and sl > _SLACK_MAX:
            continue
        out.append(rec)
    return corner, out


def resolve_jobs(want, n_files):
    """실제로 쓸 프로세스 수를 정한다.

    코너 수보다 많이 띄워 봐야 노는 프로세스만 생긴다. 그래서 항상 코너 수로
    자른다. want 가 0 이면 자동인데, 공용 서버라 자동일 때는 8 에서 멈춘다.
    더 쓰고 싶으면 --jobs 로 직접 준다(상한 없음).
    """
    if n_files <= 1:
        return 1
    if want and want > 0:
        return min(want, n_files)
    try:
        ncpu = multiprocessing.cpu_count()
    except NotImplementedError:
        ncpu = 1
    return max(1, min(ncpu, n_files, 8))


def iter_parsed(files, jobs, work, init=None, initargs=()):
    """work(파일) 결과를 하나씩 내놓는다. **파일 순서를 지킨다.**

    순서를 지키는 이유: 화면의 코너 표와 TSV 의 slack__<코너> 열 순서가 파일
    이름 순이어야 예전 결과와 그대로 비교된다. 그래서 imap 을 쓴다(순서 보장).
    결과는 --jobs 를 뭘 주든 완전히 같다.

    프로세스를 못 띄우는 서버가 있다(/dev/shm 이 막혀 sem_open 실패 등).
    그럴 때는 조용히 1개로 되돌아간다. 멈추지 않는다.
    """
    if jobs <= 1:
        if init is not None:
            init(*initargs)                    # 1개로 돌 때도 같은 값을 쓴다
        for fp in files:
            yield work(fp)
        return

    try:
        pool = multiprocessing.Pool(processes=jobs,
                                    initializer=init, initargs=initargs)
    except Exception as e:
        print("  [ 알림 ] 프로세스를 못 띄워 1개로 돌립니다 (%s)" % e)
        print("           결과는 같습니다. 시간만 더 걸립니다.")
        if init is not None:
            init(*initargs)
        for fp in files:
            yield work(fp)
        return

    try:
        # chunksize=1 : 리포트 하나가 크고 코너마다 크기가 제각각이라,
        # 미리 뭉텅이로 나눠 주면 큰 것만 몰린 프로세스 하나를 다 같이 기다리게 된다.
        for r in pool.imap(work, files, 1):
            yield r
        pool.close()
    finally:
        pool.terminate()
        pool.join()


# ---- 결과 코드 -------------------------------------------------------
# 마지막에 "무슨 문제인지 + 어떻게 하면 되는지 + 코드" 를 함께 찍는다.
# 현장에서 화면을 복사하기 어려우므로, 읽고 바로 이해할 수 있어야 하고
# 코드는 원격으로 물어볼 때 쓴다. 코드 목록은 코드표.md 에 있다.
CODE_INFO = {
    # 코드            (한 줄 설명,                          무엇을 하면 되는지)
    "E-NORPT":    ("리포트 파일(.rpt)을 못 찾았습니다",
                   "--dir 로 준 폴더에 코너별 report_timing 결과를 넣어 주세요."),
    "E-NOFILE":   ("필요한 입력 파일이 없습니다",
                   "0_check.py 를 돌리면 무엇이 없는지 알려줍니다."),
    "E-THTIGHT":  ("--slack-max 가 너무 좁아 남은 경로가 0개입니다",
                   "위 '몇 개로 줄일까' 표를 보고 문턱값을 키워 주세요. "
                   "리포트를 다시 뽑을 필요는 없습니다."),
    "E-NOPATH":   ("리포트에서 경로를 하나도 못 읽었습니다",
                   "report_timing 에 -input_pins 를 넣어 다시 뽑아 주세요."),
    "E-NONET":    ("리포트에 '(net)' 줄이 없습니다",
                   "report_timing 에 -nets 를 넣어 다시 뽑아 주세요."),
    "E-NOATTR":   ("속성 덤프에서 값을 하나도 못 읽었습니다",
                   "report_attribute 에 -application 을 넣어 다시 뽑아 주세요."),
    "E-PINNAME":  ("리포트의 핀 이름이 속성 덤프와 하나도 안 맞습니다",
                   "지금 쓰는 리포트로 dump_attr.tcl 을 다시 돌려 주세요."),
    "E-RES0":     ("SPEF 에서 저항(Res)을 하나도 못 구했습니다",
                   "SPEF 가 이 리포트와 같은 디자인/코너인지 확인해 주세요."),
    "E-NOINPUT":  ("붙일 값(cpin/distres)이 하나도 없습니다",
                   "2a_cpin.py 와 2b_distres.py 를 먼저 돌려 주세요."),
    "E-NOROW":    ("결과 표에 줄이 하나도 없습니다",
                   "timing.rpt 이 report_timing 출력이 맞는지 확인해 주세요."),
    "W-DROP":     ("합집합에서 버린 경로가 많습니다",
                   "report_timing 옵션 4개(-nets -input_pins -nosplit "
                   "-path_type full_clock_expanded)를 확인해 주세요."),
    "W-CPIN":     ("Cpin 이 비어 있는 줄이 많습니다",
                   "지금 리포트로 dump_attr.tcl 을 다시 돌려 보세요."),
    "W-RES":      ("Dist/Res 가 비어 있는 줄이 많습니다",
                   "9_diagnose.py 를 돌리면 원인을 A/B/C 로 나눠 줍니다."),
    "W-NA":       ("결과에 N/A 가 남아 있습니다",
                   "9_diagnose.py 를 돌리면 원인을 알려줍니다."),
}


def code(c, *msg):
    """무슨 일이 있었는지 설명하고 코드를 찍는다.

    E- 로 시작하면 실패라 여기서 멈춘다. W- 는 결과는 나왔지만 확인이 필요한 경우.
    """
    for m in msg:
        print(m)
    print("")
    print("=" * 66)
    if c.startswith("OK-"):
        print("  정상 종료           [ %s ]" % c)
        print("=" * 66)
        return
    what, todo = CODE_INFO.get(c, ("", ""))
    kind = "문제 발생" if c.startswith("E-") else "확인 필요"
    print("  %s" % kind)
    if what:
        print("    무엇이   : %s" % what)
        print("    하실 일  : %s" % todo)
    print("")
    print("    에러 코드: %s" % c)
    print("    (해결이 안 되면 이 코드를 알려주세요)")
    print("=" * 66)
    # 코드는 항상 마지막에 한 번만 나와야 한다. 경고(W-)에서 멈추지 않으면
    # 뒤이어 정상(OK-)까지 찍혀 어느 쪽인지 헷갈린다.
    sys.exit(1 if c.startswith("E-") else 0)


def main():
    ap = argparse.ArgumentParser(description="코너별 리포트를 합쳐 경로 목록을 만든다.")
    ap.add_argument("--dir", default="round1/corners",
                    help="코너별 .rpt 가 들어 있는 폴더")
    ap.add_argument("--out-tsv", default=None)
    ap.add_argument("--out-tcl", default=None)
    ap.add_argument("--out-txt", default=None,
                    help="vi 로 보기 좋게 정렬한 요약 파일")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="setup(-delay_type max) / hold(min). **1회차 리포트를 "
                         "뽑을 때 쓴 것과 같아야 한다.** 2회차 tcl 에 그대로 들어간다")
    ap.add_argument("--per-corner-max", type=int, default=None,
                    help="**합치기 전에** 코너마다 이 개수만 남긴다. 리포트가 "
                         "너무 커서 코너별로 먼저 줄여야 할 때. 각 코너의 "
                         "worst slack 부터 남는다")
    ap.add_argument("--max-paths", type=int, default=None,
                    help="합집합 결과를 이 개수만 남긴다. **가장 나쁜 slack 부터** "
                         "고른다. 문턱값을 계산할 필요 없이 개수로 바로 정할 때. "
                         "--slack-max 와 같이 주면 둘 다 적용된다")
    ap.add_argument("--slack-max", type=float, default=None,
                    help="이 값보다 slack 이 큰 경로는 제외. 생략하면 리포트에 있는 것 전부.")
    ap.add_argument("--no-edge", action="store_true",
                    help="rise/fall 고정을 끈다. 기본은 켜짐(코너마다 엣지가 뒤바뀌는 것을 막는다).")
    ap.add_argument("--jobs", "-j", type=int, default=1, metavar="N",
                    help="리포트를 **코너 단위로** 동시에 읽을 프로세스 수. "
                         "**기본 1(하나씩)**. 0 을 주면 자동(코어 수와 코너 수 "
                         "중 작은 쪽, 최대 8). 올리면 빨라지지만 메모리도 그만큼 "
                         "늘어난다. 코너 수보다 크게 줘도 코너 수로 잘린다. "
                         "결과는 몇을 주든 완전히 같다")
    args = ap.parse_args()

    d = args.dir
    out_tsv = args.out_tsv or os.path.join(d, "union_paths.tsv")
    out_tcl = args.out_tcl or os.path.join(d, "fixed_paths.tcl")
    out_txt = args.out_txt or os.path.join(d, "union_summary.txt")

    print("=" * 68)
    print("1 - 코너 합집합")
    print("=" * 68)

    files = sorted(glob.glob(os.path.join(d, "*.rpt")))
    if not files:
        print("")
        code("E-NORPT",
             "[ 실패 ] %s 안에 .rpt 파일이 없습니다." % d,
             "         코너마다 report_timing 결과를 이 폴더에 모아 주세요.",
             "         파일 이름이 그대로 코너 이름이 됩니다.")

    jobs = resolve_jobs(args.jobs, len(files))
    total_mb = sum(os.path.getsize(f) for f in files) / (1024.0 * 1024.0)

    print("  폴더 : %s" % d)
    print("  코너 : %d개  (리포트 합계 %.0f MB)" % (len(files), total_mb))
    print("  분석 : %s  (2회차는 -delay_type %s 로 측정)"
          % (args.mode, "min" if args.mode == "hold" else "max"))
    if jobs > 1:
        print("  동시 : %d개씩 읽음  (--jobs %d)" % (jobs, jobs))
    elif len(files) > 1:
        print("  동시 : 1개씩 읽음.  --jobs %d 을 주면 코너를 나눠 읽습니다"
              % min(len(files), 8))

    # 자르기 설정은 **시작할 때** 보여 준다. 예전에는 다 끝난 뒤에야 몇 개
    # 남겼는지 나와서, 옵션을 빠뜨린 채 전부 돌려 놓고 한참 뒤에 알게 됐다.
    cuts = []
    if args.max_paths is not None:
        cuts.append("--max-paths %d  (가장 나쁜 slack 부터 %d개)"
                    % (args.max_paths, args.max_paths))
    if args.slack_max is not None:
        cuts.append("--slack-max %g  (slack 이 %g 이하인 것만)"
                    % (args.slack_max, args.slack_max))
    if args.per_corner_max is not None:
        cuts.append("--per-corner-max %d  (합치기 **전에** 코너마다 %d개)"
                    % (args.per_corner_max, args.per_corner_max))
    if cuts:
        print("  자르기 : %s" % cuts[0])
        for c in cuts[1:]:
            print("           %s" % c)
        if args.max_paths is not None:
            print("           -> 2회차 예상 %d분/코너 (경로당 0.1초)"
                  % max(1, int(args.max_paths * 0.1 / 60)))
    else:
        print("  자르기 : 없음 (리포트에 있는 경로 전부)")
        print("           많으면 --max-paths 2000 처럼 개수로 자릅니다."
              " 아래 표 참고")
    print("")

    # ---- 1차 : 무엇이 있는지만 가볍게 센다 --------------------------
    # 경로당 16바이트 열쇠 + slack 만 본다. 핀 이름은 여기서 그냥 버린다.
    # 어디서 자를지 정하는 데는 slack 만 있으면 되기 때문이다.
    per_corner_cut = {}
    best_slack = {}   # 열쇠 -> 여러 코너 중 가장 나쁜(작은) slack
    corner_names = []
    total_drop = {"no_chain": 0, "no_slack": 0}
    n_pin_seen = 0
    n_path_seen = 0
    print("  %-34s %8s %8s %8s" % ("코너", "리포트", "사용", "제외"))
    print("  " + "-" * 62)
    for corner, scan, stat in iter_parsed(files, jobs, _scan_one):
        corner_names.append(corner)
        total_drop["no_chain"] += stat["no_chain"]
        total_drop["no_slack"] += stat["no_slack"]
        n_pin_seen += stat["npin"]
        n_path_seen += len(scan)

        # --per-corner-max : 합치기 **전에** 코너별로 자른다.
        # 코너마다 자기 기준으로 자르므로, 그 코너 목록에서 밀려난 경로는
        # 다른 코너에서 위험했더라도 합집합에 못 들어온다. 그래서 기본은 끄고,
        # 리포트가 너무 커서 어쩔 수 없을 때만 쓴다.
        n_corner_before = len(scan)
        if args.per_corner_max is not None and n_corner_before > args.per_corner_max:
            scan = sorted(scan, key=lambda r: r[1])[:args.per_corner_max]
            per_corner_cut[corner] = (n_corner_before, len(scan))
        kept = 0
        for k, sl in scan:
            b = best_slack.get(k)
            if b is None or sl < b:
                best_slack[k] = sl
            if args.slack_max is None or sl <= args.slack_max:
                kept += 1
        dropped = stat["no_chain"] + stat["no_slack"]
        mark = ""
        if corner in per_corner_cut:
            mark = "   <- %d개에서 자름" % per_corner_cut[corner][0]
        print("  %-34s %8d %8d %8d%s"
              % (corner, stat["startpoint"], kept, dropped, mark))

    if total_drop["no_chain"] or total_drop["no_slack"]:
        print("")
        print("  [ 제외된 경로 설명 ]")
        if total_drop["no_chain"]:
            print("    핀 연결을 못 찾음 : %d개" % total_drop["no_chain"])
            print("      시작 FF 의 Q 부터 끝 FF 의 D 까지 이어지는 핀 줄이 없는 경로입니다.")
            print("      - 포트에서 시작하거나 끝나는 경로면 정상입니다(FF 사이가 아님).")
            print("      - 전부 제외됐다면 report_timing 에 -input_pins 가 빠진 것입니다.")
        if total_drop["no_slack"]:
            print("    slack 줄이 없음   : %d개" % total_drop["no_slack"])
            print("      경로 블록 끝의 'slack (...)' 줄을 못 만난 경우입니다.")
            print("      - 1~2개면 파일 맨 끝이 잘린 것입니다. 무시해도 됩니다.")
            print("      - 여러 개면 report_timing 에 -nosplit 이 빠져 줄이 접혔을")
            print("        가능성이 큽니다. 아래로 다시 뽑으세요:")
            print("          report_timing ... -nets -input_pins -nosplit ...")

    # ---- 몇 개로 줄이려면 문턱값을 얼마로 줘야 하는지 -------------
    # 현장에서 코너당 수만 경로가 나오면 2회차가 감당이 안 된다. 어디서
    # 자를지 정하는 데 쓰라고, PT 를 다시 돌리지 않고 이 표만 보고 고르면 된다.
    # 2회차는 경로마다 report_timing 한 번 -- 실측 약 0.1초/경로/코너.
    if best_slack:
        vals = sorted(best_slack.values())
        print("")
        print("  [ 몇 개로 줄일까 ]  --slack-max <문턱값> 으로 다시 돌리면 그만큼이 된다")
        print("  %10s %12s %14s" % ("경로 수", "문턱값", "2회차 시간/코너"))
        print("  " + "-" * 40)
        shown = set()
        for want in (200, 500, 1000, 2000, 3000, 5000, 10000, 20000, len(vals)):
            if want > len(vals) or want in shown:
                continue
            shown.add(want)
            th = vals[want - 1]
            sec = want * 0.1
            est = ("%d초" % int(sec)) if sec < 90 else ("%d분" % int(sec / 60))
            tag = "  (전체)" if want == len(vals) else ""
            print("  %10d %12.4f %14s%s" % (want, th, est, tag))
        print("  " + "-" * 40)

    # ---- 남길 경로를 **여기서** 정한다 ------------------------------
    # 예전에는 다 담아 놓고 마지막에 잘랐다. 담는 도중에 메모리가 터졌다.
    # 이제는 1차 결과(열쇠+slack)만 보고 자를 곳을 먼저 정하고, 2차에서
    # 남길 것만 담는다. 그래서 메모리가 '리포트 전체'가 아니라 '남길 개수'에
    # 비례한다.
    keep_keys = [k for k, v in best_slack.items()
                 if args.slack_max is None or v <= args.slack_max]
    n_after_slack = len(keep_keys)

    # --max-paths 는 문턱값으로 바꿔서 건다. 같은 slack 이 여러 개면 조금
    # 넉넉히 남는데, 최종 개수 자르기는 아래 원래 자리에서 그대로 하므로
    # 결과는 정확히 같다.
    if args.max_paths is not None and n_after_slack > args.max_paths:
        cut = sorted(best_slack[k] for k in keep_keys)[args.max_paths - 1]
        keep_keys = [k for k in keep_keys if best_slack[k] <= cut]
    keep = set(keep_keys)
    del keep_keys

    if best_slack:
        if args.slack_max is not None:
            print("  지금 --slack-max %.4f 로 %d개를 골랐습니다."
                  % (args.slack_max, n_after_slack))
        else:
            print("  지금은 문턱값 없이 전부(%d개) 씁니다." % len(vals))
        print("  ** 문턱값을 좁혀도 1회차를 다시 돌릴 필요는 없습니다. **")
        print("     리포트는 그대로 두고 이 명령만 다시 돌리면 됩니다.")

    if not keep:
        print("")
        # 문턱값 때문에 0개가 된 것과, 리포트를 아예 못 읽은 것은 원인이 다르다.
        if best_slack and args.slack_max is not None:
            code("E-THTIGHT",
                 "[ 실패 ] --slack-max %.4f 로 걸러서 남은 경로가 0개입니다."
                 % args.slack_max,
                 "         리포트에는 경로가 %d개 있고, 그중 가장 나쁜 slack 은 "
                 "%.4f 입니다." % (len(best_slack), min(best_slack.values())),
                 "         --slack-max 를 그보다 크게 주세요. 위 표를 참고하세요.")
        code("E-NOPATH",
             "[ 실패 ] 쓸 수 있는 경로가 하나도 없습니다.",
             "         report_timing 에 -input_pins 가 빠졌을 가능성이 큽니다.")

    # ---- 2차 : 남길 경로의 핀만 담는다 -----------------------------
    # 메모리가 얼마나 필요한지 먼저 알려 준다. 핀 하나가 대략 110 바이트다.
    avg_pin = (n_pin_seen / float(n_path_seen)) if n_path_seen else 0.0
    need_mb = len(keep) * avg_pin * 110 / 1048576.0
    print("")
    print("  2차 : 남길 %d경로의 핀만 다시 읽습니다 (예상 메모리 %.0f MB)"
          % (len(keep), need_mb))
    if need_mb > 4000:
        print("")
        print("  [ 주의 ] 예상 메모리가 %.1f GB 입니다." % (need_mb / 1024.0))
        print("           경로가 %d개로 너무 많습니다. 위 표를 보고"
              % len(keep))
        print("           --max-paths 2000 처럼 개수를 줄여서 다시 돌리세요.")
        print("           (2회차 측정 시간도 경로 수에 그대로 비례합니다)")

    union = {}
    for corner, recs in iter_parsed(files, jobs, _collect_one, _init_collect,
                                    (keep, args.slack_max, args.per_corner_max)):
        for k, p_start, p_end, p_pins, p_dirs, sl in recs:
            u = union.setdefault(k, {
                "start": p_start, "end": p_end,
                "n_through": len(p_pins) - 2,
                "pins": p_pins, "dirs": p_dirs,
                "slacks": {},
            })
            prev = u["slacks"].get(corner)
            if prev is None or sl < prev:
                u["slacks"][corner] = sl
                # 가장 나쁜 코너의 방향을 쓴다(2회차에 그 엣지로 고정)
                if sl == min(u["slacks"].values()):
                    u["dirs"] = p_dirs

    # 버려진 비율이 크면 형식 문제일 가능성이 높다. 눈에 띄게 알린다.
    dropped_all = total_drop["no_chain"] + total_drop["no_slack"]
    if union and dropped_all > 0:
        used = len(union)
        if dropped_all > used * 0.1:
            print("")
            print("  [ 주의 ] 버린 경로가 %d개로 적지 않습니다 (쓴 것 %d개)."
                  % (dropped_all, used))
            print("           리포트 형식 문제일 수 있습니다. 아래 옵션을 모두 넣었는지")
            print("           확인하세요:")
            print("             -nets -input_pins -nosplit -path_type full_clock_expanded")

    if not union:
        print("")
        code("E-NOPATH",
             "[ 실패 ] 쓸 수 있는 경로가 하나도 없습니다.",
             "         report_timing 에 -input_pins 가 빠졌을 가능성이 큽니다.")

    rows = []
    for sig, e in union.items():
        s = e["slacks"]
        worst_c = min(s, key=lambda c: s[c])
        rows.append({
            "start": e["start"], "end": e["end"], "n_through": e["n_through"],
            "pins": e["pins"], "dirs": e["dirs"],
            "n_viol": sum(1 for v in s.values() if v < 0),
            "n_corner": len(s),
            "worst": s[worst_c], "worst_c": worst_c, "slacks": s,
        })
    rows.sort(key=lambda r: (r["worst"], r["start"], r["end"]))

    # ---- 개수로 자르기 --------------------------------------------
    # 위에서 이미 '가장 나쁜 slack' 순으로 정렬돼 있으므로 앞에서부터 자르면
    # 위험한 것부터 남는다. 문턱값(--slack-max)을 계산해 줄 필요가 없다.
    n_before_cut = len(rows)
    cut_at = None
    if args.max_paths is not None and len(rows) > args.max_paths:
        cut_at = rows[args.max_paths - 1]["worst"]
        rows = rows[:args.max_paths]

    for i, r in enumerate(rows, 1):
        r["idx"] = i

    # ---- union_paths.tsv -------------------------------------------
    with wopen(out_tsv) as fh:
        head = ["path_idx", "startpoint", "endpoint", "n_through",
                "n_corners_seen", "n_corners_violating", "worst_slack", "worst_corner"]
        head += ["slack__" + c for c in corner_names]
        fh.write("\t".join(head) + "\n")
        for r in rows:
            vals = [str(r["idx"]), r["start"], r["end"], str(r["n_through"]),
                    str(r["n_corner"]), str(r["n_viol"]),
                    "%.6f" % r["worst"], r["worst_c"]]
            vals += ["" if c not in r["slacks"] else "%.6f" % r["slacks"][c]
                     for c in corner_names]
            fh.write("\t".join(vals) + "\n")

    # ---- union_summary.txt : vi 로 그냥 열어 보는 용도 --------------
    # TSV 는 탭이라 vi 에서 열이 어긋난다. 폭을 맞춰 미리 정렬해 둔다.
    def short(name, w=34):
        """긴 인스턴스 이름을 앞뒤만 남기고 줄인다."""
        if len(name) <= w:
            return name
        keep = (w - 2) // 2
        return name[:keep] + ".." + name[-(w - 2 - keep):]

    n_viol_any = sum(1 for r in rows if r["n_viol"] > 0)
    with wopen(out_txt) as fh:
        fh.write("합집합 경로 요약  (위험한 것부터 정렬)\n")
        fh.write("=" * 118 + "\n")
        fh.write("코너 %d개 : %s\n" % (len(corner_names), ", ".join(corner_names)))
        fh.write("경로 %d개 (그중 위반 이력 있는 것 %d개)\n" % (len(rows), n_viol_any))
        fh.write("\n")
        fh.write("  코너수 = 몇 개 코너의 목록에 있었나 (1 이면 그 코너에서만 나온 경로)\n")
        fh.write("  위반   = slack 이 음수였던 코너 수\n")
        fh.write("  코너별 slack 에서 '.' 은 그 코너 목록에 없었다는 뜻\n")
        fh.write("=" * 118 + "\n")
        head = "%6s %6s %6s %5s %11s  " % ("idx", "핀수", "코너수", "위반", "worst")
        head += " ".join("%9s" % c[:9] for c in corner_names)
        head += "   %s" % "경로 (시작 -> 끝)"
        fh.write(head + "\n")
        fh.write("-" * 118 + "\n")
        for r in rows:
            line = "%6d %6d %6d %5d %11.6f  " % (
                r["idx"], r["n_through"], r["n_corner"], r["n_viol"], r["worst"])
            line += " ".join(
                ("%9.4f" % r["slacks"][c]) if c in r["slacks"] else "%9s" % "."
                for c in corner_names)
            line += "   %s -> %s" % (short(r["start"]), short(r["end"]))
            fh.write(line + "\n")

    # ---- fixed_paths.tcl -------------------------------------------
    # 경로마다 report_timing 을 -from/-through/-to 로 걸어 같은 경로를 다시 뽑는다.
    # through 는 데이터 구간 핀 전부를 쓴다(일부만 쓰면 비슷한 다른 경로가 잡힌다).
    edge = not args.no_edge
    with wopen(out_tcl) as fh:
        fh.write("# 2회차용. pt_shell 에서:  source fixed_paths.tcl\n")
        fh.write("# 코너를 바꿔 로드할 때마다 한 번씩 실행한다.\n")
        fh.write("#   결과는 <코너이름>.rpt 로 저장된다. 코너마다 CORNER 만 바꾼다.\n\n")
        fh.write("### 결과 파일 이름 #############################################\n")
        fh.write("set CORNER [file tail [pwd]]\n")
        fh.write("###############################################################\n")
        fh.write("# 지금 있는 폴더 이름을 코너 이름으로 쓴다.\n")
        fh.write("#   cd .../round2/tt0p6v25c_Cnom  ->  tt0p6v25c_Cnom.rpt\n")
        fh.write("# 폴더와 상관없이 정하고 싶으면 위 줄을 이렇게 바꾼다.\n")
        fh.write('#   set CORNER "내가정한이름"\n')
        fh.write("# 조건 없이 set 한다(일부러). if {![info exists CORNER]} 로 두면\n")
        fh.write("# 두 번째 코너부터 앞 코너 이름이 그대로 남아 덮어써 버린다.\n\n")
        fh.write('puts "  this corner : $CORNER   ->  $CORNER.rpt"\n')
        fh.write('puts "  (if that name does not match the db you just loaded, stop now)"\n\n')
        fh.write('set OUT "$CORNER.rpt"\n')
        fh.write('set DTYPE "%s"      ;# setup=max, hold=min\n'
                 % ("min" if args.mode == "hold" else "max"))
        fh.write('set SIGDIG 6\n\n')
        fh.write("file delete -force $OUT\n")
        fh.write("set FIXED_PATHS {\n")
        for r in rows:
            frm, to = r["pins"][0], r["pins"][-1]
            thr = r["pins"][1:-1]
            key = "%s->%s#%d" % (r["start"], r["end"], r["idx"])
            thr_s = " ".join("{%s}" % p for p in thr)
            if edge and all(d in ("r", "f") for d in r["dirs"]) and len(r["dirs"]) == len(r["pins"]):
                dir_s = " ".join("{%s}" % d for d in r["dirs"])
                fh.write("  {{%s} {%s} {%s} {%s} {%s}}\n" % (key, frm, to, thr_s, dir_s))
            else:
                fh.write("  {{%s} {%s} {%s} {%s}}\n" % (key, frm, to, thr_s))
        fh.write("}\n\n")
        fh.write(TCL_LOOP)

    n_edge = sum(1 for r in rows
                 if all(d in ("r", "f") for d in r["dirs"]) and len(r["dirs"]) == len(r["pins"]))
    print("")
    print("-" * 68)
    if per_corner_cut:
        print("  --per-corner-max %d 로 **합치기 전에** 코너별로 잘랐습니다."
              % args.per_corner_max)
        print("    잘린 코너 %d개. 그 코너에서 밀려난 경로는 다른 코너에서"
              % len(per_corner_cut))
        print("    위험했더라도 합집합에 들어오지 않습니다.")
        print("")
    if cut_at is not None:
        print("  --max-paths %d 로 %d개 중 %d개만 남겼습니다."
              % (args.max_paths, n_before_cut, len(rows)))
        print("    (가장 나쁜 slack 부터. 자른 지점의 slack = %.4f)" % cut_at)
        print("")
    print("  합집합 경로 : %d개" % len(rows))
    print("  결과 목록   : %s   (vi 로 열어 보세요)" % out_txt)
    print("  같은 내용 TSV: %s" % out_tsv)
    print("  2회차 tcl   : %s" % out_tcl)
    if edge:
        print("  rise/fall 고정 : %d / %d 경로" % (n_edge, len(rows)))
    print("-" * 68)
    only1 = sum(1 for r in rows if r["n_corner"] == 1)
    allc = sum(1 for r in rows if r["n_corner"] == len(corner_names))
    print("  한 코너에서만 나온 경로 : %d  (합집합이 필요한 이유)" % only1)
    print("  모든 코너에 나온 경로   : %d" % allc)
    print("")
    warn = (total_drop["no_chain"] + total_drop["no_slack"]) > len(rows) * 0.1
    code("W-DROP" if warn else "OK-UNION",
         "[ %s ] 합집합 %d경로. 2회차: 코너마다 pt_shell 에서"
         % ("주의" if warn else "정상", len(rows)))
    print("           set CORNER \"<코너이름>\"      (결과는 <코너이름>.rpt 로 저장)")
    print("           source %s" % out_tcl)
    print("           source dev/dump_attr.tcl")
    print("")


TCL_LOOP = r"""
# --- 시작 전 확인 : 디자인이 올라와 있나 -------------------------------
# 이게 없으면 294개 report_timing 이 전부 "Current design is not defined" 로
# 실패하는데도 파일은 만들어져서, 다 된 줄 알고 넘어가게 된다.
if {[sizeof_collection [get_designs -quiet *]] == 0} {
    puts ""
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : no design is loaded in PrimeTime."
    puts "             the netlist / library must be read first."
    puts "    action : read_verilog + link_design + read_sdc + read_parasitics"
    puts "             for the example :  source example/00_setup.tcl"
    puts ""
    puts "    code   : E-NODESIGN"
    puts "=================================================================="
    return
}

# --- 위 목록의 경로를 하나씩 다시 뽑는다 (내용은 안 봐도 된다) ---------
proc edge_opt {base dir} {
    if {$dir eq "r"} { return "-rise_$base" }
    if {$dir eq "f"} { return "-fall_$base" }
    return "-$base"
}

set idx 0
foreach item $FIXED_PATHS {
    incr idx
    set key  [lindex $item 0]
    set frm  [lindex $item 1]
    set to   [lindex $item 2]
    set thr  [lindex $item 3]
    set dirs [lindex $item 4]
    set use_edge [expr {[llength $dirs] == [llength $thr] + 2}]

    set fopt "-from"
    set topt "-to"
    if {$use_edge} {
        set fopt [edge_opt "from" [lindex $dirs 0]]
        set topt [edge_opt "to"   [lindex $dirs end]]
    }

    set cmd "report_timing -delay_type $DTYPE -path_type full_clock_expanded \
        $fopt \[get_pins -quiet {$frm}\] $topt \[get_pins -quiet {$to}\] \
        -max_paths 1 -sort_by slack \
        -nets -input_pins -capacitance -transition_time \
        -nosplit -significant_digits $SIGDIG"

    set i 0
    foreach tp $thr {
        set topt2 "-through"
        if {$use_edge} { set topt2 [edge_opt "through" [lindex $dirs [expr {$i+1}]]] }
        append cmd " $topt2 \[get_pins -quiet {$tp}\]"
        incr i
    }

    redirect -append $OUT {
        puts "### FIXED_PATH idx=$idx key=$key"
        eval $cmd
        puts ""
    }
}

# --- 끝나고 확인 : 요청한 만큼 실제로 측정됐나 -------------------------
# 리포트 안의 "Startpoint:" 개수를 센다. 요청 수보다 적으면 그만큼 실패한 것.
proc count_measured {f} {
    set n 0
    set fh [open $f r]
    while {[gets $fh line] >= 0} {
        if {[string first "Startpoint:" $line] >= 0} { incr n }
    }
    close $fh
    return $n
}

set NGOT [count_measured $OUT]
puts ""
puts "  paths requested : $idx"
puts "  paths measured  : $NGOT"
puts "  output file     : $OUT"
if {$NGOT == 0} {
    puts ""
    puts "=================================================================="
    puts "  PROBLEM"
    puts "    what   : not one path was captured.  the report holds only errors."
    puts "    action : open $OUT and read the first few Error lines."
    puts "             'Current design is not defined' means no design is loaded."
    puts "             an error about 'get_pins' means this corner's netlist is"
    puts "             not the one used in round 1."
    puts ""
    puts "    code   : E-NOMEASURED"
    puts "=================================================================="
} elseif {$NGOT < $idx} {
    puts "  WARNING: [expr {$idx - $NGOT}] paths were not captured."
    puts "           a small drop is normal -- a path can disappear in another"
    puts "           corner.  if the drop is large, check the Error lines in $OUT."
}
"""


if __name__ == "__main__":
    main()
