from django.core.management.base import BaseCommand
from tickets.services import expire_all_due_holds


class Command(BaseCommand):
    help = "Finds and releases all expired HELD holds."

    def handle(self, *args, **options):
        released = expire_all_due_holds()
        if released:
            for hold in released:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Released hold {hold.id} (event {hold.event_id}, qty {hold.quantity})"
                    )
                )
        else:
            self.stdout.write("No expired holds found.")