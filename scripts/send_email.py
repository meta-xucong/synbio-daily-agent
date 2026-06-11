#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合成生物行业日报 - 邮件发送脚本
"""

import smtplib
import sys
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

def load_email_config():
    """从配置文件读取邮件配置"""
    config_path = Path(r"D:\AI\合成生物行业报告\config\email_config.json")
    if not config_path.exists():
        raise FileNotFoundError(f"邮件配置文件不存在: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def send_daily_report(date_str, md_path, html_path, email_html_path=None):
    """发送日报邮件"""
    
    # 读取邮件配置
    config = load_email_config()
    smtp_server = config["smtp_server"]
    smtp_port = config["smtp_port"]
    sender = config["sender_email"]
    password = config["sender_password"]
    receiver = config["receiver_email"]
    
    if not config.get("enabled", True):
        print("邮件发送已禁用 (enabled=false)")
        return False
    
    # 读取文件
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 创建邮件
    msg = MIMEMultipart('related')
    msg['Subject'] = f'合成生物行业日报 - {date_str}'
    msg['From'] = sender
    msg['To'] = receiver
    
    # 邮件正文（HTML）
    if email_html_path and Path(email_html_path).exists():
        with open(email_html_path, 'r', encoding='utf-8') as f:
            email_body = f.read()
    else:
        email_body = html_content
    
    msg.attach(MIMEText(email_body, 'html', 'utf-8'))
    
    # HTML附件 - 必须使用 text/html MIME类型
    html_attachment = MIMEText(html_content, 'html', 'utf-8')
    html_attachment.add_header('Content-Disposition', 'attachment', filename=f'synbio_daily_{date_str}.html')
    msg.attach(html_attachment)
    
    # Markdown附件 - 必须使用 text/plain MIME类型
    md_attachment = MIMEText(md_content, 'plain', 'utf-8')
    md_attachment.add_header('Content-Disposition', 'attachment', filename=f'synbio_daily_{date_str}.md')
    msg.attach(md_attachment)
    
    # 发送邮件
    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender, password)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        print(f"邮件发送成功: {date_str}")
        return True
    except Exception as e:
        print(f"邮件发送失败: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python send_email.py <date> <md_path> <html_path> [email_html_path]")
        sys.exit(1)
    
    date_str = sys.argv[1]
    md_path = sys.argv[2]
    html_path = sys.argv[3]
    email_html_path = sys.argv[4] if len(sys.argv) > 4 else None
    
    success = send_daily_report(date_str, md_path, html_path, email_html_path)
    sys.exit(0 if success else 1)
