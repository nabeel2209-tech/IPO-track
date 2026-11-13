def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_root_sends_people_to_the_docs(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/docs"


def test_list_and_sort(client):
    data = client.get("/api/ipos", params={"sort": "latest_return", "order": "desc"}).json()
    assert data["total"] == 5
    first = data["items"][0]
    assert first["company"] == "Jio Platforms Limited"  # best performer in the sample
    assert data["items"][-1]["latest_return"] is None  # no prices yet → listed last
    ww = next(i for i in data["items"] if i["nse_symbol"] == "CORDELIA")
    assert abs(ww["latest_adj_close"] - 852.5) < 1e-6  # split adjusted


def test_filters(client):
    assert client.get("/api/ipos", params={"segment": "sme"}).json()["total"] == 1
    assert client.get("/api/ipos", params={"q": "jio"}).json()["items"][0]["isin"] == "INE0BJO01010"


def test_detail_has_categories(client):
    d = client.get("/api/ipos/INE0BJO01010").json()
    keys = [c["key"] for c in d["categories"]]
    assert keys == ["individual", "snii", "bnii", "shareholder", "employee"]
    snii = d["categories"][1]
    assert (snii["min_lots"], snii["shares"], snii["amount"]) == (15, 180, 201420)


def test_pnl_on_a_date(client):
    r = client.get("/api/ipos/INE0BJO01010/pnl", params={"date": "2026-10-29"}).json()
    assert r["on_date"]["trade_date"] == "2026-10-29"
    retail = next(c for c in r["on_date"]["categories"] if c["key"] == "individual")
    assert round(retail["pnl"], 2) == round(12 * (1423.05 - 1119), 2)


def test_pnl_errors(client):
    assert client.get("/api/ipos/INE0BJO01010/pnl", params={"date": "2026-01-01"}).status_code == 422
    assert client.get("/api/ipos/INE000000000/pnl").status_code == 404


def test_prices_include_actions(client):
    r = client.get("/api/ipos/INE0LZF01039/prices").json()
    assert r["corporate_actions"][0]["share_multiplier"] == 10
    assert all(p["adj_close"] > 500 for p in r["points"])  # all comparable with the ₹808 issue price


def test_meta(client):
    m = client.get("/api/meta").json()
    assert (m["ipo_count"], m["mainboard_count"], m["sme_count"]) == (5, 4, 1)
    assert m["latest_price_date"] == "2026-10-30"


def test_ask_without_key_is_503(client):
    assert client.post("/api/ask", json={"question": "best IPO?"}).status_code == 503
