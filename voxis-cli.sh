#!/bin/bash
# VOXIS CLI — processes audio from the command line
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/venv/bin/activate"
export PYTORCH_ENABLE_MPS_FALLBACK=1
cd "$DIR/trinity_engine"
python3 trinity_core.py "$@"
