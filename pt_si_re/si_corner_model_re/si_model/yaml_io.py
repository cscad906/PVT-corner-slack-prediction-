"""Read YAML without depending on the host locale or editor encoding."""

import yaml


def load_yaml(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Legacy EDA workstations may save the same YAML as Korean CP949.
        source = raw.decode("cp949")
    return yaml.safe_load(source)
