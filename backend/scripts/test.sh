#!/usr/bin/env bash

set -e

exec python scripts/run_isolated_tests.py "$@"
