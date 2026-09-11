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
            "date": formatdate(row.posting_date, "dd.MM.yyyy"),
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


@frappe.whitelist()
def bootstrap(from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    """Return the minimum shell data needed by the accountant-facing UI."""
    company = _current_company()
    start, end = _period_bounds(from_date, to_date)

    return {
        "company": company,
        "period": f"{formatdate(start, 'dd.MM.yyyy')} — {formatdate(end, 'dd.MM.yyyy')}",
        "purchases": _purchase_rows(company, start, end),
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
                    "date": formatdate(debit_entry.get("posting_date"), "dd.MM.yyyy"),
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
