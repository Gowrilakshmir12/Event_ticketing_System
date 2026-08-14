from django.core.management.base import BaseCommand
from tickets.models import Event
from tickets.services import backfill_waitlist


class Command(BaseCommand):
    help = "Runs waitlist backfill for every event, catching any inventory increases not triggered by hold expiry."

    def handle(self, *args, **options):
        for event in Event.objects.select_related('inventory').all():
            if not hasattr(event, 'inventory'):
                continue

            fulfilled = backfill_waitlist(event_id=event.id)
            if fulfilled:
                for entry, hold in fulfilled:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Backfilled waitlist entry {entry.id} (user {entry.user_id}, event {event.id}) -> hold {hold.id}"
                        )
                    )