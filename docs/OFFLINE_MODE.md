# Offline mode

## For officers
1. **Once, while online and signed in:** open *Offline desk*, choose a passphrase (8+ characters) and press *Prepare this device*, then *Download station and detainee lists*. Repeat the download whenever you are online so the lists stay current.
2. **With no internet:** open the app (or the *Offline desk* link on the sign-in screen), unlock with your passphrase, and enter bookings or log entries. They are saved encrypted on the device.
3. **When the connection returns:** sign in, open the desk, press *Send now*. For each booking the server gives a register number; write it in the paper register.
4. Entries marked *Needs attention* were refused by the server (for example the person was already booked elsewhere, or the record was closed). Read the reason, fix it online, then discard the offline copy.

## Limits (deliberate)
- Offline: booking and log entries only. Cell choice, moves, releases, transfers, court, charges and incidents need current data and are done online.
- The device clock stamps entries. Keep it correct. The server rejects times in the future or before the booking.
- A forgotten passphrase cannot be recovered. Wiping removes unsent entries for good.
- Anyone who has the device **and** the passphrase can read the vault, so do not share the passphrase; send entries before handing a device over.
- The offline lists are a snapshot: people booked after the download do not appear until the next download.

## Technical notes
- Vault: IndexedDB `policehq-offline`; AES-GCM 256, PBKDF2-SHA256 600,000 iterations, key in memory only. Only the count of waiting items is readable while locked.
- Idempotency: `client_ref` (UUID) on `DetentionRecord` and `DetentionEvent`, partial unique constraints; re-sent requests answer 200 with `already_recorded: true`.
- Offline events bypass the record version (they only append) but not any other rule; only kinds in `OFFLINE_EVENT_KINDS` are accepted with `offline: true`.
- Service worker `policehq-v2` caches the generic HTML shell for navigations only; `/api/` is never cached.
- Not tested in this build environment (no Django or browser available): run `python manage.py test apps.detention.tests.test_offline` and try the desk in Chrome with the network switched off.
