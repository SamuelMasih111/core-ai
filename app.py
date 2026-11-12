"""
Automation Control Center Web Application (app.py)
==================================================
A local, modern web-based Control Center to run and monitor:
1. Google Maps Lead Scraper (scraper.py)
2. WhatsApp Auto-Sender with Anti-Ban Protection (sender.py)

Features:
- Dynamic input control panel (location, query, lead limits)
- Real-time terminal log streaming (SSE)
- Live campaign progress tracker & cooldown timer
- Integrated Contacts Manager (view, filter, search, add, delete, export)
- Live Message Template Editor with real-time preview
- Anti-ban pause controller and checkpoint management
- Zero external dependencies: 100% local, runs on Flask
"""

from __future__ import annotations

import os
import re
import csv
import sys
import time
import json
import queue
import random
import threading
import webbrowser
import urllib.parse
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response, send_file

# Configure UTF-8 for console output
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Import core automation helpers
from scraper import clean_phone_number, is_valid_indian_mobile, create_driver, handle_consent_modal, scroll_feed_to_collect_items, extract_contact_info, save_contacts_to_csv, find_results_feed
from sender import (
    load_checkpoint, record_checkpoint, log_delivery, load_message_template,
    format_message, create_whatsapp_driver, wait_for_whatsapp_login,
    send_via_selenium, send_via_pywhatkit, normalize_whatsapp_phone,
    count_messages_sent_today, BATCH_SIZE, BATCH_COOLDOWN_MINUTES,
    BATCH_COOLDOWN_MIN_MINUTES, BATCH_COOLDOWN_MAX_MINUTES,
    DAILY_SAFETY_LIMIT, HUMAN_TYPING_MODE, SAFE_LINK_MODE
)
from blacklist import is_banned_institute, add_banned_institute, get_all_banned_keywords
import supabase_db

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Constants
CSV_FILE = os.path.join(BASE_DIR, "contacts.csv")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "sent_contacts.txt")
LOG_FILE = os.path.join(BASE_DIR, "delivery_log.txt")
TEMPLATE_FILE = os.path.join(BASE_DIR, "message_template.txt")
SESSION_DIR = os.path.join(BASE_DIR, "whatsapp_session")

# Global Event/Log Queues
log_queue = queue.Queue()
active_clients = []

# Execution State Tracker
state = {
    "scraper": {
        "status": "idle",       # idle, running, captcha_wait, stopping, finished, error
        "progress": 0,
        "total": 0,
        "query": "",
        "location": "",
        "found": 0,
        "error": None
    },
    "sender": {
        "status": "idle",       # idle, running, pausing, stopping, finished, error
        "mode": "live",         # live or test
        "progress": 0,
        "total": 0,
        "success": 0,
        "invalid": 0,
        "cooldown_remaining": 0,
        "current_contact": "",
        "error": None
    }
}

# Thread control locks & stop events
scraper_stop_event = threading.Event()
scraper_captcha_resolved = threading.Event()
sender_stop_event = threading.Event()

active_scraper_driver = None
active_sender_driver = None


def broadcast_log(message: str, category: str = "info"):
    """
    Pushes log message to SSE queue for real-time frontend terminal display.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "time": timestamp,
        "text": message,
        "category": category   # info, success, warning, error, alert
    }
    log_queue.put(entry)
    # Safely print to terminal without UnicodeEncodeError on Windows
    try:
        print(f"[{timestamp}] [{category.upper()}] {message}")
    except Exception:
        try:
            safe_text = message.encode("ascii", errors="replace").decode("ascii")
            print(f"[{timestamp}] [{category.upper()}] {safe_text}")
        except Exception:
            pass


# ==============================================================================
# BACKGROUND THREAD: SCRAPER WORKER
# ==============================================================================
def run_scraper_thread(location: str, query: str, target_count: int):
    global active_scraper_driver
    state["scraper"]["status"] = "running"
    state["scraper"]["progress"] = 0
    state["scraper"]["total"] = target_count
    state["scraper"]["found"] = 0
    state["scraper"]["error"] = None
    state["scraper"]["query"] = query
    state["scraper"]["location"] = location

    scraper_stop_event.clear()
    scraper_captcha_resolved.clear()

    driver = None
    search_term = f"{query} in {location}"
    encoded = urllib.parse.quote_plus(search_term)
    url = f"https://www.google.com/maps/search/{encoded}?hl=en"

    broadcast_log(f"🚀 Initializing Google Maps Scraper for: '{search_term}'", "info")
    broadcast_log(f"🎯 Target Leads: {target_count} | Output: {CSV_FILE}", "info")

    try:
        driver = create_driver(headless=False)
        active_scraper_driver = driver
        driver.get(url)
        time.sleep(3)

        handle_consent_modal(driver)

        # Check for CAPTCHA
        page_source = driver.page_source.lower()
        if "recaptcha" in page_source or "unusual traffic" in page_source:
            state["scraper"]["status"] = "captcha_wait"
            broadcast_log("⚠️ CAPTCHA Detected! Please solve it in the Chrome window and click 'I Solved It' in the UI.", "alert")
            while not scraper_captcha_resolved.is_set():
                if scraper_stop_event.is_set():
                    break
                time.sleep(1)
            state["scraper"]["status"] = "running"
            broadcast_log("✓ Resuming scraper after CAPTCHA resolution...", "success")

        feed = find_results_feed(driver, timeout=12)
        cards = scroll_feed_to_collect_items(driver, feed, target_count=target_count)

        if not cards:
            broadcast_log("❌ No business listing cards were located on Google Maps.", "warning")
            state["scraper"]["status"] = "finished"
            return

        total_cards = len(cards)
        state["scraper"]["total"] = total_cards
        broadcast_log(f"✓ Discovered {total_cards} listing cards. Beginning extraction...", "info")

        extracted_batch = []
        for idx, card in enumerate(cards, start=1):
            if scraper_stop_event.is_set():
                broadcast_log("🛑 Scraper cancelled by user request.", "warning")
                break

            state["scraper"]["progress"] = idx

            # Extract info
            info = extract_contact_info(driver, card)
            if info:
                info["location"] = location
                info["search_query"] = query
                info["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                banned, ban_reason = is_banned_institute(info["name"])
                if banned or info.get("is_banned"):
                    broadcast_log(f"[{idx}/{total_cards}] 🛡️ BANNED: {info['name']} skipped ({ban_reason})", "warning")
                    continue

                phone = info.get("clean_phone")
                if phone:
                    if not is_valid_indian_mobile(phone):
                        broadcast_log(f"[{idx}/{total_cards}] ⚠️ Landline skipped: {info['name']} ({phone})", "warning")
                        continue
                    state["scraper"]["found"] += 1
                    broadcast_log(f"[{idx}/{total_cards}] ✓ Extracted: {info['name']} -> {phone}", "success")
                else:
                    broadcast_log(f"[{idx}/{total_cards}] ⚠️ {info['name']} (No valid phone found)", "warning")

                extracted_batch.append(info)

        # Save to CSV
        new_saved, total_in_file = save_contacts_to_csv(extracted_batch, CSV_FILE)
        broadcast_log(f"🎉 Scraping Complete! {new_saved} new contacts saved to '{CSV_FILE}' (Total: {total_in_file}).", "success")

        # Sync to Supabase cloud if connected
        if supabase_db.is_connected():
            sb_upserted, sb_total = supabase_db.upsert_contacts(extracted_batch)
            broadcast_log(f"☁️ [SUPABASE CLOUD] Synced {sb_upserted} leads to Supabase PostgreSQL (Total in DB: {sb_total})", "success")

        state["scraper"]["status"] = "finished"

    except Exception as e:
        broadcast_log(f"❌ Scraper error: {str(e)}", "error")
        state["scraper"]["status"] = "error"
        state["scraper"]["error"] = str(e)
    finally:
        active_scraper_driver = None
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ==============================================================================
# BACKGROUND THREAD: SENDER WORKER
# ==============================================================================
def run_sender_thread(mode: str = "live", min_delay: int = 30, max_delay: int = 60):
    global active_sender_driver
    state["sender"]["status"] = "running"
    state["sender"]["mode"] = mode
    state["sender"]["progress"] = 0
    state["sender"]["success"] = 0
    state["sender"]["invalid"] = 0
    state["sender"]["error"] = None
    state["sender"]["cooldown_remaining"] = 0

    sender_stop_event.clear()

    if not os.path.exists(CSV_FILE):
        broadcast_log(f"❌ '{CSV_FILE}' not found. Run scraper first!", "error")
        state["sender"]["status"] = "error"
        return

    # Load contacts
    all_contacts = []
    try:
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Phone", "").strip():
                    all_contacts.append(row)
    except Exception as e:
        broadcast_log(f"❌ Error loading contacts: {e}", "error")
        state["sender"]["status"] = "error"
        return

    processed = load_checkpoint()
    pending = [c for c in all_contacts if c.get("Phone", "").strip() not in processed]
    total_pending = len(pending)

    state["sender"]["total"] = total_pending

    if total_pending == 0:
        broadcast_log("🎉 All contacts in 'contacts.csv' have already been processed!", "info")
        state["sender"]["status"] = "finished"
        return

    template = load_message_template()
    sent_today = count_messages_sent_today()

    broadcast_log(f"🚀 Starting WhatsApp Campaign ({mode.upper()} MODE) for {total_pending} contacts", "info")
    broadcast_log(f"🛡️ Anti-ban shield: Random delay {min_delay}s-{max_delay}s | Human typing: {'ON' if HUMAN_TYPING_MODE else 'OFF'}", "info")
    broadcast_log(f"📊 Daily Health: {sent_today}/{DAILY_SAFETY_LIMIT} sent today | Batch cooldown: Every {BATCH_SIZE} msgs -> {BATCH_COOLDOWN_MIN_MINUTES}-{BATCH_COOLDOWN_MAX_MINUTES}m random break", "info")

    if sent_today >= DAILY_SAFETY_LIMIT and mode == "live":
        broadcast_log(f"⚠️ [SAFETY WARNING] Daily recommended limit ({DAILY_SAFETY_LIMIT}) reached! Sending more risks automated WhatsApp flags.", "warning")

    driver = None
    try:
        if mode == "live":
            broadcast_log("📱 Launching Chrome WhatsApp Web session...", "info")
            driver = create_whatsapp_driver(SESSION_DIR)
            active_sender_driver = driver

            state["sender"]["status"] = "qr_wait"
            broadcast_log("👉 [SCAN QR CODE] Chrome has opened WhatsApp Web. Please scan the QR code to connect your account!", "alert")

            def on_qr():
                state["sender"]["status"] = "qr_wait"
                broadcast_log("📱 QR Code is visible on Chrome! Open WhatsApp on phone -> Linked Devices -> Scan.", "alert")

            is_ready = wait_for_whatsapp_login(driver, timeout=180, on_qr_callback=on_qr)
            if not is_ready:
                broadcast_log("❌ WhatsApp Web login timeout or cancelled.", "error")
                state["sender"]["status"] = "error"
                return

            state["sender"]["status"] = "running"
            broadcast_log("✓ WhatsApp Web authenticated! Starting dispatch queue...", "success")

        for idx, row in enumerate(pending, start=1):
            if sender_stop_event.is_set():
                broadcast_log("🛑 Campaign stopped by user.", "warning")
                break

            phone = str(row.get("Phone", "")).strip()
            name = str(row.get("Name", "Valued Partner")).strip()

            state["sender"]["progress"] = idx
            state["sender"]["current_contact"] = f"{name} ({phone})"

            # 1. Check if banned institute
            banned, ban_reason = is_banned_institute(name)
            if banned:
                broadcast_log(f"[{idx}/{total_pending}] 🛡️ BANNED INSTITUTE EXCLUDED: {name} ({phone}) - {ban_reason}", "warning")
                log_delivery("BANNED", phone, name, f"Skipped: {ban_reason}")
                record_checkpoint(phone, status="banned")
                continue

            # 2. Check if landline
            raw_digits = re.sub(r"[^\d]", "", phone).lstrip("0")
            if raw_digits.startswith("91") and len(raw_digits) == 12:
                raw_digits = raw_digits[2:]
            if len(raw_digits) == 10 and raw_digits[0] not in "6789":
                broadcast_log(f"[{idx}/{total_pending}] ⚠️ Landline detected: {name} ({phone}) - Skipping non-mobile number", "warning")
                log_delivery("INVALID", phone, name, "Landline number cannot receive WhatsApp messages")
                record_checkpoint(phone, status="invalid")
                continue

            # Format with Spintax, zero-width unique byte entropy, and soft opt-out
            msg = format_message(template, row, safe_link=SAFE_LINK_MODE, soft_opt_out=True)
            broadcast_log(f"[{idx}/{total_pending}] Sending to: {name} ({phone})...", "info")

            if mode == "test":
                time.sleep(1.2)
                state["sender"]["success"] += 1
                broadcast_log(f"    ✓ [SIMULATED TEST] Sent to {name} ({phone})", "info")
            else:
                success, detail = send_via_selenium(driver, phone, msg, human_typing=HUMAN_TYPING_MODE)

                if success:
                    state["sender"]["success"] += 1
                    log_delivery("SUCCESS", phone, name, detail)
                    broadcast_log(f"    ✓ [SUCCESS] Sent to {name} ({phone})", "success")
                    record_checkpoint(phone, status="sent")
                else:
                    is_invalid = "not registered" in detail.lower() or "landline" in detail.lower()
                    status_label = "INVALID" if is_invalid else "FAILED"
                    state["sender"]["invalid"] += 1
                    log_delivery(status_label, phone, name, detail)
                    broadcast_log(f"    ❌ [{status_label}] {name} ({phone}) - {detail}", "warning")
                    if is_invalid:
                        record_checkpoint(phone, status="invalid")

            # Anti-ban delay & Batch cooldown
            if idx < total_pending and not sender_stop_event.is_set():
                if mode == "live" and idx % BATCH_SIZE == 0:
                    total_break_secs = random.randint(BATCH_COOLDOWN_MIN_MINUTES * 60, BATCH_COOLDOWN_MAX_MINUTES * 60)
                    break_mins_display = round(total_break_secs / 60, 1)
                    broadcast_log(
                        f"☕ [BATCH COOLING BREAK] Reached {BATCH_SIZE} sends! Pausing for randomized {break_mins_display} minutes ({BATCH_COOLDOWN_MIN_MINUTES}-{BATCH_COOLDOWN_MAX_MINUTES}m range) to protect WhatsApp health...",
                        "alert"
                    )
                    state["sender"]["status"] = "pausing"
                    for rem in range(total_break_secs, 0, -1):
                        if sender_stop_event.is_set():
                            break
                        state["sender"]["cooldown_remaining"] = rem
                        if rem % 60 == 0:
                            broadcast_log(f"☕ Batch cooldown remaining: {rem // 60}m...", "info")
                        time.sleep(1)
                    state["sender"]["cooldown_remaining"] = 0
                    state["sender"]["status"] = "running"
                    broadcast_log("✓ Batch cooling break finished! Resuming dispatch queue...", "success")
                else:
                    delay = random.randint(min_delay, max_delay) if mode == "live" else 1
                    broadcast_log(f"⏳ Anti-ban cooldown: Waiting {delay}s before next message...", "info")
                    state["sender"]["status"] = "pausing"
                    for rem in range(delay, 0, -1):
                        if sender_stop_event.is_set():
                            break
                        state["sender"]["cooldown_remaining"] = rem
                        time.sleep(1)
                    state["sender"]["cooldown_remaining"] = 0
                    state["sender"]["status"] = "running"

        broadcast_log("🎉 WhatsApp Campaign finished!", "success")
        state["sender"]["status"] = "finished"

    except Exception as e:
        broadcast_log(f"❌ Campaign error: {str(e)}", "error")
        state["sender"]["status"] = "error"
        state["sender"]["error"] = str(e)
    finally:
        active_sender_driver = None
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ==============================================================================
# FLASK WEB ROUTES & APIS
# ==============================================================================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def get_status():
    return jsonify({
        "scraper": state["scraper"],
        "sender": state["sender"],
        "supabase": supabase_db.get_connection_status(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/api/supabase/status", methods=["GET"])
def get_supabase_status():
    return jsonify(supabase_db.get_connection_status())


@app.route("/api/supabase/reconnect", methods=["POST"])
def reconnect_supabase():
    success = supabase_db.init_supabase()
    status = supabase_db.get_connection_status()
    if success:
        broadcast_log("✓ Supabase cloud database connected successfully!", "success")
    else:
        broadcast_log(f"⚠️ Supabase connection failed: {status.get('error')}", "warning")
    return jsonify(status)


@app.route("/api/supabase/sync", methods=["POST"])
def sync_to_supabase():
    count, msg = supabase_db.sync_csv_to_supabase(CSV_FILE)
    category = "success" if count > 0 or "Successfully" in msg else "warning"
    broadcast_log(f"🔄 CSV -> Supabase: {msg}", category)
    return jsonify({"status": "success" if category == "success" else "error", "message": msg, "synced_count": count})


@app.route("/api/supabase/export", methods=["POST"])
def export_from_supabase():
    count, msg = supabase_db.export_supabase_to_csv(CSV_FILE)
    category = "success" if count > 0 else "warning"
    broadcast_log(f"🔄 Supabase -> CSV: {msg}", category)
    return jsonify({"status": "success" if count > 0 else "error", "message": msg, "count": count})


@app.route("/api/scraper/start", methods=["POST"])
def start_scraper():
    if state["scraper"]["status"] in ["running", "captcha_wait"]:
        return jsonify({"status": "error", "message": "Scraper is already running!"}), 400

    data = request.json or {}
    location = data.get("location", "").strip()
    query = data.get("query", "").strip()
    limit = int(data.get("limit", 25))

    if not location or not query:
        return jsonify({"status": "error", "message": "Location and Query are required!"}), 400

    thread = threading.Thread(target=run_scraper_thread, args=(location, query, limit), daemon=True)
    thread.start()
    return jsonify({"status": "success", "message": "Scraper started successfully."})


@app.route("/api/scraper/stop", methods=["POST"])
def stop_scraper():
    scraper_stop_event.set()
    scraper_captcha_resolved.set()
    state["scraper"]["status"] = "idle"
    broadcast_log("🛑 Scraper termination signal sent.", "warning")
    return jsonify({"status": "success", "message": "Scraper stop requested."})


@app.route("/api/scraper/resolve-captcha", methods=["POST"])
def resolve_captcha():
    scraper_captcha_resolved.set()
    broadcast_log("✓ User confirmed CAPTCHA resolution.", "info")
    return jsonify({"status": "success", "message": "Resumed from CAPTCHA."})


@app.route("/api/sender/start", methods=["POST"])
def start_sender():
    if state["sender"]["status"] in ["running", "pausing"]:
        return jsonify({"status": "error", "message": "WhatsApp Campaign is already running!"}), 400

    data = request.json or {}
    mode = data.get("mode", "live")
    min_delay = int(data.get("min_delay", 30))
    max_delay = int(data.get("max_delay", 60))

    thread = threading.Thread(target=run_sender_thread, args=(mode, min_delay, max_delay), daemon=True)
    thread.start()
    return jsonify({"status": "success", "message": f"WhatsApp sender started in {mode.upper()} mode."})


@app.route("/api/sender/stop", methods=["POST"])
def stop_sender():
    global active_sender_driver
    sender_stop_event.set()
    if active_sender_driver:
        try:
            active_sender_driver.quit()
        except Exception:
            pass
        active_sender_driver = None
    state["sender"]["status"] = "idle"
    broadcast_log("🛑 WhatsApp campaign termination signal sent.", "warning")
    return jsonify({"status": "success", "message": "Sender stop requested."})


@app.route("/api/sender/qr_code", methods=["GET"])
def get_sender_qr_code():
    global active_sender_driver
    if not active_sender_driver:
        return jsonify({"status": "error", "message": "No active WhatsApp session"}), 404

    try:
        from selenium.webdriver.common.by import By
        # Look for the canvas element containing the QR code
        canvases = active_sender_driver.find_elements(By.XPATH, "//canvas")
        if canvases and canvases[0].is_displayed():
            png_bytes = canvases[0].screenshot_as_png
            return Response(png_bytes, mimetype="image/png")
        
        # Fallback to screenshot
        png_bytes = active_sender_driver.get_screenshot_as_png()
        return Response(png_bytes, mimetype="image/png")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/contacts", methods=["GET"])
def get_contacts():
    contacts = []
    processed_set = load_checkpoint()

    # Priority 1: Supabase Cloud Database (if connected)
    if supabase_db.is_connected():
        try:
            db_rows = supabase_db.get_all_contacts(limit=500)
            if db_rows:
                for idx, r in enumerate(db_rows, start=1):
                    phone = str(r.get("phone", "")).strip()
                    is_sent = r.get("status") in ["sent", "SUCCESS"] or phone in processed_set
                    banned, reason = is_banned_institute(r.get("name") or "")
                    contacts.append({
                        "id": idx,
                        "Name": r.get("name") or "Valued Partner",
                        "Phone": phone,
                        "Raw_Phone": r.get("raw_phone", ""),
                        "Address": r.get("address", ""),
                        "Website": r.get("website", ""),
                        "Search_Query": r.get("search_query", ""),
                        "Location": r.get("location", ""),
                        "Scraped_At": str(r.get("scraped_at", ""))[:19],
                        "status": "banned" if banned else r.get("status", "pending"),
                        "is_processed": is_sent,
                        "is_banned": banned,
                        "ban_reason": reason
                    })
                return jsonify({
                    "status": "success",
                    "total": len(contacts),
                    "processed_count": len([c for c in contacts if c.get("is_processed")]),
                    "source": "supabase_cloud",
                    "contacts": contacts
                })
        except Exception as e:
            broadcast_log(f"Supabase contacts load warning: {e}", "warning")

    # Priority 2: Local CSV Fallback
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader, start=1):
                    phone = row.get("Phone", "").strip()
                    row["id"] = idx
                    row["is_processed"] = phone in processed_set
                    banned, reason = is_banned_institute(row.get("Name") or "")
                    row["is_banned"] = banned
                    row["ban_reason"] = reason
                    if banned:
                        row["status"] = "banned"
                    contacts.append(row)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({
        "status": "success",
        "total": len(contacts),
        "processed_count": len([c for c in contacts if c.get("is_processed")]),
        "source": "local_csv",
        "contacts": contacts
    })


@app.route("/api/contacts/add", methods=["POST"])
def add_contact():
    data = request.json or {}
    name = data.get("name", "Manual Contact").strip()

    # Verify if institute is banned
    banned, reason = is_banned_institute(name)
    if banned:
        return jsonify({"status": "error", "message": f"Cannot add contact: {name} is on the banned institutes list ({reason})."}), 400

    raw_phone = data.get("phone", "").strip()
    clean = clean_phone_number(raw_phone)
    if not clean:
        return jsonify({"status": "error", "message": "Invalid 10-digit phone number!"}), 400

    if not is_valid_indian_mobile(clean):
        return jsonify({"status": "error", "message": f"'{clean}' is a landline/invalid number. Indian mobile numbers must start with 6, 7, 8, or 9."}), 400

    new_row = {
        "Name": name,
        "Phone": clean,
        "clean_phone": clean,
        "Raw_Phone": raw_phone,
        "Address": data.get("address", "").strip(),
        "Website": data.get("website", "").strip(),
        "Search_Query": data.get("query", "Manual").strip(),
        "Location": data.get("location", "Direct").strip(),
        "Scraped_At": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Save to CSV
    save_contacts_to_csv([new_row], CSV_FILE)

    # Save to Supabase Cloud
    if supabase_db.is_connected():
        supabase_db.upsert_contacts([new_row])

    broadcast_log(f"✓ Added lead: {new_row['Name']} ({clean})", "success")
    return jsonify({"status": "success", "message": "Contact added successfully."})


@app.route("/api/contacts/delete", methods=["POST"])
def delete_contact():
    data = request.json or {}
    phone_to_del = data.get("phone", "").strip()
    if not phone_to_del:
        return jsonify({"status": "error", "message": "Invalid phone number."}), 400

    # Delete from CSV
    if os.path.exists(CSV_FILE):
        rows = []
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for r in reader:
                if r.get("Phone", "").strip() != phone_to_del:
                    rows.append(r)

        with open(CSV_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    # Delete from Supabase Cloud
    if supabase_db.is_connected():
        supabase_db.delete_contact(phone_to_del)

    broadcast_log(f"🗑️ Deleted contact: {phone_to_del}", "info")
    return jsonify({"status": "success", "message": "Contact deleted."})


@app.route("/api/contacts/clear", methods=["POST"])
def clear_contacts():
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Phone", "Raw_Phone", "Address", "Website", "Search_Query", "Location", "Scraped_At"])

    # Clear Supabase Cloud
    if supabase_db.is_connected():
        supabase_db.clear_all_contacts()

    broadcast_log("🗑️ Contacts list cleared.", "warning")
    return jsonify({"status": "success", "message": "All contacts cleared."})


@app.route("/api/contacts/export", methods=["GET"])
def export_contacts():
    if os.path.exists(CSV_FILE):
        return send_file(CSV_FILE, as_attachment=True, download_name="contacts.csv")
    return jsonify({"status": "error", "message": "File not found"}), 404


@app.route("/api/blacklist", methods=["GET", "POST"])
def manage_blacklist():
    if request.method == "POST":
        data = request.json or {}
        keyword = data.get("keyword", "").strip()
        if not keyword:
            return jsonify({"status": "error", "message": "Keyword cannot be empty!"}), 400
        ok = add_banned_institute(keyword)
        if ok:
            broadcast_log(f"🛡️ Added '{keyword}' to banned institutes list.", "info")
            return jsonify({"status": "success", "message": f"Added '{keyword}' to banned institutes list."})
        return jsonify({"status": "error", "message": "Failed to add banned institute"}), 500
    else:
        keywords = get_all_banned_keywords()
        return jsonify({"status": "success", "banned_keywords": keywords})


@app.route("/api/template", methods=["GET", "POST"])
def manage_template():
    if request.method == "POST":
        data = request.json or {}
        new_template = data.get("template", "").strip()
        if not new_template:
            return jsonify({"status": "error", "message": "Template cannot be empty!"}), 400
        with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
            f.write(new_template)
        broadcast_log("✓ Message template updated successfully.", "success")
        return jsonify({"status": "success", "message": "Template saved."})
    else:
        tmpl = load_message_template()
        return jsonify({"status": "success", "template": tmpl})


@app.route("/api/checkpoint/reset", methods=["POST"])
def reset_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    broadcast_log("🔄 Checkpoint history reset! All contacts will now be re-sent on next campaign.", "info")
    return jsonify({"status": "success", "message": "Checkpoint reset successfully."})


@app.route("/api/logs/delivery", methods=["GET"])
def get_delivery_logs():
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        logs.append(line.strip())
        except Exception:
            pass
    return jsonify({"status": "success", "logs": logs[-200:]})


@app.route("/api/logs/stream")
def stream_logs():
    """
    Server-Sent Events (SSE) endpoint to stream live logs to the browser terminal.
    """
    def event_stream():
        while True:
            try:
                # Block for up to 1 second waiting for logs
                entry = log_queue.get(timeout=1.0)
                data = json.dumps(entry)
                yield f"data: {data}\n\n"
            except queue.Empty:
                # Keep-alive heartbeat
                yield ": heartbeat\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


# ==============================================================================
# MAIN LAUNCHER
# ==============================================================================
if __name__ == "__main__":
    port = 5000
    host = "127.0.0.1"
    url = f"http://{host}:{port}"

    print("=" * 65)
    print("      CORE AI AUTOMATION CONTROL CENTER - WEB DASHBOARD")
    print("=" * 65)
    print(f"🌐 Server starting at: {url}")
    print("👉 Opening your web browser automatically...")
    print("=====================================================\n")

    # Auto-open browser in 1.5 seconds
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    app.run(host=host, port=port, debug=False)
