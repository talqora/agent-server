"""RS256/JWKS 联邦身份端到端:本地 JWKS 服务 + 真 RS256 token → zero-touch 建本地用户。

模拟 our-chat 作为 IdP 的真实跨服务鉴权路径(本地无 our-chat,故自建 JWKS 端点):
  1. 生成 RSA 密钥对,起本地 JWKS 服务(/.well-known/jwks.json);
  2. 以 OAUTH_ISSUER/OAUTH_JWKS_URI 指向它,另起一个 rag-http(:3104);
  3. 用私钥签 RS256 token(iss/aud/kid 齐备)→ /auth/me → 首次 zero-touch 建本地用户;
  4. 二次请求命中同一本地用户(联合身份映射稳定);
  5. 联邦用户可正常建会话(归属链路打通);
  6. 反例:aud 不匹配 401、过期 401。

用法:``uv run python tools/e2e_jwks_test.py``(自起自停 :3104 实例与 JWKS 服务)
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PORT = 3104
JWKS_PORT = 3999
ISSUER = f"http://localhost:{JWKS_PORT}"
AUDIENCE = "agent-server"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  [{detail}]" if detail and not ok else ""))


def b64url(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def start_jwks_server(jwks: dict[str, object]) -> HTTPServer:
    payload = json.dumps(jwks).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server 约定
            if self.path == "/.well-known/jwks.json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args: object) -> None:  # 静音访问日志
            return

    server = HTTPServer(("127.0.0.1", JWKS_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    kid = "e2e-key-1"
    server = start_jwks_server(
        {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": kid,
                    "use": "sig",
                    "alg": "RS256",
                    "n": b64url(public_numbers.n),
                    "e": b64url(public_numbers.e),
                }
            ]
        }
    )
    print(f"JWKS 服务已启动: {ISSUER}/.well-known/jwks.json")

    env = {
        **os.environ,
        "PORT": str(PORT),
        "OAUTH_ISSUER": ISSUER,
        "OAUTH_JWKS_URI": f"{ISSUER}/.well-known/jwks.json",
    }
    proc = subprocess.Popen(
        ["uv", "run", "rag-http"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = httpx.Client(base_url=f"http://localhost:{PORT}/api", timeout=30)
    try:
        # 等待实例就绪
        ready = False
        for _ in range(60):
            try:
                if client.get("/health").status_code == 200:
                    ready = True
                    break
            except httpx.TransportError:
                pass
            time.sleep(1)
        check("启用 JWKS 的实例就绪(:3104)", ready)
        if not ready:
            return 1

        def sign(sub: str, *, aud: str = AUDIENCE, exp_delta: int = 3600) -> str:
            return jwt.encode(
                {
                    "sub": sub,
                    "iss": ISSUER,
                    "aud": aud,
                    "exp": int(time.time()) + exp_delta,
                    "username": "oc_e2e_user",
                },
                private_key,
                algorithm="RS256",
                headers={"kid": kid},
            )

        print("== 1. RS256 token → zero-touch 建本地用户 ==")
        sub = f"oc-{uuid.uuid4().hex[:8]}"
        token = sign(sub)
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        check("RS256 验签通过 200", me.status_code == 200, me.text[:200])
        body = me.json() if me.status_code == 200 else {}
        check("联邦用户已建(username/roleCode)", body.get("username") == "oc_e2e_user", str(body))
        first_id = body.get("id")

        print("== 2. 二次请求命中同一本地用户(映射稳定) ==")
        me2 = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        check("同一本地 id", me2.json().get("id") == first_id, f"{first_id} vs {me2.json()}")

        print("== 3. 联邦用户归属链路(建会话) ==")
        conv = client.post("/conversations", headers={"Authorization": f"Bearer {token}"}, json={})
        check("建会话 201", conv.status_code == 201, conv.text[:200])

        print("== 4. 反例:aud 不匹配 / 过期 ==")
        bad_aud = client.get(
            "/auth/me", headers={"Authorization": f"Bearer {sign(sub, aud='other-service')}"}
        )
        check("aud 不匹配 401", bad_aud.status_code == 401, str(bad_aud.status_code))
        expired = client.get(
            "/auth/me", headers={"Authorization": f"Bearer {sign(sub, exp_delta=-60)}"}
        )
        check("过期 token 401", expired.status_code == 401, str(expired.status_code))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        server.shutdown()

    print()
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        print("失败项:")
        for name in FAIL:
            print(f"  - {name}")
        return 1
    print("RS256/JWKS 联邦身份端到端通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
