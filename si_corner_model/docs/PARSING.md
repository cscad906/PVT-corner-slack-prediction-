# PARSING — 리포트를 읽히는 법

**핵심 사실 하나: 엔진은 raw 텍스트를 절대 다시 읽지 않는다. 항상 npz 만 읽는다.**

```
리포트 ──build──► cache/<design>/<temp>/dataset.npz ──► base / 학습 / 예측
```

그래서 "형식이 뭐든" 문제는 **npz 를 만드는 단계 하나**로 좁혀지고, 아래 4단계로
흡수된다. 위로 갈수록 쉽다.

```
새 데이터
 ├─ 파일명만 다르다            → config 한 줄 (§1)           ← 대부분 여기
 ├─ 디렉토리 배치가 다르다      → config layout (§2)
 ├─ 리포트 본문 줄이 다르다     → 정규식 몇 줄 (§4)
 └─ 완전히 다른 도구다          → npz 직접 생성 (§6)
```

---

## 1. 파일 찾기 — `layout: flat` (이번 데이터)

코너가 전부 **파일명**에 들어있는 경우. 하위폴더가 몇 겹이든 재귀로 찾는다.

```yaml
files:
  layout: flat
  subdir: ""              # 회로폴더 밑 하위경로. 비우면 회로폴더 전체 재귀 탐색
  annotated_regex: auto   # 기본값. 아래 설명 참고
```

### `auto` (기본) — 순서·대소문자에 안 휘둘린다

파일명에서 **전압 / 레벨 / 온도 / 공정**을 각각 찾아낸다. 순서, 대소문자,
구분자(`.` `_` `-`), 온도 뒤 `c` 유무에 전혀 영향받지 않는다. 아래가 전부 같은
코너로 읽힌다:

```
report.sspg_0p5000_125c_rcmax.rpt      기준
report.sspg_0p5000_125_rcmax.rpt       온도에 c 없음
report.sspg_0p5000_rcmax_125c.rpt      레벨/온도 순서 바뀜
report.SSPG_0P5000_125C_RCMAX.rpt      전부 대문자
report.sspg_0.5400_125c_rcmax.rpt      전압이 0.5400 형식
sspg-0p5000-125c-rcmax.rpt             하이픈 구분자
RCMAX.125.SSPG.0p5000.rpt              순서 완전히 뒤죽박죽
report.sspg_0p5000_-25c_rcmin.rpt       온도가 -25 (= m25)
```

구분 규칙은 두 가지뿐이다:

- **전압은 소수점 표시(`p` 또는 `.`)가 반드시 있어야 한다** — 그래야 `125`(온도)와
  안 헷갈린다. `0p5400` / `0.5400` / `v0p54` 전부 OK, 그냥 `550` 은 안 됨.
- **레벨은 `temps[].levels` 에 적은 이름과 정확히 일치**해야 한다(대소문자 무시).
  모르는 레벨이 든 파일은 조용히 건너뛴다.

온도는 `data.temp` 와 일치하는 파일만 고른다 — 한 폴더에 온도가 섞여 있어도
모델별로 알아서 갈린다. `m25` / `M25` / `-25` / `m25c` 는 전부 같은 값으로 본다.

### 정규식을 직접 주는 경우

파일명에 숫자가 잔뜩 섞여 `auto` 가 헷갈리거나, 코너를 더 엄격히 지정하고 싶으면:

```yaml
files:
  annotated_regex: 'report\.(?P<proc>\w+)_(?P<v>0p\d+)_(?P<temp>m?\d+)c_(?P<level>\w+)\.'
```

이름있는 그룹의 역할 (대소문자는 무시된다):

| 그룹 | 필수 | 역할 |
|---|---|---|
| `v` | **필수** | 전압 토큰. `0p5000` → 0.5 |
| `level` | **필수** | BEOL 레벨. `temps[].levels` 와 대소문자 무시하고 매칭 |
| `temp` | 선택 | 있으면 `temps[].token` 과 비교해 **필터**. 한 폴더에 온도가 섞여 있어도 모델별로 갈린다 |
| `proc` | 선택 | 있으면 `corners.process` 와 비교해 **필터** |

정규식은 `search` 라 파일명 전체를 맞출 필요가 없다. 뒤쪽이 불확실하면 `\.` 로
끊어두는 게 안전하다 (확장자가 `.rpt` 든 `.rpt.gz` 든 걸린다).

**생성되는 코너 라벨**은 `SSPG_0p5V_cmax` 형태로 **정규화**된다 — `0p5000` 이
`0p5` 가 되는 이유. `ref_corner` 도 이 형태로 만들어지므로
`ref_voltage: 0.6850` 은 `SSPG_0p685V_...` 가 된다.

### 자주 나는 에러

| 메시지 | 뜻 |
|---|---|
| `regex matched NO filenames` | 정규식이 아무것도 못 잡음 → `annotated_regex` 수정 |
| `regex matched some filenames` | 정규식은 맞음. `process` / `temps[].token` / `temps[].levels` 중 하나가 실제 토큰과 불일치 |
| `corner ... matched by more than one file` | 정규식이 헐렁하거나 탐색 범위가 넓음 → `subdir` 을 더 깊게 |

`bash scripts/run.sh recon` 이 실제 파일명과 코너 토큰 분포를 찍어주므로,
거기 값을 그대로 옮겨 적으면 된다.

---

## 2. 파일 찾기 — `layout: levels`

레벨이 **하위폴더**이고 파일명엔 전압만 있는 배치:

```
<annotated_dir>/cmax/   xxx_tt0p5000v_125c_...rpt
                        xxx_tt0p5400v_125c_...rpt
                rcmax/  ...
```

```yaml
files:
  layout: levels
  annotated_suffix: _fixed_annotated.txt   # 고를 파일 확장자
  voltage_regex: '_tt(0p\d+)v'             # 그룹1 = 전압 토큰
  crosstalk_suffix: .by_path.rpt
```

폴더 이름은 `temps[].levels` 로 지정한 그대로여야 한다.

---

## 3. 셀 이름 규칙 (SAED 가 아닌 라이브러리)

**에러는 안 난다.** 규칙에 안 걸리는 셀은 전부 `<unk>` 패밀리 + drive 1.0 으로
학습된다 — 품질만 손해다. 확인부터:

```bash
python - <<'EOF'
from collections import Counter
from si_model.parsing.annotated import parse_annotated
ann = parse_annotated("<리포트 하나>", with_stages=True)
c = Counter(s.cell for p in ann.values() for s in p.stages if s.kind == "cell")
for name, n in c.most_common(30): print("%6d  %s" % (n, name))
EOF
```

예를 들어 이렇게 나온다면:

```
  1626  gt3_6t_inv_x1_rvt
  1434  gt3_6t_buf_x1_rvt
  1230  gt3_6t_buf_x12_rvt
  1176  gt3_6t_dffasync_x1_rvt
   734  gt3_6t_nand2_x1_rvt
   670  gt3_6t_oai211_x1_rvt
```

**보통은 아무것도 안 적어도 된다.** `cell_taxonomy` 를 비워두면 build 가 실제
셀 이름을 보고 스스로 정한다:

- SAED14 내장 표가 이름의 60% 이상을 설명하면 → 그 표를 쓴다 (패밀리가 진짜 함수명)
- 아니면 → 이름에서 규칙을 유도한다. `_` 로 나눈 토큰 중 **가장 변별력이 큰 위치**를
  패밀리로 삼고(벤더 토큰은 다 같아서, drive 토큰은 숫자라서 자동 탈락),
  drive 는 후보 패턴 중 가장 잘 맞는 것을 고른다.

어느 쪽을 썼는지 build 로그의 `[CELLS]` 줄에 예시와 함께 찍힌다:

```
[CELLS] 232 distinct cell names; built-in SAED14 taxonomy covers 100% -- using it
[CELLS] 41 distinct cell names; SAED14 taxonomy covers only 0% -- deriving rules from the names instead
        family from '_'-token #2, 38 families; drive from 'X(\d+(?:P\d+)?)(?:_|$)' (100% of names)
        e.g. SEC9TCPDLL_HVT_NAND2X4_A9PP96CPDLL_C14_R2 -> NANDX/4
```

자동 판정이 마음에 안 들 때만 `config.yaml` 에 직접 적는다 (적으면 자동 판정은 꺼진다):

```yaml
parsing:
  cell_taxonomy:
    strip_prefixes: [gt3_6t_, gt3_]      # 이름 앞에서 떼어낼 접두사
    family_rules:                        # 첫 매치 승. 정규식, 대소문자 무시.
      - ['^dff|^sdff|ff', DFF]
      - ['^inv|^iv',      INV]
      - ['^buf|^bf|^dly', BUF]
      - ['^nand|^nd',     NAND]
      - ['^nor|^nr',      NOR]
      - ['^aoi',          AOI]
      - ['^oai',          OAI]
      - ['^ao',           AO]
      - ['^oa',           OA]
      - ['^xnor',         XNOR]
      - ['^xor',          XOR]
      - ['^mux',          MUX]
    drive_regex: '_x(\d+)_'              # 그룹1 = 드라이브 강도. 대소문자 무시.
```

결과: `inv→INV`, `buf_x12→BUF drive 12`, `dffasync→DFF`, `oai211→OAI`, `nand2→NAND`.

**순서가 중요하다** (첫 매치가 이긴다):
`^aoi` 를 `^ao` 보다, `^xnor` 를 `^xor` 보다, `^nand` 를 `^nand|^nd` 안에서
구체적인 것부터 위에 둔다.

패밀리 이름은 **데이터 내부 라벨**일 뿐이라(어휘를 데이터에서 만든다) 규칙이
*완전할* 필요는 없고 *일관되기만* 하면 된다. 처음엔 대충 분류해도 학습된다.

### FF 핀 이름도 라이브러리마다 다르다

```yaml
parsing:
  clock_pins: [CK, CLK, CP, C]      # FF 클럭핀.  SAED14=CK, gt3=CLK
  ff_output_pins: [Q, QN, QB, Z]    # FF 출력핀. launch_clock -> data 전환 지점
```

안 적으면 위 후보를 순서대로 시도한다. **못 찾아도 에러가 아니라
`launch_clk`/`capture_clk` 가 조용히 NaN 이 된다** — 실제로 gt3 데이터가 `/CLK`
라서 294경로 전부 NaN 이었던 적이 있다. `run.sh check` 가 이 필드의 NaN 여부를
찍어주므로 build 전에 확인할 것.

### 경로 키의 `#번호`

```yaml
parsing:
  strip_path_idx: auto     # auto | true | false
```

경로 키 `<start>-><end>#12` 의 `#12` 를 뗄지 여부다. 두 관행이 공존한다:

- 코너마다 `report_timing` 을 따로 돌린 리포트 → 번호가 코너마다 제각각이라
  **반드시 떼야** 한다(안 떼면 코너 간 join 이 붕괴).
- `1_union.py` 처럼 고정경로 목록을 만들어 전 코너에서 재측정한 리포트 →
  번호가 한 번 정해져 모든 코너에서 같고, **같은 FF 쌍의 서로 다른 경로를
  구분하는 식별자**다. 떼면 병합된다(실측: 294 → 210).

`auto` 는 떼봤을 때 중복이 생기면 식별자로 보고 유지한다. 판단 결과를
`[KEYS] ...` 로 찍어주므로 build 로그에서 확인할 수 있다.

## 4. 리포트 **본문**이 다를 때 — 코드를 고치는 유일한 지점

`파싱된 경로가 0개` 에러가 나면 여기다. 고치는 파일은 3개뿐이고 각각 작다:

| 파일 | 파싱하는 것 | 언제 |
|---|---|---|
| `si_model/parsing/annotated.py` | 타이밍 리포트 한 개의 줄 배치 | **1순위** |
| `si_model/parsing/crosstalk.py` | 탭 14열 크로스토크 행 | 크로스토크 스키마가 다를 때 |
| `si_model/parsing/build_dataset.py` 의 `cell_family`/`cell_drive` | 셀명 분류 | §3 로 안 될 때 |

`annotated.py` 는 **상단 정규식들**이 줄 문법을 정의한다:

| 정규식 | 잡는 줄 |
|---|---|
| `FIXED_PATH_RE` | `### FIXED_PATH idx=<i> key=<start>-><end>` — 경로 블록 구분자 |
| `SLACK_RE` | `slack (VIOLATED\|MET) <num>` — **라벨** |
| `ARRIVAL_RE` / `REQUIRED_RE` | `data arrival time` / `data required time` |
| `CHECK_RE` | `library (setup\|hold) time <incr> <path>` |
| `CELL_RE` | `<inst/pin> (<libcell>) [<-] <trans> <incr> <path> <r\|f>` |
| `NET_RE` | `<net> (net) <fanout> <cap> [<dist> <res> <cpin>]` |

예:

```python
# "Slack (MET): 0.123" 형식이면
SLACK_RE = re.compile(r"^\s*Slack \((?:VIOLATED|MET)[^)]*\):\s+(-?\d+\.\d+)\s*$")
# FF 클럭핀이 /CLK 이면 parse_annotated 안의 "/CK" 두 곳을 "/CLK" 로
```

고친 뒤 즉석 검증:

```bash
python - <<'EOF'
from si_model.parsing.annotated import parse_annotated
ann = parse_annotated("<리포트 하나>", with_stages=True)
print(len(ann), "paths")
p = next(iter(ann.values()))
print("slack", p.slack, "| arrival", p.arrival, "| stages", len(p.stages))
print("segments", {s.segment for s in p.stages})
EOF
```

---

## 5. ★ `### FIXED_PATH` 가 없을 때 — 진짜 질문은 "SSTA냐"가 아니다

`### FIXED_PATH` 헤더는 *고정 경로 리스트를 모든 코너에서 다시 annotate 했다*는
표시다. **중요한 건 헤더가 아니라 코너마다 경로 집합이 같은가** 이다.

이 모델의 대전제가 "**같은 경로**를 여러 코너에서 관측했다" 이기 때문이다. 그냥
`report_timing` 을 코너별로 돌린 거면 코너마다 worst path 가 달라서 경로가 안
겹치고, 그러면 전제 자체가 깨진다 — 파서로 우회할 수 있는 문제가 아니다.

**확인:**

```bash
cd <회로폴더>
# ① 코너마다 경로 수가 같은가
for f in report.sspg_*_125c_rcmax.rpt; do echo -n "$f : "; grep -c 'Startpoint' "$f"; done

# ② 실제로 같은 경로들인가
grep -E 'Startpoint|Endpoint' report.sspg_0p5000_125c_rcmax.rpt | head -20 > /tmp/a
grep -E 'Startpoint|Endpoint' report.sspg_0p6850_125c_rcmax.rpt | head -20 > /tmp/b
diff /tmp/a /tmp/b && echo "SAME (좋음)" || echo "DIFFERENT (재-annotate 필요)"
```

`run.sh recon` 도 ①을 찍어준다.

| 결과 | 조치 |
|---|---|
| **같다** | 헤더만 없는 것. `Startpoint→Endpoint` 로 키를 만들고 등장 순서로 idx 를 매기는 모드를 `annotated.py` 에 추가하면 된다. 작은 수정 |
| **다르다** | 고정 경로 리스트로 재-annotate 한 리포트가 필요하다. 옆 `pt_si_re/` 에 그 파이프라인이 있다 |
| **SSTA 라 열이 더 붙음** | 우선 **nominal/mean 값만** 뽑아 기존 구조에 태울 것. sigma 예측은 그 다음 (새 task) |

### 경로 키의 함정 (직접 파서를 짜도 반드시 지킬 것)

경로 키는 `<start>-><end>_#<idx>` 모양인데, `#idx` 는 **리포트별 일련번호**이지
경로 식별자가 아니다. `norm_path_key` 가 이걸 뗀다. 안 떼고 코너 간 join 하면
공통 경로가 수천 개에서 몇 개로 붕괴한다.

### 무결성 검사 (build 가 자동으로 함)

| | 검사 |
|---|---|
| **I1** | annotated 와 crosstalk 의 코너 집합이 일치 |
| **I2** | 모든 코너·두 소스에서 idx → 정규화 키 매핑이 동일 |
| **I3** | 코너·경로마다 annotated slack == crosstalk 헤더 slack (5e-5 이내) |
| **I4** | 중복 (segment, net) 행의 델타가 일치 (크로스토크 파서 내부) |

---

## 6. 크로스토크(SI) — 폴더·파일 구성

### 어디에 두나

```
<root>/
├── si_corner_model/
├── boomcore/
│   ├── report.sspg_0p5000_125c_rcmax.rpt          ← annotated (타이밍)
│   ├── report.sspg_0p5000_125c_cmax.rpt
│   └── xtalk/                                      ← 크로스토크는 여기
│       ├── xt.sspg_0p5000_125c_rcmax.rpt
│       └── xt.sspg_0p5000_125c_cmax.rpt
├── fft/  ...
└── aes/  ...
```

```yaml
files:
  crosstalk_subdir: xtalk     # <root>/<회로>/xtalk (그 아래 몇 겹이든 재귀)
  crosstalk_regex: auto       # 파일명 규칙은 annotated 와 완전히 동일
```

### 같은 폴더에 둘 다 있는 배치 (`pt_si_re` 산출물)

`pt_si_re` 는 코너마다 폴더 하나를 만들고 그 **안에 둘 다** 넣는다:

```
<root>/boomcore/round2/
├── SSPG_0p5V_125C_rcmax/
│   ├── SSPG_0p5V_125C_rcmax_fixed_annotated.txt          ← annotated
│   ├── SSPG_0p5V_125C_rcmax.path_context_si_compact.by_path.rpt  ← crosstalk
│   ├── corner_info.tcl  cpin.tsv  distres.tsv  ...       ← 중간 파일(무시됨)
│   └── xtalk/
└── SSPG_0p5V_125C_cmax/ ...
```

두 파일 다 코너 토큰을 갖고 있어 그대로는 "같은 코너가 두 파일에 매칭" 이 된다.
**파일명으로 구분**해준다:

```yaml
files:
  crosstalk_subdir: ""                     # 크로스토크도 같은 폴더
  annotated_contains: _fixed_annotated     # 이 문자열이 있어야 annotated
  crosstalk_contains: by_path              # 이 문자열이 있어야 crosstalk
```

**코너 이름(`corner_info.tcl` 의 `CI_CORNER`)에 전압·온도·BEOL 레벨이 모두 들어
있어야 한다** — 파일명이 곧 코너 이름이므로 거기서 좌표를 읽는다. PT 플로우에서
코너를 만들 때 `SSPG_0p5000V_125C_rcmax` 처럼 레벨까지 넣어 두면 그대로 파싱된다.

검증됨: 실제 `pt_si_re/example/round2` 산출물로 build 성공
(`N=294 C=6 S=3362 A=10`).

- **회로 폴더 안 어디든** 된다. 이름만 알려주면 된다.
- 이 폴더는 **annotated 탐색에서 자동 제외**되므로, 회로폴더 안에 두어도
  "같은 코너가 두 파일에 매칭" 에러가 나지 않는다.
- 파일명 접두사(`report.` / `xt.` / 아무거나)는 상관없다. **전압·온도·레벨
  토큰만** 있으면 되고 순서·대소문자도 무관하다(§1 `auto`).
- **annotated 와 코너 집합이 정확히 일치**해야 한다. 하나라도 어긋나면
  `I1: corner sets differ` 로 멈춘다.
- 위치를 모르면 `crosstalk_subdir: null` — SI 없이 학습된다. 나중에 두 줄만
  채우고 `run.sh build` 다시 하면 켜진다.

### 파일 내용 — 탭 14열

```
### FIXED_PATH idx=1 key=<start>-><end>#1
# Slack: VIOLATED -0.054488
data⇥n_0_0⇥agg_0_0⇥0.0078⇥0.023⇥2⇥u_c/g0/A⇥1.0000⇥1.2000⇥u_d/h0/Y⇥0.95⇥1.15⇥0.03⇥0.8
```

| # | 열 | # | 열 |
|---|---|---|---|
| 0 | segment (`launch_clock`/`data`/`capture_clock`) | 7 | victim min arrival |
| 1 | victim net | 8 | victim max arrival |
| 2 | aggressor net (`0` = 활성 aggressor 없음) | 9 | aggressor driver pin |
| 3 | crosstalk delta | 10 | aggressor min arrival |
| 4 | aggressor bump (**이미 /VDD 된 비율**) | 11 | aggressor max arrival |
| 5 | aggressor 수 | 12 | aggressor slew |
| 6 | victim load pin | 13 | coupling cap (fF) |

- **ACTIVE aggressor 당 한 줄.** victim 의 `crosstalk_delta` 는 그 줄들에 반복되며
  (net 당 값이라) 파서가 일치 검증한다.
- `### FIXED_PATH` 의 idx·key 와 `# Slack:` 값이 annotated 와 **같아야** 한다
  (I2/I3). `# Slack: VIOLATED -0.054` 처럼 앞에 상태가 붙어도 된다(마지막 토큰을 읽음).
- 지수 표기(`2.2e-05`) 가능.
- **setup dump = MAX(+) 델타, hold = MIN(−) 델타.** hold 인데 `-min` 없이 뽑으면
  **에러 없이 조용히 틀린다.** `report_delay_calculation -crosstalk -min` 확인.
- 열 구성이 다르면 `crosstalk.py` 의 `!= 14` 검사와 `t[i]` 인덱스를 고친다.

### 무엇이 SI feature 가 되나

단위는 경로가 아니라 **스테이지 = (경로, 세그먼트, victim net)** 이다. 학습에는
`launch_clock` + `data` 만 쓴다(`capture_clock` 은 MIN 방향 델타가 필요한데 이
dump 엔 없다). aggressor 가 하나도 없는 arc 는 스테이지로 만들지 않는다.

aggressor 는 코너마다 활성/비활성이 바뀌어 값이 비는데, `features/si_features.py`
가 (a) 전 코너 활성 aggressor 의 **합집합**을 후보로 잡고 (b) 값이 있는 seen 코너로
저차 다항식을 피팅해 (anchor ≥8이면 2차, ≥4면 1차, 그 미만은 평균) 아무 코너에서나
평가하며 (c) **overlap 은 직접 보간하지 않고** 윈도우 끝점을 보간한 뒤 다시 계산하고
(d) seen 코너에서는 자기 자신을 뺀 LOO 값으로 대체한다(누수 방지).

## 7. 탈출구 — `dataset.npz` 를 직접 만든다

텍스트 파서로 감당이 안 되면, 아무 스크립트로든 아래 배열을 담은 `.npz` 를
`cache/<design>/<temp>/dataset.npz` 에 만들면 된다. 그 뒤 단계
(`base`/`train`/`predict`/`merge`)는 전부 동일하다.

`N`=경로, `C`=코너, `L`=최대 stage 체인 길이, `S`=SI 스테이지, `A`=스테이지당 최대 aggressor.

**코너 그리드**

| 키 | shape / dtype | 의미 |
|---|---|---|
| `corners` | `[C]` str | 라벨, 예 `SSPG_0p5V_cmax` |
| `vt` | `[C,2]` f32 | 코너별 (전압, 레벨값) |
| `measured` | `[C]` bool (선택) | False = 순수 추론 코너. 생략 시 전부 True |

**경로×코너 스칼라** — 전부 `[N,C]` f32, 단위 **ns**
`slack`(라벨, SI 포함), `si_label`(Σ 크로스토크 델타), `arrival`, `required`,
`launch_clk`, `capture_clk`, `lib_check_time`.

**경로 식별 / 인코더 입력**

| 키 | shape | 의미 |
|---|---|---|
| `path_keys` | `[N]` str | 정규화된 경로 키 (코너 간 join 키) |
| `path_idx` | `[N]` i32 | 원본 리포트 idx |
| `path_sig` | `[N,27]` f32 | 세그먼트별 경로 시그니처 |
| `sig_names` | `[27]` str | 그 열 이름 |
| `node_fam` | `[N,L]` i16 | ref 코너 stage 체인 패밀리 id |
| `node_feat` | `[N,L,9]` f32 | 노드 feature (열 5 = critical 마커) |
| `edge_feat` | `[N,L-1,5]` f32 | 엣지 feature (cap, fanout, res, dist, cpin) |
| `node_mask` | `[N,L]` bool | 유효 노드 |
| `fam_vocab` | `[V]` str | 패밀리 어휘 (인덱스 0 = `<pad>`) |
| `node_feat_names`, `edge_feat_names` | str | 열 이름 |

**SI branch 입력** — SI 자료가 없으면 `S=0`, `A=1` 로 두면 된다

| 키 | shape | 의미 |
|---|---|---|
| `stage_path` | `[S]` i32 | 스테이지 → 경로 인덱스 |
| `stage_seg` | `[S]` i8 | 0/1 = launch/data(유지), ≥2 버림 |
| `n_aggr` | `[S]` i16 | aggressor 수 |
| `vwin` | `[S,C,2]` f32 | victim (min,max) arrival 윈도우, ns |
| `arc_delta` | `[S,C]` f32 | victim 크로스토크 델타, ns |
| `abump` | `[S,A,C]` f32 | aggressor bump 비율 (이미 /VDD) |
| `awin` | `[S,A,C,2]` f32 | aggressor (min,max) 윈도우, ns |
| `aslew` | `[S,A,C]` f32 | aggressor slew, ns |
| `acc` | `[S,A]` f32 | 커플링 cap (V/BEOL 무관) |

없는 값은 `NaN` (예: 어떤 코너에서 비활성인 aggressor) — feature 단계가 보간하고
마스킹한다. `si_features.npz` 는 첫 학습 때 자동 생성된다.

**`task: slew` 는 더 작다**: `corners`, `vt`, `path_keys`, `path_idx`,
`slew` `[N,C]`(ns, 라벨), `cap` `[N,C]`, 그리고 위와 동일한 인코더 배열.
SI/크로스토크 배열 없음.
