import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import license_check


ROOT = Path(__file__).resolve().parents[1]
ADMIN_TOKEN = "test-admin-token-that-is-at-least-32-chars"


class LicenseServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_file = Path(self.temporary_directory.name) / "licenses.json"
        self.client_data = Path(self.temporary_directory.name) / "client"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process = None
        self.start_server()
        self.addCleanup(self.stop_server)

    def start_server(self):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PORT": str(self.port),
            "ADMIN_TOKEN": ADMIN_TOKEN,
            "DATA_FILE": str(self.data_file),
            "NODE_ENV": "test",
        }
        for variable in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
            if variable in os.environ:
                env[variable] = os.environ[variable]
        self.process = subprocess.Popen(
            ["node", str(ROOT / "Server.js")],
            cwd=self.temporary_directory.name,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output = self.process.stdout.read()
                self.process.stdout.close()
                self.fail(f"Licence server exited during startup:\n{output}")
            try:
                self.request("GET", "/health")
                return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        self.fail("Licence server did not become ready")

    def stop_server(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.process and self.process.stdout and not self.process.stdout.closed:
            self.process.stdout.close()

    def restart_server(self):
        self.stop_server()
        self.start_server()

    def request(self, method, route, body=None, admin=True):
        headers = {"Content-Type": "application/json"}
        if admin:
            headers["Authorization"] = "Bearer " + ADMIN_TOKEN
        request = urllib.request.Request(
            self.base_url + route,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def verify(self, name, key, device):
        return self.request(
            "POST",
            "/api/verify",
            {
                "customerName": name,
                "key": key,
                "device": device,
                "nonce": "integration-test-nonce",
            },
            admin=False,
        )

    def run_client_check(self, name, key, device):
        _status, public_data = self.request("GET", "/api/public-key", admin=False)
        with (
            patch.object(license_check, "LICENSE_URL", self.base_url),
            patch.object(license_check, "PUBLIC_KEY", public_data["publicKey"]),
            patch.object(license_check, "USER_DATA_DIR", self.client_data),
            patch.object(license_check, "KEY_FILE", self.client_data / "license.key"),
            patch.object(license_check, "CACHE_FILE", self.client_data / ".license_cache"),
            patch.object(license_check, "ACTIVATION_FILE", self.client_data / ".activation"),
            patch.object(license_check, "device_id", return_value=device),
        ):
            return license_check.check(key=key, name=name)

    def test_name_activation_binding_status_and_persistence(self):
        status, _ = self.request("GET", "/api/admin/keys", admin=False)
        self.assertEqual(status, 401)

        status, harshita = self.request(
            "POST",
            "/api/admin/keys",
            {"customerName": "Harshita", "days": 30},
        )
        self.assertEqual(status, 200)
        self.assertEqual(harshita["customerName"], "Harshita")
        self.assertEqual(harshita["status"], "Inactive")
        self.assertTrue(harshita["id"])

        status, another = self.request(
            "POST",
            "/api/admin/keys",
            {"customerName": "Another Customer", "days": 30},
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(harshita["id"], another["id"])
        self.assertNotEqual(harshita["key"], another["key"])

        status, searched = self.request("GET", "/api/admin/keys?q=harshita")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in searched], [harshita["id"]])
        status, searched = self.request(
            "GET", "/api/admin/keys?q=" + harshita["key"].lower()
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in searched], [harshita["id"]])

        with self.assertRaisesRegex(
            license_check.LicenseError, "Name and licence key do not match"
        ):
            self.run_client_check("Someone Else", harshita["key"], "device-a")
        with self.assertRaisesRegex(
            license_check.LicenseError, "Invalid licence key"
        ):
            self.run_client_check("Harshita", "WRONG-KEY", "device-a")

        payload = self.run_client_check(
            "  hARSHITA   ", harshita["key"], "device-a"
        )
        self.assertEqual(payload["licenseId"], harshita["id"])
        self.assertTrue((self.client_data / ".activation").is_file())
        self.assertTrue((self.client_data / ".license_cache").is_file())

        status, response = self.verify("Harshita", harshita["key"], "device-b")
        self.assertEqual(status, 200)
        self.assertFalse(response["ok"])
        self.assertEqual(
            response["reason"],
            "This licence is already activated on another device.",
        )

        self.restart_server()
        payload = self.run_client_check("", "", "device-a")
        self.assertEqual(payload["licenseId"], harshita["id"])

        status, list_after_restart = self.request("GET", "/api/admin/keys")
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in list_after_restart}, {
            harshita["id"],
            another["id"],
        })
        current_harshita = next(
            item for item in list_after_restart if item["id"] == harshita["id"]
        )
        self.assertEqual(current_harshita["status"], "Active")
        self.assertEqual(current_harshita["activationStatus"], "Activated")
        self.assertEqual(current_harshita["activatedDevice"], "device-a")

        status, response = self.verify("Another Customer", another["key"], "device-c")
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])

        status, revoked = self.request(
            "POST", f"/api/admin/keys/{another['key']}/revoke"
        )
        self.assertEqual(status, 200)
        self.assertEqual(revoked["status"], "Revoked")
        status, response = self.verify(
            "Another Customer", another["key"], "device-c"
        )
        self.assertFalse(response["ok"])

        status, reset = self.request(
            "POST", f"/api/admin/keys/{harshita['key']}/reset-devices"
        )
        self.assertEqual(status, 200)
        self.assertEqual(reset["status"], "Inactive")
        status, response = self.verify("Harshita", harshita["key"], "device-b")
        self.assertTrue(response["ok"])

        _status, race = self.request(
            "POST",
            "/api/admin/keys",
            {"customerName": "Race Customer", "days": 30},
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda device: self.verify("Race Customer", race["key"], device)[1],
                ("race-device-a", "race-device-b"),
            ))
        self.assertEqual(sum(bool(result["ok"]) for result in results), 1)

        status, expired = self.request(
            "POST",
            "/api/admin/keys",
            {"customerName": "Expired Customer", "days": 1},
        )
        self.assertEqual(status, 200)
        self.stop_server()
        records = json.loads(self.data_file.read_text(encoding="utf-8"))
        for record in records["keys"]:
            if record["key"] == expired["key"]:
                record["expiresAt"] = int(time.time() * 1000) - 1000
        self.data_file.write_text(json.dumps(records), encoding="utf-8")
        self.start_server()

        status, listed = self.request("GET", "/api/admin/keys")
        expired_record = next(item for item in listed if item["id"] == expired["id"])
        self.assertEqual(expired_record["status"], "Expired")
        status, response = self.verify(
            "Expired Customer", expired["key"], "device-d"
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["reason"], "This licence has expired.")


if __name__ == "__main__":
    unittest.main()
