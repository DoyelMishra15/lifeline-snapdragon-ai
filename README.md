# LifeLine

LifeLine turns important personal documents into an organized, prioritized source of truth
for everyday attention and emergency continuity.

Built for the **WeMakeDevs × AWS First Commit hackathon**, **Build It track**, and now extended with
Snapdragon-optimized on-device OCR for the **Snapdragon® AI Lab Build & Present Challenge**.

**COLLECT → UNDERSTAND → PRIORITIZE → RESPOND**

## Demo

[Watch the 3-minute LifeLine demo on YouTube](https://youtu.be/hGvXdTfEL2w)

The demo shows the complete local workflow in GitHub Codespaces: document upload, information extraction and prioritization, and emergency action-plan generation.

## Hackathon / Project Overview

Important information is often scattered across insurance documents, IDs, warranties,
bills, certificates, and other files. In a stressful moment, finding the right detail is
as difficult as knowing what to do next.

LifeLine collects those documents, extracts useful structured information, validates and
prioritizes dates and risks, and connects each result back to its source. For example, a
user can upload important documents, let LifeLine structure and prioritize them, then
report an emergency such as losing a wallet. LifeLine produces a relevant action plan
from the information already stored, with clear next steps and missing information.

The complete Codespaces workflow is local and offline-friendly: **no AWS account,
credentials, or paid API is required** to run the project locally.

## Run locally in GitHub Codespaces

1. Open the repository in GitHub Codespaces and wait for the environment setup to finish.
2. Start the stack:

   ```bash
   ./start.sh
   ```

   This starts LocalStack, creates the local DynamoDB table and S3 bucket, builds the
   Lambda code with AWS SAM, starts the API with `sam local start-api`, and starts Vite.
   The first run may take a few minutes while Docker downloads the Lambda runtime image.
3. Open forwarded port **5173** and create an account with an email address and an
   8-character minimum password.
4. Upload a document, review its extracted and prioritized information, then choose
   **I have a problem** to generate an emergency action plan.

See [`docs/demo-flow.md`](docs/demo-flow.md) for the short submission walkthrough.

Stop the frontend with `Ctrl+C`, then run:

```bash
./stop.sh
```

## Local/Codespaces implementation

The local workflow uses the same Lambda handlers and SAM template, but replaces AWS-only
services that are not available in the free local stack:

- **GitHub Codespaces** provides the development environment.
- **AWS SAM CLI** runs the Lambda handlers locally in Docker.
- **LocalStack** provides local, AWS-compatible DynamoDB and S3 services.
- A deterministic, offline reasoning engine handles document extraction and emergency-plan
  generation locally, with Tesseract OCR for supported images.
- Local JWT authentication replaces Amazon Cognito for local signup and login.
- Vite serves the React frontend and proxies `/api` requests to the local SAM API.

Amazon Bedrock and Amazon Cognito are **not running locally** in this workflow. The local
substitutes share the application interfaces used by the production path; details are in
[`docs/local-development.md`](docs/local-development.md).

## Production AWS architecture

The same SAM template can be deployed to real AWS. The production architecture uses:

- **AWS Lambda** and **API Gateway** for the backend API
- **Amazon S3** for document storage
- **Amazon DynamoDB** for application data and reminder indexes
- **Amazon Bedrock** for document understanding and emergency-plan drafting
- **Amazon Cognito** for user authentication and API JWT authorization
- **AWS Amplify Hosting** for the frontend
- **Amazon EventBridge** for the daily reminder sweep
- **AWS SAM** for infrastructure definition and deployment

This project is not presented as a deployed production service. To explore a real AWS
deployment, follow [`docs/deployment-checklist.md`](docs/deployment-checklist.md).

## Snapdragon on-device OCR

For the Snapdragon® AI Lab Build & Present Challenge, LifeLine adds an optional
`LIFELINE_AI_PROVIDER=snapdragon` provider that reads document images on-device with
**RapidOCR** and **ONNX Runtime**, with a **QNNExecutionProvider** path targeting
Windows-on-Snapdragon (ARM64). Only the OCR step changes; document structuring and
emergency-plan drafting reuse the existing local reasoning logic.

```text
Document → RapidOCR → ONNX Runtime → QNNExecutionProvider → Snapdragon NPU → Structured information
                                      └─ QNN unavailable → CPUExecutionProvider
```

Set the mode with `LIFELINE_OCR_EXECUTION_MODE`:

| Mode | Behavior |
|---|---|
| `cpu` | Always `CPUExecutionProvider` (portable development and testing) |
| `auto` (default) | Prefers QNN and falls back to CPU when QNN is unavailable |
| `qnn` | Requires QNN and fails clearly instead of silently using CPU |

**Current validation:** 172 backend tests pass. CPU OCR was verified in GitHub Codespaces,
`auto` mode falls back to CPU there, and explicit `qnn` mode correctly reports that QNN is
unavailable.

**Not yet done:** running OCR on a Snapdragon NPU. That needs a compatible
Windows-on-Snapdragon device, and no NPU latency or accuracy figures are claimed. Local OCR
reduces the need to send raw document images off the device, but the production
architecture above still uses AWS services. See
[`docs/snapdragon-optimization.md`](docs/snapdragon-optimization.md) for setup and the full
list of what is and is not verified.

## Repository layout

```text
lifeline/
├── backend/                 Lambda handlers, shared libraries, and tests
│   ├── handlers/            API entry points, including local auth routes
│   ├── lib/                 Storage, validation, priority, OCR, and AI providers
│   ├── tools/               Snapdragon OCR demo and benchmark scripts
│   └── tests/               172-test pytest suite
├── frontend/                React + Vite web application
│   ├── src/                 Pages, components, API client, and auth context
│   ├── package.json         Frontend scripts and dependencies
│   └── package-lock.json    Locked frontend dependency versions
├── infrastructure/          AWS SAM template and Amplify build specification
├── docs/                    Architecture, local development, deployment, and demo guides
├── scripts/                 Local resource setup helpers
├── docker-compose.yml        LocalStack service definition
├── start.sh / stop.sh       Local stack lifecycle scripts
└── README.md                Project overview and setup guide
```

## Backend tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v
```

The current suite contains **172 tests**. It covers schema validation, deterministic
prioritization, PDF extraction, offline document and emergency reasoning, local JWT auth,
DynamoDB type handling, reminder sweeps, conflict detection, uploads, per-user data
isolation, and the on-device OCR execution modes (`cpu`, `auto`, `qnn`). The OCR-specific
tests need `pip install -r requirements-snapdragon.txt` and skip cleanly without it. The suite uses `moto` and does not require Docker, LocalStack, or an AWS account.

## Deploy to real AWS

The local workflow and production deployment are intentionally different service paths.
For a real deployment:

1. Request access to the configured Amazon Bedrock model in the target AWS Region.
2. Build and deploy the SAM application:

   ```bash
   cd infrastructure
   sam build
   sam deploy --guided
   ```

3. Configure `frontend/.env` with the deployed API Gateway URL and Cognito outputs, then
   build the frontend.
4. Connect the repository to AWS Amplify Hosting using
   [`infrastructure/amplify.yml`](infrastructure/amplify.yml).
5. Set the SAM `AllowedOrigin` parameter to the deployed Amplify domain.

See [`docs/architecture.md`](docs/architecture.md) and
[`docs/aws-services.md`](docs/aws-services.md) for the request flows and service roles.

## Documentation

- [`docs/snapdragon-optimization.md`](docs/snapdragon-optimization.md) — Snapdragon OCR modes, setup, and verification status
- [`docs/local-development.md`](docs/local-development.md) — local service map and networking
- [`docs/architecture.md`](docs/architecture.md) — request flows, data model, and security
- [`docs/aws-services.md`](docs/aws-services.md) — AWS service choices
- [`docs/deployment-checklist.md`](docs/deployment-checklist.md) — real AWS deployment steps
- [`docs/demo-flow.md`](docs/demo-flow.md) — submission demo script
- [`docs/limitations.md`](docs/limitations.md) — current boundaries and risks
- [`docs/future-improvements.md`](docs/future-improvements.md) — possible next steps

## Scope and safety

LifeLine is an organizational and decision-support tool. It does not diagnose medical
conditions, provide treatment advice, move money, or autonomously contact anyone. It
prepares information and next steps for a human to review and act on. These constraints
are enforced in both the reasoning layer and the deterministic validation step described
in [`backend/handlers/emergency.py`](backend/handlers/emergency.py).
