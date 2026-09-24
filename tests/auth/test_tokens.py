import base64
import json

from penpine.auth.tokens import jwt_claims, jwt_expiry


def make_jwt(payload: dict) -> str:
    def seg(obj) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg({'alg': 'none'})}.{seg(payload)}.signature"


def test_jwt_expiry_reads_exp():
    token = make_jwt({"sub": "u", "exp": 1700000000})
    assert jwt_expiry(token) == 1700000000.0


def test_jwt_expiry_none_without_exp():
    assert jwt_expiry(make_jwt({"sub": "u"})) is None


def test_jwt_expiry_none_for_garbage():
    assert jwt_expiry("not-a-jwt") is None
    assert jwt_expiry("a.b") is None  # payload segment not valid base64/json


def test_jwt_claims_decodes_payload_with_padding():
    # A payload whose base64 needs padding restored (length not a multiple of 4).
    token = make_jwt({"role": "admin", "n": 1})
    assert jwt_claims(token) == {"role": "admin", "n": 1}


def test_jwt_claims_empty_on_non_object_payload():
    seg = base64.urlsafe_b64encode(b"[1,2,3]").rstrip(b"=").decode()
    assert jwt_claims(f"h.{seg}.s") == {}
