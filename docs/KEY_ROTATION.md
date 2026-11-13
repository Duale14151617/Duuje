# Rotating the field-encryption key

`FIELD_ENCRYPTION_KEY` protects MFA secrets, personnel records and photos, documents, vehicle and equipment files and payment details.
It accepts several keys separated by commas. The FIRST is used to write; all of them can read.

1. **Back up the database first** (and keep the current key somewhere safe: without it the data cannot be read).
2. **Pin the weapon-ID key.** Set `FIELD_HMAC_KEY` to your CURRENT key. Weapon-ID matching is keyed with it and must not change.
3. Generate a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
4. Set `FIELD_ENCRYPTION_KEY=<new>,<current>` and deploy. Nothing breaks: new data uses the new key, old data still reads.
5. Run `python manage.py rotate_encryption_key` (dry run), then `python manage.py rotate_encryption_key --apply`.
6. When it reports "Everything is under the new key", set `FIELD_ENCRYPTION_KEY=<new>` and deploy.
   If it says some values are still under an older key (append-only tables such as disciplinary records), keep the old key listed.
7. Keep a copy of the retired key until you have a backup taken after step 6 that you have verified.

Rotate on a schedule (yearly) and immediately if the key may have leaked.
