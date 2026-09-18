"""A small, local input gate for an educational product.

This module makes no network calls and can only reject obvious cases; passing
these rules NEVER authorizes research. Mandatory semantic admission follows in
moderation_service before any research, writing or source-reading operation.
Rules cover common Vietnamese and English
phrasing, including several simple obfuscations; they are not a complete
multilingual classifier or a determination of what is legal. Educational
discussion, prevention, health information, and historical analysis are allowed.
Pornographic content and requests to facilitate harmful acts are rejected before
paid research starts. Keep the public error independent of the matched text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from urllib.parse import unquote


CONTENT_POLICY_VERSION = "2026-09-18.3"


_MESSAGES = {
    "adult_content": (
        "Nội dung này có yếu tố khiêu dâm hoặc 18+. "
        "Hãy chọn chủ đề phù hợp với môi trường học tập."
    ),
    "harmful_instruction": (
        "Nội dung này chưa phù hợp để nghiên cứu. Chủ đề liên quan hành vi phạm pháp "
        "chỉ được xử lý khi có mục đích phòng ngừa, cảnh báo hoặc bảo vệ rõ ràng, "
        "không kèm hướng dẫn thực hiện hay cổ vũ hành vi đó."
    ),
    "needs_clarification": (
        "Chưa xác định rõ mục đích an toàn của bài giảng nên chưa bắt đầu tìm tài liệu. "
        "Hãy làm rõ chủ đề và mục tiêu; nếu liên quan hành vi phạm pháp, cần nêu rõ "
        "mục đích phòng chống, cảnh báo hoặc bảo vệ người học."
    ),
    "admission_unavailable": (
        "Chưa thể hoàn tất kiểm tra mục đích bài giảng. Việc tìm tài liệu chưa bắt đầu; "
        "hãy thử lại sau."
    ),
    "input_too_long": "Nội dung đầu vào quá dài. Hãy rút gọn trước khi tiếp tục.",
}


class ContentPolicyError(ValueError):
    """A safe, displayable validation error; never includes the submitted text."""

    def __init__(self, field: str, category: str):
        self.field = field
        self.category = category
        self.public_message = _MESSAGES[category]
        super().__init__(self.public_message)


def _pattern(expressions: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)(?:" + "|".join(expressions) + r")(?!\w)")


def _phrase_obfuscations(phrases: tuple[str, ...]) -> re.Pattern[str]:
    # Each separator is bounded by a literal letter, avoiding nested repetition.
    expressions = [r"[\W_]*".join(re.escape(c) for c in phrase.replace(" ", "")) for phrase in phrases]
    return _pattern(tuple(expressions))


def _normalize(value: str) -> str:
    # Decode twice to cover a quoted URL pasted into another URL/query string.
    for _ in range(2):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    value = unicodedata.normalize("NFKC", value).casefold().replace("đ", "d")
    value = "".join(c for c in unicodedata.normalize("NFKD", value)
                    if not unicodedata.combining(c) and unicodedata.category(c) != "Cf")
    # Preserve numeric ages/quantities. Translate leetspeak only inside words.
    table = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
    value = re.sub(r"[a-z0-9]+", lambda m: m.group().translate(table)
                   if re.search("[a-z]", m.group()) else m.group(), value)
    return re.sub(r"\s+", " ", value).strip()


_EXPLICIT = _pattern((
    r"porn(?:ographic|ography|o)?", r"hentai", r"nsfw", r"xxx", r"sex[ _-]*chat",
    r"cybersex", r"erotic(?:a)?", r"khieu[ _-]*dam", r"dam[ _-]*duc",
    r"phim[ _-]*(?:sex|nguoi lon)", r"truyen[ _-]*(?:sex|nguoi lon)",
    r"anh[ _-]*khoa than", r"nude[ _-]*(?:photos?|pictures?|videos?)",
    r"explicit[ _-]*sexual", r"explicit[ _-]*sex", r"sexual[ _-]*(?:roleplay|fantasy)",
    r"dirty[ _-]*talk", r"dit[ _-]*(?:nhau|me)", r"bu[ _-]*cac", r"du[ _-]*ma",
))
_EXPLICIT_OBFUSCATED = _phrase_obfuscations(("porn", "pornographic", "pornography", "hentai", "khieu dam", "nsfw"))
_ADULT_MARKER = re.compile(r"(?<!\w)18\s*(?:\+(?!\s*\d)|plus\b)")
_AGE_BEFORE = re.compile(r"(?<!\w)(?:sinh vien|hoc vien|nguoi hoc|doi tuong|learners?|students?)\s*(?:tu|tren|from|aged)?\s*$")
_AGE_AFTER = re.compile(r"^\s*(?:tuoi|years? old|learners?|students?)(?!\w)")
_SEXUAL = _pattern((r"sex", r"tinh duc", r"quan he tinh duc", r"thu dam", r"masturbat(?:e|ion|ing)",
                    r"orgasm", r"cuc khoai", r"giao hop", r"sexual intercourse"))
_HEALTH_CONTEXT = _pattern((
    r"giao duc gioi tinh", r"giao duc tinh duc", r"suc khoe (?:tinh duc|sinh san)",
    r"benh lay (?:truyen )?qua duong tinh duc", r"phong (?:ngua|tranh) (?:benh|xam hai)",
    r"tinh duc an toan", r"dong thuan", r"sex(?:ual)? education", r"sexual health",
    r"reproductive health", r"sexually transmitted", r"sexual consent", r"safe sex", r"biology",
    r"day thi", r"kien thuc gioi tinh", r"sinh hoc", r"y hoc", r"sexual development",
))
_SEXUAL_FACILITATION = _pattern((
    r"(?:mo ta|viet|ke|dong vai).{0,45}(?:canh sex|canh nong|khoai cam)",
    r"(?:describe|write|roleplay).{0,45}(?:sex scene|sexual act|arousal)",
    r"(?:cach|huong dan|ky thuat).{0,35}(?:thu dam|dat cuc khoai|quan he tinh duc)",
    r"(?:how to|teach me).{0,35}(?:masturbate|have sex|reach orgasm)",
))

# Action phrases describe facilitation. Restricted subjects additionally require
# a clear protective educational scope, checked after explicit intent below.
_ACTIONS = _pattern((
    r"(?:che tao|lam|lap rap|san xuat) (?:bom|min no|vu khi|sung|chat no)",
    r"(?:make|build|manufacture|assemble) (?:a |an |homemade )?(?:bomb|explosive|weapon|gun)s?",
    r"(?:san xuat|dieu che|tong hop|che bien|buon ban|van chuyen) (?:ma tuy|heroin|cocaine|meth|fentanyl)",
    r"(?:make|manufacture|synthesize|produce|traffic|sell) (?:illegal )?(?:drugs|meth(?:amphetamine)?|cocaine|heroin|fentanyl)",
    r"(?:danh cap|lay trom|trom) (?:mat khau|tai khoan|thong tin dang nhap|du lieu|danh tinh)",
    r"(?:steal|harvest) (?:passwords?|credentials?|identit(?:y|ies)|credit cards?)",
    r"hack (?:tai khoan|facebook|email|gmail|mat khau)",
    r"hack (?:someone'?s |a |an )?(?:account|email|password)",
    r"(?:xam nhap|chiem doat) (?:tai khoan|email|hop thu)",
    r"bypass (?:a |an )?(?:bank |someone'?s )?(?:login|authentication)",
    r"break into (?:someone'?s |another person'?s |a |an )?(?:email|account)",
    r"(?:tao|viet|phat tan|trien khai) (?:ma doc|ransomware|malware|virus may tinh)",
    r"(?:write|build|create|deploy|spread) (?:a )?(?:ransomware|malware|keylogger)",
    r"(?:tao|viet) (?:trang|website|tin nhan|email) (?:.{0,30} )?(?:lua dao|phishing)",
    r"(?:create|write|build) (?:a )?(?:phishing|scam) (?:investment )?(?:email|page|website|message|advertisement|ad)",
    r"(?:gia mao|lam gia) (?:giay to|can cuoc|ho chieu|giay phep|bang cap|tien|hoa don)",
    r"lam (?:giay to|can cuoc|ho chieu|giay phep|bang cap|hoa don) gia", r"tuon hang cam",
    r"(?:forge|counterfeit) (?:a |an )?(?:passport|id|document|money|currency|invoice)s?",
    r"(?:launder money|launder funds|evade taxes)",
    r"(?:trom xe|trom tien|cuop ngan hang|cuop tai san|thuc hien lua dao)",
    r"(?:rob a bank|commit fraud|commit theft|extort money)",
    r"(?:pha|be) khoa (?:cua|xe|nha)", r"break into (?:a |someone'?s )?(?:home|house|car)",
    r"(?:giet|sat hai|dau doc|tan cong) (?:nguoi|ai do|nan nhan)",
    r"(?:kill|poison|assault) (?:someone|a person|people|a victim)",
))
_ACTION_OBFUSCATED = _phrase_obfuscations(("che tao bom", "danh cap mat khau", "hack tai khoan", "san xuat ma tuy"))
_INSTRUCTION = _pattern((
    r"cach", r"huong dan", r"chi (?:toi|minh|em)", r"giup (?:toi|minh|em)",
    r"tung buoc", r"quy trinh", r"cong thuc", r"meo", r"thuc hien", r"toi muon",
    r"how to", r"instructions?", r"step by step", r"teach me", r"show me", r"help me", r"i want to",
    r"viet", r"tao (?:noi dung|phim|truyen|canh|anh)", r"write", r"create", r"roleplay", r"dong vai",
))
_PREVENTION = _pattern((
    r"phong (?:chong|tranh|ngua)", r"ngan chan", r"ngan ngua", r"nhan (?:dien|biet)",
    r"phat hien", r"canh bao", r"tac hai", r"hau qua", r"rui ro", r"dau hieu",
    r"phan tich (?:phap ly|phap luat)", r"trach nhiem (?:hinh su|phap ly)", r"lich su",
    r"phan tich toi danh", r"(?:quy dinh|quy dinh phap luat|phap luat) ve", r"bao cao", r"bao ve",
    r"to giac", r"luat (?:ve|hinh su|xu ly)", r"ho tro nan nhan", r"support(?:ing)? victims?",
    r"chan", r"ho tro nguoi nghien", r"dieu tri nghien", r"cai nghien", r"addiction support",
    r"khong (?:de bi|tham gia)", r"khong nen tham gia", r"tranh xa", r"avoid (?:gambling|betting)",
    r"prevent(?:ion|ing)?", r"detect(?:ion|ing)?", r"recogniz(?:e|ing)", r"warning signs",
    r"risks? of", r"dangers? of", r"consequences? of", r"legal analysis", r"history of",
    r"report(?:ing)?", r"protect(?:ion|ing)?", r"harms? of", r"laws? (?:on|about|against)",
))
_RISK_TOPIC = _pattern((
    r"lua dao", r"gian lan", r"phishing", r"fraud", r"scam", r"ma tuy", r"heroin",
    r"cocaine", r"methamphetamine", r"fentanyl", r"illegal drugs", r"bom", r"chat no",
    r"bomb", r"explosives?", r"ransomware", r"malware", r"trom cap", r"theft",
    r"rua tien", r"tron thue", r"tong tien", r"blackmail", r"money laundering", r"counterfeit", r"tien gia",
    r"xam hai tinh duc", r"sexual assault",
))
_GAMBLING_TOPIC = _pattern((
    r"danh bac", r"co bac", r"ca do", r"ca cuoc", r"tai xiu", r"xoc dia", r"lo de",
    r"nha cai", r"danh bai an tien", r"casino", r"gambl(?:ing|e)", r"betting",
    r"sportsbook", r"bookmak(?:er|ing)", r"roulette", r"baccarat", r"poker", r"slot machines?",
))
_GAMBLING_OBFUSCATED = _phrase_obfuscations(("danh bac", "co bac", "ca do", "tai xiu", "xoc dia", "nha cai", "gambling"))
_RESTRICTED_TOPIC = _pattern((
    r"lua dao", r"trom cap", r"rua tien", r"tron thue", r"tong tien", r"ma tuy", r"heroin",
    r"cocaine", r"tien gia", r"hang cam", r"phishing", r"fraud", r"scams?",
    r"money laundering", r"illegal drugs", r"blackmail", r"counterfeit", r"theft",
))
_RESTRICTED_FAMILIES = tuple(_pattern(terms) for terms in (
    (r"lua dao", r"phishing", r"fraud", r"scams?"),
    (r"trom cap", r"theft", r"tong tien", r"blackmail"),
    (r"rua tien", r"money laundering", r"tron thue"),
    (r"ma tuy", r"heroin", r"cocaine", r"illegal drugs"),
    (r"tien gia", r"counterfeit"),
    (r"hang cam",),
))
_PROFIT_PROMOTION_INTENT = _pattern((
    r"kiem (?:tien|loi)", r"lam giau", r"(?:tang|kiem) thu nhap", r"loi nhuan",
    r"quang (?:ba|cao)", r"tuyen (?:nguoi|thanh vien|dai ly)",
    r"(?:make|earn) (?:extra )?(?:money|income)", r"profit from", r"(?:promote|advertise|recruit)",
))
_GAMBLING_INTENT = _pattern((
    r"kiem (?:tien|loi)", r"lam giau", r"thang (?:cuoc|lon|chac)", r"loi nhuan",
    r"(?:huong dan|cach|meo|bi quyet|chien thuat) (?:choi|danh bac|ca cuoc|dat cuoc|thang|chon cua)",
    r"(?:toi uu|tang) (?:tien cuoc|co hoi thang)", r"nap tien", r"chot so", r"soi keo",
    r"quang (?:ba|cao)", r"tuyen (?:nguoi|thanh vien|dai ly)", r"thu hut nguoi choi", r"loi keo nguoi",
    r"(?:make|earn) money", r"(?:win|place) bets?", r"betting strateg(?:y|ies)",
    r"(?:how to|tips to|strategies to) (?:gamble|bet|win)", r"(?:promote|advertise|recruit)",
    r"(?:increase|maximize|make) (?:profits?|winnings)", r"deposit money",
    r"chon keo", r"(?:tham gia|bat dau|tap) (?:choi|dat cuoc|ca cuoc)",
    r"recommend (?:betting|gambling|casino) (?:sites?|platforms?)",
))
_MATH_SCOPE = _pattern((
    r"xac suat", r"toan hoc", r"ly thuyet tro choi", r"ky vong toan hoc",
    r"probability", r"mathematics", r"game theory", r"expected value",
))
_CROSS_FIELD_INTENT = _pattern((
    r"(?:huong dan|giai thich|mo ta|chi tiet) (?:.{0,25} )?(?:tung buoc thuc hien|cach thuc hien|quy trinh san xuat|quy trinh che tao)",
    r"(?:cach|quy trinh|cac buoc) (?:san xuat|che tao|thuc hien) (?:no|chung|dieu do)",
    r"(?:khong|ma khong) bi phat hien", r"qua mat (?:canh sat|co quan chuc nang)",
    r"(?:how to|steps to|instructions to) (?:make|build|produce|carry out|do) (?:it|them|this)",
    r"(?:avoid|evade) (?:detection|law enforcement|the police)",
))
_CLAUSE_BREAK = re.compile(
    r"[\n;.!?]|(?<!\w)(?:nhung|tuy nhien|but|however)(?!\w)|"
    r"(?<!\w)(?:va|and)\s+(?=(?:tao|viet|che tao|san xuat|danh cap|xam nhap|chiem doat|"
    r"lam gia|tuon|create|write|build|bypass|steal|make|kiem tien|kiem loi|quang ba|quang cao|"
    r"tuyen nguoi|tuyen thanh vien|chien thuat|nap tien)(?!\w))|"
    r"[,:]\s*(?=(?:chi |huong dan|kiem tien|kiem loi|nap tien|quang ba|tuyen nguoi)(?!\w))"
)
_NEGATED_SCOPE = re.compile(
    r"(?<!\w)(?:khong(?: can|nen|muon)?(?: de cap|ban|noi|nhac|quan tam|tap trung)?|"
    r"bo qua|dung(?: de cap|noi|nhac)|do not|don't|never|without|ignore|omit|exclude|skip|no)"
    r"(?:\W+\w+){0,8}\W*$"
)
_NEGATED_ACTION = re.compile(r"(?<!\w)(?:khong(?: nen| duoc)?|do not|don't|never|avoid)\s*$")


def _positive_scope_matches(text: str, pattern: re.Pattern[str] = _PREVENTION) -> list[re.Match[str]]:
    matches = []
    boundaries = list(_CLAUSE_BREAK.finditer(text))
    for match in pattern.finditer(text):
        start = max([item.end() for item in boundaries if item.end() <= match.start()] or [0])
        before = text[max(start, match.start() - 100):match.start()]
        if not _NEGATED_SCOPE.search(before):
            matches.append(match)
    return matches


def _facilitates(text: str, match: re.Match[str], *, direct: bool) -> bool:
    """Resolve the nearby purpose, never let a distant 'education' label bypass."""
    prefix = text[:match.start()]
    # Inspect the complete text so a conjunction's lookahead can see an action
    # that starts exactly at this match, then retain only preceding boundaries.
    breaks = [item for item in _CLAUSE_BREAK.finditer(text) if item.end() <= match.start()]
    prefix = prefix[breaks[-1].end():] if breaks else prefix
    prefix = prefix[-160:]
    if _NEGATED_ACTION.search(prefix):
        return False
    prevention = _positive_scope_matches(prefix)
    instruction = list(_INSTRUCTION.finditer(prefix))
    # For example, 'cách phòng chống …' has prevention as its final purpose,
    # while 'phòng chống … nhưng hướng dẫn …' has an instructional purpose.
    if prevention and (not instruction or prevention[-1].start() > instruction[-1].start()):
        return False
    if direct:
        return True
    return bool(instruction)


def _check_one(text: str, field: str, health_context: bool) -> None:
    adult_marker = any(
        not (_AGE_BEFORE.search(text[max(0, match.start() - 45):match.start()])
             or _AGE_AFTER.search(text[match.end():match.end() + 25]))
        for match in _ADULT_MARKER.finditer(text)
    )
    explicit_request = any(_facilitates(text, match, direct=True)
                           for pattern in (_EXPLICIT, _EXPLICIT_OBFUSCATED)
                           for match in pattern.finditer(text))
    if explicit_request or adult_marker or _SEXUAL_FACILITATION.search(text):
        raise ContentPolicyError(field, "adult_content")
    if not health_context and any(_facilitates(text, match, direct=True) for match in _SEXUAL.finditer(text)):
        # A generic sex topic needs an explicit educational/health scope.
        raise ContentPolicyError(field, "adult_content")
    for pattern in (_ACTIONS, _ACTION_OBFUSCATED):
        if any(_facilitates(text, match, direct=True) for match in pattern.finditer(text)):
            raise ContentPolicyError(field, "harmful_instruction")
    for match in _RISK_TOPIC.finditer(text):
        if _facilitates(text, match, direct=False):
            raise ContentPolicyError(field, "harmful_instruction")


def _has_protective_scope(text: str, match: re.Match[str], *, allow_math: bool = False) -> bool:
    """Look on both sides of a subject, inside its clause and a small window."""
    boundaries = list(_CLAUSE_BREAK.finditer(text))
    start = max([item.end() for item in boundaries if item.end() <= match.start()] or [0])
    end = min([item.start() for item in boundaries if item.start() >= match.end()] or [len(text)])
    nearby = text[max(start, match.start() - 160):min(end, match.end() + 160)]
    return bool(_positive_scope_matches(nearby) or (allow_math and _positive_scope_matches(nearby, _MATH_SCOPE)))


def _check_restricted_subjects(parts: list[tuple[str, str]]) -> None:
    families = (((_GAMBLING_TOPIC, _GAMBLING_OBFUSCATED), True),) + tuple(
        ((pattern,), False) for pattern in _RESTRICTED_FAMILIES
    )
    for patterns, allow_math in families:
        matches = [(field, text, match) for field, text in parts
                   for pattern in patterns for match in pattern.finditer(text)]
        if not matches:
            continue
        # A specific protective learning objective can scope a short topic. A
        # style label alone cannot grant an exception to an unrelated request.
        objective_scope = any(field == "objectives" and _positive_scope_matches(text)
                              and not any(pattern.search(text) for pattern in (_RISK_TOPIC, _GAMBLING_TOPIC, _RESTRICTED_TOPIC))
                              for field, text in parts)
        for field, text, match in matches:
            local_scope = _has_protective_scope(text, match, allow_math=allow_math)
            other_field_scope = objective_scope or any(
                scope_field != field and scope_field in {"topic", "objectives"}
                and _has_protective_scope(scope_text, scope_match, allow_math=allow_math)
                for scope_field, scope_text, scope_match in matches
            )
            if not local_scope and not other_field_scope:
                raise ContentPolicyError(field, "harmful_instruction")


def validate_lesson_content(payload: Mapping) -> None:
    """Validate the four user-authored lesson fields before any paid operation.

    ``objectives`` is reported as one field (not an array index). Unknown fields
    are ignored; request-schema validation remains the caller's responsibility.
    """
    parts: list[tuple[str, str]] = []
    total = 0
    for field in ("topic", "target_audience", "objectives", "teaching_style"):
        value = payload.get(field, "")
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            total += len(item)
            if total > 24_000:
                raise ContentPolicyError(field, "input_too_long")
            parts.append((field, _normalize(item)))
    combined = " ; ".join(text for _, text in parts)
    health_context = bool(_HEALTH_CONTEXT.search(combined))
    for field, text in parts:
        _check_one(text, field, health_context)
    # A dangerous topic and an instruction can be split across form fields.
    gambling = bool(_GAMBLING_TOPIC.search(combined) or _GAMBLING_OBFUSCATED.search(combined))
    if gambling or _RESTRICTED_TOPIC.search(combined):
        for field, text in parts:
            for match in _PROFIT_PROMOTION_INTENT.finditer(text):
                if _facilitates(text, match, direct=True):
                    raise ContentPolicyError(field, "harmful_instruction")
    if gambling:
        for field, text in parts:
            for match in _GAMBLING_INTENT.finditer(text):
                if _facilitates(text, match, direct=True):
                    raise ContentPolicyError(field, "harmful_instruction")
    if _RISK_TOPIC.search(combined) or gambling:
        for field, text in parts:
            for match in _CROSS_FIELD_INTENT.finditer(text):
                if _facilitates(text, match, direct=True):
                    raise ContentPolicyError(field, "harmful_instruction")
    _check_restricted_subjects(parts)


def validate_source_input(text: str, field: str = "url") -> None:
    """Check a user-supplied URL or filename; never fetch or read its contents."""
    if len(text) > 8_000:
        raise ContentPolicyError(field, "input_too_long")
    normalized = _normalize(text)
    # URL slugs and file names usually use '-' or '_' in place of word spaces.
    normalized = re.sub(r"[_/-]+", " ", normalized)
    _check_one(normalized, field, bool(_HEALTH_CONTEXT.search(normalized)))
    if _GAMBLING_TOPIC.search(normalized) or _GAMBLING_OBFUSCATED.search(normalized) or _RESTRICTED_TOPIC.search(normalized):
        if any(_facilitates(normalized, match, direct=True) for match in _PROFIT_PROMOTION_INTENT.finditer(normalized)):
            raise ContentPolicyError(field, "harmful_instruction")
    if _GAMBLING_TOPIC.search(normalized) or _GAMBLING_OBFUSCATED.search(normalized):
        if any(_facilitates(normalized, match, direct=True) for match in _GAMBLING_INTENT.finditer(normalized)):
            raise ContentPolicyError(field, "harmful_instruction")
    _check_restricted_subjects([(field, normalized)])
