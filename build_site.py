#!/usr/bin/env python3
"""Render researchmap records into the existing static site, without network access."""

import argparse
from datetime import date, datetime
from html import escape
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import quote, unquote, urlsplit
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
TOKYO = ZoneInfo("Asia/Tokyo")
VERSION_LABELS = {
    "accepted_manuscript": "著者最終稿 PDF",
    "published_version": "出版社版 PDF",
    "preprint": "プレプリント PDF",
}
PROJECT_ROLE_LABELS = {
    "principal_investigator": "研究代表者",
    "coinvestigator": "研究分担者",
}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON {path}: {exc}") from exc


def text(value):
    """Prefer researchmap's Japanese display field, then its English field."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        for language in ("ja", "en"):
            if isinstance(value.get(language), str) and value[language].strip():
                return value[language].strip()
    return ""


def authors_text(value):
    if isinstance(value, dict):
        value = next(
            (value[lang] for lang in ("ja", "en")
             if isinstance(value.get(lang), list) and value[lang]), []
        )
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    names = []
    for author in value:
        if isinstance(author, str):
            name = author.strip()
        elif isinstance(author, dict):
            name = text(author.get("name")) or " ".join(filter(None, (
                text(author.get("family_name")), text(author.get("given_name"))
            )))
        else:
            name = ""
        if name:
            names.append(name)
    return ", ".join(names)


def record_id(item):
    return text(item.get("rm:id"))


def validate_data(data):
    if not isinstance(data, dict):
        raise ValueError("Researchmap data must be a JSON object.")
    for name in ("published_papers", "research_projects", "awards"):
        items = data.get(name)
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise ValueError(f"'{name}' must be an array of records.")
    if not data["published_papers"]:
        raise ValueError("No publications were supplied; refusing to publish an empty list.")
    ids = set()
    for item in data["published_papers"]:
        identifier = record_id(item)
        if not re.fullmatch(r"[0-9]+", identifier):
            raise ValueError("Every publication must have a numeric researchmap 'rm:id'.")
        if identifier in ids:
            raise ValueError(f"Duplicate researchmap publication ID: {identifier}")
        ids.add(identifier)
        if not text(item.get("paper_title") or item.get("title")):
            raise ValueError(f"Publication {identifier} has no title.")
        published = item.get("publication_date")
        if published not in (None, ""):
            if not isinstance(published, str) or not re.fullmatch(
                r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?", published
            ):
                raise ValueError(f"Publication {identifier} has an invalid publication_date.")
            parts = [int(part) for part in published.split("-")]
            try:
                date(parts[0], parts[1] if len(parts) > 1 else 1,
                     parts[2] if len(parts) > 2 else 1)
            except ValueError as exc:
                raise ValueError(f"Publication {identifier} has an invalid publication_date.") from exc
    return ids


def doi_for(item):
    candidates = [item.get("doi")]
    identifiers = item.get("identifiers")
    if isinstance(identifiers, dict):
        doi = identifiers.get("doi")
        candidates.extend(doi if isinstance(doi, list) else [doi])
    links = item.get("see_also") or []
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict):
                url = link.get("@id")
                if isinstance(url, str) and re.match(
                    r"https?://(?:dx\.)?doi\.org/", url, re.IGNORECASE
                ):
                    candidates.append(url)
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        doi = re.sub(r"^doi:\s*", "", candidate.strip(), flags=re.IGNORECASE)
        if re.match(r"https?://(?:dx\.)?doi\.org/", doi, re.IGNORECASE):
            doi = unquote(urlsplit(doi).path.lstrip("/"))
        if re.fullmatch(r"10\.[0-9]{4,9}/\S+", doi):
            return doi
    return ""


def load_manuscripts(path, publication_ids, required=False):
    if not path.exists() and not required:
        return {}
    manifest = read_json(path)
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1):
        raise ValueError("Manuscript manifest must have schema_version 1.")
    papers = manifest.get("papers")
    if not isinstance(papers, dict):
        raise ValueError("Manuscript manifest 'papers' must be an object keyed by researchmap ID.")
    today = datetime.now(TOKYO).date()
    validated = {}
    for identifier, entry in papers.items():
        if identifier not in publication_ids:
            raise ValueError(f"Manuscript ID {identifier!r} is absent from the researchmap data.")
        if not isinstance(entry, dict):
            raise ValueError(f"Manuscript {identifier} must be an object.")
        unknown = set(entry) - {"pdf", "version", "rights_statement", "available_from"}
        if unknown:
            raise ValueError(f"Manuscript {identifier} has unknown fields: {', '.join(sorted(unknown))}")
        version = entry.get("version")
        if not isinstance(version, str) or version not in VERSION_LABELS:
            raise ValueError(f"Manuscript {identifier} has an unsupported version.")
        rights = entry.get("rights_statement", "")
        if not isinstance(rights, str):
            raise ValueError(f"Manuscript {identifier}: rights_statement must be text.")
        available = entry.get("available_from")
        if available is not None:
            if not isinstance(available, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", available):
                raise ValueError(f"Manuscript {identifier}: available_from must be YYYY-MM-DD.")
            try:
                available_date = date.fromisoformat(available)
            except ValueError as exc:
                raise ValueError(f"Manuscript {identifier}: invalid available_from date.") from exc
            if available_date > today:
                raise ValueError(
                    f"Manuscript {identifier} is embargoed until {available}. "
                    "Do not commit embargoed PDFs to a public repository; keep them offline "
                    "and add the file and manifest entry only when publication is permitted."
                )
        raw_path = entry.get("pdf")
        if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path or "\x00" in raw_path:
            raise ValueError(f"Manuscript {identifier}: pdf must be a relative path under papers/.")
        relative = PurePosixPath(raw_path)
        if (relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2
                or relative.parts[0] != "papers" or relative.suffix.lower() != ".pdf"):
            raise ValueError(f"Manuscript {identifier}: pdf must be a relative .pdf path under papers/.")
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(ROOT / "papers") or not source.is_file():
            raise ValueError(f"Manuscript {identifier}: PDF is missing or resolves outside papers/.")
        with source.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError(f"Manuscript {identifier}: file does not have a PDF signature.")
        validated[identifier] = {
            "pdf": relative.as_posix(), "source": source,
            "version": version, "rights_statement": rights.strip(),
        }
    return validated


def publication_html(item, manuscripts):
    identifier = record_id(item)
    author = authors_text(item.get("authors") or item.get("author"))
    title = text(item.get("paper_title") or item.get("title"))
    journal = text(item.get("publication_name") or item.get("journal"))
    volume = text(item.get("volume"))
    number = text(item.get("number") or item.get("issue"))
    published = text(item.get("publication_date"))
    pieces = []
    if author:
        pieces.append(escape(author))
    pieces.append(f"“{escape(title)}”")
    if journal:
        pieces.append(f"<em>{escape(journal)}</em>")
    if volume:
        pieces.append(escape(volume) + (f"({escape(number)})" if number else ""))
    elif number:
        pieces.append(f"({escape(number)})")
    if published:
        pieces.append(escape(published[:4]))
    start, end = text(item.get("starting_page")), text(item.get("ending_page"))
    pages = text(item.get("page_range")) or (
        f"{start}–{end}" if start and end else start or end
    ) or text(item.get("pages"))
    if pages:
        # researchmap uses these fields for page ranges and article numbers.
        pieces.append(escape(pages))
    doi = doi_for(item)
    if doi:
        url = "https://doi.org/" + quote(doi, safe="/")
        pieces.append(f'<a href="{escape(url)}" target="_blank" rel="noopener">doi:{escape(doi)}</a>')
    content = ", ".join(pieces)
    if identifier in manuscripts:
        manuscript = manuscripts[identifier]
        href = escape(quote(manuscript["pdf"], safe="/"))
        label = VERSION_LABELS[manuscript["version"]]
        content += f' <a class="manuscript-link" href="{href}">{label}</a>'
        if manuscript["rights_statement"]:
            content += '<br><span class="muted manuscript-rights">' + escape(manuscript["rights_statement"]) + "</span>"
    return f'<li data-researchmap-id="{identifier}">{content}</li>'


def grants_html(items):
    result = []
    for item in sorted(items, key=lambda x: text(x.get("from_date")), reverse=True):
        title = text(item.get("research_project_title") or item.get("title"))
        meta = [text(item.get(field)) for field in (
            "offer_organization", "system_name", "category", "institution_name"
        )]
        start, end = text(item.get("from_date")), text(item.get("to_date"))
        if start or end:
            meta.append(f"{start} – {end}")
        role = text(item.get("research_project_owner_role") or item.get("research_project_roles"))
        meta.append(PROJECT_ROLE_LABELS.get(role, role))
        content = f"<strong>{escape(title)}</strong>" if title else ""
        details = " / ".join(filter(None, meta))
        if details:
            content += f'<br><span class="muted">{escape(details)}</span>'
        result.append(f"<li>{content}</li>")
    return result


def awards_html(items):
    result = []
    for item in sorted(items, key=lambda x: text(x.get("award_date")), reverse=True):
        name = text(item.get("award_name") or item.get("name"))
        title = text(item.get("award_title") or item.get("title"))
        content = f"<strong>{escape(name)}</strong>" if name else ""
        if title:
            content += (" – " if content else "") + escape(title)
        details = " / ".join(filter(None, (
            text(item.get("association") or item.get("organization")), text(item.get("award_date"))
        )))
        if details:
            content += f'<br><span class="muted">{escape(details)}</span>'
        result.append(f"<li>{content}</li>")
    return result


def replace_contents(html, tag, identifier, content, required=True):
    pattern = re.compile(
        r"(<" + tag + r"\b[^>]*\bid\s*=\s*([\"'])" + re.escape(identifier)
        + r"\2[^>]*>).*?(</" + tag + r"\s*>)", re.IGNORECASE | re.DOTALL
    )
    matches = list(pattern.finditer(html))
    if len(matches) != 1:
        if not matches and not required:
            return html
        raise ValueError(f"Template must contain exactly one <{tag}> with id='{identifier}'.")
    return pattern.sub(lambda match: match.group(1) + content + match.group(3), html)


def synced_at(data):
    meta = data.get("_meta")
    if meta is None:
        return "取得日時未記録"
    if not isinstance(meta, dict):
        raise ValueError("Researchmap '_meta' must be an object.")
    fetched = meta.get("fetched_at")
    if fetched in (None, ""):
        return "取得日時未記録"
    try:
        stamp = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Timezone missing")
    except (ValueError, AttributeError) as exc:
        raise ValueError("_meta.fetched_at must be an ISO timestamp with a timezone.") from exc
    return stamp.astimezone(TOKYO).strftime("%Y年%m月%d日 %H:%M（日本時間）")


def atomic_write(destination, content=None, source=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            if source is None:
                handle.write(content)
            else:
                with source.open("rb") as reader:
                    shutil.copyfileobj(reader, handle)
        temporary.chmod(0o644)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "researchmap_data.json")
    parser.add_argument("--manuscripts", type=Path, help="Optional manuscript manifest (default: manuscripts.json).")
    parser.add_argument("--output-dir", type=Path, default=ROOT,
                        help="Output only the publishable HTML, CSS and explicitly listed PDFs here.")
    args = parser.parse_args()
    try:
        data = read_json(args.data)
        ids = validate_data(data)
        manuscripts = load_manuscripts(
            args.manuscripts or ROOT / "manuscripts.json", ids,
            required=args.manuscripts is not None,
        )
        publications = sorted(data["published_papers"],
                              key=lambda item: text(item.get("publication_date")), reverse=True)
        rows = [publication_html(item, manuscripts) for item in publications]
        lists = {
            "index.html": {"publist-recent": rows[:10],
                           "grants-list": grants_html(data["research_projects"]),
                           "awards-list": awards_html(data["awards"])},
            "publications.html": {"publist-all": rows},
        }
        stamp = escape(synced_at(data))
        generated = {}
        for filename, replacements in lists.items():
            html = (ROOT / filename).read_text(encoding="utf-8")
            for identifier, items in replacements.items():
                content = "\n" + "\n".join("        " + item for item in items) + "\n      "
                html = replace_contents(html, "ul", identifier, content)
            html = replace_contents(html, "span", "researchmap-synced-at", stamp, required=False)
            generated[filename] = html.encode("utf-8")
        generated["style.css"] = (ROOT / "style.css").read_bytes()
        generated[".nojekyll"] = b""

        output = args.output_dir.resolve()
        if output.exists() and not output.is_dir():
            raise ValueError(f"Output path is not a directory: {output}")
        paths = set(generated) | {entry["pdf"] for entry in manuscripts.values()}
        destinations = {name: (output / name).resolve() for name in paths}
        for name, destination in destinations.items():
            if not destination.is_relative_to(output) or destination.is_dir():
                raise ValueError(f"Unsafe output path: {name}")

        if output != ROOT and output.exists():
            unexpected = sorted(
                str(path.relative_to(output)) for path in output.rglob("*")
                if (path.is_file() or path.is_symlink())
                and path.relative_to(output).as_posix() not in paths
            )
            if unexpected:
                raise ValueError(
                    "Output directory contains files not included in this build: "
                    + ", ".join(unexpected[:5])
                    + ". Use a fresh empty output directory so removed PDFs are not retained."
                )

        # All inputs, templates and paths have been validated before writing output.
        for filename, content in generated.items():
            atomic_write(destinations[filename], content=content)
        for entry in manuscripts.values():
            destination = destinations[entry["pdf"]]
            if destination != entry["source"]:
                atomic_write(destination, source=entry["source"])
        print(f"Built {output}: {len(publications)} publications, {len(manuscripts)} public PDFs.")
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(1, f"Build failed: {exc}\n")


if __name__ == "__main__":
    main()
