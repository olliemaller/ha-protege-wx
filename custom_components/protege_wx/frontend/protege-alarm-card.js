/*
 * Protege WX alarm card, by Arcnode IT.
 *
 *   type: custom:protege-alarm-card
 *   entity: alarm_control_panel.alarm
 *   # optional:
 *   name: House
 *   show_keypad: true      # when the alarm needs a code
 *   show_activity: true    # recent arming / disarming / doors
 *   activity_count: 5
 *
 * Finds the area's open-zones, delay and alarm-cause sensors on the same
 * device by itself. Ships with the integration; nothing to add to resources.
 */

const VERSION = "0.3.1";

const FEATURE = { HOME: 1, AWAY: 2, NIGHT: 4, VACATION: 32 };

const STATE_LABEL = {
  disarmed: "Disarmed",
  armed_away: "Armed away",
  armed_home: "Armed home",
  armed_night: "Armed night",
  armed_vacation: "Armed holidays",
  armed_custom_bypass: "Armed",
  arming: "Arming",
  pending: "Entry delay",
  disarming: "Disarming",
  triggered: "Alarm",
  unavailable: "Offline",
  unknown: "Unknown",
};

const MODES = [
  { key: "away", label: "Away", service: "alarm_arm_away", feature: FEATURE.AWAY },
  { key: "home", label: "Home", service: "alarm_arm_home", feature: FEATURE.HOME },
  { key: "night", label: "Night", service: "alarm_arm_night", feature: FEATURE.NIGHT },
  { key: "vacation", label: "Holidays", service: "alarm_arm_vacation", feature: FEATURE.VACATION },
];

// The Arcnode arcs, as the brand kit draws them.
const ARCS = `
  <svg class="mark" viewBox="0 0 100 100" aria-hidden="true">
    <path d="M12 78 C20 30, 60 8, 88 22" />
    <path d="M28 88 C34 52, 62 34, 82 40" />
    <path d="M44 92 C48 68, 64 54, 78 54" />
    <line x1="18" y1="74" x2="43" y2="43" class="link" />
    <line x1="57" y1="34" x2="82" y2="25" class="link" />
    <circle cx="12" cy="78" r="4" /><circle cx="50" cy="38" r="4" /><circle cx="88" cy="22" r="4" />
  </svg>`;

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class ProtegeAlarmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._code = "";
    this._error = "";
    this._busy = false;
    this._activity = [];
    this._activityLoaded = 0;
    this._tick = null;
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass?.states || {}).find(
      (id) => id.startsWith("alarm_control_panel.") && hass.entities?.[id]?.platform === "protege_wx"
    );
    return { entity: entity || "alarm_control_panel.alarm" };
  }

  setConfig(config) {
    if (!config?.entity || !config.entity.startsWith("alarm_control_panel.")) {
      throw new Error("Set entity: to a Protege alarm_control_panel");
    }
    this._config = { show_keypad: true, show_activity: true, activity_count: 5, ...config };
    if (this._hass) this._render();
  }

  set hass(hass) {
    const old = this._hass;
    this._hass = hass;
    if (!this._config) return; // Home Assistant may set hass before the config
    const watched = this._watched();
    if (!old || watched.some((id) => old.states[id] !== hass.states[id]) || old.themes?.darkMode !== hass.themes?.darkMode) {
      this._render();
      if (this._config.show_activity && Date.now() - this._activityLoaded > 1500) this._loadActivity();
    }
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  connectedCallback() {
    this._tick = setInterval(() => this._updateCountdown(), 1000);
  }

  disconnectedCallback() {
    clearInterval(this._tick);
  }

  // ── related entities ─────────────────────────────────────────────────────

  _related(translationKey, domain = "sensor") {
    const hass = this._hass;
    const alarm = this._config.entity;
    const device = hass.entities?.[alarm]?.device_id;
    if (device) {
      const match = Object.values(hass.entities).find(
        (e) => e.device_id === device && e.platform === "protege_wx" && e.translation_key === translationKey
      );
      if (match) return match.entity_id;
    }
    const guess = `${domain}.${alarm.split(".")[1]}_${translationKey}`;
    return hass.states[guess] ? guess : null;
  }

  _watched() {
    if (!this._hass || !this._config) return [];
    return [
      this._config.entity,
      this._related("open_zones"),
      this._related("delay_ends"),
      this._related("alarm_cause"),
      this._related("area_events", "event"),
    ].filter(Boolean);
  }

  // ── actions ──────────────────────────────────────────────────────────────

  async _call(service) {
    const state = this._hass.states[this._config.entity];
    const data = { entity_id: this._config.entity };
    const needsCode =
      state.attributes.code_format &&
      (service === "alarm_disarm" || state.attributes.code_arm_required !== false);
    if (needsCode) {
      if (!this._code) {
        this._error = "Enter your PIN first";
        this._render();
        return;
      }
      data.code = this._code;
    }
    this._busy = true;
    this._error = "";
    this._render();
    try {
      await this._hass.callService("alarm_control_panel", service, data);
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._code = "";
    this._busy = false;
    this._render();
  }

  async _loadActivity() {
    this._activityLoaded = Date.now();
    const ids = [this._config.entity, this._related("area_events", "event")].filter(Boolean);
    try {
      const start = new Date(Date.now() - 3 * 24 * 3600 * 1000).toISOString();
      const entries = await this._hass.callWS({ type: "logbook/get_events", start_time: start, entity_ids: ids });
      this._activity = entries
        .filter((e) => e.message && e.entity_id !== this._config.entity)
        .slice(-this._config.activity_count)
        .reverse();
      if (!this._activity.length) {
        this._activity = entries.filter((e) => e.state).slice(-this._config.activity_count).reverse();
      }
    } catch (_err) {
      this._activity = [];
    }
    this._render();
  }

  // ── countdown ────────────────────────────────────────────────────────────

  _delay() {
    const id = this._related("delay_ends");
    const state = id && this._hass.states[id];
    if (!state || !state.state || ["unknown", "unavailable"].includes(state.state)) return null;
    const ends = new Date(state.state).getTime();
    const phase = state.attributes.phase;
    const total = (phase === "entry" ? state.attributes.entry_delay : state.attributes.exit_delay) || 60;
    return { ends, phase, total };
  }

  _updateCountdown() {
    const el = this.shadowRoot?.querySelector(".countdown");
    if (!el || !this._hass) return;
    const delay = this._delay();
    if (!delay) return;
    const left = Math.max(0, Math.round((delay.ends - Date.now()) / 1000));
    el.querySelector(".secs").textContent = left;
    el.querySelector(".bar span").style.width = `${Math.min(100, (left / delay.total) * 100)}%`;
  }

  // ── render ───────────────────────────────────────────────────────────────

  _render() {
    if (!this._config) return;
    const hass = this._hass;
    if (!hass) {
      this.shadowRoot.innerHTML = "";
      return;
    }
    const state = hass.states[this._config.entity];
    if (!state) {
      this.shadowRoot.innerHTML = `<ha-card><div class="pad">Entity not found: ${esc(this._config.entity)}</div></ha-card>`;
      return;
    }
    const dark = !!hass.themes?.darkMode;
    const value = state.state;
    const armed = value.startsWith("armed_") || value === "arming";
    const tone =
      value === "triggered" ? "alarm" : value === "pending" ? "warn" : armed ? "armed" : value === "disarmed" ? "ok" : "off";
    const name = this._config.name || state.attributes.friendly_name || "Alarm";
    const features = state.attributes.supported_features || 0;
    const needsCode = !!state.attributes.code_format;

    const zonesId = this._related("open_zones");
    const zones = zonesId ? hass.states[zonesId] : null;
    const openZones = zones?.attributes?.zones || [];
    const causeId = this._related("alarm_cause");
    const cause = causeId ? hass.states[causeId]?.state : null;
    const delay = this._delay();

    const modeButtons = MODES.filter((m) => features & m.feature)
      .map(
        (m) => `<button class="mode" data-service="${m.service}" ${this._busy || value === "unavailable" ? "disabled" : ""}>
          ${esc(m.label)}</button>`
      )
      .join("");

    let status = "";
    if (value === "triggered" && cause && cause !== "none") {
      status = `<div class="notice alarm"><span class="label">Set off by</span><b>${esc(cause)}</b></div>`;
    } else if (value === "disarmed" && zones) {
      status = openZones.length
        ? `<div class="notice warn"><span class="label">Open</span>${openZones.map((z) => `<span class="chip">${esc(z)}</span>`).join("")}</div>`
        : `<div class="notice ok"><span class="label">Ready</span>All zones closed</div>`;
    }

    const countdown = delay
      ? `<div class="countdown"><div class="row"><span class="label">${delay.phase === "entry" ? "Entry delay" : "Exit delay"}</span>
          <span class="secs">${Math.max(0, Math.round((delay.ends - Date.now()) / 1000))}</span><span class="unit">s</span></div>
          <div class="bar"><span></span></div></div>`
      : "";

    const keypad =
      needsCode && this._config.show_keypad
        ? `<div class="keypad">
            <div class="display">${this._code ? "•".repeat(this._code.length) : '<span class="hint">PIN</span>'}</div>
            ${["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"]
              .map((k) => `<button class="key" data-key="${k}">${k === "clear" ? "C" : k === "back" ? "⌫" : k}</button>`)
              .join("")}
          </div>`
        : "";

    const activity =
      this._config.show_activity && this._activity.length
        ? `<div class="activity"><div class="label">Recent</div>${this._activity
            .map((e) => {
              const when = new Date(e.when * 1000);
              const time = when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
              const text = e.message ? `${e.name || ""} ${e.message}` : `${e.name || ""} ${STATE_LABEL[e.state] || e.state}`;
              return `<div class="entry"><span class="time">${esc(time)}</span><span>${esc(text.trim())}</span></div>`;
            })
            .join("")}</div>`
        : "";

    const changedBy = state.attributes.changed_by ? `by ${esc(state.attributes.changed_by)}` : "";

    this.shadowRoot.innerHTML = `
      <style>${this._css(dark)}</style>
      <ha-card class="${tone}">
        <div class="head">
          ${ARCS}
          <div class="title">
            <div class="label">Protege WX</div>
            <div class="name">${esc(name)}</div>
          </div>
          <div class="state">
            <div class="value">${esc(STATE_LABEL[value] || value)}</div>
            <div class="by">${changedBy}</div>
          </div>
        </div>
        ${countdown}
        ${status}
        <div class="body">
          ${keypad}
          <div class="actions">
            ${armed || value === "triggered" || value === "pending"
              ? `<button class="mode disarm" data-service="alarm_disarm" ${this._busy ? "disabled" : ""}>Disarm</button>`
              : modeButtons}
          </div>
        </div>
        ${this._error ? `<div class="error">${esc(this._error)}</div>` : ""}
        ${activity}
        <div class="foot"><span class="label">by Arcnode IT</span></div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll("button[data-service]").forEach((b) =>
      b.addEventListener("click", () => this._call(b.dataset.service))
    );
    this.shadowRoot.querySelectorAll("button[data-key]").forEach((b) =>
      b.addEventListener("click", () => {
        const k = b.dataset.key;
        if (k === "clear") this._code = "";
        else if (k === "back") this._code = this._code.slice(0, -1);
        else if (this._code.length < 10) this._code += k;
        this._error = "";
        this._render();
      })
    );
    this._updateCountdown();
  }

  _css(dark) {
    const accent = dark ? "#378ADD" : "#185FA5";
    const navy = "#042C53";
    return `
      :host { --pw-accent: ${accent}; --pw-navy: ${navy}; --pw-soft: ${dark ? "rgba(55,138,221,.14)" : "#E6F1FB"};
        --pw-line: ${dark ? "rgba(181,212,244,.16)" : "#B5D4F4"}; --pw-text: var(--primary-text-color);
        --pw-muted: var(--secondary-text-color); --pw-ok: #2E7D4F; --pw-warn: #B7791F; --pw-alarm: #C62828; }
      ha-card { overflow: hidden; font-family: Inter, var(--ha-font-family-body, system-ui), sans-serif; color: var(--pw-text); }
      .label { font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px;
        letter-spacing: .08em; text-transform: uppercase; color: var(--pw-muted); }
      .head { display: flex; align-items: center; gap: 12px; padding: 16px; border-bottom: 1px solid var(--pw-line); }
      .mark { width: 36px; height: 36px; flex: none; }
      .mark path { fill: none; stroke: var(--pw-accent); stroke-width: 6; stroke-linecap: round; }
      .mark .link { stroke: var(--pw-accent); stroke-width: 3; opacity: .35; }
      .mark circle { fill: var(--pw-accent); }
      .title { flex: 1; min-width: 0; }
      .name { font-size: 18px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .state { text-align: right; }
      .state .value { font-size: 16px; font-weight: 600; }
      .state .by { font-size: 12px; color: var(--pw-muted); }
      .armed .state .value { color: var(--pw-accent); }
      .ok .state .value { color: var(--pw-ok); }
      .warn .state .value { color: var(--pw-warn); }
      .alarm .state .value { color: var(--pw-alarm); }
      .alarm .head { background: ${dark ? "rgba(198,40,40,.18)" : "#FDECEC"}; }
      .countdown { padding: 12px 16px; border-bottom: 1px solid var(--pw-line); }
      .countdown .row { display: flex; align-items: baseline; gap: 6px; }
      .countdown .label { flex: 1; }
      .countdown .secs { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 28px; font-weight: 600; color: var(--pw-accent); }
      .countdown .unit { color: var(--pw-muted); }
      .bar { height: 4px; background: var(--pw-soft); border-radius: 2px; margin-top: 8px; overflow: hidden; }
      .bar span { display: block; height: 100%; background: var(--pw-accent); transition: width 1s linear; }
      .notice { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--pw-line); font-size: 14px; }
      .notice.ok .label { color: var(--pw-ok); }
      .notice.warn .label { color: var(--pw-warn); }
      .notice.alarm .label { color: var(--pw-alarm); }
      .chip { padding: 2px 8px; border-radius: 10px; background: var(--pw-soft); font-size: 13px; }
      .body { padding: 16px; display: grid; gap: 14px; }
      .keypad { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; max-width: 280px; margin: 0 auto; width: 100%; }
      .display { grid-column: 1 / -1; height: 40px; display: flex; align-items: center; justify-content: center;
        border: 1px solid var(--pw-line); border-radius: 8px; font-size: 22px; letter-spacing: .3em; }
      .display .hint { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12px; letter-spacing: .08em; color: var(--pw-muted); }
      button { font: inherit; cursor: pointer; border-radius: 8px; border: 1px solid var(--pw-line); background: transparent; color: var(--pw-text); }
      button:disabled { opacity: .5; cursor: default; }
      .key { height: 44px; font-size: 18px; }
      .key:active { background: var(--pw-soft); }
      .actions { display: flex; flex-wrap: wrap; gap: 8px; }
      .mode { flex: 1 1 90px; height: 44px; font-weight: 600; border-color: var(--pw-accent); color: var(--pw-accent); }
      .mode:hover:not(:disabled) { background: var(--pw-soft); }
      .mode.disarm { background: var(--pw-accent); color: #fff; }
      .error { margin: 0 16px 12px; padding: 8px 12px; border-radius: 8px; background: ${dark ? "rgba(198,40,40,.18)" : "#FDECEC"}; color: var(--pw-alarm); font-size: 13px; }
      .activity { padding: 12px 16px; border-top: 1px solid var(--pw-line); display: grid; gap: 6px; font-size: 13px; }
      .entry { display: flex; gap: 10px; }
      .entry .time { font-family: "JetBrains Mono", ui-monospace, monospace; color: var(--pw-muted); min-width: 64px; }
      .foot { padding: 8px 16px 12px; text-align: right; }
      .pad { padding: 16px; }`;
  }
}

// Loaded early (as an "extra module"), possibly before Home Assistant has set up
// its own custom-element registry. Defining the card then would put it in a
// registry the dashboard never looks in, so wait until Home Assistant's own
// elements are defined, then define the card there.
function defineCard() {
  if (customElements.get("protege-alarm-card")) return;
  customElements.define("protege-alarm-card", ProtegeAlarmCard);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "protege-alarm-card")) {
    window.customCards.push({
      type: "protege-alarm-card",
      name: "Protege WX alarm",
      description: "Arm, disarm, countdown, open zones and recent activity for a Protege WX area. By Arcnode IT.",
      preview: true,
    });
  }
  console.info(`%c PROTEGE-ALARM-CARD %c ${VERSION} `, "background:#042C53;color:#fff", "background:#185FA5;color:#fff");
}

if (customElements.get("ha-card")) {
  defineCard();
} else {
  let tries = 0;
  const wait = setInterval(() => {
    tries += 1;
    if (customElements.get("ha-card") || tries > 600) {
      clearInterval(wait);
      defineCard();
    }
  }, 100);
}
