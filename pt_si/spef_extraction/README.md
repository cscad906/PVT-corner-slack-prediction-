# spef_extraction — StarRC coupled-SPEF 추출

crosstalk/SI 흐름의 입력이 되는 **coupling 유지 SPEF** 를 StarRC(StarXtract)로
추출하는 스크립트. `.cmd` 를 자동 생성하고 `StarXtract -clean` 으로 실행한 뒤,
결과 SPEF 의 완결성/코너 일치를 검증한다.

| 스크립트 | 공정 | 용도 |
|---|---|---|
| `14nm/run_starrc_temp_rc_matrix_coupled.sh` | SAED14 | RC(Cmin/Cnom/Cmax) × 온도(-40/25/125) 매트릭스, 병렬 지원 |
| `14nm/run_starrc_beol_spef_coupled.sh` | SAED14 | 단일(BEOL) 추출 |
| `3nm/run_starrc_temp_spef_coupled.sh` | 3nm | 온도 스윕(멀티코너 동시 추출) 후 deliver 로 복사 |
| `example.starrc_coupled.cmd` | — | 단일 코너 `.cmd` 예시 (경로는 placeholder). 스크립트가 코너별로 생성하는 것과 동일한 형태 |

## coupling 을 유지하는 핵심 (자동 생성되는 `.cmd`)

```
EXTRACTION: RC
COUPLE_TO_GROUND: NO          # coupling cap 을 ground 로 합치지 않음
COUPLING_ABS_THRESHOLD: 0     # 임계값 0 → 작은 coupling cap 도 보존
COUPLING_REL_THRESHOLD: 0
NETLIST_FORMAT: SPEF
```

이 네 줄이 crosstalk 용 SPEF 의 조건이다. `COUPLE_TO_GROUND: YES` 로 뽑으면
grounded SPEF 가 되어 다운스트림 crosstalk 결과가 무의미해진다.

## 환경변수 (사이트별 값 — 하드코딩 없음)

셸이 csh/tcsh 면 `setenv A B`, bash 면 `export A=B`.

| 변수 | 용도 | 필수? |
|---|---|---|
| `PROJ_ROOT` | 프로젝트 루트 (`…/deliverables` 가 이 아래) | ✅ |
| `STARRC_ROOT` | StarRC 설치 루트 (`$STARRC_ROOT/bin/StarXtract`) | ✅ (14nm) |
| `SNPSLMD_LICENSE_FILE` | Synopsys 라이선스 `port@host` | ✅ |
| `PDK_ROOT` | layer map + corners 파일 디렉토리 | 14nm, 기본 `<base>/pdk` |
| `STARRC_MAPPING_FILE` | layer 매핑 파일 경로 (직접 지정 시) | 선택 |
| `STARRC_CORNERS_FILE` | corners 파일 경로 (직접 지정 시) | 선택 |
| `PDK_LAYER_MAP` | (3nm) StarRC layer 매핑 파일 | ✅ (3nm) |
| `PDK_NXTGRD` | (3nm) StarRC grid(`.nxtgrd`) 파일 | ✅ (3nm) |
| `STARRC_JOBS` / `-j` | 병렬 job 수 (14nm matrix) | 선택 |
| `FORCE_STARRC=1` | 기존 SPEF 있어도 재추출 | 선택 |

> **PDK 기술파일(layer map, `.nxtgrd`, corners)은 이 패키지에 포함되지 않는다.**
> 각 사이트가 자기 PDK 의 해당 파일 경로를 위 환경변수로 지정해야 한다.

## 실행 예시

**14nm (RC × 온도 매트릭스)**
```bash
export PROJ_ROOT=/data/pvt_project
export STARRC_ROOT=/tools/synopsys/starrc/<ver>
export SNPSLMD_LICENSE_FILE=port@license-host
export PDK_ROOT=/data/pdk/saed14

# 특정 디자인, 코너 1개만 (스모크)
bash 14nm/run_starrc_temp_rc_matrix_coupled.sh --corner Cnom_model_25 BoomCoreV3
# 전체 (디자인 병렬 2)
bash 14nm/run_starrc_temp_rc_matrix_coupled.sh -j 2 ibex RocketCore SmallBoomV2 BoomCoreV3
```

**3nm (온도 스윕)**
```bash
export PROJ_ROOT=/data/pvt_project
export PDK_LAYER_MAP=/data/pdk/3nm/<layer_map>
export PDK_NXTGRD=/data/pdk/3nm/<grid>.nxtgrd
export SNPSLMD_LICENSE_FILE=port@license-host   # StarXtract 는 PATH 에 있다고 가정

bash 3nm/run_starrc_temp_spef_coupled.sh BoomCoreV3
```

## 입력 (StarRC 가 요구)

- **NDM 데이터베이스** — ICC2 배치 결과 (스크립트가 `processors/<design>/icc2/<lib>` 에서 찾음)
- **layer 매핑 파일**, **corners 파일**(온도/RC grid 정의), **`.nxtgrd` grid 파일**
- 디자인별 `BLOCK`(top), run-tag, prefix — 각 스크립트의 `run_one()` 상단에
  우리 케이스 값이 예시로 들어있다. 다른 디자인에 적용할 때 이 부분을 수정한다.

## 산출물 검증 (스크립트 내장)

- SPEF 완결성: `*PROGRAM "StarRC"` + `*END` 존재
- 코너 일치: 헤더의 `OPERATING_TEMPERATURE` / `TCAD_GRD_FILE` 가 요청 코너와 일치
- (3nm) coupling 존재: `*CAP` 섹션의 coupling 엔트리 수 > 0

## 다른 BEOL 코너로 확장 (공정 SS/FF 는 무관)

SPEF 는 **배선(interconnect) 기생성분(RC)** 이므로 트랜지스터 공정 코너
(TT/SS/FF)와 **무관**하다 — 같은 SPEF 를 SS/TT/FF 어떤 트랜지스터 라이브러리와
페어링해도 된다. 따라서 이 단계에서 확장할 축은 **BEOL(RC) 코너뿐**이다.

- **BEOL 코너 정의 파일 교체** — 온도/RC grid 정의는 `.corners` 파일에서 온다.
  `STARRC_CORNERS_FILE`(14nm) 또는 3nm 의 `.corners` 생성부를 그쪽 BEOL 코너
  정의로 바꾼다.
- **추출할 코너 목록** — 14nm 은 스크립트 상단 `default_corners=(...)`, 3nm 은
  `run_one()` 의 `<label>:<temp>` 목록을 그쪽 코너/온도로 교체한다.
- **layer map / grid 파일** — `STARRC_MAPPING_FILE`(14nm), `PDK_LAYER_MAP`/
  `PDK_NXTGRD`(3nm) 환경변수로 지정한다.
- **coupling 레시피는 그대로** — `COUPLE_TO_GROUND: NO` + threshold 0 은 BEOL
  코너가 바뀌어도 유지한다(crosstalk 입력 조건).
