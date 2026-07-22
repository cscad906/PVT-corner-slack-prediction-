# PT vs SPICE Crosstalk 개념 정리 (공부용)

이 프로젝트에서 다룬 개념들을 문답 중심으로 자세히 정리. 순서: 기초(arc·delay) → crosstalk 물리 → PT의 처리 → SPICE 측정 → mirror & 재귀속 → CCS 모델 → 정확도 → unseen 코너.

---

# 1. arc — 타이밍의 기본 단위

**arc = 두 핀 사이의 방향성 delay 관계.** 신호가 A→B로 전파될 때의 delay 정보(방향 있음).

두 종류:
- **cell arc**: 셀 입력핀 → 출력핀 (게이트 내부). 예 `INV: A → X`. delay = Liberty 트랜지스터 특성.
- **net arc**: 구동셀 출력핀 → 수신셀 입력핀 (배선). 예 `U1/X → U2/A`. delay = 배선 RC.

**path = arc들의 사슬:**
```
launch flop ─(cell)→ Q ─(net)→ A ─(cell)→ X ─(net)→ ... → capture flop
한 stage = [cell arc] + [net arc]
전체 path delay = 모든 arc delay 합
```
각 arc는 rise/fall 방향 + unateness(positive=입력↑→출력↑ BUF/AND, negative=입력↑→출력↓ INV/NAND/NOR).

---

# 2. delay 측정 = "측정점"과 스톱워치

**HSPICE는 delay를 "귀속"하지 않는다.** 노드별 전압 파형만 계산. delay는 우리가 `.measure`로 정의.

**측정점 = "어느 노드의 몇% 전압 통과 시각"** (스톱워치 이벤트):
```
.measure TRAN d TRIG v(A)=0.4 rise  TARG v(X)=0.4 fall
                 └START(측정점=A)┘   └STOP(측정점=X)┘
= "A가 0.4V 지날 때 START, X가 0.4V 지날 때 STOP" = A→X delay
```
- **cell delay** = TRIG v(A) → TARG v(X)  (측정점 A·X)
- **net delay**  = TRIG v(X) → TARG v(D0) (측정점 X·D0)

파형은 하나, **스톱워치를 어느 노드쌍에 거느냐**로 cell/net이 갈린다. → HSPICE 내부엔 cell/net 구분이 없고, 측정점 선택 + 후처리 분류의 산물.

---

# 3. crosstalk 물리 — victim net 양끝을 같이 민다

aggressor(주변 net)가 스위칭 → 커플링 cap으로 victim net에 charge 주입.
victim net은 RC 배선이라 **X(구동단)와 D0(수신단)가 함께** 밀림 (τ≈11ps 차이로 거의 동시).

**왜 X가 밀리나? (구동셀이 잡고 있는데)**
```
정적: 트랜지스터 완전 ON → 낮은 임피던스 → X 꽉 잡음 → 범프 못 밀음
천이 중: 트랜지스터 반쯤 켜짐 → 출력 임피던스 유한 → 범프가 X를 밀 수 있음
```
비유: **멈춰서 버티는 문은 툭 쳐도 안 밀리지만, 미는 도중인 문은 툭 치면 도착이 늦어진다.**
우리가 재는 50% 교차 순간이 딱 "미는 도중"이라, 그때 범프가 X 도착을 Δ만큼 민다. X가 밀리면 전선으로 이어진 D0도 ~Δ 밀림.

---

# 4. mirror attribution (귀속 거울) — 핵심 개념

같은 물리적 crosstalk를 **PT는 net에, SPICE는 cell에** 기입한다.

**SPICE (파형 실측):**
```
cell = t(X) − t(A):  A는 안 밀림(상류 독립), X만 +Δ → cell = base + Δ  (crosstalk가 cell에!)
net  = t(D0) − t(X): D0도 X도 같이 +Δ → 상쇄 → net ≈ base
→ SPICE: crosstalk가 cell에 나타남
```
핵심 = **기준점 차이**: cell은 안 밀리는 A 기준이라 X의 Δ를 봄 / net은 둘 다 밀린 X·D0 사이라 Δ가 지워짐.

**PT (Liberty 조회):**
```
cell delay = Liberty 테이블 조회(crosstalk 무관) → cell Δ=0
crosstalk = net arc의 delta delay로 정의 기입 (UG p.331/571 명시)
→ PT: crosstalk가 net에 나타남
```

**같은 Δ, 다른 칸 = mirror. total(cell+net)은 양쪽 동일** (Δ를 어디 적든 A→D0 통과시간은 하나).

---

# 5. PT는 SI 켜도 cell delay가 정말 안 늘어나나?

"cell delay 두 가지 정의"로 갈림:
```
① 게이트 고유지연(트랜지스터 스위칭): SI로 안 변함 (커플링은 출력net 외부교란, 소자 I-V 불변)
   → PT의 cell Δ=0이 이 관점. 물리적으로 타당.
② 실측 A→X 교차: 증가함 (X가 주입전하로 밀림) → 실리콘·SPICE서 실제로 보임
```
**PT의 cell Δ=0은 "물리 주장"이 아니라 "장부 선택"** — 밀림(②)을 net delta에 몰아넣고 cell arc는 Liberty값 유지. "게이트는 안 느려지되 출력 교차는 밀린다"를 net에 적는 관례.

UG 명시(`/home/KSW/User Guide/PrimeTime User Guide.pdf`):
- p.331: "dynamic component = **change in net delay (delta delay)** caused by crosstalk"
- p.571: "delta delay = crosstalk on a switching net, **includes fanout stage effect**" (하류 왜곡까지 net delta에 포함)
- cell로 옮기는 옵션 **없음** (`set_annotated_delay -net -delta_only`만).

---

# 6. 재귀속 (re-attribution) — SPICE를 PT식에 맞추기

cell/net 개별 비교하면 mirror로 어긋남 → SPICE crosstalk를 cell→net으로 옮겨 PT식 정렬.

```
crosstalk = align_total − quiet_total   (total로 뽑음 = 불변량이라 정확)
cell_reattr = quiet_cell                (base, crosstalk 뺌)
net_reattr  = quiet_net + crosstalk     (crosstalk를 net에 얹음)
```
예 (stage4): quiet cell 50.5/net 0.1, align cell 61.3/net 0.1
→ crosstalk=10.8, 재귀속: cell 50.5, net 10.9 → PT처럼 crosstalk가 net에.

**재귀속해도 0.8V에서 cell −4%, net +23% 남는 이유:** 재귀속은 crosstalk "위치"(mirror)만 고침. 안 고쳐지는 것:
- **cell −4%**: base 모델차 (SPICE 트랜지스터 vs Liberty, crosstalk 무관)
- **net +23%**: crosstalk "크기"차 (SPICE 최악정렬 worst vs PT 실현 realized)
이 둘은 반대부호라 total에서 상쇄 → **판정은 total로.**

---

# 7. total로 비교해야 하는 이유

```
cell/net split = 귀속 관례에 따라 흔들림 (tool마다 다르게 booking)
total(A→D0) = 물리적 실체 (실제 통과시간) → 두 tool 일치해야 함
```
stage별론 ±수십ps 요동해도 부호 섞여 상쇄되고 total만 실제 경로차. 개별 cell/net으로 "누가 틀렸다" 판단 금지.

---

# 8. PT net delay가 0인데 crosstalk가 net에? (긴 net vs crosstalk)

net delay가 커 보이면 대부분 **wire가 아니라 crosstalk**다.
```
net delay ≈ R×C. 로컬 신호net은 R·C 작아 ~0.02ps → 0.0으로 반올림
net delay가 3.7ps인데 R×C=0.03ps면? → 그건 crosstalk (xtalk 컬럼과 일치 확인)
```
진짜 wire delay(길이·저항 기인)는 클럭트리 같은 긴 net에서만. 리포트 컬럼 주의: `Cpin`(핀cap)을 net delay로 오해 금지, net delay는 수신핀 줄의 Incr.

---

# 9. worst-case vs realized (crosstalk 크기)

```
xtalk 컬럼(dPT) = PT arc의 최악정렬 crosstalk 상한 (모든 aggressor 최악 겹침 가정)
PTnet(SIon)   = 풀패스 실현 crosstalk (timing window로 de-rate, 실제 겹침만)
→ 최악(6.1) > 실현(1.8) 가능. base RC≈0이면 PTnet≈실현crosstalk
```
우리 SPICE arc-align deck은 aggressor를 **최악정렬**하므로 xtalk(최악)와 같은 basis.

**"SPICE worst인데 PT와 왜 비슷?"**
- per-arc 비교라 **PT arc값도 그 arc 안에선 거의 worst** (window는 어느 aggressor 셀지만, 세는 건 worst). 차이 = 안겹치는 aggressor뿐 = ~20~30%.
- PT의 진짜 "not worst"(동시성 de-rate)는 **full-path 비교**에서만(71%). per-arc엔 안 들어감.
- total 비슷한 건 crosstalk가 total의 ~12%뿐이라 희석.

---

# 10. CCS (Composite Current Source) — PT가 cell delay 내는 법

**PT는 CCS delay를 "조회"하지 않는다** (NLDM만 조회). CCS는:
```
lib 저장 = delay 아님. 구동셀 "출력 전류 파형 I(t)" (격자 slew×load로 SPICE 특성화)
PT 사용 = 그 전류원을 "실제 load(RC+수신cap)"에 물려 런타임 시뮬 → delay 계산
```
- CCS는 실제 SPICE 격자 sweep 산물 (보간 아님).
- 단 PT delay = 전류원 축약모델을 실제 load에 구동한 **계산값** (full 트랜지스터 재풀이 아님).
- 그래서 full SPICE와 ~3% 차 = 전류원 근사 (조회오차 아님).
- receiver cap도 CCS 2단(c1/c2) 모델: 구동셀 delay엔 전이 전 작은 c1만 봄.

**NLDM vs CCS**: NLDM = delay 테이블 조회(그대로 씀). CCS = 전류파형 저장, 실제 load에 구동해 delay 계산.

---

# 11. full SPICE vs CCS — 뭐가 정확?

```
full 트랜지스터 SPICE = 소자 방정식 직접 풀이 (원본)
CCS = 그 SPICE로 특성화한 축약 전류원 (근사)
→ CCS 최선 = full SPICE와 일치. 오차만 얹지 더 정확해질 수 없음 (같은 modelcard)
```
- 상대비교로는 **full SPICE가 기준**, CCS가 근사 (~3% 축약오차).
- 둘 다 "실리콘 진실"은 아님 (둘 다 modelcard 의존). 계층: 실리콘 ≈ full SPICE(모델오차) ≈ CCS(모델오차+축약).
- near-threshold일수록 CCS 축약 붕괴 → full SPICE 우위 커짐.
- 실무: CCS/PT = 빠른 사인오프 표준, full SPICE = 크리티컬 검증 기준.

**"같은 slew면 PT=SPICE?"** 거의(2~7%), 정확힌 아님. 잔여 = BSIM 직접풀이 vs CCS 계산 차. → 풀패스 cell gap은 대부분 slew차, 모델차는 ~1%.

---

# 12. slew 전파 발산 — near-threshold 붕괴 원인

**고립 셀(clean ramp 입력)은 다 일치, 풀패스만 발산.**
```
풀패스 out_slew SPICE/PT: 0.7V 81% → 0.6V 59% (SPICE가 날카로움)
→ 셀은 다 맞는데 풀패스 slew가 갈림 → near-threshold서 delay가 slew에 극민감 → 누적
```
원인: Liberty는 셀을 clean-ramp로 추상화, near-threshold 실제 파형은 비이상적(느린tail/빠른중간). 같은 20-80%값이어도 다음 셀을 다르게 구동 → stage마다 누적.
- 0.7V OK(above-threshold, delay가 slew에 둔감) / 0.6V 붕괴(near-threshold 극민감).
- 함의: 모델·Liberty·셀 다 정확 검증됨 → near-threshold선 SPICE(실제파형)가 오히려 정확할 수 있고 Liberty per-cell slew 추상화가 근본한계.

---

# 13. surrogate stage — arc-align의 함정

`write_spice_deck -align_aggressors`는:
- **net arc만** 정렬 가능 (crosstalk가 net 물리현상 → cell arc엔 정렬할 victim net 없음)
- **arc만** (path 안 됨: 다중 victim 최악정렬 모순 + deck 과대)
- net arc victim 천이 생성 위해 **update_timing의 구동 cell arc 재사용** = worst-arrival 핀(A1)

→ path가 A2로 진입해도 deck은 A1 구동 = **틀린 cell arc 측정(surrogate)** → base cell 오염.
해결: full-path base deck(올바른 핀 자연전파)으로 base 따로 + arc-align은 crosstalk delta만(pin-무관 self-consistent).

---

# 14. unseen 코너 — Liberty 없이 예측

특성화(Liberty) 없는 전압에서 PT 못 돌림 → **reference(0.8V) deck을 후처리 retarget**.

**b-1 vs b-2 (retarget slew 처리):**
```
b-1: 전압레벨만 ×(Vn/Vr), slew(램프폭)는 0.8V 그대로 재사용 (--k-slew 1.0)
b-2: 전압 + slew 램프폭 ×k (저전압 느린 slew 근사, --k-slew 1.258)
결론: b-1이 crosstalk 정확(135%), b-2는 과예측(153%)
```
왜 b-2 과예측? slew 넓히기(anchor 고정 stretch)가 aggressor 최대 dV/dt 시점을 victim 민감구간으로 밀어 **정렬 아티팩트** → 커플링 과주입. "느린 aggressor"가 아니라 "정렬 틀어진 aggressor".

**hidden 코너 stage별 input slew는 주입 안 함**: base 풀패스는 launch CK slew(PT ~48ps) 하나만, stage 2~N은 SPICE 자연전파 emergent (ml.csv input_slew=0은 skip-patch라 무시). arc-align만 reference slew 재사용.

유효구간: **0.7V↑ (total 96~103%)**, 0.6V near-threshold 붕괴(82%).

---

# 15. lumped cap vs 실제 수신기 (fanout 큰 net)

고립 셀 load를 lumped cap으로 하면 fanout 큰 net에서 어긋남:
```
INV_0P5 (fanout 4 net, 2.6fF):
  lumped 2.6fF      = 27.6ps  (정적 full cap → 과부하)
  실제 수신기 4셀   = 17.2ps  (구동 delay 창엔 전이 전 작은 cap만 → 가벼움)
  PT CCS            = 21.6ps  (2단 receiver 모델, 중간)
```
→ load 모델이 결정적. lumped는 조잡. 실제 수신기 셀 붙이면 크게 바뀜. (같은 INV라도 fanout-1은 잘 맞음)
- wire R 자체는 R×C=0.068ps로 무시가능 (shielding 아님) → 원인은 **receiver cap 모델링**.

---

# 16. PT 실행 옵션 (우리가 켠 것)

```
① CCS 라이브러리 (전류원 delay 모델)
② si_enable_analysis true (SI/crosstalk on), off와 쌍
③ delay_calc_waveform_analysis_mode=full_design (실제 파형 전파, CCS 정밀모드)
④ report_timing -input_pins -nets -capacitance -transition_time (cell/net/cap/slew 분해)
⑤ -crosstalk_delta (delta 별도 리포트)
```
우리가 비교한 모든 PT 값 = 이 설정의 산물.

---

# 부록: 헷갈리기 쉬운 것 요약
| 오해 | 정정 |
|---|---|
| net delay 크다 = 긴 wire | 대부분 crosstalk (R×C로 확인) |
| PT cell Δ=0 = 물리적으로 cell 안 밀림 | 장부 관례. 실측 A→X는 밀림 |
| cell/net 개별로 누가 맞나 | split은 관례. total로 판정 |
| CCS = SPICE 보간 | 전류원 격자 특성화 + 실제 load 계산 |
| 재귀속하면 cell/net 다 맞아야 | crosstalk 위치만 맞춤. 모델차·크기차 잔존 |
| 0.6V SPICE가 틀림 | slew 전파 발산 (셀·모델·Liberty 다 정상) |
| lumped cap이면 load 반영됨 | fanout 큰 net은 실제 수신기 필요 |
| b-2(slew 맞춤)가 더 정확 | 정렬 아티팩트로 과예측, b-1이 정확 |
