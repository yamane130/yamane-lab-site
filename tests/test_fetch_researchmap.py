"""Offline checks for pagination and preserving the last usable snapshot."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_researchmap as importer


def record(category, number):
    return {
        "@id": f"{importer.API_BASE}/{category}/{number}",
        "@type": category,
        "rm:id": str(number),
        "untouched": {"ja": "元のデータ", "nested": [False, None]},
    }


class Responses:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def __call__(self, url, *, timeout):
        self.calls.append((url, timeout))
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        if isinstance(page, bytes):
            return io.BytesIO(page)
        return io.BytesIO(json.dumps(page).encode("utf-8"))


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "researchmap_data.json"
        self.original = {
            category: [record(category, 1)] for category in importer.CATEGORIES
        }
        self.original_bytes = json.dumps(self.original).encode("utf-8")
        self.output.write_bytes(self.original_bytes)
        self.log = redirect_stdout(io.StringIO())
        self.log.__enter__()
        self.addCleanup(self.log.__exit__, None, None, None)
        self.error_log = redirect_stderr(io.StringIO())
        self.error_log.__enter__()
        self.addCleanup(self.error_log.__exit__, None, None, None)
        sleep_patch = patch.object(importer.time, "sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def assert_preserved(self):
        self.assertEqual(self.output.read_bytes(), self.original_bytes)
        self.assertEqual(list(self.output.parent.glob(".*.tmp")), [])

    def valid_pages(self):
        return [
            {"items": [record(category, 2)], "total_items": 1}
            for category in importer.CATEGORIES
        ]

    def test_pagination_and_category_selection_preserve_records(self):
        category = "published_papers"
        expected = [record(category, i) for i in range(3)]
        opener = Responses([
            {"items": expected[:2], "total_items": 3},
            {"@graph": [
                {"@type": "awards", "items": [], "total_items": 0},
                {"@id": f"{importer.API_BASE}/{category}",
                 "items": expected[2:], "total_items": 3},
            ]},
        ])
        self.assertEqual(importer.fetch_items(category, opener=opener), expected)
        queries = [parse_qs(urlparse(url).query) for url, _ in opener.calls]
        self.assertEqual(queries, [
            {"format": ["json"], "limit": ["1000"], "start": ["1"]},
            {"format": ["json"], "limit": ["1000"], "start": ["3"]},
        ])
        self.assertTrue(all(timeout > 0 for _, timeout in opener.calls))

    def test_duplicate_page_cannot_replace_snapshot(self):
        page = {"items": [record("published_papers", 2)], "total_items": 2}
        with self.assertRaisesRegex(importer.FetchError, "duplicate"):
            importer.update_snapshot(self.output, opener=Responses([page, page]))
        self.assert_preserved()

    def test_last_category_failure_cannot_commit_partial_update(self):
        for failure in ({"error": "service unavailable"}, TimeoutError("timed out")):
            with self.subTest(failure=failure):
                pages = self.valid_pages()
                pages[-1:] = [failure] * (3 if isinstance(failure, Exception) else 1)
                with self.assertRaises((importer.FetchError, OSError)):
                    importer.update_snapshot(self.output, opener=Responses(pages))
                self.assert_preserved()

    def test_transient_failures_retry_same_page_with_bounded_backoff(self):
        category = "published_papers"
        expected = [record(category, 2)]
        page = {"items": expected, "total_items": 1}
        failures = [
            HTTPError("https://api.researchmap.jp", 503, "Unavailable", {}, None),
            HTTPError("https://api.researchmap.jp", 429, "Too Many Requests", {}, None),
            URLError("connection reset"),
            TimeoutError("timed out"),
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                self.sleep.reset_mock()
                opener = Responses([failure, failure, page])
                self.assertEqual(importer.fetch_items(category, opener=opener), expected)
                self.assertEqual(len(opener.calls), 3)
                self.assertEqual(len(set(opener.calls)), 1)
                self.assertEqual(opener.calls[0][1], 20)
                self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [1, 2])

    def test_permanent_http_errors_and_invalid_content_are_not_retried(self):
        cases = [
            HTTPError("https://api.researchmap.jp", 403, "Forbidden", {}, None),
            HTTPError("https://api.researchmap.jp", 404, "Not Found", {}, None),
            b"not json",
            {"error": "invalid category response"},
        ]
        for response in cases:
            with self.subTest(response=response):
                self.sleep.reset_mock()
                opener = Responses([response])
                with self.assertRaises((HTTPError, ValueError, importer.FetchError)):
                    importer.fetch_items("published_papers", opener=opener)
                self.assertEqual(len(opener.calls), 1)
                self.sleep.assert_not_called()

    def test_empty_category_cannot_erase_previous_records(self):
        pages = self.valid_pages()
        pages[-1] = {"items": [], "total_items": 0}
        with self.assertRaisesRegex(importer.FetchError, "empty list"):
            importer.update_snapshot(self.output, opener=Responses(pages))
        self.assert_preserved()

    def test_inconsistent_or_unidentifiable_pages_fail(self):
        category = "published_papers"
        first = {"items": [record(category, 1)], "total_items": 2}
        cases = [
            [first, {"items": [record(category, 2)], "total_items": 3}],
            [first, {"items": [], "total_items": 2}],
            [{"items": [], "total_items": True}],
            [{"items": [record(category, 1)]}],
            [{"items": [{}], "total_items": 1}],
            [{"@graph": [dict(first, **{"@type": category})] * 2}],
        ]
        for pages in cases:
            with self.subTest(pages=pages), self.assertRaises(importer.FetchError):
                importer.fetch_items(category, opener=Responses(pages))

    def test_atomic_replace_failure_preserves_destination(self):
        with patch.object(importer.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                importer.update_snapshot(self.output, opener=Responses(self.valid_pages()))
        self.assert_preserved()

    def test_success_writes_all_records_and_provenance(self):
        snapshot = importer.update_snapshot(self.output, opener=Responses(self.valid_pages()))
        self.assertEqual(json.loads(self.output.read_text()), snapshot)
        for category in importer.CATEGORIES:
            self.assertEqual(snapshot[category], [record(category, 2)])
        meta = snapshot["_meta"]
        self.assertEqual(meta["schema_version"], 1)
        self.assertEqual(meta["source_profile_url"], importer.PROFILE_URL)
        self.assertEqual(meta["source_api_url"], importer.API_BASE)
        self.assertEqual(
            datetime.fromisoformat(meta["fetched_at"].replace("Z", "+00:00")).tzinfo,
            timezone.utc,
        )


if __name__ == "__main__":
    unittest.main()
