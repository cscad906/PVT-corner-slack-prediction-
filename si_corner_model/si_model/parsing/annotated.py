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
import re
from dataclasses import dataclass, field

# Every row regex ends with _TAIL rather than `$`, so a report that carries EXTRA
# TRAILING COLUMNS still parses and the extra columns are ignored. That is the
# statistical (SSTA) case: `report_timing` there appends per-row sigma /
# sensitivity columns after the deterministic ones. The columns this parser reads
# stay in the same order and position, so the FIRST value after each keyword is
# taken -- i.e. the nominal/mean number -- and anything after it is dropped.
#
# If a deliverable puts the nominal value somewhere OTHER than first, these
# regexes are the place to fix it (see docs/PARSING.md section 4); `bash scripts/run.sh
# check <file>` reports which of them match how many lines.
_TAIL = r"(?:\s+\S+)*\s*$"
# Skip anything that is not the start of a number. Lets a label sit BETWEEN the
# keyword and its value -- the statistical case, e.g.
#   'data arrival time (mean)   1.5000'
# -- so the first number after the keyword is still the one taken.
_GAP = r"[^0-9+-]*"

FIXED_PATH_RE = re.compile(r"^### FIXED_PATH idx=(\d+) key=(.*)$")
# 'slack (VIOLATED) -3.24' / '(MET)' plus rare '(VIOLATED: increase significant digits)'
SLACK_RE = re.compile(r"^\s+slack \((?:VIOLATED|MET)[^)]*\)" + _GAP + r"(-?\d+\.\d+)")
ARRIVAL_RE = re.compile(r"^\s+data arrival time\b" + _GAP + r"(-?\d+\.\d+)")
REQUIRED_RE = re.compile(r"^\s+data required time\b" + _GAP + r"(-?\d+\.\d+)")
# 'library setup time  -0.0804  2.9422' / 'library hold time  0.0775  0.5427' -> Incr col.
# The check name varies by deliverable (setup / hold / recovery / removal / ...),
# so any 'library <word> time' row counts; only the Incr column is used, and the
# field is OPTIONAL -- a report without it still trains (that token is just NaN).
CHECK_RE = re.compile(
    r"^\s+library \S+ time\b" + _GAP + r"(-?\d+\.\d+)" + _GAP + r"(-?\d+\.\d+)")
STARTPOINT_RE = re.compile(r"^\s+Startpoint:\s+(\S+)")
ENDPOINT_RE = re.compile(r"^\s+Endpoint:\s+(\S+)")
CLOCK_EDGE_RE = re.compile(r"^\s+clock \S+ \(rise edge\)")
# cell pin row:  <inst/pin> (<libcell>) [<-] [trans] [incr] [&] path r|f
#
# The report is column-aligned (Fanout Cap Trans Incr Path) and blank columns
# simply collapse, so the NUMBER OF VALUES ON A CELL ROW VARIES. Verified on a
# real PrimeTime V-2023.12 run:
#   ...reg_4_/Q (FDP_V2LP_1)     0.0144   0.0362 &   0.0362 r   <- trans incr path
#   ...reg_4_/CK (FDPRBQ_0P5)                       1.4999 r    <- path only
#     (an ideal-clock capture pin has no Trans/Incr) -- requiring three numbers
#     silently lost `capture_clk` on every such path.
# So the numeric run is captured as a whole and split by position from the RIGHT:
# the last value is always Path; Incr and Trans fill in when present.
CELL_RE = re.compile(
    r"^\s+(\S+/\S+) \((\S+)\)( <-)?\s+"
    r"((?:-?\d+\.\d+\s+(?:&\s+)?)+)([rf])(?:\s|$)"
)


def _cell_nums(blob: str) -> "tuple[float, float, float]":
    """Numeric run of a cell row -> (trans, incr, path). POSITIONAL fallback,
    used only when the report carries no column header (see ColumnMap).

    Values are right-aligned under Trans/Incr/Path, so the LAST one is Path.
    Missing leading columns become 0.0 (they are additive/feature inputs, and a
    blank column means the tool reported nothing there, not a real zero delay).
    """
    v = [float(x) for x in blob.replace("&", " ").split()]
    if len(v) >= 3:
        return v[-3], v[-2], v[-1]
    if len(v) == 2:
        return 0.0, v[0], v[1]
    return 0.0, 0.0, v[0]


# --------------------------------------------------------------- column header
# PrimeTime prints a column header above each path table and right-aligns every
# value under its heading. Reading that header is what makes this parser survive
# report variants instead of counting columns: a statistical run can SPLIT a
# heading into sub-columns, e.g.
#
#                            ------------ Incr -------------   ------ Path ------
#   Point            Fanout   Cap   Trans   Mean  Sensit  Corner  Value   Mean  Sensit  Value
#
# and a deterministic run prints the plain
#
#   Point            Fanout   Cap   Trans   Incr   Path
#
# Both are handled: a value is assigned to whichever heading its RIGHT EDGE is
# nearest, and a split heading becomes 'Incr.Value', 'Path.Mean', ... so the
# wanted sub-column is selected by name rather than by counting.
_HDR_NAME_RE = re.compile(r"\S+")
_HDR_GROUP_RE = re.compile(r"-{3,}\s*([A-Za-z][\w ]*?)\s*-{3,}")
# sub-column names a split heading uses; anything else is treated as a heading
_SUBCOLS = {"mean", "sensit", "sensitivity", "corner", "value", "sigma", "std"}


class ColumnMap:
    """Heading name -> right-edge character position, built from a header line
    (plus the optional group line above it)."""

    __slots__ = ("cols",)

    def __init__(self, name_line: str, group_line: "str | None" = None):
        groups = []
        if group_line:
            for m in _HDR_GROUP_RE.finditer(group_line):
                groups.append((m.start(), m.end(), m.group(1).strip()))
        self.cols: "list[tuple[str, int]]" = []
        for m in _HDR_NAME_RE.finditer(name_line):
            nm = m.group(0)
            if nm == "Point":
                continue
            if nm.lower() in _SUBCOLS:
                owner = next((g for lo, hi, g in groups if lo <= m.start() < hi), None)
                nm = f"{owner}.{nm}" if owner else nm
            self.cols.append((nm, m.end()))

    def has(self, *names: str) -> bool:
        have = {n for n, _ in self.cols}
        return all(n in have for n in names)

    def pick(self, values: "list[tuple[float, int]]", *names: str) -> float:
        """Value under the first present heading among ``names`` (NaN if none).

        ``values`` is [(number, right-edge-position), ...] from the data row.
        Each number is attributed to the nearest heading by right edge, which
        tolerates the small drift real reports have.
        """
        want = {n for n, _ in self.cols if n in names}
        if not want:
            return float("nan")
        best = float("nan")
        for v, end in values:
            nm = min(self.cols, key=lambda c: abs(c[1] - end))[0]
            if nm in want:
                best = v
        return best


_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _row_values(line: str, offset: int = 0) -> "list[tuple[float, int]]":
    """Numbers on a row with each one's right-edge column position.

    Integers (Fanout) and exponent notation are included; non-numeric fillers
    like the ``N/A`` that ``2c_merge.py`` writes for a missing Dist/Res/Cpin are
    simply absent from the result, which reads downstream as "not reported".
    """
    return [(float(m.group(0)), m.end() + offset) for m in _NUM_RE.finditer(line)]


def _is_header(line: str) -> bool:
    return "Point" in line and ("Incr" in line or "Path" in line or "Trans" in line)


# A net row is identified by the '(net)' object tag alone; its VALUES are then
# read from the column header (see ColumnMap). NET_RE below stays as the
# positional fallback for reports that carry no header at all.
NET_OBJ_RE = re.compile(r"^\s+(\S+) \(net\)")
# net row: <net> (net)  fanout cap [dist res cpin]  (BEOL parasitics present)
NET_RE = re.compile(
    r"^\s+(\S+) \(net\)\s+(\d+)\s+(\d+\.\d+)"
    r"(?:\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+))?" + _TAIL
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
    stages: "list[Stage]" = field(default_factory=list)


# Flip-flop pin names differ by library: the SAED14 drop uses /CK, the gt3 drop
# uses /CLK, others use /CP or /C. Hardcoding one silently loses launch_clk and
# capture_clk (they stay NaN) without any parse error, so the candidates are a
# configurable list -- `data.clock_pins` / `data.ff_output_pins`.
CLOCK_PINS = ("CK", "CLK", "CP", "C")
FF_OUT_PINS = ("Q", "QN", "QB", "Z")


def configure_pins(cfg: dict) -> None:
    """Install library-specific flip-flop pin names from config."""
    global CLOCK_PINS, FF_OUT_PINS
    d = cfg.get("data") or {}
    CLOCK_PINS = tuple(str(x) for x in d.get("clock_pins") or CLOCK_PINS)
    FF_OUT_PINS = tuple(str(x) for x in d.get("ff_output_pins") or FF_OUT_PINS)


def _finish(path: "AnnotatedPath | None", out: "dict[int, AnnotatedPath]") -> None:
    """Keep the block even when no slack line was parsed (slack stays NaN).

    A fixed-path re-measurement run emits one ``### FIXED_PATH`` header per path
    in the union list and then whatever ``report_timing`` returns -- which at
    some corners is nothing ("No paths."). Those blocks are UNRESOLVED, not
    corrupt: the builder drops any path that is unresolved at some corner, so
    what survives is the set measured at EVERY corner. Raising here instead
    would abort the whole build over one path missing at one corner.
    """
    if path is None:
        return
    out[path.idx] = path


def resolved(paths: "dict[int, AnnotatedPath]") -> "dict[int, AnnotatedPath]":
    """Only the blocks that actually carry a slack value."""
    return {i: p for i, p in paths.items() if p.slack == p.slack}


def parse_annotated(fp: str, with_stages: bool = False) -> "dict[int, AnnotatedPath]":
    """Parse one 14nm annotated report. Returns {idx: AnnotatedPath}."""
    out: "dict[int, AnnotatedPath]" = {}
    path: "AnnotatedPath | None" = None
    segment = ""
    clock_edges_seen = 0
    cmap: "ColumnMap | None" = None      # current table's column layout
    prev = ""                          # previous line (the group header, if any)

    with open(fp, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = FIXED_PATH_RE.match(line)
            if m:
                _finish(path, out)
                path = AnnotatedPath(idx=int(m.group(1)), key=m.group(2).strip())
                segment = ""
                clock_edges_seen = 0
                cmap = None
                prev = line
                continue
            # Re-read the header for every table: a fixed-path file concatenates
            # many report_timing outputs and each sizes its own columns.
            if _is_header(line):
                cmap = ColumnMap(line, prev if "---" in prev else None)
                prev = line
                continue
            prev = line
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
                pin, cell, crit, blob, edge = m.groups()
                if cmap is not None and cmap.has("Trans"):
                    # header-driven: pick columns BY NAME, so extra/split columns
                    # (statistical Mean/Sensit/Corner/Value) cannot shift them
                    off = m.start(4)
                    vals = _row_values(line[off:], off)
                    trans = cmap.pick(vals, "Trans")
                    incr = cmap.pick(vals, "Incr", "Incr.Value", "Incr.Mean")
                    pathv = cmap.pick(vals, "Path", "Path.Value", "Path.Mean")
                    if pathv != pathv:                 # heading not found
                        trans, incr, pathv = _cell_nums(blob)
                    trans = 0.0 if trans != trans else trans
                    incr = 0.0 if incr != incr else incr
                else:
                    trans, incr, pathv = _cell_nums(blob)
                if segment == "launch_clock" and pin in [
                        f"{path.startpoint}/{c}" for c in CLOCK_PINS]:
                    path.launch_clk = pathv
                elif segment == "capture_clock" and pin in [
                        f"{path.endpoint}/{c}" for c in CLOCK_PINS]:
                    path.capture_clk = pathv
                # launch clock -> data handoff: the startpoint FF's Q|QN output
                # pin starts the data segment (hierarchy-safe exact match).
                if (
                    segment == "launch_clock"
                    and clock_edges_seen == 1
                    and pin in [f"{path.startpoint}/{o}" for o in FF_OUT_PINS]
                ):
                    segment = "data"
                if not with_stages:
                    continue
                path.stages.append(Stage(
                    segment=segment, kind="cell", name=pin, cell=cell,
                    trans=trans, incr=incr, edge=edge,
                    critical=bool(crit),
                ))
                continue
            m = NET_OBJ_RE.match(line)
            if m and with_stages:
                net = m.group(1)
                off = m.end()
                if cmap is not None and cmap.has("Cap"):
                    # BEOL parasitics are APPENDED columns (pt_si_re/2c_merge.py
                    # widens the header with 'Dist Res Cpin' and right-aligns the
                    # values under them, writing 'N/A' where SPEF gave nothing).
                    # Selecting by heading therefore works whether those columns
                    # are present, absent, or shifted by other added columns.
                    vals = _row_values(line[off:], off)
                    g = lambda *n: cmap.pick(vals, *n)
                    fanout, cap = g("Fanout"), g("Cap")
                    dist, res, cpin = g("Dist"), g("Res"), g("Cpin")
                    if not cmap.has("Dist", "Res", "Cpin") and len(vals) == 5:
                        # BEOL parasitics appended with NO matching header. That
                        # is `2c_merge.py` on a statistical report: it widens the
                        # header only when the name line contains both 'Point'
                        # and 'Path', but a statistical run prints 'Path' on the
                        # GROUP line above, so the header is left untouched while
                        # net rows still get the three values appended.
                        # PrimeTime itself never puts Trans/Incr/Path on a net
                        # row, so anything past Fanout/Cap is the appended
                        # parasitics -- exactly three of them, or it is ambiguous
                        # (partial 'N/A') and they are better left unset.
                        dist, res, cpin = (v for v, _ in vals[2:5])
                else:
                    m2 = NET_RE.match(line)
                    if not m2:
                        continue
                    _, fo, cp, dist, res, cpin = m2.groups()
                    fanout, cap = float(fo), float(cp)
                    dist = float(dist) if dist else float("nan")
                    res = float(res) if res else float("nan")
                    cpin = float(cpin) if cpin else float("nan")
                z = lambda v: 0.0 if v != v else v          # NaN/N-A -> 0
                path.stages.append(Stage(
                    segment=segment, kind="net", name=net,
                    fanout=int(z(fanout)), cap=z(cap),
                    dist=z(dist), res=z(res), cpin=z(cpin),
                ))

    _finish(path, out)
    return out
