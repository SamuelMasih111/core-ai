"""
Supabase Database Adapter Module (supabase_db.py)
=================================================
Provides seamless, high-performance database sync with Supabase PostgreSQL:
- Automatic deduplication of scraped leads on phone number
- Real-time campaign tracking & status updates ('pending', 'sent', 'invalid', 'failed')
- Structured audit logs for delivery events
- 1-Click synchronization between local contacts.csv and Supabase cloud
- Graceful offline fallback: if Supabase credentials are not configured or offline,
  the system runs in Local CSV Mode without interruption or crashes.
"""

from __future__ import annotations

import os
import csv
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Load environment variables from .env
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

# Setup module logger
logger = logging.getLogger("supabase_db")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [DB] %(message)s", datefmt="%H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Supabase Client Import
try:
    from supabase import create_client, Client
    HAS_SUPABASE_LIB = True
except ImportError:
    HAS_SUPABASE_LIB = False
    Client = Any

# Global connection state
_client: Optional[Client] = None
_is_connected: bool = False
_connection_error: Optional[str] = None


def init_supabase() -> bool:
    """
    Initializes and validates connection to Supabase using .env credentials.
    Returns True if connection succeeded, False otherwise.
    """
    global _client, _is_connected, _connection_error

    # Always reload .env so edits to credentials take effect immediately
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

    if not HAS_SUPABASE_LIB:
        _is_connected = False
        _connection_error = "supabase package is not installed (run 'pip install supabase')"
        logger.warning(f"⚠️ {_connection_error}")
        return False

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()

    if not url or not key or "your-project" in url or "your-supabase" in key:
        _is_connected = False
        _connection_error = "Supabase URL or Key not set in .env file"
        return False

    try:
        _client = create_client(url, key)
        # Test connection by making a small lightweight query
        _ = _client.table("contacts").select("id").limit(1).execute()
        _is_connected = True
        _connection_error = None
        logger.info(f"✓ Connected to Supabase project ({url.split('//')[-1].split('.')[0]})")
        return True
    except Exception as e:
        err_msg = str(e)
        _is_connected = False
        _connection_error = err_msg
        logger.warning(f"⚠️ Supabase connection failed: {err_msg}. Running in local CSV mode.")
        return False


def is_connected() -> bool:
    """Check if active Supabase connection is established."""
    global _is_connected
    if not _is_connected and os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"):
        # Attempt lazy reconnect
        return init_supabase()
    return _is_connected


def get_connection_status() -> Dict[str, Any]:
    """Returns detailed connection status dictionary for UI and API."""
    connected = is_connected()
    return {
        "connected": connected,
        "mode": "supabase_cloud" if connected else "local_csv",
        "url": os.getenv("SUPABASE_URL", "").strip() if connected else "",
        "error": _connection_error if not connected else None
    }


def normalize_contact_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Standardizes contact dictionary keys whether coming from scraper or CSV.
    """
    phone = str(item.get("Phone") or item.get("clean_phone") or item.get("phone") or "").strip()
    raw_phone = str(item.get("Raw_Phone") or item.get("raw_phone") or "").strip()
    name = str(item.get("Name") or item.get("name") or "Valued Partner").strip()
    address = str(item.get("Address") or item.get("address") or "").strip()
    website = str(item.get("Website") or item.get("website") or "").strip()
    query = str(item.get("Search_Query") or item.get("search_query") or "").strip()
    location = str(item.get("Location") or item.get("location") or "").strip()
    scraped_at = item.get("Scraped_At") or item.get("scraped_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = item.get("status") or "pending"

    return {
        "name": name,
        "phone": phone,
        "raw_phone": raw_phone,
        "address": address,
        "website": website,
        "search_query": query,
        "location": location,
        "scraped_at": scraped_at,
        "status": status
    }


def upsert_contacts(contacts_list: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Upserts a list of contacts into Supabase with automatic deduplication on 'phone'.
    Returns (inserted/updated_count, total_in_database).
    """
    if not is_connected() or not _client:
        return 0, 0

    valid_records = []
    for c in contacts_list:
        normalized = normalize_contact_dict(c)
        if normalized["phone"] and len(normalized["phone"]) >= 10:
            valid_records.append(normalized)

    if not valid_records:
        return 0, 0

    try:
        # Upsert in batches of 50 to avoid payload limits
        batch_size = 50
        upserted_count = 0
        for i in range(0, len(valid_records), batch_size):
            batch = valid_records[i:i + batch_size]
            res = _client.table("contacts").upsert(batch, on_conflict="phone").execute()
            if res.data:
                upserted_count += len(res.data)

        # Get total count
        count_res = _client.table("contacts").select("id", count="exact").execute()
        total_count = count_res.count if hasattr(count_res, "count") and count_res.count is not None else upserted_count
        return upserted_count, total_count
    except Exception as e:
        logger.error(f"Error upserting contacts to Supabase: {e}")
        return 0, 0


def get_pending_contacts(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Fetches contacts with status 'pending' ready for outreach.
    """
    if not is_connected() or not _client:
        return []

    try:
        query = _client.table("contacts").select("*").eq("status", "pending").order("id", desc=False)
        if limit:
            query = query.limit(limit)
        res = query.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching pending contacts: {e}")
        return []


def mark_contact_status(phone: str, status: str, detail: Optional[str] = None) -> bool:
    """
    Updates the delivery status of a contact by phone number.
    Statuses: 'pending', 'sent', 'invalid', 'failed'
    """
    if not is_connected() or not _client:
        return False

    phone = str(phone).strip()
    payload = {
        "status": status,
        "last_contacted_at": datetime.now().isoformat()
    }
    if detail:
        payload["notes"] = detail

    try:
        res = _client.table("contacts").update(payload).eq("phone", phone).execute()
        return bool(res.data)
    except Exception as e:
        logger.error(f"Error updating contact status for {phone}: {e}")
        return False


def log_delivery_event(status: str, phone: str, name: str = "", detail: str = "") -> bool:
    """
    Records a delivery event in the Supabase 'delivery_logs' table.
    """
    if not is_connected() or not _client:
        return False

    phone = str(phone).strip()
    try:
        payload = {
            "phone": phone,
            "name": name,
            "status": status.upper(),
            "detail": detail,
            "logged_at": datetime.now().isoformat()
        }
        res = _client.table("delivery_logs").insert(payload).execute()
        return bool(res.data)
    except Exception as e:
        logger.error(f"Error logging delivery to Supabase: {e}")
        return False


def get_all_contacts(limit: int = 200, status_filter: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetches contacts from Supabase for UI directory view with optional filters.
    """
    if not is_connected() or not _client:
        return []

    try:
        query = _client.table("contacts").select("*").order("id", desc=True).limit(limit)
        if status_filter and status_filter.lower() != "all":
            query = query.eq("status", status_filter.lower())
        if search:
            # Search by phone or name
            query = query.or_(f"name.ilike.%{search}%,phone.ilike.%{search}%,location.ilike.%{search}%")
        res = query.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Error retrieving contacts from Supabase: {e}")
        return []


def get_database_stats() -> Dict[str, Any]:
    """
    Retrieves real-time counts from Supabase.
    """
    if not is_connected() or not _client:
        return {"total": 0, "pending": 0, "sent": 0, "invalid": 0, "failed": 0}

    try:
        total = _client.table("contacts").select("id", count="exact").execute().count or 0
        pending = _client.table("contacts").select("id", count="exact").eq("status", "pending").execute().count or 0
        sent = _client.table("contacts").select("id", count="exact").eq("status", "sent").execute().count or 0
        invalid = _client.table("contacts").select("id", count="exact").eq("status", "invalid").execute().count or 0
        failed = _client.table("contacts").select("id", count="exact").eq("status", "failed").execute().count or 0
        return {
            "total": total,
            "pending": pending,
            "sent": sent,
            "invalid": invalid,
            "failed": failed
        }
    except Exception as e:
        logger.error(f"Error fetching Supabase stats: {e}")
        return {"total": 0, "pending": 0, "sent": 0, "invalid": 0, "failed": 0}


def sync_csv_to_supabase(csv_path: str = "contacts.csv") -> Tuple[int, str]:
    """
    Imports all contacts from local contacts.csv into Supabase.
    Existing contacts are deduplicated automatically.
    """
    if not is_connected():
        return 0, "Supabase is not connected. Please verify your .env credentials."

    if not os.path.exists(csv_path):
        return 0, f"Local CSV file '{csv_path}' does not exist."

    records = []
    try:
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Phone", "").strip():
                    records.append(row)
    except Exception as e:
        return 0, f"Error reading CSV: {e}"

    if not records:
        return 0, "No valid contacts found in CSV."

    upserted, total = upsert_contacts(records)
    return upserted, f"Successfully synced {upserted} contacts to Supabase (Total in Cloud: {total})."


def export_supabase_to_csv(csv_path: str = "contacts.csv") -> Tuple[int, str]:
    """
    Exports all Supabase contacts into the local CSV file as an offline backup.
    """
    if not is_connected() or not _client:
        return 0, "Supabase is not connected."

    try:
        res = _client.table("contacts").select("*").order("id", desc=False).execute()
        rows = res.data or []
        if not rows:
            return 0, "No contacts found in Supabase to export."

        fieldnames = ["Name", "Phone", "Raw_Phone", "Address", "Website", "Search_Query", "Location", "Scraped_At"]
        with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    "Name": r.get("name", ""),
                    "Phone": r.get("phone", ""),
                    "Raw_Phone": r.get("raw_phone", ""),
                    "Address": r.get("address", ""),
                    "Website": r.get("website", ""),
                    "Search_Query": r.get("search_query", ""),
                    "Location": r.get("location", ""),
                    "Scraped_At": r.get("scraped_at", "")
                })

        return len(rows), f"Exported {len(rows)} contacts from Supabase to '{csv_path}'."
    except Exception as e:
        return 0, f"Export error: {e}"


def delete_contact(phone: str) -> bool:
    """
    Deletes a contact by phone number from Supabase.
    """
    if not is_connected() or not _client:
        return False
    try:
        _client.table("contacts").delete().eq("phone", phone.strip()).execute()
        return True
    except Exception as e:
        logger.error(f"Error deleting contact {phone} from Supabase: {e}")
        return False


def clear_all_contacts() -> bool:
    """
    Clears all contacts from Supabase.
    """
    if not is_connected() or not _client:
        return False
    try:
        _client.table("contacts").delete().neq("phone", "").execute()
        return True
    except Exception as e:
        logger.error(f"Error clearing contacts in Supabase: {e}")
        return False


# Auto-attempt initialization on import
init_supabase()
