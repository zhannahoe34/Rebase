from shop.auth.tokens import check_token, token_for


def test_token_roundtrip():
    assert check_token("ann", "s3cret", token_for("ann", "s3cret"))
    assert not check_token("ann", "s3cret", "nope")
