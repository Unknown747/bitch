import tempfile
import unittest
from unittest.mock import Mock

from modules.fotmob import (
    FotMobClient,
    FotMobRateLimitError,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FotMobClientTests(unittest.TestCase):
    def make_client(self, cache_dir, responses):
        session = Mock()
        session.headers = {}
        session.get.side_effect = responses
        return FotMobClient(
            cache_dir=cache_dir,
            request_delay_seconds=0,
            max_retries=0,
            session=session,
        ), session

    def test_fixtures_are_normalized_and_cached(self):
        response = FakeResponse({
            "date": "20261011",
            "leagues": [{
                "id": 47,
                "name": "Premier League",
                "matches": [{
                    "id": 5795469,
                    "home": {"id": 9826, "name": "Crystal Palace"},
                    "away": {"id": 10203, "name": "Nottingham Forest"},
                    "status": {
                        "utcTime": "2026-10-11T13:00:00.000Z",
                        "cancelled": False,
                    },
                }],
            }],
        })
        with tempfile.TemporaryDirectory() as cache_dir:
            client, session = self.make_client(cache_dir, [response])

            first = client.get_fixtures_by_date("2026-10-11")
            second = client.get_fixtures_by_date("2026-10-11")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["fixture_id"], 5795469)
        self.assertEqual(first[0]["kickoff_iso"], "2026-10-11T13:00:00")
        self.assertEqual(first[0]["league_id"], 47)
        session.get.assert_called_once()

    def test_h2h_uses_finished_status_and_parses_score(self):
        response = FakeResponse({
            "content": {
                "h2h": {
                    "matches": [
                        {
                            "home": {"id": 10, "name": "Home"},
                            "away": {"id": 20, "name": "Away"},
                            "time": {"utcTime": "2027-01-01T12:00:00Z"},
                            "status": {"finished": False},
                        },
                        {
                            "home": {"id": "20", "name": "Away"},
                            "away": {"id": "10", "name": "Home"},
                            "time": {"utcTime": "2026-01-01T12:00:00Z"},
                            "league": {"name": "Premier League"},
                            # FotMob's row-level `finished` value can disagree;
                            # the nested status is the reliable result flag.
                            "finished": False,
                            "status": {"finished": True, "scoreStr": "1 - 2"},
                        },
                    ],
                },
            },
        })
        with tempfile.TemporaryDirectory() as cache_dir:
            client, _ = self.make_client(cache_dir, [response])
            h2h = client.get_h2h_matches(123, last_n=5)

        self.assertEqual(len(h2h), 1)
        self.assertEqual(h2h[0]["score"], {"home": 1, "away": 2})
        self.assertTrue(h2h[0]["teams"]["away"]["winner"])
        self.assertEqual(h2h[0]["teams"]["home"]["id"], 20)

    def test_team_stats_use_only_finished_matches_in_requested_league(self):
        response = FakeResponse({
            "fixtures": {
                "allFixtures": {
                    "fixtures": [
                        {
                            "home": {"id": 10, "score": 2},
                            "away": {"id": 20, "score": 0},
                            "tournament": {"leagueId": 47},
                            "status": {"finished": True, "utcTime": "2026-08-01T12:00:00Z"},
                        },
                        {
                            "home": {"id": 20, "score": 1},
                            "away": {"id": 10, "score": 1},
                            "tournament": {"leagueId": "47"},
                            "status": {"finished": True, "utcTime": "2026-08-10T12:00:00Z"},
                        },
                        {
                            "home": {"id": 10, "score": 0},
                            "away": {"id": 30, "score": 1},
                            "tournament": {"leagueId": 489},
                            "status": {"finished": True, "utcTime": "2026-08-12T12:00:00Z"},
                        },
                        {
                            "home": {"id": 10, "score": 0},
                            "away": {"id": 20, "score": 0},
                            "tournament": {"leagueId": 47},
                            "status": {"finished": False, "utcTime": "2026-08-20T12:00:00Z"},
                        },
                    ],
                },
            },
        })
        with tempfile.TemporaryDirectory() as cache_dir:
            client, _ = self.make_client(cache_dir, [response])
            stats = client.get_team_statistics(10, 47)

        self.assertEqual(stats["form"], "WD")
        self.assertEqual(stats["fixtures"]["played"]["home"], 1)
        self.assertEqual(stats["fixtures"]["wins"]["home"], 1)
        self.assertEqual(stats["fixtures"]["played"]["away"], 1)
        self.assertEqual(stats["fixtures"]["draws"]["away"], 1)

    def test_http_429_stops_requests_and_persists_cooldown(self):
        response = FakeResponse(status_code=429, headers={"Retry-After": "60"})
        with tempfile.TemporaryDirectory() as cache_dir:
            client, session = self.make_client(cache_dir, [response])

            with self.assertRaises(FotMobRateLimitError):
                client._request_json("matches", {"date": "20261011"}, "matches")

            self.assertTrue((client.cache_dir / "rate-limit.json").exists())
            with self.assertRaises(FotMobRateLimitError):
                client._request_json("matches", {"date": "20261011"}, "matches")

        session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
