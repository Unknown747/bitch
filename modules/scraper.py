import ast
import asyncio
from datetime import datetime
import re
from urllib.parse import urljoin
import zoneinfo

import requests
from bs4 import BeautifulSoup


class ParlayScraper:
    def __init__(self, target_url="https://mainbolakaki.pro/_view/odds4.aspx"):
        self.url = target_url
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )

    async def fetch_odds_data(self) -> list:
        return await asyncio.to_thread(self._fetch_odds_data)

    def _fetch_odds_data(self) -> list:
        with requests.Session() as session:
            session.headers.update({"User-Agent": self.user_agent})

            page_response = session.get(self.url, timeout=30)
            page_response.raise_for_status()
            page = BeautifulSoup(page_response.content, "html.parser")

            feed_path = None
            for script in page.find_all("script"):
                script_text = script.get_text()
                match = re.search(
                    r"\bajaxToday\s*\(\s*(['\"])([^'\"]+)\1",
                    script_text,
                )
                if match:
                    feed_path = match.group(2)
                    break

            if not feed_path:
                raise ValueError("Could not find the odds data feed URL in the page.")

            feed_url = urljoin(page_response.url, feed_path)
            feed_response = session.get(
                feed_url,
                headers={
                    "Referer": page_response.url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=30,
            )
            feed_response.raise_for_status()

        try:
            payload = ast.literal_eval(feed_response.text.lstrip("\ufeff").replace(r"\/", "/"))
        except (SyntaxError, ValueError) as exc:
            raise ValueError("The odds feed format could not be parsed.") from exc

        if not isinstance(payload, list) or len(payload) <= 3 or not isinstance(payload[3], list):
            raise ValueError("The odds feed has an unexpected data structure.")

        today = datetime.now(zoneinfo.ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d")
        kickoff_iso = f"{today}T20:00:00"
        scraped_matches = []
        seen_matches = set()

        for league in payload[3]:
            if not isinstance(league, list) or len(league) < 2:
                continue

            league_info, match_rows = league[0], league[1]
            if not isinstance(league_info, list) or len(league_info) < 2:
                continue
            if not isinstance(match_rows, list):
                continue

            for row in match_rows:
                if not isinstance(row, list) or len(row) <= 13:
                    continue

                home = self._clean_team_name(row[6])
                away = self._clean_team_name(row[7])
                if not home or not away:
                    continue

                home_odds = self._parse_odds(row[11])
                away_odds = self._parse_odds(row[13])
                if home_odds is None and away_odds is None:
                    continue

                event_time = str(row[4]).strip() if len(row) > 4 else ""
                match_key = (
                    str(league_info[0]),
                    home.casefold(),
                    away.casefold(),
                    event_time.casefold(),
                )
                if match_key in seen_matches:
                    continue
                seen_matches.add(match_key)

                if home_odds is not None and (away_odds is None or home_odds <= away_odds):
                    selected_team = home
                    selected_odds = home_odds
                    pick_type = "Home Win"
                else:
                    selected_team = away
                    selected_odds = away_odds
                    pick_type = "Away Win"

                scraped_matches.append({
                    "home": home,
                    "away": away,
                    "selected_pick": selected_team,
                    "pick_type": pick_type,
                    "odds_value": selected_odds,
                    "kickoff_iso": kickoff_iso,
                })

        print(f"  [Scraper] Extracted {len(scraped_matches)} unique matches from odds feed.")
        return scraped_matches

    @staticmethod
    def _clean_team_name(value) -> str:
        return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)

    @staticmethod
    def _parse_odds(value):
        try:
            odds = float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None
        return odds if 1.01 <= odds <= 10.0 else None
