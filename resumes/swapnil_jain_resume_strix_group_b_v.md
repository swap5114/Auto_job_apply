# Swapnil Jain
Noida, India | +91 6397834087 | swapniljain5114@gmail.com | https://www.linkedin.com/in/swapnil-jain-1581b0224/ | https://github.com/swap5114 | https://portfolio-psi-dun-36.vercel.app/

## Education
**Bennett University, Uttar Pradesh, India** — B.Tech in Computer Science Engineering (2022 – 2026)
GPA: 8.4 / 10

## Experience
**Software Development Intern**, AFI Digital Services LLP (Jan 2026 – Present)
- Followed Agile (Scrum) methodology with bi-weekly sprints and PR-based code reviews; validated Razorpay webhook flows with mock payloads (HMAC-SHA256) and wrote Postman collection-based automated regression tests across all service endpoints.
- Architected a scalable, multi-tiered LMS on the MERN stack, separating auth, content delivery, progress tracking, and payment service layers — improving course management efficiency by 40% and enabling independent scaling of each tier.
- Orchestrated robust request logging and error-tracing middleware within Node.js, ensuring full observability across API tiers; correlated request lifecycles across critical services, cutting down mean time to resolution for production incidents by 30%.
- Engineered a pluggable live class SDK using the Strategy design pattern supporting Dyte, Zoom, Google Meet, and MS Teams via a unified provider interface with OAuth2 and MS Graph API auth — enabling zero-frontend-change provider switching.

## Projects
**Artha.ai — AI-Powered Pre-Trade Analysis Platform (https://artha-one-sigma.vercel.app/)** — Jan 2026 – Present
*Next.js, FastAPI (Python), APScheduler, Google Gemini, Kite Connect, SQLite (PostgreSQL-ready)*
- Designed and built a multi-tiered market intelligence platform with a Next.js frontend, integrating 5 heterogeneous data sources (Zerodha Kite Connect, NSE India, Finnhub, FMP, Screener.in) behind a unified async FastAPI backend with a PostgreSQL-ready relational schema — implementing an NSE → Kite → yfinance fallback chain for 99% data availability.
- Engineered an async scheduled pipeline using APScheduler (AsyncIOScheduler) to generate a 7-section AI morning brief at 8:00 AM IST on market days — aggregating FII/DII flows, index snapshots, and sector cues via Google Gemini, with a 6-hour fundamentals cache refresh cycle.
- Spearheaded the creation of a trade signal engine, incorporating sentiment analysis and risk thresholds, to deliver GO/CAUTION/AVOID recommendations, decreasing portfolio drawdowns in backtests by 7%.
- Developed a Chrome Extension (Manifest V3) that intercepts the Zerodha Kite order flow and surfaces real-time pre-trade risk analysis inline — private repo, code available on request.

**Job Application Multi-Agent Pipeline  (https://github.com/swap5114/Auto_job_apply)** — 2026 – Present
*Python, LangGraph, Claude API, Google Sheets API, Firecrawl, Hunter.io API*
- Architecting an end-to-end multi-agent job application pipeline: a LangGraph-orchestrated graph coordinating lead sourcing, Claude-powered resume tailoring and outreach drafting, a human-in-the-loop review checkpoint, and a cyclic follow-up-tracking node (architecture designed; tailoring, outreach, and orchestration in active development).
- Built a multi-source lead-sourcing pipeline aggregating job postings from structured REST APIs (Arbeitnow, Jobicy) and unstructured company career pages via Firecrawl-based content extraction, normalized into a single deduplicated schema.
- Designed a Google Sheets-backed data layer (gspread + service-account auth) with dedupe logic preventing duplicate lead ingestion across repeated scrape runs.
- Integrated a third-party X/Twitter API for hiring-signal lead discovery and built a keyword-based relevance filter (role, seniority, experience-threshold matching) to auto-exclude out-of-scope leads.
- Implemented a contact-discovery skill using Hunter.io's Domain Search API with multi-path domain resolution to enrich leads with verified contact emails.

## Skills
**Frontend:** React.js, Next.js, Redux, Tailwind CSS, EJS
**Backend:** REST APIs, MVC, Node.js, Express.js, FastAPI, WebSockets, Middleware, MERN
**Databases:** SQLite / PostgreSQL-ready schema, MongoDB (NoSQL), Supabase, SQL
**Cloud & DevOps:** Git, GitHub, Postman, Agile / Scrum, AWS (Basic - EC2, S3), APScheduler
**Languages:** JavaScript (ES6+), Python, C++, SQL, HTML/CSS
**Auth & Payments:** JWT, OAuth2, MS Graph API, Razorpay Webhooks (HMAC-SHA256), Kite Connect API
**Observability:** Structured logging, request tracing middleware, async scheduled pipelines, fallback chain design, threshold-based alerting
**DSA:** LeetCode Rating 1679, Top 15% globally, 160+ problems solved in C++
