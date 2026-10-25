"""Tests must not depend on the developer's .env: force demo (in-memory) mode.

An explicit empty MONGODB_URI wins over .env (see core/config.py), so
main_api bootstraps with the in-memory repository. Mongo integration tests
use MONGODB_TEST_URI instead.
"""
import os

os.environ["MONGODB_URI"] = ""
