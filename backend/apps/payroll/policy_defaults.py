"""Default policy items. Every item is now confirmed by the institution (instruction of 2026-10-23), and every value can be revised later
through /payroll/policy/{key}/revise/ (authority reference and reason required, old and new value audited).
Seeded by migration payroll 0004 and again (idempotently) by `seed_reference_data`, so a fresh or restored database always has them."""

INSTRUCTION_REF = "Institution instruction 2026-10-23"

# key, title, description, status, value
POLICY = [
    ("month_of_death_salary", "Salary for the month of death",
     "The FULL salary for the month in which the soldier dies is paid, with no proration, through the normal verification and approval process.",
     "confirmed", "full_month_no_proration"),
    ("survivor_benefit_duration", "Survivor benefit duration",
     "Survivor benefits are indefinite: no preset end date, no automatic expiry. Any change or termination needs a documented decision.",
     "confirmed", "indefinite"),
    ("survivor_priority_order", "Survivor priority order",
     "1. wife and children; 2. parents (only if no eligible wife or child); 3. siblings (only if no eligible parent).", "confirmed", "wife_children>parents>siblings"),
    ("suspended_jailed_interim_treatment", "Suspended and jailed personnel: interim treatment",
     "Until Finance approves a pay decision with a deduction tier for the person, the existing treatment is retained and the case is flagged. No automatic stop, reduction or withholding.",
     "confirmed", "retain_existing_and_flag"),
    ("payment_methods", "Payment methods", "Sahal mobile money and bank transfer.", "confirmed", "sahal,bank_transfer"),
    ("payment_provider_integration", "Provider integration",
     "No Sahal or bank API is integrated. Payments are made outside the system and recorded and reconciled here.", "confirmed", "none_manual_recording"),
    ("suspended_jailed_official_pay_rule", "Suspended and jailed personnel: official pay rule",
     "Suspended and jailed personnel are PAID, with a percentage deduction set by the severity of the case. The severity (and so the tier) is decided by Finance through a documented, separately approved pay decision. Tiers are listed in suspended_jailed_deduction_tiers.",
     "confirmed", "paid_with_severity_deduction"),
    ("suspended_jailed_deduction_tiers", "Suspended and jailed personnel: deduction tiers (percent)",
     "The allowed deduction percentages, as a comma-separated list. The tier for a case is chosen by Finance in the approved pay decision.", "confirmed", "5,10,20"),
    ("survivor_allocation_rule", "Survivor allocation among beneficiaries",
     "The priority order decides WHO is paid (wife and children, then parents, then siblings). Within the paid class, the benefit is divided according to Sharia law. The system holds no share formula: each amount is typed by an officer citing the decision, then authorized by a different officer.",
     "confirmed", "priority_order_then_sharia_division"),
    ("survivor_eligibility_conditions", "Survivor eligibility conditions",
     "Eligible survivors are the soldier's wife and children first, then parents, then siblings, in that order. No age, marital-status or proof rule is applied automatically; the verification step checks the evidence.", "confirmed", "wife_children>parents>siblings"),
    ("survivor_priority_after_loss", "Priority when a higher-priority beneficiary ceases",
     "The priority order stands: when no eligible wife or child remains, parents become eligible; when no eligible parent remains, siblings. Each change needs a documented decision.", "confirmed", "wife_children>parents>siblings"),
    ("deceased_salary_recipient", "Who receives the month-of-death salary and arrears",
     "Paid to the verified beneficiaries of the soldier's survivor case, following the priority order, with the division according to Sharia law.", "confirmed", "priority_order_then_sharia_division"),
    ("arrears_entitlement_rules", "Arrears entitlement and limits",
     "Which unpaid periods are payable, and any time limit, is decided by Finance. Every claim is verified and approved individually; nothing expires or is forfeited automatically.", "confirmed", "finance_decides"),
    ("payroll_currency", "Payroll currency", "Official payroll currency: US dollars.", "confirmed", "USD"),
]


def seed_policy(model):
    """Create any missing item; never overwrite an existing row (an officer may have confirmed it since)."""
    for key, title, description, status, value in POLICY:
        model.objects.get_or_create(key=key, defaults={"title": title, "description": description, "status": status, "value": value,
                                                       "authority_ref": INSTRUCTION_REF if status == "confirmed" else ""})


def upgrade_open_items(model):
    """For databases seeded earlier: fill in the rows that are STILL unconfirmed with the institution's answers, and add the new
    tier row. Rows an officer has already confirmed or revised are never touched."""
    seed_policy(model)
    for key, title, description, status, value in POLICY:
        if status == "confirmed":
            model.objects.filter(key=key, status="unconfirmed").update(title=title, description=description, status="confirmed", value=value,
                                                                       authority_ref=INSTRUCTION_REF)
