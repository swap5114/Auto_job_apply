import os
import sys
import re
import json
from anthropic import Anthropic
from dotenv import load_dotenv
from xhtml2pdf import pisa
import html as html_lib

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from storage.sheet_client import get_leads, update_lead

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
BASE_RESUME_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "base_resume.json")
RESUMES_DIR = os.path.join(os.path.dirname(__file__), "..", "resumes")

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are a resume-tailoring assistant. You will be given a candidate's base resume (as structured JSON) and a job description. Your job is to produce a tailored version of the resume for this specific job.

STRICT RULES -- violating any of these is a critical failure:
1. NEVER invent a bullet, skill, project, job title, company, date, or metric that is not already present in the base resume.
2. You MUST actively tailor bullets, not just reorder them wholesale -- this applies especially to PROJECT bullets and Technical Skills, which are the sections most directly relevant to matching a specific job/company's stack. Reword bullets to use this job description's and company's own terminology wherever the base resume already truthfully supports that claim. Passing a bullet through completely unchanged should be the exception (when no honest alignment is possible), not the default -- if you find yourself leaving every project bullet word-for-word identical to the input, you have not done the job.
3. You MAY reorder bullets within an experience or project entry to lead with whatever is most relevant to this job description.
4. Rewording must NEVER change what a bullet claims -- no new scope, no upgraded metrics, no changed responsibility level, and no technology/tool that isn't already listed for that specific entry in the base resume.
5. You MAY reorder skill categories and the skills within them to bring job-relevant skills to the front, and MAY rephrase a skill using the JD's terminology if it is a genuine synonym for a skill already listed (e.g. "REST API design" for "REST APIs") -- never add a skill that isn't already there.
6. You MAY reorder which projects/experience entries appear first, based on relevance to this job description.
7. You MUST NOT change company names, job titles, dates, degree, GPA, or institution names -- copy these through exactly as given.
8. When the base resume already truthfully supports a claim, use the job description's exact terminology where possible (e.g. if the JD says "Node.js" and the bullet already covers that, keep the term "Node.js" rather than paraphrasing) -- this matters for ATS keyword matching.

Return ONLY valid JSON matching the exact same structure as the input base resume. No prose, no markdown code fences, no explanation -- just the JSON object."""


def load_base_resume() -> dict:
    with open(BASE_RESUME_PATH, encoding="utf-8") as f:
        return json.load(f)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def tailor_resume(base_resume: dict, company: str, role: str, jd_text: str) -> dict:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = f"""Job description:
Company: {company}
Role: {role}

{jd_text}

Base resume (JSON):
{json.dumps(base_resume, indent=2)}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text").strip()

    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    return json.loads(raw_text)


def keyword_coverage(jd_text: str, tailored_resume: dict) -> float:
    """Rough ATS-style check: what % of significant JD words appear
    somewhere in the tailored resume. Not a real ATS simulation, just a
    directional signal -- printed alongside each tailored resume."""
    stopwords = {
        "the", "and", "for", "with", "you", "your", "our", "are", "will",
        "this", "that", "have", "from", "who", "a", "an", "to", "of", "in",
        "on", "we", "is", "as", "be", "or", "at", "will", "can", "not",
    }
    jd_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9+.#]{2,}", jd_text.lower())) - stopwords
    if not jd_words:
        return 0.0

    resume_text = json.dumps(tailored_resume).lower()
    matched = sum(1 for word in jd_words if word in resume_text)
    return round(100 * matched / len(jd_words), 1)


def resume_to_markdown(resume: dict) -> str:
    lines = [f"# {resume.get('name', '')}"]

    contact = resume.get("contact", {})
    contact_line = " | ".join(filter(None, [
        contact.get("location"), contact.get("phone"), contact.get("email"),
        contact.get("linkedin"), contact.get("github"), contact.get("portfolio"),
    ]))
    lines.append(contact_line)
    lines.append("")

    if resume.get("summary"):
        lines.append("## Summary")
        lines.append(resume["summary"])
        lines.append("")

    if resume.get("education"):
        lines.append("## Education")
        for edu in resume["education"]:
            lines.append(f"**{edu.get('institution', '')}** — {edu.get('degree', '')} "
                         f"({edu.get('start_date', '')} – {edu.get('end_date', '')})")
            if edu.get("details"):
                lines.append(edu["details"])
        lines.append("")

    if resume.get("experience"):
        lines.append("## Experience")
        for exp in resume["experience"]:
            lines.append(f"**{exp.get('title', '')}**, {exp.get('company', '')} "
                         f"({exp.get('start_date', '')} – {exp.get('end_date', '')})")
            for bullet in exp.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    if resume.get("projects"):
        lines.append("## Projects")
        for proj in resume["projects"]:
            title = proj.get("name", "")
            if proj.get("link"):
                title += f" ({proj['link']})"
            lines.append(f"**{title}** — {proj.get('date', '')}")
            if proj.get("tech_stack"):
                lines.append(f"*{', '.join(proj['tech_stack'])}*")
            for bullet in proj.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    if resume.get("skills"):
        lines.append("## Skills")
        for category, items in resume["skills"].items():
            lines.append(f"**{category}:** {', '.join(items)}")
        lines.append("")

    if resume.get("certifications"):
        lines.append("## Certifications")
        for cert in resume["certifications"]:
            lines.append(f"- {cert}")

    return "\n".join(lines)


def sanitize_for_pdf(text: str) -> str:
    """The default PDF fonts only support Latin-1/WinAnsi encoding, but our
    resume text has em dashes, smart quotes, and arrows (e.g. the Artha.ai
    fallback-chain bullet). Swap those for ASCII-safe equivalents instead of
    risking missing glyphs."""
    if not text:
        return text
    replacements = {
        "—": "-", "–": "-",
        "‘": "'", "’": "'",
        "“": '"', "”": '"',
        "…": "...", "→": "->",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def esc(text: str) -> str:
    """Sanitize then HTML-escape a piece of resume text before it goes into the template."""
    return html_lib.escape(sanitize_for_pdf(text or ""))


RESUME_CSS = """
@page { size: letter; margin: 0.3in 0.5in; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.6pt; line-height: 1.12; color: #000000; }
h1.name { text-align: center; font-size: 18pt; margin: 0 0 1px 0; line-height: 1.1; }
p.contact { text-align: center; font-size: 9.3pt; margin: 0 0 4px 0; }
h2.section { font-size: 11pt; border-bottom: 1px solid #000000; margin: 4px 0 1px 0; padding-bottom: 0px; line-height: 1.1; }
table.row { width: 100%; border-collapse: collapse; }
table.row td { padding: 0; vertical-align: top; line-height: 1.1; }
td.left { text-align: left; font-weight: bold; }
td.left.plain { font-weight: normal; }
td.right { text-align: right; }
p.subtext { font-style: italic; margin: 0; line-height: 1.1; }
p.plain { margin: 0; line-height: 1.1; }
ul.bullets { list-style-type: disc; margin: 0 0 2px 0; padding-left: 13px; }
ul.bullets li { text-align: justify; margin-bottom: 0px; line-height: 1.15; }
p.skills-line { margin: 0; line-height: 1.2; }
a { color: #1155cc; }
"""


def resume_to_html(resume: dict) -> str:
    name = esc(resume.get("name", ""))

    contact = resume.get("contact", {})
    contact_parts = []
    if contact.get("location"):
        contact_parts.append(esc(contact["location"]))
    if contact.get("phone"):
        contact_parts.append(esc(contact["phone"]))
    if contact.get("email"):
        contact_parts.append(esc(contact["email"]))
    if contact.get("linkedin"):
        contact_parts.append(f'<a href="{esc(contact["linkedin"])}">LinkedIn</a>')
    if contact.get("github"):
        contact_parts.append(f'<a href="{esc(contact["github"])}">GitHub</a>')
    if contact.get("portfolio"):
        contact_parts.append(f'<a href="{esc(contact["portfolio"])}">Portfolio</a>')
    contact_line = " | ".join(contact_parts)

    sections = []

    if resume.get("summary"):
        sections.append(f'<h2 class="section">Summary</h2><p class="plain">{esc(resume["summary"])}</p>')

    if resume.get("education"):
        rows = ['<h2 class="section">Education</h2>']
        for edu in resume["education"]:
            institution = edu.get("institution", "")
            if "," in institution:
                inst_name, inst_location = institution.split(",", 1)
            else:
                inst_name, inst_location = institution, ""
            rows.append(
                f'<table class="row"><tr>'
                f'<td class="left">{esc(inst_name.strip())}</td>'
                f'<td class="right">{esc(inst_location.strip())}</td>'
                f'</tr></table>'
            )
            dates = f'{edu.get("start_date", "")} – {edu.get("end_date", "")}'
            rows.append(
                f'<table class="row"><tr>'
                f'<td class="left plain">{esc(edu.get("degree", ""))}</td>'
                f'<td class="right">{esc(dates)}</td>'
                f'</tr></table>'
            )
            if edu.get("details"):
                rows.append(f'<p class="plain">{esc(edu["details"])}</p>')
        sections.append("".join(rows))

    if resume.get("experience"):
        rows = ['<h2 class="section">Experience</h2>']
        for exp in resume["experience"]:
            dates = f'{exp.get("start_date", "")} – {exp.get("end_date", "")}'
            rows.append(
                f'<table class="row"><tr>'
                f'<td class="left">{esc(exp.get("title", ""))}</td>'
                f'<td class="right">{esc(dates)}</td>'
                f'</tr></table>'
            )
            rows.append(f'<p class="subtext">{esc(exp.get("company", ""))}</p>')
            bullets = "".join(f"<li>{esc(b)}</li>" for b in exp.get("bullets", []))
            rows.append(f'<ul class="bullets">{bullets}</ul>')
        sections.append("".join(rows))

    if resume.get("projects"):
        rows = ['<h2 class="section">Projects</h2>']
        for proj in resume["projects"]:
            name_html = esc(proj.get("name", ""))
            if proj.get("link"):
                link_label = "GitHub" if "github.com" in proj["link"].lower() else "Live Link"
                name_html += f' (<a href="{esc(proj["link"])}">{link_label}</a>)'
            rows.append(
                f'<table class="row"><tr>'
                f'<td class="left">{name_html}</td>'
                f'<td class="right">{esc(proj.get("date", ""))}</td>'
                f'</tr></table>'
            )
            if proj.get("tech_stack"):
                tech_line = " · ".join(esc(t) for t in proj["tech_stack"])
                rows.append(f'<p class="subtext">{tech_line}</p>')
            bullets = "".join(f"<li>{esc(b)}</li>" for b in proj.get("bullets", []))
            rows.append(f'<ul class="bullets">{bullets}</ul>')
        sections.append("".join(rows))

    if resume.get("skills"):
        rows = ['<h2 class="section">Technical Skills</h2>']
        for category, items in resume["skills"].items():
            items_line = ", ".join(esc(i) for i in items)
            rows.append(f'<p class="skills-line"><b>{esc(category)}:</b> {items_line}</p>')
        sections.append("".join(rows))

    if resume.get("certifications"):
        rows = ['<h2 class="section">Certifications</h2>']
        bullets = "".join(f"<li>{esc(c)}</li>" for c in resume["certifications"])
        rows.append(f'<ul class="bullets">{bullets}</ul>')
        sections.append("".join(rows))

    return f"""<html>
<head><meta charset="utf-8"><style>{RESUME_CSS}</style></head>
<body>
<h1 class="name">{name}</h1>
<p class="contact">{contact_line}</p>
{"".join(sections)}
</body>
</html>"""


def resume_to_pdf(resume: dict, output_path: str):
    """Renders via HTML/CSS (xhtml2pdf) so we can match the actual visual
    template -- bold-left/date-right rows, justified bullets, section
    divider lines -- instead of a generic manually-positioned layout."""
    html_str = resume_to_html(resume)
    with open(output_path, "wb") as f:
        result = pisa.CreatePDF(html_str, dest=f)
    if result.err:
        raise RuntimeError(f"xhtml2pdf failed to render {output_path} ({result.err} errors)")


def save_resume(resume: dict, company: str) -> str:
    os.makedirs(RESUMES_DIR, exist_ok=True)
    name_slug = slugify(resume.get("name", "resume"))
    company_slug = slugify(company)
    base_filename = f"{name_slug}_resume_{company_slug}"

    json_path = os.path.join(RESUMES_DIR, f"{base_filename}.json")
    md_path = os.path.join(RESUMES_DIR, f"{base_filename}.md")
    pdf_path = os.path.join(RESUMES_DIR, f"{base_filename}.pdf")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resume, f, indent=2, ensure_ascii=False)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(resume_to_markdown(resume))

    resume_to_pdf(resume, pdf_path)

    return base_filename


def backfill_pdfs():
    """Generate PDFs for any already-tailored resume that doesn't have one
    yet, without re-calling the API (reads the .json already saved)."""
    if not os.path.isdir(RESUMES_DIR):
        return
    for filename in os.listdir(RESUMES_DIR):
        if not filename.endswith(".json"):
            continue
        base_filename = filename[:-5]
        pdf_path = os.path.join(RESUMES_DIR, f"{base_filename}.pdf")
        if os.path.exists(pdf_path):
            continue
        with open(os.path.join(RESUMES_DIR, filename), encoding="utf-8") as f:
            resume = json.load(f)
        resume_to_pdf(resume, pdf_path)
        print(f"Backfilled PDF: resumes/{base_filename}.pdf")


def run():
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY not set in config/.env -- skipping tailor_resume.")
        return

    backfill_pdfs()

    base_resume = load_base_resume()
    leads = get_leads()
    targets = [lead for lead in leads if not (lead.get("resume_version") or "").strip()]

    tailored_count = 0

    for lead in targets:
        company = lead.get("company") or lead.get("x_handle") or "Unknown"
        role = lead.get("role") or ""
        jd_text = lead.get("jd_text") or ""

        if not jd_text.strip():
            print(f"Skipping {company} ({lead['id']}) -- no jd_text to tailor against.")
            continue

        try:
            tailored = tailor_resume(base_resume, company, role, jd_text)
        except Exception as e:
            print(f"Failed to tailor resume for {company}: {e}")
            continue

        filename = save_resume(tailored, company)
        coverage = keyword_coverage(jd_text, tailored)
        update_lead(lead["id"], {"resume_version": filename})
        tailored_count += 1
        print(f"Tailored resume for {company} -> resumes/{filename}.json / .md "
              f"(ATS keyword coverage: {coverage}%)")

    print(f"\ntailor_resume: {tailored_count} resumes tailored.")


if __name__ == "__main__":
    run()
