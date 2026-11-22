"""Detention register (Army custody). One row per person held at a station, plus an append-only log of what happened to them.

* A record is never deleted. A wrong entry is voided with a reason; a person leaving custody is closed with an outcome.
* The custody clock runs from `booked_at` until `ended_at`. Anything held past DETENTION_REVIEW_HOURS is flagged for review (a
  configurable alert, not a statement of law).
* Every change also writes a DetentionEvent (append-only), so the register shows the whole custody story in order.
"""
import uuid

from django.db import models

from apps.core.appendonly import AppendOnlyError, AppendOnlyModel


class DetentionCounter(models.Model):
    """Single row that hands out register numbers (locked with SELECT ... FOR UPDATE), so numbers are never reused."""

    name = models.CharField(max_length=20, primary_key=True)
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "detention_counters"


def id_key(value):
    """Normal form of an ID / document number for duplicate detection: upper case letters and digits only."""
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())[:80]


class CustodyFacility(models.Model):
    """A place where people are held. Two kinds, kept apart on purpose:

    * Jail center (Jeel / lock-up): the army cell at a station. Short-term custody run by the Army: people arrested and held
      while the case is investigated and until they are charged, released or handed to the court. Belongs to one station.
    * Prison (Xabsi): a long-term institution run by the prison authority, NOT the Army. It receives people the court has
      sentenced (or remanded). The Army only hand people over; the system records the hand-over, nothing inside the prison.

    Never deleted: a facility that closes is switched off (active = False).
    """

    class Kind(models.TextChoices):
        JAIL_CENTER = "jail_center", "Jail center (army lock-up)"
        PRISON = "prison", "Prison"

    class Status(models.TextChoices):
        UNVERIFIED = "unverified", "Not verified"
        OPERATIONAL = "operational", "Operational"
        SUSPENDED = "suspended", "Temporarily out of use"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    name_en = models.CharField(max_length=150)
    name_so = models.CharField(max_length=150, blank=True)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="custody_facilities")
    location = models.CharField(max_length=200, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    operated_by = models.CharField(max_length=150, blank=True)
    active = models.BooleanField(default=True)
    # Real operating status. A record created automatically (or by anyone) is UNVERIFIED: it proves nothing about the building.
    # Only a person with detention.verify for the station marks it operational, after checking it on the ground.
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UNVERIFIED)
    status_note = models.CharField(max_length=300, blank=True)
    status_at = models.DateTimeField(null=True, blank=True)
    status_by_username = models.CharField(max_length=150, blank=True)
    last_edited_by_username = models.CharField(max_length=150, blank=True)  # who created or last changed the record (empty: made by the system); that person cannot verify it
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "custody_facilities"
        ordering = ["kind", "name_en"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(kind="jail_center") | models.Q(org_unit__isnull=False), name="facility_jail_has_station"),
            models.CheckConstraint(condition=~models.Q(kind="prison") | models.Q(org_unit__isnull=True), name="facility_prison_no_station"),
        ]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Facilities cannot be deleted; switch them off instead.")

    @property
    def usable(self):
        """Can people be placed here today: switched on and verified as operational."""
        return self.active and self.status == self.Status.OPERATIONAL


class CustodyCell(models.Model):
    """One cell (or holding room) of a jail center, with the number of people it may hold. Cells are optional: a facility with none
    is tracked by its overall capacity only. Never deleted; a cell that is no longer used is switched off."""

    class ReservedFor(models.TextChoices):
        ANY = "any", "Anyone"
        WOMEN = "women", "Women only"
        JUVENILES = "juveniles", "Juveniles only"
        MEN = "men", "Adult men only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility = models.ForeignKey(CustodyFacility, on_delete=models.PROTECT, related_name="cells")
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveSmallIntegerField()
    note = models.CharField(max_length=200, blank=True)  # e.g. medical observation
    # Who the cell is meant for. Set by the administration; the system only WARNS when someone else is placed there, it never blocks.
    reserved_for = models.CharField(max_length=10, choices=ReservedFor.choices, default=ReservedFor.ANY)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "custody_cells"
        ordering = ["facility", "code"]
        constraints = [models.UniqueConstraint(fields=["facility", "code"], name="cell_unique_code_per_facility"),
                       models.CheckConstraint(condition=models.Q(capacity__gte=1), name="cell_capacity_positive")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Cells cannot be deleted; switch them off instead.")


class DetentionRecord(models.Model):
    class Status(models.TextChoices):
        IN_CUSTODY = "in_custody", "In custody"
        RELEASED = "released", "Released"
        TRANSFERRED = "transferred", "Transferred"
        VOID = "void", "Void"

    class Sex(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        UNKNOWN = "unknown", "Not recorded"

    class Outcome(models.TextChoices):
        NO_CHARGE = "no_charge", "Released without charge"
        BAIL = "bail", "Released on bail / guarantee"
        COURT_ORDER = "court_order", "Released on court order"
        SENTENCE_SERVED = "sentence_served", "Sentence served"
        TRANSFER_STATION = "transfer_station", "Transferred to another station"
        TRANSFER_COURT = "transfer_court", "Handed to the court"
        TRANSFER_PRISON = "transfer_prison", "Handed to the prison"
        DIED = "died_in_custody", "Died in custody"
        OTHER = "other", "Other"

    RELEASE_OUTCOMES = ("no_charge", "bail", "court_order", "sentence_served", "died_in_custody", "other")
    TRANSFER_OUTCOMES = ("transfer_station", "transfer_court", "transfer_prison")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    register_no = models.CharField(max_length=20, unique=True)  # DET-000001, system generated, never reused
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="detention_records")
    detainee_name = models.CharField(max_length=200)
    detainee_alias = models.CharField(max_length=200, blank=True)
    sex = models.CharField(max_length=8, choices=Sex.choices, default=Sex.UNKNOWN)
    age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    id_ref = models.CharField(max_length=80, blank=True)  # national ID / document number shown by the person, if any
    address = models.CharField(max_length=200, blank=True)
    booked_at = models.DateTimeField()
    arrest_place = models.CharField(max_length=200, blank=True)
    arresting_officer = models.ForeignKey("personnel.Personnel", null=True, blank=True, on_delete=models.PROTECT, related_name="detentions_made")
    arresting_officer_name = models.CharField(max_length=200, blank=True)  # when the officer has no personnel record
    reason = models.CharField(max_length=300)  # offence or ground for holding
    authority_ref = models.CharField(max_length=150, blank=True)  # warrant / court order / prosecutor instruction number
    cell = models.CharField(max_length=60, blank=True)
    cell_ref = models.ForeignKey(CustodyCell, null=True, blank=True, on_delete=models.PROTECT, related_name="records")
    facility = models.ForeignKey(CustodyFacility, null=True, blank=True, on_delete=models.PROTECT, related_name="records")  # the jail center holding the person
    destination_facility = models.ForeignKey(CustodyFacility, null=True, blank=True, on_delete=models.PROTECT, related_name="received")  # the prison, on hand-over
    property_held = models.CharField(max_length=500, blank=True)
    health_note = models.CharField(max_length=300, blank=True)
    # id_ref in a normalised form (upper case, letters and digits only) while the person is in custody, "" otherwise. The database allows
    # one in-custody row per key, so the same person cannot be held twice (at this or any other station).
    id_ref_key = models.CharField(max_length=80, blank=True, editable=False)
    last_review_at = models.DateTimeField(null=True, blank=True)  # latest custody review; the review clock restarts from it
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_CUSTODY)
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    case_ref = models.CharField(max_length=80, blank=True)  # case / investigation file number
    client_ref = models.CharField(max_length=36, blank=True)  # id made on the device for an offline entry: a re-sent booking is never created twice
    charge = models.CharField(max_length=300, blank=True)  # recorded once a charge exists
    charged_at = models.DateTimeField(null=True, blank=True)
    charged_by_username = models.CharField(max_length=150, blank=True)
    destination = models.CharField(max_length=200, blank=True)  # receiving station / court / prison for a transfer
    destination_unit = models.ForeignKey("organization.OrganizationalUnit", null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_detentions")
    outcome_ref = models.CharField(max_length=150, blank=True)  # court / bail / transfer order reference for the outcome
    # A station-to-station transfer is two steps: the sending station closes its record as "transferred" naming the receiving station,
    # and the receiving station then receives the person, which opens a new record pointing back here. Only once.
    received_at = models.DateTimeField(null=True, blank=True)  # set on the receiving station's record; booked_at stays the original arrest booking
    transferred_from = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="received_as")
    outcome_note = models.CharField(max_length=300, blank=True)
    created_by_username = models.CharField(max_length=150, blank=True)
    ended_by_username = models.CharField(max_length=150, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by_username = models.CharField(max_length=150, blank=True)
    voided_reason = models.CharField(max_length=300, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "detention_records"
        ordering = ["-booked_at"]
        indexes = [models.Index(fields=["org_unit", "status", "-booked_at"], name="det_unit_status_idx"),
                   models.Index(fields=["status", "-booked_at"], name="det_status_idx")]
        constraints = [models.CheckConstraint(condition=models.Q(ended_at__isnull=True) | models.Q(ended_at__gte=models.F("booked_at")),
                                              name="det_end_after_booking"),
                       models.UniqueConstraint(fields=["id_ref_key"], condition=~models.Q(id_ref_key=""), name="det_one_active_custody_per_id"),
                       models.UniqueConstraint(fields=["client_ref"], condition=~models.Q(client_ref=""), name="det_unique_client_ref")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Detention register rows cannot be deleted.")


class DetentionEvent(AppendOnlyModel):
    class Kind(models.TextChoices):
        BOOKED = "booked", "Booked in"
        WELFARE = "welfare", "Welfare check"
        MEDICAL = "medical", "Medical"
        VISIT = "visit", "Visit"
        CELL_MOVE = "cell_move", "Moved cell"
        PROPERTY = "property", "Property"
        STATEMENT = "statement", "Statement / interview"
        NOTE = "note", "Note"
        REVIEW = "review", "Custody review"
        COURT = "court", "Court"
        CHARGE = "charge", "Charge recorded"
        INCIDENT = "incident", "Custody incident"
        RECEIVED = "received", "Received from another station"
        RELEASED = "released", "Released"
        TRANSFERRED = "transferred", "Transferred"
        CORRECTED = "corrected", "Details corrected"
        VOIDED = "voided", "Voided"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(DetentionRecord, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    occurred_at = models.DateTimeField()
    text = models.CharField(max_length=500, blank=True)
    by_username = models.CharField(max_length=150, blank=True)
    client_ref = models.CharField(max_length=36, blank=True)  # offline entries: a re-sent event is never added twice
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "detention_events"
        ordering = ["occurred_at", "created_at"]
        indexes = [models.Index(fields=["record", "occurred_at"], name="detevt_record_idx")]
        constraints = [models.UniqueConstraint(fields=["client_ref"], condition=~models.Q(client_ref=""), name="detevt_unique_client_ref")]


class CourtHearing(models.Model):
    """A court date, remand order or bail hearing for a person in the register. The system only RECORDS what the court or prosecutor
    ordered and flags dates that are near or passed; it sets no legal limit of its own. Never deleted: a hearing that does not happen
    is marked cancelled or adjourned."""

    class Purpose(models.TextChoices):
        HEARING = "hearing", "Court hearing"
        REMAND = "remand", "Remand order"
        BAIL = "bail", "Bail hearing"
        SENTENCING = "sentencing", "Sentencing"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        HELD = "held", "Held"
        ADJOURNED = "adjourned", "Adjourned"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(DetentionRecord, on_delete=models.PROTECT, related_name="hearings")
    purpose = models.CharField(max_length=12, choices=Purpose.choices, default=Purpose.HEARING)
    hearing_at = models.DateTimeField(null=True, blank=True)  # next court date (a remand order may have only an end date)
    court = models.CharField(max_length=200, blank=True)
    ordered_by = models.CharField(max_length=200, blank=True)  # judge / prosecutor who ordered it
    order_ref = models.CharField(max_length=150, blank=True)
    remand_until = models.DateField(null=True, blank=True)  # the date the remand order runs to, as written in the order
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    note = models.CharField(max_length=300, blank=True)
    created_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "detention_hearings"
        ordering = ["hearing_at", "created_at"]
        indexes = [models.Index(fields=["record", "hearing_at"], name="dethear_record_idx")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Court hearings cannot be deleted; mark them cancelled instead.")


class CustodyIncident(models.Model):
    """A death, injury or use of force involving a person in custody. Reported by the station, read by the commanders above it, and
    reviewed by a regional authority (detention.incident_review), who cannot review their own report. The report itself is never
    edited or deleted; the review is added to it."""

    class Kind(models.TextChoices):
        DEATH = "death", "Death in custody"
        INJURY = "injury", "Injury"
        FORCE = "use_of_force", "Use of force"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(DetentionRecord, on_delete=models.PROTECT, related_name="incidents")
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="custody_incidents")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    occurred_at = models.DateTimeField()
    place = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=1000)
    people_involved = models.CharField(max_length=300, blank=True)  # staff / officers involved, as names or service numbers
    medical_attended = models.BooleanField(default=False)
    medical_note = models.CharField(max_length=300, blank=True)
    reported_by_username = models.CharField(max_length=150, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by_username = models.CharField(max_length=150, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "custody_incidents"
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["org_unit", "-occurred_at"], name="custinc_unit_idx")]

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Custody incident reports cannot be deleted.")


class ShiftHandover(AppendOnlyModel):
    """The note an officer leaves at the end of a shift: who is in custody, what is pending, what to watch. Never edited or deleted.
    `custody_snapshot` is taken by the server from the register at the moment of writing, so the note shows what was true then.
    The next officer acknowledges it (ShiftHandoverAck); the author cannot acknowledge their own note."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="shift_handovers")
    shift_ended_at = models.DateTimeField()
    custody_snapshot = models.JSONField(default=list)  # [{register_no, name, cell, held_hours, review_due, court_soon, remand_expired}]
    custody_note = models.CharField(max_length=1000, blank=True)  # the officer's own words about the people held (health, risk, visitors)
    pending = models.CharField(max_length=2000)
    watch = models.CharField(max_length=2000)
    written_by_username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shift_handovers"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["org_unit", "-created_at"], name="handover_unit_idx")]


class ShiftHandoverAck(AppendOnlyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    handover = models.OneToOneField(ShiftHandover, on_delete=models.PROTECT, related_name="ack")  # one acknowledgement per note, enforced by the database
    acknowledged_by_username = models.CharField(max_length=150)
    acknowledged_at = models.DateTimeField(auto_now_add=True)
    comment = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "shift_handover_acks"
