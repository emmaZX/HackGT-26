# Recall Me Maybe

A consumer product-safety intelligence demo for HackGT. Official recalls stay official. Community reports stay community reports. AI connects fragments that a single person would never see together.

The app starts from seeded data so the demo is full even when vendor APIs are offline. Add a search key later and the same pipeline can run niche web queries without a scraper per site.

## Quick start

```powershell
copy .env.example .env
copy frontend\.env.example frontend\.env.local
copy backend\.env.example backend\.env

python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt
backend\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000 --app-dir backend

cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). If port 3000 is busy, Next hops to 3001. `.env.example` allows both origins. The API lives at [http://localhost:8000/docs](http://localhost:8000/docs).

With `NEXT_PUBLIC_API_URL` left empty, Next proxies `/api` and `/health` to port 8000. Browsing works without keys. Creating a complaint needs Cognito IDs in the root `.env`, `backend/.env`, and `frontend/.env.local` (see below).

`GET /health` should return `"auth": true` after those IDs are set and uvicorn is restarted.

## Sign in with Cognito

Home, Browse, and Look up stay public. Creating a complaint, community post, comment, or like requires an AWS Cognito account. **Tell us** redirects to `/login?next=/report` when you are signed out.

1. In the AWS console, create a **Cognito user pool**.
2. Application type: **Single-page application (SPA)**. Do not pick Traditional web application — that adds a client secret and breaks browser sign-in.
3. Sign-in: email. Required attributes: **email** plus a public display name. Either **name** or **preferred_username** works. The app sends both.
4. App client: public SPA client, **no client secret**. Enable `ALLOW_USER_SRP_AUTH` and `ALLOW_REFRESH_TOKEN_AUTH`.
5. Return / callback and sign-out URLs: `http://localhost:3000` and `http://localhost:3001` (add your real domain later).
6. Copy the IDs into **all three** env files. Next.js only reads `frontend/.env.local`. The API reads the root `.env` and `backend/.env`.

Backend (root `.env` and `backend/.env`):

```
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_xxxxxxxx
COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
```

Frontend (`frontend/.env.local` — Next ignores the root `.env`):

```
NEXT_PUBLIC_COGNITO_USER_POOL_ID=us-east-1_xxxxxxxx
NEXT_PUBLIC_COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
```

The pool id already includes the region, so the frontend does not read `NEXT_PUBLIC_COGNITO_REGION`. Never put a client secret in these files. Restart uvicorn and `npm run dev` after changing env files.

Until the pool IDs are set, write endpoints return **503**. A request without a valid Bearer token returns **401**.

After signup, Cognito emails a confirmation code. Confirm that before the header will show your name and **Sign out**. Unconfirmed users can finish confirmation on `/login`. You can also confirm the user under Cognito → Users.

A custom domain is separate from Cognito. You can later attach `www.yourdomain.com` to Amplify or CloudFront and `api.yourdomain.com` to the FastAPI host. Login pages live on this site (`/login`, `/signup`), so Cognito can stay on `*.amazoncognito.com`.

## Pages

| Nav label | Route | Notes |
| --- | --- | --- |
| Home | `/` | Notable warnings, optional **LOCAL** tags, trending, recent reports |
| Browse | `/explore` | Full product list |
| Look up | `/search?q=` | Keyword + lexical/semantic search |
| Tell us | `/report` | Sign-in required. Accepts `?product=` to prefill a new item |
| Sign in / Create account | `/login`, `/signup` | Email + password through Cognito |
| Product | `/product/{slug}` | Official status vs community signal |

## Search misses

A catalog miss is intentional, not a broken search. Weak semantic hits (score under 0.72) are dropped when there are no keyword matches, so a nonsense query stays empty.

- No products, notes, or related hits: **We do not have that item yet** and a **Submit a report** button
- Notes or related hits but no product name match: **No matching product yet** with the same button
- Unknown `/product/{slug}`: **Item not found** with the same button

**Submit a report** opens `/report?product=` with the search text (or slug words) filled in so you can add the item.

## Public-repo setup

1. Copy the example env files. Leave keys blank unless you have them.
2. Never commit `.env`, `.env.local`, SQLite files, or upload folders.
3. Read `SECURITY.md` before the first push.

`.env.example` documents every variable the app reads. The running app does not require any paid key.

## What is implemented

- Home feed with notable warnings, optional **LOCAL** tags, trending, and recent reports
- Browse (`/explore`) and canonical product pages (`/product/acme-x100`) with official status vs community signal
- Evidence cards, issue filters, and city-level geographic clusters
- Community posts, comments, and likes on each product page (writes require login)
- Keyword + lexical/semantic search on Look up
- Empty / unknown-item pages with a button to submit a report
- Report form that searches existing products, lets you add a new one, looks up any city, and accepts `?product=` (sign-in required)
- Email signup / login through AWS Cognito (`/login`, `/signup`)
- Historical “before the recall” timeline on Harborline Instant Cooker
- Modular connectors under `backend/app/data_sources/`
- Optional live discovery: OpenAI web search, then Gemini grounding, then Exa, then Brave

## Demo path

1. Home shows emerging signals and official recalls.
2. Open **Acme X100** (`/product/acme-x100`) — no official recall, emerging community signal, evidence, Atlanta cluster.
3. Search `burning plastic` or `Acme X100` and land on the same page.
4. Search something that is not in the catalog. Confirm the miss prompt, then **Submit a report**.
5. Sign in, open **Tell us**, search a product or add a new one, and optionally look up a city.
6. Open **Harborline Instant Cooker** (`/product/harborline-cooker-6`) for the pre-recall timeline.

## Signal labels

There is no public danger score. Internal strength is mapped to:

- No significant signal
- Limited reports
- Elevated reports
- Emerging safety signal
- Strong emerging signal
- Official recall (separate overlay)

The recipe lives in `backend/app/pipeline/signals.py`.

## API

Public reads: `GET /health`, `/api/feed`, `/api/products`, `/api/products/{slug}`, `/api/search`, `/api/locations`.

Writes that need a Cognito ID token: `POST /api/reports`, `/api/posts`, `/api/posts/{id}/comments`, `/api/posts/{id}/likes`.

`POST /api/products/{slug}/discover` is public. It writes a few narrow queries, fetches pages through one generic reader, extracts claims, embeds them, and collapses near-duplicates. An `OPENAI_API_KEY` is enough. Gemini, Exa, and Brave remain optional fallbacks.

City lookup (`GET /api/locations`) matches the demo city list, then Open-Meteo geocoding.

## Data files

Relative `DATABASE_URL` values such as `sqlite:///./data/signal.db` always resolve to `backend/data/signal.db`, no matter which folder you start uvicorn from. Uploads go to `backend/data/uploads/`. New reports are stored in that same file, so they show up in Look up after submit.
