"""Parse USPTO weekly full-text XML (grant "Red Book" and application files).

Each weekly file is thousands of standalone XML documents concatenated together,
so it is not well-formed as a whole. We split on the XML declaration and parse
one document at a time, which also keeps memory flat for ~1 GB files.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Iterator

from lxml import etree

ROOTS = {"us-patent-grant": "grant", "us-patent-application": "application"}
_WS = re.compile(r"\s+")
_PARSER_OPTS = dict(recover=True, resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)


def _text(el) -> str:
    if el is None:
        return ""
    return _WS.sub(" ", "".join(el.itertext())).strip()


def _date(el) -> str:
    raw = _text(el)
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def iter_documents(path: Path) -> Iterator[bytes]:
    """Yield each XML document in a weekly file (.zip or already-extracted .xml)."""
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                if member.lower().endswith(".xml"):
                    with zf.open(member) as fh:
                        yield from _split(fh)
    else:
        with open(path, "rb") as fh:
            yield from _split(fh)


def _split(lines) -> Iterator[bytes]:
    buf: list[bytes] = []
    for line in lines:
        if line.startswith(b"<?xml") and buf:
            yield b"".join(buf)
            buf = []
        buf.append(line)
    if buf:
        yield b"".join(buf)


def _cpc_codes(root) -> list[str]:
    codes = []
    for c in root.iterfind(".//classifications-cpc//classification-cpc"):
        head = _text(c.find("section")) + _text(c.find("class")) + _text(c.find("subclass"))
        group, sub = _text(c.find("main-group")), _text(c.find("subgroup"))
        if head and group:
            code = f"{head} {group}/{sub}"
            if code not in codes:
                codes.append(code)
    return codes


def _orgs(root, xpath: str) -> list[str]:
    names = []
    for book in root.iterfind(xpath):
        name = _text(book.find("orgname"))
        if not name:
            name = " ".join(filter(None, [_text(book.find("first-name")), _text(book.find("last-name"))]))
        if name and name not in names:
            names.append(name)
    return names


def parse_document(raw: bytes) -> dict | None:
    """Return one patent record, or None for non-patent docs (e.g. sequence listings)."""
    try:
        root = etree.fromstring(raw, etree.XMLParser(**_PARSER_OPTS))
    except etree.XMLSyntaxError:
        return None
    if root is None or root.tag not in ROOTS:
        return None
    doc_type = ROOTS[root.tag]
    bib = root.find(f"us-bibliographic-data-{doc_type}")
    if bib is None:
        return None

    pub = bib.find("publication-reference/document-id")
    app = bib.find("application-reference/document-id")
    if pub is None:
        return None
    country = _text(pub.find("country")) or "US"
    number = _text(pub.find("doc-number")).lstrip("0") if doc_type == "grant" else _text(pub.find("doc-number"))
    kind = _text(pub.find("kind"))
    pub_number = f"{country}{number}{kind}"

    priorities = sorted(d for d in (_date(p.find("date")) for p in bib.iterfind("priority-claims/priority-claim")) if d)
    assignees = _orgs(bib, "assignees/assignee/addressbook") or _orgs(
        bib, "us-parties/us-applicants/us-applicant/addressbook"
    )
    claims = root.findall("claims/claim")
    app_ref = bib.find("application-reference")

    return {
        "pub_number": pub_number,
        "doc_type": doc_type,
        "appl_type": app_ref.get("appl-type", "") if app_ref is not None else "",
        "pub_date": _date(pub.find("date")),
        "app_number": _text(app.find("doc-number")) if app is not None else "",
        "filing_date": _date(app.find("date")) if app is not None else "",
        "priority_date": priorities[0] if priorities else "",
        "title": _text(bib.find("invention-title")),
        "abstract": _text(root.find("abstract")),
        "first_claim": _text(claims[0])[:3000] if claims else "",
        "n_claims": len(claims),
        "cpc": _cpc_codes(bib),
        "assignees": assignees,
        "inventors": _orgs(bib, "us-parties/inventors/inventor/addressbook"),
        "url": f"https://patents.google.com/patent/{pub_number}/en",
    }


def iter_patents(path: Path) -> Iterator[dict]:
    for raw in iter_documents(path):
        record = parse_document(raw)
        if record:
            yield record
