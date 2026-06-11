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
python scripts\render_html.py --approved tests\fixtures\approved_render.json --date 2026-06-10 --output $env:TEMP\rendered.html
```

The validation and AI analysis commands above are expected to fail for the invalid fixture.

## Send Gate

Use dry-run before real SMTP:

```powershell
python scripts\send_email.py YYYY-MM-DD reports\YYYY-MM-DD.md reports\YYYY-MM-DD.html reports\YYYY-MM-DD_email.html --dry-run
```

The gate must pass before SMTP is opened. Gate failures return non-zero and do not call SMTP.
Dry-run can run without a real `config/email_config.json`; real SMTP sends still require it.

## Runtime Artifacts

Do not commit generated runtime data from `data/` or `reports/`. Test fixtures belong under `tests/fixtures/`.
