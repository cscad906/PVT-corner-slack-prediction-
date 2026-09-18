"""Read YAML without depending on the host locale or editor encoding."""

import yaml


def load_yaml(path):
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "euc-kr", "cp949"):
        try:
            source = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UnicodeError("Cannot decode YAML as UTF-8, EUC-KR, or CP949: " + str(path))
    return yaml.safe_load(source)
