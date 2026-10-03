"""
Loads KEY=VALUE lines from the repo's .env into os.environ, without overriding
variables already set. Imported before hl.info, which reads HL_NETWORK at
import time. Stdlib only, so the read-only oracle needs no extra dependency.
"""

import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load(path=PATH):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip())


load()
