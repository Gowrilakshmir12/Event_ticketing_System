from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone as dj_timezone

from .models import Event, Inventory,Waitlist

from .models import Inventory, Hold
from .serializers import (
    InventorySerializer,
    HoldCreateSerializer,
    HoldResponseSerializer,
    WaitlistCreateSerializer,
    WaitlistResponseSerializer,
)
from .services import (
    create_hold,
    confirm_hold,
    join_waitlist,
    get_waitlist_status,
    InsufficientInventoryError,
    HoldNotFoundError,
    HoldNotConfirmableError,
)


class InventoryView(APIView):
    def get(self, request, event_id):
        try:
            inventory = Inventory.objects.get(event_id=event_id)
        except Inventory.DoesNotExist:
            return Response({"detail": "Event not found."}, status=http_status.HTTP_404_NOT_FOUND)

        serializer = InventorySerializer(inventory)
        return Response(serializer.data)


class HoldCreateView(APIView):
    def post(self, request, event_id):
        serializer = HoldCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            hold = create_hold(
                event_id=event_id,
                user_id=serializer.validated_data['user_id'],
                quantity=serializer.validated_data['quantity'],
            )
        except Inventory.DoesNotExist:
            return Response({"detail": "Event not found."}, status=http_status.HTTP_404_NOT_FOUND)
        except InsufficientInventoryError as e:
            return Response({"detail": str(e)}, status=http_status.HTTP_409_CONFLICT)

        return Response(HoldResponseSerializer(hold).data, status=http_status.HTTP_201_CREATED)


class HoldConfirmView(APIView):
    def post(self, request, hold_id):
        idempotency_key = request.headers.get('Idempotency-Key')
        if not idempotency_key:
            return Response(
                {"detail": "Idempotency-Key header is required."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        try:
            purchase = confirm_hold(hold_id=hold_id, idempotency_key=idempotency_key)
        except HoldNotFoundError as e:
            return Response({"detail": str(e)}, status=http_status.HTTP_404_NOT_FOUND)
        except HoldNotConfirmableError as e:
            return Response({"detail": str(e)}, status=http_status.HTTP_409_CONFLICT)

        return Response({
            "hold_id": purchase.hold_id,
            "purchase_id": purchase.id,
            "status": "CONFIRMED",
        })


class WaitlistCreateView(APIView):
    def post(self, request, event_id):
        serializer = WaitlistCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        entry = join_waitlist(
            event_id=event_id,
            user_id=serializer.validated_data['user_id'],
            quantity=serializer.validated_data['quantity'],
        )

        return Response(WaitlistResponseSerializer(entry).data, status=http_status.HTTP_201_CREATED)





def event_list_page(request):
    events = Event.objects.select_related('inventory').order_by('event_date')
    return render(request, 'tickets/event_list.html', {'events': events})


def event_create_page(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        event_date = parse_datetime(request.POST.get('event_date'))
        if event_date and dj_timezone.is_naive(event_date):
            event_date = dj_timezone.make_aware(event_date)
        total_tickets = int(request.POST.get('total_tickets'))

        event = Event.objects.create(name=name, description=description, event_date=event_date)
        Inventory.objects.create(event=event, total_tickets=total_tickets, available_tickets=total_tickets)

        return redirect('event-detail-page', event_id=event.id)

    return render(request, 'tickets/event_create.html')


def event_detail_page(request, event_id):
    event = get_object_or_404(Event.objects.select_related('inventory'), id=event_id)
    return render(request, 'tickets/event_detail.html', {'event': event})
def stress_test_page(request):
    events = Event.objects.select_related('inventory').order_by('event_date')
    return render(request, 'tickets/stress_test.html', {'events': events})
class WaitlistStatusView(APIView):
    def get(self, request, waitlist_id):
        try:
            data = get_waitlist_status(waitlist_id)
        except Waitlist.DoesNotExist:
            return Response({"detail": "Waitlist entry not found."}, status=404)
        return Response(data)