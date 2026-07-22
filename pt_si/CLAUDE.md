# CLAUDE.md — 현장 실행 지침 (on-site runbook)

이 파일은 이 패키지를 **다른 서버(기업 사이트)에서 실행할 때** Claude/사람이
바로 참고하도록 만든 실행 지침이다. 개념 설명이 아니라 "무엇을 세팅하고, 어떤
명령을 치고, 에러가 나면 어떻게 하는가"에 집중한다. 전체 개요는 `README.md`,
각 파이프라인 상세는 하위 `*/README.md` 를 본다.

## 이 패키지가 하는 일 (한 줄)

PrimeTime 으로 (1) 고정 경로를 여러 PVT 코너에서 재측정하며 Dist/Res/Cpin feature 를
붙이고(`pt_annotation/`), (2) 같은 축에서 crosstalk delta / victim–aggressor feature 를
뽑는다(`crosstalk_features/`). 산출 CSV/TSV/RPT 가 ML 학습 입력이다.

## 실행 전 체크 (5분)

```bash
which pt_shell          # 경로가 나오면 PT_SOURCE 불필요. 안 나오면 아래 PT_SOURCE 세팅
python3 --version       # 3.9 이상 필수 (3.6 이면 SyntaxError. 아래 트러블슈팅 참조)
python3 -c "import networkx"   # pt_annotation 에만 필요. 없으면 pip install -r pt_annotation/requirements.txt
```

PrimeTime 검증 버전: **V-2023.12-SP4**. SI/crosstalk 는 **PrimeTime SI 라이선스** +
**coupling cap 이 유지된 SPEF**(StarRC `COUPLING_CAP: YES`) 필요. grounded SPEF 로 SI 를
돌리면 러너가 pre-flight 에서 막는다(의도된 동작).

## 공통 환경변수

셸이 csh/tcsh 면 `setenv A B`, bash 면 `export A=B`. (이 프로젝트 원 서버는 csh)

| 변수 | 용도 | 없으면 |
|---|---|---|
| `PT_SOURCE` | `pt_shell` 을 PATH 에 올리는 사이트 셋업 스크립트 | `pt_shell` 이 이미 PATH 면 생략 가능 |
| `PT_LICENSE` | `LM_LICENSE_FILE` 값 (예: `27020@host`) | 라이선스가 이미 환경에 잡혀 있으면 생략 |
| `LC_ROOT` | Library Compiler 설치 루트 (pt_annotation) | 대개 생략 가능 |

## 파이프라인 1 — pt_annotation (fixed-path 스윕 + annotation)

CLI 인자로 경로를 준다(환경변수 아님). 기본값은 우리 BoomCoreV3 케이스라 **자기
디자인 값으로 바꿔야 한다.** 먼저 작은 범위로 확인 후 전체를 돌린다.

```bash
cd pt_annotation
# (필요시) setenv PT_SOURCE /site/pt_setup.cshrc

python3 run_sweep.py \
  --design MyCore --top MyCoreTop \
  --spef-prefix mycore_14nm \
  --mode setup --si \
  --verilog   /data/deliver/mycore_icc2.v \
  --sdc       /data/deliver/mycore.sdc \
  --spef-root /data/deliver/spef \
  --db-root   /data/lib_db/db  --lib-root /data/lib_db/lib \
  --ref-db    /data/lib_db/db/<ref_corner>.db \
  --out-dir   /data/results/mycore_setup_si \
  --max-paths 3000 --edge-aware-fixed-paths
```

주요 인자: `--mode setup|hold`, `--si`(SI on), `--rc-corners Cmax,Cnom,Cmin`,
`--ref-rc Cnom`, `--max-workers N`(병렬 코너 수 = PT 라이선스 소비 수),
`--spef-name-format`(기본 `{prefix}.starrc.{rc}_model_{temp}.spef`), `--spef-temp`.
전체 목록은 `python3 run_sweep.py --help`.

- SPEF 파일명 규약이 다르면 `--spef-name-format` 로 맞춘다.
- db 파일명에서 전압 토큰(`tt0p7v25c`→`0p7`)을 파싱하므로 db 이름이 이 규약과
  다르면 정렬이 깨진다. 다르면 `run_sweep.py` 상단 파싱부를 확인.
- 산출물: `<out-dir>/annotated/<RC>/<corner>_fixed_annotated.txt` (ML 입력).

## 파이프라인 2 — crosstalk path_context_sweep

**환경변수로** 디자인 입력을 준다. 기본값이 우리 smallboom 케이스라 반드시 덮어쓴다.

```bash
cd crosstalk_features/path_context_sweep
setenv XTALK_VERILOG     /data/deliver/mycore_icc2.v      # bash: export
setenv XTALK_SDC         /data/deliver/mycore.sdc
setenv XTALK_SPEF_DIR    /data/deliver/spef
setenv XTALK_SPEF_PREFIX mycore_14nm
setenv XTALK_DATA_ROOT   /data/mycore_iter                # annotation/ db/ 등이 있는 루트

# 먼저 dry-run 으로 어떤 job 이 돌고 입력이 다 있는지 확인
python3 run_sweep.py --dry-run
# 스모크: 코너 1개 + context 몇 개만
python3 run_sweep.py --analysis setup --corner Cnom --temp 25 --vtag 0p8 \
                     --max-contexts 20 --jobs 1
# 전체 (옵션 생략 시 setup+hold × 3 RC × 3 온도 × 17 전압 = 306 job)
python3 run_sweep.py --jobs 12
```

`--jobs` = 동시 PT 라이선스 소비 수. `--limit-jobs N`, `--force`(기존 RPT 재생성),
`--keep-work`(중간파일 보존). 산출물:
`crosstalk/<setup|hold>/<RC>/TT_<V>V_<T>C.path_context_si_compact.by_path.rpt` (14컬럼).
디자인명/전압·온도 목록 등 사이트 종속값은 `run_sweep.py` 상단
(`TEMPS`/`VOLTAGES`/`DB_STEM_FORMAT`/`Job`)에 모여 있다.

## 파이프라인 3 — crosstalk coupling_pair_features

단일 고정 경로(시작 FF ~ 끝 FF)에 대한 전압 스윕. **환경변수로** 준다.

```bash
cd crosstalk_features/coupling_pair_features
setenv XTALK_VERILOG    /data/deliver/mycore_icc2.v
setenv XTALK_SDC        /data/deliver/mycore.sdc
setenv XTALK_SPEF       /data/deliver/spef/mycore.Cnom_model_25.spef   # 전압 무관 1개
setenv XTALK_DB_DIR     /data/lib_db/db
setenv XTALK_OUT_DIR    /data/results/coupling_pair
setenv XTALK_START_CELL <시작 레지스터 인스턴스>
setenv XTALK_END_CELL   <끝 레지스터 인스턴스>

pt_shell -f extract_requested_si_features_unified.tcl
```

핵심 산출물: `<out>/requested_si_features_path1/requested_si_features.active_pairs.tsv`
(pair 별 crosstalk_delta, aggressor_bump, coupling_cap_ff, timing window 등).
db 파일명 패턴과 전압 목록(`VOLTAGES`)은 TCL 상단에서 수정.

## 라이선스 체크리스트 (현장에서 순서대로)

```bash
which pt_shell                                    # ① PT 가 PATH 에 있나 (없으면 PT_SOURCE 세팅)
echo $SNPSLMD_LICENSE_FILE $LM_LICENSE_FILE       # ② 라이선스 서버 env 잡혀 있나 (port@host)
lmutil lmstat -a -c $SNPSLMD_LICENSE_FILE | grep -i prime   # ③ PrimeTime 좌석 총/사용중 확인
```

- 러너들의 `--max-workers`/`--jobs` = **동시 pt_shell 프로세스 수 = 동시 라이선스 소비 수**.
  ③에서 확인한 **여유 좌석 이하**로 준다. 도구는 가용 좌석을 조회하지 않는다(단순 동시성 상한).
- pt_shell 1개 = PrimeTime base 1석. `--si`/`SI=1` 이면 **PrimeTime-SI 1석 추가** 소비.
- 좌석 초과 시 "unable to checkout license" 로 해당 job 실패.
  `extract_violation_paths.py` 는 실패 코너를 건너뛰고 계속 진행(summary 에 FAILED, exit 2);
  다른 러너는 해당 job 이 실패로 남는다. 좌석 확보 후 재실행.
- 사이트에 따라 Synopsys 라이선스 큐잉(실패 대신 대기) 정책을 쓰기도 한다 — CAD 팀에 확인.

## 트러블슈팅 (실제로 겪은 것들)

| 증상 | 원인 | 해결 |
|---|---|---|
| `SyntaxError` / `from __future__` 관련 실패 | 시스템 `python3` 이 3.6 | 3.9+ python 을 PATH 앞에 두거나 그 인터프리터로 직접 실행. 러너는 하위 파서를 `sys.executable` 로 호출하므로 러너를 3.9+ 로 띄우면 파서도 따라온다 |
| SI 결과가 이상/무의미 | grounded SPEF (coupling cap 없음) | `COUPLING_CAP: YES` 로 재추출한 SPEF 사용. pt_annotation 은 pre-flight 로 자동 중단 |
| `read_parasitics` 후 coupling 이 안 잡힘 | `-keep_capacitive_coupling` 누락 | SI 경로는 `--si`/`SI=1` 로 돌려야 tcl 이 이 옵션을 켠다 |
| db 코너 정렬이 뒤죽박죽 | db 파일명이 `tt0pNvNNc` 전압 토큰 규약과 다름 | 파일명을 규약에 맞추거나 러너 상단 파싱부 수정 |
| SPEF 를 못 찾음 | 파일명 포맷 불일치 | pt_annotation `--spef-name-format`, crosstalk 는 `XTALK_SPEF_PREFIX`/상단 포맷 확인 |
| PT 라이선스 부족으로 job 대기/실패 | `--max-workers`/`--jobs` 가 가용 라이선스 초과 | 값을 낮춘다 (가용 SI 라이선스 수 이하) |
| Res/Cpin/시간 값 스케일이 예상과 다름 | 코드가 SPEF `*R_UNIT`/`*C_UNIT`/`*L_UNIT`·Liberty 단위를 정규화하지 않고 **원시값 그대로** 사용 | SPEF 헤더 단위(OHM vs KOHM, FF vs PF 등)와 PT 시간 단위를 확인. 출력 단위 = 입력 단위. **서로 다른 단위의 데이터셋을 한 학습셋에 섞지 말 것** (한 데이터셋 내부는 통일되어 문제없음) |
| N/A 매칭 실패가 대량 발생 | SPEF/netlist 이름 규약이 코드가 아는 평탄화 변형과 다름 (다른 추출 툴/표기) | 이름 매칭 실패는 CONN(핀 연결) 매칭이 대부분 흡수하나, 인스턴스·핀 토큰까지 다르면 뚫린다. `res.py` 의 `bus_flatten_variants`/평탄화 규칙을 그쪽 SPEF 규약에 맞게 확장. N/A 는 `summary` 의 `na_tokens`/`na_lines` 로 자가 집계되니 돌려보면 감지된다 |

## Claude 에게 시킬 때 (권장 프롬프트)

> "이 패키지 `CLAUDE.md` 와 `pt_annotation/README.md` 를 읽고, 우리 디자인은
> `<디자인명>`, 넷리스트/SDC/SPEF/db 는 `<경로>` 에 있어. 먼저 `--help` 로 인자
> 확인하고, 코너 1개 + `--max-contexts`(또는 작은 범위)로 스모크 테스트한 뒤
> 결과가 정상이면 전체를 돌리는 명령을 제안해줘. 우리 서버 `pt_shell` 경로와
> 라이선스도 먼저 확인해줘."

**항상 작은 범위(1 코너 / dry-run / max-contexts)로 먼저 확인한 뒤 전체를 돌린다.**
전체 스윕은 코너 수 × 파일 I/O 가 커서 시간이 오래 걸린다.
