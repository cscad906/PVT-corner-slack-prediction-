# PVT Cross-Corner Delay Prediction — Handoff Release

ML 기반 PVT cross-corner delay 예측 프로젝트의 데이터 생산 파이프라인 핸드오프 패키지.
내부 작업 트리에서 실제 데이터 생산에 사용한 코드를 정리한 것으로, 하드코딩된
서버 경로/라이선스를 제거하고 실행 진입점을 통합했다.

## 패키지 구성

| 디렉토리 | 내용 |
|---|---|
| `spef_extraction/` | StarRC coupling-preserved SPEF 추출 스크립트 (crosstalk 흐름의 입력 생산) |
| `pt_annotation/` | 고정 경로(fixed-path) 전압 스윕 + Dist/Res/Cpin feature annotation. 경로 선정은 2방식: ref top-N(`run_sweep.py`) 또는 hidden 제외 전 코너의 위반/위험 경로 union(`extract_violation_paths.py` → `--emit-fixed-paths-tcl` 로 연결) |
| `crosstalk_features/path_context_sweep/` | 전 코너 스윕 crosstalk delta + timing window feature 추출 (주력) |
| `crosstalk_features/coupling_pair_features/` | 단일 경로 victim–aggressor pair feature 테이블 추출 (검증용 보조) |

파이프라인 순서: `spef_extraction` (SPEF 생산) → `pt_annotation` (annotation) →
`crosstalk_features` (annotation 산출물 사용).

각 하위 디렉토리의 `README.md` 에 상세 흐름과 실행 예시가 있다.

## Quick Start (처음 받은 사람용)

1. **하위 `README.md` 를 먼저 읽는다** — 돌리려는 파이프라인(`pt_annotation/`
   또는 `crosstalk_features/*`) 의 흐름·입력·산출물이 거기 다 있다.
2. **환경변수를 자기 사이트 값으로 세팅한다** — 코드는 서버 경로/라이선스를
   하드코딩하지 않고 아래 "공통 환경변수" 를 실행 직전 셸에 얹어 읽는다.
   `pt_shell` 이 이미 PATH 에 있으면 대부분 생략 가능하다.
   ```csh
   setenv PT_SOURCE  /path/to/site_pt_setup.cshrc   # csh/tcsh
   ```
   ```bash
   export PT_SOURCE=/path/to/site_pt_setup.cshrc    # bash
   ```
3. **디자인 종속 부분만 자기 디자인에 맞춘다** — 파일명 규약(디자인명,
   라이브러리 스타일 태그, 전압/온도 목록)은 각 러너 상단 한 곳에 모여 있다
   (`run_sweep.py` 의 `TEMPS`/`VOLTAGES`/`Job`, 또는 unified TCL 상단).
   그 외 로직은 수정할 필요가 없다.

## 공통 요구사항

- Python **3.9+** (`removesuffix`, dataclass 문법 사용. 3.6 불가)
- `pt_annotation` 은 추가로 `networkx` 필요 (`pip install -r pt_annotation/requirements.txt`)
- Synopsys PrimeTime (검증 버전: V-2023.12-SP4). SI 기능은 PrimeTime SI 라이선스 필요
- coupling capacitance 가 유지된 SPEF (StarRC `COUPLING_CAP: YES`) — SI/crosstalk 흐름 한정

## 공통 환경변수

| 변수 | 용도 |
|---|---|
| `PT_SOURCE` | `pt_shell` 을 PATH 에 올려주는 사이트별 셋업 스크립트 경로. `pt_shell` 이 이미 PATH 에 있으면 불필요 |
| `PT_LICENSE` | `LM_LICENSE_FILE` 값 (crosstalk 스윕 러너용, 선택) |
| `LC_ROOT` | Library Compiler 설치 루트 (pt_annotation, 선택) |

## 유효성 검증 이력

이 릴리즈의 코드는 내부 트리에서 다음 데이터 생산에 실사용된 코드와 로직이 동일하다
(경로 파라미터화 및 진입점 통합만 수행):

- SAED14 RVT CCS 17-전압(0.600–0.800V @25C) × RC 3코너(Cmax/Cnom/Cmin) × SI on/off
  fixed-path setup/hold 스윕 + annotation
- 동일 스윕 축의 path-context crosstalk delta 추출 (306 job)
