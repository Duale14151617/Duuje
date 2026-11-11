from django.apps import AppConfig


class OrganizationConfig(AppConfig):
    name = "apps.organization"

    def ready(self):
        from . import signals  # noqa: F401  (registers the receivers)
