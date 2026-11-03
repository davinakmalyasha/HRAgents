# Release Process

**Status:** active · applies from the first public release.

## Versioning

Semantic Versioning (`MAJOR.MINOR.PATCH`). Pre-1.0, the API may change in a MINOR
release; breaking changes are always called out in the changelog.

- The version lives in `pyproject.toml` (single source); code reads it via
  `importlib.metadata`.
- API paths are versioned (`/v1`). Breaking an endpoint means `/v2`, never a silent
  change.
- Database migrations are append-only. Applied revisions are never edited; schema
  changes use expand/contract so old and new code can run during an upgrade.
- Docs travel with `main`; release notes link the tag's commit range.

## Branching

Trunk-based development:

| Branch | Purpose |
|---|---|
| `main` | Always green, always releasable. Protected: PR + CI required, linear history |
| `feat/…`, `fix/…`, `docs/…`, `chore/…` | Short-lived work branches, squash-merged |
| `fix/<version>` from a tag | Only for a hotfix when `main` has moved on |

Contributors fork and open PRs; they never push to `main`.

## Commits → releases

Commits follow [Conventional Commits](https://www.conventionalcommits.org/). The
`release-please` workflow runs on every push to `main`:

| Commit | Release effect |
|---|---|
| `fix:` | patch release |
| `feat:` | minor release |
| `feat!:` / `BREAKING CHANGE:` | major release (minor pre-1.0, called out in notes) |
| `docs:`, `chore:`, `test:`, `ci:` | hidden from the changelog, no release on their own |

release-please keeps an open release PR that accumulates changes and updates
`CHANGELOG.md` and `pyproject.toml`. Merging it creates the `vX.Y.Z` tag and GitHub
Release.

## Cutting a release

1. Merge the release PR (review the generated changelog — edit the PR if needed).
2. `release-please` tags and publishes the GitHub Release.
3. Because `release-please` publishes with `GITHUB_TOKEN` (whose events do not start
   workflows), dispatch the three post-release workflows for the tag:
   - `Release artifacts` — builds the sdist and wheel (`twine check` validated)
   - `Release image` — builds/scans the multi-arch image before pushing, and attaches
     the SARIF + SPDX SBOM; provenance and the SBOM are attached to the image digest
   - `Docs` with the version input — publishes that version and moves `latest`
4. Announce in Discussions; update the README status if the release changes it.

## Hotfixes

1. Branch `fix/<version>` from the released tag; make the minimal fix plus a test.
2. Open a PR to `main` as usual; note the target version in the PR description.
3. After merge, release-please proposes the patch release; merge it, then
   `git cherry-pick` the fix commit onto the `fix/<version>` branch if a maintenance
   branch is being supported (pre-1.0: usually not).

## Artifacts and channels

| Artifact | Status |
|---|---|
| sdist + wheel on the GitHub Release | active (workflow `release.yml`) |
| Container image on GHCR (multi-arch, Trivy-gated) | active (`image.yml`; 0.2.0 onward) |
| SPDX SBOM + Trivy SARIF on the release | active; SBOM and max-mode provenance also on the image digest |
| Versioned docs (`mike`) | active (`docs.yml`; `latest` plus each release) |
| PyPI package | deferred — the product is a server, not a library |

## Reproducible from the tag

The artifacts are built from the tagged commit with locked inputs:

```bash
git checkout hr-agents-vX.Y.Z
uv sync --locked
uv build                 # sdist + wheel
uvx twine check dist/*
```

The image is built by `image.yml` from the same ref with pinned base images and
pinned actions; the pushed digest is recorded by BuildKit provenance. A rebuild
on the same tag should produce the same Python artifacts; the container layers
may differ if a base image is re-tagged, which the release notes should say if
it matters.

## Pre-release checklist

- [ ] CI green: quality, migrations, postgres-adapters, windows, secrets, web, landing, CodeQL
- [ ] `CHANGELOG.md` reviewed and human-edited if the generated notes miss nuance
- [ ] `docs/plan/master-build-plan.md` status table matches reality
- [ ] Upgrade notes written for any migration or config change
- [ ] README quickstart still works from a clean clone
