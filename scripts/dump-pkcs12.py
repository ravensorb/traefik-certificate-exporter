#!/usr/bin/env python3

import argparse

from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

argParser = argparse.ArgumentParser(prog="dump-pkcs12", description="Convert PEM cert and key to PKCS12")
argParser.add_argument('-c', "--cert-file", dest="cert_file", default='fullchain.pem', help="PEM cert file") 
argParser.add_argument('-k', "--key-file", dest="key_file", default='privkey.pem', help="PEM key file") 
argParser.add_argument('-p', "--passphrase", dest="passphrase", default=None, help="Passphrase for the PKCS12 file") 
argParser.add_argument('-o',"--output-file", dest="output_file", default='cert-temp.pfx', help="PKCS12 output file")

args = argParser.parse_args()

print("Reading PEM file: " + args.cert_file + "...")
pem_cert_bytes = Path(args.cert_file).read_bytes()
cert = x509.load_pem_x509_certificate(pem_cert_bytes)
cert_subject_common_name = str(cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value)
if cert_subject_common_name is not None:
    if "*." in cert_subject_common_name:
        cert_subject_common_name = "{} (wildcard)".format(cert_subject_common_name.split("*.")[1])
else:
    cert_subject_common_name = "LetsEncrypt Certificate"

print("Reading PEM key: " + args.key_file + "...")
pem_key_bytes = Path(args.key_file).read_bytes()
key = serialization.load_pem_private_key(pem_key_bytes, password=None)

print("Serializing PKCS12: " + args.output_file + "...")
pkcs12_encryption = serialization.BestAvailableEncryption(args.passphrase.encode('utf-8')) if args.passphrase is not None else serialization.NoEncryption()
pkcs12_bytes = pkcs12.serialize_key_and_certificates(cert_subject_common_name.encode('utf-8'), 
                                            key, # type: ignore
                                            cert, 
                                            None, 
                                            pkcs12_encryption)

Path(args.output_file).write_bytes(pkcs12_bytes)

(pkcs12_key, pkcs12_cert, pkcs12_chain) = pkcs12.load_key_and_certificates(pkcs12_bytes, args.passphrase.encode('utf-8') if args.passphrase is not None else None)

print("PKCS12 Details:")
print("  Name: {}".format(cert_subject_common_name))
print("  Subject: {}".format(str(pkcs12_cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value)))                   # type: ignore
print("  Issuer: {}".format(str(pkcs12_cert.issuer.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value)))                     # type: ignore
print("  Serial Number: {}".format(str(pkcs12_cert.serial_number)))       # type: ignore
print("  Not Before: {}".format(pkcs12_cert.not_valid_before_utc.date())) # type: ignore
print("  Not After: {}".format(pkcs12_cert.not_valid_after_utc.date()))   # type: ignore

