#!/bin/sh
# Use the repository hook for this push without changing another worktree's Git configuration.
set -eu
exec git -c core.hooksPath=.github/hooks push "$@"
