# AGENTS.md

Instructions for AI coding agents working in this repository (OpenAI Codex, GitHub Copilot
coding agent, Cursor, Gemini CLI, Aider, Claude Code and others). Human contributors should
read [CONTRIBUTING.md](CONTRIBUTING.md); this file summarizes the same rules plus the
architectural context an agent needs.

## Project overview

Lithops is a Python framework that runs unmodified Python functions at scale on serverless
platforms, container and batch services, virtual machines and the local machine, behind one
small API (`FunctionExecutor.call_async()`, `map()`, `map_reduce()`, `wait()`,
`get_result()`, `Storage`). The architecture is described in
[docs/source/design.rst](docs/source/design.rst); read it before changing core code.

- **Client:** where `import lithops` runs. Builds jobs, serializes code and data, invokes the
  workers and collects results. All orchestration lives here.
- **Compute backend:** where the workers run, one call each.
- **Object storage:** the only communication bus between client and workers. The client
  writes the pickled function and data; workers read their input and write their output and
  status back. There are no direct client-worker connections.

## Setup and commands

```bash
pip3 install -e '.[tests,dev]'             # editable install + test deps + ruff / pre-commit
                                           # (backend extras: '.[aws]', '.[gcp]', '.[all]', ...)
ruff check .                               # lint; must pass (config in pyproject.toml, line length 120)

cd lithops/tests
pytest -v --timeout=120 --timeout-method=thread --backend localhost --storage localhost
pytest -v --backend localhost --storage localhost -k test_map    # a subset
pytest --collect-only                                            # list the tests
```

**Always pass `--backend localhost --storage localhost`.** Without them the test session
loads the developer's own configuration (`~/.lithops/config`, `.lithops_config`,
`LITHOPS_CONFIG_FILE`) and runs against whatever cloud account it points to. Some tests need a
Redis server on `localhost:6379` and skip themselves when none is reachable.

Documentation is built with Sphinx from `docs/` (`pip3 install -e '.[docs]'`, then
`make -C docs html SPHINXOPTS="-W --keep-going"`, see [docs/README.md](docs/README.md)). Pull
requests that touch the docs must build without warnings: CI runs that same command.

## Repository map

| Path | Content |
|---|---|
| `lithops/__init__.py` | Public API surface (`FunctionExecutor`, `Storage`, `wait`, `get_result`, ...) |
| `lithops/executors.py` | `FunctionExecutor` and `LocalhostExecutor` / `ServerlessExecutor` / `StandaloneExecutor` |
| `lithops/config.py` | Loads and merges configuration (dict, env vars, YAML), validates backends |
| `lithops/job/` | Job creation, function/module serialization (`cloudpickle`), data partitioning |
| `lithops/invokers.py` | `FaaSInvoker` (per-call invocations) and `BatchInvoker` (one submission, many tasks) |
| `lithops/future.py`, `wait.py`, `retries.py` | `ResponseFuture`, `wait()` / `get_result()`, `RetryingFunctionExecutor` |
| `lithops/worker/` | Code that runs on the compute backend: `handler.py` (`function_handler`) and `jobrunner.py` (`JobRunner`) |
| `lithops/serverless/backends/<name>/` | Serverless / batch compute backends (`<name>.py`, `config.py`, `entry_point.py`) |
| `lithops/standalone/` | Standalone mode: master / worker VMs coordinated through Redis; `backends/<name>/` for VM providers |
| `lithops/localhost/` | Localhost compute backend (`v1`, `v2`) |
| `lithops/storage/` | `Storage` / `InternalStorage`, cloud file APIs; `backends/<name>/` for object stores |
| `lithops/monitoring/` | Job monitor and its pluggable backends (storage polling, RabbitMQ, Redis, queues) |
| `lithops/telemetry/` | Prometheus / OpenTelemetry metrics (off by default) |
| `lithops/multiprocessing/`, `concurrent/`, `util/joblib/` | Drop-in `multiprocessing`, `concurrent.futures` and joblib APIs |
| `lithops/scripts/` | `lithops` CLI (`cli.py`) and the temporary-data cleaner |
| `lithops/tests/` | pytest suite (`conftest.py` defines `--backend`, `--storage`, `--config`, `--region`) |
| `runtime/<backend>/` | Dockerfiles and instructions to build runtimes for each backend |
| `config/` | `config_template.yaml` (every configuration key) and the configuration guide |
| `docs/` | Sphinx documentation; `docs/source/compute_config/` and `storage_config/` per backend |
| `examples/` | Single-file usage examples |

## Architectural invariants

1. **Storage is the bus.** Workers receive their input and return their results and status
   through object storage (`func_key`, `agg_data`, `output_key`, `status_key`), never through
   a direct connection to the client.
2. **Every backend looks the same to the core.** Backend-specific code stays in its backend
   package; the executor, invoker, job and worker code must not special-case a backend by
   name when an interface method or a config value can express it.
3. **The worker must tolerate the environment it runs in.** Worker code runs in minimal
   runtimes (Lambda, containers, VMs, macOS/Windows localhost). Imports of optional
   dependencies stay lazy, and a failure in the user's function is reported in its status
   rather than crashing the worker.
4. **Configuration keys are documented where users look for them.** A new or changed key goes
   into `config/config_template.yaml` and the backend's page in `docs/source/compute_config/`
   or `docs/source/storage_config/` (general `lithops` keys also in
   `docs/source/lithops_config_keys.csv`).
5. **Public API compatibility.** `FunctionExecutor`, `Storage`, futures and the
   `multiprocessing` / `concurrent.futures` layers are used by existing programs; do not
   change signatures or defaults without a deprecation path and a CHANGELOG entry.

## Conventions

- Python 3.10 - 3.14 (the versions CI tests). Match the style of the surrounding code;
  `ruff check .` clean with line length 120. Do not run `ruff format`: the code base is not
  formatted with it and it would rewrite almost every file.
- Package metadata, dependencies and extras live in `pyproject.toml`. When adding a
  dependency to an extra, also add it to the `all` extra (except the `dev` and `docs` tooling
  extras).
- Every bug fix includes a regression test; every feature includes tests of its behaviour.
  Tests must run on the localhost backend and storage; backend-specific code that cannot be
  exercised locally is tested with fakes or mocks.
- Functional changes (API, backends, behaviour, bug fixes in the library) go into
  `CHANGELOG.md` under the topmost (development) version heading, in the *Added / Changed /
  Fixed / Removed* section, prefixed with the component, e.g. `- [Monitoring] ...`. Docs
  fixes, packaging metadata and repository tooling (CI, templates, agent files) get no entry:
  that section becomes the release notes. Entries describe the difference from the latest
  release, not the history of the development cycle: a fix or change to something added since
  that release updates its existing `Added` entry instead of adding a `Fixed` or `Changed` one,
  and something added and removed again before a release has no entry. Update `docs/` and
  `README.md` when behaviour changes.
- `CONTRIBUTING.md` and `docs/source/contributing.rst` carry the same content: change both.
- Pull requests target `master`. Keep changes small and focused; do not refactor unrelated
  code.

## Safety

- Do not run tests, examples or `lithops` CLI commands against real cloud backends (AWS, GCP,
  Azure, IBM Cloud, Aliyun, Oracle, Kubernetes clusters) and do not build or push runtime
  images without the maintainer's explicit approval: it creates billable resources and uses
  real credentials.
- Never commit credentials or configuration files (`~/.lithops/config`, `.lithops_config`).
- Do not commit or push unless asked to.
