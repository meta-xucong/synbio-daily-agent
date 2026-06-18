# Release Checklist

- [ ] `python -m pytest -q` passes.
- [ ] `python -m compileall scripts` passes.
- [ ] `report_pipeline.py --process` accepts a complete raw dict fixture.
- [ ] Structured `search_log` can generate raw through `--build-raw-from-search`.
- [ ] Production raw items include `source_round`, and `search_log_YYYY-MM-DD.json` covers `r1` through `r5`.
- [ ] Production `--build-approved` runs use `--strict-search-coverage --check-url-health --check-title-match --search-log`.
- [ ] `report_pipeline.py --render-md` uses `--raw` so the report trace shows the true raw candidate count.
- [ ] `send_email.py --dry-run` passes for a known-good local report.
- [ ] `send_email.py --dry-run` does not require real SMTP credentials.
- [ ] AI invalid fixture fails and reports ungrounded entity/number.
- [ ] `report_pipeline.py --validate` fails on AI ungrounded entity/number fixtures.
- [ ] No runtime logic contains a machine-specific absolute path.
- [ ] HTML/email links use `rel="noopener noreferrer"` when `target="_blank"` is present.
- [ ] External text is escaped before HTML insertion; unsafe URL schemes are rejected.
- [ ] README, SKILL, USAGE_GUIDE, and `config/dedup_rules.md` agree on dedup, scoring, empty-section, and send-gate rules.
- [ ] No secrets, SMTP passwords, cookies, or tokens are committed.
