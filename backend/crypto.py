import base64, hmac, hashlib, os, time, json
from typing import Optional, Tuple
def b64url_encode(b: bytes) -> str: return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def b64url_decode(s: str) -> bytes: return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
def hash_password(pw: str, *, iterations: int = 200_000, salt: Optional[bytes]=None) -> str:
    salt = os.urandom(16) if salt is None else salt
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iterations, dklen=32)
    return f"pbkdf2$sha256${iterations}${b64url_encode(salt)}${b64url_encode(dk)}"
def verify_password(pw: str, enc: str) -> bool:
    try:
        scheme, algo, iters, sb64, db64 = enc.split("$")
        assert scheme=="pbkdf2" and algo=="sha256"
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), b64url_decode(sb64), int(iters), dklen=32)
        return hmac.compare_digest(dk, b64url_decode(db64))
    except Exception: return False
HEADER = {"alg":"HS256","typ":"JWT"}
def sign_token(payload: dict, secret: str, expires_in: int = 3600) -> str:
    data = payload.copy(); data["exp"] = int(time.time()) + expires_in
    h = b64url_encode(json.dumps(HEADER, separators=(",",":")).encode())
    p = b64url_encode(json.dumps(data, separators=(",",":")).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64url_encode(sig)}"
def verify_token(token: str, secret: str) -> Tuple[bool, Optional[dict], str]:
    try:
        h,p,s = token.split("."); signing=f"{h}.{p}".encode()
        if not hmac.compare_digest(b64url_decode(s), hmac.new(secret.encode(), signing, hashlib.sha256).digest()): return False, None, "bad-signature"
        payload = json.loads(b64url_decode(p).decode())
        if payload.get("exp",0) < int(time.time()): return False, None, "expired"
        return True, payload, ""
    except Exception: return False, None, "invalid"
