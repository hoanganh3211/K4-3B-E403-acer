"""Evidence integrity tests; these use only local fixtures and mocked HTTP/DNS."""

import hashlib
from pathlib import Path
import socket
import unittest
import unicodedata
from unittest.mock import patch

import httpx

from models.source import RawSource
from services.citation_checker import CitationChecker
from services.scraper_service import ScraperService


FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]


class CitationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.checker = CitationChecker(threshold=1)

    def test_changed_number_never_passes_even_with_low_threshold(self):
        self.assertFalse(self.checker.verify_single(
            "The study involved 210 students.", "The study involved 120 students."
        ).is_verified)

    def test_removed_negation_never_passes(self):
        self.assertFalse(self.checker.verify_single(
            "The treatment did improve outcomes.", "The treatment did not improve outcomes."
        ).is_verified)

    def test_partial_number_and_word_never_pass(self):
        self.assertFalse(self.checker.verify_single("20", "120 students participated").is_verified)
        self.assertFalse(self.checker.verify_single("effective", "ineffective").is_verified)

    def test_unicode_and_whitespace_match_preserves_actual_offsets(self):
        text = "Header\n" + unicodedata.normalize("NFD", "Học tập") + "\n  là hữu ích.\nEnd"
        result = self.checker.verify_single("Học tập là hữu ích.", text, "line_1", "src_1")
        self.assertTrue(result.is_verified)
        self.assertEqual(result.best_match, text[result.match_start:result.match_end])
        self.assertEqual(result.match_start, len("Header\n"))
        self.assertIn("chưa xác nhận", result.verification_note)

    def test_original_language_not_translation_is_quote(self):
        source = "研究では学習方法を比較しました。"
        self.assertTrue(self.checker.verify_single("学習方法を比較しました", source).is_verified)
        self.assertFalse(self.checker.verify_single("Nghiên cứu so sánh các phương pháp học.", source).is_verified)

    def test_missing_source_and_whitespace_quote_fail(self):
        results = self.checker.verify_script([
            {"line_id": "line_1", "source_refs": [{"source_id": "absent", "snippet_quote": "quote"}]}
        ], {})
        self.assertFalse(results[0].is_verified)
        self.assertFalse(self.checker.verify_single("  \n ", "any text").is_verified)


class FetchIntegrityTests(unittest.TestCase):
    def fetch(self, handler, url="https://example.org/article"):
        service = ScraperService(transport=httpx.MockTransport(handler))
        with patch("services.scraper_service.socket.getaddrinfo", return_value=PUBLIC_DNS):
            return service.fetch_url(url)

    def test_multilingual_html_metadata_and_content_provenance(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                                  content=(FIXTURES / "multilingual_article.html").read_bytes())

        source = self.fetch(handler)
        self.assertTrue(source.is_accessible, source.error_message)
        self.assertEqual(source.language, "de")
        self.assertEqual(source.author, "Dr. Beispiel")
        self.assertEqual(source.published_date, "2024-02-15")
        self.assertIn("Học tập", source.raw_markdown)
        self.assertNotIn("Copyright", source.raw_markdown)
        self.assertEqual(source.content_hash, hashlib.sha256(source.raw_markdown.encode()).hexdigest())
        self.assertEqual(calls[0].url.host, "93.184.215.14")
        self.assertEqual(calls[0].headers["Host"], "example.org")
        self.assertEqual(calls[0].extensions["sni_hostname"], "example.org")
        self.assertEqual(source.final_url, "https://example.org/article")
        self.assertIsNotNone(source.fetched_at.tzinfo)

    def test_hidden_injection_is_flagged_before_hidden_nodes_are_removed(self):
        source = self.fetch(lambda request: httpx.Response(
            200, headers={"content-type": "text/html"},
            content=(FIXTURES / "hidden_injection.html").read_bytes(),
        ))
        self.assertTrue(source.has_prompt_injection)
        self.assertNotIn("Ignore previous", source.raw_markdown)
        self.assertNotIn("987654", source.raw_markdown)
        self.assertNotIn("throw new Error", source.raw_markdown)
        self.assertTrue(source.retrieval_details)
        self.assertFalse(source.warnings)

    def test_non_success_is_not_evidence(self):
        for status in (403, 404, 429, 503):
            with self.subTest(status=status):
                source = self.fetch(lambda request: httpx.Response(status, text="x" * 200))
                self.assertFalse(source.is_accessible)
                self.assertEqual(source.raw_markdown, "")
                self.assertEqual(source.http_status, status)
                self.assertTrue(any(str(status) in detail for detail in source.retrieval_details))
                self.assertNotIn("HTTP", source.error_message)

    def test_paywall_is_not_full_text(self):
        source = self.fetch(lambda request: httpx.Response(
            200, headers={"content-type": "text/html"},
            text="<article>Subscribe to read this article. " + "Preview only. " * 50 + "</article>",
        ))
        self.assertFalse(source.is_accessible)
        self.assertFalse(source.raw_markdown)
        self.assertIn("quyền truy cập", source.error_message)

    def test_private_urls_and_credentials_never_open_a_connection(self):
        forbidden = [
            "file:///etc/passwd", "http://127.0.0.1/", "http://10.0.0.5/", "http://[::1]/",
            "http://[::ffff:127.0.0.1]/", "http://169.254.169.254/latest/meta-data/",
            "http://localhost/", "https://service.internal/", "https://user:secret@example.org/",
            "https://example.org:8080/", "https://example.org/\nInjected:yes",
        ]
        for url in forbidden:
            with self.subTest(url=url):
                calls = []
                source = self.fetch(lambda request: calls.append(request), url)
                self.assertFalse(calls)
                self.assertFalse(source.is_accessible)
                self.assertIn("chặn", source.error_message)

    def test_private_dns_result_never_opens_a_connection(self):
        calls = []
        service = ScraperService(transport=httpx.MockTransport(lambda request: calls.append(request)))
        private_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443))]
        with patch("services.scraper_service.socket.getaddrinfo", return_value=private_dns):
            source = service.fetch_url("https://public-looking.example.org/")
        self.assertFalse(calls)
        self.assertFalse(source.is_accessible)

    def test_redirect_to_private_host_is_blocked_before_second_request(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secrets"})

        source = self.fetch(handler)
        self.assertEqual(len(calls), 1)
        self.assertFalse(source.is_accessible)
        self.assertIn("chặn", source.error_message)

    def test_relative_public_redirect_and_plaintext(self):
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(301, headers={"location": "/document.txt"})
            return httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8", "content-language": "fr"},
                                  text="Les étudiants ont étudié le document. " * 5)

        source = self.fetch(handler)
        self.assertEqual(len(calls), 2)
        self.assertTrue(source.is_accessible, source.error_message)
        self.assertEqual(source.language, "fr")
        self.assertEqual(source.final_url, "https://example.org/document.txt")

    def test_response_size_is_bounded(self):
        source = self.fetch(lambda request: httpx.Response(
            200, headers={"content-type": "text/plain", "content-length": "999999999"}, text="short"
        ))
        self.assertFalse(source.is_accessible)
        self.assertIn("8 MB", source.error_message)

    def test_search_snippet_without_fetch_cannot_be_accessible(self):
        source = RawSource(url="https://example.org", raw_markdown="Search snippet. " * 50)
        self.assertFalse(source.is_accessible)

    def test_missing_pdf_parser_has_actionable_error(self):
        with patch.dict("sys.modules", {"pypdf": None}):
            source = self.fetch(lambda request: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7\n"
            ))
        self.assertFalse(source.is_accessible)
        self.assertIn("pypdf", source.error_message)

    def test_timeout_is_an_explicit_inaccessible_source(self):
        def handler(request):
            raise httpx.ReadTimeout("simulated timeout")

        source = self.fetch(handler)
        self.assertFalse(source.is_accessible)
        self.assertIn("Hết thời gian", source.error_message)

    def test_mixed_private_public_dns_is_rejected(self):
        calls = []
        service = ScraperService(transport=httpx.MockTransport(lambda request: calls.append(request)))
        records = PUBLIC_DNS + [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]
        with patch("services.scraper_service.socket.getaddrinfo", return_value=records):
            source = service.fetch_url("https://public-looking.example.org/")
        self.assertFalse(calls)
        self.assertIn("chặn", source.error_message)


if __name__ == "__main__":
    unittest.main()
