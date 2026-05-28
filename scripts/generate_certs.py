import datetime
import ipaddress
import os
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


CERT_FILES = (
    "ca.key",
    "ca.crt",
    "server.key",
    "server.crt",
    "client.key",
    "client.crt",
)


def should_force_regenerate() -> bool:
    return os.getenv("FORCE_REGENERATE_CERTS", "false").strip().lower() in {"1", "true", "yes", "on"}


def cert_paths(output_dir: str) -> list[str]:
    return [os.path.join(output_dir, filename) for filename in CERT_FILES]


def cert_bundle_exists(output_dir: str) -> bool:
    return all(os.path.exists(path) for path in cert_paths(output_dir))


def generate_certs(output_dir="certs"):
    os.makedirs(output_dir, exist_ok=True)

    if cert_bundle_exists(output_dir) and not should_force_regenerate():
        print(f"Certificates already exist in directory: {output_dir}. Skipping regeneration.")
        return

    print(f"Generating certificates in directory: {output_dir}")

    # 1. Generate CA Key and Certificate
    print("Generating CA key and certificate...")
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Metropolitana"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Santiago"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "IntellyDTE"),
            x509.NameAttribute(NameOID.COMMON_NAME, "IntellyDTE Root CA"),
        ]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=3650)
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Save CA
    with open(os.path.join(output_dir, "ca.key"), "wb") as f:
        f.write(
            ca_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(os.path.join(output_dir, "ca.crt"), "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

    # 2. Generate Server Certificate (for Python service)
    print("Generating Server certificate...")
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Metropolitana"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Santiago"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "IntellyDTE"),
            x509.NameAttribute(
                NameOID.COMMON_NAME, "folio-bridge-py.local"
            ),  # Or localhost
        ]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=1825)
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("folio-bridge-py"),
                    x509.DNSName("folio-bridge-py.local"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Save Server
    with open(os.path.join(output_dir, "server.key"), "wb") as f:
        f.write(
            server_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(os.path.join(output_dir, "server.crt"), "wb") as f:
        f.write(server_cert.public_bytes(serialization.Encoding.PEM))

    # 3. Generate Client Certificate (for Node application)
    print("Generating Client certificate...")
    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Metropolitana"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Santiago"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "IntellyDTE"),
            x509.NameAttribute(NameOID.COMMON_NAME, "intellydte-node-client"),
        ]
    )
    client_cert = (
        x509.CertificateBuilder()
        .subject_name(client_subject)
        .issuer_name(ca_name)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=1825)
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Save Client
    with open(os.path.join(output_dir, "client.key"), "wb") as f:
        f.write(
            client_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(os.path.join(output_dir, "client.crt"), "wb") as f:
        f.write(client_cert.public_bytes(serialization.Encoding.PEM))

    print("Mutual TLS Certificates generated successfully!")


if __name__ == "__main__":
    generate_certs()
