from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from tickets.models import Event, Inventory


class Command(BaseCommand):
    help = "Seeds the database with sample events and inventory for testing."

    def handle(self, *args, **options):
        # Wipe existing sample data so this command is safely re-runnable
        Event.objects.filter(name__startswith="Sample Event").delete()

        events_data = [
            {"name": "Sample Event - Concert", "total_tickets": 10},
            {"name": "Sample Event - Conference", "total_tickets": 50},
            {"name": "Sample Event - Workshop", "total_tickets": 5},
        ]

        for data in events_data:
            event = Event.objects.create(
                name=data["name"],
                description=f"Auto-generated sample event: {data['name']}",
                event_date=timezone.now() + timedelta(days=30),
            )
            Inventory.objects.create(
                event=event,
                total_tickets=data["total_tickets"],
                available_tickets=data["total_tickets"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created '{event.name}' (id={event.id}) with {data['total_tickets']} tickets"
                )
            )
            