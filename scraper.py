"""
Google Maps Scraper Module (scraper.py)
=======================================
A robust, local automation tool to scrape business listings from Google Maps
based on dynamic user inputs (Location and Search Query).

Features:
- Dynamic console inputs at runtime (no hardcoded search terms)
- Dynamic scrolling of Google Maps results panel
- Extraction of Institution/Business Name, Phone Number, Address, and Website
- Advanced Phone Number Cleaning:
    * Strips spaces, dashes, parentheses, and special characters
    * Strips leading zero (e.g., 09876543210 -> 9876543210)
    * Formats numbers with country code (e.g., +91XXXXXXXXXX)
    * Filters out invalid, short, or unusable numbers
- CAPTCHA / Bot detection pause mechanism (allows manual resolution)
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

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        NoSuchElementException,
        StaleElementReferenceException,
        ElementClickInterceptedException,
    )
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# Optional webdriver-manager support for legacy environments
try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WDM = True
except ImportError:
    USE_WDM = False



# ==============================================================================
# PHONE NUMBER CLEANING ENGINE
# ==============================================================================
def clean_phone_number(raw_phone: str, country_code_to_strip: str = "91") -> str | None:
    """
    Cleans, normalizes, and extracts a pure 10-digit phone number.
    Strips '+91', leading zero '0', spaces, dashes, brackets, and special characters.
    This prevents WhatsApp from duplicating country prefixes.
    
    Rules applied:
    1. Removes all spaces, dashes, dots, brackets, and non-digit characters.
    2. Strips international prefixes ('00', '+').
    3. Strips '+91' or '91' when present with a 10-digit number (e.g., '919876543210' -> '9876543210').
    4. Strips leading zero(s) (e.g., '09876543210' -> '9876543210').
    5. Validates that the resulting mobile number is exactly 10 digits.
    6. Rejects numbers that are invalid, short, or consist of repetitive dummy digits.
    
    Returns:
        Clean 10-digit string (e.g. '9876543210') or None if invalid.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        return None

    # Normalize country code prefix to strip (e.g. '+91' -> '91')
    code_digits = country_code_to_strip.lstrip("+").strip()

    # Extract all digits
    digits_only = re.sub(r"[^\d]", "", raw_phone)
    if not digits_only:
        return None

    # Handle international dialing prefix '00' (e.g. 0091... -> 91...)
    if digits_only.startswith("00"):
        digits_only = digits_only[2:]

    # Strip country code if present at the start (e.g., 919876543210 -> 9876543210)
    if code_digits and digits_only.startswith(code_digits) and len(digits_only) == (len(code_digits) + 10):
        digits_only = digits_only[len(code_digits):]

    # Strip leading zero(s) (e.g. 09876543210 -> 9876543210)
    while digits_only.startswith("0"):
        digits_only = digits_only[1:]

    # Check again if country code was placed after a leading zero (e.g., 0919876543210)
    if code_digits and digits_only.startswith(code_digits) and len(digits_only) == (len(code_digits) + 10):
        digits_only = digits_only[len(code_digits):]

    # Validate resulting length: standard mobile number must be exactly 10 digits
    if len(digits_only) != 10:
        return None

    # Sanity checks: reject dummy repeating numbers like 9999999999, 0000000000
    if len(set(digits_only[-8:])) <= 1:
        return None

    return digits_only


def is_valid_indian_mobile(phone: str | None) -> bool:
    """
    Validates whether a 10-digit number is an Indian mobile number.
    In India (TRAI numbering plan), all mobile numbers start with 6, 7, 8, or 9.
    Numbers starting with 1, 2, 3, 4, 5 are landlines/STD codes or special services.
    """
    if not phone or not isinstance(phone, str):
        return False
    digits = re.sub(r"[^\d]", "", phone)
    return len(digits) == 10 and digits[0] in "6789"


# ==============================================================================
# BROWSER DRIVER INITIALIZATION
# ==============================================================================
def create_driver(headless: bool = False):
    """
    Configures and initializes Chrome WebDriver with anti-detection flags.
    """
    if not HAS_SELENIUM:
        raise ImportError(
            "Selenium is required to run the scraper.\n"
            "Please install dependencies with: pip install -r requirements.txt"
        )

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--lang=en-US")
    
    # Realistic User-Agent
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Exclude automation flags to evade basic detection
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    try:
        # Modern Selenium 4 Manager handles driver automatically
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"[i] Selenium Manager encountered: {e}. Trying webdriver-manager fallback...")
        if USE_WDM:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        else:
            raise

    # Override navigator.webdriver
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
    )
    return driver


# ==============================================================================
# BOT & CAPTCHA DETECTION
# ==============================================================================
def check_for_captcha(driver: webdriver.Chrome) -> None:
    """
    Checks if a CAPTCHA or Google bot verification block is present.
    Pauses execution and alerts the user to solve it manually in the browser.
    """
    page_source = driver.page_source.lower()
    current_url = driver.current_url.lower()

    captcha_indicators = [
        "recaptcha",
        "sorry/index",
        "unusual traffic from your computer network",
        "solve the challenge below",
        "verify that you are human",
        "our systems have detected unusual traffic"
    ]

    is_blocked = any(ind in page_source or ind in current_url for ind in captcha_indicators)

    if is_blocked:
        print("\n" + "=" * 65)
        print("⚠️  SECURITY ALERT: GOOGLE VERIFICATION / CAPTCHA DETECTED!")
        print("=" * 65)
        print("Google has displayed a challenge or verification page.")
        print("1. Switch to the open Chrome browser window.")
        print("2. Solve the CAPTCHA / puzzle manually.")
        print("3. Once the normal Google Maps interface is visible, return here.")
        print("=" * 65)
        input("👉 Press [ENTER] in this terminal once you have solved the CAPTCHA: ")
        print("[✓] Resuming scraping process...\n")
        time.sleep(2)


def handle_consent_modal(driver: webdriver.Chrome) -> None:
    """
    Auto-clicks Google's 'Accept All' or consent buttons if shown.
    """
    try:
        buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(., 'Accept all') or contains(., 'I agree') or contains(@aria-label, 'Accept all')]"
        )
        if buttons:
            buttons[0].click()
            time.sleep(1)
    except Exception:
        pass


# ==============================================================================
# SCROLLING & RESULTS EXTRACTION
# ==============================================================================
def find_results_feed(driver: webdriver.Chrome, timeout: int = 15):
    """
    Locates the scrollable container holding search results.
    """
    feed_xpaths = [
        "//div[@role='feed']",
        "//div[contains(@aria-label, 'Results for')]",
        "//div[contains(@class, 'm6QErb') and contains(@class, 'DxyBCb')]"
    ]
    start_time = time.time()
    while time.time() - start_time < timeout:
        for xpath in feed_xpaths:
            elements = driver.find_elements(By.XPATH, xpath)
            if elements and elements[0].is_displayed():
                return elements[0]
        time.sleep(0.5)
    return None


def scroll_feed_to_collect_items(
    driver: webdriver.Chrome,
    feed_element,
    target_count: int = 30,
    max_scroll_attempts: int = 60
) -> list:
    """
    Dynamically scrolls the results feed panel to trigger lazy loading of entries.
    Returns list of WebElements representing business listing cards.
    """
    print(f"\n[+] Scrolling results panel to discover up to {target_count} listings...")
    
    collected_cards = []
    last_item_count = 0
    stagnant_scrolls = 0

    for scroll_num in range(1, max_scroll_attempts + 1):
        check_for_captcha(driver)

        # In Google Maps, cards link with role='article' or anchor tag with class 'hfpxzc'
        cards = driver.find_elements(
            By.XPATH,
            "//a[contains(@class, 'hfpxzc') or contains(@href, '/maps/place/')]"
        )
        
        # Deduplicate by unique href
        seen_urls = set()
        unique_cards = []
        for c in cards:
            try:
                href = c.get_attribute("href")
                if href and "/maps/place/" in href and href not in seen_urls:
                    seen_urls.add(href)
                    unique_cards.append(c)
            except StaleElementReferenceException:
                continue

        collected_cards = unique_cards
        current_count = len(collected_cards)
        print(f"    • Loaded {current_count}/{target_count} listings (Scroll #{scroll_num})...", end="\r")

        if current_count >= target_count:
            print(f"\n[✓] Reached requested target of {target_count} listings!")
            break

        # Check if Google Maps displays 'end of list' message
        end_indicators = driver.find_elements(
            By.XPATH,
            "//*[contains(text(), \"You've reached the end of the list\") or contains(text(), \"No more results\")]"
        )
        if end_indicators:
            print("\n[i] Google Maps reached the end of available results.")
            break

        # Scroll the feed container
        if feed_element:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", feed_element)
        else:
            # Fallback to key scrolling
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        time.sleep(random.uniform(1.8, 2.6))

        # Check for stagnation (end of feed with no new items)
        if current_count == last_item_count:
            stagnant_scrolls += 1
            if stagnant_scrolls >= 5:
                print("\n[i] No more new listings loading. Proceeding with extracted items.")
                break
        else:
            stagnant_scrolls = 0

        last_item_count = current_count

    return collected_cards[:target_count]


# ==============================================================================
# DETAIL EXTRACTION PER LISTING
# ==============================================================================
def extract_contact_info(driver: webdriver.Chrome, card_element) -> dict | None:
    """
    Clicks a listing card to load the side detail panel, extracts name,
    phone number, address, and website, then cleans the phone number.
    """
    try:
        # Extract name from card's aria-label first as a safeguard
        name = card_element.get_attribute("aria-label") or ""
        listing_url = card_element.get_attribute("href") or ""

        # Scroll item into view and click
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card_element)
        time.sleep(0.3)
        try:
            card_element.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", card_element)

        # Allow side panel details to render
        time.sleep(random.uniform(1.2, 1.8))

        # 1. Business Name (from headline h1 if available)
        try:
            name_el = driver.find_element(
                By.XPATH,
                "//h1[contains(@class, 'DUwDvf') or contains(@class, 'fontHeadlineLarge')]"
            )
            if name_el.text.strip():
                name = name_el.text.strip()
        except NoSuchElementException:
            pass

        if not name:
            name = "Unknown Business"

        # 2. Phone Number Extraction
        raw_phone = ""
        # Strategy A: button with data-item-id starting with 'phone:tel:'
        try:
            phone_btn = driver.find_element(
                By.XPATH,
                "//button[starts-with(@data-item-id, 'phone:tel:') or contains(@data-item-id, 'phone')]"
            )
            raw_phone = phone_btn.get_attribute("data-item-id") or ""
            # Format: 'phone:tel:+919876543210' -> extract actual number
            if "phone:tel:" in raw_phone:
                raw_phone = raw_phone.replace("phone:tel:", "")
            else:
                # Text or aria-label of button
                raw_phone = phone_btn.get_attribute("aria-label") or phone_btn.text
        except NoSuchElementException:
            pass

        # Strategy B: aria-label containing 'Phone:'
        if not raw_phone:
            try:
                phone_btn2 = driver.find_element(
                    By.XPATH,
                    "//button[contains(@aria-label, 'Phone:') or contains(@aria-label, 'phone')]"
                )
                raw_phone = phone_btn2.get_attribute("aria-label") or phone_btn2.text
            except NoSuchElementException:
                pass

        # Strategy C: anchor tag with 'tel:'
        if not raw_phone:
            try:
                tel_link = driver.find_element(By.XPATH, "//a[starts-with(@href, 'tel:')]")
                raw_phone = tel_link.get_attribute("href").replace("tel:", "")
            except NoSuchElementException:
                pass

        # Clean the extracted phone number if present
        clean_phone = clean_phone_number(raw_phone) if raw_phone else None

        # 3. Address Extraction
        address = ""
        try:
            addr_btn = driver.find_element(
                By.XPATH,
                "//button[@data-item-id='address' or contains(@aria-label, 'Address:')]"
            )
            address = addr_btn.get_attribute("aria-label") or addr_btn.text
            if address.startswith("Address:"):
                address = address.replace("Address:", "").strip()
        except NoSuchElementException:
            pass

        # 4. Website Extraction (bonus)
        website = ""
        try:
            web_btn = driver.find_element(
                By.XPATH,
                "//a[@data-item-id='authority' or contains(@aria-label, 'Website:')]"
            )
            website = web_btn.get_attribute("href") or ""
        except NoSuchElementException:
            pass

        # Check if banned institute
        banned, ban_reason = is_banned_institute(name)

        return {
            "name": name,
            "raw_phone": raw_phone.strip(),
            "clean_phone": clean_phone,
            "address": address.strip(),
            "website": website.strip(),
            "url": listing_url,
            "is_banned": banned,
            "ban_reason": ban_reason
        }

    except Exception as e:
        # Ignore individual element errors to maintain scraper stability
        return None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(BASE_DIR, "contacts.csv")

# ==============================================================================
# CSV EXPORT & DEDUPLICATION
# ==============================================================================
def save_contacts_to_csv(contacts: list, filename: str = DEFAULT_CSV) -> tuple[int, int]:
    """
    Saves contacts to contacts.csv. Deduplicates against existing entries
    based on the cleaned phone number.
    
    Returns:
        (new_contacts_saved, total_existing_records)
    """
    fieldnames = [
        "Name",
        "Phone",
        "Raw_Phone",
        "Address",
        "Website",
        "Search_Query",
        "Location",
        "Scraped_At"
    ]

    existing_phones = set()
    file_exists = os.path.exists(filename) and os.path.getsize(filename) > 0

    if file_exists:
        try:
            with open(filename, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    phone = row.get("Phone", "").strip()
                    if phone:
                        existing_phones.add(phone)
        except Exception as e:
            print(f"[!] Warning reading existing CSV: {e}")

    new_saved = 0
    mode = "a" if file_exists else "w"

    with open(filename, mode=mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for contact in contacts:
            c_name = contact.get("name") or contact.get("Name") or "Valued Partner"
            banned, reason = is_banned_institute(c_name)
            if banned or contact.get("is_banned"):
                continue

            phone = str(contact.get("clean_phone") or contact.get("Phone") or contact.get("phone") or "").strip()
            # Filter out landline numbers (in India, mobile numbers start with 6, 7, 8, or 9)
            if phone and not is_valid_indian_mobile(phone):
                continue

            # Only save entries with a valid, non-duplicate cleaned phone
            if phone and phone not in existing_phones:
                writer.writerow({
                    "Name": contact.get("name") or contact.get("Name") or "Valued Partner",
                    "Phone": phone,
                    "Raw_Phone": contact.get("raw_phone") or contact.get("Raw_Phone", ""),
                    "Address": contact.get("address") or contact.get("Address", ""),
                    "Website": contact.get("website") or contact.get("Website", ""),
                    "Search_Query": contact.get("search_query") or contact.get("Search_Query", ""),
                    "Location": contact.get("location") or contact.get("Location", ""),
                    "Scraped_At": contact.get("scraped_at") or contact.get("Scraped_At") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                existing_phones.add(phone)
                new_saved += 1

    # Also automatically sync leads to Supabase if connected
    if supabase_db and supabase_db.is_connected() and contacts:
        try:
            sb_upserted, sb_total = supabase_db.upsert_contacts(contacts)
            print(f"  [☁️ SUPABASE] Synced {sb_upserted} leads to Supabase cloud (Total: {sb_total})")
        except Exception as e:
            print(f"  [!] Warning syncing leads to Supabase: {e}")

    return new_saved, len(existing_phones)


# ==============================================================================
# MAIN EXECUTION FLOW
# ==============================================================================
def main():
    print("=" * 65)
    print("      GOOGLE MAPS LOCAL SCRAPER & CONTACT CLEANER")
    print("=" * 65)
    print("Module 1 of WhatsApp Automation Suite | Free & Local\n")

    # 1. Dynamic Console Inputs
    while True:
        location = input("Enter the target location/city (e.g., Moradabad, Delhi): ").strip()
        if location:
            break
        print("❌ Location cannot be empty. Please enter a valid city or location.")

    while True:
        query = input("Enter the search query (e.g., schools, coaching centers, or teachers): ").strip()
        if query:
            break
        print("❌ Search query cannot be empty. Please enter what you want to search.")

    # Target limits & country code configuration
    limit_input = input("Enter max number of results to fetch [default 25]: ").strip()
    target_count = int(limit_input) if limit_input.isdigit() and int(limit_input) > 0 else 25

    # Sanitization Info
    print("\n[ℹ️ Info] Phone numbers will be sanitized into clean 10-digit numbers")
    print("         (+91 and leading 0 are automatically removed for WhatsApp compatibility).")

    # Combine inputs automatically
    search_term = f"{query} in {location}"
    encoded_search = urllib.parse.quote_plus(search_term)
    search_url = f"https://www.google.com/maps/search/{encoded_search}?hl=en"

    print("\n" + "-" * 65)
    print(f"🎯 Target Location: {location}")
    print(f"🔍 Search Query:    {query}")
    print(f"🌐 Combined Search:  {search_term}")
    print(f"🔢 Target Results:  {target_count}")
    print(f"📱 Number Format:   Clean 10-digit mobile (No +91 prefix)")
    print("-" * 65)

    print("\n[+] Launching Chrome browser...")
    driver = None
    try:
        driver = create_driver(headless=False)
        print(f"[+] Navigating to: {search_url}")
        driver.get(search_url)

        # Initial wait and modal handling
        time.sleep(3)
        handle_consent_modal(driver)
        check_for_captcha(driver)

        # Locate the scrollable results feed
        feed_element = find_results_feed(driver)
        if not feed_element:
            print("[!] Results feed container not immediately found. Searching page...")

        # Dynamically scroll to load requested number of results
        listing_cards = scroll_feed_to_collect_items(driver, feed_element, target_count=target_count)

        if not listing_cards:
            print("❌ No business listings were found for this query.")
            return

        print(f"\n[+] Extracting details from {len(listing_cards)} listings...")
        extracted_data = []
        valid_phone_count = 0

        for idx, card in enumerate(listing_cards, start=1):
            check_for_captcha(driver)
            print(f"    [{idx}/{len(listing_cards)}] Processing listing...", end="\r")

            info = extract_contact_info(driver, card)
            if info:
                info["location"] = location
                info["search_query"] = query
                info["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                safe_name = info['name'][:28].encode('ascii', errors='replace').decode('ascii')
                if info.get("is_banned"):
                    print(f"    [{idx}/{len(listing_cards)}] 🛡️ BANNED: {safe_name:<28} | ({info.get('ban_reason')})")
                    continue

                if info["clean_phone"]:
                    if not is_valid_indian_mobile(info["clean_phone"]):
                        print(f"    [{idx}/{len(listing_cards)}] ⚠️ LANDLINE: {safe_name:<28} | Skipped ({info['clean_phone']})")
                        continue
                    valid_phone_count += 1
                    print(f"    [{idx}/{len(listing_cards)}] ✓ {safe_name:<28} | {info['clean_phone']}")
                else:
                    raw_preview = info["raw_phone"] if info["raw_phone"] else "No phone"
                    print(f"    [{idx}/{len(listing_cards)}] ⚠️ {safe_name:<28} | Filtered ({raw_preview})")

                extracted_data.append(info)

        # Save to CSV with deduplication
        csv_filename = "contacts.csv"
        new_saved, total_in_file = save_contacts_to_csv(extracted_data, csv_filename)

        print("\n" + "=" * 65)
        print("🎉 SCRAPING & CLEANING SUMMARY")
        print("=" * 65)
        print(f"Total listings examined:       {len(extracted_data)}")
        print(f"Valid formatted phone numbers: {valid_phone_count}")
        print(f"New contacts saved to CSV:     {new_saved}")
        print(f"Total records in '{csv_filename}': {total_in_file}")
        print("=" * 65)
        print(f"📁 Output File: {os.path.abspath(csv_filename)}")
        print("👉 You can now review 'contacts.csv' or run 'python sender.py' to dispatch messages.\n")

    except KeyboardInterrupt:
        print("\n\n⚠️ Process interrupted by user. Saving already scraped results...")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            print("[+] Closing Chrome browser session.")
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
