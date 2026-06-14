# Cover lang/*.py by importing each language as a real package module.

import importlib

import pytest

from opensak.lang import AVAILABLE_LANGUAGES

# Import at collection time, before test_languages / e2e load_language() spec-exec
# these files (which otherwise blocks coverage attribution for opensak.lang.*).
_MODULES = {code: importlib.import_module(f"opensak.lang.{code}") for code in AVAILABLE_LANGUAGES}


@pytest.mark.parametrize("code", sorted(AVAILABLE_LANGUAGES))
def test_language_module_exposes_strings(code):
    strings = _MODULES[code].STRINGS
    assert isinstance(strings, dict)
    assert strings
