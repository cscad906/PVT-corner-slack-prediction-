# -*- coding: utf-8 -*-
import argparse
from difflib import SequenceMatcher
import sys as _sys
import time as _time
import fnmatch
import glob
import os
import re
from functools import lru_cache

import heapq


# ---- 최단경로 (SPEF 저항 그물에서 드라이버->리시버 저항 합) --------------
# 예전에는 networkx 를 썼는데, 이 파이프라인에서 쓰는 기능이 "가중치 최단경로 길이"
# 하나뿐이라 직접 넣었다. 외부 패키지가 없어도 돌아가야 현장에서 안전하다
# (PrimeTime 번들 python3 에는 networkx 가 있지만 python2.7 에는 없다).
class _Graph(object):
    """무방향 가중 그래프. 저항값을 가중치로 쓴다."""

    def __init__(self):
        self.adj = {}

    def add_edge(self, a, b, weight=0.0):
        # 같은 두 노드 사이에 여러 저항이 있으면 작은 쪽을 남긴다(병렬 경로).
        for x, y in ((a, b), (b, a)):
            d = self.adj.setdefault(x, {})
            if y not in d or weight < d[y]:
                d[y] = weight

    def nodes(self):
        return self.adj.keys()

    def shortest_path_length(self, source, target):
        """source -> target 최단 가중치 합. 길이 없으면 None.

        노드 수가 넷 하나 분량(수십~수백)이라 단순 다익스트라로 충분하다.
        """
        if source not in self.adj or target not in self.adj:
            return None
        if source == target:
            return 0.0
        dist = {source: 0.0}
        heap = [(0.0, source)]
        seen = set()
        while heap:
            d, u = heapq.heappop(heap)
            if u in seen:
                continue
            seen.add(u)
            if u == target:
                return d
            for v, w in self.adj[u].items():
                nd = d + w
                if v not in dist or nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))
        return None


def _fmt_value(v, nd=4):
    """소수점 표기를 유지하며 값을 문자열로 (지수 표기 없음).

    기존 산출물과 **형식이 같아야 하므로** 소수점 4자리 고정이다.
    단위: Dist = um, Res = ohm, Cpin = pF.
    더 정밀한 값이 필요하면 2b_distres.py 가 만드는 distres.tsv 를 쓴다
    (거기에는 반올림 전 값이 남아 있다).
    """
    if v is None:
        return "N/A"
    # 기존 산출물과 형식을 맞춘다: 소수점 4자리 고정, 뒤쪽 0 을 떼지 않는다.
    try:
        return "%.*f" % (nd, float(v))
    except (TypeError, ValueError):
        return str(v)


def _dedup_keep_order(seq):
    """중복을 없애되 **순서를 보존**한다.

    예전에는 list(dict.fromkeys(...)) 를 썼는데, python3.7+ 는 dict 가 입력 순서를
    지켜 의도대로 동작하지만 python2.7 은 지키지 않는다. 그러면 어떤 후보를 먼저
    시도할지가 달라져, 계층 이름(a/b/c)처럼 후보가 여러 개인 넷에서 매칭 결과가
    갈린다(실제로 2.7 에서 159줄이 다르게 나왔다).
    """
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


@lru_cache(maxsize=1 << 20)
def normalize_name_token(name):
    """SPEF 는 대괄호를 이스케이프하고 PT 리포트는 안 하므로 맞춰 준다.

    캐시가 있는 이유: 이름으로 못 찾은 넷을 연결(CONN)로 찾는 구간에서
    이 함수가 1억 5천만 번 불린다. 그런데 실제로 서로 다른 이름은 수십만
    개뿐이라, 같은 문자열을 몇백 번씩 다시 바꾸고 있었다(str.replace 만
    3억 회). 캐시 하나로 그 반복이 사라진다.
    """
    return name.replace(r'\[', '[').replace(r'\]', ']')

@lru_cache(maxsize=None)
def load_lib_pin_caps(lib_path):
    cell_to_pin_caps = {}
    current_cell = None
    current_pin = None
    cell_depth = 0
    pin_depth = 0

    cell_re = re.compile(r'^\s*cell\s*\(\s*([^\s)]+)\s*\)\s*\{')
    pin_re = re.compile(r'^\s*pin\s*\(\s*([^\s)]+)\s*\)\s*\{')
    cap_re = re.compile(r'^\s*capacitance\s*:\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*;')
    dir_re = re.compile(r'^\s*direction\s*:\s*(input|output|inout)\s*;')

    with open(lib_path, 'r', encoding='utf-8', errors='ignore') as f:
        for raw in f:
            line = raw.rstrip('\n')
            opens = line.count('{')
            closes = line.count('}')

            m_cell = cell_re.match(line)
            if m_cell:
                current_cell = m_cell.group(1)
                cell_to_pin_caps.setdefault(current_cell, {})
                current_pin = None
                cell_depth = max(1, opens - closes)
                pin_depth = 0
                continue

            if current_cell is None:
                continue

            m_pin = pin_re.match(line)
            if m_pin:
                current_pin = m_pin.group(1)
                cell_to_pin_caps[current_cell].setdefault(current_pin, {"cap": None, "dir": None})
                pin_depth = max(1, opens - closes)
                cell_depth += opens - closes
                continue

            if current_pin is not None:
                m_dir = dir_re.match(line)
                if m_dir:
                    cell_to_pin_caps[current_cell][current_pin]["dir"] = m_dir.group(1)

                m_cap = cap_re.match(line)
                if m_cap:
                    try:
                        cell_to_pin_caps[current_cell][current_pin]["cap"] = float(m_cap.group(1))
                    except ValueError:
                        pass

            if current_pin is not None:
                pin_depth += opens - closes
                if pin_depth <= 0:
                    current_pin = None
                    pin_depth = 0

            cell_depth += opens - closes
            if cell_depth <= 0:
                current_cell = None
                current_pin = None
                cell_depth = 0
                pin_depth = 0

    result = {}
    for cell, pins in cell_to_pin_caps.items():
        result[cell] = {}
        for pin, attrs in pins.items():
            if attrs["dir"] in ("input", "inout") and attrs["cap"] is not None:
                result[cell][pin] = attrs["cap"]
    return result


class Tick(object):
    """긴 루프가 도는 동안 살아 있다는 것을 보여 준다.

    2b 는 1GB SPEF 를 여섯 번까지 훑는데, 그 사이 화면에 아무것도 안 나온다.
    몇십 분을 보고도 도는 중인지 멈춘 건지 알 수가 없어서, 잘못된 SPEF 로
    한참을 기다린 뒤에야 알게 된다.

    줄마다 시계를 보면 그것대로 비싸므로, 2만 줄에 한 번만 본다. 실제로
    찍는 것은 3초에 한 번이다. 화면이 넘치지 않으면서 멈춤은 바로 보인다.

    화면에 나가는 문장은 영어로 쓴다(현장 터미널이 한글을 깨뜨린다).
    """

    EVERY = 20000
    SECS = 3.0

    def __init__(self, label, total_bytes=None):
        self.label = label
        self.total = total_bytes
        self.n = 0
        self.t0 = _time.time()
        self.last = self.t0

    def __call__(self, fh=None):
        self.n += 1
        if self.n % self.EVERY:
            return
        now = _time.time()
        if now - self.last < self.SECS:
            return
        self.last = now
        el = now - self.t0
        where = ""
        if fh is not None and self.total:
            try:
                pos = fh.tell()
                where = "  %3d%%" % min(100, int(100.0 * pos / self.total))
            except (IOError, OSError, ValueError):
                where = ""
        print("      %s%s   %d lines, %.0fs" % (self.label, where, self.n, el))
        _sys.stdout.flush()

    def done(self):
        print("      %s   done in %.0fs (%d lines)"
              % (self.label, _time.time() - self.t0, self.n))
        _sys.stdout.flush()


def annotate_timing_report(report_path, spef_path, output_path, lib_path=None,
                           pin_cap_map=None):
    """타이밍 리포트의 (net) 줄에 Dist/Res/Cpin 을 붙인다.

    Cpin 출처는 세 가지이며 이 순서로 시도한다:
      ① pin_cap_map  -- PT `report_attribute [get_pins *]` 의 pin_capacitance_max.
                        키는 설계 핀 이름 'inst/pin'. Liberty 를 받을 수 없는
                        사이트에서 쓰는 경로이며, 단위가 리포트의 Cap 과 같다.
      ② lib_path     -- Liberty 의 cell/pin capacitance (기존 방식)
      ③ SPEF *CONN 의 *L -- 두 경로가 모두 실패했을 때. SPEF 에 따라 없을 수 있다.
    """
    # 이름 fuzzy 검색 예산. [남은 횟수, 건너뛴 횟수]
    # 넷 하나마다 NAME_MAP 전체를 훑는 경로라, 이름이 크게 어긋난 SPEF 에서
    # 이것 하나로 몇 시간이 간다. 정상 리포트는 이 한도에 안 닿는다.
    _fuzzy_budget = [200, 0]

    print("1. reading the timing report for target nets and driver/receiver pins ...")
    _sys.stdout.flush()
    try:
        _spef_size = os.path.getsize(spef_path)
    except OSError:
        _spef_size = None

    with open(report_path, 'r') as f:
        report_lines = f.readlines()

    queries = []
    lib_pin_caps = load_lib_pin_caps(lib_path) if lib_path else {}
    pin_cap_map = pin_cap_map or {}
    
    # 드라이버/리시버 파싱을 위한 변수
    last_seen_inst = None
    last_seen_pin = None
    last_seen_cell = None
    pending_net = None
    net_idx = -1

    # 정규표현식
    pin_pattern = re.compile(r'^\s*(\S+)/([^/\s]+)\s+\(([^)]+)\)')
    port_pattern = re.compile(r'^\s*(\S+)\s+\((in|out)\)\s+', flags=re.IGNORECASE)
    net_pattern = re.compile(r'^\s*(\S+)\s+\(net\)')
    
    # 표 정렬을 위한 기준 길이
    header_len = 80 

    for i, line in enumerate(report_lines):
        # [표 양식 수정] 헤더 및 점선 연장
        if "Point" in line and "Fanout" in line and "Path" in line:
            header_len = len(line.rstrip('\n\r'))
            report_lines[i] = line.rstrip('\n\r') + "       Dist        Res       Cpin\n"
            continue
        elif set(line.strip()) == {'-'}: # 점선(---)으로만 이루어진 줄
            report_lines[i] = line.rstrip('\n\r') + "---------------------------------\n"
            continue

        # [경로 파싱] 1. 넷(Net) 라인 확인
        # net 이름에 '/'가 포함되면 pin 정규식에도 걸릴 수 있으므로 net을 우선 처리
        m_net = net_pattern.match(line)
        if m_net:
            pending_net = m_net.group(1)
            net_idx = i
            continue

        # [경로 파싱] 2. 핀(Pin) 라인 확인
        m_pin = pin_pattern.match(line)
        if m_pin:
            inst = m_pin.group(1)
            pin = m_pin.group(2)
            cell = m_pin.group(3)
            
            # 이전에 발견한 넷(net)이 있다면, 지금 발견한 핀은 Receiver입니다.
            if pending_net and last_seen_inst:
                queries.append({
                    'net': pending_net,
                    'drvr_inst': last_seen_inst,
                    'drvr_pin': last_seen_pin,
                    'recv_inst': inst,
                    'recv_pin': pin,
                    'recv_cell': cell,
                    'net_idx': net_idx
                })
                pending_net = None # 넷 1개 처리 완료
                
            # 현재 핀을 기억 (다음 넷의 Driver가 될 수 있음)
            last_seen_inst = inst
            last_seen_pin = pin
            last_seen_cell = cell
            continue

        # [경로 파싱] 3. 포트(Port) 라인 확인: ex) clk_i (in)
        # clock/event line(예: clock myCLK (rise edge))은 제외
        m_port = port_pattern.match(line)
        if m_port:
            port = m_port.group(1)
            if pending_net and last_seen_inst:
                queries.append({
                    'net': pending_net,
                    'drvr_inst': last_seen_inst,
                    'drvr_pin': last_seen_pin,
                    'recv_inst': port,
                    'recv_pin': "__PORT__",
                    'recv_cell': None,
                    'net_idx': net_idx
                })
                pending_net = None
            last_seen_inst = port
            last_seen_pin = "__PORT__"
            last_seen_cell = None

    print(f"-> 총 {len(queries)}개의 넷 연결(Edge) 경로를 찾았습니다.")

    # ---------------------------------------------------------
    print("2. reading the SPEF *NAME_MAP ...")
    _sys.stdout.flush()
    _tk = Tick("2. NAME_MAP", _spef_size)
    name_to_ids = {}
    norm_name_to_ids = {}
    leaf_to_ids = {}
    norm_leaf_to_ids = {}
    id_to_name = {}
    name_entries = []
    with open(spef_path, 'r') as f:
        in_name_map = False
        for line in f:
            _tk(f)
            line = line.strip()
            is_star = line[:1] == '*'
            if is_star and line.startswith('*NAME_MAP'):
                in_name_map = True
                continue
            if in_name_map:
                if is_star:
                    parts = line.split()
                    if len(parts) >= 2:
                        spef_id = parts[0]
                        full_name = parts[1]
                        name_entries.append((spef_id, full_name))
                        id_to_name[spef_id] = full_name
                        if full_name not in name_to_ids:
                            name_to_ids[full_name] = []
                        name_to_ids[full_name].append(spef_id)
                        norm_full_name = normalize_name_token(full_name)
                        if norm_full_name not in norm_name_to_ids:
                            norm_name_to_ids[norm_full_name] = []
                        norm_name_to_ids[norm_full_name].append(spef_id)
                        leaf = normalize_name_token(full_name.split('/')[-1])
                        if leaf not in leaf_to_ids:
                            leaf_to_ids[leaf] = []
                        leaf_to_ids[leaf].append(spef_id)
                        norm_leaf_to_ids.setdefault(leaf, []).append(spef_id)
                else:
                    break

    _tk.done()
    print("2-1. reading port-to-D_NET aliases ...")
    _sys.stdout.flush()
    _tk = Tick("2-1. port alias", _spef_size)
    port_id_to_dnet_ids = {}
    with open(spef_path, 'r') as f:
        current_dnet = None
        for raw in f:
            _tk(f)
            line = raw.strip()
            if not line:
                continue
            if line[0] != '*':          # 값 줄이 대부분이다. 먼저 걸러낸다
                continue
            if line.startswith('*D_NET'):
                parts = line.split()
                current_dnet = parts[1] if len(parts) >= 2 else None
                continue
            if current_dnet is None:
                continue
            if line.startswith('*END'):
                current_dnet = None
                continue
            if line.startswith('*P '):
                parts = line.split()
                if len(parts) >= 2:
                    port_id = parts[1]
                    port_id_to_dnet_ids.setdefault(port_id, []).append(current_dnet)

    spef_id_cache = {}

    def get_spef_ids(name):
        if name in spef_id_cache:
            return spef_id_cache[name]

        def bus_flatten_variants(raw_name):
            variants = []
            norm_raw = normalize_name_token(raw_name)
            m_bus = re.match(r'^(.*?)/([^/\[]+)\[(\d+)\]$', norm_raw)
            if not m_bus:
                return variants

            prefix, leaf_base, bit_idx = m_bus.groups()
            parts = prefix.split('/') if prefix else []

            if prefix:
                variants.append(f"{prefix}_{leaf_base}_{bit_idx}_")
            if parts:
                variants.append(parts[0] + '/_' + '_'.join(parts[1:] + [leaf_base, bit_idx, '']))
            for split_idx in range(1, len(parts) + 1):
                prefix_parts = parts[:split_idx]
                suffix_parts = parts[split_idx:]
                if not prefix_parts:
                    continue
                variants.append('/'.join(prefix_parts + ['_' + '_'.join(suffix_parts + [leaf_base, bit_idx, ''])]))
            variants.append('_' + '_'.join(parts + [leaf_base, bit_idx, '']))
            return _dedup_keep_order(v for v in variants if v)

        ids = []
        norm_name = normalize_name_token(name)
        if name in name_to_ids:
            ids.extend(name_to_ids[name])
        if not ids:
            if norm_name in norm_name_to_ids:
                ids.extend(norm_name_to_ids[norm_name])
        if not ids and "/" in name:
            for variant in bus_flatten_variants(name):
                if variant in name_to_ids:
                    ids.extend(name_to_ids[variant])
                norm_variant = normalize_name_token(variant)
                if norm_variant in norm_name_to_ids:
                    ids.extend(norm_name_to_ids[norm_variant])

            parts = name.split("/")
            # Some SPEFs flatten the tail hierarchy into a single underscore-joined token.
            # Example:
            #   report: a/b/c/d
            #   spef  : a/b/_c_d
            for split_idx in range(1, len(parts) - 1):
                prefix = parts[:split_idx]
                suffix = parts[split_idx:]
                variant = "/".join(prefix + ["_" + "_".join(suffix)])
                if variant in name_to_ids:
                    ids.extend(name_to_ids[variant])
            # Also try fully flattened suffix under the first hierarchy element.
            if len(parts) >= 2:
                variant = parts[0] + "/_" + "_".join(parts[1:])
                if variant in name_to_ids:
                    ids.extend(name_to_ids[variant])
                # Some top-level nets are fully flattened with a leading underscore.
                variant = "_" + "_".join(parts)
                if variant in name_to_ids:
                    ids.extend(name_to_ids[variant])
            # Some SPEFs drop one middle hierarchy segment and flatten only the
            # last two report segments under the remaining prefix.
            # Example:
            #   report: a/b/c/d/e
            #   spef  : a/b/c/_d_e
            if len(parts) >= 4:
                variant = "/".join(parts[:-3] + ["_" + "_".join(parts[-2:])])
                if variant in name_to_ids:
                    ids.extend(name_to_ids[variant])
        if not ids:
            norm_name = normalize_name_token(name)
            for variant in bus_flatten_variants(norm_name):
                if variant in name_to_ids:
                    ids.extend(name_to_ids[variant])
                norm_variant = normalize_name_token(variant)
                if norm_variant in norm_name_to_ids:
                    ids.extend(norm_name_to_ids[norm_variant])
            if norm_name in norm_name_to_ids:
                ids.extend(norm_name_to_ids[norm_name])
            elif "/" in norm_name:
                parts = norm_name.split("/")
                for split_idx in range(1, len(parts) - 1):
                    prefix = parts[:split_idx]
                    suffix = parts[split_idx:]
                    variant = "/".join(prefix + ["_" + "_".join(suffix)])
                    if variant in name_to_ids:
                        ids.extend(name_to_ids[variant])
                    norm_variant = normalize_name_token(variant)
                    if norm_variant in norm_name_to_ids:
                        ids.extend(norm_name_to_ids[norm_variant])
                if len(parts) >= 2:
                    variant = parts[0] + "/_" + "_".join(parts[1:])
                    if variant in name_to_ids:
                        ids.extend(name_to_ids[variant])
                    norm_variant = normalize_name_token(variant)
                    if norm_variant in norm_name_to_ids:
                        ids.extend(norm_name_to_ids[norm_variant])
                    variant = "_" + "_".join(parts)
                    if variant in name_to_ids:
                        ids.extend(name_to_ids[variant])
                    norm_variant = normalize_name_token(variant)
                    if norm_variant in norm_name_to_ids:
                        ids.extend(norm_name_to_ids[norm_variant])
                if len(parts) >= 4:
                    variant = "/".join(parts[:-3] + ["_" + "_".join(parts[-2:])])
                    if variant in name_to_ids:
                        ids.extend(name_to_ids[variant])
                    norm_variant = normalize_name_token(variant)
                    if norm_variant in norm_name_to_ids:
                        ids.extend(norm_name_to_ids[norm_variant])
        # Top-level ports often appear as *NAME_MAP IDs, but their parasitics live on
        # a different *D_NET ID referenced from a *P entry inside the D_NET block.
        if ids:
            extra_dnets = []
            for spef_id in ids:
                extra_dnets.extend(port_id_to_dnet_ids.get(spef_id, []))
            ids.extend(extra_dnets)
        if '/' not in name and norm_name in norm_leaf_to_ids:
            ids.extend(norm_leaf_to_ids[norm_name])
        # Final fallback: after all structured matching fails, try only the trailing
        # leaf token from the report name and pick the best full-name candidate.
        if not ids and '/' in norm_name:
            leaf = norm_name.split('/')[-1]
            leaf_ids = norm_leaf_to_ids.get(leaf, [])
            if leaf_ids:
                scored = []
                for spef_id in leaf_ids:
                    full = normalize_name_token(id_to_name.get(spef_id, spef_id))
                    score = SequenceMatcher(None, norm_name, full).ratio()
                    scored.append((score, spef_id))
                scored.sort(reverse=True)
                best_score, best_id = scored[0]
                if len(scored) == 1 or best_score > 0.55:
                    ids.append(best_id)
        # Last resort: fuzzy name-map search. We only reach here after all exact,
        # normalized, flattened, and leaf-based rules failed. Return a small set
        # of high-similarity candidates and let later pin-resolution discard
        # mismatches.
        # 여기는 넷 하나마다 NAME_MAP 전체(수십만)를 훑는다. 이름이 잘 맞는
        # 리포트에서는 몇 번 안 오지만, SPEF 가 어긋나면 못 찾은 넷 전부가
        # 여기로 몰려 시간이 제곱으로 간다. 실측에서 22분에 2% 였다.
        #
        # 그런데 건지는 양이 거의 없다. 같은 실행에서 이 계열 fallback 이
        # 3952개를 훑어 6개(0.15%)를 건졌다. 몇 시간을 더 써도 결과는
        # 사실상 같고, 어차피 E-RES0 로 끝난다.
        #
        # 그래서 횟수를 제한한다. 정상적인 리포트는 이 한도에 닿지 않는다.
        # 닿았다면 그것 자체가 "SPEF 가 이 리포트 것이 아니다" 라는 신호이고,
        # 그 사실을 몇 시간 뒤가 아니라 지금 알려 주는 편이 낫다.
        if not ids and _fuzzy_budget[0] <= 0:
            _fuzzy_budget[1] += 1        # 건너뛴 횟수. 끝에 알린다
        elif not ids:
            _fuzzy_budget[0] -= 1
            leaf = norm_name.split('/')[-1]
            fuzzy = []
            for spef_id, full_name in name_entries:
                norm_full = normalize_name_token(full_name)
                norm_leaf = norm_full.split('/')[-1]
                if leaf not in norm_leaf and leaf not in norm_full:
                    continue
                score = SequenceMatcher(None, norm_name, norm_full).ratio()
                if norm_leaf.endswith(leaf):
                    score += 0.15
                elif leaf in norm_leaf:
                    score += 0.08
                if score >= 0.55:
                    fuzzy.append((score, spef_id))
            fuzzy.sort(reverse=True)
            ids.extend([spef_id for _, spef_id in fuzzy[:5]])
        if not ids:
            result = [name]
        else:
            result = _dedup_keep_order(ids)
        spef_id_cache[name] = result
        return result

    def short_leaf(name):
        return normalize_name_token(name.split('/')[-1])

    def second_pass_exact_conn_match(line_idx_to_query, spef_path, current_results):
        pending = {idx: q for idx, q in line_idx_to_query.items() if current_results.get(idx, (None, None, None))[0] is None}
        if not pending:
            return {}

        pending_by_driver_pin = {}
        for idx, q in pending.items():
            if q['drvr_pin'] == '__PORT__' or q['recv_pin'] == '__PORT__':
                continue
            pending_by_driver_pin.setdefault(q['drvr_pin'], set()).add(idx)

        resolved = {}

        def process_dnet(dnet_id, conn_entries):
            if not conn_entries:
                return
            candidate_indices = set()
            for conn in conn_entries:
                if conn['pin_name'] is None:
                    continue
                candidate_indices.update(pending_by_driver_pin.get(conn['pin_name'], ()))
            if not candidate_indices:
                return
            node_tokens = {conn['node_token'] for conn in conn_entries}
            conn_cap_map = {conn['node_token']: None for conn in conn_entries}
            for idx in list(candidate_indices):
                if idx in resolved:
                    continue
                q = pending[idx]
                driver = [c for c in conn_entries if c['direction'] == 'O' and endpoint_matches_conn(c, q['drvr_inst'], q['drvr_pin'])]
                recv = [c for c in conn_entries if endpoint_matches_conn(c, q['recv_inst'], q['recv_pin'])]
                if len(driver) != 1 or len(recv) != 1:
                    continue
                resolved[idx] = {
                    'dnet_id': dnet_id,
                    'drvr_node_token': driver[0]['node_token'],
                    'recv_node_token': recv[0]['node_token'],
                }

        with open(spef_path, 'r') as f:
            current_dnet = None
            in_conn = False
            conn_entries = []
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith('*D_NET'):
                    if current_dnet is not None:
                        process_dnet(current_dnet, conn_entries)
                    parts = line.split()
                    current_dnet = parts[1] if len(parts) >= 2 else None
                    in_conn = False
                    conn_entries = []
                    continue
                if current_dnet is None:
                    continue
                if line.startswith('*CONN'):
                    in_conn = True
                    continue
                if line.startswith('*CAP') or line.startswith('*RES'):
                    in_conn = False
                if line.startswith('*END'):
                    process_dnet(current_dnet, conn_entries)
                    current_dnet = None
                    in_conn = False
                    conn_entries = []
                    continue
                if not in_conn:
                    continue
                conn = parse_conn_entry(line)
                if conn is not None:
                    conn_entries.append(conn)
            if current_dnet is not None:
                process_dnet(current_dnet, conn_entries)
        return resolved

    def instance_name_matches(query_inst, conn_full_name):
        q_norm = normalize_name_token(query_inst)
        c_norm = normalize_name_token(conn_full_name)

        if q_norm == c_norm:
            return True
        if short_leaf(c_norm) == q_norm:
            return True
        if short_leaf(c_norm) == short_leaf(q_norm):
            return True
        return False

    def parse_conn_entry(line):
        parts = line.split()
        if len(parts) < 3 or parts[0] not in ('*I', '*P'):
            return None

        node_token = parts[1]
        direction = parts[2]
        if ':' in node_token:
            base_node, pin_name = node_token.split(':', 1)
        else:
            base_node, pin_name = node_token, None

        return {
            'kind': parts[0],
            'node_token': node_token,
            'base_node': base_node,
            'pin_name': pin_name,
            'direction': direction,
            'full_name': id_to_name.get(base_node, base_node),
        }

    def endpoint_matches_conn(conn, inst_name, pin_name):
        if pin_name == "__PORT__":
            if conn['pin_name'] is not None:
                return False
            return instance_name_matches(inst_name, conn['full_name'])

        if conn['pin_name'] != pin_name:
            return False
        return instance_name_matches(inst_name, conn['full_name'])

    net_queries = {}
    unresolved_queries = []
    for q in queries:
        spef_nets = [
            spef_id for spef_id in get_spef_ids(q['net'])
            if isinstance(spef_id, str) and spef_id.startswith('*')
        ]
        for spef_net in spef_nets:
            if spef_net not in net_queries:
                net_queries[spef_net] = []
            net_queries[spef_net].append({
                'drvr_inst': q['drvr_inst'],
                'drvr_pin': q['drvr_pin'],
                'recv_inst': q['recv_inst'],
                'recv_pin': q['recv_pin'],
                'recv_cell': q.get('recv_cell'),
                'orig_idx': q['net_idx'],
            })
        if not spef_nets:
            unresolved_queries.append(q)

    if unresolved_queries:
        print(f"2-2. NAME_MAP으로 못 찾은 net {len(unresolved_queries)}개에 대해 CONN fallback 매칭 중...")

        unresolved_by_driver_pin = {}
        unresolved_by_recv_pin = {}
        unresolved_port_query_indices = set()

        for q_idx, q in enumerate(unresolved_queries):
            if q['drvr_pin'] == "__PORT__" or q['recv_pin'] == "__PORT__":
                unresolved_port_query_indices.add(q_idx)
            if q['drvr_pin'] != "__PORT__":
                unresolved_by_driver_pin.setdefault(q['drvr_pin'], set()).add(q_idx)
            if q['recv_pin'] != "__PORT__":
                unresolved_by_recv_pin.setdefault(q['recv_pin'], set()).add(q_idx)

        fallback_hits = {}
        driver_only_hits = {}
        ambiguous_driver_only = set()

        def process_fallback_dnet(dnet_id, conn_entries):
            if not conn_entries:
                return

            candidate_query_indices = set()
            for conn in conn_entries:
                pin_name = conn['pin_name']
                if pin_name is None:
                    candidate_query_indices.update(unresolved_port_query_indices)
                    continue
                candidate_query_indices.update(unresolved_by_driver_pin.get(pin_name, ()))
                candidate_query_indices.update(unresolved_by_recv_pin.get(pin_name, ()))

            if not candidate_query_indices:
                return

            # 이 D_NET 의 CONN 을 **핀 이름으로 한 번만** 색인해 둔다.
            # 예전에는 후보 질의마다 conn_entries 를 처음부터 끝까지 두 번씩
            # 훑었다. 그래서 endpoint_matches_conn 이 4억 3천만 번 불렸고,
            # 그 안에서 이름 정규화가 또 1억 5천만 번 돌았다. 이 구간 하나가
            # 2b 시간의 대부분이다.
            #
            # 핀 이름이 같은 것만 후보가 될 수 있으므로(endpoint_matches_conn
            # 의 첫 조건), 그것으로 먼저 좁힌 뒤 인스턴스 이름을 비교한다.
            by_pin = {}
            ports = []
            for conn in conn_entries:
                pn = conn['pin_name']
                if pn is None:
                    ports.append(conn)
                else:
                    by_pin.setdefault(pn, []).append(conn)

            def matches(inst_name, pin_name):
                """endpoint_matches_conn 과 같은 판정. 후보만 본다."""
                cands = ports if pin_name == "__PORT__" else by_pin.get(pin_name)
                if not cands:
                    return None
                for conn in cands:
                    if endpoint_matches_conn(conn, inst_name, pin_name):
                        return conn
                return None

            for q_idx in candidate_query_indices:
                if q_idx in fallback_hits:
                    continue

                q = unresolved_queries[q_idx]
                if matches(q['drvr_inst'], q['drvr_pin']) is None:
                    continue

                if matches(q['recv_inst'], q['recv_pin']) is not None:
                    fallback_hits[q_idx] = dnet_id
                    continue

                # 아래는 드물게만 오므로 예전대로 전체를 본다.
                driver_matches = [
                    conn for conn in conn_entries
                    if endpoint_matches_conn(conn, q['drvr_inst'], q['drvr_pin'])
                ]

                driver_output_matches = [
                    conn for conn in driver_matches
                    if conn['direction'] == 'O'
                ]
                if len(driver_output_matches) != 1:
                    continue
                if q_idx in ambiguous_driver_only:
                    continue
                if q_idx in driver_only_hits and driver_only_hits[q_idx] != dnet_id:
                    ambiguous_driver_only.add(q_idx)
                    driver_only_hits.pop(q_idx, None)
                    continue
                driver_only_hits[q_idx] = dnet_id

        with open(spef_path, 'r') as f:
            current_dnet = None
            in_conn = False
            conn_entries = []

            for raw in f:
                line = raw.strip()
                if not line:
                    continue

                if line.startswith('*D_NET'):
                    if current_dnet is not None:
                        process_fallback_dnet(current_dnet, conn_entries)
                    parts = line.split()
                    current_dnet = parts[1] if len(parts) >= 2 else None
                    in_conn = False
                    conn_entries = []
                    continue

                if current_dnet is None:
                    continue

                if line.startswith('*CONN'):
                    in_conn = True
                    continue

                if line.startswith('*CAP') or line.startswith('*RES'):
                    in_conn = False

                if line.startswith('*END'):
                    process_fallback_dnet(current_dnet, conn_entries)
                    current_dnet = None
                    in_conn = False
                    conn_entries = []
                    continue

                if not in_conn:
                    continue

                conn = parse_conn_entry(line)
                if conn is not None:
                    conn_entries.append(conn)

            if current_dnet is not None:
                process_fallback_dnet(current_dnet, conn_entries)

        for q_idx, spef_net in driver_only_hits.items():
            fallback_hits.setdefault(q_idx, spef_net)

        for q_idx, spef_net in fallback_hits.items():
            q = unresolved_queries[q_idx]
            net_queries.setdefault(spef_net, []).append({
                'drvr_inst': q['drvr_inst'],
                'drvr_pin': q['drvr_pin'],
                'recv_inst': q['recv_inst'],
                'recv_pin': q['recv_pin'],
                'recv_cell': q.get('recv_cell'),
                'orig_idx': q['net_idx'],
            })

        print(
            f"-> CONN fallback으로 추가 매칭된 net: {len(fallback_hits)}개 "
            f"(driver-only unique fallback {len(driver_only_hits)}개 포함)"
        )

    line_idx_to_query = {q['net_idx']: q for q in queries}
    target_nets = set(net_queries.keys())
    results = {}

    # ---------------------------------------------------------
    _tk.done()
    print("3. scanning the SPEF and computing (single pass) ...")
    _sys.stdout.flush()
    _tk3 = Tick("3. main scan", _spef_size)
    
    in_target_net = False
    current_spef_net = None
    coords = {}
    res_lines = []
    conn_caps = {}

    def process_collected_net_data():
        if current_spef_net in net_queries:
            G = _Graph()
            for r_line in res_lines:
                p = r_line.split()
                if len(p) >= 4 and p[0].isdigit():
                    G.add_edge(p[1], p[2], weight=float(p[3]))

            available_nodes = set(G.nodes())
            available_nodes.update(coords.keys())

            def resolve_pin_nodes(inst_name, pin_name):
                candidates = []
                inst_name_norm = normalize_name_token(inst_name)

                # Port endpoint uses bare net node in SPEF (e.g., *1), not inst:pin
                if pin_name == "__PORT__":
                    if inst_name in available_nodes:
                        candidates.append(inst_name)
                    if inst_name_norm in available_nodes:
                        candidates.append(inst_name_norm)
                    for spef_id in get_spef_ids(inst_name):
                        if spef_id in available_nodes:
                            candidates.append(spef_id)
                    for node in available_nodes:
                        if ":" in node:
                            continue
                        full = id_to_name.get(node, node)
                        full_norm = normalize_name_token(full)
                        if full == inst_name or full_norm == inst_name_norm or short_leaf(full) == inst_name_norm:
                            candidates.append(node)
                    return _dedup_keep_order(candidates)

                direct_node = f"{inst_name}:{pin_name}"
                if direct_node in available_nodes:
                    candidates.append(direct_node)
                direct_node_norm = f"{inst_name_norm}:{pin_name}"
                if direct_node_norm in available_nodes:
                    candidates.append(direct_node_norm)

                for spef_id in get_spef_ids(inst_name):
                    node = f"{spef_id}:{pin_name}"
                    if node in available_nodes:
                        candidates.append(node)

                # 계층명 충돌(U####, mem_reg[..]) 보정: 같은 leaf 이름을 가진 노드 후보를 현재 net 내부에서 찾음
                for node in available_nodes:
                    if ":" not in node:
                        continue
                    n_inst, n_pin = node.split(":", 1)
                    if n_pin != pin_name:
                        continue
                    full = id_to_name.get(n_inst, n_inst)
                    if short_leaf(full) == inst_name_norm:
                        candidates.append(node)

                return _dedup_keep_order(candidates)
            
            for net_q in net_queries[current_spef_net]:
                d_nodes = resolve_pin_nodes(net_q['drvr_inst'], net_q['drvr_pin'])
                r_nodes = resolve_pin_nodes(net_q['recv_inst'], net_q['recv_pin'])

                # 세 값은 출처가 서로 다르므로 **독립적으로** 구한다.
                #   Res  : SPEF *RES 그래프의 최단경로   (그래프 필요)
                #   Dist : SPEF 좌표의 맨해튼 거리        (좌표만 필요, 그래프 불필요)
                #   Cpin : 리시버 핀의 capacitance        (SPEF 와 무관)
                # 예전에는 최단경로를 못 찾으면 continue 로 빠져나가 Dist/Cpin 까지
                # 함께 N/A 가 됐다. 구할 수 있는 값은 남기고, 못 구한 것만 N/A 로 둔다.
                # Res 를 구한 경우의 Dist 는 예전과 같이 '최소 저항 쌍'의 것을 쓴다.
                best_r = None
                best_d = None            # best_r 에 대응하는 dist
                fallback_d = None        # Res 를 못 구했을 때 쓸 dist
                for d_pin in d_nodes:
                    for r_pin in r_nodes:
                        dist = None
                        if d_pin in coords and r_pin in coords:
                            dist = abs(coords[d_pin][0] - coords[r_pin][0]) + abs(coords[d_pin][1] - coords[r_pin][1])
                            if fallback_d is None:
                                fallback_d = dist

                        r_path = None
                        r_path = G.shortest_path_length(d_pin, r_pin)
                        if r_path is None:
                            continue
                        if best_r is None or r_path < best_r:
                            best_r = r_path
                            best_d = dist
                if best_r is None:
                    best_d = fallback_d

                # Cpin 은 핀 쌍 순회와 무관하다 -- 리시버 핀 하나로 정해진다.
                best_c = None
                recv_cell = net_q.get('recv_cell')
                recv_pin = net_q.get('recv_pin')
                recv_inst = net_q.get('recv_inst')
                # ① PT 가 뽑아준 핀 capacitance (report_attribute 덤프).
                #    Liberty 를 못 받는 사이트에서는 이게 유일한 Cpin 출처다.
                #    키는 설계 핀 이름(inst/pin)이라 PT 출력과 그대로 맞는다.
                if pin_cap_map and recv_inst and recv_pin and recv_pin != "__PORT__":
                    best_c = pin_cap_map.get('{0}/{1}'.format(recv_inst, recv_pin))
                # ② Liberty 의 cell/pin capacitance
                if best_c is None and recv_cell and recv_pin and recv_pin != "__PORT__":
                    best_c = lib_pin_caps.get(recv_cell, {}).get(recv_pin)
                # ③ SPEF *CONN 의 *L 부하 (있는 SPEF 에만 존재)
                if best_c is None:
                    for r_pin in r_nodes:
                        if r_pin in conn_caps:
                            best_c = conn_caps[r_pin]
                            break
                
                idx = net_q['orig_idx']
                prev_r, prev_d, prev_c = results.get(idx, (None, None, None))
                if prev_r is None and best_r is None:
                    if idx not in results:
                        results[idx] = (None, None, None)
                elif prev_r is None and best_r is not None:
                    results[idx] = (best_r, best_d, best_c)
                elif prev_r is not None and best_r is None:
                    pass
                else:
                    if best_r < prev_r:
                        results[idx] = (best_r, best_d, best_c)

    with open(spef_path, 'r') as f:
        for line in f:
            _tk3(f)
            line = line.strip()
            if not line: continue
            # 첫 글자만 먼저 본다. '*' 로 시작하지 않는 줄이 대부분이라
            # startswith 를 줄마다 다섯 번씩 부를 이유가 없다.
            # (line 은 위에서 빈 줄을 걸렀으므로 line[0] 은 항상 있다)
            is_star = line[0] == '*'

            if is_star and line.startswith('*D_NET'):
                if in_target_net: process_collected_net_data()
                net_id = line.split()[1]
                if net_id in target_nets:
                    in_target_net = True
                    current_spef_net = net_id
                    coords = {}
                    res_lines = []
                    conn_caps = {}
                else:
                    in_target_net = False
                continue

            if in_target_net:
                parts = line.split()
                if is_star and line[1:2] in ('I', 'P') and '*L' in parts:
                    try:
                        node = parts[1]
                        lidx = parts.index('*L')
                        conn_caps[node] = float(parts[lidx + 1])
                    except (ValueError, IndexError):
                        pass
                if is_star and '*C' in parts:
                    try:
                        name = parts[1]
                        idx = parts.index('*C')
                        coords[name] = (float(parts[idx + 1]), float(parts[idx + 2]))
                    except (ValueError, IndexError):
                        pass
                elif not is_star and len(parts) >= 4 and parts[0].isdigit():
                    res_lines.append(line)

        if in_target_net: process_collected_net_data()

    _tk3.done()
    print("3-1. second pass over the nets still missing ...")
    _sys.stdout.flush()
    second_pass_hits = second_pass_exact_conn_match(line_idx_to_query, spef_path, results)
    if second_pass_hits:
        # Build per-D_NET queries with fixed node tokens and recompute only unresolved rows.
        extra_net_queries = {}
        for idx, info in second_pass_hits.items():
            q = line_idx_to_query[idx]
            extra_net_queries.setdefault(info['dnet_id'], []).append({
                'drvr_inst': q['drvr_inst'],
                'drvr_pin': q['drvr_pin'],
                'recv_inst': q['recv_inst'],
                'recv_pin': q['recv_pin'],
                'recv_cell': q.get('recv_cell'),
                'orig_idx': idx,
                'forced_driver_nodes': [info['drvr_node_token']],
                'forced_recv_nodes': [info['recv_node_token']],
            })
        orig_net_queries = net_queries
        net_queries = extra_net_queries
        target_nets = set(extra_net_queries.keys())
        in_target_net = False
        current_spef_net = None
        coords = {}
        res_lines = []
        conn_caps = {}
        with open(spef_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('*D_NET'):
                    if in_target_net:
                        process_collected_net_data()
                    net_id = line.split()[1]
                    if net_id in target_nets:
                        in_target_net = True
                        current_spef_net = net_id
                        coords = {}
                        res_lines = []
                        conn_caps = {}
                    else:
                        in_target_net = False
                    continue
                if in_target_net:
                    parts = line.split()
                    if (line.startswith('*I') or line.startswith('*P')) and '*L' in parts:
                        try:
                            node = parts[1]
                            lidx = parts.index('*L')
                            conn_caps[node] = float(parts[lidx + 1])
                        except (ValueError, IndexError):
                            pass
                    if line.startswith('*') and '*C' in parts:
                        try:
                            name = parts[1]
                            idx2 = parts.index('*C')
                            coords[name] = (float(parts[idx2 + 1]), float(parts[idx2 + 2]))
                        except (ValueError, IndexError):
                            pass
                    elif not line.startswith('*') and len(parts) >= 4 and parts[0].isdigit():
                        res_lines.append(line)
            if in_target_net:
                process_collected_net_data()
        net_queries = orig_net_queries
        print(f"-> exact CONN 2차 처리 추가 매칭: {len(second_pass_hits)}개")
    else:
        print("-> exact CONN 2차 처리 추가 매칭: 0개")

    # ---------------------------------------------------------
    # output_path 가 None 이면 리포트를 쓰지 않고 계산 결과만 돌려준다.
    # (1b_distres.py 처럼 Dist/Res 표만 필요할 때 쓰는 경로)
    if output_path is None:
        return results

    if _fuzzy_budget[1]:
        print("")
        print("  NOTE: gave up the last-resort name search for %d nets."
              % _fuzzy_budget[1])
        print("        That search walks the whole NAME_MAP for one net, and")
        print("        it is capped at %d nets per run. Hitting the cap means"
              % (200,))
        print("        the names in this SPEF do not line up with this report.")
        print("        Measured on a good run it recovered 6 nets out of 3952,")
        print("        so lifting the cap would cost hours and change almost")
        print("        nothing. Check the SPEF instead:")
        print("          python3 debug/spef_match_check.py <report> <spef>")
        _sys.stdout.flush()

    print("4. writing the annotated report ...")
    _sys.stdout.flush()
    
    net_row_re = re.compile(
        r'^(?P<prefix>.*\(net\)\s+\d+\s+[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$'
    )

    for idx, line in enumerate(report_lines):
        clean_line = line.rstrip('\n\r')
        is_net_line = "(net)" in clean_line

        if idx in results:
            r_path, dist, cpin = results[idx]
        elif is_net_line:
            r_path, dist, cpin = (None, None, None)
        else:
            continue

        str_dist = _fmt_value(dist)
        str_rpath = _fmt_value(r_path)
        str_cpin = _fmt_value(cpin)

        if is_net_line:
            m_net = net_row_re.match(clean_line)
            if m_net:
                prefix = m_net.group("prefix")
                report_lines[idx] = (
                    f"{prefix}"
                    f" {'':>10} {'':>10} {'':>10}"
                    f" {str_dist:>10} {str_rpath:>10} {str_cpin:>10}\n"
                )
                continue

        padded_line = clean_line.ljust(header_len)
        append_str = f" {str_dist:>10} {str_rpath:>10} {str_cpin:>10}\n"
        report_lines[idx] = padded_line + append_str

    with open(output_path, 'w') as f:
        f.writelines(report_lines)

    print(f"완료! 수정된 리포트가 저장되었습니다: {output_path}")
    # 호출부가 Dist/Res 를 표로 따로 쓸 수 있게 결과를 돌려준다.
    # 키: timing.rpt 의 줄 번호(0부터), 값: (Res, Dist, Cpin)
    return results


def infer_temp_from_report_name(report_path):
    basename = os.path.basename(report_path)
    m = re.search(r'_(125C|25C|m25C|m40C)(?:_[^/]+)?_fixed\.rpt$', basename, flags=re.IGNORECASE)
    if m:
        return m.group(1).lower()
    # Fallback for custom report names (e.g., *_report_timing.txt)
    m2 = re.search(r'(125c|25c|m25c|m40c)', basename, flags=re.IGNORECASE)
    return m2.group(1).lower() if m2 else None


def find_spef_for_report(report_path, spef_root, force_temp=None):
    base = os.path.basename(report_path)
    # Primary: parent directory name (legacy layout: <report_root>/<design>/*.rpt)
    design = os.path.basename(os.path.dirname(report_path))
    temp = force_temp.lower() if force_temp else infer_temp_from_report_name(report_path)
    if temp is None:
        return None

    # Support flat boomcore report layout such as TT_0p8V_25C_op_cond_all_fixed.rpt
    boomcore_temp_map = {
        "125c": "125",
        "25c": "25",
        "m25c": "m25",
        "m40c": "m40",
    }
    if re.match(r"^TT_.*_(125C|25C|m25C|m40C)(?:_[^/]+)?_fixed\.rpt$", base, flags=re.IGNORECASE):
        for boomcore_name in (
            f"boomcore_temp_{boomcore_temp_map[temp]}.spef",
            f"boomcore_3nm_{boomcore_temp_map[temp]}.spef",
        ):
            boomcore_spef = os.path.join(spef_root, boomcore_name)
            if os.path.exists(boomcore_spef):
                return boomcore_spef

    model_temp = {
        '125c': '125',
        '25c': '25',
        'm25c': '-25',
        'm40c': '-40',
    }[temp]
    def candidate_spef_names(dname, ttoken):
        names = [f"{dname}_{ttoken}.spef.Cnom_model_{model_temp}.spef"]
        # Support both m40c and -40c filename conventions
        if ttoken == "m40c":
            names.append(f"{dname}_-40c.spef.Cnom_model_{model_temp}.spef")
        elif ttoken == "-40c":
            names.append(f"{dname}_m40c.spef.Cnom_model_{model_temp}.spef")
        return names

    for spef_name in candidate_spef_names(design, temp):
        spef_path = os.path.join(spef_root, spef_name)
        if os.path.exists(spef_path):
            return spef_path

    # Fallback: infer design token from filename prefix (e.g., ac97_worst500_report_timing.txt)
    m = re.match(r'^([A-Za-z0-9]+)_', base)
    if m:
        design2 = m.group(1)
        for spef_name2 in candidate_spef_names(design2, temp):
            spef_path2 = os.path.join(spef_root, spef_name2)
            if os.path.exists(spef_path2):
                return spef_path2
    return None


def build_output_path(report_path, report_root, output_suffix, output_root=None):
    if output_root:
        rel_dir = os.path.relpath(os.path.dirname(report_path), report_root)
        report_dir = os.path.join(output_root, rel_dir)
        os.makedirs(report_dir, exist_ok=True)
    else:
        report_dir = os.path.dirname(report_path)
    stem = os.path.splitext(os.path.basename(report_path))[0]
    return os.path.join(report_dir, f"{stem}{output_suffix}")


def collect_reports(report_root, include_glob):
    report_files = []
    for root, _, files in os.walk(report_root):
        for name in files:
            if fnmatch.fnmatch(name, include_glob):
                report_files.append(os.path.join(root, name))
    report_files.sort()
    return report_files


def run_batch(report_root, spef_root, include_glob, output_suffix, output_root=None, dry_run=False, force_temp=None):
    reports = collect_reports(report_root, include_glob)
    if not reports:
        print(f"[INFO] 대상 리포트가 없습니다: root={report_root}, pattern={include_glob}")
        return 0

    success = 0
    skip = 0
    fail = 0

    for rpt in reports:
        spef = find_spef_for_report(rpt, spef_root, force_temp=force_temp)
        if spef is None:
            print(f"[SKIP] SPEF 매칭 실패: {rpt}")
            skip += 1
            continue

        out = build_output_path(rpt, report_root, output_suffix, output_root=output_root)
        lib_path = None
        lib_root = getattr(run_batch, "_lib_root", None)
        if lib_root:
            stem = os.path.basename(rpt)
            if stem.endswith("_fixed.rpt"):
                lib_name = stem[:-len("_fixed.rpt")] + ".lib"
                cand = os.path.join(lib_root, lib_name)
                if os.path.exists(cand):
                    lib_path = cand
                else:
                    corner_prefix = stem[:-len("_fixed.rpt")]
                    lib_glob = os.path.join(lib_root, f"{corner_prefix}*.lib")
                    lib_matches = sorted(glob.glob(lib_glob))
                    if lib_matches:
                        lib_path = lib_matches[0]

        if dry_run:
            print(f"[DRY-RUN] rpt={rpt}")
            print(f"          spef={spef}")
            print(f"          lib={lib_path}")
            print(f"          out={out}")
            success += 1
            continue

        try:
            print("=" * 100)
            print(f"[RUN] rpt={rpt}")
            print(f"      spef={spef}")
            print(f"      lib={lib_path}")
            print(f"      out={out}")
            annotate_timing_report(rpt, spef, out, lib_path=lib_path)
            success += 1
        except Exception as exc:
            print(f"[FAIL] {rpt}: {exc}")
            fail += 1

    print("=" * 100)
    print(f"[SUMMARY] total={len(reports)} success={success} skip={skip} fail={fail}")
    return 1 if fail else 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Annotate timing reports with SPEF-derived Dist/Res columns.",
    )
    parser.add_argument(
        "--report-root",
        default=os.environ.get("REPORT_ROOT", "."),
        help="Root folder that contains circuit subfolders and .rpt files.",
    )
    parser.add_argument(
        "--spef-root",
        default=os.environ.get("SPEF_ROOT", "."),
        help="Folder that stores SPEF files.",
    )
    parser.add_argument(
        "--include-glob",
        default="*_fixed.rpt",
        help="Filename pattern for reports to process.",
    )
    parser.add_argument(
        "--output-suffix",
        default="_annotated.txt",
        help="Suffix appended to each report stem for output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print resolved input/output paths.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Optional separate root directory to store outputs while preserving source subfolders.",
    )
    parser.add_argument(
        "--force-temp",
        default=None,
        choices=["125c", "25c", "m25c", "m40c"],
        help="Force report temperature token when filename does not contain it.",
    )
    parser.add_argument(
        "--lib-root",
        default=None,
        help="Optional folder that stores per-corner .lib files for Cpin lookup.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_batch._lib_root = args.lib_root
    raise SystemExit(
        run_batch(
            report_root=args.report_root,
            spef_root=args.spef_root,
            include_glob=args.include_glob,
            output_suffix=args.output_suffix,
            output_root=args.output_root,
            dry_run=args.dry_run,
            force_temp=args.force_temp,
        )
    )
