"""Local API for ScriptScout; long operations run in a bounded worker pool."""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import uuid

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from config import settings
from json_exporter import export_session_markdown
from models.requests import AddSourceRequest, PatchRequest, PipelineRequest, ReviewRequest, RetrySourceRequest
from models.limits import MAX_SOURCES, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from services.llm_service import ServiceError, api_key_configured
from services.content_policy import CONTENT_POLICY_VERSION, ContentPolicyError, validate_lesson_content, validate_source_input
from services.moderation_service import moderation_model, require_research_admission
from services.admission_policy import ADMISSION_POLICY_VERSION
from services.pipeline_service import PipelineService, TRUST_RUBRIC, eligible_source
from services.session_store import SessionStore, now_iso

# Open/migrate user data only when the server starts, never on module import
# (tests and tooling import this module to inspect routes).
store: SessionStore | None = None
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scriptscout")
operation_lock = threading.RLock()
ACTIVE_STATUSES = {"researching", "writing", "patching"}


@asynccontextmanager
async def lifespan(app):
    global store
    if store is None:
        store = SessionStore(settings.session_db_path)
    store.recover_interrupted()
    yield


app = FastAPI(title="ScriptScout API", version="2.0.0", lifespan=lifespan)


def configuration():
    provider = settings.llm_provider.strip().lower()
    if provider == "gemini":
        provider = "google"
    return {"llm_provider": provider, "model": getattr(settings, f"{provider}_model", ""),
            "llm_configured": provider in {"openai", "google"} and api_key_configured(getattr(settings, f"{provider}_api_key", "")),
            "search_configured": api_key_configured(settings.tavily_api_key)}


def require_config(search=False):
    config = configuration()
    if not config["llm_configured"]:
        raise HTTPException(503, "Chưa cấu hình LLM_PROVIDER và API key thật phù hợp trong .env.")
    if search and not config["search_configured"]:
        raise HTTPException(503, "Thiếu TAVILY_API_KEY thật trong .env. Thêm khóa rồi khởi động lại API.")


def get_session(session_id):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, "Không tìm thấy phiên làm việc.")
    return session


def check_content(lesson=None, *, source_input=None, field="url"):
    """Reject unsuitable input locally, before configuration or paid services."""
    try:
        if lesson is not None:
            validate_lesson_content(lesson)
        if source_input is not None:
            validate_source_input(source_input, field=field)
    except ContentPolicyError as exc:
        raise HTTPException(422, {"code": "content_not_allowed", "message": exc.public_message,
                                  "field": exc.field, "category": exc.category}) from None


def check_admission(lesson):
    """Only an affirmative semantic decision can authorize provider work."""
    try:
        return require_research_admission(lesson)
    except ContentPolicyError as exc:
        code, status = {
            "needs_clarification": ("content_needs_clarification", 422),
            "admission_unavailable": ("content_review_unavailable", 503),
        }.get(exc.category, ("content_not_allowed", 422))
        raise HTTPException(status, {"code": code, "message": exc.public_message,
                                     "field": exc.field, "category": exc.category}) from None


def get_allowed_session(session_id):
    session = get_session(session_id)
    check_content(session["req"])
    return session


def envelope(session):
    public = {k: v for k, v in session.items() if k != "raw_sources"}
    return {"session_id": session["session_id"], "status": session["status"], "data": public}


def assert_idle(session):
    if session["status"] in ACTIVE_STATUSES:
        raise HTTPException(409, "Phiên đang xử lý. Hãy đợi tác vụ hiện tại hoàn tất.")


def run_operation(session_id, operation, args):
    pipeline = None
    try:
        session = get_session(session_id)
        # Recheck queued or older sessions before even constructing a provider.
        validate_lesson_content(session["req"])
        if operation == "add":
            validate_source_input(args)
        elif operation == "upload":
            validate_source_input(args["filename"], field="filename")
        require_research_admission(session["req"])

        def progress(step, message):
            with operation_lock:
                current = get_session(session_id)
                current.setdefault("progress", []).append({"step": step, "message": message, "at": now_iso()})
                store.update(current)

        pipeline = PipelineService(progress=progress)
        if operation == "research":
            result = pipeline.research(session["req"])
        elif operation == "review":
            result = pipeline.review(session, args)
        elif operation == "patch":
            result = pipeline.patch(session, args)
        elif operation == "retry_source":
            result = pipeline.retry_source(session, args)
        elif operation == "upload":
            result = pipeline.add_pdf(session, args["filename"], args["content"])
        else:
            result = pipeline.add_source(session, args)
        with operation_lock:
            current = get_session(session_id)
            current.update(result)
            reviewing = operation in {"research", "add", "retry_source", "upload"}
            current["status"] = "awaiting_review" if reviewing else "script_ready"
            current["error_message"] = None
            current["progress"].append({"step": "complete", "message": "Hồ sơ đã sẵn sàng để duyệt." if reviewing else "Đã lưu kịch bản và kết quả kiểm tra.", "at": now_iso()})
            store.update(current)
    except Exception as exc:
        with operation_lock:
            current = store.get(session_id)
            if current:
                message = str(exc) if isinstance(exc, (ServiceError, ValueError)) else f"Không hoàn tất tác vụ ({type(exc).__name__}). Dữ liệu trước đó được giữ lại; hãy thử lại."
                current["status"] = "failed"
                current["error_message"] = message[:1200]
                current.setdefault("progress", []).append({"step": "failed", "message": message[:1200], "at": now_iso()})
                store.update(current)
    finally:
        if pipeline is not None:
            pipeline.llm.close()


def dispatch(session, status, operation, args=None, *, create=False):
    # This is the common boundary for every paid operation. A rejected,
    # ambiguous or unavailable decision cannot save/queue any provider work.
    check_admission(session["req"])
    session["status"] = status
    session["error_message"] = None
    session["progress"] = [{"step": "queued", "message": "Đã xếp tác vụ; đang chuẩn bị xử lý.", "at": now_iso()}]
    if create:
        store.put(session)
    elif not store.update(session):
        raise HTTPException(404, "Không tìm thấy phiên làm việc.")
    executor.submit(run_operation, session["session_id"], operation, args)
    return envelope(session)


@app.get("/")
def root():
    return {"service": "ScriptScout API", "status": "running", "version": "2.0.0"}


@app.get("/api/health")
def health():
    return {"status": "ok", "configuration": configuration(), "trust_criteria": TRUST_RUBRIC,
            "content_policy_version": CONTENT_POLICY_VERSION,
            "research_admission": {"required": True, "policy_version": ADMISSION_POLICY_VERSION,
                                   "configured": api_key_configured(settings.google_api_key) and bool(moderation_model())}}


@app.get("/api/sessions")
def list_sessions(deleted: bool = False):
    if deleted:
        raise HTTPException(422, "Phiên đã xóa được xóa vĩnh viễn; không có thùng rác.")
    return {"sessions": store.list()}


@app.get("/api/sessions/{session_id}")
def read_session(session_id: str):
    return envelope(get_session(session_id))


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    with operation_lock:
        session = get_session(session_id)
        assert_idle(session)
        store.delete(session_id)
    return {"deleted": True, "session_id": session_id}


@app.post("/api/pipeline/start", status_code=202)
def start_pipeline(req: PipelineRequest):
    check_content(req.model_dump())
    require_config(search=True)
    session = {"session_id": f"ss_{uuid.uuid4().hex}", "req": req.model_dump(), "dossier": None, "script": None,
               "raw_sources": [], "active_source_ids": [], "progress": [], "created_at": now_iso()}
    with operation_lock:
        return dispatch(session, "researching", "research", create=True)


@app.post("/api/pipeline/review", status_code=202)
def review_sources(req: ReviewRequest):
    with operation_lock:
        session = get_allowed_session(req.session_id)
        assert_idle(session)
        require_config()
        sources = {source["source_id"]: source for source in (session.get("dossier") or {}).get("sources", [])}
        ids = list(dict.fromkeys(req.approved_source_ids))
        if not set(ids) <= set(sources):
            raise HTTPException(422, "Danh sách phê duyệt chứa mã nguồn không có trong hồ sơ.")
        if not set(req.rejected_source_ids) <= set(sources):
            raise HTTPException(422, "Danh sách loại bỏ chứa mã nguồn không có trong hồ sơ.")
        if set(ids) & set(req.rejected_source_ids):
            raise HTTPException(422, "Một nguồn không thể đồng thời được duyệt và bị loại.")
        if any(not eligible_source(sources[sid]) for sid in ids):
            raise HTTPException(422, "Chỉ duyệt nguồn đọc được, không có lệnh ẩn và có ít nhất một trích dẫn khớp.")
        return dispatch(session, "writing", "review", ids)


@app.post("/api/pipeline/patch", status_code=202)
def patch_script(req: PatchRequest):
    with operation_lock:
        session = get_allowed_session(req.session_id)
        assert_idle(session)
        require_config()
        if not session.get("script"):
            raise HTTPException(409, "Chưa có kịch bản để sửa.")
        if not set(req.remove_source_ids) <= set(session.get("active_source_ids", [])):
            raise HTTPException(422, "Chỉ có thể bỏ nguồn đang được duyệt trong phiên này.")
        return dispatch(session, "patching", "patch", list(dict.fromkeys(req.remove_source_ids)))


@app.post("/api/pipeline/sources", status_code=202)
def add_source(req: AddSourceRequest):
    check_content(source_input=req.url)
    with operation_lock:
        session = get_allowed_session(req.session_id)
        assert_idle(session)
        require_config()
        if not session.get("dossier"):
            raise HTTPException(409, "Chưa có hồ sơ. Hãy hoàn tất bước tìm kiếm trước.")
        sources = session["dossier"]["sources"]
        if len(sources) >= MAX_SOURCES:
            raise HTTPException(422, f"Mỗi phiên hỗ trợ tối đa {MAX_SOURCES} nguồn.")
        if any(source["url"].rstrip("/") == req.url.rstrip("/") for source in sources):
            raise HTTPException(409, "Nguồn này đã có trong hồ sơ.")
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(req.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Hãy nhập URL HTTP/HTTPS công khai, không kèm tài khoản/mật khẩu.") from None
        return dispatch(session, "researching", "add", req.url)


@app.get("/api/sessions/{session_id}/sources/{source_id}")
def source_evidence(session_id: str, source_id: str):
    session = get_session(session_id)
    source = next((s for s in (session.get("dossier") or {}).get("sources", []) if s["source_id"] == source_id), None)
    raw = next((s for s in session.get("raw_sources", []) if s["source_id"] == source_id), None)
    if source is None:
        raise HTTPException(404, "Không tìm thấy nguồn trong phiên này.")
    public_raw = {k: v for k, v in raw.items() if k != "uploaded_pdf_base64"} if raw else None
    return {"source": source, "raw_source": public_raw}


@app.post("/api/pipeline/sources/retry", status_code=202)
def retry_source(req: RetrySourceRequest):
    with operation_lock:
        session = get_allowed_session(req.session_id)
        assert_idle(session)
        source = next((s for s in (session.get("dossier") or {}).get("sources", []) if s["source_id"] == req.source_id), None)
        if source is None:
            raise HTTPException(404, "Không tìm thấy tài liệu trong phiên này.")
        check_content(source_input=source.get("url", ""))
        require_config()
        referenced = any(ref["source_id"] == req.source_id for scene in (session.get("script") or {}).get("scenes", [])
                         for line in scene.get("lines", []) for ref in line.get("source_refs", []))
        if source.get("is_accessible") or source.get("claims") or req.source_id in session.get("active_source_ids", []) or referenced:
            raise HTTPException(409, "Tài liệu này đã được đọc. Chỉ thử lại nguồn chưa truy cập được để giữ nguyên bằng chứng đang dùng.")
        if source.get("document_kind") == "uploaded_pdf":
            raise HTTPException(422, "Hãy tải lại một PDF có văn bản đọc được.")
        return dispatch(session, "researching", "retry_source", req.source_id)


@app.post("/api/pipeline/sources/upload", status_code=202)
def upload_source(session_id: str = Form(...), file: UploadFile = File(...)):
    try:
        filename = (file.filename or "tai-lieu.pdf").replace("\\", "/").rsplit("/", 1)[-1]
        check_content(source_input=filename, field="filename")
        with operation_lock:
            session = get_allowed_session(session_id)
            assert_idle(session)
            require_config()
            if not session.get("dossier"):
                raise HTTPException(409, "Hãy hoàn tất tìm tài liệu trước khi bổ sung PDF.")
            if len(session["dossier"]["sources"]) >= MAX_SOURCES:
                raise HTTPException(422, f"Mỗi phiên hỗ trợ tối đa {MAX_SOURCES} tài liệu.")
            check_admission(session["req"])
            content = file.file.read(MAX_UPLOAD_BYTES + 1)
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"PDF quá lớn. Hãy chọn tệp tối đa {MAX_UPLOAD_MB} MB.")
            if not content.startswith(b"%PDF-"):
                raise HTTPException(422, "Tệp này không phải PDF hợp lệ. Hãy chọn bản PDF có thể tìm kiếm hoặc sao chép văn bản.")
            return dispatch(session, "researching", "upload", {"filename": filename[:150], "content": content})
    finally:
        file.file.close()


@app.get("/api/sessions/{session_id}/sources/{source_id}/file")
def download_source_file(session_id: str, source_id: str):
    import base64
    from urllib.parse import quote
    session = get_session(session_id)
    raw = next((r for r in session.get("raw_sources", []) if r["source_id"] == source_id), None)
    if not raw or not raw.get("uploaded_pdf_base64"):
        raise HTTPException(404, "Nguồn này không có PDF được tải lên.")
    filename = quote(raw.get("uploaded_filename") or "tai-lieu.pdf", safe="")
    return Response(base64.b64decode(raw["uploaded_pdf_base64"]), media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@app.get("/api/sessions/{session_id}/export")
def export_session(session_id: str, format: str = Query(default="json", pattern="^(json|markdown)$")):
    session = get_session(session_id)
    if not session.get("dossier"):
        raise HTTPException(409, "Chưa có hồ sơ để xuất.")
    if format == "json":
        data = {k: v for k, v in session.items() if k != "raw_sources"}
        body, media, suffix = json.dumps(data, ensure_ascii=False, indent=2), "application/json", "json"
    else:
        body, media, suffix = export_session_markdown(session), "text/markdown; charset=utf-8", "md"
    return Response(content=body, media_type=media, headers={"Content-Disposition": f'attachment; filename="scriptscout-{session_id}.{suffix}"'})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host=settings.api_host, port=settings.api_port)
