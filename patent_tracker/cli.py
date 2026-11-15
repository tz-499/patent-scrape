"""Entry point: ``python -m patent_tracker run``."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from . import digest, odp, parse, score, summarize

log = logging.getLogger("patent_tracker")


def load_config(path: Path) -> tuple[dict, list[score.Topic]]:
    cfg = yaml.safe_load(path.read_text())
    topics = [score.Topic(**t) for t in cfg["topics"]]
    return cfg, topics


def load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"processed": []}


def scan(paths: list[Path], topics: list[score.Topic], include_designs: bool = False) -> tuple[list[dict], int]:
    """Stream every file, keeping only stage-1 candidates in memory."""
    candidates, scanned, seen = [], 0, set()
    for path in paths:
        for patent in parse.iter_patents(path):
            scanned += 1
            if patent["appl_type"] != "utility" and not include_designs:
                continue  # designs, plants, reissues
            if patent["pub_number"] in seen:
                continue
            if score.is_candidate(patent, topics):
                seen.add(patent["pub_number"])
                candidates.append(patent)
        log.info("%s: %d scanned so far, %d candidates", path.name, scanned, len(candidates))
    return candidates, scanned


def run(args) -> int:
    root = Path(args.root)
    cfg, topics = load_config(root / args.config)
    state_path = root / "data" / "state.json"
    state = load_state(state_path)

    if args.file:  # local files: no API key, no state changes
        paths, names = [Path(f) for f in args.file], [Path(f).name for f in args.file]
    else:
        api_key = os.environ.get("USPTO_API_KEY")
        if not api_key:
            log.error("Set USPTO_API_KEY (free key from https://data.uspto.gov/apis/getting-started).")
            return 2
        cutoff = dt.date.today() - dt.timedelta(days=args.lookback_days)
        todo = []
        for product in cfg["sources"]["products"]:
            files = odp.list_files(product, api_key)
            new = [f for f in files if f.date >= cutoff and f.name not in state["processed"]]
            log.info("%s: %d weekly files listed, %d new since %s", product, len(files), len(new), cutoff)
            todo += new
        if not todo:
            log.info("Nothing new to process.")
            return 0
        paths = [odp.download(f, root / "data" / "raw", api_key) for f in todo]
        names = [f.name for f in todo]

    candidates, scanned = scan(paths, topics)
    ranked = score.rank(candidates, topics, cfg.get("scoring", {}))
    summarize.add_summaries(ranked, {t.name: t.description for t in topics}, cfg.get("llm", {}))

    run_date = args.date or dt.date.today().isoformat()
    stats = {"files": names, "scanned": scanned, "candidates": len(candidates)}
    out_md = root / "digests" / f"{run_date}.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    text = digest.render(run_date, ranked, stats)
    out_md.write_text(text)
    (root / "digests" / "latest.md").write_text(text)

    out_jsonl = root / "data" / "matches" / f"{run_date}.jsonl"
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(out_jsonl, "w") as fh:
        for matches in ranked.values():
            for m in matches:
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")

    if not args.file:
        state["processed"] = sorted(set(state["processed"]) | set(names))
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        if not args.keep_raw:
            for p in paths:
                p.unlink(missing_ok=True)

    total = sum(len(m) for m in ranked.values())
    log.info("Wrote %s (%d matches from %d documents)", out_md, total, scanned)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="patent_tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch new weekly files, score them, write a digest")
    r.add_argument("--root", default=".", help="repo root (holds config.yaml, data/, digests/)")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--lookback-days", type=int, default=14, help="how far back to look for unprocessed files")
    r.add_argument("--file", action="append", help="process a local .zip/.xml instead of downloading (repeatable)")
    r.add_argument("--date", help="override the digest date (YYYY-MM-DD)")
    r.add_argument("--keep-raw", action="store_true", help="keep downloaded zips in data/raw")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
