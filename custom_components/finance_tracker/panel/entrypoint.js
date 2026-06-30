const FINANCE_TRACKER_PANEL_VERSION = (() => {
  const scriptUrl = document.currentScript?.src || "";
  try {
    return new URL(scriptUrl, window.location.href).searchParams.get("v") || "dev";
  } catch (_err) {
    return "dev";
  }
})();

const FINANCE_TRACKER_PANEL_ELEMENT = `finance-tracker-panel-${FINANCE_TRACKER_PANEL_VERSION
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, "-")
  .replace(/^-+|-+$/g, "") || "dev"}`;

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
    this._expenseDraft = null;
    this._selectedExpenseIds = new Set();
    this._expenseBulkResult = "";
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
    this._cleanupResult = null;
    this._importBusy = false;
    this._importError = "";
    this._importResult = null;
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
      this.loadSettings(true);
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
    if (!window.confirm(`Mark ${entry.name} as paid for ${this.formatAmount(entry.remaining_amount || entry.scheduled_amount)}?`)) {
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
    this._expenseDraft = Object.fromEntries(formData.entries());
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

  async undoPayment(paymentId, label = "this payment") {
    if (!this._hass || this._busyEntryId || this._settingsBusy) {
      return;
    }
    if (!window.confirm(`Undo ${label}? The linked expense balance will be recalculated.`)) {
      return;
    }

    this._error = "";
    this._historyError = "";
    this.render();
    try {
      await this._hass.callService("finance_tracker", "undo_payment", {
        payment_id: paymentId,
      });
      if (this._route === "history") {
        await this.loadHistory(this._historyYear);
      } else {
        await this.loadCurrentMonth();
      }
    } catch (err) {
      const message = err?.message || String(err);
      if (this._route === "history") {
        this._historyError = message;
      } else {
        this._error = message;
      }
    } finally {
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
      this._expenseDraft = null;
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
    if (!expense || !window.confirm(`Safe delete ${expense.name}? Existing month history will be preserved, but future generated years will skip it.`)) {
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
        this._expenseDraft = null;
      }
      await this.loadExpenses();
    } catch (err) {
      this._expenseError = err?.message || String(err);
    } finally {
      this._expenseBusy = false;
      this.render();
    }
  }

  async reactivateExpense(templateId) {
    if (!this._hass || this._expenseBusy) {
      return;
    }
    const expense = this._expenses?.expenses?.find((item) => item.template_id === templateId);
    if (!expense || !window.confirm(`Reactivate ${expense.name}? It will be included in future generated years.`)) {
      return;
    }

    this._expenseBusy = true;
    this._expenseError = "";
    this.render();
    try {
      await this._hass.callService("finance_tracker", "update_expense", {
        template_id: templateId,
        is_active: true,
      });
      await this.loadExpenses();
    } catch (err) {
      this._expenseError = err?.message || String(err);
    } finally {
      this._expenseBusy = false;
      this.render();
    }
  }

  async bulkArchiveExpenses() {
    const ids = [...this._selectedExpenseIds];
    const activeIds = ids.filter((id) =>
      this._expenses?.expenses?.find((expense) => expense.template_id === id)?.is_active
    );
    if (!activeIds.length || !window.confirm(`Safe delete ${activeIds.length} selected active expense(s)? Past history will remain available.`)) {
      return;
    }
    this._expenseBusy = true;
    this._expenseError = "";
    this.render();
    try {
      for (const templateId of activeIds) {
        await this._hass.callService("finance_tracker", "archive_expense", { template_id: templateId });
      }
      this._expenseBulkResult = `${activeIds.length} expense(s) archived. Historical entries were preserved.`;
      this._selectedExpenseIds.clear();
      await this.loadExpenses();
    } catch (err) {
      this._expenseError = err?.message || String(err);
    } finally {
      this._expenseBusy = false;
      this.render();
    }
  }

  async bulkDeleteExpenses() {
    const ids = [...this._selectedExpenseIds];
    if (!ids.length || !window.confirm(`Permanently delete ${ids.length} selected definition(s)? Only archived expenses with no generated history can be deleted.`)) {
      return;
    }
    this._expenseBusy = true;
    this._expenseError = "";
    this.render();
    try {
      const result = await this._hass.callService(
        "finance_tracker", "delete_expenses", { template_ids: ids }, {}, true
      );
      const response = result?.response || result || {};
      const blocked = response.blocked || [];
      this._expenseBulkResult = `${response.deleted_count || 0} permanently deleted.${blocked.length ? ` ${blocked.length} kept because they are active or have history.` : ""}`;
      this._selectedExpenseIds.clear();
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

  async loadSettings(silent = false) {
    if (!this._hass) {
      return;
    }
    if (!silent) {
      this._settingsLoading = true;
      this._settingsError = "";
      this.render();
    }
    try {
      this._settings = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/get_settings",
      });
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      if (!silent) {
        this._settingsLoading = false;
      }
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
        mobile_notification_service: String(data.get("mobile_notification_service") || "").trim(),
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

  async sendTestNotification(servicePath) {
    const target = String(servicePath || "").trim();
    if (!target || !target.includes(".")) {
      this._settingsError = "Choose a valid notify service first.";
      this.render();
      return;
    }
    this._settingsBusy = true;
    this._settingsError = "";
    this.render();
    try {
      const [domain, service] = target.split(".", 2);
      await this._hass.callService(domain, service, {
        title: "Finance Tracker",
        message: "Phone notifications are configured correctly.",
      });
      this._reminderRunResult = { sent: 1, failed: 0, candidates: "test" };
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

  async deleteYearPlan(year) {
    if (!this._hass || this._settingsBusy) {
      return;
    }
    const planYear = Number(year);
    if (!Number.isInteger(planYear) || planYear < 2000 || planYear > 2100) {
      this._settingsError = "Enter a valid year between 2000 and 2100.";
      this.render();
      return;
    }
    if (!window.confirm(`Delete the ${planYear} Finance Tracker year plan and its ledger rows? Expense definitions will stay.`)) {
      return;
    }

    this._settingsBusy = true;
    this._settingsError = "";
    this._cleanupResult = null;
    this.render();
    try {
      this._cleanupResult = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/delete_year_plan",
        year: planYear,
      });
      if (planYear === this._planYear) {
        this._yearPlan = null;
      }
      await this.loadCurrentMonth();
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsBusy = false;
      this.render();
    }
  }

  async deleteMonth(monthKey) {
    if (!this._hass || this._settingsBusy) {
      return;
    }
    const targetMonth = String(monthKey || "").trim();
    if (!targetMonth) {
      this._settingsError = "Choose a month to wipe.";
      this.render();
      return;
    }
    if (!window.confirm(`Wipe the ${targetMonth} month ledger and its payments? Expense definitions and other months will stay.`)) {
      return;
    }

    this._settingsBusy = true;
    this._settingsError = "";
    this._cleanupResult = null;
    this.render();
    try {
      this._cleanupResult = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/delete_month",
        month_key: targetMonth,
      });
      if (targetMonth === this._monthKey) {
        await this.loadCurrentMonth();
      }
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsBusy = false;
      this.render();
    }
  }

  async generateMonth(monthKey) {
    if (!this._hass || this._settingsBusy) {
      return;
    }
    const targetMonth = String(monthKey || "").trim();
    if (!targetMonth) {
      this._settingsError = "Choose a month to generate.";
      this.render();
      return;
    }
    if (!window.confirm(`Generate the ${targetMonth} month ledger from the existing year plan? Existing entries for that month will be replaced.`)) {
      return;
    }

    this._settingsBusy = true;
    this._settingsError = "";
    this._cleanupResult = null;
    this.render();
    try {
      this._cleanupResult = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/generate_month",
        month_key: targetMonth,
      });
      if (targetMonth === this._monthKey) {
        await this.loadCurrentMonth();
      }
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsBusy = false;
      this.render();
    }
  }

  async resetDatabase() {
    if (!this._hass || this._settingsBusy) {
      return;
    }
    const confirmation = window.prompt(
      "This deletes all Finance Tracker expenses, year plans, month ledgers, payments, reminders, and settings. Type RESET to continue."
    );
    if (confirmation !== "RESET") {
      return;
    }

    this._settingsBusy = true;
    this._settingsError = "";
    this._cleanupResult = null;
    this.render();
    try {
      this._cleanupResult = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/reset_database",
      });
      this._data = null;
      this._expenses = null;
      this._yearPlan = null;
      this._history = null;
      this._settings = null;
      await this.loadSettings(true);
      await this.loadCurrentMonth();
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsBusy = false;
      this.render();
    }
  }

  async clearReminderLog() {
    if (!this._hass || this._settingsBusy) {
      return;
    }
    if (!window.confirm("Clear reminder delivery history? This lets reminders be sent again if they are still eligible.")) {
      return;
    }

    this._settingsBusy = true;
    this._settingsError = "";
    this._cleanupResult = null;
    this.render();
    try {
      this._cleanupResult = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/clear_reminder_log",
      });
    } catch (err) {
      this._settingsError = err?.message || String(err);
    } finally {
      this._settingsBusy = false;
      this.render();
    }
  }

  async importExpensesFile(form) {
    if (!this._hass || this._importBusy) {
      return;
    }
    const input = form.querySelector("input[type=file]");
    const file = input?.files?.[0];
    if (!file) {
      this._importError = "Choose a CSV or XLSX file first.";
      this.render();
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      this._importError = "Import files must be 5 MB or smaller.";
      this.render();
      return;
    }

    this._importBusy = true;
    this._importError = "";
    this._importResult = null;
    this.render();
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      const chunkSize = 0x8000;
      for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
      }
      this._importResult = await this._hass.connection.sendMessagePromise({
        type: "finance_tracker/import_expenses_file",
        filename: file.name,
        content: btoa(binary),
      });
    } catch (err) {
      this._importError = err?.message || String(err);
    } finally {
      this._importBusy = false;
      this.render();
    }
  }

  downloadSampleCsv() {
    const sample = [
      "name,category,amount,recurrence,due_day,start_month,end_month,custom_months,icon,notes,reminder_days",
      "Electricity,Utilities,2500,monthly,15,1,12,,mdi:lightning-bolt,Monthly power bill,3",
      "Insurance,Insurance,12000,annual,10,4,4,,mdi:shield-home,Annual home insurance,7",
      'Quarterly maintenance,Home,3000,custom_months,5,,,"1,4,7,10",mdi:tools,Quarterly maintenance,5',
    ].join("\n");
    const url = URL.createObjectURL(new Blob([sample], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "finance-tracker-expenses-sample.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  exportExpensesCsv() {
    const expenses = this._expenses?.expenses || [];
    const rows = expenses.map((expense) => ({
      name: expense.name,
      category: expense.category,
      amount: expense.default_amount,
      recurrence: expense.recurrence,
      due_day: expense.due_day || "",
      start_month: expense.start_month || "",
      end_month: expense.end_month || "",
      custom_months: Array.isArray(expense.custom_months) ? expense.custom_months.join("|") : "",
      icon: expense.icon || "",
      notes: expense.notes || "",
      reminder_days: expense.reminder_days,
      active: expense.is_active ? "yes" : "no",
    }));
    this.downloadCsv(
      `finance-tracker-expenses-${this._today()}.csv`,
      [
        "name", "category", "amount", "recurrence", "due_day", "start_month",
        "end_month", "custom_months", "icon", "notes", "reminder_days", "active",
      ],
      rows,
    );
  }

  exportCurrentMonthCsv() {
    const entries = this._data?.entries || [];
    const rows = entries.map((entry) => ({
      month_key: entry.month_key,
      name: entry.name,
      category: entry.category,
      scheduled_amount: entry.scheduled_amount,
      actual_paid_amount: entry.actual_paid_amount,
      remaining_amount: entry.remaining_amount,
      due_date: entry.due_date || "",
      status: entry.status,
      paid_date: entry.paid_date || "",
      notes: entry.notes || "",
    }));
    this.downloadCsv(
      `finance-tracker-current-${this._data?.month_key || this._monthKey}.csv`,
      [
        "month_key", "name", "category", "scheduled_amount", "actual_paid_amount",
        "remaining_amount", "due_date", "status", "paid_date", "notes",
      ],
      rows,
    );
  }

  exportHistoryCsv() {
    const history = this._history;
    const rows = [];
    for (const month of history?.monthly || []) {
      for (const entry of month.entries || []) {
        rows.push({
          row_type: "ledger_entry",
          year: this._historyYear,
          month: month.month,
          name: entry.name,
          category: entry.category,
          scheduled_amount: entry.scheduled_amount,
          actual_paid_amount: entry.actual_paid_amount,
          remaining_amount: entry.remaining_amount,
          status: entry.status,
          paid_date: entry.paid_date || "",
          note: entry.notes || "",
        });
      }
    }
    for (const payment of history?.payments || []) {
      rows.push({
        row_type: "payment",
        year: this._historyYear,
        month: "",
        name: payment.name,
        category: payment.category,
        scheduled_amount: "",
        actual_paid_amount: payment.amount,
        remaining_amount: "",
        status: "paid",
        paid_date: payment.paid_date,
        note: payment.note || "",
      });
    }
    this.downloadCsv(
      `finance-tracker-history-${this._historyYear}.csv`,
      [
        "row_type", "year", "month", "name", "category", "scheduled_amount",
        "actual_paid_amount", "remaining_amount", "status", "paid_date", "note",
      ],
      rows,
    );
  }

  downloadCsv(filename, columns, rows) {
    const csv = [
      columns.join(","),
      ...rows.map((row) => columns.map((column) => this.csvCell(row[column])).join(",")),
    ].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  csvCell(value) {
    const text = value === null || value === undefined ? "" : String(value);
    return `"${text.replaceAll('"', '""')}"`;
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
      ["import", "Bulk Import"],
      ["year-setup", "Year Setup"],
      ["history", "History"],
      ["settings", "Settings"],
    ];

    const currentBody = route === "current"
      ? this.renderCurrentMonth()
      : route === "add"
        ? this.renderExpenseManagement()
        : route === "import"
          ? this.renderBulkImport()
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
          font-family: Roboto, "Segoe UI", sans-serif;
        }

        *,
        *::before,
        *::after {
          box-sizing: border-box;
        }

        .app {
          min-height: 100vh;
          background: var(--primary-background-color, #f4f6f8);
          padding: clamp(16px, 3vw, 36px);
          overflow-x: hidden;
          width: 100%;
        }

        .shell {
          max-width: 1200px;
          margin: 0 auto;
          min-width: 0;
        }

        .app-header {
          align-items: center;
          background: var(--app-header-background-color, var(--primary-color));
          color: var(--app-header-text-color, var(--text-primary-color, #fff));
          display: none;
          gap: 16px;
          font-size: 20px;
          font-weight: 500;
          min-height: 56px;
          padding: 0 8px;
          position: sticky;
          top: 0;
          z-index: 1;
        }

        .menu-button {
          align-items: center;
          background: transparent;
          border: 0;
          border-radius: 50%;
          color: inherit;
          cursor: pointer;
          display: inline-flex;
          height: 48px;
          justify-content: center;
          padding: 0;
          width: 48px;
        }

        .menu-button:focus-visible {
          outline: 2px solid currentColor;
          outline-offset: -8px;
        }

        .menu-button-icon,
        .menu-button-icon::before,
        .menu-button-icon::after {
          background: currentColor;
          border-radius: 999px;
          content: "";
          display: block;
          height: 2px;
          width: 22px;
        }

        .menu-button-icon {
          position: relative;
        }

        .menu-button-icon::before,
        .menu-button-icon::after {
          left: 0;
          position: absolute;
        }

        .menu-button-icon::before {
          top: -7px;
        }

        .menu-button-icon::after {
          top: 7px;
        }

        .hero {
          display: grid;
          gap: 6px;
          margin: 0 0 18px;
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
          font-size: clamp(26px, 3vw, 34px);
          letter-spacing: -0.015em;
          line-height: 1.15;
        }

        .subtitle {
          color: var(--secondary-text-color);
          font-size: 16px;
          line-height: 1.5;
          max-width: 58ch;
        }

        .tabs {
          display: flex;
          flex-wrap: nowrap;
          gap: 8px;
          margin: 16px 0 20px;
          overflow-x: auto;
          padding-bottom: 2px;
          scrollbar-width: thin;
        }

        .tab {
          border: 1px solid var(--divider-color);
          background: var(--card-background-color, #fff);
          border-radius: 8px;
          color: inherit;
          cursor: pointer;
          flex: 0 0 auto;
          font: inherit;
          padding: 9px 14px;
          white-space: nowrap;
          transition: background-color 140ms ease, border-color 140ms ease;
        }

        .tab:hover:not([disabled]) { border-color: var(--primary-color); }

        .tab.active {
          background: var(--primary-color, #03a9f4);
          border-color: var(--primary-color, #03a9f4);
          color: #fff;
        }

        .panel {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e1e4e8);
          border-radius: 12px;
          box-shadow: none;
          overflow: hidden;
          padding: clamp(16px, 2.5vw, 28px);
        }

        .summary {
          display: grid;
          gap: 14px;
          grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
          margin-bottom: 20px;
        }

        .metric {
          background: var(--secondary-background-color, #f6f7f8);
          border: 1px solid var(--divider-color, #e1e4e8);
          border-radius: 10px;
          border-top: 3px solid var(--primary-color);
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

        .pay-button {
          background: var(--primary-color);
          border: 0;
          border-radius: 8px;
          color: var(--text-primary-color, #fff);
          cursor: pointer;
          font: inherit;
          padding: 10px 14px;
        }

        .pay-button[disabled],
        .primary-button[disabled],
        .secondary-button[disabled],
        .danger-button[disabled] {
          cursor: progress;
          opacity: 0.65;
        }

        .ledger {
          display: grid;
          gap: 12px;
        }

        .entry {
          background: var(--secondary-background-color, #f6f7f8);
          border: 1px solid var(--divider-color, #e1e4e8);
          border-radius: 12px;
          display: grid;
          gap: 12px;
          grid-template-columns: 1fr auto;
          min-width: 0;
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
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 12px;
        }

        .entry-tools details {
          flex: 1 1 220px;
        }

        .entry-tools summary {
          align-items: center;
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #d8dde3);
          border-radius: 8px;
          color: var(--primary-text-color);
          cursor: pointer;
          display: flex;
          font-size: 14px;
          font-weight: 600;
          gap: 8px;
          justify-content: center;
          list-style: none;
          min-height: 42px;
          padding: 8px 12px;
          width: 100%;
        }

        .entry-tools summary::before {
          align-items: center;
          background: color-mix(in srgb, var(--primary-color) 14%, transparent);
          border-radius: 6px;
          color: var(--primary-color);
          content: "+";
          display: inline-flex;
          font-size: 17px;
          font-weight: 700;
          height: 24px;
          justify-content: center;
          width: 24px;
        }

        .entry-tools summary.edit-action::before {
          content: "✎";
          font-size: 15px;
        }

        .entry-tools details[open] > summary {
          border-color: var(--primary-color);
          color: var(--primary-color);
        }

        .entry-tools summary::-webkit-details-marker {
          display: none;
        }

        .detail-form {
          background: var(--primary-background-color, #f4f6f8);
          border-radius: 10px;
          margin-top: 10px;
          padding: 12px;
        }

        .current-filters {
          align-items: end;
        }

        .name {
          font-size: 18px;
          font-weight: 700;
          overflow-wrap: anywhere;
        }

        .badge {
          border: 1px solid transparent;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.04em;
          padding: 6px 10px;
          text-transform: uppercase;
        }

        .badge.pending {
          background: rgba(245, 158, 11, 0.12);
          border-color: rgba(245, 158, 11, 0.42);
          color: var(--warning-color, #9a5b00);
        }

        .badge.partial {
          background: rgba(59, 130, 246, 0.12);
          border-color: rgba(59, 130, 246, 0.42);
          color: var(--info-color, #1d4ed8);
        }

        .badge.overdue {
          background: rgba(220, 38, 38, 0.10);
          border-color: rgba(220, 38, 38, 0.40);
          color: var(--error-color, #b91c1c);
        }

        .badge.paid {
          background: rgba(34, 197, 94, 0.10);
          border-color: rgba(34, 197, 94, 0.40);
          color: var(--success-color, #166534);
        }

        .badge.archived {
          background: rgba(100, 116, 139, 0.10);
          border-color: rgba(100, 116, 139, 0.36);
          color: var(--secondary-text-color);
        }

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
          grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr);
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
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color);
          border-radius: 8px;
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
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .primary-button,
        .secondary-button,
        .danger-button {
          border: 0;
          border-radius: 8px;
          cursor: pointer;
          font: inherit;
          padding: 9px 13px;
          transition: filter 140ms ease, opacity 140ms ease;
        }

        .primary-button {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }

        .secondary-button {
          background: var(--secondary-background-color, #eef1f4);
          border: 1px solid var(--divider-color, #d8dde3);
          color: inherit;
        }

        .danger-button {
          background: var(--card-background-color, #fff);
          border: 1px solid rgba(220, 38, 38, 0.45);
          color: var(--error-color, #b91c1c);
        }

        button:hover:not([disabled]) {
          filter: brightness(1.06);
        }

        button:focus-visible,
        input:focus-visible,
        select:focus-visible,
        textarea:focus-visible,
        summary:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        button[disabled] {
          background: color-mix(in srgb, var(--secondary-background-color, #eef1f4) 86%, transparent);
          border: 1px solid var(--divider-color, #d8dde3);
          color: var(--disabled-text-color, var(--secondary-text-color));
          cursor: not-allowed;
          opacity: 0.72;
        }

        button {
          min-height: 44px;
        }

        .expense-list {
          display: grid;
          gap: 10px;
        }

        .expense-card {
          background: var(--secondary-background-color, #f6f7f8);
          border: 1px solid var(--divider-color, #e1e4e8);
          border-radius: 10px;
          display: grid;
          gap: 10px;
          padding: 14px;
          transition: border-color 140ms ease, box-shadow 140ms ease;
        }

        .expense-card:hover {
          border-color: color-mix(in srgb, var(--divider-color) 45%, var(--primary-color));
        }

        .expense-card.selected {
          border-color: var(--primary-color);
          box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 20%, transparent);
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
          background: var(--secondary-background-color, #f6f7f8);
          border: 1px solid var(--divider-color, #e1e4e8);
          border-radius: 10px;
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
          min-width: 0;
        }

        .plan-list {
          display: grid;
          gap: 14px;
        }

        .month-heading {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          justify-content: space-between;
          cursor: pointer;
          list-style: none;
        }

        .month-heading::-webkit-details-marker { display: none; }

        .month-heading::after {
          align-items: center;
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color);
          border-radius: 50%;
          content: "+";
          display: inline-flex;
          font-size: 18px;
          height: 30px;
          justify-content: center;
          margin-left: auto;
          width: 30px;
        }

        .month-group[open] > .month-heading {
          margin-bottom: 12px;
        }

        .month-group[open] > .month-heading::after { content: "−"; }

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
          flex-wrap: wrap;
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
          grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
        }

        .report-card {
          background: var(--secondary-background-color, #f6f7f8);
          border: 1px solid var(--divider-color, #e1e4e8);
          border-radius: 10px;
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
          flex-wrap: wrap;
          gap: 12px;
          justify-content: space-between;
          padding-top: 8px;
        }

        .import-zone {
          background: var(--secondary-background-color, #f6f7f8);
          border: 2px dashed rgba(148, 163, 184, 0.35);
          border-radius: 12px;
          display: grid;
          gap: 16px;
          padding: 24px;
        }

        .column-list {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .column-list code {
          background: rgba(148, 163, 184, 0.14);
          border-radius: 8px;
          padding: 5px 8px;
        }

        .next-steps {
          margin: 12px 0 0;
          padding-left: 22px;
        }

        .next-steps li {
          margin: 6px 0;
        }

        .getting-started {
          display: grid;
          gap: 12px;
        }

        .checklist {
          display: grid;
          gap: 10px;
          margin-top: 12px;
        }

        .checklist-item {
          align-items: start;
          display: grid;
          gap: 10px;
          grid-template-columns: auto 1fr;
        }

        .checklist-number {
          align-items: center;
          background: var(--primary-color);
          border-radius: 999px;
          color: var(--text-primary-color, #fff);
          display: inline-flex;
          font-size: 12px;
          font-weight: 700;
          height: 24px;
          justify-content: center;
          width: 24px;
        }

        .error,
        .empty,
        .placeholder {
          background: var(--secondary-background-color, #f6f7f8);
          border: 1px dashed rgba(148, 163, 184, 0.32);
          border-radius: 10px;
          color: var(--secondary-text-color);
          padding: 18px;
        }

        @media (max-width: 720px) {
          .app { padding: 0 0 16px; }
          .app-header { display: flex; }
          .shell {
            padding: 0 12px;
            width: 100%;
          }
          .hero {
            margin: 14px 0 10px;
          }
          h1 { font-size: 24px; }
          .subtitle { font-size: 14px; }
          .tabs {
            margin: 10px -12px 12px;
            padding: 0 12px 4px;
          }
          .tab { padding: 8px 12px; }
          .panel {
            border-radius: 14px;
            padding: 12px;
          }
          .summary { grid-template-columns: 1fr 1fr; }
          .metric { padding: 12px; }
          .metric-value { font-size: 22px; }
          .entry { grid-template-columns: 1fr; }
          .amounts { justify-items: start; text-align: left; }
          .toolbar { align-items: flex-start; flex-direction: column; }
          .toolbar .form-actions { width: 100%; }
          .expense-layout, .form-grid { grid-template-columns: 1fr; }
          .field.full { grid-column: auto; }
          .inline-form { align-items: stretch; flex-direction: column; }
          .inline-form .field { flex-basis: auto; }
          .form-actions button,
          .expense-actions button,
          .toolbar button,
          .pay-button {
            width: 100%;
          }
          .expense-card-top,
          .report-label {
            flex-direction: column;
          }
          .expense-amount,
          .payment-row strong {
            white-space: normal;
          }
        }

        @media (max-width: 420px) {
          .summary { grid-template-columns: 1fr; }
        }
      </style>
      <div class="app">
        <div class="app-header">
          <button class="menu-button" type="button" data-toggle-menu aria-label="Open Home Assistant menu">
            <span class="menu-button-icon" aria-hidden="true"></span>
          </button>
          <span>Finance</span>
        </div>
        <div class="shell">
          <div class="hero">
            <h1>Finance Tracker</h1>
            <div class="subtitle">
              Track household expenses, dues, and payments in one place.
            </div>
          </div>
          <nav class="tabs" aria-label="Finance sections">
            ${tabs
              .map(
                ([key, label]) => `
                  <button class="tab ${route === key ? "active" : ""}" data-route="${key}" ${route === key ? 'aria-current="page"' : ""}>
                    ${label}
                  </button>
                `
              )
              .join("")}
          </nav>
          <main class="panel" id="finance-content" tabindex="-1">${currentBody}</main>
        </div>
      </div>
    `;

    this.shadowRoot.querySelectorAll("[data-route]").forEach((button) => {
      button.addEventListener("click", () => this.navigate(button.dataset.route));
    });

    this.shadowRoot.querySelector("[data-toggle-menu]")?.addEventListener("click", () => {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
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

    this.shadowRoot.querySelectorAll("[data-undo-payment]").forEach((button) => {
      button.addEventListener("click", () => {
        this.undoPayment(
          button.dataset.undoPayment,
          button.dataset.undoPaymentLabel || "this payment",
        );
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
      this._expenseDraft = null;
      this._expenseError = "";
      this.render();
    });

    this.shadowRoot.querySelectorAll("[data-expense-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        this._editingExpenseId = button.dataset.expenseEdit;
        this._expenseDraft = null;
        this._expenseError = "";
        this.render();
        requestAnimationFrame(() => {
          const form = this.shadowRoot.querySelector("[data-expense-editor]");
          form?.scrollIntoView({ behavior: "smooth", block: "start" });
          this.shadowRoot.querySelector("#expense-name")?.focus({ preventScroll: true });
        });
      });
    });

    this.shadowRoot.querySelectorAll("[data-expense-select]").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) {
          this._selectedExpenseIds.add(input.dataset.expenseSelect);
        } else {
          this._selectedExpenseIds.delete(input.dataset.expenseSelect);
        }
        this.render();
      });
    });

    this.shadowRoot.querySelector("[data-expense-select-all]")?.addEventListener("change", (event) => {
      this._selectedExpenseIds.clear();
      if (event.currentTarget.checked) {
        (this._expenses?.expenses || []).forEach((expense) => this._selectedExpenseIds.add(expense.template_id));
      }
      this.render();
    });

    this.shadowRoot.querySelector("[data-expense-bulk-archive]")?.addEventListener("click", () => {
      this.bulkArchiveExpenses();
    });

    this.shadowRoot.querySelector("[data-expense-bulk-delete]")?.addEventListener("click", () => {
      this.bulkDeleteExpenses();
    });

    this.shadowRoot.querySelectorAll("[data-expense-archive]").forEach((button) => {
      button.addEventListener("click", () => this.archiveExpense(button.dataset.expenseArchive));
    });

    this.shadowRoot.querySelectorAll("[data-expense-reactivate]").forEach((button) => {
      button.addEventListener("click", () => this.reactivateExpense(button.dataset.expenseReactivate));
    });

    this.shadowRoot.querySelector("[data-year-load]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this.loadYearPlan(Number(data.get("year")));
    });

    this.shadowRoot.querySelectorAll("[data-year-generate]").forEach((button) => {
      button.addEventListener("click", () => {
        if (window.confirm(`Generate or rebuild the ${this._planYear} draft from active expenses? Existing draft edits for this year may be replaced.`)) {
          this.runYearAction("generate_year", { year: this._planYear });
        }
      });
    });

    this.shadowRoot.querySelector("[data-year-activate]")?.addEventListener("click", () => {
      if (window.confirm(`Activate the ${this._planYear} plan?`)) {
        this.runYearAction("activate_year", { year: this._planYear });
      }
    });

    this.shadowRoot.querySelector("[data-year-copy]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      const sourceYear = Number(data.get("source_year"));
      const targetYear = Number(data.get("target_year"));
      if (window.confirm(`Copy ${sourceYear} into ${targetYear}? Existing draft rows for ${targetYear} may be replaced.`)) {
        this.runYearAction("copy_year", {
          source_year: sourceYear,
          target_year: targetYear,
        });
      }
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

    this.shadowRoot.querySelector("[data-test-mobile-notification]")?.addEventListener("click", () => {
      const service = this.shadowRoot.querySelector("[name='mobile_notification_service']")?.value;
      this.sendTestNotification(service);
    });

    this.shadowRoot.querySelector("[data-delete-year-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this.deleteYearPlan(data.get("year"));
    });

    this.shadowRoot.querySelector("[data-delete-month-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this.deleteMonth(data.get("month_key"));
    });

    this.shadowRoot.querySelector("[data-generate-month-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      this.generateMonth(data.get("month_key"));
    });

    this.shadowRoot.querySelector("[data-generate-current-month]")?.addEventListener("click", () => {
      this.generateMonth(this._monthKey);
    });

    this.shadowRoot.querySelector("[data-clear-reminder-log]")?.addEventListener("click", () => {
      this.clearReminderLog();
    });

    this.shadowRoot.querySelector("[data-reset-database]")?.addEventListener("click", () => {
      this.resetDatabase();
    });

    this.shadowRoot.querySelector("[data-import-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this.importExpensesFile(event.currentTarget);
    });

    this.shadowRoot.querySelector("[data-download-sample]")?.addEventListener("click", () => {
      this.downloadSampleCsv();
    });

    this.shadowRoot.querySelector("[data-export-expenses]")?.addEventListener("click", () => {
      this.exportExpensesCsv();
    });

    this.shadowRoot.querySelector("[data-export-current]")?.addEventListener("click", () => {
      this.exportCurrentMonthCsv();
    });

    this.shadowRoot.querySelector("[data-export-history]")?.addEventListener("click", () => {
      this.exportHistoryCsv();
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
      return `${filters}<br><div class="placeholder" role="status" aria-live="polite">Loading current month ledger...</div>`;
    }

    if (this._error) {
      return `${filters}<br><div class="error" role="alert">${this._escape(this._error)}</div>`;
    }

    const data = this._data;
    if (!data || !Array.isArray(data.entries) || data.entries.length === 0) {
      return `
        ${filters}
        <br>
        <div class="toolbar">
          <div>No month entries yet.</div>
          <div class="form-actions">
            <button class="secondary-button" data-refresh>Refresh</button>
            <button class="primary-button" data-generate-current-month>Generate this month</button>
          </div>
        </div>
        <div class="empty">
          <div class="getting-started">
            <strong>Getting started</strong>
            <div>Current Month appears after you add expenses, generate a year plan, and activate it.</div>
            <div class="meta">If this month was wiped, click <strong>Generate this month</strong> to recreate it from the existing year plan.</div>
            <div class="checklist">
              <div class="checklist-item">
                <span class="checklist-number">1</span>
                <span>Add expenses manually or use Bulk Import for CSV/XLSX files.</span>
              </div>
              <div class="checklist-item">
                <span class="checklist-number">2</span>
                <span>Open Year Setup and click Generate ${this._escape(this._planYear)}.</span>
              </div>
              <div class="checklist-item">
                <span class="checklist-number">3</span>
                <span>Review the draft and click Activate year.</span>
              </div>
              <div class="checklist-item">
                <span class="checklist-number">4</span>
                <span>Return here to record full or partial payments.</span>
              </div>
            </div>
            <div class="form-actions">
              <button class="primary-button" data-route="import">Bulk Import</button>
              <button class="secondary-button" data-route="add">Add Expense</button>
              <button class="secondary-button" data-route="year-setup">Year Setup</button>
            </div>
          </div>
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
                <span>Paid ${this._escape(this.formatAmount(entry.actual_paid_amount))}</span>
              </div>
              <div class="entry-tools">
                ${
                  entry.latest_payment_id
                    ? `<button class="secondary-button" type="button" data-undo-payment="${this._escape(entry.latest_payment_id)}" data-undo-payment-label="${this._escape(`the latest payment for ${entry.name}`)}" ${disabled}>Undo last payment</button>`
                    : ""
                }
                ${entry.remaining_amount > 0 ? `
                  <details>
                    <summary class="partial-action" role="button">Record partial payment</summary>
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
                  <summary class="edit-action" role="button">Edit this month</summary>
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
              <strong>${this._escape(this.formatAmount(entry.remaining_amount))}</strong>
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
        <div class="form-actions">
          <button class="secondary-button" data-refresh ${this._loading ? "disabled" : ""}>Refresh</button>
          <button class="secondary-button" data-export-current ${this._loading ? "disabled" : ""}>Export CSV</button>
        </div>
      </div>
      <div class="summary">
        <div class="metric">
          <div class="metric-label">Scheduled</div>
          <div class="metric-value">${this._escape(this.formatAmount(summary.scheduled_total || 0))}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Paid</div>
          <div class="metric-value">${this._escape(this.formatAmount(summary.actual_paid_total || 0))}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Remaining</div>
          <div class="metric-value">${this._escape(this.formatAmount(summary.remaining_total || 0))}</div>
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
    const selectedCount = this._selectedExpenseIds.size;
    const allSelected = expenses.length > 0 && selectedCount === expenses.length;
    const editing = expenses.find(
      (expense) => expense.template_id === this._editingExpenseId
    );
    const formState = this._expenseDraft || editing || {};
    const value = (field, fallback = "") => {
      const stateField = field === "default_amount" ? "amount" : field;
      return this._escape(formState[stateField] ?? formState[field] ?? fallback);
    };
    const recurrence = formState.recurrence || "monthly";
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
        ? `<div class="empty">
            <strong>No expenses yet.</strong>
            <p>Create the first recurring expense with this form, or import a full list from CSV/XLSX.</p>
            <div class="form-actions">
              <button class="primary-button" data-route="import">Bulk Import</button>
            </div>
          </div>`
        : `<div class="expense-list">${expenses.map((expense) => `
            <div class="expense-card ${expense.is_active ? "" : "archived"} ${this._selectedExpenseIds.has(expense.template_id) ? "selected" : ""}">
              <div class="expense-card-top">
                <div style="display:flex;gap:10px;align-items:flex-start">
                  <input type="checkbox" data-expense-select="${expense.template_id}" aria-label="Select ${this._escape(expense.name)}" ${this._selectedExpenseIds.has(expense.template_id) ? "checked" : ""} style="width:20px;height:20px;margin-top:2px">
                  <div>
                  <div class="name">${this._escape(expense.name)}</div>
                  <div class="meta">
                    <span>${this._escape(expense.category)}</span>
                    <span>${this._escape(expense.recurrence.replaceAll("_", " "))}</span>
                    <span>Due day ${this._escape(expense.due_day || "—")}</span>
                    ${expense.is_active ? "" : '<span class="badge archived">Archived</span>'}
                  </div>
                  </div>
                </div>
                <div class="expense-amount">${this._escape(this.formatAmount(expense.default_amount))}</div>
              </div>
              ${expense.notes ? `<div class="meta">${this._escape(expense.notes)}</div>` : ""}
              <div class="expense-actions">
                <button class="secondary-button" data-expense-edit="${expense.template_id}" ${this._expenseBusy ? "disabled" : ""}>Edit</button>
                ${
                  expense.is_active
                    ? `<button class="danger-button" data-expense-archive="${expense.template_id}" ${this._expenseBusy ? "disabled" : ""}>Safe delete</button>`
                    : `<button class="primary-button" data-expense-reactivate="${expense.template_id}" ${this._expenseBusy ? "disabled" : ""}>Reactivate</button>`
                }
              </div>
            </div>
          `).join("")}</div>`;

    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">Expense Management</div>
          <div>${expenses.length} expense${expenses.length === 1 ? "" : "s"}</div>
        </div>
        <div class="form-actions">
          <button class="secondary-button" data-expense-refresh ${this._expenseLoading || this._expenseBusy ? "disabled" : ""}>Refresh</button>
          <button class="secondary-button" data-export-expenses ${expenses.length === 0 ? "disabled" : ""}>Export CSV</button>
        </div>
      </div>
      ${this._expenseError ? `<div class="error" role="alert">${this._escape(this._expenseError)}</div><br>` : ""}
      ${this._expenseBulkResult ? `<div class="empty" role="status" aria-live="polite">${this._escape(this._expenseBulkResult)}</div><br>` : ""}
      ${expenses.length ? `<div class="toolbar report-card">
        <label style="display:flex;align-items:center;gap:8px">
          <input type="checkbox" data-expense-select-all ${allSelected ? "checked" : ""} style="width:20px;height:20px">
          Select all (${selectedCount} selected)
        </label>
        <div class="form-actions">
          <button class="secondary-button" type="button" data-expense-bulk-archive ${!selectedCount || this._expenseBusy ? "disabled" : ""}>Bulk archive</button>
          <button class="danger-button" type="button" data-expense-bulk-delete ${!selectedCount || this._expenseBusy ? "disabled" : ""}>Bulk permanent delete</button>
        </div>
      </div><br>` : ""}
      <div class="expense-layout">
        <section data-expense-editor>
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
                <input id="expense-custom-months" name="custom_months" value="${this._escape(Array.isArray(formState.custom_months) ? formState.custom_months.join(",") : formState.custom_months || "")}" placeholder="1, 4, 7, 10">
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

  renderBulkImport() {
    const response = this._importResult?.response || this._importResult;
    const imported = response?.expenses || [];
    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">Bulk Import</div>
          <div class="section-title">Load expense definitions</div>
          <div class="meta">Import up to 1,000 expenses from a UTF-8 CSV or Excel XLSX file.</div>
        </div>
        <button class="secondary-button" type="button" data-download-sample>Download sample CSV</button>
      </div>
      ${this._importError ? `<div class="error" role="alert">${this._escape(this._importError)}</div><br>` : ""}
      ${response ? `
        <div class="empty">
          <strong>${this._escape(response.imported_count || 0)} expenses imported from ${this._escape(response.filename || "file")}.</strong>
          <p>Import creates reusable expense definitions only. Create the yearly ledger next so Current Month can show payable entries.</p>
          <ol class="next-steps">
            <li>Open Year Setup.</li>
            <li>Click Generate ${this._escape(this._planYear)} to create a draft from the imported expenses.</li>
            <li>Review the draft amounts and dates, then Activate year.</li>
            <li>Return to Current Month to record payments.</li>
          </ol>
          ${imported.length ? `<div class="meta">${imported.map((expense) => this._escape(expense.name)).join(" · ")}</div>` : ""}
          <div class="form-actions" style="margin-top:12px">
            <button class="primary-button" data-route="year-setup">Next: Generate ${this._escape(this._planYear)}</button>
            <button class="secondary-button" data-route="add">Review expenses</button>
          </div>
        </div><br>
      ` : ""}
      <div class="expense-layout">
        <section>
          <form class="import-zone" data-import-form>
            <div>
              <div class="eyebrow">Choose File</div>
              <div class="section-title">CSV or Excel</div>
            </div>
            <input name="expense_file" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required>
            <div class="meta">Maximum file size: 5 MB. The first worksheet is imported from Excel files.</div>
            <button class="primary-button" type="submit" ${this._importBusy ? "disabled" : ""}>${this._importBusy ? "Importing..." : "Import expenses"}</button>
          </form>
        </section>
        <section class="report-card">
          <div class="eyebrow">File Format</div>
          <div class="section-title">Expected columns</div>
          <p class="meta">Required:</p>
          <div class="column-list">
            <code>name</code><code>category</code><code>amount</code><code>recurrence</code>
          </div>
          <p class="meta">Optional:</p>
          <div class="column-list">
            <code>due_day</code><code>start_month</code><code>end_month</code><code>custom_months</code><code>icon</code><code>notes</code><code>reminder_days</code>
          </div>
          <p class="meta">Recurrence values: monthly, one_time, annual, twice_yearly, or custom_months. Use comma-separated month numbers for custom_months.</p>
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
      ? `<div class="placeholder" role="status" aria-live="polite">Loading ${this._planYear} plan...</div>`
      : !plan
        ? `<div class="empty">
            <strong>No plan is loaded for ${this._planYear}.</strong>
            <p>Generate a draft from active expenses, or copy a prior year if you already have one.</p>
            <div class="form-actions">
              <button class="primary-button" data-year-generate ${disabled}>Generate ${this._escape(this._planYear)}</button>
              <button class="secondary-button" data-route="add">Review expenses</button>
            </div>
          </div>`
        : `<div class="plan-list">${[...itemsByMonth.entries()].map(([month, items]) => {
            const monthName = new Intl.DateTimeFormat(undefined, { month: "long" }).format(
              new Date(this._planYear, month - 1, 1)
            );
            const total = items.reduce((sum, item) => sum + item.scheduled_amount, 0);
            return `
              <details class="month-group" ${month === (this._planYear === currentYear ? new Date().getMonth() + 1 : 1) ? "open" : ""}>
                <summary class="month-heading">
                  <strong>${this._escape(monthName)}</strong>
                  <span>${items.length} item${items.length === 1 ? "" : "s"} · ${this._escape(this.formatAmount(total))}</span>
                </summary>
                ${items.map((item) => `
                  <details class="plan-item">
                    <summary>
                      <span>
                        <span class="name">${this._escape(item.name)}</span>
                        <span class="meta">${this._escape(item.category)} · Due ${this._escape(item.due_date || "—")}</span>
                      </span>
                      <span class="expense-amount">${this._escape(this.formatAmount(item.scheduled_amount))}</span>
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
              </details>
            `;
          }).join("")}</div>`;

    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">Year Setup</div>
          <div class="section-title">Plan ${this._escape(this._planYear)}</div>
          ${plan ? `<div class="meta"><span>Status: ${this._escape(plan.plan.status)}</span><span>${plan.item_count} entries</span></div>` : ""}
          <div class="meta">After importing expenses, generate this year, review the draft, then activate it to populate Current Month.</div>
        </div>
        ${isDraft ? `<button class="primary-button" data-year-activate ${disabled}>Activate year</button>` : ""}
      </div>
      ${this._yearError ? `<div class="error" role="alert">${this._escape(this._yearError)}</div><br>` : ""}
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
          <div class="eyebrow">Step 1 · Generate</div>
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
      return `<div class="placeholder" role="status" aria-live="polite">Loading ${this._escape(this._historyYear)} history...</div>`;
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
        <div class="form-actions">
          <form class="inline-form" data-history-year>
            <div class="field">
              <label>Year</label>
              <input name="year" type="number" min="2000" max="2100" value="${this._escape(this._historyYear)}" required>
            </div>
            <button class="primary-button" type="submit">Load</button>
          </form>
          <button class="secondary-button" data-export-history ${!history || history.entry_count === 0 ? "disabled" : ""}>Export CSV</button>
        </div>
      </div>
      ${this._historyError ? `<div class="error" role="alert">${this._escape(this._historyError)}</div><br>` : ""}
      ${!history || history.entry_count === 0 ? `
        <div class="empty">
          <strong>No ledger history exists for ${this._escape(this._historyYear)}.</strong>
          <p>Generate and activate a year plan, then record payments in Current Month.</p>
          <div class="form-actions">
            <button class="primary-button" data-route="year-setup">Open Year Setup</button>
            <button class="secondary-button" data-route="current">Current Month</button>
          </div>
        </div>
      ` : `
        <div class="summary">
          <div class="metric"><div class="metric-label">Planned</div><div class="metric-value">${this._escape(this.formatAmount(summary.scheduled_total))}</div></div>
          <div class="metric"><div class="metric-label">Paid</div><div class="metric-value">${this._escape(this.formatAmount(summary.actual_paid_total))}</div></div>
          <div class="metric"><div class="metric-label">Remaining</div><div class="metric-value">${this._escape(this.formatAmount(summary.remaining_total))}</div></div>
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
                    <span>${this._escape(this.formatAmount(monthSummary.actual_paid_total))} / ${this._escape(this.formatAmount(monthSummary.scheduled_total))}</span>
                  </summary>
                  <div class="progress-track"><div class="progress-value" style="width:${progress(monthSummary.actual_paid_total, monthSummary.scheduled_total)}%"></div></div>
                  <div class="payment-list">
                    ${month.entries.map((entry) => `
                      <div class="payment-row">
                        <span>${this._escape(entry.name)} <span class="meta">${this._escape(entry.status)}</span></span>
                        <span>${this._escape(this.formatAmount(entry.actual_paid_amount))} / ${this._escape(this.formatAmount(entry.scheduled_amount))}</span>
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
                  <span>${this._escape(this.formatAmount(category.actual_paid_amount))} / ${this._escape(this.formatAmount(category.scheduled_amount))}</span>
                </div>
                <div class="progress-track"><div class="progress-value" style="width:${progress(category.actual_paid_amount, category.scheduled_amount)}%"></div></div>
              </div>
            `).join("")}
          </section>
          <section class="report-card">
            <div class="eyebrow">Payment History</div>
            <div class="section-title">Recorded transactions</div>
            ${payments.length === 0 ? `<div class="empty">
              <strong>No payments recorded for this year.</strong>
              <p>Use Current Month to mark expenses paid or record partial payments.</p>
              <div class="form-actions">
                <button class="primary-button" data-route="current">Open Current Month</button>
              </div>
            </div>` : `
              <div class="payment-list">
                ${payments.map((payment) => `
                  <div class="payment-row">
                    <span>
                      <strong>${this._escape(payment.name)}</strong>
                      <span class="meta">${this._escape(payment.paid_date)} · ${this._escape(payment.category)}${payment.note ? ` · ${this._escape(payment.note)}` : ""}</span>
                    </span>
                    <span class="expense-amount">${this._escape(this.formatAmount(payment.amount))}</span>
                    <button class="secondary-button" data-undo-payment="${this._escape(payment.payment_id)}" data-undo-payment-label="${this._escape(`${this.formatAmount(payment.amount)} payment for ${payment.name}`)}">Undo</button>
                  </div>
                `).join("")}
              </div>
            `}
          </section>
        </div>
      `}
    `;
  }

  renderCleanupResult(cleanup) {
    if (!cleanup) {
      return "";
    }
    if (cleanup.deleted_counts) {
      return `
        <div class="empty">
          <strong>Finance data reset.</strong>
          <p>All expenses, generated years, month ledgers, payments, reminders, and settings were removed.</p>
          <div class="form-actions">
            <button class="primary-button" data-route="import">Bulk Import</button>
            <button class="secondary-button" data-route="add">Add Expense</button>
          </div>
        </div>
        <br>
      `;
    }
    if (cleanup.year && cleanup.deleted_entries !== undefined) {
      return `
        <div class="empty">
          <strong>Year ${this._escape(cleanup.year)} deleted.</strong>
          <p>${this._escape(cleanup.deleted_entries)} ledger rows and ${this._escape(cleanup.deleted_payments || 0)} payments were removed. To add it back, open Year Setup and generate ${this._escape(cleanup.year)} again.</p>
          <div class="form-actions">
            <button class="primary-button" data-route="year-setup">Open Year Setup</button>
          </div>
        </div>
        <br>
      `;
    }
    if (cleanup.month_key && cleanup.created_entries !== undefined) {
      return `
        <div class="empty">
          <strong>Month ${this._escape(cleanup.month_key)} generated.</strong>
          <p>${this._escape(cleanup.created_entries)} ledger rows were created from the existing year plan.</p>
          <div class="form-actions">
            <button class="primary-button" data-route="current">Open Current Month</button>
          </div>
        </div>
        <br>
      `;
    }
    if (cleanup.month_key && cleanup.deleted_entries !== undefined) {
      return `
        <div class="empty">
          <strong>Month ${this._escape(cleanup.month_key)} wiped.</strong>
          <p>${this._escape(cleanup.deleted_entries)} ledger rows and ${this._escape(cleanup.deleted_payments || 0)} payments were removed. Use Generate month below to recreate only this month from the year plan.</p>
        </div>
        <br>
      `;
    }
    return `<div class="empty">Cleanup complete.</div><br>`;
  }

  renderSettings() {
    if (this._settingsLoading && !this._settings) {
      return `<div class="placeholder" role="status" aria-live="polite">Loading settings...</div>`;
    }
    const settings = this._settings || {
      currency: "INR",
      reminders_enabled: true,
      notification_service: "persistent_notification.create",
      mobile_notification_service: "",
      scan_interval_minutes: 60,
    };
    const mobileNotifyServices = Object.keys(this._hass?.services?.notify || {})
      .filter((service) => service.startsWith("mobile_app_"))
      .sort();
    const mobileOptions = mobileNotifyServices.map((service) =>
      `<option value="notify.${this._escape(service)}"></option>`
    ).join("");
    const currencies = [
      ["INR", "₹ Indian Rupee (INR)"],
      ["USD", "$ US Dollar (USD)"],
      ["EUR", "€ Euro (EUR)"],
      ["GBP", "£ British Pound (GBP)"],
      ["AED", "د.إ UAE Dirham (AED)"],
      ["AUD", "$ Australian Dollar (AUD)"],
      ["CAD", "$ Canadian Dollar (CAD)"],
      ["CHF", "CHF Swiss Franc (CHF)"],
      ["CNY", "¥ Chinese Yuan (CNY)"],
      ["HKD", "$ Hong Kong Dollar (HKD)"],
      ["JPY", "¥ Japanese Yen (JPY)"],
      ["NZD", "$ New Zealand Dollar (NZD)"],
      ["SAR", "﷼ Saudi Riyal (SAR)"],
      ["SGD", "$ Singapore Dollar (SGD)"],
      ["ZAR", "R South African Rand (ZAR)"],
    ];
    if (!currencies.some(([code]) => code === settings.currency)) {
      currencies.push([settings.currency, `${settings.currency} (current)`]);
    }
    const currencyOptions = currencies.map(([code, label]) =>
      `<option value="${this._escape(code)}" ${settings.currency === code ? "selected" : ""}>${this._escape(label)}</option>`
    ).join("");
    const result = this._reminderRunResult;
    const cleanup = this._cleanupResult;

    return `
      <div class="toolbar">
        <div>
          <div class="eyebrow">Settings</div>
          <div class="section-title">Notifications and defaults</div>
        </div>
      </div>
      ${this._settingsError ? `<div class="error" role="alert">${this._escape(this._settingsError)}</div><br>` : ""}
      ${result ? `<div class="empty" role="status" aria-live="polite">Reminder scan complete: ${this._escape(result.sent ?? 0)} sent, ${this._escape(result.failed ?? 0)} failed, ${this._escape(result.candidates ?? 0)} eligible.</div><br>` : ""}
      ${this.renderCleanupResult(cleanup)}
      <div class="expense-layout">
        <section>
          <form class="expense-form" data-settings-form>
            <div class="form-grid">
              <div class="field">
                <label for="settings-currency">Display currency</label>
                <select id="settings-currency" name="currency" required>${currencyOptions}</select>
              </div>
              <div class="field">
                <label for="settings-interval">Scan interval (minutes)</label>
                <input id="settings-interval" name="scan_interval_minutes" type="number" min="5" max="1440" required value="${this._escape(settings.scan_interval_minutes)}">
              </div>
              <div class="field full">
                <label for="settings-service">Home Assistant notification service</label>
                <input id="settings-service" name="notification_service" required value="${this._escape(settings.notification_service)}" placeholder="notify.mobile_app_phone">
              </div>
              <div class="field full">
                <label for="settings-mobile-service">Phone notification service (optional)</label>
                <input id="settings-mobile-service" name="mobile_notification_service" list="mobile-notify-services" value="${this._escape(settings.mobile_notification_service || "")}" placeholder="Select or enter notify.mobile_app_your_phone">
                <datalist id="mobile-notify-services">${mobileOptions}</datalist>
                <span class="meta">${mobileNotifyServices.length ? `${mobileNotifyServices.length} Companion App device service(s) detected.` : "No mobile_app notify service detected. Open the Home Assistant Companion App once, then reload this page."}</span>
              </div>
              <div class="field full">
                <label for="settings-reminders-enabled">
                  <input id="settings-reminders-enabled" name="reminders_enabled" type="checkbox" ${settings.reminders_enabled ? "checked" : ""} style="width:auto">
                  Enable automatic reminders
                </label>
              </div>
            </div>
            <div class="form-actions">
              <button class="primary-button" type="submit" ${this._settingsBusy ? "disabled" : ""}>${this._settingsBusy ? "Working..." : "Save settings"}</button>
              <button class="secondary-button" type="button" data-test-mobile-notification ${this._settingsBusy ? "disabled" : ""}>Send test to phone</button>
            </div>
          </form>
        </section>
        <section class="report-card">
          <div class="eyebrow">Reminder Engine</div>
          <div class="section-title">Delivery behavior</div>
          <p class="meta">Each expense uses its reminder-days setting. Upcoming, due-today, and overdue reminders are sent at most once per entry per day.</p>
          <p class="meta">The Home Assistant target creates an in-app notification. Add a detected <strong>notify.mobile_app_…</strong> target to send the same reminder to your phone as well.</p>
          <button class="secondary-button" type="button" data-run-reminders ${this._settingsBusy ? "disabled" : ""}>Run reminder scan now</button>
        </section>
        <section class="report-card">
          <div class="eyebrow">Cleanup Tools</div>
          <div class="section-title">Safe maintenance</div>
          <p class="meta">These actions do not remove expense definitions or delete the Finance Tracker database. Use them when testing or rebuilding a generated year.</p>
          <p class="meta">If you delete a year, open Year Setup and Generate that year again. If you wipe a month, use Generate month here to recreate only that month.</p>
          <form class="inline-form" data-delete-year-form>
            <div class="field">
              <label>Year to delete</label>
              <input name="year" type="number" min="2000" max="2100" value="${this._escape(this._planYear)}" required>
            </div>
            <button class="danger-button" type="submit" ${this._settingsBusy ? "disabled" : ""}>Delete generated year</button>
          </form>
          <form class="inline-form" data-delete-month-form style="margin-top:12px">
            <div class="field">
              <label>Month to wipe</label>
              <input name="month_key" type="month" value="${this._escape(this._monthKey)}" required>
            </div>
            <button class="danger-button" type="submit" ${this._settingsBusy ? "disabled" : ""}>Wipe month ledger</button>
          </form>
          <form class="inline-form" data-generate-month-form style="margin-top:12px">
            <div class="field">
              <label>Month to generate</label>
              <input name="month_key" type="month" value="${this._escape(this._monthKey)}" required>
            </div>
            <button class="primary-button" type="submit" ${this._settingsBusy ? "disabled" : ""}>Generate month</button>
          </form>
          <div class="form-actions" style="margin-top:12px">
            <button class="secondary-button" type="button" data-clear-reminder-log ${this._settingsBusy ? "disabled" : ""}>Clear reminder log</button>
            <button class="danger-button" type="button" data-reset-database ${this._settingsBusy ? "disabled" : ""}>Reset all Finance data</button>
          </div>
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
          This Finance Tracker route is not available yet. Use the tabs above to open a live workflow.
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

  formatAmount(value) {
    const amount = Number(value || 0);
    const currency = String(this._settings?.currency || "INR").toUpperCase();
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch (_err) {
      return `${currency} ${amount.toFixed(2)}`;
    }
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

if (!customElements.get(FINANCE_TRACKER_PANEL_ELEMENT)) {
  customElements.define(FINANCE_TRACKER_PANEL_ELEMENT, FinanceTrackerPanel);
}
