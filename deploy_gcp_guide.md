# Complete Google Cloud Console (GCP) SaaS Deployment Guide

This guide details step-by-step instructions to deploy `Auto_Job_apply` on Google Cloud Console using Google Cloud Run, Cloud SQL PostgreSQL, Secret Manager, Artifact Registry, and Cloud Scheduler.

---

## Architecture Overview

- **Cloud SQL PostgreSQL**: Multi-tenant database storing user accounts, search criteria, leads, email drafts, and shared company/job catalog.
- **Cloud Run (API Service)**: FastAPI application providing public anonymous resume hook, authentication, dashboard API, and catalog matching endpoints.
- **Cloud Run (Worker Service)**: Task processor for background LangGraph execution & async enrichment.
- **Cloud Run (Frontend)**: Next.js SaaS dashboard user interface.
- **Secret Manager**: Secure environment variable storage for LLM API keys (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`), database credentials, and OAuth tokens.
- **Cloud Scheduler**: Cron jobs for daily job catalog refresh & outreach follow-up checks.

---

## 1. Prerequisites & Environment Setup

Run the following commands in your local shell (or Cloud Shell) with `gcloud` CLI installed:

```bash
# 1. Login and set active GCP Project ID
gcloud auth login
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
gcloud config set project $PROJECT_ID
gcloud config set run/region $REGION

# 2. Enable required GCP API services
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  vpcaccess.googleapis.com
```

---

## 2. Artifact Registry Setup

Create a Docker repository to store API, Worker, and Frontend images:

```bash
gcloud artifacts repositories create autoapply-repo \
  --repository-format=docker \
  --location=$REGION \
  --description="Auto Job Apply Container Repository"
```

---

## 3. Cloud SQL PostgreSQL Instance Setup

Create a Cloud SQL PostgreSQL instance and set up application database & credentials:

```bash
# 1. Create Cloud SQL PostgreSQL instance
gcloud sql instances create autoapply-db \
  --database-version=POSTGRES_16 \
  --cpu=2 \
  --memory=7.5GiB \
  --region=$REGION \
  --root-password="REPLACE_WITH_SECURE_ROOT_PASSWORD"

# 2. Create autoapply user and database
gcloud sql users create autoapply \
  --instance=autoapply-db \
  --password="REPLACE_WITH_SECURE_PASSWORD"

gcloud sql databases create autoapply \
  --instance=autoapply-db

# 3. Obtain Instance Connection Name (format: PROJECT_ID:REGION:INSTANCE_NAME)
export INSTANCE_CONNECTION_NAME=$(gcloud sql instances describe autoapply-db --format="value(connectionName)")
echo "Connection Name: $INSTANCE_CONNECTION_NAME"
```

---

## 4. Secret Manager Configuration

Store secrets safely in Secret Manager:

```bash
# Database URL secret (using unix socket connection for Cloud Run Cloud SQL connector)
gcloud secrets create DATABASE_URL --replication-policy="automatic"
echo -n "postgresql+psycopg2://autoapply:REPLACE_WITH_SECURE_PASSWORD@/autoapply?host=/cloudsql/$INSTANCE_CONNECTION_NAME" | \
  gcloud secrets versions add DATABASE_URL --data-file=-

# Gemini API Key
gcloud secrets create GEMINI_API_KEY --replication-policy="automatic"
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets versions add GEMINI_API_KEY --data-file=-

# Worker Secret Token
gcloud secrets create WORKER_SECRET --replication-policy="automatic"
echo -n "YOUR_WORKER_SECRET_TOKEN" | gcloud secrets versions add WORKER_SECRET --data-file=-
```

---

## 5. Building & Deploying Containers to Cloud Run

### A. Deploy API Service

```bash
# Build API image
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT_ID/autoapply-repo/api:latest -f docker/Dockerfile.api .

# Deploy to Cloud Run
gcloud run deploy autoapply-api \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/autoapply-repo/api:latest \
  --add-cloudsql-instances $INSTANCE_CONNECTION_NAME \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,WORKER_SECRET=WORKER_SECRET:latest" \
  --set-env-vars "MODEL_BACKEND=gemini,PORT=8000" \
  --allow-unauthenticated \
  --port 8000 \
  --cpu 1 --memory 1Gi \
  --min-instances 1 --max-instances 10
```

### B. Deploy Worker Service

```bash
# Build Worker image
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT_ID/autoapply-repo/worker:latest -f docker/Dockerfile.worker .

# Deploy Worker to Cloud Run
gcloud run deploy autoapply-worker \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/autoapply-repo/worker:latest \
  --add-cloudsql-instances $INSTANCE_CONNECTION_NAME \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,WORKER_SECRET=WORKER_SECRET:latest" \
  --set-env-vars "MODEL_BACKEND=gemini,PORT=8080" \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 --memory 1Gi
```

### C. Deploy Frontend Service

```bash
# Get public API Service URL
export API_URL=$(gcloud run services describe autoapply-api --format="value(status.url)")

# Build Frontend image
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT_ID/autoapply-repo/frontend:latest -f docker/Dockerfile.frontend .

# Deploy Frontend to Cloud Run
gcloud run deploy autoapply-frontend \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/autoapply-repo/frontend:latest \
  --set-env-vars "API_URL=$API_URL" \
  --allow-unauthenticated \
  --min-instances 1 \
  --port 3000
```

---

## 6. Database Migrations & Catalog Seeding

Run database schema migration and seed the 500-1000+ company catalog:

```bash
# Execute Database Migration & Catalog Seeding using ephemeral Cloud Run Job or Cloud Build
gcloud run jobs create autoapply-migrate \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/autoapply-repo/api:latest \
  --add-cloudsql-instances $INSTANCE_CONNECTION_NAME \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest" \
  --command "sh" \
  --args "-c","python -m alembic upgrade head && python -m db.seed_catalog --target 500"

gcloud run jobs execute autoapply-migrate --wait
```

---

## 7. Cloud Scheduler Cron Jobs Setup

Set up scheduled background triggers for Job Catalog Refresh and Outreach Follow-ups:

```bash
# 1. Catalog Refresh Cron (Runs daily at 2 AM)
gcloud scheduler jobs create http catalog-refresh-job \
  --schedule="0 2 * * *" \
  --uri="$API_URL/api/internal/catalog-refresh" \
  --http-method=POST \
  --time-zone="UTC"

# 2. Outreach Followup Check Cron (Runs daily at 9 AM)
gcloud scheduler jobs create http followups-check-job \
  --schedule="0 9 * * *" \
  --uri="$API_URL/api/internal/check-followups" \
  --http-method=POST \
  --time-zone="UTC"
```

---

## Verification & Health Check Checklist

- [ ] **API Liveness Probe**: Open `$API_URL/healthz` (returns HTTP 200 `{"status": "ok"}`).
- [ ] **API Readiness Probe**: Open `$API_URL/readiness` (verifies DB connection health).
- [ ] **Company Catalog Feed**: Query `$API_URL/api/anon/preview` or inspect DB count (`SELECT COUNT(*) FROM companies`).
- [ ] **Frontend Dashboard**: Open Frontend Cloud Run URL and verify resume upload & job matching workflow.

---

## 8. Google OAuth Connector Guidelines & 100 Test Users Cap

The Google Gmail connector relies on Google Cloud OAuth 2.0 (`https://mail.google.com/` scope for sending outreach).

### Important Testing Mode Constraints:
1. **Google OAuth Testing Status**: Until official Google Cloud App Verification is completed, the OAuth client status in Google Cloud Console is set to **Testing**.
2. **100 Test User Limit**: Google enforces a hard ceiling of **100 maximum test users** per unverified GCP OAuth project.

### Admin Guidelines for Managing Access:
- **Adding Authorized Users**: To authorize a user to sign in & connect Gmail, workspace admins must add their Google email address under:
  `Google Cloud Console -> APIs & Services -> OAuth consent screen -> Test users -> + ADD USERS`.
- **Propagation Wait Time (24–48 Hours)**: Users should be advised to wait up to **24–48 hours** after adding their email for Google OAuth test user authorization to fully propagate across Google accounts.
- **Handling Access Blocked Error**: If an unlisted Google account attempts authorization, Google blocks sign-in with:
  `"Access blocked: {App Name} has not completed the Google verification process"`.
  Adding their email address to the Test users list in GCP Console grants access once propagated.
- **Production Rollout**: For public deployment beyond 100 users, submit the app for **Google Verification** via the GCP OAuth consent screen tab (requires domain verification & privacy policy link).
