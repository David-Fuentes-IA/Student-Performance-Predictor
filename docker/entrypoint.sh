#!/bin/sh
# Container start-up: optionally seed demo data, then hand over to the real command
# (gunicorn). `exec` makes gunicorn PID 1 so it receives SIGTERM and shuts down cleanly.
set -e

if [ "${SEED_DEMO:-false}" = "true" ] && [ -n "${MONGODB_URI:-}" ]; then
    echo "SEED_DEMO=true: creating the demo groups (idempotent, only synthetic data)..."
    python scripts/seed_demo_data.py > /dev/null \
        || echo "WARNING: demo seeding failed (is MongoDB reachable?); starting the app anyway."
fi

exec "$@"
