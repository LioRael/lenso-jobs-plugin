#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "::error title=Publish main identity::$*" >&2
  exit 1
}

[[ "${GITHUB_REPOSITORY:-}" == "LioRael/lenso-jobs-plugin" ]] ||
  fail "unexpected repository"
[[ -n "${GITHUB_TOKEN:-}" ]] || fail "GITHUB_TOKEN is required"
[[ -n "${RELEASE_SHA:-}" ]] || fail "RELEASE_SHA is required"
source_sha="${RELEASE_SHA,,}"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || fail "RELEASE_SHA must be a full commit SHA"
[[ "$(git rev-parse HEAD)" == "$source_sha" ]] ||
  fail "checkout no longer matches the approved source SHA"

git fetch origin main --no-tags >/dev/null || fail "could not refresh origin/main"
fetched_sha="$(git rev-parse refs/remotes/origin/main 2>/dev/null)" ||
  fail "origin/main is unavailable after fetch"
remote_sha="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main" --jq '.object.sha')" ||
  fail "could not read remote main"
[[ "$remote_sha" =~ ^[0-9a-f]{40}$ ]] || fail "remote main did not return a full commit SHA"
[[ "$fetched_sha" == "$remote_sha" ]] ||
  fail "fetched origin/main disagrees with remote main; rerun release verification"
[[ "$remote_sha" == "$source_sha" ]] ||
  fail "main advanced after release verification; do not publish this source"

printf 'Publish main identity confirmed: %s\n' "$source_sha"
