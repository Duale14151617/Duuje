"""Bulk profile pictures: a zip of images named by username. Pure checking and processing; the view saves and audits.

Limits keep a hostile or careless zip harmless: file count, per-file size, total declared size, and the declared size of each entry
is never trusted (reading stops at the per-file limit)."""
import zipfile
from pathlib import PurePosixPath

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.errors import field_error
from apps.personnel import profile as profile_svc

from . import avatar as avatar_svc
from .models import User

MAX_FILES = 200
MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


def read_zip(upload, actor) -> list:
    """One row per image: {file, username, status, user?, jpeg?}. status is "ok" or why the picture was skipped."""
    if upload.size > MAX_ZIP_BYTES:
        raise field_error("file", "zip_too_large", "The zip is too large.")
    try:
        zf = zipfile.ZipFile(upload)
    except (zipfile.BadZipFile, OSError):
        raise field_error("file", "zip_invalid", "That is not a valid zip file.")
    infos = []
    for i in zf.infolist():
        name = PurePosixPath(i.filename.replace("\\", "/"))
        if i.is_dir() or "__MACOSX" in name.parts or name.name.startswith("."):
            continue
        infos.append((i, name.name))
    if not infos:
        raise field_error("file", "zip_empty", "The zip has no files.")
    if len(infos) > MAX_FILES:
        raise field_error("file", "zip_too_many", f"At most {MAX_FILES} pictures per zip.")
    if sum(i.file_size for i, _ in infos) > MAX_TOTAL_BYTES:
        raise field_error("file", "zip_too_large", "The zip is too large.")

    rows, seen = [], set()
    for info, base in infos:
        stem, dot, ext = base.rpartition(".")
        username = (stem if dot else base).strip().lower()
        row = {"file": base, "username": username, "status": "ok", "user": None, "jpeg": None}
        rows.append(row)
        if not dot or "." + ext.lower() not in IMAGE_EXT:
            row["status"] = "not_image"
        elif username in seen:
            row["status"] = "duplicate"
        elif info.file_size > profile_svc.PHOTO_MAX_BYTES:
            row["status"] = "photo_too_large"
        else:
            seen.add(username)
            user = User.objects.filter(username=username).first()
            if user is None:
                row["status"] = "unknown_user"
            elif not avatar_svc.can_set_avatar(actor, user):
                row["status"] = "not_allowed"
            else:
                with zf.open(info) as fh:
                    data = fh.read(profile_svc.PHOTO_MAX_BYTES + 1)
                if len(data) > profile_svc.PHOTO_MAX_BYTES:
                    row["status"] = "photo_too_large"
                    continue
                try:
                    row["jpeg"] = profile_svc.process_photo(SimpleUploadedFile(base, data))
                    row["user"] = user
                except Exception:  # not a real image, corrupt, or unsupported
                    row["status"] = "photo_invalid"
    return rows
