"""Vietnamese teaching studio for the persistent ScriptScout API."""
from __future__ import annotations

import os
import re
import time
from html import escape
from typing import Any
from urllib.parse import urlsplit

import requests
import streamlit as st
from models.limits import MAX_SOURCES, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from services.admission_policy import ADMISSION_POLICY_VERSION
from services.content_policy import ContentPolicyError, validate_lesson_content, validate_source_input

st.set_page_config(page_title="ScriptScout · Studio bài giảng", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
  .stApp {background: #f8f5ee; color: #173342;}
  [data-testid="stMainBlockContainer"] {max-width: 1180px; padding: 4.5rem 2.6rem 3rem;}
  [data-testid="stSidebar"] {background: #e9f1ed; border-right: 1px solid #c3d6ce;}
  [data-testid="stSidebarContent"] {padding-top: .6rem;}
  [data-testid="stAppDeployButton"], [data-testid="stMainMenu"] {display: none;}
  [data-testid="stHeader"] {background: #f8f5eef2;}
  h1, h2, h3 {letter-spacing: -.035em; font-weight: 650 !important;}
  h1 {font-size: 2.15rem !important; line-height: 1.2 !important;}
  h2 {font-size: 1.45rem !important;}
  h3 {font-size: 1.15rem !important;}
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
  [data-testid="stCaptionContainer"] span {color: #324d5a !important; line-height: 1.6; font-size: .875rem;}
  [data-testid="stWidgetLabel"] p, [data-testid="stMetricLabel"] p {color: #203f4a !important; font-weight: 600;}
  [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] > div {
    border-color: #dce5eb; border-radius: 16px;
  }
  [data-testid="stForm"] {background: #fffefb; padding: 1.6rem; border-top: 4px solid #0f766e; box-shadow: 0 6px 24px #203f4a06;}
  [data-testid="stExpander"] {background: #fffefb; border-radius: 12px;}
  [data-testid="stExpander"] summary p {color: #203f4a; font-weight: 600;}
  [data-testid="stExpander"] summary {min-height: 3rem;}
  .stButton button, .stDownloadButton button, .stLinkButton a, .stFormSubmitButton button {
    border-radius: 12px; min-height: 2.75rem; font-weight: 600; border-color: #b8ccc4;
  }
  button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] {
    background: #0f766e; border-color: #0f766e; color: white;
  }
  button[kind="primary"]:enabled:hover {background: #115e59; border-color: #115e59;}
  [data-testid="stMetric"] {background: #fffdf7; padding: 1rem 1.15rem; border: 1px solid #d7dacb; border-radius: 16px; border-top: 3px solid #d5a846;}
  [data-testid="stMetricValue"] {font-size: 1.8rem; color: #0f766e;}
  [class*="st-key-source-card-"] {background: #fffefb; border-radius: 16px; border-left: 4px solid #79b5a2 !important; box-shadow: 0 3px 12px #17334205;}
  [class*="st-key-source-card-"] [data-testid="stCheckbox"] {padding: .45rem .7rem; background: #edf5ed; border-radius: 9px;}
  .ss-brand {display: flex; align-items: center; gap: .65rem; padding: .3rem 0 .5rem; font-size: 1.4rem; font-weight: 720; letter-spacing: -.04em;}
  .ss-logo {display: grid; place-items: center; width: 35px; height: 35px; border-radius: 11px; background: #0f766e; color: white; font-size: 1rem; letter-spacing: -.05em;}
  .ss-eyebrow {font-size: .72rem; font-weight: 750; letter-spacing: .14em; color: #115e59; margin: 0 0 .6rem;}
  .ss-steps {display: flex; gap: .7rem; flex-wrap: wrap; margin: .2rem 0 1rem; color: #243f4a; font-size: .85rem;}
  .ss-steps span {background: #fff9e8; border: 1px solid #e7d6a5; border-radius: 100px; padding: .45rem .85rem; font-weight: 550;}
  .ss-steps b {color: #0f766e; padding-right: .3rem;}
  .ss-welcome {display: flex; align-items: center; justify-content: space-between; gap: 1.5rem; background: #edf3e9; background-image: radial-gradient(#4077611a 1px, transparent 1px); background-size: 16px 16px; border: 1px solid #c9d8c8; border-radius: 22px; padding: 1.5rem 1.8rem; margin-bottom: .85rem; overflow: hidden;}
  .ss-welcome > div {min-width: 0; overflow-wrap: anywhere;}
  .ss-welcome h1 {margin: 0 0 .6rem !important; padding: 0 !important; color: #163747; max-width: 750px; font-size: 2rem !important; line-height: 1.2 !important;}
  .ss-welcome p {margin: 0; color: #294d57; max-width: 680px; font-size: .97rem; line-height: 1.65;}
  .ss-welcome > svg {flex: 0 0 155px; width: 155px; height: 132px;}
  .ss-meta {display: flex; align-items: center; flex-wrap: wrap; gap: .5rem; margin: .5rem 0 .85rem;}
  .ss-badge {display: inline-flex; align-items: center; gap: .35rem; padding: .38rem .65rem; border-radius: 8px; font-size: .82rem; line-height: 1.3; font-weight: 700; color: #193d4b; background: #e7eff3; border: 1px solid #bdcfd7;}
  .ss-badge--ready {color: #14583d; background: #e3f2e8; border-color: #95c6a7;}
  .ss-badge--review {color: #714709; background: #fff0ca; border-color: #dec37c;}
  .ss-badge--blocked {color: #8b2430; background: #fce9e8; border-color: #dfa6aa;}
  .ss-badge--score {color: #fff; background: #244b5a; border-color: #244b5a;}
  .ss-badge--score strong {color: #fff !important; font-size: .95rem;}
  .ss-section {display: flex; align-items: center; gap: .65rem; color: #173e46; font-size: 1.02rem; font-weight: 700; margin: .6rem 0 1rem;}
  .ss-section span {display: grid; place-items: center; height: 30px; width: 30px; border-radius: 9px; background: #ffedbc; color: #725015; font-size: .82rem;}
  [class*="st-key-workspace-nav-"] {background: #e8efea; padding: .55rem; border: 1px solid #c2d3c8; border-radius: 16px; margin: .2rem 0 1rem;}
  [class*="st-key-workspace-nav-"] button {min-height: 3.65rem; border-radius: 12px; text-align: left; justify-content: flex-start; padding: .75rem 1rem; background: #fffdf6; color: #1d4350;}
  [class*="st-key-workspace-nav-"] button p {font-size: .97rem; font-weight: 700;}
  [class*="st-key-workspace-nav-"] button[kind="primary"] {background: #174b4b; color: #fff; border-color: #174b4b; box-shadow: 0 3px 8px #174b4b20;}
  [class*="st-key-workspace-nav-"] button[kind="primary"] p,
  [class*="st-key-workspace-nav-"] button[kind="primary"] span {color: #fff !important;}
  .ss-sidebar-note {border: 1px solid #d6c89b; background: #fff7de; border-radius: 12px; padding: .9rem; color: #58451c; font-size: .86rem; line-height: 1.6;}
  .ss-sidebar-note strong {color: #4a3d20;}
  @keyframes ss-content-enter {
    from {opacity: 0; transform: translateY(6px);}
    to {opacity: 1; transform: translateY(0);}
  }
  @keyframes ss-book-enter {
    from {opacity: 0; transform: translateY(5px) rotate(-3deg);}
    to {opacity: 1; transform: translateY(0) rotate(0);}
  }
  @keyframes ss-working {
    from {transform: translateX(-105%);}
    to {transform: translateX(305%);}
  }
  .stButton button, .stFormSubmitButton button, .stDownloadButton button, .stLinkButton a {
    transition: transform 140ms ease, box-shadow 160ms ease, background-color 160ms ease, border-color 160ms ease;
  }
  .stButton button:enabled:active, .stFormSubmitButton button:enabled:active,
  .stDownloadButton button:enabled:active, .stLinkButton a:not([aria-disabled="true"]):active {
    transform: translateY(0) scale(.985); box-shadow: 0 1px 3px #17334218;
  }
  .stButton button:focus-visible, .stFormSubmitButton button:focus-visible,
  .stDownloadButton button:focus-visible, .stLinkButton a:focus-visible,
  [data-testid="stExpander"] summary:focus-visible {
    outline: 3px solid #98690a; outline-offset: 3px;
  }
  .ss-welcome, [class*="st-key-view-content-"], [class*="st-key-source-card-"] {
    animation: ss-content-enter 220ms ease-out both;
  }
  .ss-welcome > svg {animation: ss-book-enter 340ms ease-out both; transform-origin: center;}
  [class*="st-key-source-card-"] {transition: box-shadow 180ms ease, border-color 180ms ease;}
  [class*="st-key-source-card-"]:focus-within {box-shadow: 0 5px 16px #17334210; border-left-color: #0f766e !important;}
  [data-testid="stExpander"] summary {transition: background-color 160ms ease; border-radius: 11px;}
  .ss-activity-track {height: 4px; overflow: hidden; border-radius: 100px; background: #d5e8df; margin: .35rem 0 .65rem;}
  .ss-activity-track > span {display: block; width: 34%; height: 100%; border-radius: inherit; background: #0f766e; animation: ss-working 1.55s ease-in-out infinite;}
  @media (hover: hover) and (pointer: fine) {
    .stButton button:enabled:hover, .stFormSubmitButton button:enabled:hover,
    .stDownloadButton button:enabled:hover, .stLinkButton a:not([aria-disabled="true"]):hover {
      transform: translateY(-1px); box-shadow: 0 5px 12px #17334218;
    }
    .stButton button:enabled:active, .stFormSubmitButton button:enabled:active,
    .stDownloadButton button:enabled:active, .stLinkButton a:not([aria-disabled="true"]):active {
      transform: translateY(0) scale(.985); box-shadow: 0 1px 3px #17334218;
    }
    [class*="st-key-source-card-"]:hover {box-shadow: 0 7px 22px #17334210; border-left-color: #0f766e !important;}
    [data-testid="stExpander"] summary:hover {background: #edf3e9;}
  }
  @media (prefers-reduced-motion: reduce) {
    .ss-welcome, .ss-welcome > svg, [class*="st-key-view-content-"], [class*="st-key-source-card-"],
    .stButton button, .stFormSubmitButton button, .stDownloadButton button, .stLinkButton a,
    [data-testid="stExpander"] summary, [data-testid="stSpinner"] *, [data-testid="stStatusWidget"] * {
      animation: none !important; transition: none !important; transform: none !important;
    }
    .ss-activity-track {display: none;}
    .ss-activity-track > span {animation: none;}
  }
  @media (max-width: 760px) {
    [data-testid="stMainBlockContainer"] {padding: 4rem 1rem 2rem;}
    h1 {font-size: 1.8rem !important;}
    [data-testid="stForm"] {padding: 1rem;}
    .ss-welcome {padding: 1.2rem; gap: .5rem;}
    .ss-welcome h1 {font-size: 1.65rem !important;}
    .ss-welcome > svg {display: none;}
    .ss-badge {font-size: .8rem; padding: .4rem .55rem;}
  }
</style>
""", unsafe_allow_html=True)
API_BASE = os.getenv("SCRIPTSCOUT_API_URL", "http://127.0.0.1:8000").rstrip("/")
ACTIVE_STATUSES = {"researching", "writing", "patching", "adding_source"}
STATUS_LABELS = {
    "researching": "Đang tìm và đọc tài liệu", "adding_source": "Đang đọc tài liệu bổ sung",
    "awaiting_review": "Chờ bạn duyệt nguồn", "writing": "Đang viết kịch bản",
    "patching": "Đang cập nhật kịch bản", "script_ready": "Kịch bản đã sẵn sàng",
    "failed": "Cần xử lý lỗi",
}
LANGUAGES = {
    "vi": "Tiếng Việt", "en": "Tiếng Anh", "fr": "Tiếng Pháp", "de": "Tiếng Đức",
    "ja": "Tiếng Nhật", "ko": "Tiếng Hàn", "zh": "Tiếng Trung", "es": "Tiếng Tây Ban Nha",
}
TRUST_LABELS = {
    "domain_authority": "Uy tín nơi xuất bản", "recency": "Tính cập nhật",
    "evidence_quality": "Chất lượng bằng chứng", "author_credibility": "Uy tín tác giả",
}
STYLE_PRESETS = {
    "Giải thích từng bước": "Giải thích từ trực giác đến khái niệm, chia nhỏ từng bước và chốt ý sau mỗi phần.",
    "Gợi mở bằng câu hỏi": "Dẫn dắt bằng câu hỏi gợi mở, dành nhịp dừng cho người học suy nghĩ rồi giải thích lập luận.",
    "Kể chuyện và ví dụ": "Bắt đầu bằng một tình huống gần gũi, kể chuyện ngắn và dùng ví dụ để dẫn đến kiến thức.",
    "Thực hành và giải quyết vấn đề": "Bắt đầu từ bài toán thực tế, làm mẫu từng bước rồi giao một nhiệm vụ ngắn để người học vận dụng.",
    "Phong cách riêng của tôi": "",
}
VIEWS = {"sources": "01 · Tài liệu và bằng chứng", "script": "02 · Kịch bản có dẫn nguồn"}
SOURCES_PER_PAGE = 8
ADMISSION_UPDATING_MESSAGE = "Ứng dụng đang cập nhật bước kiểm tra nội dung. Hãy thử lại sau."


class APIError(RuntimeError):
    """A concise API failure suitable for showing in the studio."""


def detail_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " · ".join(detail_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("message", "description", "summary", "detail", "reason", "msg"):
            if value.get(key):
                return detail_text(value[key])
        return "; ".join(f"{key}: {detail_text(item)}" for key, item in value.items())
    return str(value) if value is not None else ""


def public_message(value: Any, *, fallback: str = "Chưa thể hoàn tất thao tác. Hãy thử lại sau; bài giảng đã lưu vẫn được giữ nguyên.") -> str:
    """Keep useful lesson feedback while removing internal service diagnostics."""
    message = detail_text(value).strip()
    if not message:
        return fallback
    lower = message.casefold()
    if lower.startswith("model đọc"):
        return "Chỉ phần đầu tài liệu đã được đọc; phần còn lại chưa được kiểm tra."
    if "không thể thẩm định bằng model" in lower:
        return "Chưa thể đánh giá tài liệu này. Thử đọc lại nguồn hoặc bổ sung một bản khác."
    if "chưa hoàn tất đối chiếu bằng model" in lower:
        return "Chưa hoàn tất đối chiếu nội dung. Cần kiểm tra thêm những khác biệt giữa nguồn."
    if "model đánh giá phù hợp ngữ nghĩa" in lower:
        return "Đối chiếu tự động chưa phát hiện khác biệt; giảng viên vẫn cần kiểm tra ý nghĩa."
    internal = r"\b(?:API|HTTP|provider|endpoint|model|Gemini|OpenAI|Tavily|Google|token|quota|traceback|sqlite|localhost|connectionerror|apikey)\b|\.env\b|127\.0\.0\.1|API_KEY|AIza|sk-[A-Za-z0-9]{8,}|mô hình AI|cấu hình|máy chủ"
    if re.search(internal, message, flags=re.I):
        return fallback
    return message


def api_request(method: str, path: str, *, payload: dict | None = None, binary: bool = False,
                files: dict | None = None, form_data: dict | None = None) -> Any:
    try:
        kwargs = {"data": form_data, "files": files} if files else {"json": payload}
        response = requests.request(method, f"{API_BASE}{path}", timeout=(5, 25), **kwargs)
    except requests.Timeout as exc:
        raise APIError("Việc xử lý đang lâu hơn dự kiến. Tác vụ có thể vẫn đang chạy; mở lại bài giảng đã lưu để kiểm tra trước khi gửi lại.") from exc
    except requests.ConnectionError as exc:
        raise APIError("Chưa thể tải bài giảng lúc này. Vui lòng thử lại sau.") from exc
    except requests.RequestException as exc:
        raise APIError("Chưa thể thực hiện yêu cầu. Vui lòng thử lại sau.") from exc
    if not response.ok:
        try:
            detail = response.json().get("detail", "")
        except (ValueError, AttributeError):
            detail = ""
        if isinstance(detail, list):
            readable = "Thông tin bài giảng chưa hợp lệ. Kiểm tra các mục bạn đã nhập rồi thử lại."
        else:
            readable = public_message(detail)
        raise APIError(readable)
    if binary:
        return response.content
    try:
        result = response.json()
    except ValueError as exc:
        raise APIError("Chưa thể đọc kết quả bài giảng. Vui lòng thử lại sau.") from exc
    if not isinstance(result, dict):
        raise APIError("Chưa thể đọc kết quả bài giảng. Vui lòng thử lại sau.")
    return result


@st.cache_data(ttl=15, show_spinner=False)
def read_health() -> tuple[dict, str | None]:
    try:
        return api_request("GET", "/api/health"), None
    except APIError as exc:
        return {}, str(exc)


def has_current_admission(health: dict) -> bool:
    capability = health.get("research_admission")
    return (
        isinstance(capability, dict)
        and capability.get("required") is True
        and capability.get("policy_version") == ADMISSION_POLICY_VERSION
        and capability.get("configured") is True
    )


def require_current_admission() -> None:
    """Check the live server immediately before each paid dispatch, never a cache."""
    try:
        latest_health = api_request("GET", "/api/health")
    except APIError:
        raise APIError(ADMISSION_UPDATING_MESSAGE) from None
    if not has_current_admission(latest_health):
        raise APIError(ADMISSION_UPDATING_MESSAGE)


def accept_session(envelope: dict) -> None:
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise APIError("Chưa thể mở bài giảng này. Hãy thử chọn lại bài giảng đã lưu.")
    session_id = envelope.get("session_id") or data.get("session_id")
    if not session_id:
        raise APIError("Chưa thể mở bài giảng này. Hãy thử chọn lại bài giảng đã lưu.")
    if "status" not in data:
        data["status"] = envelope.get("status", "awaiting_review")
    previous = st.session_state.get("session") or {}
    if st.session_state.get("session_id") != session_id:
        st.session_state.workspace_view = "script" if data.get("script") else "sources"
    elif previous.get("status") in {"writing", "patching"} and data.get("status") == "script_ready":
        st.session_state.workspace_view = "script"
    st.session_state.session_id = session_id
    st.session_state.session = data
    st.session_state.action_error = None
    st.session_state.export_files = None


def set_view(view: str) -> None:
    st.session_state.workspace_view = view


def remember_source_choice(evidence_key: str, widget_key: str) -> None:
    st.session_state.source_choices[evidence_key]["selected"] = bool(st.session_state[widget_key])


def remember_library_filter(session_id: str, field: str, widget_key: str) -> None:
    library = st.session_state.source_filters[session_id]
    library[field] = st.session_state[widget_key]
    if field != "page":
        library["page"] = 1


def sync_source_choice(source: dict, session_id: str, *, active_ids: set[str], already_written: bool) -> dict:
    source_id = source["source_id"]
    evidence_key = f"{session_id}:{source_id}"
    is_active = source_id in active_ids
    choice = st.session_state.source_choices.setdefault(
        evidence_key, {"selected": is_active if already_written else True, "active": is_active},
    )
    if not eligible_source(source):
        choice["selected"] = False
    elif already_written and choice["active"] != is_active:
        choice["selected"] = is_active
    choice["active"] = is_active
    return choice


def forget_session(session_id: str) -> None:
    """Discard only the deleted session's UI data, leaving other sessions intact."""
    for mapping_key in ("evidence", "source_choices"):
        mapping = st.session_state[mapping_key]
        for key in list(mapping):
            if key.startswith(f"{session_id}:"):
                del mapping[key]
    st.session_state.source_filters.pop(session_id, None)
    for key in list(st.session_state):
        if key.startswith(tuple(f"{prefix}:{session_id}:" for prefix in ("approve", "active", "raw", "evidence", "retry"))) or key in {f"{prefix}:{session_id}" for prefix in ("remove", "upload", "source-query", "source-filter", "source-language", "source-page")}:
            del st.session_state[key]
    if st.session_state.session_id == session_id:
        st.session_state.session_id = None
        st.session_state.session = None
        st.session_state.export_files = None
        st.session_state.action_error = None
        set_view("sources")


def readable_source_message(value: Any) -> str:
    message = detail_text(value)
    # Successful page cleaning is an implementation detail, including in saved sessions.
    if re.fullmatch(r"(?:S\d+:\s*)?Đã loại \d+ phần tử HTML bị ẩn khỏi nội dung dùng làm dẫn chứng\.?", message.strip()):
        return ""
    if "HTTP 403" in message:
        return "Trang xuất bản không cho phép ứng dụng đọc tài liệu này. Hãy thử tìm bản công khai bằng nút bên dưới hoặc bổ sung đường dẫn PDF được phép truy cập."
    if message == "Không đọc được toàn văn; không dùng đoạn mô tả tìm kiếm làm bằng chứng.":
        return "Chưa đọc được nội dung bài viết nên nguồn này chưa thể dùng để dẫn chứng."
    return public_message(message, fallback="Chưa thể hoàn tất kiểm tra tài liệu này. Hãy đọc lại nguồn hoặc bổ sung bản PDF của bạn.") if message else ""


def act(path: str, payload: dict) -> None:
    try:
        request_data = payload if path == "/api/pipeline/start" else (st.session_state.session or {}).get("req", {})
        validate_lesson_content(request_data)
        if path == "/api/pipeline/sources":
            validate_source_input(payload.get("url", ""))
        require_current_admission()
        pending_label = {
            "/api/pipeline/start": "Đang kiểm tra mục đích bài giảng…",
            "/api/pipeline/review": "Đang chuẩn bị viết kịch bản…",
            "/api/pipeline/patch": "Đang cập nhật các nguồn bạn chọn…",
            "/api/pipeline/sources": "Đang mở tài liệu bạn bổ sung…",
            "/api/pipeline/sources/retry": "Đang thử đọc lại tài liệu…",
        }.get(path, "Đang xử lý yêu cầu…")
        with st.spinner(pending_label):
            accept_session(api_request("POST", path, payload=payload))
    except ContentPolicyError as exc:
        st.session_state.action_error = exc.public_message
    except APIError as exc:
        st.session_state.action_error = str(exc)
    st.rerun()


def safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"https", "http"} and parsed.hostname else None
    except ValueError:
        return None


def eligible_source(source: dict) -> bool:
    return (
        not source.get("has_prompt_injection")
        and source.get("is_accessible") is not False
        and str(source.get("status", "")).lower() not in {
            "blocked", "inaccessible", "unreachable", "failed", "error", "excluded"
        }
        and any(claim.get("is_verified") for claim in source.get("claims", []))
    )


def show_messages(messages: list, *, kind: str = "warning", source_labels: dict | None = None) -> None:
    source_labels = source_labels or {}
    for item in messages:
        message = readable_source_message(item)
        if isinstance(item, dict) and "source_a_claim" in item:
            message = (
                f"{item.get('topic', 'Điểm khác biệt giữa nguồn')}\n\n"
                f"{source_labels.get(item.get('source_a_id'), 'Nguồn thứ nhất')}: {item.get('source_a_claim', '')}\n\n"
                f"{source_labels.get(item.get('source_b_id'), 'Nguồn thứ hai')}: {item.get('source_b_claim', '')}"
            )
        elif isinstance(item, dict) and item.get("source_ids"):
            message += " · " + ", ".join(source_labels.get(sid, "Tài liệu liên quan") for sid in item["source_ids"])
        if message:
            getattr(st, kind)(message)


def render_verification_summary(summary: Any) -> None:
    if not isinstance(summary, dict):
        st.info(detail_text(summary))
        return
    labels = {
        "total_lines": "Tổng số câu", "factual_lines": "Câu chứa thông tin thực tế",
        "unverified_lines": "Câu cần kiểm tra thêm", "original_quotes_matched": "Trích dẫn khớp nguyên văn",
    }
    values = [(label, summary[key]) for key, label in labels.items() if key in summary]
    if values:
        for column, (label, value) in zip(st.columns(len(values)), values):
            column.metric(label, value)
    if summary.get("human_review_required"):
        st.caption("Giảng viên cần duyệt nội dung và ý nghĩa của bằng chứng trước khi ghi hình.")


def render_trust_criteria(criteria: Any) -> None:
    if not isinstance(criteria, dict):
        st.write(detail_text(criteria))
        return
    for key, criterion in criteria.items():
        label = TRUST_LABELS.get(key, "Tiêu chí bổ sung")
        if isinstance(criterion, dict):
            weight = criterion.get("weight")
            if isinstance(weight, (float, int)):
                label += f" · {weight:.0%}"
            st.markdown(f"**{label}**")
            if criterion.get("description"):
                st.write(criterion["description"])
        else:
            st.write(f"{label}: {criterion}")


def render_progress(data: dict) -> None:
    status = data.get("status", "")
    is_active = status in ACTIVE_STATUSES
    with st.status(
        STATUS_LABELS.get(status, "Đang chuẩn bị bài giảng"),
        state="running" if is_active else "error" if status == "failed" else "complete",
        expanded=is_active or status == "failed",
    ):
        progress_labels = {
            "planning": "Lập kế hoạch tìm tài liệu theo mục tiêu bài học.",
            "search": "Tìm tài liệu trong các ngôn ngữ bạn chọn.",
            "searching": "Tìm tài liệu trong các ngôn ngữ bạn chọn.",
            "research": "Tìm và đọc tài liệu cho bài giảng.",
            "researching": "Tìm và đọc tài liệu cho bài giảng.",
            "fetching": "Đọc tài liệu và tìm bản công khai khi cần.",
            "reading_pdf": "Đọc nội dung tệp PDF bạn cung cấp.",
            "evaluating": "Tóm tắt tiếng Việt và kiểm tra bằng chứng.",
            "cross_checking": "Đối chiếu luận điểm và số liệu giữa các nguồn.",
            "writing": "Viết kịch bản theo phong cách giảng dạy của bạn.",
            "verifying": "Kiểm tra từng câu và dẫn chứng trong kịch bản.",
            "patching": "Cập nhật các câu liên quan đến nguồn bạn thay đổi.",
            "completed": "Đã lưu kết quả bài giảng.",
            "failed": "Chưa hoàn tất bước này. Bạn có thể thử lại thao tác.",
        }
        rendered = set()
        for event in (data.get("progress") or [])[-10:]:
            label = progress_labels.get(event.get("step"), "Đang xử lý bài giảng.")
            if label not in rendered:
                st.write(label)
                rendered.add(label)
        if is_active:
            st.markdown(
                '<div class="ss-activity-track" role="progressbar" aria-label="Tiến trình bài giảng" '
                f'aria-valuetext="{escape(STATUS_LABELS.get(status, "Đang xử lý bài giảng"))}"><span></span></div>',
                unsafe_allow_html=True,
            )
            st.caption("Tự cập nhật mỗi 3 giây. Bạn có thể mở lại phiên này trong danh sách phiên đã lưu.")


def poll_session() -> None:
    """Only progress polls; a change of workflow status rerenders the studio."""
    current = st.session_state.session or {}
    previous_status = current.get("status")
    try:
        accept_session(api_request("GET", f"/api/sessions/{st.session_state.session_id}"))
        current = st.session_state.session
    except APIError as exc:
        st.warning(str(exc))
    render_progress(current)
    if current.get("status") != previous_status:
        st.rerun()


def render_source(source: dict, session_id: str, *, busy: bool,
                  active_ids: set[str], already_written: bool, source_number: int) -> bool:
    with st.container(border=True, key=f"source-card-{session_id}-{source['source_id']}"):
        return render_source_card(source, session_id, busy=busy, active_ids=active_ids, already_written=already_written, source_number=source_number)


def render_source_card(source: dict, session_id: str, *, busy: bool,
                  active_ids: set[str], already_written: bool, source_number: int) -> bool:
    source_id = str(source.get("source_id", ""))
    can_approve = eligible_source(source)
    language = LANGUAGES.get(source.get("language"), "Chưa rõ ngôn ngữ")
    title = source.get("title") or source.get("url") or "Nguồn chưa có tiêu đề"
    try:
        score = float(source.get("trust_score", 0))
        score_label = f"{score:.0f}/100"
    except (TypeError, ValueError):
        score, score_label = None, "Chưa chấm điểm"
    if source.get("is_accessible") is False:
        score_label = "Chưa đánh giá"
    evidence_key = f"{session_id}:{source_id}"
    st.markdown(f"**{source_number:02d} · {title}**")
    state_label = "Có bằng chứng để duyệt" if can_approve else "Nguồn bị chặn" if source.get("has_prompt_injection") else "Chưa đủ bằng chứng"
    state_class = "ready" if can_approve else "blocked" if source.get("has_prompt_injection") else "review"
    st.markdown(
        f'<div class="ss-meta"><span class="ss-badge">Ngôn ngữ: {escape(language)}</span>'
        f'<span class="ss-badge ss-badge--{state_class}">{escape(state_label)}</span>'
        f'<span class="ss-badge ss-badge--score">Điểm sàng lọc <strong>{escape(score_label)}</strong></span></div>',
        unsafe_allow_html=True,
    )
    summary = source.get("summary_vi") or ""
    if summary:
        st.write(summary if len(summary) <= 240 else summary[:237].rsplit(" ", 1)[0] + "…")
    elif source.get("is_accessible") is False:
        st.caption("Chưa đọc được tài liệu. Mở phần đánh giá bên dưới để tìm bản công khai hoặc bổ sung PDF của bạn.")
    choice = sync_source_choice(source, session_id, active_ids=active_ids, already_written=already_written)
    key = f"approve:{session_id}:{source_id}"
    # Canonical choices survive filtering, pagination and hidden widget cleanup.
    st.session_state[key] = choice["selected"]
    selected = st.checkbox("Dùng nguồn này khi viết kịch bản", key=key, disabled=busy or not can_approve,
                           on_change=remember_source_choice, args=(evidence_key, key))
    with st.expander("Đọc bằng chứng và đánh giá", expanded=False):
        metadata = [source.get("author"), source.get("published_date")]
        st.caption(" · ".join(str(item) for item in metadata if item) or "Chưa xác định tác giả / ngày xuất bản")
        original_url = safe_url(source.get("original_url") or source.get("url"))
        url = safe_url(source.get("final_url") or source.get("url"))
        if url:
            if original_url and url != original_url and source.get("retrieval_method") == "public_repository":
                st.caption("Đã đọc một bản công khai của nghiên cứu này để lấy bằng chứng.")
                st.link_button("Mở bản công khai đã đọc ↗", url)
                st.link_button("Trang xuất bản ban đầu ↗", original_url)
            else:
                st.link_button("Mở tài liệu gốc ↗", url)
        elif source.get("document_kind") == "uploaded_pdf":
            st.caption(f"Tài liệu PDF bạn đã tải lên: {source.get('uploaded_filename') or title}")
        if source.get("retrieval_note"):
            st.caption(readable_source_message(source["retrieval_note"]))
        if st.button("Xem bản nội dung đã tải", key=f"evidence:{evidence_key}", disabled=busy):
            try:
                result = api_request("GET", f"/api/sessions/{session_id}/sources/{source_id}")
                st.session_state.evidence[evidence_key] = result.get("raw_source") or {}
            except APIError as exc:
                st.error(str(exc))
        if evidence_key in st.session_state.evidence:
            raw = st.session_state.evidence[evidence_key]
            if raw.get("raw_markdown"):
                st.text_area(
                    "Nội dung gốc đã lưu", value=raw["raw_markdown"],
                    height=240, disabled=True, key=f"raw:{evidence_key}",
                )
                st.caption(f"Thời điểm tải: {raw.get('fetched_at') or 'Chưa xác định'}")
                if raw.get("content_hash"):
                    st.caption(f"Mã kiểm tra nội dung: {raw['content_hash']}")
            else:
                st.info("Phiên này chưa có bản văn bản gốc được lưu cho nguồn này.")
        if source.get("summary_vi"):
            st.write(source["summary_vi"])
        if source.get("trust_reasoning"):
            reasoning = readable_source_message(source["trust_reasoning"])
            if reasoning:
                st.info(reasoning)
        breakdown = source.get("trust_breakdown") or {}
        if breakdown:
            st.caption("Thành phần điểm: " + " · ".join(f"{TRUST_LABELS.get(key, 'Tiêu chí bổ sung')}: {value}" for key, value in breakdown.items()))
        if score is not None and score < 40 and source.get("is_accessible") is not False:
            st.warning("Điểm sàng lọc thấp. Xem kỹ bằng chứng và đối chiếu thêm trước khi dùng.")
        if source.get("has_prompt_injection"):
            st.error("Nguồn bị chặn vì chứa chỉ dẫn có thể làm sai lệch kết quả; không dùng để viết kịch bản.")
        if source.get("is_outdated"):
            st.warning("Nguồn có dấu hiệu cũ. Đối chiếu bối cảnh và thời điểm trước khi sử dụng.")
        if source.get("error_message"):
            message = readable_source_message(source["error_message"])
            if message:
                st.error(message)
        show_messages(source.get("warnings") or [])
        inaccessible = source.get("is_accessible") is False or str(source.get("status", "")).lower() in {"inaccessible", "unreachable", "failed", "error"}
        if inaccessible and not source.get("has_prompt_injection") and original_url:
            st.caption("Thử tìm bản được chia sẻ công khai của cùng nghiên cứu. Nếu chưa có bản phù hợp, bạn có thể tải tệp PDF ở cuối trang.")
            if st.button("Tìm bản công khai và đọc lại", key=f"retry:{evidence_key}", disabled=busy):
                set_view("sources")
                st.session_state.evidence.pop(evidence_key, None)
                act("/api/pipeline/sources/retry", {"session_id": session_id, "source_id": source_id})
        if source.get("claims"):
            st.markdown("**Luận điểm và bằng chứng**")
        for claim_number, claim in enumerate(source.get("claims") or [], start=1):
            label = "✓ Khớp nguyên văn" if claim.get("is_verified") else "⚠ Chưa khớp nguyên văn"
            st.markdown(f"**Luận điểm {claim_number}** · {label}")
            st.write(claim.get("claim_text", ""))
            if claim.get("is_statistical"):
                st.caption("Luận điểm chứa số liệu — kiểm tra đơn vị, mốc thời gian và phạm vi.")
            st.caption("Trích nguyên văn")
            st.text(claim.get("snippet_quote") or "Không có trích dẫn gốc.")
            if claim.get("snippet_translation_vi"):
                st.caption("Bản dịch tiếng Việt")
                st.write(claim["snippet_translation_vi"])
            if claim.get("verification_note"):
                st.caption(public_message(claim["verification_note"], fallback="Cần đối chiếu lại bằng chứng trong tài liệu."))
            st.divider()
        if not can_approve:
            st.caption("Chưa đủ điều kiện phê duyệt: nguồn phải truy cập được, không bị chặn và có ít nhất một trích dẫn khớp nguyên văn.")
    return bool(selected and can_approve)


def render_dossier(data: dict, *, busy: bool) -> None:
    dossier = data.get("dossier") or {}
    sources = dossier.get("sources") or []
    session_id = st.session_state.session_id
    active_ids = set(data.get("active_source_ids") or [])
    source_numbers = {source["source_id"]: index for index, source in enumerate(sources, 1)}
    source_labels = {source_id: f"Nguồn {number:02d}" for source_id, number in source_numbers.items()}
    already_written = bool(data.get("script"))
    library = st.session_state.source_filters.setdefault(session_id, {"query": "", "filter": "Tất cả", "language": "", "page": 1})
    approved_ids = [source["source_id"] for source in sources
                    if sync_source_choice(source, session_id, active_ids=active_ids, already_written=already_written)["selected"]]
    st.subheader("Thư viện tài liệu")
    st.caption("Đọc tóm tắt tiếng Việt, đối chiếu nguyên văn rồi chọn nguồn cho bài giảng.")
    if sources:
        total, usable, chosen = st.columns(3)
        total.metric("Tài liệu đã tìm", len(sources))
        usable.metric("Có bằng chứng", sum(eligible_source(source) for source in sources))
        chosen.metric("Đã chọn", len(approved_ids))
    notices = dossier.get("warnings") or []
    conflicts = dossier.get("conflicts") or []
    if notices or conflicts:
        with st.expander(f"Lưu ý và điểm cần đối chiếu · {len(notices) + len(conflicts)}"):
            st.caption("Điểm tin cậy giúp sàng lọc. Trích dẫn khớp nguyên văn vẫn cần được kiểm tra ý nghĩa và bối cảnh.")
            show_messages(notices, source_labels=source_labels)
            show_messages(conflicts, source_labels=source_labels)
    if not sources:
        st.info("Tài liệu sẽ xuất hiện sau khi agent tìm kiếm và đọc nguồn. Bạn có thể bổ sung đường dẫn tài liệu khi tác vụ hoàn tất.")
    filtered = sources
    if sources:
        query_col, status_col, language_col = st.columns([2, 1.2, 1.2])
        query_key, filter_key, language_key = (f"source-{field}:{session_id}" for field in ("query", "filter", "language"))
        for field, key in (("query", query_key), ("filter", filter_key), ("language", language_key)):
            st.session_state[key] = library[field]
        with query_col:
            query = st.text_input("Tìm trong tài liệu", placeholder="Tiêu đề, từ khóa hoặc mã nguồn…", key=query_key,
                                  on_change=remember_library_filter, args=(session_id, "query", query_key))
        with status_col:
            source_filter = st.selectbox("Trạng thái nguồn", ["Tất cả", "Đã chọn", "Có bằng chứng", "Chưa đủ bằng chứng"], key=filter_key,
                                          on_change=remember_library_filter, args=(session_id, "filter", filter_key))
        with language_col:
            language_codes = sorted({source.get("language") or "unknown" for source in sources})
            if library["language"] not in [""] + language_codes:
                st.session_state[language_key] = library["language"] = ""
            language = st.selectbox("Ngôn ngữ", [""] + language_codes, format_func=lambda code: LANGUAGES.get(code, "Chưa rõ ngôn ngữ") if code else "Tất cả ngôn ngữ", key=language_key,
                                     on_change=remember_library_filter, args=(session_id, "language", language_key))
        query = query.strip().casefold()
        filtered = [source for source in sources
                    if (not query or query in " ".join(str(source.get(key) or "") for key in ("source_id", "title", "summary_vi")).casefold())
                    and (not language or (source.get("language") or "unknown") == language)
                    and (source_filter == "Tất cả" or source_filter == "Đã chọn" and source["source_id"] in approved_ids
                         or source_filter == "Có bằng chứng" and eligible_source(source)
                         or source_filter == "Chưa đủ bằng chứng" and not eligible_source(source))]
        render_review_action(data, approved_ids, busy=busy, position="top")
    page_count = max(1, (len(filtered) + SOURCES_PER_PAGE - 1) // SOURCES_PER_PAGE)
    page_key = f"source-page:{session_id}"
    if library["page"] > page_count:
        library["page"] = 1
    st.session_state[page_key] = library["page"]
    if page_count > 1:
        page = st.selectbox("Trang tài liệu", list(range(1, page_count + 1)),
                            format_func=lambda value: f"Trang {value} / {page_count}", key=page_key,
                            on_change=remember_library_filter, args=(session_id, "page", page_key))
    else:
        page = 1
    start = (page - 1) * SOURCES_PER_PAGE
    if filtered:
        st.caption(f"Đang xem {start + 1}–{min(start + SOURCES_PER_PAGE, len(filtered))} trong {len(filtered)} tài liệu phù hợp. Lựa chọn được giữ ở mọi trang.")
    elif sources:
        st.info("Không có tài liệu phù hợp với bộ lọc. Thử từ khóa hoặc ngôn ngữ khác.")
    for source in filtered[start:start + SOURCES_PER_PAGE]:
        render_source(source, session_id, busy=busy, active_ids=active_ids, already_written=already_written,
                       source_number=source_numbers[source["source_id"]])
    if page_count > 1:
        previous, next_page = st.columns(2)
        previous.button("← Trang trước", disabled=page == 1, use_container_width=True,
                        on_click=turn_source_page, args=(session_id, page_key, -1))
        next_page.button("Trang sau →", disabled=page == page_count, use_container_width=True,
                         on_click=turn_source_page, args=(session_id, page_key, 1))
    if sources:
        render_review_action(data, approved_ids, busy=busy, position="bottom")
    with st.expander("Bổ sung tài liệu · Đường dẫn hoặc PDF", expanded=not sources):
        render_add_source(session_id, source_count=len(sources), busy=busy)
    if dossier.get("search_queries_used"):
        with st.expander("Các từ khóa đã dùng để tìm nguồn"):
            for query in dossier["search_queries_used"]:
                st.write(detail_text(query))


def turn_source_page(session_id: str, key: str, step: int) -> None:
    st.session_state[key] += step
    st.session_state.source_filters[session_id]["page"] = st.session_state[key]


def render_review_action(data: dict, approved_ids: list[str], *, busy: bool, position: str) -> None:
    if position == "bottom" and data.get("script"):
        st.caption("Chỉ cập nhật các câu bị ảnh hưởng khi bạn thay đổi nguồn đã duyệt.")
    label_col, action_col = st.columns([1, 1.5], vertical_alignment="center")
    label_col.caption(f"{len(approved_ids)} nguồn đã chọn trên toàn bộ danh sách")
    with action_col:
        if st.button(
            "Cập nhật nguồn đã duyệt" if data.get("script") else "Duyệt nguồn và viết kịch bản",
            key=f"review:{position}", type="primary", disabled=busy or not approved_ids, use_container_width=True,
        ):
            act("/api/pipeline/review", {"session_id": st.session_state.session_id, "approved_source_ids": approved_ids})


def render_add_source(session_id: str, *, source_count: int, busy: bool) -> None:
    busy = busy or source_count >= MAX_SOURCES
    if source_count >= MAX_SOURCES:
        st.info(f"Phiên đã đủ {MAX_SOURCES} nguồn. Bạn vẫn có thể đọc và thay đổi lựa chọn trong thư viện.")
    st.caption("Có tài liệu chuyên ngành? Thêm đường dẫn hoặc tệp PDF để đọc cùng các nguồn đã tìm.")
    with st.form(f"add_source:{session_id}", clear_on_submit=False):
        manual_url = st.text_input("Đường dẫn tài liệu", placeholder="https://…", disabled=busy)
        add_source = st.form_submit_button("Đọc và bổ sung nguồn", disabled=busy)
    if add_source:
        if not safe_url(manual_url.strip()):
            st.error("Nhập đường dẫn hợp lệ bắt đầu bằng https:// hoặc http://.")
        else:
            set_view("sources")
            act("/api/pipeline/sources", {"session_id": session_id, "url": manual_url.strip()})
    st.markdown("**Hoặc tải tài liệu PDF bạn có**")
    st.caption(f"Dùng khi trang xuất bản yêu cầu đăng nhập hoặc chặn đọc tự động. Mỗi tệp tối đa {MAX_UPLOAD_MB} MB.")
    uploaded_pdf = st.file_uploader("Chọn tệp PDF", type=["pdf"], disabled=busy, key=f"upload:{session_id}", max_upload_size=MAX_UPLOAD_MB)
    if st.button("Đọc PDF của tôi", disabled=busy or uploaded_pdf is None):
        if uploaded_pdf.size > MAX_UPLOAD_BYTES:
            st.error(f"Tệp vượt quá {MAX_UPLOAD_MB} MB. Hãy chọn bản PDF nhỏ hơn.")
        else:
            try:
                validate_lesson_content((st.session_state.session or {}).get("req", {}))
                validate_source_input(uploaded_pdf.name, field="filename")
                require_current_admission()
                set_view("sources")
                with st.spinner("Đang gửi tài liệu PDF của bạn…"):
                    accept_session(api_request("POST", "/api/pipeline/sources/upload",
                                               form_data={"session_id": session_id},
                                               files={"file": (uploaded_pdf.name, uploaded_pdf.getvalue(), "application/pdf")}))
            except ContentPolicyError as exc:
                st.session_state.action_error = exc.public_message
            except APIError as exc:
                st.session_state.action_error = str(exc)
            st.rerun()


def render_script(data: dict, *, busy: bool) -> None:
    script = data.get("script") or {}
    if not script:
        st.info("Chọn mục Tài liệu và duyệt ít nhất một nguồn để viết kịch bản theo phong cách giảng dạy của bạn.")
        return
    sources = (data.get("dossier") or {}).get("sources") or []
    source_lookup = {source["source_id"]: source for source in sources}
    source_numbers = {source["source_id"]: index for index, source in enumerate(sources, 1)}
    st.subheader(script.get("title") or "Kịch bản bài giảng")
    st.caption(f"Thời lượng ước tính: {script.get('estimated_duration_minutes', '—')} phút · Nội dung tiếng Việt")
    if script.get("teaching_style"):
        with st.expander("Phong cách được áp dụng"):
            st.write(script["teaching_style"])
    if script.get("verification_summary"):
        render_verification_summary(script["verification_summary"])
    st.caption("Mở “Xem dẫn chứng” để đối chiếu nguyên văn và bản dịch. Giảng viên cần duyệt ý nghĩa trước khi ghi hình.")
    show_messages(script.get("warnings") or [])
    for index, scene in enumerate(script.get("scenes") or [], start=1):
        st.markdown(f"### {scene.get('scene_number', index)}. {scene.get('scene_label') or scene.get('title') or 'Cảnh bài giảng'}")
        st.caption(f"Khoảng {scene.get('estimated_duration_seconds', '—')} giây")
        if scene.get("visual_cue"):
            st.markdown("**Hình ảnh / trình chiếu**")
            st.write(scene["visual_cue"])
        if scene.get("speaker_note"):
            st.markdown("**Gợi ý cho giảng viên**")
            st.write(scene["speaker_note"])
        for line in scene.get("lines") or []:
            st.write(line.get("text", ""))
            if line.get("is_unverified"):
                st.warning(public_message(line.get("verification_note"), fallback="Câu này chưa đủ bằng chứng; cần đối chiếu trước khi sử dụng."))
            refs = line.get("source_refs") or []
            if refs:
                ref_count = len({ref.get("source_id") for ref in refs})
                with st.expander(f"Xem dẫn chứng · {ref_count} nguồn"):
                    if line.get("verification_note") and not line.get("is_unverified"):
                        st.caption(public_message(line["verification_note"], fallback="Cần đối chiếu ý nghĩa câu với tài liệu gốc."))
                    for ref in refs:
                        source = source_lookup.get(ref.get("source_id"), {})
                        st.markdown(f"**{source.get('title') or 'Tài liệu gốc'}**")
                        url = safe_url(ref.get("url") or source.get("final_url") or source.get("url"))
                        if url:
                            st.link_button("Mở bằng chứng gốc ↗", url)
                        st.caption("Trích nguyên văn")
                        st.text(ref.get("snippet_quote") or "Không có trích dẫn.")
                        if ref.get("snippet_translation_vi"):
                            st.caption("Bản dịch tiếng Việt")
                            st.write(ref["snippet_translation_vi"])
                        st.caption("✓ Khớp nguyên văn" if ref.get("is_verified") else "⚠ Chưa khớp nguyên văn")
            elif line.get("has_factual_content") and not line.get("is_unverified"):
                st.warning("Phát biểu có nội dung thực tế nhưng chưa có dẫn nguồn đính kèm.")
        st.divider()
    st.markdown("**Loại bỏ nguồn và cập nhật các câu liên quan**")
    removable = [sid for sid in data.get("active_source_ids") or [] if sid in source_lookup]
    selected = st.multiselect(
        "Nguồn muốn loại bỏ", removable,
        format_func=lambda sid: f"Nguồn {source_numbers[sid]:02d} · {source_lookup[sid].get('title', '')}",
        key=f"remove:{st.session_state.session_id}", disabled=busy,
    )
    if selected and len(selected) == len(removable):
        st.warning("Bạn đang loại bỏ tất cả nguồn. Các câu mất bằng chứng sẽ được đánh dấu chưa kiểm chứng để bạn bổ sung tài liệu hoặc điều chỉnh.")
    if st.button("Bỏ nguồn và cập nhật kịch bản",
                 disabled=busy or not selected):
        act("/api/pipeline/patch", {"session_id": st.session_state.session_id, "remove_source_ids": selected})


def render_exports(*, busy: bool) -> None:
    st.divider()
    if st.button("Chuẩn bị tệp tải xuống", disabled=busy):
        try:
            session_id = st.session_state.session_id
            st.session_state.export_files = {
                "markdown": api_request("GET", f"/api/sessions/{session_id}/export?format=markdown", binary=True),
                "json": api_request("GET", f"/api/sessions/{session_id}/export?format=json", binary=True),
            }
        except APIError as exc:
            st.error(str(exc))
    files = st.session_state.export_files
    if files and not busy:
        markdown_col, json_col = st.columns(2)
        stem = f"scriptscout-{st.session_state.session_id}"
        markdown_col.download_button("Tải bản đọc (.md)", files["markdown"], f"{stem}.md", "text/markdown", use_container_width=True)
        json_col.download_button("Tải toàn bộ hồ sơ (.json)", files["json"], f"{stem}.json", "application/json", use_container_width=True)


def render_view_navigation(position: str) -> None:
    if position in {"top", "sidebar"}:
        with st.container(key=f"workspace-nav-{position}"):
            slots = st.columns(2, gap="small") if position == "top" else [st.container(), st.container()]
            for slot, view, label, icon in zip(slots, ("sources", "script"), ("Tài liệu & bằng chứng", "Kịch bản bài giảng"), (":material/menu_book:", ":material/movie_edit:")):
                active = st.session_state.workspace_view == view
                with slot:
                    st.button(label, key=f"view_{view}:{position}", on_click=set_view, args=(view,),
                              icon=":material/check_circle:" if active else icon,
                              type="primary" if active else "secondary", use_container_width=True,
                              help="Bạn đang xem mục này" if active else "Mở mục này; lựa chọn nguồn được giữ nguyên")
        return
    if st.session_state.workspace_view == "sources":
        st.button("Xem kịch bản →", key=f"view_script:{position}", on_click=set_view, args=("script",),
                  use_container_width=True)
    else:
        st.button("← Quay lại tài liệu", key=f"view_sources:{position}", on_click=set_view, args=("sources",),
                  use_container_width=True)


def render_workspace_header(data: dict) -> None:
    req = data.get("req") or {}
    has_session = bool(st.session_state.session_id)
    title = req.get("topic") or "Từ tài liệu hay, đến bài giảng của bạn"
    description = (f"{req.get('target_audience', 'Bài giảng')} · {req.get('duration_minutes', '—')} phút · Nội dung tiếng Việt"
                   if has_session else "Khám phá nguồn đa ngôn ngữ, hiểu bằng tiếng Việt và kể lại theo phong cách riêng của bạn.")
    st.markdown(f'''
<div class="ss-welcome">
  <div><div class="ss-eyebrow">KHÔNG GIAN SOẠN BÀI GIẢNG</div><h1>{escape(title)}</h1><p>{escape(description)}</p></div>
  <svg viewBox="0 0 180 150" fill="none" aria-hidden="true" focusable="false">
    <circle cx="94" cy="73" r="60" fill="#F8E5AC"/>
    <path d="M25 111 86 127 152 111" stroke="#CBA253" stroke-width="3" stroke-linecap="round"/>
    <path d="M27 48c21-5 43 1 61 13v61c-19-12-40-18-61-13V48Z" fill="#FFFDF5" stroke="#245454" stroke-width="3" stroke-linejoin="round"/>
    <path d="M88 61c19-12 41-18 62-13v61c-22-5-43 1-62 13V61Z" fill="#DCEDE1" stroke="#245454" stroke-width="3" stroke-linejoin="round"/>
    <path d="m40 65 31 9m-31 6 31 9m-31 6 23 7m39-27 32-10m-32 25 32-10m-32 24 22-7" stroke="#8EAAA0" stroke-width="3" stroke-linecap="round"/>
    <path d="m142 22 9 11-31 34-12 3 2-12 32-36Z" fill="#DBA53C" stroke="#76571C" stroke-width="2" stroke-linejoin="round"/>
    <path d="m134 31 9 10" stroke="#76571C" stroke-width="2"/>
    <rect x="30" y="17" width="48" height="27" rx="9" fill="#0F766E"/>
    <path d="m48 31 5 5 11-12" stroke="#FFFDF6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="158" cy="87" r="5" fill="#0F766E"/><circle cx="21" cy="30" r="4" fill="#C79A33"/>
  </svg>
</div>''', unsafe_allow_html=True)
    if not has_session:
        st.markdown('<div class="ss-steps"><span><b>01</b> Đặt mục tiêu</span><span><b>02</b> Khám phá & duyệt nguồn</span><span><b>03</b> Hoàn thiện lời giảng</span></div>', unsafe_allow_html=True)


def render_request_form(*, configured: bool) -> None:
    st.caption("Bắt đầu với mục tiêu của người học. Những chi tiết dưới đây sẽ định hướng toàn bộ bài giảng.")
    with st.form("lesson_request"):
        topic = st.text_input("Chủ đề bài giảng", placeholder="Ví dụ: Self-Attention hoạt động như thế nào?", max_chars=500)
        left, right = st.columns(2, gap="large")
        with left:
            st.markdown('<div class="ss-section"><span>01</span>Nội dung & người học</div>', unsafe_allow_html=True)
            audience = st.text_input("Người học", placeholder="Ví dụ: Sinh viên CNTT năm 3, đã biết đại số tuyến tính", max_chars=500)
            objectives = st.text_area(
                "Mục tiêu học tập · mỗi dòng một mục tiêu", height=150,
                placeholder="Giải thích trực giác của Self-Attention\nTheo dõi một ví dụ tính trọng số\nPhân biệt Self-Attention với cơ chế của RNN",
            )
            duration = st.slider("Thời lượng video (phút)", 1, 15, 5)
        with right:
            st.markdown('<div class="ss-section"><span>02</span>Dấu ấn giảng dạy của bạn</div>', unsafe_allow_html=True)
            preset = st.selectbox("Phong cách giảng dạy", list(STYLE_PRESETS))
            style_detail = st.text_area(
                "Mô tả cách giảng của riêng bạn", height=150, max_chars=4000,
                placeholder="Tôi xưng thầy – các em, nói ngắn gọn và gần gũi. Mở đầu bằng một câu hỏi, dùng ví dụ đời sống ở Việt Nam. Với thuật ngữ mới, giữ tên tiếng Anh rồi giải thích tiếng Việt. Cuối mỗi phần có một câu hỏi tự kiểm tra.",
                help="Mô tả cách xưng hô, giọng nói, nhịp giảng, loại ví dụ, mức độ thuật ngữ và cách tương tác. Agent dùng chỉ dẫn này khi xây dựng lời thoại và ghi chú giảng viên.",
            )
            st.caption("Cách xưng hô, ví dụ, nhịp giảng và câu hỏi — giữ đúng dấu ấn của bạn.")
        st.divider()
        st.markdown('<div class="ss-section"><span>03</span>Khám phá kho tri thức</div>', unsafe_allow_html=True)
        language_codes = st.multiselect(
            "Ngôn ngữ tài liệu cần tìm", list(LANGUAGES), default=["vi", "en"],
            format_func=lambda code: LANGUAGES[code],
            help="Đọc tài liệu trong ngôn ngữ gốc; tóm tắt, bản dịch bằng chứng và kịch bản bằng tiếng Việt.",
        )
        max_sources = st.slider("Số nguồn tối đa để đọc và thẩm định", 3, MAX_SOURCES, 6,
                                help="Tìm nhiều nguồn hơn sẽ cần thêm thời gian. Bạn có thể duyệt theo từng trang sau khi tìm.")
        st.caption("Chủ đề được kiểm tra trước khi tìm tài liệu. Nội dung liên quan hành vi phạm pháp chỉ được xử lý khi có mục đích phòng chống rõ ràng.")
        submit = st.form_submit_button("Tìm tài liệu và lập hồ sơ", type="primary", disabled=not configured, use_container_width=True)
    if submit:
        goals = [line.strip() for line in objectives.splitlines() if line.strip()]
        if not topic.strip() or not audience.strip() or not goals or not language_codes:
            st.error("Điền chủ đề, người học, ít nhất một mục tiêu và chọn ít nhất một ngôn ngữ tài liệu.")
        elif preset == "Phong cách riêng của tôi" and not style_detail.strip():
            st.error("Mô tả phong cách giảng dạy của bạn để agent có chỉ dẫn cụ thể.")
        else:
            teaching_style = "\n".join(part for part in [STYLE_PRESETS[preset], style_detail.strip()] if part)
            payload = {
                "topic": topic.strip(), "target_audience": audience.strip(), "objectives": goals,
                "duration_minutes": float(duration), "teaching_style": teaching_style,
                "source_languages": language_codes, "max_sources": max_sources,
            }
            try:
                validate_lesson_content(payload)
            except ContentPolicyError as exc:
                st.error(exc.public_message)
            else:
                act("/api/pipeline/start", payload)


for state_key, default in {
    "session_id": None, "session": None, "action_error": None, "export_files": None, "evidence": {},
    "source_choices": {}, "source_filters": {}, "workspace_view": "sources", "pending_delete": None, "pending_toast": None,
}.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default

health, health_error = read_health()
configuration = health.get("configuration") or {}
configured = bool(configuration.get("llm_configured") and configuration.get("search_configured"))
admission_ready = has_current_admission(health)
session = st.session_state.session or {}
busy = session.get("status") in ACTIVE_STATUSES
if st.session_state.pending_toast:
    st.toast(st.session_state.pending_toast)
    st.session_state.pending_toast = None

with st.sidebar:
    st.markdown('<div class="ss-brand"><span class="ss-logo">Ss</span>ScriptScout</div>', unsafe_allow_html=True)
    st.caption("KHÔNG GIAN SOẠN BÀI GIẢNG")
    if st.button("＋ Bài giảng mới", type="primary", use_container_width=True, disabled=busy):
        st.session_state.session_id = None
        st.session_state.session = None
        st.session_state.action_error = None
        st.session_state.export_files = None
        st.session_state.pending_delete = None
        set_view("sources")
        st.rerun()
    if st.session_state.session_id:
        render_view_navigation("sidebar")
    st.divider()
    st.markdown("**Phiên đã lưu**")
    try:
        history = (api_request("GET", "/api/sessions").get("sessions") or []) if not health_error else []
    except APIError as exc:
        history = []
        st.caption(public_message(str(exc)))
    if history:
        by_id = {item["session_id"]: item for item in history}
        history_labels = {sid: f"{index}. {item.get('topic', 'Bài giảng')} · {STATUS_LABELS.get(item.get('status'), 'Đã lưu')}"
                          for index, (sid, item) in enumerate(by_id.items(), 1)}
        selected_session = st.selectbox(
            "Chọn bài giảng", list(by_id),
            format_func=history_labels.get,
            label_visibility="collapsed", disabled=busy,
        )
        if st.button("Mở phiên đã chọn", disabled=busy, use_container_width=True):
            try:
                st.session_state.pending_delete = None
                accept_session(api_request("GET", f"/api/sessions/{selected_session}"))
            except APIError as exc:
                st.session_state.action_error = str(exc)
            st.rerun()
        if st.button("Xóa phiên", disabled=busy or by_id[selected_session].get("status") in ACTIVE_STATUSES,
                     use_container_width=True, help="Xóa vĩnh viễn bài giảng, nguồn và các tệp đã tải lên trong phiên này."):
            st.session_state.pending_delete = selected_session
        if st.session_state.pending_delete and st.session_state.pending_delete != selected_session:
            st.session_state.pending_delete = None
        if st.session_state.pending_delete == selected_session:
            st.warning(f"Xóa vĩnh viễn “{by_id[selected_session].get('topic', 'bài giảng')}” cùng nguồn và tệp PDF? Thao tác này không thể hoàn tác.")
            if st.button("Xóa vĩnh viễn", type="primary", disabled=busy, use_container_width=True):
                try:
                    api_request("DELETE", f"/api/sessions/{selected_session}")
                    forget_session(selected_session)
                    st.session_state.pending_delete = None
                    st.session_state.pending_toast = "Đã xóa vĩnh viễn phiên và dữ liệu liên quan."
                except APIError as exc:
                    st.session_state.action_error = str(exc)
                st.rerun()
            if st.button("Hủy", disabled=busy, use_container_width=True):
                st.session_state.pending_delete = None
                st.rerun()
    else:
        st.caption("Bài giảng của bạn sẽ được lưu tự động tại đây.")
    st.divider()
    if health.get("trust_criteria"):
        with st.expander("Hiểu về điểm sàng lọc"):
            render_trust_criteria(health["trust_criteria"])
    st.markdown('<div class="ss-sidebar-note"><strong>Một bài giảng tốt bắt đầu từ nguồn rõ ràng.</strong><br>Đọc nguyên văn, đối chiếu bản dịch và chọn điều phù hợp với người học.</div>', unsafe_allow_html=True)

render_workspace_header(session)
if st.session_state.action_error:
    st.error(public_message(st.session_state.action_error))
if health_error:
    st.error("Chưa thể tải không gian làm việc lúc này. Bài giảng đã lưu vẫn được giữ nguyên; hãy thử lại sau.")
elif not admission_ready:
    st.warning(ADMISSION_UPDATING_MESSAGE)
elif not configured:
    st.warning("Chức năng tạo bài giảng đang tạm gián đoạn. Bạn vẫn có thể đọc bài giảng đã lưu; hãy thử lại sau.")
if health_error or not configured or not admission_ready:
    if st.button("Thử lại", icon=":material/refresh:"):
        read_health.clear()
        st.rerun()

if not st.session_state.session_id:
    render_request_form(configured=configured and admission_ready and not health_error)
else:
    req = session.get("req") or {}
    with st.expander("Thông số và phong cách giảng dạy"):
        st.write(f"Người học: {req.get('target_audience', '—')}")
        st.write(f"Thời lượng: {req.get('duration_minutes', '—')} phút")
        st.write("Ngôn ngữ tìm nguồn: " + ", ".join(LANGUAGES.get(code, code) for code in req.get("source_languages", [])))
        st.markdown("**Mục tiêu**")
        for objective in req.get("objectives") or []:
            st.write(f"• {objective}")
        st.markdown("**Phong cách giảng dạy**")
        st.write(req.get("teaching_style") or "Chưa mô tả")
    if busy and hasattr(st, "fragment"):
        st.fragment(run_every="3s")(poll_session)()
    elif busy:
        poll_session()
    else:
        render_progress(session)
    if session.get("error_message"):
        st.error(public_message(session["error_message"]))
    render_view_navigation("top")
    with st.container(key=f"view-content-{st.session_state.workspace_view}"):
        if st.session_state.workspace_view == "sources":
            render_dossier(session, busy=busy)
        else:
            render_script(session, busy=busy)
    render_view_navigation("bottom")
    render_exports(busy=busy)
    if busy and not hasattr(st, "fragment"):
        time.sleep(3)
        st.rerun()
