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
    this._boundPopstate = () => {
      this._route = this._routeFromLocation();
      this.render();
      if (this._route === "current") {
        this.loadCurrentMonth();
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
        paid_date: new Date().toISOString().slice(0, 10),
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

  navigate(route) {
    if (route === this._route) {
      return;
    }

    history.pushState({}, "", `/finance/${route}`);
    this._route = route;
    this.render();
    if (route === "current") {
      this.loadCurrentMonth();
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

    const currentBody =
      route === "current"
        ? this.renderCurrentMonth()
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
  }

  renderCurrentMonth() {
    if (this._loading) {
      return `<div class="placeholder">Loading current month ledger...</div>`;
    }

    if (this._error) {
      return `<div class="error">${this._escape(this._error)}</div>`;
    }

    const data = this._data;
    if (!data || !Array.isArray(data.entries) || data.entries.length === 0) {
      return `
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
            <div>
              <div class="entry-top">
                <div class="name">${this._escape(entry.name)}</div>
                <div class="badge ${entry.status}">${this._escape(entry.status)}</div>
              </div>
              <div class="meta">
                <span>${this._escape(entry.category)}</span>
                <span>Due ${this._escape(entry.due_date || "No due date")}</span>
                <span>Paid ${this._escape(entry.actual_paid_amount.toFixed(2))}</span>
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
