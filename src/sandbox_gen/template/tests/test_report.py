from shop.report import stock_report


def test_stock_report_sorted():
    assert stock_report({"pear": 2, "apple": 1}) == "apple: 1\npear: 2"
