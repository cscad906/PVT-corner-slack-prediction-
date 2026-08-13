"""Parser for compact per-path crosstalk reports (*.path_context_si_compact.by_path.rpt).

Row schema (tab-separated, one header per path block):
  path_segment victim_net aggressor_net crosstalk_delta aggressor_bump
  number_of_aggressors victim_load_pin victim_load_min_arrival
  victim_load_max_arrival aggressor_driver_pin aggressor_driver_min_arrival
  aggressor_driver_max_arrival aggressor_driver_slew_max coupling_cap_ff

Facts verified on the 14nm iter51 SmallBoomV2 dataset (2026-07):
  - every path arc has a victim row; ``aggressor_net == "0"`` means no ACTIVE
    aggressor at this corner. In the setup (max) dump its delta is then
    always 0; in the hold (-min) dump small nonzero deltas (fs-scale) can
    remain after all aggressors were screened from the final table -- they
    are kept (part of the annotated slack) but such arcs have no aggressor
    candidates for the SI branch
  - aggressor rows repeat the victim-level crosstalk_delta (it is a per-net,
    not per-aggressor quantity); one row per ACTIVE ('A') aggressor
  - values may use exponent notation (e.g. 2.2e-05)
  - crosstalk_delta comes from ``report_delay_calculation -crosstalk``:
    the ``newsetup`` dump reports the MAX (late) analysis (positive deltas),
    the ``newhold`` dump the MIN (early) analysis (negative deltas). UNLIKE
    the earlier 3nm drop, the 14nm hold crosstalk was already extracted with
    ``-min`` (verified: newhold deltas are negative) -- so hold is NOT blocked
    here and ``si_total`` carries the correct sign for both checks.
"""
from dataclasses import dataclass, field

SEGMENTS = ("launch_clock", "data", "capture_clock")


@dataclass
class Aggressor:
    net: str
    driver_pin: str
    bump: float
    min_arrival: float
    max_arrival: float
    slew: float
    cc_ff: float


@dataclass
class VictimArc:
    segment: str
    net: str
    delta: float
    n_aggressors: int
    load_pin: str
    min_arrival: float
    max_arrival: float
    aggressors: "list[Aggressor]" = field(default_factory=list)


@dataclass
class CrosstalkPath:
    idx: int
    key: str
    slack: float
    arcs: "list[VictimArc]" = field(default_factory=list)

    def arc_map(self) -> "dict[tuple[str, str], VictimArc]":
        """{(segment, victim_net): arc}; duplicates verified consistent."""
        return {(a.segment, a.net): a for a in self.arcs}

    def si_total(self, segments: "tuple[str, ...]" = ("launch_clock", "data")) -> float:
        """Path-level SI delta: sum of unique (segment, net) deltas.

        Default sums launch_clock+data only: those are max-direction deltas,
        which is the correct direction for the setup data path. capture_clock
        would need MIN-direction deltas (not in this dump; measured <=1.7 ps,
        excluded until the per-net attribute dump lands).
        """
        seen: "dict[tuple[str, str], float]" = {}
        for a in self.arcs:
            if a.segment in segments:
                seen[(a.segment, a.net)] = a.delta
        return sum(seen.values())


def parse_crosstalk(fp: str) -> "dict[int, CrosstalkPath]":
    """Parse one compact crosstalk report. Returns {idx: CrosstalkPath}."""
    out: "dict[int, CrosstalkPath]" = {}
    path: "CrosstalkPath | None" = None
    arcs_by_key: "dict[tuple[str, str], VictimArc]" = {}

    def finish() -> None:
        if path is None:
            return
        if path.slack != path.slack:
            raise ValueError(f"path idx={path.idx}: missing '# Slack:' header")
        out[path.idx] = path

    with open(fp, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("### FIXED_PATH"):
                finish()
                head = line.split()
                idx = int(head[2].split("=", 1)[1])
                key = line.split("key=", 1)[1].strip()
                path = CrosstalkPath(idx=idx, key=key, slack=float("nan"))
                arcs_by_key = {}
                continue
            if path is None:
                continue
            if line.startswith("# Slack:"):
                path.slack = float(line.split()[-1])
                continue
            if not line.startswith(SEGMENTS):
                continue

            t = line.rstrip("\n").split("\t")
            if len(t) != 14:
                raise ValueError(f"idx={path.idx}: expected 14 columns, got {len(t)}: {line!r}")
            seg, vnet, anet = t[0], t[1], t[2]
            delta = float(t[3])
            akey = (seg, vnet)
            arc = arcs_by_key.get(akey)
            if arc is None:
                arc = VictimArc(
                    segment=seg, net=vnet, delta=delta,
                    n_aggressors=int(t[5]), load_pin=t[6],
                    min_arrival=float(t[7]), max_arrival=float(t[8]),
                )
                arcs_by_key[akey] = arc
                path.arcs.append(arc)
            elif abs(arc.delta - delta) > 1e-12:
                raise ValueError(
                    f"idx={path.idx} {akey}: inconsistent delta {arc.delta} vs {delta}")

            if anet == "0":
                continue
            arc.aggressors.append(Aggressor(
                net=anet, driver_pin=t[9], bump=float(t[4]),
                min_arrival=float(t[10]), max_arrival=float(t[11]),
                slew=float(t[12]), cc_ff=float(t[13]),
            ))

    finish()
    return out
