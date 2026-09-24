# Contributing to Lithops

Thanks for your interest in improving Lithops! This guide explains how to get help, report
problems, set up a development environment, and get a change merged.

## Questions, bugs and ideas

- **Questions and ideas:** use [GitHub Discussions](https://github.com/lithops-cloud/lithops/discussions)
  for usage questions, design discussions and feature ideas.
- **Bugs:** open a [GitHub issue](https://github.com/lithops-cloud/lithops/issues) with the bug
  template. Include the Lithops version (`lithops --version`), the compute and storage
  backends, a minimal script that reproduces the problem and the full traceback (ideally with
  `log_level: DEBUG`). Remove credentials and account IDs from any configuration you paste.
- **Larger changes** (new backends, API changes, changes to the execution flow): open an issue
  or discussion first, so we can agree on the approach before you write the code.
- **Security issues:** do **not** open a public issue, see [SECURITY.md](SECURITY.md).

## Development setup

```bash
git clone https://github.com/<your-user>/lithops && cd lithops    # your fork
python3 -m venv .venv && source .venv/bin/activate                  # optional, recommended
pip3 install -e '.[tests,dev]'      # editable install + test deps + ruff and pre-commit
pip3 install -e '.[aws]'            # add the extras of the backends you work on
                                    # (aws, gcp, azure, ibm, aliyun, oracle, ... or all)
pre-commit install                  # optional: run ruff on every commit
```

The localhost backend needs no cloud account and no configuration, so it is all you need for
most changes. To work on a cloud backend, configure it as described in the
[configuration guide](config/README.md).

## Running the tests

The tests live in `lithops/tests/` and are run from that folder:

```bash
cd lithops/tests
pytest -v --timeout=120 --timeout-method=thread --backend localhost --storage localhost
```

Always pass `--backend` and `--storage`: without them the tests use your own Lithops
configuration (`~/.lithops/config`, `.lithops_config` or `LITHOPS_CONFIG_FILE`) and run
against the cloud account it points to. Some tests need a Redis server on `localhost:6379`
(for example `docker run -d -p 6379:6379 redis:7`) and are skipped when none is reachable.

Other useful invocations:

```bash
pytest -v --backend localhost --storage localhost -k test_map    # a test or group of tests
pytest --collect-only                                            # list all the tests
pytest -o log_cli=true --log-cli-level=DEBUG --backend localhost --storage localhost   # with logs
```

If you change a specific backend, also run the tests on that backend, for example:

```bash
pytest -v --backend aws_lambda --storage aws_s3
pytest -v --config /path/to/config.yaml --backend code_engine --storage ibm_cos --region eu-de
```

CI runs the localhost suite on Python 3.10 - 3.14 for every pull request; cloud backends are
not exercised in CI, so mention in your pull request which backend you tested on.

## Code conventions

- **Linting:** `ruff check .` must pass (`ruff check --fix .` fixes what it can). The
  configuration (rules, line length 120) is in `pyproject.toml`; CI runs the same check.
- **Style:** follow the style of the surrounding code. The editor settings are in
  `.editorconfig`. Do not run `ruff format`: the code base is not formatted with it.
- **Dependencies:** package metadata, dependencies and extras are declared in
  `pyproject.toml`. A dependency added to an extra also goes into the `all` extra.
- **Tests:** every bug fix comes with a regression test, and every feature with tests of its
  behaviour. Tests must pass on the localhost backend; code that only runs in a cloud
  backend is tested with fakes or mocks.
- **Backends:** backend-specific code stays in its package (`lithops/serverless/backends/`,
  `lithops/standalone/backends/`, `lithops/storage/backends/`). Import the provider SDKs
  there, not in the core modules, so Lithops keeps working without the extras installed.
- **Configuration keys:** document new or changed keys in `config/config_template.yaml` and
  in the backend's page under `docs/source/compute_config/` or `docs/source/storage_config/`
  (general `lithops` keys in `docs/source/lithops_config_keys.csv`).
- **Public API:** keep `FunctionExecutor`, `Storage`, futures and the `multiprocessing` /
  `concurrent.futures` APIs backwards compatible, or discuss the change in an issue first.

## Documentation

The documentation is written in reStructuredText and Markdown under `docs/` and built with
Sphinx; see [docs/README.md](docs/README.md) for how to build it locally. Update it together
with any user-visible change.

## Changelog

Add an entry for every user-visible change to [CHANGELOG.md](CHANGELOG.md), under the topmost
(development) version, in the *Added*, *Changed*, *Fixed* or *Removed* section, prefixed with
the component:

```markdown
### Fixed
- [AWS Lambda] Short description of the fix.
```

## Pull requests

1. Break your work into small, single-purpose pull requests. A large change with many
   unrelated parts is much harder to review and merge.
2. Open the pull request against the `master` branch and fill in the template: what changed,
   why, and how you tested it.
3. Make sure ruff and the localhost tests pass, and that tests, docs and the changelog are
   updated.
4. By opening a pull request you certify the Developer's Certificate of Origin included in the
   pull request template.

## Releasing (maintainers)

Releases are made by the [Release workflow](.github/workflows/release.yml): *Actions* ->
*Release* -> *Run workflow*, with the version to release (e.g. `3.7.1`). Before running it,
review the development section at the top of `CHANGELOG.md`, which becomes the release notes.
The workflow sets the version, tags it, publishes the sdist and wheel to PyPI, creates the
GitHub release, publishes the docs to the website repository and bumps `master` to the next
development version. Check *dry run* to build and check a release without pushing or
publishing anything. To republish the docs without a release, run the *Publish docs* workflow:
it builds `master` and publishes it as the docs of the latest release.

## AI coding agents

Instructions for AI coding agents (Claude Code, Codex, Copilot, Cursor, ...) are in
[AGENTS.md](AGENTS.md). Contributions made with their help follow the same rules as any other:
you are responsible for reviewing, testing and understanding the code you submit.

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
