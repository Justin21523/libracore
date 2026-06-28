from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.acquisitions.models import (
    AcquisitionOrder,
    AcquisitionOrderLine,
    Fund,
    FundTransaction,
    Invoice,
    InvoiceLine,
    ReceivingEvent,
    Vendor,
)
from apps.acquisitions.services import match_invoice, place_order, receive_order_line
from apps.catalog.models import BibliographicRecord
from apps.core.models import AuditLog
from apps.holdings.models import Branch, Holding, Item, Location


@pytest.fixture
def acquisition_setup():
    vendor = Vendor.objects.create(code="bookco", name="Book Co.")
    branch = Branch.objects.create(code="main-acq", name="總館")
    location = Location.objects.create(branch=branch, code="processing", name="編目加工")
    fund = Fund.objects.create(
        code="books", name="圖書經費", fiscal_year="2026", allocated_amount=100000
    )
    order = AcquisitionOrder.objects.create(vendor=vendor, order_number="PO-2026-001")
    line = AcquisitionOrderLine.objects.create(
        order=order,
        title="採訪流程測試書",
        isbn="9789570000099",
        publisher="測試出版社",
        publication_date="2026",
        branch=branch,
        location=location,
        fund=fund,
        quantity=2,
        unit_price=Decimal("500.00"),
    )
    return {
        "vendor": vendor,
        "branch": branch,
        "location": location,
        "fund": fund,
        "order": order,
        "line": line,
    }


@pytest.mark.django_db
def test_order_receiving_creates_instance_holding_items_and_audit(acquisition_setup):
    place_order(order_id=acquisition_setup["order"].id)

    event = receive_order_line(
        order_line_id=acquisition_setup["line"].id,
        quantity=2,
        barcodes=["ACQ001", "ACQ002"],
    )

    acquisition_setup["order"].refresh_from_db()
    acquisition_setup["line"].refresh_from_db()
    assert acquisition_setup["order"].status == AcquisitionOrder.Status.RECEIVED
    assert (
        acquisition_setup["line"].receiving_status == AcquisitionOrderLine.ReceivingStatus.RECEIVED
    )
    assert ReceivingEvent.objects.count() == 1
    assert Holding.objects.filter(instance=acquisition_setup["line"].instance).count() == 1
    assert (
        Item.objects.filter(barcode__in=["ACQ001", "ACQ002"], status=Item.Status.IN_PROCESS).count()
        == 2
    )
    assert BibliographicRecord.objects.filter(
        source="acquisitions", status=BibliographicRecord.Status.APPROVED
    ).exists()
    assert event.created_items.count() == 2
    assert AuditLog.objects.filter(action="acquisition_order_line_received").exists()


@pytest.mark.django_db
def test_invoice_match_records_expenditure_and_release(acquisition_setup):
    place_order(order_id=acquisition_setup["order"].id)
    receive_order_line(order_line_id=acquisition_setup["line"].id, quantity=1, barcodes=["ACQ003"])
    invoice = Invoice.objects.create(
        vendor=acquisition_setup["vendor"],
        order=acquisition_setup["order"],
        invoice_number="INV-001",
        total_amount=Decimal("500.00"),
    )
    invoice_line = InvoiceLine.objects.create(
        invoice=invoice,
        order_line=acquisition_setup["line"],
        quantity=1,
        unit_price=Decimal("500.00"),
        line_total=Decimal("500.00"),
    )

    match_invoice(invoice_id=invoice.id)

    invoice.refresh_from_db()
    invoice_line.refresh_from_db()
    assert invoice.match_status == "matched"
    assert invoice_line.match_status == InvoiceLine.MatchStatus.MATCHED
    assert FundTransaction.objects.filter(
        fund=acquisition_setup["fund"],
        transaction_type=FundTransaction.TransactionType.EXPENDITURE,
        invoice_line=invoice_line,
    ).exists()


@pytest.mark.django_db
def test_acquisitions_api_receive_action_requires_staff_and_receives_item(acquisition_setup):
    staff = get_user_model().objects.create_user(username="acq-api", password="x", is_staff=True)
    client = APIClient()
    client.force_authenticate(staff)
    place_order(order_id=acquisition_setup["order"].id)

    response = client.post(
        f"/api/acquisition-order-lines/{acquisition_setup['line'].id}/receive/",
        {"quantity": 1, "barcodes": ["API-ACQ-001"]},
        format="json",
    )

    assert response.status_code == 201
    assert Item.objects.filter(barcode="API-ACQ-001").exists()


@pytest.mark.django_db
def test_staff_acquisition_views_render_order_and_receive(acquisition_setup):
    staff = get_user_model().objects.create_user(username="acq-view", password="x", is_staff=True)
    client = Client()
    client.force_login(staff)

    detail = client.get(
        reverse("staff:acquisition_order_detail", args=[acquisition_setup["order"].id])
    )
    assert detail.status_code == 200
    assert "採訪流程測試書" in detail.content.decode()

    response = client.post(
        reverse("staff:acquisition_receive_line", args=[acquisition_setup["line"].id]),
        {"quantity": "1", "barcodes": "VIEW-ACQ-001"},
    )
    assert response.status_code == 302
    assert Item.objects.filter(barcode="VIEW-ACQ-001").exists()
