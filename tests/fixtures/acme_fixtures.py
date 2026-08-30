import base64


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


DUMMY_PRIVATE_KEY = "dummy private key bytes -- synthetic fixture, not a real key"
DUMMY_FULLCHAIN = (
    "-----BEGIN CERTIFICATE-----\n"
    "synthetic-leaf-cert-not-real\n"
    "-----END CERTIFICATE-----\n"
    "-----BEGIN CERTIFICATE-----\n"
    "synthetic-chain-cert-not-real\n"
    "-----END CERTIFICATE-----\n"
)


def acme_v1_fixture(domain: str = "v1.example.test") -> dict:
    """Legacy Traefik ACME v1 shape, wrapped under a resolver name."""
    return {
        "myresolver": {
            "Account": {
                "Registration": {
                    "uri": "https://acme-v01.api.letsencrypt.org/directory"
                }
            },
            "DomainsCertificate": {
                "Certs": [
                    {
                        "Certificate": {
                            "Domain": domain,
                            "PrivateKey": _b64(DUMMY_PRIVATE_KEY),
                            "Certificate": _b64(DUMMY_FULLCHAIN),
                        },
                        "Domains": {"SANs": []},
                    }
                ]
            },
        }
    }


def acme_v2_lowercase_fixture(domain: str = "v2-lower.example.test") -> dict:
    """Traefik ACME v2 shape, resolver-name-wrapped, lowercase field names."""
    return {
        "myresolver": {
            "Account": {
                "Registration": {
                    "uri": "https://acme-v02.api.letsencrypt.org/directory"
                }
            },
            "Certificates": [
                {
                    "domain": {"main": domain, "sans": []},
                    "key": _b64(DUMMY_PRIVATE_KEY),
                    "certificate": _b64(DUMMY_FULLCHAIN),
                }
            ],
        }
    }


def acme_v2_uppercase_fixture(domain: str = "v2-upper.example.test") -> dict:
    """Traefik ACME v2 shape, NOT resolver-wrapped, uppercase field names."""
    return {
        "Account": {
            "Registration": {"uri": "https://acme-v02.api.letsencrypt.org/directory"}
        },
        "Certificates": [
            {
                "Domain": {"Main": domain, "SANs": []},
                "Key": _b64(DUMMY_PRIVATE_KEY),
                "Certificate": _b64(DUMMY_FULLCHAIN),
            }
        ],
    }
