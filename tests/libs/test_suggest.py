from traefik_certificate_exporter.libs.suggest import nearest_name


def test_nearest_name_returns_close_match():
    options = ["SETTINGS_OUTPUTPATH", "SETTINGS_DATAPATH", "SETTINGS_FILESPEC"]

    assert nearest_name("SETTINGS_OUTPUTPAHT", options) == "SETTINGS_OUTPUTPATH"


def test_nearest_name_returns_none_without_close_match():
    assert nearest_name("FOO", ["SETTINGS_OUTPUTPATH", "SETTINGS_DATAPATH"]) is None
