from django.http import HttpResponse, JsonResponse

from .oai import oai_response
from .sru import sru_search_response


def oai_endpoint(request):
    return HttpResponse(oai_response(request), content_type="text/xml; charset=utf-8")


def sru_endpoint(request):
    start_record = _positive_int(request.GET.get("startRecord"), default=1)
    maximum_records = _positive_int(request.GET.get("maximumRecords"), default=10)
    payload = sru_search_response(
        request.GET.get("query", ""),
        start_record=start_record,
        maximum_records=maximum_records,
        record_schema=request.GET.get("recordSchema", "json"),
    )
    return JsonResponse(payload)


def _positive_int(value, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)
