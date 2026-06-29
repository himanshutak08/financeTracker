class FinanceTrackerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._route = this._routeFromLocation();
    this._data = null;
    this._loading = false;
    this._error = "";
    this._busyEntryId = null;
    this._monthKey = new Date().toLocaleDateString("en-CA", { year: "numeric", month: "2-digit" });
    this._monthStatus = "";
    this._monthCategory = "";
    this._expenses = null;
    this._expenseLoading = false;
    this._expenseError = "";
    this._expenseBusy = false;
    this._editingExpenseId = null;
    this._planYear = new Date().getFullYear();
    this._yearPlan = null;
    this._yearLoading = false;
    this._yearError = "";
    this._yearBusy = false;
    this._historyYear = new Date().getFullYear();
    this._history = null;
    this._historyLoading = false;
    this._historyError = "";
    this._settings = null;
    this._settingsLoading = false;
    this._settingsError = "";
    this._settingsBusy = false;
    this._reminderRunResult = null;
    this._boundPopstate = () => {
      this._route = this._routeFromLocation();
      this.render();
      if (this._route === "current") {
        this.loadCurrentMonth();
      } else if (this._route === "add") {
        this.loadExpenses();
      } else if (this._route === "year-setup") {
        this.loadYearPlan();
      } else if (this._route === "history") {
        this.loadHistory();
      } else if (this._route === "settings") {
        this.loadSettings();
      }
    };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._booted) {
      this._booted = true;
      window.addEventListener("popstate", this._boundPopstate);
      if (this._route === "current") {
        this.loadCurrentMonth();
      } else if (this._route === "add") {
        this.loadExpenses();
      } else if (this._route === "year-setup") {
        this.loadYearPlan();
      } else if (this._route === "history") {
        this.loadHistory();
      } else if (this._route === "settings") {
        this.loadSettings();
      } else {
        this.render();
      }
      return;
    }

    this.render();
  }

  disconnectedCallback() {
    window.removeEventListener("popstate", this._boundPopstate);
  }

  _routeFromLocation() {
    const path = window.location.pathname.replace(/\/+$/, "");
    const parts = path.split("/").filter(Boolean);
    if (parts[0] !== "finance") {
      return "current";
    }

    return parts[1] || "current";
  }

  async loadCurrentMonth() {
    if (!this._hass) {
      return;
    }

    this._loading = true;
    this._error = "";
    this.render();

    try {
      this._data = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/get_current_month",
        month_key: this._monthKey,
        ...(this._monthStatus ? { status: this._monthStatus } : {}),
        ...(this._monthCategory ? { category: this._monthCategory } : {}),
      });
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._loading = false;
      this.render();
    }
  }

  async markPaid(entry) {
    if (!this._hass || this._busyEntryId) {
      return;
    }

    this._busyEntryId = entry.entry_id;
    this.render();

    try {
      await this._hass.callService("finance_tracker", "mark_paid", {
        entry_id: entry.entry_id,
        amount: entry.remaining_amount || entry.scheduled_amount,
        paid_date: this._today(),
      });
      await this.loadCurrentMonth();
    } catch (err) {
      this._error = err?.message || String(err);
      this.render();
    } finally {
      this._busyEntryId = null;
      this.render();
    }
  }

  async recordPartialPayment(form) {
    if (!this._hass || this._busyEntryId) {
      return;
    }
    const formData = new FormData(form);
    const entryId = String(formData.get("entry_id"));
    const amount = Number(formData.get("amount"));
    if (!Number.isFinite(amount) || amount <= 0) {
      this._error = "Payment amount must be greater than zero.";
      this.render();
      return;
    }

    this._busyEntryId = entryId;
    this._error = "";
    this.render();
    try {
      await this._hass.callService("finance_tracker", "mark_partial", {
        entry_id: entryId,
        amount,
        paid_date: String(formData.get("paid_date") || this._today()),
        note: String(formData.get("note") || "").trim(),
      });
      await this.loadCurrentMonth();
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._busyEntryId = null;
      this.render();
    }
  }

  async updateCurrentEntry(form) {
    if (!this._hass || this._busyEntryId) {
      return;
    }
    const formData = new FormData(form);
    const entryId = String(formData.get("entry_id"));
    const scheduledAmount = Number(formData.get("scheduled_amount"));
    if (!Number.isFinite(scheduledAmount) || scheduledAmount < 0) {
      this._error = "Scheduled amount must be a valid non-negative number.";
      this.render();
      return;
    }

    this._busyEntryId = entryId;
    this._error = "";
    this.render();
    try {
      await this._hass.callService("finance_tracker", "update_month_entry", {
        entry_id: entryId,
        name: String(formData.get("name") || "").trim(),
        category: String(formData.get("category") || "").trim(),
        scheduled_amount: scheduledAmount,
        due_date: String(formData.get("due_date") || "").trim() || null,
        notes: String(formData.get("notes") || "").trim() || null,
      });
      await this.loadCurrentMonth();
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._busyEntryId = null;
      this.render();
    }
  }

  async loadExpenses() {
    if (!this._hass) {
      return;
    }

    this._expenseLoading = true;
    this._expenseError = "";
    this.render();
    try {
      this._expenses = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/list_expenses",
      });
    } catch (err) {
      this._expenseError = err?.message || String(err);
    } finally {
      this._expenseLoading = false;
      this.render();
    }
  }

  async saveExpense(form) {
    if (!this._hass || this._expenseBusy) {
      return;
    }

    const formData = new FormData(form);
    const payload = {
      name: String(formData.get("name") || "").trim(),
      category: String(formData.get("category") || "").trim(),
      recurrence: String(formData.get("recurrence") || "monthly"),
      amount: Number(formData.get("amount")),
      reminder_days: Number(formData.get("reminder_days") || 3),
    };
    for (const field of ["due_day", "start_month", "end_month"]) {
      const value = String(formData.get(field) || "").trim();
      if (value) {
        payload[field] = Number(value);
      } else if (this._editingExpenseId) {
        payload[field] = null;
      }
    }
    for (const field of ["icon", "notes", "custom_months"]) {
      const value = String(formData.get(field) || "").trim();
      if (value) {
        payload[field] = value;
      } else if (this._editingExpenseId) {
        payload[field] = field === "custom_months" ? "" : null;
      }
    }

    if (!payload.name || !payload.category || !Number.isFinite(payload.amount) || payload.amount < 0) {
      this._expenseError = "Name, category, and a valid non-negative amount are required.";
      this.render();
      return;
    }

    this._expenseBusy = true;
    this._expenseError = "";
    this.render();
    try {
      if (this._editingExpenseId) {
        await this._hass.callService("finance_tracker", "update_expense", {
          template_id: this._editingExpenseId,
          ...payload,
        });
      } else {
        await this._hass.callService("finance_tracker", "add_expense", payload);
      }
      this._editingExpenseId = null;
      await this.loadExpenses();
    } catch (err) {
      this._expenseError = err?.message || String(err);
    } finally {
      this._expenseBusy = false;
      this.render();
    }
  }

  async archiveExpense(templateId) {
    if (!this._hass || this._expenseBusy) {
      return;
    }
    const expense = this._expenses?.expenses?.find((item) => item.template_id === templateId);
    if (!expense || !window.confirm(`Archive ${expense.name}? Existing month history will be preserved.`)) {
      return;
    }

    this._expenseBusy = true;
    this._expenseError = "";
    this.render();
    try {
      await this._hass.callService("finance_tracker", "archive_expense", {
        template_id: templateId,
      });
      if (this._editingExpenseId === templateId) {
        this._editingExpenseId = null;
      }
      await this.loadExpenses();
    } catch (err) {
      this._expenseError = err?.message || String(err);
    } finally {
      this._expenseBusy = false;
      this.render();
    }
  }

  async loadYearPlan(year = this._planYear) {
    if (!this._hass) {
      return;
    }
    this._planYear = Number(year);
    this._yearLoading = true;
    this._yearError = "";
    this.render();
    try {
      this._yearPlan = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/get_year_plan",
        year: this._planYear,
      });
    } catch (err) {
      this._yearPlan = null;
      this._yearError = err?.message || String(err);
    } finally {
      this._yearLoading = false;
      this.render();
    }
  }

  async runYearAction(service, data) {
    if (!this._hass || this._yearBusy) {
      return;
    }
    this._yearBusy = true;
    this._yearError = "";
    this.render();
    try {
      await this._hass.callService("finance_tracker", service, data);
      await this.loadYearPlan(data.target_year || data.year || this._planYear);
    } catch (err) {
      this._yearError = err?.message || String(err);
    } finally {
      this._yearBusy = false;
      this.render();
    }
  }

  async updateYearEntry(form) {
    if (!this._hass || this._yearBusy) {
      return;
    }
    const formData = new FormData(form);
    const data = {
      entry_id: String(formData.get("entry_id")),
      scheduled_amount: Number(formData.get("scheduled_amount")),
      due_date: String(formData.get("due_date") || "").trim() || null,
      notes: String(formData.get("notes") || "").trim() || null,
    };
    if (!Number.isFinite(data.scheduled_amount) || data.scheduled_amount < 0) {
      this._yearError = "Planned amount must be a valid non-negative number.";
      this.render();
      return;
    }
    await this.runYearAction("update_month_entry", data);
  }

  async loadHistory(year = this._historyYear) {
    if (!this._hass) {
      return;
    }
    this._historyYear = Number(year);
    this._historyLoading = true;
    this._historyError = "";
    this.render();
    try {
      this._history = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/get_history",
        year: this._historyYear,
      });
    } catch (err) {
      this._history = null;
      this._historyError = err?.message || String(err);
    } finally {
      this._historyLoading = false;
      this.render();
    }
  }

  async loadSettings() {
    if (!this._hass) {
      return;
    }
    this._settingsLoading = true;
    this._settingsError = "";
    this.render();
    try {
      this._settings = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/get_settings",
      });
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsLoading = false;
      this.render();
    }
  }

  async saveSettings(form) {
    if (!this._hass || this._settingsBusy) {
      return;
    }
    const data = new FormData(form);
    this._settingsBusy = true;
    this._settingsError = "";
    this.render();
    try {
      await this._hass.callService("finance_tracker", "update_settings", {
        currency: String(data.get("currency") || "").trim().toUpperCase(),
        reminders_enabled: data.get("reminders_enabled") === "on",
        notification_service: String(data.get("notification_service") || "").trim(),
        scan_interval_minutes: Number(data.get("scan_interval_minutes")),
      });
      await this.loadSettings();
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsBusy = false;
      this.render();
    }
  }

  async runRemindersNow() {
    if (!this._hass || this._settingsBusy) {
      return;
    }
    this._settingsBusy = true;
    this._settingsError = "";
    this._reminderRunResult = null;
    this.render();
    try {
      this._reminderRunResult = await this._hass.callService(
        "finance_tracker",
        "run_reminders",
        {},
        {},
        true
      );
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsBusy = false;
      this.render();
    }
  }

  navigate(route) {
    if (route === this._route) {
      return;
    }

    history.pushState({}, "", `/finance/${route}`);
    this._route = route;
    this.render();
    if (route === "current") {
      this.loadCurrentMonth();
    } else if (route === "add") {
      this.loadExpenses();
    } else if (route === "year-setup") {
      this.loadYearPlan();
    } else if (route === "history") {
      this.loadHistory();
    } else if (route === "settings") {
      this.loadSettings();
    }
  }

  render() {
    const route = this._route;
    const tabs = [
      ["current", "Current Month"],
      ["add", "Add Expense"],
      ["year-setup", "Year Setup"],
      ["history", "History"],
      ["settings", "Settings"],
    ];

    const currentBody = route === "current"
      ? this.renderCurrentMonth()
      : route === "add"
        ? this.renderExpenseManagement()
        : route === "year-setup"
          ? this.renderYearSetup()
          : route === "history"
            ? this.renderHistory()
            : route === "settings"
              ? this.renderSettings()
        : this.renderPlaceholder(route);

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          color: var(--primary-text-color);
          display: block;
          font-family: "Avenir Next", "Segoe UI", sans-serif;
        }

        .app {
          min-height: 100vh;
          background:
            radial-gradient(circle at top left, rgba(28, 126, 214, 0.18), transparent 24rem),
            linear-gradient(180deg, var(--primary-background-color), var(--secondary-background-color));
          padding: 24px;
          box-sizing: border-box;
        }

        .shell {
          max-width: 1200px;
          margin: 0 auto;
        }

        .hero {
          display: grid;
          gap: 12px;
          margin-bottom: 20px;
        }

        .eyebrow {
          color: var(--secondary-text-color);
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }

        h1 {
          margin: 0;
          font-size: clamp(32px, 4vw, 48px);
          line-height: 1;
        }

        .subtitle {
          color: var(--secondary-text-color);
          font-size: 15px;
          max-width: 60ch;
        }

        .tabs {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin: 20px 0 28px;
        }

        .tab {
          border: 1px solid var(--divider-color);
          background: rgba(255, 255, 255, 0.04);
          border-radius: 999px;
          color: inherit;
          cursor: pointer;
          font: inherit;
          padding: 10px 16px;
        }

        .tab.active {
          background: var(--primary-color);
          border-color: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }

        .panel {
          background: rgba(18, 24, 35, 0.48);
          border: 1px solid rgba(148, 163, 184, 0.2);
          border-radius: 24px;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.18);
          padding: 20px;
          backdrop-filter: blur(14px);
        }

        .summary {
          display: grid;
          gap: 14px;
          grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
          margin-bottom: 20px;
        }

        .metric {
          background: rgba(255, 255, 255, 0.04);
          border-radius: 18px;
          padding: 16px;
        }

        .metric-label {
          color: var(--secondary-text-color);
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }

        .metric-value {
          font-size: 28px;
          font-weight: 700;
          margin-top: 8px;
        }

        .toolbar {
          align-items: center;
          display: flex;
          gap: 12px;
          justify-content: space-between;
          margin-bottom: 18px;
        }

        .toolbar button,
        .pay-button {
          background: var(--primary-color);
          border: 0;
          border-radius: 999px;
          color: var(--text-primary-color, #fff);
          cursor: pointer;
          font: inherit;
          padding: 10px 14px;
        }

        .pay-button[disabled],
        .toolbar button[disabled] {
          cursor: progress;
          opacity: 0.65;
        }

        .ledger {
          display: grid;
          gap: 12px;
        }

        .entry {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(148, 163, 184, 0.16);
          border-radius: 18px;
          display: grid;
          gap: 12px;
          grid-template-columns: 1fr auto;
          padding: 16px;
        }

        .entry-top {
          align-items: center;
          display: flex;
          gap: 10px;
          justify-content: space-between;
        }

        .entry-main {
          min-width: 0;
        }

        .entry-tools {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          margin-top: 12px;
        }

        .entry-tools details {
          flex: 1 1 220px;
        }

        .entry-tools summary {
          color: var(--primary-color);
          cursor: pointer;
          font-size: 14px;
          font-weight: 600;
        }

        .detail-form {
          background: rgba(0, 0, 0, 0.12);
          border-radius: 14px;
          margin-top: 10px;
          padding: 12px;
        }

        .current-filters {
          align-items: end;
        }

        .name {
          font-size: 18px;
          font-weight: 700;
        }

        .badge {
          border-radius: 999px;
          font-size: 12px;
          padding: 6px 10px;
          text-transform: uppercase;
        }

        .badge.pending { background: rgba(245, 158, 11, 0.18); color: #fbbf24; }
        .badge.partial { background: rgba(59, 130, 246, 0.18); color: #93c5fd; }
        .badge.overdue { background: rgba(239, 68, 68, 0.18); color: #fca5a5; }
        .badge.paid { background: rgba(34, 197, 94, 0.18); color: #86efac; }

        .meta {
          color: var(--secondary-text-color);
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          font-size: 14px;
        }

        .amounts {
          display: grid;
          gap: 4px;
          justify-items: end;
          text-align: right;
        }

        .amounts strong {
          font-size: 22px;
        }

        .expense-layout {
          display: grid;
          gap: 24px;
          grid-template-columns: minmax(280px, 0.85fr) minmax(360px, 1.15fr);
        }

        .section-title {
          font-size: 22px;
          font-weight: 700;
          margin: 4px 0 16px;
        }

        .expense-form,
        .form-grid {
          display: grid;
          gap: 14px;
        }

        .form-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .field {
          display: grid;
          gap: 6px;
        }

        .field.full {
          grid-column: 1 / -1;
        }

        .field label {
          color: var(--secondary-text-color);
          font-size: 13px;
          font-weight: 600;
        }

        input,
        select,
        textarea {
          background: var(--card-background-color, rgba(255, 255, 255, 0.06));
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          box-sizing: border-box;
          color: var(--primary-text-color);
          font: inherit;
          padding: 11px 12px;
          width: 100%;
        }

        textarea {
          min-height: 80px;
          resize: vertical;
        }

        .form-actions,
        .expense-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .primary-button,
        .secondary-button,
        .danger-button {
          border: 0;
          border-radius: 999px;
          cursor: pointer;
          font: inherit;
          padding: 9px 13px;
        }

        .primary-button {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }

        .secondary-button {
          background: rgba(148, 163, 184, 0.16);
          color: inherit;
        }

        .danger-button {
          background: rgba(239, 68, 68, 0.16);
          color: #fca5a5;
        }

        button[disabled] {
          cursor: progress;
          opacity: 0.6;
        }

        .expense-list {
          display: grid;
          gap: 10px;
        }

        .expense-card {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(148, 163, 184, 0.16);
          border-radius: 16px;
          display: grid;
          gap: 10px;
          padding: 14px;
        }

        .expense-card.archived {
          opacity: 0.62;
        }

        .expense-card-top {
          align-items: start;
          display: flex;
          gap: 12px;
          justify-content: space-between;
        }

        .expense-amount {
          font-size: 18px;
          font-weight: 700;
          white-space: nowrap;
        }

        .year-controls {
          display: grid;
          gap: 12px;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          margin-bottom: 22px;
        }

        .control-card,
        .month-group {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(148, 163, 184, 0.16);
          border-radius: 18px;
          padding: 16px;
        }

        .inline-form {
          align-items: end;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .inline-form .field {
          flex: 1 1 110px;
        }

        .plan-list {
          display: grid;
          gap: 14px;
        }

        .month-heading {
          align-items: center;
          display: flex;
          gap: 12px;
          justify-content: space-between;
          margin-bottom: 12px;
        }

        .month-heading strong {
          font-size: 18px;
        }

        .plan-item {
          border-top: 1px solid rgba(148, 163, 184, 0.14);
          padding: 12px 0;
        }

        .plan-item:first-of-type {
          border-top: 0;
        }

        .plan-item summary {
          align-items: center;
          cursor: pointer;
          display: flex;
          gap: 12px;
          justify-content: space-between;
          list-style: none;
        }

        .plan-item summary::-webkit-details-marker {
          display: none;
        }

        .plan-edit {
          margin-top: 14px;
        }

        .report-grid {
          display: grid;
          gap: 18px;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        }

        .report-card {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(148, 163, 184, 0.16);
          border-radius: 18px;
          padding: 16px;
        }

        .report-row {
          display: grid;
          gap: 6px;
          margin-top: 12px;
        }

        .report-label {
          display: flex;
          gap: 10px;
          justify-content: space-between;
        }

        .progress-track {
          background: rgba(148, 163, 184, 0.16);
          border-radius: 999px;
          height: 8px;
          overflow: hidden;
        }

        .progress-value {
          background: var(--primary-color);
          border-radius: inherit;
          height: 100%;
        }

        .payment-list {
          display: grid;
          gap: 8px;
          margin-top: 12px;
        }

        .payment-row {
          align-items: center;
          border-top: 1px solid rgba(148, 163, 184, 0.14);
          display: flex;
          gap: 12px;
          justify-content: space-between;
          padding-top: 8px;
        }

        .error,
        .empty,
        .placeholder {
          background: rgba(255, 255, 255, 0.03);
          border: 1px dashed rgba(148, 163, 184, 0.32);
          border-radius: 18px;
          color: var(--secondary-text-color);
          padding: 18px;
        }

        @media (max-width: 720px) {
          .app { padding: 16px; }
          .entry { grid-template-columns: 1fr; }
          .amounts { justify-items: start; text-align: left; }
          .toolbar { align-items: flex-start; flex-direction: column; }
          .expense-layout, .form-grid { grid-template-columns: 1fr; }
          .field.full { grid-column: auto; }
        }
      </style>
      <div class="app">
        <div class="shell">
          <div class="hero">
            <div class="eyebrow">Finance Tracker</div>
            <h1>Household finance, inside Home Assistant.</h1>
            <div class="subtitle">
              Current Month is live first. The remaining routes are scaffolded so the panel can grow into
              expense master management, year setup, history, and settings without another frontend reset.
            </div>
          </div>
          <div class="tabs">
            ${tabs
              .map(
                ([key, label]) => `
                  <button class="tab ${route === key ? "active" : ""}" data-route="${key}">
                    ${label}
                  </button>
                `
              )
              .join("")}
          </div>
          <div class="panel">${currentBody}</div>
        </div>
      </div>
    `;

    this.shadowRoot.querySelectorAll("[data-route]").forEach((button) => {
      button.addEventListener("click", () => this.navigate(button.dataset.route));
    });

    this.shadowRoot.querySelector("[data-refresh]")?.addEventListener("click", () => {
      this.loadCurrentMonth();
    });

    this.shadowRoot.querySelectorAll("[data-entry-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const entry = this._data?.entries?.find(
          (item) => item.entry_id === button.dataset.entryId
        );
        if (entry) {
          this.markPaid(entry);
        }
      });
    });

    this.shadowRoot.querySelector("[data-month-filters]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this._monthKey = String(data.get("month_key"));
      this._monthStatus = String(data.get("status") || "");
      this._monthCategory = String(data.get("category") || "").trim();
      this.loadCurrentMonth();
    });

    this.shadowRoot.querySelector("[data-month-reset]")?.addEventListener("click", () => {
      this._monthKey = new Date().toLocaleDateString("en-CA", { year: "numeric", month: "2-digit" });
      this._monthStatus = "";
      this._monthCategory = "";
      this.loadCurrentMonth();
    });

    this.shadowRoot.querySelectorAll("[data-partial-payment-form]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        this.recordPartialPayment(event.currentTarget);
      });
    });

    this.shadowRoot.querySelectorAll("[data-current-entry-form]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        this.updateCurrentEntry(event.currentTarget);
      });
    });

    this.shadowRoot.querySelector("[data-expense-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this.saveExpense(event.currentTarget);
    });

    this.shadowRoot.querySelector("[data-expense-refresh]")?.addEventListener("click", () => {
      this.loadExpenses();
    });

    this.shadowRoot.querySelector("[data-expense-cancel]")?.addEventListener("click", () => {
      this._editingExpenseId = null;
      this._expenseError = "";
      this.render();
    });

    this.shadowRoot.querySelectorAll("[data-expense-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        this._editingExpenseId = button.dataset.expenseEdit;
        this._expenseError = "";
        this.render();
      });
    });

    this.shadowRoot.querySelectorAll("[data-expense-archive]").forEach((button) => {
      button.addEventListener("click", () => this.archiveExpense(button.dataset.expenseArchive));
    });

    this.shadowRoot.querySelector("[data-year-load]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this.loadYearPlan(Number(data.get("year")));
    });

    this.shadowRoot.querySelector("[data-year-generate]")?.addEventListener("click", () => {
      this.runYearAction("generate_year", { year: this._planYear });
    });

    this.shadowRoot.querySelector("[data-year-activate]")?.addEventListener("click", () => {
      if (window.confirm(`Activate the ${this._planYear} plan?`)) {
        this.runYearAction("activate_year", { year: this._planYear });
      }
    });

    this.shadowRoot.querySelector("[data-year-copy]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this.runYearAction("copy_year", {
        source_year: Number(data.get("source_year")),
        target_year: Number(data.get("target_year")),
      });
    });

    this.shadowRoot.querySelectorAll("[data-plan-entry-form]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        this.updateYearEntry(event.currentTarget);
      });
    });

    this.shadowRoot.querySelector("[data-history-year]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this.loadHistory(Number(data.get("year")));
    });

    this.shadowRoot.querySelector("[data-settings-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this.saveSettings(event.currentTarget);
    });

    this.shadowRoot.querySelector("[data-run-reminders]")?.addEventListener("click", () => {
      this.runRemindersNow();
    });
  }

  renderCurrentMonth() {
    const filters = `
      <form class="inline-form current-filters" data-month-filters>
        <div class="field">
          <label>Month</label>
          <input name="month_key" type="month" value="${this._escape(this._monthKey)}" required>
        </div>
        <div class="field">
          <label>Status</label>
          <select name="status">
            <option value="" ${this._monthStatus ? "" : "selected"}>All statuses</option>
            ${["pending", "partial", "paid", "overdue"].map((status) =>
              `<option value="${status}" ${this._monthStatus === status ? "selected" : ""}>${status}</option>`
            ).join("")}
          </select>
        </div>
        <div class="field">
          <label>Category</label>
          <input name="category" value="${this._escape(this._monthCategory)}" placeholder="All categories">
        </div>
        <button class="primary-button" type="submit" ${this._loading ? "disabled" : ""}>Apply</button>
        <button class="secondary-button" type="button" data-month-reset ${this._loading ? "disabled" : ""}>This month</button>
      </form>
    `;

    if (this._loading) {
      return `${filters}<br><div class="placeholder">Loading current month ledger...</div>`;
    }

    if (this._error) {
      return `${filters}<br><div class="error">${this._escape(this._error)}</div>`;
    }

    const data = this._data;
    if (!data || !Array.isArray(data.entries) || data.entries.length === 0) {
      return `
        ${filters}
        <br>
        <div class="toolbar">
          <div>No month entries yet.</div>
          <button data-refresh>Refresh</button>
        </div>
        <div class="empty">
          Generate or activate a year plan first, then this route will render the live ledger.
        </div>
      `;
    }

    const summary = data.summary || {};
    const statusCounts = summary.status_counts || {};
    const entriesHtml = data.entries
      .map((entry) => {
        const disabled = this._busyEntryId === entry.entry_id ? "disabled" : "";
        const buttonLabel =
          this._busyEntryId === entry.entry_id ? "Paying..." : "Mark Paid";
        return `
          <div class="entry">
            <div class="entry-main">
              <div class="entry-top">
                <div class="name">${this._escape(entry.name)}</div>
                <div class="badge ${entry.status}">${this._escape(entry.status)}</div>
              </div>
              <div class="meta">
                <span>${this._escape(entry.category)}</span>
                <span>Due ${this._escape(entry.due_date || "No due date")}</span>
                <span>Paid ${this._escape(entry.actual_paid_amount.toFixed(2))}</span>
              </div>
              <div class="entry-tools">
                ${entry.remaining_amount > 0 ? `
                  <details>
                    <summary>Record partial payment</summary>
                    <form class="inline-form detail-form" data-partial-payment-form>
                      <input type="hidden" name="entry_id" value="${this._escape(entry.entry_id)}">
                      <div class="field">
                        <label>Amount</label>
                        <input name="amount" type="number" min="0.01" max="${this._escape(entry.remaining_amount)}" step="0.01" required>
                      </div>
                      <div class="field">
                        <label>Paid date</label>
                        <input name="paid_date" type="date" value="${this._today()}" required>
                      </div>
                      <div class="field">
                        <label>Note</label>
                        <input name="note" placeholder="Optional">
                      </div>
                      <button class="primary-button" type="submit" ${disabled}>Record</button>
                    </form>
                  </details>
                ` : ""}
                <details>
                  <summary>Edit this month</summary>
                  <form class="form-grid detail-form" data-current-entry-form>
                    <input type="hidden" name="entry_id" value="${this._escape(entry.entry_id)}">
                    <div class="field">
                      <label>Name</label>
                      <input name="name" required value="${this._escape(entry.name)}">
                    </div>
                    <div class="field">
                      <label>Category</label>
                      <input name="category" required value="${this._escape(entry.category)}">
                    </div>
                    <div class="field">
                      <label>Scheduled amount</label>
                      <input name="scheduled_amount" type="number" min="0" step="0.01" required value="${this._escape(entry.scheduled_amount)}">
                    </div>
                    <div class="field">
                      <label>Due date</label>
                      <input name="due_date" type="date" value="${this._escape(entry.due_date || "")}">
                    </div>
                    <div class="field full">
                      <label>Notes</label>
                      <textarea name="notes">${this._escape(entry.notes || "")}</textarea>
                    </div>
                    <div class="form-actions field full">
                      <button class="primary-button" type="submit" ${disabled}>Save month entry</button>
                    </div>
                  </form>
                </details>
              </div>
            </div>
            <div class="amounts">
              <div>Remaining</div>
              <strong>${this._escape(entry.remaining_amount.toFixed(2))}</strong>
              ${
                entry.remaining_amount > 0
                  ? `<button class="pay-button" data-entry-id="${entry.entry_id}" ${disabled}>${buttonLabel}</button>`
                  : ""
              }
            </div>
          </div>
        `;
      })
      .join("");

    return `
      ${filters}
      <br>
      <div class="toolbar">
        <div>
          <div class="eyebrow">Current Month</div>
          <div>${this._escape(data.month_key || "Unknown month")}</div>
        </div>
        <button data-refresh ${this._loading ? "disabled" : ""}>Refresh</button>
      </div>
      <div class="summary">
        <div class="metric">
          <div class="metric-label">Scheduled</div>
          <div class="metric-value">${this._escape((summary.scheduled_total || 0).toFixed(2))}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Paid</div>
          <div class="metric-value">${this._escape((summary.actual_paid_total || 0).toFixed(2))}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Remaining</div>
          <div class="metric-value">${this._escape((summary.remaining_total || 0).toFixed(2))}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Open Items</div>
          <div class="metric-value">${this._escape(String((statusCounts.pending || 0) + (statusCounts.partial || 0) + (statusCounts.overdue || 0)))}</div>
        </div>
      </div>
      <div class="ledger">${entriesHtml}</div>
    `;
  }

  renderExpenseManagement() {
    const expenses = this._expenses?.expenses || [];
    const editing = expenses.find(
      (expense) => expense.template_id === this._editingExpenseId
    );
    const value = (field, fallback = "") => this._escape(editing?.[field] ?? fallback);
    const recurrence = editing?.recurrence || "monthly";
    const recurrenceOptions = [
      ["monthly", "Monthly"],
      ["one_time", "One time"],
      ["annual", "Annual"],
      ["twice_yearly", "Twice yearly"],
      ["custom_months", "Custom months"],
    ].map(([key, label]) =>
      `<option value="${key}" ${recurrence === key ? "selected" : ""}>${label}</option>`
    ).join("");

    const listBody = this._expenseLoading
      ? `<div class="placeholder">Loading expense catalog...</div>`
      : expenses.length === 0
        ? `<div class="empty">No expenses yet. Create the first recurring expense with this form.</div>`
        : `<div class="expense-list">${expenses.map((expense) => `
            <div class="expense-card ${expense.is_active ? "" : "archived"}">
              <div class="expense-card-top">
                <div>
                  <div class="name">${this._escape(expense.name)}</div>
                  <div class="meta">
                    <span>${this._escape(expense.category)}</span>
                    <span>${this._escape(expense.recurrence.replaceAll("_", " "))}</span>
                    <span>Due day ${this._escape(expense.due_day || "—")}</span>
                    ${expense.is_active ? "" : "<span>Archived</span>"}
                  </div>
                </div>
                <div class="expense-amount">${this._escape(expense.default_amount.toFixed(2))}</div>
              </div>
              ${expense.notes ? `<div class="meta">${this._escape(expense.notes)}</div>` : ""}
              <div class="expense-actions">
                <button class="secondary-button" data-expense-edit="${expense.template_id}" ${this._expenseBusy ? "disabled" : ""}>Edit</button>
                ${expense.is_active ? `<button class="danger-button" data-expense-archive="${expense.template_id}" ${this._expenseBusy ? "disabled" : ""}>Archive</button>` : ""}
              </div>
            </div>
          `).join("")}</div>`;

    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">Expense Management</div>
          <div>${expenses.length} expense${expenses.length === 1 ? "" : "s"}</div>
        </div>
        <button data-expense-refresh ${this._expenseLoading || this._expenseBusy ? "disabled" : ""}>Refresh</button>
      </div>
      ${this._expenseError ? `<div class="error">${this._escape(this._expenseError)}</div><br>` : ""}
      <div class="expense-layout">
        <section>
          <div class="eyebrow">${editing ? "Edit Expense" : "New Expense"}</div>
          <div class="section-title">${editing ? this._escape(editing.name) : "Add an obligation"}</div>
          <form class="expense-form" data-expense-form>
            <div class="form-grid">
              <div class="field full">
                <label for="expense-name">Name</label>
                <input id="expense-name" name="name" required value="${value("name")}" placeholder="Electricity bill">
              </div>
              <div class="field">
                <label for="expense-category">Category</label>
                <input id="expense-category" name="category" required value="${value("category")}" placeholder="Utilities">
              </div>
              <div class="field">
                <label for="expense-amount">Default amount</label>
                <input id="expense-amount" name="amount" type="number" min="0" step="0.01" required value="${value("default_amount")}">
              </div>
              <div class="field">
                <label for="expense-recurrence">Recurrence</label>
                <select id="expense-recurrence" name="recurrence">${recurrenceOptions}</select>
              </div>
              <div class="field">
                <label for="expense-due-day">Due day</label>
                <input id="expense-due-day" name="due_day" type="number" min="1" max="31" value="${value("due_day")}" placeholder="15">
              </div>
              <div class="field">
                <label for="expense-start-month">Start month</label>
                <input id="expense-start-month" name="start_month" type="number" min="1" max="12" value="${value("start_month")}" placeholder="1">
              </div>
              <div class="field">
                <label for="expense-end-month">End month</label>
                <input id="expense-end-month" name="end_month" type="number" min="1" max="12" value="${value("end_month")}" placeholder="12">
              </div>
              <div class="field full">
                <label for="expense-custom-months">Custom months</label>
                <input id="expense-custom-months" name="custom_months" value="${this._escape(editing?.custom_months?.join(",") || "")}" placeholder="1, 4, 7, 10">
              </div>
              <div class="field">
                <label for="expense-reminders">Reminder days</label>
                <input id="expense-reminders" name="reminder_days" type="number" min="0" max="60" value="${value("reminder_days", 3)}">
              </div>
              <div class="field">
                <label for="expense-icon">Icon</label>
                <input id="expense-icon" name="icon" value="${value("icon")}" placeholder="mdi:lightning-bolt">
              </div>
              <div class="field full">
                <label for="expense-notes">Notes</label>
                <textarea id="expense-notes" name="notes" placeholder="Optional context">${value("notes")}</textarea>
              </div>
            </div>
            <div class="form-actions">
              <button class="primary-button" type="submit" ${this._expenseBusy ? "disabled" : ""}>${this._expenseBusy ? "Saving..." : editing ? "Save changes" : "Add expense"}</button>
              ${editing ? `<button class="secondary-button" type="button" data-expense-cancel ${this._expenseBusy ? "disabled" : ""}>Cancel</button>` : ""}
            </div>
          </form>
        </section>
        <section>
          <div class="eyebrow">Expense Catalog</div>
          <div class="section-title">Recurring definitions</div>
          ${listBody}
        </section>
      </div>
    `;
  }

  renderYearSetup() {
    const plan = this._yearPlan;
    const isDraft = plan?.plan?.status === "draft";
    const disabled = this._yearBusy || this._yearLoading ? "disabled" : "";
    const currentYear = new Date().getFullYear();
    const itemsByMonth = new Map();
    for (const item of plan?.items || []) {
      if (!itemsByMonth.has(item.month_number)) {
        itemsByMonth.set(item.month_number, []);
      }
      itemsByMonth.get(item.month_number).push(item);
    }

    const planBody = this._yearLoading
      ? `<div class="placeholder">Loading ${this._planYear} plan...</div>`
      : !plan
        ? `<div class="empty">No plan is loaded for ${this._planYear}. Generate it from active expenses or copy a prior year.</div>`
        : `<div class="plan-list">${[...itemsByMonth.entries()].map(([month, items]) => {
            const monthName = new Intl.DateTimeFormat(undefined, { month: "long" }).format(
              new Date(this._planYear, month - 1, 1)
            );
            const total = items.reduce((sum, item) => sum + item.scheduled_amount, 0);
            return `
              <section class="month-group">
                <div class="month-heading">
                  <strong>${this._escape(monthName)}</strong>
                  <span>${items.length} item${items.length === 1 ? "" : "s"} · ${this._escape(total.toFixed(2))}</span>
                </div>
                ${items.map((item) => `
                  <details class="plan-item">
                    <summary>
                      <span>
                        <span class="name">${this._escape(item.name)}</span>
                        <span class="meta">${this._escape(item.category)} · Due ${this._escape(item.due_date || "—")}</span>
                      </span>
                      <span class="expense-amount">${this._escape(item.scheduled_amount.toFixed(2))}</span>
                    </summary>
                    <form class="inline-form plan-edit" data-plan-entry-form>
                      <input type="hidden" name="entry_id" value="${this._escape(item.entry_id)}">
                      <div class="field">
                        <label>Planned amount</label>
                        <input name="scheduled_amount" type="number" min="0" step="0.01" required value="${this._escape(item.scheduled_amount)}" ${isDraft ? "" : "disabled"}>
                      </div>
                      <div class="field">
                        <label>Due date</label>
                        <input name="due_date" type="date" value="${this._escape(item.due_date || "")}" ${isDraft ? "" : "disabled"}>
                      </div>
                      <div class="field">
                        <label>Notes</label>
                        <input name="notes" value="${this._escape(item.notes || "")}" ${isDraft ? "" : "disabled"}>
                      </div>
                      ${isDraft ? `<button class="primary-button" type="submit" ${disabled}>Save</button>` : ""}
                    </form>
                  </details>
                `).join("")}
              </section>
            `;
          }).join("")}</div>`;

    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">Year Setup</div>
          <div class="section-title">Plan ${this._escape(this._planYear)}</div>
          ${plan ? `<div class="meta"><span>Status: ${this._escape(plan.plan.status)}</span><span>${plan.item_count} entries</span></div>` : ""}
        </div>
        ${isDraft ? `<button data-year-activate ${disabled}>Activate year</button>` : ""}
      </div>
      ${this._yearError ? `<div class="error">${this._escape(this._yearError)}</div><br>` : ""}
      <div class="year-controls">
        <div class="control-card">
          <div class="eyebrow">Open Plan</div>
          <form class="inline-form" data-year-load>
            <div class="field">
              <label>Year</label>
              <input name="year" type="number" min="2000" max="2100" value="${this._escape(this._planYear)}" required>
            </div>
            <button class="secondary-button" type="submit" ${disabled}>Load</button>
          </form>
        </div>
        <div class="control-card">
          <div class="eyebrow">Generate</div>
          <p class="meta">Create or rebuild a draft from active expense definitions.</p>
          <button class="primary-button" data-year-generate ${disabled}>Generate ${this._escape(this._planYear)}</button>
        </div>
        <div class="control-card">
          <div class="eyebrow">Copy Prior Year</div>
          <form class="inline-form" data-year-copy>
            <div class="field">
              <label>From</label>
              <input name="source_year" type="number" min="2000" max="2100" value="${this._escape(this._planYear - 1 || currentYear - 1)}" required>
            </div>
            <div class="field">
              <label>To</label>
              <input name="target_year" type="number" min="2000" max="2100" value="${this._escape(this._planYear)}" required>
            </div>
            <button class="secondary-button" type="submit" ${disabled}>Copy</button>
          </form>
        </div>
      </div>
      ${planBody}
    `;
  }

  renderHistory() {
    if (this._historyLoading) {
      return `<div class="placeholder">Loading ${this._escape(this._historyYear)} history...</div>`;
    }

    const history = this._history;
    const summary = history?.summary || {};
    const categories = summary.category_totals || [];
    const months = (history?.monthly || []).filter((month) => month.entry_count > 0);
    const payments = history?.payments || [];
    const progress = (paid, scheduled) => scheduled > 0
      ? Math.max(0, Math.min(100, (paid / scheduled) * 100))
      : 0;

    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">History</div>
          <div class="section-title">${this._escape(this._historyYear)} reporting</div>
        </div>
        <form class="inline-form" data-history-year>
          <div class="field">
            <label>Year</label>
            <input name="year" type="number" min="2000" max="2100" value="${this._escape(this._historyYear)}" required>
          </div>
          <button class="primary-button" type="submit">Load</button>
        </form>
      </div>
      ${this._historyError ? `<div class="error">${this._escape(this._historyError)}</div><br>` : ""}
      ${!history || history.entry_count === 0 ? `
        <div class="empty">No ledger history exists for ${this._escape(this._historyYear)}.</div>
      ` : `
        <div class="summary">
          <div class="metric"><div class="metric-label">Planned</div><div class="metric-value">${this._escape(summary.scheduled_total.toFixed(2))}</div></div>
          <div class="metric"><div class="metric-label">Paid</div><div class="metric-value">${this._escape(summary.actual_paid_total.toFixed(2))}</div></div>
          <div class="metric"><div class="metric-label">Remaining</div><div class="metric-value">${this._escape(summary.remaining_total.toFixed(2))}</div></div>
          <div class="metric"><div class="metric-label">Payments</div><div class="metric-value">${payments.length}</div></div>
        </div>
        <div class="report-grid">
          <section class="report-card">
            <div class="eyebrow">Monthly trend</div>
            <div class="section-title">Paid vs planned</div>
            ${months.map((month) => {
              const monthName = new Intl.DateTimeFormat(undefined, { month: "short" }).format(
                new Date(this._historyYear, month.month - 1, 1)
              );
              const monthSummary = month.summary;
              return `
                <details class="report-row">
                  <summary class="report-label">
                    <span>${this._escape(monthName)}</span>
                    <span>${this._escape(monthSummary.actual_paid_total.toFixed(2))} / ${this._escape(monthSummary.scheduled_total.toFixed(2))}</span>
                  </summary>
                  <div class="progress-track"><div class="progress-value" style="width:${progress(monthSummary.actual_paid_total, monthSummary.scheduled_total)}%"></div></div>
                  <div class="payment-list">
                    ${month.entries.map((entry) => `
                      <div class="payment-row">
                        <span>${this._escape(entry.name)} <span class="meta">${this._escape(entry.status)}</span></span>
                        <span>${this._escape(entry.actual_paid_amount.toFixed(2))} / ${this._escape(entry.scheduled_amount.toFixed(2))}</span>
                      </div>
                    `).join("")}
                  </div>
                </details>
              `;
            }).join("")}
          </section>
          <section class="report-card">
            <div class="eyebrow">Categories</div>
            <div class="section-title">Annual breakdown</div>
            ${categories.map((category) => `
              <div class="report-row">
                <div class="report-label">
                  <span>${this._escape(category.category)}</span>
                  <span>${this._escape(category.actual_paid_amount.toFixed(2))} / ${this._escape(category.scheduled_amount.toFixed(2))}</span>
                </div>
                <div class="progress-track"><div class="progress-value" style="width:${progress(category.actual_paid_amount, category.scheduled_amount)}%"></div></div>
              </div>
            `).join("")}
          </section>
          <section class="report-card">
            <div class="eyebrow">Payment History</div>
            <div class="section-title">Recorded transactions</div>
            ${payments.length === 0 ? `<div class="empty">No payments recorded for this year.</div>` : `
              <div class="payment-list">
                ${payments.map((payment) => `
                  <div class="payment-row">
                    <span>
                      <strong>${this._escape(payment.name)}</strong>
                      <span class="meta">${this._escape(payment.paid_date)} · ${this._escape(payment.category)}${payment.note ? ` · ${this._escape(payment.note)}` : ""}</span>
                    </span>
                    <span class="expense-amount">${this._escape(payment.amount.toFixed(2))}</span>
                  </div>
                `).join("")}
              </div>
            `}
          </section>
        </div>
      `}
    `;
  }

  renderSettings() {
    if (this._settingsLoading && !this._settings) {
      return `<div class="placeholder">Loading settings...</div>`;
    }
    const settings = this._settings || {
      currency: "INR",
      reminders_enabled: true,
      notification_service: "persistent_notification.create",
      scan_interval_minutes: 60,
    };
    const result = this._reminderRunResult;

    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">Settings</div>
          <div class="section-title">Notifications and defaults</div>
        </div>
      </div>
      ${this._settingsError ? `<div class="error">${this._escape(this._settingsError)}</div><br>` : ""}
      ${result ? `<div class="empty">Reminder scan complete: ${this._escape(result.sent ?? 0)} sent, ${this._escape(result.failed ?? 0)} failed, ${this._escape(result.candidates ?? 0)} eligible.</div><br>` : ""}
      <div class="expense-layout">
        <section>
          <form class="expense-form" data-settings-form>
            <div class="form-grid">
              <div class="field">
                <label for="settings-currency">Currency code</label>
                <input id="settings-currency" name="currency" minlength="3" maxlength="3" required value="${this._escape(settings.currency)}">
              </div>
              <div class="field">
                <label for="settings-interval">Scan interval (minutes)</label>
                <input id="settings-interval" name="scan_interval_minutes" type="number" min="5" max="1440" required value="${this._escape(settings.scan_interval_minutes)}">
              </div>
              <div class="field full">
                <label for="settings-service">Notification service</label>
                <input id="settings-service" name="notification_service" required value="${this._escape(settings.notification_service)}" placeholder="notify.mobile_app_phone">
              </div>
              <div class="field full">
                <label>
                  <input name="reminders_enabled" type="checkbox" ${settings.reminders_enabled ? "checked" : ""} style="width:auto">
                  Enable automatic reminders
                </label>
              </div>
            </div>
            <div class="form-actions">
              <button class="primary-button" type="submit" ${this._settingsBusy ? "disabled" : ""}>${this._settingsBusy ? "Working..." : "Save settings"}</button>
            </div>
          </form>
        </section>
        <section class="report-card">
          <div class="eyebrow">Reminder Engine</div>
          <div class="section-title">Delivery behavior</div>
          <p class="meta">Each expense uses its reminder-days setting. Upcoming, due-today, and overdue reminders are sent at most once per entry per day.</p>
          <p class="meta">Use <strong>persistent_notification.create</strong> for notifications inside Home Assistant, or a service such as <strong>notify.mobile_app_phone</strong> for a device.</p>
          <button class="secondary-button" type="button" data-run-reminders ${this._settingsBusy ? "disabled" : ""}>Run reminder scan now</button>
        </section>
      </div>
    `;
  }

  renderPlaceholder(route) {
    const titles = {
      add: "Add Expense",
      "year-setup": "Year Setup",
      history: "History",
      settings: "Settings",
    };

    return `
      <div class="placeholder">
        <div class="eyebrow">${this._escape(titles[route] || "Coming Soon")}</div>
        <div>
          This route is scaffolded, but only Current Month is implemented in this first panel milestone.
        </div>
      </div>
    `;
  }

  _today() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  _escape(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
}

customElements.define("finance-tracker-panel", FinanceTrackerPanel);
