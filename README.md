# Recall Me Maybe

A consumer product-safety intelligence demo for HackGT. Official recalls stay official. Community reports stay community reports. AI connects fragments that a single person would never see together.

The app starts from seeded data so the demo is full even when vendor APIs are offline. Add a search key later and the same pipeline can run niche web queries without a scraper per site.

## Quick start

```powershell
copy .env.example .env
copy frontend\.env.example frontend\.env.local

python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt
backend\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000 --app-dir backend

cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The API lives at [http://localhost:8000/docs](http://localhost:8000/docs).

## Public-repo setup

1. Copy the example env files. Leave keys blank unless you have them.
2. Never commit `.env`, `.env.local`, SQLite files, or upload folders.
3. Read `SECURITY.md` before the first push.

`.env.example` documents every variable. The running app does not require any paid key.

## What is implemented

- Home feed with notable warnings, optional **LOCAL** tags, trending, and recent reports
- Canonical product pages (`/product/acme-x100`) with official status vs community signal
- Evidence cards, issue filters, and coarse geographic clusters
- Community posts, comments, and likes that feed the same report table
- Keyword + lexical/semantic search
- User report submission that updates counts immediately
- Historical “before the recall” timeline on Harborline Instant Cooker
- Modular connectors under `backend/app/data_sources/`
- Optional live discovery: Gemini grounding, then Exa, then Brave

## Demo path

1. Home shows emerging signals and official recalls.
2. Open **Acme X100** — no official recall, emerging community signal, evidence, Atlanta cluster.
3. Search `burning plastic` or `Acme X100` and land on the same page.
4. Submit “Mine started overheating too.” Attach Atlanta.
5. Open **Harborline Instant Cooker** for the pre-recall timeline.

## Signal labels

There is no public danger score. Internal strength is mapped to:

- No significant signal
- Limited reports
- Elevated reports
- Emerging safety signal
- Strong emerging signal
- Official recall (separate overlay)

The recipe lives in `backend/app/pipeline/signals.py`.

## Live web discovery

`POST /api/products/{slug}/discover` writes a few narrow queries, fetches pages through one generic reader, extracts claims, embeds them, and collapses near-duplicates. No Reddit/news/FDA client is required for the demo.
