# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["msal==1.39.0", "mssql-python==1.17.0"]
# ///
"""Milestone 3 live check: region security in Azure SQL, run on the laptop (D-019).

Reads evals/.env. The browser opens three times: sign in as north.mgr, then south.mgr, then
pricing.director. Each runs the same queries; only the rows they may see come back."""

import os
import pathlib
import struct
import sys
import time

import msal
import mssql_python

SCOPE = "https://database.windows.net/.default"
# The bundled macOS ODBC driver loads OpenSSL from Homebrew's unversioned link, which can point at
# OpenSSL 4 (unsupported); macOS reads DYLD_LIBRARY_PATH only at process start (data repo, sql.py).
OPENSSL3 = "/opt/homebrew/opt/openssl@3/lib"
USERS = ("north.mgr", "south.mgr", "pricing.director")
ROWS = {
    "north.mgr": {"N": 32_850},
    "south.mgr": {"S": 32_760},
    "pricing.director": {"C": 32_850, "N": 32_850, "S": 32_760},
}
PRICE_CHANGES = {"north.mgr": 1, "south.mgr": 1, "pricing.director": 4}
DAIRY_OCTOBER = {"C": 23.6, "N": 21.3, "S": 24.2}
QUERIES = {
    "rows": "SELECT region_id, COUNT(*) FROM dbo.fact_sales GROUP BY region_id",
    "price_changes": "SELECT COUNT(*) FROM dbo.price_history",
    "south_through_join": (
        "SELECT COUNT(*) FROM dbo.dim_store AS s "
        "JOIN dbo.fact_sales AS f ON f.store_id = s.store_id WHERE s.region_id = 'S'"
    ),
    "dairy_october": (
        "SELECT f.region_id, "
        "CAST(SUM(f.net_sales_mad - f.cogs_mad) * 100.0 / SUM(f.net_sales_mad) AS decimal(5, 1)) "
        "FROM dbo.fact_sales AS f JOIN dbo.dim_product AS p ON p.sku = f.sku "
        "WHERE p.category = 'Dairy' AND f.sale_date >= '2026-10-01' AND f.sale_date < '2026-11-01' "
        "GROUP BY f.region_id"
    ),
    "mapping": "SELECT COUNT(*) FROM rls.user_region",
}


def load_env(path: pathlib.Path) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs if not key.startswith("#")}


def sign_in(env: dict[str, str], expected: str) -> str:
    app = msal.PublicClientApplication(
        env["CLI_CLIENT_ID"], authority=f"https://login.microsoftonline.com/{env['TENANT_ID']}"
    )
    result = app.acquire_token_interactive([SCOPE], prompt="select_account")
    if "access_token" not in result:
        sys.exit(f"sign-in failed: {result.get('error')}: {result.get('error_description')}")
    alias = result["id_token_claims"]["preferred_username"].split("@")[0].lower()
    if alias != expected:
        sys.exit(f"signed in as {alias}, expected {expected}")
    return result["access_token"]


def connect(env: dict[str, str], token: str):
    mssql_python.pooling(enabled=False)
    raw = token.encode("utf-16-le")
    database = env.get("SQL_DATABASE", "riad")
    connection_string = f"Server=tcp:{env['SQL_SERVER']},1433;Database={database};Encrypt=yes"
    for delay in (5, 10, 20, 40, 60, 0):  # a paused free database answers 40613 while it wakes
        try:
            return mssql_python.connect(
                connection_string, attrs_before={1256: struct.pack(f"<I{len(raw)}s", len(raw), raw)}
            )
        except mssql_python.Error as error:
            if "40613" not in str(error) or not delay:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")


def fetch(cursor, query: str) -> list:
    cursor.execute(QUERIES[query])
    return cursor.fetchall()


def main() -> int:
    if (
        sys.platform == "darwin"
        and os.environ.get("DYLD_LIBRARY_PATH") != OPENSSL3
        and os.path.exists(f"{OPENSSL3}/libssl.3.dylib")
    ):
        os.execve(
            sys.executable,
            [sys.executable, *sys.argv],
            {**os.environ, "DYLD_LIBRARY_PATH": OPENSSL3},
        )
    env = load_env(pathlib.Path(__file__).resolve().parent.parent / ".env")
    results = []

    def check(name: str, passed: bool, detail: object) -> None:
        results.append(passed)
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")

    for user in USERS:
        connection = connect(env, sign_in(env, user))
        try:
            cursor = connection.cursor()

            visible = {region: count for region, count in fetch(cursor, "rows")}
            check(f"{user} sees only their rows", visible == ROWS[user], visible)
            changes = fetch(cursor, "price_changes")[0][0]
            check(f"{user} price changes", changes == PRICE_CHANGES[user], changes)
            if user != "pricing.director":
                through_join = fetch(cursor, "south_through_join")[0][0]
                expected_join = ROWS[user].get("S", 0)
                check(
                    f"{user} reaches South only if allowed",
                    through_join == expected_join,
                    through_join,
                )
            margins = {region: float(value) for region, value in fetch(cursor, "dairy_october")}
            expected = {region: DAIRY_OCTOBER[region] for region in ROWS[user]}
            check(f"{user} October dairy margin", margins == expected, margins)
            try:
                fetch(cursor, "mapping")
                check(f"{user} can't read rls.user_region", False, "query succeeded")
            except mssql_python.Error as error:
                check(f"{user} can't read rls.user_region", True, type(error).__name__)
        finally:
            connection.close()
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
