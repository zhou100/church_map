"""Phase B crawl pipeline (R2 + Postgres + LLM extraction).

Three stages, each independently re-runnable and idempotent:

  fetch.py    HTTP GET church websites, write raw HTML to R2, metadata to Postgres
  extract.py  LLM extraction over R2-cached HTML, structured JSON + confidence
  tag.py      deterministic tag rules over extracted_tags JSON

Driven by GitHub Actions cron hitting X-Crawl-Token-protected admin endpoints.
"""
