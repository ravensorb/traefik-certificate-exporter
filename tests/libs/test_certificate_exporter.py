import json

from traefik_certificate_exporter.libs.certificate_exporter import (
    AcmeCertificateExporter,
)
from traefik_certificate_exporter.libs.settings import Settings

from ..fixtures.acme_fixtures import (
    acme_v1_fixture,
    acme_v2_lowercase_fixture,
    acme_v2_uppercase_fixture,
)


def _make_settings(**overrides) -> Settings:
    defaults = {
        "dataPath": "/data",
        "fileSpec": "*.json",
        "outputPath": "/certs",
        "resolverInPathName": False,
        "traefikResolverId": None,
        "flat": False,
        "dryRun": True,  # never touch disk for exported cert files in these tests
        "restartContainers": False,
        "domains": {"include": [], "exclude": []},
        "watchForChanges": False,
        "runAtStart": False,
        "watchInterval": 60,
        "pkcs12Passphrase": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _write_fixture(tmp_path, data: dict, name: str = "acme.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return str(path)


def test_acme_v1_shape_is_parsed(tmp_path):
    fixture_path = _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"))
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["v1.example.test"]


def test_acme_v2_lowercase_shape_is_parsed(tmp_path):
    fixture_path = _write_fixture(
        tmp_path, acme_v2_lowercase_fixture("v2-lower.example.test")
    )
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["v2-lower.example.test"]


def test_acme_v2_uppercase_shape_is_parsed(tmp_path):
    fixture_path = _write_fixture(
        tmp_path, acme_v2_uppercase_fixture("v2-upper.example.test")
    )
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["v2-upper.example.test"]


def test_domains_include_filters_out_non_matching_domain(tmp_path):
    fixture_path = _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"))
    settings = _make_settings(
        domains={"include": ["other.example.test"], "exclude": []}
    )
    exporter = AcmeCertificateExporter(settings=settings)

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []


def test_domains_exclude_filters_out_matching_domain(tmp_path):
    fixture_path = _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"))
    settings = _make_settings(domains={"include": [], "exclude": ["v1.example.test"]})
    exporter = AcmeCertificateExporter(settings=settings)

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []


def test_missing_file_returns_empty_list_not_an_exception(tmp_path):
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(str(tmp_path / "does-not-exist.json"))

    assert names == []


def test_empty_file_returns_empty_list_not_an_exception(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("")
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(str(path))

    assert names == []


def test_export_certificates_globs_data_path(tmp_path):
    _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"), name="acme.json")
    settings = _make_settings(dataPath=str(tmp_path), fileSpec="*.json")
    exporter = AcmeCertificateExporter(settings=settings)

    processed = exporter.exportCertificates()

    assert processed == ["v1.example.test"]
