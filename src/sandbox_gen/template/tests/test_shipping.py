from shop.shipping import shipping_cost


def test_shipping_cost():
    assert shipping_cost(2.0) == 8.0
