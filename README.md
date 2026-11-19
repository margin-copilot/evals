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

The harness builds the system in one process: orchestrator → A2A → data-agent, with fake outbound adapters and locally signed tokens. No Azure, no network. `milestone` is the first milestone where a case must pass:
- **Done milestones:** cases up to `CURRENT_MILESTONE` (`src/margin_evals/__init__.py`) must pass.
- **Later milestones:** later cases must fail, and only with `CaseFailed`, meaning the system answered differently from what the case expects.
- **Crashes and early passes:** a crash fails CI, and so does a 5xx where a case expects an answer (`SystemFault`).
  A case that starts passing early fails CI too; promote it by finishing its milestone and bumping `CURRENT_MILESTONE`.
- **Matching:** numbers match whole: `0%` isn't found in `30%`.
- **Forbidden agents:** `not_agents` lists agents that must not be called.

```bash
uv sync
uv run pytest -q -rxX
```

Why it works this way, and the response fields the cases expect: D-029 in the [docs repo](https://github.com/margin-copilot/docs/blob/main/decisions.md).

## Live checks (run on a laptop)

The live suite runs against real Azure after an interactive browser sign-in per test user (D-019 in the docs repo). Device code flow is blocked in new tenants.

```bash
cp .env.example .env     # or: ../infra/scripts/spike-env.sh > .env (private infra repo)
uv run live/identity_hop.py
```

`identity_hop.py` (milestone 1) checks four things:
- A signed-in test user crosses the orchestrator → data-agent A2A hop, and the data-agent's tool reaches Microsoft Graph as that user.
- A token from an app that isn't on the allow-list gets 403.
- A locally signed token gets 401.
- The data-agent can't be reached from the internet.

CI suites on fake adapters arrive in milestone 2.

## License

MIT. See [LICENSE](LICENSE).
