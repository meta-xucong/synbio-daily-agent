import os


os.environ.setdefault("SYNBIO_DAILY_NOW", "2026-06-11T12:00:00+08:00")
os.environ.setdefault("SYNBIO_SKIP_DOTENV", "1")

for key in (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "SMTP_PASSWORD",
    "SYNBIO_DAILY_HOME",
    "SYNBIO_LLM_JUDGE_CACHE",
):
    os.environ.pop(key, None)
