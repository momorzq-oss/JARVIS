from integrations.colibri_health import colibri_health


class _Disabled:
    enabled = False
    mode = "disabled"


def test_health_reports_disabled_without_network_access():
    assert colibri_health(_Disabled()) == {
        "status": "disabled", "detail": "COLIBRI_ENABLED=false"
    }
