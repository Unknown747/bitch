import asyncio
from datetime import datetime
import sys
import zoneinfo

from config import (
    MIN_ODDS, 
    MAX_ODDS, 
    MIN_EXPECTED_VALUE, 
    TIME_WINDOW_MINUTES, 
    FUZZY_THRESHOLD
)
from modules.scraper import ParlayScraper
from modules.fotmob import FotMobClient, FotMobClientError
from modules.matcher import EntityMatcher
from modules.filter_engine import ParlayFilterEngine
from modules.slip_writer import write_result_slip


TOP_5_EUROPEAN_LEAGUES = {
    47: "Premier League",
    87: "LaLiga",
    55: "Serie A",
    54: "Bundesliga",
    53: "Ligue 1",
}


def _save_slip(picks, reason=None):
    slip_path = write_result_slip(picks, reason=reason)
    print(f"  └─ Result slip saved: {slip_path}")
    return slip_path


async def run_pipeline():
    print("==================================================")
    print("🚀 STARTING MIX PARLAY DETAILED DEBUG PIPELINE")
    print("==================================================")

    # STEP 1: SCRAPING ODDS
    print("\n[STEP 1/4] Scraping Odds dari mainbolakaki.pro...")
    scraper = ParlayScraper()
    odds_data = await scraper.fetch_odds_data()
    print(f"  └─ Total Scraped Matches: {len(odds_data)}")

    if not odds_data:
        print("  ❌ [ABORT] Tidak ada data odds yang di-scrape. Pipeline dihentikan.")
        _save_slip([], reason="Tidak ada data odds yang berhasil diambil.")
        return []

    # STEP 2: FETCH API FIXTURES
    print("\n[STEP 2/4] Fetching FotMob Fixtures...")
    wib_tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    today_str = datetime.now(wib_tz).strftime("%Y-%m-%d")
    print(f"  └─ Target Date (WIB): {today_str}")

    fotmob_client = FotMobClient()
    all_fotmob_fixtures = fotmob_client.get_fixtures_by_date(today_str)
    fotmob_fixtures = [
        fixture for fixture in all_fotmob_fixtures
        if int(fixture.get('league_id') or 0) in TOP_5_EUROPEAN_LEAGUES
    ]
    print(
        f"  └─ Top 5 European Fixtures: {len(fotmob_fixtures)} "
        f"of {len(all_fotmob_fixtures)} total FotMob fixtures"
    )

    if not fotmob_fixtures:
        print("  ❌ [ABORT] Tidak ada fixture Top 5 Eropa dari FotMob.")
        _save_slip([], reason="Tidak ada fixture Top 5 Eropa untuk tanggal ini.")
        return []

    # STEP 3: ENTITY MATCHING
    print("\n[STEP 3/4] Matching Scraped Teams with FotMob Entities...")
    matcher = EntityMatcher(time_window_minutes=TIME_WINDOW_MINUTES, threshold=FUZZY_THRESHOLD)
    matched_results = matcher.match(odds_data, fotmob_fixtures)
    print(f"  └─ Total Successfully Matched Fixtures: {len(matched_results)}")

    if not matched_results:
        print("  ❌ [ABORT] Tidak ada pertandingan yang berhasil dicocokkan.")
        _save_slip([], reason="Tidak ada pertandingan Top 5 Eropa yang berhasil dicocokkan.")
        return []

    # STEP 4: API INGESTION & EVALUATION
    print("\n[STEP 4/4] Ingesting Form & H2H from FotMob...")
    filtered_matched = []
    
    for idx, item in enumerate(matched_results, 1):
        odds_val = float(item['odds_data'].get('odds_value', 0.0))
        home_team = item['odds_data'].get('home')
        away_team = item['odds_data'].get('away')

        if not (MIN_ODDS <= odds_val <= MAX_ODDS):
            continue

        api_item = item['api_data']
        home_id = api_item.get('home_id')
        away_id = api_item.get('away_id')
        league_id = api_item.get('league_id')

        print(f"  ► Processing [{idx}/{len(matched_results)}] {home_team} vs {away_team} (Odds: {odds_val})")

        # Ingest H2H
        h2h_data = []
        if home_id and away_id:
            h2h_data = fotmob_client.get_h2h_matches(
                fixture_id=api_item.get('fixture_id'),
                last_n=5,
            )
            print(f"     └─ H2H Matches Found: {len(h2h_data)}")

        item['api_data']['h2h'] = h2h_data

        # Ambil statistik tim yang dipilih saja agar tidak menggandakan pemakaian kuota API.
        pick_type = item['odds_data'].get('pick_type', 'Home Win')
        selected_team_id = home_id if pick_type == 'Home Win' else away_id
        selected_stats = {}
        if selected_team_id and league_id:
            selected_stats = fotmob_client.get_team_statistics(
                team_id=selected_team_id,
                league_id=league_id,
            )
        print(f"     └─ Selected Team Stats Fetched: Form='{selected_stats.get('form', 'N/A')}'")

        item['api_data']['selected_stats'] = selected_stats
        filtered_matched.append(item)

    print(f"\n  └─ Total Matches Passed to EV Evaluator: {len(filtered_matched)}")

    # EVALUATE
    print("\n[EVALUATION] Estimasi probabilitas heuristik & EV (belum divalidasi historis)...")
    filter_engine = ParlayFilterEngine(min_odds=MIN_ODDS, max_odds=MAX_ODDS, min_ev=MIN_EXPECTED_VALUE)
    final_picks = filter_engine.evaluate(filtered_matched)

    print("\n==================================================")
    print(f"🎯 FINAL EVALUATION RESULTS ({len(final_picks)} PICKS):")
    print("==================================================")

    for idx, pick in enumerate(final_picks, 1):
        print(f"  {idx}. {pick['match']} | PASANG: {pick['pick']} ({pick['pick_type']}) | Odds: {pick['selected_odds']} | EV: {pick['expected_value']}")

    if final_picks:
        _save_slip(final_picks)
    else:
        _save_slip(
            [],
            reason=(
                "Tidak ada pilihan yang memenuhi batas minimum EV "
                f"{MIN_EXPECTED_VALUE * 100:.2f}%. Batas EV tidak diturunkan otomatis."
            ),
        )

    print("\n✅ PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
    return final_picks


if __name__ == "__main__":
    try:
        asyncio.run(run_pipeline())
    except FotMobClientError as exc:
        print(f"\n❌ FotMob request failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
