import argparse
import json
import os
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RELEASE_DIR = ROOT / "release"
PACKAGE_DIR = RELEASE_DIR / "Automation_Package"
STAGING_DIR = RELEASE_DIR / ".Automation_Package_staging"
BACKUP_DIR = RELEASE_DIR / ".Automation_Package_previous"
ZIP_FILE = RELEASE_DIR / "Automation_Package.zip"
REQUIRED_EXECUTABLES = (
    "Automation.exe",
    "PhoneGenerator.exe",
    "UploadConsent.exe",
)
FORBIDDEN_NAMES = {
    ".env",
    ".license_cache",
    ".device_id",
    "admin.html",
    "admin_token",
    "licenses.json",
    "license.key",
    "server.js",
}


def playwright_browser_source():
    import playwright

    manifest_path = (
        Path(playwright.__file__).resolve().parent
        / "driver"
        / "package"
        / "browsers.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    revision = next(
        browser["revision"]
        for browser in manifest["browsers"]
        if browser["name"] == "chromium"
    )
    browser_dir_names = (
        f"chromium-{revision}",
        f"chromium_headless_shell-{revision}",
    )
    roots = []

    configured_root = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if configured_root and configured_root != "0":
        roots.append(Path(configured_root).expanduser())
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "ms-playwright")

    for root in roots:
        candidates = [root / name for name in browser_dir_names]
        if all(candidate.is_dir() for candidate in candidates):
            return candidates

    checked = ", ".join(
        str(root / name) for root in roots for name in browser_dir_names
    ) or (
        "the configured Playwright browser cache"
    )
    raise FileNotFoundError(
        f"Playwright Chromium {revision} was not found. Checked: {checked}"
    )


def verify_package_tree(package_dir):
    actual_top_level = {path.name for path in package_dir.iterdir()}
    expected_top_level = {
        *REQUIRED_EXECUTABLES,
        "code.html",
        "data.txt",
        "README.txt",
        "output",
        "ms-playwright",
    }
    if (package_dir / "template.html").is_file():
        expected_top_level.add("template.html")
    if actual_top_level != expected_top_level:
        raise RuntimeError(
            "Customer package contents do not match the allowlist: "
            f"{sorted(actual_top_level)}"
        )

    for path in package_dir.rglob("*"):
        if path.name.casefold() in FORBIDDEN_NAMES:
            raise RuntimeError(f"Forbidden customer file found: {path}")
        if path.is_file() and path.suffix.casefold() in {
            ".key",
            ".pem",
            ".p12",
            ".pfx",
            ".private",
        }:
            raise RuntimeError(f"Private key material found in package: {path}")


def write_readme(package_dir):
    readme = r"""AUTOMATION SOFTWARE - CUSTOMER PACKAGE

Keep the EXE files, HTML files, data.txt, and ms-playwright folder together.
Extract the complete ZIP before using the software. You can double-click an
EXE, or open PowerShell in the extracted Automation_Package folder and run:

1. Prepare records:
   .\PhoneGenerator.exe
2. Process records and create screenshots/reports in output:
   .\Automation.exe
3. Upload consent files; enter the OTP email when prompted:
   .\UploadConsent.exe
4. Or specify the OTP email directly:
   .\UploadConsent.exe --email name@example.com

Sign in with your own account and enter the OTP in the browser.
On first launch of any EXE, enter the licence details provided by the
administrator:
   Your Name: the customer name the administrator used
   Licence Key: the matching key
Then select "Activate licence". The same licence works with all three EXEs
on this PC. It is bound to this PC; a copied key will not activate on another
PC. The administrator can revoke the licence or reset its device binding.

The activation session is protected with Windows DPAPI under your Windows
user profile. The signed validation cache and device binding data are also
stored in %LOCALAPPDATA%\OWAutomation, not in this package.
Internet access is required for online license verification. The existing
signed offline grace period remains available for up to 12 hours during
temporary outages.

Do not delete the ms-playwright folder. It contains the bundled Chromium
required by Automation.exe and UploadConsent.exe.
"""
    (package_dir / "README.txt").write_text(readme, encoding="utf-8")


def create_package(create_zip=True):
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    for temporary_dir in (STAGING_DIR, BACKUP_DIR):
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
    STAGING_DIR.mkdir()

    try:
        for name in REQUIRED_EXECUTABLES:
            executable = ROOT / "dist" / name
            if not executable.is_file():
                raise FileNotFoundError(f"Built executable is missing: {executable}")
            shutil.copy2(executable, STAGING_DIR / name)

        code_page = ROOT / "code.html"
        if not code_page.is_file():
            raise FileNotFoundError(f"Required customer page is missing: {code_page}")
        shutil.copy2(code_page, STAGING_DIR / code_page.name)
        template = ROOT / "template.html"
        if template.is_file():
            shutil.copy2(template, STAGING_DIR / template.name)

        (STAGING_DIR / "data.txt").write_text(
            "Name\tEmail\tNumber\tDate\tCategory\n",
            encoding="utf-8",
        )
        (STAGING_DIR / "output").mkdir()
        write_readme(STAGING_DIR)

        browser_sources = playwright_browser_source()
        browser_destination = STAGING_DIR / "ms-playwright"
        browser_destination.mkdir()
        for browser_source in browser_sources:
            shutil.copytree(
                browser_source,
                browser_destination / browser_source.name,
            )
        verify_package_tree(STAGING_DIR)

        if PACKAGE_DIR.exists():
            PACKAGE_DIR.replace(BACKUP_DIR)
        try:
            STAGING_DIR.replace(PACKAGE_DIR)
        except OSError:
            shutil.copytree(STAGING_DIR, PACKAGE_DIR)
            shutil.rmtree(STAGING_DIR)
        verify_package_tree(PACKAGE_DIR)
        if BACKUP_DIR.exists():
            shutil.rmtree(BACKUP_DIR)

        if create_zip:
            temporary_zip = ZIP_FILE.with_suffix(".zip.tmp")
            if temporary_zip.exists():
                temporary_zip.unlink()
            try:
                with zipfile.ZipFile(
                    temporary_zip,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    for path in sorted(PACKAGE_DIR.rglob("*")):
                        if path.is_dir():
                            archive.writestr(
                                path.relative_to(RELEASE_DIR).as_posix().rstrip("/") + "/",
                                "",
                            )
                        else:
                            archive.write(
                                path,
                                path.relative_to(RELEASE_DIR).as_posix(),
                            )
                temporary_zip.replace(ZIP_FILE)
            finally:
                if temporary_zip.exists():
                    temporary_zip.unlink()
    except Exception:
        if STAGING_DIR.exists():
            shutil.rmtree(STAGING_DIR)
        if BACKUP_DIR.exists() and not PACKAGE_DIR.exists():
            BACKUP_DIR.replace(PACKAGE_DIR)
        raise

    print(f"Customer package: {PACKAGE_DIR}")
    if create_zip:
        print(f"ZIP: {ZIP_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Create and validate the package directory without writing its ZIP",
    )
    arguments = parser.parse_args()
    create_package(create_zip=not arguments.no_zip)
