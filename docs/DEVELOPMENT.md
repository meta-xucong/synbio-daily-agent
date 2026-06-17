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
python scripts\report_pipeline.py --build-approved tests\fixtures\raw_full.json --date 2026-06-10 --output $env:TEMP\synbio-data
python scripts\report_pipeline.py --render-md $env:TEMP\synbio-data\approved_2026-06-10.json --date 2026-06-10 --raw tests\fixtures\raw_full.json --output $env:TEMP\2026-06-10.md
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
When no email config exists, dry-run still defaults to URL health checking. Mock `send_email.validate_url_health` in tests that use placeholder domains.
Real sends are single-send by default for each report date. Use `--force-send --send-mode manual` only for explicit manual resends; all other gates still run, and `data/send_log.json` records the attempt.
Set `url_health_mode` to `soft` only for restricted network environments where SSL/certificate handshakes fail locally; soft mode still blocks HTTP errors and deleted-content pages.

## Production Runtime Chain

Use this chain for local end-to-end execution from real search data:

```powershell
python scripts\report_pipeline.py --build-approved data\raw_YYYY-MM-DD.json --date YYYY-MM-DD --output data --check-url-health --check-title-match --search-log data\search_log_YYYY-MM-DD.json
python scripts\report_pipeline.py --render-md data\approved_YYYY-MM-DD.json --date YYYY-MM-DD --raw data\raw_YYYY-MM-DD.json --output reports\YYYY-MM-DD.md
python scripts\generate_from_template.py --date YYYY-MM-DD --approved data\approved_YYYY-MM-DD.json --markdown reports\YYYY-MM-DD.md --html-output reports\synbio_daily_YYYY-MM-DD.html --email-output reports\email_YYYY-MM-DD.html
python scripts\send_email.py YYYY-MM-DD reports\YYYY-MM-DD.md reports\synbio_daily_YYYY-MM-DD.html reports\email_YYYY-MM-DD.html --dry-run
```

`--build-approved --check-url-health --check-title-match` is intentionally slower because it touches outbound links before report generation. It prevents stale/deleted articles from entering approved data and rejects reachable pages whose title signals clearly do not match the collected item title. Title-match network failures are warnings rather than blockers; see `docs/TITLE_URL_MATCH_GATE.md`.

Production runs should also pass `--search-log data\search_log_YYYY-MM-DD.json` to `--build-approved`. The send gate requires the same search log file and verifies that it covers rounds `r1` through `r5`; every raw candidate must include a `source_round` that matches one of those logged rounds.

## Runtime Artifacts

Do not commit generated runtime data from `data/` or `reports/`. Test fixtures belong under `tests/fixtures/`.
