#!/bin/bash

set -ex

TEST_RUNNER=$([ "$1" = "code-coverage" ] && echo "coverage run --append --source=sakuya" || echo "python3")
PYTHONPATH=. ${TEST_RUNNER} -m pytest tests --asyncio-mode=auto -v
