# CLAUDE.md — pt_si_re

이 폴더가 **현행 파이프라인**입니다. 옆의 `pt_si/` 는 예전 것이라 쓰지 않습니다.

PT(PrimeTime) 리포트에서 모델 학습 입력 2종을 만듭니다. EDA 데이터 파이프라인이지
애플리케이션 코드가 아닙니다.

## 두 갈래 — 서로 독립입니다

| 갈래 | 단계 | 최종 산출물 |
|---|---|---|
| **annotation** | `2a_cpin` → `2b_distres` → `2c_merge` | `<코너>_fixed_annotated.txt` |
| **crosstalk** | `5a_contexts` → [PT] → `5b_pairs` → `5c_report` | `<코너>.path_context_si_compact.by_path.rpt` (14열) |

crosstalk 은 Dist/Res/Cpin 을 안 씁니다. annotated 파일이 없어도 원본 `.rpt` 로
같은 결과가 나옵니다. **한쪽이 막혀도 다른 쪽을 먼저 돌릴 수 있습니다.**

`7_collect.py` 가 위 두 파일만 모아 넘길 형태로 만듭니다.

## 헷갈리기 쉬운 것들

**`4_all_corners.py` 의 phase 는 갈래로 나뉜 게 아닙니다.** pt_shell 을 다녀오는
지점으로 나뉩니다.

- phase 1 = `2a` `2b` `2c` (annotation 여기서 끝) + `5a` (PT 에 물어볼 목록)
- [PT 한 번]
- phase 2 = `5b` `5c`

**crosstalk PT 본체는 `pt/xtalk_all.tcl` 입니다.** `dev/all_xtalk_one.tcl` 은 그걸
코너마다 부르는 껍데기일 뿐입니다(`all_xtalk_one.tcl:110`). 코너 하나만 볼 때는
그 폴더에서 `xtalk_all.tcl` 을 직접 돌리면 됩니다. `4_all_corners.py` 의 주석은
껍데기 이름만 적어 두어 본체가 안 드러납니다.

**브랜치 이름이 폴더 이름과 같습니다.** `git checkout pt_si_re` 는 "브랜치냐 경로냐"로
막힙니다. `git switch pt_si_re` 를 쓰세요.

**받은 표는 코너 폴더에 정해진 이름으로 둡니다.** 만들어 주는 코드는 없습니다.

- `cpin_map.txt` → `2a_cpin.py`
- `distres_map.txt` → `2b_distres_table.py`
- `design.spef` → `2b_distres.py` (또는 `--spef-dir`)

## 2b 는 세 가지입니다 — 셋 다 `distres.tsv` 를 만듭니다

| 스크립트 | 읽는 것 | 언제 |
|---|---|---|
| `2b_distres.py` | SPEF (넷 이름으로 탐색) | 기본 |
| `2b_distres2.py` | SPEF (NAME_MAP 숫자 ID) | 위가 느릴 때. **아직 커밋 안 됨** |
| `2b_distres_table.py` | 받은 표 (SPEF 안 읽음) | SPEF 를 못 뽑는 사이트 |

`4_all_corners.py` 에는 `2b_distres.py` 가 하드코딩돼 있습니다. 표 방식으로 전 코너를
돌리려면 코너마다 `2b_distres_table.py` 를 따로 부르거나 `PHASES` 에 선택지를
넣어야 합니다.

## Dist / Res / Cpin 이 코너에 따라 변하는가

실측(BoomCoreV3, (net) 82,472줄):

- **Dist** — 전압·온도·RC 코너 모두에서 안 변합니다. 배치 좌표라서.
- **Res** — 전압으로 안 변하고, RC 코너로도 83% 는 그대로. **온도로만 크게 변합니다**
  (25C→125C 전 넷 +39%, -40C→125C +86%). `R(T) = R(0C) x (1 + 0.00432 x T)`.
- **Cpin** — Liberty 에서 오므로 전압·온도 모두 변합니다. 코너별로 받아야 합니다.

받은 표로 갈 때 **Res 표는 온도마다 따로** 필요합니다. 전압별로는 필요 없습니다.

## 문서

| 파일 | 내용 |
|---|---|
| `README.md` | 전체 흐름, 단계별 상세, 막혔을 때. 제일 두껍습니다 |
| `코드표.md` | `OK-` / `W-` / `E-` 코드 전체 목록과 조치 |
| `변경이력.md` | 현장 장비에서 코드 갱신할 때 보는 문서 |
| `UNION_설명.md` | `1_union.py` 가 경로를 고르는 방식 |
| `담당자요청.md` / `원격문의.md` | 현장에 부탁드리는 내용 |

각 스크립트는 끝에 `[ OK- ]` / `[ W- ]` / `[ E- ]` 코드를 찍습니다. 그 코드로
`코드표.md` 를 보면 무엇을 하면 되는지 나옵니다.

## 주의

- **화면 출력은 영어로 씁니다.** 한글이 깨지는 터미널이 있습니다. 주석과 문서는 한글입니다.
- **SPEF 추출 스크립트는 이 폴더에 없습니다.** StarRC 로 coupled SPEF 를 뽑는
  셸 스크립트는 `pt_si/spef_extraction/` 에만 있습니다. `pt_si` 를 지우기 전에
  그것만 옮겨 오세요.
- 결과 파일은 다 쓴 뒤에야 그 이름이 생깁니다. 중간에 끊겨도 `--skip-done` 이 안전합니다.
