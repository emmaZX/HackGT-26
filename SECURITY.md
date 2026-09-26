# Security notes for a public repository

Recall Me Maybe is meant to be pushed to a public GitHub repo. Treat every commit as world-readable.

## Secrets

- Copy `.env.example` to `.env` (and `frontend/.env.local`). Never commit the real files.
- `.gitignore` already blocks `.env`, `.env.*`, key files, and credential JSON.
- Put vendor keys only in the backend environment: `GEMINI_API_KEY`, `EXA_API_KEY`, `BRAVE_SEARCH_API_KEY`, `OPENAI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.
- `NEXT_PUBLIC_*` values are shipped to the browser. They may contain the public API URL. They must never contain API keys.

If a key is committed by accident, rotate it at the vendor immediately. Removing it from git history is not enough.

## What the API is allowed to expose

- User reports store only a display name and an optional city-level location.
- Coordinates are snapped to a coarse grid before save. Responses return a city label, never a precise pin.
- Uploaded files stay on local disk in `backend/data/uploads/` (gitignored).
- Live web discovery only fetches `http(s)` URLs and stores the page text plus the source URL.

## Language and evidence

- Do not paste real people’s posts, emails, or medical details into seed data.
- Seed “official” recalls use demo source URLs so they are not mistaken for live CPSC pages.
- The model may only extract what a report says. It must not invent quotes or diagnose people.

## Before you push

1. `git status` and confirm no `.env` or `*.db` is staged.
2. Search the diff for `sk-`, `AIza`, `Bearer`, and `postgres://`.
3. Keep `CORS_ORIGINS` limited to your frontend origin.
