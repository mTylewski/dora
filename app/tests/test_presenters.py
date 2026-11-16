from app.corrections import parse_decimal, parse_value
from app.presenters import edit_choices, edit_value


def test_price_edit_value_is_grouped_and_parses_back():
    shown = edit_value("price_gross", "1080000.0")
    assert shown == "1 080 000,00"
    assert parse_decimal(shown) == parse_decimal("1080000")


def test_penalty_rate_accepts_percent():
    assert parse_value("rate", "0,02%") == "0.0002"
    assert parse_value("rate", "0,02 %") == "0.0002"
    assert parse_value("rate", "0,0002") == "0.0002"
    assert parse_value("rate", "150") == "150"  # fixed zł/day


def selected(choices):
    return [(code, label) for code, label, sel in choices if sel]


def test_basis_is_a_polish_drop_down_with_the_current_value_selected():
    choices = edit_choices("penalty_basis", "statutory_interest")
    assert selected(choices) == [("statutory_interest", "odsetki ustawowe")]
    labels = [label for _, label, _ in choices]
    assert "% ceny za dzień" in labels and "— brak w dokumencie —" in labels
    assert not any("_" in label for label in labels)  # no internal codes shown to the lawyer
    assert selected(edit_choices("penalty_basis", None)) == [("", "— brak w dokumencie —")]


def test_events_drop_down_handles_both_orders_and_parses_back():
    both = edit_choices("penalty_events", ["transfer_delay", "handover_delay"])
    (code, label), = selected(both)
    assert code == "handover_delay, transfer_delay" and label.startswith("oba:")
    assert parse_value("events", code) == ["handover_delay", "transfer_delay"]
    assert selected(edit_choices("penalty_events", ["transfer_delay"])) == [
        ("transfer_delay", "opóźnienie umowy przenoszącej")]


def test_unexpected_value_is_kept_not_lost():
    choices = edit_choices("penalty_basis", "something_new")
    assert selected(choices) == [("something_new", "something_new")]


def test_bool_fields_and_text_fields():
    assert selected(edit_choices("waiver_of_claims", True)) == [("tak", "tak")]
    assert selected(edit_choices("exclusive_penalty_clause", False)) == [("nie", "nie")]
    assert selected(edit_choices("exclusive_penalty_clause", None)) == [("", "— brak w dokumencie —")]
    assert edit_choices("price_gross", "450000") is None
    assert edit_choices("handover_deadline", "2024-03-31") is None
