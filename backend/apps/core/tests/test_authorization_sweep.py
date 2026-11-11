"""Deny-by-default evidence: every registered API route is exercised without credentials and without any role."""
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.permissions import IsFullyAuthenticated, ScopedPermission
from apps.core.testing import PASSWORD, BaseApiTest
from config.api_v1 import router

STANDARD = ["list", "retrieve", "create", "partial_update", "update", "destroy"]
OWN_DATA_ONLY = {"notification"}  # authenticated users may list *their own* notifications (empty without roles)


def registry():
    return [(prefix, viewset, basename) for prefix, viewset, basename in router.registry]


class RouteInventoryTests(BaseApiTest):
    def test_every_viewset_requires_a_fully_authenticated_user(self):
        self.assertGreaterEqual(len(registry()), 20)
        for prefix, viewset, basename in registry():
            classes = list(viewset.permission_classes)
            self.assertTrue(classes and all(issubclass(c, IsFullyAuthenticated) for c in classes), f"{basename}: {classes}")

    def test_scoped_viewsets_map_every_action_to_a_permission_and_nothing_stale(self):
        for prefix, viewset, basename in registry():
            if not any(issubclass(c, ScopedPermission) for c in viewset.permission_classes):
                self.assertIn(basename, OWN_DATA_ONLY, f"{basename} has no explicit permission map")
                continue
            defined = {a for a in STANDARD if hasattr(viewset, a)} | {a.__name__ for a in viewset.get_extra_actions()}
            mapped = set(viewset.permission_map)
            self.assertFalse(defined - mapped - {"update"}, f"{basename}: actions without a permission rule {defined - mapped}")
            self.assertFalse(mapped - defined, f"{basename}: stale permission rules {mapped - defined}")

    def test_no_viewset_allows_put_or_delete(self):
        for prefix, viewset, basename in registry():
            if hasattr(viewset, "update") or hasattr(viewset, "destroy"):
                allowed = getattr(viewset, "http_method_names", [])
                self.assertTrue(allowed, f"{basename} must restrict http_method_names")
                self.assertNotIn("put", allowed, basename)
                self.assertNotIn("delete", allowed, basename)


class DenyByDefaultSweep(BaseApiTest):
    def list_urls(self):
        return [(basename, reverse(f"{basename}-list")) for _, _, basename in registry()]

    def test_unauthenticated_requests_are_refused_on_every_route(self):
        c = APIClient()
        for basename, url in self.list_urls():
            for method in ("get", "post"):
                r = getattr(c, method)(url, {}, format="json") if method == "post" else c.get(url)
                self.assertEqual(r.status_code, 403, f"{method.upper()} {url}")
                self.assertEqual(r.json()["code"], "not_authenticated", f"{method.upper()} {url}")
        for url in ("/api/v1/dashboard/", "/api/v1/auth/me/", "/api/v1/auth/password/change/", "/api/v1/auth/mfa/setup/"):
            self.assertEqual(APIClient().get(url).status_code, 403, url)

    def test_a_signed_in_user_with_no_role_is_refused_on_every_route(self):
        user = User.objects.create_user("norole", password=PASSWORD, full_name="No Role")
        c = self.client_for(user)
        for basename, url in self.list_urls():
            get = c.get(url)
            post = c.post(url, {}, format="json")  # authorization must come before validation
            if basename in OWN_DATA_ONLY:
                self.assertEqual(get.status_code, 200, url)
                self.assertEqual(get.json()["count"], 0, url)
                continue
            self.assertEqual(get.status_code, 403, f"GET {url}")
            self.assertEqual(post.status_code, 403, f"POST {url}")
        self.assertEqual(c.get("/api/v1/dashboard/").status_code, 403)
        self.assertEqual(c.get("/api/v1/auth/me/").status_code, 200)

    def test_object_routes_do_not_reveal_whether_an_id_exists(self):
        user = User.objects.create_user("norole", password=PASSWORD, full_name="No Role")
        c = self.client_for(user)
        ghost = "00000000-0000-0000-0000-000000000000"
        for _, viewset, basename in registry():
            if basename in OWN_DATA_ONLY or not (hasattr(viewset, "retrieve") or hasattr(viewset, "partial_update")):
                continue  # only viewsets that actually expose a detail route
            url = reverse(f"{basename}-list")
            self.assertEqual(c.get(f"{url}{ghost}/").status_code, 403, url)  # same answer as for an existing, forbidden object
