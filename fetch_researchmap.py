"""Fetch a complete public researchmap snapshot without replacing it on failure."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PERMALINK = "t_yamane"
PROFILE_URL = f"https://researchmap.jp/{PERMALINK}"
API_BASE = f"https://api.researchmap.jp/{PERMALINK}"
CATEGORIES = ("published_papers", "research_projects", "awards")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "researchmap_data.json"
PAGE_SIZE = 1000
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3


class FetchError(RuntimeError):
    """The API did not return a complete, identifiable category snapshot."""


def _category_matches(node, endpoint):
    node_id = node.get("@id")
    return (
        node.get("@type") == endpoint
        or (isinstance(node_id, str) and node_id.rstrip("/") == f"{API_BASE}/{endpoint}")
    )


def _page(data, endpoint):
    if not isinstance(data, dict):
        raise FetchError(f"{endpoint}: expected a JSON object")

    if "items" in data or "total_items" in data:
        page = data
    else:
        graph = data.get("@graph")
        if not isinstance(graph, list):
            raise FetchError(f"{endpoint}: missing items/total_items or @graph")
        matches = [
            node for node in graph
            if isinstance(node, dict) and _category_matches(node, endpoint)
        ]
        if len(matches) != 1:
            raise FetchError(f"{endpoint}: expected one matching @graph category")
        page = matches[0]

    items, total = page.get("items"), page.get("total_items")
    if not isinstance(items, list) or type(total) is not int or total < 0:
        raise FetchError(f"{endpoint}: invalid items or total_items")
    if len(items) > PAGE_SIZE:
        raise FetchError(f"{endpoint}: response exceeds the requested page size")
    return items, total


def _request_json(url, opener):
    """Retry only transient transport failures, never invalid content."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with opener(url, timeout=TIMEOUT_SECONDS) as response:
                content = response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            if isinstance(error, urllib.error.HTTPError):
                if error.code != 429 and not 500 <= error.code < 600:
                    raise
            if attempt == MAX_ATTEMPTS:
                raise
            delay = 2 ** (attempt - 1)
            print(
                f"  transient request failure ({error}); retrying in {delay}s "
                f"({attempt + 1}/{MAX_ATTEMPTS})",
                file=sys.stderr,
            )
            time.sleep(delay)
        else:
            return json.loads(content)


def fetch_items(endpoint, *, opener=urllib.request.urlopen):
    """Fetch every page using researchmap's one-based start parameter."""
    if endpoint not in CATEGORIES:
        raise ValueError(f"Unsupported category: {endpoint}")

    result, seen_ids = [], set()
    expected_total = None
    while True:
        query = urllib.parse.urlencode({
            "format": "json", "limit": PAGE_SIZE, "start": len(result) + 1,
        })
        url = f"{API_BASE}/{endpoint}?{query}"
        print(f"fetching: {url}")
        items, total = _page(_request_json(url, opener), endpoint)

        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise FetchError(f"{endpoint}: total_items changed during pagination")
        if len(result) + len(items) > total:
            raise FetchError(f"{endpoint}: items exceed total_items")
        if not items and len(result) < total:
            raise FetchError(f"{endpoint}: empty page before all items were received")

        for item in items:
            if not isinstance(item, dict):
                raise FetchError(f"{endpoint}: an item is not a JSON object")
            if "@type" in item and item["@type"] != endpoint:
                raise FetchError(f"{endpoint}: an item belongs to another category")
            identifiers = []
            for field in ("@id", "rm:id"):
                if field in item:
                    value = item[field]
                    if not isinstance(value, str) or not value.strip():
                        raise FetchError(f"{endpoint}: invalid {field}")
                    identifiers.append((field, value))
            if not identifiers:
                raise FetchError(f"{endpoint}: an item has no identifier")
            if any(identifier in seen_ids for identifier in identifiers):
                raise FetchError(f"{endpoint}: duplicate item ID during pagination")
            seen_ids.update(identifiers)
            result.append(item)

        if len(result) == expected_total:
            print(f"  -> {len(result)} items")
            return result


def update_snapshot(output, *, opener=urllib.request.urlopen):
    """Validate all categories, then atomically replace the destination file."""
    output = Path(output)
    previous = {}
    if output.exists():
        with output.open(encoding="utf-8") as stream:
            previous = json.load(stream)
        if not isinstance(previous, dict) or any(
            not isinstance(previous.get(category), list) for category in CATEGORIES
        ):
            raise FetchError(f"{output}: existing snapshot has an invalid schema")

    data = {}
    for category in CATEGORIES:
        data[category] = fetch_items(category, opener=opener)
        if previous.get(category) and not data[category]:
            raise FetchError(f"{category}: refusing to replace existing records with an empty list")

    data["_meta"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_profile_url": PROFILE_URL,
        "source_api_url": API_BASE,
        "schema_version": 1,
    }

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        update_snapshot(args.output)
    except (FetchError, OSError, ValueError) as error:
        print(f"researchmap update failed; previous snapshot preserved: {error}", file=sys.stderr)
        return 1
    print(f"saved: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
