"""Make a signing key pair for position archives. Prints both halves; nothing is stored."""
from django.core.management.base import BaseCommand

from apps.vehicles import archive


class Command(BaseCommand):
    help = "Make an Ed25519 key pair for signing position archives (set ARCHIVE_SIGNING_KEY from the private half)."

    def handle(self, *args, **opts):
        private, public = archive.keygen()
        self.stdout.write("Private key (secret; set as ARCHIVE_SIGNING_KEY on the machine that runs the archive command only):")
        self.stdout.write(private)
        self.stdout.write("\nPublic key (not secret; give to whoever must verify archives, or set as ARCHIVE_PUBLIC_KEYS):")
        self.stdout.write(public)
        self.stdout.write("\nStore the private key in your password vault or HSM, never in the repository or in database backups.")
