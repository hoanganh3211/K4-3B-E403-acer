"""Quote provenance checks; these do not establish truth or translation quality."""

from dataclasses import dataclass
import unicodedata

@dataclass
class VerificationResult:
    line_id: str
    source_id: str
    snippet_quote: str
    best_match: str
    score: float
    is_verified: bool
    match_location: str | None = None
    match_start: int | None = None
    match_end: int | None = None
    verification_note: str = ""

class CitationChecker:
    def __init__(self, threshold: int | None = None):
        # Kept for compatibility. A fuzzy score must never authorize a quote.
        self.threshold = threshold

    @staticmethod
    def _normalized_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
        """NFC + collapsed whitespace, retaining original Python string offsets."""
        normalized: list[str] = []
        offsets: list[tuple[int, int]] = []
        i = 0
        while i < len(text):
            start = i
            i += 1
            if text[start].isspace():
                while i < len(text) and text[i].isspace():
                    i += 1
                if normalized:
                    normalized.append(" ")
                    offsets.append((start, i))
                continue
            while i < len(text) and unicodedata.combining(text[i]):
                i += 1
            cluster = unicodedata.normalize("NFC", text[start:i])
            normalized.extend(cluster)
            offsets.extend([(start, i)] * len(cluster))
        if normalized and normalized[-1] == " ":
            normalized.pop()
            offsets.pop()
        return "".join(normalized), offsets

    def _normalize_text(self, text: str) -> str:
        return self._normalized_with_offsets(text)[0]

    @staticmethod
    def _word_character(char: str) -> bool:
        # CJK text has no obligatory word separators.
        return char.isdigit() or char == "_" or "LATIN" in unicodedata.name(char, "")

    def verify_single(self, snippet: str, source_text: str, line_id: str = "", source_id: str = "") -> VerificationResult:
        failure = VerificationResult(
            line_id, source_id, snippet, "", 0.0, False,
            verification_note="Không tìm thấy trích dẫn nguyên văn trong nội dung đã tải.",
        )
        if not snippet or not source_text:
            failure.verification_note = "Thiếu trích dẫn hoặc chưa tải được nội dung nguồn."
            return failure
        normalized_snippet = self._normalize_text(snippet)
        normalized_source, offsets = self._normalized_with_offsets(source_text)
        if not normalized_snippet:
            return failure
        start = normalized_source.find(normalized_snippet)
        while start >= 0:
            end = start + len(normalized_snippet)
            left_ok = not (
                start > 0 and self._word_character(normalized_snippet[0])
                and self._word_character(normalized_source[start - 1])
            )
            right_ok = not (
                end < len(normalized_source) and self._word_character(normalized_snippet[-1])
                and self._word_character(normalized_source[end])
            )
            if left_ok and right_ok:
                original_start, original_end = offsets[start][0], offsets[end - 1][1]
                return VerificationResult(
                    line_id=line_id,
                    source_id=source_id,
                    snippet_quote=snippet,
                    best_match=source_text[original_start:original_end],
                    score=100.0,
                    is_verified=True,
                    match_location=f"Ký tự {original_start}:{original_end}",
                    match_start=original_start,
                    match_end=original_end,
                    verification_note=(
                        "Khớp nguyên văn sau chuẩn hóa Unicode/khoảng trắng; "
                        "chưa xác nhận ý nghĩa bản dịch hoặc độ đúng của luận điểm."
                    ),
                )
            start = normalized_source.find(normalized_snippet, start + 1)
        return failure

    def verify_script(self, script_lines: list[dict], sources_content: dict[str, str]) -> list[VerificationResult]:
        results = []
        for line in script_lines:
            line_id = line.get("line_id", "")
            for ref in line.get("source_refs", []):
                src_id = ref.get("source_id", "")
                snippet = ref.get("snippet_quote", "")
                source_text = sources_content.get(src_id, "")
                res = self.verify_single(snippet, source_text, line_id, src_id)
                results.append(res)
        return results
