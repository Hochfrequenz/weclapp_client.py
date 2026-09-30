# weclapp-client

![Unittests status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Unittests/badge.svg)
![Coverage status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Coverage/badge.svg)
![Linting status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Linting/badge.svg)
![Formatting status badge](https://github.com/Hochfrequenz/weclapp_client.py/workflows/Formatting/badge.svg)

A typed Python client for the [weclapp REST API v2](https://www.weclapp.com/api/).
It deliberately covers only the endpoints needed to synchronise employee master data into weclapp:
`/user`, `/employee`, `/customAttributeDefinition` and `/user/currentUser`.

The synchronisation logic itself (matching, diffing, reporting) lives in a separate repository that uses this package
as a dependency.

> **Status:** under development, see the [implementation plan](docs/umsetzungsplan.md) (German).
> The [API analysis](docs/weclapp_api_analyse.md) (German) explains which endpoints are relevant and why.

## Installation

The package is not released yet. Once it is, install it from PyPI:

```bash
uv add weclapp-client
```

## Development

This project uses [uv](https://docs.astral.sh/uv/) to manage the Python interpreter, the virtual environment and the
dependencies. Create the dev environment with:

```bash
uv sync --group dev
```

The checks that run in CI:

```bash
uv run pytest
uv run ruff check src/weclapp_client unittests
uv run ruff format --check .
uv run mypy --show-error-codes src/weclapp_client --strict
uv run mypy --show-error-codes unittests --strict
uv run codespell --ignore-words=domain-specific-terms.txt src README.md
```

## Releasing

Versions are derived from git tags (`v0.1.0`, `v0.1.0a1`, ...) via hatch-vcs.
Publishing to PyPI uses trusted publishing via [`.github/workflows/python-publish.yml`](.github/workflows/python-publish.yml),
which still needs to be activated:

1. Uncomment the workflow.
2. Create a GitHub environment named `release`. If its deployment branches are restricted, add a rule of type *Tag*
   matching `v*`, because a release deploys from the tag, not from a branch.
3. Register the trusted publisher on PyPI (project `weclapp-client`, owner `Hochfrequenz`,
   repository `weclapp_client.py`, workflow `python-publish.yml`, environment `release`).
4. Create a GitHub release with a `v*` tag.
