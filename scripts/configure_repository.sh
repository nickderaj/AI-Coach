#!/usr/bin/env bash
# Apply the repository merge policy and main-branch protection.
# Must be run by a repository admin (the owner), authenticated with `gh`.
set -euo pipefail

cd "$(dirname "$0")/.."
repository=${1:-nickderaj/hermes-trainer}

# Squash-only merges whose subject is the (policy-checked) PR title, so main's
# history is one Conventional Commit per reviewed pull request.
gh api --method PATCH "repos/${repository}" \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F allow_auto_merge=true \
  -F delete_branch_on_merge=true \
  -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=PR_BODY \
  --silent

gh api --method PUT "repos/${repository}/branches/main/protection" \
  --input scripts/branch-protection.json \
  --silent

echo "applied merge policy and branch protection to ${repository}"
