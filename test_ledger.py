import csv
import json
import random
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import ledger
import split
from ledger import Ledger, LedgerError


def trip():
    return Ledger.new("Goa", ["Asha", "Ben", "Chitra"])


class MoneyTests(unittest.TestCase):
    def test_to_paise(self):
        self.assertEqual(ledger.to_paise("1,234.50"), 123450)
        self.assertEqual(ledger.to_paise("0.1") + ledger.to_paise("0.2"), 30)   # no float drift
        self.assertEqual(ledger.to_paise("10.005"), 1001)                       # half-up
        for bad in ("0", "-5", "abc", "NaN", "inf", "1e12", ""):
            with self.assertRaises(LedgerError, msg=bad):
                ledger.to_paise(bad)

    def test_fmt(self):
        self.assertEqual(ledger.fmt(123456), "1,234.56")
        self.assertEqual(ledger.fmt(-5), "-0.05")

    def test_split_always_sums_exactly(self):
        rnd = random.Random(7)
        for _ in range(500):
            total = rnd.randint(1, 10_000_000)
            ws = [Decimal(rnd.randint(1, 9)) for _ in range(rnd.randint(1, 8))]
            self.assertEqual(sum(ledger.split_weights(total, ws)), total)

    def test_equal_split_remainder_goes_to_first(self):
        self.assertEqual(ledger.split_weights(100, [Decimal(1)] * 3), [34, 33, 33])


class ExpenseTests(unittest.TestCase):
    def test_equal_split_and_balances(self):
        lg = trip()
        lg.add_expense("asha", "3600", "Dinner")     # case-insensitive names
        self.assertEqual(lg.balances(), {"Asha": 240000, "Ben": -120000, "Chitra": -120000})

    def test_among_subset_and_payer_outside_split(self):
        lg = trip()
        lg.add_expense("Ben", "900", "Cab", among=["Ben", "Chitra"])
        self.assertEqual(lg.balances()["Asha"], 0)
        lg.add_expense("Asha", "600", "Gift for Ben", among=["Ben"])    # Asha not in split
        self.assertEqual(lg.balances()["Asha"], 60000)

    def test_percent_and_shares(self):
        lg = trip()
        e = lg.add_expense("Asha", "5000", "Villa", mode="percent", values=["50", "30", "20"])
        self.assertEqual(list(e["split"].values()), [250000, 150000, 100000])
        e = lg.add_expense("Ben", "1200", "Food", mode="shares", values=["2", "1", "1"])
        self.assertEqual(list(e["split"].values()), [60000, 30000, 30000])

    def test_exact_must_match_total(self):
        lg = trip()
        with self.assertRaisesRegex(LedgerError, "add up to"):
            lg.add_expense("Asha", "100", "x", mode="exact", values=["50", "30", "10"])
        e = lg.add_expense("Asha", "100", "x", mode="exact", values=["50", "30", "20"])
        self.assertEqual(sum(e["split"].values()), 10000)

    def test_percent_must_be_100(self):
        with self.assertRaisesRegex(LedgerError, "100"):
            trip().add_expense("Asha", "100", "x", mode="percent", values=["50", "30", "10"])

    def test_validation(self):
        lg = trip()
        for kw in ({"paid_by": "Zed"}, {"amount": "0"}, {"desc": " "}, {"among": ["Asha", "asha"]},
                   {"among": ["Zed"]}, {"mode": "shares"}, {"mode": "weird", "values": ["1", "1", "1"]},
                   {"mode": "shares", "values": ["1", "-1", "1"]}):
            args = {"paid_by": "Asha", "amount": "100", "desc": "x", **kw}
            with self.assertRaises(LedgerError, msg=str(kw)):
                lg.add_expense(**args)
        self.assertEqual(lg.d["expenses"], [])

    def test_undo(self):
        lg = trip()
        lg.add_expense("Asha", "100", "a")
        lg.add_expense("Asha", "200", "b")
        self.assertEqual(lg.undo()["desc"], "b")
        self.assertEqual(len(lg.d["expenses"]), 1)
        self.assertIsNone(Ledger.new("x", ["a", "b"]).undo())


class SettleTests(unittest.TestCase):
    def test_balances_always_sum_to_zero(self):
        rnd = random.Random(3)
        lg = Ledger.new("t", ["a", "b", "c", "d", "e"])
        for i in range(60):
            people = rnd.sample(lg.members, rnd.randint(1, 5))
            lg.add_expense(rnd.choice(lg.members), str(rnd.randint(1, 5000) / 7), f"e{i}", among=people)
        self.assertEqual(sum(lg.balances().values()), 0)

    def test_settle_clears_everyone_with_few_payments(self):
        rnd = random.Random(11)
        for trial in range(50):
            lg = Ledger.new("t", ["a", "b", "c", "d", "e", "f"])
            for i in range(rnd.randint(1, 20)):
                lg.add_expense(rnd.choice(lg.members), str(rnd.randint(1, 9999) / 3), f"e{i}",
                               among=rnd.sample(lg.members, rnd.randint(1, 6)))
            moves = lg.settle()
            self.assertLessEqual(len(moves), len(lg.members) - 1)
            for frm, to, amt in moves:
                lg.record_payment(frm, to, Decimal(amt) / 100)
            self.assertTrue(all(v == 0 for v in lg.balances().values()), trial)

    def test_simple_case(self):
        lg = trip()
        lg.add_expense("Asha", "3600", "Dinner")
        self.assertEqual(sorted(lg.settle()), [("Ben", "Asha", 120000), ("Chitra", "Asha", 120000)])

    def test_payment_validation(self):
        lg = trip()
        with self.assertRaises(LedgerError):
            lg.record_payment("Asha", "Asha", "5")
        with self.assertRaises(LedgerError):
            lg.record_payment("Asha", "Zed", "5")

    def test_all_settled(self):
        self.assertEqual(trip().settle(), [])

    def test_upi_link(self):
        lg = trip()
        self.assertIsNone(lg.upi_link("Asha", 50000))
        lg.set_upi("asha", "asha@okbank")
        link = lg.upi_link("Asha", 123450, "Goa dinner")
        self.assertTrue(link.startswith("upi://pay?pa=asha%40okbank"))
        self.assertIn("am=1234.50", link)
        self.assertIn("cu=INR", link)
        for bad in ("nope", "a b@bank", "x@", "@bank", "x@1bank"):
            with self.assertRaises(LedgerError, msg=bad):
                lg.set_upi("Asha", bad)

    def test_summary(self):
        lg = trip()
        lg.add_expense("Asha", "100", "a", category="Food")
        lg.add_expense("Ben", "50", "b", category="Food")
        lg.add_expense("Ben", "25", "c")
        sp = lg.spend_by()
        self.assertEqual((sp["total"], sp["categories"]["Food"], sp["paid"]["Ben"]), (17500, 15000, 7500))


class GroupTests(unittest.TestCase):
    def test_member_rules(self):
        with self.assertRaises(LedgerError):
            Ledger.new("t", ["Solo"])
        with self.assertRaises(LedgerError):
            Ledger.new("t", ["Asha", "asha"])
        with self.assertRaises(LedgerError):
            Ledger.new("t", ["x" * 31, "b"])


class FileAndCliTests(unittest.TestCase):
    def test_roundtrip_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.json"
            lg = trip()
            lg.add_expense("Asha", "100", "x")
            lg.save(p)
            self.assertEqual(Ledger.load(p).balances(), lg.balances())
            self.assertEqual([f.name for f in Path(d).iterdir()], ["t.json"])    # no stray temp files

    def test_load_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(LedgerError):
                Ledger.load(Path(d) / "missing.json")
            bad = Path(d) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(LedgerError):
                Ledger.load(bad)

    def test_cli_flow(self):
        with tempfile.TemporaryDirectory() as d:
            f = ["--file", str(Path(d) / "t.json")]
            self.assertEqual(split.main(f + ["new", "Goa Trip", "--members", "Asha", "Ben", "Chitra"]), 0)
            self.assertEqual(split.main(f + ["new", "Again", "--members", "A", "B"]), 1)        # won't overwrite
            self.assertEqual(split.main(f + ["add", "--paid-by", "Asha", "--amount", "3600", "--desc", "=Dinner"]), 0)
            self.assertEqual(split.main(f + ["add", "--paid-by", "Zed", "--amount", "1", "--desc", "x"]), 1)
            self.assertEqual(split.main(f + ["upi", "Asha", "asha@okbank"]), 0)
            for cmd in ("balances", "settle", "list", "summary"):
                self.assertEqual(split.main(f + [cmd]), 0)
            self.assertEqual(split.main(f + ["paid", "Ben", "Asha", "1200"]), 0)
            out = Path(d) / "o.csv"
            self.assertEqual(split.main(f + ["export", str(out)]), 0)
            with open(out, newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[1][1], "'=Dinner")      # formula neutralised
            self.assertEqual(split.main(f + ["undo"]), 0)


if __name__ == "__main__":
    unittest.main()
