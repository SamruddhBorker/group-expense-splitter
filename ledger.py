"""Shared-expense ledger: exact splitting, balances and settle-up. Standard library only.

All money is integer paise internally, so shares always add up to the exact total
(no floating point, no lost or invented paise).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
from urllib.parse import quote

MAX_PAISE = 1_000_000_000  # Rs 1 crore per expense


class LedgerError(ValueError):
    """Bad input; the message says what to fix."""


def to_paise(value, what: str = "amount") -> int:
    try:
        d = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise LedgerError(f"{what} must be a number, got {value!r}") from None
    if not d.is_finite():
        raise LedgerError(f"{what} must be a normal number")
    p = int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if p <= 0:
        raise LedgerError(f"{what} must be above zero")
    if p > MAX_PAISE:
        raise LedgerError(f"{what} is too large")
    return p


def fmt(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    p = abs(paise)
    return f"{sign}{p // 100:,}.{p % 100:02d}"


def split_weights(total: int, weights: list[Decimal]) -> list[int]:
    """Split `total` paise in proportion to weights; the result sums exactly to total.

    Largest-remainder method: everyone gets the floor of their share, then the
    leftover paise go to whoever has the biggest fractional part (ties: first listed).
    """
    s = sum(weights)
    if s <= 0:
        raise LedgerError("weights must add up to more than zero")
    exact = [Decimal(total) * w / s for w in weights]
    base = [int(x) for x in exact]
    left = total - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - base[i]), i))
    for i in order[:left]:
        base[i] += 1
    return base


def clean_name(s: str) -> str:
    n = re.sub(r"[\x00-\x1f\x7f]", " ", s or "").strip()
    n = " ".join(n.split())
    if not 1 <= len(n) <= 30:
        raise LedgerError("names must be 1-30 characters")
    return n


class Ledger:
    def __init__(self, data: dict) -> None:
        self.d = data

    # ---- creation / persistence
    @classmethod
    def new(cls, name: str, members: list[str]) -> "Ledger":
        names = [clean_name(m) for m in members]
        if len(names) < 2:
            raise LedgerError("a group needs at least 2 members")
        if len({n.lower() for n in names}) != len(names):
            raise LedgerError("member names must be different (ignoring upper/lower case)")
        return cls({"name": clean_name(name), "members": {n: {"upi": ""} for n in names},
                    "expenses": [], "payments": []})

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        try:
            return cls(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise LedgerError(f"can't read {path}: {e}") from None

    def save(self, path: str | Path) -> None:
        """Atomic write: a crash mid-save can't corrupt the file."""
        p = Path(path)
        fd, tmp = tempfile.mkstemp(dir=p.parent or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.d, f, indent=2, ensure_ascii=False)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ---- members
    @property
    def members(self) -> list[str]:
        return list(self.d["members"])

    def resolve(self, name: str) -> str:
        """Match a typed name to a member, ignoring case."""
        for m in self.d["members"]:
            if m.lower() == name.strip().lower():
                return m
        raise LedgerError(f"{name!r} isn't in this group ({', '.join(self.members)})")

    def set_upi(self, name: str, vpa: str) -> None:
        if not re.fullmatch(r"[\w.\-]{2,50}@[A-Za-z][\w.\-]{1,30}", vpa):
            raise LedgerError("UPI id should look like name@bank")
        self.d["members"][self.resolve(name)]["upi"] = vpa

    # ---- expenses
    def add_expense(self, paid_by: str, amount, desc: str, among: Optional[list[str]] = None,
                    mode: str = "equal", values: Optional[list[str]] = None, category: str = "") -> dict:
        payer = self.resolve(paid_by)
        total = to_paise(amount)
        people = [self.resolve(a) for a in (among or self.members)]
        if len(set(people)) != len(people):
            raise LedgerError("a person is listed twice in the split")
        desc = re.sub(r"[\x00-\x1f\x7f]", " ", desc or "").strip()[:80]
        if not desc:
            raise LedgerError("add a short description")
        if mode == "equal":
            shares = split_weights(total, [Decimal(1)] * len(people))
        else:
            if not values or len(values) != len(people):
                raise LedgerError(f"--values needs one number per person ({len(people)} here)")
            try:
                vals = [Decimal(str(v)) for v in values]
            except InvalidOperation:
                raise LedgerError("--values must be numbers") from None
            if any((not v.is_finite()) or v < 0 for v in vals):
                raise LedgerError("--values can't be negative")
            if mode == "exact":
                shares = [to_paise(v, "share") if v > 0 else 0 for v in vals]
                if sum(shares) != total:
                    raise LedgerError(f"exact shares add up to {fmt(sum(shares))}, but the expense is {fmt(total)}")
            elif mode == "percent":
                if sum(vals) != 100:
                    raise LedgerError(f"percentages add up to {sum(vals)}, they must add up to 100")
                shares = split_weights(total, vals)
            elif mode == "shares":
                shares = split_weights(total, vals)
            else:
                raise LedgerError("mode must be equal, exact, percent or shares")
        exp = {"id": max([e["id"] for e in self.d["expenses"]], default=0) + 1, "paid_by": payer,
               "amount": total, "desc": desc, "category": re.sub(r"[\x00-\x1f\x7f]", " ", category).strip()[:30],
               "split": dict(zip(people, shares))}
        self.d["expenses"].append(exp)
        return exp

    def undo(self) -> Optional[dict]:
        return self.d["expenses"].pop() if self.d["expenses"] else None

    def record_payment(self, frm: str, to: str, amount) -> dict:
        a, b = self.resolve(frm), self.resolve(to)
        if a == b:
            raise LedgerError("can't pay yourself")
        p = {"from": a, "to": b, "amount": to_paise(amount)}
        self.d["payments"].append(p)
        return p

    # ---- maths
    def balances(self) -> dict[str, int]:
        """Net position per member in paise: positive = is owed money, negative = owes."""
        net = {m: 0 for m in self.members}
        for e in self.d["expenses"]:
            net[e["paid_by"]] += e["amount"]
            for m, s in e["split"].items():
                net[m] -= s
        for p in self.d["payments"]:
            net[p["from"]] += p["amount"]
            net[p["to"]] -= p["amount"]
        return net

    def settle(self) -> list[tuple[str, str, int]]:
        """Suggested transfers (debtor, creditor, paise). Greedy: biggest debtor pays biggest
        creditor. Never more than (members - 1) transfers; not always the theoretical minimum."""
        net = self.balances()
        debtors = sorted([[m, -v] for m, v in net.items() if v < 0], key=lambda x: (-x[1], x[0]))
        creditors = sorted([[m, v] for m, v in net.items() if v > 0], key=lambda x: (-x[1], x[0]))
        out, i, j = [], 0, 0
        while i < len(debtors) and j < len(creditors):
            pay = min(debtors[i][1], creditors[j][1])
            out.append((debtors[i][0], creditors[j][0], pay))
            debtors[i][1] -= pay
            creditors[j][1] -= pay
            if debtors[i][1] == 0:
                i += 1
            if creditors[j][1] == 0:
                j += 1
        return out

    def spend_by(self) -> dict:
        """Total paid per person and spend per category."""
        paid = {m: 0 for m in self.members}
        cats: dict[str, int] = {}
        for e in self.d["expenses"]:
            paid[e["paid_by"]] += e["amount"]
            cats[e["category"] or "(none)"] = cats.get(e["category"] or "(none)", 0) + e["amount"]
        return {"paid": paid, "categories": cats, "total": sum(e["amount"] for e in self.d["expenses"])}

    def upi_link(self, to: str, paise: int, note: str = "") -> Optional[str]:
        """Standard UPI deep link, if the receiver has a UPI id saved."""
        vpa = self.d["members"][self.resolve(to)]["upi"]
        if not vpa:
            return None
        return (f"upi://pay?pa={quote(vpa)}&pn={quote(to)}&am={paise // 100}.{paise % 100:02d}"
                f"&cu=INR&tn={quote(note or self.d['name'])}")
