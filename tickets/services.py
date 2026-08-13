# tickets/services.py
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from .models import Inventory, Hold,Purchase, Waitlist

HOLD_DURATION_MINUTES = 1

class HoldNotFoundError(Exception):
    pass

class HoldNotConfirmableError(Exception):
    """Raised when a hold is expired , already confirmed, or otherwise invalid."""
    pass
    

class InsufficientInventoryError(Exception):
    """Raised when there aren't enough available tickets to fulfill the request."""
    pass


def create_hold(event_id, user_id, quantity):
    """
    Attempts to create a temporary hold for `quantity` tickets on `event_id`.
    Locks the event's inventory row so concurrent requests for the SAME event
    are serialized, while requests for OTHER events proceed independently.
    """
    with transaction.atomic():
        # select_for_update() locks this specific row until the transaction
        # commits or rolls back. Other transactions trying to lock the same
        # row will wait here; transactions on a DIFFERENT event's row are unaffected.
        inventory = Inventory.objects.select_for_update().get(event_id=event_id)

        if inventory.available_tickets < quantity:
            raise InsufficientInventoryError(
                f"Requested {quantity}, only {inventory.available_tickets} available."
            )

        inventory.available_tickets -= quantity
        inventory.save()

        hold = Hold.objects.create(
            event_id=event_id,
            user_id=user_id,
            quantity=quantity,
            status=Hold.HELD,
            expires_at=timezone.now() + timedelta(minutes=HOLD_DURATION_MINUTES),
        )

    return hold
def confirm_hold(hold_id, idempotency_key):
    """
    Confirms a HELD, non-expired hold and converts it into a Purchase.
    Idempotent: if a Purchase already exists for this idempotency_key,
    returns that existing Purchase instead of creating a new one.
    """
    # Fast path: check if this exact confirmation was already processed.
    # This handles retries without even needing to touch the Hold row.
    existing = Purchase.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    with transaction.atomic():
        try:
            hold = Hold.objects.select_for_update().get(id=hold_id)
        except Hold.DoesNotExist:
            raise HoldNotFoundError(f"Hold {hold_id} does not exist.")

        # Re-check idempotency INSIDE the lock too — covers the race where
        # two identical requests both passed the fast-path check above
        # before either had committed.
        existing = Purchase.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        if hold.status != Hold.HELD:
            raise HoldNotConfirmableError(
                f"Hold {hold_id} is '{hold.status}', cannot confirm."
            )

        if hold.expires_at <= timezone.now():
            raise HoldNotConfirmableError(f"Hold {hold_id} has expired.")

        purchase = Purchase.objects.create(
            hold=hold,
            event_id=hold.event_id,
            user_id=hold.user_id,
            quantity=hold.quantity,
            idempotency_key=idempotency_key,
        )

        hold.status = Hold.CONFIRMED
        hold.save()

    return purchase
def release_expired_hold(hold_id):
    with transaction.atomic():
        try:
            hold = Hold.objects.select_for_update().get(id=hold_id)
        except Hold.DoesNotExist:
            return None

        if hold.status != Hold.HELD:
            return None

        if hold.expires_at > timezone.now():
            return None

        inventory = Inventory.objects.select_for_update().get(event_id=hold.event_id)
        inventory.available_tickets += hold.quantity
        inventory.save()

        hold.status = Hold.EXPIRED
        hold.save()

    # Trigger backfill AFTER the release transaction commits, in its own
    # transaction — matches section 8's failure-recovery design: if backfill
    # fails, the release itself is already safely committed and won't be
    # undone or retried incorrectly.
    backfill_waitlist(hold.event_id)

    return hold


def expire_all_due_holds():
    """
    Finds all HELD holds whose expiry time has passed and releases each
    one individually (each in its own transaction, so one failure doesn't
    roll back the others).
    """
    expired_ids = list(
        Hold.objects.filter(
            status=Hold.HELD,
            expires_at__lte=timezone.now(),
        ).values_list('id', flat=True)
    )

    released = []
    for hold_id in expired_ids:
        result = release_expired_hold(hold_id)
        if result:
            released.append(result)

    return released
def join_waitlist(event_id, user_id, quantity):
    """
    Adds a user to the FIFO waitlist for an event. Simple insert — no
    locking needed here since we're not touching inventory, just recording
    intent to wait.
    """
    entry = Waitlist.objects.create(
        event_id=event_id,
        user_id=user_id,
        quantity=quantity,
        status=Waitlist.WAITING,
    )
    return entry
def backfill_waitlist(event_id):
    """
    Attempts to fulfill eligible waitlist entries for an event using
    currently available inventory. Processes entries in FIFO order.
    All-or-nothing: an entry is either fully satisfied or skipped (left
    WAITING) so later, smaller entries can still use the available tickets.

    Each fulfilled entry gets a HELD hold created for it (not an immediate
    purchase) — the user still has to go through normal confirmation before
    the hold's own expiry window closes.
    """
    fulfilled = []

    with transaction.atomic():
        # Lock the inventory row for the whole backfill pass so no other
        # worker can allocate from the same pool concurrently.
        inventory = Inventory.objects.select_for_update().get(event_id=event_id)

        waiting_entries = Waitlist.objects.select_for_update().filter(
            event_id=event_id,
            status=Waitlist.WAITING,
        ).order_by('created_at')

        for entry in waiting_entries:
            if entry.quantity <= inventory.available_tickets:
                # Fulfill: create a hold, decrement inventory, mark FULFILLED
                inventory.available_tickets -= entry.quantity
                inventory.save()

                hold = Hold.objects.create(
                    event_id=event_id,
                    user_id=entry.user_id,
                    quantity=entry.quantity,
                    status=Hold.HELD,
                    expires_at=timezone.now() + timedelta(minutes=HOLD_DURATION_MINUTES),
                )

                entry.status = Waitlist.FULFILLED
                entry.save()

                fulfilled.append((entry, hold))
            # else: skip this entry, leave it WAITING, move to the next one
            # (this is the "unfulfillable request doesn't block later ones" rule)

    return fulfilled
def get_waitlist_status(waitlist_id):
    """
    Returns the current status of a waitlist entry. If it's been fulfilled,
    also finds the Hold that was created for it, so the frontend can show
    the confirm/countdown panel.
    """
    entry = Waitlist.objects.get(id=waitlist_id)

    result = {
        "waitlist_id": entry.id,
        "status": entry.status,
        "hold": None,
    }

    if entry.status == Waitlist.FULFILLED:
        hold = Hold.objects.filter(
            event_id=entry.event_id,
            user_id=entry.user_id,
            quantity=entry.quantity,
            status=Hold.HELD,
            created_at__gte=entry.created_at,
        ).order_by('created_at').first()

        if hold:
            result["hold"] = {
                "hold_id": hold.id,
                "quantity": hold.quantity,
                "expires_at": hold.expires_at.isoformat(),
            }

    return result
