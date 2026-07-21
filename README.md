# KYC Verifier

A web app for **bulk KYC document verification**. Customers/entities are added,
their KYC documents uploaded, and an OpenAI vision model checks the documents
against five bulk-upload rules — returning a per-rule PASS / FAIL / N/A verdict
with evidence, plus a branded PDF report.

## Checks performed

| Rule | Flag | Severity | Documents |
|------|------|----------|-----------|
| KYC_01 | Incomplete KYC | High | Application form |
| KYC_02 | Poor Documentation | Medium | Application form |
| KYC_04 | Invalid Document | High | Identity document |
| KYC_05 | Data Mismatch | High | Form + ID (cross-check) |
| KYC_09 | Incomplete Profile | Medium | Application form |

The cross-document check (KYC_05) is why verification runs per *customer* —
the form and ID are compared together in one model call.

## Run locally

```bash
cp .env.example .env      # then fill in OPENAI_API_KEY and AUTH_PASSWORD
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

Open <http://127.0.0.1:8000>. On Windows, `run.bat` does the same thing.

Set `COOKIE_SECURE=false` in `.env` for local development — the session cookie
is HTTPS-only by default and the browser will silently drop it over plain HTTP.

## Deploy to Render

The repo ships a [`render.yaml`](render.yaml) blueprint.

1. Render dashboard → **New** → **Blueprint** → select this repo.
2. Render reads `render.yaml` and prompts for the three secrets:
   `OPENAI_API_KEY`, `AUTH_USERNAME`, `AUTH_PASSWORD`.
3. Deploy. Health check is `/api/health`.

`GET /api/health` reports the model, whether an OpenAI key is configured, and
whether the instance has persistent storage — check it first when a deploy
looks wrong.

### Storage and the free tier

The free plan has **no persistent disk**. `data/` — the SQLite database and
every uploaded document — is wiped on each deploy and restart, then re-seeded
with the 12 demo customers from `kyc-test-docs/`. Verification runs do not
survive.

To keep data across deploys: move to a paid instance, uncomment the `disk:`
block in `render.yaml`, and set `DATA_DIR=/var/data`. No code change is needed;
the app reads that one variable to decide where to write.

### Two free-tier behaviours worth knowing

- **Cold starts.** The service sleeps after ~15 minutes idle. The next request
  pays the wake-up plus a re-seed, so a shared demo link can take ~30s to
  respond the first time.
- **Verification latency.** A run sends 4–12 high-detail page images to the
  vision model synchronously and can take 30–90 seconds with no progress
  indicator. This is inherent to the current design, not a deployment problem —
  moving verification to a background job would fix it.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | — | Required for verification to run. |
| `AUTH_USERNAME` | `admin` | Login username. |
| `AUTH_PASSWORD` | — | **Required.** The app refuses to start without it. |
| `OPENAI_VISION_MODEL` | `gpt-4o` | Vision model used for verification. |
| `RENDER_DPI` | `150` | Page raster resolution. Higher costs memory. |
| `MAX_PAGES_PER_DOC` | `6` | Page cap per document sent to the model. |
| `DATA_DIR` | `./data` | Database + upload location. |
| `COOKIE_SECURE` | `true` | Set `false` for local HTTP development. |

## How it works

1. Add a customer/entity (Individual or Corporate).
2. **Documents tab** — upload application forms and identity documents
   (PDF / PNG / JPG). View or remove any document.
3. **Verification tab** — *Run Verification* sends every document for that
   customer to the vision model with the rule set, and shows a per-rule verdict
   with evidence.
4. **Run All Verifications** (top bar) runs every customer that has documents.
5. Export a per-customer PDF report, or a ZIP of all completed reports.

## Layout

```
backend/
  main.py       FastAPI app + routes
  config.py     settings (env / .env)
  auth.py       single-credential session auth
  db.py         SQLite schema + helpers
  rules.py      the 5 KYC rules
  verifier.py   OpenAI vision verification engine
  reports.py    PDF report + ZIP generation
  seed.py       demo data bootstrap
frontend/
  index.html    single-page UI
  styles.css
  app.js
kyc-test-docs/  48 synthetic documents + manifest.csv answer key
data/           SQLite db + uploaded files (gitignored, created at runtime)
```

## Known constraints

- **Single instance only.** Sessions live in process memory, so multiple
  replicas would scatter them and log users out at random. Scaling out needs a
  shared session store.
- **One shared credential.** There are no user accounts or roles.
- The synthetic documents in `kyc-test-docs/output` and the answer key in
  `kyc-test-docs/manifest.csv` can be used to validate the pipeline end-to-end.
