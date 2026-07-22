#!/usr/bin/env python3
"""Shared library for the PT fixed-path annotation pipeline.

Contents (extracted verbatim from the original working scripts, so results
are bit-identical to the internal pipeline):
  - PT report parsing            (parse_report, count_na)
  - Dist/Res annotation cache    (extract_dist_res_cache, lookup_dist_res,
                                  apply_fast_annotation)
  - pt_shell launcher            (run_pt)
  - ref-report -> FIXED_PATHS    (parse_ref_report_blocks,
                                  extract_data_pin_chain, sample_through_pins,
                                  write_fixed_tcl_from_ref_report)

Environment:
  PT_SOURCE  optional path to a shell file that puts pt_shell on PATH
             (e.g. a site-specific prime.bashrc). If unset, pt_shell must
             already be on PATH.
  LC_ROOT    optional Library Compiler install root to prepend to PATH.
"""
from datetime import datetime
from pathlib import Path
import os
import re
import subprocess
from typing import Optional

import res

# ---------------------------------------------------------------- regexes
PIN_PATTERN = re.compile(r'^\s*(\S+)/([^/\s]+)\s+\(([^)]+)\)')
PORT_PATTERN = re.compile(r'^\s*(\S+)\s+\((in|out)\)\s+', flags=re.IGNORECASE)
NET_PATTERN = re.compile(r'^\s*(\S+)\s+\(net\)')
NET_ROW_RE = re.compile(r'^(?P<prefix>.*\(net\)\s+\d+\s+[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$')

STARTPOINT_RE = re.compile(r'^\s*Startpoint:\s*(\S+)')
ENDPOINT_RE = re.compile(r'^\s*Endpoint:\s*(\S+)')
PIN_RE = re.compile(r'^\s*(\S+/\S+)\s+\(([^)]+)\)')


def now():
    return datetime.now().isoformat(timespec='seconds')


def count_na(path: Path):
    na_tokens = 0
    na_lines = 0
    with path.open(errors='ignore') as f:
        for line in f:
            c = line.count('N/A')
            na_tokens += c
            if c:
                na_lines += 1
    return na_tokens, na_lines


# ------------------------------------------------- report parsing / cache
def parse_report(report_path: Path):
    with report_path.open('r', encoding='utf-8', errors='ignore') as f:
        report_lines = f.readlines()

    queries = []
    last_seen_inst = None
    last_seen_pin = None
    pending_net = None
    net_idx = -1
    header_len = 80

    for i, line in enumerate(report_lines):
        if 'Point' in line and 'Fanout' in line and 'Path' in line:
            header_len = len(line.rstrip('\n\r'))

        m_net = NET_PATTERN.match(line)
        if m_net:
            pending_net = m_net.group(1)
            net_idx = i
            continue

        m_pin = PIN_PATTERN.match(line)
        if m_pin:
            inst = m_pin.group(1)
            pin = m_pin.group(2)
            cell = m_pin.group(3)
            if pending_net and last_seen_inst:
                queries.append({
                    'net': pending_net,
                    'drvr_inst': last_seen_inst,
                    'drvr_pin': last_seen_pin,
                    'recv_inst': inst,
                    'recv_pin': pin,
                    'recv_cell': cell,
                    'net_idx': net_idx,
                })
                pending_net = None
            last_seen_inst = inst
            last_seen_pin = pin
            continue

        m_port = PORT_PATTERN.match(line)
        if m_port:
            port = m_port.group(1)
            if pending_net and last_seen_inst:
                queries.append({
                    'net': pending_net,
                    'drvr_inst': last_seen_inst,
                    'drvr_pin': last_seen_pin,
                    'recv_inst': port,
                    'recv_pin': '__PORT__',
                    'recv_cell': None,
                    'net_idx': net_idx,
                })
                pending_net = None
            last_seen_inst = port
            last_seen_pin = '__PORT__'

    return report_lines, queries, header_len


def query_key(q):
    return (q['net'], q['drvr_inst'], q['drvr_pin'], q['recv_inst'], q['recv_pin'])


def endpoint_key(q):
    return (q['drvr_inst'], q['drvr_pin'], q['recv_inst'], q['recv_pin'])


def extract_dist_res_cache(annotated_path: Path):
    lines, queries, _ = parse_report(annotated_path)
    cache = {}
    for q in queries:
        toks = lines[q['net_idx']].split()
        if len(toks) < 3:
            continue
        try:
            dist = None if toks[-3] == 'N/A' else float(toks[-3])
            rpath = None if toks[-2] == 'N/A' else float(toks[-2])
        except ValueError:
            continue
        if dist is None or rpath is None:
            continue
        cache[query_key(q)] = (dist, rpath)
        cache.setdefault(endpoint_key(q), (dist, rpath))
    return cache


def lookup_dist_res(dist_res_cache, q):
    pair = dist_res_cache.get(query_key(q))
    if pair is not None:
        return pair
    return dist_res_cache.get(endpoint_key(q), (None, None))


def apply_fast_annotation(report_path: Path, output_path: Path, dist_res_cache, lib_path: Optional[Path]):
    report_lines, queries, header_len = parse_report(report_path)
    lib_pin_caps = res.load_lib_pin_caps(str(lib_path)) if lib_path and lib_path.exists() else {}
    q_by_idx = {q['net_idx']: q for q in queries}

    for idx, line in enumerate(report_lines):
        clean_line = line.rstrip('\n\r')
        if 'Point' in line and 'Fanout' in line and 'Path' in line:
            report_lines[idx] = clean_line + '       Dist        Res       Cpin\n'
            continue
        if set(line.strip()) == {'-'}:
            report_lines[idx] = clean_line + '---------------------------------\n'
            continue
        if '(net)' not in clean_line:
            continue

        q = q_by_idx.get(idx)
        if q is None:
            continue
        dist, rpath = lookup_dist_res(dist_res_cache, q)
        cpin = None
        recv_cell = q.get('recv_cell')
        recv_pin = q.get('recv_pin')
        if recv_cell and recv_pin and recv_pin != '__PORT__':
            cpin = lib_pin_caps.get(recv_cell, {}).get(recv_pin)

        str_dist = f'{dist:.4f}' if dist is not None else 'N/A'
        str_rpath = f'{rpath:.4f}' if rpath is not None else 'N/A'
        str_cpin = f'{cpin:.4f}' if cpin is not None else 'N/A'

        m_net = NET_ROW_RE.match(clean_line)
        if m_net:
            prefix = m_net.group('prefix')
            report_lines[idx] = (
                f'{prefix}'
                f" {'':>10} {'':>10} {'':>10}"
                f' {str_dist:>10} {str_rpath:>10} {str_cpin:>10}\n'
            )
        else:
            padded_line = clean_line.ljust(header_len)
            report_lines[idx] = padded_line + f' {str_dist:>10} {str_rpath:>10} {str_cpin:>10}\n'

    with output_path.open('w', encoding='utf-8') as f:
        f.writelines(report_lines)


# ------------------------------------------------------------ pt launcher
def run_pt(tcl: Path, env_updates: dict, log_path: Path):
    """Run pt_shell -f <tcl> with env_updates exported.

    pt_shell discovery order:
      1. already on PATH
      2. source $PT_SOURCE (site-specific setup script), if set
    """
    exports = []
    for k, v in env_updates.items():
        exports.append(f'export {k}={subprocess.list2cmdline([str(v)])}')
    pt_source = os.environ.get('PT_SOURCE', '')
    lc_root = os.environ.get('LC_ROOT', '')
    script = """
set -euo pipefail
if ! command -v pt_shell >/dev/null 2>&1; then
  if [ -n "{pt_source}" ] && [ -f "{pt_source}" ]; then
    set +u
    source "{pt_source}"
    set -u
  else
    echo "ERROR: pt_shell not found in PATH; set PT_SOURCE to a setup script that provides it" >&2
    exit 127
  fi
fi
if [ -n "{lc_root}" ] && [ -d "{lc_root}/bin" ]; then
  export SYNOPSYS_LC_ROOT="{lc_root}"
  export PATH="{lc_root}/bin:$PATH"
fi
{exports}
pt_shell -f {tcl}
""".format(pt_source=pt_source, lc_root=lc_root,
           exports='\n'.join(exports), tcl=subprocess.list2cmdline([str(tcl)]))
    with log_path.open('a', encoding='utf-8') as lf:
        lf.write(f'\n[{now()}] RUN {tcl.name}\n')
        proc = subprocess.run(['bash', '-lc', script], stdout=lf, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(f'pt_shell failed for {tcl} with code {proc.returncode}')


# ------------------------------------- ref report -> FIXED_PATHS tcl
def parse_ref_report_blocks(report_path: Path):
    blocks = []
    cur = None
    with report_path.open('r', encoding='utf-8', errors='ignore') as f:
        for raw in f:
            line = raw.rstrip('\n')
            m_start = STARTPOINT_RE.match(line)
            if m_start:
                if cur is not None and cur.get('endpoint'):
                    blocks.append(cur)
                cur = {
                    'startpoint': m_start.group(1),
                    'endpoint': None,
                    'lines': [],
                }
                continue
            if cur is None:
                continue
            m_end = ENDPOINT_RE.match(line)
            if m_end and cur.get('endpoint') is None:
                cur['endpoint'] = m_end.group(1)
                continue
            cur['lines'].append(line)
    if cur is not None and cur.get('endpoint'):
        blocks.append(cur)
    return blocks


def extract_data_pin_chain(block):
    start_inst = block['startpoint']
    end_inst = block['endpoint']
    pins = []
    collecting = False

    for line in block['lines']:
        s = line.strip().lower()
        if s.startswith('data arrival time'):
            break
        m_pin = PIN_RE.match(line)
        if not m_pin:
            continue
        pin = m_pin.group(1)
        cell = m_pin.group(2).lower()
        if cell == 'net':
            continue
        if not collecting:
            if pin == f'{start_inst}/Q' or pin == f'{start_inst}/QN':
                pins.append(pin)
                collecting = True
            continue
        pins.append(pin)
        if pin == f'{end_inst}/D':
            break

    if len(pins) >= 2 and pins[-1] == f'{end_inst}/D':
        return pins
    return []


def sample_through_pins(pins, n_through: int):
    internal = pins[1:-1]
    if not internal or n_through <= 0:
        return []
    n = min(n_through, len(internal))
    sampled = []
    for k in range(n):
        idx = int((k + 1) * len(internal) / (n + 1))
        sampled.append(internal[idx])
    deduped = []
    seen = set()
    for pin in sampled:
        if pin in seen:
            continue
        seen.add(pin)
        deduped.append(pin)
    return deduped


def write_fixed_tcl_from_ref_report(report_path: Path, output_path: Path, n_through: int, limit: int):
    blocks = parse_ref_report_blocks(report_path)
    emitted = 0
    skipped = 0
    with output_path.open('w', encoding='utf-8') as f:
        f.write('# Auto-generated fixed paths (from ref report)\n')
        f.write('set FIXED_PATHS {\n')
        for idx, block in enumerate(blocks, start=1):
            pins = extract_data_pin_chain(block)
            if len(pins) < 2:
                skipped += 1
                continue
            from_pin = pins[0]
            to_pin = pins[-1]
            through_pins = sample_through_pins(pins, n_through)
            path_key = '{}->{}#{}'.format(block['startpoint'], block['endpoint'], idx)
            thr_list = ' '.join('{{{}}}'.format(pin) for pin in through_pins)
            f.write('  {{{{{}}} {{{}}} {{{}}} {{{}}}}}\n'.format(path_key, from_pin, to_pin, thr_list))
            emitted += 1
            if limit and emitted >= limit:
                break
        f.write('}\n\n')
        f.write('# each entry: {path_key {from_pin} {to_pin} { {through1} {through2} ... }}\n')
    return emitted, skipped, len(blocks)
