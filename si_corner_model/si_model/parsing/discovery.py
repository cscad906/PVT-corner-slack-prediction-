"""Corner discovery: map report files on disk -> canonical corner labels.

Shared by the slack builder (``parsing/build_dataset``) and the slew builder
(``tasks/slew/build_slew``), so the two can never drift apart.

Two layouts, selected by ``data.patterns.layout``:

``levels`` (default -- the 14nm/SAED reference drop)
    ``<dir>/<LEVEL>/<one report per voltage>``; the level comes from the
    sub-folder name, the voltage from the filename.

``flat``
    every corner coordinate is encoded in ONE filename, at any depth below
    ``<dir>``; the tree is walked recursively and each basename matched against
    a single regex with named groups::

        data:
          annotated_dir: ${root}/${design}
          patterns:
            layout: flat
            annotated_regex: 'report\\.(?P<proc>[A-Za-z]+)_(?P<v>0p\\d+)_(?P<temp>m?\\d+)c_(?P<level>[A-Za-z]+\\d*)\\.'

    Named groups: ``v`` and ``level`` are required; ``temp`` and ``proc`` are
    optional and, when present, FILTER the files down to this model's split
    (``data.temp`` / ``data.corner_prefix``) -- which is how one flat directory
    holding every temperature and process feeds several model instances.

Crosstalk discovery is identical but optional: a config with no
``data.crosstalk_dir`` builds an SI-free dataset (base + attention only), so a
deliverable whose crosstalk dump has not been located yet is not blocked.
"""
import os
import re

from .keys import (RC_NAMES, RC_VAL, corner_label, parse_corner,
                   parse_voltage_from_annotated, parse_xt_name, volt_to_float)


# ------------------------------------------------------------------ config bits
def corner_levels(cfg: dict) -> dict:
    """Second-axis level name->value map (config ``axes[1].levels``), falling
    back to the built-in RC map."""
    from si_model.config import axis_levels
    return axis_levels(cfg) or dict(RC_VAL)


def level_names(cfg: dict) -> list:
    """Level names to look for, in config order (``data.rc_corners``)."""
    levels = corner_levels(cfg)
    return list(cfg["data"].get("rc_corners", list(levels) or list(RC_NAMES)))


def _patterns(cfg: dict) -> dict:
    return cfg["data"].get("patterns") or {}


def layout(cfg: dict) -> str:
    lay = _patterns(cfg).get("layout", "levels")
    assert lay in ("levels", "flat"), f"data.patterns.layout must be levels|flat, got {lay!r}"
    return lay


# --------------------------------------------------- order-free token matching
# A single positional regex breaks on anything the vendor arranges differently:
# a missing 'c' after the temperature, level and temperature swapped, upper case,
# a voltage written 0.5400 instead of 0p5000. Since the four things we need are
# each recognisable ON THEIR OWN, the default mode identifies them token by token
# and does not care about order, case, or separators at all.
# Fields are LOCATED and cut out one at a time rather than splitting the name on
# separators: '.' and '-' are both separators AND part of the values we want
# (0.5400, -25c), so splitting first destroys exactly the tokens we are after.
# Cutting in order (level, process, voltage, temperature) also removes the
# ambiguity between them -- once 0p5000 is gone, no digits are left to confuse
# with a temperature.
#
# voltage: 0p5000 / 0.54 / v0p55 / 0p55v  (a decimal marker is REQUIRED, so a
# bare '125' can never be read as a voltage)
# A digit is REQUIRED before the decimal marker: without it a plain separator
# run like ".125." would read as the voltage 0.125.
_V_TOK_RE = re.compile(r"(?<!\d)v?(\d+)[p.](\d+)v?(?!\d)", re.IGNORECASE)
# temperature: 125 / 125c / m25 / m25c / -25 / n40
_T_TOK_RE = re.compile(r"(?<![\dA-Za-z])([mn]|-)?(\d+)c?(?![\dA-Za-z])", re.IGNORECASE)


def _word_re(word: str):
    """``word`` as a whole token (letters on either side would make it a
    different word: 'cmax' must not match inside 'rcmax')."""
    return re.compile(r"(?<![A-Za-z])" + re.escape(str(word)) + r"(?![A-Za-z])",
                      re.IGNORECASE)


def _cut(s: str, m) -> str:
    """Replace a matched span with a separator so it cannot match again."""
    return s[:m.start()] + "_" + s[m.end():]


def _tok_volt(tok: str) -> "float | None":
    m = _V_TOK_RE.search(tok)
    if not m:
        return None
    return float("%s.%s" % (m.group(1), m.group(2)))


def norm_temp(tok, hyphen_is_sep: bool = False) -> str:
    """Temperature token -> comparable form: lower case, no trailing ``c``,
    a leading minus written as ``m`` (so ``-25`` / ``m25`` / ``M25C`` all match
    the same ``data.temp``).

    ``hyphen_is_sep`` is set when the FILENAME uses '-' as a field separator
    (``sspg-0p5000-125c-rcmax``). There a leading '-' is punctuation, not a sign,
    and reading it as one would turn 125C into -125C and drop the file.
    """
    s = str(tok).strip().lower()
    s = re.sub(r"c$", "", s)
    s = re.sub(r"^-", "" if hyphen_is_sep else "m", s)
    s = re.sub(r"^n", "m", s)
    return s


# '-' next to a letter means it is being used as a separator, not as a minus sign
_HYPHEN_SEP_RE = re.compile(r"[A-Za-z]-|-[A-Za-z]")


def _match_tokens(fname: str, cfg: dict, levels: list, prefix: str, temp):
    """Identify (voltage, level) in a filename regardless of field order.

    Returns ``(volt, level_name)`` or None when the file is not one of ours or
    belongs to another temperature/process. ``temp``/``prefix`` act as filters
    only when a matching token is actually present.
    """
    s = fname
    # 1) level -- longest name first so 'rcmax' is not shadowed by 'cmax'
    lvl = None
    for n in sorted(levels, key=len, reverse=True):
        m = _word_re(n).search(s)
        if m:
            lvl, s = n, _cut(s, m)
            break
    if lvl is None:
        return None                               # not a level this model covers
    # 2) process token (a filter, and removing it keeps it out of the way)
    if prefix:
        m = _word_re(prefix).search(s)
        if m:
            s = _cut(s, m)
    # 3) voltage -- must carry a decimal marker
    m = _V_TOK_RE.search(s)
    if not m:
        return None
    volt = float("%s.%s" % (m.group(1), m.group(2)))
    s = _cut(s, m)
    # 4) temperature -- with the voltage gone, the remaining number is it
    if temp is not None:
        sep = bool(_HYPHEN_SEP_RE.search(fname))
        want = norm_temp(temp)
        if not any(norm_temp(t.group(0), sep) == want for t in _T_TOK_RE.finditer(s)):
            return None                           # another temperature, or none found
    return volt, lvl


def _canon_level(tok: str, names: list) -> "str | None":
    """Match a filename level token against the configured names, case-
    insensitively, returning the config's own spelling (labels stay canonical)."""
    for n in names:
        if n.lower() == tok.lower():
            return n
    return None


def _flat_scan(root: str, regex: str, cfg: dict, kind: str, exclude=None,
               contains=None) -> dict:
    assert os.path.isdir(root), f"missing {kind} dir: {root}"
    # The annotated scan recurses over the whole design folder, so a crosstalk
    # SUB-folder inside it would be scanned too and every corner would match
    # twice. Skip that subtree -- but only when it really is a sub-folder: a
    # deliverable that keeps both kinds in ONE directory (the pt_si_re layout,
    # <corner>/<corner>_fixed_annotated.txt next to <corner>.<...>.by_path.rpt)
    # would otherwise exclude the annotated directory from itself.
    skip = os.path.abspath(exclude) if exclude else None
    if skip and skip == os.path.abspath(root):
        skip = None
    # Filename filter for the one-directory case: the two kinds are then told
    # apart by a marker in the name rather than by directory.
    need = str(contains).lower() if contains else None
    prefix = cfg["data"].get("corner_prefix", "TT")
    temp = cfg["data"].get("temp")
    names = level_names(cfg)
    auto = regex is None or str(regex) == "auto"
    rx = None if auto else re.compile(regex, re.IGNORECASE)

    found: "dict[str, str]" = {}
    dupes: "list[tuple]" = []
    seen_any = False
    for dirpath, dirs, fns in os.walk(root):
        if skip and (os.path.abspath(dirpath) == skip
                     or os.path.abspath(dirpath).startswith(skip + os.sep)):
            dirs[:] = []
            continue
        for fn in sorted(fns):
            if need and need not in fn.lower():
                continue
            if auto:
                hit = _match_tokens(fn, cfg, names, prefix, temp)
                if hit is None:
                    continue
                seen_any = True
                volt, lv = hit
            else:
                m = rx.search(fn)
                if not m:
                    continue
                g = m.groupdict()
                if "v" not in g or "level" not in g:
                    raise ValueError(
                        f"patterns.{kind}_regex must define named groups (?P<v>...) "
                        f"and (?P<level>...); got {sorted(g)}")
                seen_any = True
                if g.get("proc") and g["proc"].upper() != str(prefix).upper():
                    continue
                if (temp is not None and g.get("temp") is not None
                        and norm_temp(g["temp"]) != norm_temp(temp)):
                    continue
                lv = _canon_level(g["level"], names)
                if lv is None:
                    continue                 # a level this model does not cover
                volt = _tok_volt(g["v"])
                if volt is None:
                    volt = volt_to_float(g["v"])
            lab = corner_label(volt, lv, prefix)
            fp = os.path.join(dirpath, fn)
            if lab in found and found[lab] != fp:
                dupes.append((lab, found[lab], fp))
            found[lab] = fp
    if dupes:
        lab, a, b = dupes[0]
        if os.path.dirname(a) == os.path.dirname(b):
            raise AssertionError(
                f"{kind}: corner {lab} matched two files in the same folder:\n  {a}\n  {b}\n"
                f"  This is a layout where annotated and crosstalk share one folder.\n"
                f"  Add the following to the config so they are told apart by name:\n"
                f"    files:\n"
                f"      annotated_contains: _fixed_annotated\n"
                f"      crosstalk_contains: by_path")
        raise AssertionError(
            f"{kind}: corner {lab} matched by more than one file:\n  {a}\n  {b}\n"
            f"filenames do not identify a corner uniquely. Narrow data.{kind}_dir to a\n"
            f"deeper directory, or state the exact format with patterns.{kind}_regex.")
    if not found:
        how = ("auto (token) mode" if auto else f"regex {regex!r}")
        raise AssertionError(
            f"no {kind} corners discovered under {root}\n"
            f"  discovery mode: {how} -- found {'nothing' if not seen_any else 'only part'} "
            f"in the filenames\n"
            f"  expected: somewhere in the filename, a voltage (0p5400 / 0.54),\n"
            f"        a level ({names}), and a temperature\n"
            f"        (data.temp={cfg['data'].get('temp')!r}) token\n"
            f"  (process prefix = {prefix!r})\n"
            f"  to see the actual filenames: bash scripts/run.sh recon")
    return found


# ------------------------------------------------------------- levels scanning
def _levels_scan_annotated(cfg: dict) -> dict:
    root = cfg["data"]["annotated_dir"]
    pats = _patterns(cfg)
    suffix = pats.get("annotated_suffix", "_fixed_annotated.txt")
    volt_re = re.compile(pats["voltage_regex"]) if pats.get("voltage_regex") else None
    prefix = cfg["data"].get("corner_prefix", "TT")
    out: "dict[str, str]" = {}
    for lv in level_names(cfg):
        d = os.path.join(root, lv)
        assert os.path.isdir(d), f"missing annotated level dir: {d}"
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(suffix):
                continue
            v = parse_voltage_from_annotated(fn, volt_re)
            if v is None:
                continue
            out[corner_label(v, lv, prefix)] = os.path.join(d, fn)
    assert out, (f"no corners discovered under {root} "
                 f"(temp={cfg['data'].get('temp')!r}) -- check patterns.voltage_regex "
                 f"/ patterns.annotated_suffix")
    return out


def _levels_scan_crosstalk(cfg: dict) -> dict:
    root = cfg["data"]["crosstalk_dir"]
    pats = _patterns(cfg)
    suffix = pats.get("crosstalk_suffix", ".by_path.rpt")
    prefix = cfg["data"].get("corner_prefix", "TT")
    temp = str(cfg["data"]["temp"])
    out: "dict[str, str]" = {}
    for lv in level_names(cfg):
        d = os.path.join(root, lv)
        assert os.path.isdir(d), f"missing crosstalk level dir: {d}"
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(suffix):
                continue
            pv = parse_xt_name(fn, prefix)
            if pv is None:
                continue
            v, tk = pv
            if tk != temp:
                continue
            out[corner_label(v, lv, prefix)] = os.path.join(d, fn)
    return out


# ----------------------------------------------------------------- public API
def discover_annotated(cfg: dict) -> dict:
    """{corner_label: annotated report path}."""
    if layout(cfg) == "flat":
        rx = _patterns(cfg).get("annotated_regex")     # None/"auto" -> token mode
        return _flat_scan(cfg["data"]["annotated_dir"], rx, cfg, "annotated",
                          exclude=cfg["data"].get("crosstalk_dir"),
                          contains=_patterns(cfg).get("annotated_contains"))
    return _levels_scan_annotated(cfg)


def discover_crosstalk(cfg: dict) -> "dict | None":
    """{corner_label: crosstalk report path}, or None when the config declares
    no ``data.crosstalk_dir`` (SI-free build -- base + attention only)."""
    if not cfg["data"].get("crosstalk_dir"):
        return None
    if layout(cfg) == "flat":
        rx = _patterns(cfg).get("crosstalk_regex")     # None/"auto" -> token mode
        return _flat_scan(cfg["data"]["crosstalk_dir"], rx, cfg, "crosstalk",
                          contains=_patterns(cfg).get("crosstalk_contains"))
    return _levels_scan_crosstalk(cfg)


def discover(cfg: dict, need_crosstalk: bool = True):
    """Return ``(corners, ann_by_corner, xt_by_corner_or_None)``.

    ``corners`` are canonical labels sorted by (voltage, level value). When
    crosstalk is present, integrity invariant **I1** is enforced: annotation and
    crosstalk must cover exactly the same corner set.
    """
    ann_by = discover_annotated(cfg)
    xt_by = discover_crosstalk(cfg) if need_crosstalk else None
    if xt_by is not None:
        only_a, only_x = set(ann_by) - set(xt_by), set(xt_by) - set(ann_by)
        assert not only_a and not only_x, \
            f"I1: corner sets differ: only-ann={sorted(only_a)} only-xt={sorted(only_x)}"
    levels = corner_levels(cfg)
    prefix = cfg["data"].get("corner_prefix", "TT")
    corners = sorted(ann_by, key=lambda c: parse_corner(c, levels, prefix))
    return corners, ann_by, xt_by
