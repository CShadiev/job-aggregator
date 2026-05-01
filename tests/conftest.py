import pytest


def pytest_addoption(parser):
    parser.addoption("--run-priced", action="store_true", help="Run priced tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-priced"):
        skip = pytest.mark.skip(reason="Priced tests are disabled. Use --run-priced to run them")
        for item in items:
            if "priced" in item.keywords:
                item.add_marker(skip)
