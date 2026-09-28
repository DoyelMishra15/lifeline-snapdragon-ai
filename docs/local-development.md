# Local development (GitHub Codespaces / Build It track)

This document explains exactly what runs locally, what replaces what,
and why — so it's clear both how to run the project and how it maps
back to the real AWS architecture in `docs/architecture.md`.

## TL;DR

```
./start.sh
```
Then open the forwarded port **5173** (Codespaces will prompt you, or
use the "Ports" tab). Sign up with any email + an 8+ character
password — this creates a real account in your local database, not a
demo login.

## What's actually running

| Piece | Real AWS | Local (Codespaces) | Why |
|---|---|---|---|
| Compute / API | Lambda + API Gateway | `sam local start-api` (same Lambda code, real AWS SAM CLI, running in Docker) | This is the literal AWS SAM CLI — same handlers, same template.yaml, no rewrite. |
| Database | DynamoDB | DynamoDB **inside LocalStack** | LocalStack's community edition fully supports DynamoDB; `boto3`'s built-in `AWS_ENDPOINT_URL` env var redirects every SDK call there with zero code changes (see `infrastructure/env.local.json`). |
| File storage | S3 | S3 **inside LocalStack** | Same as above. |
| Auth | Amazon Cognito | A small local JWT auth service (`backend/handlers/local_auth.py`) | Cognito is a **LocalStack Pro** (paid) feature — not available community/free. Real signup/login, real password hashing (PBKDF2), issuing a JWT with the same `sub` claim shape Cognito would. `backend/lib/auth_utils.py` accepts either. |
| Document understanding | Amazon Bedrock (Claude) | A deterministic, offline extraction engine (`backend/lib/local_reasoning.py`) + Tesseract OCR for images (`backend/lib/ocr.py`) | Bedrock requires a real AWS account and a paid API call — not available offline. The local engine does real work: regex-based date/amount/provider extraction over actual document text, not filename guessing. Both share one interface (`backend/lib/ai_provider.py`), so swapping back to Bedrock for a real deployment is a one-line env var change, not a rewrite. |
| Scheduled reminders | EventBridge `rate(1 day)` rule | The same Lambda, plus a `POST /reminders/sweep` route for on-demand triggering | A once-a-day schedule can't be watched firing in a 3-minute demo in **either** environment — this isn't a local-only limitation. The manual trigger (also usable via `aws lambda invoke` against a real deployment) makes the same code demoable. See the "Run attention sweep now" button in Settings. |
| Frontend hosting | AWS Amplify Hosting | Vite dev server | Not part of the backend/infra story either way — this is just how you'd run any Vite app locally. |

A third option, `LIFELINE_AI_PROVIDER=snapdragon`, swaps only the OCR half of "Document
understanding" — on-device ONNX Runtime OCR (`backend/lib/onnx_ocr.py`), with a real
`auto`/`qnn`/`cpu` execution-mode system for Qualcomm Snapdragon NPU acceleration via
`QNNExecutionProvider` (`backend/lib/qnn_execution.py`) — instead of Tesseract, everything
else unchanged, through the same `backend/lib/ai_provider.py` seam described above. This
Codespace is the supported environment for developing and testing it: `cpu` and `auto`
modes fully work here on `CPUExecutionProvider` (no Snapdragon NPU present), and explicit
`qnn` mode correctly fails with an actionable error rather than silently using CPU — see
`docs/snapdragon-optimization.md` for exactly what has and hasn't been verified, including
the exact Windows-on-Snapdragon production setup and verification steps. It hasn't been
run through this SAM-local/LocalStack stack end-to-end (only through
`backend/tools/snapdragon_demo.py` and the pytest suite directly).

## Why SAM CLI + LocalStack, specifically (not a full rewrite)

`sam local start-api` reads the *exact same* `infrastructure/template.yaml`
that a real `sam deploy` uses, and runs the exact same Python handlers
in `backend/handlers/`. It talks to LocalStack over Docker's network
for DynamoDB/S3 calls, using boto3's standard `AWS_ENDPOINT_URL`
environment variable — no LocalStack-specific SDK code anywhere in
`backend/`. This is the difference between "the demo pretends to work"
and "the real Lambda code runs, against real (if local) AWS-API-
compatible services."

## Why a presigned S3 URL isn't used for local uploads/downloads

In real AWS, the frontend gets a presigned S3 URL from Lambda and
PUTs/GETs the file directly — Lambda never sees the file bytes. A
presigned URL generated *inside* a `sam local` Lambda container would
embed LocalStack's internal Docker-network hostname
(`http://localstack:4566`), which your browser — running outside that
network — can never resolve. So `LIFELINE_LOCAL_MODE=true` switches to:
- **Upload**: the frontend sends the file inline as base64
  (`backend/handlers/upload.py`), and Lambda writes it to S3
  server-side. Capped at 4MB (comfortably under API Gateway/Lambda's
  own 6MB synchronous payload limit).
- **Download**: `backend/handlers/documents.py` returns the file as a
  `data:` URI instead of a presigned URL.

Both fall back to the normal presigned-URL flow automatically when
`LIFELINE_LOCAL_MODE` isn't set — i.e., for a real deployment.

## Why the frontend talks to `/api`, not `localhost:3000`, directly

`sam local start-api` listens on port 3000 *inside the devcontainer*.
If the browser (which might be on your own laptop, viewing Codespaces
through a forwarded URL) tried to call `http://localhost:3000`
directly, "localhost" would mean *your laptop*, not the codespace —
nothing would be listening there. `vite.config.js` configures Vite's
dev server to proxy `/api/*` to `http://localhost:3000` **server-side**
(Vite and SAM both run inside the same devcontainer), so the browser
only ever talks to Vite's one forwarded origin (port 5173). This also
means no CORS configuration is needed for local dev.

## What Build It technologies were considered and not used

- **Strands Agents SDK**: an agent framework needs a model behind it to
  do anything; without a real LLM available offline, wiring it up here
  would just be indirection around the same rule-based logic already
  in `local_reasoning.py` — no functional benefit, just name-dropping.
  Skipped.
- **Cedar** (policy-based authorization): LifeLine's actual
  authorization model is "a user can only ever see their own data,"
  enforced structurally by the DynamoDB key design
  (`USER#<id>/DOC#<id>`) — see `docs/limitations.md`. There's no
  role/attribute-based policy complexity here for Cedar to meaningfully
  simplify. Skipped.
- **OpenSearch**: LifeLine has no full-text search or complex query
  requirement — documents are looked up by user + id, and the
  dashboard/attention views are small, in-memory sorts over a
  per-user document list. Adding a search cluster would be
  infrastructure with no feature behind it. Skipped.

Per the hackathon's own guidance, these are only worth including where
they'd genuinely improve the project — none of them would here.

## Rebuilding after a code change

`./start.sh` runs `sam build` every time, so backend changes are
picked up on the next `./start.sh`. For a running session, Ctrl+C the
frontend, then `./stop.sh && ./start.sh` to pick up backend changes;
frontend changes hot-reload automatically (Vite).

## Resetting local data

`./stop.sh` preserves your LocalStack data (documents, accounts)
across restarts. For a completely clean slate:
```bash
./stop.sh
docker compose down -v   # also removes the LocalStack data volume
./start.sh
```
