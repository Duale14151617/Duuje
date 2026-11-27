"""ARMYHQ_* variables are read through apps.core.env; the older ARMYHQ_DEMO_* names still work as a last resort; blank counts as not set."""
import os
from unittest import mock

from django.test import SimpleTestCase

from apps.core import env


class EnvTests(SimpleTestCase):
    def get(self, environ, *a, **kw):
        with mock.patch.dict(os.environ, environ, clear=True):
            return env.get(*a, **kw)

    def test_the_variable_is_read(self):
        self.assertEqual(self.get({"ARMYHQ_PROFILE": "army"}, "PROFILE", "x"), "army")

    def test_the_default_applies_when_it_is_not_set(self):
        self.assertEqual(self.get({}, "PROFILE", "army"), "army")

    def test_a_blank_value_counts_as_not_set(self):
        self.assertEqual(self.get({"ARMYHQ_ADMIN_PASSWORD": ""}, "ADMIN_PASSWORD", "fallback"), "fallback")

    def test_the_oldest_demo_names_are_the_last_resort(self):
        legacy = ("DEMO_MODE",)
        self.assertEqual(self.get({"ARMYHQ_DEMO_MODE": "1"}, "SAMPLE_MODE", "0", legacy=legacy), "1")
        self.assertEqual(self.get({"ARMYHQ_DEMO_MODE": "1", "ARMYHQ_SAMPLE_MODE": "0"}, "SAMPLE_MODE", "0", legacy=legacy), "0")

    def test_booleans(self):
        with mock.patch.dict(os.environ, {"ARMYHQ_BREAK_GLASS": "0"}, clear=True):
            self.assertFalse(env.get_bool("BREAK_GLASS", True))
        with mock.patch.dict(os.environ, {"ARMYHQ_BREAK_GLASS": "yes"}, clear=True):
            self.assertTrue(env.get_bool("BREAK_GLASS", False))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(env.get_bool("STEP_UP_MFA", True))
