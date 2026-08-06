# pt_annotation — Fixed-Path Voltage Sweep + Dist/Res/Cpin Annotation

reference 코너에서 worst timing path 들을 뽑아 **경로 정의(fixed path)로 박제**한 뒤,
전압/RC/SI 코너를 바꿔가며 **정확히 같은 경로**를 재측정하고, 각 net 구간에
SPEF/Liberty 기반 feature 3종(Dist/Res/Cpin)을 붙인다. 코너가 바뀌어도 동일한 물리
경로를 보므로 cross-corner delay 차이를 ML label 로 쓸 수 있다.

## 흐름

```
[ref db + ref SPEF]
   │ tcl/run_ref_topk.tcl            report_timing -nworst … topK 경로 추출
   ▼
ref_topK.rpt
   │ (runner 내장) write_fixed_tcl_from_ref_report
   ▼
fixed_paths.tcl                      {path_key from_pin to_pin {through…}} 목록
   │ tcl/run_corner_fixed.tcl        ref 재타이밍
   │ res.py                          ref annotate
   │ make_strict_fixed_paths_tcl.py  strict 버전 생성 (edge-aware 선택)
   ▼
strict_fixed_paths.tcl               ← 모든 코너가 공유하는 경로 정의
   │
   │ RC 코너(Cmax/Cnom/Cmin) 병렬 × 전압 순차:
   │   tcl/run_corner_fixed.tcl → <corner>_fixed.rpt
   │   res.py / 캐시 → <corner>_fixed_annotated.txt
   ▼
annotated/<RC>/<corner>_fixed_annotated.txt   ← 최종 산출물
```

같은 RC 코너는 전압에 무관하게 SPEF 1개를 공유하므로, 그룹 첫 코너만 full
annotation 을 수행하고 이후 코너는 Dist/Res 캐시를 재사용한다(fast path).
캐시 미스 시 자동으로 full annotation 으로 fallback 한다.

## Annotation 컬럼 (res.py)

각 `(net)` 라인 뒤에 3컬럼을 추가:

| 컬럼 | 정의 | 출처 |
|---|---|---|
| `Dist` | driver 핀 ↔ receiver 핀 맨해튼 거리 | SPEF `*C` 좌표 |
| `Res` | driver→receiver 최단 경로 저항 (가중 shortest path) | SPEF `*RES` 그래프 (networkx) |
| `Cpin` | receiver 입력 핀 capacitance | Liberty `.lib` (fallback: SPEF `*L`) |

SPEF `*NAME_MAP` 의 계층 평탄화 변형(`a/b/c/d` ↔ `a/b/_c_d` 등)을 자동 매칭한다.
매칭 실패 시 해당 값은 `N/A` 로 남고 개수가 summary 에 집계된다.

> **단위 주의.** 이 코드는 SPEF `*R_UNIT`/`*C_UNIT`/`*L_UNIT` 와 Liberty 단위
> 선언을 **정규화하지 않고 원시값 그대로** Dist/Res/Cpin 에 기입한다. 즉
> **출력 단위 = 입력 SPEF/Liberty 의 단위 선언을 그대로 따른다** (예: `R_UNIT 1.0
> OHM` 이면 Res 는 옴, `1.0 KOHM` 이면 킬로옴; `C_UNIT` FF vs PF 도 동일).
> Dist 는 SPEF `*C` 좌표 단위(통상 µm)를 따른다. 실행 전 SPEF 헤더의 단위를
> 확인하고, **서로 다른 단위의 데이터셋을 한 학습셋에 섞지 말 것.** 한 데이터셋
> 안에서는 단위가 통일되므로(상대 비교) 문제없다.

## 파일

> **실행은 `run_sweep.py` 하나면 된다.** `ptann_lib.py`·`res.py`·
> `make_strict_fixed_paths_tcl.py`·`tcl/*` 는 러너가 내부에서 자동 호출하므로
> 직접 실행할 필요가 없다 (단, `res.py` 는 이미 뽑아둔 리포트에 annotation 만
> 다시 붙일 때 단독 실행도 가능 — `--help` 참조). `qc/*` 만 사후 검증용으로
> 별도 실행한다.

| 파일 | 역할 |
|---|---|
| `run_sweep.py` | 메인 러너 (topK 추출 → fixed path → 코너 스윕 → annotation) |
| `ptann_lib.py` | 공용 라이브러리 (report 파싱, 캐시, pt_shell 실행, fixed-tcl 생성) |
| `res.py` | Dist/Res/Cpin annotation 엔진. 단독 실행도 가능 (`--help` 참조) |
| `make_strict_fixed_paths_tcl.py` | annotated ref report → strict `FIXED_PATHS` tcl |
| `tcl/run_ref_topk.tcl` | topK 경로 report 생성 (env `SI=1` 이면 SI 분석) |
| `tcl/run_corner_fixed.tcl` | fixed path 재측정 report 생성 (env `SI=1` 이면 SI 분석) |
| `tcl/report_fixed_paths.tcl` | `FIXED_PATHS` 목록을 따라 report_timing 하는 공용 proc |
| `qc/check_fixed_path_edge_consistency.py` | 전압 간 동일 path/edge 일관성 + monotonic 위반 분류 |
| `qc/analyze_pt_slew_load_coverage.py` | PT 사용 slew/load 가 Liberty grid 범위 내인지 (외삽 검출) |
| `qc/compare_si_on_off_arrival_fast.py` | SI on/off arrival/slack delta 정량화 |

## 실행 예시

> **다른 디자인에 적용할 때 바꿀 것.** 사이트 종속값은 전부 **CLI 인자로 주입**한다
> (코드 수정 불필요). 인자 기본값은 내부 BoomCoreV3 케이스이므로 반드시 덮어쓴다:
> `--design/--top/--spef-prefix` (디자인), `--verilog/--sdc/--spef-root/--db-root/`
> `--lib-root/--ref-db` (경로). SPEF 파일명 규약이 다르면 `--spef-name-format`,
> 온도 토큰은 `--spef-temp` 로 맞춘다. db 파일명은 `tt0pNvNNc` 전압 토큰 규약을
> 따라야 정렬된다 (다르면 파일명을 맞추거나 `run_sweep.py` 상단 `volt_token` 파싱부 수정).

```bash
export PT_SOURCE=/path/to/site_prime_setup.sh   # pt_shell 이 PATH 에 없을 때만
pip install -r requirements.txt

python3 run_sweep.py \
  --design MyCore --top MyCore \
  --spef-prefix mycore_14nm \
  --mode setup --si \
  --verilog  /data/deliver/mycore_14nm_icc2.v \
  --sdc      /data/deliver/mycore_14nm.sdc \
  --spef-root /data/deliver \
  --db-root  /data/lib_db/db --lib-root /data/lib_db/lib \
  --ref-db   /data/lib_db/db/saed14rvt_tt0p8v25c_ccs_vendor.db \
  --out-dir  /data/results/mycore_setup_si \
  --max-paths 3000 --edge-aware-fixed-paths
```

> **주의 — 이 예시(run_sweep.py)는 "worst top-N" 추출이다.** `--max-paths 3000` 은
> "가장 나쁜 3000개"를 뽑는 것이므로 violation 이 그보다 많으면 **전부를 담지
> 못한다.** "violation 전부(+위반 위험 리스트)" 가 필요하면 아래
> **"위반/위험 경로 전수 추출 (extract_violation_paths.py)"** 섹션의 방식을 쓴다
> (slack 임계 기반 전수 추출 → `--emit-fixed-paths-tcl` → 본 러너의
> `--reuse-strict-tcl` 로 연결).

- `--mode setup|hold` → `report_timing -delay_type max|min`
- `--si`: PrimeTime SI + `read_parasitics -keep_capacitive_coupling`.
  실행 전 SPEF 에 coupling cap 이 실재하는지 pre-flight 검사하며, 없으면 즉시 중단
  (grounded SPEF 로 SI 를 돌리면 무의미한 결과가 나오기 때문)
- SPEF 파일명 규약: `<spef-prefix>.starrc.<RC>_model_25.spef` (RC = Cmax/Cnom/Cmin)
- db 파일명에서 전압 토큰(`tt0p7v25c` → `0p7`)을 파싱해 정렬한다

## 산출물

```
<out-dir>/
  ref_<mode>_top<K>_<refdb>_<RC>.rpt        ref topK report
  <prefix>_<mode>_strict_fixed_paths_<K>.tcl 경로 정의 (전 코너 공유)
  reports/<RC>/<corner>_fixed.rpt            코너별 재측정 report
  annotated/<RC>/<corner>_fixed_annotated.txt  ← ML 입력
  summary.txt                                코너별 mode/N-A 카운트
  run.log, logs/<RC>.log
```

산출물이 어떻게 생겼는지는 **`example_annotated_excerpt.txt`** 참조 — 실제 run 의
annotated 파일에서 FIXED_PATH 2개 블록을 발췌한 것으로, `(net)` 라인 끝의
Dist/Res/Cpin 3컬럼이 이 파이프라인이 추가하는 feature 다.

## QC 권장 순서

1. `qc/check_fixed_path_edge_consistency.py --reports-dir <out>/reports/<RC>` —
   전압 간 path/edge 일치 확인 (label 유효성의 전제)
2. `qc/analyze_pt_slew_load_coverage.py --lib <대표.lib> --reports <out>/reports` —
   Liberty grid 외삽 비율 확인
3. SI 데이터라면 `qc/compare_si_on_off_arrival_fast.py` 로 SI 영향량 분포 확인

## 다른 공정(SS/FF) / BEOL 코너로 확장

현재 스윕 축은 **전압 × RC × 온도**(공정은 단일 TT)이다. 축을 확장할 때 손볼
지점을 아래에 모은다. (crosstalk·SPEF 추출 쪽 확장 지점은 각각
`../crosstalk_features/README.md`, `../spef_extraction/README.md` 참조.)

- **공정 코너(SS/FF/SSG 등) db 파일명** — 공정(SS/FF)은 **트랜지스터 라이브러리
  (.db/.lib)** 축이라 이 파이프라인의 db 선택에 영향을 준다. db 이름에서 전압을
  뽑는 정규식 `VOLT_RE`(`run_sweep.py` 상단)는 `<V>v<T>c` 접미사로 잡으므로
  `tt`/`ss`/`ff`/`ssg` 등 **접두사와 무관하게 이미 동작**한다. SS/FF db(`ss…`,
  `ff…`)를 `--db-root`/`--lib-root`/`--ref-db` 로 주면 그대로 인식된다. 단 파일명
  안에 `…p…v…c` 형태의 전압 토큰이 **하나만** 있어야 오탐이 없다(둘 이상이면
  `re.search` 가 첫 번째를 잡으므로 그 규약이면 `VOLT_RE` 를 더 좁힌다). **SPEF 는
  SS/FF 와 무관**하므로 `--spef-root`/`--spef-prefix` 는 그대로 둔다. 여러 공정을
  동시에 넣기보다 공정별로 `--db-root` 를 분리해 각각 스윕하는 편이 라벨이 깔끔하다.
- **RC(BEOL) 코너 이름 변경** — 값은 `--rc-corners`/`--ref-rc` 로 주지만, 현재
  기본 집합(`RC_CORNERS = ("Cmax","Cnom","Cmin")`)에 없는 이름은 **거부된다**
  (`unknown RC corner` 로 종료). 다른 BEOL 코너 이름을 쓰려면 `run_sweep.py` 상단
  `RC_CORNERS` 튜플에 그 이름을 추가하거나, 검증(`if rc not in RC_CORNERS: …`)을
  경고로 완화한다. 코너 이름은 `--spef-name-format` 의 `{rc}` 로 SPEF 파일명에 들어간다.

## 위반/위험 경로 전수 추출 (extract_violation_paths.py)

`run_sweep.py` 는 **ref 코너 한 곳**에서 top-N(nworst/max_paths) worst 경로를 뽑아
그 경로를 "박제"한 뒤 전 코너에서 **동일 경로**를 재측정한다.
`extract_violation_paths.py` 는 **추출 정책이 다르다**: hidden corner 를 제외한
**모든 측정 코너 각각**에서 slack 이 임계값(TH) 미만인 path 를 **전부** 뽑아
(startpoint,endpoint) 페어 단위로 **union** 한다. 코너마다 critical path 가 다를 수
있으므로, "ref 한 곳의 worst-N" 이 아니라 "코너별 위반/위험 리스트의 합집합" 이
필요할 때 쓴다. 예: hidden corner 를 빼고 나머지 코너들의 위반 경로를 모두 모아
학습·검증 대상 경로 집합을 만들 때.

측정 코너 = (RC 코너 × 전압 코너) 조합이다. 각 조합마다 기존
`tcl/run_ref_topk.tcl` 을 `report_timing -nworst NWORST -max_paths MAX_PATHS
-slack_lesser_than SLACK_TH` 로 실행해 "slack < TH 인 path 전부"를 리포트한 뒤 파싱한다.

### 인자

`--design/--top/--spef-prefix/--mode/--si/--verilog/--sdc/--spef-root/`
`--spef-name-format/--spef-temp/--db-root/--lib-root/--out-dir/--extra-libs/`
`--force-basic-rc` 는 `run_sweep.py` 와 **동일 관례**다(위 실행 예시 참조).
아래는 이 도구 고유 인자.

| 인자 | 기본값 | 의미 |
|---|---|---|
| `--slack-threshold` | `0.05` | slack < TH 인 path 만 추출. **단위는 SDC 시간 단위**(통상 ns) → 기본 `0.05` = **50ps 마진**, 즉 위반 + 위반 위험을 함께 뽑는다. `0.0` 을 주면 violation 만. |
| `--nworst` | mode 분기 (**setup 3 / hold 10**) | endpoint 당 최대 리포트 path 수 = **고정 정책값** (endpoint 당 상위 후보 몇 개를 담을지). hidden corner 에서 endpoint 내 순위가 뒤바뀔 수 있어 상위 몇 개를 확보하는 것이 목적이며, hold 는 짧은 경로가 촘촘해 조금 더 크게 잡는다. 위반이 많은 데이터에서는 truncated 가 떠도 **올리지 않는 것을 권장** — 올리면 `--max-paths` 예산을 소수 endpoint 가 깊이로 잠식해 endpoint 커버리지(폭)가 줄어든다. |
| `--max-paths` | `50000` | 코너당 리포트 path **안전 상한**. 리포트 path 수가 이 값과 같으면 잘렸을 수 있으므로 summary 에 `TRUNCATED?` 경고를 표기한다. |
| `--rc-corners` | `Cmax,Cnom,Cmin` | 스윕할 SPEF RC 코너 콤마 목록. |
| `--exclude-vtags` | (없음) | 제외할 전압 태그 콤마 목록(**hidden corner**). 예: `0p75,0p795` → 그 전압 코너를 측정 목록에서 뺀다. |
| `--max-workers` | `3` | 병렬 실행 코너 수(= 동시 PT 라이선스 소비 수). |
| `--emit-fixed-paths-tcl` | off | path-level union 전체를 기존 `FIXED_PATHS` tcl 로 내보낸다(`<out-dir>/<design>_<mode>_violation_fixed_paths_<N>.tcl`). `run_sweep.py --reuse-strict-tcl` 이 그대로 소비. |
| `--fixed-through-count` | `0` | 경로당 `-through` 핀 수. **0 = 내부 데이터 핀 전부**(`make_strict_fixed_paths_tcl.py` 와 같은 strict 정책, 권장). 양수를 주면 그 개수만 균등 샘플링(하위 호환) — 아래 경고 참조. |
| `--edge-aware-fixed-paths` | off | 각 핀의 전이 방향(r/f)을 5번째 필드로 실어 `-rise_from`/`-fall_through` 로 엣지까지 고정. `run_sweep.py` 의 동명 옵션과 같은 효과. 전체 체인(`--fixed-through-count 0`)일 때만 적용된다. |

> **`--emit-fixed-paths-tcl` 로 만든 tcl 은 `--reuse-strict-tcl` 자리에 들어간다 —
> 즉 `make_strict_fixed_paths_tcl.py` 단계를 대체한다.** `run_sweep.py` 는
> `--reuse-strict-tcl` 이 주어지면 strict tcl 생성 단계를 통째로 건너뛰므로
> (`run_sweep.py:366`), 여기서 내보내는 tcl 이 **strict 와 같은 등급**이어야 한다.
> 그래서 through 기본값이 "전체 체인"이고, 엣지 고정이 필요하면
> `--edge-aware-fixed-paths` 를 여기서 켜야 한다(run_sweep 쪽에 줘도 무시됨).
>
> **샘플링(`--fixed-through-count N>0`)을 쓰면 안 되는 이유.** union 의 경로 정체성은
> 전체 핀 체인인데 `-through` 제약만 일부면, 같은 `(start,end)` 를 공유하면서 샘플
> 지점 밖에서만 갈리는 **쌍둥이 경로**들의 제약이 완전히 같아진다. `report_fixed_paths.tcl`
> 은 항목마다 `-max_paths 1 -sort_by slack` 으로 리포트하므로 둘 다 worst 하나로
> 수렴 → **한쪽은 중복 측정되고 다른 쪽은 통째로 누락**되며, 이 사고는 조용히 일어난다
> (summary 에 경고가 안 뜬다). 예: 내부 핀 11개에 `N=8` 이면 샘플러는 인덱스
> 1,2,3,4,6,7,8,9 만 집어 **0/5/10 에서 갈리는 경로 쌍을 구분하지 못한다.**

> **nworst 는 고정 정책값(setup 3 / hold 10).** union 의 목적은 "위험한 endpoint 를
> **넓게** 커버하되, endpoint 마다 상위 후보 몇 개(순위 교체 대비)를 확보하는 것"
> 이다. endpoint 별 1등만 보면 다른 코너에서 2등이 1등으로 올라오는 경로를 놓치므로
> 상위 N 개를 담고, hold 는 짧은 경로가 촘촘해 조금 더 깊게 잡는다.
> **truncated=0 을 목표로 nworst 를 올리는 방식은 권장하지 않는다** — 위반이 많은
> 데이터에서는 endpoint 당 TH 안쪽 path 가 수십 개라 nworst 가 폭주하고, 그러면
> `--max-paths` 예산을 소수 endpoint 가 깊이로 잠식해 **endpoint 커버리지(폭)가
> 무너진다**(깊이 vs 폭 트레이드오프). 아래 자가진단은 "얼마나 잘렸는지"를 알려주는
> **정보성 지표**로 쓰고, endpoint 별 전수 열거가 정말 필요할 때만 `--max-paths` 와
> 함께 올린다.

> **TH 의미.** `--slack-threshold 0.0` 은 **위반(violation) 경로만**,
> 양수 TH 는 **위반 + 위반 위험(risky) 경로**를 함께 뽑는다. 위험 마진을 넓힐수록
> 코너별 path 수가 늘고 union 도 커진다(단, `--max-paths` 상한에 걸려 잘리면 비교가
> 무의미해지므로 상한을 넉넉히 준다).
>
> **기본값은 `0.05`(= SDC 단위가 ns 일 때 50ps 마진)** 로, 위반과 위험을 한 번에
> 담는 쪽을 택했다. 뽑은 뒤 **위반만 보고 싶으면 CSV 에서 걸러내면 되지만**
> (`n_corners_violating > 0`), 반대로 TH 를 좁게 잡고 돌린 뒤 위험 경로를 되살릴
> 방법은 없다 — 리포트 자체에 안 남아 **재실행뿐**이다. 그래서 기본을 넓게 둔다.
>
> ⚠️ **SDC 시간 단위가 ns 가 아니면 0.05 는 50ps 가 아니다.** 클럭 주기가 ps 나 다른
> 스케일로 쓰인 디자인이면 TH 도 그 스케일로 환산해서 준다
> (`grep -i units <design>.sdc` 또는 `report_units` 로 확인).

### 실행 예시

```bash
export PATH=/path/to/pt/bin:$PATH          # 또는 export PT_SOURCE=/path/to/setup.sh

python3 extract_violation_paths.py \
  --design MyCore --top MyCore \
  --spef-prefix mycore_14nm \
  --mode setup \
  --verilog  /data/deliver/mycore_icc2.v \
  --sdc      /data/deliver/mycore.sdc \
  --spef-root /data/deliver/spef \
  --spef-name-format '{prefix}.{rc}_model_{temp}.spef' --spef-temp 25 \
  --db-root  /data/lib_db/db --lib-root /data/lib_db/lib \
  --rc-corners Cmax,Cnom,Cmin \
  --exclude-vtags 0p795 \
  --slack-threshold 0.05 \
  --max-paths 50000 --max-workers 3 \
  --emit-fixed-paths-tcl --edge-aware-fixed-paths \
  --out-dir  /data/results/mycore_violscan_setup

# ── 2단계: 위에서 emit 된 tcl 을 run_sweep 에 물려 재측정 + annotation ──
python3 run_sweep.py \
  --design MyCore --top MyCore \
  --spef-prefix mycore_14nm \
  --mode setup \
  --verilog  /data/deliver/mycore_icc2.v \
  --sdc      /data/deliver/mycore.sdc \
  --spef-root /data/deliver/spef \
  --spef-name-format '{prefix}.{rc}_model_{temp}.spef' --spef-temp 25 \
  --db-root  /data/lib_db/db --lib-root /data/lib_db/lib \
  --ref-db   /data/lib_db/db/<아무 측정 코너>.db \
  --reuse-strict-tcl /data/results/mycore_violscan_setup/MyCore_setup_violation_fixed_paths_<N>.tcl \
  --out-dir  /data/results/mycore_violscan_annotated
# → annotated/<RC>/<corner>_fixed_annotated.txt (union 경로들의 코너별 재측정 + Dist/Res/Cpin)
```

> `--reuse-strict-tcl` 을 쓰면 run_sweep 의 `--edge-aware-fixed-paths` /
> `--max-fanout` / `--max-paths`(top-N 추출용) 는 **적용되지 않는다** — strict tcl
> 생성 단계 자체를 건너뛰기 때문이다. 엣지 고정은 1단계(extract)에서 켠다.
> `--max-fanout` 상당의 필터는 이 route 에 없으므로, fanout 이 큰 넷이 낀 경로를
> 빼고 싶으면 `union_paths_bypath.csv` 를 후처리해 tcl 을 걸러 쓴다.

**2단계 후 필수 QC.** 코너 간 경로/엣지가 실제로 유지됐는지 확인한다:

```bash
python3 qc/check_fixed_path_edge_consistency.py \
  --reports-dir /data/results/mycore_violscan_annotated/reports/Cnom
```

### 산출물

```
<out-dir>/
  rpts/<RC>/<corner>.rpt        코너별 원본 report_timing 리포트(slack<TH path 전부)
  csv/per_corner.csv            corner,rc,vtag,startpoint,endpoint,slack,arrival,status,
                                rank,endpoint_truncated
                                (모든 occurrence. 같은 (start,end)가 nworst 로 여러 번 나오면
                                 코너 내부에서 slack 오름차순 rank 1..k 부여, 전부 기록.
                                 endpoint_truncated = 그 endpoint 가 nworst 상한에 걸렸을
                                 수 있는지 자가진단 플래그)
  csv/union_paths.csv           (start,end) **페어 단위** union(거친 수준). 컬럼:
                                  startpoint,endpoint,
                                  n_corners_violating (slack<0 인 코너 수),
                                  n_corners_risky     (slack<TH 인 코너 수),
                                  worst_slack, worst_corner,
                                  slack__<RC>__<vtag> ... (코너별 worst slack 와이드 컬럼)
  csv/union_paths_bypath.csv    **경로(path) 단위** union(=downstream 호환 단위). 컬럼:
                                  path_idx(1..N, worst_slack 오름차순),
                                  startpoint,endpoint,n_through,
                                  n_corners_violating,n_corners_risky,
                                  worst_slack,worst_corner,
                                  slack__<RC>__<vtag> ...
                                  같은 (start,end)라도 through 가 다르면 별도 행.
  csv/truncated_endpoints.csv   nworst 상한에 걸렸을 수 있는 endpoint 상세(자가진단):
                                  rc,vtag,corner,endpoint,n_paths,worst_rank_slack,nworst
  <design>_<mode>_violation_fixed_paths_<N>.tcl
                                (--emit-fixed-paths-tcl 일 때만) path-level union 전체를
                                 기존 FIXED_PATHS 형식으로 내보낸 tcl. run_sweep
                                 --reuse-strict-tcl 이 그대로 소비한다.
  summary.txt                   코너별 위반/위험 path·pair 수, pair/path union 크기,
                                 코너 간 매칭 통계, nworst 자가진단, TRUNCATED 경고
  run.log, logs/<RC>.log        실행 로그
```

- **per_corner.csv** = 코너별 원본(중복 포함). **union_paths.csv** = (start,end) **페어**당
  코너별 worst. **union_paths_bypath.csv** = **경로(signature=start,end,through)**당 코너별
  worst — 같은 FF쌍이라도 through 다른 별개 물리 경로를 구분한다. 둘 다 `worst_slack`
  오름차순 정렬. 항상 `path 행수 >= pair 행수`.
- **경로 단위가 downstream 과 호환되는 단위다.** 기존 파이프라인이 FIXED_PATH idx +
  through 로 경로 정체성을 유지하는 이유가, 같은 FF쌍 사이에도 through 가 다른 별개
  물리 경로가 있기 때문이다. `--emit-fixed-paths-tcl` 로 path-level union 을 그대로
  `FIXED_PATHS` tcl 로 떨궈 `run_sweep.py --reuse-strict-tcl` 에 물릴 수 있다. through 는
  각 경로의 **worst corner** rpt 체인에서 **내부 데이터 핀 전부**를 기록한다
  (`make_strict_fixed_paths_tcl.py` 와 동일한 strict 정책). `--edge-aware-fixed-paths`
  를 켜면 그 worst corner 의 핀별 전이 방향(r/f)도 함께 실린다.
- 한 코너의 리포트 path 수가 `--max-paths` 와 같으면 잘렸을 수 있어(=globally-worst
  전부를 담지 못함) summary 에 `TRUNCATED?` 를 붙인다. 잘린 코너는 pair 수준 비교가
  불안정하므로 `--max-paths` 를 키워 재실행한다.

### nworst 충분성 자가진단 (endpoint 단위)

`--nworst` 의 적절한 값은 **디자인 종속**이다(endpoint 당 촘촘한 정도가 회로마다
다름). 따라서 우리 데이터에서 고른 값이 다른 사이트로 그대로 이식되지 않는다. 이
도구는 **스스로 nworst 가 부족한지**를 판정한다.

- 원리: `report_timing -nworst N` 은 endpoint 마다 최대 N 개 path 를 리포트한다.
  어떤 endpoint 가 N 개를 꽉 채웠고(마지막 순위 `rank==N` 의 path 도 여전히
  `slack < TH`), 그 아래 순위에 TH 안쪽 후보가 더 있을 수 있으면 그 endpoint 를
  **"possibly truncated"** 로 표시한다. N 개 미만이면 TH 안쪽 path 를 모두 소진한
  것이므로 truncated 아님.
- 산출: `summary.txt` 와 stdout 에 **코너별 truncated endpoint 수**
  (`nworst_trunc_eps`)와 전체 합(`NWORST_TRUNCATED_ENDPOINTS_TOTAL`), 그리고
  `MAX_RANK_OBSERVED`(실제 관측된 endpoint 당 최대 path 수)를 표기한다. 상세 목록은
  `csv/truncated_endpoints.csv`, per-path 플래그는 `per_corner.csv` 의
  `endpoint_truncated` 컬럼에 있다.
- **해석(중요): 이 지표는 정보성이다 — truncated>0 이어도 nworst 를 올리라는 뜻이
  아니다.** 위반이 많은 데이터에서는 endpoint 당 TH 안쪽 path 가 수십 개라 대부분의
  endpoint 가 상한에 닿는 것이 정상이며, nworst 는 "endpoint 당 상위 후보 N 개" 라는
  **고정 정책값**으로 운용한다. truncated 를 0 으로 만들려고 올리면 nworst 가
  폭주하고, `--max-paths` 예산을 소수 endpoint 가 잠식해 endpoint 폭이 무너진다.
  endpoint 별 **전수 열거**가 정말 필요한 특수한 경우에만 `--max-paths` 를 함께
  키우며 올린다.

> 이 자가진단은 코너 전체 상한인 `--max-paths` `TRUNCATED?` 경고와 **별개 항목**이다.
> 그건 코너당 총 path 상한, 이건 endpoint 단위 nworst 상한이다.

### 알려진 상황/제약 (extract_violation_paths.py)

| 상황 | 동작/대처 |
|---|---|
| db-root 에 같은 전압 db 2개(온도/스타일 혼재) | **에러로 중단** — 코너 키가 (RC×전압)이라 충돌. 온도별로 db-root 분리 |
| db 온도 토큰 ≠ `--spef-temp` (예: v125c db + 25C SPEF) | **경고 출력** — db·SPEF 온도 불일치는 물리적으로 비일관 |
| 일부 코너 실패(라이선스 부족 등) | **계속 진행** — summary 에 `FAILED` 목록, union 은 부분 결과, **exit code 2**. 원인 해결 후 재실행 |
| union 이 0 페어 | 위반/위험이 없는 것. 위험 리스트가 필요하면 `--slack-threshold` 를 올려서 재실행 |
| 같은 (start,end) 페어의 **다른 through 경로** | **path-level union 으로 해소됨.** `union_paths_bypath.csv` 가 through 시퀀스까지 넣은 signature 단위로 별개 물리 경로를 구분하고, `--emit-fixed-paths-tcl` 로 그 경로들을 기존 `FIXED_PATHS` tcl(run_sweep `--reuse-strict-tcl` 호환)로 내보낸다. tcl 의 `-through` 도 **전체 체인**이라 쌍둥이 경로가 PT 에서 같은 경로로 수렴하지 않는다(`--fixed-through-count 0`, 기본). `union_paths.csv`(페어 단위)는 거친 요약으로 함께 제공 |
| 코너마다 rise/fall **worst 가 뒤바뀜** | `--edge-aware-fixed-paths` 로 해소. 끄면 같은 `idx` 에 전압별로 rise 경로와 fall 경로가 섞여 들어가 cross-corner delta 가 오염될 수 있다. 켜지 않았다면 `qc/check_fixed_path_edge_consistency.py` 로 반드시 확인 |
| 코너 간 **경로 매칭** | signature=(startpoint,endpoint,데이터-핀 튜플). 같은 넷리스트를 공유하므로 through 핀 이름이 코너 무관하게 동일 → 같은 물리 경로는 코너 간 byte-identical signature 로 매칭된다(라이브러리 celltype 차이는 핀 이름을 바꾸지 않아 매칭에 영향 없음). 서로 다른 코너에서 endpoint 의 worst 가 **다른 물리 경로**로 바뀌는 것은 매칭 실패가 아니라 실제 현상 — `--nworst` 를 올리면 양쪽 경로가 두 코너에 다 잡혀 매칭된다 |
| 데이터-핀 체인이 없는 경로(포트 시작/끝 등 FF-Q..FF-D 아님) | `union_paths_bypath.csv` 에는 `(start,end,())` 로 병합되어 남지만 `FIXED_PATHS` tcl 에는 실리지 않는다(기존 fixed-path 파이프라인도 이런 경로는 skip). summary 의 `PATHS_NO_DATA_CHAIN` 로 개수 집계 |
| 다중 클럭/path group 디자인 | `report_timing` 이 전 path group 을 함께 리포트 — slack 의 기준 클럭이 페어마다 다를 수 있다. 그룹별 분리가 필요하면 rpt 의 Path Group 을 참조해 후처리 |
| reg2reg 만 원할 때 | 필터 없음(IO 경로 포함). endpoint/startpoint 이름 패턴으로 CSV 후처리 |
| slack/TH 단위 | SDC 시간 단위 그대로(통상 ns). 클럭 주기가 다른 디자인이면 TH 도 그 스케일로 |
| 리포트 용량 | `--max-paths` 를 크게 주면 rpts/ 가 커진다(full 포맷). 디스크 여유 확인 |
| PT 버전 | 파서는 V-2023.12-SP4 리포트 형식으로 검증됨. 다른 버전에서 slack 라인 형식이 다르면 파서 정규식 확인 |
