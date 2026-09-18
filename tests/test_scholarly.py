"""Exact-identity public-copy retrieval without network or API keys."""

import socket
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx

from services.scraper_service import ScraperService
from services.scholarly_service import ScholarlyService, identify_url, search_exact_doi


PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
DOI = "10.1234/example.2024"
PMCID = "PMC1234567"
PII = "S0167926019301762"
PAPER = "The researchers evaluated learning outcomes in a controlled study. " * 8


def article_xml(doi=DOI, pmcid=PMCID, body=True):
    return (
        '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS//EN" "JATS.dtd">'
        f'<article><front><article-meta><article-id pub-id-type="doi">{doi}</article-id>'
        f'<article-id pub-id-type="pmc">{pmcid}</article-id><title-group>'
        '<article-title>Learning outcomes</article-title></title-group></article-meta></front>'
        + (f'<body><sec><title>Results</title><p>{PAPER}</p></sec></body>' if body else f'<abstract>{PAPER}</abstract>')
        + '</article>'
    )


def europe_metadata(doi=DOI, pmcid=PMCID, oa="Y"):
    return {"resultList": {"result": [{"doi": doi, "pmcid": pmcid, "isOpenAccess": oa}]}}


def pdf_fixture(*page_texts):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        })})
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class ScholarlyCopyTests(unittest.TestCase):
    def fetch(self, handler, url=f"https://doi.org/{DOI}", search=None):
        scraper = ScraperService(httpx.MockTransport(handler), scholarly_search=search or (lambda doi: []))
        with patch("services.scraper_service.socket.getaddrinfo", return_value=PUBLIC_DNS):
            return scraper.fetch_with_fallback(url, "A search title is not identity")

    def test_same_doi_oa_copy_has_actual_evidence_url_and_provenance(self):
        calls = []

        def handler(request):
            calls.append(request)
            host = request.headers["Host"]
            if host == "doi.org":
                return httpx.Response(403)
            if host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"DOI": DOI}})
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=europe_metadata())
            return httpx.Response(200, headers={"content-type": "application/xml"}, text=article_xml())

        source = self.fetch(handler)
        self.assertTrue(source.is_accessible, source.error_message)
        self.assertEqual(source.original_url, f"https://doi.org/{DOI}")
        self.assertEqual(source.url, source.final_url)
        self.assertTrue(source.url.endswith(f"{PMCID}/fullTextXML"))
        self.assertEqual(source.retrieval_method, "public_repository")
        self.assertIn("Europe PMC", source.retrieval_note)
        self.assertIn("researchers evaluated", source.raw_markdown)
        self.assertEqual(source.document_doi, DOI)
        self.assertTrue(all(request.url.host == "93.184.215.14" for request in calls))
        self.assertEqual(calls[1].headers["Accept"], "application/json")

    def test_wrong_doi_or_non_oa_metadata_never_loads_copy(self):
        for metadata in (europe_metadata(doi="10.1234/another"), europe_metadata(oa="N")):
            with self.subTest(metadata=metadata):
                calls = []

                def handler(request):
                    calls.append(request)
                    if request.headers["Host"] == "doi.org":
                        return httpx.Response(403)
                    if request.headers["Host"] == "api.crossref.org":
                        return httpx.Response(200, json={"message": {"DOI": DOI}})
                    return httpx.Response(200, json=metadata)

                source = self.fetch(handler)
                self.assertFalse(source.is_accessible)
                self.assertEqual(len(calls), 3)
                self.assertFalse(source.raw_markdown)
                self.assertIn("chưa tải được", source.retrieval_note)

    def test_metadata_abstract_or_mismatched_xml_is_never_evidence(self):
        for xml in (article_xml(body=False), article_xml(doi="10.9999/other", pmcid="PMC999999")):
            with self.subTest(xml=xml[:90]):

                def handler(request):
                    if request.headers["Host"] == "doi.org":
                        return httpx.Response(403)
                    if request.headers["Host"] == "api.crossref.org":
                        return httpx.Response(200, json={"message": {"DOI": DOI}})
                    if request.url.path.endswith("/search"):
                        return httpx.Response(200, json=europe_metadata())
                    return httpx.Response(200, headers={"content-type": "text/xml"}, text=xml)

                self.assertFalse(self.fetch(handler).is_accessible)

    def test_pii_is_resolved_only_with_exact_crossref_identifier(self):
        for alt_id, success in ((PII, True), ("S0000000000000000", False)):
            with self.subTest(alt_id=alt_id):
                calls = []

                def handler(request):
                    calls.append(request)
                    host = request.headers["Host"]
                    if host == "www.sciencedirect.com":
                        return httpx.Response(403)
                    if host == "api.crossref.org":
                        self.assertEqual(parse_qs(request.url.query.decode())["filter"], [f"alternative-id:{PII}"])
                        return httpx.Response(200, json={"message": {"items": [{
                            "DOI": DOI, "alternative-id": [alt_id], "title": ["Identical search title"],
                        }]}})
                    if request.url.path.endswith("/search"):
                        return httpx.Response(200, json=europe_metadata())
                    return httpx.Response(200, headers={"content-type": "application/xml"}, text=article_xml())

                source = self.fetch(handler, f"https://www.sciencedirect.com/science/article/pii/{PII}")
                self.assertEqual(source.is_accessible, success, source.error_message)
                if not success:
                    self.assertEqual(len(calls), 2)

    def test_metadata_copy_redirect_to_private_host_is_blocked(self):
        calls = []

        def handler(request):
            calls.append(request)
            if request.headers["Host"] == "doi.org":
                return httpx.Response(403)
            if request.headers["Host"] == "api.crossref.org":
                return httpx.Response(200, json={"message": {"DOI": DOI, "link": [{
                    "URL": "https://public.example.org/full.pdf", "content-type": "application/pdf",
                }]}})
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={})
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secrets"})

        source = self.fetch(handler)
        self.assertFalse(source.is_accessible)
        self.assertEqual(len(calls), 4)
        self.assertFalse(any(request.url.host == "127.0.0.1" for request in calls))

    def test_unsafe_original_doi_path_does_not_trigger_metadata(self):
        calls = []
        source = self.fetch(lambda request: calls.append(request), f"http://127.0.0.1/{DOI}")
        self.assertFalse(source.is_accessible)
        self.assertFalse(calls)

    def test_arxiv_abstract_is_replaced_by_same_id_full_text(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, headers={"content-type": "text/html"}, text=f"<article>{PAPER}</article>")

        source = self.fetch(handler, "https://arxiv.org/abs/2401.12345v2")
        self.assertTrue(source.is_accessible)
        self.assertEqual(source.url, "https://arxiv.org/html/2401.12345v2")
        self.assertEqual(len(calls), 2)

    def test_generic_blocked_site_never_uses_title_to_find_another_paper(self):
        calls = []
        source = self.fetch(lambda request: (calls.append(request) or httpx.Response(403)),
                            "https://www.sciencedirect.com/topics/computer-science/computer-vision-algorithms")
        self.assertFalse(source.is_accessible)
        self.assertEqual(len(calls), 1)
        self.assertIn("PDF", source.error_message)

    def test_discovery_is_bounded_and_metadata_is_not_an_article(self):
        def read(url):
            if "crossref" in url:
                return {"message": {"DOI": DOI, "link": [
                    {"URL": f"https://example.org/{index}.pdf", "content-type": "application/pdf"}
                    for index in range(12)
                ]}}
            return europe_metadata()

        discovery = ScholarlyService(read).discover(f"https://doi.org/{DOI}")
        self.assertEqual(len(discovery.candidates), 3)
        self.assertTrue(discovery.candidates[0].url.endswith("fullTextXML"))

    def test_pmc_and_legacy_arxiv_identifiers(self):
        self.assertEqual(identify_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/").pmcid, PMCID)
        self.assertEqual(identify_url("https://arxiv.org/abs/cs.CV/9901001v3").arxiv, "cs.CV/9901001v3")
        self.assertFalse(identify_url("https://arxiv.org.evil.example/abs/2401.12345").recognized)

    def test_exact_doi_search_reads_pdf_and_rejects_doi_only_in_references(self):
        calls, queries = [], []

        def handler(request):
            calls.append(request)
            host = request.headers["Host"]
            if host == "doi.org":
                return httpx.Response(403)
            if host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"DOI": DOI}})
            if host == "www.ebi.ac.uk":
                return httpx.Response(200, json={})
            if request.url.path == "/citing.pdf":
                body = pdf_fixture(f"Another study doi: 10.1234/different {PAPER}", f"References {DOI}")
            else:
                body = pdf_fixture(f"Learning outcomes https://doi.org/{DOI} {PAPER}")
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)

        def search(doi):
            queries.append(doi)
            return [{"url": "https://repo.example.org/citing.pdf", "content": f"Snippet {DOI}"},
                    {"url": "https://repo.example.org/actual.pdf"}]

        source = self.fetch(handler, search=search)
        self.assertTrue(source.is_accessible, source.error_message)
        self.assertEqual(source.url, "https://repo.example.org/actual.pdf")
        self.assertEqual(source.document_doi, DOI)
        self.assertEqual(queries, [DOI])
        self.assertTrue(any("chưa xác nhận" in line for line in source.retrieval_details))

    def test_search_and_metadata_share_three_document_attempt_limit(self):
        copies, queries = [], []

        def handler(request):
            host = request.headers["Host"]
            if host == "doi.org":
                return httpx.Response(403)
            if host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"DOI": DOI, "link": [{
                    "URL": "https://repo.example.org/metadata.pdf", "content-type": "application/pdf",
                }]}})
            if host == "www.ebi.ac.uk":
                return httpx.Response(200, json={})
            copies.append(request.url.path)
            return httpx.Response(403)

        def search(doi):
            queries.append(doi)
            return [{"url": f"https://repo.example.org/search{index}.pdf"} for index in range(10)]

        source = self.fetch(handler, search=search)
        self.assertFalse(source.is_accessible)
        self.assertEqual(copies, ["/metadata.pdf", "/search0.pdf", "/search1.pdf"])
        self.assertEqual(queries, [DOI])

    def test_search_snippet_and_html_are_not_matching_pdf_evidence(self):
        def handler(request):
            if request.headers["Host"] == "doi.org":
                return httpx.Response(403)
            if request.headers["Host"] in {"api.crossref.org", "www.ebi.ac.uk"}:
                return httpx.Response(200, json={})
            return httpx.Response(200, headers={"content-type": "text/html"}, text=f"<article>{DOI} {PAPER}</article>")

        source = self.fetch(handler, search=lambda doi: [{"url": "https://repo.example.org/fake.pdf", "content": f"{DOI} {PAPER}"}])
        self.assertFalse(source.is_accessible)
        self.assertFalse(source.raw_markdown)

    def test_malformed_nested_metadata_is_gracefully_unavailable(self):
        for data in ({"message": None}, {"message": {"items": [{"DOI": DOI, "alternative-id": None}], "link": None}},
                     {"resultList": None}, {"message": {"DOI": DOI, "link": "not a list"}}):
            with self.subTest(data=data):
                source = self.fetch(lambda request: httpx.Response(403) if request.headers["Host"] == "doi.org"
                                    else httpx.Response(200, json=data))
                self.assertFalse(source.is_accessible)
                self.assertEqual(source.http_status, 403)

    def test_search_request_is_basic_single_query_no_answers_or_raw_content(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"results": [{"url": "https://example.org/paper.pdf"}]})

        with patch("config.settings", SimpleNamespace(tavily_api_key="tvly-fixture-not-a-real-key")):
            results = search_exact_doi(DOI, transport=httpx.MockTransport(handler))
        self.assertEqual(len(results), 1)
        self.assertEqual(len(requests), 1)
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["query"], f'"{DOI}" filetype:pdf')
        self.assertEqual(payload["search_depth"], "basic")
        self.assertEqual(payload["max_results"], 3)
        self.assertFalse(payload["include_answer"])
        self.assertFalse(payload["include_raw_content"])


if __name__ == "__main__":
    unittest.main()
