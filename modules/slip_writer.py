from datetime import datetime
from pathlib import Path
import zoneinfo


def write_result_slip(picks, reason=None, output_dir="data/slips") -> Path:
    generated_at = datetime.now(zoneinfo.ZoneInfo("Asia/Jakarta"))
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    slip_path = output_path / f"result-slip-{generated_at:%Y%m%d-%H%M%S-%f}.txt"

    lines = [
        "FOOTBALL RESULT SLIP",
        f"Generated: {generated_at:%Y-%m-%d %H:%M:%S} WIB",
        f"Qualifying picks: {len(picks)}",
        "",
    ]

    if not picks:
        lines.extend([
            "STATUS: NO QUALIFYING PICKS",
            reason or "Tidak ada pilihan yang memenuhi kriteria.",
        ])
    else:
        lines.append("STATUS: READY")
        for index, pick in enumerate(picks, start=1):
            lines.extend([
                f"{index}. {pick.get('match', 'Unknown match')}",
                f"   Pick: {pick.get('pick', 'Unknown')} ({pick.get('pick_type', 'Unknown')})",
                f"   Odds: {pick.get('selected_odds', 'N/A')}",
                f"   Expected value: {pick.get('expected_value', 'N/A')}",
                f"   Estimated probability: {pick.get('estimated_real_prob', 'N/A')}",
                f"   Form: {pick.get('form_history', 'N/A')}",
                f"   Rationale: {pick.get('rationale', 'N/A')}",
            ])
            h2h_history = pick.get("h2h_history", [])
            if h2h_history:
                lines.append("   H2H:")
                lines.extend(f"     - {entry}" for entry in h2h_history)
            lines.append("")

    slip_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return slip_path
