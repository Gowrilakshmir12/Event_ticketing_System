from rest_framework import serializers
from .models import Inventory, Hold, Waitlist


class InventorySerializer(serializers.ModelSerializer):
    event_id = serializers.IntegerField(source='event.id')

    class Meta:
        model = Inventory
        fields = ['event_id', 'total_tickets', 'available_tickets']


class HoldCreateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class HoldResponseSerializer(serializers.ModelSerializer):
    hold_id = serializers.IntegerField(source='id')

    class Meta:
        model = Hold
        fields = ['hold_id', 'event_id', 'user_id', 'quantity', 'status', 'expires_at']


class WaitlistCreateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class WaitlistResponseSerializer(serializers.ModelSerializer):
    waitlist_id = serializers.IntegerField(source='id')

    class Meta:
        model = Waitlist
        fields = ['waitlist_id', 'event_id', 'status']