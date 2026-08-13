from django.urls import path
from .views import InventoryView, HoldCreateView, HoldConfirmView, WaitlistCreateView,WaitlistStatusView

urlpatterns = [
    path('events/<int:event_id>/inventory/', InventoryView.as_view(), name='event-inventory'),
    path('events/<int:event_id>/holds/', HoldCreateView.as_view(), name='hold-create'),
    path('holds/<int:hold_id>/confirm/', HoldConfirmView.as_view(), name='hold-confirm'),
    path('events/<int:event_id>/waitlist/', WaitlistCreateView.as_view(), name='waitlist-create'),
    path('waitlist/<int:waitlist_id>/status/',WaitlistStatusView.as_view(), name='waitlist-status'),
]