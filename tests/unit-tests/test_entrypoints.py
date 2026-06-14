# Cover the console-script entry points; stub the callees to avoid GUI/recursion.

import sys
import types

import pytest


def test_run_cli_delegates_to_app_main(monkeypatch):
    calls = []
    fake_app = types.ModuleType("opensak.app")
    fake_app.main = lambda: calls.append("ran")
    monkeypatch.setitem(sys.modules, "opensak.app", fake_app)

    from opensak.utils.run_cli import main

    main()
    assert calls == ["ran"]


def test_run_test_forwards_argv_to_pytest_and_exits(monkeypatch):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        return 3

    monkeypatch.setattr(sys, "argv", ["opensak-test", "-k", "foo", "-x"])
    monkeypatch.setattr(pytest, "main", fake_pytest_main)

    from opensak.utils.run_test import run

    with pytest.raises(SystemExit) as exit_info:
        run()

    assert exit_info.value.code == 3
    assert captured["args"] == ["tests", "-k", "foo", "-x"]
