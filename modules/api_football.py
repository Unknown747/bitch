import os
import json
import requests
import time
from typing import Dict, List

class APIFootballClient:
    def __init__(
        self,
        api_key: str,
        cache_dir: str = "data/cache",
        request_delay_seconds: float = 7.0,
    ):
        self.api_key = api_key
        self.base_url = "https://v3.football.api-sports.io"
        self.headers = {'x-apisports-key': self.api_key}
        self.cache_dir = cache_dir
        self.request_delay_seconds = max(0.0, float(request_delay_seconds))
        self._last_request_at = None
        os.makedirs(cache_dir, exist_ok=True)

    def _request(self, endpoint: str, params: Dict) -> requests.Response:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            wait_seconds = self.request_delay_seconds - elapsed
            if wait_seconds > 0:
                print(f"  [API] Waiting {wait_seconds:.1f}s before next request.")
                time.sleep(wait_seconds)

        self._last_request_at = time.monotonic()
        return requests.get(
            f"{self.base_url}/{endpoint}",
            headers=self.headers,
            params=params,
            timeout=15,
        )

    def _request_json(self, endpoint: str, params: Dict, label: str):
        try:
            response = self._request(endpoint, params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                print(f"❌ API-Football returned an unexpected response for {label}.")
                return None

            errors = payload.get('errors')
            if errors:
                print(f"❌ API-Football {label} error: {errors}")
                return None
            return payload
        except Exception as exc:
            print(f"❌ Error fetching {label}: {exc}")
            return None

    def get_fixtures_by_date(self, date_str: str) -> List[Dict]:
        """
        Mengambil jadwal pertandingan resmi dari API-Football berdasarkan tanggal (YYYY-MM-DD).
        """
        cache_file = os.path.join(self.cache_dir, f"fixtures_{date_str}.json")
        
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                return json.load(f)

        params = {'date': date_str}
        res_json = self._request_json("fixtures", params, "fixtures")
        if res_json is None:
            return []
        data = res_json.get('response', [])

        formatted = []
        for item in data:
            formatted.append({
                "fixture_id": item['fixture']['id'],
                "home": item['teams']['home']['name'],
                "home_id": item['teams']['home']['id'],
                "away": item['teams']['away']['name'],
                "away_id": item['teams']['away']['id'],
                "kickoff_iso": item['fixture']['date'][:19],
                "league": item['league']['name'],
                "league_id": item['league']['id']
            })

        if formatted:
            with open(cache_file, "w") as f:
                json.dump(formatted, f, indent=2)

        return formatted

    def get_h2h_matches(self, team_id_1: int, team_id_2: int, last_n: int = 5) -> List[Dict]:
        """
        Mengambil riwayat pertemuan Head-to-Head antara dua tim.
        """
        sorted_ids = sorted([team_id_1, team_id_2])
        cache_file = os.path.join(self.cache_dir, f"h2h_{sorted_ids[0]}_{sorted_ids[1]}.json")

        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                return json.load(f)[:last_n]

        # The Free API plan rejects the `last` parameter; trim the response locally instead.
        params = {'h2h': f"{team_id_1}-{team_id_2}"}
        res_json = self._request_json("fixtures/headtohead", params, "H2H")
        if res_json is None:
            return []
        data = res_json.get('response', [])

        formatted = []
        for item in data:
            formatted.append({
                "fixture_id": item['fixture']['id'],
                "date": item['fixture']['date'][:10],
                "league": item['league']['name'],
                "teams": {
                    "home": {"id": item['teams']['home']['id'], "name": item['teams']['home']['name'], "winner": item['teams']['home']['winner']},
                    "away": {"id": item['teams']['away']['id'], "name": item['teams']['away']['name'], "winner": item['teams']['away']['winner']}
                },
                "score": item['goals']
            })

        if formatted:
            with open(cache_file, "w") as f:
                json.dump(formatted, f, indent=2)

        return formatted[:last_n]

    def get_team_statistics(self, team_id: int, league_id: int, season: int = None) -> Dict:
        """
        Mengambil data statistik tim (Form & Fixtures).
        Aman dari AttributeError 'list' object has no attribute 'get'.
        """
        from datetime import datetime
        if not season:
            season = datetime.now().year - 1

        cache_file = os.path.join(self.cache_dir, f"stats_{team_id}_{league_id}_{season}.json")

        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                return json.load(f)

        params = {'team': team_id, 'league': league_id, 'season': season}
        payload = self._request_json(
            "teams/statistics",
            params,
            f"statistics for team {team_id}",
        )
        data = {}
        api_failed = payload is None
        raw_res = payload.get('response', {}) if payload else {}
        if isinstance(raw_res, dict):
            data = raw_res
        elif isinstance(raw_res, list) and raw_res and isinstance(raw_res[0], dict):
            data = raw_res[0]

        raw_form = data.get("form", "") if isinstance(data, dict) else ""

        # Fallback 1: Coba season alternatif (+1/2026) jika season berjalan belum/sudah usai
        if not raw_form and not api_failed:
            alt_params = {'team': team_id, 'league': league_id, 'season': season + 1}
            alt_payload = self._request_json(
                "teams/statistics",
                alt_params,
                f"alternate-season statistics for team {team_id}",
            )
            if alt_payload is None:
                api_failed = True
            else:
                raw_alt = alt_payload.get('response', {})
                if isinstance(raw_alt, dict):
                    data_alt = raw_alt
                elif isinstance(raw_alt, list) and raw_alt and isinstance(raw_alt[0], dict):
                    data_alt = raw_alt[0]
                else:
                    data_alt = {}
                raw_form = data_alt.get("form", "")
                if raw_form:
                    data = data_alt

        # Fallback 2: Ambil langsung dari 5 laga terakhir tim jika endpoint statistik liga kosong
        if not raw_form and not api_failed:
            fixture_params = {
                'team': team_id,
                'season': season + 1,
                'status': 'FT',
            }
            fixture_payload = self._request_json(
                "fixtures",
                fixture_params,
                f"recent fixtures for team {team_id}",
            )
            if fixture_payload is not None:
                fixture_rows = fixture_payload.get('response', [])
                if isinstance(fixture_rows, list):
                    last_fixtures = sorted(
                        fixture_rows,
                        key=lambda fixture: fixture.get('fixture', {}).get('date', ''),
                        reverse=True,
                    )[:5]
                    form_chars = []
                    for fix in last_fixtures:
                        teams = fix.get('teams', {})
                        home = teams.get('home', {})
                        away = teams.get('away', {})
                        if str(team_id) == str(home.get('id')):
                            selected_winner = home.get('winner')
                            opponent_winner = away.get('winner')
                        elif str(team_id) == str(away.get('id')):
                            selected_winner = away.get('winner')
                            opponent_winner = home.get('winner')
                        else:
                            continue

                        if selected_winner is True:
                            form_chars.append('W')
                        elif opponent_winner is True:
                            form_chars.append('L')
                        else:
                            form_chars.append('D')
                    raw_form = "".join(form_chars)

        fixtures_dict = data.get("fixtures", {}) if isinstance(data, dict) else {}

        formatted = {
            "form": raw_form,
            "fixtures": {
                "played": fixtures_dict.get("played", {}),
                "wins": fixtures_dict.get("wins", {}),
                "draws": fixtures_dict.get("draws", {}),
                "loses": fixtures_dict.get("loses", {})
            }
        }

        if formatted["form"]:
            with open(cache_file, "w") as f:
                json.dump(formatted, f, indent=2)

        return formatted
