"""JWT 双模鉴权单测(HS256 兜底 + alg 分发 + 失败路径)。"""

import time

import jwt
import pytest
from agent_core.auth import JwtVerifier, UnauthorizedError, sign_hs256

SECRET = "unit-test-secret-0123456789abcdef"  # ≥32 字节,避免 InsecureKeyLengthWarning


def test_hs256_roundtrip() -> None:
    token = sign_hs256(secret=SECRET, sub="42", username="u", role="USER", expire_seconds=60)
    claims = JwtVerifier(hs_secret=SECRET).verify(token)
    assert claims.sub == "42"
    assert claims.username == "u"
    assert claims.iss is None


def test_hs256_scope_parsing() -> None:
    now = int(time.time())
    token = jwt.encode(
        {"sub": "1", "scope": "read write", "exp": now + 60}, SECRET, algorithm="HS256"
    )
    claims = JwtVerifier(hs_secret=SECRET).verify(token)
    assert claims.scope == ("read", "write")


def test_expired_token_rejected() -> None:
    now = int(time.time())
    token = jwt.encode({"sub": "1", "exp": now - 10}, SECRET, algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        JwtVerifier(hs_secret=SECRET, clock_tolerance_s=0).verify(token)


def test_wrong_secret_rejected() -> None:
    token = sign_hs256(secret=SECRET, sub="1", username="u", role="USER", expire_seconds=60)
    with pytest.raises(UnauthorizedError):
        JwtVerifier(hs_secret="another-secret-0123456789abcdef").verify(token)


def test_unsupported_alg_rejected() -> None:
    token = jwt.encode({"sub": "1"}, "", algorithm="none")
    with pytest.raises(UnauthorizedError):
        JwtVerifier(hs_secret=SECRET).verify(token)


def test_rs256_without_jwks_rejected() -> None:
    # 真造一个 RS256 token;未配置 JWKS 时必须拒绝(不能拿本地 secret 蒙混)
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode({"sub": "1", "exp": int(time.time()) + 60}, private_key, algorithm="RS256")
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    with pytest.raises(UnauthorizedError, match="未配置 JWKS"):
        JwtVerifier(hs_secret=SECRET).verify(token)
