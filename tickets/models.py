from django.db import models


class Event(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    event_date = models.DateTimeField()

    def __str__(self):
        return self.name


class Inventory(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='inventory')
    total_tickets = models.PositiveIntegerField()
    available_tickets = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(available_tickets__lte=models.F('total_tickets')),
                name='available_lte_total',
            ),
        ]

    def __str__(self):
        return f"{self.event.name}: {self.available_tickets}/{self.total_tickets}"


class Hold(models.Model):
    HELD = 'HELD'
    CONFIRMED = 'CONFIRMED'
    EXPIRED = 'EXPIRED'
    STATUS_CHOICES = [
        (HELD, 'Held'),
        (CONFIRMED, 'Confirmed'),
        (EXPIRED, 'Expired'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='holds')
    user_id = models.IntegerField()
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=HELD)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    idempotency_key = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'expires_at'], name='hold_status_expiry_idx'),
        ]

    def __str__(self):
        return f"Hold #{self.id} ({self.status}) - {self.quantity} for event {self.event_id}"


class Purchase(models.Model):
    hold = models.OneToOneField(Hold, on_delete=models.CASCADE, related_name='purchase')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='purchases')
    user_id = models.IntegerField()
    quantity = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Purchase #{self.id} for hold {self.hold_id}"


class Waitlist(models.Model):
    WAITING = 'WAITING'
    FULFILLED = 'FULFILLED'
    STATUS_CHOICES = [
        (WAITING, 'Waiting'),
        (FULFILLED, 'Fulfilled'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='waitlist_entries')
    user_id = models.IntegerField()
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=WAITING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['event', 'status', 'created_at'], name='waitlist_fifo_idx'),
        ]

    def __str__(self):
        return f"Waitlist #{self.id} ({self.status}) - {self.quantity} for event {self.event_id}"