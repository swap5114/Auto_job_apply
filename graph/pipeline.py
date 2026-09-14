"""LangGraph pipeline — full graph definition.

Nodes: find_email → research_company → tailor_resume → draft →
    review (interrupt) → [send | END]
Cyclic edge: followup_check → draft (for follow-ups)

Each node wraps the corresponding skill's core logic. Per-node error handling
ensures one lead failing doesn't kill the batch. The review node uses
LangGraph's native interrupt() for human-in-the-loop approval.

v1 note: this is an OUTREACH-ONLY pipeline. The apply channel (channel
routing, cover-note drafting, the ready_to_apply/mark-applied hand-off) was
removed to keep the pipeline simple and robust. Leads are always outreach.
"""

import os
import sqlite3
import threading
from urllib.parse import urlsplit, urlunsplit
from typing import TypedDict, Optional, Any, Dict, List
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.sqlite import SqliteSaver

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
DB_PATH = os.path.join(DB_DIR, "checkpoints.sqlite")

# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class PipelineState(TypedDict, total=False):
    user_id: str  # Phase 4.3: whose lead this is. Set by feed_pending_leads/
    # check_and_queue_followups before graph.invoke(...) -- never left for a
    # node to fall back to db.current_user's single-operator stand-in. None
    # of today's per-lead skill functions (find_contact_email_for_lead,
    # tailor_resume_for_lead, research_company, the Gmail helpers) call
    # db.repository or db.current_user internally -- they're pure functions
    # over the lead dict already carried in state -- so this field exists
    # for the *next* node/skill that needs a real user_id (e.g. a future
    # per-user Gmail account lookup in Phase 6), not because any node today
    # is missing one.
    lead_id: str
    source: str
    company: str
    role: str
    jd_text: str
    contact_name: Optional[str]
    contact_email: Optional[str]
    x_handle: Optional[str]
    resume_version: Optional[str]
    outreach_draft: Optional[str]
    review_decision: Optional[str]
    status: str
    sent_at: Optional[str]  # ISO timestamp the outreach was sent (for reply-window scoping, M-1)
    is_followup: bool
    followup_count: int
    listing_url: Optional[str]
    domain: Optional[str]
    company_research: Optional[Dict[str, Any]]  # Added for research_company node
    channel: Optional[List[str]]  # Lead.channel array (v1: always ["outreach"]) copied from the lead row
    keyword_coverage: Optional[float]  # ATS keyword coverage %, surfaced alongside review

# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------

def find_email_node(state: PipelineState) -> Dict[str, Any]:
    """Find contact email for a lead using Hunter.io or regex scan."""
    from skills.find_contact_email import find_contact_email_for_lead
    
    lead_id = state.get("lead_id", "")
    company = state.get("company", "")
    domain = state.get("domain")
    x_handle = state.get("x_handle")
    source = state.get("source", "")
    
    try:
        # Mock lead dict for the skill function. jd_text/listing_url are needed
        # so the X (bio/tweet scan) and careers_page (site domain) paths work.
        lead = {
            "id": lead_id,
            "company": company,
            "domain": domain,
            "x_handle": x_handle,
            "source": source,
            "jd_text": state.get("jd_text", ""),
            "listing_url": state.get("listing_url", ""),
        }
        result = find_contact_email_for_lead(lead)
        
        user_id = state.get("user_id")
        email = result.get("contact_email")
        name = result.get("contact_name")
        if email:
            print(f"  📧 find_email_node: found email for {company}: {email}")
            if user_id and lead_id:
                try:
                    from db import repository as repo
                    fields = {"contact_email": email, "failure_reason": None}
                    if name:
                        fields["contact_name"] = name
                    repo.update_lead(user_id, lead_id, fields)
                except Exception as db_err:
                    print(f"  ⚠️  find_email_node: failed to persist email to DB: {db_err}")
            return {
                "contact_email": email,
                "contact_name": name,
                "status": "email_found",
            }
        else:
            print(f"  ⚠️  find_email_node: no email found for {company}")
            if user_id and lead_id:
                try:
                    from db import repository as repo
                    repo.update_lead(user_id, lead_id, {"failure_reason": "no_contact_found"})
                except Exception:
                    pass
            return {"status": "email_not_found"}
    except Exception as e:
        print(f"  ❌ find_email_node failed for {company}: {e}")
        return {"status": "email_search_failed"}

def research_company_node(state: PipelineState) -> Dict[str, Any]:
    """Research company and generate demo project idea using LLM."""
    from skills.research_company import research_company
    
    company = state.get("company", "")
    domain = state.get("domain") or ""
    role = state.get("role") or ""
    jd_text = state.get("jd_text") or ""
    
    # Need at least company name or JD to research
    if not company and not jd_text:
        print(f"  ⚠️  research_company_node: no company/JD, skipping research")
        return {"status": "research_skipped"}
    
    try:
        research_data = research_company(
            company=company,
            domain=domain,
            role=role,
            jd_text=jd_text,
        )
        
        if research_data:
            demo = research_data.get("demo_project", {})
            demo_title = demo.get("title", "N/A") if demo else "N/A"
            print(f"  🔍 research_company_node: researched {company}")
            print(f"     Demo idea: {demo_title}")
            return {
                "company_research": research_data,
                "status": "researched",
            }
        else:
            print(f"  ⚠️  research_company_node: no data found for {company}")
            return {"status": "research_failed"}
    except Exception as e:
        print(f"  ❌ research_company_node failed for {company}: {e}")
        return {"status": "research_failed"}

def tailor_resume_node(state: PipelineState) -> Dict[str, Any]:
    """Tailor resume for a lead using Claude/Gemini."""
    from skills.tailor_resume import tailor_resume_for_lead
    
    company = state.get("company", "")
    role = state.get("role", "")
    jd_text = state.get("jd_text", "")
    company_research = state.get("company_research")
    
    if not jd_text:
        print(f"  ⚠️  tailor_resume_node: no JD for {company}, skipping")
        return {"status": "tailor_skipped"}
    
    try:
        lead = {
            "id": state.get("lead_id", ""),
            "user_id": state.get("user_id"),
            "company": company,
            "role": role,
            "jd_text": jd_text,
            "company_research": company_research,  # Pass research data to tailoring
        }
        result = tailor_resume_for_lead(lead)
        
        if result.get("resume_version"):
            print(f"  📄 tailor_resume_node: tailored resume for {company}")
            return {
                "resume_version": result["resume_version"],
                "keyword_coverage": result.get("keyword_coverage"),
                "status": "tailored",
            }
        else:
            print(f"  ⚠️  tailor_resume_node: tailoring failed for {company}")
            return {"status": "tailor_failed"}
    except Exception as e:
        print(f"  ❌ tailor_resume_node failed for {company}: {e}")
        return {"status": "tailor_failed"}

def review_node(state: PipelineState) -> Dict[str, Any]:
    """Interrupt execution for human review checkpoint (outreach only).

    Pauses graph execution natively via interrupt(). When resumed via
    Command(resume=...), receives the user decision ('approved', 'rejected',
    or an edit dict).

    v1 note: this is now outreach-only. The apply channel (cover notes,
    ready_to_apply, the listing-url hand-off) was removed to keep the
    outreach pipeline simple and robust, so there is no per-channel
    branching here anymore.

    Resume contract:
    - Command(resume="approved") -> status "approved" (a send step follows)
    - Command(resume="rejected") -> status "rejected" (routes to END)
    - Command(resume={"status": "approved", "outreach_draft": "..."}) -> edit
    `review_decision` reflects the raw human decision (approved/rejected).
    """
    decision = interrupt({
        "lead_id": state.get("lead_id"),
        "company": state.get("company"),
        "role": state.get("role"),
        "resume_version": state.get("resume_version"),
        "keyword_coverage": state.get("keyword_coverage"),
        "listing_url": state.get("listing_url"),
        "outreach_draft": state.get("outreach_draft"),
        "is_followup": state.get("is_followup", False),
        "followup_count": state.get("followup_count", 0),
    })

    new_draft = state.get("outreach_draft")

    if isinstance(decision, dict):
        status_str = decision.get("status", "approved")
        new_draft = decision.get("outreach_draft", new_draft)
    elif decision == "rejected":
        status_str = "rejected"
    else:
        status_str = "approved"

    return {
        "review_decision": status_str,
        "status": status_str,
        "outreach_draft": new_draft,
    }

def send_node(state: PipelineState) -> Dict[str, Any]:
    """Send email or create Gmail draft for approved leads.

    Skips if status is not 'approved' (e.g. rejected leads route to END without sending).
    """
    if state.get("status") != "approved":
        return {"status": state.get("status", "rejected")}

    contact_email = state.get("contact_email") or ""
    outreach_draft = state.get("outreach_draft") or ""
    company = state.get("company") or ""
    role = state.get("role") or ""

    if not contact_email or not outreach_draft:
        print(f"  ⚠️  send_node: skipping {company} — missing email or draft")
        return {"status": "send_skipped"}

    user_id = state.get("user_id")

    try:
        from skills.send_via_gmail import (
            get_user_send_context,
            extract_subject_and_body,
            create_draft,
            send_email,
            resume_pdf_path,
            NoGmailConnected,
        )

        # v1: send from the lead-owner's OWN connected Gmail, using THEIR
        # send preference. If they haven't connected Gmail, this is a soft,
        # recoverable state -- the lead stays 'approved' so a later run (after
        # they connect) picks it up, rather than a hard failure.
        try:
            service, sender, send_mode = get_user_send_context(user_id)
        except NoGmailConnected:
            print(f"  ⚠️  send_node: {company} approved but user has no Gmail connected")
            return {"status": "approved_needs_gmail"}

        subject, body = extract_subject_and_body(outreach_draft, company, role)

        # Attach the tailored resume PDF if available
        attachment = resume_pdf_path({"resume_version": state.get("resume_version")})

        if send_mode == "direct":
            send_email(service, contact_email, subject, body, attachment, sender=sender)
            print(f"  ✅ send_node: SENT to {contact_email} ({company}) from {sender}")
            return {"status": "sent"}
        else:
            create_draft(service, contact_email, subject, body, attachment, sender=sender)
            print(f"  📝 send_node: DRAFT created for {contact_email} ({company})")
            return {"status": "draft_created"}

    except Exception as e:
        print(f"  ❌ send_node failed for {company}: {e}")
        return {"status": "send_failed"}

def followup_check_node(state: PipelineState) -> Dict[str, Any]:
    """Check if a sent lead needs a follow-up.

    This node is the entry point for the follow-up cycle. It checks Gmail
    for replies and decides whether to route back to drafting.
    """
    from skills.track_followups import (
        get_gmail_service,
        check_thread_for_reply,
        days_since_sent,
        get_max_followups,
        _now_iso,
    )

    lead_id = state.get("lead_id", "")
    company = state.get("company", "")
    contact_email = state.get("contact_email") or ""
    user_id = state.get("user_id")
    followup_count = int(state.get("followup_count") or 0)

    # H-2: read the cap live so a Settings change is honored without restart.
    if followup_count >= get_max_followups():
        print(f"  ⏭️  followup_check: {company} — max follow-ups reached")
        return {"status": "max_followups_reached"}

    try:
        from skills.send_via_gmail import NoGmailConnected
        try:
            # Reply-checking reads the lead-owner's OWN mailbox.
            service = get_gmail_service(user_id)
        except NoGmailConnected:
            print(f"  ⚠️  followup_check: {company} — user has no Gmail connected, skipping")
            return {"status": "followup_check_skipped"}
        sent_at = state.get("sent_at") or ""
        if not isinstance(sent_at, str):
            sent_at = str(sent_at) if sent_at else ""
        has_reply = check_thread_for_reply(service, contact_email, sent_at)

        if has_reply:
            print(f"  💬 followup_check: {company} — reply detected!")
            return {"status": "replied"}
        else:
            print(f"  📨 followup_check: {company} — no reply, needs follow-up")
            return {
                "status": "needs_followup",
                "is_followup": True,
                "followup_count": followup_count + 1,
            }
    except Exception as e:
        print(f"  ❌ followup_check failed for {company}: {e}")
        return {"status": "followup_check_failed"}

def draft_node(state: PipelineState) -> Dict[str, Any]:
    """Draft outreach (or follow-up) message for a lead.

    If is_followup=True, adjusts the prompt to generate a follow-up nudge
    rather than a first-time outreach.
    """
    import json
    from skills.llm_client import llm_generate
    from skills.draft_outreach import SYSTEM_PROMPT, load_tailored_resume

    company = state.get("company") or ""
    role = state.get("role") or ""
    resume_version = state.get("resume_version") or ""
    is_followup = state.get("is_followup", False)
    followup_count = state.get("followup_count", 0)
    company_research = state.get("company_research")

    if not resume_version:
        print(f"  ⚠️  draft_node: no resume_version for {company}, skipping")
        return {"status": "draft_skipped"}

    try:
        tailored_resume = load_tailored_resume(resume_version)
    except FileNotFoundError:
        print(f"  ⚠️  draft_node: resume file not found for {company}")
        return {"status": "draft_skipped"}

    source = state.get("source") or ""
    jd_text = state.get("jd_text") or ""
    contact_name = state.get("contact_name") or ""
    x_handle = state.get("x_handle") or ""
    previous_draft = state.get("outreach_draft") or ""

    if source == "x":
        format_instruction = (
            f"Use DM format. This is a reply to an X user (@{x_handle or 'unknown'}) who posted "
            "a hiring signal. No subject line."
        )
    else:
        format_instruction = (
            f"Use EMAIL format, reaching out about the role '{role}' at '{company}'. "
            f"Address it to '{contact_name}' if that's a real name, otherwise use a generic greeting."
        )

    # Add follow-up context if this is a nudge
    followup_context = ""
    if is_followup:
        followup_context = f"""

IMPORTANT: This is follow-up #{followup_count}. The candidate already sent an initial outreach
(shown below) and received no reply. Write a SHORT follow-up nudge — NOT a repeat of the first message.
Reference the original briefly, add one new angle or value prop, keep it under 80 words for email / 40 for DM.

Previous message sent:
{previous_draft}
"""

    # Add company research context if available (especially the use-case idea)
    research_context = ""
    if company_research:
        idea = company_research.get("demo_project", {})
        if idea:
            research_context = f"""

IMPORTANT — A SPECIFIC IDEA TO LEAD WITH:
The candidate has a concrete, specific idea/use-case for THIS company. Lead the outreach
with it to show genuine understanding of their problem and real value:
- Idea: {idea.get('title', 'N/A')}
- What it is: {idea.get('description', 'N/A')}
- Why it matters to them: {idea.get('why_it_matters', idea.get('why_impressive', 'N/A'))}

HONESTY RULES for how to use this idea (critical):
- Frame it as thinking the candidate has been doing — an angle they'd love to explore or
  prototype with the team. Something like "one thing I'd be keen to try..." or "I had an idea
  for how you might...".
- NEVER claim it is already built, shipped, attached, or demoed. Do NOT say "I built",
  "I've made", "here's my demo", "please find attached", or anything implying a finished artifact.
- Keep it to one or two sentences in the message — a hook that shows insight, not a spec dump.

Full company research data (context only — do not fabricate beyond it):
{json.dumps(company_research, indent=2)}
"""
        else:
            research_context = f"""

Company research data (use this to personalize the outreach honestly — do not fabricate):
{json.dumps(company_research, indent=2)}
"""

    user_message = f"""{format_instruction}{followup_context}{research_context}

Lead details:
Source: {source}
Company: {company}
Role: {role}
Contact name: {contact_name or "(none given)"}
X handle: {x_handle or "(n/a)"}

Job description / hiring-signal text:
{jd_text}

Candidate's tailored resume for this lead (JSON):
{json.dumps(tailored_resume, indent=2)}"""

    try:
        draft = llm_generate(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=1024,
        )
        print(f"  ✍️  draft_node: {'follow-up' if is_followup else 'outreach'} drafted for {company}")
        return {
            "outreach_draft": draft,
            "status": "pending_review",
        }
    except Exception as e:
        print(f"  ❌ draft_node failed for {company}: {e}")
        return {"status": "draft_failed"}

# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def route_after_review(state: PipelineState) -> str:
    """Route after review: approved → send; everything else (rejected,
    draft_failed, etc.) → END."""
    if state.get("status") == "approved":
        return "send"
    return END

def route_after_followup_check(state: PipelineState) -> str:
    """Route after followup check: needs_followup → draft, otherwise → END."""
    if state.get("status") == "needs_followup":
        return "draft"
    return END

# ---------------------------------------------------------------------------
# Graph builders
# ---------------------------------------------------------------------------

def build_pipeline_graph(checkpointer=None):
    """Builds the outreach pipeline graph with review interrupt and follow-up cycle.

    Full flow: START → find_email → research_company → tailor_resume →
        draft → review → [send | END]
    Follow-up flow: followup_check → draft → review → send

    Each node handles its own errors gracefully, allowing the graph to continue
    processing other leads even if one fails.
    """
    builder = StateGraph(PipelineState)

    # Nodes (v1: outreach-only; the apply channel and its cover-note node
    # were removed to keep this pipeline simple and robust).
    builder.add_node("find_email", find_email_node)
    builder.add_node("research_company", research_company_node)
    builder.add_node("tailor_resume", tailor_resume_node)
    builder.add_node("draft", draft_node)
    builder.add_node("review", review_node)
    builder.add_node("send", send_node)
    builder.add_node("followup_check", followup_check_node)

    # Main flow: START → find_email → research → tailor → draft → review →
    #   [send | END]
    builder.add_edge(START, "find_email")
    builder.add_edge("find_email", "research_company")
    builder.add_edge("research_company", "tailor_resume")
    builder.add_edge("tailor_resume", "draft")
    builder.add_edge("draft", "review")

    # After review: route to send (approved) or END (rejected).
    builder.add_conditional_edges("review", route_after_review, ["send", END])

    # After send: done
    builder.add_edge("send", END)

    # Follow-up cycle: followup_check → draft (if needed) → review → send
    # The followup_check node is entered via a separate graph invocation
    builder.add_conditional_edges("followup_check", route_after_followup_check, ["draft", END])

    return builder.compile(checkpointer=checkpointer, interrupt_before=["review"])

def build_followup_graph(checkpointer=None):
    """Builds a graph that enters at followup_check for the cyclic follow-up flow.

    Flow: START → followup_check → [draft → review → send | END]
    This is a separate compiled graph that shares the same nodes but enters
    at the followup_check node instead of the main pipeline start.
    
    For follow-ups, we skip find_email and research_company since those were
    already done in the initial pass. We may optionally re-tailor the resume
    for follow-ups in the future.
    """
    builder = StateGraph(PipelineState)

    builder.add_node("followup_check", followup_check_node)
    builder.add_node("draft", draft_node)
    builder.add_node("review", review_node)
    builder.add_node("send", send_node)

    builder.add_edge(START, "followup_check")
    builder.add_conditional_edges("followup_check", route_after_followup_check, ["draft", END])
    builder.add_edge("draft", "review")
    builder.add_conditional_edges("review", route_after_review, ["send", END])
    builder.add_edge("send", END)

    return builder.compile(checkpointer=checkpointer, interrupt_before=["review"])

def get_checkpointer_connection(db_path: str = DB_PATH):
    """Returns a SqliteSaver checkpointer instance connected to db_path.

    Kept for tests/test_phase7_review.py (and any other test that wants a
    fast, disposable, file-based checkpointer) -- NOT used by production
    code paths anymore. Real (non-test) pipeline runs use
    get_postgres_checkpointer() below, which is durable across worker
    restarts and safe for concurrent multi-user/multi-process access,
    neither of which a single SQLite file guarantees.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)


# ---------------------------------------------------------------------------
# Postgres checkpointer (Phase 4.2) -- the real, production checkpointer.
# ---------------------------------------------------------------------------
#
# Points at the same Postgres database as db/session.py's DATABASE_URL (the
# LangGraph checkpoint tables -- checkpoints/checkpoint_blobs/checkpoint_writes
# -- live alongside the app's own tables, in the same database, managed by
# PostgresSaver.setup() rather than an Alembic migration; see module-level
# note on _POSTGRES_SETUP_DONE below for why a separate migration isn't
# needed here). This is what makes "kill/restart the worker mid-run, resume
# from the same thread_id" and "two users' pipelines running at once, no
# collision" both actually true -- a single sqlite3.Connection is neither
# restart-durable in the way that matters (it is durable, but not shared
# across worker processes/replicas) nor safe for concurrent writers.

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

_pg_pool: Optional[ConnectionPool] = None
_pg_pool_lock = threading.Lock()
_pg_setup_done = False
_pg_setup_lock = threading.Lock()


def _to_psycopg_dsn(sqlalchemy_url: str) -> str:
    """Convert a SQLAlchemy-style DATABASE_URL (postgresql+psycopg2://...)
    into a plain libpq connection string psycopg (v3) accepts.

    db/session.py's DATABASE_URL always carries the `+psycopg2` driver
    suffix SQLAlchemy needs to pick a DBAPI -- psycopg (v3, what
    langgraph-checkpoint-postgres requires) doesn't understand that suffix
    in the scheme and will fail to parse the URL. Everything else about
    the URL (user, password, host, port, database, query string) is
    identical libpq syntax, so this is a pure scheme rewrite, not a
    different connection target.
    """
    parts = urlsplit(sqlalchemy_url)
    scheme = parts.scheme.split("+", 1)[0]  # postgresql+psycopg2 -> postgresql
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def get_postgres_checkpointer() -> PostgresSaver:
    """Returns a PostgresSaver backed by a shared, process-wide connection
    pool pointed at db.session.DATABASE_URL.

    A pool (not a single Connection) is used because the API/worker
    processes are multi-threaded (FastAPI + threading.Thread background
    runs) and PostgresSaver's own internal lock only serializes access to
    a single Connection -- a ConnectionPool lets truly concurrent graph
    runs (e.g. two different users' pipelines, per PHASE_4_PLAN.md 4.6)
    check out separate connections instead of queueing behind one lock.

    setup() (creates the checkpoint tables if missing) is called exactly
    once per process, guarded by a lock -- safe to call repeatedly
    (CREATE TABLE IF NOT EXISTS), but there's no reason to round-trip to
    Postgres on every single graph build.
    """
    global _pg_pool, _pg_setup_done

    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                from psycopg.rows import dict_row
                from db.session import DATABASE_URL

                dsn = _to_psycopg_dsn(DATABASE_URL)
                pool = ConnectionPool(
                    dsn,
                    min_size=1,
                    max_size=10,
                    # autocommit + dict_row are both required by PostgresSaver
                    # -- see langgraph-checkpoint-postgres's own README:
                    # autocommit so .setup()'s CREATE TABLEs actually persist,
                    # dict_row because PostgresSaver reads rows by column name.
                    kwargs={"autocommit": True, "row_factory": dict_row},
                    open=False,
                )
                pool.open()
                _pg_pool = pool

    checkpointer = PostgresSaver(_pg_pool)

    if not _pg_setup_done:
        with _pg_setup_lock:
            if not _pg_setup_done:
                checkpointer.setup()
                _pg_setup_done = True

    return checkpointer


def reset_postgres_checkpointer_pool() -> None:
    """Close and drop the shared connection pool, forcing the next
    get_postgres_checkpointer() call to open a brand new one.

    This is what a real worker restart does at the process level (the old
    pool and its connections are simply gone); tests use this function to
    simulate that within a single pytest process -- see
    tests/test_phase4_pipeline_engine.py's restart-resume test -- without
    actually killing and relaunching a worker.
    """
    global _pg_pool, _pg_setup_done
    with _pg_pool_lock:
        if _pg_pool is not None:
            _pg_pool.close()
        _pg_pool = None
    with _pg_setup_lock:
        _pg_setup_done = False


def make_thread_id(user_id: str, lead_id: str, channel: Optional[str] = None) -> str:
    """Builds the checkpoint thread_id for a lead's main pipeline run,
    scoped by user_id (Phase 4.2) so tenant isolation in the checkpoint
    store is structural, not just "IDs happen not to collide."

    channel (Phase 5.2) is optional, defaulting to None, on purpose --
    NOT a required third positional arg. A lead with channel = ["apply",
    "outreach"] needs two independent review gates (approving the
    tailored resume+cover note is a separate human decision from
    approving the outreach draft), which means two separate thread_ids,
    one per channel: f"{user_id}:{lead_id}:{channel}".

    When channel is None, this returns the exact same f"{user_id}:{lead_id}"
    string this function always has -- this is a real backward-compatibility
    requirement, not a nicety. Postgres already has real outreach-channel
    checkpoint threads paused under that 2-part shape (pre-Phase-5). If
    the signature had instead changed shape outright (channel required,
    or the format always including a channel suffix), every one of those
    already-in-flight threads would become unaddressable -- a differently
    -computed thread_id can't resume a paused thread it doesn't match --
    which is silent data loss, not a refactor. New callers (feed_graph.py,
    check_followups.py's analog, review_cli.py) always pass channel
    explicitly; the 2-arg form is only hit by old in-flight outreach
    threads and by direct tests of this back-compat behavior itself.
    """
    if channel is None:
        return f"{user_id}:{lead_id}"
    return f"{user_id}:{lead_id}:{channel}"


def make_followup_thread_id(user_id: str, lead_id: str, followup_count: int) -> str:
    """Builds the checkpoint thread_id for a lead's follow-up run, scoped
    by user_id -- same reasoning as make_thread_id, extended with the
    followup_count suffix check_followups.py already used to avoid
    colliding with the main pipeline thread for the same lead.
    """
    return f"{user_id}:{lead_id}_followup_{followup_count}"
