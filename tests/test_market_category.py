from make_betslips import market_category, CATEGORY_ORDER


def test_corners_wins_over_first_half():
    assert market_category("1st half - total corners") == "corners"


def test_carte_wins_over_first_half():
    assert market_category("1st half - total bookings") == "carte"


def test_carte_matches_bookings_and_cards():
    assert market_category("Total bookings") == "carte"
    assert market_category("Both teams 3+ bookings each") == "carte"


def test_multigoals():
    assert market_category("1st half - multigoals") == "multigoals"


def test_first_and_second_half():
    assert market_category("1st half - total") == "1st half"
    assert market_category("2nd half - double chance") == "2nd half"


def test_combo_dc():
    assert market_category("Double chance & total 2.5") == "combo DC"
    assert market_category("DC Halftime/ DC Fulltime") == "combo DC"


def test_main_is_default():
    assert market_category("1x2") == "main"
    assert market_category("Correct score") == "main"


def test_category_order_has_seven_families():
    assert CATEGORY_ORDER == ["main", "combo DC", "1st half", "2nd half",
                              "corners", "carte", "multigoals"]
