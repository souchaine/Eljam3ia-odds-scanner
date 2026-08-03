"""Fixture matching and result validation — the two places a retro-load can corrupt itself.

Both used to live in a JS blob in the browser. They live here because this is the logic that can
silently produce a plausible wrong number, and untested logic is exactly what the project's join
discipline exists to prevent.
"""
import pytest

from scores import (Fixture, match_fixtures, normalize_key, qualifiers, validate_report)


def _fx(comp, home, away, ma="ma1"):
    return Fixture(ma=ma, comp=comp, home=home, away=away, href=f"/match-report/{ma}/")


# ---- normalization: generic club-type tokens only ---------------------------------------------

def test_club_type_prefixes_are_stripped_symmetrically():
    assert normalize_key("MSK Zilina") == normalize_key("Zilina")
    assert normalize_key("FK Akron Tolyatti") == normalize_key("Akron Tolyatti")
    assert normalize_key("Hajduk Split") == normalize_key("HNK Hajduk Split")


def test_accents_and_punctuation_are_folded():
    assert normalize_key("Häcken") == normalize_key("Hacken")
    assert normalize_key("Queen's Park") == normalize_key("Queens Park")


def test_distinct_clubs_do_not_collide_after_stripping():
    assert normalize_key("Manchester United") != normalize_key("Manchester City")
    assert normalize_key("Estudiantes") != normalize_key("Estudiantes Rio Cuarto")


# ---- qualifiers: a reserve or women's side is NEVER the first team ------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Perth Azzurri (W)", "W"), ("Salzburg Frauen", "W"), ("Shanghai Shenhua U20", "U20"),
    ("Wisla II Krakow", "R"), ("Real Oviedo Vetusta", ""), ("Sturm Graz", ""),
])
def test_qualifiers_are_detected(name, expected):
    assert qualifiers(name) == expected


def test_womens_fixture_never_matches_the_mens_fixture():
    # the real trap: "FC Salzburg vs. Hartberg" matched BOTH austria-bundesliga and
    # austria-women-bundesliga on 2026-08-01
    index = [_fx("austria-bundesliga", "rb-salzburg", "tsv-hartberg", "ma_men"),
             _fx("austria-women-bundesliga", "rb-salzburg", "spg-hartberg", "ma_women")]
    r = match_fixtures(["FC Salzburg vs. Hartberg"], index)
    assert r["matched"] == [(0, "ma_men", "austria-bundesliga")]


def test_reserve_side_never_matches_the_first_team():
    index = [_fx("spain-segunda", "real-oviedo", "mirandes", "ma_first")]
    r = match_fixtures(["Real Oviedo II vs. Mirandes"], index)
    assert r["matched"] == [] and r["unmatched"] == [0]


def test_u20_never_matches_the_senior_fixture():
    index = [_fx("china-super-league", "shanghai-shenhua", "tianjin-jinmen-tiger", "ma_senior")]
    assert match_fixtures(["Shanghai Shenhua U20 vs. Tianjin Jinmen Tiger U20"],
                          index)["matched"] == []


# ---- the join: unique-exact, or nothing --------------------------------------------------------

def test_unique_exact_match_on_both_sides():
    index = [_fx("scotland-championship", "ayr-united", "arbroath-fc", "ma_x")]
    assert match_fixtures(["Ayr United vs. Arbroath"], index)["matched"] == [
        (0, "ma_x", "scotland-championship")]


def test_ambiguity_is_rejected_never_resolved_by_guess():
    index = [_fx("league-a", "everton", "colo-colo", "ma1"),
             _fx("league-b", "everton", "colo-colo", "ma2")]
    r = match_fixtures(["Everton vs. Colo Colo"], index)
    assert r["matched"] == [] and r["ambiguous"] == [0]


def test_home_and_away_order_is_respected():
    index = [_fx("l", "arbroath-fc", "ayr-united", "ma_x")]
    r = match_fixtures(["Ayr United vs. Arbroath"], index)
    assert r["matched"] == [], "a reversed fixture is a DIFFERENT match, not the same one"


def test_unmatched_is_skipped_not_approximated():
    index = [_fx("l", "universitatea-cluj", "dynamo-kyiv", "ma_x")]
    r = match_fixtures(["U. Cluj vs. FC Dynamo Kiev"], index)
    assert r["matched"] == [] and r["unmatched"] == [0]


def test_alias_match_is_reported_separately_from_exact():
    # orthographic-only substitution (kyiv/kiev). Reported as an alias so it can carry the
    # 100% independent cross-check that exact matches do not need.
    index = [_fx("l", "dynamo-kyiv", "shakhtar", "ma_x")]
    r = match_fixtures(["Dynamo Kiev vs. Shakhtar"], index)
    assert r["matched"] == [] and [a[0] for a in r["aliased"]] == [0]


def test_a_malformed_fixture_name_is_unmatched():
    assert match_fixtures(["no separator here"], [_fx("l", "a", "b")])["unmatched"] == [0]


# ---- result validation: HT must agree with the goal minutes ------------------------------------

def test_ht_agreeing_with_goal_minutes_passes():
    ok, why = validate_report(ft="3:1", ht="2:1", goals=["1:0 X 17.", "2:0 Y 32.", "2:1 Z 38.",
                                                        "3:1 W 88."], pso=False)
    assert ok is True and why == ""


def test_stoppage_time_counts_as_first_half():
    ok, _ = validate_report(ft="1:2", ht="1:0", goals=["1:0 X 45.+2", "1:1 Y 77.", "1:2 Z 88."],
                            pso=False)
    assert ok is True


def test_ht_contradicting_goal_minutes_is_rejected():
    ok, why = validate_report(ft="2:0", ht="2:0", goals=["1:0 X 50.", "2:0 Y 70."], pso=False)
    assert ok is False and "half-time" in why.lower()


def test_ft_contradicting_the_goal_count_is_rejected():
    ok, why = validate_report(ft="3:0", ht="1:0", goals=["1:0 X 20.", "2:0 Y 60."], pso=False)
    assert ok is False and "full-time" in why.lower()


def test_goalless_match_with_no_goals_passes():
    assert validate_report(ft="0:0", ht="0:0", goals=[], pso=False)[0] is True


def test_a_shootout_fixture_is_rejected_not_silently_used():
    # O'Higgins-Boca showed "3:4"; the real result was 1:0. A pso headline must never be taken.
    ok, why = validate_report(ft="3:4", ht="0:0", goals=["1:0 X 72."], pso=True)
    assert ok is False and "shootout" in why.lower()


def test_an_unplayed_fixture_is_rejected():
    ok, why = validate_report(ft="-:-", ht=None, goals=[], pso=False)
    assert ok is False and ("not played" in why.lower() or "no result" in why.lower())


def test_missing_half_time_is_rejected_not_inferred():
    ok, why = validate_report(ft="2:0", ht=None, goals=["1:0 X 20.", "2:0 Y 60."], pso=False)
    assert ok is False and "half-time" in why.lower()
