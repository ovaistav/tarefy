from django.http import Http404
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    MethodNotAllowed,
    ParseError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

# Persian details for the framework errors the app can receive.
PERSIAN_ERRORS = (
    (ParseError, status.HTTP_400_BAD_REQUEST, _('قالب درخواست نامعتبر است.')),
    (
        MethodNotAllowed,
        status.HTTP_405_METHOD_NOT_ALLOWED,
        _('این متد مجاز نیست.'),
    ),
    (Http404, status.HTTP_404_NOT_FOUND, _('موردی با این مشخصات یافت نشد.')),
)


class ConflictAPIException(APIException):
    """409 with a machine readable ``code`` the Android app can branch on."""

    status_code = status.HTTP_409_CONFLICT
    default_code = 'conflict'

    def __init__(self, detail=None, code=None):
        super().__init__(detail or self.default_detail, code or self.default_code)


class StaleStateConflict(ConflictAPIException):
    default_code = 'stale_state'
    default_detail = 'وضعیت بارها تغییر کرده است. لطفاً دوباره تلاش کنید.'


class RestoreConflict(ConflictAPIException):
    default_code = 'restore_conflict'
    default_detail = 'بار دیگری با همین برچسب موجود است.'


def api_exception_handler(exc, context):
    if isinstance(exc, ConflictAPIException):
        return Response(
            {'code': exc.get_codes(), 'detail': str(exc.detail)},
            status=exc.status_code,
        )
    for exception_class, error_status, detail in PERSIAN_ERRORS:
        if isinstance(exc, exception_class):
            return Response({'detail': str(detail)}, status=error_status)
    return drf_exception_handler(exc, context)
