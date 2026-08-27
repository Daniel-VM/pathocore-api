from email.utils import parseaddr

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


def _email_domain(address):
    _, parsed_address = parseaddr(address or "")
    if "@" not in parsed_address:
        return ""
    return parsed_address.rsplit("@", 1)[1].lower()


class Command(BaseCommand):
    help = "Send a test email using the active Django email settings."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Recipient email address.")
        parser.add_argument(
            "--subject",
            default="PathoCore email test",
            help="Email subject. Default: PathoCore email test",
        )
        parser.add_argument(
            "--message",
            default="This is a PathoCore email test.",
            help="Plain-text email body.",
        )
        parser.add_argument(
            "--from-email",
            default=None,
            help="Sender address. Defaults to DEFAULT_FROM_EMAIL.",
        )
        parser.add_argument(
            "--ignore-domain-policy",
            action="store_true",
            help="Skip ALLOWED_EMAIL_DOMAINS validation for this test send.",
        )

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        from_email = options["from_email"] or settings.DEFAULT_FROM_EMAIL
        allowed_domains = {
            domain.lower() for domain in getattr(settings, "ALLOWED_EMAIL_DOMAINS", [])
        }

        if not _email_domain(recipient):
            raise CommandError("recipient must be a valid email address")

        recipient_domain = _email_domain(recipient)
        if (
            allowed_domains
            and not options["ignore_domain_policy"]
            and recipient_domain not in allowed_domains
        ):
            raise CommandError(
                "recipient domain '%s' is not in ALLOWED_EMAIL_DOMAINS"
                % recipient_domain
            )

        self.stdout.write("EMAIL_BACKEND=%s" % settings.EMAIL_BACKEND)
        self.stdout.write("EMAIL_HOST=%s" % getattr(settings, "EMAIL_HOST", ""))
        self.stdout.write("EMAIL_PORT=%s" % getattr(settings, "EMAIL_PORT", ""))
        self.stdout.write("EMAIL_USE_TLS=%s" % getattr(settings, "EMAIL_USE_TLS", ""))
        self.stdout.write("DEFAULT_FROM_EMAIL=%s" % settings.DEFAULT_FROM_EMAIL)
        if allowed_domains:
            self.stdout.write(
                "ALLOWED_EMAIL_DOMAINS=%s" % ",".join(sorted(allowed_domains))
            )

        sent_count = send_mail(
            options["subject"],
            options["message"],
            from_email,
            [recipient],
            fail_silently=False,
        )

        self.stdout.write(
            self.style.SUCCESS("Sent %s test email(s) to %s" % (sent_count, recipient))
        )
