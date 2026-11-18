import argparse
import csv
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from playwright_runtime import configure_browser_path

configure_browser_path()

from playwright.sync_api import sync_playwright

import license_check

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent

OUTPUT_DIR = Path(
    os.getenv("OUTPUT_DIR", str(BASE / "output"))
).expanduser()

if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = BASE / OUTPUT_DIR

LOG_FILE = OUTPUT_DIR / "upload_log.csv"
PANEL_URL = os.getenv(
    "PANEL_URL",
    "https://www.redapp.vodafoneidea.com:1818/SmartRetentionEnterprise/Customer/Login",
).strip()
LOGIN_EMAIL = os.getenv("LOGIN_EMAIL", "").strip()
CDP_URL = os.getenv("CDP_URL", "http://localhost:9222")

TARGET_STATUSES = [
    "Consent to be Uploaded",
    "Rejected, Consent to be Re-Uploaded",
]
MAX_SIZE = 5 * 1024 * 1024
TYPE_DELAY_MS = 40
CONSENT_FIELD = 'input[name="Uploaded_MSISDN"]'
BUTTON_CSS = "[role=button], a.k-button, button, input[type=button], input[type=submit]"

dialog_messages = []


def log(number, file, status, note=""):
    new = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "number", "file", "status", "note"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), number, file, status, note])
    print(f"  [{status}] {number} {note}")


FILE_INDEX = {}
MULTI_NUMBER_FILES = []


def build_file_index():
    FILE_INDEX.clear()
    MULTI_NUMBER_FILES.clear()
    for f in OUTPUT_DIR.rglob("*"):
        if not f.is_file():
            continue
        nums = set(re.findall(r"(?<!\d)(\d{8,15})(?!\d)", f.stem))
        if len(nums) > 1:
            MULTI_NUMBER_FILES.append(f)
            continue
        for n in nums:
            FILE_INDEX.setdefault(n, []).append(f)
    dup = {k: v for k, v in FILE_INDEX.items() if len(v) > 1}
    print(f"File index: {len(FILE_INDEX)} alag numbers mile")
    if dup:
        print(f"  dhyaan: {len(dup)} number ki 1 se zyada files hain, unhe script SKIP karegi (galat file na lage)")
    if MULTI_NUMBER_FILES:
        print(f"  dhyaan: {len(MULTI_NUMBER_FILES)} files ke naam me 2 alag number hain, unhe use nahi karegi")


def find_file(number):
    c = FILE_INDEX.get(number, [])
    if not c:
        return None, "output/ me file nahi mili"
    exact = [f for f in c if f.stem == number]
    if len(exact) == 1:
        return exact[0], ""
    if not exact and len(c) == 1:
        return c[0], ""
    return None, "ek se zyada files mili, galat na lage isliye skip: " + ", ".join(f.name for f in c[:5])


def on_dialog(d):
    dialog_messages.append(d.message)
    print(f"  [alert] {d.message}")
    try:
        d.accept()
    except Exception:
        pass


def get_page(p):
    ctx, mode = None, None
    try:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        mode = "cdp"
        print("Chrome (debug mode) se attach ho gaya.")
    except Exception:
        print("Debug Chrome nahi mila, Chrome khol raha hoon.")
        try:
            ctx = p.chromium.launch_persistent_context(
                str(license_check.USER_DATA_DIR / "chrome_profile"),
                channel="chrome",
                headless=False,
                viewport=None,
            )
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                str(license_check.USER_DATA_DIR / "chrome_profile"),
                headless=False,
                viewport=None,
            )
        mode = "own"

    page = None
    host = PANEL_URL.split("//")[-1].split("/")[0] if PANEL_URL else ""
    for pg in ctx.pages:
        if pg.url.startswith("http") and (not host or host in pg.url):
            page = pg
            break
    if page is None:
        if not PANEL_URL:
            sys.exit("PANEL_URL set karo (env ya .env) ya panel ka tab Chrome me kholkar rakho.")
        page = ctx.pages[0] if (mode == "own" and ctx.pages) else ctx.new_page()
        page.goto(PANEL_URL)
    page.on("dialog", on_dialog)
    page.set_default_timeout(12000)
    return page


def logged_in(page):
    try:
        return page.get_by_text("Consent Status").first.is_visible()
    except Exception:
        return False


def start_login(page, login_email=""):
    if logged_in(page):
        return
    try:
        box = page.get_by_role("textbox", name="Your email address")
        box.wait_for(timeout=10000)
        if login_email:
            if (box.input_value() or "").strip() != login_email:
                box.fill(login_email)
        elif not (box.input_value() or "").strip():
            print("Browser me apna email daal kar GET OTP dabao.")
            return
        page.get_by_role("button", name="GET OTP").click()
        print("Email bhar diya aur GET OTP dab gaya. Ab 4 digit OTP daalo (Enter bhi dabao).")
    except Exception as e:
        print("Login ka auto step nahi hua, manually kar lo:", str(e)[:120])


def wait_for_login(page, login_email="", timeout_s=900):
    start_login(page, login_email)
    print("OTP browser me daalo... login hote hi script aage chalegi.")
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            if logged_in(page):
                return
            rep = page.get_by_text("UCC Report", exact=True).first
            if rep.is_visible():
                rep.click()
                page.get_by_text("Consent Status").first.wait_for(timeout=20000)
                return
        except Exception:
            pass
        page.wait_for_timeout(1000)
    sys.exit("Login timeout: OTP time pe nahi daala gaya.")


def prompt_for_login_email(cli_email=None):
    if cli_email is not None:
        email = cli_email.strip()
    else:
        prompt = "OTP kis email par bhejna hai?"
        if LOGIN_EMAIL:
            prompt += f" [{LOGIN_EMAIL}]"
        email = input(prompt + " (blank = browser me khud bharein): ").strip()
        if not email and LOGIN_EMAIL:
            email = LOGIN_EMAIL

    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Valid email address enter karein.")
    return email


def pending_numbers(page, status=None):
    try:
        return page.evaluate(
            """(status) => {
              const out = [];
              document.querySelectorAll('tr[role=row]').forEach(tr => {
                const cells = tr.querySelectorAll('td');
                if (cells.length < 3) return;
                const btn = tr.querySelector(%r);
                if (!btn || !btn.getClientRects().length) return;
                const txt = tr.innerText;
                if (status && !txt.includes(status)) return;
                let n = (cells[2].innerText || '').trim();
                if (!/^\\d{8,15}$/.test(n)) {
                  const m = txt.match(/\\b\\d{8,15}\\b/g) || [];
                  n = m.length > 1 ? m[1] : '';
                }
                if (n) out.push(n);
              });
              return out;
            }""" % BUTTON_CSS,
            status,
        )
    except Exception as e:
        print("  rows padhne me dikkat:", str(e)[:100])
        return []


def wait_for_grid(page, status, timeout_s=15):
    start = time.time()
    while time.time() - start < timeout_s:
        nums = pending_numbers(page, status)
        if nums:
            page.wait_for_timeout(800)
            return True
        page.wait_for_timeout(500)
    return False


def press_go(page):
    cands = [
        page.locator("#mainForm").get_by_role("button", name="Go", exact=True),
        page.get_by_role("button", name="Go", exact=True),
        page.locator("#mainForm input[value='Go' i], #mainForm button:has-text('Go')"),
        page.get_by_text("Go", exact=True),
    ]
    for i, loc in enumerate(cands, 1):
        try:
            if loc.count() == 0:
                continue
            el = loc.first
            try:
                el.click(timeout=6000)
            except Exception:
                el.click(timeout=4000, force=True)
            return True
        except Exception as e:
            print(f"  Go tareeka {i} fail:", str(e)[:90])
    print("  Go button dab nahi paya!")
    return False


def click_go(page, status):
    if not press_go(page):
        return False
    print("  Go dabaya, rows aane ka wait...")
    ok = wait_for_grid(page, status)
    n = len(pending_numbers(page, status))
    print(f"  grid: {n} Upload wali rows mili" + ("" if ok else " (15 sec tak kuch nahi aaya)"))
    return ok


def sync_grid(page, status, number, timeout_s=15):
    start = time.time()
    go_at = None
    while time.time() - start < timeout_s:
        nums = pending_numbers(page, status)
        if number not in nums:
            if nums:
                page.wait_for_timeout(300)
                return True
            page.wait_for_timeout(2500)
            return bool(pending_numbers(page, status))
        if go_at is None and time.time() - start > 2.5:
            press_go(page)
            go_at = time.time()
        if go_at is not None and time.time() - go_at > 5:
            return True
        page.wait_for_timeout(400)
    return bool(pending_numbers(page, status))


NEXT_FALLBACKS = (
    "button[title*='next' i], button[aria-label*='next' i], a[title*='next' i], [role=button][aria-label*='next' i]",
    "a.k-pager-nav:has(.k-i-arrow-e), a.k-pager-nav:has(.k-i-arrow-60-right), a.k-pager-nav:has(.k-i-caret-alt-right), li.next a, a[rel=next]",
)


def next_page_button(page):
    first = page.locator("a[title*='next page' i], a[aria-label*='next' i]").first
    if first.count():
        return first
    for css in NEXT_FALLBACKS:
        loc = page.locator(css)
        for i in range(loc.count()):
            el = loc.nth(i)
            if el.is_visible():
                return el
    return None


def go_next_page(page, status):
    try:
        nxt = next_page_button(page)
        if nxt is None:
            return False
        cls = (nxt.get_attribute("class") or "") + (nxt.get_attribute("aria-disabled") or "")
        if "disabled" in cls.lower() or "true" in cls.lower():
            return False
        before = pending_numbers(page, status)
        try:
            nxt.click(timeout=6000)
        except Exception:
            nxt.click(timeout=4000, force=True)
        page.wait_for_timeout(1500)
        end = time.time() + 8
        while time.time() < end:
            now = pending_numbers(page, status)
            if now and now != before:
                page.wait_for_timeout(800)
                return True
            page.wait_for_timeout(500)
        return False
    except Exception:
        return False


def dropdown_candidates(page):
    form = page.locator("#mainForm")
    return [
        form.locator("span.k-widget.k-dropdown"),
        form.locator(".k-dropdown, .k-dropdownlist, .k-picker, .k-combobox"),
        form.locator("span.k-dropdown-wrap"),
        page.get_by_text("Consent Status", exact=True).first.locator(
            "xpath=following::*[contains(@class,'k-dropdown') or contains(@class,'k-picker')"
            " or contains(@class,'k-widget')][1]"
        ),
    ]


def dropdown(page):
    for loc in dropdown_candidates(page):
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            pass
    return None


def widget_text(page):
    dd = dropdown(page)
    if dd is None:
        return ""
    try:
        inp = dd.locator(".k-input")
        node = inp.first if inp.count() else dd
        return (node.inner_text(timeout=3000) or "").strip()
    except Exception:
        return ""


def dump_form(page):
    try:
        html = page.locator("#mainForm").first.evaluate("e => e.outerHTML")
        print("  #mainForm ka HTML (pehle 2500 chars):\n", html[:2500])
    except Exception:
        try:
            print("  page URL:", page.url)
            print("  body text:", page.locator("body").inner_text()[:600])
        except Exception:
            pass


def click_option(page, dd, status, wait_s=5):
    exact_name = re.compile(rf"^\s*{re.escape(status)}\s*$")
    owns = None
    try:
        owns = dd.get_attribute("aria-owns")
    except Exception:
        pass
    cands = []
    if owns:
        cands.append(page.locator(f'[id="{owns}"]').get_by_role("option", name=exact_name))
        cands.append(page.locator(f'[id="{owns}"] li').filter(has_text=exact_name))
    cands.append(page.get_by_role("option", name=exact_name))
    cands.append(page.locator("ul[role=listbox] li, .k-list li, li.k-item").filter(has_text=exact_name))
    end = time.time() + wait_s
    while time.time() < end:
        for c in cands:
            try:
                if c.count() and c.first.is_visible():
                    c.first.click(timeout=3000)
                    return True
            except Exception:
                pass
        page.wait_for_timeout(300)
    return False


def kendo_select(page, status):
    try:
        return bool(page.evaluate(
            """(s) => {
              const j = window.jQuery || window.$;
              if (!j) return false;
              const root = document.querySelector('#mainForm');
              const el = root && root.querySelector('[data-role=dropdownlist]');
              const dl = el && j(el).data('kendoDropDownList');
              if (!dl) return false;
              const items = [...dl.ul[0].querySelectorAll('li')];
              const i = items.findIndex(li => li.textContent.trim() === s);
              if (i < 0) return false;
              dl.select(i); dl.trigger('change');
              return true;
            }""",
            status,
        ))
    except Exception:
        return False


def select_status(page, status):
    for attempt in range(1, 4):
        try:
            sel = page.locator("#mainForm select:visible")
            if sel.count():
                sel.first.select_option(label=status, timeout=3000)
                page.wait_for_timeout(800)
                print(f"Status select: {status} (native)")
                return True
        except Exception:
            pass
        if widget_text(page) == status:
            print(f"Status select: {status} (pehle se chuna hua)")
            return True
        dd = dropdown(page)
        if dd is None:
            print(f"  dropdown element nahi mila ({attempt}/3), 2 sec ruk ke dobara dekhta hoon")
            page.wait_for_timeout(2000)
            continue
        try:
            dd.click(timeout=5000)
            page.wait_for_timeout(500)
            if click_option(page, dd, status):
                page.wait_for_timeout(800)
                now = widget_text(page)
                if now == status:
                    print(f"Status select: {status}")
                    return True
                print(f"  select ke baad dropdown me '{now}' dikha, dobara try ({attempt}/3)")
            else:
                print(f"  option '{status}' list me nahi dikha ({attempt}/3)")
        except Exception as e:
            print(f"  dropdown select nahi hua ({attempt}/3):", str(e)[:100])
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(1000)
    if kendo_select(page, status):
        page.wait_for_timeout(800)
        if widget_text(page) == status:
            print(f"Status select: {status} (Kendo API se)")
            return True
    dump_form(page)
    return False


def expected_count(page, status):
    try:
        return page.evaluate(
            """(status) => {
              const cells = [...document.querySelectorAll('table th, table td')];
              const hdr = cells.find(c => c.innerText.trim() === status
                                      && c.closest('table').innerText.includes('Validation Pending'));
              if (!hdr) return null;
              const row = hdr.parentElement;
              const idx = [...row.children].indexOf(hdr);
              const rows = [...hdr.closest('table').querySelectorAll('tr')];
              const next = rows[rows.indexOf(row) + 1];
              if (!next || !next.children[idx]) return null;
              const v = parseInt(next.children[idx].innerText.trim(), 10);
              return isNaN(v) ? null : v;
            }""",
            status,
        )
    except Exception:
        return None


def load_status(page, status):
    expected = expected_count(page, status)
    print(f"  summary me '{status}' ki count: {expected}")
    for attempt in range(1, 4):
        if not select_status(page, status):
            print(f"  '{status}' select nahi ho paya, is option ko skip kar raha hoon")
            return False
        if click_go(page, status):
            return True
        if expected == 0 and attempt >= 2:
            break
        if attempt < 3:
            print(f"  rows nahi aayi, dobara select + Go ({attempt}/3)")
            page.wait_for_timeout(2000)
    return bool(pending_numbers(page, status))


def close_popup(page):
    try:
        page.get_by_role("button", name="Cancel").first.click(timeout=3000)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass


def attach_file(page, file):
    path = str(file.resolve())
    done, last_err = False, ""
    for loc in (page.get_by_role("button", name="files"), page.locator("input[type=file]").last):
        try:
            loc.set_input_files(path, timeout=4000)
            done = True
            break
        except Exception as e:
            last_err = str(e)[:80]
    if not done:
        try:
            with page.expect_file_chooser(timeout=5000) as fc:
                page.get_by_text("Select files").first.click(timeout=3000)
            fc.value.set_files(path)
            done = True
        except Exception as e:
            raise RuntimeError("file attach nahi hui: " + last_err + " | " + str(e)[:80])
    page.wait_for_timeout(400)
    shown = page.get_by_text(file.name).count() > 0
    print(f"  file attach: {file.name} | popup me naam dikha: {shown}")


FILE_EXT = r"(?:png|jpe?g|gif|bmp|webp|pdf)"


def verify_before_submit(page, number, file):
    problems = []
    typed = (page.locator(CONSENT_FIELD).input_value() or "").strip()
    if typed != number:
        problems.append(f"'Consent uploaded for' me '{typed}' hai, chahiye '{number}'")
    still, vals = popup_ready(page, number, timeout_s=1)
    if not still:
        problems.append(f"popup me row ka number nahi dikh raha, dikha: {vals}")
    text = page.evaluate(
        """() => {
          const f = document.querySelector('input[name="Uploaded_MSISDN"]');
          const box = (f && f.closest('.modal, [role=dialog], .k-window, form')) || document.body;
          return box.innerText || '';
        }"""
    )
    if file.name not in text:
        problems.append(f"popup me chuni hui file ka naam '{file.name}' nahi dikha")
    rest = text.replace(file.name, " ")
    extra = re.findall(r"\S*\." + FILE_EXT + r"\b", rest, re.I)
    if extra:
        problems.append(f"popup me aur file/files bhi dikh rahi hain: {extra[:3]}")
    return problems


def popup_ready(page, number, timeout_s=6):
    end = time.time() + timeout_s
    vals = []
    while time.time() < end:
        vals = page.evaluate(
            "() => [...document.querySelectorAll('input')]"
            ".filter(i => i.name !== 'Uploaded_MSISDN' && i.type !== 'file' && i.getClientRects().length)"
            ".map(i => (i.value || '').trim())"
        )
        if number in vals:
            return True, vals
        page.wait_for_timeout(250)
    return False, vals


def process_one(page, number, dry_run, confirm=False):
    file, note = find_file(number)
    if not file:
        log(number, "", "SKIP", note)
        return "skip"
    if file.stat().st_size > MAX_SIZE:
        log(number, file.name, "SKIP", "file 5 MB se badi hai")
        return "skip"

    row = page.locator("tr[role=row]").filter(has_text=number).first
    row.wait_for(state="visible", timeout=6000)
    btn = row.locator(BUTTON_CSS).first
    btn.scroll_into_view_if_needed()
    try:
        btn.click(timeout=6000)
    except Exception:
        btn.click(timeout=4000, force=True)
    consent_for = page.locator(CONSENT_FIELD)
    consent_for.wait_for(state="visible", timeout=10000)

    ok_popup, vals = popup_ready(page, number)
    if not ok_popup:
        log(number, file.name, "ERROR", f"popup me row ka number nahi aaya, dikha: {vals}")
        close_popup(page)
        return "error"

    consent_for.click()
    consent_for.fill("")
    consent_for.press_sequentially(number, delay=TYPE_DELAY_MS)
    if (consent_for.input_value() or "").strip() != number:
        consent_for.fill("")
        consent_for.press_sequentially(number, delay=TYPE_DELAY_MS + 40)

    attach_file(page, file)

    problems = verify_before_submit(page, number, file)
    if problems:
        log(number, file.name, "ERROR", "Submit NAHI kiya: " + " | ".join(problems))
        close_popup(page)
        return "error"

    if dry_run:
        log(number, file.name, "DRY-RUN", "sab bhara, Submit nahi kiya")
        page.wait_for_timeout(2000)
        close_popup(page)
        return "dry"

    if confirm:
        print(f"  >>> Number: {number} | File: {file.name} | Upload (popup me sab check ho chuka)")
        ans = input("  >>> Submit karu? Enter = haan, n = skip: ").strip().lower()
        if ans.startswith("n"):
            log(number, file.name, "SKIP", "tumne confirm me skip kiya")
            close_popup(page)
            return "skip"

    dialog_messages.clear()
    page.get_by_role("button", name="Submit").click()

    try:
        consent_for.wait_for(state="hidden", timeout=30000)
        log(number, file.name, "OK", "; ".join(dialog_messages))
        return "ok"
    except Exception:
        log(number, file.name, "ERROR", "Submit ke baad popup band nahi hua " + "; ".join(dialog_messages))
        close_popup(page)
        return "error"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="kitne upload karne hain (0 = sab)")
    ap.add_argument("--dry-run", action="store_true", help="sab bharo par Submit mat karo")
    ap.add_argument("--confirm", action="store_true", help="har Submit se pehle tumse Enter/n puchta hai")
    ap.add_argument("--email", help="OTP receive karne wala email (prompt skip karega)")
    args = ap.parse_args()
    license_check.require()
    try:
        login_email = prompt_for_login_email(args.email)
    except ValueError as error:
        ap.error(str(error))

    if not OUTPUT_DIR.exists():
        sys.exit(f"'output' folder nahi mila: {OUTPUT_DIR}")
    n_files = sum(1 for f in OUTPUT_DIR.rglob("*") if f.is_file())
    print(f"Files folder: {OUTPUT_DIR} ({n_files} files)")
    build_file_index()

    with sync_playwright() as p:
        page = get_page(p)
        wait_for_login(page, login_email)

        handled, stats, tried = set(), {"ok": 0, "skip": 0, "error": 0, "dry": 0}, 0
        for status in TARGET_STATUSES:
            try:
                if args.limit and tried >= args.limit:
                    break
                print(f"\n=== {status} ===")
                if not load_status(page, status):
                    print("  is option me koi row nahi mili / select nahi hua, aage badh raha hoon")
                    continue
                while True:
                    if args.limit and tried >= args.limit:
                        break
                    todo = [n for n in pending_numbers(page, status) if n not in handled]
                    if not todo:
                        if go_next_page(page, status):
                            print("  is page ki saari rows ho chuki (skip/upload), agle page par gaya")
                            continue
                        print(f"  '{status}' me ab koi nayi row ya agla page nahi mila, aage badh raha hoon")
                        break
                    number = todo[0]
                    handled.add(number)
                    print(f"-> {number}")
                    try:
                        res = process_one(page, number, args.dry_run, args.confirm)
                    except Exception as e:
                        log(number, "", "ERROR", str(e)[:200])
                        try:
                            close_popup(page)
                        except Exception:
                            pass
                        res = "error"
                    stats[res] += 1
                    if res in ("ok", "dry", "error"):
                        tried += 1
                    if res == "ok":
                        sync_grid(page, status, number)
            except KeyboardInterrupt:
                print("\nCtrl+C: rok diya.")
                break
            except Exception:
                print(f"  '{status}' me error aaya, traceback:")
                traceback.print_exc()

        print("\nKhatam:", stats, "| log:", LOG_FILE)
        print("Browser khula rehne diya hai.")


if __name__ == "__main__":
    main()