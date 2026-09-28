# LifeLine — Architecture

> This document describes the real-AWS architecture (what `sam deploy` creates). For how
> the exact same Lambda code runs locally in GitHub Codespaces via `sam local start-api` +
> LocalStack — including the two things that differ (Bedrock → local extraction engine,
> Cognito → local JWT auth) and why — see `docs/local-development.md`.

## Concept

LifeLine implements COLLECT → UNDERSTAND → PRIORITIZE → RESPOND:

1. **Collect** — the user uploads documents (insurance, IDs, warranties, bills, certificates).
2. **Understand** — Amazon Bedrock extracts structured information (type, dates, amounts,
   actions) from each document; the output is schema-validated before it's trusted. An
   `LIFELINE_AI_PROVIDER=snapdragon` backend performs this same step on-device (ONNX
   Runtime OCR, with Qualcomm Snapdragon NPU acceleration via `QNNExecutionProvider` when
   available, plus the existing deterministic structuring logic) instead of calling
   Bedrock — fully developable/testable in GitHub Codespaces on CPU alone, with the
   Snapdragon NPU path production-ready for real hardware — see
   `docs/snapdragon-optimization.md`.
3. **Prioritize** — deterministic application code (not the LLM) classifies each dated item
   into urgent / attention-soon / upcoming / safe / needs-review, with an explainable reason.
4. **Respond** — "I HAVE A PROBLEM" mode lets the user pick a situation; Bedrock drafts a
   prioritized action plan grounded *only* in the user's already-stored data, which is then
   re-validated in code before being shown.

## Request flows

### Document upload & processing
```
Frontend
  -> POST /documents/upload-url   (API Gateway -> Lambda)
  -> Lambda creates document_id, writes a DynamoDB placeholder row,
     returns a presigned S3 PUT URL
  -> Frontend PUTs the file bytes directly to S3 (never through Lambda —
     LOCAL_MODE sends the file inline instead; see local-development.md)
  -> POST /documents/{id}/process (API Gateway -> Lambda)
       -> Lambda reads the object from S3
       -> Images (PNG/JPEG/WebP): sent to Bedrock as multimodal input
          (or Tesseract OCR locally — see lib/ai_provider.py)
       -> PDFs: text extracted via pypdf (backend/lib/pdf_extract.py) first;
          a PDF with no usable text layer (scanned/image-only) fails
          honestly as needs_review instead of being sent to Bedrock empty
       -> Bedrock extracts structured JSON (with one retry on throttling)
       -> schema.py validates it, with a fallback JSON-block extractor for
          stray model preamble (invalid/low-confidence -> needs_review,
          never fabricated)
       -> DynamoDB updated with extraction + status
       -> if expiry_date present, an EVENT# row is written (GSI1-indexed by date)
```

### Dashboard
```
GET /documents -> Lambda queries DynamoDB for the user's partition only
                -> priority_engine.py classifies + sorts every document
                -> conflict detection (same type + a provider detected on
                   both documents, different expiry dates)
                -> recent_events read from DynamoDB (written by the
                   EventBridge reminder sweep — real event-driven data,
                   not recomputed client-side)
                -> response to frontend
```

### Emergency / situation mode
```
POST /emergency/plan {situation}
  -> Lambda loads the user's processed documents + profile from DynamoDB
  -> Bedrock drafts a plan (system prompt forbids inventing facts, medical
     diagnosis/treatment advice, financial transactions, or autonomous outreach)
  -> validate_plan() defensively parses the model's JSON (handles stray
     preamble text), strips any document reference that isn't actually
     this user's, drops any malformed step rather than crashing, renumbers
     steps, and always attaches the fixed disclaimer
  -> response to frontend, which links each step back to its source document
```

### Event-driven reminders
```
EventBridge (rate(1 day)) -> ReminderSweepFunction
  -> queries DynamoDB GSI1 for documents expiring within +/-90 days
     (no full table scan; catches both upcoming deadlines and items that
     already expired and were never renewed)
  -> writes/refreshes an attention EVENT# row per item, classified with
     the same deterministic priority_engine.py used by the dashboard
  -> GET /documents surfaces these as recent_events in the dashboard's
     "Recent activity" section
```

## Data model (DynamoDB single-table)

| PK              | SK                          | Item                                  |
|-----------------|------------------------------|----------------------------------------|
| `USER#<uid>`    | `DOC#<document_id>`          | document metadata + extraction        |
| `USER#<uid>`    | `EVENT#<date>#<document_id>` | attention/reminder event              |
| `USER#<uid>`    | `PROFILE`                    | display name, emergency contact       |

`GSI1` (`gsi1pk = DATE#<expiry_date>`, `gsi1sk = USER#<uid>#DOC#<id>`) lets the reminder
sweep and conflict checks query by date without scanning the table.

## Security model

- Cognito-authenticated API Gateway (JWT authorizer) — Lambda never runs for an
  unauthenticated request in real AWS. `PreventUserExistenceErrors` is enabled so
  sign-in/sign-up responses don't reveal whether an email is registered. Locally (no
  Cognito authorizer available), `lib/auth_utils.py` falls back to verifying a local JWT
  directly — a path that's structurally unreachable in real AWS, since API Gateway itself
  rejects an unauthenticated request before Lambda ever runs. See local-development.md.
- Every DynamoDB and S3 access is scoped by the verified `sub` claim, never a
  client-supplied user id (application-level isolation — see `docs/limitations.md` for
  what this does and doesn't guarantee vs. per-user IAM scoping).
- S3 objects are keyed `users/<sub>/documents/...`; the bucket has no public access, denies
  any non-HTTPS request (bucket policy), and CORS/API Gateway origins are controlled by the
  `AllowedOrigin` stack parameter (defaults to `'*'` for first deploy; tighten to your
  Amplify domain once you have one — see `docs/deployment-checklist.md`).
- File type/size are validated before a presigned URL is issued.
- Bedrock IAM permissions are scoped to `bedrock:InvokeModel` on foundation-model and
  inference-profile ARNs — not `Resource: '*'`.

## Why this is realistic for a hackathon MVP

- No EC2/RDS/ECS/etc. — every compute path is Lambda, every service listed is one the
  hackathon explicitly provides.
- Step Functions was deliberately **not** used — the document pipeline is a handful of
  sequential steps inside one Lambda invocation, and a state machine would add
  operational surface without changing behavior at this scale (see `docs/limitations.md`
  for when it would earn its place).
- EventBridge is used for exactly one thing (the daily reminder sweep) rather than a
  speculative notification platform.
