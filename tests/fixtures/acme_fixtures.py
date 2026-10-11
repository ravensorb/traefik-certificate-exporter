import base64
import datetime
from typing import NamedTuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _b64(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return base64.b64encode(raw).decode("ascii")


class RealChain(NamedTuple):
    """Genuine key material: an EC P-256 leaf issued by an intermediate under a root.

    `fullchain_pem` is what Traefik stores: the leaf, then the intermediate, each in
    `Encoding.PEM` form (64-column base64, `\\n` line endings -- the same bytes Go's
    `pem.Encode` writes). The root is not part of it, exactly as with Let's Encrypt.
    """

    key_pem: bytes
    leaf_pem: bytes
    intermediate_pem: bytes
    fullchain_pem: bytes


class _Issuer(NamedTuple):
    key: ec.EllipticCurvePrivateKey
    name: x509.Name


_LEAF_COMMON_NAME = "leaf.example.test"
_CACHE: dict[str, RealChain] = {}


def _name(commonName: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, commonName)])


def _issue(
    subject: x509.Name,
    publicKey,
    issuer: _Issuer,
    *,
    ca: bool,
    days: int = 30,
) -> x509.Certificate:
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.name)
        .public_key(publicKey)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(issuer.key, hashes.SHA256())
    )


def _pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _build(days: int = 30) -> RealChain:
    rootKey = ec.generate_private_key(ec.SECP256R1())
    root = _Issuer(rootKey, _name("Test Root CA"))

    intermediateKey = ec.generate_private_key(ec.SECP256R1())
    intermediateName = _name("Test Intermediate CA")
    intermediate = _issue(intermediateName, intermediateKey.public_key(), root, ca=True)
    issuer = _Issuer(intermediateKey, intermediateName)

    leafKey = ec.generate_private_key(ec.SECP256R1())
    leaf = _issue(
        _name(_LEAF_COMMON_NAME), leafKey.public_key(), issuer, ca=False, days=days
    )

    keyPem = leafKey.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return RealChain(
        key_pem=keyPem,
        leaf_pem=_pem(leaf),
        intermediate_pem=_pem(intermediate),
        fullchain_pem=_pem(leaf) + _pem(intermediate),
    )


def real_chain() -> RealChain:
    """The session's real chain, generated once (EC P-256 is fast; nothing is checked in)."""
    if "chain" not in _CACHE:
        _CACHE["chain"] = _build()
    return _CACHE["chain"]


def real_chain_expiring_in(days: int) -> RealChain:
    """A different real chain whose leaf expires `days` from now (cached per `days`)."""
    key = f"chain-{days}"
    if key not in _CACHE:
        _CACHE[key] = _build(days)
    return _CACHE[key]


def acme_v1_fixture(domain: str = "v1.example.test") -> dict:
    """Legacy Traefik ACME v1 shape, wrapped under a resolver name."""
    chain = real_chain()
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
                            "PrivateKey": _b64(chain.key_pem),
                            "Certificate": _b64(chain.fullchain_pem),
                        },
                        "Domains": {"SANs": []},
                    }
                ]
            },
        }
    }


def acme_v2_certificate(domain: str, chain: RealChain | None = None) -> dict:
    """One entry of a lowercase v2 resolver's `Certificates` list."""
    chain = chain or real_chain()
    return {
        "domain": {"main": domain, "sans": []},
        "key": _b64(chain.key_pem),
        "certificate": _b64(chain.fullchain_pem),
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
            "Certificates": [acme_v2_certificate(domain)],
        }
    }


def acme_v2_uppercase_fixture(domain: str = "v2-upper.example.test") -> dict:
    """Traefik ACME v2 shape, NOT resolver-wrapped, uppercase field names."""
    chain = real_chain()
    return {
        "Account": {
            "Registration": {"uri": "https://acme-v02.api.letsencrypt.org/directory"}
        },
        "Certificates": [
            {
                "Domain": {"Main": domain, "SANs": []},
                "Key": _b64(chain.key_pem),
                "Certificate": _b64(chain.fullchain_pem),
            }
        ],
    }


# Shapes beyond the three above (E014-S01-003). Each is the JSON Traefik's Go encoder
# writes for `map[resolverName]*StoredData` (or one unkeyed `StoredData` for v1.7): nil
# slices and pointers encode as `null`, and the CA is whatever `Registration.uri` names.


def acme_v3_fixture(
    domain: str = "v3.example.test",
    uri: str = "https://acme.zerossl.com/v2/DV90/account/x",
    resolver: str = "zerossl",
) -> dict:
    """A Traefik v3 store from a non-Let's-Encrypt CA: nothing in the URI says `acme-v02`."""
    return {
        resolver: {
            "Account": {
                "Email": "ops@example.test",
                "Registration": {"body": {"status": "valid"}, "uri": uri},
                "PrivateKey": _b64(b"account-key"),
                "KeyType": "4096",
            },
            "Certificates": [acme_v2_certificate(domain)],
        }
    }


def acme_null_certificates_resolver(resolver: str = "empty") -> dict:
    """A resolver that has an account but has not issued anything yet."""
    return {
        resolver: {
            "Account": {
                "Email": "ops@example.test",
                "Registration": {
                    "uri": "https://acme-v02.api.letsencrypt.org/acme/acct/1"
                },
            },
            "Certificates": None,
        }
    }


def acme_null_account(domain: str = "null-account.example.test") -> dict:
    """A resolver whose account is `null` but whose certificates are present."""
    return {
        "myresolver": {
            "Account": None,
            "Certificates": [acme_v2_certificate(domain)],
        }
    }


def acme_v17_single_store(domain: str = "v17.example.test") -> dict:
    """Traefik v1.7: one unkeyed `StoredData` with untagged (uppercase) fields."""
    chain = real_chain()
    return {
        "Account": {
            "Email": "ops@example.test",
            "Registration": {
                "body": {"status": "valid"},
                "uri": "https://acme-v02.api.letsencrypt.org/acme/acct/1",
            },
            "PrivateKey": _b64(b"account-key"),
            "KeyType": "4096",
        },
        "Certificates": [
            {
                "Domain": {"Main": domain, "SANs": None},
                "Certificate": _b64(chain.fullchain_pem),
                "Key": _b64(chain.key_pem),
            }
        ],
        "HTTPChallenges": {},
        "TLSChallenges": {},
    }


def acme_legacy_v1_under_account(domain: str = "legacy.example.test") -> dict:
    """Legacy ACME-v1 (Traefik <= 1.6): `DomainsCertificate.Certs` inside `Account`."""
    chain = real_chain()
    return {
        "Account": {
            "Email": "ops@example.test",
            "Registration": {"uri": "https://acme-v01.api.letsencrypt.org/acme/reg/1"},
            "DomainsCertificate": {
                "Certs": [
                    {
                        "Domains": {"Main": domain, "SANs": None},
                        "Certificate": {
                            "Domain": domain,
                            "CertURL": "https://acme.example.test/cert/1",
                            "PrivateKey": _b64(chain.key_pem),
                            "Certificate": _b64(chain.fullchain_pem),
                        },
                    }
                ]
            },
        }
    }


def acme_mixed_case(
    lower: str = "lower.example.test", upper: str = "upper.example.test"
) -> dict:
    """One resolver whose entries use different key cases (case is chosen per entry)."""
    chain = real_chain()
    return {
        "myresolver": {
            "Account": {"Registration": {"uri": "https://ca.example.test/acct/1"}},
            "Certificates": [
                acme_v2_certificate(lower),
                {
                    "Domain": {"Main": upper, "SANs": None},
                    "Key": _b64(chain.key_pem),
                    "Certificate": _b64(chain.fullchain_pem),
                    "Store": "default",
                },
            ],
        }
    }
