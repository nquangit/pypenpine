import pytest

from penpine.transport.ws_frame import (
    OP_BINARY,
    OP_CLOSE,
    OP_PING,
    OP_TEXT,
    Frame,
    IncompleteFrame,
)


def _roundtrip(frame: Frame) -> Frame:
    parsed, rest = Frame.parse(frame.serialize())
    assert rest == b""
    return parsed


def test_text_frame_roundtrip_unmasked():
    f = Frame.text("hello")
    assert f.opcode == OP_TEXT and f.fin is True and f.payload == b"hello"
    out = _roundtrip(f)
    assert out.opcode == OP_TEXT and out.payload == b"hello" and out.fin is True


def test_masked_frame_roundtrips_to_plaintext_payload():
    f = Frame(opcode=OP_TEXT, payload=b"secret", mask=b"\x01\x02\x03\x04")
    wire = f.serialize()
    assert wire[1] & 0x80  # MASK bit set
    assert b"secret" not in wire  # payload is masked on the wire
    out, rest = Frame.parse(wire)
    assert rest == b"" and out.payload == b"secret"  # parse unmasks


def test_16bit_and_64bit_length_encodings():
    mid = Frame.binary(b"a" * 200)  # >125 -> 16-bit
    assert mid.serialize()[1] & 0x7F == 126
    assert _roundtrip(mid).payload == b"a" * 200
    big = Frame.binary(b"b" * 70000)  # >65535 -> 64-bit
    assert big.serialize()[1] & 0x7F == 127
    assert _roundtrip(big).payload == b"b" * 70000


def test_control_frames():
    assert _roundtrip(Frame.ping(b"pi")).opcode == OP_PING
    c = _roundtrip(Frame.close(1000, "bye"))
    assert c.opcode == OP_CLOSE and c.payload[:2] == (1000).to_bytes(2, "big")


def test_continuation_and_reserved_bits_are_faithful():
    f = Frame(opcode=OP_BINARY, payload=b"x", fin=False, rsv1=True)
    out = _roundtrip(f)
    assert out.fin is False and out.rsv1 is True and out.opcode == OP_BINARY


def test_parse_incomplete_raises():
    full = Frame.text("abcdef").serialize()
    with pytest.raises(IncompleteFrame):
        Frame.parse(full[:1])  # too short for even the header
    with pytest.raises(IncompleteFrame):
        Frame.parse(full[:-2])  # header present, payload truncated


def test_parse_returns_trailing_bytes():
    two = Frame.text("a").serialize() + Frame.text("b").serialize()
    first, rest = Frame.parse(two)
    assert first.payload == b"a"
    second, rest2 = Frame.parse(rest)
    assert second.payload == b"b" and rest2 == b""
