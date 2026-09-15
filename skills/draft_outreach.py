import os
import sys
import re
import json
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db import repository as repo
from db.current_user import get_current_user_id
from skills.llm_client import llm_generate

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

RESUMES_DIR = os.path.join(os.path.dirname(__file__), "..", "resumes")

SYSTEM_PROMPT = """You are an outreach-drafting assistant for a job candidate. You will be given the candidate's tailored resume (JSON) for one specific lead, plus details about that lead. Your job is to draft a short, personalized outreach message about that opportunity.

STRICT RULES -- violating any of these is a critical failure:
1. NEVER claim a skill, experience, project, or credential that is not present in the resume JSON given.
2. Do NOT copy resume bullets verbatim -- reference at most 1-2 relevant highlights in natural, conversational outreach language, not resume prose restated.
3. Do NOT claim the resume is attached as a literal file in the message body (it gets attached separately when this is actually sent) -- "I've tailored my resume for this role" is fine, "please find attached" is not, since nothing is attached yet at draft time. Likewise, if you mention an idea, use-case, or project for the company, frame it as a PROPOSAL the candidate is thinking about or would prototype -- NEVER claim it is already built, shipped, demoed, or attached ("I built", "I've made", "here's my demo", "attached is my prototype" are all forbidden). Offer thinking, not a finished artifact.
4. HARD LENGTH LIMIT: the message body (not counting the subject line or signature) must be under 150 words for EMAIL format, and under 60 words for DM format. Count as you write. Cut anything that isn't earning its place -- a shorter, sharper message beats a longer one.
5. Write like a real person typed this in one sitting, not like a cover letter or a mail-merge template. Never use: "I came across your opening," "I am writing to express my interest," "I wanted to reach out," "I believe I would be a great fit," "please find attached," "I look forward to hearing from you," or any equivalent throat-clearing. Open with something specific -- a real observation about the company or role -- not a windup.
6. Show hunger and a point of view, not a qualifications checklist. This candidate is ambitious and has a specific reason THIS company/problem excites them -- pull that reason from something real in the job description (what they build, the problem they're solving, a detail only this company's listing mentions), not a compliment generic enough to paste into any other outreach message. If you can't point to what in the JD justifies a line, cut the line.
7. Confident and direct, not desperate, not stiff -- write like someone pitching an idea they actually believe in, to a peer, not petitioning an authority.
8. End with a clear, low-friction call to action (e.g. open to a quick chat, happy to answer questions) -- never pushy or presumptuous.
9. Sign off with the candidate's name and one relevant link from their resume contact info (GitHub or portfolio) when it fits naturally.

FORMAT: The user message tells you which of two formats to use:
- EMAIL format: first line "Subject: <subject line>", then a blank line, then the body (under 150 words, per rule 4). Address the given contact name if it's a real name, otherwise a generic greeting.
- DM format: no subject line, just the message body (under 60 words, per rule 4). Casual, replying to the specific hiring-signal post/bio text given.

Return ONLY the message text in the exact format requested. No prose, no explanation, no markdown code fences."""


def load_tailored_resume(resume_version: str) -> dict:
    from storage import artifact_store as store

    data = store.get_bytes(f"{resume_version}.json")
    if data is None:
        raise FileNotFoundError(f"tailored resume JSON not found for version '{resume_version}'")
    return json.loads(data.decode("utf-8"))


def _own_links(tailored_resume: dict) -> set[str]:
    """The candidate's own contact links (github/linkedin/portfolio/email),
    normalized to lowercase, so we can verify the outreach draft only ever
    cites links that belong to this specific user's resume."""
    contact = (tailored_resume.get("contact") or {}) if isinstance(tailored_resume, dict) else {}
    links: set[str] = set()
    for key in ("github", "linkedin", "portfolio", "email", "website"):
        val = (contact.get(key) or "").strip().lower()
        if val:
            links.add(val)
    return links


def sanitize_outreach_links(draft: str, tailored_resume: dict) -> str:
    """Defense-in-depth: strip any URL or email in the outreach draft that is
    NOT one of the candidate's own resume contact links.

    The prompt already instructs the model to only sign off with a link from
    the resume, but this guarantees a hallucinated/foreign handle (someone
    else's GitHub, a made-up portfolio) can never go out. A link is kept only
    if one of the user's own contact values is a substring of it (or vice
    versa), so "github.com/alice" survives when the resume lists that handle
    but a fabricated "github.com/bob" is removed.
    """
    if not draft:
        return draft
    own = _own_links(tailored_resume)

    url_or_email = re.compile(
        r"(https?://[^\s<>\)\]]+|www\.[^\s<>\)\]]+|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
    )

    def _keep(token: str) -> bool:
        t = token.rstrip(".,;:!?)\u201d\"'").lower()
        for link in own:
            if link and (link in t or t in link):
                return True
        return False

    def _repl(m: re.Match) -> str:
        token = m.group(0)
        return token if _keep(token) else ""

    cleaned = url_or_email.sub(_repl, draft)
    # Tidy up any orphaned "()" / doubled spaces / dangling label left behind.
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +\n", "\n", cleaned)
    return cleaned.strip()


def draft_outreach_message(tailored_resume: dict, lead: dict) -> str:
    source = lead.get("source") or ""
    company = lead.get("company") or ""
    role = lead.get("role") or ""
    jd_text = lead.get("jd_text") or ""
    contact_name = lead.get("contact_name") or ""
    x_handle = lead.get("x_handle") or ""

    if source == "x":
        format_instruction = (
            f"Use DM format. This is a reply to an X user (@{x_handle or 'unknown'}) who posted "
            "a hiring signal -- their bio and the relevant tweet text are given below as the "
            "job description / hiring-signal text. No subject line."
        )
    else:
        format_instruction = (
            f"Use EMAIL format, reaching out about the role '{role}' at '{company}'. "
            f"Address it to '{contact_name}' if that's a real name, otherwise use a generic "
            "greeting like 'Hi there' or 'Hi {company} team'."
        )

    user_message = f"""{format_instruction}

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
        raw_text = llm_generate(
            system_prompt=SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=1024,
        )
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```\w*\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
        return raw_text
    except Exception as e:
        print(f"  ⚠️  draft_outreach_message LLM call failed ({e}); using template fallback.")
        greeting = f"Hi {contact_name}" if contact_name else f"Hi {company} team"
        candidate_name = tailored_resume.get("name") or "Candidate"
        if source == "x":
            return (
                f"Hi @{x_handle or 'there'}, I saw your post regarding the {role} role at {company}. "
                f"With my experience in software engineering and modern tech stacks, I'd love to learn more and see if my background is a fit!"
            )
        else:
            return (
                f"Subject: Interested in {role} role at {company}\n\n"
                f"{greeting},\n\n"
                f"I'm writing to express my interest in the {role} position at {company}. "
                f"My experience aligns well with your team's engineering focus, and I'd welcome the chance to connect.\n\n"
                f"Best regards,\n{candidate_name}"
            )



def run(user_id: str | None = None):
    from skills.llm_client import MODEL_BACKEND, ANTHROPIC_API_KEY

    if MODEL_BACKEND == "claude" and not ANTHROPIC_API_KEY:
        print("MODEL_BACKEND=claude but ANTHROPIC_API_KEY not set -- skipping draft_outreach.")
        return

    if user_id is None:
        user_id = get_current_user_id()
    leads = repo.get_leads(user_id)
    targets = [
        lead for lead in leads
        if (lead.get("resume_version") or "").strip()
        and not (lead.get("outreach_draft") or "").strip()
        # Phase 5: don't waste an LLM call drafting an outreach message for
        # a lead that has no outreach channel at all -- a lead with no
        # channel set defaults to outreach (v1 is outreach-only).
        and "outreach" in (lead.get("channel") or ["outreach"])
    ]

    drafted = 0

    for lead in targets:
        label = lead.get("company") or lead.get("x_handle") or lead["id"]
        resume_version = lead["resume_version"]

        try:
            tailored_resume = load_tailored_resume(resume_version)
        except FileNotFoundError:
            print(f"Skipping {label} ({lead['id']}) -- tailored resume file not found for "
                  f"resume_version '{resume_version}'.")
            try:
                repo.update_lead(user_id, lead["id"], {"failure_reason": "draft_failed"})
            except Exception:
                pass
            continue

        try:
            draft = draft_outreach_message(tailored_resume, lead)
        except Exception as e:
            print(f"Failed to draft outreach for {label}: {e}")
            try:
                repo.update_lead(user_id, lead["id"], {"failure_reason": "draft_failed"})
            except Exception:
                pass
            continue

        # Strip any link/email that isn't this user's own resume contact, so
        # only the sender's real credentials ever go out.
        draft = sanitize_outreach_links(draft, tailored_resume)

        # Success clears any prior failure flag.
        repo.update_lead(user_id, lead["id"], {
            "outreach_draft": draft, "status": "pending_review", "failure_reason": None,
        })
        drafted += 1
        print(f"\nDrafted outreach for {label} [status -> pending_review]:\n{'-' * 60}\n{draft}\n{'-' * 60}")

    print(f"\ndraft_outreach: {drafted} drafts written.")


if __name__ == "__main__":
    run()
