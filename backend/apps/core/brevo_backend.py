"""Django email backend that sends through Brevo's transactional API over HTTPS (port 443).

Use it where outgoing SMTP is blocked (Render's free web services block 25/465/587). Enabled automatically when BREVO_API_KEY is
set. DEFAULT_FROM_EMAIL must be a sender address verified in Brevo. Uses only the standard library, so there is nothing to install.
"""
import json
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

ENDPOINT = "https://api.brevo.com/v3/smtp/email"


class BrevoEmailBackend(BaseEmailBackend):
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
        sender = {"email": address}
        if name:
            sender["name"] = name
        body = {"sender": sender, "to": [{"email": a} for a in message.to], "subject": message.subject, "textContent": message.body}
        request = urllib.request.Request(
            ENDPOINT, data=json.dumps(body).encode(), method="POST",
            headers={"api-key": settings.BREVO_API_KEY, "content-type": "application/json", "accept": "application/json"})
        with urllib.request.urlopen(request, timeout=settings.EMAIL_TIMEOUT):  # noqa: S310 - fixed https URL
            return True
