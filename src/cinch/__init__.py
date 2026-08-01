"""Cinch — human-in-the-loop job application assistant.

Discovers roles from official job APIs, tailors a master resume to each posting
with an LLM (rephrasing real experience, never fabricating), and sends the job
plus tailored resume to Telegram with Approve/Skip buttons. Nothing is submitted
until the user approves.
"""

__version__ = "0.0.0"
