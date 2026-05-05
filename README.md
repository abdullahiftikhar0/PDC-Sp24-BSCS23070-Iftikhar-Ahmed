Muhammad Abdullah BSCS23070

# SecureAIApp / StudySync Resilience Assignment

This repo contains a FastAPI backend and React frontend. For the PDC assignment, Part 3 implements **Problem 2 (Coordination)**: a fault-tolerant Clerk webhook handler using an inbox table + idempotency + retries.

## Backend (FastAPI)

### Prereqs
- Python 3.11+

### Environment variables
Set these before running:
- `STUDENT_ID` (required for the submission header middleware)
- `CLERK_WEBHOOK_SECRET` (required for verifying Clerk/Svix webhooks)
- `CLERK_SECRET_KEY` and `JWT_KEY` (required for authenticated `/api/*` endpoints)
- `OPENAI_API_KEY` (only needed if you use the AI challenge generation endpoint)

Optional:
- `CLERK_WEBHOOK_VERIFY_SIGNATURE=false` (dev/testing only)
- `WEBHOOK_WORKER_ENABLED=false` (disable background worker; useful for deterministic tests)

### Install + run
From a PowerShell terminal:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install fastapi uvicorn sqlalchemy python-dotenv clerk-backend-api openai svix
python server.py
```

Backend listens on `http://localhost:8000`.

### Run the coordination fix tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

## Frontend (React)

```powershell
cd frontend
npm install
npm run dev
```

## Report (LaTeX)
The report source is in `report/report.tex`.

## Notes for grading
- Every API response includes `X-Student-ID: BSCS23070` via FastAPI middleware.
- The Clerk webhook endpoint is `POST /webhooks/clerk`.
