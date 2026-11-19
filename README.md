# Margin Copilot: evals

Margin Copilot evals: golden and adversarial test suites.

Part of **Margin Copilot**, a secure multi-agent pricing assistant on Azure, built as a personal learning project.

**Start here:** [margin-copilot/docs](https://github.com/margin-copilot/docs) explains how the whole system works and how the repos fit together.

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
