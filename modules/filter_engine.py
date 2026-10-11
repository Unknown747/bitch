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

    def evaluate(self, matched_data: List[Dict]) -> List[Dict]:
        candidates = []

        for item in matched_data:
            odds_info = item.get('odds_data', {})
            api_info = item.get('api_data', {})
            
            odds_val = float(odds_info.get('odds_value', 0.0))
            if not (self.min_odds <= odds_val <= self.max_odds):
                continue

            h2h_data = api_info.get('h2h', [])
            
            pick_type = odds_info.get('pick_type', 'Home Win')
            selected_pick = odds_info.get('selected_pick')
            is_home_pick = (pick_type == 'Home Win')
            selected_team_id = api_info.get('home_id' if is_home_pick else 'away_id')
            team_stats = api_info.get('selected_stats')
            if team_stats is None:
                team_stats = api_info.get(
                    'home_stats' if is_home_pick else 'away_stats',
                    api_info.get('stats', {}),
                )

            if not selected_pick:
                selected_pick = odds_info.get('home' if is_home_pick else 'away', api_info.get('home' if is_home_pick else 'away', 'Team'))

            estimated_real_prob, form_str, h2h_details, rationale = self.estimate_real_probability(
                team_stats,
                h2h_data,
                is_home=is_home_pick,
                team_id=selected_team_id,
            )
            implied_prob = self.calculate_implied_probability(odds_val)
            ev = self.calculate_expected_value(odds_val, estimated_real_prob)

            home_team = odds_info.get('home', api_info.get('home', 'Home Team'))
            away_team = odds_info.get('away', api_info.get('away', 'Away Team'))

            candidates.append({
                "match": f"{home_team} vs {away_team}",
                "pick": selected_pick,
                "pick_type": pick_type,
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
