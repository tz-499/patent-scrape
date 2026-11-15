import json
import zipfile
from pathlib import Path

from patent_tracker import cli, odp, parse, score

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_week.xml"


def patents():
    return {p["pub_number"]: p for p in parse.iter_patents(FIXTURE)}


def test_splits_and_skips_non_patent_docs():
    assert len(list(parse.iter_documents(FIXTURE))) == 5  # incl. one sequence listing
    assert set(patents()) == {"US12900001B2", "US12900002B1", "US20260345678A1", "USD1099999S"}


def test_grant_fields():
    p = patents()["US12900001B2"]
    assert p["doc_type"] == "grant" and p["appl_type"] == "utility"
    assert p["pub_date"] == "2026-11-10" and p["filing_date"] == "2023-03-15"
    assert p["priority_date"] == "2022-03-14"
    assert p["title"] == "Transcranial focused ultrasound system for targeted neuromodulation"
    assert p["cpc"] == ["A61N 7/00", "A61B 5/369"]
    assert p["assignees"] == ["Example Neuro Labs, Inc."]
    assert p["inventors"] == ["Dana Rivera"]
    assert p["n_claims"] == 2 and p["first_claim"].startswith("1. A system")
    assert "\n" not in p["abstract"]


def test_application_falls_back_to_applicant():
    p = patents()["US20260345678A1"]
    assert p["doc_type"] == "application"
    assert p["assignees"] == ["Example Systems Corporation"]
    assert p["url"].endswith("/US20260345678A1/en")


def test_reads_zip(tmp_path):
    z = tmp_path / "ipg261110.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(FIXTURE, "ipg261110.xml")
    assert len(list(parse.iter_patents(z))) == 4


def test_cpc_prefix_matching():
    t = score.Topic("t", "d", cpc_prefixes=["G06F 9/50", "A61N1/"])
    hit = lambda code: score.stage1({"cpc": [code], "title": "", "abstract": ""}, t)[0]
    assert hit("G06F 9/5027")      # subgroup under 9/50
    assert not hit("G06F 9/45")
    assert hit("A61N 1/36")
    assert not hit("A61N 10/00")   # "A61N1/" must not match main group 10


def test_ranking_puts_each_patent_in_its_topic():
    _, topics = cli.load_config(ROOT / "config.yaml")
    candidates, scanned = cli.scan([FIXTURE], topics)
    assert scanned == 4
    assert {c["pub_number"] for c in candidates} == {"US12900001B2", "US20260345678A1"}  # no coffee maker, no design
    ranked = score.rank(candidates, topics, {"min_score": 0.1})
    assert [m["pub_number"] for m in ranked["Neuromodulation and brain stimulation"]] == ["US12900001B2"]
    assert [m["pub_number"] for m in ranked["Idle compute and GPU scheduling"]] == ["US20260345678A1"]
    assert ranked["AI and machine learning"] == []


def test_watched_assignee_boost():
    _, topics = cli.load_config(ROOT / "config.yaml")
    candidates, _ = cli.scan([FIXTURE], topics)
    base = score.rank(candidates, topics, {})["Idle compute and GPU scheduling"][0]["score"]
    boosted = score.rank(candidates, topics, {"watch_assignees": ["example systems"]})
    assert boosted["Idle compute and GPU scheduling"][0]["score"] > base


def test_odp_response_parsing():
    payload = {"bulkDataProductBag": [{"productIdentifier": "PTGRXML", "productFileBag": {"fileDataBag": [
        {"fileName": "ipg261110.zip", "fileDownloadURI": "https://api.uspto.gov/api/v1/datasets/products/files/PTGRXML/2026/ipg261110.zip"},
        {"fileName": "ipg261103.zip", "fileDownloadURI": "https://api.uspto.gov/x/ipg261103.zip"},
        {"fileName": "2025.zip", "fileDownloadURI": "https://api.uspto.gov/x/2025.zip"},
        {"fileDownloadURI": "https://api.uspto.gov/x/ipg261027.zip"},
    ]}}]}
    files = odp.files_from_response(payload)
    assert [f.name for f in files] == ["ipg261027.zip", "ipg261103.zip", "ipg261110.zip"]
    assert files[-1].date.isoformat() == "2026-11-10"


def test_end_to_end_local_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "config.yaml").write_text((ROOT / "config.yaml").read_text())
    rc = cli.main(["run", "--root", str(tmp_path), "--file", str(FIXTURE), "--date", "2026-11-13"])
    assert rc == 0
    md = (tmp_path / "digests" / "2026-11-13.md").read_text()
    assert "Transcranial focused ultrasound" in md and "Beverage brewing" not in md
    rows = [json.loads(l) for l in (tmp_path / "data" / "matches" / "2026-11-13.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert not (tmp_path / "data" / "state.json").exists()  # local runs don't touch state
