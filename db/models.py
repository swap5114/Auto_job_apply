"""SQLAlchemy ORM models for the multi-tenant Postgres store.

Replaces storage/sheet_client.py's Google Sheet as the system of record.
Two families of tables:

- Shared catalog (no user_id): companies, jobs. Scraped once, read by everyone.
- Per-user (user_id-scoped, hard tenant isolation): users, resumes,
  search_criteria, leads, gmail_accounts, subscriptions, usage_counters,
  notifications.
- Shared caches keyed by domain/job rather than by user, since enrichment and
  research results are reusable across users who happen to look at the same
  company/job: enrichment_cache, research_cache.

All per-user tables carry a user_id FK to users.id with ON DELETE CASCADE, so
deleting a user cleans up everything they own (relevant later for GDPR
delete in Phase 9). Every repository method that touches a per-user table
must filter by user_id -- that discipline is enforced in repository.py and
verified by the tenant-isolation test suite.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Shared catalog (Phase 1 territory, modeled now so migrations don't churn)
# ---------------------------------------------------------------------------


class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=True, index=True)
    ats_type = Column(String, nullable=True)  # greenhouse | lever | ashby | yc | other
    ats_token = Column(String, nullable=True)
    last_scraped_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    jobs = relationship("Job", back_populates="company", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("ats_type", "ats_token", name="uq_companies_ats_type_token"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id = Column(
        UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    source = Column(String, nullable=False)  # greenhouse | lever | ashby | yc
    external_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    location = Column(String, nullable=True)
    department = Column(String, nullable=True)
    jd_text = Column(Text, nullable=True)
    apply_url = Column(String, nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    # Freshness/still-open tracking (added after launch -- before this, a
    # job that got filled/pulled from the company's live board just sat in
    # the catalog forever, matchable, with a dead apply_url). Each ATS
    # connector's sync_company() stamps last_seen_at = now() on every job
    # its provider's API STILL returns on a given sync; add_job's dedup
    # path (existing job, same external_id) does the same stamp on the
    # re-scrape, not just on first insert. is_open flips to False the
    # moment a full sync of that company completes and a previously-seen
    # job's external_id did NOT show up in that sync's response --i.e. the
    # company's own board is the source of truth, this only reflects what
    # it just said.
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    is_open = Column(Boolean, nullable=False, default=True)

    company = relationship("Company", back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("company_id", "external_id", name="uq_jobs_company_external_id"),
        Index("ix_jobs_source", "source"),
        Index("ix_jobs_is_open", "is_open"),
    )


# ---------------------------------------------------------------------------
# Per-user tables (hard tenant isolation)
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    firebase_uid = Column(String, nullable=False, unique=True, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    plan = Column(String, nullable=False, default="free")  # free | pro | power
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    resumes = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    search_criteria = relationship("SearchCriteria", back_populates="user", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="user", cascade="all, delete-orphan")
    gmail_accounts = relationship("GmailAccount", back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    usage_counters = relationship("UsageCounter", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    pipeline_runs = relationship("PipelineRun", back_populates="user", cascade="all, delete-orphan")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_ref = Column(String, nullable=True)  # GCS object path / signed-URL key
    parsed_json = Column(JSONB, nullable=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="resumes")


class SearchCriteria(Base):
    __tablename__ = "search_criteria"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    roles = Column(ARRAY(String), nullable=False, default=list)
    tech_stack = Column(ARRAY(String), nullable=False, default=list)
    seniority = Column(String, nullable=True)
    locations = Column(ARRAY(String), nullable=False, default=list)
    remote_pref = Column(String, nullable=True)
    inferred_from_resume = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User", back_populates="search_criteria")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)

    # channel is a list because a single job can support both apply + outreach
    channel = Column(ARRAY(String), nullable=False, default=list)

    # Where this lead came from (arbeitnow | jobicy | yc | careers_page |
    # company_list | x). Drives format/routing decisions in the pipeline
    # (e.g. email vs X-DM outreach format, which domain-guessing strategy
    # find_contact_email uses) -- this is live pipeline logic, not metadata.
    source = Column(String, nullable=True)

    # Nullable (no default="") rather than NOT NULL: X/Twitter leads
    # (source="x") have no company/role at scrape time -- the hiring
    # signal is a tweet from x_handle instead, per
    # skills/scrape_x_leads.py. This matters for uq_leads_user_company_role
    # below -- Postgres unique constraints treat NULL as "no value to
    # compare" (any number of NULLs are allowed), but treat "" as a real,
    # collidable value. If these stayed NOT NULL default="", a second
    # X-sourced lead for the same user (company="", role="") would violate
    # the constraint on insert, even though x_handle-based dedup is a
    # completely separate, valid lead.
    company = Column(String, nullable=True)
    role = Column(String, nullable=True)
    jd_text = Column(Text, nullable=True)

    # X/Twitter leads (source="x") have no company/role at scrape time --
    # the hiring signal is a tweet from this handle instead. Nullable, and
    # part of the dedup key alongside (company, role) -- see
    # uq_leads_user_company_role below and repository.add_lead's dedup logic.
    x_handle = Column(String, nullable=True)

    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)

    status = Column(String, nullable=False, default="matched")

    # Plain filename slug (e.g. "jane_doe_resume_acme_corp"), matching
    # skills/tailor_resume.py's save_resume() naming -- the tailored
    # resume's .json/.md/.pdf live under resumes/<resume_version>.*.  This
    # is intentionally a separate column from resume_version_id below: that
    # FK is forward-looking for Phase 3+'s per-user Resume rows in Cloud
    # Storage, but nothing writes it yet since the tailoring pipeline
    # still saves to the local resumes/ folder, not the resumes table.
    resume_version = Column(String, nullable=True)
    resume_version_id = Column(UUID(as_uuid=False), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    cover_note = Column(Text, nullable=True)
    outreach_draft = Column(Text, nullable=True)

    # Human reviewer's decision from the LangGraph review interrupt
    # (approved | edited | rejected) -- distinct from status, which tracks
    # the lead's overall pipeline stage.
    review_decision = Column(String, nullable=True)

    # ATS keyword coverage % for the tailored resume (Phase 5.5) --
    # skills/tailor_resume.py's keyword_coverage(), a rough directional
    # signal, not a real ATS simulation. "sane," not "enforced" per the
    # plan's own wording: this is surfaced to the reviewer, never used to
    # block approval.
    keyword_coverage = Column(Float, nullable=True)

    applied_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    last_checked = Column(DateTime(timezone=True), nullable=True)
    followup_count = Column(Integer, nullable=False, default=0)

    listing_url = Column(String, nullable=True)
    # Original listing's posting date, kept as free-form text since sources
    # report it in inconsistent formats (ISO date, RFC 2822, or a Unix
    # timestamp already rendered to text by the scraper) -- not something
    # the pipeline parses/compares today, only displays.
    posted_date = Column(String, nullable=True)
    domain = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User", back_populates="leads")

    __table_args__ = (
        # Dedup: within a tenant, the same company+role should not be added twice.
        # Case sensitivity is handled at the repository layer (normalized before insert).
        UniqueConstraint("user_id", "company", "role", name="uq_leads_user_company_role"),
        # Separate dedup path for X leads, which have no company/role at
        # scrape time (see x_handle above) -- same handle shouldn't be
        # added twice for one tenant either.
        UniqueConstraint("user_id", "x_handle", name="uq_leads_user_x_handle"),
        Index("ix_leads_user_status", "user_id", "status"),
    )


class GmailAccount(Base):
    __tablename__ = "gmail_accounts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String, nullable=False)
    encrypted_refresh_token = Column(Text, nullable=False)
    scopes = Column(ARRAY(String), nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="gmail_accounts")

    __table_args__ = (
        UniqueConstraint("user_id", "email", name="uq_gmail_accounts_user_email"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan = Column(String, nullable=False, default="free")
    status = Column(String, nullable=False, default="active")  # active | past_due | canceled
    provider_sub_id = Column(String, nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User", back_populates="subscriptions")


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    leads_used = Column(Integer, nullable=False, default=0)
    enrichments_used = Column(Integer, nullable=False, default=0)
    period = Column(String, nullable=False, default="lifetime")  # lifetime | YYYY-MM

    user = relationship("User", back_populates="usage_counters")

    __table_args__ = (
        UniqueConstraint("user_id", "period", name="uq_usage_counters_user_period"),
    )


class PipelineRun(Base):
    """Tracks the on-demand "Run Pipeline" background job (Phase 10b's
    dashboard button, run via orchestrator.pipeline_runner) per user.

    Phase 4 replaces api/main.py's single global `_pipeline_run_state`
    dict + `_pipeline_lock` (a correctness bug: two different signed-in
    users triggering a run at the same time collided on one shared dict,
    and a spurious 409 on the second call) with rows here, one per run,
    scoped by user_id. This also closes the "why does a run's status
    disappear on an API restart / wouldn't be shared by a second replica"
    gap for free, since the row -- not an in-process dict -- is now the
    system of record /api/pipeline/run-status reads from.
    """
    __tablename__ = "pipeline_runs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, default="running")  # running | completed | failed
    current_step = Column(String, nullable=True)
    steps = Column(JSONB, nullable=False, default=list)  # [{step, status}]
    summary = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="pipeline_runs")

    __table_args__ = (
        Index("ix_pipeline_runs_user_started", "user_id", "started_at"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")


# ---------------------------------------------------------------------------
# Shared caches (keyed by domain/job, not user -- reusable across tenants)
# ---------------------------------------------------------------------------


class EnrichmentCache(Base):
    __tablename__ = "enrichment_cache"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    domain = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False)  # apollo | hunter
    result_json = Column(JSONB, nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("domain", "provider", name="uq_enrichment_cache_domain_provider"),
    )


class ResearchCache(Base):
    __tablename__ = "research_cache"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    job_id = Column(UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    result_json = Column(JSONB, nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
