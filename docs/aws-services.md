# AWS services used, and why

This is a **Build It track** submission: the table below is written from the real-AWS
architecture's perspective (what `sam deploy` creates), since that's what "which AWS
services and why" means architecturally. For exactly how each one maps to something
running locally in Codespaces (and why), see `docs/local-development.md` — short version:
API Gateway/Lambda/DynamoDB/S3/EventBridge all run for real locally via the actual AWS SAM
CLI + LocalStack; only Bedrock and Cognito are replaced (no AWS account, and Cognito isn't
in LocalStack's free tier), each with a genuine open-source/offline equivalent, not a stub.

| Service | Used for | Why this one |
|---|---|---|
| **Amazon Cognito** | User sign-up/sign-in, issuing JWTs | Native fit with API Gateway's JWT authorizer; no custom auth code needed. Locally replaced by `backend/handlers/local_auth.py` (real PBKDF2 password hashing + JWT issuance), since LocalStack's community edition doesn't include Cognito. |
| **Amazon API Gateway** (HTTP API) | Public REST surface | Cheapest/simplest API Gateway flavor that still supports a JWT (Cognito) authorizer natively. Locally: the identical routes, served by `sam local start-api`. |
| **AWS Lambda** | All backend compute — upload URLs, document processing, priority queries, emergency plan generation, profile, reminder sweep, local auth | Matches the request pattern exactly (short, bursty, stateless); zero servers to manage for a hackathon timeline. Locally: the exact same Python handlers, run by the real AWS SAM CLI (`sam local start-api`), not reimplemented. |
| **Amazon S3** | Storage for original uploaded documents | Purpose-built for exactly this; DynamoDB is explicitly *not* used for file bytes. Locally: S3 inside LocalStack, reached via boto3's standard `AWS_ENDPOINT_URL` override — zero S3-specific code changes. |
| **Amazon DynamoDB** | Document metadata, extracted structured data, dates, actions, attention events, user profile, (locally) auth credentials | Single-table design keyed by user partition gives cheap, strongly-isolated per-user access with one GSI for date-range queries — no need for a relational store at this scale. Locally: DynamoDB inside LocalStack, same mechanism as S3 above. |
| **Amazon Bedrock** | (1) Structured extraction from uploaded documents, (2) drafting emergency action plans | The only AI/reasoning step in the system; every output is validated or guardrailed in application code before it's trusted (see `backend/lib/schema.py` and `backend/handlers/emergency.py::validate_plan`). Defaults to `global.anthropic.claude-sonnet-4-6`, configurable via the `BedrockModelId` stack parameter. IAM is scoped to `bedrock:InvokeModel` on foundation-model/inference-profile ARNs only — not `Resource: '*'`. Locally replaced by `backend/lib/local_reasoning.py` (real regex/keyword-based extraction + Tesseract OCR) behind the same interface (`backend/lib/ai_provider.py`) — switching back is a one-line env var change. |
| **Amazon EventBridge** | Daily scheduled sweep that (re)computes upcoming/urgent attention events | The one genuinely useful event-driven piece for this MVP — keeps the "reminders" pillar real without building a notification platform. A `rate(1 day)` schedule can't be watched firing live in *either* environment, so the same Lambda is also reachable via `POST /reminders/sweep` for on-demand triggering (see Settings → "Run attention sweep now") — this route exists in the real template too, not just locally. |
| **AWS Amplify Hosting** | Frontend hosting/CI from the React build | Matches the provided hackathon toolkit for a real deployment; build spec in `infrastructure/amplify.yml`. Locally: the Vite dev server instead (see `docs/local-development.md`). |
| **AWS SAM CLI** | Infrastructure-as-code + local Lambda/API Gateway emulation | `infrastructure/template.yaml` is the single source of truth for both `sam deploy` (real AWS) and `sam local start-api` (Codespaces) — the Build It track's required local-infra tooling, used as intended rather than only for deployment. |
| **LocalStack** (community edition) | Local DynamoDB + S3 | The Build It track's required local-AWS tooling. Only DynamoDB and S3 are enabled (`SERVICES=dynamodb,s3` in `docker-compose.yml`) — no services are started that the app doesn't actually use. |

## Explicitly not used, and why

- **Step Functions** — the document-processing pipeline (extract → validate → store) is a
  handful of sequential steps inside one Lambda invocation. A state machine would add
  deployment surface without changing behavior at hackathon scale. It's the natural next
  step if processing grows multi-stage (e.g., separate OCR, translation, or multi-model
  passes) — see `docs/future-improvements.md`.
- **Strands Agents SDK** — an agent framework needs a real model behind it to do anything
  useful; without one available offline (no Bedrock, no paid API), wiring it up would just
  be indirection around the same rule-based logic already in `local_reasoning.py` — no
  functional benefit, just name-dropping. Skipped, per the hackathon's own guidance to only
  add these where they'd genuinely help.
- **Cedar** — LifeLine's actual authorization model is "a user can only ever see their own
  data," enforced structurally by the DynamoDB key design (`USER#<id>/DOC#<id>`), not by
  role- or attribute-based policy logic. There's no policy complexity here for Cedar to
  meaningfully simplify. Skipped.
- **OpenSearch** — no full-text search or complex query requirement; documents are looked
  up by user + id, and dashboard/attention views are small in-memory sorts over one user's
  document list. Skipped.
- **EC2 / ECS / EKS / RDS / Redis / Kafka / SageMaker / CloudFront / Firebase / Supabase /
  external vector DBs** — none of these are needed for the MVP's actual requirements.
