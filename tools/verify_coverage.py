#!/usr/bin/env python3
"""Fallisce se il gateway non copre 1:1 lo Swagger incluso."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = json.loads((ROOT / "swagger.json").read_text(encoding="utf-8"))
catalog = json.loads((ROOT / "app/api/v3/upstream_catalog.json").read_text(encoding="utf-8"))
methods = {"get", "post", "put", "delete", "patch", "head", "options"}
expected = {(m.upper(), p) for p, item in spec["paths"].items()
            for m in item if m.lower() in methods}
actual = {(op["method"], op["path"]) for op in catalog["operations"]}
missing = sorted(expected - actual)
extra = sorted(actual - expected)
print(f"Swagger: {len(expected)} operazioni; gateway: {len(actual)}")
if missing:
    print("MANCANTI:")
    for method, path in missing:
        print(" ", method, path)
if extra:
    print("EXTRA:")
    for method, path in extra:
        print(" ", method, path)
if missing or extra or len(actual) != len(catalog["operations"]):
    raise SystemExit(1)
print("COPERTURA COMPLETA: 91/91")
