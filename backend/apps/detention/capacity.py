"""Capacity and occupancy of custody facilities, computed from the register (never stored, so it cannot drift).

* Capacity of a jail center = the sum of its active cells when it has cells, otherwise the capacity typed on the facility, otherwise
  unknown (None). Nothing here assumes or invents a number.
* Occupied = people currently in custody recorded against the facility (booked into a cell or not).
* Over capacity is reported, never enforced at the facility level (an arrest is never refused for lack of room); a cell, which is an
  explicit allocation, does refuse one person too many.
"""
from django.db.models import Count, Sum

from .models import CustodyCell, DetentionRecord


def stats_for(facility_ids):
    """{facility_id: {"cells": n, "cell_capacity": n, "held": n}} for the given facilities."""
    ids = list(facility_ids)
    out = {i: {"cells": 0, "cell_capacity": 0, "held": 0} for i in ids}
    for row in CustodyCell.objects.filter(facility_id__in=ids, active=True).values("facility_id").annotate(n=Count("id"), cap=Sum("capacity")):
        out[row["facility_id"]].update(cells=row["n"], cell_capacity=row["cap"] or 0)
    for row in DetentionRecord.objects.filter(facility_id__in=ids, status="in_custody").values("facility_id").annotate(n=Count("id")):
        out[row["facility_id"]]["held"] = row["n"]
    return out


def summarise(facility, st):
    cap = st["cell_capacity"] if st["cells"] else facility.capacity
    held = st["held"]
    return {"capacity": cap, "cells": st["cells"], "occupied": held,
            "available": None if cap is None else max(cap - held, 0), "over_capacity": cap is not None and held > cap}


def cell_occupancy(cell_ids):
    return {r["cell_ref_id"]: r["n"] for r in DetentionRecord.objects.filter(cell_ref_id__in=list(cell_ids), status="in_custody")
            .values("cell_ref_id").annotate(n=Count("id"))}
