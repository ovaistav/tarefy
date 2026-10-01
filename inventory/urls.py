from django.urls import path

from .views import LoadFinishView, LoadListCreateView, LoadRestoreView

urlpatterns = [
    path('loads/', LoadListCreateView.as_view(), name='load-list-create'),
    path('loads/<int:pk>/finish/', LoadFinishView.as_view(), name='load-finish'),
    path(
        'loads/<int:pk>/restore/', LoadRestoreView.as_view(), name='load-restore'
    ),
]
