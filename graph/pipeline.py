# import os
# import sqlite3
# from typing import TypedDict, Optional, Any, Dict
# from langgraph.graph import StateGraph, START, END
# from langgraph.types import interrupt
# from langgraph.checkpoint.sqlite import SqliteSaver

# DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")
# DB_PATH = os.path.join(DB_DIR, "checkpoints.sqlite")


# class PipelineState(TypedDict, total=False):
#     lead_id: str
#     source: str
#     company: str
#     role: str
#     jd_text: str
#     contact_name: Optional[str]
#     contact_email: Optional[str]
#     x_handle: Optional[str]
#     resume_version: Optional[str]
#     outreach_draft: Optional[str]
#     review_decision: Optional[str]
#     status: str


# def review_node(state: PipelineState) -> Dict[str, Any]:
#     """Interrupt execution for human review checkpoint.

#     Pauses graph execution natively via interrupt(). When resumed via
#     Command(resume=...), receives user decision ('approved', 'rejected', or edit dict).
#     """
#     decision = interrupt({
#         "lead_id": state.get("lead_id"),
#         "company": state.get("company"),
#         "role": state.get("role"),
#         "resume_version": state.get("resume_version"),
#         "outreach_draft": state.get("outreach_draft"),
#     })

#     if isinstance(decision, dict):
#         status_str = decision.get("status", "approved")
#         new_draft = decision.get("outreach_draft", state.get("outreach_draft"))
#         return {
#             "review_decision": status_str,
#             "status": status_str,
#             "outreach_draft": new_draft
#         }
#     elif decision == "rejected":
#         return {
#             "review_decision": "rejected",
#             "status": "rejected"
#         }
#     else:
#         return {
#             "review_decision": "approved",
#             "status": "approved"
#         }


# def build_pipeline_graph(checkpointer=None):
#     """Builds and compiles the pipeline graph with review checkpoint interrupt."""
#     builder = StateGraph(PipelineState)
#     builder.add_node("review", review_node)
#     builder.add_edge(START, "review")
#     builder.add_edge("review", END)
#     return builder.compile(checkpointer=checkpointer)


# def get_checkpointer_connection(db_path: str = DB_PATH):
#     """Returns a SqliteSaver checkpointer instance connected to db_path."""
#     os.makedirs(os.path.dirname(db_path), exist_ok=True)
#     conn = sqlite3.connect(db_path, check_same_thread=False)
#     return SqliteSaver(conn)



"""LangGraph pipeline — full graph definition.

Nodes: scrape → filter → find_email → tailor → draft → review (interrupt) → send
Cyclic edge: followup_check → draft (for follow-ups)

Each node wraps the corresponding skill's core logic. Per-node error handling
ensures one lead failing doesn't kill the batch. The review node uses
LangGraph's native interrupt() for human-in-the-loop approval.
"""

import os
import sqlite3
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
    is_followup: bool
    followup_count: int
    listing_url: Optional[str]
    domain: Optional[str]
    company_research: Optional[Dict[str, Any]]  # Added for research_company node

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
        # Mock lead dict for the skill function
        lead = {
            "id": lead_id,
            "company": company,
            "domain": domain,
            "x_handle": x_handle,
            "source": source,
        }
        result = find_contact_email_for_lead(lead)
        
        if result.get("contact_email"):
            print(f"  📧 find_email_node: found email for {company}")
            return {
                "contact_email": result["contact_email"],
                "contact_name": result.get("contact_name"),
                "status": "email_found",
            }
        else:
            print(f"  ⚠️  find_email_node: no email found for {company}")
            return {"status": "email_not_found"}
    except Exception as e:
        print(f"  ❌ find_email_node failed for {company}: {e}")
        return {"status": "email_search_failed"}

def research_company_node(state: PipelineState) -> Dict[str, Any]:
    """Research company using Context.dev Brand + Web Scrape APIs."""
    from skills.research_company import research_company
    
    company = state.get("company", "")
    domain = state.get("domain")
    listing_url = state.get("listing_url")
    
    if not domain and not listing_url:
        print(f"  ⚠️  research_company_node: no domain/URL for {company}, skipping")
        return {"status": "research_skipped"}
    
    try:
        research_data = research_company(company, domain, listing_url)
        
        if research_data:
            print(f"  🔍 research_company_node: researched {company}")
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
        # Mock lead dict for the skill function
        lead = {
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
                "status": "tailored",
            }
        else:
            print(f"  ⚠️  tailor_resume_node: tailoring failed for {company}")
            return {"status": "tailor_failed"}
    except Exception as e:
        print(f"  ❌ tailor_resume_node failed for {company}: {e}")
        return {"status": "tailor_failed"}

def review_node(state: PipelineState) -> Dict[str, Any]:
    """Interrupt execution for human review checkpoint.

    Pauses graph execution natively via interrupt(). When resumed via
    Command(resume=...), receives user decision ('approved', 'rejected', or edit dict).
    """
    decision = interrupt({
        "lead_id": state.get("lead_id"),
        "company": state.get("company"),
        "role": state.get("role"),
        "resume_version": state.get("resume_version"),
        "outreach_draft": state.get("outreach_draft"),
        "is_followup": state.get("is_followup", False),
        "followup_count": state.get("followup_count", 0),
    })

    if isinstance(decision, dict):
        status_str = decision.get("status", "approved")
        new_draft = decision.get("outreach_draft", state.get("outreach_draft"))
        return {
            "review_decision": status_str,
            "status": status_str,
            "outreach_draft": new_draft,
        }
    elif decision == "rejected":
        return {
            "review_decision": "rejected",
            "status": "rejected",
        }
    else:
        return {
            "review_decision": "approved",
            "status": "approved",
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

    try:
        from skills.send_via_gmail import (
            get_gmail_service,
            extract_subject_and_body,
            create_draft,
            send_email,
            GMAIL_DIRECT_SEND,
            SENDER_EMAIL,
            _now_iso,
        )

        service = get_gmail_service()
        subject, body = extract_subject_and_body(outreach_draft, company, role)

        if GMAIL_DIRECT_SEND:
            result = send_email(service, contact_email, subject, body)
            print(f"  ✅ send_node: SENT to {contact_email} ({company})")
            return {"status": "sent"}
        else:
            result = create_draft(service, contact_email, subject, body)
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
        FOLLOWUP_DAYS,
        MAX_FOLLOWUPS,
        _now_iso,
    )

    lead_id = state.get("lead_id", "")
    company = state.get("company", "")
    contact_email = state.get("contact_email") or ""
    sent_at = state.get("status")  # We'll need sent_at in state
    followup_count = int(state.get("followup_count") or 0)

    if followup_count >= MAX_FOLLOWUPS:
        print(f"  ⏭️  followup_check: {company} — max follow-ups reached")
        return {"status": "max_followups_reached"}

    try:
        service = get_gmail_service()
        has_reply = check_thread_for_reply(service, contact_email, "")

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

    # Add company research context if available
    research_context = ""
    if company_research:
        research_context = f"""

Company research data (use this to personalize the outreach):
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
    """Route after review: approved → send, rejected → END."""
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
    """Builds the full pipeline graph with review interrupt and follow-up cycle.

    Full flow: START → find_email → research_company → tailor_resume → draft → review → [send | END]
    Follow-up flow: followup_check → draft → review → send

    Each node handles its own errors gracefully, allowing the graph to continue
    processing other leads even if one fails.
    """
    builder = StateGraph(PipelineState)

    # Nodes
    builder.add_node("find_email", find_email_node)
    builder.add_node("research_company", research_company_node)
    builder.add_node("tailor_resume", tailor_resume_node)
    builder.add_node("draft", draft_node)
    builder.add_node("review", review_node)
    builder.add_node("send", send_node)
    builder.add_node("followup_check", followup_check_node)

    # Main flow: START → find_email → research → tailor → draft → review → [send | END]
    builder.add_edge(START, "find_email")
    builder.add_edge("find_email", "research_company")
    builder.add_edge("research_company", "tailor_resume")
    builder.add_edge("tailor_resume", "draft")
    builder.add_edge("draft", "review")

    # After review: route to send (approved) or END (rejected)
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
    """Returns a SqliteSaver checkpointer instance connected to db_path."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)
