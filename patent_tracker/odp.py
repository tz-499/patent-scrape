"""Client for the USPTO Open Data Portal (ODP) bulk-data API.

Docs: https://data.uspto.gov/apis/bulk-data/product
Every call needs a free API key sent in the ``x-api-key`` header.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import requests

API_BASE = "https://api.uspto.gov/api/v1/datasets/products"

# Weekly full-text files are named ipgYYMMDD.zip (grants) / ipaYYMMDD.zip (applications).
WEEKLY_FILE = re.compile(r"^ip[ga](\d{2})(\d{2})(\d{2})\.zip$")


@dataclass(frozen=True)
class BulkFile:
    name: str
    url: str
    date: dt.date


def _walk_files(node):
    """Yield every dict carrying a download URI, wherever it sits in the response."""
    if isinstance(node, dict):
        if node.get("fileDownloadURI"):
            yield node
        for value in node.values():
            yield from _walk_files(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_files(item)


def files_from_response(payload: dict) -> list[BulkFile]:
    """Extract the weekly zip files from a product-data response."""
    found = {}
    for entry in _walk_files(payload):
        url = entry["fileDownloadURI"]
        name = entry.get("fileName") or url.rsplit("/", 1)[-1]
        match = WEEKLY_FILE.match(name)
        if not match:
            continue  # yearly archives, DTDs, documentation, etc.
        yy, mm, dd = (int(g) for g in match.groups())
        found[name] = BulkFile(name=name, url=url, date=dt.date(2000 + yy, mm, dd))
    return sorted(found.values(), key=lambda f: f.date)


def list_files(product: str, api_key: str, session: requests.Session | None = None) -> list[BulkFile]:
    http = session or requests
    resp = http.get(f"{API_BASE}/{product}", headers={"x-api-key": api_key}, timeout=60)
    resp.raise_for_status()
    return files_from_response(resp.json())


def download(file: BulkFile, dest_dir: Path, api_key: str) -> Path:
    """Stream a bulk file to disk; skips the download if it is already there."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file.name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(".part")
    with requests.get(file.url, headers={"x-api-key": api_key}, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as out:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                out.write(chunk)
    tmp.rename(dest)
    return dest
