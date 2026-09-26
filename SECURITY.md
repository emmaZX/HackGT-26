# Security notes for a public repository

Recall Me Maybe is meant to be pushed to a public GitHub repo. Treat every commit as world-readable.

## Secrets

- Copy the example env files to `.env`, `backend/.env`, and `frontend/.env.local`. Never commit the real files.
- `.gitignore` already blocks `.env`, `.env.*`, key files, and credential JSON.
- Put vendor keys only in the backend environment: `GEMINI_API_KEY`, `EXA_API_KEY`, `BRAVE_SEARCH_API_KEY`, `OPENAI_API_KEY`. Supabase keys are reserved and unused.
- `NEXT_PUBLIC_*` values are shipped to the browser. They may contain the public API URL and public Cognito pool / app client IDs. They must never contain API keys or a Cognito client secret.
- Cognito user pool id and app client id are public browser config. A client secret must not exist on this SPA client. The frontend does not need a separate region variable; the pool id already includes it.

If a key is committed by accident, rotate it at the vendor immediately. Removing it from git history is not enough.

## What the API is allowed to expose

- Authenticated writes store a Cognito `user_sub` internally so likes and reports cannot be spoofed by display name.
- Public responses still show only a display name and an optional city-level location.
- Coordinates are snapped to a coarse grid before save. Responses return a city label plus an optional snapped city centroid, never a street-level pin.
- City lookup goes through `GET /api/locations` (known demo cities plus Open-Meteo geocoding). Only the chosen city label and snapped centroid are stored.
- The sketch map plots the seven demo cities. Other looked-up cities still appear as labels in the list.
- Uploaded files stay on local disk in `backend/data/uploads/` (gitignored).
- Live web discovery (`POST /api/products/{slug}/discover`) is unauthenticated. It only fetches `http(s)` URLs and stores the page text plus the source URL.

## Language and evidence

- Do not paste real people’s posts, emails, or medical details into seed data.
- Seed “official” recalls use demo source URLs so they are not mistaken for live CPSC pages.
- The model may only extract what a report says. It must not invent quotes or diagnose people.

## Before you push

1. `git status` and confirm no `.env`, `.env.local`, or `*.db` is staged.
2. Search the diff for `sk-`, `AIza`, `Bearer`, and `postgres://`.
3. Keep `CORS_ORIGINS` limited to your frontend origins (local demo may list `http://localhost:3000` and `http://localhost:3001`).
