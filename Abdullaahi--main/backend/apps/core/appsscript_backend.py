"""Django email backend that sends through a Google Apps Script web app over HTTPS (port 443).

For a Gmail sender when SMTP is blocked (Render's free web services) and no sending domain or Google Cloud project is available. The
script (see docs/APPS_SCRIPT_MAILER.md) runs as the Gmail account and calls MailApp.sendEmail. Enabled automatically when
APPS_SCRIPT_URL and APPS_SCRIPT_TOKEN are set. Standard library only.
"""
import json
import urllib.request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class AppsScriptEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            try:
                if message.to and self._send(message):
                    sent += 1
            except Exception:  # callers decide what a failed send means
                if not self.fail_silently:
                    raise
        return sent

    @staticmethod
    def _send(message):
        body = {"token": settings.APPS_SCRIPT_TOKEN, "to": ",".join(message.to), "subject": message.subject, "body": message.body}
        request = urllib.request.Request(
            settings.APPS_SCRIPT_URL, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "text/plain"})
        # Apps Script answers the POST with a redirect to the result; the mail is sent by then, and the redirect is followed with GET.
        with urllib.request.urlopen(request, timeout=max(settings.EMAIL_TIMEOUT, 20)) as response:  # noqa: S310 - https URL from settings
            if response.read().decode().strip() != "ok":
                raise RuntimeError("mail script refused the message")
        return True
