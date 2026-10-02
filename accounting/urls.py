from django.urls import path

from .views import BankListView

urlpatterns = [
    path('banks/', BankListView.as_view(), name='bank-list'),
]