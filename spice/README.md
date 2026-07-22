# PT vs SPICE Crosstalk 검증 & Unseen-Corner Timing 예측

> **처음 보는 사람용 전체 개요** — 이 코드가 왜 만들어졌고, 무엇을 시도했고, 지금 어떻게 돌아가는지.
> 실행법만 필요하면 → `RUN_GUIDE.md`, 조정값만 필요하면 → `CONFIG_KNOBS.md`, 개념 공부 → `CONCEPTS_STUDY.md`.

---

## 0. 한 줄 요약

**PrimeTime(STA)이 계산한 crosstalk 지연을 HSPICE(회로 시뮬)로 재현·검증하고, 나아가 Liberty(셀 특성화 파일)가 없는 전압 코너에서도 SPICE만으로 타이밍을 예측하는 자동화 플로우.**

---

## 1. 배경 — 무엇을 풀려고 했나

### 문제 1: PT의 crosstalk 값은 믿을 만한가?
칩의 타이밍 사인오프는 PrimeTime(PT)이 한다. PT는 SI(Signal Integrity) 분석을 켜면 **crosstalk**(이웃 배선의 스위칭이 내 신호를 밀어내는 현상)로 인한 추가 지연을 계산한다. 그런데 이 값은 Liberty 테이블 + 추상화 모델의 산물이다 — **트랜지스터 레벨 시뮬레이션(HSPICE)으로 같은 회로를 돌리면 같은 값이 나올까?** 이걸 검증하는 게 첫 목적.

### 문제 2: Liberty가 없는 전압에서 타이밍을 알 수 있나? (unseen corner)
PT를 돌리려면 그 전압/온도에서 특성화된 Liberty(.db)가 필요하다. 그런데 특성화는 비싸서 모든 코너에 없다. **특성화 안 된 전압(예: 0.7V만 있고 0.72V는 없음)에서 타이밍·crosstalk을 예측할 수 있을까?** — SPICE는 트랜지스터 모델(전압 연속)만 있으면 어떤 전압이든 돌릴 수 있다는 점을 이용한다.

### 대상
- 설계: BoomCore (RISC-V, 14nm SAED14 라이브러리), 962개 중 선별한 타이밍 path들
- 기준 코너: TT 0.8V 25C (Liberty 있음), 검증 코너: 0.78/0.7/0.625/0.6V

---

## 2. 핵심 방법 (현재 확립된 플로우)

한 path의 지연을 **두 조각으로 분해**해서 각각 다른 deck으로 잰다:

```
total = base (crosstalk 없는 순수 지연)  +  crosstalk (aggressor가 밀어낸 양)

base      ← full-path deck : path 전체를 한 회로로, launch flop만 구동 → 자연 전파
             (aggressor 없음. 각 stage의 slew는 SPICE가 스스로 만듦)
crosstalk ← arc-align deck : stage(net)마다 독립 deck, aggressor를 최악 시점에 정렬
             (quiet run과 aligned run의 차이 = 그 stage의 crosstalk)
```

왜 두 deck인가? PT의 `write_spice_deck -align_aggressors`(aggressor 최악 정렬)는 **net arc 단위로만** 동작하고(User Guide p.1315), 그 방식은 다입력 게이트에서 **틀린 핀을 구동**(surrogate)해 base가 오염된다. 그래서 base는 full-path deck(올바른 핀), crosstalk은 arc-align(핀과 무관한 차분값)으로 나눠 얻는다.

그리고 **재귀속(re-attribution)**: HSPICE에선 crosstalk이 cell 측정에 잡히고 PT는 net에 기입한다(같은 물리, 다른 장부 = mirror). 비교를 위해 SPICE 값을 PT식(crosstalk→net)으로 옮긴다:
`net_reattr = quiet_net + (align_total − quiet_total)`, `cell = quiet_cell`.

### unseen corner 방법 (b-1 retarget)
Liberty가 없는 전압은 **0.8V reference deck을 후처리**로 변환한다:
```
전압 레벨만 ×(V_new/0.8), VDD 교체. slew(파형 램프폭)는 0.8V 값 그대로 재사용.
트랜지스터 물리는 modelcard(.param VDD)가 자동 처리.
```
slew를 새 전압으로 맞추려는 시도(b-2)는 오히려 crosstalk을 과예측했다 — **전압만 바꾸는 b-1이 정확**하다는 게 실측 결론.

목표전압을 **감싸는 두 코너**가 있으면 추가로 `interp_pt_corner.py`(물리모델 `y=A/(V−Vth)^α`, Vth=0.45)로 stage별 예측 PT reference(cell/net/slew)를 만들 수 있다 — base/절대 타이밍용 (crosstalk은 b-1로 충분). §3-8 참고.

---

## 3. 무엇을 시도했고 무엇을 알아냈나 (여정)

이 코드는 수많은 시행착오의 산물이다. 주요 마일스톤:

### 3-1. "재현 불가"는 오판이었다 (진단)
초기 실험은 "HSPICE가 PT crosstalk을 재현 못 한다"였는데, 두 겹의 아티팩트였다:
- **aggressor 1-cycle 어긋남**: PT가 aggressor 파형을 측정 edge보다 1클럭 뒤에 emit → 시뮬 창 안에서 aggressor가 아예 안 움직임(무효 실험). 시각 보정으로 해결.
- **cell/net 귀속(mirror)**: crosstalk이 victim net 양끝(X, D0)을 같이 밀어 net 측정(X→D0)엔 안 보이고 cell 측정(A→X)에 잡힘. **stage 합/total로 비교**해야 함을 확립.

### 3-2. arc-align + quiet baseline → 85~99% 재현 (핵심 성과)
stage(net arc)마다 aggressor를 최악 정렬한 deck + 동일 조건 quiet deck의 차분으로 crosstalk delta를 재면 PT arc 값의 85~99%를 재현. "PT delta는 SPICE로 재현 불가"라는 통념을 반증.

### 3-3. surrogate 발견과 해결
arc-align deck이 다입력 게이트를 path 핀(A2/B)이 아닌 기본 핀(A1)으로 구동 → base cell delay가 틀림(surrogate). 원인은 PT 툴 제약(UG p.1315: 정렬은 net arc만, 구동은 update_timing의 arc 재사용). **crosstalk delta는 핀 무관(차분이라 상쇄)이라 유효**, base만 full-path deck으로 대체 → base gap ±수%로 해결.

### 3-4. 표준 플로우 확립 → 5-path 검증
`run_fullflow.sh` 하나로 S1(PT SI on/off) → S2(base deck+HSPICE) → S3(arc-align+HSPICE) → 자동 집계.
5개 다양한 path(ALU/FP/regfile/mem, crosstalk 큰 것)에서 **total = PT의 96~103%** 달성.

### 3-5. unseen corner 5-전압 스윕
0.8V deck을 retarget해 0.78/0.7/0.625/0.6V 예측, 그 전압 Liberty로 사후 검증:
```
전압      0.8V   0.78V   0.7V   0.625V   0.6V
total     100%    99%    98%     93%     82%
→ b-1 유효구간 = 0.7V 이상. 0.6V는 붕괴.
```

### 3-6. 0.6V 붕괴 원인 규명 (7가설 소거)
0.6V에서 cell이 -23% 벌어진 원인을 추적 — modelcard 차이(원본 PDK로 스왑해도 <1%), Liberty 스케일링 의혹(PrimeLib로 재특성화하니 1~6% 일치 = Liberty 정확), 셀 모델(고립 셀은 SPICE=Liberty 5~7% 일치), 측정 임계값, net RC, 셀 타입, sharp 입력 — **전부 무죄**. 진범 = **slew 전파 발산**: 풀패스에서 SPICE가 전파하는 slew가 PT보다 날카로워지고(0.6V에서 59%), near-threshold에선 delay가 slew에 극도로 민감해 stage마다 누적. 셀·모델·Liberty는 다 정확하고, **Liberty의 "셀당 slew 숫자 하나" 추상화가 near-threshold 실제 파형을 못 따라가는 근본 한계**.

### 3-7. 고립 셀 검증 — 모델 자체는 ~1% 일치 (0.8V와 0.6V 모두)
각 stage 셀을 고립시켜 **PT의 입력 slew + 올바른 핀 + 실제 load**로 HSPICE 실행하면 PT CCS와 **0.8V +0.8% / 0.6V -0.8%**(47-stage 합계) 일치. 같은 0.6V가 풀패스에선 -24.9%이므로 **붕괴는 100% slew 전파 발산 탓**임이 정량으로 완결됨. (부산물: fanout 큰 net은 lumped cap 근사가 부정확 — 실제 수신기 셀 필요. 0.6V는 `--tran-ps 1200` 필요.)

### 3-8. 양쪽-코너 보간 — 감싸는 두 코너가 있으면 base까지 예측 (2026-07-22)
"가서 어떤 코너를 받을지 모른다"에 대비해, 목표전압을 **감싸는 두 코너 run**(예: 0.8V+0.6V)의 PT 결과에서 stage별 cell/net/slew를 보간해 **목표전압 Liberty 없이 예측 PT reference**를 만드는 도구(`interp_pt_corner.py`)를 추가:
- 모델 = `y(V) = A/(V−Vth)^α` (Vth=0.45 앵커). **선형보간은 +14~15% 틀림** — near-threshold 볼록성 때문에 물리모델 필수.
- 검증(0.8+0.6→0.7, 실제 0.7V PT 대비): cell합 **-0.3~-0.4%**, slew합 +0.1~+1.2% (p146/p153).
- 위상: **crosstalk delta에는 불필요**(b-1로 충분 — delta는 slew가 상쇄). 보간의 가치는 **base/절대 타이밍 예측**.
- 코너 미상 시 가이드: 코너 1개 → b-1 retarget / 감싸는 2개 → base까지 보간(cell ~0.5% 이내).
- `run_fullflow_unseen.sh` USER CONFIG 7) `INTERP_HI_RUN/INTERP_LO_RUN` 지정 시 자동 실행(비우면 스킵) → `p<P>/interp_ref_p<P>.csv`.
- **새 사이트에서 받은 코너에 맞춰 뭘 고칠지**(시나리오별 수정 순서, VREF/Vth 주의) = `RUN_GUIDE.md` **§F-1**.
- **새 사이트 검증 순서**(스모크→ref 검증→b-1 검증→보간 검증→DK-less, 판정 기준표 포함) = `RUN_GUIDE.md` **§F-2**.

### 시도했지만 기각된 것들 (코드에 남아있음)
- full-path 가속 5종(effective-only aggressor, RC 축약, clock 축소 등) — 전부 실익 없음
- per-stage drift 보정 — 균일 shift보다 후퇴
- b-2(slew 스케일 retarget) — crosstalk 과예측
- cell-arc 구동(surrogate fix 시도) — `-align_aggressors`와 양립 불가

---

## 4. 현재 상태 — 코드 구조와 실행

### 폴더 구조 (역할별 분리, 상호 참조로 함께 동작)
```
/home/KSW/code/
├── README.md            ← 이 문서 (전체 개요)
├── RUN_GUIDE.md         ← 실행법 상세
├── CONFIG_KNOBS.md      ← 사용자 조정 변수 정리
├── CONCEPTS_STUDY.md    ← 개념 공부 자료 (16개 주제)
│
├── pt_spice_deck/       ★ SPICE deck "생성" (PrimeTime 필요)
│   ├── run_fullflow.sh         마스터: 전체 플로우 (0.8V)  — 맨 위 USER CONFIG만 편집
│   ├── run_fullflow_unseen.sh  마스터: 전압 스윕 통합 (TARGET_VDD로 전압 선택)
│   ├── tcl/     PT가 실행하는 deck 생성/리포트 tcl 4개
│   ├── py/      PT 구동 + deck 후처리 14개 (flow 오케스트레이터, retarget, 코너보간 …)
│   ├── config/  코너별 설정 json 8개
│   └── README.md, FILES.md (파일별 상세)
│
└── spice/               ★ HSPICE "실행 + 분석"
    ├── py/      HSPICE 실행기, mt0 파서, 비교/리포트 도구, 고립 셀 플로우 12개
    └── README.md, FILES.md
```

### 어떻게 돌아가나 (현재)
```
1. run_fullflow.sh 맨 위 USER CONFIG 확인 (툴/데이터 경로, PATCH_MODE, 전압)
2. bash run_fullflow.sh "146 153 366" "IntToFP FP_fpiu FP_FDivSqrt" myrun
   → path 병렬 실행 (path당 5~9분)
   → S1 PT SI on/off → S2 base deck+HSPICE → S3 arc-align+HSPICE → 자동 집계
3. 결과: <DATA_BASE>/output/input2/myrun/
   summary_*.txt        path별 한 줄 (cell gap / crosstalk repro / total %)
   p*/stage_detail_*.txt stage별 절대 cell/net delay + 차이
   p*/xtalk_delta_*.txt  stage별 crosstalk delta (PT SIoff→on vs HSPICE quiet→align)
   p*/interp_ref_*.csv   (선택) 양쪽-코너 보간 예측 PT reference — INTERP_*_RUN 지정 시
   p*/stage_detail_interp_*.txt (선택) 보간-PT vs SPICE stage별 cell/net 분리 표
```
- **코드는 이 폴더에서 자립 실행** (재배선 완료, 실행 테스트 PASS). 데이터(설계 파일·Liberty, ~9GB)는 `DATA_BASE`(현재 원본 repo)에 있고 USER CONFIG에서 지정.
- 다른 전압: `run_fullflow_unseen.sh`에서 `TARGET_VDD/LIB_DB/CONFIG` 3개만 교체.
- input slew/output load를 강제하려면: `PATCH_MODE=true` + `INPUT_SLEW_PS/OUTPUT_LOAD_FF` (경로 시작/끝 boundary).

### 검증된 성능 (이 플로우가 보장하는 것)
```
base cell gap        ±수%      (SPICE 트랜지스터 vs Liberty의 정상 오프셋)
total (vs PT SI-on)  96~103%   (0.8~0.7V; 최종 판정 지표)
crosstalk repro      111~134%  (SPICE 최악정렬이라 PT arc보다 약간 높음 = 정상·보수적)
unseen 유효구간      0.7V 이상 (0.6V는 near-threshold slew 발산으로 82%)
고립 셀(조건 일치 시) ~1%       (모델 자체는 매우 정확, 0.8V +0.8% / 0.6V -0.8%)
양쪽-코너 보간       cell합 ~0.5% 이내 (0.8+0.6→0.7 검증; base/절대 타이밍용)
```

### 실행에 필요한 것 (요약; 상세는 각 README)
```
툴   : pt_shell, hspice (+ 재특성화시 primelib, lc_shell), 라이선스
데이터: 설계(verilog/sdc/spef) + CCS Liberty(.db) + modelcard + 셀 SPF + fixed-path tcl
      (현재 DATA_BASE=/home/KSW/auto_spice_breakdown/codex/pt_spice_deck 아래, ~9GB)
```

### 다른 회로에 쓸 수 있나?
deck 생성 엔진은 **회로-독립**(표준 PT 플로우, 전부 파라미터). 새 회로 = 설계 파일 경로 + path 목록만 교체. 단 **고립 셀 플로우만 SAED14 라이브러리 종속**(셀명/sensitization) — 다른 라이브러리면 그 부분만 재작성.

---

## 5. 알려진 한계 / 주의

- **0.6V(near-threshold)**: Liberty 추상화 한계로 PT-SPICE가 발산(누가 실리콘에 맞는지는 실측 필요). 방법 탓 아님.
- **crosstalk은 최악정렬 상한**: PT 풀패스 실현값보다 ~20-30% 높게 나옴(보수적). 실동작 예측이 목적이면 center 값 참고.
- **slew/load patch는 경로 boundary만**: 시작 slew·끝 load. stage별 주입 아님.
- **arc-align의 절대 base는 surrogate 오염** 가능 → base는 반드시 full-path 값 사용 (플로우가 자동 처리).
- 데이터가 원본 repo에 있으므로 그 폴더를 지우면 안 됨. **새 머신 이식 시 바꿔야 하는 경로 전체 목록 = `CONFIG_KNOBS.md` ⓪ 이식 체크리스트** (스크립트 USER CONFIG / config json 12개 키 — `work_dir`·`prime_time.tcl` 함정 포함 / 고립 플로우 상수 / 코드 밖 데이터 파일 + 전수 검증 grep).

---

## 6. 더 읽을 것

| 문서 | 내용 |
|---|---|
| `RUN_GUIDE.md` | 실행법 단계별 (인자, patch 모드, 전압 스윕, 고립 셀) |
| `CONFIG_KNOBS.md` | 바꿀 수 있는 모든 변수 (환경/실험/고급) |
| `CONCEPTS_STUDY.md` | 개념 16개 상세 (arc, mirror, CCS, slew 발산 …) |
| `pt_spice_deck/FILES.md`, `spice/FILES.md` | 파일 하나하나의 역할·인자 |
| `PT_SPICE_XTALK_METHODS_LEDGER.md` | 시도한 방식 전수 기록 (A~N + §9 unseen + §10 전압스윕 + §11 보간) — 이 폴더에 복사본 있음 |
