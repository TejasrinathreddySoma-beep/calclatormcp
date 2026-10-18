import asyncio

import pytest

from mcpcalc.backends import PythonBackend
from mcpcalc.config import load_config
from mcpcalc.db import Database
from mcpcalc.executors import LocalExecutor
from mcpcalc.safety import Policy


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def backend():
    return PythonBackend()


@pytest.fixture
def policy():
    return Policy()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def executor(backend, policy, db):
    return LocalExecutor(backend, policy, db, source="test")


@pytest.fixture
def cfg(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")  # defaults only
    cfg["database"]["path"] = str(tmp_path / "server.db")
    return cfg
