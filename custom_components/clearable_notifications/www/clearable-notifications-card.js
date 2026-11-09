/* Clearable Notifications card — served by the clearable_notifications integration. */
(() => {
  const DOMAIN = "clearable_notifications";
  const CARD_TYPE = "clearable-notifications-card";
  const VERSION = "0.2.0";
  const SEVERITIES = ["info", "warning", "critical"];
  const RANK = { info: 1, warning: 2, critical: 3 };
  const SEVERITY_COLOR = {
    info: "var(--info-color, #039be5)",
    warning: "var(--warning-color, #ffa600)",
    critical: "var(--error-color, #db4437)",
  };
  const CLEARED_LIMIT = 5;

  const DEFAULTS = {
    layout: "large",
    title: "",
    icon: "mdi:bell-outline",
    entities: [],
    min_severity: "info",
    read_action: "auto",
    read_icon: "mdi:check",
    show_acknowledged: true,
    show_cleared: false,
    show_actions: true,
    show_time: true,
    hide_when_empty: false,
    empty_message: "",
  };

  const STRINGS = {
    en: {
      read: "Mark as read",
      read_all: "Mark all as read",
      acknowledge: "Acknowledge",
      clear: "Clear",
      acknowledged: "Read",
      empty: "No notifications",
      recently_cleared: "Recently cleared",
      cleared: "Cleared {time}",
      clears: "clears {time}",
      just_now: "just now",
      info: "Info",
      warning: "Warning",
      critical: "Critical",
      error: "Could not update the notification: {error}",
    },
    de: {
      read: "Gelesen",
      read_all: "Alle gelesen",
      acknowledge: "Bestätigen",
      clear: "Entfernen",
      acknowledged: "Gelesen",
      empty: "Keine Benachrichtigungen",
      recently_cleared: "Zuletzt entfernt",
      cleared: "Entfernt {time}",
      clears: "verschwindet {time}",
      just_now: "gerade eben",
      info: "Info",
      warning: "Warnung",
      critical: "Kritisch",
      error: "Benachrichtigung konnte nicht aktualisiert werden: {error}",
    },
  };

  const EDITOR_STRINGS = {
    en: {
      layout: "Layout",
      layout_large: "Large",
      layout_compact: "Compact list",
      title: "Heading",
      icon: "Heading icon",
      entities: "Notifications (empty = all)",
      min_severity: "Minimum severity",
      read_action: "Read button",
      read_auto: "Info: clear, others: acknowledge",
      read_acknowledge: "Always acknowledge",
      read_clear: "Always clear",
      read_icon: "Read button icon",
      show_acknowledged: "Show read notifications",
      show_cleared: "Show recently cleared",
      show_actions: "Show buttons",
      show_time: "Show time",
      hide_when_empty: "Hide when nothing is active",
      empty_message: "Empty message",
    },
    de: {
      layout: "Darstellung",
      layout_large: "Groß",
      layout_compact: "Kompakte Liste",
      title: "Überschrift",
      icon: "Symbol der Überschrift",
      entities: "Benachrichtigungen (leer = alle)",
      min_severity: "Mindest-Schweregrad",
      read_action: "Gelesen-Schaltfläche",
      read_auto: "Info: entfernen, sonst: bestätigen",
      read_acknowledge: "Immer bestätigen",
      read_clear: "Immer entfernen",
      read_icon: "Symbol der Gelesen-Schaltfläche",
      show_acknowledged: "Gelesene anzeigen",
      show_cleared: "Zuletzt entfernte anzeigen",
      show_actions: "Schaltflächen anzeigen",
      show_time: "Zeit anzeigen",
      hide_when_empty: "Ausblenden, wenn nichts aktiv ist",
      empty_message: "Text, wenn leer",
    },
  };

  const langOf = (hass) => String(hass?.locale?.language || hass?.language || "en");
  const pick = (table, hass) => table[langOf(hass).split("-")[0]] || table.en;
  const fill = (template, values) => template.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const isNotification = (hass, entityId) => {
    if (!entityId.startsWith("binary_sensor.")) return false;
    const entry = hass.entities?.[entityId];
    if (entry) return entry.platform === DOMAIN;
    const attrs = hass.states[entityId]?.attributes;
    return !!attrs && "notification_id" in attrs && "severity_rank" in attrs;
  };

  const relativeTime = (iso, lang, t) => {
    if (!iso) return "";
    const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
    const abs = Math.abs(seconds);
    if (abs < 45 && seconds <= 0) return t.just_now;
    const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
    const minutes = Math.round(seconds / 60);
    if (Math.abs(minutes) < 60) return rtf.format(minutes, "minute");
    const hours = Math.round(seconds / 3600);
    if (Math.abs(hours) < 24) return rtf.format(hours, "hour");
    return rtf.format(Math.round(seconds / 86400), "day");
  };

  const absoluteTime = (iso, lang) =>
    iso ? new Date(iso).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" }) : "";

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

    static getStubConfig(hass) {
      return { title: langOf(hass).startsWith("de") ? "Benachrichtigungen" : "Notifications" };
    }

    setConfig(config) {
      if (!config) throw new Error("Invalid configuration");
      if (config.min_severity && !SEVERITIES.includes(config.min_severity)) {
        throw new Error(`min_severity must be one of: ${SEVERITIES.join(", ")}`);
      }
      if (config.layout && !["large", "compact"].includes(config.layout)) {
        throw new Error("layout must be large or compact");
      }
      if (config.read_action && !["auto", "acknowledge", "clear"].includes(config.read_action)) {
        throw new Error("read_action must be auto, acknowledge or clear");
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
      const per = this._config?.layout === "compact" ? 2 : 3;
      return 1 + Math.max(1, this._items?.length || 0) * per;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 6, min_rows: 2 };
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
          Number(x.acknowledged) - Number(y.acknowledged) ||
          RANK[y.severity] - RANK[x.severity] ||
          String(y.activatedAt).localeCompare(String(x.activatedAt))
      );
      cleared.sort((x, y) => String(y.clearedAt).localeCompare(String(x.clearedAt)));
      return { active, cleared: cleared.slice(0, CLEARED_LIMIT) };
    }

    _readService(severity) {
      const mode = this._config.read_action;
      if (mode === "auto") return severity === "info" ? "clear" : "acknowledge";
      return mode;
    }

    _render() {
      if (!this._config || !this._hass) return;
      const { active, cleared } = this._collect();
      const lang = langOf(this._hass);
      const signature = JSON.stringify([active, cleared, this._config, this._busy, lang]);
      if (signature === this._signature) return;
      this._signature = signature;
      this._items = [...active, ...cleared];

      const cfg = this._config;
      const t = pick(STRINGS, this._hass);
      const large = cfg.layout !== "compact";
      const hidden = cfg.hide_when_empty && !active.length && !cleared.length;
      this.style.display = hidden ? "none" : "";
      if (hidden) {
        this.shadowRoot.innerHTML = "";
        return;
      }

      const unread = active.filter((i) => !i.acknowledged);
      const top = [...active].sort((x, y) => RANK[y.severity] - RANK[x.severity])[0]?.severity;
      const readAll = cfg.show_actions && unread.length > 1
        ? `<button class="text-btn" data-action="read-all" ${this._busy ? "disabled" : ""}>
             <ha-icon icon="mdi:check-all"></ha-icon><span>${esc(large ? t.read_all : t.acknowledge)}</span>
           </button>`
        : "";
      // Without a title the header only appears when it has a button to show.
      const header = cfg.title || readAll
        ? `<div class="header${cfg.title ? "" : " bare"}">
             <div class="heading">
               ${cfg.title && large && cfg.icon ? `<ha-icon class="heading-icon" icon="${esc(cfg.icon)}"></ha-icon>` : ""}
               ${cfg.title ? `<span class="name">${esc(cfg.title)}</span>` : ""}
               ${cfg.title && active.length > (large ? 1 : 0) ? `<span class="count" style="--sev:${SEVERITY_COLOR[top]}">${active.length}</span>` : ""}
             </div>
             ${readAll}
           </div>`
        : "";

      const renderItem = (i) => (large ? this._renderLarge(i, lang, t) : this._renderCompact(i, lang, t));
      const body = active.length || cleared.length
        ? `<div class="list">
             ${active.map(renderItem).join("")}
             ${cleared.length ? `<div class="divider">${esc(t.recently_cleared)}</div>` : ""}
             ${cleared.map(renderItem).join("")}
           </div>`
        : `<div class="empty">
             <ha-icon icon="mdi:check-circle-outline"></ha-icon>
             <span>${esc(cfg.empty_message || t.empty)}</span>
           </div>`;

      this.shadowRoot.innerHTML = `<style>${STYLES}</style>
        <ha-card class="${large ? "large" : "compact"}">${header}${body}</ha-card>`;
    }

    _meta(item, lang, t) {
      const cfg = this._config;
      const parts = [];
      if (item.title && item.title !== item.name) parts.push(esc(item.name));
      if (cfg.show_time) {
        const when = item.active ? item.activatedAt : item.clearedAt;
        if (when) {
          const rel = relativeTime(when, lang, t);
          parts.push(`<time title="${esc(absoluteTime(when, lang))}">${esc(item.active ? rel : fill(t.cleared, { time: rel }))}</time>`);
        }
        if (item.active && item.autoClearAt) {
          parts.push(`<span title="${esc(absoluteTime(item.autoClearAt, lang))}">${esc(fill(t.clears, { time: relativeTime(item.autoClearAt, lang, t) }))}</span>`);
        }
      }
      if (item.active && item.acknowledged) {
        parts.push(`<span class="read"><ha-icon icon="mdi:check"></ha-icon>${esc(t.acknowledged)}</span>`);
      }
      return parts.join('<span class="dot">·</span>');
    }

    _renderLarge(item, lang, t) {
      const cfg = this._config;
      const heading = item.title || item.name;
      const meta = this._meta(item, lang, t);
      const classes = ["item", item.severity, item.active ? "active" : "cleared", item.acknowledged ? "acked" : "unacked"];
      const busy = this._busy === item.entityId || this._busy === "all";
      const button = cfg.show_actions && item.active && !item.acknowledged
        ? `<button class="tile-btn" data-action="read" data-entity="${esc(item.entityId)}" data-severity="${item.severity}" ${busy ? "disabled" : ""}>
             <ha-icon icon="${esc(cfg.read_icon || DEFAULTS.read_icon)}"></ha-icon><span>${esc(t.read)}</span>
           </button>`
        : "";
      return `<div class="${classes.join(" ")}" style="--sev:${SEVERITY_COLOR[item.severity]}">
        <div class="hero" data-action="more-info" data-entity="${esc(item.entityId)}" tabindex="0" role="button"
             aria-label="${esc(t[item.severity])}: ${esc(heading)}">
          <div class="tile-icon"><ha-icon icon="${esc(item.icon || "mdi:bell")}"></ha-icon></div>
          <div class="text">
            <div class="title">${esc(heading)}</div>
            ${item.message ? `<div class="message">${esc(item.message)}</div>` : ""}
            ${meta ? `<div class="meta">${meta}</div>` : ""}
          </div>
        </div>
        ${button}
      </div>`;
    }

    _renderCompact(item, lang, t) {
      const cfg = this._config;
      const heading = item.title || item.name;
      const meta = this._meta(item, lang, t);
      const classes = ["row", item.severity, item.active ? "active" : "cleared", item.acknowledged ? "acked" : "unacked"];
      const busy = this._busy === item.entityId || this._busy === "all";
      const actions = cfg.show_actions && item.active
        ? `<div class="actions">
             ${item.acknowledged
               ? ""
               : `<button class="icon-btn" data-action="acknowledge" data-entity="${esc(item.entityId)}" title="${esc(t.acknowledge)}" aria-label="${esc(t.acknowledge)}: ${esc(heading)}" ${busy ? "disabled" : ""}><ha-icon icon="mdi:check"></ha-icon></button>`}
             <button class="icon-btn" data-action="clear" data-entity="${esc(item.entityId)}" title="${esc(t.clear)}" aria-label="${esc(t.clear)}: ${esc(heading)}" ${busy ? "disabled" : ""}><ha-icon icon="mdi:close"></ha-icon></button>
           </div>`
        : "";
      return `<div class="${classes.join(" ")}" style="--sev:${SEVERITY_COLOR[item.severity]}"
                  data-action="more-info" data-entity="${esc(item.entityId)}" tabindex="0" role="button"
                  aria-label="${esc(t[item.severity])}: ${esc(heading)}">
        <div class="badge"><ha-icon icon="${esc(item.icon || "mdi:bell")}"></ha-icon></div>
        <div class="content">
          <div class="title-row">
            <span class="title">${esc(heading)}</span>
            <span class="sev">${esc(t[item.severity])}</span>
          </div>
          ${item.message ? `<div class="message">${esc(item.message)}</div>` : ""}
          ${meta ? `<div class="meta">${meta}</div>` : ""}
        </div>
        ${actions}
      </div>`;
    }

    _onKeyDown(ev) {
      if ((ev.key === "Enter" || ev.key === " ") && ev.target.matches?.('[data-action="more-info"]')) {
        ev.preventDefault();
        this._handle(ev.target);
      }
    }

    _onClick(ev) {
      const target = ev.composedPath().find((el) => el instanceof HTMLElement && el.dataset?.action);
      if (target && !target.disabled) this._handle(target);
    }

    async _handle(target) {
      const { action, entity, severity } = target.dataset;
      if (action === "more-info") {
        this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: entity }, bubbles: true, composed: true }));
        return;
      }
      // service -> entity ids
      const calls = {};
      const add = (service, entityId) => (calls[service] ||= []).push(entityId);
      if (action === "read-all") {
        const large = this._config.layout !== "compact";
        for (const i of this._collect().active.filter((i) => !i.acknowledged)) {
          add(large ? this._readService(i.severity) : "acknowledge", i.entityId);
        }
      } else if (action === "read") {
        add(this._readService(severity), entity);
      } else if (action === "acknowledge" || action === "clear") {
        add(action, entity);
      } else {
        return;
      }
      this._busy = action === "read-all" ? "all" : entity;
      this._render();
      try {
        await Promise.all(
          Object.entries(calls).map(([service, ids]) => this._hass.callService(DOMAIN, service, { entity_id: ids }))
        );
      } catch (err) {
        const t = pick(STRINGS, this._hass);
        this.dispatchEvent(
          new CustomEvent("hass-notification", {
            detail: { message: fill(t.error, { error: err?.message || String(err) }) },
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
    .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .heading { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .count { min-width: 22px; height: 22px; padding: 0 7px; box-sizing: border-box; border-radius: 11px; background: var(--sev); color: #fff;
             font-size: 0.8rem; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; }
    .text-btn { display: inline-flex; align-items: center; gap: 4px; border: none; background: transparent; cursor: pointer; border-radius: 18px;
                padding: 6px 10px; color: var(--primary-color); font: inherit; font-size: 0.875rem; font-weight: 500; --mdc-icon-size: 18px; }
    .text-btn:hover { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
    .text-btn[disabled] { opacity: 0.5; cursor: progress; }
    .dot { opacity: 0.6; }
    .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: 0.8rem; color: var(--secondary-text-color); }
    .read { display: inline-flex; align-items: center; gap: 2px; color: var(--success-color, #43a047); --mdc-icon-size: 14px; }
    .divider { padding: 4px 4px 0; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--secondary-text-color); }
    .empty { display: flex; align-items: center; gap: 12px; padding: 16px; color: var(--secondary-text-color); --mdc-icon-size: 28px; }
    .empty ha-icon { color: var(--success-color, #43a047); }
    [role="button"] { cursor: pointer; outline: none; }
    @keyframes pulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--sev) 55%, transparent); } 70%, 100% { box-shadow: 0 0 0 12px transparent; } }

    /* ---- large layout: sits directly on the dashboard like a heading + tiles ---- */
    ha-card.large { background: none; border: none; box-shadow: none; overflow: visible; }
    .large .header { padding: 4px 4px 12px; }
    .large .header.bare { justify-content: flex-end; padding-bottom: 4px; }
    .large .heading { gap: 12px; color: var(--secondary-text-color); --mdc-icon-size: 24px; }
    .large .name { font-size: var(--ha-font-size-l, 1.125rem); font-weight: 400; color: var(--secondary-text-color); }
    .large .list { display: flex; flex-direction: column; gap: 24px; padding-bottom: 8px; }
    .item { display: flex; flex-direction: column; gap: 16px; }
    .hero { display: flex; align-items: center; gap: 24px; padding: 0 16px; border-radius: 20px; }
    .hero:focus-visible { box-shadow: 0 0 0 2px var(--sev); }
    .tile-icon { flex: none; width: 80px; height: 80px; border-radius: 20px; display: flex; align-items: center; justify-content: center;
                 background: color-mix(in srgb, var(--sev) 35%, #fff); color: rgba(0, 0, 0, 0.87); --mdc-icon-size: 32px; }
    .item.critical.unacked .tile-icon { animation: pulse 2s ease-out infinite; }
    .text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
    .large .title { font-size: var(--ha-font-size-2xl, 1.5rem); font-weight: 500; line-height: 1.25; color: var(--primary-text-color); overflow-wrap: anywhere; }
    .large .message { font-size: var(--ha-font-size-l, 1.05rem); line-height: 1.4; color: var(--primary-text-color); white-space: pre-wrap; overflow-wrap: anywhere; }
    .item.acked .tile-icon { background: transparent; color: var(--sev); box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--sev) 60%, transparent); }
    .item.acked .title, .item.acked .message { color: var(--secondary-text-color); }
    .item.cleared { opacity: 0.6; }
    .item.cleared .tile-icon { background: var(--disabled-color, #9e9e9e); color: var(--card-background-color, #fff); box-shadow: none; }
    .tile-btn { display: flex; align-items: center; gap: 24px; width: 100%; min-height: 56px; padding: 0 20px; box-sizing: border-box; cursor: pointer;
                font: inherit; font-size: var(--ha-font-size-m, 1rem); font-weight: 500; color: var(--primary-text-color); text-align: start;
                background: var(--ha-card-background, var(--card-background-color, #fff));
                border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
                border-radius: var(--ha-card-border-radius, 12px); box-shadow: var(--ha-card-box-shadow, none);
                --mdc-icon-size: 24px; transition: background-color 150ms ease; }
    .tile-btn ha-icon { color: var(--secondary-text-color); }
    .tile-btn:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, var(--ha-card-background, var(--card-background-color, #fff))); }
    .tile-btn:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .tile-btn[disabled] { opacity: 0.5; cursor: progress; }
    .large .empty { padding: 4px 16px; }

    /* ---- compact layout: list inside a regular card ---- */
    .compact .header { padding: 12px 16px 4px; }
    .compact .header.bare { justify-content: flex-end; padding: 8px 8px 0; }
    .compact .name { font-size: var(--ha-card-header-font-size, 1.25rem); font-weight: 500; color: var(--ha-card-header-color, var(--primary-text-color)); }
    .compact .list { padding: 8px; display: flex; flex-direction: column; gap: 6px; }
    .row { position: relative; display: flex; align-items: flex-start; gap: 12px; padding: 10px 10px 10px 12px; border-radius: 12px;
           background: color-mix(in srgb, var(--sev) 10%, var(--card-background-color, transparent)); transition: background-color 150ms ease; }
    .row::before { content: ""; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 3px; background: var(--sev); }
    .row:hover { background: color-mix(in srgb, var(--sev) 16%, var(--card-background-color, transparent)); }
    .row:focus-visible { box-shadow: 0 0 0 2px var(--sev); }
    .row.acked { background: color-mix(in srgb, var(--sev) 4%, var(--card-background-color, transparent)); }
    .row.acked .badge { background: transparent; color: var(--sev); box-shadow: inset 0 0 0 1.5px var(--sev); }
    .row.acked .title, .row.acked .message { color: var(--secondary-text-color); }
    .row.cleared { background: transparent; opacity: 0.65; }
    .row.cleared::before, .row.cleared .badge { background: var(--disabled-color, #9e9e9e); }
    .badge { flex: none; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
             background: var(--sev); color: #fff; --mdc-icon-size: 20px; }
    .row.critical.unacked.active .badge { animation: pulse 2s ease-out infinite; }
    .content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
    .title-row { display: flex; align-items: baseline; gap: 8px; }
    .compact .title { font-weight: 500; color: var(--primary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sev { flex: none; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sev); }
    .row.cleared .sev { color: var(--secondary-text-color); }
    .compact .message { color: var(--primary-text-color); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.4; }
    .actions { flex: none; display: flex; align-items: center; gap: 2px; }
    .icon-btn { width: 36px; height: 36px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
                --mdc-icon-size: 20px; color: var(--secondary-text-color); border: none; background: transparent; cursor: pointer; padding: 0; }
    .icon-btn:hover { background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); color: var(--primary-text-color); }
    .icon-btn:focus-visible { outline: 2px solid var(--primary-color); }
    .icon-btn[disabled] { opacity: 0.4; cursor: progress; }

    @media (max-width: 450px) {
      .hero { gap: 16px; padding: 0 8px; }
      .tile-icon { width: 64px; height: 64px; border-radius: 16px; --mdc-icon-size: 28px; }
      .large .title { font-size: var(--ha-font-size-xl, 1.25rem); }
    }
    @media (prefers-reduced-motion: reduce) {
      .item.critical.unacked .tile-icon, .row.critical.unacked.active .badge { animation: none; }
    }
  `;

  const editorSchema = (l, t) => [
    {
      name: "layout",
      selector: { select: { mode: "box", options: [{ value: "large", label: l.layout_large }, { value: "compact", label: l.layout_compact }] } },
    },
    {
      type: "grid",
      name: "",
      schema: [
        { name: "title", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
      ],
    },
    {
      name: "entities",
      selector: { entity: { multiple: true, filter: { integration: DOMAIN, domain: "binary_sensor" } } },
    },
    {
      type: "grid",
      name: "",
      schema: [
        {
          name: "min_severity",
          selector: { select: { mode: "dropdown", options: SEVERITIES.map((value) => ({ value, label: t[value] })) } },
        },
        {
          name: "read_action",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "auto", label: l.read_auto },
                { value: "acknowledge", label: l.read_acknowledge },
                { value: "clear", label: l.read_clear },
              ],
            },
          },
        },
      ],
    },
    { name: "read_icon", selector: { icon: {} } },
    {
      type: "grid",
      name: "",
      schema: [
        { name: "show_acknowledged", selector: { boolean: {} } },
        { name: "show_cleared", selector: { boolean: {} } },
        { name: "show_actions", selector: { boolean: {} } },
        { name: "show_time", selector: { boolean: {} } },
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
      const labels = pick(EDITOR_STRINGS, this._hass);
      if (!this._form) {
        this._form = document.createElement("ha-form");
        this._form.computeLabel = (s) => labels[s.name] ?? s.name;
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
      this._form.schema = editorSchema(labels, pick(STRINGS, this._hass));
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
      description: "Active notifications with severity, mark as read and clear.",
      preview: true,
      documentationURL: "https://github.com/poesterlin/ha-clearable-notifications",
    });
  }

  console.info(`%c CLEARABLE-NOTIFICATIONS-CARD %c ${VERSION} `, "color:#fff;background:#9333ea;font-weight:600", "color:#9333ea");
})();
