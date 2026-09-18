"""Discover public full text by exact scholarly identifiers, never by title.

Crossref and Europe PMC responses are discovery metadata, never evidence. The
caller downloads each returned document through the same SSRF-safe reader used
for ordinary URLs. No credentials, browser challenges or paywalls are bypassed.
"""

from dataclasses import dataclass, field
import re
from typing import Callable
from urllib.parse import quote, unquote, urlencode, urlsplit


def normalize_doi(value: str) -> str:
    value = unquote(str(value or "")).strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/|^doi:\s*", "", value, flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/[^\s<>\"?#]+", value, re.I) else ""


def _list(value) -> list:
    return value if isinstance(value, list) else []


@dataclass(frozen=True)
class ScholarlyIdentity:
    doi: str = ""
    pmcid: str = ""
    arxiv: str = ""
    pii: str = ""

    @property
    def recognized(self) -> bool:
        return bool(self.doi or self.pmcid or self.arxiv or self.pii)


@dataclass(frozen=True)
class PublicCopy:
    url: str
    identity: ScholarlyIdentity
    provider: str
    require_document_doi: bool = False


@dataclass
class Discovery:
    candidates: list[PublicCopy] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    recognized: bool = False
    doi: str = ""


def identify_url(url: str, document_doi: str = "") -> ScholarlyIdentity:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ScholarlyIdentity()
    host, path = (parsed.hostname or "").lower().rstrip("."), unquote(parsed.path)
    doi = normalize_doi(document_doi)
    if host in {"doi.org", "dx.doi.org"}:
        doi = normalize_doi(path.lstrip("/")) or doi
    match = re.search(r"/(?:doi/(?:abs/|full/|pdf/|epdf/)?)?(10\.\d{4,9}/.+)$", path, re.I)
    if match:
        doi = normalize_doi(match.group(1)) or doi
    if host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        match = re.fullmatch(r"/(?:abs|html|pdf)/((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)(?:\.pdf)?/?", path, re.I)
        if match:
            return ScholarlyIdentity(arxiv=match.group(1))
    if host in {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "europepmc.org", "www.europepmc.org"}:
        match = re.search(r"/(PMC\d+)(?:/|$)", path, re.I)
        if match:
            return ScholarlyIdentity(doi=doi, pmcid=match.group(1).upper())
    if host in {"sciencedirect.com", "www.sciencedirect.com", "linkinghub.elsevier.com"}:
        match = re.search(r"/pii/(S\d{16}|B\d{16})(?:/|$)", path, re.I)
        if match:
            return ScholarlyIdentity(doi=doi, pii=match.group(1).upper())
    return ScholarlyIdentity(doi=doi)


def is_abstract_page(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return bool(
        host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"} and parsed.path.startswith("/abs/")
        or host == "pubmed.ncbi.nlm.nih.gov" and re.fullmatch(r"/\d+/?", parsed.path)
        or "/doi/abs/" in parsed.path
        or host in {"www.sciencedirect.com", "sciencedirect.com"} and "/article/abs/pii/" in parsed.path
    )


def search_exact_doi(doi: str, *, transport=None) -> list[dict]:
    """One basic search using the existing app key; results are URLs, never evidence."""
    # Lazy imports keep deterministic readers usable without configuring an LLM.
    import httpx
    from config import settings
    from services.llm_service import api_key_configured

    doi = normalize_doi(doi)
    api_key = settings.tavily_api_key.strip()
    if not doi or not api_key_configured(api_key):
        return []
    try:
        with httpx.Client(transport=transport, timeout=10, trust_env=False) as client:
            response = client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": f'"{doi}" filetype:pdf', "topic": "general", "search_depth": "basic",
                      "max_results": 3, "include_answer": False, "include_raw_content": False},
            )
            response.raise_for_status()
            data = response.json()
        return data.get("results", []) if isinstance(data, dict) and isinstance(data.get("results"), list) else []
    except Exception:
        # Never leak provider exception strings that can include credentials.
        return []


class ScholarlyService:
    MAX_CANDIDATES = 3

    def __init__(self, read_metadata: Callable[[str], dict]):
        self.read_metadata = read_metadata

    @staticmethod
    def search_copies(doi: str, search: Callable[[str], list[dict]]) -> list[PublicCopy]:
        doi = normalize_doi(doi)
        if not doi:
            return []
        try:
            results = search(doi)
        except Exception:
            return []
        copies = []
        seen = set()
        for result in results[:3] if isinstance(results, list) else []:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")) and url not in seen:
                copies.append(PublicCopy(url, ScholarlyIdentity(doi=doi), "bản PDF công khai", True))
                seen.add(url)
        return copies

    def discover(self, url: str, document_doi: str = "") -> Discovery:
        identity = identify_url(url, document_doi)
        result = Discovery(recognized=identity.recognized)
        if not result.recognized:
            return result
        if identity.arxiv:
            for kind in ("html", "pdf"):
                result.candidates.append(PublicCopy(
                    f"https://arxiv.org/{kind}/{identity.arxiv}", identity, "arXiv"
                ))
            return result

        def read(endpoint: str) -> dict:
            try:
                value = self.read_metadata(endpoint)
                return value if isinstance(value, dict) else {}
            except Exception:
                result.details.append("Không tra cứu được kho metadata công khai; sẽ tiếp tục với các bản đã xác định.")
                return {}

        crossref = {}
        doi = identity.doi
        if identity.pii and not doi:
            data = read("https://api.crossref.org/works?" + urlencode({
                "filter": f"alternative-id:{identity.pii}", "rows": 3,
                "select": "DOI,alternative-id,link,title",
            }))
            # Never trust the API search ranking or a similar title as identity.
            message = data.get("message")
            items = message.get("items") if isinstance(message, dict) else []
            matches = [item for item in (items if isinstance(items, list) else [])
                       if isinstance(item, dict) and identity.pii in {
                           str(value).upper() for value in _list(item.get("alternative-id"))
                       } and normalize_doi(item.get("DOI", ""))]
            dois = {normalize_doi(item["DOI"]) for item in matches}
            if len(dois) == 1:
                crossref = matches[0]
                doi = normalize_doi(crossref["DOI"])
                result.details.append(f"Crossref xác nhận {identity.pii} tương ứng DOI {doi}.")
            else:
                result.details.append("Chưa xác định được DOI duy nhất khớp chính xác mã bài báo của nhà xuất bản.")
        elif doi:
            data = read("https://api.crossref.org/works/" + quote(doi, safe=""))
            item = data.get("message", {})
            if isinstance(item, dict) and normalize_doi(item.get("DOI", "")) == doi:
                crossref = item

        verified_identity = ScholarlyIdentity(doi=doi, pmcid=identity.pmcid, pii=identity.pii)
        result.doi = doi
        if doi or identity.pmcid:
            query = f'EXT_ID:{identity.pmcid} AND SRC:PMC' if identity.pmcid else f'DOI:"{doi}"'
            data = read("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urlencode({
                "query": query, "format": "json", "resultType": "core", "pageSize": 3,
            }))
            result_list = data.get("resultList")
            records = result_list.get("result") if isinstance(result_list, dict) else []
            for item in records if isinstance(records, list) else []:
                if not isinstance(item, dict):
                    continue
                pmcid = str(item.get("pmcid", "")).upper()
                if not re.fullmatch(r"PMC\d+", pmcid) or item.get("isOpenAccess") != "Y":
                    continue
                if doi and normalize_doi(item.get("doi", "")) != doi:
                    continue
                if identity.pmcid and pmcid != identity.pmcid:
                    continue
                result.candidates.append(PublicCopy(
                    f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                    ScholarlyIdentity(doi=doi, pmcid=pmcid), "Europe PMC",
                ))

        for link in _list(crossref.get("link")):
            if not isinstance(link, dict):
                continue
            content_type = str(link.get("content-type", "")).lower()
            candidate_url = str(link.get("URL", ""))
            # Use explicitly published full-text links only, not abstract/landing URLs.
            if content_type in {"application/pdf", "application/xml", "text/xml"} and candidate_url.startswith("https://"):
                result.candidates.append(PublicCopy(candidate_url, verified_identity, "nhà xuất bản (Crossref)"))

        seen = {url}
        unique = []
        for candidate in result.candidates:
            if candidate.url not in seen:
                unique.append(candidate)
                seen.add(candidate.url)
        result.candidates = unique[:self.MAX_CANDIDATES]
        return result
