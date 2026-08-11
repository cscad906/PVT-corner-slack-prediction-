#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0 - 코너별 리포트를 '나쁜 것 N개만' 남긴 리포트로 줄인다.  (1회차 -> 1_union)

    python3 0_trim.py --dir round1/corners --keep 10000

무엇을 왜 하나
    현업 리포트는 코너 하나에 경로가 8만 개씩 나온다. 그걸 그대로 1_union.py
    에 넣으면 메모리가 감당이 안 된다. 그래서 **합치기 전에 파일 자체를**
    코너마다 나쁜 것 N개만 남긴 리포트로 줄여 둔다.

    줄인 리포트는 진짜 report_timing 출력의 부분집합이다. 형식이 그대로라
    1_union.py 든 vi 든 원본과 똑같이 쓸 수 있고, 한 번 만들어 두면 문턱값을
    바꿔 가며 몇 번을 다시 돌려도 순식간이다.

코너별로 잘라도 합집합은 멀쩡한가
    멀쩡하다. 코너 A 에서 위반인 경로는 A 자신의 상위 N 목록에 들어가므로,
    다른 코너에서 안 잡히는 경로도 합집합에 그대로 들어온다. 빠지는 것은
    **어느 코너에서도 상위 N 에 못 든 경로**뿐이고, 그건 애초에 볼 필요가 없다.

    딱 하나 달라지는 것: 경로 P 가 코너 A 의 상위 N 에는 있고 코너 B 에서는
    한참 밀려 잘렸다면, union_paths.tsv 의 slack__B 열이 빈칸이 된다.
    경로 자체는 합집합에 들어가고 fixed_paths.tcl 도 정상이다. 어차피 2회차에
    **모든 코너에서 다시 측정**하므로, 빈칸은 1회차 참고값이 비는 것뿐이다.

메모리
    파일을 두 번 흘려 읽는다. 경로를 쌓아 두지 않는다.
      1번째 : slack 값만 읽어 '어디서 자를지' 정한다   (경로당 8바이트)
      2번째 : 그 문턱을 넘는 경로 블록만 그대로 써낸다  (한 블록씩 흘려보냄)
    그래서 리포트가 몇 GB 든 메모리는 수십 MB 를 안 넘는다.

입력
    <dir>/*.rpt      코너마다 하나. 파일 이름이 그대로 코너 이름이 된다.

출력
    <out>/*.rpt      같은 이름, 같은 형식. 경로만 N개로 줄어 있다.
                     그다음:  python3 1_union.py --dir <out>

옵션
    --dir <폴더>     원본 .rpt 가 있는 폴더                  (필수)
    --keep N         코너마다 남길 경로 수. slack 이 나쁜 것부터. (기본 10000)
    --out <폴더>     결과를 쓸 폴더. 생략하면 <dir>_top<N>
    --mode setup|hold  setup 은 slack 이 작은 것이 나쁘다. hold 도 같다.
                     (지금은 둘 다 '작은 것부터'. 표시용으로만 쓴다)
    --verify         정렬돼 있는지 끝까지 확인한다. 리포트를 -sort_by slack
                     없이 뽑았을 가능성이 있을 때만 쓴다. 기본은 확인하지 않고
                     **앞에서 N개만 읽고 멈춘다**(그래서 '원래' 개수는 ? 로 뜬다).

    --jobs N (-j N)  코너를 동시에 몇 개 처리할지. **기본 1(하나씩)**.
                     이 단계는 경로를 쌓아 두지 않아 몇 개로 나눠도 메모리가
                     거의 안 늘어난다(코너 12개 기준 34MB). 코너가 많으면
                     -j 8 정도로 올리면 그만큼 빨라진다.
    --force          결과 폴더에 이미 파일이 있어도 덮어쓴다

자주 쓰는 형태
    python3 0_trim.py  --dir round1/corners --keep 10000
    python3 1_union.py --dir round1/corners_top10000 --max-paths 2000
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

# 바이트용 같은 정규식. 이 스크립트는 리포트에서 숫자만 꺼내고 나머지는
# 그대로 복사하므로, 문자열로 디코딩했다가 다시 인코딩할 이유가 없다.
# 디코딩을 안 하면 빠르기도 하고, 이상한 문자가 섞여 있어도 원본이 그대로 나온다.
START_B_RE = re.compile(rb"^[ \t]*Startpoint:")
SLACK_B_RE = re.compile(rb"^[ \t]*slack\s*\([^)]*\)\s+(-?[\d.]+)")


# ---- 결과 코드 -------------------------------------------------------
CODE_INFO = {
    "E-NORPT":   ("리포트 파일(.rpt)을 못 찾았습니다",
                  "--dir 로 준 폴더에 코너별 report_timing 결과를 넣어 주세요."),
    "E-OUTSAME": ("결과 폴더가 원본 폴더와 같습니다",
                  "--out 으로 다른 폴더를 주세요. 원본을 덮어쓰면 되돌릴 수 없습니다."),
    "E-OUTFULL": ("결과 폴더에 이미 .rpt 가 있습니다",
                  "다른 --out 을 주거나, 덮어쓸 생각이면 --force 를 붙이세요."),
    "E-NOPATH":  ("리포트에서 경로를 하나도 못 읽었습니다",
                  "report_timing 출력이 맞는지, 파일이 비지 않았는지 확인해 주세요."),
    "W-NOCUT":   ("자를 것이 없었습니다 (원본이 이미 --keep 이하)",
                  "그대로 복사만 했습니다. 1_union.py 를 원본으로 돌려도 같습니다."),
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


# ---- 자르기 본체 -----------------------------------------------------
# 파일을 두 번 읽는다. 한 번에 끝내려면 남길 블록 N개를 메모리에 들고 있어야
# 하는데, 그러면 "메모리 때문에 줄이는 것"이 목적인 이 스크립트가 스스로
# 메모리를 먹는다. 두 번 읽는 편이 훨씬 싸다(디스크는 순차 읽기라 빠르다).

def scan_slacks(path):
    """1번째 읽기 : slack 값만 모은다. -> (slack 목록, Startpoint 개수)

    줄 단위로 돈다. 리포트의 99% 는 핀 줄이고 그 줄들은 어차피 아무것도 안
    걸리므로, 정규식을 걸기 전에 문자열 검사로 먼저 쳐낸다. `in` 은 정규식보다
    훨씬 싸다.

    (덩어리로 읽어 한 번에 훑는 방법도 해 봤는데, 덩어리를 이어 붙이는 복사와
     findall 이 만드는 목록 때문에 오히려 느리고 메모리도 7배였다. 파이썬의
     줄 단위 읽기가 이미 C 로 최적화돼 있어 이 편이 낫다.)
    """
    vals = []
    n_start = 0
    with open(path, "rb") as f:
        for line in f:
            if b"slack" in line:
                m = SLACK_B_RE.match(line)
                if m:
                    vals.append(float(m.group(1)))
                    continue
            if b"Startpoint:" in line and START_B_RE.match(line):
                n_start += 1
    return vals, n_start


def write_trimmed(src, dst, cut, n_keep):
    """2번째 읽기 : slack 이 cut 이하인 경로 블록만 그대로 써낸다.

    블록 하나를 buf 에 모았다가, slack 줄을 만나 남길 것으로 판정되면 쓴다.
    같은 slack 이 여러 개라 cut 에서 개수가 넘칠 수 있으므로 n_keep 에서 멈춘다.
    맨 앞 머리말(Report : timing ... 같은 줄)은 그대로 옮긴다.
    """
    written = 0
    buf = []
    in_block = False
    # 바이트 그대로 옮긴다. 원본 리포트를 한 글자도 안 바꾸기 위해서다
    # (디코딩했다가 다시 인코딩하면 이상한 문자가 있을 때 내용이 달라진다).
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for line in fi:
            # 정규식은 후보 줄에만 건다. 리포트의 99% 는 핀 줄이라
            # 아래 두 문자열 검사에서 바로 걸러진다.
            if b"Startpoint:" in line and START_B_RE.match(line):
                if not in_block:
                    fo.write(b"".join(buf))   # 첫 블록 앞 = 머리말
                in_block = True
                buf = [line]
                continue
            buf.append(line)
            if not in_block:
                continue                      # 아직 머리말 구간
            if b"slack" not in line:
                continue
            m = SLACK_B_RE.match(line)
            if m:
                if written < n_keep and float(m.group(1)) <= cut:
                    fo.write(b"".join(buf))
                    fo.write(b"\n\n")  # 블록 사이 빈 줄. 원본처럼 보이게 한다
                    written += 1
                buf = []
    return written


VERIFY = [False]      # --verify 여부. 하위 프로세스에도 보이게 리스트로 둔다


def trim_head(src, dst, n_keep):
    """맨 앞 N개만 쓰고 **거기서 읽기를 멈춘다.** -> (전체 개수 or None, 남긴 개수)

    report_timing 은 -sort_by slack 이 기본이라 리포트가 이미 나쁜 것부터
    정렬돼 있다. 그러면 앞에서 N개가 곧 최악 N개다.

    N개를 채우면 **파일 나머지는 아예 읽지 않는다.** 수 GB 짜리에서 앞부분만
    읽고 끝나므로 크기와 상관없이 빠르다. 대신 전체 경로가 몇 개인지는
    알 수 없어 None 으로 돌려준다(화면에 '?' 로 표시된다).

    정렬을 못 믿겠으면 --verify 를 준다. 그러면 trim_verify() 가 끝까지
    훑어 확인하고, 정렬이 아니면 두 번 읽기로 되돌아간다.
    """
    written = 0
    buf = []
    in_block = False
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for line in fi:
            if b"Startpoint:" in line and START_B_RE.match(line):
                if not in_block:
                    fo.write(b"".join(buf))   # 첫 블록 앞 = 머리말
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
            fo.write(b"".join(buf))
            fo.write(b"\n\n")
            written += 1
            buf = []
            if written >= n_keep:
                break                      # 나머지는 읽지 않는다
    return None, written


def trim_verify(src, dst, n_keep):
    """한 번만 읽고 자르되, 정렬이 맞는지 끝까지 확인한다. (--verify)

    -> (전체 개수, 남긴 개수)  또는 정렬이 아니면 None.

    report_timing 을 -sort_by slack 으로 뽑으면 리포트가 **이미 나쁜 것부터**
    정렬돼 있다. 그러면 앞에서 N개를 그대로 쓰면 끝이고, slack 을 모아 정렬할
    필요도 파일을 두 번 읽을 필요도 없다.

    다만 정렬돼 있다고 믿어 버리면 안 된다. -sort_by 를 안 준 리포트도 있고,
    path group 별로 따로 정렬돼 붙은 리포트도 있다. 그런 파일에서 앞 N개만
    집으면 뒤에 있는 더 나쁜 경로를 놓친다.

    그래서 N개를 쓴 뒤에도 **끝까지 slack 만 훑어보며** 확인한다.
      - 뒤에 더 나쁜(작은) slack 이 하나도 없다  -> 앞 N개가 정말 최악 N개다
      - 하나라도 있다                           -> None. 부르는 쪽이 두 번
                                                   읽기 방식으로 다시 한다
    뒤쪽 훑기는 블록을 모으지 않고 문자열 검사만 하므로 거의 공짜다.
    덤으로 전체 경로 개수도 정확히 세어진다.
    """
    written = 0
    n_total = 0
    worst_kept = None      # 남긴 것 중 가장 나쁘지 않은(가장 큰) slack
    buf = []
    in_block = False
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        for line in fi:
            if written < n_keep:
                if b"Startpoint:" in line and START_B_RE.match(line):
                    if not in_block:
                        fo.write(b"".join(buf))   # 첫 블록 앞 = 머리말
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
            if written < n_keep:
                if worst_kept is None or sl > worst_kept:
                    worst_kept = sl
                fo.write(b"".join(buf))
                fo.write(b"\n\n")
                written += 1
                buf = []
            elif sl < worst_kept:
                return None            # 뒤에 더 나쁜 것이 있다. 정렬 아님
    return n_total, written


def _trim_one(job):
    """코너 하나를 줄인다. -> (코너, 원래 개수, 남긴 개수, 파일 크기, 비고)"""
    src, dst, n_keep = job
    corner = os.path.splitext(os.path.basename(src))[0]

    if VERIFY[0]:
        r = trim_verify(src, dst, n_keep)
    else:
        r = trim_head(src, dst, n_keep)
    if r is not None:
        n_total, written = r
        if not written:
            return corner, 0, 0, 0, "경로 없음"
        return corner, n_total, written, os.path.getsize(dst), ""

    # 정렬돼 있지 않았다. slack 을 다 모아 문턱값을 구한 뒤 다시 쓴다.
    vals, n_start = scan_slacks(src)
    if not vals:
        return corner, n_start, 0, 0, "경로 없음"
    if len(vals) <= n_keep:
        cut = max(vals)                     # 전부 남긴다
    else:
        cut = sorted(vals)[n_keep - 1]
    written = write_trimmed(src, dst, cut, n_keep)
    return corner, len(vals), written, os.path.getsize(dst), "정렬 안 됨"


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
    """파일 순서를 지키며 처리한다. 프로세스를 못 띄우면 1개로 되돌아간다."""
    if jobs <= 1:
        for j in jobs_list:
            yield _trim_one(j)
        return
    try:
        pool = multiprocessing.Pool(processes=jobs)
    except Exception as e:
        print("  [ 알림 ] 프로세스를 못 띄워 1개로 돌립니다 (%s)" % e)
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


def main():
    ap = argparse.ArgumentParser(
        description="코너별 리포트를 나쁜 것 N개만 남긴 리포트로 줄인다.")
    ap.add_argument("--dir", required=True,
                    help="원본 .rpt 가 들어 있는 폴더")
    ap.add_argument("--keep", type=int, default=10000, metavar="N",
                    help="코너마다 남길 경로 수. slack 이 나쁜 것부터. (기본 10000)")
    ap.add_argument("--out", default=None,
                    help="결과 폴더. 생략하면 <dir>_top<N>")
    ap.add_argument("--mode", default="setup", choices=["setup", "hold"],
                    help="표시용. 어느 쪽이든 slack 이 작은 것부터 남긴다")
    ap.add_argument("--jobs", "-j", type=int, default=1, metavar="N",
                    help="코너를 동시에 몇 개 처리할지. **기본 1(하나씩)**. "
                         "0 을 주면 자동(코어 수와 코너 수 중 작은 쪽, 최대 8)")
    ap.add_argument("--verify", action="store_true",
                    help="정렬돼 있는지 끝까지 확인한다. 리포트를 -sort_by slack "
                         "없이 뽑았을 가능성이 있을 때만. 기본은 확인 안 함 "
                         "(정렬을 믿고 앞에서 N개만 읽고 멈춘다)")
    ap.add_argument("--force", action="store_true",
                    help="결과 폴더에 이미 .rpt 가 있어도 덮어쓴다")
    args = ap.parse_args()
    VERIFY[0] = args.verify

    d = args.dir.rstrip("/")
    out = args.out or ("%s_top%d" % (d, args.keep))

    print("=" * 68)
    print("0 - 리포트 줄이기  (코너마다 나쁜 것 %d개만)" % args.keep)
    print("=" * 68)

    files = sorted(glob.glob(os.path.join(d, "*.rpt")))
    if not files:
        print("")
        code("E-NORPT",
             "[ 실패 ] %s 안에 .rpt 파일이 없습니다." % d)

    if os.path.abspath(out) == os.path.abspath(d):
        print("")
        code("E-OUTSAME",
             "[ 실패 ] --out 이 원본 폴더와 같습니다: %s" % out)

    if os.path.isdir(out) and glob.glob(os.path.join(out, "*.rpt")) \
            and not args.force:
        print("")
        code("E-OUTFULL",
             "[ 실패 ] %s 에 이미 .rpt 가 있습니다." % out)

    if not os.path.isdir(out):
        os.makedirs(out)

    jobs = resolve_jobs(args.jobs, len(files))
    src_mb = sum(os.path.getsize(f) for f in files) / 1048576.0

    print("  원본   : %s   (%d코너, 합계 %.0f MB)" % (d, len(files), src_mb))
    print("  결과   : %s" % out)
    print("  남길 것: 코너마다 %d개  (slack 이 나쁜 것부터)" % args.keep)
    if jobs > 1:
        print("  동시   : %d개씩  (--jobs %d)" % (jobs, jobs))
    elif len(files) > 1:
        print("  동시   : 1개씩 (기본).  -j 8 을 주면 코너를 나눠 처리합니다")
    print("")

    jobs_list = [(f, os.path.join(out, os.path.basename(f)), args.keep)
                 for f in files]

    print("  %-30s %10s %10s %10s" % ("코너", "원래", "남김", "파일"))
    print("  " + "-" * 64)
    tot_before = tot_after = tot_bytes = 0
    n_uncut = 0
    # n_before 가 None 이면 '원래 몇 개인지 안 셌다'는 뜻이다(기본 동작).
    # 앞에서 N개만 읽고 멈추므로 전체 개수를 알 수가 없다. --verify 를 주면 센다.
    unknown_total = False
    for corner, n_before, n_after, nbytes, note in run_jobs(jobs_list, jobs):
        if n_before is None:
            unknown_total = True
        else:
            tot_before += n_before
            if n_before and n_before <= args.keep:
                n_uncut += 1
        tot_after += n_after
        tot_bytes += nbytes
        print("  %-30s %10s %10d %9.0fMB %s"
              % (corner, "?" if n_before is None else n_before,
                 n_after, nbytes / 1048576.0, note))
    print("  " + "-" * 64)
    print("  %-30s %10s %10d %9.0fMB"
          % ("합계", "?" if unknown_total else tot_before,
             tot_after, tot_bytes / 1048576.0))
    if unknown_total:
        print("")
        print("  '원래' 가 ? 인 이유: 앞에서 N개만 읽고 멈추기 때문입니다.")
        print("  리포트가 -sort_by slack 으로 정렬돼 있다고 보고 나머지는 안 읽습니다.")
        print("  전체 개수까지 세고 정렬도 확인하려면 --verify 를 주세요.")
    print("")

    if tot_after == 0:
        code("E-NOPATH",
             "[ 실패 ] 리포트에서 경로를 하나도 못 읽었습니다.")

    shrink = (1.0 - tot_bytes / (src_mb * 1048576.0)) * 100.0
    print("-" * 68)
    print("  경로 %s -> %d개,  용량 %.0f MB -> %.0f MB  (%.0f%% 줄었습니다)"
          % ("?" if unknown_total else "%d개" % tot_before,
             tot_after, src_mb, tot_bytes / 1048576.0, shrink))
    print("")
    print("  다음:")
    print("      python3 1_union.py --dir %s" % out)
    print("")
    print("  더 줄이고 싶으면 --keep 을 낮춰 다시 돌리세요.")
    print("  원본은 그대로 있으니 몇 번이든 다시 만들 수 있습니다.")
    print("-" * 68)

    if n_uncut == len(files):
        code("W-NOCUT",
             "[ 주의 ] 모든 코너가 이미 %d개 이하라 자를 것이 없었습니다."
             % args.keep)
    code("OK-TRIM",
         "[ 정상 ] %d개 코너를 줄였습니다." % len(files))


if __name__ == "__main__":
    main()
