"""Rejects every pending proposal, as pricing.director: the test drafts that the live suite and
the approval check leave behind. Touches proposals only; prints only the count.
Run from the evals folder: `uv run live/clear_drafts.py`."""

import sys

import httpx

from margin_evals.live import TIMEOUT, load_env, sign_in


def main() -> int:
    env = load_env()
    base = env["PROPOSALS_API_URL"].rstrip("/")
    headers = {
        "Authorization": f"Bearer {sign_in(env, 'pricing.director', scope=env['PROPOSALS_SCOPE'])}"
    }
    listed = httpx.get(
        f"{base}/proposals", params={"status": "pending"}, headers=headers, timeout=TIMEOUT
    )
    listed.raise_for_status()
    rejected = failed = 0
    for proposal in listed.json()["proposals"]:
        url = f"{base}/proposals/{proposal['region']}/{proposal['id']}/reject"
        response = httpx.post(url, headers=headers, timeout=TIMEOUT)
        rejected, failed = (
            (rejected + 1, failed) if response.status_code == 200 else (rejected, failed + 1)
        )
    print(f"rejected {rejected} pending test drafts" + (f"; {failed} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
