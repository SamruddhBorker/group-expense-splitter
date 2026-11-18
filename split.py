#!/usr/bin/env python3
"""group-expense-splitter: split trip and shared costs fairly. Standard library only.

    python split.py new "Goa Trip" --members Asha Ben Chitra
    python split.py add --paid-by Asha --amount 3600 --desc "Dinner"                       # split equally
    python split.py add --paid-by Ben --amount 900 --desc "Cab" --among Ben Chitra
    python split.py add --paid-by Asha --amount 5000 --desc "Villa" --mode percent --values 50 30 20
    python split.py add --paid-by Ben --amount 1200 --desc "Food" --mode shares --values 2 1 1
    python split.py balances                 # who owes / is owed
    python split.py settle                   # fewest sensible payments to clear everything
    python split.py paid Chitra Asha 500     # record that a payment happened
    python split.py upi Asha asha@okbank     # save a UPI id so settle shows a pay link
    python split.py list | undo | summary | export trip.csv
Default data file: trip.json (change with --file).
"""
from __future__ import annotations

import argparse
import csv
import sys

from ledger import Ledger, LedgerError, fmt


def csv_safe(s: str) -> str:
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # piped output on Windows defaults to cp1252
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default="trip.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("name")
    n.add_argument("--members", nargs="+", required=True)
    n.add_argument("--force", action="store_true", help="overwrite an existing file")
    a = sub.add_parser("add")
    a.add_argument("--paid-by", required=True)
    a.add_argument("--amount", required=True)
    a.add_argument("--desc", required=True)
    a.add_argument("--among", nargs="+")
    a.add_argument("--mode", default="equal", choices=["equal", "exact", "percent", "shares"])
    a.add_argument("--values", nargs="+")
    a.add_argument("--category", default="")
    p = sub.add_parser("paid")
    p.add_argument("frm")
    p.add_argument("to")
    p.add_argument("amount")
    u = sub.add_parser("upi")
    u.add_argument("name")
    u.add_argument("vpa")
    for c in ("balances", "settle", "list", "undo", "summary"):
        sub.add_parser(c)
    sub.add_parser("export").add_argument("csv_file")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "new":
            from pathlib import Path
            if Path(args.file).exists() and not args.force:
                raise LedgerError(f"{args.file} already exists (use --force to overwrite)")
            Ledger.new(args.name, args.members).save(args.file)
            print(f"created {args.file}")
            return 0
        lg = Ledger.load(args.file)
        if args.cmd == "add":
            e = lg.add_expense(args.paid_by, args.amount, args.desc, args.among, args.mode, args.values, args.category)
            lg.save(args.file)
            print(f"#{e['id']} {e['desc']}: {e['paid_by']} paid {fmt(e['amount'])}")
            for m, s in e["split"].items():
                print(f"   {m} owes {fmt(s)}")
        elif args.cmd == "paid":
            pay = lg.record_payment(args.frm, args.to, args.amount)
            lg.save(args.file)
            print(f"recorded: {pay['from']} paid {pay['to']} {fmt(pay['amount'])}")
        elif args.cmd == "upi":
            lg.set_upi(args.name, args.vpa)
            lg.save(args.file)
            print("saved")
        elif args.cmd == "undo":
            e = lg.undo()
            lg.save(args.file)
            print(f"removed #{e['id']} {e['desc']}" if e else "nothing to undo")
        elif args.cmd == "list":
            for e in lg.d["expenses"]:
                print(f"#{e['id']:<3} {e['desc']:<24} {fmt(e['amount']):>12}  paid by {e['paid_by']}")
            for pay in lg.d["payments"]:
                print(f"     payment: {pay['from']} -> {pay['to']} {fmt(pay['amount'])}")
            if not lg.d["expenses"] and not lg.d["payments"]:
                print("(nothing yet)")
        elif args.cmd == "balances":
            for m, v in lg.balances().items():
                state = "is owed" if v > 0 else "owes" if v < 0 else "is settled"
                print(f"{m:<20} {state} {fmt(abs(v)) if v else ''}".rstrip())
        elif args.cmd == "settle":
            moves = lg.settle()
            if not moves:
                print("All settled. Nobody owes anything.")
            for frm, to, amt in moves:
                print(f"{frm} pays {to} {fmt(amt)}")
                link = lg.upi_link(to, amt)
                if link:
                    print(f"   UPI link: {link}")
        elif args.cmd == "summary":
            sp = lg.spend_by()
            print(f"{lg.d['name']}: total {fmt(sp['total'])}")
            for m, v in sp["paid"].items():
                print(f"  {m} paid {fmt(v)}")
            for c, v in sorted(sp["categories"].items(), key=lambda x: -x[1]):
                print(f"  {c}: {fmt(v)}")
        elif args.cmd == "export":
            with open(args.csv_file, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["id", "description", "category", "paid_by", "amount"] + lg.members)
                for e in lg.d["expenses"]:
                    w.writerow([e["id"], csv_safe(e["desc"]), csv_safe(e["category"]), e["paid_by"],
                                fmt(e["amount"]).replace(",", "")] +
                               [fmt(e["split"].get(m, 0)).replace(",", "") for m in lg.members])
            print(f"wrote {args.csv_file}")
    except (LedgerError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
