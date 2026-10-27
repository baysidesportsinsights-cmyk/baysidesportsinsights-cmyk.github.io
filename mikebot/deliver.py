"""Delivery channels. Each one is off unless its secrets are set:

  Email   MIKEBOT_SMTP_USER, MIKEBOT_SMTP_PASSWORD (Gmail app password),
          MIKEBOT_EMAIL_TO (comma-separated), optional MIKEBOT_SMTP_HOST
  Discord MIKEBOT_DISCORD_WEBHOOK
"""

import json
import os
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage

from .http import UA


def email_configured():
    return all(os.environ.get(k) for k in ("MIKEBOT_SMTP_USER", "MIKEBOT_SMTP_PASSWORD", "MIKEBOT_EMAIL_TO"))


def send_email(subject, html, text):
    if not email_configured():
        return "email: not configured"
    user = os.environ["MIKEBOT_SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"MikeBot <{user}>", os.environ["MIKEBOT_EMAIL_TO"]
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    host = os.environ.get("MIKEBOT_SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(user, os.environ["MIKEBOT_SMTP_PASSWORD"])
        s.send_message(msg)
    return "email: sent"


def send_discord(text):
    hook = os.environ.get("MIKEBOT_DISCORD_WEBHOOK")
    if not hook:
        return "discord: not configured"
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > 1900:
            chunks.append(cur)
            cur = ""
        cur += line
    chunks.append(cur)
    for c in chunks:
        body = json.dumps({"username": "MikeBot", "content": c, "allowed_mentions": {"parse": []}}).encode()
        req = urllib.request.Request(hook, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
        urllib.request.urlopen(req, timeout=20).read()
    return f"discord: sent {len(chunks)} message(s)"
