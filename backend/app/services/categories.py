"""Investor categories and the minimum application in each.

This module is pure Python (no database) so the rules are easy to test and explain.

Rules used (amounts are at the issue price):

Mainboard IPOs
- Retail (RII): up to ₹2 lakh. Minimum 1 lot.
- Small HNI (sNII): more than ₹2 lakh, up to ₹10 lakh. Minimum = the smallest number of lots
  costing more than ₹2 lakh.
- Big HNI (bNII): more than ₹10 lakh. Minimum = the smallest number of lots costing more than
  ₹10 lakh.
- Employee quota: up to ₹5 lakh, minimum 1 lot, usually at a discount to the issue price.
- Shareholder quota: up to ₹2 lakh, minimum 1 lot (for shareholders of a listed parent).

SME IPOs (new process, issues opening on or after 1 July 2025 - NSE circular IPO68604)
- Individual investor: exactly 2 lots, and 2 lots must cost more than ₹2 lakh.
- NII (HNI): more than 2 lots. Small HNI starts at 3 lots; big HNI at the smallest number of lots
  costing more than ₹10 lakh.
- Employee and shareholder quotas: minimum 2 lots.

When categories are oversubscribed, successful applicants are drawn by lottery and each receives
the minimum application, which is why the minimum is what we show P&L for.
"""

from dataclasses import dataclass
from datetime import date
from math import floor

TWO_LAKH = 200_000
FIVE_LAKH = 500_000
TEN_LAKH = 1_000_000
SME_NEW_RULES_FROM = date(2025, 7, 1)


@dataclass(frozen=True)
class IssueTerms:
    segment: str  # "mainboard" | "sme"
    issue_price: float
    lot_size: int
    issue_open: date | None = None
    has_employee_quota: bool = False
    employee_discount: float = 0.0
    has_shareholder_quota: bool = False
    individual_min_lots: int | None = None
    snii_min_lots: int | None = None
    bnii_min_lots: int | None = None

    @property
    def lot_value(self) -> float:
        return self.issue_price * self.lot_size


@dataclass(frozen=True)
class Category:
    key: str  # stable id used by the API and front end
    label: str
    eligibility: str
    min_lots: int
    max_lots: int | None  # None when there is no upper limit
    buy_price: float  # price paid per share (employees may get a discount)

    def shares(self, lot_size: int) -> int:
        return self.min_lots * lot_size


def smallest_lots_above(amount: float, lot_value: float) -> int:
    """Smallest whole number of lots whose cost is strictly more than ``amount``."""
    if lot_value <= 0:
        raise ValueError("lot value must be positive")
    return floor(amount / lot_value) + 1


def largest_lots_within(amount: float, lot_value: float) -> int:
    """Largest whole number of lots whose cost is at most ``amount``."""
    return floor(amount / lot_value)


def uses_new_sme_rules(terms: IssueTerms) -> bool:
    return terms.segment == "sme" and (terms.issue_open is None or terms.issue_open >= SME_NEW_RULES_FROM)


def categories_for(terms: IssueTerms) -> list[Category]:
    """Every category an investor could have applied in, with its minimum application."""
    lv = terms.lot_value
    cats: list[Category] = []

    if uses_new_sme_rules(terms):
        individual_min = terms.individual_min_lots or 2
        snii_min = terms.snii_min_lots or max(3, smallest_lots_above(TWO_LAKH, lv))
        bnii_min = terms.bnii_min_lots or max(snii_min + 1, smallest_lots_above(TEN_LAKH, lv))
        cats.append(Category("individual", "Individual investor", "Exactly 2 lots, over ₹2 lakh", individual_min, individual_min, terms.issue_price))
        cats.append(Category("snii", "Small HNI (sNII)", "More than 2 lots, up to ₹10 lakh", snii_min, max(snii_min, bnii_min - 1), terms.issue_price))
        cats.append(Category("bnii", "Big HNI (bNII)", "Over ₹10 lakh", bnii_min, None, terms.issue_price))
        quota_min = 2
    else:
        retail_min = terms.individual_min_lots or 1
        snii_min = terms.snii_min_lots or smallest_lots_above(TWO_LAKH, lv)
        bnii_min = terms.bnii_min_lots or smallest_lots_above(TEN_LAKH, lv)
        cats.append(Category("individual", "Retail (RII)", "Up to ₹2 lakh", retail_min, max(retail_min, largest_lots_within(TWO_LAKH, lv)), terms.issue_price))
        cats.append(Category("snii", "Small HNI (sNII)", "Over ₹2 lakh, up to ₹10 lakh", snii_min, max(snii_min, bnii_min - 1), terms.issue_price))
        cats.append(Category("bnii", "Big HNI (bNII)", "Over ₹10 lakh", bnii_min, None, terms.issue_price))
        quota_min = 1

    if terms.has_shareholder_quota:
        cats.append(Category("shareholder", "Shareholder quota", "Shareholders of the listed parent, up to ₹2 lakh", quota_min, max(quota_min, largest_lots_within(TWO_LAKH, lv)), terms.issue_price))
    if terms.has_employee_quota:
        emp_price = terms.issue_price - (terms.employee_discount or 0.0)
        cats.append(Category("employee", "Employee quota", "Eligible employees, up to ₹5 lakh", quota_min, max(quota_min, largest_lots_within(FIVE_LAKH, emp_price * terms.lot_size)), emp_price))
    return cats
