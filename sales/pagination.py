from rest_framework.pagination import CursorPagination


class SaleCursorPagination(CursorPagination):
    """Stable paging over a list that keeps growing while the app scrolls."""

    page_size = 30
    ordering = ('-created_at', '-id')