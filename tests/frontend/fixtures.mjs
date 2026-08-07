export const ACTION_CAPABILITIES = Object.freeze({
  refresh: { available: true, physical: false, allowed_when_printing: true },
  select_tool: { available: true, physical: true, allowed_when_printing: false, requires_confirmation: true },
  unload: { available: true, physical: true, allowed_when_printing: false, requires_confirmation: true },
  feed: { available: true, physical: true, allowed_when_printing: false },
  retract: { available: true, physical: true, allowed_when_printing: false },
  feed_assist: { available: true, physical: true, allowed_when_printing: true, requires_confirmation: true },
  set_slot: { available: true, physical: false, allowed_when_printing: true },
  start_drying: { available: true, physical: true, allowed_when_printing: true },
  stop_drying: { available: true, physical: true, allowed_when_printing: true },
  set_endless_spool: { available: true, physical: false, allowed_when_printing: true },
  encoder_calibration_start: { available: true, physical: false, allowed_when_printing: false },
  encoder_calibration_finish: { available: false, physical: false, allowed_when_printing: false },
  encoder_calibration_cancel: { available: false, physical: false, allowed_when_printing: false },
  calibrate: { available: true, physical: true, allowed_when_printing: false },
  save_calibration: { available: true, physical: true, allowed_when_printing: false },
  cancel_calibration: { available: true, physical: true, allowed_when_printing: false },
  diagnose: { available: true, physical: false, allowed_when_printing: true },
  recover: { available: true, physical: true, allowed_when_printing: false },
})

export const DEFAULT_MATERIAL_TYPES = Object.freeze([
  'PLA',
  'PLA+',
  'PETG',
  'PETG-CF',
  'PETCF',
  'ABS',
  'ABSCF',
  'ASA',
  'TPU',
  'PA',
  'PA-CF',
  'PAHTCF',
  'PET-CF',
  'PC',
  'PBT-CF',
  'PEEK',
  'PVA',
  'HIPS',
])

export function makeDevice (index, model = 'ace1') {
  return {
    id: `ace${index}`,
    index,
    name: `ACE ${index + 1}`,
    model,
    protocol: model,
    connected: true,
    enabled: true,
    physical_actions_enabled: true,
    state: 'idle',
    temperature: 31 + index,
    humidity: 25,
    firmware: '1.0.0',
    capabilities: ACTION_CAPABILITIES,
    dryer: { active: false, target_temperature: 45, remaining_minutes: 0 },
    endless_spool: { enabled: false, match_mode: 'exact', candidates: [] },
    slots: Array.from({ length: 4 }, (_, slot) => ({
      slot,
      tool: `T${index * 4 + slot}`,
      state: 'ready',
      available: true,
      loaded: index === 0 && slot === 0,
      material: slot % 2 ? 'PETG' : 'PLA',
      color: slot % 2 ? '#d92d20' : '#1570ef',
      remaining_percent: 80 - slot * 10,
    })),
    diagnostics: { port: `/dev/serial/by-id/ace-${index}`, reconnects: 0, warnings: [] },
  }
}

export function makeStatus (deviceCount = 2, models = []) {
  const deviceIds = Array.from({ length: deviceCount }, (_, index) => `ace${index}`)
  const multiDevice = deviceCount > 1
  return {
    schema_version: '3.0',
    generated_at: '2026-08-02T10:00:00Z',
    material_types: [...DEFAULT_MATERIAL_TYPES],
    system: {
      print_state: 'standby',
      current_tool: 'T0',
      degraded: false,
    },
    path_lock: { locked: false, owner: '' },
    toolchange_mode: 'automatic',
    toolchange_ready: true,
    toolchange_blocked_reason: '',
    toolchange_notice: null,
    toolchange_notices: [],
    feed_assist: { active: false, device_id: '', slot: null, tool: '' },
    path: {
      busy: false,
      state: 'empty',
      sensors: {
        upper: null,
        lower: null,
        rdm: null,
        hubs: multiDevice
          ? Object.fromEntries(deviceIds.map((deviceId, index) => [deviceId, [true, false, null, true][index]]))
          : {},
      },
      sensor_policy: {
        upper: {
          control_endpoint: true,
          feed_timeout: 30,
        },
        lower: {
          bypassed: false,
          configured: true,
          control_enabled: true,
          monitor_only: false,
          bypass_load_length: 25,
        },
      },
      encoders: {
        shared: {
          configured: true,
          available: true,
          mode: 'protect',
          calibrated: true,
          resolution: 0.7425,
          detection_length: 20,
          counts: 1842,
          position: 1367.685,
          tracking_ratio: 0.997,
          min_tracking_ratio: 0.6,
          armed: true,
          calibration_active: false,
          print_monitor: {
            mode: 'pause',
            enabled: true,
            active: false,
            state: 'idle',
            detection_length: 20,
            extrusion_since_motion: 0,
            headroom: 20,
            event_sequence: 0,
            last_event: null,
            fault: null,
          },
          fault: null,
        },
      },
      topology: {
        current_device: 'ace0',
        route: multiDevice ? ['device_hub', 'rdm', 'upper', 'lower'] : ['rdm', 'upper', 'lower'],
        branch_clearance: multiDevice
          ? Object.fromEntries(deviceIds.map((deviceId, index) => [deviceId, 35 + index * 5]))
          : {},
      },
    },
    transaction: { active: false, action: '', phase: '' },
    capabilities: { actions: ACTION_CAPABILITIES },
    endless_spool: { enabled: false, match_mode: 'exact' },
    devices: Array.from({ length: deviceCount }, (_, index) => makeDevice(index, models[index] || 'ace1')),
    calibration: { state: 'idle' },
    diagnostics: { warnings: [], errors: [], last_error: null },
  }
}

export function jsonResponse (payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json () { return payload },
  }
}
