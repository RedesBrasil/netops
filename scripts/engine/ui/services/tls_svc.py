"""Certificado TLS autoassinado para o console responder em HTTPS direto pelo IP.

Navegadores só liberam microfone (ditado por voz), clipboard e outros recursos em "contexto
seguro" (HTTPS ou localhost). Pelo IP em HTTP puro isso não existe; este módulo gera/renova um
certificado com o(s) IP(s) da máquina no SAN para o segundo listener do server.py.

O certificado fica em DATA_ROOT/runs/tls/ (runs/ é git-ignorado) e é regerado sozinho quando
falta, está perto de vencer ou o SAN não cobre mais algum IP local.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import socket
import subprocess
from pathlib import Path

VALID_DAYS = 825          # teto aceito por iOS/Safari para certificados confiados manualmente
RENEW_BEFORE_DAYS = 30


def local_ips(bind_host: str) -> list[str]:
    """IPs que precisam constar no certificado: bind + loopback + todos os IPs da máquina (`hostname -I`).
    Bind curinga (0.0.0.0/::) não entra: o certificado cobre cada IP real, e se o conjunto mudar ele é refeito no próximo arranque do console."""
    ips = {"127.0.0.1"}
    if bind_host not in ("0.0.0.0", "::", "*", ""):
        ips.add(bind_host)
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout
        ips.update(out.split())
    except Exception:  # noqa: BLE001
        pass
    valid = []
    for ip in ips:
        try:
            valid.append(str(ipaddress.ip_address(ip)))
        except ValueError:
            continue
    return sorted(set(valid))


def _san_of(cert) -> tuple[set[str], set[str]]:
    from cryptography import x509  # noqa: PLC0415
    ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return ({str(i) for i in ext.get_values_for_type(x509.IPAddress)},
            {str(d) for d in ext.get_values_for_type(x509.DNSName)})


def _is_current(cert_path: Path, key_path: Path, ips: list[str]) -> bool:
    from cryptography import x509  # noqa: PLC0415
    if not (cert_path.is_file() and key_path.is_file()):
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        left = cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)
        if left < dt.timedelta(days=RENEW_BEFORE_DAYS):
            return False
        have_ips, _ = _san_of(cert)
        return set(ips) <= have_ips
    except Exception:  # noqa: BLE001
        return False


def ensure_cert(tls_dir: Path, bind_host: str) -> tuple[Path, Path]:
    """Garante cert.pem/key.pem válidos para os IPs locais; devolve (cert, key)."""
    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID  # noqa: PLC0415

    tls_dir.mkdir(parents=True, exist_ok=True)
    tls_dir.chmod(0o700)
    cert_path, key_path = tls_dir / "cert.pem", tls_dir / "key.pem"
    ips = local_ips(bind_host)
    if _is_current(cert_path, key_path, ips):
        return cert_path, key_path

    host = socket.gethostname() or "netops"
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"NetOps Console ({bind_host})"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NetOps")])
    now = dt.datetime.now(dt.timezone.utc)
    san = [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    san += [x509.DNSName("localhost"), x509.DNSName(host)]
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                         data_encipherment=False, key_agreement=True, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    key_tmp, cert_tmp = key_path.with_suffix(".tmp"), cert_path.with_suffix(".tmp")
    key_tmp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    key_tmp.chmod(0o600)
    cert_tmp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_tmp.replace(key_path)
    cert_tmp.replace(cert_path)
    return cert_path, key_path


def fingerprint(cert_path: Path) -> str:
    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
    c = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return c.fingerprint(hashes.SHA256()).hex(":").upper()
