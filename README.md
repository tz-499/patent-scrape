# patent-scrape

A weekly batch job that reads every new US patent grant and published application,
keeps the ones matching topics you care about, and writes a ranked Markdown digest.

## How it works

```
USPTO Open Data Portal ──> weekly zips ──> stream-parse XML ──> CPC/keyword filter
   (PTGRXML, APPXML)        (data/raw)      (one doc at a time)   (~15k -> hundreds)
                                                                        │
digests/YYYY-MM-DD.md  <── optional LLM summary <── TF-IDF ranking per topic
data/matches/*.jsonl
```

1. **Ingest** - lists the weekly full-text files (`ipgYYMMDD.zip` grants, `ipaYYMMDD.zip`
   applications) from the ODP bulk-data API and downloads any not yet in `data/state.json`.
2. **Parse** - each zip is thousands of concatenated XML documents; they are split and
   parsed one at a time, so memory stays flat.
3. **Filter** - a patent is a candidate if it hits a topic's CPC prefix or keyword.
4. **Rank** - candidates are scored by TF-IDF similarity to the topic's plain-English
   description, plus boosts for CPC, keyword, and watched-assignee hits.
5. **Summarise (optional)** - if `ANTHROPIC_API_KEY` is set, the top matches get a
   two-sentence summary and a 1-5 relevance score.
6. **Publish** - writes `digests/<date>.md`, `digests/latest.md`, and
   `data/matches/<date>.jsonl`. GitHub Actions commits them back to the repo.

## Setup

1. Get a free USPTO API key: <https://data.uspto.gov/apis/getting-started>
2. In the repo: **Settings -> Secrets and variables -> Actions**, add `USPTO_API_KEY`
   (and optionally `ANTHROPIC_API_KEY`).
3. The workflow runs every Friday. To run it now: **Actions -> Weekly patent digest -> Run workflow**.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest -q

export USPTO_API_KEY=...
python -m patent_tracker run                    # last 14 days of unprocessed files
python -m patent_tracker run --lookback-days 60 # backfill
python -m patent_tracker run --file ipg261110.zip   # a file you already downloaded
```

## Tuning

Everything lives in `config.yaml`:

- `topics` - name, description, `cpc_prefixes`, `keywords`. Add a topic by adding a block.
  Look up CPC codes at <https://www.uspto.gov/web/patents/classification/cpc/html/cpc.html>.
- `scoring.min_score` / `top_n` - noise vs. coverage.
- `scoring.watch_assignees` - companies and labs that get a ranking boost.
- `llm` - model and how many matches per topic to summarise.

## Querying the history

`data/matches/*.jsonl` is one JSON object per match, so DuckDB can query it directly:

```sql
SELECT topic, title, assignees, score
FROM read_json_auto('data/matches/*.jsonl')
ORDER BY score DESC LIMIT 20;
```

## Notes and limits

- Applications publish about 18 months after filing, so "new" means newly public.
- Only utility patents are scored; designs, plants, and reissues are skipped.
- Only matches are stored, not the full weekly corpus (about 1 GB of XML per file).
- TF-IDF is a keyword-overlap measure. Swapping in embeddings is the natural next step
  if ranking quality is the bottleneck.
