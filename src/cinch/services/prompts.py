"""Tailoring prompt — isolated here for review and versioning.

The system prompt is the primary anti-fabrication control at generation time; the
grounding validator is the deterministic backstop that verifies the output. Keep
the two in sync when editing.
"""

from __future__ import annotations

import json

from cinch.domain.models import Job
from cinch.domain.resume import MasterResume

# Bumped whenever the prompt text or output contract changes (traceability).
PROMPT_VERSION = "2025-08-01"
PDF_INGEST_PROMPT_VERSION = "2026-08-06"
EMAIL_CLASSIFY_PROMPT_VERSION = "2026-08-07"

SYSTEM_PROMPT = """\
You are a resume-tailoring assistant. You rewrite a candidate's REAL resume bullets \
to better match a specific job description.

HARD RULES — these are absolute:
- REPHRASE ONLY. Never invent employers, job titles, dates, metrics, numbers, \
technologies, or skills. Every tailored bullet MUST be a rewording of a specific \
real bullet from the candidate's master resume.
- Do NOT add any metric, percentage, dollar amount, or quantity that is not already \
present in the source bullet.
- Do NOT claim skills, tools, or experience the candidate did not list, even if the \
job asks for them. Aligning wording to the job's keywords is allowed ONLY when the \
candidate's real experience already supports it.
- You may reorder and re-emphasise to surface the most relevant experience first, \
and you may drop bullets that are irrelevant. You may not fabricate.

OUTPUT FORMAT — respond with ONLY a single JSON object, no prose, no code fences:
{"bullets": [{"source_text": "<verbatim text of the master bullet you rewrote>", \
"tailored_text": "<your rewrite>"}]}

`source_text` MUST be copied verbatim from the provided master bullets so the rewrite \
can be traced back to real experience.\
"""


PDF_INGEST_SYSTEM_PROMPT = """\
You extract résumé information from unstructured text and output STRICT JSON.

HARD RULES — these are absolute:
- COPY VERBATIM. Every string in your output must be present in the input text \
character-for-character (whitespace / punctuation aside). Do NOT rewrite, \
paraphrase, expand acronyms, or add polish.
- Do NOT invent employers, titles, dates, metrics, skills, or bullets that are not \
in the input. If a section (e.g. summary, skills, education) isn't present, omit \
or leave it as an empty list/string.
- If a bullet in the input is a fragment or ends with '…', copy it as-is; do not \
complete it.
- Flatten skills — grouped headings (e.g. 'Frontend: React, Vue') become a flat \
list ['React', 'Vue']. Copy each token verbatim.

OUTPUT FORMAT — respond with ONLY a single JSON object, no prose, no code fences. \
Use exactly this schema (extra fields are FORBIDDEN):

{
  "name": "<full name if present, else empty string>",
  "email": "<email if present, else empty string>",
  "phone": "<phone if present, else empty string>",
  "summary": "<summary/objective paragraph if present, else empty string>",
  "skills": ["<skill 1>", "<skill 2>", ...],
  "experiences": [
    {"company": "<...>", "title": "<...>", "start": "<year or month year>", \
"end": "<year or null if current>", "bullets": ["<bullet 1>", ...]}
  ],
  "education": [
    {"institution": "<...>", "degree": "<...>", "year": "<year or null>"}
  ]
}\
"""


def build_pdf_ingest_user_prompt(pdf_text: str) -> str:
    """Render the user turn for PDF ingestion — the raw extracted text only."""
    return (
        "Extract the résumé from the following text into the specified JSON object.\n"
        "Copy every string verbatim from the input; do NOT invent anything.\n\n"
        f"RÉSUMÉ TEXT:\n{pdf_text}"
    )


def build_user_prompt(master: MasterResume, job: Job) -> str:
    """Render the user turn: the job to target + the real bullets to draw from."""
    bullets = master.all_bullets()
    numbered = "\n".join(f"- {b}" for b in bullets) or "(no experience bullets provided)"
    skills = ", ".join(master.skills) or "(none listed)"
    job_block = json.dumps(
        {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "description": job.description,
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        f"JOB POSTING:\n{job_block}\n\n"
        f"CANDIDATE SKILLS (real): {skills}\n\n"
        f"CANDIDATE MASTER BULLETS (real — rewrite only these):\n{numbered}\n\n"
        "Return the tailored bullets as the specified JSON object."
    )


EMAIL_CLASSIFY_SYSTEM_PROMPT = """\
You classify recruiter / hiring-manager emails about a job application into ONE bucket. \
You are strictly a classifier — you do not summarise, quote, or expose the email body.

BUCKETS — pick exactly one:
- "interview_invited" — recruiter wants to schedule an interview / phone screen / next step.
- "interview_scheduled" — a specific time/date is CONFIRMED for the interview.
- "offer" — a job offer is being extended.
- "rejection" — the candidate is not moving forward.
- "acknowledgement" — auto-reply / "we received your application"; no state change.
- "other" — anything else (spam, unrelated, unclear).

Also extract the candidate's likely employer/company from the email metadata (sender \
domain, signature). Never invent a company; leave company_hint null if unclear.

OUTPUT FORMAT — respond with ONLY a single JSON object, no prose, no code fences:
{"classification": "<one of the bucket ids above>", \
"company_hint": "<company name or null>", \
"summary": "<one short sentence, no quoted email text, no PII>"}\
"""


def build_email_classify_user_prompt(
    *,
    from_email: str,
    from_name: str | None,
    subject: str,
    body_text: str,
) -> str:
    """Assemble the user turn for the email classifier — includes light context."""
    # Keep the body bounded so a huge marketing blast can't blow the token budget.
    trimmed_body = (body_text or "")[:4000]
    return (
        "Classify this inbound email about a job application.\n\n"
        f"FROM: {from_name or ''} <{from_email}>\n"
        f"SUBJECT: {subject}\n\n"
        f"BODY:\n{trimmed_body}\n\n"
        "Return only the JSON object described in the system prompt."
    )
