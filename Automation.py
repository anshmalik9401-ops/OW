import re
import json
import asyncio
import csv
import logging
import shutil
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from playwright.async_api import async_playwright

import license_check

BASE_DIR       = Path(__file__).parent
TEMPLATE       = BASE_DIR / "template.html"
CODE_PAGE      = BASE_DIR / "code.html"
DATA_FILE      = BASE_DIR / "data.txt"
OUTPUT_DIR     = BASE_DIR / "output"
TRACKER_FILE   = BASE_DIR / "processed_numbers.json"
REPORT_FILE    = OUTPUT_DIR / "processing_report.csv"
LOG_FILE       = OUTPUT_DIR / "automation.log"
SERVER_URL     = "http://127.0.0.1:8000"
VIEWPORT_W     = 1000
VIEWPORT_H     = 900


def load_processed_numbers() -> set:
    if TRACKER_FILE.exists():
        try:
            data = json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
                raise ValueError("processed_numbers.json must contain a JSON list of strings")
            return set(data)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            logging.error("Could not read processing tracker %s: %s", TRACKER_FILE, error)
            return set()
    return set()


def backup_tracker_file() -> Path | None:
    if not TRACKER_FILE.exists():
        return None
    backup_file = TRACKER_FILE.with_suffix(TRACKER_FILE.suffix + ".bak")
    suffix = 1
    while backup_file.exists():
        backup_file = TRACKER_FILE.with_suffix(TRACKER_FILE.suffix + f".bak.{suffix}")
        suffix += 1
    shutil.copy2(TRACKER_FILE, backup_file)
    return backup_file


def save_processed_numbers(numbers: set) -> None:
    temporary_file = TRACKER_FILE.with_suffix(".json.tmp")
    temporary_file.write_text(json.dumps(sorted(numbers), indent=2), encoding="utf-8")
    temporary_file.replace(TRACKER_FILE)


def parse_data(filepath: Path) -> list[dict]:
    if not filepath.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")

    records = []
    with filepath.open("r", encoding="utf-8-sig", newline="") as source:
        first_line = source.readline()
        source.seek(0)
        if "\t" in first_line:
            reader = csv.DictReader(source, delimiter="\t")
            for line_number, row in enumerate(reader, start=2):
                try:
                    number = re.sub(r"\D", "", (row.get("Number") or "").strip())
                    record = {
                        "name": (row.get("Name") or "").strip(),
                        "email": (row.get("Email") or "").strip(),
                        "number": number,
                        "date": (row.get("Date") or "").strip(),
                        "category": (row.get("Category") or "").strip(),
                    }
                    if not record["name"] or not record["email"] or not re.fullmatch(r"\d{10}", number):
                        raise ValueError("required name/email or valid 10-digit number is missing")
                    records.append(record)
                except (AttributeError, ValueError) as error:
                    logging.error("Invalid data.txt row %d: %s", line_number, error)
            return records

        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.strip()
            if not line or re.match(r"(?i)^name\b", line) or set(line) == {"-"}:
                continue
            email_match = re.search(r"[\w.%+\-]+@[\w.\-]+\.[a-zA-Z]{2,}", line)
            if not email_match:
                logging.error("Invalid legacy data.txt row %d: no email found", line_number)
                continue
            number_match = re.search(r"(?<!\d)(\d{10})(?!\d)", line[email_match.end():])
            date_match = re.search(
                r"\d{4}[-/]\d{2}[-/]\d{2}(?:\s*\(\w+\))?"
                r"|\d{2}[-/]\d{2}[-/]\d{4}(?:\s*\(\w+\))?",
                line,
            )
            if not number_match:
                logging.error("Invalid legacy data.txt row %d: no 10-digit number", line_number)
                continue
            name = re.sub(r"\s+", " ", line[:email_match.start()]).strip()
            if not name:
                logging.error("Invalid legacy data.txt row %d: no name", line_number)
                continue
            category = line[date_match.end():].strip() if date_match else ""
            records.append({
                "name": name,
                "email": email_match.group(0),
                "number": number_match.group(1),
                "date": date_match.group(0) if date_match else "",
                "category": category,
            })
    return records


def dedupe_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    seen = set()
    unique = []
    duplicates = []
    for r in records:
        if r["number"] in seen:
            logging.error("Duplicate number in data.txt: %s (%s)", r["number"], r["name"])
            duplicates.append(r)
            continue
        seen.add(r["number"])
        unique.append(r)
    return unique, duplicates


def category_key(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    if words == ["real", "state"]:
        words = ["real", "estate"]
    if any(word in {"finance", "financial", "loan", "loans"} for word in words):
        return "financialproducts"
    words = [
        word[:-3] + "y" if word.endswith("ies") and len(word) > 4
        else word[:-1] if word.endswith("s") and len(word) > 3
        else word
        for word in words
    ]
    return "".join(words)


def code_page_categories(filepath: Path = CODE_PAGE) -> list[str]:
    if not filepath.is_file():
        return []
    html = filepath.read_text(encoding="utf-8")
    categories_block = re.search(r"const\s+CATEGORIES\s*=\s*\{(.*?)\n\};", html, re.DOTALL)
    if not categories_block:
        return []
    return re.findall(r'\blabel\s*:\s*["\']([^"\']+)["\']', categories_block.group(1))


def resolve_category_page(category: str) -> dict | None:
    for label in code_page_categories():
        if category_key(label) == category_key(category):
            return {"path": CODE_PAGE, "mode": "category_app", "label": label}

    candidates = list(BASE_DIR.glob("*.html")) + list(BASE_DIR.glob("*/*.html"))
    matches = []
    for candidate in candidates:
        if candidate.parent != BASE_DIR and candidate.parent.name.casefold() in {
            "chrome_profile", "debug_screenshots", "output",
        }:
            continue
        if candidate.name.casefold() in {"index.html", "template.html", "code.html"}:
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            logging.warning("Could not inspect HTML page %s: %s", candidate, error)
            continue
        title_match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", content, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
        names = [candidate.stem, candidate.parent.name, title]
        if any(name and category_key(name) == category_key(category) for name in names):
            matches.append(candidate)
    if len(matches) > 1:
        matches.sort(key=lambda path: (len(path.parts), path.name.casefold()))
    if matches:
        return {"path": matches[0], "mode": "html"}
    if category_key(category) == "realestate" and TEMPLATE.is_file():
        return {"path": TEMPLATE, "mode": "template"}
    if CODE_PAGE.is_file():
        return {"path": CODE_PAGE, "mode": "category_app", "label": re.sub(r"\s+", " ", category).strip()}
    return None


def screenshot_path(category: str, number: str) -> Path:
    safe_category = safe_category_name(category)
    safe_number = re.sub(r"\D", "", number) or "unknown"
    folder = OUTPUT_DIR / safe_category
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_number}.png"
    if path.exists():
        raise FileExistsError(f"A screenshot already exists for number {safe_number}: {path}")
    return path


def safe_category_name(category: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", category).strip(" .") or "Uncategorized"


def resolved_category_name(target: dict) -> str:
    if target["mode"] == "template":
        return "Real Estate"
    if target.get("label"):
        return target["label"]
    if target["path"].parent != BASE_DIR:
        return target["path"].parent.name
    return target["path"].stem


def record_key(record: dict) -> str:
    return f"{record['number']}|{category_key(record['category'])}"


def append_report(record: dict, status: str, page: str = "", screenshot: str = "", error: str = "") -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not REPORT_FILE.exists() or REPORT_FILE.stat().st_size == 0
    with REPORT_FILE.open("a", encoding="utf-8", newline="") as report:
        writer = csv.writer(report)
        if write_header:
            writer.writerow(["timestamp", "number", "category", "status", "html_page", "screenshot", "error"])
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            record.get("number", ""),
            record.get("category", ""),
            status,
            page,
            screenshot,
            error,
        ])


async def replace_placeholders(page, record: dict) -> int:
    values = {
        "NAME": record["name"],
        "EMAIL": record["email"],
        "NUMBER": record["number"],
        "PHONE": record["number"],
        "MOBILE": record["number"],
        "DATE": record["date"],
        "CATEGORY": record["category"],
    }
    return await page.evaluate(
        """values => {
            let replacements = 0;
            const replaceTokens = text => {
                for (const [key, value] of Object.entries(values)) {
                    const token = `{{${key}}}`;
                    const parts = text.split(token);
                    if (parts.length > 1) {
                        replacements += parts.length - 1;
                        text = parts.join(value);
                    }
                }
                return text;
            };
            const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) node.nodeValue = replaceTokens(node.nodeValue);
            for (const element of document.querySelectorAll("*")) {
                for (const attribute of element.attributes) {
                    const updated = replaceTokens(attribute.value);
                    if (updated !== attribute.value) element.setAttribute(attribute.name, updated);
                }
            }
            return replacements;
        }""",
        values,
    )


async def fill_form_fields(page, record: dict) -> list[str]:
    values = {
        "name": record["name"],
        "email": record["email"],
        "number": record["number"],
        "phone": record["number"],
        "mobile": record["number"],
        "date": record["date"],
        "category": record["category"],
    }
    return await page.evaluate(
        """values => {
            const filled = [];
            const controls = document.querySelectorAll("input, textarea, select");
            for (const control of controls) {
                const type = (control.type || "").toLowerCase();
                if (control.disabled || control.readOnly || ["hidden", "submit", "button", "reset", "checkbox", "radio", "file"].includes(type)) continue;
                const labels = control.labels ? Array.from(control.labels).map(label => label.textContent).join(" ") : "";
                const hint = [control.name, control.id, control.placeholder, control.getAttribute("aria-label"), labels].join(" ").toLowerCase();
                const key = ["email", "name", "category", "date", "mobile", "phone", "number"].find(candidate => hint.includes(candidate));
                if (!key || !values[key]) continue;
                control.value = values[key];
                control.dispatchEvent(new Event("input", { bubbles: true }));
                control.dispatchEvent(new Event("change", { bubbles: true }));
                filled.push(key);
            }
            return filled;
        }""",
        values,
    )


async def populate_category_app(page, category_label: str, record: dict, used_sites: dict) -> None:
    await page.evaluate("label => window.selectCategory(label)", category_label)
    seen = used_sites.setdefault(category_key(category_label), set())
    brand = (await page.locator("#brandName").inner_text()).strip()
    attempts = 0
    while brand in seen and attempts < 30:
        await page.locator("#shuffleBtn").click()
        brand = (await page.locator("#brandName").inner_text()).strip()
        attempts += 1
    seen.add(brand)
    await page.evaluate(
        "row => window.setRow(row)",
        {
            "name": record["name"],
            "mobile": record["number"],
            "email": record["email"],
            "date": record["date"],
        },
    )


def existing_number_screenshots(number: str) -> list[Path]:
    safe_number = re.sub(r"\D", "", number)
    if not OUTPUT_DIR.is_dir():
        return []
    legacy_name = re.compile(
        rf"^{re.escape(safe_number)}_.+_\d{{6,8}}_\d{{6}}_\d{{6}}(?:_\d+)?$",
        re.IGNORECASE,
    )
    return sorted(
        path for path in OUTPUT_DIR.rglob("*.png")
        if path.stem == safe_number or legacy_name.fullmatch(path.stem)
    )


async def screenshot_full_page(page, path: Path) -> None:
    await page.add_style_tag(content="#ctl { display: none !important; }")
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(200)
    content_height = 0
    footer_bar = page.locator(".copy")
    if await footer_bar.count() > 0:
        box = await footer_bar.last.bounding_box()
        if box:
            content_height = math.ceil(box["y"] + box["height"])
    if content_height <= 0:
        content_height = await page.evaluate(
        """() => {
            let bottom = 0;
            const isWhite = color => color === "rgba(0, 0, 0, 0)" || color === "transparent" || color === "rgb(255, 255, 255)";
            for (const element of document.body.querySelectorAll("*")) {
                if (element.closest("#ctl")) continue;
                const style = getComputedStyle(element);
                if (style.display === "none" || style.visibility === "hidden" || style.position === "fixed") continue;
                const rect = element.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const isLeaf = element.children.length === 0;
                const hasBackground = !isWhite(style.backgroundColor) || style.backgroundImage !== "none";
                if (!isLeaf && !hasBackground) continue;
                bottom = Math.max(bottom, rect.bottom + window.scrollY);
            }
            return Math.ceil(bottom);
        }"""
    )
    if content_height <= 0:
        raise ValueError("Could not measure page content height")
    width = page.viewport_size["width"]
    await page.screenshot(
        path=str(path),
        full_page=True,
        clip={"x": 0, "y": 0, "width": width, "height": content_height},
        animations="disabled",
    )


async def run(headless: bool = False):
    license_check.require()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
        force=True,
    )

    try:
        raw_records = parse_data(DATA_FILE)
    except (OSError, UnicodeError) as error:
        logging.exception("Could not read data file %s", DATA_FILE)
        print(f"Could not read data file {DATA_FILE}: {error}")
        return
    if not raw_records:
        print("No valid records found in data.txt. Exiting.")
        return

    records, duplicate_records = dedupe_records(raw_records)
    processed_numbers = load_processed_numbers()
    for duplicate in duplicate_records:
        append_report(duplicate, "FAILED", error="Duplicate phone number in data.txt")
    counts = {"SUCCESS": 0, "FAILED": len(duplicate_records), "SKIPPED": 0}
    print(f"\nTotal parsed: {len(raw_records)}")
    print(f"Unique in this file: {len(records)}")
    tracker_backup_created = False
    used_sites: dict = {}

    async with async_playwright() as p:
        browser = None
        for record in records:
            record["category"] = record.get("category") or "Real Estate"
            target = resolve_category_page(record["category"])
            if target is None:
                error = f"No matching HTML page/category found for {record['category']!r}"
                logging.error("Record %s: %s", record["number"], error)
                print(f"  [ERROR] {record['number']} ({record['category']}): {error}")
                append_report(record, "FAILED", error=error)
                counts["FAILED"] += 1
                continue

            key = record_key(record)
            output_category = resolved_category_name(target)
            category_output = OUTPUT_DIR / safe_category_name(output_category)
            safe_number = re.sub(r"\D", "", record["number"])
            canonical_shot = category_output / f"{safe_number}.png"
            if canonical_shot.exists():
                logging.info("Skipped previously processed record %s (%s)", record["number"], record["category"])
                append_report(record, "SKIPPED", str(target["path"]), str(canonical_shot))
                counts["SKIPPED"] += 1
                continue

            page = None
            screenshot = ""
            try:
                if browser is None:
                    browser = await p.chromium.launch(headless=headless)
                page = await browser.new_page(viewport={"width": VIEWPORT_W, "height": VIEWPORT_H})
                relative_path = target["path"].relative_to(BASE_DIR).as_posix()
                url = f"{SERVER_URL}/{quote(relative_path, safe='/')}"
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(400)

                if target["mode"] == "category_app":
                    await populate_category_app(page, target["label"], record, used_sites)
                else:
                    placeholder_count = await replace_placeholders(page, record)
                    filled_fields = await fill_form_fields(page, record)
                    if placeholder_count == 0 and not filled_fields:
                        raise ValueError(
                            f"{target['path'].name} has no supported record placeholders or fillable fields"
                        )
                    await page.evaluate(
                        """() => {
                            document.querySelectorAll('tr td[height="100"]').forEach(cell => cell.closest("tr").remove());
                        }"""
                    )

                screenshot_pathname = screenshot_path(output_category, record["number"])
                screenshot = str(screenshot_pathname)
                await screenshot_full_page(page, screenshot_pathname)
                processed_numbers.add(key)
                if not tracker_backup_created:
                    backup_tracker_file()
                    tracker_backup_created = True
                save_processed_numbers(processed_numbers)
                for old_screenshot in existing_number_screenshots(safe_number):
                    if old_screenshot != screenshot_pathname:
                        old_screenshot.unlink()
                        logging.info("Removed duplicate screenshot for %s: %s", safe_number, old_screenshot)
                logging.info(
                    "Processed number=%s category=%s page=%s screenshot=%s",
                    record["number"], record["category"], target["path"], screenshot,
                )
                print(f"  [OK] {record['number']} [{record['category']}] -> {screenshot_pathname.name}")
                append_report(record, "SUCCESS", str(target["path"]), screenshot)
                counts["SUCCESS"] += 1
            except Exception as error:
                logging.exception(
                    "Failed number=%s category=%s page=%s",
                    record["number"], record["category"], target["path"],
                )
                print(f"  [ERROR] {record['number']} ({record['category']}) — {error}")
                append_report(record, "FAILED", str(target["path"]), screenshot, str(error))
                counts["FAILED"] += 1
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception as error:
                        logging.warning("Could not close page for %s: %s", record["number"], error)

        if browser is not None:
            await browser.close()

    print(
        f"\nSuccessful: {counts['SUCCESS']} | "
        f"Failed: {counts['FAILED']} | Skipped: {counts['SKIPPED']}"
    )
    print(f"Report: {REPORT_FILE}")
    print(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(run())