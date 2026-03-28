#!/usr/bin/env bash

# MacOS workaround for "OSError: no library called "cairo-2" was found" despite being installed.
# Usage: ./harden.sh <same args for tt_tool.py>
DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix cairo)/lib" uv run ./tt/tt_tool.py "$@"
