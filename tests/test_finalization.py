import base64
import json
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import Automation
import license_check
import Upload_consent


class LicenseStorageTests(unittest.TestCase):
    def test_windowed_app_uses_license_key_dialog(self):
        root = MagicMock()
        tkinter_module = types.ModuleType("tkinter")
        tkinter_module.Tk = MagicMock(return_value=root)
        tkinter_module.TclError = RuntimeError
        dialog_module = types.ModuleType("tkinter.simpledialog")
        dialog_module.askstring = MagicMock(return_value="CUSTOMER-KEY")

        with (
            patch.dict(
                "sys.modules",
                {
                    "tkinter": tkinter_module,
                    "tkinter.simpledialog": dialog_module,
                },
            ),
            patch.object(license_check.sys, "stdin", None),
        ):
            self.assertEqual(license_check.prompt_for_key(), "CUSTOMER-KEY")

        root.withdraw.assert_called_once()
        root.destroy.assert_called_once()
        dialog_module.askstring.assert_called_once()

    def test_activation_form_collects_name_and_key(self):
        root = MagicMock()
        tkinter_module = types.ModuleType("tkinter")
        tkinter_module.Tk = MagicMock(return_value=root)
        tkinter_module.TclError = RuntimeError
        ttk_module = types.ModuleType("tkinter.ttk")
        name_entry = MagicMock()
        name_entry.get.return_value = "  Harshita   "
        key_entry = MagicMock()
        key_entry.get.return_value = "HARS-2026-TEST"
        entries = iter((name_entry, key_entry))

        def widget(_parent, **options):
            if options.get("text") == "Activate licence":
                options["command"]()
            return MagicMock()

        ttk_module.Frame = widget
        ttk_module.Label = widget
        ttk_module.Entry = lambda *_args, **_kwargs: next(entries)
        ttk_module.Button = widget
        tkinter_module.ttk = ttk_module

        with (
            patch.dict(
                "sys.modules",
                {"tkinter": tkinter_module, "tkinter.ttk": ttk_module},
            ),
            patch.object(license_check.sys, "stdin", None),
        ):
            self.assertEqual(
                license_check.prompt_for_activation(),
                ("Harshita", "HARS-2026-TEST"),
            )

        root.destroy.assert_called_once()

    def test_windowed_license_errors_are_visible(self):
        root = MagicMock()
        tkinter_module = types.ModuleType("tkinter")
        tkinter_module.Tk = MagicMock(return_value=root)
        tkinter_module.TclError = RuntimeError
        messagebox_module = types.ModuleType("tkinter.messagebox")
        messagebox_module.showerror = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "tkinter": tkinter_module,
                "tkinter.messagebox": messagebox_module,
            },
        ):
            license_check.show_error_dialog("License rejected")

        messagebox_module.showerror.assert_called_once()
        self.assertIn("License rejected", messagebox_module.showerror.call_args.args)
        root.destroy.assert_called_once()

    def test_first_key_entry_is_saved_under_user_data_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory) / "OWAutomation"
            key_file = data_dir / "license.key"
            with (
                patch.object(license_check, "USER_DATA_DIR", data_dir),
                patch.object(license_check, "KEY_FILE", key_file),
                patch.object(license_check, "prompt_for_key", return_value="TEST-KEY"),
            ):
                self.assertEqual(license_check.read_key(), "TEST-KEY")

            self.assertEqual(key_file.read_text(encoding="utf-8"), "TEST-KEY")

    def test_offline_cache_requires_matching_device_and_expiry(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        current_time = int(time.time() * 1000)
        payload = {
            "key": "TEST-KEY",
            "customerName": "Harshita",
            "licenseId": "license-a",
            "device": "device-a",
            "ts": current_time,
            "expiresAt": current_time + 60_000,
        }
        payload_text = json.dumps(payload)
        signature = base64.b64encode(
            private_key.sign(payload_text.encode("utf-8"))
        ).decode("ascii")

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_file = Path(temporary_directory) / ".license_cache"
            cache_file.write_text(
                json.dumps({"payload": payload_text, "sig": signature}),
                encoding="utf-8",
            )
            with (
                patch.object(license_check, "CACHE_FILE", cache_file),
                patch.object(
                    license_check,
                    "PUBLIC_KEY",
                    base64.b64encode(public_key).decode("ascii"),
                ),
            ):
                self.assertIsNotNone(
                    license_check.from_cache("TEST-KEY", "device-a", "harshita")
                )
                self.assertIsNone(
                    license_check.from_cache("TEST-KEY", "device-b", "Harshita")
                )
                self.assertIsNone(
                    license_check.from_cache("OTHER-KEY", "device-a", "Harshita")
                )
                self.assertIsNone(
                    license_check.from_cache("TEST-KEY", "device-a", "Another name")
                )

                payload["expiresAt"] = current_time - 1
                expired_text = json.dumps(payload)
                expired_signature = base64.b64encode(
                    private_key.sign(expired_text.encode("utf-8"))
                ).decode("ascii")
                cache_file.write_text(
                    json.dumps({"payload": expired_text, "sig": expired_signature}),
                    encoding="utf-8",
                )
                self.assertIsNone(
                    license_check.from_cache("TEST-KEY", "device-a", "Harshita")
                )

    def test_server_rejection_clears_saved_key_and_cache(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            key_file = data_dir / "license.key"
            cache_file = data_dir / ".license_cache"
            activation_file = data_dir / ".activation"
            with (
                patch.object(license_check, "USER_DATA_DIR", data_dir),
                patch.object(license_check, "KEY_FILE", key_file),
                patch.object(license_check, "CACHE_FILE", cache_file),
                patch.object(license_check, "ACTIVATION_FILE", activation_file),
                patch.object(
                    license_check,
                    "prompt_for_activation",
                    return_value=("Harshita", "REVOKED-KEY"),
                ),
                patch.object(license_check, "device_id", return_value="device-a"),
                patch.object(
                    license_check,
                    "post_verify",
                    return_value={"ok": False, "reason": "revoked"},
                ),
            ):
                key_file.write_text("REVOKED-KEY", encoding="utf-8")
                cache_file.write_text("cached", encoding="utf-8")
                with self.assertRaises(license_check.LicenseError):
                    license_check.check()

            self.assertFalse(key_file.exists())
            self.assertFalse(cache_file.exists())

    def test_valid_license_is_reused_and_still_checked_online(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        def signed_reply(name, key, device, nonce):
            payload_text = json.dumps({
                "key": key,
                "customerName": name,
                "licenseId": "license-a",
                "device": device,
                "nonce": nonce,
                "ts": int(time.time() * 1000),
                "expiresAt": None,
            })
            signature = base64.b64encode(
                private_key.sign(payload_text.encode("utf-8"))
            ).decode("ascii")
            return {"ok": True, "payload": payload_text, "sig": signature}

        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            key_file = data_dir / "license.key"
            cache_file = data_dir / ".license_cache"
            activation_file = data_dir / ".activation"
            online_check = MagicMock(side_effect=signed_reply)
            with (
                patch.object(license_check, "USER_DATA_DIR", data_dir),
                patch.object(license_check, "KEY_FILE", key_file),
                patch.object(license_check, "CACHE_FILE", cache_file),
                patch.object(license_check, "ACTIVATION_FILE", activation_file),
                patch.object(license_check, "DEVICE_FILE", data_dir / ".device_id"),
                patch.object(license_check, "PUBLIC_KEY", base64.b64encode(public_key).decode("ascii")),
                patch.object(
                    license_check,
                    "prompt_for_activation",
                    return_value=("Harshita", "VALID-TEST-KEY"),
                ) as prompt_activation,
                patch.object(license_check, "device_id", return_value="device-a"),
                patch.object(license_check, "post_verify", online_check),
            ):
                license_check.check()
                license_check.check()

            prompt_activation.assert_called_once()
            self.assertEqual(online_check.call_count, 2)
            self.assertFalse(key_file.exists())
            self.assertTrue(activation_file.is_file())
            self.assertTrue(cache_file.is_file())


class LocalServerTests(unittest.TestCase):
    def test_server_serves_customer_html_but_not_data_or_admin_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            (base_dir / "code.html").write_text("<html>customer page</html>", encoding="utf-8")
            (base_dir / "data.txt").write_text("private customer data", encoding="utf-8")
            (base_dir / "admin.html").write_text("<html>admin</html>", encoding="utf-8")
            (base_dir / "Server.js").write_text("server implementation", encoding="utf-8")
            with (
                patch.object(Automation, "BASE_DIR", base_dir),
                patch.object(Automation, "CODE_PAGE", base_dir / "code.html"),
            ):
                server, thread, server_url = Automation.start_local_http_server()
                try:
                    with urllib.request.urlopen(f"{server_url}/code.html", timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"customer page", response.read())

                    for denied_path in ("data.txt", "admin.html", "Server.js"):
                        with self.subTest(path=denied_path):
                            with self.assertRaises(urllib.error.HTTPError) as error:
                                urllib.request.urlopen(
                                    f"{server_url}/{denied_path}",
                                    timeout=5,
                                )
                            self.assertEqual(error.exception.code, 404)
                            error.exception.close()
                finally:
                    Automation.stop_local_http_server(server, thread)

                self.assertFalse(thread.is_alive())


class UploadEmailTests(unittest.TestCase):
    def test_prompts_for_selected_email_each_run(self):
        with (
            patch.object(Upload_consent, "LOGIN_EMAIL", ""),
            patch("builtins.input", return_value="second@example.com") as prompt,
        ):
            self.assertEqual(
                Upload_consent.prompt_for_login_email(),
                "second@example.com",
            )
        prompt.assert_called_once()

    def test_cli_email_skips_prompt_and_invalid_email_is_rejected(self):
        with patch("builtins.input") as prompt:
            self.assertEqual(
                Upload_consent.prompt_for_login_email("third@example.com"),
                "third@example.com",
            )
            prompt.assert_not_called()

        with self.assertRaises(ValueError):
            Upload_consent.prompt_for_login_email("not-an-email")

    def test_selected_email_replaces_browser_value_before_requesting_otp(self):
        page = MagicMock()
        email_box = page.get_by_role.return_value
        email_box.input_value.return_value = "first@example.com"
        with patch.object(Upload_consent, "logged_in", return_value=False):
            Upload_consent.start_login(page, "third@example.com")

        email_box.fill.assert_called_once_with("third@example.com")
        page.get_by_role.assert_any_call("button", name="GET OTP")
        page.get_by_role.return_value.click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
