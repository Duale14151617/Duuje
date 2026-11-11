from datetime import timedelta

import hashlib
import hmac
import secrets
import time

import pyotp
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F, Q
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record
from apps.core.errors import field_error
from apps.core import crypto

from . import scope
from .models import EmailVerificationCode, MfaRecoveryCode, PasswordResetToken, Role, RoleAssignment, User
from .permissions import ScopedPermission
from .security import consume_totp, restrictions
from .serializers import (AssignmentCreateSerializer, AssignmentSerializer, EmailVerifyConfirmSerializer, EmailVerifyRequestSerializer,
                          LoginSerializer, PasswordForgotSerializer,
                          MfaConfirmSerializer, MfaRecoveryRedeemSerializer, MfaRecoveryRequestSerializer, PasswordChangeSerializer, PasswordResetRedeemSerializer,
                          PasswordResetSerializer,
                          RoleSerializer, UserCreateSerializer, UserSerializer, UserUpdateSerializer,
                          check_password_strength)
from .services import other_admins_exist, revoke_user_sessions

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


def me_payload(user):
    from apps.personnel.models import Personnel  # local import: personnel depends on accounts
    return {
        "id": str(user.pk),
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
        "preferred_language": user.preferred_language,
        "mfa_enabled": user.mfa_enabled,
        "requires_mfa": scope.requires_mfa(user),
        "restrictions": restrictions(user),
        "permissions": sorted(scope.permission_codes(user)),
        "features": {"personnel_export": settings.PERSONNEL_EXPORT_ENABLED,
                     "report_export": settings.REPORT_EXPORT_ENABLED,
                     "integrations": settings.INTEGRATIONS_ENABLED,
                     "email_verification": settings.EMAIL_VERIFICATION_ENABLED},
        "assignments": AssignmentSerializer(scope.assignments(user), many=True).data,
        # The personnel record this login belongs to (null when none is linked); drives the "My record" shortcut.
        "personnel_id": next((str(pk) for pk in Personnel.objects.filter(account_id=user.pk).values_list("pk", flat=True)[:1]), None),
    }


def enforce_csrf(request):
    SessionAuthentication().enforce_csrf(request)


def error(code, detail, http_status):
    return Response({"code": code, "detail": detail}, status=http_status)


class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request._request)})


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request):
        enforce_csrf(request)
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        username = ser.validated_data["username"].strip().lower()
        password = ser.validated_data["password"]
        otp = ser.validated_data.get("otp", "").strip()
        now = timezone.now()
        user = User.objects.filter(username=username).first()
        bad = error("invalid_credentials", "Invalid username or password.", status.HTTP_401_UNAUTHORIZED)

        if user and user.locked_until and user.locked_until > now:
            User().set_password(password)  # spend the same hashing time as a real attempt: no timing oracle for locked accounts
            record("auth.login", request=request, actor=user, outcome="denied", entity_type="user",
                   entity_id=user.pk, metadata={"reason": "locked"})
            return bad

        authed = authenticate(request, username=username, password=password)
        if authed is None:
            self._register_failure(request, user, "bad_password")
            return bad

        if authed.mfa_enabled:
            if not otp:
                return Response({"code": "otp_required", "detail": "Enter the code from your authenticator app.",
                                 "email_recovery": settings.MFA_EMAIL_RECOVERY_ENABLED}, status=401)
            if not consume_totp(authed, otp):
                self._register_failure(request, authed, "bad_otp")
                return error("invalid_otp", "That code is not valid.", 401)

        with transaction.atomic():
            User.objects.filter(pk=authed.pk).update(failed_login_count=0, locked_until=None)
            login(request, authed)
            request.session["auth_epoch"] = authed.auth_epoch
            request.session["login_at"] = int(time.time())
            record("auth.login", request=request, actor=authed, entity_type="user", entity_id=authed.pk)
        return Response(me_payload(authed))

    @staticmethod
    def _register_failure(request, user, reason):
        if user is None:
            record("auth.login", request=request, outcome="failure", metadata={"reason": "unknown_user"})
            return
        User.objects.filter(pk=user.pk).update(failed_login_count=F("failed_login_count") + 1)
        user.refresh_from_db(fields=["failed_login_count"])
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            User.objects.filter(pk=user.pk).update(
                failed_login_count=0, locked_until=timezone.now() + timedelta(minutes=LOCK_MINUTES))
            reason += "+locked"
        record("auth.login", request=request, actor=user, outcome="failure", entity_type="user",
               entity_id=user.pk, metadata={"reason": reason})


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            record("auth.logout", request=request, entity_type="user", entity_id=request.user.pk)
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    allow_restricted = True

    def get(self, request):
        return Response(me_payload(request.user))

    def patch(self, request):
        lang = request.data.get("preferred_language")
        if lang not in ("en", "so"):
            raise field_error("preferred_language", "invalid_choice", "Choose en or so.")
        User.objects.filter(pk=request.user.pk).update(preferred_language=lang)
        request.user.preferred_language = lang
        return Response(me_payload(request.user))


class PasswordChangeView(APIView):
    allow_restricted = True
    throttle_scope = "login"

    def post(self, request):
        ser = PasswordChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = request.user
        current, new = ser.validated_data["current_password"], ser.validated_data["new_password"]
        # Failure audit events are written *outside* any transaction that a raised
        # error would roll back.
        if not user.check_password(current):
            record("auth.password_change", request=request, outcome="failure", entity_type="user", entity_id=user.pk)
            raise field_error("current_password", "wrong_password", "Incorrect password.")
        if new == current:
            raise field_error("new_password", "same_password", "Choose a different password.")
        check_password_strength(new, user=user)
        with transaction.atomic():
            user.set_password(new)
            user.must_change_password = False
            user.auth_epoch += 1  # signs out every other session
            user.save(update_fields=["password", "must_change_password", "auth_epoch", "updated_at"])
            update_session_auth_hash(request, user)
            request.session["auth_epoch"] = user.auth_epoch
            record("auth.password_change", request=request, entity_type="user", entity_id=user.pk)
        return Response(me_payload(user))


class MfaSetupView(APIView):
    allow_restricted = True
    throttle_scope = "mfa"

    def post(self, request):
        user = request.user
        if user.mfa_enabled:
            return error("mfa_already_enabled", "MFA is already enabled.", 409)
        # Reuse an unconfirmed secret so repeated setup attempts (or a page reload) don't pile up
        # dead entries in the authenticator app. It rotates only once enrolment is reset.
        secret = None
        if user.mfa_secret_enc:
            try:
                secret = crypto.decrypt(user.mfa_secret_enc)
            except Exception:
                secret = None
        if not secret:
            secret = pyotp.random_base32()
            User.objects.filter(pk=user.pk).update(mfa_secret_enc=crypto.encrypt(secret))
        uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="Puntland Defence Forces HQ")
        return Response({"secret": secret, "otpauth_uri": uri})


class MfaConfirmView(APIView):
    allow_restricted = True
    throttle_scope = "mfa"

    def post(self, request):
        ser = MfaConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = User.objects.get(pk=request.user.pk)
        if user.mfa_enabled or not user.mfa_secret_enc:
            return error("mfa_not_pending", "Start MFA setup first.", 409)
        if not consume_totp(user, ser.validated_data["code"]):
            record("mfa.enable", request=request, outcome="failure", entity_type="user", entity_id=user.pk)
            raise field_error("code", "invalid_otp", "That code is not valid.")
        with transaction.atomic():
            User.objects.filter(pk=user.pk).update(mfa_enabled=True)
            record("mfa.enable", request=request, entity_type="user", entity_id=user.pk)
        return Response(me_payload(User.objects.get(pk=user.pk)))


RESET_CODE_MINUTES = 60


def _hash_code(code):
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


class PasswordResetView(APIView):
    """Redeem an administrator-issued one-time code. Every failure looks identical."""

    permission_classes = [AllowAny]
    throttle_scope = "reset"

    def post(self, request):
        enforce_csrf(request)
        ser = PasswordResetRedeemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        fail = error("invalid_reset", "That reset code is not valid or has expired.", status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(username=d["username"].strip().lower(), is_active=True).first()
        token = None
        if user is not None:
            token = PasswordResetToken.objects.filter(
                user=user, token_hash=_hash_code(d["code"]), used_at__isnull=True, expires_at__gt=timezone.now()).first()
        if token is None:
            record("auth.password_reset", request=request, actor=user, outcome="failure",
                   entity_type="user", entity_id=user.pk if user else "")
            return fail
        if token.created_by_id is None and user.mfa_enabled:
            # A code that was emailed to the account (self-service) must not be a way around the authenticator app.
            # Codes issued by an administrator are handed over through a trusted channel and keep working as before.
            otp = (d.get("otp") or "").strip()
            if not otp:
                return error("otp_required", "Enter the code from your authenticator app.", status.HTTP_401_UNAUTHORIZED)  # the code is NOT burned
            if not consume_totp(user, otp):
                LoginView._register_failure(request, user, "bad_otp_reset")
                return error("invalid_otp", "That code is not valid.", status.HTTP_401_UNAUTHORIZED)
        check_password_strength(d["new_password"], user=user)  # a weak password must not burn the code
        with transaction.atomic():
            used = PasswordResetToken.objects.filter(pk=token.pk, used_at__isnull=True).update(used_at=timezone.now())
            if used != 1:  # lost a race with another redemption
                return fail
            user.set_password(d["new_password"])
            user.must_change_password = False
            user.failed_login_count = 0
            user.locked_until = None
            user.save(update_fields=["password", "must_change_password", "failed_login_count", "locked_until", "updated_at"])
            revoke_user_sessions(user)
            record("auth.password_reset", request=request, actor=user, entity_type="user", entity_id=user.pk,
                   metadata={"via": "admin_code" if token.created_by_id else "email_code"})
        if user.email and user.email_verified_at:
            _send_mail(user.email, "Puntland Defence Forces HQ: your password was changed",
                       "The password on your account was just changed and every session was signed out. "
                       "If this was not you, tell your administrator now.")
        return Response(status=204)


def _recovery_enabled_or_404():
    if not settings.MFA_EMAIL_RECOVERY_ENABLED:
        return error("not_available", "Email recovery is not available.", status.HTTP_404_NOT_FOUND)
    return None


def _send_mail(address, subject, body):
    """Never raises: a mail failure is audited by the caller's generic path and must not reveal anything to the requester."""
    try:
        send_mail(subject, body, None, [address], fail_silently=False)
        return True
    except Exception:
        return False


def _send_recovery_mail(user, subject, body):
    return _send_mail(user.email, subject, body)


class MfaRecoveryRequestView(APIView):
    """Lost authenticator app, step 1: email a one-time code. Needs the correct password, and the answer is the same whether or
    not a code was sent, so it cannot be used to find out which accounts exist or have an email address."""

    permission_classes = [AllowAny]
    throttle_scope = "recover"

    def post(self, request):
        enforce_csrf(request)
        unavailable = _recovery_enabled_or_404()
        if unavailable:
            return unavailable
        ser = MfaRecoveryRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        username = ser.validated_data["username"].strip().lower()
        user = User.objects.filter(username=username).first()
        generic = Response({"detail": "If the details are right and the account has an email address, a code has been sent."})
        if user and user.locked_until and user.locked_until > timezone.now():
            User().set_password(ser.validated_data["password"])
            return generic
        authed = authenticate(request, username=username, password=ser.validated_data["password"])
        if authed is None:
            LoginView._register_failure(request, user, "bad_password_recovery")
            return generic
        if not (authed.mfa_enabled and authed.email):
            # The password was right, so say plainly what is missing (the normal sign-in already reveals a correct password).
            # Wrong passwords and unknown usernames still get the generic answer above.
            reason = "no_mfa" if not authed.mfa_enabled else "no_email"
            record("auth.mfa_recovery_request", request=request, actor=authed, outcome="denied", entity_type="user",
                   entity_id=authed.pk, metadata={"reason": reason})
            if reason == "no_mfa":
                return error("recovery_no_mfa", "This account does not use an authenticator app, so there is nothing to recover.", 400)
            return error("recovery_no_email", "This account has no email address. Ask an administrator to reset your authenticator.", 400)
        code = secrets.token_hex(5).upper()  # 40 bits; single use, short-lived, rate-limited, and tied to the password
        minutes = settings.MFA_RECOVERY_CODE_MINUTES
        with transaction.atomic():
            MfaRecoveryCode.objects.filter(user=authed, used_at__isnull=True).update(used_at=timezone.now())  # supersede older codes
            MfaRecoveryCode.objects.create(user=authed, code_hash=_hash_code(code),
                                           expires_at=timezone.now() + timedelta(minutes=minutes))
        sent = _send_recovery_mail(
            authed, "Puntland Defence Forces HQ: your recovery code",
            f"Your one-time recovery code is {code}\n\nIt works once and expires in {minutes} minutes. Use it to reset your "
            "authenticator app. If you did not ask for this, ignore this email and tell your administrator.")
        record("auth.mfa_recovery_request", request=request, actor=authed, outcome="success" if sent else "failure",
               entity_type="user", entity_id=authed.pk)
        return generic


class MfaRecoveryRedeemView(APIView):
    """Lost authenticator app, step 2: password + emailed code removes the old enrolment and ends every session. The user then
    signs in with the password alone and must enrol a new authenticator (privileged roles are held on that screen until they do)."""

    permission_classes = [AllowAny]
    throttle_scope = "recover"

    def post(self, request):
        enforce_csrf(request)
        unavailable = _recovery_enabled_or_404()
        if unavailable:
            return unavailable
        ser = MfaRecoveryRedeemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        username = d["username"].strip().lower()
        fail = error("invalid_recovery", "That recovery code is not valid or has expired.", status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(username=username).first()
        if user and user.locked_until and user.locked_until > timezone.now():
            User().set_password(d["password"])
            return fail
        authed = authenticate(request, username=username, password=d["password"])
        if authed is None:
            LoginView._register_failure(request, user, "bad_password_recovery")
            return fail
        token = MfaRecoveryCode.objects.filter(user=authed, code_hash=_hash_code(d["code"]), used_at__isnull=True,
                                               expires_at__gt=timezone.now()).first()
        if token is None:
            LoginView._register_failure(request, authed, "bad_recovery_code")  # guessing the code counts toward the lockout
            return fail
        with transaction.atomic():
            used = MfaRecoveryCode.objects.filter(pk=token.pk, used_at__isnull=True).update(used_at=timezone.now())
            if used != 1:  # lost a race with another redemption
                return fail
            User.objects.filter(pk=authed.pk).update(mfa_enabled=False, mfa_secret_enc="", failed_login_count=0, locked_until=None)
            authed.refresh_from_db()
            revoke_user_sessions(authed)
            record("auth.mfa_recovery", request=request, actor=authed, entity_type="user", entity_id=authed.pk)
        if authed.email:
            _send_recovery_mail(authed, "Puntland Defence Forces HQ: authenticator reset",
                                "The authenticator app on your account was reset using an emailed recovery code. You must set up a new one "
                                "at your next sign-in. If this was not you, tell your administrator now.")
        return Response(status=204)


class AuthOptionsView(APIView):
    """Which optional email features this server has switched on, so the sign-in page only offers what works."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"password_forgot": settings.PASSWORD_FORGOT_ENABLED, "email_verification": settings.EMAIL_VERIFICATION_ENABLED})


RESEND_SECONDS = 60
MAX_CODE_ATTEMPTS = 5


class PasswordForgotView(APIView):
    """Forgot password, step 1: email a one-time code. Open to anyone, so the answer is always the same: it cannot be used to find
    out which usernames or addresses exist. Only accounts with a VERIFIED email address get a code. Step 2 is the existing
    password-reset endpoint (username + code + new password, plus the authenticator code when the account has one)."""

    permission_classes = [AllowAny]
    throttle_scope = "forgot"

    @staticmethod
    def _find(identifier):
        if "@" in identifier:  # usernames cannot contain "@"
            matches = list(User.objects.filter(email__iexact=identifier, email_verified_at__isnull=False, is_active=True)[:2])
            return matches[0] if len(matches) == 1 else None  # an address that matches two accounts is ambiguous: send nothing
        return User.objects.filter(username=identifier, is_active=True, email_verified_at__isnull=False).exclude(email="").first()

    def post(self, request):
        enforce_csrf(request)
        if not settings.PASSWORD_FORGOT_ENABLED:
            return error("not_available", "Password recovery by email is not available.", status.HTTP_404_NOT_FOUND)
        ser = PasswordForgotSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        generic = Response({"detail": "If the account exists and has a verified email address, a code has been sent."})
        user = self._find(ser.validated_data["identifier"].strip().lower())
        if user is None:
            record("auth.password_forgot", request=request, outcome="failure", metadata={"reason": "no_match"})
            return generic
        now = timezone.now()
        if PasswordResetToken.objects.filter(user=user, created_by__isnull=True, created_at__gt=now - timedelta(seconds=RESEND_SECONDS)).exists():
            record("auth.password_forgot", request=request, actor=user, outcome="denied", entity_type="user", entity_id=user.pk,
                   metadata={"reason": "too_soon"})
            return generic
        code = secrets.token_hex(5).upper()  # 40 bits; single use, short-lived, rate-limited, and useless without the username
        minutes = settings.PASSWORD_FORGOT_CODE_MINUTES
        with transaction.atomic():
            # Supersede only earlier emailed codes: a code an administrator issued is a separate, deliberate action.
            PasswordResetToken.objects.filter(user=user, created_by__isnull=True, used_at__isnull=True).update(used_at=now)
            PasswordResetToken.objects.create(user=user, token_hash=_hash_code(code), expires_at=now + timedelta(minutes=minutes))
        sent = _send_mail(
            user.email, "Puntland Defence Forces HQ: your password reset code",
            f"Your one-time password reset code is {code}\n\nOpen the reset page, enter your username and this code, and choose a new "
            f"password. It works once and expires in {minutes} minutes. If you did not ask for this, ignore this email and tell your administrator.")
        record("auth.password_forgot", request=request, actor=user, outcome="success" if sent else "failure", entity_type="user", entity_id=user.pk)
        return generic


def _email_code_hash(user, email, code):
    return hashlib.sha256(f"{user.pk}|{email}|{code.strip()}".encode()).hexdigest()


class EmailVerifyRequestView(APIView):
    """Email verification, step 1 (signed in): send a six-digit code to the account's address, or to a new address the user types
    (which needs the current password, so a stolen session alone cannot move the account to a new mailbox)."""

    throttle_scope = "verify"

    def post(self, request):
        if not settings.EMAIL_VERIFICATION_ENABLED:
            return error("not_available", "Email verification is not available.", status.HTTP_404_NOT_FOUND)
        ser = EmailVerifyRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = request.user
        target = (ser.validated_data.get("email") or user.email or "").strip().lower()
        if not target:
            raise field_error("email", "no_email", "Enter an email address.")
        changing = target != (user.email or "").lower()
        if not changing and user.email_verified_at:
            return error("already_verified", "This email address is already verified.", status.HTTP_409_CONFLICT)
        if changing and not user.check_password(ser.validated_data.get("password") or ""):
            record("auth.email_verify_request", request=request, outcome="failure", entity_type="user", entity_id=user.pk,
                   metadata={"reason": "bad_password"})
            raise field_error("password", "wrong_password", "Incorrect password.")
        now = timezone.now()
        if EmailVerificationCode.objects.filter(user=user, created_at__gt=now - timedelta(seconds=RESEND_SECONDS)).exists():
            return error("too_soon", "Wait a minute before asking for another code.", status.HTTP_429_TOO_MANY_REQUESTS)
        code = f"{secrets.randbelow(1_000_000):06d}"
        minutes = settings.EMAIL_VERIFY_CODE_MINUTES
        with transaction.atomic():
            EmailVerificationCode.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
            row = EmailVerificationCode.objects.create(
                user=user, email=target, code_hash=_email_code_hash(user, target, code), expires_at=now + timedelta(minutes=minutes))
        if not _send_mail(target, "Puntland Defence Forces HQ: your verification code",
                          f"Your email verification code is {code}\n\nIt expires in {minutes} minutes. If you did not ask for this, "
                          "ignore this email."):
            row.delete()  # a failed send must not lock the user out of trying again for a minute
            record("auth.email_verify_request", request=request, outcome="failure", entity_type="user", entity_id=user.pk,
                   metadata={"reason": "send_failed"})
            return error("email_send_failed", "The code could not be sent. Try again later.", status.HTTP_502_BAD_GATEWAY)
        record("auth.email_verify_request", request=request, entity_type="user", entity_id=user.pk, metadata={"changing": changing})
        return Response(status=204)


class EmailVerifyConfirmView(APIView):
    """Email verification, step 2 (signed in): the code proves the user can read that mailbox. Confirming a new address makes it
    the account's address."""

    throttle_scope = "verify"

    def post(self, request):
        if not settings.EMAIL_VERIFICATION_ENABLED:
            return error("not_available", "Email verification is not available.", status.HTTP_404_NOT_FOUND)
        ser = EmailVerifyConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = request.user
        now = timezone.now()
        bad = error("invalid_email_code", "That code is not valid or has expired.", status.HTTP_400_BAD_REQUEST)
        wanted = (ser.validated_data.get("email") or user.email or "").strip().lower()
        row = EmailVerificationCode.objects.filter(user=user, used_at__isnull=True, expires_at__gt=now).order_by("-created_at").first()
        if row is None or row.email != wanted:
            return bad
        if row.attempts >= MAX_CODE_ATTEMPTS:
            EmailVerificationCode.objects.filter(pk=row.pk).update(used_at=now)
            return error("too_many_attempts", "Too many wrong codes. Ask for a new code.", status.HTTP_400_BAD_REQUEST)
        EmailVerificationCode.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)
        if not hmac.compare_digest(row.code_hash, _email_code_hash(user, row.email, ser.validated_data["code"])):
            record("auth.email_verify", request=request, outcome="failure", entity_type="user", entity_id=user.pk)
            return bad
        if User.objects.filter(email__iexact=row.email, email_verified_at__isnull=False).exclude(pk=user.pk).exists():
            # One verified address per account, so "forgot password by email" can never be ambiguous.
            return error("email_in_use", "That email address is already verified on another account.", status.HTTP_409_CONFLICT)
        old_email, old_verified = user.email, user.email_verified_at is not None
        changed = row.email != (old_email or "").lower()
        with transaction.atomic():
            if EmailVerificationCode.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=now) != 1:  # lost a race
                return bad
            User.objects.filter(pk=user.pk).update(email=row.email, email_verified_at=now, updated_at=now, version=F("version") + 1)
            record("auth.email_changed" if changed else "auth.email_verified", request=request, entity_type="user", entity_id=user.pk)
        if changed and old_email and old_verified:  # tell the previous mailbox, so a hijacked session cannot move the address silently
            _send_mail(old_email, "Puntland Defence Forces HQ: your account email was changed",
                       "The email address on your account was changed. If this was not you, tell your administrator now.")
        return Response(me_payload(User.objects.get(pk=user.pk)))


class RoleViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = RoleSerializer
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("users.view", "global")}
    pagination_class = None

    def get_queryset(self):
        return Role.objects.prefetch_related("permissions")


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  viewsets.GenericViewSet):
    """Account administration is a global (headquarters) capability in 1.0."""

    serializer_class = UserSerializer
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("users.view", "global"), "retrieve": ("users.view", "global"),
        "create": ("users.manage", "global"), "partial_update": ("users.manage", "global"),
        "disable": ("users.manage", "global"), "enable": ("users.manage", "global"),
        "revoke_sessions": ("users.manage", "global"), "reset_mfa": ("users.manage", "global"),
        "reset_password": ("users.manage", "global"), "issue_reset_code": ("users.manage", "global"),
        "assignments": ("users.view", "global"),
        "revoke_assignment": ("roles.assign", "global"),
    }

    def get_object(self):
        """A super administrator's account can only be changed by a super administrator (no takeover by resetting its password or MFA)."""
        target = super().get_object()
        if (self.request.method not in ("GET", "HEAD", "OPTIONS") and target.pk != self.request.user.pk
                and scope.can(target, scope.FULL_ACCESS) and not scope.can(self.request.user, scope.FULL_ACCESS)):
            record("access.denied", request=self.request, outcome="denied", entity_type="user", entity_id=target.pk,
                   metadata={"reason": "protected_account"})
            raise PermissionDenied("Only a super administrator can change a super administrator's account.")
        return target

    def get_queryset(self):
        qs = User.objects.all()
        p = self.request.query_params
        if p.get("q"):
            qs = qs.filter(Q(username__icontains=p["q"]) | Q(full_name__icontains=p["q"]))
        if p.get("is_active") in ("true", "false"):
            qs = qs.filter(is_active=p["is_active"] == "true")
        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        ser = UserCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        record("user.create", request=request, entity_type="user", entity_id=user.pk,
               metadata={"username": user.username})
        return Response(UserSerializer(user).data, status=201)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        user = self.get_object()
        ser = UserUpdateSerializer(user, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        record("user.update", request=request, entity_type="user", entity_id=user.pk,
               metadata={"fields": sorted(ser.validated_data.keys())})
        return Response(UserSerializer(user).data)

    def _is_admin(self, user):
        return any("users.manage" in a.perm_codes and scope.is_global(a) for a in scope.assignments(user))

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def disable(self, request, pk=None):
        user = self.get_object()
        if user.pk == request.user.pk:
            return error("cannot_disable_self", "You cannot disable your own account.", 409)
        if self._is_admin(user) and not other_admins_exist(excluding_user_id=user.pk):
            return error("last_admin", "This is the last active user administrator.", 409)
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
        revoke_user_sessions(user)
        record("user.disable", request=request, entity_type="user", entity_id=user.pk)
        return Response(UserSerializer(user).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def enable(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["is_active", "failed_login_count", "locked_until", "updated_at"])
        record("user.enable", request=request, entity_type="user", entity_id=user.pk)
        return Response(UserSerializer(user).data)

    @action(detail=True, methods=["post"], url_path="revoke-sessions")
    @transaction.atomic
    def revoke_sessions(self, request, pk=None):
        user = self.get_object()
        revoke_user_sessions(user)
        record("user.revoke_sessions", request=request, entity_type="user", entity_id=user.pk)
        return Response(status=204)

    @action(detail=True, methods=["post"], url_path="reset-mfa")
    @transaction.atomic
    def reset_mfa(self, request, pk=None):
        user = self.get_object()
        user.mfa_enabled = False
        user.mfa_secret_enc = ""
        user.save(update_fields=["mfa_enabled", "mfa_secret_enc", "updated_at"])
        revoke_user_sessions(user)
        record("user.reset_mfa", request=request, entity_type="user", entity_id=user.pk)
        return Response(UserSerializer(user).data)

    @action(detail=True, methods=["post"], url_path="reset-password")
    @transaction.atomic
    def reset_password(self, request, pk=None):
        user = self.get_object()
        ser = PasswordResetSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user.set_password(ser.validated_data["temporary_password"])
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        revoke_user_sessions(user)
        record("user.reset_password", request=request, entity_type="user", entity_id=user.pk)
        return Response(status=204)

    @action(detail=True, methods=["post"], url_path="issue-reset-code")
    @transaction.atomic
    def issue_reset_code(self, request, pk=None):
        """One-time recovery code, shown once, to be handed over through a trusted channel."""
        user = self.get_object()
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())  # supersede older codes
        code = secrets.token_hex(5).upper()  # 40 bits; short-lived, single use, rate-limited
        expires = timezone.now() + timedelta(minutes=RESET_CODE_MINUTES)
        PasswordResetToken.objects.create(user=user, token_hash=_hash_code(code), expires_at=expires, created_by=request.user)
        record("user.issue_reset_code", request=request, entity_type="user", entity_id=user.pk)
        return Response({"code": code, "expires_at": expires, "valid_minutes": RESET_CODE_MINUTES})

    @action(detail=True, methods=["get", "post"])
    def assignments(self, request, pk=None):
        target = self.get_object()
        if request.method == "GET":
            qs = RoleAssignment.objects.filter(user=target).select_related("role", "org_unit", "branch")
            return Response(AssignmentSerializer(qs, many=True).data)
        if not scope.can(request.user, "roles.assign"):
            record("access.denied", request=request, outcome="denied", entity_type="role_assignment",
                   metadata={"permission": "roles.assign"})
            raise PermissionDenied()
        ser = AssignmentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        beyond = sorted(c for c in ser.validated_data["role"].permissions.values_list("code", flat=True)
                        if not scope.can(request.user, c))
        if beyond:  # nobody can hand out authority they do not hold themselves (stops an administrator making themselves super admin)
            record("access.denied", request=request, outcome="denied", entity_type="role_assignment",
                   metadata={"reason": "role_exceeds_authority", "role": ser.validated_data["role"].code})
            return error("role_exceeds_authority", "This role carries authority you do not hold. Only a super administrator can assign it.", 403)
        with transaction.atomic():
            a = RoleAssignment.objects.create(user=target, created_by=request.user, **ser.validated_data)
            record("role_assignment.create", request=request, entity_type="role_assignment", entity_id=a.pk,
                   metadata={"user": str(target.pk), "role": a.role.code, "org_unit": str(a.org_unit_id),
                             "branch": str(a.branch_id) if a.branch_id else None})
        a = RoleAssignment.objects.select_related("role", "org_unit", "branch").get(pk=a.pk)
        return Response(AssignmentSerializer(a).data, status=201)

    @action(detail=True, methods=["post"], url_path=r"assignments/(?P<assignment_id>[0-9a-f-]{36})/revoke")
    @transaction.atomic
    def revoke_assignment(self, request, pk=None, assignment_id=None):
        target = self.get_object()
        a = RoleAssignment.objects.select_related("role", "org_unit").filter(
            pk=assignment_id, user=target, revoked_at__isnull=True).first()
        if a is None:
            return error("not_found", "Assignment not found.", 404)
        gives_admin = ("users.manage" in {p.code for p in a.role.permissions.all()}
                       and a.org_unit.level == "headquarters" and a.branch_id is None)
        if gives_admin and not other_admins_exist(excluding_assignment_id=a.pk):
            return error("last_admin", "This is the last active user administrator.", 409)
        a.revoked_at = timezone.now()
        a.save(update_fields=["revoked_at"])
        revoke_user_sessions(target)  # permission change takes effect on the next request
        record("role_assignment.revoke", request=request, entity_type="role_assignment", entity_id=a.pk,
               metadata={"user": str(target.pk), "role": a.role.code})
        return Response(status=204)
