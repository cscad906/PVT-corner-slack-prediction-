"""Path-key and corner utilities.

A corner's identity is a **(voltage, second-axis)** pair. The second continuous
axis is data-dependent: the 14nm BEOL corpus uses **RC** (the parasitic corner
Cmin/Cnom/Cmax), the 3nm corpus uses **temperature**. Everything else that
distinguishes one model from another -- temperature *when it is split*, process,
setup vs hold -- is NOT a corner axis; it selects a separate model (see README).

Path keys look like ``<startpoint>-><endpoint>_#<idx>`` (some reports use an
``_#idx`` ordinal, some ``#idx``; the leading underscore is optional). That
``#idx`` is a per-report enumeration, NOT part of path identity -- strip it
before any cross-corner join (the classic 14nm gotcha: aligning on the raw key
collapses common paths from ~2758 to ~8).
"""
from __future__ import annotations

import re

# RC (BEOL parasitic) corner -> signed scalar axis coordinate.
# Cmin = least coupling cap ... Cmax = most; centered so Cnom = 0.
RC_VAL = {"Cmin": -1.0, "Cnom": 0.0, "Cmax": 1.0}
RC_NAMES = ("Cmin", "Cnom", "Cmax")

# temperature directory / filename token -> Celsius (used for discovery /
# labelling, and as the second-axis coordinate when the data is V x T).
TEMP_MAP = {"m40": -40.0, "25": 25.0, "125": 125.0}

_IDX_RE = re.compile(r"_?#\d+$")
_VOLT_RE = re.compile(r"_tt(0p\d+)v", re.IGNORECASE)          # annotated filename
# canonical corner labels: voltage + (RC name) OR voltage + (temperature)
_CORNER_RC_RE = re.compile(r"TT_(\d+)p(\d+)V_(Cmin|Cnom|Cmax)")
_CORNER_T_RE = re.compile(r"TT_(\d+)p(\d+)V_(m?)(\d+)C")
# crosstalk filename: TT_0p605V_m40C.path_context_si_compact.by_path.rpt
_XT_RE = re.compile(r"TT_(0p\d+)V_(m?\d+)C")


def norm_path_key(key: str) -> str:
    """Strip the trailing ``_#<idx>`` / ``#<idx>`` ordinal from a fixed-path key."""
    return _IDX_RE.sub("", key.strip())


def volt_to_float(tok: str) -> float:
    """``0p605`` -> 0.605 ; ``0p6`` -> 0.6 ; ``0p65`` -> 0.65."""
    return float(tok.lower().replace("0p", "0.").replace("p", "."))


def volt_to_tok(v: float) -> str:
    """0.605 -> ``0p605`` ; 0.6 -> ``0p6`` (canonical, trailing zeros trimmed)."""
    s = ("%0.3f" % v).rstrip("0").rstrip(".")
    return s.replace("0.", "0p")


def parse_voltage_from_annotated(fname: str, regex=None) -> float | None:
    """Voltage from an annotated-report filename. ``regex`` (a compiled pattern
    with the voltage token as group 1) overrides the SAED default so a different
    vendor filename (e.g. ``..._v0p75_...``) can be handled from config."""
    m = (regex or _VOLT_RE).search(fname)
    return volt_to_float(m.group(1)) if m else None


def parse_xt_name(fname: str, prefix: str = "TT") -> tuple[float, str] | None:
    """crosstalk basename -> (voltage, temp_token) e.g. (0.605, 'm40').
    ``prefix`` = the process-corner token in the filename (``data.corner_prefix``)."""
    if prefix == "TT":
        m = _XT_RE.search(fname)
    else:
        m = re.search(re.escape(prefix) + r"_(0p\d+)V_(m?\d+)C", fname)
    if not m:
        return None
    return volt_to_float(m.group(1)), m.group(2)


def corner_label(v: float, axis1, prefix: str = "TT") -> str:
    """Canonical per-corner string. ``axis1`` is a categorical level NAME (any
    string, e.g. ``'Cmin'`` / ``'Cworst'`` / ``'RCmax'``) for a V x <categorical>
    grid, or a temperature number for a V x T grid.

    ``prefix`` is the process-corner token leading every label (``TT`` here,
    but e.g. ``FFPG``/``SSPG`` in another vendor's deliverable -- the process is
    a SPLIT dimension, so each model instance carries one fixed prefix; set it
    via ``data.corner_prefix`` in the config)."""
    if isinstance(axis1, str):
        return f"{prefix}_{volt_to_tok(v)}V_{axis1}"
    # temperature label, e.g. -40 -> m40C, 125 -> 125C
    tt = int(round(float(axis1)))
    tok = f"m{abs(tt)}" if tt < 0 else f"{tt}"
    return f"{prefix}_{volt_to_tok(v)}V_{tok}C"


def parse_corner(label: str, levels: dict | None = None,
                 prefix: str = "TT") -> tuple[float, float]:
    """``TT_0p605V_Cmin`` -> (0.605, -1.0) = (voltage, level_value); or
    ``TT_0p65V_m40C`` -> (0.65, -40.0) = (voltage, temperature).

    ``levels`` is the categorical second-axis name->value map from the config
    (e.g. ``{'Cbest': -1, 'Ctyp': 0, 'Cworst': 1}``); ``prefix`` is the
    process-corner token (``data.corner_prefix``, e.g. ``FFPG``). Together they
    let any vendor naming be parsed without code changes. When ``levels`` is
    omitted, the built-in RC map is tried first, then the temperature form.
    """
    lv = levels if levels is not None else RC_VAL
    names = sorted(lv, key=len, reverse=True)
    p = re.escape(prefix)
    pat = re.compile(p + r"_(\d+)p(\d+)V_(" + "|".join(re.escape(n) for n in names) + r")\b")
    m = pat.search(label)
    if m:
        volt = float(f"{m.group(1)}.{m.group(2)}")
        return volt, float(lv[m.group(3)])
    m = re.search(p + r"_(\d+)p(\d+)V_(m?)(\d+)C", label)
    if m:
        volt = float(f"{m.group(1)}.{m.group(2)}")
        temp = float(m.group(4)) * (-1.0 if m.group(3) == "m" else 1.0)
        return volt, temp
    raise ValueError(f"unrecognized corner label (prefix={prefix!r}): {label!r}")
