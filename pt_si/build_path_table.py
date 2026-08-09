#!/usr/bin/env python3
"""report_timing 리포트 + report_attribute 덤프 -> 경로 단위 wide 학습 테이블.

PT 쪽에서 필요한 것은 세 가지뿐이다:

    report_timing ...                                    -> timing.rpt
    redirect -file net_attr.txt { report_attribute -application [get_nets *] }
    redirect -file pin_attr.txt { report_attribute -application [get_pins *] }

report_attribute 출력에는 경로 정보가 없고(객체 단위), report_timing 리포트에는
crosstalk 값이 없다. 이 스크립트가 리포트에서 (path, arc, pin, net) 순서를 뽑아
attribute 를 join 한다. 결과는 arc 한 개당 한 행이다.

사용:
    python3 build_path_table.py \
        --rpt timing.rpt --net-attr net_attr.txt --pin-attr pin_attr.txt \
        --out path_table.tsv

    # 컬럼 고정(여러 코너를 합칠 때) + 코너 라벨 부착
    python3 build_path_table.py ... \
        --net-attrs annotated_delay_delta_max,number_of_aggressors \
        --pin-attrs max_rise_arrival,max_fall_arrival \
        --corner tt0p65v25c_Cnom
"""
import argparse
import csv
import re
import sys
from pathlib import Path

START_RE = re.compile(r"^\s*Startpoint:\s+(\S+)")
END_RE = re.compile(r"^\s*Endpoint:\s+(\S+)")
GROUP_RE = re.compile(r"^\s*Path Group:\s+(.+?)\s*$")
TYPE_RE = re.compile(r"^\s*Path Type:\s+(.+?)\s*$")
SLACK_RE = re.compile(r"^\s*slack\s*\(([^)]+)\)\s+(-?[\d.]+)")
# "inst/pin (CELL) ... 0.0346 r"  /  "netname (net)   9   0.0150"
OBJ_RE = re.compile(r"^\s{2,}(\S+)\s+\(([^)]+)\)")
EDGE_RE = re.compile(r"\s([rf])\s*$")

NULL_TOKENS = {"", "-", "N/A", "n/a", "NULL", "null", "{}"}


def load_attr_dump(path):
    """report_attribute 출력 -> {object: {attr: value}} 와 등장한 attribute 집합."""
    table, seen = {}, {}
    if path is None:
        return table, seen
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"ERROR: 파일 없음: {p}")
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            s = raw.strip()
            if not s or s[0] in "-*#":
                continue
            parts = raw.split(None, 4)
            if len(parts) < 5:
                continue
            _scope, obj, _atype, attr, value = parts
            value = value.strip()
            if value in NULL_TOKENS:
                value = ""
            table.setdefault(obj, {})[attr] = value
            seen[attr] = seen.get(attr, 0) + 1
    return table, seen


def iter_arcs(rpt):
    """리포트를 훑어 (path_idx, meta, arc_idx, pin, cell, edge, net) 를 내놓는다.

    한 arc = 리포트에 나오는 '핀 라인 + 바로 뒤 (net) 라인' 쌍. 핀은 신호가 지나간
    지점이고 net 은 그 핀이 구동/수신하는 배선이라, crosstalk 는 net 쪽에 붙는다.
    """
    path_idx = 0
    meta = None
    pending = None   # (arc_idx, pin, cell, edge) -- net 라인을 기다리는 중
    arc_idx = 0

    with Path(rpt).open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")

            m = START_RE.match(line)
            if m:
                path_idx += 1
                arc_idx = 0
                pending = None
                meta = {"startpoint": m.group(1), "endpoint": "",
                        "path_group": "", "path_type": "",
                        "slack": "", "slack_status": ""}
                continue
            if meta is None:
                continue

            m = END_RE.match(line)
            if m:
                meta["endpoint"] = m.group(1)
                continue
            m = GROUP_RE.match(line)
            if m:
                meta["path_group"] = m.group(1)
                continue
            m = TYPE_RE.match(line)
            if m:
                meta["path_type"] = m.group(1)
                continue
            m = SLACK_RE.match(line)
            if m:
                meta["slack_status"] = m.group(1)
                meta["slack"] = m.group(2)
                # slack 은 블록 끝에 나오므로, 남아있던 핀은 net 없이 확정한다.
                if pending:
                    yield (path_idx, meta, *pending, "")
                    pending = None
                continue

            m = OBJ_RE.match(line)
            if not m:
                continue
            name, kind = m.group(1), m.group(2)

            if kind.lower() == "net":
                if pending:
                    yield (path_idx, meta, *pending, name)
                    pending = None
                continue

            # 핀 라인. 앞의 핀이 net 을 못 만났으면 net 없이 확정.
            if pending:
                yield (path_idx, meta, *pending, "")
            arc_idx += 1
            e = EDGE_RE.search(line)
            pending = (arc_idx, name, kind, e.group(1) if e else "")

    if pending and meta is not None:
        yield (path_idx, meta, *pending, "")


def main():
    ap = argparse.ArgumentParser(
        description="report_timing + report_attribute -> 경로 단위 wide TSV")
    ap.add_argument("--rpt", required=True, help="report_timing 출력")
    ap.add_argument("--net-attr", default=None, help="report_attribute [get_nets *] 출력")
    ap.add_argument("--pin-attr", default=None, help="report_attribute [get_pins *] 출력")
    ap.add_argument("--out", required=True, help="출력 TSV")
    ap.add_argument("--net-attrs", default=None,
                    help="쉼표 구분. 지정하면 그 순서로 컬럼 고정(코너 간 합칠 때 권장).")
    ap.add_argument("--pin-attrs", default=None, help="위와 동일, 핀 쪽.")
    ap.add_argument("--corner", default=None,
                    help="모든 행에 붙일 코너 라벨. 여러 코너를 concat 할 때 쓴다.")
    args = ap.parse_args()

    if not Path(args.rpt).exists():
        raise SystemExit(f"ERROR: 파일 없음: {args.rpt}")

    net_tab, net_seen = load_attr_dump(args.net_attr)
    pin_tab, pin_seen = load_attr_dump(args.pin_attr)

    net_cols = ([a.strip() for a in args.net_attrs.split(",") if a.strip()]
                if args.net_attrs else sorted(net_seen))
    pin_cols = ([a.strip() for a in args.pin_attrs.split(",") if a.strip()]
                if args.pin_attrs else sorted(pin_seen))

    header = (["corner"] if args.corner else []) + [
        "path_idx", "startpoint", "endpoint", "path_group", "path_type",
        "slack_status", "slack", "arc_idx", "pin", "cell", "edge", "net",
    ] + [f"net.{c}" for c in net_cols] + [f"pin.{c}" for c in pin_cols]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_rows = n_paths = 0
    n_net_hit = n_net_miss = 0
    n_pin_hit = n_pin_miss = 0
    n_delta_nonzero = 0
    last_path = 0

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        for path_idx, meta, arc_idx, pin, cell, edge, net in iter_arcs(args.rpt):
            if path_idx != last_path:
                n_paths += 1
                last_path = path_idx
            na = net_tab.get(net, {})
            pa = pin_tab.get(pin, {})
            if net:
                if na:
                    n_net_hit += 1
                else:
                    n_net_miss += 1
            if pa:
                n_pin_hit += 1
            else:
                n_pin_miss += 1
            d = na.get("annotated_delay_delta_max", "")
            try:
                if d and float(d) != 0:
                    n_delta_nonzero += 1
            except ValueError:
                pass

            row = ([args.corner] if args.corner else []) + [
                path_idx, meta["startpoint"], meta["endpoint"],
                meta["path_group"], meta["path_type"],
                meta["slack_status"], meta["slack"],
                arc_idx, pin, cell, edge, net,
            ] + [na.get(c, "") for c in net_cols] + [pa.get(c, "") for c in pin_cols]
            w.writerow(row)
            n_rows += 1

    print(f"[OK] wrote {out}")
    print(f"[STATS] paths={n_paths} rows={n_rows} "
          f"net_cols={len(net_cols)} pin_cols={len(pin_cols)}")
    if args.net_attr:
        print(f"[JOIN] net  matched={n_net_hit} unmatched={n_net_miss}")
    if args.pin_attr:
        print(f"[JOIN] pin  matched={n_pin_hit} unmatched={n_pin_miss}")

    if n_rows == 0:
        print("[FAIL] 행이 하나도 없다 -- report_timing 출력이 맞는지 확인 "
              "(-nets -input_pins -path_type full_clock_expanded 필요)", file=sys.stderr)
        sys.exit(2)
    if args.net_attr and n_net_hit == 0:
        print("[FAIL] net attribute 가 하나도 매칭되지 않았다 -- "
              "리포트의 넷 이름과 report_attribute 의 객체 이름 표기가 다르다", file=sys.stderr)
        sys.exit(3)
    if args.net_attr and "annotated_delay_delta_max" in net_seen:
        if n_delta_nonzero == 0:
            print("[FAIL] crosstalk delta 가 전 구간 0 -- SPEF coupling 또는 "
                  "si_enable_analysis 확인", file=sys.stderr)
            sys.exit(3)
        print(f"[PASS] crosstalk delta nonzero rows = {n_delta_nonzero}")


if __name__ == "__main__":
    main()
