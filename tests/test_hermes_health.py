from brain.hermes_health import hermes_health


class _Disabled:
    enabled = False
    mode = "disabled"


def test_health_is_truthful_when_disabled():
    assert hermes_health(_Disabled())["status"] == "disabled"
