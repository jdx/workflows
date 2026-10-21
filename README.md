# workflows

Reusable GitHub Actions workflows and composite actions shared by jdx repositories.

| Workflow | Purpose |
| --- | --- |
| `.github/workflows/draft-limit.yml` | Closes a draft pull request when its author already has another open draft |

| `retry/action.yml` | Composite action that retries a command on failure or timeout (replaces `nick-fields/retry`) |
| `gpg-import/action.yml` | Composite action that imports a GPG key and configures git signing (replaces `crazy-max/ghaction-import-gpg`) |

Each workflow's header comment shows the caller setup.

## Releases

The workflows and actions are released as `vX.Y.Z` tags, and callers pin the tag's commit
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

## retry

`retry/action.yml` runs a command up to `max_attempts` times, killing an attempt
after `timeout_minutes` and sleeping `retry_wait_seconds` between attempts. It
takes the `nick-fields/retry` inputs mise uses (`command`, `max_attempts`,
`timeout_minutes`, `retry_wait_seconds`) without needing Node; `retry_on` and
`timeout_seconds` are not supported. Set
`shell: pwsh` to run the command as PowerShell 7.3 or newer, as on Windows runners:

```yaml
- uses: jdx/workflows/retry@<sha> # vX.Y.Z
  with:
    command: cargo test
    max_attempts: 2
    timeout_minutes: 30
    retry_wait_seconds: 30
```

## gpg-import

`gpg-import/action.yml` imports an ASCII-armored GPG private key and can turn on
git signing. It covers the inputs mise uses (`gpg_private_key`, `trust_level`,
`git_user_signingkey`, `git_commit_gpgsign`, `git_tag_gpgsign`) and outputs the
key's `fingerprint` and `keyid`. Git settings go in the global config, and keys
with a passphrase are not supported:

```yaml
- uses: jdx/workflows/gpg-import@<sha> # vX.Y.Z
  with:
    gpg_private_key: ${{ secrets.GPG_KEY }}
    git_user_signingkey: true
    git_commit_gpgsign: true
```

## draft-limit

GitHub has no setting that limits how many pull requests a contributor has
open. `draft-limit.yml` closes a draft pull request, with a comment, when its
author already has `max_drafts` other open drafts. Maintainers and bots are
exempt. See the workflow's header comment for the caller setup, including why
it needs `pull_request_target`.
