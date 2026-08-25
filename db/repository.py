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
    EnrichmentCache,
    GmailAccount,
    Job,
    Lead,
    Notification,
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
    "applied_at",
    "sent_at",
    "last_checked",
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
    """
    if not (company_id and source and external_id and title):
        raise ValidationError("add_job requires company_id, source, external_id, and title")

    with get_session() as session:
        existing = session.scalar(
            select(Job).where(Job.company_id == company_id, Job.external_id == external_id)
        )
        if existing:
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
        )
        session.add(job)
        session.flush()
        return _to_dict(job)


def get_jobs(company_id: Optional[str] = None) -> list[dict]:
    with get_session() as session:
        stmt = select(Job)
        if company_id:
            stmt = stmt.where(Job.company_id == company_id)
        jobs = session.scalars(stmt).all()
        return [_to_dict(j) for j in jobs]


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
