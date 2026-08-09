# _engine/xtalk — 손대지 마세요

기존 `crosstalk_features/path_context_sweep/parsers/` 에서 **그대로 복사**한
파서 5개입니다. 이 파일들이 만들어 온 14열 리포트를 모델 쪽에서 읽고 있으므로,
형식이 바뀌면 안 됩니다. 고치지 말고 그대로 두세요.

`5a_contexts.py` / `5b_pairs.py` / `5c_report.py` 가 이들을 순서대로 부릅니다.
