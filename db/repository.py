"""User-scoped repository layer over Postgres.

This is the multi-tenant replacement for storage/sheet_client.py. Every
function that touches a per-user table takes a user_id and scopes its query
accordingly -- there is no function in this module that can read or write
another tenant's row by accident, because the WHERE clause is baked into the
query itself rather than checked after the fact.

Design notes:
- Functions return plain dicts (not ORM objects) so callers don't need a live
  session to touch the data afterward, and so this can be a drop-in read
  shape for skills/API code migrating off sheet_client.py's dict-based
  interface later (Phase 3+).
- Lookups scoped to a specific user (get_lead, update_lead, delete_lead) filter
  by (id, user_id) in a single query. A row that exists but belongs to another
  user is treated identically to a row that doesn't exist at all (raises/returns
  the same not-found result) -- this avoids leaking existence of other tenants'
  data through a different error shape.
- Every write raises loudly on a missing/invalid required field or an unknown
  field name, per the project's "never silently skip" discipline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import (
    Company,
    DemoBuild,
    DemoUsageDaily,
    EnrichmentCache,
    GmailAccount,
    Job,
    Lead,
    Notification,
    PipelineRun,
    ResearchCache,
    Resume,
    SearchCriteria,
    Subscription,
    UsageCounter,
    User,
)
from db.session import get_session


class NotFoundError(Exception):
    """Raised when a requested row doesn't exist, or exists but is owned by
    a different tenant. Deliberately used for both cases (see module docstring).
    """


class DuplicateLeadError(Exception):
    """Raised when add_lead would create a duplicate (company, role) for a user."""


class ValidationError(Exception):
    """Raised on a missing/invalid required field or an unknown field name."""


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _to_dict(obj) -> dict:
    """Serialize a mapped ORM object to a plain dict of column values."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _is_valid_uuid(value: str) -> bool:
    """True if value parses as a UUID.

    All primary/foreign keys in db.models are UUID columns. A malformed id
    (e.g. an old Sheets-era hex string, a typo, an unrelated string a
    caller passed through) would otherwise reach Postgres as a raw
    ::UUID cast and blow up with a DataError -- a 500, not the clean
    "not found" every lookup-by-id function in this module is documented
    to return for a row that doesn't exist. Checking here lets callers
    (get_lead, update_lead, delete_lead) treat "malformed id" and
    "well-formed id, no matching row" identically, which is also what the
    tenant-isolation contract already promises for "exists but wrong
    tenant" -- one consistent not-found shape regardless of why the
    lookup failed.
    """
    import uuid as _uuid_module
    try:
        _uuid_module.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def create_user(firebase_uid: str, email: str, plan: str = "free") -> dict:
    if not firebase_uid or not email:
        raise ValidationError("create_user requires both firebase_uid and email")

    with get_session() as session:
        user = User(firebase_uid=firebase_uid, email=email, plan=plan)
        session.add(user)
        session.flush()
        return _to_dict(user)


def get_user(user_id: str) -> Optional[dict]:
    with get_session() as session:
        user = session.get(User, user_id)
        return _to_dict(user) if user else None


def get_user_by_firebase_uid(firebase_uid: str) -> Optional[dict]:
    with get_session() as session:
        user = session.scalar(select(User).where(User.firebase_uid == firebase_uid))
        return _to_dict(user) if user else None


def get_or_create_user(firebase_uid: str, email: str, plan: str = "free") -> dict:
    existing = get_user_by_firebase_uid(firebase_uid)
    if existing:
        return existing
    return create_user(firebase_uid, email, plan)


# ---------------------------------------------------------------------------
# Leads (per-user, hard tenant isolation)
# ---------------------------------------------------------------------------

_LEAD_WRITABLE_FIELDS = {
    "job_id",
    "channel",
    "source",
    "company",
    "role",
    "jd_text",
    "x_handle",
    "contact_name",
    "contact_email",
    "status",
    "resume_version",
    "resume_version_id",
    "cover_note",
    "outreach_draft",
    "review_decision",
    "keyword_coverage",
    "applied_at",
    "sent_at",
    "replied_at",
    "last_checked",
    "failure_reason",
    "followup_count",
    "listing_url",
    "posted_date",
    "domain",
}


def add_lead(user_id: str, lead: dict) -> dict:
    """Create a lead for user_id. Raises DuplicateLeadError on a (company,
    role) collision (case-insensitive) or an x_handle collision for the
    same user. Raises ValidationError if neither company+role nor
    x_handle is present -- mirrors storage/sheet_client.py's add_lead
    validation rule, since scrapers (e.g. skills/scrape_x_leads.py) rely
    on X-sourced leads (no company/role, only x_handle) being valid.
    """
    if not user_id:
        raise ValidationError("add_lead requires a user_id")

    company = (lead.get("company") or "").strip()
    role = (lead.get("role") or "").strip()
    x_handle = (lead.get("x_handle") or "").strip()

    if not (company and role) and not x_handle:
        raise ValidationError("A lead requires either 'company' and 'role', or an 'x_handle'.")

    with get_session() as session:
        # Case-insensitive existence check within this tenant only.
        dup = None
        if company and role:
            dup = session.scalar(
                select(Lead).where(
                    Lead.user_id == user_id,
                    func.lower(Lead.company) == _norm(company),
                    func.lower(Lead.role) == _norm(role),
                )
            )
        if dup is None and x_handle:
            dup = session.scalar(
                select(Lead).where(
                    Lead.user_id == user_id,
                    func.lower(Lead.x_handle) == _norm(x_handle),
                )
            )
        if dup is not None:
            raise DuplicateLeadError(
                f"Lead already exists for user {user_id}: {company or x_handle} - {role}"
            )

        new_lead = Lead(
            user_id=user_id,
            job_id=lead.get("job_id"),
            channel=lead.get("channel") or [],
            source=lead.get("source"),
            company=company or None,
            role=role or None,
            jd_text=lead.get("jd_text"),
            x_handle=x_handle or None,
            contact_name=lead.get("contact_name"),
            contact_email=lead.get("contact_email"),
            status=lead.get("status") or "matched",
            listing_url=lead.get("listing_url"),
            posted_date=lead.get("posted_date"),
            domain=lead.get("domain"),
        )
        session.add(new_lead)
        session.flush()
        return _to_dict(new_lead)


def try_add_lead(user_id: str, lead: dict) -> Optional[dict]:
    """Like add_lead, but returns None on a duplicate instead of raising.

    This matches storage/sheet_client.py's add_lead() return contract
    (True if added, False if skipped as a duplicate), which every scraper
    (skills/scrape_job_boards/*.py, skills/scrape_x_leads.py) is written
    against as "if added: count else: skip" -- a duplicate during a scrape
    run is an expected, routine outcome, not a failure worth raising for.
    Use add_lead directly wherever a duplicate should be treated as an error
    (e.g. an explicit user-initiated "add this lead" action).
    """
    try:
        return add_lead(user_id, lead)
    except DuplicateLeadError:
        return None


def get_lead(user_id: str, lead_id: str) -> Optional[dict]:
    """Fetch a single lead, scoped to user_id. Returns None if it doesn't
    exist, belongs to a different tenant, or lead_id isn't even a
    well-formed UUID -- all three are indistinguishable by design.
    """
    if not _is_valid_uuid(lead_id):
        return None

    with get_session() as session:
        lead = session.scalar(
            select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        )
        return _to_dict(lead) if lead else None


def get_leads(user_id: str, status: Optional[str] = None) -> list[dict]:
    """Return all leads for user_id, optionally filtered by status."""
    with get_session() as session:
        stmt = select(Lead).where(Lead.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Lead.status == status)
        stmt = stmt.order_by(Lead.created_at.desc())
        leads = session.scalars(stmt).all()
        return [_to_dict(lead) for lead in leads]


def update_lead(user_id: str, lead_id: str, fields: dict) -> dict:
    """Update named fields on a lead, scoped to user_id.

    Raises NotFoundError if the lead doesn't exist or belongs to another
    tenant (same error either way -- no existence leak). Raises
    ValidationError if an unknown field name is passed.
    """
    unknown = set(fields) - _LEAD_WRITABLE_FIELDS
    if unknown:
        raise ValidationError(f"Unknown lead field(s): {sorted(unknown)}")

    if not _is_valid_uuid(lead_id):
        raise NotFoundError(f"No lead found with id {lead_id} for this user")

    with get_session() as session:
        lead = session.scalar(
            select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        )
        if lead is None:
            raise NotFoundError(f"No lead found with id {lead_id} for this user")

        for field_name, value in fields.items():
            setattr(lead, field_name, value)

        session.flush()
        return _to_dict(lead)


def delete_lead(user_id: str, lead_id: str) -> bool:
    """Delete a lead scoped to user_id. Returns True if deleted, False if
    it didn't exist, belonged to another tenant, or lead_id wasn't even a
    well-formed UUID.
    """
    if not _is_valid_uuid(lead_id):
        return False

    with get_session() as session:
        lead = session.scalar(
            select(Lead).where(Lead.id == lead_id, Lead.user_id == user_id)
        )
        if lead is None:
            return False
        session.delete(lead)
        return True


# ---------------------------------------------------------------------------
# Search criteria (per-user)
# ---------------------------------------------------------------------------


def upsert_search_criteria(user_id: str, criteria: dict) -> dict:
    with get_session() as session:
        existing = session.scalar(
            select(SearchCriteria).where(SearchCriteria.user_id == user_id)
        )
        if existing:
            for key in ("roles", "tech_stack", "seniority", "locations", "remote_pref", "inferred_from_resume"):
                if key in criteria:
                    setattr(existing, key, criteria[key])
            session.flush()
            return _to_dict(existing)

        new_criteria = SearchCriteria(
            user_id=user_id,
            roles=criteria.get("roles") or [],
            tech_stack=criteria.get("tech_stack") or [],
            seniority=criteria.get("seniority"),
            locations=criteria.get("locations") or [],
            remote_pref=criteria.get("remote_pref"),
            inferred_from_resume=criteria.get("inferred_from_resume", False),
        )
        session.add(new_criteria)
        session.flush()
        return _to_dict(new_criteria)


def get_search_criteria(user_id: str) -> Optional[dict]:
    with get_session() as session:
        criteria = session.scalar(
            select(SearchCriteria).where(SearchCriteria.user_id == user_id)
        )
        return _to_dict(criteria) if criteria else None


# ---------------------------------------------------------------------------
# Resumes (per-user)
# ---------------------------------------------------------------------------


def add_resume(user_id: str, file_ref: str, parsed_json: Optional[dict] = None, is_primary: bool = False) -> dict:
    with get_session() as session:
        if is_primary:
            # Only one primary resume per user -- demote any existing ones.
            session.query(Resume).filter(
                Resume.user_id == user_id, Resume.is_primary.is_(True)
            ).update({"is_primary": False})

        resume = Resume(user_id=user_id, file_ref=file_ref, parsed_json=parsed_json, is_primary=is_primary)
        session.add(resume)
        session.flush()
        return _to_dict(resume)


def get_resumes(user_id: str) -> list[dict]:
    with get_session() as session:
        resumes = session.scalars(
            select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc())
        ).all()
        return [_to_dict(r) for r in resumes]


def get_resume(user_id: str, resume_id: str) -> Optional[dict]:
    with get_session() as session:
        resume = session.scalar(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        )
        return _to_dict(resume) if resume else None


# ---------------------------------------------------------------------------
# Usage counters (per-user; free-tier 15-lead-lifetime cap lives here in Phase 7)
# ---------------------------------------------------------------------------


def get_or_create_usage_counter(user_id: str, period: str = "lifetime") -> dict:
    with get_session() as session:
        counter = session.scalar(
            select(UsageCounter).where(
                UsageCounter.user_id == user_id, UsageCounter.period == period
            )
        )
        if counter:
            return _to_dict(counter)

        counter = UsageCounter(user_id=user_id, period=period, leads_used=0, enrichments_used=0)
        session.add(counter)
        session.flush()
        return _to_dict(counter)


def increment_usage(user_id: str, period: str = "lifetime", leads_delta: int = 0, enrichments_delta: int = 0) -> dict:
    with get_session() as session:
        counter = session.scalar(
            select(UsageCounter).where(
                UsageCounter.user_id == user_id, UsageCounter.period == period
            )
        )
        if counter is None:
            counter = UsageCounter(user_id=user_id, period=period, leads_used=0, enrichments_used=0)
            session.add(counter)
            session.flush()

        counter.leads_used += leads_delta
        counter.enrichments_used += enrichments_delta
        session.flush()
        return _to_dict(counter)


# ---------------------------------------------------------------------------
# Notifications (per-user)
# ---------------------------------------------------------------------------


def add_notification(user_id: str, type_: str, payload: Optional[dict] = None) -> dict:
    if not type_:
        raise ValidationError("add_notification requires a type")
    with get_session() as session:
        note = Notification(user_id=user_id, type=type_, payload=payload)
        session.add(note)
        session.flush()
        return _to_dict(note)


def get_notifications(user_id: str, unread_only: bool = False) -> list[dict]:
    with get_session() as session:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        stmt = stmt.order_by(Notification.created_at.desc())
        notes = session.scalars(stmt).all()
        return [_to_dict(n) for n in notes]


def mark_notification_read(user_id: str, notification_id: str) -> dict:
    with get_session() as session:
        note = session.scalar(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        if note is None:
            raise NotFoundError(f"No notification found with id {notification_id} for this user")
        note.read_at = datetime.now(timezone.utc)
        session.flush()
        return _to_dict(note)


# ---------------------------------------------------------------------------
# Pipeline runs (per-user; Phase 4.4 -- replaces api/main.py's single global
# _pipeline_run_state dict so two users' on-demand pipeline runs don't
# collide, and so run status survives an API process restart/replica swap)
# ---------------------------------------------------------------------------


def create_pipeline_run(user_id: str) -> dict:
    """Start tracking a new pipeline run for user_id. Returns the new row."""
    if not user_id:
        raise ValidationError("create_pipeline_run requires a user_id")

    with get_session() as session:
        run = PipelineRun(user_id=user_id, status="running", steps=[])
        session.add(run)
        session.flush()
        return _to_dict(run)


def get_latest_pipeline_run(user_id: str) -> Optional[dict]:
    """Return user_id's most recently started pipeline run (running or
    finished), or None if they've never triggered one. This is what
    /api/pipeline/run-status reads -- "the current/last run for this
    caller", not a global.
    """
    with get_session() as session:
        run = session.scalar(
            select(PipelineRun)
            .where(PipelineRun.user_id == user_id)
            .order_by(PipelineRun.started_at.desc())
        )
        return _to_dict(run) if run else None


def get_running_pipeline_run(user_id: str) -> Optional[dict]:
    """Return user_id's currently-running pipeline run, or None. Used to
    enforce "one run at a time per user" (the 409 check) without a global
    lock -- two different users' runs never contend with each other here.
    """
    with get_session() as session:
        run = session.scalar(
            select(PipelineRun)
            .where(PipelineRun.user_id == user_id, PipelineRun.status == "running")
            .order_by(PipelineRun.started_at.desc())
        )
        return _to_dict(run) if run else None


def update_pipeline_run(run_id: str, fields: dict) -> dict:
    """Update a pipeline run row by its own id (not user-scoped in the
    query, since the background thread that calls this already knows
    exactly which run_id it started and isn't taking it from an untrusted
    caller -- unlike every user-facing repo function above, there's no
    "which tenant is asking" ambiguity to guard against here).
    """
    with get_session() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise NotFoundError(f"No pipeline run found with id {run_id}")
        for key, value in fields.items():
            setattr(run, key, value)
        session.flush()
        return _to_dict(run)


def append_pipeline_run_step(run_id: str, step: str, status: str) -> dict:
    """Append one {step, status} entry to a run's steps list and update
    current_step -- mirrors api/main.py's old on_step callback, now
    writing to Postgres instead of an in-memory dict.
    """
    with get_session() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise NotFoundError(f"No pipeline run found with id {run_id}")
        run.current_step = step if status == "running" else None
        if status in ("ok", "error"):
            run.steps = [*(run.steps or []), {"step": step, "status": status}]
        session.flush()
        return _to_dict(run)


# ---------------------------------------------------------------------------
# Gmail accounts (per-user)
# ---------------------------------------------------------------------------


def upsert_gmail_account(user_id: str, email: str, encrypted_refresh_token: str, scopes: list[str]) -> dict:
    if not email or not encrypted_refresh_token:
        raise ValidationError("upsert_gmail_account requires email and encrypted_refresh_token")

    with get_session() as session:
        existing = session.scalar(
            select(GmailAccount).where(
                GmailAccount.user_id == user_id, GmailAccount.email == email
            )
        )
        if existing:
            existing.encrypted_refresh_token = encrypted_refresh_token
            existing.scopes = scopes
            session.flush()
            return _to_dict(existing)

        account = GmailAccount(
            user_id=user_id, email=email,
            encrypted_refresh_token=encrypted_refresh_token, scopes=scopes,
        )
        session.add(account)
        session.flush()
        return _to_dict(account)


def get_gmail_accounts(user_id: str) -> list[dict]:
    with get_session() as session:
        accounts = session.scalars(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        ).all()
        return [_to_dict(a) for a in accounts]


# ---------------------------------------------------------------------------
# Subscriptions (per-user)
# ---------------------------------------------------------------------------


def upsert_subscription(user_id: str, plan: str, status: str = "active", provider_sub_id: Optional[str] = None, period_end=None) -> dict:
    with get_session() as session:
        existing = session.scalar(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        if existing:
            existing.plan = plan
            existing.status = status
            existing.provider_sub_id = provider_sub_id
            existing.period_end = period_end
            session.flush()
            return _to_dict(existing)

        sub = Subscription(
            user_id=user_id, plan=plan, status=status,
            provider_sub_id=provider_sub_id, period_end=period_end,
        )
        session.add(sub)
        session.flush()
        return _to_dict(sub)


def get_subscription(user_id: str) -> Optional[dict]:
    with get_session() as session:
        sub = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
        return _to_dict(sub) if sub else None


# ---------------------------------------------------------------------------
# Shared catalog: companies + jobs (no user scoping -- shared across tenants)
# ---------------------------------------------------------------------------


def get_or_create_company(name: str, domain: Optional[str] = None, ats_type: Optional[str] = None, ats_token: Optional[str] = None) -> dict:
    if not name:
        raise ValidationError("get_or_create_company requires a name")

    with get_session() as session:
        existing = None
        if ats_type and ats_token:
            existing = session.scalar(
                select(Company).where(Company.ats_type == ats_type, Company.ats_token == ats_token)
            )
        if existing is None and domain:
            existing = session.scalar(select(Company).where(Company.domain == domain))

        if existing:
            return _to_dict(existing)

        company = Company(name=name, domain=domain, ats_type=ats_type, ats_token=ats_token)
        session.add(company)
        session.flush()
        return _to_dict(company)


def mark_company_scraped(company_id: str) -> None:
    """Stamp last_scraped_at=now on a company. Called by each ATS connector
    after it finishes syncing a company's jobs, so a future catalog-refresh
    job can tell which companies are stale without re-deriving that from
    the jobs table's own updated_at timestamps.
    """
    with get_session() as session:
        company = session.get(Company, company_id)
        if company is not None:
            company.last_scraped_at = datetime.now(timezone.utc)
            session.flush()


def add_job(company_id: str, source: str, external_id: str, title: str, **kwargs) -> Optional[dict]:
    """Add a job, deduped on (company_id, external_id). Returns None if the
    job already exists (idempotent re-scrape), the dict otherwise.

    Every call -- whether it inserts a new row or hits the dedup path on
    an already-known job -- stamps last_seen_at=now() and is_open=True on
    that job. This is what makes "still open" a real signal instead of a
    one-time guess: a job only keeps a fresh last_seen_at/is_open=True by
    genuinely showing up in the company's live board API again on a
    later sync. See close_unseen_jobs() below for the other half (closing
    jobs that stopped showing up).
    """
    if not (company_id and source and external_id and title):
        raise ValidationError("add_job requires company_id, source, external_id, and title")

    now = datetime.now(timezone.utc)

    with get_session() as session:
        existing = session.scalar(
            select(Job).where(Job.company_id == company_id, Job.external_id == external_id)
        )
        if existing:
            existing.last_seen_at = now
            existing.is_open = True
            session.flush()
            return None

        job = Job(
            company_id=company_id,
            source=source,
            external_id=external_id,
            title=title,
            location=kwargs.get("location"),
            department=kwargs.get("department"),
            jd_text=kwargs.get("jd_text"),
            apply_url=kwargs.get("apply_url"),
            posted_at=kwargs.get("posted_at"),
            last_seen_at=now,
            is_open=True,
        )
        session.add(job)
        session.flush()
        return _to_dict(job)


def close_unseen_jobs(company_id: str, seen_external_ids: set[str]) -> int:
    """After a full sync of one company's board, mark every job for that
    company NOT in seen_external_ids as closed (is_open=False) -- the
    company's own live API just returned the current full set of open
    postings, so anything previously in our catalog but absent from that
    response has been filled or pulled.

    Only touches jobs that are currently is_open=True (a job already
    marked closed stays closed; this never "reopens" anything -- that
    only happens via add_job's dedup path seeing it again for real).

    Returns the number of jobs newly marked closed.
    """
    with get_session() as session:
        stmt = select(Job).where(Job.company_id == company_id, Job.is_open.is_(True))
        candidates = session.scalars(stmt).all()

        closed = 0
        for job in candidates:
            if job.external_id not in seen_external_ids:
                job.is_open = False
                closed += 1

        if closed:
            session.flush()
        return closed


def get_jobs(company_id: Optional[str] = None, open_only: bool = False) -> list[dict]:
    """Return catalog jobs, optionally scoped to one company and/or
    filtered to only currently-open ones (is_open=True -- see add_job's
    docstring for how that flag stays accurate).

    open_only defaults to False so existing internal call sites (ATS
    connector tests, prioritize_tokens' bookkeeping) keep seeing every
    row unchanged; user-facing matching (skills/match_jobs.py's callers)
    should pass open_only=True.
    """
    with get_session() as session:
        stmt = select(Job)
        if company_id:
            stmt = stmt.where(Job.company_id == company_id)
        if open_only:
            stmt = stmt.where(Job.is_open.is_(True))
        jobs = session.scalars(stmt).all()
        return [_to_dict(j) for j in jobs]


def get_job_with_company(job_id: str) -> Optional[dict]:
    """Fetch a single catalog job plus its company name, for the
    job-to-lead conversion path (Phase 5.3's save-job route) -- the same
    join api/main.py's anon_tailored_preview already does inline, pulled
    out here so it's reusable instead of duplicated a second time.

    Returns None if job_id doesn't exist or isn't a well-formed UUID
    (same "malformed id is indistinguishable from not found" convention
    every other id-scoped lookup in this module follows).
    """
    if not _is_valid_uuid(job_id):
        return None

    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        company = session.get(Company, job.company_id)
        job_dict = _to_dict(job)
        job_dict["company_name"] = company.name if company else None
        return job_dict


def get_companies_by_ats_type(ats_type: str) -> list[dict]:
    """Return every company already in the catalog for one ATS provider.

    Used by the ATS connectors (skills/scrape_job_boards/{greenhouse,lever,
    ashby}.py) to prioritize a catalog-refresh run: tokens with no
    matching row here have never been synced (highest priority), and
    tokens that do have a row are sorted by last_scraped_at so the
    stalest ones get refreshed first. With thousands of seed tokens and a
    per-run cap, this is what lets repeated scheduled runs make steady
    progress across the whole list instead of only ever touching
    whichever companies sort first alphabetically.
    """
    with get_session() as session:
        companies = session.scalars(
            select(Company).where(Company.ats_type == ats_type)
        ).all()
        return [_to_dict(c) for c in companies]


# ---------------------------------------------------------------------------
# Shared caches: enrichment + research (keyed by domain/job, not user)
# ---------------------------------------------------------------------------


def get_cached_enrichment(domain: str, provider: str) -> Optional[dict]:
    with get_session() as session:
        cached = session.scalar(
            select(EnrichmentCache).where(
                EnrichmentCache.domain == domain, EnrichmentCache.provider == provider
            )
        )
        return _to_dict(cached) if cached else None


def set_cached_enrichment(domain: str, provider: str, result_json: dict) -> dict:
    with get_session() as session:
        existing = session.scalar(
            select(EnrichmentCache).where(
                EnrichmentCache.domain == domain, EnrichmentCache.provider == provider
            )
        )
        if existing:
            existing.result_json = result_json
            existing.fetched_at = datetime.now(timezone.utc)
            session.flush()
            return _to_dict(existing)

        cache_row = EnrichmentCache(domain=domain, provider=provider, result_json=result_json)
        session.add(cache_row)
        session.flush()
        return _to_dict(cache_row)


def get_cached_research(job_id: str) -> Optional[dict]:
    with get_session() as session:
        cached = session.scalar(select(ResearchCache).where(ResearchCache.job_id == job_id))
        return _to_dict(cached) if cached else None


def set_cached_research(job_id: str, result_json: dict) -> dict:
    with get_session() as session:
        existing = session.scalar(select(ResearchCache).where(ResearchCache.job_id == job_id))
        if existing:
            existing.result_json = result_json
            session.flush()
            return _to_dict(existing)

        cache_row = ResearchCache(job_id=job_id, result_json=result_json)
        session.add(cache_row)
        session.flush()
        return _to_dict(cache_row)


# ---------------------------------------------------------------------------
# Gmail accounts (per-user OAuth, Task 5) -- one connected Gmail per user in
# v1. Stores an ENCRYPTED refresh token (never a plaintext token) plus the
# user's send preference ("draft" | "direct").
# ---------------------------------------------------------------------------


def get_gmail_account(user_id: str) -> Optional[dict]:
    """Return the user's connected Gmail account (or None). Scoped by
    user_id -- another tenant's row is invisible here, same discipline as
    every other per-user lookup."""
    with get_session() as session:
        acct = session.scalar(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        )
        return _to_dict(acct) if acct else None


def upsert_gmail_account(
    user_id: str,
    email: str,
    encrypted_refresh_token: str,
    scopes: Optional[list] = None,
    send_mode: str = "draft",
) -> dict:
    """Create or update the user's connected Gmail account.

    v1 keeps a single Gmail per user: if the user reconnects (same or a
    different Google account), the existing row is updated in place rather
    than creating a second one. send_mode is preserved across a reconnect
    only when not explicitly changed by the caller.
    """
    if not user_id:
        raise ValidationError("upsert_gmail_account requires a user_id")
    if not email:
        raise ValidationError("upsert_gmail_account requires an email")
    if not encrypted_refresh_token:
        raise ValidationError("upsert_gmail_account requires an encrypted_refresh_token")
    if send_mode not in ("draft", "direct"):
        raise ValidationError(f"invalid send_mode: {send_mode!r} (expected 'draft' or 'direct')")

    with get_session() as session:
        acct = session.scalar(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        )
        if acct:
            acct.email = email
            acct.encrypted_refresh_token = encrypted_refresh_token
            acct.scopes = scopes or []
            acct.send_mode = send_mode
            session.flush()
            return _to_dict(acct)

        acct = GmailAccount(
            user_id=user_id,
            email=email,
            encrypted_refresh_token=encrypted_refresh_token,
            scopes=scopes or [],
            send_mode=send_mode,
        )
        session.add(acct)
        session.flush()
        return _to_dict(acct)


def update_gmail_send_mode(user_id: str, send_mode: str) -> dict:
    """Update just the send preference for the user's connected Gmail."""
    if send_mode not in ("draft", "direct"):
        raise ValidationError(f"invalid send_mode: {send_mode!r} (expected 'draft' or 'direct')")
    with get_session() as session:
        acct = session.scalar(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        )
        if not acct:
            raise NotFoundError("No connected Gmail account for this user")
        acct.send_mode = send_mode
        session.flush()
        return _to_dict(acct)


def delete_gmail_account(user_id: str) -> bool:
    """Disconnect the user's Gmail. Returns True if a row was removed."""
    with get_session() as session:
        acct = session.scalar(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        )
        if not acct:
            return False
        session.delete(acct)
        return True


def get_companies() -> list[dict]:
    """Return all shared companies across all tenants."""
    with get_session() as session:
        rows = session.scalars(select(Company)).all()
        return [_to_dict(r) for r in rows]


def get_jobs(open_only: bool = False) -> list[dict]:
    """Return all shared jobs across all tenants."""
    with get_session() as session:
        stmt = select(Job)
        if open_only:
            stmt = stmt.where(Job.is_open.is_(True))
        rows = session.scalars(stmt).all()
        return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Demo Build & Rate Limit Repository Methods
# ---------------------------------------------------------------------------

def check_and_increment_demo_quota(user_id: str, max_daily: int = 5) -> bool:
    """Atomically check and increment user's daily demo creation quota.

    Returns True if allowed (count <= max_daily), False if limit reached.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_session() as session:
        usage = session.scalar(
            select(DemoUsageDaily).where(
                DemoUsageDaily.user_id == user_id,
                DemoUsageDaily.usage_date == today_str,
            )
        )
        if not usage:
            usage = DemoUsageDaily(user_id=user_id, usage_date=today_str, count=1)
            session.add(usage)
            session.flush()
            return True

        if usage.count >= max_daily:
            return False

        usage.count += 1
        session.flush()
        return True


def get_daily_demo_usage(user_id: str, max_daily: int = 5) -> dict:
    """Return today's demo usage stats for user."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_session() as session:
        usage = session.scalar(
            select(DemoUsageDaily).where(
                DemoUsageDaily.user_id == user_id,
                DemoUsageDaily.usage_date == today_str,
            )
        )
        used = usage.count if usage else 0
        return {
            "date": today_str,
            "used": used,
            "limit": max_daily,
            "remaining": max(0, max_daily - used),
        }


def create_demo_build(
    user_id: str,
    build_id: str,
    title: str,
    company_name: Optional[str] = None,
    project_type: str = "fullstack",
    spec_json: Optional[dict] = None,
) -> dict:
    """Create a new DemoBuild tracking row for user."""
    with get_session() as session:
        demo = DemoBuild(
            user_id=user_id,
            build_id=build_id,
            title=title,
            company_name=company_name,
            project_type=project_type,
            spec_json=spec_json or {},
            stage="pending",
            deploy_stage="exporting",
            turn_count=1,
            refinements=[],
        )
        session.add(demo)
        session.flush()
        return _to_dict(demo)


def get_demo_build(user_id: str, build_id: str) -> dict:
    """Get a specific DemoBuild row scoped to user_id."""
    with get_session() as session:
        demo = session.scalar(
            select(DemoBuild).where(
                DemoBuild.user_id == user_id,
                DemoBuild.build_id == build_id,
            )
        )
        if not demo:
            raise NotFoundError(f"No demo build found with build_id: {build_id!r}")
        return _to_dict(demo)


def update_demo_build_status(user_id: str, build_id: str, **fields) -> dict:
    """Update fields on a DemoBuild row scoped to user_id."""
    with get_session() as session:
        demo = session.scalar(
            select(DemoBuild).where(
                DemoBuild.user_id == user_id,
                DemoBuild.build_id == build_id,
            )
        )
        if not demo:
            raise NotFoundError(f"No demo build found with build_id: {build_id!r}")

        for key, value in fields.items():
            if hasattr(demo, key):
                setattr(demo, key, value)

        demo.updated_at = datetime.now(timezone.utc)
        session.flush()
        return _to_dict(demo)


def add_refinement_turn(user_id: str, build_id: str, prompt: str, stage: str = "building") -> dict:
    """Append a refinement prompt turn to a DemoBuild."""
    with get_session() as session:
        demo = session.scalar(
            select(DemoBuild).where(
                DemoBuild.user_id == user_id,
                DemoBuild.build_id == build_id,
            )
        )
        if not demo:
            raise NotFoundError(f"No demo build found with build_id: {build_id!r}")

        refinements = list(demo.refinements or [])
        refinements.append({
            "prompt": prompt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
        })
        demo.refinements = refinements
        demo.turn_count = (demo.turn_count or 1) + 1
        demo.stage = stage
        demo.updated_at = datetime.now(timezone.utc)
        session.flush()
        return _to_dict(demo)


def list_user_demo_builds(user_id: str, limit: int = 20) -> list[dict]:
    """List recent demo builds for a tenant."""
    with get_session() as session:
        rows = session.scalars(
            select(DemoBuild)
            .where(DemoBuild.user_id == user_id)
            .order_by(DemoBuild.created_at.desc())
            .limit(limit)
        ).all()
        return [_to_dict(r) for r in rows]


def get_user_provider_keys(user_id: str) -> dict:
    """Retrieve saved provider keys (GitHub, Vercel, Render) for user."""
    with get_session() as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if not user:
            raise NotFoundError(f"User not found: {user_id}")
        return {
            "github_token": user.github_token,
            "vercel_token": user.vercel_token,
            "render_api_key": user.render_api_key,
        }


def update_user_provider_keys(
    user_id: str,
    github_token: Optional[str] = None,
    vercel_token: Optional[str] = None,
    render_api_key: Optional[str] = None,
) -> dict:
    """Update saved provider keys for user."""
    with get_session() as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if not user:
            raise NotFoundError(f"User not found: {user_id}")

        if github_token is not None:
            user.github_token = github_token.strip() or None
        if vercel_token is not None:
            user.vercel_token = vercel_token.strip() or None
        if render_api_key is not None:
            user.render_api_key = render_api_key.strip() or None

        session.flush()
        return {
            "github_token": user.github_token,
            "vercel_token": user.vercel_token,
            "render_api_key": user.render_api_key,
        }


