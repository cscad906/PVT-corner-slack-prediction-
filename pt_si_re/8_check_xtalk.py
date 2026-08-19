#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""8 - 현장에서 받은 crosstalk 결과가 코너마다 제대로 나왔는지 검사한다.

    python3 8_check_xtalk.py --root /받은곳

setup / hold 를 **자동으로 판별**한다(PT 원문의 Annotated max/min). 검사가
끝나면 다음에 칠 명령을 찍어 주는데, hold 면 5b 에 --mode hold 를 붙여서
보여 준다. 그대로 복사해 쓰면 mode 를 빼먹을 일이 없다.

담당자분이 "잘 나왔다" 고 하셔도 **화면에는 정상으로 뜨는데 값이 틀린** 경우가
있다. 제일 흔한 것이 코너를 바꿔 놓고 db 를 안 갈아 끼운 경우로, 전 코너가
같은 전압으로 계산된다. 그건 파일을 열어 봐야 안다.

받은 폴더 아래에서 **이름이 `xtalk` 인 폴더를 전부** 찾는다. 현장 구조를 몰라도
되고 setup/hold 를 따로 줄 필요도 없다. 한 번에 다 검사한다.

    /받은곳/
        TT_0p6V_25C_op_cond_all/xtalk/          <- setup
        TT_0p8V_25C_op_cond_all/xtalk/
        TT_0p6V_25C_op_cond_all_hold/xtalk/     <- hold (_hold 가 붙는다)

폴더 이름은 xtalk_all.tcl 이 로드된 db 이름으로 짓고, hold 는 뒤에 `_hold` 를
붙인다. 다만 **이름을 믿지 않고** PT 원문에 찍힌 값으로 판정한다 -- 폴더 이름은
사람이 바꿀 수 있지만 원문은 PT 가 쓴 것이라 바뀌지 않는다.
코너 폴더 이름(= xtalk 의 부모)이 표의 '코너' 열로 나온다.

코너마다 아래를 본다.

  파일 4개가 다 있고 비어 있지 않은가
  context 를 몇 개 물었고 몇 개가 실패했는가
  **어느 전압으로 계산됐는가**            <- PT 원문에 찍힌 VDD
  **setup 인가 hold 인가**                <- 원문의 'Annotated max/min'
  crosstalk 이 실제로 잡혔는가 (delta 가 0 이 아닌 넷 수)
  setup 은 delta 가 양수, hold 는 음수로 나온다 -- 부호가 아니라 0 여부를 본다
  victim/aggressor 도착시각이 채워졌는가

그리고 코너끼리 비교한다. **setup 과 hold 는 각각 따로 묶어서** 본다 --
둘은 원래 별개 2세트라 섞여 있는 것 자체는 문제가 아니다.

  같은 분석 안에서 전압이 코너마다 다른가
      같으면 db 를 안 갈아 끼운 것. 제일 잡기 어려운 실수다.
      (setup 0.6V 와 hold 0.6V 가 같은 건 당연하므로 넘어간다)
  같은 분석 안에서 넷 목록이 같은가
      다르면 서로 다른 fixed_paths.tcl 로 돌린 것.
      (setup 과 hold 는 클럭 구간이 달라 원래 다르므로 비교하지 않는다)

읽기만 한다. 아무것도 고치거나 만들지 않는다.
"""
import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_engine"))
from utf8 import force_utf8
force_utf8()

NEED = ("unique_contexts.tsv", "context_raw.rpt",
        "victim_windows.tsv", "aggressor_windows.tsv")

VDD_RE = re.compile(r"rail voltage\(VDD\):\s+([0-9.]+)")
DELTA_RE = re.compile(r"Annotated (max|min) rise net delta delay:\s+(\S+)")
NAGG_RE = re.compile(r"Number of aggressors:\s+(\d+)")

CODE_INFO = {
    "E-NOXTALK":  ("xtalk 폴더를 하나도 못 찾았습니다",
                   "받은 폴더를 통째로 --root 로 주세요. 그 아래 어디든 "
                   "xtalk 폴더가 있으면 찾습니다."),
    "E-CORNER":   ("코너 사이에 문제가 있습니다",
                   "위 표의 [문제] 줄을 보세요. 대개 db 를 안 갈아 끼운 "
                   "경우입니다."),
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


def find_xtalk_dirs(root):
    out = []
    for dirpath, dirnames, _ in os.walk(root):
        if os.path.basename(dirpath) == "xtalk":
            out.append(dirpath)
            dirnames[:] = []          # 그 아래로는 더 안 내려간다
    return sorted(out)


def count_rows(path):
    """헤더를 뺀 줄 수. 없으면 -1."""
    if not os.path.isfile(path):
        return -1
    n = 0
    with io.open(path, "r", errors="ignore") as f:
        for _ in f:
            n += 1
    return max(0, n - 1)


def count_field(path, col, want):
    """마지막 열이 want 인 줄 수."""
    n = 0
    if not os.path.isfile(path):
        return 0
    with io.open(path, "r", errors="ignore") as f:
        next(f, None)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p and p[-1] == want:
                n += 1
    return n


def scan_raw(path):
    """context_raw.rpt 을 한 번만 읽어 필요한 것을 다 모은다.

    파일이 수백 MB 가 될 수 있으므로 줄마다 싼 판정만 한다.
    """
    st = {"blocks": 0, "ok": 0, "err": 0, "vdd": {}, "mode": {},
          "delta_pos": 0, "delta_seen": 0, "nagg_max": 0, "msgs": {}}
    with io.open(path, "r", errors="ignore") as f:
        for line in f:
            c = line[:1]
            if c == "#":
                if line.startswith("### PATH_CONTEXT_BEGIN"):
                    st["blocks"] += 1
                elif line.startswith("### status="):
                    if line.rstrip().endswith("=OK"):
                        st["ok"] += 1
                    else:
                        st["err"] += 1
                elif line.startswith("### message="):
                    m = line.rstrip()[12:].strip()
                    if m:
                        st["msgs"][m] = st["msgs"].get(m, 0) + 1
                continue
            if c != "A" and c != "V" and c != "N":
                continue
            if c == "A":
                m = DELTA_RE.match(line)
                if m:
                    st["mode"][m.group(1)] = st["mode"].get(m.group(1), 0) + 1
                    st["delta_seen"] += 1
                    try:
                        # setup(-max) 은 지연이 늘어 delta 가 양수,
                        # hold(-min) 은 지연이 줄어 **음수**로 나온다.
                        # 그래서 부호가 아니라 '0 이 아닌가' 로 센다.
                        if float(m.group(2)) != 0.0:
                            st["delta_pos"] += 1
                    except ValueError:
                        pass
                continue
            if c == "V":
                m = VDD_RE.search(line)
                if m:
                    v = m.group(1)
                    st["vdd"][v] = st["vdd"].get(v, 0) + 1
                continue
            m = NAGG_RE.match(line)
            if m:
                n = int(m.group(1))
                if n > st["nagg_max"]:
                    st["nagg_max"] = n
    return st


def check_one(xdir):
    """코너 하나. (이름, 값들, 문제목록) 반환."""
    base = os.path.dirname(os.path.abspath(xdir))
    name = os.path.basename(base)
    bad = []

    missing = [n for n in NEED
               if not os.path.isfile(os.path.join(xdir, n))
               or os.path.getsize(os.path.join(xdir, n)) == 0]
    if missing:
        return name, None, ["파일 없음/빈 파일: %s" % ", ".join(missing)]

    st = scan_raw(os.path.join(xdir, "context_raw.rpt"))
    n_ctx = count_rows(os.path.join(xdir, "unique_contexts.tsv"))
    n_vw = count_rows(os.path.join(xdir, "victim_windows.tsv"))
    n_aw = count_rows(os.path.join(xdir, "aggressor_windows.tsv"))
    n_vbad = count_field(os.path.join(xdir, "victim_windows.tsv"), -1, "PIN_NOT_FOUND")
    n_abad = count_field(os.path.join(xdir, "aggressor_windows.tsv"), -1, "NO_DRIVER")

    if st["blocks"] == 0:
        bad.append("PT 원문에 context 가 0개")
    if st["blocks"] != n_ctx:
        bad.append("물어본 수(%d) != 목록 수(%d) -- 중간에 끊겼을 수 있음"
                   % (st["blocks"], n_ctx))
    if st["err"]:
        top = sorted(st["msgs"].items(), key=lambda x: -x[1])[:1]
        bad.append("%d개 실패%s" % (st["err"], (" (%s)" % top[0][0][:40]) if top else ""))
    if len(st["vdd"]) == 0:
        bad.append("VDD 를 못 읽음 -- 어느 코너로 계산됐는지 확인 불가")
    elif len(st["vdd"]) > 1:
        bad.append("한 파일 안에 VDD 가 여러 개: %s" % ", ".join(sorted(st["vdd"])))
    if len(st["mode"]) > 1:
        bad.append("한 파일 안에 setup/hold 가 섞임")
    if st["delta_seen"] and st["delta_pos"] == 0:
        bad.append("crosstalk 이 전부 0 -- SI 가 꺼졌거나 coupling 없는 SPEF")
    elif st["delta_seen"] and st["delta_pos"] * 100 < st["delta_seen"]:
        bad.append("crosstalk 이 잡힌 넷이 1%% 미만(%d/%d) -- 확인 필요"
                   % (st["delta_pos"], st["delta_seen"]))
    if n_vw <= 0:
        bad.append("victim 도착시각이 비었음")
    if n_vbad and n_vw and n_vbad * 2 > n_vw:
        bad.append("victim 핀 절반 이상을 못 찾음(%d/%d) -- 넷리스트 불일치" % (n_vbad, n_vw))
    if n_aw <= 0:
        bad.append("aggressor 도착시각이 비었음")
    if n_abad and n_aw and n_abad * 2 > n_aw:
        bad.append("aggressor driver 절반 이상을 못 찾음(%d/%d)" % (n_abad, n_aw))

    vdd = sorted(st["vdd"])[0] if len(st["vdd"]) == 1 else "?"
    mode = ("setup" if "max" in st["mode"] else
            "hold" if "min" in st["mode"] else "?")
    val = {"dir": xdir, "vdd": vdd, "mode": mode, "ctx": n_ctx,
           "ok": st["ok"], "err": st["err"],
           "dpos": st["delta_pos"], "dseen": st["delta_seen"],
           "vw": n_vw, "vbad": n_vbad, "aw": n_aw, "abad": n_abad,
           "ctxfile": os.path.join(xdir, "unique_contexts.tsv")}
    return name, val, bad


def file_sig(path):
    """파일 내용 서명. 코너끼리 같은지만 보면 되므로 전체를 읽는다
    (unique_contexts.tsv 는 수십 KB 수준이라 부담이 없다)."""
    import hashlib
    h = hashlib.md5()
    with io.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(
        description="현장에서 받은 crosstalk 결과를 코너별로 검사한다.")
    ap.add_argument("--root", default=".",
                    help="받은 폴더. 그 아래 xtalk 폴더를 전부 찾는다")
    args = ap.parse_args()

    print("=" * 68)
    print("6 - 받은 crosstalk 결과 검사")
    print("=" * 68)

    if not os.path.isdir(args.root):
        code("E-NOXTALK", "[ 실패 ] 폴더가 없습니다: %s" % args.root)

    xdirs = find_xtalk_dirs(args.root)
    if not xdirs:
        code("E-NOXTALK", "[ 실패 ] xtalk 폴더가 없습니다: %s" % args.root)

    print("  대상 : %s" % os.path.abspath(args.root))
    print("  코너 : %d개" % len(xdirs))
    print("")

    rows = []
    for x in xdirs:
        rows.append(check_one(x))

    print("  %-26s %-6s %-9s %8s %7s %10s %9s" %
          ("코너", "분석", "VDD", "context", "실패", "crosstalk", "aggressor"))
    print("  " + "-" * 82)
    n_bad = 0
    for name, v, bad in rows:
        if v is None:
            print("  %-26s %s" % (name[:26], "읽을 수 없음"))
            n_bad += 1
            continue
        print("  %-26s %-6s %-9s %8d %7d %10s %9s" %
              (name[:26], v["mode"], v["vdd"], v["ctx"], v["err"],
               "%d/%d" % (v["dpos"], v["dseen"]),
               "%d%s" % (v["aw"], ("(-%d)" % v["abad"]) if v["abad"] else "")))
        if bad:
            n_bad += 1

    # --- 코너별 문제 ---
    if any(b for _, _, b in rows):
        print("")
        print("  [ 코너별 문제 ]")
        for name, _, bad in rows:
            for b in bad:
                print("    %-26s %s" % (name[:26], b))

    # --- 코너 사이 비교 ---
    good = [(n, v) for n, v, b in rows if v is not None]
    cross = []
    if len(good) > 1:
        # VDD 는 **같은 분석(setup/hold) 안에서만** 겹치면 안 된다.
        # 같은 코너의 setup 과 hold 가 같은 전압인 것은 당연하다.
        vdds = {}
        for n, v in good:
            vdds.setdefault((v["mode"], v["vdd"]), []).append(n)
        dup = {k: ns for k, ns in vdds.items() if len(ns) > 1 and k[1] != "?"}
        if dup:
            for (mode, k), ns in sorted(dup.items()):
                cross.append("%s 에서 VDD %s 가 여러 코너에 겹칩니다: %s"
                             % (mode, k, ", ".join(ns)))
            cross.append("  -> 코너를 바꾸면서 db 를 다시 안 읽었을 때 이렇게 됩니다.")

        # 넷 목록도 같은 분석 안에서만 같아야 한다. setup 과 hold 는
        # -path_type full_clock_expanded 의 클럭 구간이 달라 원래 다르다.
        for mode in sorted(set(v["mode"] for _, v in good)):
            sigs = {}
            for n, v in good:
                if v["mode"] != mode:
                    continue
                sigs.setdefault(file_sig(v["ctxfile"]), []).append(n)
            if len(sigs) > 1:
                cross.append("%s 안에서 넷 목록이 코너마다 다릅니다(%d 종류):"
                             % (mode, len(sigs)))
                for sg, ns in sigs.items():
                    cross.append("    %s : %s" % (sg[:8], ", ".join(ns)))
                cross.append("  -> 서로 다른 fixed_paths.tcl 로 돌렸을 때 그렇습니다.")

    if cross:
        print("")
        print("  [ 코너 사이 ]")
        for c in cross:
            print("    %s" % c)

    print("")
    print("-" * 68)
    if n_bad == 0 and not cross:
        print("  코너 %d개 전부 정상입니다." % len(good))
        print("  다음은 코너마다:")
        print("    python3 5a_contexts.py --xtalk <xtalk폴더> --annotated <그 코너의 .rpt>")
        print("    python3 5b_pairs.py    --xtalk <xtalk폴더>%s"
              % ("  --mode hold" if good and good[0][1]["mode"] == "hold" else ""))
        print("    python3 5c_report.py   --xtalk <xtalk폴더>")
        code("OK-XCHECK")
        return                       # code() 는 OK 일 때 sys.exit 하지 않는다
    print("  문제 있는 코너 : %d개" % n_bad)
    if cross:
        print("  코너 사이 문제 : %d건" % len(cross))
    code("E-CORNER", "")


if __name__ == "__main__":
    main()
