/**
 * Core AI Automation Control Center - Frontend Application Logic
 * Real-time SSE streaming, interactive dashboards, and campaign controllers.
 */

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");
  
  const textScraperStatus = document.getElementById("text-scraper-status");
  const textSenderStatus = document.getElementById("text-sender-status");
  const textSupabaseStatus = document.getElementById("text-supabase-status");
  const indicatorScraper = document.getElementById("indicator-scraper");
  const indicatorSender = document.getElementById("indicator-sender");
  const indicatorSupabase = document.getElementById("indicator-supabase");
  const dotSupabase = document.getElementById("dot-supabase");

  const modalSupabaseInfo = document.getElementById("modal-supabase-info");
  const btnSbClose = document.getElementById("modal-sb-close-btn");
  const btnSbDismiss = document.getElementById("modal-sb-dismiss-btn");
  const btnSbReconnect = document.getElementById("btn-sb-reconnect");
  const btnSyncSupabase = document.getElementById("btn-sync-supabase");

  const kpiTotalContacts = document.getElementById("kpi-total-contacts");
  const kpiDelivered = document.getElementById("kpi-delivered-contacts");
  const kpiPending = document.getElementById("kpi-pending-contacts");

  const terminalOutput = document.getElementById("terminal-output");
  const btnClearTerm = document.getElementById("btn-clear-term");
  const btnToggleTerm = document.getElementById("btn-toggle-term");

  let allContactsData = [];
  let currentFilter = "all";

  // ============================================================================
  // TAB NAVIGATION
  // ============================================================================
  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      tabButtons.forEach(b => b.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");

      // Auto-refresh data when visiting tabs
      if (targetId === "tab-contacts") loadContacts();
      if (targetId === "tab-template") loadTemplate();
      if (targetId === "tab-audit") loadAuditLogs();
      if (targetId === "tab-blacklist") loadBlacklist();
    });
  });

  // ============================================================================
  // REAL-TIME TERMINAL & SSE LOG STREAMING
  // ============================================================================
  function appendTerminalLog(entry) {
    if (!entry || !entry.text) return;

    const line = document.createElement("div");
    line.className = `term-line term-${entry.category || 'info'}`;
    line.textContent = `[${entry.time || 'NOW'}] ${entry.text}`;

    terminalOutput.appendChild(line);

    // Keep scroll at bottom
    terminalOutput.scrollTop = terminalOutput.scrollHeight;
  }

  function connectSSE() {
    try {
      const evtSource = new EventSource("/api/logs/stream");

      evtSource.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data);
          appendTerminalLog(entry);
        } catch (e) {
          // ignore heartbeat
        }
      };

      evtSource.onerror = () => {
        // Reconnect automatically handled by browser EventSource
      };
    } catch (e) {
      console.warn("SSE not supported or connection error:", e);
    }
  }

  btnClearTerm.addEventListener("click", () => {
    terminalOutput.innerHTML = "";
    appendTerminalLog({ time: "SYSTEM", text: "Terminal cleared.", category: "info" });
  });

  btnToggleTerm.addEventListener("click", () => {
    if (terminalOutput.style.display === "none") {
      terminalOutput.style.display = "flex";
      btnToggleTerm.textContent = "Minimize";
    } else {
      terminalOutput.style.display = "none";
      btnToggleTerm.textContent = "Expand";
    }
  });

  // ============================================================================
  // SCRAPER CONTROLLER
  // ============================================================================
  const formScraper = document.getElementById("form-scraper");
  const inputLoc = document.getElementById("scraper-location");
  const inputQuery = document.getElementById("scraper-query");
  const inputLimit = document.getElementById("scraper-limit");
  const limitVal = document.getElementById("limit-val");
  const btnStartScraper = document.getElementById("btn-start-scraper");
  const btnStopScraper = document.getElementById("btn-stop-scraper");
  const captchaAlertBox = document.getElementById("captcha-alert-box");
  const btnCaptchaResolved = document.getElementById("btn-captcha-resolved");

  inputLimit.addEventListener("input", (e) => {
    limitVal.textContent = e.target.value;
  });

  formScraper.addEventListener("submit", async (e) => {
    e.preventDefault();
    const location = inputLoc.value.trim();
    const query = inputQuery.value.trim();
    const limit = parseInt(inputLimit.value, 10) || 25;

    btnStartScraper.disabled = true;
    try {
      const res = await fetch("/api/scraper/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ location, query, limit })
      });
      const data = await res.json();
      if (!res.ok) alert(data.message || "Failed to start scraper.");
    } catch (err) {
      alert("Error starting scraper: " + err.message);
    }
  });

  btnStopScraper.addEventListener("click", async () => {
    btnStopScraper.disabled = true;
    await fetch("/api/scraper/stop", { method: "POST" });
  });

  btnCaptchaResolved.addEventListener("click", async () => {
    await fetch("/api/scraper/resolve-captcha", { method: "POST" });
    captchaAlertBox.style.display = "none";
  });

  // ============================================================================
  // WHATSAPP SENDER CONTROLLER
  // ============================================================================
  const inputMinDelay = document.getElementById("sender-min-delay");
  const inputMaxDelay = document.getElementById("sender-max-delay");
  const btnStartSenderLive = document.getElementById("btn-start-sender-live");
  const btnStartSenderTest = document.getElementById("btn-start-sender-test");
  const btnStopSender = document.getElementById("btn-stop-sender");
  const btnResetCheckpoint = document.getElementById("btn-reset-checkpoint");
  const cooldownBox = document.getElementById("cooldown-box");
  const cooldownSeconds = document.getElementById("cooldown-seconds");

  async function triggerSender(mode) {
    const minDelay = parseInt(inputMinDelay.value, 10) || 30;
    const maxDelay = parseInt(inputMaxDelay.value, 10) || 60;

    btnStartSenderLive.disabled = true;
    btnStartSenderTest.disabled = true;

    try {
      const res = await fetch("/api/sender/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, min_delay: minDelay, max_delay: maxDelay })
      });
      const data = await res.json();
      if (!res.ok) alert(data.message || "Failed to start sender.");
    } catch (err) {
      alert("Error starting sender: " + err.message);
    }
  }

  btnStartSenderLive.addEventListener("click", () => triggerSender("live"));
  btnStartSenderTest.addEventListener("click", () => triggerSender("test"));

  btnStopSender.addEventListener("click", async () => {
    btnStopSender.disabled = true;
    await fetch("/api/sender/stop", { method: "POST" });
  });

  btnResetCheckpoint.addEventListener("click", async () => {
    if (confirm("Reset checkpoint? This allows re-sending messages to all previously contacted leads.")) {
      await fetch("/api/checkpoint/reset", { method: "POST" });
      loadContacts();
    }
  });

  // ============================================================================
  // STATE POLLING & MONITOR UPDATES
  // ============================================================================
  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();

      const sc = data.scraper || {};
      const se = data.sender || {};
      const sb = data.supabase || {};

      // 0. Supabase Status
      if (textSupabaseStatus && indicatorSupabase) {
        if (sb.connected) {
          textSupabaseStatus.textContent = "Connected";
          indicatorSupabase.className = "status-indicator connected";
          if (dotSupabase) dotSupabase.style.backgroundColor = "var(--emerald)";
        } else {
          textSupabaseStatus.textContent = "Offline (CSV Mode)";
          indicatorSupabase.className = "status-indicator offline";
          if (dotSupabase) dotSupabase.style.backgroundColor = "var(--amber)";
        }
      }

      // Update modal status box if modal is open
      const sbModalStatusText = document.getElementById("sb-modal-status-text");
      const sbModalDot = document.getElementById("sb-modal-dot");
      if (sbModalStatusText && sbModalDot) {
        if (sb.connected) {
          sbModalStatusText.textContent = `Connected to Supabase (${sb.url || 'Active'})`;
          sbModalDot.style.backgroundColor = "var(--emerald)";
        } else {
          sbModalStatusText.textContent = `Offline: ${sb.error || 'Local CSV Mode'}`;
          sbModalDot.style.backgroundColor = "var(--amber)";
        }
      }

      // 1. Scraper Status
      textScraperStatus.textContent = sc.status.toUpperCase();
      document.getElementById("scraper-status-pill").textContent = sc.status;
      document.getElementById("scraper-status-pill").className = `status-pill ${sc.status}`;

      if (sc.status === "running") {
        indicatorScraper.className = "status-indicator active";
        btnStartScraper.disabled = true;
        btnStopScraper.disabled = false;
        captchaAlertBox.style.display = "none";
      } else if (sc.status === "captcha_wait") {
        indicatorScraper.className = "status-indicator paused";
        btnStartScraper.disabled = true;
        btnStopScraper.disabled = false;
        captchaAlertBox.style.display = "flex";
      } else {
        indicatorScraper.className = "status-indicator";
        btnStartScraper.disabled = false;
        btnStopScraper.disabled = true;
        captchaAlertBox.style.display = "none";
      }

      const scProg = sc.total > 0 ? Math.round((sc.progress / sc.total) * 100) : 0;
      document.getElementById("scraper-progress-bar").style.width = `${scProg}%`;
      document.getElementById("scraper-progress-pct").textContent = `${scProg}%`;
      document.getElementById("scraper-progress-text").textContent = `Processed: ${sc.progress} / ${sc.total}`;
      document.getElementById("monitor-query").textContent = sc.query || "-";
      document.getElementById("monitor-location").textContent = sc.location || "-";
      document.getElementById("monitor-found").textContent = sc.found || 0;

      // 2. Sender Status
      textSenderStatus.textContent = se.status.toUpperCase();
      document.getElementById("sender-status-pill").textContent = `${se.status} (${se.mode || 'live'})`;
      document.getElementById("sender-status-pill").className = `status-pill ${se.status}`;

      const qrAlert = document.getElementById("qr-alert-box");

      if (se.status === "running" || se.status === "pausing" || se.status === "qr_wait") {
        indicatorSender.className = "status-indicator active";
        btnStartSenderLive.disabled = true;
        btnStartSenderTest.disabled = true;
        btnStopSender.disabled = false;

        if (se.status === "qr_wait") {
          if (qrAlert) qrAlert.style.display = "block";
          const qrImg = document.getElementById("qr-code-img");
          if (qrImg && (!qrImg._lastUpdate || Date.now() - qrImg._lastUpdate > 3500)) {
            qrImg._lastUpdate = Date.now();
            qrImg.src = "/api/sender/qr_code?t=" + Date.now();
          }
        } else {
          if (qrAlert) qrAlert.style.display = "none";
        }

        if (se.status === "pausing" && se.cooldown_remaining > 0) {
          cooldownBox.style.display = "block";
          cooldownSeconds.textContent = `${se.cooldown_remaining}s`;
        } else {
          cooldownBox.style.display = "none";
        }
      } else {
        indicatorSender.className = "status-indicator";
        btnStartSenderLive.disabled = false;
        btnStartSenderTest.disabled = false;
        btnStopSender.disabled = true;
        cooldownBox.style.display = "none";
        if (qrAlert) qrAlert.style.display = "none";
      }

      const seProg = se.total > 0 ? Math.round((se.progress / se.total) * 100) : 0;
      document.getElementById("sender-progress-bar").style.width = `${seProg}%`;
      document.getElementById("sender-progress-pct").textContent = `${seProg}%`;
      document.getElementById("sender-progress-text").textContent = `Dispatched: ${se.progress} / ${se.total}`;
      document.getElementById("sender-count-success").textContent = se.success || 0;
      document.getElementById("sender-count-invalid").textContent = se.invalid || 0;
      document.getElementById("sender-current-lead").textContent = se.current_contact || "-";

    } catch (e) {
      // offline or server restarted
    }
  }

  // ============================================================================
  // CONTACTS MANAGEMENT
  // ============================================================================
  const contactsTbody = document.getElementById("contacts-table-body");
  const contactSearch = document.getElementById("contact-search");
  const filterPills = document.querySelectorAll(".filter-pill");

  async function loadContacts() {
    try {
      const res = await fetch("/api/contacts");
      if (!res.ok) return;
      const data = await res.json();
      allContactsData = data.contacts || [];

      // Update KPI counters
      kpiTotalContacts.textContent = allContactsData.length;
      kpiDelivered.textContent = data.processed_count || 0;
      kpiPending.textContent = allContactsData.length - (data.processed_count || 0);

      document.getElementById("filter-all-count").textContent = allContactsData.length;
      document.getElementById("filter-sent-count").textContent = data.processed_count || 0;
      document.getElementById("filter-pending-count").textContent = allContactsData.length - (data.processed_count || 0);

      renderContactsTable();
    } catch (e) {
      console.error("Error loading contacts:", e);
    }
  }

  function renderContactsTable() {
    const query = contactSearch.value.toLowerCase().trim();
    const filtered = allContactsData.filter(c => {
      const matchSearch = (c.Name || "").toLowerCase().includes(query) ||
                          (c.Phone || "").toLowerCase().includes(query) ||
                          (c.Location || "").toLowerCase().includes(query);
      if (!matchSearch) return false;
      if (currentFilter === "sent") return c.is_processed;
      if (currentFilter === "pending") return !c.is_processed;
      return true;
    });

    if (filtered.length === 0) {
      contactsTbody.innerHTML = `<tr><td colspan="7" class="empty-state">No matching contacts found.</td></tr>`;
      return;
    }

    contactsTbody.innerHTML = filtered.map((c, i) => `
      <tr>
        <td>${i + 1}</td>
        <td><b>${escapeHtml(c.Name || 'Unknown')}</b></td>
        <td><span class="lead-phone">${escapeHtml(c.Phone || '')}</span></td>
        <td>${escapeHtml(c.Location || '-')}</td>
        <td>${escapeHtml(c.Search_Query || '-')}</td>
        <td>
          <span class="${c.is_banned ? 'badge-invalid' : (c.is_processed ? 'badge-sent' : 'badge-pending')}" ${c.is_banned ? `title="${escapeHtml(c.ban_reason || 'Banned Institute')}" style="background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.3);"` : ''}>
            ${c.is_banned ? '🛡️ Banned' : (c.is_processed ? '✓ Delivered' : '⏳ Pending')}
          </span>
        </td>
        <td>
          <button class="btn-del-lead" data-phone="${c.Phone}" title="Delete contact">
            <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>
        </td>
      </tr>
    `).join("");

    // Attach delete listeners
    document.querySelectorAll(".btn-del-lead").forEach(b => {
      b.addEventListener("click", async (e) => {
        const phone = b.getAttribute("data-phone");
        if (confirm(`Delete lead with phone: ${phone}?`)) {
          await fetch("/api/contacts/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phone })
          });
          loadContacts();
        }
      });
    });
  }

  contactSearch.addEventListener("input", renderContactsTable);

  filterPills.forEach(pill => {
    pill.addEventListener("click", () => {
      filterPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      currentFilter = pill.getAttribute("data-filter");
      renderContactsTable();
    });
  });

  document.getElementById("btn-clear-contacts").addEventListener("click", async () => {
    if (confirm("Clear all contacts from contacts.csv? This cannot be undone.")) {
      await fetch("/api/contacts/clear", { method: "POST" });
      loadContacts();
    }
  });

  // Modal Add Contact
  const modalAdd = document.getElementById("modal-add-contact");
  document.getElementById("btn-open-add-contact").addEventListener("click", () => {
    modalAdd.classList.add("active");
  });
  document.getElementById("modal-close-btn").addEventListener("click", () => {
    modalAdd.classList.remove("active");
  });
  document.getElementById("modal-cancel-btn").addEventListener("click", () => {
    modalAdd.classList.remove("active");
  });

  document.getElementById("form-add-lead").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("add-lead-name").value.trim();
    const phone = document.getElementById("add-lead-phone").value.trim();
    const location = document.getElementById("add-lead-location").value.trim();

    const res = await fetch("/api/contacts/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, phone, location })
    });
    const data = await res.json();
    if (res.ok) {
      modalAdd.classList.remove("active");
      document.getElementById("form-add-lead").reset();
      loadContacts();
    } else {
      alert(data.message || "Invalid phone number.");
    }
  });

  // ============================================================================
  // SUPABASE MODAL & SYNC CONTROLLER
  // ============================================================================
  if (indicatorSupabase && modalSupabaseInfo) {
    indicatorSupabase.addEventListener("click", () => {
      modalSupabaseInfo.classList.add("active");
    });
  }

  if (btnSbClose) {
    btnSbClose.addEventListener("click", () => modalSupabaseInfo.classList.remove("active"));
  }
  if (btnSbDismiss) {
    btnSbDismiss.addEventListener("click", () => modalSupabaseInfo.classList.remove("active"));
  }

  if (btnSbReconnect) {
    btnSbReconnect.addEventListener("click", async () => {
      btnSbReconnect.disabled = true;
      btnSbReconnect.textContent = "Testing...";
      try {
        const res = await fetch("/api/supabase/reconnect", { method: "POST" });
        const result = await res.json();
        if (result.connected) {
          alert("✓ Supabase connected successfully!");
          modalSupabaseInfo.classList.remove("active");
        } else {
          alert(`Connection failed: ${result.error || 'Check .env credentials'}`);
        }
      } catch (err) {
        alert("Error testing connection: " + err);
      } finally {
        btnSbReconnect.disabled = false;
        btnSbReconnect.textContent = "Test / Reconnect";
        pollStatus();
      }
    });
  }

  if (btnSyncSupabase) {
    btnSyncSupabase.addEventListener("click", async () => {
      btnSyncSupabase.disabled = true;
      const originalText = btnSyncSupabase.innerHTML;
      btnSyncSupabase.innerHTML = "Syncing...";
      try {
        const res = await fetch("/api/supabase/sync", { method: "POST" });
        const result = await res.json();
        alert(result.message);
        loadContacts();
      } catch (e) {
        alert("Failed to sync contacts to Supabase: " + e);
      } finally {
        btnSyncSupabase.disabled = false;
        btnSyncSupabase.innerHTML = originalText;
      }
    });
  }

  // ============================================================================
  // MESSAGE TEMPLATE EDITOR & LIVE PREVIEW
  // ============================================================================
  const templateEditor = document.getElementById("template-editor");
  const previewBody = document.getElementById("preview-message-body");
  const btnSaveTemplate = document.getElementById("btn-save-template");

  async function loadTemplate() {
    try {
      const res = await fetch("/api/template");
      if (res.ok) {
        const data = await res.json();
        templateEditor.value = data.template || "";
        updatePreview();
      }
    } catch (e) {
      console.error("Error loading template:", e);
    }
  }

  function updatePreview() {
    const raw = templateEditor.value || "";
    const sample = {
      name: "Delhi Public School",
      location: "Moradabad",
      query: "coaching centers",
      address: "Delhi Road, Moradabad",
      phone: "9876543210"
    };

    let rendered = raw
      .replace(/{name}/g, sample.name)
      .replace(/{location}/g, sample.location)
      .replace(/{query}/g, sample.query)
      .replace(/{address}/g, sample.address)
      .replace(/{phone}/g, sample.phone);

    previewBody.textContent = rendered;
  }

  templateEditor.addEventListener("input", updatePreview);

  document.querySelectorAll(".tag-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const tag = chip.getAttribute("data-tag");
      const start = templateEditor.selectionStart;
      const end = templateEditor.selectionEnd;
      const text = templateEditor.value;

      templateEditor.value = text.substring(0, start) + tag + text.substring(end);
      templateEditor.selectionStart = templateEditor.selectionEnd = start + tag.length;
      templateEditor.focus();
      updatePreview();
    });
  });

  btnSaveTemplate.addEventListener("click", async () => {
    const template = templateEditor.value.trim();
    const res = await fetch("/api/template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template })
    });
    if (res.ok) {
      alert("✓ Template saved successfully!");
    } else {
      alert("Failed to save template.");
    }
  });

  // ============================================================================
  // AUDIT LOGS
  // ============================================================================
  const auditList = document.getElementById("audit-log-list");
  const btnRefreshAudit = document.getElementById("btn-refresh-audit");

  async function loadAuditLogs() {
    try {
      const res = await fetch("/api/logs/delivery");
      if (!res.ok) return;
      const data = await res.json();
      const logs = data.logs || [];

      if (logs.length === 0) {
        auditList.innerHTML = `<div class="empty-state">No delivery records found yet.</div>`;
        return;
      }

      auditList.innerHTML = logs.reverse().map(line => {
        let tagClass = "tag-failed";
        let tagText = "FAILED";
        if (line.includes("[SUCCESS]")) { tagClass = "tag-success"; tagText = "SUCCESS"; }
        else if (line.includes("[INVALID]")) { tagClass = "tag-invalid"; tagText = "INVALID"; }
        else if (line.includes("[BANNED]")) { tagClass = "tag-invalid"; tagText = "BANNED"; }

        return `
          <div class="audit-item">
            <span class="audit-tag ${tagClass}">${tagText}</span>
            <span>${escapeHtml(line)}</span>
          </div>
        `;
      }).join("");
    } catch (e) {
      console.error("Error loading audit logs:", e);
    }
  }

  btnRefreshAudit.addEventListener("click", loadAuditLogs);

  // ============================================================================
  // BANNED INSTITUTES BLACKLIST
  // ============================================================================
  const blacklistChips = document.getElementById("blacklist-chips");
  const inputNewBanned = document.getElementById("input-new-banned");
  const btnAddBanned = document.getElementById("btn-add-banned");

  async function loadBlacklist() {
    if (!blacklistChips) return;
    try {
      const res = await fetch("/api/blacklist");
      if (!res.ok) return;
      const data = await res.json();
      const keywords = data.banned_keywords || [];
      if (keywords.length === 0) {
        blacklistChips.innerHTML = `<span class="chip">No banned rules defined</span>`;
        return;
      }
      blacklistChips.innerHTML = keywords.map(kw => `
        <span class="chip" style="background: rgba(239,68,68,0.15); color: #fca5a5; border: 1px solid rgba(239,68,68,0.3); font-weight: 500;">
          🛡️ ${escapeHtml(kw)}
        </span>
      `).join("");
    } catch (e) {
      console.error("Error loading blacklist:", e);
    }
  }

  if (btnAddBanned && inputNewBanned) {
    btnAddBanned.addEventListener("click", async () => {
      const kw = inputNewBanned.value.trim();
      if (!kw) return alert("Please enter a keyword or institute name");
      try {
        const res = await fetch("/api/blacklist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ keyword: kw })
        });
        const result = await res.json();
        alert(result.message);
        inputNewBanned.value = "";
        loadBlacklist();
      } catch (e) {
        alert("Error adding banned keyword: " + e);
      }
    });
  }

  // Helper
  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ============================================================================
  // INITIALIZATION
  // ============================================================================
  connectSSE();
  loadContacts();
  loadTemplate();
  loadBlacklist();
  pollStatus();

  // Poll status every 1.5 seconds
  setInterval(pollStatus, 1500);
});
