# WALKTHROUGH — 새 서버 + 새 데이터, 클론부터 예측까지 순서대로

이 문서 하나만 위에서 아래로 따라가면 됨. 예시는 가상의 새 데이터
(공정 FFPG, 전압 5개 0.503~0.9, 온도 125/-25 **분리**, BEOL 6레벨 B1~B6,
파일 형식도 다름)로 진행. 자기 데이터의 값으로 바꿔 적으면 그대로 동작.

---

## STEP 1. 데이터를 이렇게 놓는다 (권장 배치)

빌더가 기대하는 구조: **`annotated_dir` 밑에 레벨 폴더**, 그 안에 **전압당
리포트 1개**. 온도/공정/setup·hold 는 서로 다른 폴더(=서로 다른 config)로.

```
<아무 위치>/newco_data/
  setup/
    125/                          ← 온도별 폴더 (분리 차원)
      annotated/
        B1/  newco_ffpg_v0p5030_125c.timing.rpt     ← 전압당 1파일
             newco_ffpg_v0p6120_125c.timing.rpt
             ... (전압 5개)
        B2/ ... B6/               ← BEOL 레벨 폴더 (이름 자유)
      xtalk/
        B1/  FFPG_0p5030V_125C.xt.rpt
        ... B6/
    m25/                          ← -25도: 같은 구조 반복
      annotated/ ...  xtalk/ ...
  hold/
    125/ ...   m25/ ...           ← hold도 같은 구조
```

포인트:
- 레벨 폴더명(B1~B6)·파일명 형식은 **아무거나 됨** — config에 알려주면 됨(STEP 4).
- 이 배치가 안 되는 데이터(코너가 한 파일에 다 있는 등)면 → 텍스트 파서 대신
  **npz 직접 생성** ([PARSING.md §4](PARSING.md) 배열 계약) — STEP 9-D.

**크로스토크 파일 배치 규칙 (slack 모델용):**
1. `crosstalk_dir` 밑에 **annotated와 똑같은 이름의 레벨 폴더**(B1~B6)를 두고,
   각 폴더에 **코너(전압×온도)당 1개** 크로스토크 파일.
2. 파일명에 **접두사·전압·온도 토큰**이 있어야 함:
   `FFPG_0p8820V_125C....xt.rpt` — 여기의 온도 토큰이 config `data.temp`(125/m25)와
   일치하는 파일만 그 모델에 선택됨. (한 폴더에 여러 온도 파일이 섞여 있어도
   temp로 걸러지니 괜찮음)
3. **annotated와 크로스토크의 코너 집합이 정확히 일치**해야 함 — 한쪽에만 있는
   코너가 있으면 빌드가 `I1: corner sets differ`로 멈춤 (STEP 5-C).
4. 확장자가 다르면 config `patterns.crosstalk_suffix`로 알려줌.
5. **slew 모델은 크로스토크가 아예 필요 없음** — slew config엔 `crosstalk_dir`
   자체를 안 적음.
6. 크로스토크 파일 내부는 탭 14열 스키마([PARSING.md §2.3](PARSING.md)) — 열
   구성이 다르면 STEP 9-B.

---

## STEP 2. 클론 + 환경

```bash
cd <작업 위치>
git clone <repo-url> si_corner_model && cd si_corner_model
python3 -m venv .venv && source .venv/bin/activate     # conda 없어도 됨
pip install -e .[train]
python -c "import numpy, yaml, torch; print('OK, cuda =', torch.cuda.is_available())"
```

---

## STEP 3. 정찰 — config에 적을 값을 눈으로 확인

```bash
D=<아무 위치>/newco_data
ls $D/setup/125/annotated/                    # ① 레벨 폴더명 → rc_corners
ls $D/setup/125/annotated/B3/ | head -3       # ② 파일 확장자 / ③ 전압 토큰 위치
head -60 $D/setup/125/annotated/B3/<아무 rpt> # ④ 본문이 PrimeTime류인가? ★갈림길★
ls $D/setup/125/xtalk/B3/ | head -3           # ⑤ 접두사(FFPG) / ⑥ crosstalk 확장자
head -5 $D/setup/125/xtalk/B3/<아무 rpt> | cat -A | head   # ⑦ 탭 14열인가?
head -3 $D/hold/125/xtalk/B3/<아무 rpt>       # ⑧ hold 델타 부호가 음수(-min)인가? ★필수★
```

**정찰표를 채운다** (STEP 4에서 그대로 옮겨 적음):

| 항목 | 이 예시의 값 |
|---|---|
| 접두사 | FFPG |
| 레벨 폴더 | B1 ~ B6 |
| 전압 | 0.503, 0.612, 0.721, 0.882, 0.9 |
| 온도 토큰 | 125, m25 |
| annotated 확장자 / 전압토큰 | `.timing.rpt` / `_v0p5030_` |
| crosstalk 확장자 | `.xt.rpt` |

---

## STEP 4. config 작성 (모델 4개 = 파일 4개)

온도 2개 × setup/hold = 4모델. 먼저 하나를 쓰고 나머지는 복사.

```bash
mkdir -p configs/newco
cp configs/TEMPLATE.yaml configs/newco/setup_125.yaml
```

**`configs/newco/setup_125.yaml`** (정찰표 → 한 줄씩):

```yaml
data:
  annotated_dir: <아무 위치>/newco_data/setup/125/annotated
  crosstalk_dir: <아무 위치>/newco_data/setup/125/xtalk
  temp: 125                          # crosstalk 파일명의 온도 토큰
  corner_prefix: FFPG                # 라벨: FFPG_0p882V_B3 형태로 생성됨
  rc_corners: [B1, B2, B3, B4, B5, B6]
  ref_corner: FFPG_0p9V_B3           # 최고전압×중앙레벨 앵커. seen이어야 함.
                                     # 주의: 0.9000은 라벨에서 0p9로 정규화됨
  cache: cache/newco/setup_125/dataset.npz
  patterns:
    annotated_suffix: .timing.rpt
    crosstalk_suffix: .xt.rpt
    voltage_regex: '_v(0p\d+)_'      # _v0p8820_ → 0.882

split:
  hidden_voltages: [0.721]           # 가운데 전압을 숨겨 검증 (seen V 4개 남음)

base:
  axes:
    - {name: v,  ref: 0.9, order: 3}   # seen V 4개 → dv3까지. dv4는 자동 제거됨
    # 6레벨 BEOL: 등간격 정수 좌표. 절대값 무의미(ref를 빼므로), 간격만 중요.
    - {name: rc, ref: 2, order: 2,
       levels: {B1: 0, B2: 1, B3: 2, B4: 3, B5: 4, B6: 5}}   # ref=2 = B3
  # adaptive_grid 생략 → seen 간격에서 자동 유도 (새 데이터 추천)

train:
  out_dir: runs/newco/setup_125/v1
```

나머지 3개는 복사 후 경로·temp·cache·out_dir만 치환:

```bash
cd configs/newco
for m in setup_m25 hold_125 hold_m25; do cp setup_125.yaml $m.yaml; done
sed -i 's#setup/125#setup/m25#g; s#temp: 125#temp: m25#; s#setup_125#setup_m25#g' setup_m25.yaml
sed -i 's#setup/125#hold/125#g;                          s#setup_125#hold_125#g'  hold_125.yaml
sed -i 's#setup/125#hold/m25#g; s#temp: 125#temp: m25#; s#setup_125#hold_m25#g'  hold_m25.yaml
cd ../..
```

---

## STEP 5. 빌드 → 에러 케이스별 대응

```bash
bash scripts/build.sh configs/newco/setup_125.yaml
```

| 케이스 | 증상 | 고치는 곳 |
|---|---|---|
| A. 파일명이 안 맞음 | `no corners discovered` | config `patterns.*` (코드 X) |
| B. 온도 토큰이 `-25C` 식 | m25 파일 못 찾음 | `keys.py` crosstalk 정규식 `(m?\d+)C` → `(-?m?\d+)C` + `temp: "-25"` |
| C. 커버리지 불일치 | `I1: corner sets differ` | annotated/xtalk 폴더 비교 |
| D. ref 오타 | `ref corner ... not in data` | `ref_corner`를 생성 라벨 형식으로 |
| E. 본문 형식 다름 | `no slack line parsed` / 경로 0 | STEP 9-A |
| F. crosstalk 열 다름 | `expected 14 columns` | STEP 9-B |
| G. hold 델타 양수 (STEP 3-⑧) | 에러 없이 **조용히 틀림** | 데이터측에 `-min` 재추출 요청 |

성공 로그: `wrote cache/...: N=<경로수> C=30 S=... A=...` ← **5V×6RC=30 확인.**

---

## STEP 6. 학습 전 sanity — base_check (torch 불필요, 수 초)

base(OLS) 수치는 학습/예측 출력엔 절대 안 나옴. 데이터가 제대로 빌드됐는지는
이 독립 도구로만 확인:

```bash
python -m si_model.training.base_check --config configs/newco/setup_125.yaml
# [BASIS] dropped ['dv4'] ...        ← 정상 (seen V 4개라 자동 제거)
# hidden FFPG_0p721V_B1  x.xx ps ... ← 상식적인 크기인지 확인
```

수치가 터무니없으면 STEP 3~4로 돌아가 (대개 ref/levels/전압 파싱 문제).

---

## STEP 7. 학습 (4모델)

```bash
for m in setup_125 setup_m25 hold_125 hold_m25; do
  bash scripts/build.sh configs/newco/$m.yaml
  nohup bash scripts/train.sh configs/newco/$m.yaml > runs/newco_$m.log 2>&1 &
done
tail -f runs/newco_setup_125.log     # E  2 ... | val-hidden x.xx ps
```

---

## STEP 8. 결과 = 예측값 파일 (model만 출력됨)

```bash
cat runs/newco/setup_125/v1/summary.json
head runs/newco/setup_125/v1/predictions_hidden.csv
#  path_key,corner,truth_ps,model_ps,model_err_ps
```

**측정 안 한 코너의 순수 예측** (정답 없음 → truth 빈칸으로 예측만):

```yaml
# config의 data: 에 추가
  query_corners: [[0.65, B2], [0.65, B5]]
```
```bash
bash scripts/build.sh configs/newco/setup_125.yaml       # 재빌드 (코너 추가됨)
bash scripts/predict.sh configs/newco/setup_125.yaml --corners hidden
```

---

## STEP 9. 코드를 고치는 유일한 케이스들

**A. 리포트 본문 줄 형식이 다름** → [`si_model/parsing/annotated.py`](../si_model/parsing/annotated.py)
상단 정규식만. 예:
```python
# 걔네가 "Slack (MET): 0.123" 이면
SLACK_RE = re.compile(r"^\s*Slack \((?:VIOLATED|MET)[^)]*\):\s+(-?\d+\.\d+)\s*$")
# FF 클럭핀이 /CLK 이면 parse_annotated 안의 "/CK" 두 곳 → "/CLK"
```
고친 뒤 즉석 검증:
```bash
python - <<'EOF'
from si_model.parsing.annotated import parse_annotated
ann = parse_annotated("<rpt 하나>", with_stages=True)
print(len(ann), "paths;", next(iter(ann.values())).slack)
EOF
```

**B. crosstalk 스키마 다름** → [`si_model/parsing/crosstalk.py`](../si_model/parsing/crosstalk.py)
의 열 개수 검사(`!= 14`)와 `t[i]` 인덱스를 그쪽 순서로.

**C. 셀 라이브러리가 SAED 아님 (삼성 등)** → **에러 안 남.** 규칙 없으면 전부
`<unk>` 패밀리 + drive 1.0으로 학습됨(품질만 손해 가능). 살리고 싶으면 config에
분류 규칙(slack 빌더 지원):
```yaml
data:
  cell_taxonomy:
    strip_prefixes: [SEC9T_]                # 이름 앞 접두사 제거
    family_rules:                            # 첫 매치 승 (정규식, 패밀리)
      - ['^ND|^NAND', NAND]
      - ['^NR|^NOR',  NOR]
      - ['^INV|^IV',  INV]
      - ['DFF|SDFF|FF', DFF]
    drive_regex: '_X(\d+P?\d*)$'            # 그룹1 = 드라이브, P = 소수점
```
셀명 분포부터 보려면:
```bash
python - <<'EOF'
from si_model.parsing.annotated import parse_annotated
from collections import Counter
ann = parse_annotated("<rpt 하나>", with_stages=True)
c = Counter(s.cell for p in ann.values() for s in p.stages if s.kind == "cell")
[print(n, name) for name, n in c.most_common(30)]
EOF
```

**D. 아예 다른 도구/형식** → 텍스트 파서 포기, 그 데이터를 읽는 스크립트로
[PARSING.md §4](PARSING.md)의 npz 배열 계약만 채워서 `data.cache` 위치에 저장.
이후 STEP 6부터 동일.

---

## 체크리스트 (한 장 요약)

```
[ ] 데이터 배치: annotated_dir/<레벨>/전압당 rpt, xtalk 동일 (STEP 1)
[ ] 정찰표 작성: 접두사/레벨/전압/온도토큰/확장자/전압토큰 (STEP 3)
[ ] hold 크로스토크 델타 부호 = 음수 확인 (STEP 3-⑧)
[ ] config 4개: 경로·corner_prefix·rc_corners·levels·ref·patterns (STEP 4)
[ ] build 성공 + C = 전압수×레벨수 확인 (STEP 5)
[ ] base_check 수치 상식적 (STEP 6)
[ ] train 4개 → summary.json / predictions_hidden.csv (STEP 7-8)
[ ] 실전 예측은 query_corners + predict.sh (STEP 8)
```
