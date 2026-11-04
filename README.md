# 🚀 Free Local Google Maps Scraper & WhatsApp Automation Suite

A 100% free, local, and robust automation system with an interactive **Modern Web Control Center UI**:
1. **Interactive Web UI Dashboard (`app.py`)**: Control, monitor, view live terminal logs, manage leads, and edit message templates directly from your browser.
2. **Google Maps Scraper Module (`scraper.py`)**: Automated extraction of leads with dynamic runtime inputs and automatic sanitization to clean 10-digit mobile numbers (stripping `+91` and `0`).
3. **WhatsApp Auto-Sender Module (`sender.py`)**: Automated outreach with persistent session login, anti-ban randomized delays (30–60s), live cooldown tracking, checkpoint resuming, and delivery logging.

---

## 🖥️ Launching the Web Control Center (Recommended)

Run the local web dashboard:
```bash
python app.py
```
This starts the local automation server at `http://127.0.0.1:5000` and **automatically opens your web browser**!

### What you can do from the UI:
- **Scraper Tab**: Set location & query dynamically, adjust max results with a slider, launch or stop scraping, and resolve CAPTCHAs with one click.
- **WhatsApp Sender Tab**: Choose between Live Campaign and Dry-Run Test mode, adjust anti-ban delays, and watch the live cooldown timer.
- **Contacts Directory Tab**: View, search, filter (All / Pending / Sent), add, delete, or export contacts in `contacts.csv`.
- **Message Template Tab**: Edit your message template in real time with dynamic variable chips and preview it in a realistic WhatsApp chat bubble mockup.
- **Delivery Logs Tab**: Inspect delivery outcomes directly from `delivery_log.txt`.
- **Universal Live Terminal**: Watch real-time logs stream in via Server-Sent Events (SSE).

---

## 📁 System Architecture & Workflow

```text
┌────────────────────────────────┐
│   User Dynamic Inputs          │
│   • Location (e.g. Moradabad)  │
│   • Query (e.g. schools)       │
└───────────────┬────────────────┘
                ▼
┌────────────────────────────────┐
│   Module 1: scraper.py         │
│   • Automated Selenium Driver  │
│   • Google Maps Search Panel   │
│   • Dynamic Scroll Engine      │
│   • Anti-CAPTCHA Pause Handler │
│   • Advanced Number Cleaner    │
└───────────────┬────────────────┘
                ▼
        [contacts.csv]
  (Cleaned Leads & Numbers)
                │
                ▼
┌────────────────────────────────┐
│   Module 2: sender.py          │
│   • WhatsApp Web Automation    │
│   • Persistent Session Login   │
│   • Checkpoint/Resume Engine   │
│   • 30-60s Anti-Ban Delay      │
│   • Delivery & Invalid Logging │
└───────────────┬────────────────┘
                ▼
┌────────────────────────────────┐
│   Results & Logs               │
│   • delivery_log.txt           │
│   • sent_contacts.txt          │
└────────────────────────────────┘
```

---

## ⚙️ Installation & Setup

### 1. Prerequisites
- **Python 3.10+** (Tested on Python 3.13)
- **Google Chrome** installed on your system.

### 2. Install Dependencies
Open your terminal/command prompt in this project folder (`c:\Users\sam32\Desktop\core ai`) and run:

```bash
pip install -r requirements.txt
```

---

## 🔍 Module 1: Google Maps Scraper (`scraper.py`)

### How to Run:
```bash
python scraper.py
```

### Dynamic Runtime Inputs:
The script does **not** use hardcoded values. Upon execution, it prompts you interactively:
1. `Enter the target location/city (e.g., Moradabad, Delhi):`  
   *(e.g., `Moradabad`)*
2. `Enter the search query (e.g., schools, coaching centers, or teachers):`  
   *(e.g., `schools` or `coaching centers`)*
3. `Enter max number of results to fetch [default 25]:`  
   *(e.g., `30`)*
4. `Enter default country code [default +91]:`  
   *(e.g., `+91`)*

The script combines your query and location into `schools in Moradabad`, navigates to Google Maps, scrolls the results feed automatically, and extracts business details.

### 🛡️ Phone Number Cleaning Engine:
Raw phone numbers from Google Maps are often inconsistent, spaced, or formatted with country/STD prefixes. `scraper.py` applies strict sanitization:
- **Strips `+91` or `91` prefix**: Prevents WhatsApp from duplicating the country code.
- **Strips leading zero (`0`)**: `09876543210` → `9876543210`.
- **Removes all spaces, dashes, dots, brackets, and symbols**: `(0591) 245-1234` → `5912451234`.
- **Outputs clean 10-digit mobile number**: Ready for direct WhatsApp chat dispatch (`9876543210`).
- **Validates lengths and filters unusable numbers**:
  - Rejects numbers shorter or longer than 10 digits.
  - Rejects repetitive dummy numbers (e.g., `0000000000`, `9999999999`).
- **Deduplication**: Automatically ensures duplicate entries are not added.

### 🚨 CAPTCHA & Security Pause:
If Google presents a bot verification challenge or CAPTCHA:
1. The script detects it immediately and alerts you in the terminal.
2. It pauses execution without crashing.
3. You solve the challenge in the open Chrome browser.
4. Return to your terminal and press `[ENTER]` to resume scraping.

### Output:
Cleaned results are saved in `contacts.csv` with columns:
`Name`, `Phone`, `Raw_Phone`, `Address`, `Website`, `Search_Query`, `Location`, `Scraped_At`.

---

## 💬 Module 2: WhatsApp Auto-Sender (`sender.py`)

### How to Run:
```bash
python sender.py
```

### Key Safety & Operational Features:
1. **Persistent Session (One-Time QR Scan)**:
   - Uses a dedicated Chrome profile directory (`whatsapp_session/`).
   - You only scan the QR code **once** on the very first run.
   - On all future runs, you are automatically logged in!
2. **Anti-Ban Randomized Delay**:
   - Implements a mandatory randomized pause of **30 to 60 seconds** after every message sent.
   - Displays a live countdown timer in the terminal.
   - Prevents automated spam triggers and account bans.
3. **Checkpoint & Resume Mechanism**:
   - Processed numbers are logged in `sent_contacts.txt`.
   - If the script is interrupted (e.g., `Ctrl+C`, network disconnect, power outage), simply run `python sender.py` again.
   - It automatically skips already-processed numbers and continues from where it stopped.
4. **Invalid Number Detection**:
   - If a number is not registered on WhatsApp, WhatsApp displays a popup modal (*"Phone number shared via url is invalid"*).
   - `sender.py` detects this dialog, closes it automatically, logs it as `INVALID` in `delivery_log.txt`, and advances to the next contact.
5. **Personalized Templates (`message_template.txt`)**:
   - You can edit `message_template.txt` at any time with custom wording.
   - Supports dynamic placeholders:
     - `{name}`: Business or Institution name
     - `{location}`: Target city
     - `{query}`: Search query/category
     - `{address}`: Physical address

---

## ☁️ Supabase PostgreSQL Cloud Integration (Hybrid Mode)

The suite includes **Supabase cloud sync** for automated deduplication, real-time campaign tracking, and cloud accessibility:
- **Automatic Cloud Upsert**: Scraped leads from `scraper.py` are automatically uploaded to your Supabase `contacts` table without duplicate phone numbers.
- **Real-Time Delivery Logging**: Every WhatsApp delivery event is recorded in the Supabase `delivery_logs` table.
- **Fail-Safe Offline Fallback**: If Supabase credentials are not set or internet is interrupted, the app operates 100% locally with `contacts.csv` without crashes.
- **1-Click Sync**: Click the **"Sync to Supabase"** button in the web dashboard to import all local contacts into Supabase with one click.

### Quick Setup:
1. Create a free project at [supabase.com](https://supabase.com).
2. Open the **SQL Editor** in your Supabase dashboard and run the queries in `supabase_schema.sql`.
3. Open your local `.env` file and insert your Supabase credentials:
   ```env
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-or-service-role-key
   ```
4. Restart `python app.py` or click the **Supabase: Offline** badge in the UI header and tap **"Test / Reconnect"**!

---

## 📊 File Reference

| File | Purpose |
| :--- | :--- |
| `supabase_db.py` | Supabase PostgreSQL adapter with cloud deduplication & offline CSV fallback |
| `supabase_schema.sql` | Production PostgreSQL schema for contacts, delivery logs, and templates |
| `.env` / `.env.example` | Active and template environment variable configuration |
| `scraper.py` | Google Maps scraper with dynamic queries & phone sanitization |
| `sender.py` | WhatsApp automated sender with anti-ban delay & session persistence |
| `app.py` | Flask Web Control Center backend with SSE terminal & REST API |
| `contacts.csv` | Cleaned leads output and local fallback file |
| `message_template.txt`| Customizable template for WhatsApp messages |
| `sent_contacts.txt` | Checkpoint file tracking processed phone numbers |
| `delivery_log.txt` | Detailed audit log with timestamps and delivery outcomes |
| `requirements.txt` | Required Python packages |
| `whatsapp_session/` | Stored browser profile keeping WhatsApp Web permanently logged in |

---

## 🛡️ Anti-Ban Best Practices
- **Warm Up New Numbers**: If using a newly registered SIM/WhatsApp account, start with 15–20 messages/day.
- **Do Not Decrease Delays**: Keep the delay between 30–60 seconds. Rapid blasting causes WhatsApp automated bans.
- **Personalize Messages**: Always include the institution's name and location so each message is distinct.
