from django.shortcuts import get_object_or_404, render

from apps.catalog.models import BibliographicRecord, InstanceContributor, WorkAuthorityLink

from .models import AuthorityRecord


def authority_browse(request):
    authorities = _filtered_authorities(request).order_by("access_points__sort_key", "created_at").distinct()[:100]
    return render(
        request,
        "opac/authorities/browse.html",
        {"authorities": authorities, "query": request.GET.get("q", ""), "authority_type": request.GET.get("authority_type", "")},
    )


def subject_browse(request):
    request.GET = request.GET.copy()
    subject_types = [
        AuthorityRecord.AuthorityType.SUBJECT,
        AuthorityRecord.AuthorityType.GENRE,
        AuthorityRecord.AuthorityType.PLACE,
        AuthorityRecord.AuthorityType.WORK_TITLE,
    ]
    authorities = _filtered_authorities(request).filter(authority_type__in=subject_types).distinct()[:100]
    return render(request, "opac/authorities/subjects.html", {"authorities": authorities, "query": request.GET.get("q", "")})


def authority_detail(request, authority_id):
    authority = get_object_or_404(
        AuthorityRecord.objects.prefetch_related(
            "access_points",
            "external_identifiers",
            "outgoing_relations__target__access_points",
            "incoming_relations__source__access_points",
        ),
        id=authority_id,
    )
    linked_records = _linked_records(authority)
    return render(
        request,
        "opac/authorities/detail.html",
        {"authority": authority, "linked_records": linked_records},
    )


def _filtered_authorities(request):
    queryset = AuthorityRecord.objects.prefetch_related("access_points")
    if request.GET.get("q"):
        queryset = queryset.filter(access_points__label__icontains=request.GET["q"])
    if request.GET.get("authority_type"):
        queryset = queryset.filter(authority_type=request.GET["authority_type"])
    return queryset


def _linked_records(authority):
    work_ids = WorkAuthorityLink.objects.filter(authority=authority).values_list("work_id", flat=True)
    instance_ids = InstanceContributor.objects.filter(authority=authority).values_list("instance_id", flat=True)
    return (
        BibliographicRecord.objects.filter(work_id__in=work_ids)
        | BibliographicRecord.objects.filter(instance_id__in=instance_ids)
    ).select_related("instance").distinct()

