"""Synthetic test personnel for demos and load/UX testing - clearly tagged and removable in one go.

  python manage.py seed_test_personnel --count 150     add test people (idempotent: tops up to 150)
                                                       with the Police module ON this also adds Police sample people
                                                       (2/5 of the count unless --police-count is given)
  python manage.py seed_test_personnel --delete        remove every test person (and their history/training rows)
  python manage.py seed_test_personnel --from-env      used at container start, see below

On Render (no shell on the free plan) the start command runs `--from-env`, driven by ONE environment variable:
  ARMYHQ_TEST_PERSONNEL=150   -> make sure 150 test Army people exist (and, with POLICE_MODULE_ENABLED=1, 60 Police people)
  ARMYHQ_TEST_POLICE_PERSONNEL=N   optional: set the Police sample size explicitly (0 = none)
  ARMYHQ_TEST_POLICE_DRAFT_RANKS=1 optional, DEMO ONLY: let the Police sample use DRAFT ranks while the real Police ranks
                                   are still awaiting approval. Real people can never be given a draft rank; only TST- people.
  unset / 0                   -> delete all test people

Test people are identified ONLY by the service-number prefix "TST-", so real records are never touched.
Army test people are TST-0001...; Police test people are numbered from TST-5001, spread over the Police departments
(including CID) and the demo stations of every regional Police command.
Names are common Somali given names with father/grandfather names; no two test people share a name.
Each person also gets a complete identity profile (blood type, gender, date of birth, enlistment date, home district,
emergency contact, a weapon ID for about 3 in 4, and a neutral placeholder portrait).
"""
import os
import random
from datetime import date, timedelta
from io import BytesIO

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageDraw

from apps.organization.models import OrganizationalUnit as OU
from apps.personnel import profile as profile_svc
from apps.personnel import services as svc
from apps.personnel.models import Personnel, PersonnelHistory, PersonnelProfile
from apps.ranks.models import Rank

PREFIX = "TST-"
POLICE_FIRST_NUMBER = 5001
REGIONS = ("BARI", "KARKAAR", "NUGAAL", "MUDUG")

MALE = ["Abdirahman", "Abdullahi", "Abdiweli", "Abdikarim", "Abdinasir", "Abdisalam", "Abdulkadir", "Abshir", "Ahmed", "Ali",
        "Bashir", "Barre", "Dahir", "Elmi", "Farah", "Fuad", "Guled", "Hassan", "Hersi", "Hussein", "Ibrahim",
        "Ismail", "Jama", "Jibril", "Khalif", "Liban", "Mahad", "Mohamed", "Mukhtar", "Mustafe", "Nuur", "Omar", "Osman",
        "Said", "Samatar", "Shire", "Suleiman", "Warsame", "Yasin", "Yusuf", "Zakariye", "Abdiaziz", "Abdirizak",
        "Ayanle", "Deeq", "Faisal", "Gaas", "Idris", "Kaahin", "Mursal", "Salad", "Tahlil",
        "Yonis"]
FEMALE = ["Amina", "Asha", "Ayaan", "Deeqa", "Faduma", "Halima", "Hawa", "Hodan", "Ifrah", "Khadija", "Ladan",
          "Maryan", "Muna", "Nasra", "Rukia", "Sagal", "Sahra", "Ubah", "Zamzam"]
FAMILY = ["Abdi", "Abdullahi", "Adan", "Ahmed", "Ali", "Aw", "Barre", "Bile", "Botan", "Dahir", "Duale", "Egal", "Elmi",
          "Farah", "Gedi", "Guled", "Hassan", "Hussein", "Ibrahim", "Ismail", "Jama", "Jimcaale", "Kahin", "Khalif",
          "Liban", "Mohamud", "Muse", "Nur", "Omar", "Osman", "Qorane", "Robleh", "Saed", "Salah", "Samatar",
          "Sheikh", "Warsame", "Yare", "Yusuf"]
DISTRICTS = ["Garowe", "Bosaso", "Galkayo North", "Qardho", "Eyl", "Burtinle", "Dangorayo", "Iskushuban", "Bandarbeyla",
             "Jariban", "Gardo", "Caluula", "Bargaal", "Godobjiraan", "Goldogob", "Armo"]
BLOOD = ["O+"] * 8 + ["A+"] * 6 + ["B+"] * 4 + ["O-", "A-", "B-", "AB+", "AB-"]
BACKDROPS = [(28, 46, 78), (40, 58, 92), (52, 64, 84), (34, 52, 66), (60, 70, 96)]
STATUS = ["active"] * 17 + ["on_leave"] * 2 + ["suspended"]
# the 16 supplied ranks, junior -> senior; the two top appointments are left out. Junior ranks are more common.
WEIGHTS = [14, 12, 10, 9, 8, 7, 6, 5, 5, 4, 3, 3, 2, 2, 1, 1]


def _candidates(n, seed=20260):
    """Deterministic, unique-by-full-name list of (full_name) so reruns continue the same sequence."""
    rng = random.Random(seed)
    seen, out = set(), []
    while len(out) < n:
        first = rng.choice(FEMALE) if rng.random() < 0.12 else rng.choice(MALE)
        father, grand = rng.sample(FAMILY, 2)
        name = f"{first} {father} {grand}"
        key = svc.normalize_name(name)
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _units():
    units = []
    for r in REGIONS:
        cmd = OU.objects.filter(code=f"{r}-ARMY").first()
        if not cmd:
            continue
        unit = OU.objects.filter(code=f"{r}-ARMY-DEMO-A").first() or OU.objects.create(
            code=f"{r}-ARMY-DEMO-A", name_en="Synthetic Unit A", name_so="Cutubka Tijaabada A",
            level=OU.Level.UNIT, parent=cmd)
        units.append(unit)
    return units


def _placeholder_photo(rng):
    """Neutral silhouette on a navy backdrop (clearly not a real face) at the app's 360x450 portrait size."""
    w, h = profile_svc.PHOTO_SIZE
    img = Image.new("RGB", (w, h), rng.choice(BACKDROPS))
    d = ImageDraw.Draw(img)
    tone = (150, 160, 178)
    d.ellipse((w * .31, h * .17, w * .69, h * .50), fill=tone)             # head
    d.ellipse((w * .12, h * .56, w * .88, h * 1.25), fill=tone)            # shoulders
    d.rectangle((0, h - 6, w, h), fill=(196, 160, 60))                     # thin gold base line
    buf = BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def fill_profiles():
    """Give every test person a complete identity profile (blood type, gender, weapon ID, dates, district, emergency
    contact, placeholder photo). Only people whose profile is still empty are filled, so admin edits are never overwritten."""
    filled = 0
    today = date.today()
    for person in Personnel.objects.filter(service_number__startswith=PREFIX).order_by("service_number"):
        n = int(person.service_number[len(PREFIX):])
        rng = random.Random(9000 + n)
        existing = PersonnelProfile.objects.filter(pk=person.pk).first()
        if not (existing and existing.data_enc):
            first = person.full_name.split()[0]
            dob = today - timedelta(days=rng.randint(21 * 365, 48 * 365))
            earliest, latest = dob + timedelta(days=18 * 365 + 30), today - timedelta(days=60)
            enlisted = earliest + timedelta(days=rng.randint(0, (latest - earliest).days))
            contact_first = rng.choice(MALE + FEMALE)
            changes = {
                "blood_type": rng.choice(BLOOD), "gender": "female" if first in FEMALE else "male",
                "date_of_birth": dob, "enlistment_date": enlisted, "home_district": rng.choice(DISTRICTS),
                "emergency_contact_name": f"{contact_first} {rng.choice(FAMILY)}",
                "emergency_contact_phone": f"+252908{n:06d}",
            }
            if rng.random() < 0.75:  # not everyone is issued a personal weapon
                changes["weapon_id"] = f"TSTW-{n:04d}"
            profile_svc.save(person, changes)
            filled += 1
        if not (existing and existing.photo_enc):
            profile_svc.save_photo(person, _placeholder_photo(rng))
    return filled


def add_test_personnel(count):
    units = _units()
    ranks = list(Rank.objects.filter(branch__code="ARMY", approval_status=Rank.Approval.APPROVED, active=True)
                 .order_by("sort_order")[:16])
    if not units or not ranks:
        raise CommandError("Reference data missing (regional Army commands or approved ranks). Run seed_reference_data first.")
    have = set(Personnel.objects.filter(service_number__startswith=PREFIX).values_list("service_number", flat=True))
    taken = set(Personnel.objects.values_list("name_key", flat=True))
    names = _candidates(count + 400)  # spare names in case a real person already has one
    rng = random.Random(1)
    today, created, name_i = date.today(), 0, 0
    with transaction.atomic():
        for i in range(1, count + 1):
            number = f"{PREFIX}{i:04d}"
            if number in have:
                continue
            while svc.normalize_name(names[name_i]) in taken:
                name_i += 1
            name = names[name_i]
            name_i += 1
            taken.add(svc.normalize_name(name))
            # every rank appears at least once among the first people, then weighted towards junior ranks
            rank = ranks[(i - 1) % len(ranks)] if i <= len(ranks) else rng.choices(ranks, weights=WEIGHTS[:len(ranks)])[0]
            svc.create_personnel(
                None, full_name=name, phone=f"+252907{i:06d}", service_number=number, org_unit=units[(i - 1) % len(units)],
                rank=rank, status=rng.choice(STATUS), effective_date=today - timedelta(days=rng.randint(30, 1500)),
                reason="Synthetic test record")
            created += 1
    fill_profiles()  # also completes people created before profiles were added
    return created


POLICE_DEPARTMENTS = ("PERS", "OPS", "TRN", "FINLOG", "CID", "PR", "TRAFFIC")
POLICE_STATIONS = (("STN-1", "Synthetic Station 1"), ("STN-2", "Synthetic Station 2"))


def _police_units():
    """Police departments (CID included) and two clearly synthetic stations under every regional Police command."""
    units = []
    for r in REGIONS:
        cmd = OU.objects.filter(code=f"{r}-POLICE").first()
        if not cmd:
            continue
        for dept in POLICE_DEPARTMENTS:
            unit = OU.objects.filter(code=f"{r}-POLICE-{dept}").first()
            if unit:
                units.append(unit)
        for code, label in POLICE_STATIONS:
            units.append(OU.objects.filter(code=f"{r}-POLICE-{code}").first() or OU.objects.create(
                code=f"{r}-POLICE-{code}", name_en=f"{r.title()} {label}", name_so=f"{r.title()} {label}",
                level=OU.Level.STATION, parent=cmd))
    return units


def add_police_test_personnel(count, allow_draft_ranks=False):
    """Synthetic Police people, so unit admins and CID have something to see. Returns (created, note).

    Uses APPROVED Police ranks. Until the real ranks are approved, nothing is created unless `allow_draft_ranks`
    (opt-in, demo only) is set; the real approval rule is never relaxed for anyone who is not a TST- person."""
    from django.conf import settings
    if not settings.POLICE_MODULE_ENABLED:
        return 0, "Police module is off: no Police test people added."
    units = _police_units()
    ranks = list(Rank.objects.filter(branch__code="POLICE", active=True, approval_status=Rank.Approval.APPROVED)
                 .order_by("sort_order"))
    if not ranks and allow_draft_ranks:
        ranks = list(Rank.objects.filter(branch__code="POLICE", active=True).order_by("sort_order"))
        drafts = True
    else:
        drafts = False
    if not units:
        return 0, "No Police units found. Run seed_reference_data with POLICE_MODULE_ENABLED=1 first."
    if not ranks:
        return 0, ("No approved Police ranks yet, so no Police test people were added. Approve the Police ranks on the Ranks "
                   "page (or, for a demo only, set ARMYHQ_TEST_POLICE_DRAFT_RANKS=1).")
    have = set(Personnel.objects.filter(service_number__startswith=PREFIX).values_list("service_number", flat=True))
    taken = set(Personnel.objects.values_list("name_key", flat=True))
    names = _candidates(count + 400, seed=20261)
    rng = random.Random(2)
    weights = [14, 12, 10, 9, 8, 7, 6, 5, 5, 4, 3, 3, 2, 2, 1, 1]
    today, created, name_i = date.today(), 0, 0
    with transaction.atomic():
        for i in range(1, count + 1):
            number = f"{PREFIX}{POLICE_FIRST_NUMBER + i - 1:04d}"
            if number in have:
                continue
            while svc.normalize_name(names[name_i]) in taken:
                name_i += 1
            name = names[name_i]
            name_i += 1
            taken.add(svc.normalize_name(name))
            rank = ranks[(i - 1) % len(ranks)] if i <= len(ranks) else rng.choices(ranks, weights=weights[:len(ranks)])[0]
            svc.create_personnel(
                None, full_name=name, phone=f"+252909{POLICE_FIRST_NUMBER + i - 1:06d}", service_number=number,
                org_unit=units[(i - 1) % len(units)], rank=rank, status=rng.choice(STATUS),
                effective_date=today - timedelta(days=rng.randint(30, 1500)), reason="Synthetic test record",
                allow_draft_rank=drafts)
            created += 1
    fill_profiles()
    return created, ("Used DRAFT Police ranks (demo only)." if drafts and created else "")


def delete_test_personnel():
    """Remove every TST- person. History is append-only through the normal manager, so it is cleared with the plain
    base manager here; training rows protect the person, so they go first. Nothing else is touched."""
    from apps.training.models import TrainingRecord
    with transaction.atomic():
        from apps.personnel.models import DisciplinaryRecord, PersonnelDocument
        ids = list(Personnel.objects.filter(service_number__startswith=PREFIX).values_list("pk", flat=True))
        # Disciplinary entries are append-only and documents can never be deleted, so a test person who was given either
        # (someone trying the screens on a demo) is kept rather than breaking the whole clean-up.
        held = set(DisciplinaryRecord.objects.filter(personnel_id__in=ids).values_list("personnel_id", flat=True))
        held |= set(PersonnelDocument.objects.filter(personnel_id__in=ids).values_list("personnel_id", flat=True))
        ids = [i for i in ids if i not in held]
        if not ids:
            return 0
        TrainingRecord.objects.filter(personnel_id__in=ids).delete()
        PersonnelHistory._base_manager.filter(personnel_id__in=ids).delete()
        Personnel.objects.filter(pk__in=ids).delete()  # profile rows cascade
    return len(ids)


def police_target(army_count, explicit=None):
    """Police sample size: explicit when given, otherwise 2/5 of the Army sample (60 for 150)."""
    if explicit is not None:
        return max(0, min(int(explicit), 1000))
    return (army_count * 2) // 5


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class Command(BaseCommand):
    help = "Add or remove clearly-tagged synthetic test personnel (service numbers TST-0001..., Police TST-5001...)."

    def add_arguments(self, parser):
        g = parser.add_mutually_exclusive_group()
        g.add_argument("--count", type=int, help="make sure this many Army test people exist (max 1000)")
        g.add_argument("--delete", action="store_true", help="delete ALL test people (Army and Police)")
        g.add_argument("--from-env", action="store_true", help="use ARMYHQ_TEST_PERSONNEL (0/unset = delete all)")
        parser.add_argument("--police-count", type=int, default=None,
                            help="Police test people (needs POLICE_MODULE_ENABLED=1); default 2/5 of --count")
        parser.add_argument("--police-draft-ranks", action="store_true",
                            help="DEMO ONLY: allow draft Police ranks for test people while real ranks await approval")

    def handle(self, *args, **opts):
        if opts["from_env"]:
            raw = os.environ.get("ARMYHQ_TEST_PERSONNEL", "0").strip()
            try:  # start-up must never fail because of test data
                n = max(0, min(int(raw or 0), 1000))
                if n:
                    self.stdout.write(f"Test personnel: {add_test_personnel(n)} added (target {n}).")
                    raw_p = os.environ.get("ARMYHQ_TEST_POLICE_PERSONNEL", "").strip()
                    target = police_target(n, int(raw_p) if raw_p else None)
                    if target:
                        added, note = add_police_test_personnel(target, _env_flag("ARMYHQ_TEST_POLICE_DRAFT_RANKS"))
                        self.stdout.write(f"Police test personnel: {added} added (target {target}). {note}".strip())
                else:
                    self.stdout.write(f"Test personnel: {delete_test_personnel()} removed.")
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"Test personnel skipped: {exc}")
            return
        if opts["delete"]:
            self.stdout.write(self.style.SUCCESS(f"Deleted {delete_test_personnel()} test personnel."))
        elif opts["count"]:
            if not 1 <= opts["count"] <= 1000:
                raise CommandError("--count must be between 1 and 1000.")
            self.stdout.write(self.style.SUCCESS(f"Added {add_test_personnel(opts['count'])} test personnel."))
            target = police_target(opts["count"], opts["police_count"])
            if target:
                added, note = add_police_test_personnel(target, opts["police_draft_ranks"] or _env_flag("ARMYHQ_TEST_POLICE_DRAFT_RANKS"))
                self.stdout.write(self.style.SUCCESS(f"Police test personnel: {added} added (target {target}). {note}".strip()))
        else:
            raise CommandError("Use --count N, --delete or --from-env.")
