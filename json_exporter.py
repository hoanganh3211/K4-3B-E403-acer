"""Portable exports preserving provenance, translations and review warnings."""
import json
from pathlib import Path


class JsonExporter:
    @staticmethod
    def export_ho_so_nguon(dossier_data, output_path="ho-so-nguon.json"):
        Path(output_path).write_text(json.dumps(dossier_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def export_kich_ban(script_data, output_path="kich-ban.json"):
        Path(output_path).write_text(json.dumps(script_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def export_session_markdown(session):
    req = session["req"]
    lines = [f"# {req['topic']}", "", f"**Người học:** {req['target_audience']}",
             f"**Thời lượng mục tiêu:** {req['duration_minutes']:g} phút", f"**Phong cách giảng dạy:** {req.get('teaching_style', '')}",
             "", "**Mục tiêu bài học:**", *[f"- {objective}" for objective in req["objectives"]], "",
             "> Bản nháp do AI biên soạn. Giảng viên cần duyệt trước khi ghi hình.", ""]
    script = session.get("script")
    if script:
        lines.extend(["## Kịch bản", "", f"Thời lượng đọc ước tính: {script.get('estimated_duration_minutes', 0):g} phút.", ""])
        for warning in script.get("warnings", []):
            lines.append(f"> {warning}")
        for scene in script.get("scenes", []):
            lines.extend(["", f"### Cảnh {scene['scene_number']}: {scene['scene_label']}", "",
                          f"Thời lượng: ~{scene['estimated_duration_seconds']} giây", f"Hình ảnh: {scene.get('visual_cue', '')}",
                          f"Lưu ý giảng viên: {scene.get('speaker_note', '')}", ""])
            for line in scene.get("lines", []):
                refs = " ".join(f"[{ref['claim_id']}](#{ref['claim_id']})" for ref in line.get("source_refs", []))
                flag = " **[CẦN KIỂM TRA]**" if line.get("is_unverified") else ""
                lines.append(f"- **{line['line_id']}:** {line['text']} {refs}{flag}")
                if line.get("is_unverified"):
                    lines.append(f"  - {line.get('verification_note', '')}")
    dossier = session.get("dossier") or {}
    lines.extend(["", "## Hồ sơ tài liệu", "", "Điểm tin cậy là tiêu chí sàng lọc, không phải xác suất thông tin đúng.", ""])
    for name, criteria in dossier.get("trust_criteria", {}).items():
        lines.append(f"- {name} ({criteria['weight']:.0%}): {criteria['description']}")
    for warning in dossier.get("warnings", []):
        lines.extend(["", f"> {warning}"])
    for conflict in dossier.get("conflicts", []):
        lines.extend(["", f"**Khác biệt giữa nguồn:** {conflict.get('description_vi', '')}",
                      f"Nguồn: {', '.join(conflict.get('source_ids', []))}", conflict.get("resolution_vi", "")])
    for source in dossier.get("sources", []):
        location = (f"PDF do giảng viên cung cấp: {source.get('uploaded_filename') or source['title']}"
                    if source.get("document_kind") == "uploaded_pdf" else f"[Mở tài liệu đã đọc]({source['url']})")
        lines.extend(["", f"### {source['source_id']} — {source['title']}", "", location,
                      f"Tác giả: {source.get('author') or 'Chưa rõ'} · Ngày: {source.get('published_date') or 'Chưa rõ'} · Ngôn ngữ: {source.get('language', 'unknown')}",
                      f"Trạng thái: {source.get('status')} · Điểm: {source.get('trust_score', 0):g}/100",
                      source.get("trust_reasoning", ""), "", source.get("summary_vi", ""), "",
                      f"Tải lúc: {source.get('fetched_at') or 'Chưa rõ'} · SHA-256: {source.get('content_hash') or 'Không có'}"])
        if source.get("retrieval_note"):
            lines.append(source["retrieval_note"])
        if source.get("retrieval_method") == "public_repository" and source.get("original_url"):
            lines.append(f"[Trang xuất bản ban đầu]({source['original_url']})")
        for warning in source.get("warnings", []):
            lines.append(f"> {warning}")
        for claim in source.get("claims", []):
            lines.extend(["", f"<a id=\"{claim['claim_id']}\"></a>", f"#### {claim['claim_id']}", "",
                          claim["claim_text"], "", "**Trích dẫn nguyên ngữ:**", "",
                          *[f"> {part}" for part in claim["snippet_quote"].splitlines()], "",
                          f"**Diễn giải tiếng Việt:** {claim.get('snippet_translation_vi', '')}", "",
                          f"Kiểm tra: {claim.get('verification_note', '')}"])
    return "\n".join(lines) + "\n"
