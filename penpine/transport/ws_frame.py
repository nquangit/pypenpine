"""RFC 6455 WebSocket frames: byte-faithful and deliberately malformable."""

from __future__ import annotations

import struct
from dataclasses import dataclass

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class IncompleteFrame(Exception):
    """Not enough bytes to parse a full frame yet; read more and retry."""


@dataclass(frozen=True)
class Frame:
    opcode: int
    payload: bytes = b""
    fin: bool = True
    mask: bytes | None = None  # None = unmasked on the wire; 4 bytes = masked
    rsv1: bool = False
    rsv2: bool = False
    rsv3: bool = False

    def serialize(self) -> bytes:
        b0 = (
            (0x80 if self.fin else 0)
            | (0x40 if self.rsv1 else 0)
            | (0x20 if self.rsv2 else 0)
            | (0x10 if self.rsv3 else 0)
            | (self.opcode & 0x0F)
        )
        n = len(self.payload)
        mask_bit = 0x80 if self.mask is not None else 0
        if n <= 125:
            header = bytes([b0, mask_bit | n])
        elif n <= 0xFFFF:
            header = bytes([b0, mask_bit | 126]) + struct.pack("!H", n)
        else:
            header = bytes([b0, mask_bit | 127]) + struct.pack("!Q", n)
        if self.mask is not None:
            key = self.mask
            masked = bytes(b ^ key[i % 4] for i, b in enumerate(self.payload))
            return header + key + masked
        return header + self.payload

    @classmethod
    def parse(cls, data: bytes) -> tuple[Frame, bytes]:
        if len(data) < 2:
            raise IncompleteFrame
        b0, b1 = data[0], data[1]
        fin = bool(b0 & 0x80)
        rsv1, rsv2, rsv3 = bool(b0 & 0x40), bool(b0 & 0x20), bool(b0 & 0x10)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        n = b1 & 0x7F
        off = 2
        if n == 126:
            if len(data) < off + 2:
                raise IncompleteFrame
            n = struct.unpack("!H", data[off : off + 2])[0]
            off += 2
        elif n == 127:
            if len(data) < off + 8:
                raise IncompleteFrame
            n = struct.unpack("!Q", data[off : off + 8])[0]
            off += 8
        key = None
        if masked:
            if len(data) < off + 4:
                raise IncompleteFrame
            key = data[off : off + 4]
            off += 4
        if len(data) < off + n:
            raise IncompleteFrame
        payload = data[off : off + n]
        if key is not None:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        frame = cls(
            opcode=opcode, payload=payload, fin=fin, mask=key, rsv1=rsv1, rsv2=rsv2, rsv3=rsv3
        )
        return frame, data[off + n :]

    @classmethod
    def text(cls, s: str, *, fin: bool = True) -> Frame:
        return cls(opcode=OP_TEXT, payload=s.encode("utf-8"), fin=fin)

    @classmethod
    def binary(cls, b: bytes, *, fin: bool = True) -> Frame:
        return cls(opcode=OP_BINARY, payload=b, fin=fin)

    @classmethod
    def ping(cls, payload: bytes = b"") -> Frame:
        return cls(opcode=OP_PING, payload=payload)

    @classmethod
    def pong(cls, payload: bytes = b"") -> Frame:
        return cls(opcode=OP_PONG, payload=payload)

    @classmethod
    def close(cls, code: int = 1000, reason: str = "") -> Frame:
        return cls(opcode=OP_CLOSE, payload=struct.pack("!H", code) + reason.encode("utf-8"))
