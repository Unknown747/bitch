import ast
import asyncio
from collections import Counter
from datetime import datetime
import math
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
        scraped_matches = self._extract_market_picks(payload, kickoff_iso)
        counts = Counter(item["market_type"] for item in scraped_matches)
        print(
            "  [Scraper] Extracted market selections: "
            f"1X2={counts.get('1X2', 0)}, HDP={counts.get('HDP', 0)}, "
            f"O/U={counts.get('O/U', 0)}."
        )
        return scraped_matches

    @classmethod
    def _extract_market_picks(cls, payload: list, kickoff_iso: str) -> list:
        """Read full-time 1X2, HDP and O/U selections from the linked-row feed."""
        scraped_matches = []
        best_prices = {}

        for league in payload[3]:
            if not isinstance(league, list) or len(league) < 2:
                continue

            league_info, match_rows = league[0], league[1]
            if not isinstance(league_info, list) or len(league_info) < 2:
                continue
            if not isinstance(match_rows, list):
                continue

            for row in match_rows:
                if not isinstance(row, list) or len(row) <= 7:
                    continue

                home = cls._clean_team_name(row[6])
                away = cls._clean_team_name(row[7])
                if not home or not away:
                    continue

                event_time = str(row[4]).strip() if len(row) > 4 else ""
                event_key = (
                    str(league_info[0]),
                    home.casefold(),
                    away.casefold(),
                    event_time.casefold(),
                )
                picks = []

                # Full-time 1X2 values are already decimal odds: home, draw, away.
                if len(row) > 13 and cls._feed_flag(row[9]):
                    for selection, side, selected_team, odds_index, label in (
                        ("home", "home", home, 11, "Home Win"),
                        ("draw", None, "Draw", 12, "Draw"),
                        ("away", "away", away, 13, "Away Win"),
                    ):
                        odds = cls._parse_odds(row[odds_index])
                        if odds is not None:
                            picks.append({
                                "market_type": "1X2",
                                "selection": selection,
                                "selection_side": side,
                                "selection_label": label,
                                "selected_pick": selected_team,
                                "market_line": None,
                                "odds_value": odds,
                            })

                # HDP prices are stored in tenths (20.6 is displayed as 2.06).
                if (
                    len(row) > 18
                    and cls._feed_flag(row[14])
                    and cls._market_odds_available(row[16])
                ):
                    handicap = cls._parse_line(row[15])
                    if handicap is not None:
                        handicap = abs(handicap)
                        home_gives_handicap = cls._feed_flag(row[5])
                        for side, selected_team, odds_index in (
                            ("home", home, 17),
                            ("away", away, 18),
                        ):
                            team_gives_handicap = (
                                home_gives_handicap if side == "home" else not home_gives_handicap
                            )
                            signed_handicap = -handicap if team_gives_handicap else handicap
                            odds = cls._parse_odds(row[odds_index], divisor=10.0)
                            if odds is not None:
                                picks.append({
                                    "market_type": "HDP",
                                    "selection": side,
                                    "selection_side": side,
                                    "selection_label": f"{side.title()} Handicap",
                                    "selected_pick": selected_team,
                                    "market_line": signed_handicap,
                                    "odds_value": odds,
                                })

                # Full-time O/U uses a total-goals line and prices in tenths.
                if (
                    len(row) > 25
                    and cls._feed_flag(row[19])
                    and cls._market_odds_available(row[23])
                ):
                    total_line = cls._parse_line(row[20])
                    if total_line is not None:
                        for selection, odds_index in (("over", 24), ("under", 25)):
                            odds = cls._parse_odds(row[odds_index], divisor=10.0)
                            if odds is not None:
                                picks.append({
                                    "market_type": "O/U",
                                    "selection": selection,
                                    "selection_side": None,
                                    "selection_label": selection.title(),
                                    "selected_pick": f"{selection.title()} {total_line:g}",
                                    "market_line": total_line,
                                    "odds_value": odds,
                                })

                for pick in picks:
                    line_key = (
                        round(pick["market_line"], 3)
                        if pick["market_line"] is not None
                        else None
                    )
                    pick_key = event_key + (
                        pick["market_type"],
                        pick["selection"],
                        line_key,
                    )
                    candidate = {
                        "home": home,
                        "away": away,
                        **pick,
                        "pick_type": pick["selection_label"],
                        "kickoff_iso": kickoff_iso,
                    }
                    current = best_prices.get(pick_key)
                    if current is None or candidate["odds_value"] > current["odds_value"]:
                        best_prices[pick_key] = candidate

        scraped_matches.extend(best_prices.values())
        return scraped_matches

    @staticmethod
    def _clean_team_name(value) -> str:
        return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)

    @staticmethod
    def _parse_odds(value, divisor=1.0):
        try:
            odds = float(str(value).replace(",", ".")) / divisor
        except (TypeError, ValueError):
            return None
        return odds if math.isfinite(odds) and 1.01 <= odds <= 10.0 else None

    @staticmethod
    def _parse_line(value):
        try:
            line = float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(line) or line < 0 or line > 10:
            return None
        return line

    @staticmethod
    def _feed_flag(value):
        if isinstance(value, bool):
            return value
        try:
            return float(value) != 0
        except (TypeError, ValueError):
            return str(value).strip().casefold() in {"true", "yes"}

    @staticmethod
    def _market_odds_available(value):
        try:
            odds_marker = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(odds_marker) and not (-1 < odds_marker < 1)
