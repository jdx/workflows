# workflows

Reusable GitHub Actions workflows shared by jdx repositories.

| Workflow | Purpose |
| --- | --- |
| `.github/workflows/draft-limit.yml` | Closes a draft pull request when its author already has another open draft |

Each workflow's header comment shows the caller setup.

## Releases

The workflows are released as `vX.Y.Z` tags, and callers pin the tag's commit
with the version as a comment:

```yaml
uses: jdx/workflows/.github/workflows/draft-limit.yml@<sha> # v1.0.0
```

Don't pin with a `# main` comment. zizmor's `ref-version-mismatch` audit
fails every caller as soon as `main` moves past the pinned commit. Renovate
bumps pinned tags like any other action.

Releases follow the same flow as
[renovate-config](https://github.com/jdx/renovate-config). On every push to
`main`, `scripts/release-plz.sh` asks git-cliff for the next version (`feat`
bumps the minor, `fix` the patch) and opens or updates a
`chore: release vX.Y.Z` pull request that updates `CHANGELOG.md`. Merging that
pull request tags `vX.Y.Z`, moves `v1`, and creates the GitHub release.
`auto-merge-release.yml` merges the pull request each day once the previous
release is a week old.

The release workflows need two repository secrets: `RELEASE_PLZ_GITHUB_TOKEN`
(a PAT, so the release PR runs CI and its merge starts `release.yml`) and
`ANTHROPIC_API_KEY` (for communique's release notes).

## draft-limit

GitHub has no setting that limits how many pull requests a contributor has
open. `draft-limit.yml` closes a draft pull request, with a comment, when its
author already has `max_drafts` other open drafts. Maintainers and bots are
exempt. See the workflow's header comment for the caller setup, including why
it needs `pull_request_target`.
