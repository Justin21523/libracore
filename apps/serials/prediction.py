from __future__ import annotations

from django.utils import timezone

from .models import IssuePredictionPattern


def next_expected_date(date, frequency: str):
    if frequency == IssuePredictionPattern.Frequency.DAILY:
        return date + timezone.timedelta(days=1)
    if frequency == IssuePredictionPattern.Frequency.WEEKLY:
        return date + timezone.timedelta(days=7)
    if frequency == IssuePredictionPattern.Frequency.QUARTERLY:
        return _add_months(date, 3)
    if frequency == IssuePredictionPattern.Frequency.ANNUAL:
        return _add_months(date, 12)
    return _add_months(date, 1)


def issue_labels(pattern: IssuePredictionPattern):
    captions = pattern.enumeration_captions or ["v.", "no."]
    number_caption = captions[1] if len(captions) > 1 else "no."
    enumeration = f"{captions[0]} {pattern.next_volume} {number_caption} {pattern.next_number}"
    chronology = pattern.chronology_template.format(
        year=pattern.next_expected_at.year,
        month=pattern.next_expected_at.month,
        day=pattern.next_expected_at.day,
    )
    data = {
        "volume": pattern.next_volume,
        "number": pattern.next_number,
        "expected_at": pattern.next_expected_at.isoformat(),
        "frequency": pattern.frequency,
    }
    return enumeration, chronology, data


def advance_pattern(pattern: IssuePredictionPattern) -> None:
    pattern.next_number += 1
    if pattern.next_number > pattern.issues_per_volume:
        pattern.next_volume += 1
        pattern.next_number = 1
    pattern.next_expected_at = next_expected_date(pattern.next_expected_at, pattern.frequency)
    pattern.save(update_fields=["next_volume", "next_number", "next_expected_at", "updated_at"])


def _add_months(date, months: int):
    month = date.month - 1 + months
    year = date.year + month // 12
    month = month % 12 + 1
    day = min(
        date.day,
        [
            31,
            29 if year % 4 == 0 and not year % 100 == 0 or year % 400 == 0 else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ][month - 1],
    )
    return date.replace(year=year, month=month, day=day)
