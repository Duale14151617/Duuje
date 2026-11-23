"""Show how outgoing email is configured and (optionally) send a test message.

    python manage.py check_email                 # print the configuration and what is switched on
    python manage.py check_email you@example.com # also send a test message to that address

Email verification and "Forgot your password?" only work when a real email backend is configured; with the console backend the
codes are printed in the server log and never reach anyone."""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

BACKENDS = {
    "apps.core.brevo_backend.BrevoEmailBackend": "Brevo (HTTPS API)",
    "django.core.mail.backends.smtp.EmailBackend": "SMTP",
    "django.core.mail.backends.console.EmailBackend": "CONSOLE ONLY (nothing is delivered)",
}


class Command(BaseCommand):
    help = "Show the email configuration and optionally send a test message."

    def add_arguments(self, parser):
        parser.add_argument("to", nargs="?", help="address to send a test message to")

    def handle(self, *args, to=None, **opts):
        backend = BACKENDS.get(settings.EMAIL_BACKEND, settings.EMAIL_BACKEND)
        real = settings.EMAIL_BACKEND != "django.core.mail.backends.console.EmailBackend"
        out = self.stdout.write
        out(f"Backend:               {backend}")
        if settings.EMAIL_BACKEND.endswith("smtp.EmailBackend"):
            out(f"SMTP host / port:      {settings.EMAIL_HOST}:{settings.EMAIL_PORT} (TLS={settings.EMAIL_USE_TLS}, user set={bool(settings.EMAIL_HOST_USER)})")
        out(f"From address:          {settings.DEFAULT_FROM_EMAIL}")
        out(f"EMAIL_VERIFICATION:    {'on' if settings.EMAIL_VERIFICATION_ENABLED else 'OFF'}")
        out(f"PASSWORD_FORGOT:       {'on' if settings.PASSWORD_FORGOT_ENABLED else 'OFF'}")
        out(f"MFA_EMAIL_RECOVERY:    {'on' if settings.MFA_EMAIL_RECOVERY_ENABLED else 'off'}")
        out(f"Temporary passwords:   expire after {settings.TEMP_PASSWORD_DAYS} days")
        problems = []
        if not real:
            problems.append("No real email backend: set BREVO_API_KEY, or EMAIL_HOST (+ EMAIL_HOST_USER / EMAIL_HOST_PASSWORD).")
        if settings.DEFAULT_FROM_EMAIL.endswith(".invalid"):
            problems.append("DEFAULT_FROM_EMAIL is still the placeholder; set a sender address your provider has verified.")
        if not settings.EMAIL_VERIFICATION_ENABLED:
            problems.append("EMAIL_VERIFICATION_ENABLED is off: users cannot verify their address.")
        if not settings.PASSWORD_FORGOT_ENABLED:
            problems.append("PASSWORD_FORGOT_ENABLED is off: the sign-in page has no 'Forgot your password?'.")
        for p in problems:
            self.stderr.write(f"! {p}")
        if to:
            try:
                n = send_mail("Duuje email test", "If you can read this, outgoing email works.", None, [to], fail_silently=False)
            except Exception as exc:  # report any provider/network error plainly
                raise CommandError(f"Sending failed: {exc}")
            out(f"Test message {'sent' if n else 'NOT sent'} to {to}." + ("" if real else " (console backend: see the output above, nothing was delivered)"))
        if not problems:
            out("Email looks ready.")
