import os
import sys
import re
import json
from anthropic import Anthropic
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from storage.sheet_client import get_leads, update_lead

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
RESUMES_DIR = os.path.join(os.path.dirname(__file__), "..", "resumes")

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are an outreach-drafting assistant for a job candidate. You will be given the candidate's tailored resume (JSON) for one specific lead, plus details about that lead. Your job is to draft a short, personalized outreach message about that opportunity.

STRICT RULES -- violating any of these is a critical failure:
1. NEVER claim a skill, experience, project, or credential that is not present in the resume JSON given.
2. Do NOT copy resume bullets verbatim -- reference at most 1-2 relevant highlights in natural, conversational outreach language, not resume prose restated.
3. Do NOT claim the resume is attached as a literal file in the message body (it gets attached separately when this is actually sent) -- "I've tailored my resume for this role" is fine, "please find attached" is not, since nothing is attached yet at draft time.
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
    path = os.path.join(RESUMES_DIR, f"{resume_version}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def draft_outreach_message(tailored_resume: dict, lead: dict) -> str:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

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

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text").strip()

    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```\w*\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    return raw_text


def run():
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY not set in config/.env -- skipping draft_outreach.")
        return

    leads = get_leads()
    targets = [
        lead for lead in leads
        if (lead.get("resume_version") or "").strip() and not (lead.get("outreach_draft") or "").strip()
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
            continue

        try:
            draft = draft_outreach_message(tailored_resume, lead)
        except Exception as e:
            print(f"Failed to draft outreach for {label}: {e}")
            continue

        update_lead(lead["id"], {"outreach_draft": draft})
        drafted += 1
        print(f"\nDrafted outreach for {label}:\n{'-' * 60}\n{draft}\n{'-' * 60}")

    print(f"\ndraft_outreach: {drafted} drafts written.")


if __name__ == "__main__":
    run()
