"""Parser for PrimeTime fixed-path annotated timing reports -- 14nm / SAED14 /
BEOL variant (self-contained; no external P4 imports).

One file per (V, RC) corner, ``### FIXED_PATH`` blocks, each a full
``report_timing -path_type full_clock_expanded -nets`` table WITH the BEOL RC
columns (Dist / Res / Cpin on net rows).

Differences from the 3nm (gt3) parser this mirrors:
  - FF clock pin is ``/CK`` (not ``/CLK``); logic-cell outputs are ``/X``,
    FF outputs ``/Q`` / ``/QN``.
  - instance names are hierarchical (``a/b/reg_3_/CK``) -- the launch->data
    handoff is detected by matching the startpoint FF's ``/Q`` | ``/QN`` output
    pin exactly, NOT by a flat ``split('/')[0]`` (which breaks on hierarchy).
  - net rows always carry the Dist/Res/Cpin BEOL parasitics.

Per path we extract: slack (label), data arrival / required, launch & capture
clock latencies, the library setup/hold check Incr, and the per-stage cell/net
rows with segment tags (launch_clock / data / capture_clock) for the ref-corner
path-signature + stage-sequence encoder features.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FIXED_PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+) key=(.*)$")
# 'slack (VIOLATED) -3.24' / '(MET)' plus rare '(VIOLATED: increase significant digits)'
SLACK_RE = re.compile(r"^\s+slack \((?:VIOLATED|MET)[^)]*\)\s+(-?\d+\.\d+)\s*$")
ARRIVAL_RE = re.compile(r"^\s+data arrival time\s+(-?\d+\.\d+)\s*$")
REQUIRED_RE = re.compile(r"^\s+data required time\s+(-?\d+\.\d+)\s*$")
# 'library setup time  -0.0804  2.9422' / 'library hold time  0.0775  0.5427' -> Incr col
CHECK_RE = re.compile(r"^\s+library (?:setup|hold) time\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$")
STARTPOINT_RE = re.compile(r"^\s+Startpoint:\s+(\S+)")
ENDPOINT_RE = re.compile(r"^\s+Endpoint:\s+(\S+)")
CLOCK_EDGE_RE = re.compile(r"^\s+clock \S+ \(rise edge\)")
# cell pin row:  <inst/pin> (<libcell>) [<-] trans incr [&] path r|f
# (Fanout/Cap columns are blank on cell rows; whitespace collapses.)
CELL_RE = re.compile(
    r"^\s+(\S+/\S+) \((\S+)\)( <-)?\s+"
    r"(\d+\.\d+)\s+(-?\d+\.\d+)\s+(?:&\s+)?(-?\d+\.\d+)\s+([rf])\s*$"
)
# net row: <net> (net)  fanout cap [dist res cpin]  (BEOL parasitics present)
NET_RE = re.compile(
    r"^\s+(\S+) \(net\)\s+(\d+)\s+(\d+\.\d+)"
    r"(?:\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+))?\s*$"
)


@dataclass
class Stage:
    segment: str          # launch_clock | data | capture_clock
    kind: str             # cell | net
    name: str             # inst/pin or net name
    cell: str = ""        # lib cell (cell rows)
    trans: float = 0.0
    incr: float = 0.0
    edge: str = ""        # r | f (cell rows)
    fanout: int = 0
    cap: float = 0.0
    dist: float = 0.0
    res: float = 0.0
    cpin: float = 0.0
    critical: bool = False    # '<-' marker on cell rows


@dataclass
class AnnotatedPath:
    idx: int
    key: str
    startpoint: str = ""
    endpoint: str = ""
    slack: float = float("nan")
    arrival: float = float("nan")
    required: float = float("nan")
    launch_clk: float = float("nan")   # clock arrival at <startpoint>/CK
    capture_clk: float = float("nan")  # clock arrival at <endpoint>/CK
    lib_check_time: float = float("nan")  # library setup/hold time (Incr column)
    stages: list[Stage] = field(default_factory=list)


def _finish(path: AnnotatedPath | None, out: dict[int, AnnotatedPath]) -> None:
    if path is None:
        return
    if path.slack != path.slack:  # NaN
        raise ValueError(f"path idx={path.idx} key={path.key}: no slack line parsed")
    out[path.idx] = path


def parse_annotated(fp: str, with_stages: bool = False) -> dict[int, AnnotatedPath]:
    """Parse one 14nm annotated report. Returns {idx: AnnotatedPath}."""
    out: dict[int, AnnotatedPath] = {}
    path: AnnotatedPath | None = None
    segment = ""
    clock_edges_seen = 0

    with open(fp, errors="ignore") as f:
        for line in f:
            m = FIXED_PATH_RE.match(line)
            if m:
                _finish(path, out)
                path = AnnotatedPath(idx=int(m.group(1)), key=m.group(2).strip())
                segment = ""
                clock_edges_seen = 0
                continue
            if path is None:
                continue

            m = STARTPOINT_RE.match(line)
            if m:
                path.startpoint = m.group(1)
                continue
            m = ENDPOINT_RE.match(line)
            if m:
                path.endpoint = m.group(1)
                continue

            if CLOCK_EDGE_RE.match(line):
                clock_edges_seen += 1
                segment = "launch_clock" if clock_edges_seen == 1 else "capture_clock"
                continue

            m = ARRIVAL_RE.match(line)
            if m and path.arrival != path.arrival:
                path.arrival = float(m.group(1))  # first occurrence only
                continue
            m = REQUIRED_RE.match(line)
            if m and path.required != path.required:
                path.required = float(m.group(1))
                continue
            m = SLACK_RE.match(line)
            if m:
                path.slack = float(m.group(1))
                continue
            m = CHECK_RE.match(line)
            if m:
                path.lib_check_time = float(m.group(1))
                continue

            if not segment:
                continue
            m = CELL_RE.match(line)
            if m:
                pin, cell, crit, trans, incr, pathv, edge = m.groups()
                if segment == "launch_clock" and pin == f"{path.startpoint}/CK":
                    path.launch_clk = float(pathv)
                elif segment == "capture_clock" and pin == f"{path.endpoint}/CK":
                    path.capture_clk = float(pathv)
                # launch clock -> data handoff: the startpoint FF's Q|QN output
                # pin starts the data segment (hierarchy-safe exact match).
                if (
                    segment == "launch_clock"
                    and clock_edges_seen == 1
                    and pin in (f"{path.startpoint}/Q", f"{path.startpoint}/QN")
                ):
                    segment = "data"
                if not with_stages:
                    continue
                path.stages.append(Stage(
                    segment=segment, kind="cell", name=pin, cell=cell,
                    trans=float(trans), incr=float(incr), edge=edge,
                    critical=bool(crit),
                ))
                continue
            m = NET_RE.match(line)
            if m and with_stages:
                net, fanout, cap, dist, res, cpin = m.groups()
                path.stages.append(Stage(
                    segment=segment, kind="net", name=net,
                    fanout=int(fanout), cap=float(cap),
                    dist=float(dist or 0.0), res=float(res or 0.0),
                    cpin=float(cpin or 0.0),
                ))

    _finish(path, out)
    return out
