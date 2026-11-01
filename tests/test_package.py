import midimcp


def test_package_exposes_version() -> None:
    assert midimcp.__version__ == "0.1.0"
