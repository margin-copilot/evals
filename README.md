# Margin Copilot: evals

Margin Copilot evals: golden and adversarial test suites.

Part of **Margin Copilot**, a secure multi-agent pricing assistant on Azure, built as a personal learning project.

**Start here:** [margin-copilot/docs](https://github.com/margin-copilot/docs) explains how the whole system works and how the repos fit together.

## The eval suite (CI, fake adapters)

Cases live in `cases/*.toml`: golden and scope questions from the planted data stories and the policies, plus adversarial ones. Each case names a persona (`cases/personas.toml`, matching the Entra test users), a question and what a good response looks like:
- the status;
- text that must or must not appear (`a|b` accepts either);
- a refusal kind: `out_of_scope`, `no_access` or `no_data`;
- the agents called;
- the citations.

The harness builds the system in one process: orchestrator → A2A → data-agent, with fake outbound adapters and locally signed tokens. No Azure, no network. Cases marked `suite = "live"` are skipped here and run in the live suite below. `milestone` is the first milestone where a case must pass:
- **Done milestones:** cases up to `CURRENT_MILESTONE` (`src/margin_evals/__init__.py`) must pass.
- **Later milestones:** later cases must fail, and only with `CaseFailed`, meaning the system answered differently from what the case expects.
- **Crashes and early passes:** a crash fails CI, and so does a 5xx where a case expects an answer (`SystemFault`).
  A case that starts passing early fails CI too; promote it by finishing its milestone and bumping `CURRENT_MILESTONE`.
- **Matching:** numbers match whole: `0%` isn't found in `30%`.
- **Forbidden agents:** `not_agents` lists agents that must not be called.
- **Missing fields:** a missing `agents` or `citations` field fails any case that checks it.
- **Error reasons:** `expect.error` checks the reason on error responses.

```bash
uv sync
uv run pytest -q -rxX
```

Why it works this way, and the response fields the cases expect: D-029 in the [docs repo](https://github.com/margin-copilot/docs/blob/main/decisions.md).

## The live suite and checks (run on a laptop)

Cases with `suite = "live"` need the real model and data, so CI skips them (D-033). They run against the deployed system after an interactive browser sign-in per test user (D-019). Device code flow is blocked in new tenants.

```bash
../infra/scripts/spike-env.sh > .env                                  # private infra repo
grep -E '^SQL_(SERVER|DATABASE)=' ../data/.env >> .env                # for rls_check.py
uv run live/run_cases.py --milestone 4    # live cases up to milestone 4; prints every answer
uv run live/ask.py north.mgr "What was dairy margin in the North in October 2026?"
```

`run_cases.py` judges each answer like CI does. Each test user signs in through the browser once (the terminal names the user to pick); the tokens are then kept encrypted in the OS keychain (macOS: the Keychain item `msal-extensions`; forget them with `security delete-generic-password -s msal-extensions`), so later runs are silent. `ask.py` asks one question as one user and prints the answer, the refusal and the agents called.

`identity_hop.py` (milestone 1) checks four things:
- A signed-in test user's question crosses the orchestrator → data-agent A2A hop.
- A token from an app that isn't on the allow-list gets 403.
- A locally signed token gets 401.
- The data-agent can't be reached from the internet.

`rls_check.py` (milestone 3) signs in as north.mgr, south.mgr and pricing.director and runs the same SQL against the Azure SQL database for each. It checks that:
- each user gets only their region's rows, also through joins and in `price_history`;
- October's dairy margins are on target;
- no test user can read `rls.user_region`.

```bash
uv run live/identity_hop.py
uv run live/rls_check.py
```

## License

MIT. See [LICENSE](LICENSE).
