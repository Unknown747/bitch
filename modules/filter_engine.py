import math
from typing import Dict, List, Optional


class ParlayFilterEngine:
    def __init__(self, min_odds: float = 1.20, max_odds: float = 1.80, min_ev: float = -0.02):
        self.min_odds = min_odds
        self.max_odds = max_odds
        self.min_ev = min_ev

    @staticmethod
    def calculate_implied_probability(odds: float) -> float:
        if odds <= 1.0:
            return 0.0
        return round(1.0 / odds, 4)

    @staticmethod
    def _parse_form_score(form_str: str) -> float:
        if not form_str or form_str == 'WWDDL':
            return 0.50
        points = 0.0
        clean_form = form_str.upper()[-5:]
        for res in clean_form:
            if res == 'W':
                points += 1.0
            elif res == 'D':
                points += 0.5
        return points / len(clean_form) if clean_form else 0.50

    def estimate_real_probability(
        self,
        team_stats: Dict,
        h2h_matches: List[Dict],
        is_home: bool = True,
        team_id: Optional[int] = None,
    ) -> tuple:
        raw_form = team_stats.get('form', '')
        form_str = raw_form[-5:] if raw_form else "N/A"
        form_rate = self._parse_form_score(raw_form)

        h2h_wins = 0
        h2h_details = []
        relevant_h2h = []
        for match in (h2h_matches or [])[:5]:
            teams = match.get('teams', {})
            if team_id is not None and any(
                str(teams.get(side, {}).get('id')) == str(team_id)
                for side in ('home', 'away')
            ):
                relevant_h2h.append(match)

        total_h2h = len(relevant_h2h)
        if total_h2h:
            for match in relevant_h2h:
                teams = match.get('teams', {})
                score = match.get('score', match.get('goals', {}))
                home_name = teams.get('home', {}).get('name', 'Home')
                away_name = teams.get('away', {}).get('name', 'Away')
                h_score = score.get('home', 0)
                a_score = score.get('away', 0)

                selected_team = next(
                    (
                        teams[side]
                        for side in ('home', 'away')
                        if str(teams.get(side, {}).get('id')) == str(team_id)
                    ),
                    None,
                )
                if selected_team and selected_team.get('winner') is True:
                    h2h_wins += 1

                h2h_details.append(f"{home_name} {h_score}-{a_score} {away_name}")
            h2h_rate = h2h_wins / total_h2h
        else:
            h2h_rate = 0.50
            h2h_details = ["Tidak ada data H2H"]

        fixtures = team_stats.get('fixtures', {})
        venue = 'home' if is_home else 'away'
        played = fixtures.get('played', {}).get(venue, 0)
        wins = fixtures.get('wins', {}).get(venue, 0)
        try:
            played = float(played or 0)
            wins = float(wins or 0)
        except (TypeError, ValueError):
            played, wins = 0, 0
        venue_rate = (wins / played) if played > 0 else 0.50

        real_prob = (0.40 * form_rate) + (0.35 * h2h_rate) + (0.25 * venue_rate)
        
        # Generasi Rationale Bebas Bug
        rationale_parts = []
        if form_rate >= 0.6 and form_str != "N/A":
            rationale_parts.append(f"Performa 5 laga solid ({form_str})")
        if total_h2h > 0 and h2h_rate >= 0.5:
            rationale_parts.append(f"Dominasi H2H ({h2h_wins}/{total_h2h} menang)")
        if played > 0 and venue_rate >= 0.5:
            rationale_parts.append("Rekor laga kandang/tandang kuat")
            
        if not rationale_parts:
            rationale_parts.append("Tidak ada indikator statistik yang kuat")

        rationale = ", ".join(rationale_parts)

        return round(real_prob, 4), form_str, h2h_details, rationale

    def calculate_expected_value(self, odds: float, estimated_prob: float) -> float:
        net_profit = odds - 1.0
        prob_loss = 1.0 - estimated_prob
        return round((estimated_prob * net_profit) - (prob_loss * 1.0), 4)

    @staticmethod
    def _draw_rate_from_stats(team_stats: Dict) -> Optional[float]:
        recent_matches = team_stats.get("recent_matches", [])
        results = [
            str(match.get("result", "")).upper()
            for match in recent_matches
            if isinstance(match, dict) and match.get("result")
        ]
        if results:
            return results.count("D") / len(results)

        form = str(team_stats.get("form", "")).upper()
        if form:
            return form.count("D") / len(form)
        return None

    @staticmethod
    def _venue_rate(team_stats: Dict, venue: str, result: str) -> Optional[float]:
        fixtures = team_stats.get("fixtures", {})
        played = fixtures.get("played", {}).get(venue, 0)
        count = fixtures.get(result, {}).get(venue, 0)
        try:
            played, count = float(played or 0), float(count or 0)
        except (TypeError, ValueError):
            return None
        return count / played if played > 0 else None

    def estimate_draw_probability(
        self,
        home_stats: Dict,
        away_stats: Dict,
        h2h_matches: List[Dict],
    ) -> float:
        """Estimate a draw rate from each side's recent, H2H and venue records."""
        form_rates = [
            rate for rate in (
                self._draw_rate_from_stats(home_stats),
                self._draw_rate_from_stats(away_stats),
            )
            if rate is not None
        ]
        form_rate = sum(form_rates) / len(form_rates) if form_rates else 0.25

        h2h_results = []
        for match in (h2h_matches or [])[:5]:
            score = match.get("score", match.get("goals", {}))
            try:
                h2h_results.append(
                    int(score["home"]) == int(score["away"])
                )
            except (KeyError, TypeError, ValueError):
                continue
        h2h_rate = (
            sum(h2h_results) / len(h2h_results)
            if h2h_results else 0.25
        )

        venue_rates = [
            rate for rate in (
                self._venue_rate(home_stats, "home", "draws"),
                self._venue_rate(away_stats, "away", "draws"),
            )
            if rate is not None
        ]
        venue_rate = sum(venue_rates) / len(venue_rates) if venue_rates else 0.25
        return round(min(1.0, max(0.0, 0.40 * form_rate + 0.35 * h2h_rate + 0.25 * venue_rate)), 4)

    @staticmethod
    def _line_components(line: float) -> List[float]:
        """Split Asian quarter lines into their two half-unit stakes."""
        try:
            line = float(line)
        except (TypeError, ValueError):
            return []
        quarter_steps = round(line * 4)
        if not math.isfinite(line) or abs(line * 4 - quarter_steps) > 1e-6:
            return []
        if abs(line * 2 - round(line * 2)) <= 1e-6:
            return [line]
        return [math.floor(line * 2) / 2, math.ceil(line * 2) / 2]

    @classmethod
    def _settlement_return(
        cls,
        sample_value: float,
        odds: float,
        market_type: str,
        selection: str,
        line: float,
    ) -> Optional[float]:
        components = cls._line_components(line)
        if not components:
            return None

        returns = []
        for component in components:
            if market_type == "HDP":
                difference = sample_value + component
            elif selection == "over":
                difference = sample_value - component
            else:
                difference = component - sample_value

            if difference > 1e-9:
                returns.append(odds - 1.0)
            elif difference < -1e-9:
                returns.append(-1.0)
            else:
                returns.append(0.0)
        return sum(returns) / len(returns)

    @staticmethod
    def _history_key(match: Dict, is_h2h: bool = False):
        if is_h2h:
            teams = match.get("teams", {})
            home_id = teams.get("home", {}).get("id")
            away_id = teams.get("away", {}).get("id")
            date = match.get("date", "")
        else:
            home_id = match.get("home_id")
            away_id = match.get("away_id")
            date = match.get("utc_time", "")
        return (str(date)[:10], str(home_id), str(away_id))

    @staticmethod
    def _recent_score_values(team_stats: Dict, market_type: str) -> List[tuple]:
        values = []
        for match in team_stats.get("recent_matches", []):
            if not isinstance(match, dict):
                continue
            try:
                if market_type == "HDP":
                    value = float(match["team_goals"]) - float(match["opponent_goals"])
                else:
                    value = float(match["home_goals"]) + float(match["away_goals"])
            except (KeyError, TypeError, ValueError):
                continue
            values.append((ParlayFilterEngine._history_key(match), value))
        return values

    def estimate_line_market(
        self,
        odds_info: Dict,
        api_info: Dict,
        h2h_matches: List[Dict],
        odds: float,
    ) -> tuple:
        """Estimate handicap/total EV from recent score outcomes and H2H."""
        market_type = odds_info.get("market_type")
        selection = odds_info.get("selection")
        line = odds_info.get("market_line")
        try:
            line = float(line)
        except (TypeError, ValueError):
            return None, None, "Garis pasar tidak tersedia."

        if market_type == "HDP":
            side = odds_info.get("selection_side") or selection
            team_stats = api_info.get(f"{side}_stats", api_info.get("selected_stats", {}))
            recent_values = self._recent_score_values(team_stats or {}, "HDP")
            selected_team_id = api_info.get(f"{side}_id")
        else:
            recent_by_key = {}
            for side in ("home", "away"):
                for key, value in self._recent_score_values(
                    api_info.get(f"{side}_stats", {}) or {},
                    "O/U",
                ):
                    recent_by_key[key] = value
            recent_values = list(recent_by_key.items())
            selected_team_id = None

        h2h_values = []
        h2h_keys = set()
        for match in (h2h_matches or [])[:5]:
            teams = match.get("teams", {})
            score = match.get("score", match.get("goals", {}))
            try:
                home_goals = float(score["home"])
                away_goals = float(score["away"])
            except (KeyError, TypeError, ValueError):
                continue
            key = self._history_key(match, is_h2h=True)
            h2h_keys.add(key)

            if market_type == "HDP":
                home_id = teams.get("home", {}).get("id")
                away_id = teams.get("away", {}).get("id")
                if str(selected_team_id) == str(home_id):
                    h2h_values.append(home_goals - away_goals)
                elif str(selected_team_id) == str(away_id):
                    h2h_values.append(away_goals - home_goals)
            else:
                h2h_values.append(home_goals + away_goals)

        recent_values = [
            value for key, value in recent_values
            if key not in h2h_keys
        ]
        if len(recent_values) + len(h2h_values) < 3:
            return None, None, "Riwayat skor tidak cukup untuk estimasi pasar ini."

        recent_returns = [
            self._settlement_return(value, odds, market_type, selection, line)
            for value in recent_values
        ]
        recent_returns = [value for value in recent_returns if value is not None]
        h2h_returns = [
            self._settlement_return(value, odds, market_type, selection, line)
            for value in h2h_values
        ]
        h2h_returns = [value for value in h2h_returns if value is not None]
        if not recent_returns and not h2h_returns:
            return None, None, "Riwayat skor tidak dapat dihitung untuk garis ini."

        if recent_returns and h2h_returns:
            expected_return = (
                0.60 * (sum(recent_returns) / len(recent_returns))
                + 0.40 * (sum(h2h_returns) / len(h2h_returns))
            )
            positive_rate = (
                0.60 * (sum(value > 0 for value in recent_returns) / len(recent_returns))
                + 0.40 * (sum(value > 0 for value in h2h_returns) / len(h2h_returns))
            )
        elif recent_returns:
            expected_return = sum(recent_returns) / len(recent_returns)
            positive_rate = sum(value > 0 for value in recent_returns) / len(recent_returns)
        else:
            expected_return = sum(h2h_returns) / len(h2h_returns)
            positive_rate = sum(value > 0 for value in h2h_returns) / len(h2h_returns)

        sample_count = len(recent_returns) + len(h2h_returns)
        rationale = (
            f"EV {market_type} dihitung dari {len(recent_returns)} hasil tim "
            f"dan {len(h2h_returns)} hasil H2H (heuristik)."
        )
        return round(positive_rate, 4), round(expected_return, 4), rationale

    @staticmethod
    def _format_line(line: float) -> str:
        line = 0.0 if abs(line) < 1e-9 else line
        return f"{line:g}"

    def evaluate(self, matched_data: List[Dict]) -> List[Dict]:
        candidates = []

        for item in matched_data:
            odds_info = item.get('odds_data', {})
            api_info = item.get('api_data', {})
            
            odds_val = float(odds_info.get('odds_value', 0.0))
            if not (self.min_odds <= odds_val <= self.max_odds):
                continue

            h2h_data = api_info.get('h2h', [])
            market_type = odds_info.get("market_type", "1X2")
            selection = odds_info.get("selection")
            selection_side = odds_info.get("selection_side")
            pick_type = odds_info.get("pick_type", "Home Win")
            if selection is None:
                selection = (
                    "home" if pick_type == "Home Win"
                    else "away" if pick_type == "Away Win"
                    else "draw" if pick_type == "Draw"
                    else None
                )
            if selection_side is None and selection in {"home", "away"}:
                selection_side = selection

            selected_pick = odds_info.get('selected_pick')
            home_team = odds_info.get('home', api_info.get('home', 'Home Team'))
            away_team = odds_info.get('away', api_info.get('away', 'Away Team'))
            selected_team_id = (
                api_info.get(f"{selection_side}_id")
                if selection_side in {"home", "away"}
                else None
            )
            team_stats = api_info.get(
                f"{selection_side}_stats",
                api_info.get("selected_stats", api_info.get("stats", {})),
            ) if selection_side in {"home", "away"} else api_info.get("selected_stats", {})
            is_home_pick = selection_side == "home"

            if market_type == "HDP" or market_type == "O/U":
                estimated_real_prob, ev, rationale = self.estimate_line_market(
                    odds_info,
                    api_info,
                    h2h_data,
                    odds_val,
                )
                if ev is None:
                    continue
                if market_type == "HDP":
                    selected_team = home_team if selection_side == "home" else away_team
                    line_text = self._format_line(float(odds_info["market_line"]))
                    selected_pick = f"{selected_team} {float(odds_info['market_line']):+g}"
                    form_str = team_stats.get("form", "N/A") if isinstance(team_stats, dict) else "N/A"
                else:
                    line_text = self._format_line(float(odds_info["market_line"]))
                    selected_pick = f"{selection.title()} {line_text}"
                    home_form = api_info.get("home_stats", {}).get("form", "N/A")
                    away_form = api_info.get("away_stats", {}).get("form", "N/A")
                    form_str = f"H:{home_form} A:{away_form}"
                h2h_details = [
                    f"{match.get('teams', {}).get('home', {}).get('name', 'Home')} "
                    f"{match.get('score', {}).get('home', '?')}-"
                    f"{match.get('score', {}).get('away', '?')} "
                    f"{match.get('teams', {}).get('away', {}).get('name', 'Away')}"
                    for match in h2h_data[:5]
                ]
            elif market_type == "1X2" and selection == "draw":
                estimated_real_prob = self.estimate_draw_probability(
                    api_info.get("home_stats", {}),
                    api_info.get("away_stats", {}),
                    h2h_data,
                )
                ev = self.calculate_expected_value(odds_val, estimated_real_prob)
                rationale = "Estimasi draw dari form, H2H, dan rekor kandang/tandang."
                selected_pick = "Draw"
                form_str = (
                    f"H:{api_info.get('home_stats', {}).get('form', 'N/A')} "
                    f"A:{api_info.get('away_stats', {}).get('form', 'N/A')}"
                )
                h2h_details = [
                    f"{match.get('teams', {}).get('home', {}).get('name', 'Home')} "
                    f"{match.get('score', {}).get('home', '?')}-"
                    f"{match.get('score', {}).get('away', '?')} "
                    f"{match.get('teams', {}).get('away', {}).get('name', 'Away')}"
                    for match in h2h_data[:5]
                ]
            else:
                is_home_pick = selection_side == "home"
                selected_team_id = api_info.get("home_id" if is_home_pick else "away_id")
                team_stats = api_info.get(
                    "home_stats" if is_home_pick else "away_stats",
                    api_info.get("selected_stats", api_info.get("stats", {})),
                )
                estimated_real_prob, form_str, h2h_details, rationale = self.estimate_real_probability(
                    team_stats,
                    h2h_data,
                    is_home=is_home_pick,
                    team_id=selected_team_id,
                )
                ev = self.calculate_expected_value(odds_val, estimated_real_prob)
                if not selected_pick:
                    selected_pick = home_team if is_home_pick else away_team

            if not selected_pick:
                selected_pick = odds_info.get("selected_pick", "Unknown")

            implied_prob = self.calculate_implied_probability(odds_val)

            selection_label = odds_info.get("selection_label")
            if not selection_label:
                selection_label = (
                    "Draw" if selection == "draw"
                    else "Home Win" if selection == "home"
                    else "Away Win" if selection == "away"
                    else selection.title() if selection else pick_type
                )

            candidates.append({
                "match": f"{home_team} vs {away_team}",
                "pick": selected_pick,
                "pick_type": market_type,
                "market_type": market_type,
                "selection": selection,
                "selection_label": selection_label,
                "market_line": odds_info.get("market_line"),
                "selected_odds": odds_val,
                "implied_probability": f"{round(implied_prob * 100, 2)}%",
                "estimated_real_prob": f"{round(estimated_real_prob * 100, 2)}%",
                "expected_value_num": ev,
                "expected_value": f"{'+' if ev > 0 else ''}{round(ev * 100, 2)}%",
                "form_history": form_str,
                "h2h_history": h2h_details,
                "rationale": rationale,
                "league": api_info.get('league_name', api_info.get('league', 'Unknown League'))
            })

        candidates.sort(key=lambda x: x['expected_value_num'], reverse=True)
        return [c for c in candidates if c['expected_value_num'] >= self.min_ev]
