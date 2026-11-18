
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
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Configure after deploying your license server
LICENSE_URL = "https://ow-m1j8.onrender.com"
PUBLIC_KEY = "vO72F0YykVMVVks1fK2aohyFHmoi69YSvstnbMfdu3k="

GRACE_HOURS = 12
RECHECK_MINUTES = 30
REQUEST_TIMEOUT = 10

def user_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")

    return root / "OWAutomation"


USER_DATA_DIR = user_data_dir()
KEY_FILE = USER_DATA_DIR / "license.key"
CACHE_FILE = USER_DATA_DIR / ".license_cache"
DEVICE_FILE = USER_DATA_DIR / ".device_id"
ACTIVATION_FILE = USER_DATA_DIR / ".activation"


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
        try:
            if DEVICE_FILE.exists():
                seed = DEVICE_FILE.read_text(encoding="utf-8").strip()

            if not seed:
                seed = secrets.token_hex(16)
                USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                DEVICE_FILE.write_text(seed, encoding="utf-8")
        except OSError as error:
            raise LicenseError(
                f"Could not access device data in {USER_DATA_DIR}: {error}"
            ) from error

    return hashlib.sha256(
        ("device|" + seed).encode()
    ).hexdigest()[:32]


def prompt_for_key():
    if sys.stdin is not None and (
        sys.stdin.isatty() or getattr(sys, "frozen", False)
    ):
        try:
            return input("License key daalo: ").strip()
        except EOFError as error:
            raise LicenseError("License key nahi mili") from error

    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError as error:
        raise LicenseError(
            "License key prompt could not be opened. Run this app in a console "
            f"or enable the desktop UI: {error}"
        ) from error

    try:
        root = tk.Tk()
        root.withdraw()
        try:
            return (simpledialog.askstring(
                "License activation",
                "Enter your license key:",
                parent=root,
            ) or "").strip()
        finally:
            root.destroy()
    except tk.TclError as error:
        raise LicenseError(
            "License key prompt could not be opened. Run this app in a console "
            f"or enable the desktop UI: {error}"
        ) from error


def prompt_for_activation(default_name="", default_key=""):
    if sys.stdin is not None and sys.stdin.isatty() and not getattr(sys, "frozen", False):
        name = input("Your name: ").strip()
        key = input("License key: ").strip() or default_key
        return name, key

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise LicenseError(
            "The activation screen could not be opened. Run this app in a "
            f"console or enable its desktop UI: {error}"
        ) from error

    try:
        root = tk.Tk()
        root.title("Activate your licence")
        root.resizable(False, False)
        root.configure(background="#f4f6fb")
        root.geometry("430x290")
        result = {"name": "", "key": ""}

        container = ttk.Frame(root, padding=24)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text="Activate your licence",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            container,
            text="Enter the name used when your licence was created.",
            wraplength=370,
        ).pack(anchor="w", pady=(5, 18))
        ttk.Label(container, text="Your name").pack(anchor="w")
        name_entry = ttk.Entry(container, width=48)
        name_entry.pack(fill="x", pady=(4, 12))
        name_entry.insert(0, default_name)
        ttk.Label(container, text="Licence key").pack(anchor="w")
        key_entry = ttk.Entry(container, width=48)
        key_entry.pack(fill="x", pady=(4, 16))
        key_entry.insert(0, default_key)
        message = ttk.Label(container, text="", foreground="#b42318")
        message.pack(anchor="w")

        def activate():
            name = " ".join(name_entry.get().split())
            key = key_entry.get().strip()
            if not name or not key:
                message.configure(text="Enter both your name and licence key.")
                return
            result.update(name=name, key=key)
            root.destroy()

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", side="bottom", pady=(8, 0))
        ttk.Button(buttons, text="Activate licence", command=activate).pack(
            side="right"
        )
        name_entry.bind("<Return>", lambda _event: key_entry.focus_set())
        key_entry.bind("<Return>", lambda _event: activate())
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        name_entry.focus_set()
        root.mainloop()
        return result["name"], result["key"]
    except tk.TclError as error:
        raise LicenseError(
            "The activation screen could not be opened. Run this app in a "
            f"console or enable its desktop UI: {error}"
        ) from error


def _protect_activation(data):
    if os.name != "nt":
        return b"PLAINTEXT:" + data

    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(
        len(data),
        ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    protected = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    protect = crypt32.CryptProtectData
    protect.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    protect.restype = wintypes.BOOL
    if not protect(
        ctypes.byref(source),
        "OW Automation licence activation",
        None,
        None,
        None,
        1,
        ctypes.byref(protected),
    ):
        raise LicenseError("Windows could not securely protect activation data")

    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        kernel32.LocalFree(protected.pbData)


def _unprotect_activation(data):
    if os.name != "nt":
        prefix = b"PLAINTEXT:"
        if not data.startswith(prefix):
            raise LicenseError("Saved activation data is not readable")
        return data[len(prefix):]

    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(
        len(data),
        ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    plaintext = DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    unprotect.restype = wintypes.BOOL
    if not unprotect(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        1,
        ctypes.byref(plaintext),
    ):
        raise LicenseError(
            "Saved activation data could not be unlocked on this Windows account"
        )

    try:
        return ctypes.string_at(plaintext.pbData, plaintext.cbData)
    finally:
        kernel32.LocalFree(plaintext.pbData)


def load_activation():
    if not ACTIVATION_FILE.exists():
        return None

    try:
        protected = ACTIVATION_FILE.read_bytes()
        activation = json.loads(_unprotect_activation(protected).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LicenseError(
            f"Could not read saved activation data from {USER_DATA_DIR}: {error}"
        ) from error

    if not isinstance(activation, dict) or not all(
        isinstance(activation.get(field), str) and activation[field].strip()
        for field in ("name", "key")
    ):
        raise LicenseError("Saved activation data is incomplete; contact support")
    return activation


def save_activation(name, key):
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        {"name": name, "key": key},
        separators=(",", ":"),
    ).encode("utf-8")
    temporary_file = ACTIVATION_FILE.with_suffix(".tmp")
    temporary_file.write_bytes(_protect_activation(serialized))
    try:
        os.chmod(temporary_file, 0o600)
    except OSError:
        if os.name != "nt":
            raise
    temporary_file.replace(ACTIVATION_FILE)


def read_key(prompt_if_missing=True):
    env = os.getenv("LICENSE_KEY", "").strip()

    if env:
        return env

    try:
        if KEY_FILE.exists():
            value = KEY_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError as error:
        raise LicenseError(
            f"Could not read saved license data from {USER_DATA_DIR}: {error}"
        ) from error

    if not prompt_if_missing:
        raise LicenseError("License key nahi mili")

    key = prompt_for_key()

    if not key:
        raise LicenseError("License key nahi mili")

    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(key, encoding="utf-8")
    except OSError as error:
        raise LicenseError(
            f"Could not save license data to {USER_DATA_DIR}: {error}"
        ) from error

    return key


def forget_key():
    for path in (KEY_FILE, CACHE_FILE, ACTIVATION_FILE):
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


def post_verify(name, key, device, nonce):
    body = json.dumps({
        "customerName": name,
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


def normalize_name(name):
    return " ".join(
        unicodedata.normalize("NFKC", str(name)).split()
    ).lower()


def from_cache(key, device, name):
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

        if normalize_name(payload.get("customerName", "")) != normalize_name(name):
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


def check(key=None, name=None):
    if (
        "PASTE_" in LICENSE_URL
        or "PASTE_" in PUBLIC_KEY
    ):
        raise LicenseError(
            "LICENSE_URL aur PUBLIC_KEY configure karo"
        )

    activation = load_activation()
    if activation:
        name = name or activation["name"]
        key = key or activation["key"]
    else:
        name = name or os.getenv("LICENSE_NAME", "").strip()
        key = key or os.getenv("LICENSE_KEY", "").strip()
        if not key:
            try:
                key = KEY_FILE.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                key = ""
            except OSError as error:
                raise LicenseError(
                    f"Could not read saved license data from {USER_DATA_DIR}: {error}"
                ) from error

    if not name or not key:
        name, key = prompt_for_activation(name or "", key or "")

    name = " ".join(unicodedata.normalize("NFKC", name).split())
    key = key.strip().upper()
    if not name:
        raise LicenseError("Customer name is required")
    if not key:
        raise LicenseError("License key is required")

    device = device_id()
    nonce = secrets.token_hex(16)

    try:
        reply = post_verify(name, key, device, nonce)

    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ) as error:
        cached = from_cache(key, device, name) if activation else None

        if cached:
            return cached

        raise LicenseError(
            f"License server connection failed: {error}"
        )

    if not isinstance(reply, dict):
        raise LicenseError("Invalid license server response")

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

    if not isinstance(payload, dict):
        raise LicenseError("Invalid server response")

    if (
        payload.get("key") != key
        or payload.get("device") != device
        or payload.get("nonce") != nonce
        or normalize_name(payload.get("customerName", "")) != normalize_name(name)
        or not payload.get("licenseId")
    ):
        raise LicenseError(
            "Server response request se match nahi karta"
        )

    if payload.get("expiresAt") and (
        payload["expiresAt"] < time.time() * 1000
    ):
        forget_key()
        raise LicenseError("This licence has expired.")

    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        save_activation(name, key)
        if KEY_FILE.exists():
            KEY_FILE.unlink()
        CACHE_FILE.write_text(
            json.dumps({
                "payload": payload_text,
                "sig": signature,
            }),
            encoding="utf-8",
        )
    except OSError as error:
        raise LicenseError(
            f"License verified, but could not save offline validation data "
            f"to {USER_DATA_DIR}: {error}"
        ) from error

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


def show_error_dialog(message):
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as error:
        if os.name != "nt":
            raise LicenseError(f"Could not show license error dialog: {error}") from error

        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "License error", 0x10)
        return

    try:
        root = tk.Tk()
        root.withdraw()
        try:
            messagebox.showerror("License error", message, parent=root)
        finally:
            root.destroy()
    except tk.TclError as error:
        if os.name != "nt":
            raise LicenseError(f"Could not show license error dialog: {error}") from error

        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "License error", 0x10)


def require():
    try:
        payload = check()

    except LicenseError as error:
        if sys.stdout is None and sys.stderr is None:
            show_error_dialog(str(error))
        else:
            print(f"License error: {error}")
        sys.exit(1)

    left = days_left(payload.get("expiresAt"))

    print(
        "License OK"
        + (f" ({left} din baaki)" if left is not None else " (no expiry)")
    )

    watch()
