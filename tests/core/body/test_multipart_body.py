from penpine.core.body.multipart_body import MultipartBody

CT = 'multipart/form-data; boundary=----b'
RAW = (
    b"------b\r\n"
    b'Content-Disposition: form-data; name="a"\r\n\r\n'
    b"1\r\n"
    b"------b\r\n"
    b'Content-Disposition: form-data; name="file"; filename="f.txt"\r\n'
    b"Content-Type: text/plain\r\n\r\n"
    b"DATA\r\n"
    b"------b--\r\n"
)


def test_parse_parts():
    mb = MultipartBody.from_bytes(RAW, CT)
    assert mb.get("a") == b"1"
    assert mb.get("file") == b"DATA"
    assert mb.names() == ["a", "file"]


def test_set_and_reserialize_roundtrips_names():
    mb = MultipartBody.from_bytes(RAW, CT)
    mb2 = mb.set("a", b"9")
    assert mb.get("a") == b"1"
    assert mb2.get("a") == b"9"
    reparsed = MultipartBody.from_bytes(mb2.to_bytes(), CT)
    assert reparsed.get("a") == b"9"
    assert reparsed.get("file") == b"DATA"
