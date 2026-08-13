from django.urls import path
from .views import event_list_page, event_create_page, event_detail_page,stress_test_page

urlpatterns = [
    path('', event_list_page, name='event-list-page'),
    path('events/create/', event_create_page, name='event-create-page'),
    path('events/<int:event_id>/', event_detail_page, name='event-detail-page'),
    path('stress-test/',stress_test_page, name='stress-test-page'),
]