from django.urls import path

from .views import (
    PorterageSettingsView,
    SaleAccountView,
    SaleDetailView,
    SaleFinalizeView,
    SaleLineCreateView,
    SaleLineDetailView,
    SaleListCreateView,
    SalePaymentCreateView,
    SalePaymentDetailView,
    SalePorterageView,
)

urlpatterns = [
    path('sales/', SaleListCreateView.as_view(), name='sale-list-create'),
    # Declared before the <int:pk> patterns so the intent stays obvious.
    path(
        'sales/porterage-settings/',
        PorterageSettingsView.as_view(),
        name='porterage-settings',
    ),
    path('sales/', SaleListCreateView.as_view(), name='sale-list-create'),
    path('sales/<int:pk>/', SaleDetailView.as_view(), name='sale-detail'),
    path('sales/<int:pk>/lines/', SaleLineCreateView.as_view(), name='sale-line-create'),
    path(
        'sales/<int:pk>/lines/<int:line_id>/',
        SaleLineDetailView.as_view(),
        name='sale-line-detail',
    ),
    path(
        'sales/<int:pk>/porterage/',
        SalePorterageView.as_view(),
        name='sale-porterage',
    ),
    path(
        'sales/<int:pk>/payments/',
        SalePaymentCreateView.as_view(),
        name='sale-payment-create',
    ),
    path(
        'sales/<int:pk>/payments/<int:payment_id>/',
        SalePaymentDetailView.as_view(),
        name='sale-payment-detail',
    ),
    path('sales/<int:pk>/account/', SaleAccountView.as_view(), name='sale-account'),
    path('sales/<int:pk>/finalize/', SaleFinalizeView.as_view(), name='sale-finalize'),
]