# Talking about this project in interviews

Short prompts to help you explain the project by role. Read the code paths mentioned until you can explain each one without notes.

## Data engineer

- **Ingestion design**: daily batch from two official sources plus a fallback; raw files archived before parsing (`pipeline/sources/exchanges.py`), so any day can be replayed.
- **Idempotency**: upsert on (ISIN, date, exchange); a log of every attempt (`ingestion_runs`) makes runs resumable (`pipeline/ingest.py`).
- **Unreliable upstreams**: NSE's bot protection; retries with exponential backoff, 404 treated as a holiday, BSE and Yahoo covering missed days (`pipeline/http.py`).
- **Data quality**: validation gates (`pipeline/validate.py`): every IPO has a listing-day price, NSE and BSE agree within 3%, and no unexplained overnight move beyond the 20% price band.
- **A real data bug**: exchange prices aren't split-adjusted and Yahoo's are retroactively adjusted. Explain how prices are stored as traded and adjusted at read time, and how Yahoo's adjustment is undone.
- **Data as code**: the IPO master list is a reviewed CSV in git, collector-owned rows vs hand-corrected rows.
- *Likely follow-ups*: How would you backfill five years? (Cached raw files, parallel days, bulk inserts.) How would you schedule it? (GitHub Actions now; Airflow or Dagster with one task per source and date if it grew.)

## SDE

- **API design**: resource-style endpoints, typed response models (`app/schemas.py`), 404 vs 422, the `date` query parameter.
- **Separation of concerns**: pure domain functions (`services/categories.py`, `pnl.py`) with no database, tested in isolation; thin routers.
- **Performance**: the list endpoint fetches only two prices per IPO with a max-date subquery instead of loading every row (`services/summary.py`); the chart library is lazy-loaded on the front end.
- **Testing**: fixtures from real exchange rows, fake HTTP and AI clients, a test that the committed master CSV is valid, CI on every push.
- *Likely follow-ups*: How would you cache? (Response cache keyed on the latest ingestion run.) How would you scale the AI limit? (Redis.)

## AI engineer

- **Tool use, not text-to-SQL**: four typed tools with validated inputs (`app/ai/tools.py`); the model can't touch the database directly, which blocks prompt injection and keeps every number grounded.
- **The loop**: up to five tool rounds, tool errors returned to the model as data so it can recover or ask for clarification (`app/ai/agent.py`).
- **Transparency**: tool calls are returned with the answer and shown on the page.
- **Cost and abuse control**: question length limit, per-visitor and global daily limits, a small model by default.
- **Evaluation** (good next step to mention): a set of questions with known answers computed from the tools, run in CI against a fake or real model to catch regressions.

## Associate product manager

- **The user problem**: applicants care about rupees made per category, not just listing-day percentages (`docs/PRODUCT_BRIEF.md`).
- **A product decision with a reason**: showing the *minimum* application because oversubscribed categories allot exactly that.
- **Trade-offs you made**: official data over a broker API (cost, daily token renewal, licensing), version-one scope (BSE SME left out), and how you'd measure success.
- **What's next and why**: the BSE SME collector closes the biggest coverage gap; a compare-categories view answers the next question users ask.
