"""Puntland Police departments under each regional Police command (configurable; confirm with Puntland authorities).

Department names come from the Puntland Police website's list and are NOT confirmed structure. CID is a restricted
department INSIDE the Police branch (never a separate institution): only roles holding `cid.access` can reach its records.
Idempotent: creates missing units, never renames or deletes, and never loosens an existing restriction.
"""
DEPARTMENTS = [  # code, name, restricted
    ("PERS", "Personnel", False),
    ("OPS", "Operations", False),
    ("TRN", "Training", False),
    ("FINLOG", "Finance and Logistics", False),
    ("CID", "Criminal Investigation Department (CID)", True),
    ("PR", "Public Relations", False),
    ("TRAFFIC", "Traffic and Safety", False),
]


def ensure_police_module(OU, region_codes):
    created = 0
    for region in region_codes:
        command = OU.objects.filter(code=f"{region}-POLICE").first()
        if command is None:
            continue
        for code, name, restricted in DEPARTMENTS:
            unit = OU.objects.filter(code=f"{region}-POLICE-{code}").first()
            if unit is None:
                label = f"{region.title()} Police {name}"
                OU.objects.create(code=f"{region}-POLICE-{code}", name_en=label, name_so=label, level=OU.Level.UNIT,
                                  parent=command, restricted=restricted)
                created += 1
            elif restricted and not unit.restricted:
                OU.objects.filter(pk=unit.pk).update(restricted=True)
    return created
