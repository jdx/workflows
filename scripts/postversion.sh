#!/usr/bin/env bash
set -euxo pipefail

VERSION="$(grep -m1 -oE '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' CHANGELOG.md | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
MAJOR_VERSION=$(echo "$VERSION" | cut -d. -f1)

# Configure git to use gh's credential helper. The checkout step uses
# persist-credentials: false (per zizmor's artipacked audit), so the
# token isn't written to .git/config and raw `git push` would 403.
gh auth setup-git

# create the version tag (allow it to fail if it already exists)
git tag "v$VERSION" || echo "Tag v$VERSION already exists locally"

# push the current tag to github
git push origin "v$VERSION" || echo "Tag v$VERSION already exists on remote"

# set the major version tag to this release. Callers should still pin the
# exact version's sha: a moving tag in a `# v1` comment trips zizmor's
# ref-version-mismatch audit the next time it moves.
git tag "v$MAJOR_VERSION" -f
# push the major version tag to github (retry with pull if it fails)
if ! git push origin "v$MAJOR_VERSION" -f; then
  echo "Failed to push v$MAJOR_VERSION tag, pulling and retrying..."
  git fetch origin "refs/tags/v$MAJOR_VERSION:refs/tags/v$MAJOR_VERSION" -f
  git tag "v$MAJOR_VERSION" -f
  git push origin "v$MAJOR_VERSION" -f
fi

# check if release already exists before creating
if gh release view "v$VERSION" >/dev/null 2>&1; then
  echo "Release v$VERSION already exists, skipping creation"
else
  # create a release on github
  gh release create "v$VERSION" --generate-notes --verify-tag
fi
