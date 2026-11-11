"""Shared helpers for tests. Synthetic data only."""
import time

import pyotp
from django.core.cache import cache
from django.core.management import call_command
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import Role, RoleAssignment, User
from apps.core import crypto
from apps.organization.models import OrganizationalUnit, ServiceBranch

PASSWORD = "Correct-Horse-Battery-9"


class BaseApiTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_reference_data", verbosity=0)
        # Test-only fixture: a second service branch with one command per region, so the branch-scoping rules can be
        # exercised. It is not part of the seeded system, which is Army only.
        other = ServiceBranch.objects.get_or_create(code="OTHER", defaults={"name_en": "Other branch (test fixture)"})[0]
        for region in OrganizationalUnit.objects.filter(level=OrganizationalUnit.Level.REGION):
            OrganizationalUnit.objects.get_or_create(
                code=f"{region.code}-OTHER", defaults={
                    "name_en": f"{region.name_en} Other command (test)", "name_so": f"{region.name_en} Other command (test)",
                    "level": OrganizationalUnit.Level.BRANCH, "parent": region, "branch": other})

    def setUp(self):
        cache.clear()  # reset login throttles between tests

    def unit(self, code):
        return OrganizationalUnit.objects.get(code=code)

    def make_user(self, username, role, unit="HQ", branch=None, mfa=None, **extra):
        user = User.objects.create_user(username, password=PASSWORD, full_name=username, **extra)
        if mfa is None:  # privileged roles must have MFA; other roles sign in with a password alone
            mfa = Role.objects.get(code=role).is_privileged
        if mfa:
            user.mfa_enabled = True
            user.mfa_secret_enc = crypto.encrypt(pyotp.random_base32())
            user.save()
        RoleAssignment.objects.create(
            user=user, role=Role.objects.get(code=role), org_unit=self.unit(unit),
            branch=ServiceBranch.objects.get(code=branch) if branch else None)
        return User.objects.get(pk=user.pk)

    def client_for(self, user):
        client = APIClient()
        client.force_login(user)
        session = client.session
        session["auth_epoch"] = user.auth_epoch
        session["login_at"] = int(time.time())
        session.save()
        return client

    def login(self, client, username, password=PASSWORD, otp=None):
        body = {"username": username, "password": password}
        if otp:
            body["otp"] = otp
        return client.post("/api/v1/auth/login/", body, format="json")

    @staticmethod
    def codes(resp, field):
        return [e["code"] for e in resp.data["errors"][field]]
