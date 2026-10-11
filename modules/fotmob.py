import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

import requests


class FotMobClientError(RuntimeError):
    """A request or response from FotMob could not be used safely."""


class FotMobRateLimitError(FotMobClientError):
    """FotMob rate-limited or temporarily blocked the client."""


class FotMobAccessDeniedError(FotMobClientError):
    """FotMob denied access to an endpoint."""


class FotMobClient:
    BASE_URL = "https://www.fotmob.com/api/data"
    DEFAULT_COOLDOWN_SECONDS = 15 * 60
    SCORE_PATTERN = re.compile(r"^\s*(\d+)\s*[-–:]\s*(\d+)")

    def __init__(
        self,
        cache_dir: str = "data/cache/fotmob",
        request_delay_seconds: float = 1.0,
        max_retries: int = 2,
        session=None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.request_delay_seconds = max(0.0, float(request_delay_seconds))
        self.max_retries = max(0, int(max_retries))
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Referer": "https://www.fotmob.com/",
            "User-Agent": "mix-parlay-filter/1.0 (unofficial FotMob client)",
        })
        self._last_request_at = None
        self._cooldown_path = self.cache_dir / "rate-limit.json"

    def _wait_for_request_slot(self):
        self._check_rate_limit_cooldown()
        if self._last_request_at is None:
            return

        elapsed = time.monotonic() - self._last_request_at
        wait_seconds = self.request_delay_seconds - elapsed
        if wait_seconds > 0:
            print(f"  [FotMob] Waiting {wait_seconds:.1f}s before the next request.")
            time.sleep(wait_seconds)

    def _check_rate_limit_cooldown(self):
        if not self._cooldown_path.exists():
            return

        try:
            cooldown = json.loads(self._cooldown_path.read_text(encoding="utf-8"))
            not_before = float(cooldown["not_before"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise FotMobClientError(
                f"FotMob rate-limit state is unreadable at {self._cooldown_path}; "
                "check or remove it before making another request."
            ) from exc

        remaining = not_before - time.time()
        if remaining > 0:
            raise FotMobRateLimitError(
                "A previous FotMob HTTP 429 response requested a cooldown. "
                f"Wait at least {int(remaining + 0.999)} seconds before trying again."
            )

        self._cooldown_path.unlink(missing_ok=True)

    @staticmethod
    def _retry_after_seconds(value):
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def _record_rate_limit(self, response):
        delay = self._retry_after_seconds(response.headers.get("Retry-After"))
        if delay is None:
            delay = self.DEFAULT_COOLDOWN_SECONDS
        not_before = time.time() + max(1.0, delay)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_dir,
                delete=False,
            ) as cache_file:
                temporary_path = Path(cache_file.name)
                json.dump({"not_before": not_before}, cache_file)
            os.replace(temporary_path, self._cooldown_path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)
        return max(1.0, delay)

    def _request_json(self, endpoint: str, params: Dict, label: str) -> Dict:
        url = f"{self.BASE_URL}/{endpoint}"
        for attempt in range(self.max_retries + 1):
            self._wait_for_request_slot()
            self._last_request_at = time.monotonic()
            try:
                response = self.session.get(url, params=params, timeout=(5, 20))
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise FotMobClientError(
                        f"Could not fetch FotMob {label} after {attempt + 1} attempts: {exc}"
                    ) from exc
                delay = 2 ** attempt
                print(f"  [FotMob] Temporary network error for {label}; retrying in {delay}s.")
                time.sleep(delay)
                continue

            if response.status_code == 429:
                delay = self._record_rate_limit(response)
                raise FotMobRateLimitError(
                    "FotMob returned HTTP 429. The pipeline stopped without retrying; "
                    f"respect the requested cooldown of at least {int(delay + 0.999)} seconds."
                )
            if response.status_code == 403:
                raise FotMobAccessDeniedError(
                    f"FotMob denied {label} with HTTP 403. The pipeline stopped; "
                    "do not bypass the restriction with proxies or IP rotation."
                )

            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                retry_after = self._retry_after_seconds(response.headers.get("Retry-After"))
                delay = max(2 ** attempt, retry_after or 0.0)
                if delay > 30:
                    raise FotMobClientError(
                        f"FotMob returned HTTP {response.status_code} for {label} "
                        f"and requested a {int(delay)} second wait; stopping instead of retrying."
                    )
                print(
                    f"  [FotMob] HTTP {response.status_code} for {label}; "
                    f"retrying in {delay:.0f}s."
                )
                time.sleep(delay)
                continue

            if not 200 <= response.status_code < 300:
                raise FotMobClientError(
                    f"FotMob returned HTTP {response.status_code} for {label}."
                )

            try:
                payload = response.json()
            except (ValueError, requests.exceptions.JSONDecodeError) as exc:
                raise FotMobClientError(
                    f"FotMob returned invalid JSON for {label}; its endpoint may have changed."
                ) from exc
            if not isinstance(payload, dict):
                raise FotMobClientError(
                    f"FotMob returned an unexpected response for {label}; expected a JSON object."
                )
            return payload

        raise FotMobClientError(f"Could not fetch FotMob {label}.")

    def _load_or_fetch(self, cache_name: str, fetch):
        cache_path = self.cache_dir / cache_name
        if cache_path.exists():
            try:
                with cache_path.open(encoding="utf-8") as cache_file:
                    cached = json.load(cache_file)
                print(f"  [FotMob] Using cached {cache_name}.")
                return cached
            except (OSError, ValueError) as exc:
                print(f"  [FotMob] Ignoring unreadable cache {cache_name}: {exc}")

        result = fetch()
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_dir,
                delete=False,
            ) as cache_file:
                temporary_path = Path(cache_file.name)
                json.dump(result, cache_file, ensure_ascii=False)
            os.replace(temporary_path, cache_path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)
        return result

    @staticmethod
    def _today_cache_date():
        return datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d")

    @staticmethod
    def _team_id(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    def get_fixtures_by_date(self, date_str: str) -> List[Dict]:
        """Fetch and normalize FotMob fixtures for one date (YYYY-MM-DD)."""
        try:
            date_key = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y%m%d")
        except ValueError as exc:
            raise ValueError("date_str must use YYYY-MM-DD format.") from exc

        payload = self._load_or_fetch(
            f"matches_{date_key}.json",
            lambda: self._request_json(
                "matches",
                {"date": date_key},
                f"matches for {date_str}",
            ),
        )
        if not isinstance(payload, dict):
            raise FotMobClientError("FotMob matches cache must contain a JSON object.")
        leagues = payload.get("leagues")
        if not isinstance(leagues, list):
            raise FotMobClientError("FotMob matches response is missing its leagues list.")

        fixtures = []
        for league in leagues:
            if not isinstance(league, dict):
                continue
            league_id = self._team_id(league.get("id", league.get("primaryId")))
            league_name = league.get("name")
            matches = league.get("matches")
            if not isinstance(matches, list):
                continue

            for match in matches:
                if not isinstance(match, dict):
                    continue
                home = match.get("home")
                away = match.get("away")
                status = match.get("status")
                if not isinstance(home, dict) or not isinstance(away, dict):
                    continue
                if not isinstance(status, dict) or status.get("cancelled") is True:
                    continue
                if not home.get("id") or not away.get("id") or not match.get("id"):
                    continue
                kickoff = status.get("utcTime") or ""
                fixtures.append({
                    "fixture_id": self._team_id(match["id"]),
                    "home": home.get("name") or home.get("longName"),
                    "home_id": self._team_id(home["id"]),
                    "away": away.get("name") or away.get("longName"),
                    "away_id": self._team_id(away["id"]),
                    "kickoff_iso": kickoff[:19] if kickoff else "",
                    "league": league_name or "Unknown League",
                    "league_name": league_name or "Unknown League",
                    "league_id": league_id,
                })

        return fixtures

    def get_h2h_matches(self, fixture_id: int, last_n: int = 5) -> List[Dict]:
        """Read the finished head-to-head matches listed on a FotMob match page."""
        if not fixture_id:
            raise FotMobClientError("A FotMob fixture ID is required to fetch H2H data.")

        payload = self._load_or_fetch(
            f"h2h_match_{fixture_id}.json",
            lambda: self._request_json(
                "matchDetails",
                {"matchId": fixture_id},
                f"H2H for fixture {fixture_id}",
            ),
        )
        if not isinstance(payload, dict):
            raise FotMobClientError(
                f"FotMob match details for fixture {fixture_id} must be a JSON object."
            )
        content = payload.get("content")
        h2h = content.get("h2h") if isinstance(content, dict) else None
        rows = h2h.get("matches") if isinstance(h2h, dict) else None
        if not isinstance(rows, list):
            raise FotMobClientError(
                f"FotMob match details for fixture {fixture_id} are missing H2H data."
            )

        formatted = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = row.get("status")
            if not isinstance(status, dict) or status.get("finished") is not True:
                continue

            home = row.get("home")
            away = row.get("away")
            score_str = status.get("scoreStr") or ""
            score_match = self.SCORE_PATTERN.match(score_str)
            if not isinstance(home, dict) or not isinstance(away, dict) or not score_match:
                raise FotMobClientError(
                    f"FotMob returned an unreadable finished H2H result for fixture {fixture_id}."
                )

            home_score, away_score = map(int, score_match.groups())
            formatted.append({
                "fixture_id": self._team_id(row.get("id")),
                "date": (row.get("time") or {}).get("utcTime", "")[:10],
                "league": (row.get("league") or {}).get("name", "Unknown League"),
                "teams": {
                    "home": {
                        "id": self._team_id(home.get("id")),
                        "name": home.get("name", "Home"),
                        "winner": home_score > away_score,
                    },
                    "away": {
                        "id": self._team_id(away.get("id")),
                        "name": away.get("name", "Away"),
                        "winner": away_score > home_score,
                    },
                },
                "score": {"home": home_score, "away": away_score},
            })

        formatted.sort(key=lambda item: item["date"], reverse=True)
        return formatted[:max(0, int(last_n))]

    def get_team_statistics(self, team_id: int, league_id: int) -> Dict:
        """Build recent form and venue records from the team's current fixture list."""
        if not team_id or not league_id:
            raise FotMobClientError("Both a FotMob team ID and league ID are required for team stats.")

        cache_date = self._today_cache_date()
        payload = self._load_or_fetch(
            f"team_stats_{team_id}_{league_id}_{cache_date}.json",
            lambda: self._request_json(
                "teams",
                {"id": team_id},
                f"fixtures for team {team_id}",
            ),
        )
        if not isinstance(payload, dict):
            raise FotMobClientError(f"FotMob team cache for {team_id} must contain a JSON object.")
        all_fixtures = (
            payload.get("fixtures", {}).get("allFixtures", {}).get("fixtures")
            if isinstance(payload.get("fixtures"), dict)
            and isinstance(payload["fixtures"].get("allFixtures"), dict)
            else None
        )
        if not isinstance(all_fixtures, list):
            raise FotMobClientError(
                f"FotMob team response for {team_id} is missing its fixture list."
            )

        completed = []
        for fixture in all_fixtures:
            if not isinstance(fixture, dict):
                continue
            status = fixture.get("status")
            tournament = fixture.get("tournament")
            home = fixture.get("home")
            away = fixture.get("away")
            if not isinstance(status, dict) or status.get("finished") is not True:
                continue
            if not isinstance(tournament, dict) or str(tournament.get("leagueId")) != str(league_id):
                continue
            if not isinstance(home, dict) or not isinstance(away, dict):
                continue
            try:
                home_score = int(home["score"])
                away_score = int(away["score"])
            except (KeyError, TypeError, ValueError):
                raise FotMobClientError(
                    f"FotMob returned an unreadable finished team fixture for team {team_id}."
                )

            home_id = self._team_id(home.get("id"))
            away_id = self._team_id(away.get("id"))
            if str(home_id) != str(team_id) and str(away_id) != str(team_id):
                continue
            completed.append({
                "utc_time": status.get("utcTime", ""),
                "home_id": home_id,
                "away_id": away_id,
                "home_score": home_score,
                "away_score": away_score,
            })

        completed.sort(key=lambda fixture: fixture["utc_time"], reverse=True)
        latest_five = completed[:5]
        form_chars = []
        venue_stats = {
            "home": {"played": 0, "wins": 0, "draws": 0, "loses": 0},
            "away": {"played": 0, "wins": 0, "draws": 0, "loses": 0},
        }

        for fixture in completed:
            is_home = str(fixture["home_id"]) == str(team_id)
            venue = "home" if is_home else "away"
            team_goals = fixture["home_score"] if is_home else fixture["away_score"]
            opponent_goals = fixture["away_score"] if is_home else fixture["home_score"]
            venue_stats[venue]["played"] += 1
            if team_goals > opponent_goals:
                venue_stats[venue]["wins"] += 1
            elif team_goals == opponent_goals:
                venue_stats[venue]["draws"] += 1
            else:
                venue_stats[venue]["loses"] += 1

        for fixture in reversed(latest_five):
            is_home = str(fixture["home_id"]) == str(team_id)
            team_goals = fixture["home_score"] if is_home else fixture["away_score"]
            opponent_goals = fixture["away_score"] if is_home else fixture["home_score"]
            form_chars.append(
                "W" if team_goals > opponent_goals
                else "D" if team_goals == opponent_goals
                else "L"
            )

        return {
            "form": "".join(form_chars),
            "fixtures": {
                "played": {venue: stats["played"] for venue, stats in venue_stats.items()},
                "wins": {venue: stats["wins"] for venue, stats in venue_stats.items()},
                "draws": {venue: stats["draws"] for venue, stats in venue_stats.items()},
                "loses": {venue: stats["loses"] for venue, stats in venue_stats.items()},
            },
        }
