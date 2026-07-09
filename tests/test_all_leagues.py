import eljam3ia_odds_scanner as sc


def test_get_all_football_events_tags_league(monkeypatch):
    def fake_fetch(client, endpoint, **params):
        if endpoint == "GetSportMenu":
            return {"champs": [{"id": 10, "name": "\tLiga X  "}]}
        assert endpoint == "GetEvents"
        return {"events": [{"id": 1, "champId": 10}, {"id": 2, "champId": 99}]}

    monkeypatch.setattr(sc, "fetch", fake_fetch)
    events = sc.get_all_football_events(None)
    assert events[0]["_league"] == "Liga X"
    assert events[1]["_league"] == "League 99"
