# py27 — 파이썬 3 이 전혀 없을 때만

**먼저 위 폴더(`..`)의 원본을 쓰세요.** 이 폴더는 파이썬 3 을 정말 하나도 못 찾았을
때만 씁니다.

```bash
python 0_check.py          # 위 폴더에서. 2.7 로도 돌아간다
```

이게 쓸 수 있는 파이썬 3 을 찾아 줍니다. **PrimeTime 이 깔린 사이트면 거의 항상
있습니다** — PT / ICC2 / FusionCompiler 설치본 안에 3.6 이 들어 있고, 환경변수를
아무것도 안 잡아도 그냥 실행됩니다. 그게 나오면 이 폴더는 필요 없습니다.

여기 파일들은 `python` (2.7) 으로 돌립니다. 사용법은 위 폴더의 `README.md` 와
완전히 같습니다.

```bash
python 1_union.py --dir round1/corners
python 4_all_corners.py --root round2 --spef <SPEF> --phase 1
```

---

## 검증 결과 (실측)

BoomCoreV3(3nm) 294경로 · 넷 8,930줄로, 파이썬 3 판과 **같은 입력**을 주고
결과를 대조했습니다.

| 스크립트 | 산출물 | 결과 |
|---|---|---|
| `1_union.py` | `fixed_paths.tcl` | **byte 동일** |
| `2a_cpin.py` | `cpin.tsv` | **byte 동일** |
| `2b_distres.py` | `distres.tsv` | **byte 동일** (8,930/8,930) |
| `2c_merge.py` | `<코너>_fixed_annotated.txt` | **byte 동일** (40,020줄) |
| `5a_contexts.py` | `unique_contexts.tsv`, `path_victim_nets.tsv` | **byte 동일** |
| `5b_pairs.py` | `active_features.tsv`, `context_summary.tsv` | **byte 동일** |
| `5c_report.py` | `<코너>.path_context_si_compact.by_path.rpt` | **byte 동일** (코너 2개) |
| `4_all_corners.py` | phase 1/2/3, `run_pt*.tcl` 생성 | 정상 |
| `8_snapshot.py` | `snapshot.txt` | 정상 (UTF-8 저장) |
| `9_diagnose.py` | | 정상 |

실패 경로 10가지(빈 폴더, 코너 상위 폴더, `--slack-max` 과다 등)도 전부
`Traceback` 없이 에러 코드로 끝납니다.

**결론: crosstalk 14열까지 2.7 로 만들 수 있고, 결과가 파이썬 3 판과 글자 하나
다르지 않습니다.**

### 속도

| | 파이썬 3 | 파이썬 2.7 |
|---|---|---|
| `2b_distres` (SPEF 568MB, 넷 8,930줄) | 15.6초 | **31.7초** |
| 그 외 전 단계 | — | 체감 차이 없음 |

SPEF 를 읽는 `2b` 만 약 2배 느립니다. 코너가 17개여도 9분 차이라 감당 가능합니다.

---

## 예전 문서에 있던 "60배 느리고 데이터를 놓친다"는 해결됐습니다

원인은 **문자열 타입 버그** 하나였습니다.

```python
# 잘못
if isinstance(spef_id, str) and spef_id.startswith('*')
```

파이썬 2 에서 `io.open` 이 돌려주는 것은 `str` 이 아니라 `unicode` 입니다. 그래서
이 검사가 **모든 SPEF NAME_MAP id 를 걸러냈고**, 넷 8,930개가 전부 "NAME_MAP 으로
못 찾음" 으로 빠졌습니다. 그 다음 단계인 CONN fallback 이 대부분을 건졌지만

- 느린 경로를 8,930번 타서 **60배 느려졌고**
- 계층 이름(`rob/nXXXX`) **68줄(0.76%)을 끝내 못 찾았습니다**

파이썬 2/3 양쪽에서 맞는 타입 검사로 바꾸니 두 증상이 같이 사라졌습니다.

```python
try:
    _TEXT_TYPES = (str, unicode)   # 파이썬 2
except NameError:
    _TEXT_TYPES = (str,)           # 파이썬 3
```

고친 뒤: NAME_MAP 미해결 3개(파이썬 3 과 동일), `Dist 8,930/8,930`,
`distres.tsv` byte 동일.

---

## 무엇이 달라졌나 (참고)

원본과 기능은 같고, 2.7 문법으로만 바꾼 것입니다.

- f-string → `"{}".format(...)` / `%` 포맷
- `open(..., errors=)` → 읽기는 `io.open`, 쓰기는 내장 `open`
  (2.7 의 `io.open` 은 unicode 만 받아 str 을 쓰면 죽는다)
- `functools.lru_cache` → 같은 동작을 직접 구현
- `pathlib` → `os.path`
- `from __future__ import division, print_function`
- `isinstance(x, str)` → `_TEXT_TYPES` (위 참조)
- `_engine/utf8.py` 의 `force_utf8()` 은 **2.7 에서 아무것도 하지 않습니다.**
  2.7 의 문자열은 이미 utf-8 바이트라 그대로 써도 locale 과 무관하게 잘 나갑니다.
  오히려 `codecs` 로 감싸면 파이썬이 그 바이트를 ascii 로 **디코딩**하려다 죽습니다.

`0_check.py` 는 여기 없습니다. 위 폴더의 것이 2.7 과 3.x 양쪽에서 돌아갑니다.
