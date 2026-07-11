import ssl

from penpine.transport.tls import TLSConfig


def test_default_is_unverified():
    ctx = TLSConfig().build_ssl_context()
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE


def test_verify_true_keeps_hostname_checking():
    ctx = TLSConfig(verify=True).build_ssl_context()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_versions_and_ciphers_applied():
    cfg = TLSConfig(min_version=ssl.TLSVersion.TLSv1_2, max_version=ssl.TLSVersion.TLSv1_2)
    ctx = cfg.build_ssl_context()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.maximum_version == ssl.TLSVersion.TLSv1_2
