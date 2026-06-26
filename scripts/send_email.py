#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成生物行业日报 - 邮件发送脚本"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from .settings import CONFIG_DIR, DATA_DIR
    from .console_utils import ensure_utf8_console
    from . import pre_check as pre_check_module
    from . import post_check as post_check_module
    from . import generate_from_template as generate_from_template_module
    from .pre_check import pre_check
    from .post_check import post_check
    from . import report_pipeline as report_pipeline_module
    from .report_pipeline import (
        extract_http_urls,
        extract_plain_http_urls,
        run_full_validation,
        validate_email_mime_type,
        validate_approved_schema,
        validate_approved_not_previously_sent,
        validate_url_health,
        validate_urls_against_approved,
    )
    from .html_safety import validate_html_safety
except ImportError:
    from settings import CONFIG_DIR, DATA_DIR
    from console_utils import ensure_utf8_console
    import pre_check as pre_check_module
    import post_check as post_check_module
    import generate_from_template as generate_from_template_module
    from pre_check import pre_check
    from post_check import post_check
    import report_pipeline as report_pipeline_module
    from report_pipeline import (
        extract_http_urls,
        extract_plain_http_urls,
        run_full_validation,
        validate_email_mime_type,
        validate_approved_schema,
        validate_approved_not_previously_sent,
        validate_url_health,
        validate_urls_against_approved,
    )
    from html_safety import validate_html_safety

ensure_utf8_console()


@dataclass(frozen=True)
class RuntimeContext:
    project_root: Path
    data_dir: Path
    config_dir: Path
    reports_dir: Path
    warnings: tuple[str, ...] = ()


@dataclass
class PreparedSendPayload:
    runtime: RuntimeContext
    approved_data: list[dict[str, Any]]
    effective_approved_data: list[dict[str, Any]]
    md_path: Path
    html_path: Path
    email_html_path: Path | None
    warnings: list[str]
    errors: list[str]
    duplicate_check: dict[str, Any]
    date_already_sent: bool
    filtered_duplicate_count: int = 0
    tempdir: TemporaryDirectory[str] | None = None

    def cleanup(self) -> None:
        if self.tempdir is not None:
            self.tempdir.cleanup()
            self.tempdir = None


def _looks_like_project_root(path: Path) -> bool:
    return (path / "data").exists() or (path / "config").exists() or (path / "reports").exists()


def _iter_candidate_project_roots(*paths: str | Path | None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        start = path if path.is_dir() else path.parent
        for ancestor in (start, *start.parents):
            if not _looks_like_project_root(ancestor):
                continue
            if ancestor in seen:
                continue
            seen.add(ancestor)
            candidates.append(ancestor)
    return candidates


def _score_project_root(root: Path, report_paths: list[Path], date_str: str) -> tuple[int, int]:
    score = 0
    approved_path = root / "data" / f"approved_{date_str}.json"
    config_path = root / "config" / "email_config.json"
    if approved_path.exists():
        score += 10
    if config_path.exists():
        score += 6
    if (root / "data" / "send_log.json").exists():
        score += 2
    if (root / "data" / "history_index.json").exists():
        score += 2
    path_matches = 0
    for report_path in report_paths:
        try:
            report_path.relative_to(root / "reports")
        except ValueError:
            continue
        path_matches += 1
    score += path_matches * 8
    depth = len(root.parts)
    return score, depth


def _root_has_runtime_activity(root: Path, date_str: str) -> bool:
    data_dir = root / "data"
    if not data_dir.exists():
        return False
    interesting_paths = (
        data_dir / f"approved_{date_str}.json",
        data_dir / f"raw_{date_str}.json",
        data_dir / f"search_log_{date_str}.json",
        data_dir / "history_index.json",
        data_dir / "send_log.json",
        data_dir / "sent_url_registry.json",
    )
    return any(path.exists() for path in interesting_paths)


def _config_dir_has_runtime_files(config_dir: Path) -> bool:
    return config_dir.exists() and (config_dir / "search_queries.json").exists()


def resolve_runtime_context(
    date_str: str,
    md_path: str | Path,
    html_path: str | Path,
    email_html_path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
    data_dir: str | Path | None = None,
    config_dir: str | Path | None = None,
) -> RuntimeContext:
    report_paths = [Path(md_path).resolve(), Path(html_path).resolve()]
    if email_html_path:
        report_paths.append(Path(email_html_path).resolve())

    default_root = DATA_DIR.parent.resolve()
    warnings: list[str] = []
    candidate_roots = [default_root]
    candidate_roots.extend(_iter_candidate_project_roots(*report_paths))

    if project_root:
        root = Path(project_root).resolve()
    else:
        scored = sorted(
            ((*_score_project_root(candidate, report_paths, date_str), candidate) for candidate in candidate_roots),
            reverse=True,
        )
        root = scored[0][2] if scored else default_root
        if root != default_root:
            warnings.append(
                f"[数据路径] 已根据报告路径自动切换运行目录: {root}"
            )

    shadow_roots = sorted(
        {
            candidate
            for candidate in candidate_roots
            if candidate != root and _root_has_runtime_activity(candidate, date_str)
        }
    )
    if shadow_roots:
        warnings.append(
            "[数据路径] 检测到多个活跃运行目录，当前使用 "
            f"{root}；其余目录也存在当日数据或发送历史: "
            + ", ".join(str(candidate) for candidate in shadow_roots)
            + "。建议统一设置 SYNBIO_DAILY_HOME 或显式传入 --project-root。"
        )

    resolved_data_dir = Path(data_dir).resolve() if data_dir else root / "data"
    if config_dir:
        resolved_config_dir = Path(config_dir).resolve()
    else:
        candidate_config_dir = root / "config"
        default_config_dir = CONFIG_DIR.resolve()
        if _config_dir_has_runtime_files(candidate_config_dir):
            resolved_config_dir = candidate_config_dir
        else:
            resolved_config_dir = default_config_dir
            if root != default_root:
                warnings.append(
                    f"[数据路径] 运行数据使用 {resolved_data_dir}；配置回退到代码仓目录 {resolved_config_dir}"
                )
    resolved_reports_dir = root / "reports"

    outer_approved = resolved_data_dir / f"approved_{date_str}.json"
    if not outer_approved.exists():
        warnings.append(
            f"[数据路径] 当前运行 data 目录缺少 approved_{date_str}.json: {outer_approved}"
        )

    return RuntimeContext(
        project_root=root,
        data_dir=resolved_data_dir,
        config_dir=resolved_config_dir,
        reports_dir=resolved_reports_dir,
        warnings=tuple(warnings),
    )


def load_email_config(config_dir: Path | None = None) -> Dict[str, Any]:
    """从配置文件读取邮件配置"""
    requested_dir = (config_dir or CONFIG_DIR).resolve()
    candidate_paths = [requested_dir / "email_config.json"]
    default_path = CONFIG_DIR.resolve() / "email_config.json"
    if default_path not in candidate_paths:
        candidate_paths.append(default_path)
    config_path = next((path for path in candidate_paths if path.exists()), None)
    if config_path is None:
        checked = ", ".join(str(path) for path in candidate_paths)
        raise FileNotFoundError(f"邮件配置文件不存在，已检查: {checked}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_password = os.getenv("SMTP_PASSWORD")
    if env_password:
        config["sender_password"] = env_password
    return config


def dry_run_email_config() -> Dict[str, Any]:
    """Return a non-secret config suitable for validation-only dry runs."""
    return {
        "enabled": True,
        "smtp_server": "smtp.invalid",
        "smtp_port": 465,
        "sender_email": "dry-run@example.invalid",
        "sender_password": "",
        "receiver_email": "dry-run@example.invalid",
        "check_url_health": True,
        "url_health_mode": "strict",
    }


def read_report_files(md_path: str | Path, html_path: str | Path, email_html_path: str | Path | None = None) -> Dict[str, str]:
    """Read report body and attachment contents."""
    md_path = Path(md_path)
    html_path = Path(html_path)
    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    if email_html_path and Path(email_html_path).exists():
        with open(email_html_path, "r", encoding="utf-8") as f:
            email_body = f.read()
    else:
        email_body = html_content

    return {
        "md_content": md_content,
        "html_content": html_content,
        "email_body": email_body,
    }


def build_email_message(
    date_str: str,
    sender: str,
    receiver: str,
    md_content: str,
    html_content: str,
    email_body: str,
) -> MIMEMultipart:
    """Build the MIME message without sending it."""
    msg = MIMEMultipart("related")
    msg["Subject"] = f"合成生物行业日报 - {date_str}"
    msg["From"] = sender
    msg["To"] = receiver

    msg.attach(MIMEText(email_body, "html", "utf-8"))

    html_attachment = MIMEText(html_content, "html", "utf-8")
    html_attachment.add_header("Content-Disposition", "attachment", filename=f"synbio_daily_{date_str}.html")
    msg.attach(html_attachment)

    md_attachment = MIMEText(md_content, "plain", "utf-8")
    md_attachment.add_header("Content-Disposition", "attachment", filename=f"synbio_daily_{date_str}.md")
    msg.attach(md_attachment)

    return msg


def build_simple_fallback_message(date_str: str, sender: str, receiver: str, email_body: str) -> MIMEText:
    """Build an explicit no-attachment fallback email body."""
    msg = MIMEText(email_body, "html", "utf-8")
    msg["Subject"] = f"合成生物行业日报 - {date_str}"
    msg["From"] = sender
    msg["To"] = receiver
    return msg


def print_smtp_diagnostics(exc: smtplib.SMTPResponseException) -> None:
    """Print actionable diagnostics for SMTP response failures."""
    print(f"SMTP发送失败: code={exc.smtp_code}, error={exc.smtp_error!r}")
    if exc.smtp_code == 500:
        print("诊断建议：")
        print("  1. 检查 smtp_server/smtp_port 是否为邮箱服务商要求的地址和端口")
        print("  2. 检查发件人账号是否和登录账号一致")
        print("  3. 检查邮件头 Subject/From/To 是否为空或包含非法换行")
        print("  4. 检查附件文件名和 MIME 结构是否被服务商拒绝")
        print("  5. 当前发送方式使用 SMTP_SSL.send_message(); 如仍失败，请保留完整 code/error 继续排查")


def send_message_via_smtp(config: Dict[str, Any], msg) -> None:
    """Send a prepared email message through SMTP_SSL."""
    with smtplib.SMTP_SSL(config["smtp_server"], config["smtp_port"], timeout=30) as server:
        server.login(config["sender_email"], config["sender_password"])
        server.send_message(
            msg,
            from_addr=config["sender_email"],
            to_addrs=[config["receiver_email"]],
        )


def load_approved_data(date_str: str, data_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load approved data for the send gate."""
    approved_path = (data_dir or DATA_DIR) / f"approved_{date_str}.json"
    if not approved_path.exists():
        raise FileNotFoundError(f"approved数据不存在: {approved_path}")
    with open(approved_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"approved数据必须是列表: {approved_path}")
    return data


def _update_history_index(
    date_str: str,
    approved_items: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
) -> None:
    """发送成功后，将 approved 条目追加到 history_index.json 以实现跨天持久化去重。"""
    runtime_data_dir = data_dir or DATA_DIR
    history_path = runtime_data_dir / "history_index.json"
    history = {"version": 1, "entries": []}
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    existing_urls = set()
    existing_url_keys = set()
    entries_by_key: dict[str, dict[str, Any]] = {}
    for entry in history.get("entries", []):
        entry_urls = report_pipeline_module._item_candidate_urls(entry)
        entry_urls.append(entry.get("canonical_url", ""))
        entry_urls.append(entry.get("url", ""))
        existing_urls.update(
            report_pipeline_module.canonicalize_url(url)
            for url in entry_urls
            if url
        )
        if entry.get("dedup_key"):
            dedup_key = str(entry.get("dedup_key"))
            existing_url_keys.add(dedup_key)
            entries_by_key[dedup_key] = entry
        existing_url_keys.update(
            report_pipeline_module.url_dedup_key(url)
            for url in entry_urls
            if url
        )
        for url in entry_urls:
            key = report_pipeline_module.url_dedup_key(url)
            if key:
                entries_by_key[key] = entry

    for item in approved_items:
        title = item.get("title", "")
        item_urls = report_pipeline_module._item_candidate_urls(item)
        if not title or not item_urls:
            continue
        fingerprint = report_pipeline_module._make_fingerprint(item)
        updated_entry_ids: set[int] = set()
        for url in item_urls:
            canonical_url = report_pipeline_module.canonicalize_url(url)
            dedup_key = report_pipeline_module.url_dedup_key(url)
            existing_entry = entries_by_key.get(dedup_key)
            if existing_entry:
                if id(existing_entry) not in updated_entry_ids:
                    existing_entry["last_sent_date"] = date_str
                    existing_entry["sent_count"] = int(existing_entry.get("sent_count") or 1) + 1
                    updated_entry_ids.add(id(existing_entry))
                existing_entry.setdefault("canonical_url", canonical_url)
                existing_entry.setdefault("url", url)
                if item_urls:
                    existing_entry["urls"] = item_urls
                continue
            if canonical_url in existing_urls or dedup_key in existing_url_keys:
                continue
            history["entries"].append({
                "url": url,
                "canonical_url": canonical_url,
                "dedup_key": dedup_key,
                "urls": item_urls,
                "title": title[:120],
                "fingerprint": fingerprint,
                "date": item.get("date", ""),
                "first_sent_date": date_str,
                "last_sent_date": date_str,
                "sent_count": 1,
            })
            existing_urls.add(canonical_url)
            existing_url_keys.add(dedup_key)
            entries_by_key[dedup_key] = history["entries"][-1]

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    report_pipeline_module.update_sent_url_registry(date_str, approved_items, data_dir=runtime_data_dir)
    print(f"历史索引已更新: {len(history['entries'])} 条")


def _send_log_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "send_log.json"


def _load_send_log(data_dir: Path | None = None) -> dict[str, Any]:
    path = _send_log_path(data_dir)
    if not path.exists():
        return {"version": 1, "sends": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("sends"), list):
            return data
    except Exception:
        pass
    return {"version": 1, "sends": []}


def _write_send_log(log: dict[str, Any], data_dir: Path | None = None) -> None:
    runtime_data_dir = data_dir or DATA_DIR
    runtime_data_dir.mkdir(parents=True, exist_ok=True)
    with open(_send_log_path(runtime_data_dir), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def has_successful_send_for_date(date_str: str, data_dir: Path | None = None) -> bool:
    """Return True when the report date already has a successful real send."""
    log = _load_send_log(data_dir)
    return any(entry.get("date") == date_str and entry.get("status") == "success" for entry in log.get("sends", []))


def record_send_attempt(
    date_str: str,
    *,
    status: str,
    send_mode: str,
    forced: bool,
    error: str = "",
    data_dir: Path | None = None,
    item_count: int | None = None,
) -> None:
    """Append a report-level send attempt for duplicate-send auditing."""
    log = _load_send_log(data_dir)
    log.setdefault("version", 1)
    log.setdefault("sends", [])
    entry = {
        "date": date_str,
        "status": status,
        "send_mode": send_mode,
        "forced": forced,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "error": error,
    }
    if item_count is not None:
        entry["item_count"] = item_count
    log["sends"].append(entry)
    _write_send_log(log, data_dir)


def _stage_incremental_payload(
    date_str: str,
    approved_items: list[dict[str, Any]],
) -> tuple[TemporaryDirectory[str], Path, Path, Path]:
    tempdir = TemporaryDirectory(prefix=f"synbio-send-{date_str}-")
    stage_dir = Path(tempdir.name)
    approved_path = stage_dir / f"approved_{date_str}.json"
    md_path = stage_dir / f"{date_str}.md"
    html_path = stage_dir / f"{date_str}.html"
    email_path = stage_dir / f"{date_str}_email.html"

    approved_path.write_text(json.dumps(approved_items, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_pipeline_module.render_markdown_report(
        approved_items,
        date_str,
        raw_count=len(approved_items),
    )
    md_path.write_text(markdown, encoding="utf-8")
    generate_from_template_module.generate(
        report_date=date_str,
        approved_path=approved_path,
        markdown_path=md_path,
        html_output=html_path,
        email_output=email_path,
    )
    return tempdir, md_path, html_path, email_path


def prepare_send_payload(
    date_str: str,
    md_path: str | Path,
    html_path: str | Path,
    email_html_path: str | Path | None = None,
    *,
    force_send: bool = False,
    enforce_send_once: bool = True,
    project_root: str | Path | None = None,
    data_dir: str | Path | None = None,
    config_dir: str | Path | None = None,
) -> PreparedSendPayload:
    runtime = resolve_runtime_context(
        date_str,
        md_path,
        html_path,
        email_html_path,
        project_root=project_root,
        data_dir=data_dir,
        config_dir=config_dir,
    )
    warnings = list(runtime.warnings)
    errors: list[str] = []

    approved_data = load_approved_data(date_str, data_dir=runtime.data_dir)
    duplicate_check = validate_approved_not_previously_sent(
        approved_data,
        data_dir=runtime.data_dir,
        label="发送门禁approved",
    ) if approved_data else {
        "is_valid": True,
        "errors": [],
        "checked": [],
        "total_checked": 0,
        "duplicate_indices": [],
        "duplicate_records": [],
        "sent_dedup_keys": [],
    }

    date_already_sent = has_successful_send_for_date(date_str, data_dir=runtime.data_dir)
    if date_already_sent:
        warnings.append(f"[日期提醒] 日期 {date_str} 已有成功发送记录，将仅发送未发送过的新 URL")

    effective_approved = approved_data
    effective_md_path = Path(md_path)
    effective_html_path = Path(html_path)
    effective_email_path = Path(email_html_path) if email_html_path else None
    tempdir: TemporaryDirectory[str] | None = None
    filtered_duplicate_count = 0

    duplicate_indices = set(duplicate_check.get("duplicate_indices", []))
    if duplicate_indices and not force_send:
        filtered_duplicate_count = len(duplicate_indices)
        effective_approved = [
            item for index, item in enumerate(approved_data, 1)
            if index not in duplicate_indices
        ]
        if not effective_approved:
            errors.append(f"[URL去重] 日期 {date_str} 的 approved URL 均已发送过，已阻止重复发送")
        else:
            tempdir, effective_md_path, effective_html_path, effective_email_path = _stage_incremental_payload(
                date_str,
                effective_approved,
            )
            warnings.append(
                f"[URL去重] 已过滤 {filtered_duplicate_count} 条已发送信息，本次发送剩余 {len(effective_approved)} 条新信息"
            )
    elif duplicate_indices and force_send:
        warnings.extend([f"[URL去重] {error}；已使用 force_send 显式放行" for error in duplicate_check["errors"]])

    return PreparedSendPayload(
        runtime=runtime,
        approved_data=approved_data,
        effective_approved_data=effective_approved,
        md_path=effective_md_path,
        html_path=effective_html_path,
        email_html_path=effective_email_path,
        warnings=warnings,
        errors=errors,
        duplicate_check=duplicate_check,
        date_already_sent=date_already_sent,
        filtered_duplicate_count=filtered_duplicate_count,
        tempdir=tempdir,
    )


def validate_template_signature(html: str, label: str) -> Dict[str, Any]:
    """Ensure generated HTML looks like the production template output."""
    required_any = ('class="card"', 'class="data-table"')
    required_all = ('class="summary-section"', 'class="content-section"', 'class="section-title"')
    errors: list[str] = []
    for marker in required_all:
        if marker not in html:
            errors.append(f"{label}缺少定稿模板标记: {marker}")
    if not any(marker in html for marker in required_any):
        errors.append(f"{label}缺少定稿模板内容标记: card/data-table")
    if 'class="analysis-block"' not in html and 'class="risk-box"' not in html:
        errors.append(f"{label}缺少定稿模板AI分析标记: analysis-block/risk-box")
    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
    }


def validate_send_gate(
    date_str: str,
    md_path: str | Path,
    html_path: str | Path,
    email_html_path: str | Path | None = None,
    msg: MIMEMultipart | None = None,
    check_url_health: bool = True,
    url_health_mode: str = "strict",
    force_send: bool = False,
    enforce_send_once: bool = True,
    project_root: str | Path | None = None,
    data_dir: str | Path | None = None,
    config_dir: str | Path | None = None,
    prepared_payload: PreparedSendPayload | None = None,
) -> Dict[str, Any]:
    """Run all checks required before any SMTP connection is opened."""
    errors: list[str] = []
    warnings: list[str] = []
    details: Dict[str, Any] = {}
    owns_payload = prepared_payload is None
    prepared: PreparedSendPayload | None = prepared_payload
    try:
        if prepared is None:
            prepared = prepare_send_payload(
                date_str,
                md_path,
                html_path,
                email_html_path,
                force_send=force_send,
                enforce_send_once=enforce_send_once,
                project_root=project_root,
                data_dir=data_dir,
                config_dir=config_dir,
            )
    except Exception as exc:
        return {
            "passed": False,
            "errors": [str(exc)],
            "warnings": [],
            "details": {},
        }

    assert prepared is not None
    runtime_data_dir = prepared.runtime.data_dir
    runtime_reports_dir = prepared.md_path.parent
    runtime_config_dir = prepared.runtime.config_dir
    errors.extend(prepared.errors)
    warnings.extend(prepared.warnings)
    details["runtime_context"] = {
        "project_root": str(prepared.runtime.project_root),
        "data_dir": str(runtime_data_dir),
        "config_dir": str(runtime_config_dir),
        "reports_dir": str(prepared.runtime.reports_dir),
    }
    details["send_payload"] = {
        "effective_md_path": str(prepared.md_path),
        "effective_html_path": str(prepared.html_path),
        "effective_email_html_path": str(prepared.email_html_path) if prepared.email_html_path else None,
        "original_approved_count": len(prepared.approved_data),
        "effective_approved_count": len(prepared.effective_approved_data),
        "filtered_duplicate_count": prepared.filtered_duplicate_count,
        "date_already_sent": prepared.date_already_sent,
        "staged": prepared.tempdir is not None,
    }
    module_paths = (
        pre_check_module.DATA_DIR,
        post_check_module.DATA_DIR,
        post_check_module.REPORTS_DIR,
        report_pipeline_module.CONFIG_DIR,
        report_pipeline_module.DATA_DIR,
        report_pipeline_module.REPORTS_DIR,
    )
    try:
        pre_check_module.DATA_DIR = runtime_data_dir
        post_check_module.DATA_DIR = runtime_data_dir
        post_check_module.REPORTS_DIR = runtime_reports_dir
        report_pipeline_module.CONFIG_DIR = runtime_config_dir
        report_pipeline_module.DATA_DIR = runtime_data_dir
        report_pipeline_module.REPORTS_DIR = runtime_reports_dir

        pre_result = pre_check(date_str)
        details["pre_check"] = pre_result
        errors.extend(pre_result.get("errors", []))
        warnings.extend(pre_result.get("warnings", []))

        approved_data = prepared.effective_approved_data

        approved_schema = validate_approved_schema(approved_data) if approved_data else {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "total_checked": 0,
        }
        details["approved_schema"] = approved_schema
        if not approved_schema["is_valid"]:
            errors.extend([f"[approved schema] {error}" for error in approved_schema["errors"]])
        warnings.extend(approved_schema.get("warnings", []))

        details["sent_url_registry"] = prepared.duplicate_check
        if errors and not approved_data:
            details["skipped_after_dedup"] = True
            return {
                "passed": False,
                "errors": errors,
                "warnings": warnings,
                "details": details,
            }

        files = read_report_files(prepared.md_path, prepared.html_path, prepared.email_html_path)
        html_safety = validate_html_safety(files["html_content"])
        email_safety = validate_html_safety(files["email_body"])
        html_template = validate_template_signature(files["html_content"], "H5附件")
        email_template = validate_template_signature(files["email_body"], "邮件HTML")
        details["html_safety"] = html_safety
        details["email_safety"] = email_safety
        details["html_template"] = html_template
        details["email_template"] = email_template
        if not html_safety["is_safe"]:
            errors.extend([f"[HTML安全] {e}" for e in html_safety["errors"]])
        if not email_safety["is_safe"]:
            errors.extend([f"[邮件HTML安全] {e}" for e in email_safety["errors"]])
        if not html_template["is_valid"]:
            errors.extend([f"[模板样式] {e}; 请使用 scripts/generate_from_template.py 生成正式H5" for e in html_template["errors"]])
        if not email_template["is_valid"]:
            errors.extend([f"[模板样式] {e}; 请使用 scripts/generate_from_template.py 生成正式邮件HTML" for e in email_template["errors"]])

        h5_url_consistency = validate_urls_against_approved(
            extract_http_urls(files["html_content"]),
            approved_data,
            label="H5附件",
        )
        details["h5_url_consistency"] = h5_url_consistency
        if not h5_url_consistency["is_consistent"]:
            errors.extend(h5_url_consistency["errors"])

        outbound_urls = list(dict.fromkeys(
            extract_http_urls(files["html_content"])
            + extract_http_urls(files["email_body"])
            + extract_plain_http_urls(files["md_content"])
        ))
        if check_url_health and outbound_urls:
            try:
                url_health = validate_url_health(outbound_urls, label="发送内容", mode=url_health_mode)
            except TypeError:
                url_health = validate_url_health(outbound_urls, label="发送内容")
            details["url_health"] = url_health
            if not url_health["is_valid"]:
                errors.extend(url_health["errors"])
            warnings.extend(url_health.get("warnings", []))
        else:
            details["url_health"] = {
                "is_valid": True,
                "errors": [],
                "checked_urls": [],
                "total_checked": 0,
                "skipped": True,
            }

        validation = run_full_validation(str(prepared.md_path), files["email_body"], approved_data)
        details["full_validation"] = validation
        if not validation.get("can_send_email"):
            schema_errors = set(approved_schema.get("errors", []))
            errors.extend(
                instruction for instruction in validation.get("fix_instructions", [])
                if instruction not in schema_errors
            )

        post_result = post_check(date_str, str(prepared.md_path))
        details["post_check"] = post_result
        errors.extend(post_result.get("errors", []))
        warnings.extend(post_result.get("warnings", []))

        if msg is None:
            msg = build_email_message(
                date_str=date_str,
                sender="gate@example.invalid",
                receiver="gate@example.invalid",
                md_content=files["md_content"],
                html_content=files["html_content"],
                email_body=files["email_body"],
            )
        mime_result = validate_email_mime_type(msg)
        details["mime_check"] = mime_result
        if not mime_result.get("is_valid"):
            errors.extend(mime_result.get("errors", []))
        warnings.extend(mime_result.get("warnings", []))
    finally:
        (
            pre_check_module.DATA_DIR,
            post_check_module.DATA_DIR,
            post_check_module.REPORTS_DIR,
            report_pipeline_module.CONFIG_DIR,
            report_pipeline_module.DATA_DIR,
            report_pipeline_module.REPORTS_DIR,
        ) = module_paths
        if owns_payload:
            prepared.cleanup()

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def _resolve_url_health_config(config: Dict[str, Any]) -> tuple[bool, str]:
    value = config.get("check_url_health", True)
    mode = str(config.get("url_health_mode", "strict") or "strict").lower()
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"false", "off", "no", "0"}:
            return False, mode
        if lowered in {"soft", "strict"}:
            return True, lowered
        if lowered in {"true", "on", "yes", "1"}:
            return True, mode
    return bool(value), mode


def send_daily_report(
    date_str,
    md_path,
    html_path,
    email_html_path=None,
    dry_run=False,
    force_send=False,
    send_mode="manual",
    project_root: str | Path | None = None,
    data_dir: str | Path | None = None,
    config_dir: str | Path | None = None,
):
    """发送日报邮件。发送前必须通过 gate；dry-run 不连接 SMTP。"""
    prepared: PreparedSendPayload | None = None
    try:
        prepared = prepare_send_payload(
            date_str,
            md_path,
            html_path,
            email_html_path,
            force_send=force_send,
            enforce_send_once=not dry_run,
            project_root=project_root,
            data_dir=data_dir,
            config_dir=config_dir,
        )

        try:
            config = load_email_config(prepared.runtime.config_dir)
        except FileNotFoundError:
            if dry_run:
                config = dry_run_email_config()
            else:
                raise
        if not config.get("enabled", True):
            print("邮件发送已禁用 (enabled=false)")
            return False

        should_check_urls, url_health_mode = _resolve_url_health_config(config)
        files = read_report_files(prepared.md_path, prepared.html_path, prepared.email_html_path)
        msg = build_email_message(
            date_str=date_str,
            sender=config["sender_email"],
            receiver=config["receiver_email"],
            md_content=files["md_content"],
            html_content=files["html_content"],
            email_body=files["email_body"],
        )

        gate = validate_send_gate(
            date_str,
            md_path,
            html_path,
            email_html_path,
            msg=msg,
            check_url_health=should_check_urls,
            url_health_mode=url_health_mode,
            force_send=force_send,
            enforce_send_once=not dry_run,
            project_root=project_root,
            data_dir=data_dir,
            config_dir=config_dir,
            prepared_payload=prepared,
        )
        if not gate["passed"]:
            print(f"邮件发送门禁未通过: {len(gate['errors'])} 个错误")
            for error in gate["errors"][:10]:
                print(f"  - {error}")
            return False
        if gate.get("warnings"):
            print(f"邮件发送门禁警告: {len(gate['warnings'])} 个")
            for warning in gate["warnings"][:10]:
                print(f"  - {warning}")

        if dry_run:
            print(f"邮件 dry-run 通过: {date_str}")
            return True

        try:
            send_message_via_smtp(config, msg)
            print(f"邮件发送成功: {date_str}")
            record_send_attempt(
                date_str,
                status="success",
                send_mode=send_mode,
                forced=force_send,
                data_dir=prepared.runtime.data_dir,
                item_count=len(prepared.effective_approved_data),
            )
            try:
                _update_history_index(
                    date_str,
                    prepared.effective_approved_data,
                    data_dir=prepared.runtime.data_dir,
                )
            except Exception as e:
                print(f"历史索引更新失败（非阻断）: {e}")
            return True
        except smtplib.SMTPResponseException as exc:
            print_smtp_diagnostics(exc)
            failure_error = f"SMTP {exc.smtp_code}: {exc.smtp_error!r}"
            if exc.smtp_code == 500 and config.get("allow_simple_fallback", False):
                try:
                    fallback_msg = build_simple_fallback_message(
                        date_str=date_str,
                        sender=config["sender_email"],
                        receiver=config["receiver_email"],
                        email_body=files["email_body"],
                    )
                    send_message_via_smtp(config, fallback_msg)
                    print("邮件已降级发送：仅HTML正文，无附件。请检查SMTP MIME兼容性。")
                    record_send_attempt(
                        date_str,
                        status="success",
                        send_mode=send_mode,
                        forced=force_send,
                        data_dir=prepared.runtime.data_dir,
                        item_count=len(prepared.effective_approved_data),
                    )
                    try:
                        _update_history_index(
                            date_str,
                            prepared.effective_approved_data,
                            data_dir=prepared.runtime.data_dir,
                        )
                    except Exception as e:
                        print(f"历史索引更新失败（非阻断）: {e}")
                    return True
                except Exception as fallback_exc:
                    print(f"邮件降级发送失败: {fallback_exc}")
                    failure_error = f"{failure_error}; fallback failed: {fallback_exc}"
            record_send_attempt(
                date_str,
                status="failed",
                send_mode=send_mode,
                forced=force_send,
                error=failure_error,
                data_dir=prepared.runtime.data_dir,
                item_count=len(prepared.effective_approved_data),
            )
            return False
        except Exception as e:
            print(f"邮件发送失败: {e}")
            record_send_attempt(
                date_str,
                status="failed",
                send_mode=send_mode,
                forced=force_send,
                error=str(e),
                data_dir=prepared.runtime.data_dir,
                item_count=len(prepared.effective_approved_data),
            )
            return False
    finally:
        if prepared is not None:
            prepared.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send synbio daily report after validation gate")
    parser.add_argument("date")
    parser.add_argument("md_path")
    parser.add_argument("html_path")
    parser.add_argument("email_html_path", nargs="?")
    parser.add_argument("--dry-run", action="store_true", help="run gate and build email without SMTP")
    parser.add_argument("--force-send", action="store_true", help="allow a real resend for a date already recorded as sent")
    parser.add_argument("--send-mode", choices=["manual", "auto"], default="manual", help="send attempt label written to send_log.json")
    parser.add_argument("--project-root", help="override runtime project root used for data/config/reports lookup")
    parser.add_argument("--data-dir", help="override runtime data directory")
    parser.add_argument("--config-dir", help="override runtime config directory")
    args = parser.parse_args()

    success = send_daily_report(
        args.date,
        args.md_path,
        args.html_path,
        args.email_html_path,
        dry_run=args.dry_run,
        force_send=args.force_send,
        send_mode=args.send_mode,
        project_root=args.project_root,
        data_dir=args.data_dir,
        config_dir=args.config_dir,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
