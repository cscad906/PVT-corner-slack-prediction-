#!/usr/bin/env python3
"""`report_attribute -application` 출력을 wide TSV 로 바꾼다.

PT 쪽에서 이렇게 뽑은 파일이 입력이다:

    redirect -file $OUT_NET { report_attribute -application $nets }
    redirect -file $OUT_PIN { report_attribute -application $pins }

`report_attribute` 는 객체마다 attribute 를 **한 줄에 하나씩** 뱉는 long 포맷이다:

    top    net123    float     annotated_delay_delta_max    0.030036
    top    net123    int       number_of_aggressors         211
    top    net123    collection effective_aggressors        _sel12

이 스크립트는 이를 객체 1행 × attribute 1열의 wide 표로 pivot 한다. 학습 입력으로
쓰려면 이 형태여야 하고, 컬럼 집합은 파일에 실제로 등장한 attribute 로 결정된다
(코너/PT 버전마다 다를 수 있으므로 하드코딩하지 않는다).

`--attrs` 로 원하는 attribute 만 골라 컬럼 순서를 고정할 수 있다. 여러 코너의 결과를
한 학습셋으로 합칠 때는 컬럼이 흔들리지 않도록 이 옵션을 쓰는 편이 안전하다.

사용:
    python3 parse_report_attribute.py --in corner.net_attr.txt --out corner.net.tsv
    python3 parse_report_attribute.py --in corner.net_attr.txt --out corner.net.tsv \
        --attrs annotated_delay_delta_max,number_of_aggressors,total_coupling_capacitance
"""
import argparse
import csv
import sys
from pathlib import Path

# report_attribute 한 줄: <scope> <object> <type> <attr_name> <value...>
# value 에 공백이 들어갈 수 있으므로(리스트/collection) 앞 4개만 자르고 나머지는 값으로 둔다.
MIN_FIELDS = 5

# 값이 없는 attribute 를 PT 가 이렇게 표기하는 경우가 있어 빈 문자열로 정규화한다.
NULL_TOKENS = {"", "-", "N/A", "n/a", "NULL", "null", "{}"}


def parse_lines(path: Path):
    """(object, attr, value) 를 순서대로 내놓는다. 헤더/구분선/빈 줄은 건너뛴다."""
    n_skipped = 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            s = line.strip()
            if not s:
                continue
            # 구분선(---), 배너(***), 리포트 헤더 라인
            if s.startswith("-") or s.startswith("*") or s.startswith("#"):
                continue
            parts = line.split(None, 4)
            if len(parts) < MIN_FIELDS:
                # "Attributes for ..." 같은 안내 문구
                n_skipped += 1
                continue
            _scope, obj, _atype, attr, value = parts
            value = value.strip()
            if value in NULL_TOKENS:
                value = ""
            yield obj, attr, value
    if n_skipped:
        print(f"[INFO] skipped {n_skipped} non-data lines", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(
        description="report_attribute -application 출력을 wide TSV 로 pivot 한다.")
    p.add_argument("--in", dest="src", required=True, help="report_attribute 출력 파일")
    p.add_argument("--out", dest="dst", required=True, help="출력 TSV")
    p.add_argument("--attrs", default=None,
                   help="쉼표로 구분한 attribute 화이트리스트. 지정하면 그 순서대로 컬럼을 만들고 "
                        "없는 값은 빈 칸으로 둔다(코너 간 컬럼 고정용). 생략하면 파일에 등장한 "
                        "attribute 전부를 이름순으로 쓴다.")
    p.add_argument("--object-column", default="object", help="객체 이름 컬럼명")
    args = p.parse_args()

    src = Path(args.src)
    if not src.exists():
        raise SystemExit(f"ERROR: 입력 파일 없음: {src}")

    wanted = None
    if args.attrs:
        wanted = [a.strip() for a in args.attrs.split(",") if a.strip()]

    rows = {}          # object -> {attr: value}
    order = []         # 객체 등장 순서 유지
    seen_attrs = {}    # attr -> 등장 횟수

    for obj, attr, value in parse_lines(src):
        if wanted is not None and attr not in wanted:
            continue
        if obj not in rows:
            rows[obj] = {}
            order.append(obj)
        rows[obj][attr] = value
        seen_attrs[attr] = seen_attrs.get(attr, 0) + 1

    if not rows:
        raise SystemExit(
            f"ERROR: {src} 에서 데이터 행을 찾지 못했다.\n"
            "  report_attribute 출력이 맞는지, -application 을 붙였는지 확인.")

    columns = wanted if wanted is not None else sorted(seen_attrs)

    dst = Path(args.dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow([args.object_column] + columns)
        for obj in order:
            attrs = rows[obj]
            w.writerow([obj] + [attrs.get(c, "") for c in columns])

    print(f"[OK] wrote {dst}")
    print(f"[STATS] objects={len(order)} columns={len(columns)}")

    # 화이트리스트를 줬는데 파일에 없던 attribute 는 컬럼이 통째로 비므로 알려준다.
    if wanted is not None:
        missing = [a for a in wanted if a not in seen_attrs]
        if missing:
            print(f"[WARN] 입력에 없던 attribute (빈 컬럼): {', '.join(missing)}")
            print("       PT 버전에 따라 이름이 다를 수 있다. "
                  "report_attribute -application <객체 1개> 로 실제 이름을 확인할 것.")

    # 전부 빈 값인 컬럼은 SI 가 꺼졌거나 grounded SPEF 라는 신호다.
    empty_cols = [c for c in columns
                  if all(not rows[o].get(c) for o in order)]
    if empty_cols:
        print(f"[WARN] 값이 전부 비어 있는 컬럼 {len(empty_cols)}개: "
              f"{', '.join(empty_cols[:8])}{' ...' if len(empty_cols) > 8 else ''}")
        print("       crosstalk 계열이라면 si_enable_analysis 와 "
              "SPEF coupling 유무를 확인할 것.")


if __name__ == "__main__":
    main()
