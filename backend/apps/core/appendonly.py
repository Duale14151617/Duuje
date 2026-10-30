from django.db import models


class AppendOnlyError(Exception):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("Append-only records cannot be modified.")

    def delete(self):
        raise AppendOnlyError("Append-only records cannot be deleted.")

    def bulk_update(self, *args, **kwargs):
        raise AppendOnlyError("Append-only records cannot be modified.")


class AppendOnlyModel(models.Model):
    """Rows can be inserted but never changed or removed through the application."""

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Append-only records cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Append-only records cannot be deleted.")
