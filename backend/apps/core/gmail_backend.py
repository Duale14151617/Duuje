"""Django email backend that sends through the Gmail API over HTTPS (port 443).

Use it where outgoing SMTP is blocked (Render's free web services block 25/465/587) and no sending domain is available. Enabled
automatically when GMAIL_REFRESH_TOKEN, GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are all set. Messages go out from the Gmail account
that granted the token; the From address is forced to that account (Gmail rewrites any other). Standard library only.
"""
import base64
import json
import threading
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage as MimeMessage
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

_lock = threading.Lock()
_cache = {"token": "", "expires": 0.0}


def _access_token():
    """A short-lived access token from the refresh token, cached until shortly before it expires."""
    with _lock:
        if _cache["token"] and time.time() < _cache["expires"] - 60:
            return _cache["token"]
        data = urllib.parse.urlencode({
            "client_id": settings.GMAIL_CLIENT_ID, "client_secret": settings.GMAIL_CLIENT_SECRET,
            "refresh_token": settings.GMAIL_REFRESH_TOKEN, "grant_type": "refresh_token"}).encode()
        request = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:  # noqa: S310 - fixed https URL
            payload = json.loads(response.read())
        _cache["token"] = payload["access_token"]
        _cache["expires"] = time.time() + int(payload.get("expires_in", 3600))
        return _cache["token"]


class GmailApiEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            try:
                if message.to and self._send(message):
                    sent += 1
            except Exception:  # urllib raises on 4xx/5xx and on timeouts; callers decide what a failed send means
                if not self.fail_silently:
                    raise
        return sent

    @staticmethod
    def _send(message):
        name, address = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
        mime = MimeMessage()
        mime["To"] = ", ".join(message.to)
        mime["From"] = formataddr((name, address)) if name else address
        mime["Subject"] = message.subject
        mime.set_content(message.body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        request = urllib.request.Request(
            SEND_URL, data=json.dumps({"raw": raw}).encode(), method="POST",
            headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=settings.EMAIL_TIMEOUT):  # noqa: S310 - fixed https URL
            return True
