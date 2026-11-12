"""
WhatsApp Auto-Sender Module (sender.py)
=======================================
A safe, automated WhatsApp message sender with built-in Anti-Ban protection,
session persistence, and resume/checkpoint tracking.

Features:
- Reads cleaned leads from 'contacts.csv'
- Sends personalized messages using institution name, location, query, etc.
- Anti-Ban Protection:
    * Mandatory randomized delays between 30 and 60 seconds between messages
    * Human-like typing/interaction behavior
    * Warmup safety warnings and daily threshold guidance
- Session Persistence:
    * Stores WhatsApp Web session in a local folder ('whatsapp_session')
    * Requires QR scan only once; stays logged in on subsequent runs
- Checkpoint / Resume Mechanism:
    * Records processed numbers in 'sent_contacts.txt'
    * Automatically skips already contacted numbers if script is stopped/resumed
- Delivery Logging:
    * Records detailed timestamps and outcomes into 'delivery_log.txt'
- Fallback & Invalid Number Detection:
"""
from __future__ import annotations

import os
import re
import csv
import sys
import time
import random
import urllib.parse
from datetime import datetime

# Configure UTF-8 for Windows console
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Supabase cloud database adapter (optional/hybrid)
try:
    import supabase_db
except ImportError:
    supabase_db = None

# Blacklist and banned institute filtering
from blacklist import is_banned_institute

# Spintax and anti-ban message mutator
from spintax import mutate_message, parse_spintax
from scraper import find_working_chromedriver_service

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# Optional webdriver-manager support
try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WDM = True
except ImportError:
    USE_WDM = False

# Optional pywhatkit support
try:
    import pywhatkit
    HAS_PYWHATKIT = True
except ImportError:
    HAS_PYWHATKIT = False


# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "contacts.csv")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "sent_contacts.txt")
LOG_FILE = os.path.join(BASE_DIR, "delivery_log.txt")
TEMPLATE_FILE = os.path.join(BASE_DIR, "message_template.txt")
SESSION_DIR = os.path.join(BASE_DIR, "whatsapp_session")

# Advanced Anti-Ban Settings
MIN_DELAY_SECONDS = int(os.getenv("MIN_DELAY_SECONDS", "45"))
MAX_DELAY_SECONDS = int(os.getenv("MAX_DELAY_SECONDS", "85"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5"))                                                    # Messages before taking a long cooling break
BATCH_COOLDOWN_MIN_MINUTES = int(os.getenv("BATCH_COOLDOWN_MIN_MINUTES", os.getenv("BATCH_COOLDOWN_MINUTES", "5"))) # Min break duration (minutes)
BATCH_COOLDOWN_MAX_MINUTES = int(os.getenv("BATCH_COOLDOWN_MAX_MINUTES", "10"))                  # Max break duration (minutes)
BATCH_COOLDOWN_MINUTES = BATCH_COOLDOWN_MIN_MINUTES                                              # Backward compatibility alias
DAILY_SAFETY_LIMIT = int(os.getenv("DAILY_SAFETY_LIMIT", "25"))                                    # Safe daily threshold per WhatsApp number
HUMAN_TYPING_MODE = os.getenv("HUMAN_TYPING_MODE", "true").lower() in ["true", "1", "yes"]
SAFE_LINK_MODE = os.getenv("SAFE_LINK_MODE", "true").lower() in ["true", "1", "yes"]

DEFAULT_TEMPLATE = """Hello {name},

Greetings! We discovered your profile while looking up top {query} in {location}.

We are reaching out to introduce our innovative educational technology and automation solutions built to assist institutions like yours.

Would you be open for a short 5-minute conversation or demo this week?

Best regards,
Core AI Automation Team
"""


# ==============================================================================
# LOGGING & CHECKPOINT TRACKING
# ==============================================================================
def load_checkpoint() -> set:
    """
    Loads all previously processed phone numbers from the checkpoint file.
    """
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        processed = {line.strip() for line in f if line.strip()}
    return processed


def record_checkpoint(phone: str, status: str = "sent") -> None:
    """
    Appends a processed phone number to the checkpoint file immediately.
    Also syncs to Supabase if connected.
    """
    with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{phone.strip()}\n")

    if supabase_db and supabase_db.is_connected():
        try:
            supabase_db.mark_contact_status(phone, status)
        except Exception:
            pass


def log_delivery(status: str, phone: str, name: str, details: str = "") -> None:
    """
    Logs status to both console, delivery_log.txt file, and Supabase cloud.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{status.upper()}] Phone: {phone:<15} | Name: {name[:25]:<25} | {details}\n"

    # Write to log file
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line)

    # Safe Console feedback (Windows safe)
    try:
        if status.upper() == "SUCCESS":
            print(f"    [✓ SUCCESS] Message delivered to {name} ({phone})")
        elif status.upper() == "INVALID":
            print(f"    [❌ INVALID] {name} ({phone}) - {details}")
        elif status.upper() == "BANNED":
            print(f"    [🛡️ BANNED]  {name} ({phone}) - {details}")
        else:
            print(f"    [⚠️ FAILED]  {name} ({phone}) - {details}")
    except Exception:
        safe_name = name.encode("ascii", errors="replace").decode("ascii")
        print(f"    [{status.upper()}] {safe_name} ({phone}) - {details}")

    # Sync delivery event and status to Supabase
    if supabase_db and supabase_db.is_connected():
        try:
            supabase_db.log_delivery_event(status, phone, name, details)
            if status.upper() in ["INVALID", "FAILED", "BANNED"]:
                supabase_db.mark_contact_status(phone, status.lower(), details)
        except Exception:
            pass


# ==============================================================================
# MESSAGE TEMPLATE FORMATTER
# ==============================================================================
def load_message_template() -> str:
    """
    Loads template from template file, or falls back to default.
    """
    if os.path.exists(TEMPLATE_FILE):
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            print(f"[!] Warning reading '{TEMPLATE_FILE}': {e}. Using default template.")
    return DEFAULT_TEMPLATE


def format_message(template: str, row: dict, safe_link: bool = False, soft_opt_out: bool = True) -> str:
    """
    Substitutes placeholder values, resolves Spintax {Option1|Option2},
    and injects randomized invisible entropy for a 100% unique cryptographic hash.
    Also appends a polite opt-out closer to drastically reduce 'Report Spam' actions.
    """
    return mutate_message(
        template=template,
        lead=row,
        include_soft_opt_out=soft_opt_out,
        safe_link_mode=safe_link
    )


def count_messages_sent_today(log_path: str = LOG_FILE) -> int:
    """
    Counts how many successful live messages have been sent in the current calendar day.
    Helps prevent exceeding the recommended daily warm-up threshold.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith(f"[{today_str}") and "[SUCCESS]" in line and "Simulated" not in line:
                        count += 1
        except Exception:
            pass
    return count


# ==============================================================================
# ANTI-BAN DELAY & BATCH COOLDOWN CONTROLLER
# ==============================================================================
def anti_ban_delay(min_s: int = MIN_DELAY_SECONDS, max_s: int = MAX_DELAY_SECONDS) -> None:
    """
    Sleeps for a random duration between min_s and max_s with a live terminal countdown.
    This mimics human behavior and helps protect your WhatsApp account from being flagged.
    """
    delay = random.randint(min_s, max_s)
    print(f"\n[🛡️ ANTI-BAN SAFETY] Pausing for {delay} seconds before sending next message...")

    for remaining in range(delay, 0, -1):
        print(f"    ⏳ Waiting... {remaining:02d}s remaining [Anti-ban cooldown]", end="\r")
        time.sleep(1)
    print("    [✓] Cooldown finished. Resuming queue...                  \n")


def batch_cooldown_pause(
    min_minutes: int = BATCH_COOLDOWN_MIN_MINUTES,
    max_minutes: int = BATCH_COOLDOWN_MAX_MINUTES
) -> None:
    """
    Pauses execution for a randomized cooling break (between 5 and 10 minutes by default)
    after sending a batch of messages. Crucial to prevent WhatsApp telemetry from
    detecting predictable, robotic patterns.
    """
    if min_minutes > max_minutes:
        min_minutes, max_minutes = max_minutes, min_minutes

    total_seconds = random.randint(min_minutes * 60, max_minutes * 60)
    minutes_display = round(total_seconds / 60, 1)

    print(f"\n[☕ BATCH COOLING BREAK] Taking a randomized {minutes_display}-minute rest ({min_minutes}-{max_minutes}m range) to protect your WhatsApp account health...")
    for rem in range(total_seconds, 0, -1):
        m, s = divmod(rem, 60)
        print(f"    ⏳ Account resting... {m:02d}:{s:02d} remaining [Batch safety cooldown]", end="\r")
        time.sleep(1)
    print("    [✓] Cooldown finished. Resuming queue...                                     \n")


# ==============================================================================
# CHROME DRIVER WITH PERSISTENT USER SESSION
# ==============================================================================
def create_whatsapp_driver(session_path: str = SESSION_DIR):
    """
    Launches Chrome with a persistent user profile directory.
    This saves your WhatsApp Web login so you only scan the QR code once!
    Includes automatic self-healing profile recovery if a previous run was abruptly halted.
    """
    if not HAS_SELENIUM:
        raise ImportError(
            "Selenium is required to automate WhatsApp Web.\n"
            "Please install dependencies with: pip install -r requirements.txt"
        )

    os.makedirs(session_path, exist_ok=True)

    # Clean up stale DevToolsActivePort or lockfiles from previous ungraceful exits
    for stale_file in ["DevToolsActivePort", "SingletonLock", "SingletonCookie", "SingletonSocket"]:
        target = os.path.join(session_path, stale_file)
        if os.path.exists(target):
            try:
                os.remove(target)
            except Exception:
                pass

    def _build_options(path):
        options = Options()
        options.add_argument(f"--user-data-dir={path}")
        options.add_argument("--start-maximized")
        options.add_argument("--window-size=1200,900")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-notifications")
        options.add_argument("--lang=en-US")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        return options

    driver = None
    # Strategy 1: Check for verified, unblocked cached ChromeDriver (bypasses WinError 4551 from Smart App Control)
    service = find_working_chromedriver_service()
    if service:
        try:
            driver = webdriver.Chrome(service=service, options=_build_options(session_path))
        except Exception as first_err:
            print(f"[i] Pre-verified service encountered: {first_err}. Attempting profile lock purge and recovery...")

    if not driver:
        try:
            driver = webdriver.Chrome(options=_build_options(session_path))
        except Exception as first_err:
            print(f"[i] Primary Chrome startup encountered: {first_err}. Attempting profile lock purge and recovery...")
            # Purge locks inside Default subfolder
            default_dir = os.path.join(session_path, "Default")
            if os.path.exists(default_dir):
                for lock_candidate in ["LOCK", "LOCK-journal", "LOG", "LOG.old"]:
                    fpath = os.path.join(default_dir, lock_candidate)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except Exception:
                            pass
            
            try:
                if USE_WDM:
                    service = Service(ChromeDriverManager().install())
                    driver = webdriver.Chrome(service=service, options=_build_options(session_path))
                else:
                    driver = webdriver.Chrome(options=_build_options(session_path))
            except Exception:
                # If Chrome is blocked by Smart App Control, try Microsoft Edge fallback
                try:
                    from selenium.webdriver.edge.options import Options as EdgeOptions
                    edge_options = EdgeOptions()
                    edge_options.add_argument(f"--user-data-dir={session_path}")
                    edge_options.add_argument("--start-maximized")
                    edge_options.add_argument("--window-size=1200,900")
                    edge_options.add_argument("--disable-blink-features=AutomationControlled")
                    edge_options.add_argument("--disable-notifications")
                    driver = webdriver.Edge(options=edge_options)
                except Exception:
                    # If still failing, profile directory was critically corrupted. Recreate cleanly.
                    import shutil
                    backup_path = session_path + "_corrupt_backup"
                    try:
                        if os.path.exists(backup_path):
                            shutil.rmtree(backup_path, ignore_errors=True)
                        shutil.move(session_path, backup_path)
                    except Exception:
                        pass
                    os.makedirs(session_path, exist_ok=True)
                    driver = webdriver.Chrome(options=_build_options(session_path))

    try:
        driver.switch_to.window(driver.current_window_handle)
        driver.minimize_window()
        time.sleep(0.3)
        driver.maximize_window()
    except Exception:
        pass

    return driver


def wait_for_whatsapp_login(driver: webdriver.Chrome, timeout: int = 180, on_qr_callback = None) -> bool:
    """
    Navigates to WhatsApp Web and waits for the user to be logged in.
    If QR code is present, gives the user time to scan and link their device.
    """
    print("\n[+] Opening WhatsApp Web...")
    driver.get("https://web.whatsapp.com")
    time.sleep(3)

    print("[i] Checking WhatsApp Web login status...")
    start_time = time.time()
    qr_notified = False

    # Selectors that ONLY exist when fully logged into WhatsApp Web
    logged_in_selectors = [
        "//div[@id='pane-side']",
        "//div[contains(@aria-label, 'Chat list')]",
        "//div[contains(@aria-label, 'Search input textbox')]",
        "//header//div[@title='New chat' or @title='Status' or @title='Communities']",
    ]

    while time.time() - start_time < timeout:
        # 1. Check if user is logged in
        for selector in logged_in_selectors:
            elements = driver.find_elements(By.XPATH, selector)
            if elements and elements[0].is_displayed():
                print("\n======================================================")
                print(" [✓] WhatsApp Web is LOGGED IN and ready to send!")
                print("======================================================\n")
                return True

        # 2. Check if QR code is visible
        qr_indicators = driver.find_elements(
            By.XPATH,
            "//canvas | //*[@data-ref] | //*[contains(text(), 'Scan to log in')] | //*[contains(text(), 'Link with phone number')]"
        )
        if qr_indicators and not qr_notified:
            print("\n" + "=" * 65)
            print(" 📱 ACTION REQUIRED: PLEASE SCAN THE WHATSAPP QR CODE")
            print("=" * 65)
            print(" 1. Open WhatsApp on your phone.")
            print(" 2. Tap Menu / Settings -> Linked Devices -> Link a Device.")
            print(" 3. Point your camera at the QR code displayed in Chrome.")
            print(" (Your login will be saved automatically for all future runs!)")
            print("=" * 65 + "\n")
            qr_notified = True
            if on_qr_callback:
                try:
                    on_qr_callback()
                except Exception:
                    pass

        # Update countdown in terminal
        elapsed = int(time.time() - start_time)
        remaining = timeout - elapsed
        if qr_notified:
            print(f"    ⏳ Waiting for you to scan QR code... ({remaining}s remaining)", end="\r")

        time.sleep(2)

    print("\n❌ Login timeout reached (180s). Please restart and scan the QR code.")
    return False


# ==============================================================================
# PHONE NUMBER NORMALIZATION FOR WHATSAPP
# ==============================================================================
def normalize_whatsapp_phone(phone: str, default_country_code: str = "91") -> str:
    """
    Normalizes a phone number for WhatsApp Web Click-to-Chat URL (E.164 without '+').
    Ensures country code is always properly prefixed.
    
    Examples:
        '9888125354'     -> '919888125354'
        '09888125354'    -> '919888125354'
        '+91 9888125354' -> '919888125354'
        '919888125354'   -> '919888125354'
    """
    clean_digits = re.sub(r"[^\d]", "", str(phone))
    while clean_digits.startswith("0"):
        clean_digits = clean_digits[1:]

    cc = default_country_code.lstrip("+").strip()

    # If it's a 10-digit number, prepend default country code
    if len(clean_digits) == 10:
        return f"{cc}{clean_digits}"

    # If 12 digits starting with 91, it already has the country code
    if len(clean_digits) == 12 and clean_digits.startswith("91"):
        return clean_digits

    return clean_digits


# ==============================================================================
# SENDING ENGINE (SELENIUM WHATSAPP WEB)
# ==============================================================================
def type_message_like_human(input_box, message: str) -> None:
    """
    Simulates authentic human typing by dispatching characters with micro-pauses
    and Shift+Enter for line breaks. Fires genuine Chromium DOM events ('keydown',
    'input', 'keyup') with isTrusted: true, evading client-side bot detection.
    """
    lines = message.split("\n")
    for l_idx, line in enumerate(lines):
        for char in line:
            input_box.send_keys(char)
            # 15ms - 40ms realistic keystroke delay
            time.sleep(random.uniform(0.015, 0.040))
        if l_idx < len(lines) - 1:
            input_box.send_keys(Keys.SHIFT, Keys.ENTER)
            time.sleep(random.uniform(0.04, 0.10))


def send_via_selenium(
    driver: webdriver.Chrome,
    phone: str,
    message: str,
    human_typing: bool = True
) -> tuple[bool, str]:
    """
    Sends a personalized message to the recipient using WhatsApp Web.
    Properly prefixes country code (+91), handles invalid numbers & modern DOM elements.
    Uses human typing simulation to evade bot detection telemetry.
    
    Returns:
        (success: bool, status_message: str)
    """
    # 1. Reject landlines immediately (in India, mobile numbers start with 6, 7, 8, 9)
    raw_digits = re.sub(r"[^\d]", "", str(phone)).lstrip("0")
    if raw_digits.startswith("91") and len(raw_digits) == 12:
        raw_digits = raw_digits[2:]
    if len(raw_digits) == 10 and raw_digits[0] not in "6789":
        return False, "Landline number cannot receive WhatsApp messages"

    whatsapp_phone = normalize_whatsapp_phone(phone)

    if human_typing:
        # Anti-Ban: Load clean chat URL without query string injection (avoids 0-keystroke detection)
        send_url = f"https://web.whatsapp.com/send?phone={whatsapp_phone}"
    else:
        encoded_message = urllib.parse.quote(message)
        send_url = f"https://web.whatsapp.com/send?phone={whatsapp_phone}&text={encoded_message}"

    driver.get(send_url)

    # Allow WhatsApp Web to resolve the contact and decrypt chat
    max_wait_seconds = 28
    start_time = time.time()

    try:
        while time.time() - start_time < max_wait_seconds:
            time.sleep(1)

            # 1. Check if invalid number dialog/modal appears
            invalid_elements = driver.find_elements(
                By.XPATH,
                "//div[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'invalid') "
                "or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'not on whatsapp') "
                "or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), \"isn't on whatsapp\") "
                "or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), \"couldn't find an account\")]"
            )
            dialog_elements = driver.find_elements(By.XPATH, "//div[@role='dialog']")
            is_invalid = False
            for el in invalid_elements + dialog_elements:
                try:
                    txt = el.text.lower()
                    if any(phrase in txt for phrase in [
                        "invalid", "not on whatsapp", "isn't on whatsapp", "couldn't find an account"
                    ]):
                        is_invalid = True
                        break
                except Exception:
                    pass

            if is_invalid:
                # Dismiss modal with 'OK', 'Close', or 'Cancel'
                for d_xpath in [
                    "//div[@role='dialog']//button",
                    "//div[@role='dialog']//div[@role='button']",
                    "//button[contains(., 'OK') or contains(., 'Ok') or contains(., 'Close') or contains(., 'Cancel')]",
                    "//div[@role='button'][contains(., 'OK') or contains(., 'Ok') or contains(., 'Close')]"
                ]:
                    try:
                        ok_btn = driver.find_element(By.XPATH, d_xpath)
                        if ok_btn.is_displayed():
                            ok_btn.click()
                            time.sleep(1)
                            break
                    except Exception:
                        pass
                return False, "Not registered on WhatsApp"

            # 2. Check for message input box
            input_selectors = [
                "//footer//div[@contenteditable='true']",
                "//div[@contenteditable='true'][@data-tab='10' or contains(@class, 'selectable-text')]",
                "//div[@contenteditable='true'][contains(@aria-label, 'Type a message')]"
            ]
            input_box = None
            for in_xpath in input_selectors:
                inputs = driver.find_elements(By.XPATH, in_xpath)
                if inputs and inputs[0].is_displayed():
                    input_box = inputs[0]
                    break

            if input_box:
                if human_typing:
                    # Focus input box and simulate human keystrokes
                    try:
                        input_box.click()
                    except Exception:
                        driver.execute_script("arguments[0].focus();", input_box)
                    time.sleep(random.uniform(0.4, 0.8))
                    type_message_like_human(input_box, message)
                    time.sleep(random.uniform(0.6, 1.2))

                # 3. Look for Send Button
                send_selectors = [
                    "//button[@aria-label='Send' or @data-tab='11' or contains(@aria-label, 'Send')]",
                    "//button[.//span[@data-icon='send' or @data-icon='send-refreshed' or @data-icon='send-light' or @data-icon='wds-ic-send']]",
                    "//span[@data-icon='send' or @data-icon='send-refreshed' or @data-icon='wds-ic-send']/ancestor::button",
                    "//footer//button[contains(@aria-label, 'Send') or @data-tab='11']"
                ]
                for s_xpath in send_selectors:
                    send_buttons = driver.find_elements(By.XPATH, s_xpath)
                    if send_buttons and send_buttons[0].is_displayed():
                        time.sleep(random.uniform(0.5, 0.9))
                        try:
                            send_buttons[0].click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", send_buttons[0])
                        time.sleep(3)
                        return True, "Message sent successfully"

                # 4. Fallback: Press ENTER in the input box
                input_box.send_keys(Keys.ENTER)
                time.sleep(3)
                return True, "Message sent via Enter key"

        return False, "Send button or chat box did not load within timeout"

    except TimeoutException:
        return False, "Timeout waiting for chat interface"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


# ==============================================================================
# ALTERNATIVE ENGINE: PYWHATKIT
# ==============================================================================
def send_via_pywhatkit(phone: str, message: str) -> tuple[bool, str]:
    """
    Sends message using pywhatkit library (opens default browser).
    """
    if not HAS_PYWHATKIT:
        return False, "pywhatkit is not installed in the environment."
    try:
        print(f"    [pywhatkit] Dispatching to {phone}...")
        # pywhatkit sends instantly with 18 second wait for web.whatsapp.com load
        pywhatkit.sendwhatmsg_instantly(
            phone_no=phone,
            message=message,
            wait_time=18,
            tab_close=True,
            close_time=4
        )
        return True, "Dispatched via pywhatkit"
    except Exception as e:
        return False, f"pywhatkit error: {str(e)}"


# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================
def main():
    print("=" * 65)
    print("       WHATSAPP AUTO-SENDER WITH ANTI-BAN SHIELD")
    print("=" * 65)
    print("Module 2 of WhatsApp Automation Suite | Free & Local\n")

    # 1. Verify contacts file exists
    if not os.path.exists(CSV_FILE):
        print(f"❌ Error: '{CSV_FILE}' not found in the current directory.")
        print("👉 Please run 'python scraper.py' first to scrape and generate contacts.")
        return

    # 2. Read contacts using native csv.DictReader
    all_contacts = []
    try:
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                phone = row.get("Phone", "").strip()
                if phone:
                    all_contacts.append(row)
    except Exception as e:
        print(f"❌ Error reading '{CSV_FILE}': {e}")
        return

    if not all_contacts:
        print(f"❌ '{CSV_FILE}' is empty or contains no valid phone entries.")
        return

    total_in_csv = len(all_contacts)

    # 3. Checkpoint Tracking: Load already processed numbers
    processed_phones = load_checkpoint()
    
    # Filter pending contacts
    pending_contacts = [c for c in all_contacts if c.get("Phone", "").strip() not in processed_phones]
    pending_count = len(pending_contacts)

    sent_today = count_messages_sent_today()

    print("📊 CAMPAIGN OVERVIEW & ANTI-BAN SHIELD HEALTH:")
    print(f"   • Total valid contacts in CSV:    {total_in_csv}")
    print(f"   • Already processed previously:   {len(processed_phones)}")
    print(f"   • Remaining queued to send:       {pending_count}")
    print(f"   • Messages sent today:            {sent_today} / {DAILY_SAFETY_LIMIT} (Daily safety threshold)")
    print(f"   • Human typing simulation:        {'ACTIVE (Evades bot telemetry)' if HUMAN_TYPING_MODE else 'OFF'}")
    print(f"   • Spintax & unique hash entropy:  ACTIVE (Unique SHA-256 hash per dispatch)")
    print(f"   • Randomized delay range:         {MIN_DELAY_SECONDS} to {MAX_DELAY_SECONDS} seconds")
    print(f"   • Batch cooling break:            Every {BATCH_SIZE} sends -> {BATCH_COOLDOWN_MIN_MINUTES}-{BATCH_COOLDOWN_MAX_MINUTES} min randomized pause")
    print(f"   • Delivery log output:            {os.path.abspath(LOG_FILE)}")
    print(f"   • Session storage path:           {SESSION_DIR}")
    print("-" * 65)

    if sent_today >= DAILY_SAFETY_LIMIT and not is_dry_run:
        print(f"\n⚠️ [DAILY SAFETY CAP REACHED] You have already sent {sent_today} messages today.")
        print("   To protect your WhatsApp account from being flagged or banned, it is strongly")
        print("   recommended not to exceed 20-30 cold messages per day on a single number.")
        override = input("👉 Continue anyway at your own risk? (y/N): ").strip().lower()
        if override not in ["y", "yes"]:
            print("[!] Operation paused for account safety. You can resume tomorrow!")
            return

    if pending_count == 0:
        print("\n🎉 All contacts in 'contacts.csv' have already been processed!")
        print("To send again, clear 'sent_contacts.txt' or scrape new leads with 'scraper.py'.\n")
        return

    # 4. Load message template
    template = load_message_template()
    sample_contact = pending_contacts[0]
    sample_msg = format_message(template, sample_contact, safe_link=SAFE_LINK_MODE, soft_opt_out=True)

    print("\n📝 PREVIEW OF PERSONALIZED MESSAGE (First Contact with Spintax & Anti-Ban Hashing):")
    print("=" * 65)
    print(sample_msg)
    print("=" * 65)

    is_dry_run = "--dry-run" in sys.argv or "--test" in sys.argv
    if is_dry_run:
        print("\n🧪 [DRY-RUN / TEST MODE ENABLED]")
        print("   Simulating campaign pipeline without launching live WhatsApp session.")
    else:
        confirm = input("👉 Ready to proceed with automated sending? (Y/n): ").strip().lower()
        if confirm not in ["", "y", "yes"]:
            print("[!] Execution cancelled by user.")
            return

    # 5. Initialize Sending Engine
    driver = None
    success_count = 0
    failure_count = 0

    try:
        if not is_dry_run:
            driver = create_whatsapp_driver(SESSION_DIR)
            is_ready = wait_for_whatsapp_login(driver, timeout=120)
            if not is_ready:
                return
        else:
            print("[✓] Dry-run mock engine initialized.\n")

        print(f"[+] Starting dispatch queue for {pending_count} contacts...\n")

        for idx, row in enumerate(pending_contacts, start=1):
            phone = str(row.get("Phone", "")).strip()
            name = str(row.get("Name", "Valued Partner")).strip()

            # Safe display name for console
            safe_name = name.encode("ascii", errors="replace").decode("ascii")

            # 1. Check if banned institute (Allen, Aakash, Physics Wallah, etc.)
            banned, ban_reason = is_banned_institute(name)
            if banned:
                print(f"[{idx}/{pending_count}] 🛡️ BANNED INSTITUTE EXCLUDED: {safe_name} ({phone}) - {ban_reason}")
                log_delivery("BANNED", phone, name, f"Skipped: {ban_reason}")
                record_checkpoint(phone, status="banned")
                continue

            # 2. Check if landline number
            raw_digits = re.sub(r"[^\d]", "", phone).lstrip("0")
            if raw_digits.startswith("91") and len(raw_digits) == 12:
                raw_digits = raw_digits[2:]
            if len(raw_digits) == 10 and raw_digits[0] not in "6789":
                print(f"[{idx}/{pending_count}] ⚠️ LANDLINE DETECTED: {safe_name} ({phone}) - Skipping non-mobile number")
                log_delivery("INVALID", phone, name, "Landline number cannot receive WhatsApp messages")
                record_checkpoint(phone, status="invalid")
                continue

            print(f"[{idx}/{pending_count}] Sending to: {safe_name} ({phone})")

            # Format personalized message with Spintax, zero-width entropy, and soft opt-out
            msg = format_message(template, row, safe_link=SAFE_LINK_MODE, soft_opt_out=True)

            # Send message or simulate in dry-run
            if is_dry_run:
                time.sleep(1)
                success, detail = True, "Simulated successful dispatch (Dry-run mode)"
                print(f"    [SIMULATED] Would send to: {safe_name} ({phone})")
                success_count += 1
            else:
                success, detail = send_via_selenium(driver, phone, msg, human_typing=HUMAN_TYPING_MODE)

                if success:
                    log_delivery("SUCCESS", phone, name, detail)
                    success_count += 1
                    record_checkpoint(phone, status="sent")
                else:
                    is_invalid = "not registered" in detail.lower() or "landline" in detail.lower()
                    status_label = "INVALID" if is_invalid else "FAILED"
                    log_delivery(status_label, phone, name, detail)
                    failure_count += 1
                    if is_invalid:
                        record_checkpoint(phone, status="invalid")
                    # Temporary failures are not recorded in sent_contacts.txt so they can be retried

            # Anti-ban delay & Batch cooldown (only if there are more contacts remaining)
            if idx < pending_count:
                if is_dry_run:
                    print("    ⏳ [Dry-run] Pausing 2s before next simulated lead...\n")
                    time.sleep(2)
                else:
                    # After every BATCH_SIZE messages, take a randomized cooling break (5-10 min)
                    if idx % BATCH_SIZE == 0:
                        batch_cooldown_pause(BATCH_COOLDOWN_MIN_MINUTES, BATCH_COOLDOWN_MAX_MINUTES)
                    else:
                        anti_ban_delay(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)

        print("\n" + "=" * 65)
        print("🎉 WHATSAPP CAMPAIGN COMPLETE")
        print("=" * 65)
        print(f"Successfully Delivered: {success_count}")
        print(f"Failed / Invalid:       {failure_count}")
        print(f"Detailed Logs Saved:    {os.path.abspath(LOG_FILE)}")
        print(f"Checkpoint Updated:     {os.path.abspath(CHECKPOINT_FILE)}")
        print("=" * 65 + "\n")

    except KeyboardInterrupt:
        print("\n\n⚠️ Process paused by user (Ctrl+C).")
        print("Checkpoint saved! You can resume anytime by running 'python sender.py' again.")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            print("\n[+] Closing Chrome session. (WhatsApp login remains saved in 'whatsapp_session').")
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
