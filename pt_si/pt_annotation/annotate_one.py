#!/usr/bin/env python3
"""단일 timing report 에 Dist/Res/Cpin 을 붙인다 (union/스윕 없이).

정식 경로(run_sweep.py)는 코너 전체를 돌며 경로를 고정해 annotate 하지만,
이 스크립트는 **이미 있는 rpt 파일 하나**만 처리한다. 용도:

  - PT 커맨드를 수동으로 돌려본 뒤 annotation 이 되는지 확인
  - 새 사이트에서 SPEF 이름 매칭/단위가 맞는지 소규모 점검
  - 한 코너 안에서 feature 분포만 볼 때

주의: 여기서 만든 파일은 **cross-corner 학습셋으로는 쓸 수 없다.** 코너마다
독립적으로 뽑은 리포트라 같은 순번의 경로가 서로 다른 물리 경로일 수 있다.
그 용도로는 extract_violation_paths.py -> run_sweep.py --reuse-strict-tcl 를 쓴다.

입력 rpt 는 아래 옵션으로 만든 report_timing 출력이어야 한다(= tcl/run_ref_topk.tcl):
  -path_type full_clock_expanded -input_pins -nets -capacitance -transition_time -nosplit
'(net)' 라인이 없으면 Dist/Res 를 붙일 자리가 없다.

사용:
  python3 annotate_one.py \
    --report rpts/Cnom/tt0p65v25c.rpt \
    --spef   /data/deliver/spef/mycore.Cnom_model_25.spef \
    --lib    /data/lib_db/lib/saed14rvt_tt0p65v25c_ccs.lib \
    --out    annotated/tt0p65v25c_annotated.txt
"""
import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import res  # noqa: E402  (경로 세팅 후 import)


def parse_args():
    p = argparse.ArgumentParser(
        description="단일 timing report 에 SPEF 유래 Dist/Res + Liberty 유래 Cpin 을 붙인다.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--report", required=True,
                   help="PT 가 만든 timing report (.rpt).")
    p.add_argument("--spef", required=True,
                   help="그 report 를 만들 때 PT 에 넣은 SPEF. **반드시 같은 파일이어야 한다** "
                        "-- 다른 RC 코너 SPEF 를 주면 Dist/Res 가 조용히 틀린 값으로 붙는다.")
    p.add_argument("--out", required=True,
                   help="출력 파일 경로.")
    p.add_argument("--lib", default=None,
                   help="Cpin lookup 용 Liberty(.lib). Liberty 를 받을 수 없으면 대신 "
                        "--pin-attr 를 쓴다. 둘 다 없으면 Cpin 컬럼이 빈다 "
                        "(Cpin 은 SPEF 에 없다).")
    p.add_argument("--pin-attr", default=None,
                   help="PT 핀 attribute 덤프. Liberty 대신 여기서 Cpin 을 읽는다. "
                        "pt_shell 에서 아래로 만든다:\n"
                        "  redirect -file pin_attr.txt "
                        "{ report_attribute -application [get_pins *] }\n"
                        "pin_capacitance_max 를 쓰며, 값의 단위가 리포트의 Cap 과 같다.")
    return p.parse_args()


ATTR_NAME = "pin_capacitance_max"


def load_pin_caps(path, attr=ATTR_NAME):
    """report_attribute 덤프에서 {설계핀이름: <attr>} 를 만든다.

    실제 출력은 세 가지 모양으로 나온다. 인스턴스 이름이 길면 컬럼이 넘쳐
    객체 이름과 값이 다음 줄로 밀리기 때문이다:

      (A) 한 줄:      <design> <object> float <attr> <value>
      (B) 객체 접힘:  <design> <object>
                              float <attr> <value>
      (C) 값 접힘:            float <attr>
                                          <value>

    (A)만 처리하면 우리 3nm 덤프 기준 207개(약 7%)를 놓친다. 세 형태를 모두 받는다.
    직전 객체 이름을 기억해 두고, attr 토큰을 만나면 그 줄이나 다음 줄에서 값을 읽는다.
    """
    caps = {}
    last_obj = None
    awaiting_value_for = None

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            # 구분선(----, ====)과 배너(***)만 건너뛴다.
            # 예전에 s[0] 로만 판단했더니 "-0.000274" 같은 **음수 값**이 구분선으로
            # 오인돼 통째로 사라졌다. 그 줄이 없어지면 대기 상태가 남아 다음 줄까지
            # 잘못 먹어, attribute 하나가 더 사라진다.
            if not s or s[0] == "*" or set(s) <= set("-=") :
                continue
            parts = s.split()

            # (C) 이전 줄이 attr 만 남기고 끝난 경우 -> 이 줄의 첫 토큰이 값
            if awaiting_value_for is not None:
                try:
                    caps[awaiting_value_for] = float(parts[0])
                except (ValueError, IndexError):
                    pass
                awaiting_value_for = None
                continue

            # 들여쓰기가 없는 줄은 <design> <object> ... 형태 -> 객체 이름 갱신
            if not raw[:1].isspace() and len(parts) >= 2:
                last_obj = parts[1]

            if attr not in parts:
                continue
            i = parts.index(attr)
            if i + 1 < len(parts):
                # (A)/(B): 같은 줄에 값이 있다
                try:
                    caps[last_obj] = float(parts[i + 1])
                except (ValueError, TypeError):
                    pass
            else:
                # (C): 값이 다음 줄
                awaiting_value_for = last_obj
    return caps


def main():
    args = parse_args()

    report = Path(args.report)
    spef = Path(args.spef)
    out = Path(args.out)
    lib = Path(args.lib) if args.lib else None
    pin_attr = Path(args.pin_attr) if args.pin_attr else None

    missing = [str(p) for p in ([report, spef]
                                + ([lib] if lib else [])
                                + ([pin_attr] if pin_attr else [])) if not p.exists()]
    if missing:
        raise SystemExit("ERROR: 입력 파일 없음:\n  " + "\n  ".join(missing))

    # '(net)' 라인이 없으면 붙일 자리가 없다 -- 리포트 옵션 누락을 조기에 잡는다.
    with report.open("r", encoding="utf-8", errors="ignore") as f:
        has_net = any("(net)" in line for line in f)
    if not has_net:
        raise SystemExit(
            f"ERROR: {report} 에 '(net)' 라인이 없다.\n"
            "  report_timing 을 -nets -input_pins -capacitance -transition_time "
            "-path_type full_clock_expanded -nosplit 로 다시 뽑아야 한다.")

    pin_caps = {}
    if pin_attr:
        pin_caps = load_pin_caps(str(pin_attr))
        if not pin_caps:
            raise SystemExit(
                "ERROR: {0} 에서 pin_capacitance_max 를 하나도 못 읽었다.\n"
                "  pt_shell 에서 아래로 다시 뽑아야 한다:\n"
                "    redirect -file pin_attr.txt "
                "{{ report_attribute -application [get_pins *] }}".format(pin_attr))
        print("[INFO] PT 핀 capacitance {0}개 로드 ({1})".format(len(pin_caps), pin_attr))

    out.parent.mkdir(parents=True, exist_ok=True)
    res.annotate_timing_report(str(report), str(spef), str(out),
                               lib_path=str(lib) if lib else None,
                               pin_cap_map=pin_caps)

    # 자가 점검: 붙은 컬럼 수와 N/A 를 세어 성공 여부를 눈으로 확인할 수 있게 한다.
    n_net = n_ann = n_na = 0
    with out.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "(net)" not in line:
                continue
            n_net += 1
            tail = line.rstrip("\n").split()[-3:]
            if len(tail) == 3 and any("N/A" in t for t in tail):
                n_na += 1
            elif len(tail) == 3:
                n_ann += 1

    print(f"\n[OK] wrote {out}")
    print(f"[STATS] net_lines={n_net} annotated={n_ann} na={n_na}")
    if n_net and n_na / n_net > 0.1:
        print("[WARN] N/A 비율이 10%% 를 넘는다 -- SPEF/netlist 이름 규약 불일치 가능성. "
              "README 의 'N/A 매칭 실패' 항목 참조.")
    if not lib and not pin_attr:
        print("[NOTE] --lib 도 --pin-attr 도 주지 않아 Cpin 이 비어 있다.")
        print("       Liberty 가 없으면 pt_shell 에서 핀 attribute 를 덤프해 --pin-attr 로 준다:")
        print("         redirect -file pin_attr.txt "
              "{ report_attribute -application [get_pins *] }")


if __name__ == "__main__":
    main()
