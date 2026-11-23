"""The Gmail-through-Google-Apps-Script mail backend (docs/APPS_SCRIPT_MAILER.md)."""
import json
from unittest import mock

from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings

from apps.core.appsscript_backend import AppsScriptEmailBackend

SETTINGS = dict(APPS_SCRIPT_URL="https://script.google.com/macros/s/x/exec", APPS_SCRIPT_TOKEN="secret-token")


class _Response:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.text.encode()


@override_settings(**SETTINGS)
class AppsScriptBackendTests(SimpleTestCase):
    def test_posts_token_and_message_and_counts_sent(self):
        with mock.patch("urllib.request.urlopen", return_value=_Response("ok")) as urlopen:
            sent = AppsScriptEmailBackend().send_messages([EmailMessage("Subject", "Body", to=["a@example.org", "b@example.org"])])
        self.assertEqual(sent, 1)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, SETTINGS["APPS_SCRIPT_URL"])
        self.assertEqual(json.loads(request.data), {"token": "secret-token", "to": "a@example.org,b@example.org", "subject": "Subject", "body": "Body"})

    def test_refusal_raises_unless_fail_silently(self):
        message = EmailMessage("S", "B", to=["a@example.org"])
        with mock.patch("urllib.request.urlopen", return_value=_Response("forbidden")):
            with self.assertRaises(RuntimeError):
                AppsScriptEmailBackend().send_messages([message])
            self.assertEqual(AppsScriptEmailBackend(fail_silently=True).send_messages([message]), 0)

    def test_message_without_recipients_is_skipped(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.assertEqual(AppsScriptEmailBackend().send_messages([EmailMessage("S", "B", to=[])]), 0)
        urlopen.assert_not_called()
