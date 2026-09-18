"""Freeze once, evaluate once per run directory, and preserve every result."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.harness import EVAL, read_json, sha256, summarize, utc_now, verify_frozen, write_new

PROMPTFOO_VERSION = "0.123.1"
DEADLINE = "2026-09-18T16:00:00+07:00"


def validate():
    dataset = read_json(EVAL / "golden_set.json")
    cases = dataset["cases"]
    assert len(cases) == 34 and len({c["id"] for c in cases}) == 34
    assert Counter(c["group"] for c in cases) == {"ordinary": 10, "hard": 20, "rare": 4}
    classes = Counter(c["hard_class"] for c in cases if c["group"] == "hard")
    assert len(classes) == 10 and all(n >= 2 for n in classes.values())
    for c in cases:
        checks = c["expected"]["checks"]
        assert checks and len(set(checks)) == len(checks), c["id"]
        assert c["runner"] in {"admission", "source", "conflict", "patch", "teaching_style", "contract"}
    quality = read_json(EVAL / "quality_bar.json")
    lookup = {c["id"]: c for c in cases}
    for condition in quality["hard_conditions"]:
        for ref in condition["references"]:
            assert ref["check"] in lookup[ref["case_id"]]["expected"]["checks"], ref
    assert quality["expected_case_count"] == len(cases)
    print("Structure valid: 34 cases = 10 ordinary + 20 hard (10 classes) + 4 rare.")
    return cases, quality


def freeze():
    if (EVAL / "freeze.json").exists():
        raise SystemExit("Already frozen. Do not overwrite the registered spec.")
    cases, quality = validate()
    from eval.scenarios import validate_cases
    validate_cases(cases)
    if datetime.now(timezone.utc) > datetime.fromisoformat(DEADLINE):
        raise SystemExit("Deadline has passed. Refuse to claim an on-time freeze.")
    tests = [{"description": c["id"] + " | " + c["runner"],
              "vars": {"case_id": c["id"]}} for c in cases]
    if (EVAL / "cases.promptfoo.json").exists():
        assert read_json(EVAL / "cases.promptfoo.json") == tests, "Promptfoo case order differs from golden set"
    else:
        write_new(EVAL / "cases.promptfoo.json", tests)
    # Explicit directories only; never include .env, databases, credentials,
    # dependency installations, screenshots, or previous evaluation outputs.
    selected = list(ROOT.glob("*.py"))
    for directory in ("api", "agents", "models", "services", "ui", "tests", "eval"):
        base = ROOT / directory
        if not base.exists():
            continue
        selected.extend(p for p in base.rglob("*") if p.is_file()
                        and not any(part in {"runs", "frozen", "__pycache__"} for part in p.relative_to(base).parts)
                        and p.suffix.lower() in {".py", ".json", ".yaml", ".yml", ".md", ".html", ".txt", ".css"})
    selected.extend(p for p in (ROOT / "requirements.txt", ROOT / ".streamlit/config.toml") if p.is_file())
    names = sorted({p.relative_to(ROOT).as_posix() for p in selected})
    manifest = {"schema_version": "1.0", "dataset_id": "scriptscout-golden-34-v1",
                "frozen_at": utc_now(), "spec_deadline": DEADLINE,
                "timezone": "Asia/Bangkok (UTC+07:00, same offset as Vietnam)",
                "statement": quality["statement"], "promptfoo_version": PROMPTFOO_VERSION,
                "files": {name: sha256(ROOT / name) for name in names}}
    write_new(EVAL / "freeze.json", manifest)
    (EVAL / "frozen").mkdir(exist_ok=True)
    with zipfile.ZipFile(EVAL / "frozen/spec-v1.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for name in names + ["eval/freeze.json"]:
            archive.write(ROOT / name, name)
    print("FROZEN " + manifest["frozen_at"])
    print("freeze.json SHA256 " + sha256(EVAL / "freeze.json"))


def package_versions():
    output = {"python": platform.python_version(), "promptfoo": PROMPTFOO_VERSION}
    for name in ("google-genai", "pydantic", "httpx", "streamlit"):
        try:
            output[name] = version(name)
        except PackageNotFoundError:
            output[name] = None
    return output


def report(run_dir, manifest):
    cases, quality = validate()
    records = [read_json(path) for path in sorted((run_dir / "cases").glob("*.json"))]
    integrity = True
    try:
        verify_frozen()
    except RuntimeError:
        integrity = False
    result = summarize(cases, records, quality, integrity_ok=integrity)
    framework = read_json(run_dir / "promptfoo.json") if (run_dir / "promptfoo.json").exists() else {}
    result["promptfoo_stats"] = framework.get("results", {}).get("stats")
    stats = result["promptfoo_stats"] or {}
    framework_matches = (stats.get("successes") == result["passed"]
                         and stats.get("failures") == result["failed"]
                         and stats.get("errors", 0) == 0)
    result["framework_accounting_matches"] = framework_matches
    if not framework_matches:
        result["hard_violations"].append({"condition": "HC-INTEGRITY", "reason": "Promptfoo counts missing or do not match case artifacts"})
        result["quality_bar_met"] = False
        result["status"] = "Hold"
    result["run_id"] = run_dir.name
    result["finished_at"] = utc_now()
    result["freeze_sha256"] = sha256(EVAL / "freeze.json")
    result["configuration"] = manifest
    write_new(run_dir / "summary.json", result)
    by_id = {row["case_id"]: row for row in records}
    with (run_dir / "results.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case_id", "group", "hard_class", "runner", "passed", "failed_checks", "evidence_level", "provider_calls", "elapsed_seconds"])
        for case in cases:
            row = by_id.get(case["id"], {})
            observed = row.get("observed", {})
            writer.writerow([case["id"], case["group"], case.get("hard_class"), case["runner"],
                             row.get("passed", False), "; ".join(row.get("failed_checks", ["MISSING_RESULT"])),
                             observed.get("evidence_level", "missing"), observed.get("provider_call_count", 0), row.get("elapsed_seconds")])
    lines = ["# Kết quả ScriptScout Golden 34 v1", "",
             f"**{result['passed']}/{result['total']} ca đạt ({result['pass_percentage']:.2f}%). Quyết định: {result['status']}.**", "",
             f"Quality bar: {quality['statement']}", "",
             f"Đạt quality bar: **{'Có' if result['quality_bar_met'] else 'Không'}**. "
             f"Check/đối chiếu vi phạm điều kiện cứng: {len(result['hard_violations'])}. Lỗi thực thi: {len(result['errors'])}.", "",
             "| Nhóm | Đạt | Tổng | Tỷ lệ |", "| --- | ---: | ---: | ---: |"]
    for group, values in result["groups"].items():
        lines.append(f"| {group} | {values['passed']} | {values['total']} | {values['percentage']:.2f}% |")
    lines.extend(["", "## Cách đo và giới hạn", "",
                  "34 ca được chạy một lần bằng Promptfoo 0.123.1, không cache, không chọn lại kết quả tốt nhất. Mẫu số cố định 34; thiếu kết quả/check hoặc lỗi đều không đạt. Các ca có model dùng Gemini thật với tài liệu tổng hợp được kiểm soát; các ca contract là kiểm thử hồi quy có mock và được ghi riêng.", "",
                  "Không gọi tìm kiếm Internet thật. Chưa đo chuỗi web đầu-cuối, chưa có người chấm chất lượng lời giảng và chưa đối chiếu mẫu kịch bản chính thức (chưa được cung cấp). Vì vậy bộ đạt cũng chỉ đủ Limited trong phạm vi này. Kiểm tra tiếng Việt/phong cách bằng dấu hiệu văn bản, không thay thế thẩm định ngôn ngữ; quote khớp nguyên văn không chứng minh mọi diễn giải đều đúng.", "",
                  "Nhật ký model lưu đầu vào/đầu ra đã parse tại ranh giới ứng dụng, usage nếu adapter có cung cấp và loại lỗi đã làm sạch. Đây không phải bản sao toàn bộ HTTP/SDK response. Không lưu khóa API.", "",
                  f"Số lần gọi adapter model ghi nhận: **{result['provider_calls']}**. Không suy ra chi phí tiền từ số lần gọi. Evidence levels: `{json.dumps(result['evidence_levels'], ensure_ascii=False)}`.", "",
                  "## Kết quả từng ca", "", "| Ca | Kết quả | Check chưa đạt | Loại bằng chứng |", "| --- | --- | --- | --- |"])
    for case in cases:
        row = by_id.get(case["id"], {})
        lines.append(f"| {case['id']} | {'PASS' if row.get('passed') else 'FAIL'} | "
                     + ", ".join(row.get("failed_checks", ["MISSING_RESULT"]))
                     + f" | {row.get('observed', {}).get('evidence_level', 'missing')} |")
    lines.extend(["", "## Truy vết", "",
                  f"- Run ID: `{run_dir.name}`; chạy xong: `{result['finished_at']}`.",
                  f"- Spec đóng băng: `{read_json(EVAL / 'freeze.json')['frozen_at']}`; deadline: `{DEADLINE}`.",
                  f"- SHA256 freeze.json: `{result['freeze_sha256']}`.",
                  "- Dữ liệu gốc: `cases/*.json`; kết quả framework: `promptfoo.json`; bảng đầy đủ: `results.csv`; số liệu máy đọc: `summary.json`.",
                  "- Hàm băm toàn bộ bằng chứng của lần chạy: `artifacts.sha256.json`. Có thể phát hiện thay đổi bằng `python eval/run.py verify --run-dir <thư_mục_run>`.",
                  "- Phân tích nguyên nhân từ đầu ra đã giữ lại được viết riêng; không sửa raw, đáp án hoặc ngưỡng sau khi đo."])
    if result["hard_violations"]:
        lines.extend(["", "## Vi phạm điều kiện cứng", "", "```json", json.dumps(result["hard_violations"], ensure_ascii=False, indent=2), "```"])
    with (run_dir / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    sealed = {p.relative_to(run_dir).as_posix(): sha256(p) for p in sorted(run_dir.rglob("*")) if p.is_file()}
    write_new(run_dir / "artifacts.sha256.json", {"sealed_at": utc_now(), "files": sealed})
    print(json.dumps({k: result[k] for k in ("run_id", "passed", "total", "pass_percentage", "quality_bar_met", "status", "provider_calls")}, ensure_ascii=False))


def run():
    frozen = verify_frozen()
    validate()
    from config import settings
    from services.llm_service import api_key_configured
    if settings.llm_provider.strip().lower() not in {"google", "gemini"}:
        raise SystemExit("This registered run requires the configured Gemini provider.")
    if not api_key_configured(settings.google_api_key):
        raise SystemExit("Gemini credentials unavailable; no evaluation started.")
    run_dir = EVAL / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "cases").mkdir()
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise SystemExit("npx unavailable; no cases executed.")
    command = [npx, "--yes", f"promptfoo@{PROMPTFOO_VERSION}", "eval", "-c", str(EVAL / "promptfooconfig.yaml"),
               "--no-cache", "--max-concurrency", "1", "--repeat", "1", "--no-progress-bar", "--no-table",
               "--no-write", "--no-share", "-o", str(run_dir / "promptfoo.json")]
    manifest = {"run_id": run_dir.name, "started_at": utc_now(), "versions": package_versions(),
                "provider": "google", "model": settings.google_model,
                "moderation_model": settings.moderation_model or settings.google_model,
                "freeze_sha256": sha256(EVAL / "freeze.json"), "spec_frozen_at": frozen["frozen_at"],
                "command": command, "cache": False, "repeats": 1, "concurrency": 1,
                "dataset_order": "registered order", "live_search": False,
                "raw_scope": "Application-boundary requests, parsed responses, usage when exposed, sanitized errors; not raw HTTP.",
                "case_retries": 0, "sdk_attempts": 1,
                "limits": {"moderation_output_tokens": 768, "moderation_timeout_seconds": 20,
                           "script_output_tokens": 8192, "other_output_tokens": 4096,
                           "research_timeout_seconds": 60},
                "temperature": "Production adapter defaults; moderation temperature=0. No deterministic-output claim."}
    write_new(run_dir / "run.json", manifest)
    env = os.environ.copy()
    env.update(PROMPTFOO_DISABLE_TELEMETRY="1", PROMPTFOO_DISABLE_UPDATE="1", PROMPTFOO_PYTHON=sys.executable,
               PROMPTFOO_DISABLE_PROGRESS_BAR="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               SCRIPTSCOUT_EVAL_RUN_DIR=str(run_dir))
    print("RUN_DIR=" + str(run_dir), flush=True)
    with tempfile.TemporaryDirectory(prefix="scriptscout-eval-") as isolated:
        env["SESSION_DB_PATH"] = str(Path(isolated) / "sessions.sqlite3")
        env["PROMPTFOO_CONFIG_DIR"] = str(Path(isolated) / "promptfoo")
        with (run_dir / "promptfoo.log").open("x", encoding="utf-8") as stream:
            outcome = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
    write_new(run_dir / "process.json", {"exit_code": outcome.returncode, "finished_at": utc_now()})
    report(run_dir, manifest)


def verify(run_dir):
    verify_frozen()
    run_dir = Path(run_dir).resolve()
    seal = read_json(run_dir / "artifacts.sha256.json")
    mismatches = [name for name, digest in seal["files"].items() if not (run_dir / name).is_file() or sha256(run_dir / name) != digest]
    if mismatches:
        raise SystemExit("Changed or missing artifacts: " + ", ".join(mismatches))
    print(f"Verified frozen spec and {len(seal['files'])} sealed run artifacts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "freeze", "run", "verify"))
    parser.add_argument("--run-dir")
    args = parser.parse_args()
    if args.command == "verify":
        if not args.run_dir:
            parser.error("verify requires --run-dir")
        verify(args.run_dir)
    else:
        globals()[args.command]()
