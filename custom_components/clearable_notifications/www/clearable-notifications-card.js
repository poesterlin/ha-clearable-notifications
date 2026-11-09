/* Clearable Notifications card — served by the clearable_notifications integration. */
(() => {
  const DOMAIN = "clearable_notifications";
  const CARD_TYPE = "clearable-notifications-card";
  const VERSION = "0.1.0";
  const SEVERITIES = ["info", "warning", "critical"];
  const RANK = { info: 1, warning: 2, critical: 3 };
  const SEVERITY_LABEL = { info: "Info", warning: "Warning", critical: "Critical" };
  const SEVERITY_COLOR = {
    info: "var(--info-color, #039be5)",
    warning: "var(--warning-color, #ffa600)",
    critical: "var(--error-color, #db4437)",
  };
  const CLEARED_LIMIT = 5;

  const DEFAULTS = {
    title: "",
    entities: [],
    min_severity: "info",
    show_acknowledged: true,
    show_cleared: false,
    show_actions: true,
    hide_when_empty: false,
    empty_message: "All clear",
  };

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const isNotification = (hass, entityId) => {
    if (!entityId.startsWith("binary_sensor.")) return false;
    const entry = hass.entities?.[entityId];
    if (entry) return entry.platform === DOMAIN;
    const attrs = hass.states[entityId]?.attributes;
    return !!attrs && "notification_id" in attrs && "severity_rank" in attrs;
  };

  const relativeTime = (iso, lang) => {
    if (!iso) return "";
    const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
    const rtf = new Intl.RelativeTimeFormat(lang || "en", { numeric: "auto" });
    const abs = Math.abs(seconds);
    if (abs < 45) return seconds <= 0 && String(lang).startsWith("en") ? "just now" : rtf.format(0, "second");
    if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
    return rtf.format(Math.round(seconds / 86400), "day");
  };

  const absoluteTime = (iso, lang) =>
    iso ? new Date(iso).toLocaleString(lang || undefined, { dateStyle: "medium", timeStyle: "short" }) : "";

  class ClearableNotificationsCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._signature = "";
      this._onClick = this._onClick.bind(this);
      this._onKeyDown = this._onKeyDown.bind(this);
    }

    static getConfigElement() {
      return document.createElement(`${CARD_TYPE}-editor`);
    }

    static getStubConfig() {
      return { title: "Notifications" };
    }

    setConfig(config) {
      if (!config) throw new Error("Invalid configuration");
      if (config.min_severity && !SEVERITIES.includes(config.min_severity)) {
        throw new Error(`min_severity must be one of: ${SEVERITIES.join(", ")}`);
      }
      if (config.entities && !Array.isArray(config.entities)) {
        throw new Error("entities must be a list");
      }
      this._config = { ...DEFAULTS, ...config };
      this._signature = "";
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    get hass() {
      return this._hass;
    }

    connectedCallback() {
      this.shadowRoot.addEventListener("click", this._onClick);
      this.shadowRoot.addEventListener("keydown", this._onKeyDown);
      // Keep relative times ("5 minutes ago") fresh.
      this._timer = setInterval(() => {
        this._signature = "";
        this._render();
      }, 30000);
    }

    disconnectedCallback() {
      this.shadowRoot.removeEventListener("click", this._onClick);
      this.shadowRoot.removeEventListener("keydown", this._onKeyDown);
      clearInterval(this._timer);
    }

    getCardSize() {
      return 1 + Math.max(1, this._items?.length || 0) * 2;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 4, min_rows: 2 };
    }

    _entityIds() {
      const hass = this._hass;
      if (this._config.entities?.length) {
        return this._config.entities.map((e) => (typeof e === "string" ? e : e.entity)).filter(Boolean);
      }
      return Object.keys(hass.states).filter((id) => isNotification(hass, id));
    }

    _collect() {
      const hass = this._hass;
      const cfg = this._config;
      const minRank = RANK[cfg.min_severity] || 1;
      const active = [];
      const cleared = [];
      for (const entityId of this._entityIds()) {
        const stateObj = hass.states[entityId];
        if (!stateObj) continue;
        const a = stateObj.attributes;
        const severity = SEVERITIES.includes(a.severity) ? a.severity : "info";
        if (RANK[severity] < minRank) continue;
        const item = {
          entityId,
          severity,
          name: a.friendly_name || entityId,
          title: a.title,
          message: a.message,
          icon: a.icon,
          acknowledged: !!a.acknowledged,
          activatedAt: a.activated_at,
          clearedAt: a.cleared_at,
          autoClearAt: a.auto_clear_at,
          active: stateObj.state === "on",
        };
        if (item.active) {
          if (item.acknowledged && !cfg.show_acknowledged) continue;
          active.push(item);
        } else if (cfg.show_cleared && item.clearedAt) {
          cleared.push(item);
        }
      }
      active.sort(
        (x, y) =>
          RANK[y.severity] - RANK[x.severity] ||
          Number(x.acknowledged) - Number(y.acknowledged) ||
          String(y.activatedAt).localeCompare(String(x.activatedAt))
      );
      cleared.sort((x, y) => String(y.clearedAt).localeCompare(String(x.clearedAt)));
      return { active, cleared: cleared.slice(0, CLEARED_LIMIT) };
    }

    _render() {
      if (!this._config || !this._hass) return;
      const { active, cleared } = this._collect();
      const signature = JSON.stringify([active, cleared, this._config, this._busy]);
      if (signature === this._signature) return;
      this._signature = signature;
      this._items = [...active, ...cleared];

      const cfg = this._config;
      const lang = this._hass.locale?.language || this._hass.language;
      const hidden = cfg.hide_when_empty && !active.length && !cleared.length;
      this.style.display = hidden ? "none" : "";
      if (hidden) {
        this.shadowRoot.innerHTML = "";
        return;
      }

      const unacked = active.filter((i) => !i.acknowledged);
      const top = active[0]?.severity;
      const header = cfg.title
        ? `<div class="header">
            <div class="heading">
              <span class="name">${esc(cfg.title)}</span>
              ${active.length ? `<span class="count" style="--sev:${SEVERITY_COLOR[top]}">${active.length}</span>` : ""}
            </div>
            ${cfg.show_actions && unacked.length > 1
              ? `<button class="text-btn" data-action="ack-all" title="Acknowledge all">
                   <ha-icon icon="mdi:check-all"></ha-icon><span>Acknowledge all</span>
                 </button>`
              : ""}
          </div>`
        : "";

      const body = active.length || cleared.length
        ? `<ul class="list">
             ${active.map((i) => this._renderItem(i, lang)).join("")}
             ${cleared.length ? `<li class="divider">Recently cleared</li>` : ""}
             ${cleared.map((i) => this._renderItem(i, lang)).join("")}
           </ul>`
        : `<div class="empty">
             <ha-icon icon="mdi:check-circle-outline"></ha-icon>
             <span>${esc(cfg.empty_message)}</span>
           </div>`;

      this.shadowRoot.innerHTML = `<style>${STYLES}</style><ha-card>${header}${body}</ha-card>`;
    }

    _renderItem(item, lang) {
      const cfg = this._config;
      const heading = item.title || item.name;
      const showName = item.title && item.title !== item.name;
      const when = item.active ? item.activatedAt : item.clearedAt;
      const meta = [
        showName ? esc(item.name) : "",
        when
          ? `<time title="${esc(absoluteTime(when, lang))}">${item.active ? "" : "Cleared "}${esc(relativeTime(when, lang))}</time>`
          : "",
        item.active && item.autoClearAt ? `<span title="${esc(absoluteTime(item.autoClearAt, lang))}">auto-clears ${esc(relativeTime(item.autoClearAt, lang))}</span>` : "",
      ].filter(Boolean).join('<span class="dot">·</span>');

      const classes = ["item", item.severity, item.active ? "active" : "cleared", item.acknowledged ? "acked" : "unacked"];
      const busy = this._busy === item.entityId;
      const actions = cfg.show_actions && item.active
        ? `<div class="actions">
             ${item.acknowledged
               ? `<span class="ack-badge" title="Acknowledged"><ha-icon icon="mdi:check"></ha-icon></span>`
               : `<button class="icon-btn" data-action="acknowledge" data-entity="${esc(item.entityId)}" title="Acknowledge" aria-label="Acknowledge ${esc(heading)}" ${busy ? "disabled" : ""}><ha-icon icon="mdi:check"></ha-icon></button>`}
             <button class="icon-btn" data-action="clear" data-entity="${esc(item.entityId)}" title="Clear" aria-label="Clear ${esc(heading)}" ${busy ? "disabled" : ""}><ha-icon icon="mdi:close"></ha-icon></button>
           </div>`
        : "";

      return `<li class="${classes.join(" ")}" style="--sev:${SEVERITY_COLOR[item.severity]}"
                  data-action="more-info" data-entity="${esc(item.entityId)}" tabindex="0" role="button"
                  aria-label="${esc(SEVERITY_LABEL[item.severity])}: ${esc(heading)}">
        <div class="badge"><ha-icon icon="${esc(item.icon || "mdi:bell")}"></ha-icon></div>
        <div class="content">
          <div class="title-row">
            <span class="title">${esc(heading)}</span>
            <span class="sev">${esc(SEVERITY_LABEL[item.severity])}</span>
          </div>
          ${item.message ? `<div class="message">${esc(item.message)}</div>` : ""}
          ${meta ? `<div class="meta">${meta}</div>` : ""}
        </div>
        ${actions}
      </li>`;
    }

    _onKeyDown(ev) {
      if ((ev.key === "Enter" || ev.key === " ") && ev.target.matches?.("li[data-action]")) {
        ev.preventDefault();
        this._handle(ev.target);
      }
    }

    _onClick(ev) {
      const target = ev.composedPath().find((el) => el instanceof HTMLElement && el.dataset?.action);
      if (target) this._handle(target);
    }

    async _handle(target) {
      const { action, entity } = target.dataset;
      if (action === "more-info") {
        this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: entity }, bubbles: true, composed: true }));
        return;
      }
      let service;
      let entityIds;
      if (action === "ack-all") {
        service = "acknowledge";
        entityIds = this._collect().active.filter((i) => !i.acknowledged).map((i) => i.entityId);
      } else if (action === "acknowledge" || action === "clear") {
        service = action;
        entityIds = [entity];
      } else {
        return;
      }
      this._busy = entity || "all";
      this._render();
      try {
        await this._hass.callService(DOMAIN, service, { entity_id: entityIds });
      } catch (err) {
        this.dispatchEvent(
          new CustomEvent("hass-notification", {
            detail: { message: `Could not ${service} notification: ${err?.message || err}` },
            bubbles: true,
            composed: true,
          })
        );
      } finally {
        this._busy = undefined;
        this._signature = "";
        this._render();
      }
    }
  }

  const STYLES = `
    :host { display: block; }
    ha-card { overflow: hidden; }
    .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 16px 4px; }
    .heading { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .name { font-size: var(--ha-card-header-font-size, 1.25rem); font-weight: 500; color: var(--ha-card-header-color, var(--primary-text-color)); }
    .count { min-width: 22px; height: 22px; padding: 0 7px; box-sizing: border-box; border-radius: 11px; background: var(--sev); color: #fff;
             font-size: 0.8rem; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; }
    .list { list-style: none; margin: 0; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
    .item { position: relative; display: flex; align-items: flex-start; gap: 12px; padding: 10px 10px 10px 12px; border-radius: 12px; cursor: pointer;
            background: color-mix(in srgb, var(--sev) 10%, var(--card-background-color, transparent)); outline: none;
            transition: background-color 150ms ease, opacity 150ms ease; }
    .item::before { content: ""; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 3px; background: var(--sev); }
    .item:hover { background: color-mix(in srgb, var(--sev) 16%, var(--card-background-color, transparent)); }
    .item:focus-visible { box-shadow: 0 0 0 2px var(--sev); }
    .item.acked { background: color-mix(in srgb, var(--sev) 4%, var(--card-background-color, transparent)); }
    .item.acked .badge { background: transparent; color: var(--sev); box-shadow: inset 0 0 0 1.5px var(--sev); }
    .item.acked .title, .item.acked .message { color: var(--secondary-text-color); }
    .item.cleared { background: transparent; opacity: 0.65; }
    .item.cleared::before, .item.cleared .badge { background: var(--disabled-color, #9e9e9e); }
    .badge { flex: none; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
             background: var(--sev); color: #fff; --mdc-icon-size: 20px; }
    .item.critical.unacked.active .badge { animation: pulse 2s ease-out infinite; }
    @keyframes pulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--sev) 55%, transparent); } 70%, 100% { box-shadow: 0 0 0 10px transparent; } }
    @media (prefers-reduced-motion: reduce) { .item.critical.unacked.active .badge { animation: none; } }
    .content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
    .title-row { display: flex; align-items: baseline; gap: 8px; }
    .title { font-weight: 500; color: var(--primary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sev { flex: none; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sev); }
    .item.cleared .sev { color: var(--secondary-text-color); }
    .message { color: var(--primary-text-color); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.4; }
    .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: 0.8rem; color: var(--secondary-text-color); }
    .dot { opacity: 0.6; }
    .actions { flex: none; display: flex; align-items: center; gap: 2px; }
    .icon-btn, .ack-badge { width: 36px; height: 36px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
             --mdc-icon-size: 20px; color: var(--secondary-text-color); }
    .icon-btn { border: none; background: transparent; cursor: pointer; padding: 0; }
    .icon-btn:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); color: var(--primary-text-color); }
    .icon-btn:focus-visible { outline: 2px solid var(--primary-color); }
    .icon-btn[disabled] { opacity: 0.4; cursor: progress; }
    .ack-badge { color: var(--success-color, #43a047); }
    .text-btn { display: inline-flex; align-items: center; gap: 4px; border: none; background: transparent; cursor: pointer; border-radius: 18px;
                padding: 6px 10px; color: var(--primary-color); font: inherit; font-size: 0.875rem; font-weight: 500; --mdc-icon-size: 18px; }
    .text-btn:hover { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
    .divider { padding: 8px 4px 0; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--secondary-text-color); }
    .empty { display: flex; align-items: center; gap: 12px; padding: 16px; color: var(--secondary-text-color); --mdc-icon-size: 28px; }
    .empty ha-icon { color: var(--success-color, #43a047); }
  `;

  const EDITOR_LABELS = {
    title: "Title",
    entities: "Notifications (empty = all)",
    min_severity: "Minimum severity",
    show_acknowledged: "Show acknowledged",
    show_cleared: "Show recently cleared",
    show_actions: "Show acknowledge/clear buttons",
    hide_when_empty: "Hide card when nothing is active",
    empty_message: "Empty message",
  };

  const EDITOR_SCHEMA = [
    { name: "title", selector: { text: {} } },
    {
      name: "entities",
      selector: { entity: { multiple: true, filter: { integration: DOMAIN, domain: "binary_sensor" } } },
    },
    {
      name: "min_severity",
      selector: {
        select: { mode: "dropdown", options: SEVERITIES.map((value) => ({ value, label: SEVERITY_LABEL[value] })) },
      },
    },
    {
      type: "grid",
      name: "",
      schema: [
        { name: "show_acknowledged", selector: { boolean: {} } },
        { name: "show_cleared", selector: { boolean: {} } },
        { name: "show_actions", selector: { boolean: {} } },
        { name: "hide_when_empty", selector: { boolean: {} } },
      ],
    },
    { name: "empty_message", selector: { text: {} } },
  ];

  class ClearableNotificationsCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = config;
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      if (this._form) this._form.hass = hass;
      else this._render();
    }

    _render() {
      if (!this._hass || !this._config) return;
      if (!this._form) {
        this._form = document.createElement("ha-form");
        this._form.computeLabel = (s) => EDITOR_LABELS[s.name] ?? s.name;
        this._form.addEventListener("value-changed", (ev) => {
          const config = { ...ev.detail.value };
          // Drop values equal to defaults to keep YAML tidy.
          for (const [key, value] of Object.entries(config)) {
            const empty = value === "" || value === undefined || (Array.isArray(value) && !value.length);
            if (empty || (key !== "type" && DEFAULTS[key] === value)) delete config[key];
          }
          this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
        });
        this.appendChild(this._form);
      }
      this._form.hass = this._hass;
      this._form.schema = EDITOR_SCHEMA;
      this._form.data = { ...DEFAULTS, ...this._config };
    }
  }

  if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, ClearableNotificationsCard);
  if (!customElements.get(`${CARD_TYPE}-editor`)) customElements.define(`${CARD_TYPE}-editor`, ClearableNotificationsCardEditor);

  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "Clearable Notifications",
      description: "Active notifications with severity, acknowledge and clear.",
      preview: true,
      documentationURL: "https://github.com/poesterlin/ha-clearable-notifications",
    });
  }

  console.info(`%c CLEARABLE-NOTIFICATIONS-CARD %c ${VERSION} `, "color:#fff;background:#9333ea;font-weight:600", "color:#9333ea");
})();
