#!/usr/bin/env bash
# Creates GitHub labels for the Integration Bounty Program.
# Usage: ./scripts/setup-bounty-labels.sh [owner/repo]
# Requires: gh CLI authenticated

set -euo pipefail

REPO="${1:-adenhq/hive}"

echo "Setting up bounty labels for $REPO..."

# Bounty type labels
gh label create "bounty:test"     --repo "$REPO" --color "1D76DB" --description "Bounty: test a tool with real API key (20 pts)" --force
gh label create "bounty:docs"     --repo "$REPO" --color "FBCA04" --description "Bounty: write or improve documentation (20 pts)" --force
gh label create "bounty:code"     --repo "$REPO" --color "D93F0B" --description "Bounty: health checker, bug fix, or improvement (30 pts)" --force
gh label create "bounty:new-tool" --repo "$REPO" --color "6F42C1" --description "Bounty: build a new integration from scratch (75 pts)" --force

# Difficulty labels
gh label create "difficulty:easy"   --repo "$REPO" --color "BFD4F2" --description "Good first contribution" --force
gh label create "difficulty:medium" --repo "$REPO" --color "D4C5F9" --description "Requires some familiarity" --force
gh label create "difficulty:hard"   --repo "$REPO" --color "F9D0C4" --description "Significant effort or expertise needed" --force

echo "Done. Labels created for $REPO."
