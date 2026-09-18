"""Versioned golden-set accounting. Never turn missing checks into a pass."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score_case(case, observed):
    required = case["expected"]["checks"]
    checks = observed.get("checks", {})
    missing = [name for name in required if name not in checks]
    failed = [name for name in required if checks.get(name) is not True]
    passed = bool(required) and not failed and not observed.get("error")
    return {"case_id": case["id"], "group": case["group"],
            "hard_class": case.get("hard_class"), "runner": case["runner"],
            "passed": passed, "required_checks": required, "missing_checks": missing,
            "failed_checks": failed, "observed": observed}


def verify_frozen():
    manifest = read_json(EVAL / "freeze.json")
    mismatches = [name for name, digest in manifest["files"].items()
                  if not (ROOT / name).is_file() or sha256(ROOT / name) != digest]
    if mismatches:
        raise RuntimeError("Frozen files changed: " + ", ".join(mismatches))
    return manifest


def summarize(cases, records, quality, *, integrity_ok=True):
    by_id = {row["case_id"]: row for row in records}
    expected_ids = {case["id"] for case in cases}
    missing_checks = {case["id"]: [name for name in case["expected"]["checks"]
                                  if name not in by_id.get(case["id"], {}).get("observed", {}).get("checks", {})]
                      for case in cases}
    missing_checks = {key: value for key, value in missing_checks.items() if value}
    complete = len(records) == len(cases) and set(by_id) == expected_ids and not missing_checks
    errors = [row["case_id"] for row in records if row["observed"].get("error")]
    passes = sum(by_id.get(case["id"], {}).get("passed") is True for case in cases)
    rate = 100 * passes / len(cases) if cases else 0
    violations = []
    for item in quality["hard_conditions"]:
        for ref in item["references"]:
            row = by_id.get(ref["case_id"])
            actual = row and row["observed"].get("checks", {}).get(ref["check"])
            if actual is not True:
                violations.append({"condition": item["id"], **ref})
    if not complete or errors or not integrity_ok:
        violations.append({"condition": "HC-INTEGRITY", "complete": complete,
                           "error_cases": errors, "missing_checks": missing_checks, "integrity_ok": integrity_ok})
    bar_met = complete and integrity_ok and not errors and not violations and rate >= quality["pass_percentage"]
    # The registered suite does not include a live web-search E2E or a human
    # oral-style review. A green controlled suite alone never authorizes Ship.
    ship_evidence = all(quality["scope"].get(name, False)
                        for name in quality["ship_requires"])
    status = "Hold" if violations or rate < quality["limited_min_percentage"] else "Ship" if bar_met and ship_evidence else "Limited"
    groups = {}
    for group in ("ordinary", "hard", "rare"):
        rows = [case for case in cases if case["group"] == group]
        count = sum(by_id.get(case["id"], {}).get("passed") is True for case in rows)
        groups[group] = {"passed": count, "total": len(rows), "percentage": 100 * count / len(rows) if rows else 0}
    return {"total": len(cases), "passed": passes, "failed": len(cases) - passes,
            "pass_percentage": rate, "quality_bar_met": bar_met, "status": status,
            "complete": complete, "integrity_ok": integrity_ok, "hard_violations": violations,
            "errors": errors, "groups": groups,
            "evidence_levels": dict(Counter(row["observed"].get("evidence_level", "unknown") for row in records)),
            "provider_calls": sum(row["observed"].get("provider_call_count", 0) for row in records),
            "ship_evidence_complete": ship_evidence}
