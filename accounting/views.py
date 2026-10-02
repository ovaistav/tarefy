from rest_framework.generics import ListAPIView

from .models import Bank
from .serializers import BankSerializer


class BankListView(ListAPIView):
    """Read only: banks are created through the admin or seed_demo."""

    serializer_class = BankSerializer
    pagination_class = None

    def get_queryset(self):
        return Bank.objects.all().order_by('name')