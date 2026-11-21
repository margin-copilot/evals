"""Live approval check (milestone 6): no approval path without the right role and region.

Drafts two proposals through /chat, then calls proposals-api as each persona. Run from the evals
folder: `uv run live/proposals_check.py`. Settings come from evals/.env; sign-ins are silent after
the first time (the OS keychain keeps them)."""

import sys

import httpx

from margin_evals.live import TIMEOUT, chat, load_env, sign_in

UHT = "Draft a proposal to raise UHT milk 1 L in the North to 7.25 MAD."
OLIVE = "Draft a 7% increase for olive oil 1 L in the Center."
DRAFT = {"product": "UHT milk 1 L", "region": "N", "new_price": "7.25"}


def main() -> int:
    env = load_env()
    base, scope = env["PROPOSALS_API_URL"].rstrip("/"), env["PROPOSALS_SCOPE"]
    results: list[bool] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  ({detail})"))

    def api(persona: str, method: str, path: str, body: dict | None = None):
        token = sign_in(env, persona, scope=scope)
        response = httpx.request(
            method,
            f"{base}{path}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None

    def pending(persona: str) -> list[dict] | None:
        """The persona's pending list, or None when the call failed (a failure never passes)."""
        status, body = api(persona, "GET", "/proposals")
        if status != 200 or not isinstance(body, dict):
            return None
        return body.get("proposals", [])

    status, body = chat(env, sign_in(env, "north.mgr"), UHT)
    answer = (body or {}).get("answer", "")
    check("north.mgr drafts UHT milk through /chat", status == 200 and "pending" in answer, body)
    status, body = chat(env, sign_in(env, "center.mgr"), OLIVE)
    answer = (body or {}).get("answer", "")
    check(
        "center.mgr drafts olive oil (director-level)", status == 200 and "director" in answer, body
    )

    north = pending("north.mgr") or []  # newest first; empty fails the first check
    uht = next((p for p in north if p["sku"] == "DAI-002" and p["new_price"] == "7.25"), None)
    check(
        "north.mgr's list holds only North proposals",
        north and {p["region"] for p in north} == {"N"},
    )
    check("north.mgr's list holds the new UHT draft", uht is not None)
    south = pending("south.mgr")
    check(
        "south.mgr's list holds no North or Center proposal",
        south is not None and all(p["region"] == "S" for p in south),
        "the listing call failed" if south is None else south,
    )
    everything = pending("pricing.director") or []
    olive = next((p for p in everything if p["sku"] == "GRO-008" and p["region"] == "C"), None)
    ids = {p["id"] for p in everything}
    check(
        "the director's list holds both drafts", uht and olive and {uht["id"], olive["id"]} <= ids
    )

    status, body = api("north.mgr", "POST", "/drafts", DRAFT)
    check(
        "the CLI app can't create drafts",
        (status, body) == (403, {"error": "calling app not allowed"}),
        (status, body),
    )

    if uht:
        approve = f"/proposals/N/{uht['id']}/approve"
        status, body = api("south.mgr", "POST", approve)
        check(
            "south.mgr can't approve a North draft",
            (status, (body or {}).get("error")) == (403, "region not allowed"),
            (status, body),
        )
    if olive:
        status, body = api("center.mgr", "POST", f"/proposals/C/{olive['id']}/approve")
        check(
            "center.mgr can't approve a director-level draft",
            (status, (body or {}).get("error")) == (403, "needs the pricing director"),
            (status, body),
        )
    if uht:
        status, body = api("north.mgr", "POST", approve)
        check(
            "north.mgr approves the North draft",
            (status, (body or {}).get("status")) == (200, "approved"),
            (status, body),
        )
        status, body = api("north.mgr", "POST", approve)
        check(
            "a decided proposal can't be decided again",
            (status, (body or {}).get("error")) == (409, "already decided"),
            (status, body),
        )
    if olive:
        status, body = api("pricing.director", "POST", f"/proposals/C/{olive['id']}/approve")
        check(
            "the director approves the olive oil draft",
            (status, (body or {}).get("status")) == (200, "approved"),
            (status, body),
        )

    print(f"{sum(results)}/{len(results)} passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
