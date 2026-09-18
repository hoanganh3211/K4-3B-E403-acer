"""Post-freeze diagnostic only; never replaces or rescales golden v1.

The registered socket guard blocks Windows asyncio's socketpair loopback.
This separate run permits loopback IPC but still refuses external connections.
No model, dataset, production code, golden oracle or quality bar is changed.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from eval.harness import EVAL, sha256, utc_now, verify_frozen, write_new


if __name__ == "__main__":
    verify_frozen()
    destination = EVAL / "diagnostics" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
    destination.mkdir(parents=True, exist_ok=False)
    started = utc_now()
    original_connect = socket.socket.connect
    counters = {"loopback_connections": 0, "external_connections_refused": 0}

    def loopback_only(sock, address):
        if isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback:
            counters["loopback_connections"] += 1
            return original_connect(sock, address)
        counters["external_connections_refused"] += 1
        raise AssertionError("Diagnostic regression cannot connect outside loopback")

    with tempfile.TemporaryDirectory(prefix="scriptscout-diagnostic-") as isolated:
        os.environ["SESSION_DB_PATH"] = str(Path(isolated) / "sessions.sqlite3")
        with (destination / "unittest.log").open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream):
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
            with patch("socket.socket.connect", new=loopback_only):
                result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    record = {"started_at": started, "finished_at": utc_now(), "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
              "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "successful": result.wasSuccessful() and not result.skipped,
              "network_counters": counters, "scope": "Post-freeze offline diagnostic, not a replacement golden result",
              "reason": "Registered all-socket guard prevents Windows asyncio socketpair from starting TestClient/Streamlit tests",
              "baseline_golden": "20260918T075920Z-c5072b", "baseline_regression": "20260918T075921Z-a1ed8a",
              "freeze_sha256": sha256(EVAL / "freeze.json"), "diagnostic_code_sha256": sha256(__file__),
              "log_sha256": sha256(destination / "unittest.log")}
    verify_frozen()
    write_new(destination / "summary.json", record)
    print(str(destination))
    print(f"{record['passed']}/{record['tests_run']} passed, {record['failures']} failures, {record['errors']} errors, {record['skipped']} skipped")
    sys.exit(0 if record["successful"] else 1)
