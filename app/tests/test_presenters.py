from app.corrections import parse_decimal
from app.presenters import edit_value


def test_price_edit_value_is_grouped_and_parses_back():
    shown = edit_value("price_gross", "1080000.0")
    assert shown == "1 080 000,00"
    assert parse_decimal(shown) == parse_decimal("1080000")
