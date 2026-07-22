# PT SI Crosstalk 재현 — 시도 방식 전수 Ledger

작성: 2026-07-11
대상 프로젝트: PrimeTime SI-on crosstalk delta를 HSPICE로 재현/검증
기준 path: 1856 (`brinfos_0_uop_br_tag_reg_1_ → iregister_read_exe_reg_rs2_data_0_reg_61_`), PT SI-off 57.8ps / SI-on 246.3ps (**delta 188.9ps**)
자매 문서: 서사 = `PT_SPICE_XTALK_SESSION_SUMMARY_20260710.md`, 상세 = `PT_SPICE_WORK_SUMMARY_20260707.md` 11.6~11.8.5절

> 이 문서의 목적: "무엇을 시도했고, 그게 **무엇을 해결했으며, 무엇을 해결하지 못했는지**"를 방식 단위로 한눈에 보는 것.

---

## 0. 한 줄 지도

| 계열 | 방식 | 판정 |
| --- | --- | --- |
| **진단** | A. aggressor 타이밍 1-cycle 오판 정정 | ✅ 근본 결함 규명 |
| **진단** | B. cell/net 귀속 오판 정정 | ✅ 비교 기준 확립 |
| **재현** | C. cycle shift (−2.00ns) | 🟡 43% (부분) |
| **재현** | D. cycle+drift shift (−2.05ns) | 🟡 71% (full-path 상한) |
| **재현** | E. arc deck + `-align_aggressors` + quiet baseline | ✅ 85~99% (핵심 성과) |
| **재현** | F. quiet baseline 트릭 (sweep 1000ns) | ✅ 대조군 무재시뮬 생성 |
| **비용** | G. effective-only aggressor (66개) | ❌ 정확도 파괴 |
| **비용** | H. clock 네트워크 축소 | ❌ 실익 없음 |
| **비용** | I. aggressor slew 현실화 | ❌ 실익 미미+위험 |
| **비용** | J. aggressor RC 축약 (lumped-C) | ❌ 비용 실패 (물리는 보존) |
| **비용** | K. `-mt` 병렬화 | ❌ 라이선스 차단 |
| **검증** | L. logical correlation mode tri-state | ✅ no-op 확정 |
| **검증** | M. PT SI net-arc 귀속 다중 path 재확인 (1867/1868/2400) | ✅ 일반화 진척 |
| **재현** | N. full-path 전-arc align + exact-stage 게이트 (1867/1868/2400) | ✅ clean 재현율 확정 (base ±3%) |

범례: ✅ 목표 달성 · 🟡 부분/상한 도달 · ❌ 기각

---

## 1. 진단 계열 — 왜 "재현 불가"가 오판이었나

### A. aggressor 타이밍 1-cycle 불일치 정정  ✅

- **가설/문제**: PT `write_spice_deck`이 aggressor PWL 2,016개를 측정 edge보다 **1 clock period(2ns) 뒤**(5.0~7.0ns)에 emit. `.tran`이 4.8ns에서 끝나 aggressor가 **시뮬 내내 발화조차 안 함(inert)**.
- **방법**: `shift_aggressor_pwl.py`로 aggressor PWL 시각을 일괄 −2ns 평행이동 (0.0ns anchor 유지, victim/clock/measure/.tran 불변).
- **해결한 것 ✅**
  - 기존 "full-aggressor run에서 HSPICE net(57.83ps) ≈ PT SI-off(57.80ps) 일치"가 물리 결론이 아니라 **degenerate(무효) 실험**이었음을 규명.
  - crosstalk이 실제로 발생하게 됨 → 재현 실험의 출발점 확보.
- **해결 못한 것 ✗**
  - 단일 전역 shift로는 stage별 도착 시각 차이를 개별로 맞출 수 없음 (자유도 1 vs 31) → C/D의 상한 원인이 됨.
- **핵심 통찰**: aggressor는 **단일 edge**(양극성 중 worst-case 하나만 활성, 반대극성 주석처리) → shift는 순수 시간이동이라 **방향 불변**, 정렬(크기)만 이동. 데이터 victim도 노드당 단일 edge라 "다른 edge와 겹쳐 부호가 뒤집힘"은 물리적으로 불가 (예외=클럭 net, 아래 M 및 §4 참조).

### B. cell/net 귀속 오판 정정  ✅

- **가설/문제**: coupling bump가 victim net **양단(driver output X + receiver input D0)을 함께** 밀어, net measure(X→D0)로는 delta가 안 보임. delta는 **driver cell measure(A→X)로 흡수**. PT는 같은 물리량을 net arc에 기록 → net끼리 비교하면 **구조적 "재현 실패"**처럼 보임.
- **방법**: 비교 지표를 **stage 합(A→D0) / path total**로 전환. `compare_si_logical_corr_reports.py`로 cell/net split 비교.
- **해결한 것 ✅**
  - net-only 비교의 착시 제거 → 8개 arc 전수에서 net-only delta 전부 ±0.03ps 이하로 귀속 법칙 성립.
  - 파형 실측(Codex): X +46.9ps / D0 +47.4ps 동시 이동, net measure 변화 +0.5ps뿐 (RC τ≈11ps로 bump가 net 양단 동시 도달).
- **해결 못한 것 ✗**
  - HSPICE와 PT의 귀속 칸이 다름(HSPICE=cell, PT=net)은 후처리 재귀속으로 표기 변환만 가능할 뿐, "칸별 직접 비교"는 여전히 무의미 → quiet+aligned 2-run 차분이 필요.
- **재귀속 공식(후처리 산수, 전 항 HSPICE 실측)**: `net(재귀속) = quiet_net + (aligned_stage − quiet_stage)`.

---

## 2. 재현 계열 — delta를 SPICE로 얼마나 되살리나

### C. cycle shift −2.00ns  🟡 43%

- **방법**: A의 shift 폭 = clock 1주기(2.00ns)만 적용.
- **해결 ✅**: full-path delta +81.4ps 실측 → "재현 불가"가 거짓임을 최초 입증.
- **미해결 ✗**: PT 188.9ps 대비 43%에 그침. SPICE 전파가 PT보다 누적 빨라지는 **drift**를 미보정.

### D. cycle+drift shift −2.05ns  🟡 71% (full-path 상한)

- **방법**: cycle(2.00) + drift(0.05) 보정. drift = SPICE CK→D 1497.2 vs PT 1550.3ns → ~53ps 빠름을 aggressor 정렬에 반영.
- **해결 ✅**: full-path delta **+134.1ps (71%)**. `pt_si_hspice_shift_sweep_compare.csv`.
- **미해결 ✗ (구조적 상한)**
  - drift는 stage 따라 0→53ps로 **자라는데** 전역 shift는 한 값만 적용 가능 → stage 명중률 8~136% 편차. **자유도 1 vs 31**.
  - `-align_aggressors`는 full-path에서 PT가 **명시적으로 무시**(`SPICE-041: ignored for the timing path`) — victim 31개라 "누구 기준 worst?" 정의 불가. arc deck 전용.
  - **[2026-07-10 추가] per-stage 차등 shift도 기각** — stage별 이론 drift 적용 시 60%로 오히려 후퇴 (§8-1 참조). 71%는 자유도 부족이 아니라 **"PT emit 시각 자체가 victim 비정렬"**이라는 더 깊은 원인의 경험적 최적점이었음. 71% = 이 계열 확정 상한.

### E. arc deck + `-align_aggressors` + quiet baseline  ✅ 85~99% (핵심 성과)

- **방법**: net arc 단위 deck을 만들고, 시뮬 시점에 각 aggressor를 자기 victim에 대해 worst-case로 **개별 재정렬**. quiet baseline과 차분.
- **해결 ✅ (이 프로젝트 최대 성과)**

  | arc | 실측 delta | PT delta | 재현율 |
  | --- | ---: | ---: | ---: |
  | stage28 `ropt_net_3994` (shift+10ps) | +53.01 | 56.20 | **94.3%** |
  | **n38062** (최대 미스터리) | **+129.2** | 131.52 | **98.2%** |
  | stage30 `HFSNET_10711` | +17.78 | 18.02 | **99%** |

  - n38062 "131.5ps 재현 불가" 미스터리 **종결**(과거 실패=정렬 미사용+net-only 읽기).
  - stage30 "유일한 진짜 실패" 판정도 **baseline 착시**였음(arc 자체 quiet로 실측하니 99%).
  - **8개 arc 전수 재현 실패 0건.** delta 클수록 재현율 정확.
  - 옛 결론 "PT SI delta = vectorless pessimism(SPICE 재현 불가)"을 **정면으로 반증**.
- **미해결 ✗**: arc 단위 국소 정렬이라 **동시성 정보 없음**. "모든 aggressor 동시 최악" 가정의 보수성은 full-path(71%)와의 gap으로만 드러남(§5 참조). full-path 자체 가속은 불가(§3).

### F. quiet baseline 트릭  ✅

- **방법**: arc deck sweep의 shift 파라미터를 **1000ns**로 밀어 aggressor를 window 밖으로 → 회로/조건 동일한 **완전 대조군**을 재시뮬 없이 생성.
- **해결 ✅**: 같은 slew/load/조건의 quiet를 공짜로 확보 → aligned와의 순수 차분이 곧 delta. quiet은 정렬 실험 간 재활용 가능.
- **미해결 ✗**: 없음(도구적 성공). 단 quiet run 1개는 항상 추가로 필요.

---

## 3. 비용 절감 계열 — full-path 가속 시도 (전멸)

> 배경: full-path run ~2h. 이 환경에서 가속 가능성을 5종 실측 → **전부 기각**. 결론: 이 환경에서 full-path 가속은 불가. 매달리지 말 것.

### G. effective-only aggressor (66개만 구동)  ❌ 정확도 파괴

- **방법**: `freeze_noneffective_aggressors.py` — PT active('A') aggressor만 구동, 나머지 DC 동결.
- **해결 ✅ (부분)**: 5.4배 빨라짐. + 부산물: delta = **effective 기여(정렬 민감) + screened 집단 기여(정렬 둔감)** 구성 확인.
- **미해결 ✗**: delta 134→48ps(**36%**)로 붕괴. PT non-active ~1,950개가 **집단 +86.2ps** 기여(개별 작아도 합쳐서 큼). 정확도 희생이 너무 큼.
- 부수: 파서 결함 1건 적발(driver-net 주석 의존 → 소스명 매칭 보강, 영향 +0.7ps).

### H. clock 네트워크 축소  ❌ 실익 없음

- **방법**: clock buffer 제거로 노드 축소 기대.
- **미해결 ✗**: clock buffer 124/22,337 = **0.55%**. 축소해도 규모에 무의미.

### I. aggressor slew 현실화  ❌ 실익 미미+위험

- **방법**: 비현실적 초고속 slew를 현실값으로 교체해 수렴 가속 기대.
- **미해결 ✗**: 초고속(0.6ps)은 98/2016개(port aggressor 관례)뿐. 바꿔도 실익 미미하고 delta 왜곡 위험.

### J. aggressor RC 축약 (lumped-C)  ❌ 비용 실패 (물리는 보존)

- **방법**: `reduce_aggressor_rc.py` — aggressor net RC를 driver 노드로 lumped 병합 (58,200노드 병합, R 64,968→747).
- **해결 ✅ (물리)**: **delta 136.8ps 보존(2% 이내)** — lumped-C aggressor 모델이 crosstalk 보존 물리 확인. wire-RC 지배 회로(긴 버스/클럭)엔 유효 가능성 남김.
- **미해결 ✗ (비용)**: 시간 **+11%**, 메모리 −3%뿐. 노드 몸통은 wire RC 1.3%가 아니라 **트랜지스터 23만 + cap 115만** → RC 줄여도 총량 안 줄어듦.

### K. `-mt` 병렬화  ❌ 라이선스 차단

- **미해결 ✗**: 요청 스레드 무관 **Actual Threads=1**(토큰 2개, MT feature 미포함). 환경 차단.

---

## 4. 방식들이 기대는 물리 전제 (재현이 왜 성립하나)

이 계열 방식들이 유효한 근거 — 대화에서 실물 deck으로 검증한 사실:

- **aggressor = 단일 edge**: 활성 2016개 전부 방향전환 0건. PT가 worst-case 극성 하나만 활성화(반대극성 주석). → shift는 방향 불변, 정렬만 이동.
- **데이터 victim = 노드당 단일 edge**: D 소스 edges=1, 계산 노드도 단조 천이 후 park. → "다른 victim edge 겹침" 불가 → **부호(slowdown/speedup) 반전 불가, 크기만 0→peak**.
- **victim 방향은 노드마다 다름**: 게이트 체인(INV 반전/BUF 유지)이 결정. aggressor는 각자 **로컬 victim segment의 반대**(max-delay) → 절대방향 rise 933/fall 1083 혼합.
- **coupling 토폴로지 고정**: `cc` 캡이 특정 victim-seg↔aggressor-seg를 물리 결선. shift는 시간만 바꿈, 결선 불변 → aggressor가 다른 stage로 점프 안 함.
- **예외 = 클럭 net(multi-edge)**: victim CK(n_GEN[1], edges=10)에 115 aggressor 커플링. multi-edge라 shift가 aggressor를 **다른-방향 클럭 edge에 겹치게** 만들 수 있어 국소 부호 반전 가능 → 전역 shift 위험, **arc 단위 align이 정답**.

---

## 5. 검증 계열

### L. logical correlation mode tri-state  ✅

- **방법**: `debug_pt_n38062_si_compare.tcl`에서 `si_analysis_logical_correlation_mode`를 tri-state화 + 적용값 로깅.
- **해결 ✅**: PT 기본값이 이미 true. true 재설정은 **no-op**, off로 돌리면 이 path에서 **1.7ps만** 차이 → 이 계열은 재현율에 미미. 착시 후보 하나 제거.

### M. PT SI net-arc 귀속 — 다중 path 재확인 (1867/1868/2400)  ✅

- **방법**: 세 path를 SI-off/on 실행, `si_enable_analysis` 토글+되읽기 audit, `-crosstalk_delta` 리포트, cell/net split 정량.
- **해결 ✅ (일반화 진척, §9-④)**

  | path | cell Δ | net Δ | total Δ |
  | --- | ---: | ---: | ---: |
  | 1867 | 0.000 | +104.5 | +104.5 ps |
  | 1868 | 0.000 | +70.3 | +70.3 ps |
  | 2400 | −0.001 | +28.5 | +28.5 ps |

  *(권위값 = `input2_diverse_paths_pt_sioff_sion_hspice_compare.rpt`. 주의: 2400은 adder `/S` 출력핀이 있어 단순 정규식 cell/net 분류가 오분류하니, 비교 리포트 값을 쓸 것.)*

  - Incr 바뀐 핀 **전부 net arc**, cell arc **0** → 결함 B 귀속 법칙을 path1856 밖 3개 path에서 재확인.
  - SI 실제 작동 명백(mode audit on=1/1, off=0/0, 새 세션 재실행 일치).
- **미해결/유의 ⚠️**
  - Trans(slew) **0/59 완전 불변** → 이번 run은 **delay-only SI**(delta-slew 미전파). crosstalk-delta 검증엔 오히려 적합(delay 고립 = apples-to-apples). 단 **full signoff SI 용도면 delta-slew 설정 별도 확인 필요**.
  - PT cell Δ=0은 **11개 PT off/on 쌍 전수(1856·1867·1868·2400·n38062·path1)에서 동일** — PT는 처음부터 일관 delay-only. ("cell ~50" 기억은 PT 아니라 **HSPICE cell-side** crosstalk; stage28=+53).
- 검증 원본: `output/input2/input2_diverse_paths_1867_1868_2400_pt_si_verify/`

### N. full-path 전-arc align + exact-stage 게이트  ✅ (clean 재현율 확정)

- **방법**: 세 path(1867/1868/2400)의 **전 stage arc를 개별 정렬(align worst/center) + quiet baseline** 생성 후 합산. 이후 **absolute 검증(quiet vs SI-off)으로 stage를 게이트** → `exact_path_stage`만 채택.
- **핵심 방법론 (중요)**: crosstalk 지표 = **delta(align−quiet)** (base 상쇄), 단 **absolute base 게이트로 arc 유효성 검증** 필수. delta 혼자선 surrogate arc 위에서도 그럴듯하게 나옴(위험).
- **base 게이트 결과** (quiet vs PT base):

  | path | ALL gap | exact gap | 판정 |
  | --- | ---: | ---: | --- |
  | 1867 | −0.9% | **−1.7%** | 원래 깨끗 |
  | 1868 | **+17.5%** | **−2.9%** | surrogate 58 stage 제거로 정상화 |
  | 2400 | **+54.3%** | **−2.5%** | surrogate 68 stage 제거로 정상화 |

  → base gap 전 gap은 **100% `pt_selected_stage_source`(대체 arc) stage**에서 발생. exact만 남기면 **세 path 모두 ±3%** (quiet≈SI-off 확인).

- **Clean crosstalk 재현율 (exact-gated, base 검증됨)**:

  | path | N exact/전체 | PT Δ | HSP center | HSP worst | 재현율 center | 재현율 worst | crosstalk 커버리지 |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | 1867 | 20/30 | 87.5 | 98.3 | 107.1 | **112.3%** | **122.3%** | 78% |
  | 1868 | 18/76 | 23.8 | 26.3 | 31.3 | **110.3%** | **131.4%** | **31%** ⚠️ |
  | 2400 | 44/112 | 32.2 | 24.4 | 29.1 | **75.8%** | **90.2%** | 92% |

  (단위 ps. worst=arc별 독립최악 합=상한, center=nominal 정렬)

- **해결한 것 ✅**
  - base ±3% 검증 위에서 clean 재현율 확정: **worst 90~131% / center 76~112%**.
  - surrogate stage가 base만 오염(2400 +937ps)하고 **crosstalk은 거의 안 실음**(2400은 crosstalk 92%가 exact에) → 게이팅이 신호 손실 없이 잡음 제거.
  - 귀속 mirror(PT→net, HSPICE→cell) 세 path 재확인. worst가 PT를 오버슈트하는 건 "독립최악 합"의 상한 성질(방식 E와 동일).
- **미해결/유의 ⚠️**
  - **1868은 crosstalk의 69%가 surrogate stage** → exact-gated는 전체 crosstalk의 31%만 검증. **surrogate arc 매핑 수정 전엔 1868 미검증분 큼.**
  - **2400 재현율 76~90%로 소폭 낮음** — base 깨끗하니 per-path 특성(작은 crosstalk 32ps 상대오차/곱셈기 경로) 원인 규명 필요.
  - **absolute total path delay(본래 목적)**를 쓰려면 surrogate stage base 오염을 못 버리므로 **arc 매핑 수정 필수**.
- **교훈**: delta는 "측정 지표", absolute(quiet≈SI-off)는 "유효성 게이트" — **둘 다 필요**. 단 게이트의 의미는 N-2 재해석 참조.
- 검증 원본: `output/input2/input2_path{1867,1868,2400}_all_arcs_align_quiet_compare/`

### N-2. surrogate delta 재해석 → **full 재현율 확정** (최종 결론)

- **배경**: N에서 surrogate stage를 게이트아웃하니 1868 crosstalk 커버리지 31%뿐. surrogate 고치기(§8-8)는 ①cell-arc·③post-process 모두 write_spice_deck 제약으로 막힘.
- **재해석 (검증됨)**: surrogate의 틀린 건 **base(cell delay 절대값)뿐**. **crosstalk delta(align−quiet)는 self-consistent** — align·quiet 둘 다 같은 (틀린 A1) arc에서 재므로 base 상쇄. 그리고 **crosstalk은 victim net coupling 효과라 구동핀(A1 vs B)과 물리적으로 무관** → PT·HSPICE 둘 다 net 커플링을 재니 delta는 옳다.
- **실증 (mode별 재현율 비교)**:

  | path | exact 재현(worst) | surrogate 재현(worst) | 판정 |
  | --- | ---: | ---: | --- |
  | 1867 | 122% | 112% | 근접 → surrogate delta 유효 |
  | 1868 | 131% | 115% | 근접 → 유효 |
  | 2400 | 90% | 156% | surrogate가 crosstalk 8%(2.8ps)뿐 → noise, 무의미 |

- **Full 재현율 (전 stage, 100% 커버)**:

  | path | 재현율 worst | 재현율 center | base(exact 검증) |
  | --- | ---: | ---: | ---: |
  | 1867 | 120% | 109% | −1.7% |
  | 1868 | 120% | 93% | −2.9% |
  | 2400 | 96% | 79% | −2.5% |

  (worst=arc별 독립최악 합=상한, PT 오버슈트 / center=nominal, PT selected 근접)

- **결론**: 세 path 모두 **crosstalk full 재현(center 79~109% / worst 96~120%)**, surrogate delta는 pin-무관 self-consistent로 유효. base(exact)는 ±3% 정상 검증.
- **잔여 open (base only)**: → **N-3에서 full-path deck으로 해소됨.**

### N-3. full-path base deck + 재귀속 합성 → **cell/net 절대 비교 완성** (surrogate 해소)

- **아이디어**: surrogate는 arc-deck이 stage를 잘라 구동핀을 새로 정해서 생김. **full-path deck은 launch점(flop CK/D)만 구동하고 신호가 자연 전파** → 전 stage가 실제 path 핀으로 스위칭 → surrogate 원천 부재.
- **실행**: `run_pt_native_spice_flow.py --config code/config/pt_native_spice_config_input2_cnom25.json --ml-csv (path_id,0,0,0.8,25) --skip-patch` — paths1-5 선례와 동일. 이 config는 **aggressor 없는 순수 victim deck**이라 HSPICE **5~19초/path**(2h 아님). 산출물에 stage별 `pt_vs_native_stage_compare.csv`(pt/spice cell/net 나란히) 자동 생성.
- **결과 (base cell gap, arc-deck→full-path)**: 1867 −1%→**−0.8%** / 1868 **+17%→−2.1%** / 2400 **+54%→−4.6%** — surrogate 오염 완전 해소.
- **최종 합성 (base=full-path quiet + crosstalk=arc-align Δ 재귀속)**:

  | path | SPICE quiet (cell/net) | SPICE SI-est 재귀속 (cell/net) | vs PT SI-on total |
  | --- | --- | --- | ---: |
  | 1867 | 1570.4 / 69.7 | 1570.4 / 204.6 | **101.0%** |
  | 1868 | 1645.9 / 5.1 | 1645.9 / 97.7 | **99.0%** |
  | 2400 | 1615.1 / 10.2 | 1615.1 / 43.7 | **95.8%** |

- **결론**: **absolute total path delay가 PT SI-on 대비 96~101%로 정합** — cell/net 분리 절대 비교(본래 목적) 완성. cell base 95~99%, crosstalk은 arc-align 재귀속(net) 사용. §8-8의 arc 매핑 수정은 **불필요해짐**(full-path가 우회 완성).
- 산출물: `output/input2/input2_fullpath_path{1867,1868,2400}_cnom25_base/` (stage별 cell/net CSV 포함).
- **잔여 관찰 ⑥ (규명·무해)**: 1868만 base **net** 절대값이 PT-off 대비 47%(10.8→5.1). 원인 = **초소형 net(~0.1ps) 측정 해상도 한계** — deck `TRAN_STEP_NS=0.001ns(=1ps)`가 재려는 net delay(0.1ps)의 10배라 격자 보간 정밀도에서 초소형 net을 ~절반 과소측정. 1868은 base net의 41%가 ≤0.2ps 초소형 60개에 흩어져 드러났고(1867은 큰net 지배 101%, 2400은 net 작아 무해). **규모 = 5.7ps/1691.8ps = path의 0.34%, crosstalk delta엔 무관, cell(−2.1%)·total(−2.4%)은 정상.** 고치려면 TRAN_STEP 0.0001ns이나 실익 없음. **교훈: base net 절대비교 시 초소형-net 지배 path(1868류)는 net 단독 대신 cell+net total 또는 delta로 볼 것.** (2400은 내 정규식이 adder `/S` 출력핀을 net 오분류하니 net 분해는 compare 리포트 권위값 사용.)

---

## 6. 확정 워크플로우 (방식 선택 가이드)

```text
정밀 delta (net 단위)   : arc deck + -align_aggressors + quiet baseline 쌍   [방식 E+F]
                          → 1분/run, 재현율 85~99%, 병렬 다발 가능
path 합산 캘리브레이션   : full-path + 글로벌 shift(-2.05ns) 1회             [방식 D]
                          → ~2h, 71% (동시 파형 기준)
비교 지표               : 반드시 stage 합/path total (net-only 금지)          [방식 B]
delta 산출              : quiet + aligned 두 run 차분 (재귀속으로 PT식 표기)  [방식 B+F]
```

- full-path(동시 파형)와 arc/PT(per-arc worst)는 **다른 물리량** — full-path가 낮은 게 정상.
- HSPICE는 이 환경 single-thread 고정. 동시 실행 상한 3개(peak ~25GB/job).

### PT delta 188.9ps의 실측 기반 분해

```text
├─ 71%    : full-path 글로벌 정렬로 재현 [방식 D, 실측]
├─ ~15-25%: stage별 정렬 오차분 (per-arc 정렬 시 회복 — 방식 E로 85~99%)
└─ ~5-15% : 잔여 (per-arc 동시-worst 가정 등 PT 보수성 = 71 vs 99 gap의 정체)
```

---

## 7. 신규 도구 (code/)

| 파일 | 역할 | 관련 방식 |
| --- | --- | --- |
| `native_flow/shift_aggressor_pwl.py` | aggressor PWL 일괄 shift (cycle/drift) | A,C,D |
| `native_flow/freeze_noneffective_aggressors.py` | active aggressor만 구동, 나머지 DC 동결 | G |
| `native_flow/reduce_aggressor_rc.py` | aggressor net RC → driver lumped 병합 | J |
| `native_flow/compare_si_logical_corr_reports.py` | report_timing 4-case cell/net split 비교 | B,M |
| `si_debug/dump_path_arc_delaycalc.tcl` | path 전 net arc에 report_delay_calculation -crosstalk | E |
| `native_flow/run_pt_native_spice_deck.tcl` (수정) | env-gated `ALIGN_AGGRESSORS` | E |
| `si_debug/debug_pt_n38062_si_compare.tcl` (수정) | SI_LOGICAL_CORRELATION_MODE tri-state + 로깅 | L |
| **`native_flow/run_fullflow.sh`** | **표준 실행 드라이버** — path 리스트 4단계 병렬 + 자동 집계 | N-3 |
| **`native_flow/summary_pt_spice.py`** | path별 요약표 (PT\|SPICE cell/net/total) → md/txt/csv | N-3 |
| **`native_flow/stage_pt_spice_compare.py`** | stage별 PT\|SPICE cell/net 상세 (`--top 0`=전 stage) → md/txt/csv | N-3 |

### 표준 실행/출력 플로우 (2026-07-13 확립)

**한 명령**: `code/native_flow/run_fullflow.sh "146 153 366" "IntToFP FP_fpiu FP_FDivSqrt" <runname>`
(arg2 라벨은 **ASCII만** — 한글/화살표 double-width라 monospace 정렬 깨짐)

**4단계 자동 실행** (path별 병렬, path당 ~5~9분, HSPICE(3c)가 stage수 비례 지배):
```
S1  PT SI-off/on report         (~35s, report_fixed_paths_si_on_off.tcl, FIXED_INDEXES)
S2  full-path base (HSPICE 1회)  (~45s, run_pt_native_spice_flow.py --skip-patch, aggressor無)
S3a stage arc list 생성          (~0s, prepare-stage-csv-from-report)
S3b arc-align deck 생성          (~43s, run_pt_aligned_path_arcs, DRIVE_PATH_INPUT_PIN=false TRAN_SIZE=4.8)
S3c HSPICE align+quiet (stage×2)  (지배; 27stage=150s ~ 125stage=425s)
```
**자동 산출** (`output/input2/<runname>/`):
- `summary_<runname>.{md,txt,csv}` — path=행 (base cell PT|SPICE gap%, SI-on net PT|SPICE재귀속 repro%, total %)
- `p<P>/stage_detail_p<P>.{md,txt,csv}` — 전 stage (cell PT|SPICE|Δ, net(SI-on) PT|SPICE재귀속|Δ, xtalk)
- `timing_all.txt` — 단계별 wall-clock

**핵심 구성**: base=full-path(surrogate無), crosstalk=arc-align(재귀속 net). SPICE 출력은 항상 재귀속(사용자 규칙). 검증 지표=base cell gap ±수%, crosstalk repro(vs PT-arc), total(vs PT SI-on) 96~103%.

---

## 8. 미해결 / 열린 항목 (다음 후보)

방식별로 남은 미해결분을 공략하는 후보 실험:

1. ~~**per-stage drift 보정**~~ → **실행됨, 기각 (2026-07-10, WORK_SUMMARY 11.8.6)**: stage별 실측 drift(−9~+67ps, 비단조)를 2,010 aggressor에 64개 차등값(−1.991~−2.067ns)으로 적용했으나 **+114.2ps(60%)로 균일 −2.05(71%)보다 후퇴**. 원인 = full-path aggressor 시각은 victim 정렬이 아니라 **각자의 PT arrival**(SPICE-041) — drift 보존은 비최적 정렬의 충실 보존일 뿐이고, 71%는 준무작위 offset 분포의 경험적 최적 슬라이드. **→ 71% = PT-emit 기반 shift 계열의 확정 상한.** 도구: `shift_aggressor_pwl_perstage.py`.
2. ~~**0~7.2ns + drift(−0.05ns)만**~~ → **검토됨, 불가 (2026-07-10)**: victim D 소스가 one-shot PWL(2.14ns에 0→0.8 후 유지)이라 Q는 3.123ns CK edge에서 **한 번만** 토글 (5.123ns edge에선 D 불변 → 재전파 없음). 6.6ns대에 측정할 victim edge가 존재하지 않아 tran 연장으로는 overlap 불가 — **aggressor shift가 유일한 방법**이었음을 확인. (§4의 "데이터 victim = 단일 edge" 전제와 일치)
3. **unseen corner 적용** (본래 목적) — quiet+aligned → stage 합 → 재귀속을 PT report 없는 corner에 적용. 선행: base correlation 확대(방식 M 계속).
4. **다른 path 일반화** — 방식 M을 더 많은 path로 확장해 재현율/귀속 결론 견고화. (1867/1868/2400 완료, 진행 중)
5. **재귀속 컬럼 정식화** — `parse_pt_native_mt0.py`에 `--quiet-baseline` 옵션.
6. **클럭-커플 aggressor 전용 처리** — §4 예외(multi-edge victim 부호 반전) 때문에, 클럭 net crosstalk은 반드시 arc 단위 align으로 별도 다룰 것. (전역 shift 금지 구역 명시)
7. **full signoff용 delta-slew 확인** — 방식 M이 delay-only였음. signoff 목적이면 delta-slew 전파 설정 검토.
8. **surrogate stage arc 매핑 수정 (방식 N 후속) — deck-gen fix 3종 모두 막힘. delta는 N-2 재해석으로 해결됨, base(absolute)만 open.**
   - **요약 결말**: crosstalk delta 재현은 **N-2에서 full로 확정**(surrogate delta = pin-무관 self-consistent). 이 §8-8의 arc 매핑 수정은 **absolute base(= total path delay 용도)**를 위해서만 남은 과제. 아래는 시도·실패 기록.
   - **근본원인**: `run_pt_aligned_path_arcs_spice_deck.tcl`이 write_spice_deck에 **net arc(X→다음핀)만** 넘겨, 다입력 driver 셀을 **디폴트 입력(A1)으로 구동** → path가 A2/B로 진입하는 stage에서 **틀린 cell arc(A1→X) 측정** → `pt_selected_stage_source` fallback + base +307ps(1868)/+937ps(2400). 실증: stage3 U2658(NR2_1) 메타 `cell_from=A2`인데 deck은 `U2658/A1` 구동.
   - **fix (코드 반영·검증됨)**: env `DRIVE_PATH_INPUT_PIN=true`(기본). write_spice_deck에 **path cell arc(cell_from→cell_to = A2→X) 단독**을 넘겨 실제 path 핀을 구동. 패치 위치 3곳 + summary `drive_pin_mode` 로깅.
   - **교훈 ① 결합 금지**: 처음엔 `add_to_collection`으로 cell+net **2-arc를 결합**했더니 write_spice_deck이 두 arc를 **독립 시간기준으로 배치**(trig td=2.295ns vs targ td=0.827ns 역전) → 전 measure 실패. **cell arc 단독**이 정답.
   - **교훈 ② TRAN_SIZE**: `TRAN_SIZE_NS`(=`.tran` 종료시각) 기본 3.0으로 두면 victim 스위칭(stage3=3.088ns)이 **창 밖으로 잘려** 전 measure 실패. **원본 run과 동일하게 `TRAN_SIZE_NS=4.8` 필수.**
   - **stage3 단독 검증은 성공했으나 일반화 실패 ❌ (근본 장애 발견)**:
     - stage3(U2658 NR2, A2)만은 mode surrogate→**exact**, base gap −5.9%, crosstalk 79%로 잘 됨.
     - **하지만 전체 76 stage 실행 시 write_spice_deck이 56/76 stage에 완전히 빈 deck(.sp 0바이트) 생성** → HSPICE 0.00초 즉시 종료 → 집계 무효(FIXED base −49.5%는 결측 데이터 산물).
     - **원인(확정)**: `write_spice_deck -align_aggressors`는 **NET arc(aggressor 있는 victim net)를 요구**하는데, 내가 넘긴 **CELL arc(A2→X)는 셀 내부 arc라 정렬할 victim net이 없다** → 대부분 빈 출력. stage3는 driver 출력net이 우연히 victim으로 잡혀 생존한 소수(~20).
     - **교훈 ③**: cell-arc 방식은 `-align_aggressors`와 **양립 불가**. `DRIVE_PATH_INPUT_PIN` 기본값 **false로 되돌림**(원래 net-arc working 흐름 보존).
   - **올바른 fix 방향(미구현)**: (a) net arc를 유지하되 write_spice_deck이 **path 입력핀을 구동하도록** 하는 옵션/방법, (b) `get_timing_paths` **path 객체**를 넘겨 write_spice_deck이 coherent하게 stitch+align, (c) net-arc deck을 **후처리**해 구동핀을 A1→path핀으로 교체. → 재검토 필요.
   - **검증 인프라는 확보**: PT/HSPICE 로컬 실행 경로·라이선스(`SNPSLMD_LICENSE_FILE=26585@cscad`)·9 env·1-stage 검증 루프 전부 동작 확인. hspice=`.../hspice/linux64/hspice`, `TRAN_SIZE_NS=4.8` 필수.

---

## 9. Unseen corner (Liberty-free PVT) — V-only 검증 (2026-07-14)

**목적**: 특성화(Liberty) 없는 corner에서 PT를 못 돌리는 상황에, reference corner(0.8V) deck을 **후처리 retarget**만으로 unseen corner(0.7V) crosstalk을 예측. 슬라이드 제목(확정) = **"Liberty-Free Timing at Unseen PVT Corners"** (부제: reference PT + ML boundary conditions + SPICE corner-retarget).

- **분해 원칙(0.8V와 동일)**: unseen total = base(full-path deck) + crosstalk(arc-align deck, 재귀속). 한 deck에서 둘 다 못 얻음(UG p.1315 제약) → **deck 2종 각각 retarget**.
- **corner의 성질**: SPEF는 V-무관(재사용), T는 R에 영향. modelcard는 V/T 연속(`.param VDD`, `.temp`)이라 트랜지스터 물리는 자동. **gap = aggressor slew**(Liberty에서 오던 값).

- **도구 `code/native_flow/retarget_corner_deck.py`**: arc-align deck을 Vref→Vnew로 후처리. ①PWL 전압레벨 ×(Vnew/Vref) ②`.param VDD`/rail = Vnew ③(옵션) aggressor+victim slew 램프폭 ×k_slew. 정렬(shift_* offset) 보존. **주의: manifest의 deck_file 경로가 절대경로라 copy dir로 sed 치환 + 옛 mt0 삭제 후 재실행해야 함**(안 하면 옛 전압 deck이 돎).

- **STEP 1 (V knob 검증, base) — PASS**: SPICE 0.7V base(전압 retarget) vs PT 0.7V base = **총합 97.1%**. 전압효과 PT +37% ≈ SPICE +34%. → 전압 retarget이 base 물리를 올바르게 재현.

- **STEP 3 (정답 없이 crosstalk 예측)**: PT 0.7V Liberty **미사용**, reference(0.8V) arc-align deck을 retarget해서 crosstalk 예측 후 PT 0.7V와 사후 비교.
  - **aggressor slew 처리 두 방식 비교** (path 1867, PT 0.7V xtalk worst=129.1ps 기준):
    - **(b-1) 전압만 retarget, aggressor slew = reference(0.8V) 그대로**: xtalk worst **174.6ps = PT의 135%**, 트렌드 +29% ≈ PT +27%. 오버슈트비 135% ≈ 0.8V의 133%(**오버슈트 corner-불변**).
    - **(b-2) slew도 ×k (k=victim_slew(0.7)/victim_slew(0.8)=1.258)**: base는 개선(96% vs b-1 91%)이나 **crosstalk 악화 197.2ps=153%**(과예측).
  - **결론**: **aggressor slew를 정교히 예측할 필요 없음. 전압 retarget만(b-1)이 crosstalk에 더 정확.** slew를 늘리면 coupling 주입이 과해져 과예측. (base 절대값만 원하면 b-2가 근소 우위지만, crosstalk 목적엔 b-1.)

- **aggressor slew의 소재(FAQ)**: slew는 deck의 **각 aggressor PWL 램프폭**에 net마다 존재(PT가 reference 생성 시 Liberty에서 채움). unseen에선 **net별로 새로 예측·조달 불필요** — reference deck 값 재사용 + 전압 스케일만. ML로 net별 slew를 넣고 싶으면 tcl/PT가 아니라 **deck PWL을 python 후처리**(retarget의 k_slew를 전역→net별로 확장)로 주입. 단 이번 "재사용으로 충분" 결론은 **V-only 검증**임 — T변화·큰 전압차(예: 0.8→0.5V)에선 재확인 필요.

- **인프라**: 0.7V db = `input2/CCS/0p7V/saed14rvt_tt0p7v25c_ccs_rth0p01_full385_3ns250fj_mono.db`(area/footprint 속성 없어도 base 검증엔 무방), config = `code/config/pt_native_spice_config_input2_0p7v.json`(lib_db 0.7V, target vdd 0.7). `TRAN_SIZE_NS=4.8` 유지.

- **③ victim input slew harvest 실증 (등가)**: base full-path deck의 실측 0.7V slew(`spice_out_slew_ps`)를 arc-align deck victim 입력 PWL에 per-stage 주입(`code/native_flow/inject_victim_slew.py`, k=slew07/slew08=1.20~1.29, aggressor는 reference 유지). 결과 worst 176.1 ≈ b-1 174.6 → **victim slew 무관 실증**. **b-2 과예측(197)의 범인 = aggressor slew widen**(b-2−③=+21ps), victim widen은 무해. **매핑 주의**: arc-align stage N victim 입력 = base stage N-1 out_slew, surrogate stage는 path핀(A2) 아닌 default핀(A1) 구동이라 **셀 prefix로 매칭**(정확 핀명 아님). **hidden corner stage별 input slew는 "주입 안 함"**: base 풀패스는 launch CK slew(PT값 ~48ps) 하나만 주입, stage 2~N은 SPICE 자연전파 emergent(`ml.csv input_slew=0`은 skip-patch라 무시). arc-align만 reference slew 주입.

---

## 10. Unseen corner 전압 스윕 + near-threshold 붕괴 규명 (2026-07-15)

**5전압 스윕 (5-path: 146/153/366/966/2135, b-1 방식)**. 결과 = `output/input2/fullflow_5paths{,_0p78v,_0p7v,_0p625v,_0p6v}/`.
```
전압     0.8V   0.78V   0.7V   0.625V   0.6V
total    100%    99%    98%     93%     82%   (SPICE/PT SI-on 평균)
cell gap  -3%    -3%    -5%    -11%    -23%
net repro 120%   127%   163%    223%    254%
         ✅정확  ✅정확  ✅정확  ⚠️경계   ❌붕괴
```
- **b-1(V-only retarget) 유효구간 = 0.7V 이상** (total 96~103%). 0.625V 전이, **0.6V 붕괴**(total 82%). 전압점프 작을수록(0.78) 완벽. cell gap 곡선이 near-threshold로 매끄럽게 벌어짐.

**0.6V 붕괴 원인 규명 — 7가설 소거 후 slew 전파 발산 확정:**
1. **total 붕괴의 89%가 base cell**(절대 ps 분해: 0.6V cell 기여 −3945ps vs net +492ps 부호반대·상쇄). net repro 254%는 %는 크나 net이 total의 ~12%라 절대기여 작음.
2. **소거된 가설(전부 무죄)**: ①modelcard(원본 PDK saed14nm.lib로 스왑 <1%, dvtshift/rdsw 차이 무관) ②Liberty 스케일링(PrimeLib `characterize` 풀특성화로 0.6V 재생성→BUF_2 delay 1~6% 일치, 스케일 아님) ③셀 모델(고립 HSPICE: BUF_2 47.1 vs Liberty 48 / NR2_MM_0P5 25.9 vs 27.1ps 출력slew, 5~7% 일치) ④측정임계값(양쪽 20-80%, derate 1) ⑤net RC(고-RC net도 89% 일치) ⑥셀 타입(같은 NR2가 stage2 92%/stage14 39%) ⑦sharp입력 자체(고립 NR2 sharp 30ps서 일치).
3. **진짜 원인 = slew 전파 발산**: 풀패스 out_slew SPICE/PT = 0.7V 81% → 0.6V **59%**(SPICE가 날카로움). 셀은 고립서 다 일치하는데 **풀패스 실제(비이상) 파형이 Liberty의 clean-ramp 추상화와 갈림** → near-threshold서 delay가 slew·파형모양에 극민감 → stage마다 누적 → 25%. **0.7V OK/0.6V 붕괴 = 같은 발산, near-threshold 증폭.**
4. **함의**: 모델·Liberty·셀 다 정확 검증됨 → **SPICE 풀패스가 near-threshold서 오히려 더 정확할 수 있고, Liberty(NLDM/CCS)의 per-cell slew 추상화가 근본 한계**. 어느 쪽이 silicon에 맞나는 실측 필요. unseen 방법(SPICE 예측) 자체는 문제 아님.

**인프라 신규 확보**: PrimeLib=`/home/synopsys_tool/Primelib/W-2024.09-SP5/bin/primelib`(풀특성화 가능, 5셀 2분). tt0p6 재특성화 셋업=`output/input2/rechar_tt0p6/drive_tt0p6.tcl`(hyunss `thermal_aware_sta/primelib_tt0p7` 템플릿 기반, seed=tt0p8 NLDM, model=원본 PDK). lc_shell=`.../Library_compiler/lc/T-2022.03-SP3/bin/lc_shell`(.lib→.db). **원본 PDK 모델카드 = `/home/0Park/SAED14nm_PDK_12142021/SAED14_PDK/hspice/saed14nm.lib`**(우리 `saed14nm_hspice_local.lib`은 dvtshift 걸린 변형판, but 0.6V gap엔 <1% 영향). **PDK 공식 CCS는 0.8V만**(`/home/hyunss/SAED14nm/.../db_ccs`), 저전압 lib은 sogang1이 PrimeLib로 커스텀 생성. **단위주의**: 우리 커스텀 lib cap=pf, PrimeLib 재특성화=ff (1000× 차, set_load 시 환산 필수).

**stage_detail 출력 형식 변경 (2026-07-15)**: `stage_pt_spice_compare.py`에서 xtalk 컬럼 제거 + 맨 뒤 `d(SP-PT)`=stage 총 delay 차이(cell_d+net_d) 추가. csv=`stage_delta_ps`. 25개 파일(5전압×5path) 재생성. SUM d(SP-PT)가 붕괴 지표: p366 −8.9(0.8V)→−813(0.6V). 개별 stage ±수십ps 요동하나 부호섞여 상쇄→SUM만 실제 경로차(total과 일치).

**신규 도구 `code/native_flow/crosstalk_delta_compare.py` (2026-07-15)** — crosstalk delta 전용 뷰(stage_detail은 절대 delay 뷰, 상보적):
```
stage별:  PT: SIoff SIon dPT  |  HSPICE: quiet align dSP  |  dSP-dPT     + SUM에 repro%
  dPT = pt_arc_delta_selected_ps (= PT SI-on − SI-off, PT가 본 crosstalk)
  dSP = align_stage_worst − quiet_stage (= HSPICE가 본 crosstalk, aggressor 최악정렬)
  PT SI-off = pt_si_stage_ps − dPT 로 역산 (ac.csv만으로 자족, --fullpath는 to_pin 라벨용)
  --center 옵션: align worst 대신 center(nominal)
```
- **두 delta가 같은 basis(arc worst-aligned)라 repro% 비교가 정당.** dPT=0 stage(aggressor 없는 net)는 quiet=align 정상.
- 산출: `p<P>/xtalk_delta_p<P>.{txt,md,csv}` (csv=`pt_si_off_ps,pt_si_on_ps,pt_xtalk_delta_ps,hspice_quiet_ps,hspice_align_worst_ps,hspice_xtalk_delta_ps,xtalk_delta_diff_ps`). 5전압×5path=25개 생성 완료.
- **crosstalk repro 전압 스윕(평균)**: 0.8V 120% / 0.78V 127% / 0.7V 163% / 0.625V 223% / 0.6V 254% — 저전압일수록 SPICE 과예측 심화(= net repro와 동일 지표).
- **run_fullflow*.sh 5종(0.8/0.78/0.7/0.625/0.6) 전부에 자동 생성 통합** — 이제 path마다 `stage_detail_p*`(절대) + `xtalk_delta_p*`(crosstalk delta) 두 뷰가 자동 산출.

---

## 11. 양쪽-코너 보간 reference + 0.6V 정량 완결 (2026-07-22)

**0.6V 붕괴의 정량 완결 (47-stage 고립 비교)**: §10의 "slew 전파 발산" 주장을 수치로 닫음. p146 전 stage를 고립 deck으로 **PT의 per-stage input slew를 주입**해 돌리면(각 stage 입력 = PT의 stage N-1 out_slew, 경로 핀·edge·sensitization 정확, tran 1200ps):
```
            0.8V         0.6V
고립 SUM    +0.8%        -0.8%    (PT-slew 주입 시)
풀패스 SUM  -3%          -24.9%   (slew 자연전파 시)
```
→ **0.6V -24.9% 붕괴는 100% slew 전파 발산 탓** (셀 모델·Liberty는 0.6V에서도 ±1% 정확). 결과=`output/input2/iso_p146_0p6v/REPORT_p146_0p6v.md`. 도구=`gen_isolated_cell_decks.py`(--tran-ps 1200 필요: 0.6V slew 최대 208ps→램프 347ps라 기본 400ps 부족).

**양쪽-코너 보간 (신규, `interp_pt_corner.py`)** — "가서 어떤 코너를 받을지 모름" 대비. 목표전압을 감싸는 두 코너 run의 `pt_vs_native_stage_compare.csv`에서 stage별 pt_cell/pt_net/pt_out_slew를 보간해 **목표전압 Liberty 없이 예측 PT reference** 생성:
- **모델**: `y(V) = A/(V−Vth)^α`, per-stage·per-quantity로 α를 두 코너에서 풀어냄. **Vth=0.45 앵커** (±0.05 → ±1~2%). ~0 값(net 0 등)만 선형 fallback.
- **선형보간은 +14~15% 틀림** — near-threshold 볼록성(0.7V 실제값이 0.8/0.6 평균보다 한참 아래) 때문. 물리모델 필수.
- **검증 (0.8V+0.6V → 0.7V, 실제 0.7V PT 대비)**: p146 cell합 **-0.3%**/slew합 +1.2%, p153 cell합 **-0.4%**/slew합 +0.1%.
- **위상 정리**: crosstalk delta에는 보간 불필요 — b-1로 충분(delta는 victim slew가 상쇄, ③실험 174.6 vs 176.1로 기실증). **보간의 가치 = base/절대 타이밍 예측** (감싸는 코너 2개가 있을 때 cell ~0.5% 이내).
- **통합**: `run_fullflow_unseen.sh` USER CONFIG에 `INTERP_HI_RUN/INTERP_LO_RUN/INTERP_{HI,LO}_VDD/INTERP_VTH` (비우면 스킵). 지정 시 path별 `p<P>/interp_ref_p<P>.csv` + `.txt` 자동 생성. 원본(`code/native_flow/`)과 이동본(`/home/KSW/code/pt_spice_deck/`) 양쪽 적용, 문서(`CONFIG_KNOBS/RUN_GUIDE/FILES.md`) 갱신.

**코너 미상 시 선택 가이드**:
| 제공 코너 | crosstalk delta | base/절대 타이밍 |
|---|---|---|
| 1개 (예: 0.8V만) | b-1 retarget (0.7V↑ 96~103%) | cell gap 곡선 감수 (-3~-23%) |
| 감싸는 2개 | b-1로 충분 (보간 무익) | **보간 reference** (cell ~0.5% 이내) |

**새 사이트에서 코너를 받았을 때 수정 순서** (예: 0.75V+0.55V 제공, 목표 0.65V):
1. **받은 코너마다 `run_fullflow.sh`로 reference run 생성** (보간 입력 = 각 run의 `p<P>_base/pt_vs_native_stage_compare.csv`): `bash run_fullflow.sh "146 153 ..." "..." run_0p75v` / `... run_0p55v`.
2. **`run_fullflow_unseen.sh` USER CONFIG 수정**: `TARGET_VDD=0.65`; `SRC_RUN=run_0p75v` + **`VREF=0.75`** (★ 0.8 고정 아님 — reference run의 실제 전압. 안 바꾸면 전압 스케일 비율 Vnew/Vref가 틀어짐); `INTERP_HI_RUN=run_0p75v INTERP_HI_VDD=0.75 INTERP_LO_RUN=run_0p55v INTERP_LO_VDD=0.55 INTERP_VTH=0.45`.
3. **시나리오**: 코너 1개뿐 → INTERP 비워둠(스킵), SRC_RUN/VREF만 그 코너로(b-1만). 감싸는 2개 → 위처럼 채움(crosstalk은 여전히 b-1 담당, 보간은 base 추가). 목표가 코너 밖 → 외삽 경고 출력, 정확도 미보장(감싸는 쌍 요청 권장).
4. **`INTERP_VTH`는 공정 의존**: SAED14=0.45 유지. 다른 공정이면 그 공정 대략 Vth 넣고, 검증 코너 있으면 ±0.05 스윕 캘리브레이션(±0.05→±1~2%라 둔감).
5. 풀플로우 없이 단독 실행: `python3 interp_pt_corner.py --hi-csv <run>/p146/p146_base/pt_vs_native_stage_compare.csv --hi-vdd 0.75 --lo-csv ... --lo-vdd 0.55 --target-vdd 0.65 --out-csv interp_p146.csv`.

**새 사이트 검증 순서 (데이터 형식 미상 대비, 상세=/home/KSW/code/RUN_GUIDE.md §F-2)**:
`0. 스모크(1-path 관통+단위 pf/ff+임계값 20-80/50+(V,T)목록+lib포맷) → 1. ref corner 풀플로우(판정표: cell gap ±수%, quiet≈SI-off ±3%=surrogate 신호, total 96~103%, repro 111~134%=정상) → 1.5 A→B retarget vs B실제PT (b-1 crosstalk 단독검증; 안 하면 3단계 오류원인 분리불가) → 2. A+C→B 보간 vs B실제PT (base검증+Vth ±0.05 캘리브레이션, 3코너↑면 leave-one-out=error bar) → 3. DK-less (crosstalk=b-1, base=보간, 외삽경고 주의, near-threshold는 base붕괴 가능, 2단계 오차 병기)`. 주의: 전 검증이 V-only·25°C — 코너쌍 T 다르면 검증범위 밖.

**입력 데이터 형식 + 암묵 가정 (상세=/home/KSW/code/RUN_GUIDE.md §F-3)**: 입력 9종(verilog/sdc/**coupled SPEF**(cc cap 보존, decoupled면 실험 불가; `read_parasitics -keep_capacitive_coupling`)/Liberty **.db**(lc_shell 변환)/cell `.SUBCKT` SPF(셀·핀명 Liberty 일치)/modelcard(`.lib TT`+`.param VDD` — retarget이 VDD param에 의존)/fixed tcl(회로별)/ml.csv/config json). 암묵 가정: **단일 전원도메인**(multi-V path 제외)·**flop-발 path**(input-port 시작 제외)·인스턴스명 정규식(escaped name 주의, measure 이름 잘림)·`.SUBCKT` 핀순서 `VDD VSS X ...`(well핀 있으면 고립플로우만 어긋남)·SPF↔modelcard 모델 섹션명 일치·HSPICE 토큰 수(동시 수십 개)·PT 버전(검증=W-2024.09-SP3)·디스크 path당 수GB·`cp -i` alias 함정. **사전 질문 4개: ①SPEF coupled? ②단일 전원 도메인? ③.db or .lib? ④HSPICE 토큰 수?**

---

## UG 근거 정리 (PrimeTime User Guide, `/home/KSW/User Guide/PrimeTime User Guide.pdf`)

- **crosstalk = net delay 성분 (명시)**: p.331 "static component = net delay without crosstalk; **dynamic component = change in net delay (delta delay) caused by crosstalk**". p.571 "delta delay = additional delay by crosstalk **on a switching net**, **includes fanout stage effect** as part of the delta delay". → PT가 crosstalk를 net에 booking + 하류(cell) 효과까지 net delta에 포함. **cell Δ=0은 verbatim 아니고 귀결+실측**.
- **cell로 옮기는 옵션 없음**: `set_annotated_delay -net -delta_only`(net 전용). PT는 crosstalk를 stage(cell+net)단위로 입력핀에 저장, `Delta` 컬럼 보고. cell arc delay는 Liberty값 유지. cell 물리영향은 ①net delta에 fanout포함 ②delta slew(`set_annotated_transition -delta_only`)로 우회, cell arc 안 바꿈.
- **align은 net arc·arc만 (p.1315)**: "aggressor alignment available for get_timing_arcs, **not get_timing_paths**"; "done **only for net timing arc, not cell timing arc**"; "chooses **same driving cell arc used during update_timing**"(=surrogate 근원). **이유**: crosstalk가 net 물리현상→정렬기준(victim net 천이)이 net arc에만; 정렬은 단일victim 최악화→다중victim인 path엔 모순+deck과대; net arc victim 천이 생성 위해 worst-arrival 구동핀 재사용→path진입핀과 다르면 surrogate.
- **mirror 물리**: 범프가 천이중(구동셀 유한임피던스) X 교차를 Δ 밀고 X-D0 RC결합으로 D0도 ~Δ. cell=X−A(A고정)→Δ잡힘, net=D0−X(둘다+Δ)→상쇄. 잔차=RC τ≈11ps. SPICE는 cell에·PT는 net에 = 거울, total 불변.

---

## 부록: 판정 원칙

- **재현율은 delta가 클수록 정확** — 소형 arc(<1ps)는 노이즈 지배로 37~101% 산포, 판정 근거로 약함.
- **비용 방식은 "정확도 보존" 우선** — G/J처럼 물리는 보존해도 정확도/비용이 안 맞으면 기각.
- **"동시 최악" 보수성은 phantom이 아니라 정량화 대상** — arc(개별 정렬 99%) vs full-path(동시 71%) gap이 그 실체.
