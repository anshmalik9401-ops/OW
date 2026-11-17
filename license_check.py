
import base64
import hashlib
import json
import os
import platform
import secrets
import sys
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Configure after deploying your license server
LICENSE_URL = "http://localhost:5000"
PUBLIC_KEY = "vO72F0YykVMVVks1fK2aohyFHmoi69YSvstnbMfdu3k="

GRACE_HOURS = 12
RECHECK_MINUTES = 30
REQUEST_TIMEOUT = 10

BASE = Path(
    sys.executable if getattr(sys, "frozen", False) else __file__
).resolve().parent

KEY_FILE = BASE / "license.key"
CACHE_FILE = BASE / ".license_cache"
DEVICE_FILE = BASE / ".device_id"


class LicenseError(Exception):
    pass


def machine_seed():
    system = platform.system()

    try:
        if system == "Windows":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as handle:
                return str(winreg.QueryValueEx(handle, "MachineGuid")[0])

        elif system == "Darwin":
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout

            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]

        else:
            for name in (
                "/etc/machine-id",
                "/var/lib/dbus/machine-id",
            ):
                path = Path(name)
                if path.exists():
                    value = path.read_text().strip()
                    if value:
                        return value

    except Exception:
        pass

    return ""


def device_id():
    seed = machine_seed()

    if not seed:
        if DEVICE_FILE.exists():
            seed = DEVICE_FILE.read_text().strip()

        if not seed:
            seed = secrets.token_hex(16)
            DEVICE_FILE.write_text(seed)

    return hashlib.sha256(
        ("device|" + seed).encode()
    ).hexdigest()[:32]


def read_key(prompt_if_missing=True):
    env = os.getenv("LICENSE_KEY", "").strip()

    if env:
        return env

    if KEY_FILE.exists():
        value = KEY_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value

    if not prompt_if_missing:
        raise LicenseError("License key nahi mili")

    key = input("License key daalo: ").strip()

    if not key:
        raise LicenseError("License key nahi mili")

    KEY_FILE.write_text(key, encoding="utf-8")
    return key


def forget_key():
    for path in (KEY_FILE, CACHE_FILE):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def verify_signature(payload_text, sig_b64):
    try:
        public_bytes = base64.b64decode(
            PUBLIC_KEY, validate=True
        )
        signature = base64.b64decode(
            sig_b64, validate=True
        )

        public = Ed25519PublicKey.from_public_bytes(
            public_bytes
        )

        public.verify(
            signature,
            payload_text.encode("utf-8"),
        )

        return True

    except (
        InvalidSignature,
        ValueError,
        TypeError,
    ):
        return False


def post_verify(key, device, nonce):
    body = json.dumps({
        "key": key,
        "device": device,
        "nonce": nonce,
    }).encode()

    req = urllib.request.Request(
        LICENSE_URL.rstrip("/") + "/api/verify",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "license-client/1",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req, timeout=REQUEST_TIMEOUT
    ) as response:
        return json.loads(response.read().decode())


def days_left(expires_at):
    if not expires_at:
        return None

    return max(
        0,
        int((expires_at / 1000 - time.time()) // 86400),
    )


def from_cache(key, device):
    try:
        data = json.loads(
            CACHE_FILE.read_text(encoding="utf-8")
        )

        if not verify_signature(
            data["payload"], data["sig"]
        ):
            return None

        payload = json.loads(data["payload"])

        if payload.get("key") != key:
            return None

        if payload.get("device") != device:
            return None

        age_hours = (
            time.time() * 1000 - payload["ts"]
        ) / 3600000

        if age_hours < 0 or age_hours > GRACE_HOURS:
            return None

        expires = payload.get("expiresAt")

        if expires and expires < time.time() * 1000:
            return None

        return payload

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ):
        return None


def check(key=None):
    if (
        "PASTE_" in LICENSE_URL
        or "PASTE_" in PUBLIC_KEY
    ):
        raise LicenseError(
            "LICENSE_URL aur PUBLIC_KEY configure karo"
        )

    key = key or read_key()
    device = device_id()
    nonce = secrets.token_hex(16)

    try:
        reply = post_verify(key, device, nonce)

    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ) as error:
        cached = from_cache(key, device)

        if cached:
            return cached

        raise LicenseError(
            f"License server connection failed: {error}"
        )

    if not reply.get("ok"):
        forget_key()
        raise LicenseError(
            reply.get("reason") or "License valid nahi hai"
        )

    payload_text = reply.get("payload", "")
    signature = reply.get("sig", "")

    if not verify_signature(payload_text, signature):
        raise LicenseError(
            "Server signature verification failed"
        )

    try:
        payload = json.loads(payload_text)
    except ValueError:
        raise LicenseError("Invalid server response")

    if (
        payload.get("key") != key
        or payload.get("device") != device
        or payload.get("nonce") != nonce
    ):
        raise LicenseError(
            "Server response request se match nahi karta"
        )

    if payload.get("expiresAt") and (
        payload["expiresAt"] < time.time() * 1000
    ):
        forget_key()
        raise LicenseError("License expire ho gaya")

    CACHE_FILE.write_text(
        json.dumps({
            "payload": payload_text,
            "sig": signature,
        }),
        encoding="utf-8",
    )

    return payload


def watch(interval_minutes=RECHECK_MINUTES):
    def loop():
        while True:
            time.sleep(interval_minutes * 60)

            try:
                check()

            except LicenseError as error:
                print(f"\nLicense band ho gaya: {error}")
                os._exit(1)

    threading.Thread(
        target=loop,
        daemon=True,
    ).start()


def require():
    try:
        payload = check()

    except LicenseError as error:
        print(f"License error: {error}")
        sys.exit(1)

    left = days_left(payload.get("expiresAt"))

    print(
        "License OK"
        + (f" ({left} din baaki)" if left is not None else " (no expiry)")
    )

    watch()
