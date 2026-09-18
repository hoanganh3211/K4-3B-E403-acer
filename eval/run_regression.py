"""Supplementary offline tests, never added to the 34-case golden numerator."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.harness import EVAL, sha256, utc_now, verify_frozen, write_new


if __name__ == "__main__":
    verify_frozen()
    destination = EVAL / "regression" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
    destination.mkdir(parents=True, exist_ok=False)
    started = utc_now()
    with tempfile.TemporaryDirectory(prefix="scriptscout-regression-") as isolated:
        os.environ["SESSION_DB_PATH"] = str(Path(isolated) / "sessions.sqlite3")
        with (destination / "unittest.log").open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream):
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
            with patch("socket.socket.connect", side_effect=AssertionError("Offline regression cannot connect to network")):
                result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    record = {"started_at": started, "finished_at": utc_now(), "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
              "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "successful": result.wasSuccessful() and not result.skipped,
              "live_provider_calls": 0, "network": "socket connections blocked during tests",
              "scope": "Existing offline regression suite, reported separately from golden 34",
              "freeze_sha256": sha256(EVAL / "freeze.json"), "log_sha256": sha256(destination / "unittest.log")}
    verify_frozen()
    write_new(destination / "summary.json", record)
    print(str(destination))
    print(f"{record['passed']}/{record['tests_run']} passed, {record['failures']} failures, {record['errors']} errors, {record['skipped']} skipped")
    sys.exit(0 if record["successful"] else 1)
