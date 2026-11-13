from datetime import date

import pytest

from app.services.categories import IssueTerms, categories_for, largest_lots_within, smallest_lots_above


def by_key(terms):
    return {c.key: c for c in categories_for(terms)}


def test_lot_maths():
    assert smallest_lots_above(200_000, 13_428) == 15  # 14 lots = ₹1,87,992; 15 lots = ₹2,01,420
    assert largest_lots_within(200_000, 13_428) == 14
    assert smallest_lots_above(200_000, 20_000) == 11  # exactly ₹2 lakh is still retail, so one more lot
    with pytest.raises(ValueError):
        smallest_lots_above(1, 0)


def test_mainboard_jio_platforms_matches_published_minimums():
    # Published by the exchange/offer document: retail 1 lot, S-HNI 15 lots, B-HNI 75 lots.
    t = IssueTerms("mainboard", 1119.0, 12, date(2026, 10, 21), True, 54.0, True)
    c = by_key(t)
    assert [c["individual"].min_lots, c["snii"].min_lots, c["bnii"].min_lots] == [1, 15, 75]
    assert c["individual"].max_lots == 14
    assert c["snii"].max_lots == 74
    assert c["shareholder"].min_lots == 1
    assert c["employee"].buy_price == 1065.0  # ₹54 employee discount
    assert c["individual"].shares(12) * c["individual"].buy_price == 13_428


def test_mainboard_without_quotas_has_three_categories():
    t = IssueTerms("mainboard", 75.0, 200)
    assert [c.key for c in categories_for(t)] == ["individual", "snii", "bnii"]
    c = by_key(t)
    assert (c["snii"].min_lots, c["bnii"].min_lots) == (14, 67)


def test_sme_new_rules_two_lot_minimum():
    # Ravita Engineering (NSE Emerge, Oct 2026): lot 1,200 × ₹112 = ₹1,34,400
    t = IssueTerms("sme", 112.0, 1200, date(2026, 10, 14))
    c = by_key(t)
    assert c["individual"].min_lots == c["individual"].max_lots == 2
    assert c["individual"].shares(1200) * 112 > 200_000
    assert c["snii"].min_lots == 3
    assert c["bnii"].min_lots == 8  # 7 lots = ₹9,40,800; 8 lots = ₹10,75,200
    assert c["snii"].max_lots == 7


def test_overrides_from_offer_document_win():
    t = IssueTerms("mainboard", 100.0, 150, individual_min_lots=1, snii_min_lots=20, bnii_min_lots=70)
    c = by_key(t)
    assert (c["snii"].min_lots, c["bnii"].min_lots) == (20, 70)
