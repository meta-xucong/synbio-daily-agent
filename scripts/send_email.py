#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成生物行业日报 - 邮件发送脚本"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from .settings import CONFIG_DIR, DATA_DIR
    from .console_utils import ensure_utf8_console
    from . import pre_check as pre_check_module
    from . import post_check as post_check_module
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


def load_email_config() -> Dict[str, Any]:
    """从配置文件读取邮件配置"""
    config_path = CONFIG_DIR / "email_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"邮件配置文件不存在: {config_path}")
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


def load_approved_data(date_str: str) -> list[dict[str, Any]]:
    """Load approved data for the send gate."""
    approved_path = DATA_DIR / f"approved_{date_str}.json"
    if not approved_path.exists():
        raise FileNotFoundError(f"approved数据不存在: {approved_path}")
    with open(approved_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"approved数据必须是列表: {approved_path}")
    return data


def _update_history_index(date_str: str, approved_items: list[dict[str, Any]]) -> None:
    """发送成功后，将 approved 条目追加到 history_index.json 以实现跨天持久化去重。"""
    history_path = DATA_DIR / "history_index.json"
    history = {"version": 1, "entries": []}
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    existing_urls = set()
    existing_url_keys = set()
    for entry in history.get("entries", []):
        entry_urls = report_pipeline_module._item_candidate_urls(entry)
        entry_urls.append(entry.get("canonical_url", ""))
        existing_urls.update(
            report_pipeline_module.canonicalize_url(url)
            for url in entry_urls
            if url
        )
        if entry.get("dedup_key"):
            existing_url_keys.add(str(entry.get("dedup_key")))
        existing_url_keys.update(
            report_pipeline_module.url_dedup_key(url)
            for url in entry_urls
            if url
        )

    for item in approved_items:
        title = item.get("title", "")
        item_urls = report_pipeline_module._item_candidate_urls(item)
        new_urls = [
            url for url in item_urls
            if report_pipeline_module.canonicalize_url(url) not in existing_urls
            and report_pipeline_module.url_dedup_key(url) not in existing_url_keys
        ]
        if not title or not new_urls:
            continue
        fingerprint = report_pipeline_module._make_fingerprint(item)
        for url in new_urls:
            canonical_url = report_pipeline_module.canonicalize_url(url)
            dedup_key = report_pipeline_module.url_dedup_key(url)
            history["entries"].append({
                "url": url,
                "canonical_url": canonical_url,
                "dedup_key": dedup_key,
                "urls": item_urls,
                "title": title[:120],
                "fingerprint": fingerprint,
                "date": item.get("date", ""),
                "first_sent_date": date_str,
            })
            existing_urls.add(canonical_url)
            existing_url_keys.add(dedup_key)

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    report_pipeline_module.update_sent_url_registry(date_str, approved_items, data_dir=DATA_DIR)
    print(f"历史索引已更新: {len(history['entries'])} 条")


def _send_log_path() -> Path:
    return DATA_DIR / "send_log.json"


def _load_send_log() -> dict[str, Any]:
    path = _send_log_path()
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


def _write_send_log(log: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_send_log_path(), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def has_successful_send_for_date(date_str: str) -> bool:
    """Return True when the report date already has a successful real send."""
    log = _load_send_log()
    if any(entry.get("date") == date_str and entry.get("status") == "success" for entry in log.get("sends", [])):
        return True

    history_path = DATA_DIR / "history_index.json"
    if not history_path.exists():
        return False
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return False
    return any(entry.get("first_sent_date") == date_str for entry in history.get("entries", []))


def record_send_attempt(date_str: str, *, status: str, send_mode: str, forced: bool, error: str = "") -> None:
    """Append a report-level send attempt for duplicate-send auditing."""
    log = _load_send_log()
    log.setdefault("version", 1)
    log.setdefault("sends", [])
    log["sends"].append({
        "date": date_str,
        "status": status,
        "send_mode": send_mode,
        "forced": forced,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "error": error,
    })
    _write_send_log(log)


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
) -> Dict[str, Any]:
    """Run all checks required before any SMTP connection is opened."""
    errors: list[str] = []
    warnings: list[str] = []
    details: Dict[str, Any] = {}

    report_path = Path(md_path)
    runtime_data_dir = DATA_DIR
    runtime_reports_dir = report_path.parent
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
        report_pipeline_module.CONFIG_DIR = CONFIG_DIR
        report_pipeline_module.DATA_DIR = runtime_data_dir
        report_pipeline_module.REPORTS_DIR = runtime_reports_dir

        if has_successful_send_for_date(date_str):
            duplicate_message = f"[发送门禁] 日期 {date_str} 已发送过日报，禁止重复发送"
            if force_send:
                warnings.append(f"{duplicate_message}；已使用 force_send 显式放行")
            elif not enforce_send_once:
                warnings.append(f"{duplicate_message}；当前为验证模式，不阻断")
            else:
                errors.append(duplicate_message)

        pre_result = pre_check(date_str)
        details["pre_check"] = pre_result
        errors.extend(pre_result.get("errors", []))
        warnings.extend(pre_result.get("warnings", []))

        try:
            approved_data = load_approved_data(date_str)
        except Exception as exc:
            approved_data = []
            errors.append(str(exc))

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

        sent_url_check = validate_approved_not_previously_sent(
            approved_data,
            data_dir=runtime_data_dir,
            label="发送门禁approved",
        ) if approved_data else {
            "is_valid": True,
            "errors": [],
            "checked": [],
            "total_checked": 0,
        }
        details["sent_url_registry"] = sent_url_check
        if not sent_url_check["is_valid"]:
            if force_send:
                warnings.extend([f"[URL去重] {error}；已使用 force_send 显式放行" for error in sent_url_check["errors"]])
            elif not enforce_send_once:
                warnings.extend([f"[URL去重] {error}；当前为验证模式，不阻断" for error in sent_url_check["errors"]])
            else:
                errors.extend([f"[URL去重] {error}" for error in sent_url_check["errors"]])

        files = read_report_files(md_path, html_path, email_html_path)
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

        validation = run_full_validation(str(md_path), files["email_body"], approved_data)
        details["full_validation"] = validation
        if not validation.get("can_send_email"):
            schema_errors = set(approved_schema.get("errors", []))
            errors.extend(
                instruction for instruction in validation.get("fix_instructions", [])
                if instruction not in schema_errors
            )

        post_result = post_check(date_str, str(md_path))
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
):
    """发送日报邮件。发送前必须通过 gate；dry-run 不连接 SMTP。"""
    try:
        config = load_email_config()
    except FileNotFoundError:
        if dry_run:
            config = dry_run_email_config()
        else:
            raise
    if not config.get("enabled", True):
        print("邮件发送已禁用 (enabled=false)")
        return False

    should_check_urls, url_health_mode = _resolve_url_health_config(config)
    files = read_report_files(md_path, html_path, email_html_path)
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
        record_send_attempt(date_str, status="success", send_mode=send_mode, forced=force_send)
        # 发送成功后更新跨天历史索引
        try:
            approved_data = load_approved_data(date_str)
            _update_history_index(date_str, approved_data)
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
                record_send_attempt(date_str, status="success", send_mode=send_mode, forced=force_send)
                try:
                    approved_data = load_approved_data(date_str)
                    _update_history_index(date_str, approved_data)
                except Exception as e:
                    print(f"历史索引更新失败（非阻断）: {e}")
                return True
            except Exception as fallback_exc:
                print(f"邮件降级发送失败: {fallback_exc}")
                failure_error = f"{failure_error}; fallback failed: {fallback_exc}"
        record_send_attempt(date_str, status="failed", send_mode=send_mode, forced=force_send, error=failure_error)
        return False
    except Exception as e:
        print(f"邮件发送失败: {e}")
        record_send_attempt(date_str, status="failed", send_mode=send_mode, forced=force_send, error=str(e))
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Send synbio daily report after validation gate")
    parser.add_argument("date")
    parser.add_argument("md_path")
    parser.add_argument("html_path")
    parser.add_argument("email_html_path", nargs="?")
    parser.add_argument("--dry-run", action="store_true", help="run gate and build email without SMTP")
    parser.add_argument("--force-send", action="store_true", help="allow a real resend for a date already recorded as sent")
    parser.add_argument("--send-mode", choices=["manual", "auto"], default="manual", help="send attempt label written to send_log.json")
    args = parser.parse_args()

    success = send_daily_report(
        args.date,
        args.md_path,
        args.html_path,
        args.email_html_path,
        dry_run=args.dry_run,
        force_send=args.force_send,
        send_mode=args.send_mode,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
