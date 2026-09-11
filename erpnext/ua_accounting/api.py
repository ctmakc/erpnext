from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, formatdate, get_first_day, get_last_day, getdate, nowdate


_ALLOWED_VOUCHER_TYPES = {
    "Purchase Invoice",
    "Sales Invoice",
    "Payment Entry",
    "Journal Entry",
    "Purchase Receipt",
    "Stock Entry",
}


def _current_company() -> str:
    company = frappe.defaults.get_user_default("Company")
    if company:
        return company

    companies = frappe.get_list("Company", pluck="name", limit_page_length=1)
    if not companies:
        frappe.throw(_("No company is available for the current user."))
    return companies[0]


def _period_bounds(from_date: str | None = None, to_date: str | None = None):
    today = getdate(nowdate())
    start = getdate(from_date) if from_date else get_first_day(today)
    end = getdate(to_date) if to_date else get_last_day(today)
    return start, end


def _purchase_rows(company: str, from_date, to_date) -> list[dict[str, Any]]:
    rows = frappe.get_list(
        "Purchase Invoice",
        filters={
            "company": company,
            "posting_date": ["between", [from_date, to_date]],
            "docstatus": ["<", 2],
        },
        fields=[
            "name",
            "posting_date",
            "supplier",
            "supplier_name",
            "grand_total",
            "currency",
            "docstatus",
            "status",
            "set_warehouse",
            "bill_no",
        ],
        order_by="posting_date desc, modified desc",
        limit_page_length=100,
    )

    return [
        {
            "id": row.name,
            "number": row.bill_no or row.name,
            "date": formatdate(row.posting_date),
            "counterparty": row.supplier_name or row.supplier,
            "warehouse": row.set_warehouse or "",
            "amount": flt(row.grand_total),
            "currency": row.currency,
            "status": "posted" if row.docstatus == 1 else "draft",
            "backendStatus": row.status,
            "voucherType": "Purchase Invoice",
        }
        for row in rows
    ]


def _reference_data(company: str) -> dict[str, Any]:
    suppliers = frappe.get_list(
        "Supplier",
        fields=["name", "supplier_name", "tax_id"],
        order_by="supplier_name asc",
        limit_page_length=500,
    )
    items = frappe.get_list(
        "Item",
        filters={"disabled": 0},
        fields=["name", "item_name", "is_stock_item", "stock_uom"],
        order_by="item_name asc",
        limit_page_length=1000,
    )
    warehouses = frappe.get_list(
        "Warehouse",
        filters={"company": company, "is_group": 0, "disabled": 0},
        fields=["name", "warehouse_name"],
        order_by="warehouse_name asc",
        limit_page_length=500,
    )

    return {
        "suppliers": [
            {
                "id": row.name,
                "name": row.supplier_name or row.name,
                "taxId": row.tax_id,
            }
            for row in suppliers
        ],
        "items": [
            {
                "id": row.name,
                "name": row.item_name or row.name,
                "isStockItem": bool(row.is_stock_item),
                "uom": row.stock_uom,
            }
            for row in items
        ],
        "warehouses": [
            {"id": row.name, "name": row.warehouse_name or row.name}
            for row in warehouses
        ],
    }


@frappe.whitelist()
def bootstrap(from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    """Return shell, journal and reference data for the accountant-facing UI."""
    company = _current_company()
    start, end = _period_bounds(from_date, to_date)

    return {
        "company": company,
        "period": f"{formatdate(start)} — {formatdate(end)}",
        "purchases": _purchase_rows(company, start, end),
        **_reference_data(company),
    }


def _validate_purchase_payload(payload: dict[str, Any]) -> None:
    if not payload.get("supplier"):
        frappe.throw(_("Supplier is required."))
    if not payload.get("items"):
        frappe.throw(_("At least one item is required."))

    for index, row in enumerate(payload["items"], start=1):
        if not row.get("item_code"):
            frappe.throw(_("Item is required in row {0}.").format(index))
        if flt(row.get("qty")) <= 0:
            frappe.throw(_("Quantity must be greater than zero in row {0}.").format(index))
        if flt(row.get("rate")) < 0:
            frappe.throw(_("Rate cannot be negative in row {0}.").format(index))


def _purchase_doc_from_payload(payload: dict[str, Any]):
    _validate_purchase_payload(payload)

    company = payload.get("company") or _current_company()
    document_id = payload.get("document_id")

    if document_id:
        doc = frappe.get_doc("Purchase Invoice", document_id)
        doc.check_permission("write")
        if doc.docstatus != 0:
            frappe.throw(_("Only draft purchase documents can be edited."))
        doc.set("items", [])
    else:
        doc = frappe.new_doc("Purchase Invoice")
        doc.company = company

    doc.supplier = payload["supplier"]
    doc.posting_date = payload.get("posting_date") or nowdate()
    doc.set_posting_time = 1
    doc.bill_no = payload.get("number") or None
    doc.set_warehouse = payload.get("warehouse") or None

    item_codes = [row["item_code"] for row in payload["items"]]
    stock_flags = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "is_stock_item"],
    )
    stock_by_item = {row.name: bool(row.is_stock_item) for row in stock_flags}
    has_stock_items = any(stock_by_item.get(code, False) for code in item_codes)

    if has_stock_items and not doc.set_warehouse:
        frappe.throw(_("Warehouse is required when the purchase contains stock items."))

    doc.update_stock = 1 if has_stock_items else 0

    for row in payload["items"]:
        child = {
            "item_code": row["item_code"],
            "qty": flt(row["qty"]),
            "rate": flt(row["rate"]),
        }
        if stock_by_item.get(row["item_code"], False):
            child["warehouse"] = doc.set_warehouse
        doc.append("items", child)

    return doc


@frappe.whitelist(methods=["POST"])
def save_purchase(payload: dict[str, Any] | str, submit: bool | int | str = False) -> dict[str, Any]:
    """Create/update a Purchase Invoice and optionally submit it.

    This is deliberately thin: ERPNext remains responsible for validation,
    ledger posting and stock posting. The compatibility API only translates
    the user-facing document into the backend document.
    """
    if isinstance(payload, str):
        payload = frappe.parse_json(payload)

    doc = _purchase_doc_from_payload(payload)

    if doc.is_new():
        doc.insert()
    else:
        doc.save()

    should_submit = str(submit).lower() in {"1", "true", "yes"}
    if should_submit:
        doc.submit()

    return {
        "id": doc.name,
        "status": "posted" if doc.docstatus == 1 else "draft",
        "docstatus": doc.docstatus,
        "grandTotal": flt(doc.grand_total),
        "currency": doc.currency,
        "voucherType": "Purchase Invoice",
    }


def _pair_gl_entries(entries: list[dict[str, Any]], currency: str) -> list[dict[str, Any]]:
    """Convert ERPNext debit/credit ledger lines into familiar paired Dt/Kt rows.

    ERPNext stores each ledger side as an individual GL Entry. 1C/BAS users expect
    a paired debit-account / credit-account representation. The pairing below is
    deterministic and amount-preserving. It is intended for inspection, not for
    posting logic.
    """
    debits: list[dict[str, Any]] = []
    credits: list[dict[str, Any]] = []

    for entry in entries:
        debit = flt(entry.get("debit"))
        credit = flt(entry.get("credit"))
        if debit > 0:
            debits.append({"entry": entry, "remaining": debit})
        if credit > 0:
            credits.append({"entry": entry, "remaining": credit})

    result: list[dict[str, Any]] = []
    credit_index = 0

    for debit_line in debits:
        while debit_line["remaining"] > 0.0000001 and credit_index < len(credits):
            credit_line = credits[credit_index]
            if credit_line["remaining"] <= 0.0000001:
                credit_index += 1
                continue

            amount = min(debit_line["remaining"], credit_line["remaining"])
            debit_entry = debit_line["entry"]
            credit_entry = credit_line["entry"]

            result.append(
                {
                    "id": f"{debit_entry.get('name')}:{credit_entry.get('name')}:{len(result)}",
                    "date": formatdate(debit_entry.get("posting_date")),
                    "debit": debit_entry.get("account") or "—",
                    "credit": credit_entry.get("account") or "—",
                    "amount": amount,
                    "currency": currency,
                    "counterparty": debit_entry.get("party") or credit_entry.get("party"),
                    "item": None,
                    "warehouse": None,
                    "source": f"{debit_entry.get('voucher_type')} {debit_entry.get('voucher_no')}",
                }
            )

            debit_line["remaining"] -= amount
            credit_line["remaining"] -= amount
            if credit_line["remaining"] <= 0.0000001:
                credit_index += 1

    return result


@frappe.whitelist()
def postings(document_id: str, voucher_type: str = "Purchase Invoice") -> list[dict[str, Any]]:
    """Return normalized paired Dt/Kt rows for a supported posted document."""
    if voucher_type not in _ALLOWED_VOUCHER_TYPES:
        frappe.throw(_("Unsupported voucher type: {0}").format(voucher_type))

    document = frappe.get_doc(voucher_type, document_id)
    document.check_permission("read")

    company = getattr(document, "company", None) or _current_company()
    currency = frappe.get_cached_value("Company", company, "default_currency") or "UAH"

    entries = frappe.get_list(
        "GL Entry",
        filters={
            "voucher_type": voucher_type,
            "voucher_no": document_id,
            "is_cancelled": 0,
        },
        fields=[
            "name",
            "posting_date",
            "account",
            "debit",
            "credit",
            "party_type",
            "party",
            "voucher_type",
            "voucher_no",
        ],
        order_by="creation asc, name asc",
        limit_page_length=500,
    )

    return _pair_gl_entries(entries, currency)
