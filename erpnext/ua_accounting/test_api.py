from unittest import TestCase

from erpnext.ua_accounting.api import _pair_gl_entries


class TestUaAccountingCompatibilityApi(TestCase):
    def test_pairs_simple_debit_credit(self):
        entries = [
            {
                "name": "GLE-D",
                "posting_date": "2026-09-11",
                "account": "281 Goods",
                "debit": 1000,
                "credit": 0,
                "party": None,
                "voucher_type": "Purchase Invoice",
                "voucher_no": "PINV-1",
            },
            {
                "name": "GLE-C",
                "posting_date": "2026-09-11",
                "account": "631 Payables",
                "debit": 0,
                "credit": 1000,
                "party": "SUP-1",
                "voucher_type": "Purchase Invoice",
                "voucher_no": "PINV-1",
            },
        ]

        rows = _pair_gl_entries(entries, "UAH")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["debit"], "281 Goods")
        self.assertEqual(rows[0]["credit"], "631 Payables")
        self.assertEqual(rows[0]["amount"], 1000)
        self.assertEqual(rows[0]["counterparty"], "SUP-1")

    def test_splits_one_debit_across_multiple_credit_lines(self):
        entries = [
            {
                "name": "GLE-D",
                "posting_date": "2026-09-11",
                "account": "281 Goods",
                "debit": 1000,
                "credit": 0,
                "party": None,
                "voucher_type": "Purchase Invoice",
                "voucher_no": "PINV-2",
            },
            {
                "name": "GLE-C1",
                "posting_date": "2026-09-11",
                "account": "631 Payables",
                "debit": 0,
                "credit": 600,
                "party": "SUP-1",
                "voucher_type": "Purchase Invoice",
                "voucher_no": "PINV-2",
            },
            {
                "name": "GLE-C2",
                "posting_date": "2026-09-11",
                "account": "644 Tax clearing",
                "debit": 0,
                "credit": 400,
                "party": None,
                "voucher_type": "Purchase Invoice",
                "voucher_no": "PINV-2",
            },
        ]

        rows = _pair_gl_entries(entries, "UAH")

        self.assertEqual([row["amount"] for row in rows], [600, 400])
        self.assertEqual(sum(row["amount"] for row in rows), 1000)
        self.assertEqual(rows[0]["credit"], "631 Payables")
        self.assertEqual(rows[1]["credit"], "644 Tax clearing")
