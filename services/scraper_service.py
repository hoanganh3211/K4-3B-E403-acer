"""Read bounded public web documents, never search-result snippets.

Every hop is DNS validated and the HTTP connection is pinned to that validated
IP while retaining the original Host/TLS SNI. No proxy, browser script, or remote
reader is used; redirect targets therefore stay subject to the same validation.
"""

from datetime import datetime, timezone
import hashlib
import html
import io
import ipaddress
import json
import re
import socket
import time
from urllib.parse import urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Comment
import httpx

from models.source import RawSource
from models.limits import MAX_UPLOAD_BYTES
from services.scholarly_service import ScholarlyService, identify_url, is_abstract_page, normalize_doi, search_exact_doi


INJECTION_PATTERNS = [
    r"ignore\s+(?:(?:all|the)\s+)?(?:previous|prior|above)\s+instructions",
    r"(?:system|developer)\s*prompt\s*:",
    r"(?:lệnh\s+hệ\s+thống|bỏ\s+qua\s+(?:mọi\s+|các\s+)?(?:chỉ\s+dẫn|hướng\s+dẫn)\s+trước)",
    r"you\s+are\s+now\s+(?:a|an|the)\b",
    r"<\|(?:im_start|system|developer)\|>",
    r"(?:reveal|print|send|exfiltrate)\s+(?:(?:the|your|all)\s+)?(?:api\s*key|secrets?|system\s+prompt)",
]

HIDDEN_STYLE = re.compile(
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|em|rem|%)?\b|opacity\s*:\s*0(?:\s|;|!|$))",
    re.I,
)


class UnsafeURLError(ValueError):
    pass


class ScraperService:
    MAX_RESPONSE_BYTES = MAX_UPLOAD_BYTES
    MAX_TEXT_CHARS = 60000
    MAX_REDIRECTS = 5
    FETCH_DEADLINE_SECONDS = 45

    def __init__(self, transport: httpx.BaseTransport | None = None, *, scholarly_search=None):
        # An injectable transport keeps tests deterministic, without network/API keys.
        self.transport = transport
        self.scholarly_search = scholarly_search if scholarly_search is not None else (
            lambda doi: search_exact_doi(doi, transport=self.transport)
        )
        self.headers = {
            "User-Agent": "ScriptScout/1.0 (educational research; document reader)",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9",
        }

    def detect_injection(self, text: str) -> tuple[bool, str]:
        text = html.unescape(text)
        for pattern in INJECTION_PATTERNS:
            match = re.search(pattern, text, re.I)
            if match:
                return True, f"Nội dung chứa chỉ dẫn đáng ngờ: {match.group()[:120]}"
        return False, ""

    @staticmethod
    def _is_public_ip(value: str) -> bool:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_global and not (
            address.is_multicast or address.is_reserved or address.is_unspecified
            or address.is_loopback or address.is_link_local
        )

    def _resolve_target(self, url: str) -> tuple[httpx.URL, list[str]]:
        if not isinstance(url, str) or len(url) > 8192 or re.search(r"[\x00-\x20\x7f]", url):
            raise UnsafeURLError("URL không hợp lệ hoặc chứa ký tự điều khiển.")
        try:
            parsed = httpx.URL(url)
        except (httpx.InvalidURL, ValueError) as exc:
            raise UnsafeURLError("URL không hợp lệ.") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.host:
            raise UnsafeURLError("Chỉ đọc URL HTTP/HTTPS công khai.")
        if parsed.userinfo:
            raise UnsafeURLError("Không chấp nhận URL chứa tài khoản hoặc mật khẩu.")
        host = parsed.raw_host.decode("ascii").rstrip(".").lower()
        if "%" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home", ".lan")):
            raise UnsafeURLError("Không được truy cập địa chỉ nội bộ.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in {80, 443}:
            raise UnsafeURLError("Chỉ hỗ trợ cổng web công khai 80 và 443.")
        try:
            direct_ip = ipaddress.ip_address(host)
        except ValueError:
            direct_ip = None
        if direct_ip is not None:
            addresses = [str(direct_ip)]
        else:
            try:
                records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise UnsafeURLError("Không phân giải được tên miền của nguồn.") from exc
            addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or any(not self._is_public_ip(address) for address in addresses):
            raise UnsafeURLError("Đã chặn URL trỏ tới IP nội bộ, dành riêng hoặc không công khai.")
        # Prefer IPv4 for machines without outbound IPv6 support.
        addresses.sort(key=lambda address: ":" in address)
        return parsed.copy_with(fragment=None), addresses

    def _download(self, url: str) -> tuple[int, httpx.Headers, bytes, str]:
        current = url
        visited: set[str] = set()
        deadline = time.monotonic() + self.FETCH_DEADLINE_SECONDS
        for _ in range(self.MAX_REDIRECTS + 1):
            if time.monotonic() >= deadline:
                raise httpx.TimeoutException("Hết thời gian tải tài liệu.")
            parsed, addresses = self._resolve_target(current)
            original_url = str(parsed)
            if original_url in visited:
                raise UnsafeURLError("Nguồn chuyển hướng vòng lặp.")
            visited.add(original_url)
            hostname = parsed.raw_host.decode("ascii")
            host_header = f"[{hostname}]" if ":" in hostname else hostname
            if parsed.port is not None:
                host_header += f":{parsed.port}"
            last_error = None
            response_data = None
            for address in addresses[:3]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise httpx.TimeoutException("Hết thời gian tải tài liệu.")
                try:
                    # A new client per request also prevents cookies crossing sites.
                    with httpx.Client(
                        transport=self.transport,
                        timeout=httpx.Timeout(min(20.0, remaining), connect=min(8.0, remaining)),
                        trust_env=False, follow_redirects=False,
                    ) as client:
                        with client.stream(
                            "GET", parsed.copy_with(host=address),
                            headers={**self.headers, "Host": host_header},
                            extensions={"sni_hostname": hostname},
                        ) as response:
                            status, headers = response.status_code, response.headers
                            chunks: list[bytes] = []
                            length = 0
                            if 200 <= status < 300:
                                declared_length = headers.get("content-length", "")
                                if declared_length.isdigit() and int(declared_length) > self.MAX_RESPONSE_BYTES:
                                    raise ValueError("Tài liệu vượt giới hạn tải 8 MB.")
                                for chunk in response.iter_bytes():
                                    if time.monotonic() >= deadline:
                                        raise httpx.TimeoutException("Hết thời gian tải tài liệu.")
                                    length += len(chunk)
                                    if length > self.MAX_RESPONSE_BYTES:
                                        raise ValueError("Tài liệu vượt giới hạn tải 8 MB.")
                                    chunks.append(chunk)
                            response_data = (status, headers, b"".join(chunks))
                    break
                except httpx.TransportError as exc:
                    last_error = exc
            if response_data is None:
                raise last_error or httpx.ConnectError("Không thể kết nối nguồn.")
            status, headers, body = response_data
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location:
                    raise ValueError("Nguồn trả về chuyển hướng không có địa chỉ đích.")
                # Resolved/revalidated on the next iteration before any connection.
                current = urljoin(original_url, location)
                continue
            return status, headers, body, original_url
        raise ValueError("Nguồn chuyển hướng quá nhiều lần.")

    @staticmethod
    def _meta(soup: BeautifulSoup, *names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
            if not tag:
                tag = soup.find("meta", attrs={"property": re.compile(f"^{re.escape(name)}$", re.I)})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return ""

    @staticmethod
    def _language(text: str) -> str:
        # Conservative script cues; Latin-script languages need source metadata or LLM assessment.
        if re.search(r"[ぁ-ゟ゠-ヿ]", text):
            return "ja"
        if re.search(r"[가-힣]", text):
            return "ko"
        if re.search(r"[\u4e00-\u9fff]", text):
            return "zh"
        if re.search(r"[ăĂđĐơƠưƯạ-ỹ]", text):
            return "vi"
        return "unknown"

    def _extract_html(self, body: bytes, source: RawSource) -> str:
        soup = BeautifulSoup(body, "html.parser")
        source.title = self._meta(soup, "og:title", "twitter:title")
        if not source.title and soup.title:
            source.title = soup.title.get_text(" ", strip=True)
        source.author = self._meta(soup, "author", "citation_author", "dc.creator") or "Không rõ"
        source.published_date = self._meta(
            soup, "article:published_time", "citation_publication_date", "date", "dc.date"
        ) or None
        source.document_doi = normalize_doi(self._meta(soup, "citation_doi", "dc.identifier", "prism.doi"))
        declared_language = soup.html.get("lang", "") if soup.html else ""
        if declared_language:
            source.language = str(declared_language).strip()[:35]
        # Inspect before removing hidden text so a discarded attack remains visible in review.
        source.has_prompt_injection, details = self.detect_injection(
            str(soup) + "\n" + soup.get_text(" ", strip=True)
        )
        source.injection_details = details or None
        hidden_count = 0
        for style in soup.find_all("style"):
            for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", style.get_text()):
                if HIDDEN_STYLE.search(declarations):
                    try:
                        for element in soup.select(selectors.strip()[:500]):
                            element.decompose()
                            hidden_count += 1
                    except Exception:
                        # Unsupported CSS selectors never cause execution or extraction failure.
                        continue
        for element in list(soup.find_all(True)):
            if element.attrs is None:
                continue
            style = str(element.get("style", ""))
            if (
                element.has_attr("hidden") or element.has_attr("inert")
                or str(element.get("aria-hidden", "")).lower() == "true"
                or HIDDEN_STYLE.search(style)
            ):
                element.decompose()
                hidden_count += 1
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()
        for element in soup.find_all(["script", "style", "noscript", "template", "svg", "iframe", "form", "nav", "footer", "header", "aside"]):
            element.decompose()
        if hidden_count:
            source.retrieval_details.append(f"Đã loại {hidden_count} phần tử HTML bị ẩn khỏi nội dung dùng làm dẫn chứng.")
        root = soup.find("article") or soup.find("main") or soup.body or soup
        text = root.get_text(" ", strip=True)
        return re.sub(r"[ \t\r\f\v]+", " ", text).strip()

    @staticmethod
    def _extract_pdf(body: bytes, source: RawSource) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("Chưa cài bộ đọc PDF: cần cài pypdf để đọc tài liệu này.") from exc
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            raise ValueError("PDF bị mã hóa; không đọc được nội dung nguồn.")
        metadata = reader.metadata
        if metadata:
            source.title = str(metadata.title or "")
            source.author = str(metadata.author or "Không rõ")
        page_texts = [page.extract_text() or "" for page in reader.pages[:100]]
        text = "\n\n".join(page_texts)
        if page_texts:
            # The first page identifies the paper; DOIs in the references of a
            # different paper must not turn it into an apparent matching copy.
            first_page = page_texts[0].replace("\u00ad", "")
            match = re.search(r"\b10\.\d{4,9}/[^\s<>\"?#]+", first_page, re.I)
            if match:
                source.document_doi = normalize_doi(match.group().rstrip(".,;"))
        if len(reader.pages) > 100:
            source.warnings.append("Chỉ đọc 100 trang đầu của PDF.")
        if len(text.strip()) < 80:
            raise ValueError("PDF không có đủ văn bản; có thể là bản quét cần OCR.")
        return text

    @staticmethod
    def _extract_article_xml(body: bytes, source: RawSource) -> str:
        # Public scholarly APIs may return JATS/Elsevier XML, or metadata only.
        # Requiring a real article body prevents an API abstract becoming evidence.
        if re.search(br"<!\s*ENTITY", body, re.I):
            raise ValueError("Tài liệu XML có khai báo không được hỗ trợ.")
        root = ElementTree.fromstring(body)

        def local(element):
            return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""

        def text_of(element):
            return " ".join(" ".join(element.itertext()).split())

        if local(root) not in {"article", "full-text-retrieval-response"}:
            raise ValueError("Nguồn chỉ cung cấp thông tin bài báo, chưa có toàn văn để trích dẫn.")
        bodies = [element for element in root.iter() if local(element) == "body"]
        if not bodies:
            raise ValueError("Nguồn chỉ cung cấp phần tóm tắt, chưa có toàn văn để trích dẫn.")
        # Identifiers in cited references do not identify the document itself.
        metadata_roots = [element for element in root if local(element) in {"front", "coredata"}]
        for metadata in metadata_roots:
            for element in metadata.iter():
                name, value = local(element), text_of(element)
                if name == "doi" or (name == "article-id" and element.get("pub-id-type") == "doi"):
                    source.document_doi = normalize_doi(value)
                elif name == "article-id" and element.get("pub-id-type") in {"pmc", "pmcid"}:
                    value = value.upper()
                    source.document_pmcid = value if value.startswith("PMC") else f"PMC{value}"
                elif name in {"article-title", "title"} and not source.title:
                    source.title = value
        return "\n\n".join(text_of(element) for element in bodies)

    def _read_scholarly_metadata(self, url: str) -> dict:
        # Fixed public endpoints only; same pinned-IP/redirect validation as documents.
        reader = ScraperService(transport=self.transport)
        reader.FETCH_DEADLINE_SECONDS = 10
        reader.MAX_RESPONSE_BYTES = 1024 * 1024
        reader.MAX_REDIRECTS = 2
        reader.headers["Accept"] = "application/json"
        status, _, body, _ = reader._download(url)
        if status != 200:
            raise ValueError("Không truy cập được metadata công khai.")
        return json.loads(body)

    def fetch_with_fallback(self, url: str, title: str = "") -> RawSource:
        """Read a document or up to three exact-identifier public full-text copies."""
        original = self.fetch_url(url)
        if original.is_accessible:
            return original
        # Never resolve copies for an unsafe original URL, even if it embeds a DOI.
        if original.error_message and original.error_message.startswith("URL bị chặn:"):
            return original
        try:
            discovery = ScholarlyService(self._read_scholarly_metadata).discover(
                url, original.document_doi
            )
        except Exception:
            original.retrieval_details.append("Không xác nhận được dữ liệu tra cứu bản công khai.")
            return original
        original.retrieval_details.extend(discovery.details)
        attempts = 0
        attempted_urls = {url}

        def try_copy(candidate):
            nonlocal attempts
            attempts += 1
            attempted_urls.add(candidate.url)
            copy = self.fetch_url(candidate.url)
            original.retrieval_details.append(
                f"Thử bản công khai tại {candidate.provider}: {candidate.url}; HTTP {copy.http_status}. "
                + (copy.error_message or "")
            )
            if not copy.is_accessible:
                return None
            expected = candidate.identity
            if candidate.require_document_doi:
                same_article = copy.content_type == "application/pdf" and copy.document_doi == expected.doi
            elif expected.arxiv:
                actual = identify_url(copy.final_url)
                same_article = actual.arxiv == expected.arxiv and not is_abstract_page(copy.final_url)
            else:
                # XML must carry the matching identifier itself. For PDF, the
                # authoritative metadata maps the exact DOI to this full-text URL.
                is_pdf = copy.content_type == "application/pdf"
                same_article = bool(is_pdf or (
                    expected.doi and copy.document_doi == expected.doi
                    or expected.pmcid and copy.document_pmcid == expected.pmcid
                ))
                if expected.doi and copy.document_doi and copy.document_doi != expected.doi:
                    same_article = False
                if expected.pmcid and copy.document_pmcid and copy.document_pmcid != expected.pmcid:
                    same_article = False
            if not same_article:
                original.retrieval_details.append("Bỏ qua bản tải về vì chưa xác nhận được cùng bài báo.")
                return None
            copy.source_id = original.source_id
            copy.original_url = url
            copy.url = copy.final_url or candidate.url
            copy.retrieval_method = "public_repository"
            copy.retrieval_note = f"Đã đọc bản toàn văn công khai của cùng bài báo từ {candidate.provider}."
            copy.retrieval_details = original.retrieval_details + copy.retrieval_details
            copy.title = copy.title or original.title or title
            return copy

        for candidate in discovery.candidates:
            if attempts >= ScholarlyService.MAX_CANDIDATES:
                break
            if found := try_copy(candidate):
                return found
        if discovery.doi and attempts < ScholarlyService.MAX_CANDIDATES:
            original.retrieval_details.append(f"Tìm bản PDF công khai theo DOI chính xác: {discovery.doi}.")
            for candidate in ScholarlyService.search_copies(discovery.doi, self.scholarly_search):
                if attempts >= ScholarlyService.MAX_CANDIDATES:
                    break
                if candidate.url not in attempted_urls:
                    if found := try_copy(candidate):
                        return found
        if discovery.recognized:
            original.retrieval_note = "Đã tìm bản toàn văn công khai theo mã bài báo nhưng chưa tải được bản phù hợp."
        return original

    def fetch_url(self, url: str) -> RawSource:
        source = RawSource(url=url, original_url=url, fetched_at=datetime.now(timezone.utc))
        try:
            status, headers, body, final_url = self._download(url)
            source.http_status = status
            source.final_url = final_url
            source.content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if not 200 <= status < 300:
                source.retrieval_details.append(f"Máy chủ nguồn trả về HTTP {status}.")
                if status in {401, 403}:
                    raise ValueError("Trang nguồn chưa cho phép đọc tự động. Bạn có thể thêm liên kết PDF hoặc bản toàn văn công khai khác của bài báo.")
                if status == 404:
                    raise ValueError("Liên kết tài liệu không còn tồn tại. Hãy kiểm tra địa chỉ hoặc thêm nguồn khác.")
                if status == 429:
                    raise ValueError("Trang nguồn đang giới hạn lượt truy cập. Hãy thử lại sau hoặc thêm nguồn khác.")
                raise ValueError("Trang nguồn đang gặp lỗi khi tải tài liệu. Hãy thử lại sau hoặc thêm nguồn khác.")
            if source.content_type in {"text/html", "application/xhtml+xml"} or (
                not source.content_type and body.lstrip().lower().startswith((b"<!doctype html", b"<html"))
            ):
                text = self._extract_html(body, source)
            elif source.content_type == "application/pdf" or body.startswith(b"%PDF-"):
                source.content_type = "application/pdf"
                text = self._extract_pdf(body, source)
            elif source.content_type in {"application/xml", "text/xml", "application/jats+xml"}:
                text = self._extract_article_xml(body, source)
            elif source.content_type.startswith("text/") or not source.content_type:
                text = httpx.Response(status, headers=headers, content=body).text
            else:
                raise ValueError(f"Chưa hỗ trợ định dạng nguồn: {source.content_type or 'không rõ'}.")
            if is_abstract_page(final_url):
                raise ValueError("Liên kết này là trang tóm tắt bài báo; cần bản PDF hoặc toàn văn để trích dẫn.")
            detected, details = self.detect_injection(text)
            if detected:
                source.has_prompt_injection = True
                source.injection_details = source.injection_details or details
            access_gate = re.search(
                r"(?:subscribe (?:to (?:read|continue)|for (?:full|unlimited) access)|"
                r"sign in to (?:read|continue)|enable javascript and cookies|"
                r"checking your browser|verify (?:that )?you are human|"
                r"đăng (?:nhập|ký) để (?:đọc|xem tiếp))", text, re.I,
            )
            if access_gate:
                source.warnings.append("Trang có dấu hiệu tường phí, đăng nhập hoặc chặn truy cập; không coi là toàn văn.")
                raise ValueError("Không xác nhận được toàn văn vì trang yêu cầu quyền truy cập hoặc kiểm tra trình duyệt.")
            if len(text.strip()) < 80:
                raise ValueError("Trang không có đủ nội dung để làm dẫn chứng (dưới 80 ký tự).")
            if len(text) > self.MAX_TEXT_CHARS:
                source.warnings.append(f"Nội dung được giới hạn ở {self.MAX_TEXT_CHARS:,} ký tự; chỉ kiểm chứng phần đã tải.")
            source.raw_markdown = text[:self.MAX_TEXT_CHARS]
            source.content_hash = hashlib.sha256(source.raw_markdown.encode("utf-8")).hexdigest()
            if source.language == "unknown":
                declared = headers.get("content-language", "").split(",", 1)[0].strip()
                source.language = declared[:35] or self._language(source.raw_markdown)
        except UnsafeURLError as exc:
            source.error_message = f"URL bị chặn: {exc}"
        except httpx.TimeoutException:
            source.error_message = "Hết thời gian tải tài liệu; hãy thử lại hoặc chọn nguồn khác."
        except httpx.TransportError:
            source.error_message = "Không kết nối được nguồn hoặc không xác thực được chứng chỉ HTTPS."
        except Exception as exc:
            source.error_message = str(exc)[:500]
        source.error = source.error_message
        return source
