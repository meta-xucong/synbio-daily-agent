# Development Guide

## Local Setup

```powershell
python -m pip install -r requirements.txt
$env:SYNBIO_DAILY_HOME = (Get-Location).Path
$env:SYNBIO_DAILY_TZ = "Asia/Shanghai"
```

`SYNBIO_DAILY_HOME` is optional. When unset, scripts use the repository root.

## Verification Commands

```powershell
python -m pytest -q
python -m compileall scripts
python scripts\report_pipeline.py --process tests\fixtures\raw_full.json --type news --output $env:TEMP\news_processed.json
python scripts\report_pipeline.py --validate tests\fixtures\invalid_ai_report.md --output $env:TEMP\invalid_ai_validation.json
python scripts\ai_analysis_check.py --report tests\fixtures\invalid_ai_report.md
python scripts\generate_from_template.py --date 2026-06-10 --approved tests\fixtures\approved_render.json --markdown tests\fixtures\valid_report.md --html-output $env:TEMP\synbio_daily_2026-06-10.html --email-output $env:TEMP\email_2026-06-10.html
```

The validation and AI analysis commands above are expected to fail for the invalid fixture.
`generate_from_template.py` is the production renderer for `templates/daily_report_template_v2.html`. `render_html.py` and `render_email.py` are safe minimal fallback/test-fixture renderers only.

## Send Gate

Use dry-run before real SMTP:

```powershell
python scripts\send_email.py YYYY-MM-DD reports\YYYY-MM-DD.md reports\synbio_daily_YYYY-MM-DD.html reports\email_YYYY-MM-DD.html --dry-run
```

The gate must pass before SMTP is opened. Gate failures return non-zero and do not call SMTP.
Dry-run can run without a real `config/email_config.json`; real SMTP sends still require it.

## Runtime Artifacts

Do not commit generated runtime data from `data/` or `reports/`. Test fixtures belong under `tests/fixtures/`.
