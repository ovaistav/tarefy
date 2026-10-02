from django.urls import path

from .views import PartyDetailView, PartyListCreateView

urlpatterns = [
    path('parties/', PartyListCreateView.as_view(), name='party-list-create'),
    path('parties/<int:pk>/', PartyDetailView.as_view(), name='party-detail'),
]