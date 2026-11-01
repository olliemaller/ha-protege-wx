/*
 * Protege WX alarm card.
 *
 *   type: custom:protege-alarm-card
 *   entity: alarm_control_panel.alarm
 *   # optional:
 *   name: House
 *   show_keypad: true      # when the alarm needs a code
 *   show_activity: true    # recent arming / disarming / doors
 *   activity_count: 5
 *   show_arm_when_ready: true  # "Arm when ready" while zones are open
 *
 * Every option can also be set in the dashboard's visual card editor.
 * Finds the area's open-zones, delay and alarm-cause sensors on the same
 * device by itself. Ships with the integration; nothing to add to resources.
 */

const VERSION = "0.4.0";

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

const MARK = `
  <svg class="mark" viewBox="0 0 256 256" aria-hidden="true">
    <rect x="8" y="8" width="240" height="240" rx="56" fill="#042C53"/>
    <path d="M128 36 L200 64 V124 C200 170 170 204 128 222 C86 204 56 170 56 124 V64 Z" fill="#FFFFFF"/>
    <g fill="#042C53">
      <circle cx="100" cy="90" r="10"/><circle cx="128" cy="90" r="10"/><circle cx="156" cy="90" r="10"/>
      <circle cx="100" cy="118" r="10"/><circle cx="128" cy="118" r="10"/><circle cx="156" cy="118" r="10"/>
      <circle cx="100" cy="146" r="10"/><circle cx="128" cy="146" r="10"/><circle cx="156" cy="146" r="10"/>
    </g>
    <circle cx="128" cy="180" r="12" fill="#378ADD"/>
  </svg>`;

// A status node: the mark's ringed dot, in the state's colour (beside words).
const NODE = `<svg class="node" viewBox="0 0 20 20" aria-hidden="true">
  <circle cx="10" cy="10" r="9" class="ring"/><circle cx="10" cy="10" r="4.2" class="middle"/><circle cx="10" cy="10" r="1.8" class="core"/></svg>`;

const WAIT_MODE_LABEL = { away: "away", home: "home", night: "night" };

// The visual editor (Home Assistant 2024.11+ builds it from this schema).
const EDITOR_SCHEMA = [
  { name: "entity", required: true, selector: { entity: { filter: { domain: "alarm_control_panel", integration: "protege_wx" } } } },
  { name: "name", selector: { text: {} } },
  {
    type: "grid",
    name: "",
    schema: [
      { name: "show_keypad", selector: { boolean: {} } },
      { name: "show_arm_when_ready", selector: { boolean: {} } },
      { name: "show_activity", selector: { boolean: {} } },
      { name: "activity_count", selector: { number: { min: 1, max: 10, mode: "box" } } },
    ],
  },
];

const EDITOR_LABELS = {
  entity: "Alarm area",
  name: "Name (optional)",
  show_keypad: "Show the keypad when a PIN is needed",
  show_arm_when_ready: "Offer \"Arm when ready\" while zones are open",
  show_activity: "Show recent activity",
  activity_count: "Activity lines",
};

const EDITOR_HELPERS = {
  name: "Leave empty to use the area's name.",
  show_keypad: "Only appears once users with PINs are set up in the integration.",
};

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

  static getConfigForm() {
    return {
      schema: EDITOR_SCHEMA,
      computeLabel: (field) => EDITOR_LABELS[field.name],
      computeHelper: (field) => EDITOR_HELPERS[field.name],
    };
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
    this._config = {
      show_keypad: true,
      show_activity: true,
      show_arm_when_ready: true,
      activity_count: 5,
      ...config,
    };
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
      this._related("arm_when_ready", "switch"),
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

  async _wait(on) {
    const id = this._related("arm_when_ready", "switch");
    if (!id) return;
    this._busy = true;
    this._error = "";
    this._render();
    try {
      await this._hass.callService("switch", on ? "turn_on" : "turn_off", { entity_id: id });
    } catch (err) {
      this._error = err?.message || String(err);
    }
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
        // No plain-English lines yet: fall back to real alarm states, skipping
        // restarts (unknown / unavailable) and repeats.
        const states = [];
        for (const e of entries) {
          if (!e.state || ["unknown", "unavailable"].includes(e.state)) continue;
          if (states.length && states[states.length - 1].state === e.state) continue;
          states.push(e);
        }
        this._activity = states.slice(-this._config.activity_count).reverse();
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

    const waitId = this._config.show_arm_when_ready ? this._related("arm_when_ready", "switch") : null;
    const wait = waitId ? hass.states[waitId] : null;
    const waiting = wait?.state === "on";
    const chips = (list) => list.map((z) => `<span class="chip">${esc(z)}</span>`).join("");

    let status = "";
    if (value === "triggered" && cause && cause !== "none") {
      status = `<div class="notice alarm"><span class="label">Set off by</span><b>${esc(cause)}</b></div>`;
    } else if (value === "disarmed" && waiting) {
      const mode = WAIT_MODE_LABEL[wait.attributes.mode] || "away";
      const still = wait.attributes.open_zones || openZones;
      const until = wait.attributes.until ? new Date(wait.attributes.until) : null;
      const by = until ? ` until ${esc(until.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}` : "";
      status = `<div class="notice info"><span class="label">Arming ${esc(mode)} when ready</span>
        <span class="muted">Waiting${by}${still.length ? ". Still open:" : ""}</span>${chips(still)}</div>`;
    } else if (value === "disarmed" && zones) {
      status = openZones.length
        ? `<div class="notice warn"><span class="label">Open</span>${chips(openZones)}</div>`
        : `<div class="notice ok"><span class="label">Ready</span>All zones closed</div>`;
    }

    let waitButton = "";
    if (wait && value === "disarmed" && waiting) {
      waitButton = `<button class="mode secondary" data-wait="off" ${this._busy ? "disabled" : ""}>Stop waiting</button>`;
    } else if (wait && value === "disarmed" && openZones.length) {
      waitButton = `<button class="mode secondary" data-wait="on" ${this._busy ? "disabled" : ""}>Arm when ready</button>`;
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
          ${MARK}
          <div class="title">
            <div class="label">Protege WX</div>
            <div class="name">${esc(name)}</div>
          </div>
          <div class="state">
            <div class="value">${NODE}${esc(STATE_LABEL[value] || value)}</div>
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
              : modeButtons + waitButton}
          </div>
        </div>
        ${this._error ? `<div class="error">${esc(this._error)}</div>` : ""}
        ${activity}
      </ha-card>`;

    this.shadowRoot.querySelectorAll("button[data-service]").forEach((b) =>
      b.addEventListener("click", () => this._call(b.dataset.service))
    );
    this.shadowRoot.querySelectorAll("button[data-wait]").forEach((b) =>
      b.addEventListener("click", () => this._wait(b.dataset.wait === "on"))
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
    const t = dark
      ? { accent: "#378ADD", soft: "rgba(55,138,221,0.10)", softLine: "rgba(133,183,235,0.35)", line: "rgba(255,255,255,0.1)",
          ok: "#3DD68C", okSoft: "rgba(61,214,140,0.14)", warn: "#F5B544", warnSoft: "rgba(245,181,68,0.14)",
          danger: "#FF6B5E", dangerText: "#FF6B5E", dangerSoft: "rgba(255,107,94,0.14)", focus: "#85B7EB" }
      : { accent: "#185FA5", soft: "#E6F1FB", softLine: "#B5D4F4", line: "#E5E7EB",
          ok: "#1B6B3A", okSoft: "#E3F5EA", warn: "#8F5A00", warnSoft: "#FBEFD6",
          danger: "#C0392B", dangerText: "#9B2C20", dangerSoft: "#FBE4E1", focus: "#378ADD" };
    return `
      :host { --pw-accent: ${t.accent}; --pw-fill: #185FA5; --pw-soft: ${t.soft}; --pw-soft-line: ${t.softLine};
        --pw-line: ${t.line}; --pw-text: var(--primary-text-color); --pw-muted: var(--secondary-text-color);
        --pw-ok: ${t.ok}; --pw-ok-soft: ${t.okSoft}; --pw-warn: ${t.warn}; --pw-warn-soft: ${t.warnSoft};
        --pw-alarm: ${t.danger}; --pw-alarm-text: ${t.dangerText}; --pw-alarm-soft: ${t.dangerSoft}; --pw-focus: ${t.focus};
        --pw-ease: cubic-bezier(.25,.1,.25,1); }
      ha-card { overflow: hidden; font-family: Inter, var(--ha-font-family-body, system-ui), sans-serif; color: var(--pw-text); }
      .label { font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-weight: 500;
        letter-spacing: .18em; text-transform: uppercase; color: var(--pw-accent); }
      .muted { color: var(--pw-muted); }
      .head { display: flex; align-items: center; gap: 12px; padding: 16px; border-bottom: 1px solid var(--pw-line); }
      .mark { width: 36px; height: 36px; flex: none; }
      .title { flex: 1; min-width: 0; }
      .name { font-size: 18px; font-weight: 700; letter-spacing: -.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .state { text-align: right; }
      .state .value { display: inline-flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; }
      .state .by { font-size: 12px; color: var(--pw-muted); }
      .node { width: 16px; height: 16px; flex: none; }
      .node .ring { fill: var(--pw-accent); } .node .middle { fill: rgba(255,255,255,0.55); } .node .core { fill: #E6F1FB; }
      .armed .state .value { color: var(--pw-accent); }
      .ok .state .value { color: var(--pw-ok); } .ok .node .ring { fill: var(--pw-ok); }
      .warn .state .value { color: var(--pw-warn); } .warn .node .ring { fill: var(--pw-warn); }
      .alarm .state .value { color: var(--pw-alarm-text); } .alarm .node .ring { fill: var(--pw-alarm); }
      .off .node .ring { fill: var(--pw-muted); }
      .alarm .head { background: var(--pw-alarm-soft); }
      .countdown { padding: 12px 16px; border-bottom: 1px solid var(--pw-line); }
      .countdown .row { display: flex; align-items: baseline; gap: 6px; }
      .countdown .label { flex: 1; }
      .countdown .secs { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 28px; font-weight: 600;
        font-variant-numeric: tabular-nums; color: var(--pw-accent); }
      .countdown .unit { color: var(--pw-muted); }
      .bar { height: 4px; background: var(--pw-soft); border-radius: 999px; margin-top: 8px; overflow: hidden; }
      .bar span { display: block; height: 100%; background: var(--pw-accent); transition: width 1s linear; }
      .notice { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--pw-line); font-size: 14px; }
      .notice.ok .label { color: var(--pw-ok); }
      .notice.warn .label { color: var(--pw-warn); }
      .notice.alarm .label { color: var(--pw-alarm-text); }
      .notice.info { background: var(--pw-soft); }
      .chip { padding: 2px 10px; border-radius: 999px; background: var(--pw-soft); border: 1px solid var(--pw-soft-line); font-size: 12px; font-weight: 500; }
      .body { padding: 16px; display: grid; gap: 14px; }
      .keypad { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; max-width: 280px; margin: 0 auto; width: 100%; }
      .display { grid-column: 1 / -1; height: 40px; display: flex; align-items: center; justify-content: center;
        border: 1px solid var(--pw-line); border-radius: 999px; font-size: 22px; letter-spacing: .3em; }
      .display .hint { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 11px; letter-spacing: .18em; color: var(--pw-muted); }
      button { font: inherit; cursor: pointer; border-radius: 999px; border: 1px solid var(--pw-line); background: transparent;
        color: var(--pw-text); transition: background-color 240ms var(--pw-ease), transform 240ms var(--pw-ease); }
      button:focus-visible { outline: 2px solid var(--pw-focus); outline-offset: 2px; }
      button:disabled { opacity: .5; cursor: default; }
      .key { height: 44px; font-size: 18px; font-variant-numeric: tabular-nums; }
      .key:active { background: var(--pw-soft); }
      .actions { display: flex; flex-wrap: wrap; gap: 8px; }
      .mode { flex: 1 1 90px; min-height: 44px; font-weight: 600; border-color: var(--pw-accent); color: var(--pw-accent); }
      .mode:hover:not(:disabled) { background: var(--pw-soft); }
      .mode.secondary { flex-basis: 100%; border-color: var(--pw-soft-line); }
      .mode.disarm { background: var(--pw-fill); border-color: var(--pw-fill); color: #fff; }
      .error { margin: 0 16px 12px; padding: 8px 14px; border-radius: 14px; background: var(--pw-alarm-soft); color: var(--pw-alarm-text); font-size: 13px; }
      .activity { padding: 12px 16px; border-top: 1px solid var(--pw-line); display: grid; gap: 6px; font-size: 13px; }
      .activity .label { color: var(--pw-muted); }
      .entry { display: flex; gap: 10px; }
      .entry .time { font-family: "JetBrains Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; color: var(--pw-muted); min-width: 64px; }
      .foot { padding: 8px 16px 12px; text-align: right; }
      .foot .label { color: var(--pw-muted); }
      .pad { padding: 16px; }
      @media (prefers-reduced-motion: reduce) { button, .bar span { transition: none; } }`;
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
      description: "Arm, disarm, arm when ready, countdown, open zones and recent activity for a Protege WX area.",
      documentationURL: "https://github.com/olliemaller/ha-protege-wx#alarm-card",
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
