/*
 * Protege WX alarm card.
 *
 *   type: custom:protege-alarm-card
 *   entity: alarm_control_panel.alarm
 *   # optional:
 *   name: House
 *   show_keypad: true      # when the alarm needs a code
 *   show_activity: true    # the area's recent events
 *   activity_count: 5
 *   show_arm_when_ready: true  # "Arm when ready" while zones are open
 *
 * Every option can also be set in the dashboard's visual card editor.
 * Finds the area's open-zones, delay and alarm-cause sensors on the same
 * device by itself. Ships with the integration; nothing to add to resources.
 */

const VERSION = "0.4.3";

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

// Material Design Icons paths, so the card draws its own icons.
const ICON = {
  disarmed: "M21,11C21,16.55 17.16,21.74 12,23C6.84,21.74 3,16.55 3,11V5L12,1L21,5V11M12,21C15.75,20 19,15.54 19,11.22V6.3L12,3.18L5,6.3V11.22C5,15.54 8.25,20 12,21Z",
  armed_away: "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1M12,7C13.4,7 14.8,8.1 14.8,9.5V11C15.4,11 16,11.6 16,12.3V15.8C16,16.4 15.4,17 14.7,17H9.2C8.6,17 8,16.4 8,15.7V12.2C8,11.6 8.6,11 9.2,11V9.5C9.2,8.1 10.6,7 12,7M12,8.2C11.2,8.2 10.5,8.7 10.5,9.5V11H13.5V9.5C13.5,8.7 12.8,8.2 12,8.2Z",
  armed_home: "M11,13H13V16H16V11H18L12,6L6,11H8V16H11V13M12,1L21,5V11C21,16.55 17.16,21.74 12,23C6.84,21.74 3,16.55 3,11V5L12,1Z",
  armed_night: "M12 1L3 5V11C3 16.55 6.84 21.74 12 23C17.16 21.74 21 16.55 21 11V5L12 1M15.97 14.41C14.13 16.58 10.76 16.5 9 14.34C6.82 11.62 8.36 7.62 11.7 7C12.04 6.95 12.33 7.28 12.21 7.61C11.75 8.84 11.82 10.25 12.53 11.47C13.24 12.69 14.42 13.46 15.71 13.67C16.05 13.72 16.2 14.14 15.97 14.41Z",
  armed_vacation: "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1M12,5.68C12.5,5.68 12.95,6.11 12.95,6.63V10.11L18,13.26V14.53L12.95,12.95V16.42L14.21,17.37V18.32L12,17.68L9.79,18.32V17.37L11.05,16.42V12.95L6,14.53V13.26L11.05,10.11V6.63C11.05,6.11 11.5,5.68 12,5.68Z",
  triggered: "M21,19V20H3V19L5,17V11C5,7.9 7.03,5.17 10,4.29C10,4.19 10,4.1 10,4A2,2 0 0,1 12,2A2,2 0 0,1 14,4C14,4.1 14,4.19 14,4.29C16.97,5.17 19,7.9 19,11V17L21,19M14,21A2,2 0 0,1 12,23A2,2 0 0,1 10,21M19.75,3.19L18.33,4.61C20.04,6.3 21,8.6 21,11H23C23,8.07 21.84,5.25 19.75,3.19M1,11H3C3,8.6 3.96,6.3 5.67,4.61L4.25,3.19C2.16,5.25 1,8.07 1,11Z",
  pending: "M6,2H18V8H18V8L14,12L18,16V16H18V22H6V16H6V16L10,12L6,8V8H6V2M16,16.5L12,12.5L8,16.5V20H16V16.5M12,11.5L16,7.5V4H8V7.5L12,11.5M10,6H14V6.75L12,8.75L10,6.75V6Z",
  unavailable: "M4,1C2.89,1 2,1.89 2,3V7C2,8.11 2.89,9 4,9H1V11H13V9H10C11.11,9 12,8.11 12,7V3C12,1.89 11.11,1 10,1H4M4,3H10V7H4V3M14,13C12.89,13 12,13.89 12,15V19C12,20.11 12.89,21 14,21H11V23H23V21H20C21.11,21 22,20.11 22,19V15C22,13.89 21.11,13 20,13H14M3.88,13.46L2.46,14.88L4.59,17L2.46,19.12L3.88,20.54L6,18.41L8.12,20.54L9.54,19.12L7.41,17L9.54,14.88L8.12,13.46L6,15.59L3.88,13.46M14,15H20V19H14V15Z",
  backspace: "M19,15.59L17.59,17L14,13.41L10.41,17L9,15.59L12.59,12L9,8.41L10.41,7L14,10.59L17.59,7L19,8.41L15.41,12L19,15.59M22,3A2,2 0 0,1 24,5V19A2,2 0 0,1 22,21H7C6.31,21 5.77,20.64 5.41,20.11L0,12L5.41,3.88C5.77,3.35 6.31,3 7,3H22M22,5H7L2.28,12L7,19H22V5Z",
};
ICON.arming = ICON.pending;
ICON.disarming = ICON.pending;
ICON.armed_custom_bypass = ICON.armed_away;
ICON.unknown = ICON.unavailable;

const svg = (path, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;

const time = (date) => date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

const list = (names) =>
  names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

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
    const alarm = this._hass.states[this._config.entity];
    const needsCode = on && alarm.attributes.code_format && alarm.attributes.code_arm_required !== false;
    if (needsCode && !this._code) {
      this._error = "Enter your PIN first";
      this._render();
      return;
    }
    this._busy = true;
    this._error = "";
    this._render();
    try {
      if (needsCode) {
        // The switch can't take a PIN, so arm through the action instead.
        const mode = this._hass.states[id]?.attributes?.mode || "away";
        await this._hass.callService("protege_wx", "arm_when_ready", {
          entity_id: this._config.entity,
          mode,
          code: this._code,
        });
        this._code = "";
      } else {
        await this._hass.callService("switch", on ? "turn_on" : "turn_off", { entity_id: id });
      }
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
    el.querySelector(".track span").style.transform = `scaleX(${Math.min(1, left / delay.total)})`;
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
      this.shadowRoot.innerHTML = `<style>${this._css()}</style><ha-card><div class="empty">Entity not found: ${esc(this._config.entity)}</div></ha-card>`;
      return;
    }
    const value = state.state;
    const armed = value.startsWith("armed_");
    const tone =
      value === "triggered" ? "alarm"
      : value === "pending" || value === "arming" || value === "disarming" ? "busy"
      : armed ? "armed"
      : value === "disarmed" ? "ok"
      : "off";
    const name = this._config.name || state.attributes.friendly_name || "Alarm";
    const features = state.attributes.supported_features || 0;
    const needsCode = !!state.attributes.code_format;

    const zonesId = this._related("open_zones");
    const zones = zonesId ? hass.states[zonesId] : null;
    const openZones = zones?.attributes?.zones || [];
    const causeId = this._related("alarm_cause");
    const cause = causeId ? hass.states[causeId]?.state : null;
    const delay = this._delay();

    const waitId = this._config.show_arm_when_ready ? this._related("arm_when_ready", "switch") : null;
    const wait = waitId ? hass.states[waitId] : null;
    const waiting = wait?.state === "on";
    const offline = value === "unavailable" || value === "unknown";
    const busy = this._busy ? "disabled" : "";

    // One line under the header that says what matters now.
    let detail = "";
    if (value === "triggered") {
      detail = `<div class="note alarm">${cause && cause !== "none" ? `Set off by <b>${esc(cause)}</b>` : "The alarm is sounding"}</div>`;
    } else if (delay) {
      const left = Math.max(0, Math.round((delay.ends - Date.now()) / 1000));
      detail = `<div class="note countdown">
          <div class="row"><span>${delay.phase === "entry" ? "Entry delay" : "Exit delay"}</span>
            <span class="time"><span class="secs">${left}</span> s</span></div>
          <div class="track"><span></span></div></div>`;
    } else if (value === "disarmed" && waiting) {
      const mode = WAIT_MODE_LABEL[wait.attributes.mode] || "away";
      const still = wait.attributes.open_zones || openZones;
      const until = wait.attributes.until ? ` until ${esc(time(new Date(wait.attributes.until)))}` : "";
      detail = `<div class="note waiting"><b>Arming ${esc(mode)} when ready</b><br>
          <span class="muted">${still.length ? `Waiting for ${esc(list(still))}` : "Arming now"}${until}</span></div>`;
    } else if (value === "disarmed" && zones) {
      detail = openZones.length
        ? `<div class="note warn">${esc(list(openZones))} ${openZones.length === 1 ? "is" : "are"} open</div>`
        : `<div class="note ready">Ready to arm</div>`;
    }

    const available = MODES.filter((m) => features & m.feature);
    const modes = available
      .map((m) => `<button class="btn" data-service="${m.service}" ${busy || offline ? "disabled" : ""}>${esc(m.label)}</button>`)
      .join("");

    let actions;
    if (armed || value === "triggered" || value === "pending" || value === "arming") {
      actions = `<button class="btn primary wide" data-service="alarm_disarm" ${busy}>Disarm</button>`;
    } else {
      let extra = "";
      if (wait && value === "disarmed" && waiting) {
        extra = `<button class="btn quiet wide" data-wait="off" ${busy}>Stop waiting</button>`;
      } else if (wait && value === "disarmed" && openZones.length) {
        extra = `<button class="btn quiet wide" data-wait="on" ${busy}>Arm when ready</button>`;
      }
      actions = modes + extra;
    }
    // One row of modes, however many the area has (no orphan on a second row).
    const columns = Math.max(1, available.length);

    const keypad =
      needsCode && this._config.show_keypad && !offline
        ? `<div class="keypad">
            <div class="dots" aria-label="PIN, ${this._code.length} digits entered">${
              this._code.length ? "<i></i>".repeat(this._code.length) : '<span class="muted">Enter PIN</span>'
            }</div>
            ${["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"]
              .map((k) =>
                k === "clear"
                  ? `<button class="key text" data-key="clear" ${this._code ? "" : "disabled"}>Clear</button>`
                  : k === "back"
                    ? `<button class="key text" data-key="back" aria-label="Delete" ${this._code ? "" : "disabled"}>${svg(ICON.backspace)}</button>`
                    : `<button class="key" data-key="${k}">${k}</button>`
              )
              .join("")}
          </div>`
        : "";

    const activity =
      this._config.show_activity && this._activity.length
        ? `<div class="recent"><h3>Recent</h3>${this._activity
            .map((e) => {
              const text = e.message ? `${e.name || ""} ${e.message}` : `${e.name || ""} ${STATE_LABEL[e.state] || e.state}`;
              return `<div class="entry"><span>${esc(text.trim())}</span><span class="when">${esc(time(new Date(e.when * 1000)))}</span></div>`;
            })
            .join("")}</div>`
        : "";

    const by = state.attributes.changed_by && !offline ? ` · ${esc(state.attributes.changed_by)}` : "";

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <ha-card class="${tone}">
        <div class="head">
          <div class="badge">${svg(ICON[value] || ICON.unknown)}</div>
          <div class="title">
            <div class="name">${esc(name)}</div>
            <div class="state">${esc(STATE_LABEL[value] || value)}<span class="by">${by}</span></div>
          </div>
        </div>
        ${detail}
        ${keypad}
        <div class="actions" style="--pw-columns: ${columns}">${actions}</div>
        ${this._error ? `<div class="error" role="alert">${esc(this._error)}</div>` : ""}
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

  _css() {
    // Home Assistant's own theme colours, so the card matches every theme.
    return `
      :host {
        --pw-accent: var(--primary-color, #03a9f4);
        --pw-ok: var(--success-color, #43a047);
        --pw-warn: var(--warning-color, #ffa600);
        --pw-alarm: var(--error-color, #db4437);
        --pw-text: var(--primary-text-color, #212121);
        --pw-muted: var(--secondary-text-color, #727272);
        --pw-fill: color-mix(in srgb, var(--pw-text) 6%, transparent);
        --pw-line: var(--divider-color, rgba(0, 0, 0, 0.12));
        --pw-tone: var(--pw-muted);
      }
      ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; color: var(--pw-text); }
      .ok { --pw-tone: var(--pw-ok); }
      .armed { --pw-tone: var(--pw-accent); }
      .busy { --pw-tone: var(--pw-warn); }
      .alarm { --pw-tone: var(--pw-alarm); }
      svg { width: 24px; height: 24px; fill: currentColor; display: block; }
      .muted { color: var(--pw-muted); }

      .head { display: flex; align-items: center; gap: 12px; min-width: 0; }
      .badge { flex: none; width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center;
        color: var(--pw-tone); background: color-mix(in srgb, var(--pw-tone) 15%, transparent); }
      .title { min-width: 0; }
      .name { font-size: 14px; line-height: 20px; color: var(--pw-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .state { font-size: 20px; line-height: 26px; font-weight: 600; letter-spacing: -0.01em; }
      .state .by { font-weight: 400; color: var(--pw-muted); font-size: 15px; letter-spacing: 0; }

      .note { padding: 10px 12px; border-radius: 12px; background: var(--pw-fill); font-size: 14px; line-height: 20px; }
      .note.ready { color: var(--pw-ok); background: color-mix(in srgb, var(--pw-ok) 10%, transparent); }
      .note.warn { color: var(--pw-text); background: color-mix(in srgb, var(--pw-warn) 14%, transparent); }
      .note.alarm { color: var(--pw-alarm); background: color-mix(in srgb, var(--pw-alarm) 12%, transparent); }
      .note.waiting { background: color-mix(in srgb, var(--pw-accent) 10%, transparent); }
      .countdown .row { display: flex; justify-content: space-between; align-items: baseline; }
      .countdown .time { color: var(--pw-muted); font-variant-numeric: tabular-nums; }
      .countdown .secs { font-size: 22px; font-weight: 600; color: var(--pw-text); }
      .track { height: 4px; border-radius: 2px; margin-top: 8px; overflow: hidden; background: color-mix(in srgb, var(--pw-warn) 20%, transparent); }
      .track span { display: block; height: 100%; background: var(--pw-warn); transform-origin: left; transition: transform 1s linear; }

      .actions { display: grid; grid-template-columns: repeat(var(--pw-columns, 3), minmax(0, 1fr)); gap: 8px; }
      .btn { font: inherit; font-size: 15px; min-width: 0; padding: 0 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; height: 44px; border: 0; border-radius: 12px; cursor: pointer;
        color: var(--pw-accent); background: color-mix(in srgb, var(--pw-accent) 12%, transparent);
        transition: transform 100ms ease-out, background-color 150ms ease; -webkit-tap-highlight-color: transparent; }
      .btn.wide { grid-column: 1 / -1; }
      .actions[style*="--pw-columns: 4"] .btn:not(.wide) { font-size: 14px; }
      .btn.primary { color: var(--text-primary-color, #fff); background: var(--pw-accent); }
      .btn.quiet { color: var(--pw-text); background: var(--pw-fill); font-weight: 500; }
      .btn:active:not(:disabled), .key:active:not(:disabled) { transform: scale(0.97); }
      .btn:disabled { opacity: 0.4; cursor: default; }
      button:focus-visible { outline: 2px solid var(--pw-accent); outline-offset: 2px; }

      .keypad { display: grid; grid-template-columns: repeat(3, 60px); justify-content: center; gap: 10px 22px; }
      .dots { grid-column: 1 / -1; height: 24px; display: flex; justify-content: center; align-items: center; gap: 10px; font-size: 14px; }
      .dots i { width: 10px; height: 10px; border-radius: 50%; background: var(--pw-text); }
      .key { font: inherit; width: 60px; height: 60px; border-radius: 50%; border: 0; cursor: pointer; font-size: 24px; font-weight: 400;
        color: var(--pw-text); background: var(--pw-fill); font-variant-numeric: tabular-nums;
        transition: transform 100ms ease-out, background-color 150ms ease; -webkit-tap-highlight-color: transparent; }
      .key:active { background: color-mix(in srgb, var(--pw-text) 14%, transparent); }
      .key.text { background: transparent; font-size: 15px; color: var(--pw-muted); display: grid; place-items: center; }
      .key.text:disabled { visibility: hidden; }

      .error { font-size: 14px; color: var(--pw-alarm); }
      .recent h3 { margin: 0 0 4px; font-size: 13px; font-weight: 600; color: var(--pw-muted); }
      .entry { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; font-size: 14px; line-height: 20px;
        border-top: 1px solid var(--pw-line); }
      .entry:first-of-type { border-top: 0; }
      .entry .when { flex: none; color: var(--pw-muted); font-variant-numeric: tabular-nums; }
      .empty { color: var(--pw-muted); }
      @media (prefers-reduced-motion: reduce) { .btn, .key, .track span { transition: none; } }`;
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
      documentationURL: "https://github.com/olliemaller/ha-protege-wx/blob/main/docs/Alarm-card.md",
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
