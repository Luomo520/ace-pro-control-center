import {
  ACE_ASSIST_ONLY_MESSAGE,
  ACE_ACTIONS,
  ENCODER_CALIBRATION_DEFAULTS,
  buildViewModel,
  canPerformAction,
  collectPrintMonitorEvent,
  evaluateEncoderCalibrationSegments,
  normalizeAceState,
} from '../shared/ace-core.js?v=V2.5ahpha'

const MATERIAL_TYPES = [
  'PLA', 'PLA+', 'PETG', 'PETG-CF', 'ABS', 'ASA', 'TPU', 'PA-CF', 'PC', 'PVA',
]
const HUB_SENSOR_STATES = Object.freeze([true, false, null, true])
const ENCODER_SCENARIOS = Object.freeze(['protect', 'monitor', 'calibrating', 'uncalibrated', 'not-armed', 'fault', 'off', 'unconfigured'])

const SLOT_PRESETS = [
  { material: 'PLA', color: '#e5484d', temperature: 215, rfid: 2 },
  { material: 'PETG', color: '#2f7de1', temperature: 240, rfid: 2 },
  { material: 'PLA+', color: '#f1c40f', temperature: 220, rfid: 0 },
  { material: 'TPU', color: '#22a06b', temperature: 225, rfid: 2 },
  { material: 'ABS', color: '#8b5cf6', temperature: 255, rfid: 2 },
  { material: 'ASA', color: '#f08c46', temperature: 260, rfid: 2 },
  { material: 'PA-CF', color: '#343a40', temperature: 285, rfid: 0 },
  { material: 'PVA', color: '#f8f9fa', temperature: 205, rfid: 2 },
]

const CAPABILITIES = Object.freeze({
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
  encoder_calibration_finish: { available: true, physical: false, allowed_when_printing: false },
  encoder_calibration_cancel: { available: true, physical: false, allowed_when_printing: false },
  calibrate: { available: false, physical: true, allowed_when_printing: false, reason: '通用校准后端尚未开放。' },
  save_calibration: { available: false, physical: true, allowed_when_printing: false },
  cancel_calibration: { available: false, physical: true, allowed_when_printing: false },
  diagnose: { available: true, physical: false, allowed_when_printing: true },
  recover: { available: true, physical: true, allowed_when_printing: false },
})

const root = document.querySelector('#sim-root')
const toastRegion = document.querySelector('#toast-region')
const countSelect = document.querySelector('#device-count')
const modelsSelect = document.querySelector('#device-models')
const scenarioSelect = document.querySelector('#device-scenario')
const encoderSelect = document.querySelector('#encoder-scenario')
const noticeButton = document.querySelector('#trigger-toolchange-notice')

const params = new URLSearchParams(window.location.search)
const state = {
  view: ['card', 'page', 'standalone'].includes(params.get('view')) ? params.get('view') : 'card',
  deviceCount: [1, 2, 3, 4].includes(Number(params.get('devices'))) ? Number(params.get('devices')) : 3,
  modelMode: ['ace1', 'mixed', 'ace2'].includes(params.get('models')) ? params.get('models') : 'mixed',
  scenario: ['ready', 'manual', 'not-ready', 'notice', 'busy', 'offline', 'lower-bypass'].includes(params.get('scenario')) ? params.get('scenario') : 'ready',
  encoderScenario: ENCODER_SCENARIOS.includes(params.get('encoder')) ? params.get('encoder') : 'protect',
  selectedDeviceId: 'ace0',
  standaloneTab: 'overview',
  extraOpen: false,
  encoderCalibrationLength: ENCODER_CALIBRATION_DEFAULTS.segmentLength,
  encoderCalibrationSegments: [],
  encoderCalibrationLastCounts: null,
  rawStatus: null,
  noticeCursor: null,
  noticeCursorSignature: '',
  noticeTimer: null,
  monitorEventCursor: null,
  monitorEventCursorSignature: '',
  calibrationTimer: null,
  calibrationStartCounts: null,
}

function escapeHtml (value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function attrDisabled (decision) {
  return decision?.allowed ? '' : `disabled title="${escapeHtml(decision?.reason || '当前不可用')}"`
}

function modelForIndex (index) {
  if (state.modelMode === 'ace1') return 'ace1'
  if (state.modelMode === 'ace2') return 'ace2'
  return index % 2 === 0 ? 'ace1' : 'ace2'
}

function createDevice (index) {
  const model = modelForIndex(index)
  return {
    id: `ace${index}`,
    index,
    name: `ACE ${index + 1}`,
    model,
    protocol: model === 'ace1' ? 'ACE1 JSON/CRC' : 'ACE2 BUS',
    connected: true,
    enabled: true,
    physical_actions_enabled: model === 'ace1',
    state: 'ready',
    temperature: 31 + index,
    humidity: 24 + index * 3,
    fan_speed: 0,
    firmware: model === 'ace1' ? '1.3.0' : '2.0.7',
    rfid_enabled: true,
    capabilities: CAPABILITIES,
    dryer: {
      active: false,
      temperature: 31 + index,
      target_temperature: 45,
      remaining_minutes: 0,
    },
    slots: Array.from({ length: 4 }, (_, slotIndex) => {
      const toolIndex = index * 4 + slotIndex
      const preset = SLOT_PRESETS[toolIndex % SLOT_PRESETS.length]
      return {
        slot: slotIndex,
        tool: `T${toolIndex}`,
        state: 'ready',
        available: true,
        loaded: toolIndex === 0,
        material: preset.material,
        color: preset.color,
        target_temperature: preset.temperature,
        remaining_percent: Math.max(28, 92 - toolIndex * 5),
        rfid: model === 'ace2' ? null : preset.rfid,
        spool_id: model === 'ace2' ? `UID-${index + 1}-${slotIndex + 1}` : `AC-${String(toolIndex + 1).padStart(4, '0')}`,
      }
    }),
    diagnostics: {
      port: model === 'ace1' ? `/dev/serial/by-id/ACE_PRO_${index + 1}` : `/dev/serial/by-id/ACE2_BUS_${Math.floor(index / 2) + 1}`,
      uid: model === 'ace2' ? `ace2-${index + 1}-a9f3` : '',
      reconnects: index === 0 ? 0 : 1,
      warnings: [],
    },
  }
}

function createEncoderStatus () {
  const status = {
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
      active: true,
      state: 'monitoring',
      detection_length: 20,
      extrusion_since_motion: 4.5,
      headroom: 15.5,
      event_sequence: 0,
      last_event: null,
      fault: null,
    },
    fault: null,
  }
  if (state.encoderScenario === 'unconfigured') return { configured: false }
  if (state.encoderScenario === 'off') return { ...status, mode: 'off', armed: false, print_monitor: { ...status.print_monitor, mode: 'off', enabled: false, active: false, state: 'off', headroom: null } }
  if (state.encoderScenario === 'monitor') return { ...status, mode: 'monitor', armed: false, print_monitor: { ...status.print_monitor, mode: 'monitor', extrusion_since_motion: 7, headroom: 13 } }
  if (state.encoderScenario === 'calibrating') {
    return { ...status, mode: 'off', calibrated: false, resolution: null, armed: false, calibration_active: true, print_monitor: { ...status.print_monitor, active: false, state: 'idle' } }
  }
  if (state.encoderScenario === 'uncalibrated') {
    return { ...status, calibrated: false, resolution: null, armed: false }
  }
  if (state.encoderScenario === 'not-armed') return { ...status, armed: false }
  if (state.encoderScenario === 'fault') {
    return {
      ...status,
      armed: false,
      print_monitor: {
        ...status.print_monitor,
        active: false,
        state: 'pause_requested',
        extrusion_since_motion: 20,
        headroom: 0,
        event_sequence: 12,
        last_event: {
          code: 'encoder_no_motion',
          message: '挤出期间共享编码器未检测到耗材移动。',
          probable_cause: '耗材打滑、断料或打印头入口堵塞。',
          pause_requested: true,
          context: {
            tool: 'T0', device: 'ace0', path_state: 'loaded', print_state: 'printing',
            sensors: { upper: true, lower: false, rdm: true, hubs: { ace0: true } },
          },
        },
        fault: {
          code: 'encoder_no_motion',
          message: '共享编码器打印监测故障。',
          probable_cause: '耗材打滑、断料或打印头入口堵塞。',
          pause_requested: true,
          context: {
            tool: 'T0', device: 'ace0', path_state: 'loaded', print_state: 'printing',
            sensors: { upper: true, lower: false, rdm: true, hubs: { ace0: true } },
          },
        },
      },
      fault: { code: 'encoder_no_motion', message: '共享编码器未检测到耗材移动。' },
    }
  }
  return status
}

function createStatus () {
  const devices = Array.from({ length: state.deviceCount }, (_, index) => createDevice(index))
  const multiDevice = devices.length > 1
  const hubs = multiDevice
    ? Object.fromEntries(devices.map((device, index) => [device.id, HUB_SENSOR_STATES[index]]))
    : {}
  const branchClearance = multiDevice
    ? Object.fromEntries(devices.map((device, index) => [device.id, 35 + index * 5]))
    : {}
  const status = {
    schema_version: '3.0',
    generated_at: new Date().toISOString(),
    material_types: MATERIAL_TYPES,
    system: {
      print_state: 'standby',
      current_tool: 'T0',
      degraded: false,
    },
    path_lock: { locked: false, owner: '' },
    path: {
      busy: false,
      state: 'empty',
      sensors: { upper: false, lower: false, rdm: false, hubs },
      sensor_policy: {
        upper: {
          control_endpoint: true,
          feed_timeout: 30,
        },
        lower: {
          bypassed: state.scenario === 'lower-bypass',
          configured: true,
          control_enabled: state.scenario !== 'lower-bypass',
          monitor_only: state.scenario === 'lower-bypass',
          bypass_load_length: 25,
        },
      },
      encoders: { shared: createEncoderStatus() },
      topology: {
        current_device: 'ace0',
        route: multiDevice ? ['device_hub', 'rdm', 'upper', 'lower'] : ['rdm', 'upper', 'lower'],
        branch_clearance: branchClearance,
      },
    },
    transaction: { active: false, action: '', phase: '', progress: null },
    capabilities: {
      actions: Object.fromEntries(
        Object.entries(CAPABILITIES).map(([action, capability]) => [action, { ...capability }]),
      ),
    },
    toolchange_mode: 'automatic',
    toolchange_ready: true,
    toolchange_blocked_reason: '',
    toolchange_notice: null,
    toolchange_notices: [],
    feed_assist: { active: false, device_id: '', slot: null, tool: '' },
    endless_spool: { enabled: false, match_mode: 'exact', candidates: [] },
    devices,
    calibration: { state: 'unavailable' },
    diagnostics: { warnings: [], errors: [], last_error: null },
  }

  if (state.scenario === 'manual' || state.scenario === 'notice') {
    status.toolchange_mode = 'manual'
    status.toolchange_ready = false
    status.toolchange_blocked_reason = '自动换料未配置；当前仅可使用手动送料、回抽、烘干和 ACE 辅助送料。'
  }

  if (state.scenario === 'not-ready') {
    status.toolchange_mode = 'automatic'
    status.toolchange_ready = false
    status.toolchange_blocked_reason = '切刀坐标和换料后处理宏尚未完成检查。'
  }

  const sharedEncoder = status.path.encoders.shared
  if (sharedEncoder.calibration_active) {
    status.system.current_tool = null
    status.path.state = 'empty'
    status.devices.forEach(device => device.slots.forEach(slot => { slot.loaded = false }))
  } else if (status.system.current_tool !== null) {
    status.path.state = 'nozzle'
  }
  if (status.toolchange_mode === 'automatic' && sharedEncoder.mode === 'protect' && !sharedEncoder.armed) {
    status.toolchange_ready = false
    status.toolchange_blocked_reason = '共享编码器保护模式尚未就绪，请先完成校准并排除故障。'
  }

  if (state.scenario === 'notice') {
    const staleNotice = {
      sequence: 10,
      code: 'TOOLCHANGE_NOT_READY',
      command: 'T1',
      message: 'ACE 自动换料未配置，已忽略工具指令；当前无法进行多色打印，仅可使用已启用的 ACE 辅助送料。',
    }
    status.toolchange_notice = staleNotice
    status.toolchange_notices = [staleNotice]
  }

  if (state.scenario === 'busy') {
    const activeIndex = Math.min(1, devices.length - 1)
    devices[activeIndex].state = 'feeding'
    devices[activeIndex].current_action = '送料至打印头'
    status.path_lock = { locked: true, owner: devices[activeIndex].id }
    status.path.busy = true
    status.path.state = 'loading'
    status.path.sensors = {
      ...status.path.sensors,
      upper: true,
      lower: true,
      rdm: false,
      hubs: multiDevice
        ? { ...status.path.sensors.hubs, [devices[activeIndex].id]: true }
        : {},
    }
    status.path.topology.current_device = devices[activeIndex].id
    status.transaction = {
      active: true,
      action: 'select_tool',
      phase: '装载至打印头',
      progress: 58,
      device_id: devices[activeIndex].id,
      tool: `T${activeIndex * 4}`,
    }
  }

  if (state.scenario === 'offline') {
    const offline = devices.at(-1)
    offline.connected = false
    offline.state = 'offline'
    offline.diagnostics.warnings = [{ message: '设备连接中断，等待串口重新枚举。' }]
    status.system.degraded = true
    status.system.degraded_reason = `${offline.name} 未连接。`
    status.path.sensors = {
      ...status.path.sensors,
      upper: null,
      lower: null,
      rdm: null,
      hubs: { ...status.path.sensors.hubs, [offline.id]: null },
    }
    status.diagnostics.warnings = [{ code: 'ACE_DEVICE_OFFLINE', message: `${offline.name} 未连接。` }]
  }
  return status
}

function resetStatus () {
  if (state.noticeTimer) window.clearTimeout(state.noticeTimer)
  if (state.calibrationTimer) window.clearInterval(state.calibrationTimer)
  state.rawStatus = createStatus()
  state.noticeCursor = null
  state.noticeCursorSignature = ''
  state.monitorEventCursor = null
  state.monitorEventCursorSignature = ''
  state.calibrationStartCounts = state.rawStatus.path.encoders.shared.calibration_active
    ? Number(state.rawStatus.path.encoders.shared.counts || 0)
    : null
  if (Number(state.selectedDeviceId.slice(3)) >= state.deviceCount) state.selectedDeviceId = 'ace0'
  if (state.scenario === 'notice') state.noticeTimer = window.setTimeout(emitToolchangeNotice, 350)
  syncCalibrationTimer()
}

function syncCalibrationTimer () {
  if (state.calibrationTimer) window.clearInterval(state.calibrationTimer)
  state.calibrationTimer = null
  if (!state.rawStatus?.path?.encoders?.shared?.calibration_active) return
  state.calibrationTimer = window.setInterval(() => {
    const encoder = state.rawStatus.path.encoders.shared
    encoder.counts = Number(encoder.counts || 0) + 7
    render()
  }, 1000)
}

function getViewModel () {
  syncEncoderCalibrationCapabilities(state.rawStatus)
  return buildViewModel(normalizeAceState(state.rawStatus))
}

function syncEncoderCalibrationCapabilities (status) {
  const actions = status?.capabilities?.actions
  const encoder = status?.path?.encoders?.shared
  if (!actions || !encoder) return
  const update = (action, available, reason = '') => {
    actions[action] = { ...actions[action], available, reason }
  }
  if (!encoder.configured) {
    const reason = '共享编码器未配置。'
    update('encoder_calibration_start', false, reason)
    update('encoder_calibration_finish', false, reason)
    update('encoder_calibration_cancel', false, reason)
    return
  }
  const calibrationActive = Boolean(encoder.calibration_active)
  if (!calibrationActive) {
    update('encoder_calibration_finish', false, '共享编码器当前没有进行中的校准。')
    update('encoder_calibration_cancel', false, '共享编码器当前没有进行中的校准。')
  } else {
    update('encoder_calibration_start', false, '共享编码器校准已在进行中。')
    update('encoder_calibration_cancel', true)
  }
  const feedAssist = status.feed_assist
  const feedAssistActive = Boolean(feedAssist?.enabled || feedAssist?.active || feedAssist?.tool)
  const routeReason = status.path.busy || status.path_lock?.locked
    ? '共享耗材路径正在执行其他动作。'
    : status.system.current_tool !== null
      ? '请先卸载当前耗材，使共享路径处于空闲状态。'
      : feedAssistActive
        ? '请先停用 ACE 辅助送料。'
        : status.path.state !== 'empty'
          ? '共享耗材路径必须为空。'
          : ''
  if (calibrationActive) {
    update(
      'encoder_calibration_finish',
      Boolean(encoder.available) && !routeReason,
      !encoder.available ? '共享编码器当前不可用，无法完成校准。' : routeReason,
    )
  } else {
    update('encoder_calibration_start', !routeReason, routeReason)
  }
}

function syncUrl () {
  const query = new URLSearchParams({
    view: state.view,
    devices: String(state.deviceCount),
    models: state.modelMode,
    scenario: state.scenario,
    encoder: state.encoderScenario,
  })
  window.history.replaceState(null, '', `${window.location.pathname}?${query}`)
}

function syncControls () {
  countSelect.value = String(state.deviceCount)
  modelsSelect.value = state.modelMode
  scenarioSelect.value = state.scenario
  encoderSelect.value = state.encoderScenario
  document.querySelectorAll('[data-view]').forEach(button => {
    const active = button.dataset.view === state.view
    button.classList.toggle('active', active)
    button.setAttribute('aria-pressed', String(active))
  })
}

function toast (title, message = '') {
  const item = document.createElement('div')
  item.className = 'sim-toast'
  item.innerHTML = `<strong>${escapeHtml(title)}</strong>${message ? `<span>${escapeHtml(message)}</span>` : ''}`
  toastRegion.append(item)
  window.setTimeout(() => item.remove(), 2600)
}

function collectToolchangeNotices (notices, cursor, cursorSignature = '') {
  if (!notices.length) return { cursor, cursorSignature, notices: [] }
  const latest = notices[notices.length - 1]
  const latestSignature = JSON.stringify([latest.sequence, latest.code || '', latest.command || '', latest.message || ''])
  const sequenceRestarted = cursor !== null && (
    latest.sequence < cursor ||
    (latest.sequence === cursor && cursorSignature && latestSignature !== cursorSignature)
  )
  const unseen = cursor === null || sequenceRestarted
    ? notices
    : notices.filter(notice => notice.sequence > cursor)
  return {
    cursor: latest.sequence,
    cursorSignature: latestSignature,
    notices: unseen,
  }
}

function observeToolchangeNotices (status) {
  const notices = Array.isArray(status.toolchangeNotices) ? status.toolchangeNotices : []
  const batch = collectToolchangeNotices(notices, state.noticeCursor, state.noticeCursorSignature)
  state.noticeCursor = batch.cursor
  state.noticeCursorSignature = batch.cursorSignature
  for (const notice of batch.notices) toast(`${notice.command || '工具指令'} 已忽略`, notice.message)
}

function observePrintMonitorEvent (status) {
  const monitor = status?.path?.encoders?.shared?.printMonitor
  const batch = collectPrintMonitorEvent(monitor, state.monitorEventCursor, state.monitorEventCursorSignature)
  state.monitorEventCursor = batch.cursor
  state.monitorEventCursorSignature = batch.cursorSignature
  if (!batch.event) return
  const passive = monitor.mode === 'monitor'
  toast(
    passive ? '打印监测提示' : '打印监测故障',
    `${batch.event.message}${batch.event.probableCause ? ` 可能原因：${batch.event.probableCause}` : ''}${passive ? ' 仅提示，未请求暂停。' : monitor.pauseRequested ? ' 打印已请求暂停。' : ''}`
  )
}

function emitToolchangeNotice () {
  const queue = state.rawStatus.toolchange_notices
  const sequence = Math.max(0, ...queue.map(notice => notice.sequence)) + 1
  const command = `T${sequence % Math.min(16, state.deviceCount * 4)}`
  const notice = {
    sequence,
    code: 'TOOLCHANGE_NOT_READY',
    command,
    message: 'ACE 自动换料未配置，已忽略工具指令；当前无法进行多色打印，仅可使用已启用的 ACE 辅助送料。',
  }
  queue.push(notice)
  state.rawStatus.toolchange_notices = queue.slice(-16)
  state.rawStatus.toolchange_notice = notice
  render()
}

function spoolGraphic (slot) {
  return `<svg viewBox="0 0 200 140" class="acepro-slot-card__spool-svg" aria-hidden="true">
    <ellipse cx="60" cy="70" rx="36" ry="64" class="acepro-slot-card__spool-flange-back" />
    <rect x="58" y="18" width="90" height="104" rx="40" ry="40" fill="${escapeHtml(slot.color)}" class="acepro-slot-card__spool-body" />
    <ellipse cx="142" cy="70" rx="36" ry="64" class="acepro-slot-card__spool-flange-front" />
    <ellipse cx="142" cy="70" rx="10" ry="20" class="acepro-slot-card__spool-hole" />
  </svg>`
}

function renderSlotCard (device, slot, status) {
  const action = slot.active ? ACE_ACTIONS.UNLOAD : ACE_ACTIONS.SELECT_TOOL
  const decision = canPerformAction(status, action, { device, slot })
  const statusText = !device.connected ? '离线' : slot.empty ? '空槽' : '可用'
  const statusClass = !device.connected ? 'error' : slot.empty ? 'empty' : 'ready'
  const options = MATERIAL_TYPES.map(material => `<option value="${material}" ${slot.materialLabel === material ? 'selected' : ''}>${material}</option>`).join('')
  return `<article class="acepro-slot-card ${slot.active ? 'acepro-slot-card--active' : 'acepro-slot-card--ready'}">
    <div class="acepro-slot-card__header">
      <div class="acepro-slot-card__tool">${slot.tool}<span class="acepro-slot-card__slot-label">${slot.label} · ${escapeHtml(slot.materialLabel)}</span></div>
      <div class="acepro-slot-card__badges">
        ${slot.active ? '<span class="acepro-slot-card__badge acepro-slot-card__badge--loaded">已装载</span>' : ''}
        <span class="acepro-slot-card__badge acepro-slot-card__badge--${statusClass}">${statusText}</span>
      </div>
    </div>
    <div class="acepro-slot-card__spool"><div class="acepro-slot-card__spool-visual">${spoolGraphic(slot)}</div></div>
    <div class="acepro-slot-card__meta">
      <div class="acepro-slot-card__meta-row"><span>RFID</span><strong>${escapeHtml(slot.rfidLabel)}</strong></div>
      <div class="acepro-slot-card__meta-row"><span>SKU</span><strong>${escapeHtml(slot.spoolId || '--')}</strong></div>
    </div>
    <div class="acepro-slot-card__editor">
      <div class="acepro-input-row">
        <label>材料<select data-material="${device.id}:${slot.index}" ${!device.connected ? 'disabled' : ''}>${options}</select></label>
        <label>温度<input type="number" value="${slot.targetTemperature ?? ''}" min="0" max="400" ${!device.connected ? 'disabled' : ''}></label>
      </div>
      <div class="acepro-color-row">
        <input type="color" value="${escapeHtml(slot.color)}" data-color="${device.id}:${slot.index}" aria-label="耗材颜色" ${!device.connected ? 'disabled' : ''}>
        <input type="text" value="${escapeHtml(slot.color)}" aria-label="颜色值" readonly>
      </div>
    </div>
    <div class="acepro-slot-card__actions">
      <button type="button" class="fluidd-button primary" data-slot-action="${device.id}:${slot.index}" ${attrDisabled(decision)}>${slot.active ? '卸载' : '更换耗材'}</button>
      <button type="button" class="fluidd-button" data-save-slot="${device.id}:${slot.index}" ${!device.connected ? 'disabled' : ''}>保存</button>
      <button type="button" class="fluidd-button danger-text" data-clear-slot="${device.id}:${slot.index}" ${!device.connected ? 'disabled' : ''}>清空</button>
    </div>
    <div class="acepro-slot-card__secondary-actions">
      <button type="button" class="fluidd-button text" disabled>开启助推</button>
      <button type="button" class="fluidd-button text" disabled>换卷</button>
    </div>
  </article>`
}

function renderDeviceSwitch (viewModel) {
  if (viewModel.devices.length < 2) return ''
  return `<div class="acepro-device-switch" style="--ace-device-count:${viewModel.devices.length}" role="group" aria-label="选择 ACE 设备">
    ${viewModel.devices.map(device => `<button type="button" class="fluidd-button device-button ${device.id === state.selectedDeviceId ? 'primary' : ''}" data-device="${device.id}" aria-pressed="${device.id === state.selectedDeviceId}">
      <span class="acepro-device-switch__dot acepro-device-switch__dot--${device.statusTone}"></span>
      <span>${escapeHtml(device.name)}</span><span class="acepro-device-switch__tools">${device.slots[0].tool}-${device.slots[3].tool}</span>
    </button>`).join('')}
  </div>`
}

function renderGlobalCurrentTool (viewModel) {
  if (viewModel.devices.length < 2) return ''
  const target = viewModel.currentToolTarget
  const device = target && viewModel.devices.find(item => item.id === target.deviceId)
  const jump = device && device.id !== state.selectedDeviceId
    ? `<button type="button" class="fluidd-button" data-jump-current-tool="${device.id}">转到所属 ACE</button>`
    : ''
  return `<div class="acepro-global-tool"><div><span>全局当前工具</span><strong>${escapeHtml(viewModel.currentToolLabel)}</strong><small>${device ? `${escapeHtml(device.name)} · 槽${target.slot + 1}` : '当前没有装载工具'}</small></div>${jump}</div>`
}

function renderToolchangeMode (viewModel) {
  const toolchange = viewModel.toolchange
  const tone = toolchange.mode === 'manual' ? 'manual' : toolchange.ready ? 'ready' : 'blocked'
  const label = toolchange.mode === 'manual' ? '手动模式' : toolchange.ready ? '自动换料已就绪' : '自动换料未就绪'
  const description = toolchange.ready ? '工具指令、卸载和无限续料可用。' : (toolchange.assistanceMessage || ACE_ASSIST_ONLY_MESSAGE)
  const detail = !toolchange.ready && toolchange.blockedReason ? `<small>${escapeHtml(toolchange.blockedReason)}</small>` : ''
  return `<div class="acepro-toolchange-mode acepro-toolchange-mode--${tone}"><div><strong>${label}</strong><span>${escapeHtml(description)}</span>${detail}</div><span>${toolchange.ready ? '可自动换料' : '自动换料不可用'}</span></div>`
}

function renderEncoderStatus (encoder) {
  const title = encoder.fault?.message || (encoder.state === 'not_armed'
    ? '保护模式尚未启用，当前不会参与送料保护。'
    : encoder.mode === 'monitor'
      ? '只读监测耗材移动；发现异常时仅提示，不参与控制。'
      : encoder.mode === 'protect'
        ? '保护模式监测耗材移动；发现异常时参与送料保护。'
        : encoder.summaryLabel)
  return `<strong class="acepro-encoder-status acepro-encoder-status--${escapeHtml(encoder.tone)}" title="${escapeHtml(title)}"><span class="acepro-encoder-status__dot"></span>${escapeHtml(encoder.summaryLabel)}</strong>`
}

function formatMonitorLength (value) {
  if (value === null || value === undefined || value === '') return '--'
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(1)} mm` : '--'
}

function formatFeedTimeout (value) {
  if (value === null || value === undefined || value === '') return '--'
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? `${number.toFixed(1)} 秒` : '--'
}

function formatTrackingRatio (value) {
  if (value === null || value === undefined || value === '') return '--'
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0 || number > 1) return '--'
  return `${(number * 100).toFixed(1).replace(/\.0$/, '')}%`
}

function renderMonitorSensor (name, value) {
  const detected = value && typeof value === 'object'
    ? value.detected ?? value.triggered ?? value.present
    : value
  const tone = detected === true ? 'present' : detected === false ? 'empty' : 'unknown'
  const label = detected === true ? '有料' : detected === false ? '无料' : '未知'
  return `<span class="sim-monitor-sensor ${tone}"><i></i>${escapeHtml(name)}：${label}</span>`
}

function renderMonitorSensors (issue) {
  const sensors = issue?.context?.sensors
  if (!sensors || typeof sensors !== 'object') return ''
  const names = { upper: '上方', lower: '下方', rdm: '总五通', hub: '一级五通' }
  return Object.entries(sensors).flatMap(([name, value]) => {
    if (name === 'hubs' && value && typeof value === 'object') {
      return Object.entries(value).map(([device, sensor]) => renderMonitorSensor(`${device} 五通`, sensor))
    }
    return [renderMonitorSensor(names[name] || name, value)]
  }).join('')
}

function renderEncoderMaintenance (viewModel, standalone = false) {
  const encoder = viewModel.sharedEncoder
  const calibration = evaluateEncoderCalibrationSegments(state.encoderCalibrationSegments)
  const monitor = encoder.printMonitor
  const start = canPerformAction(viewModel.status, ACE_ACTIONS.ENCODER_CALIBRATION_START)
  const finish = canPerformAction(viewModel.status, ACE_ACTIONS.ENCODER_CALIBRATION_FINISH)
  const cancel = canPerformAction(viewModel.status, ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL)
  const length = Number(state.encoderCalibrationLength)
  const finishDecision = Number.isFinite(length) && length >= 0.01 && length <= 2000 && calibration.canSave
    ? finish
    : { allowed: false, reason: calibration.message }
  const recordDecision = encoder.calibrationActive && state.encoderCalibrationLastCounts !== null && !calibration.complete
    ? { allowed: true, reason: '' }
    : { allowed: false, reason: '请先开始校准，或重置分段建立计数基线。' }
  const blocker = encoder.configured
    ? (encoder.calibrationActive ? finishDecision.reason : start.reason)
    : '共享编码器未配置。'
  const issue = monitor.fault || monitor.lastEvent
  const context = issue?.context
  const contextLabel = context ? [
    context.tool && `工具 ${context.tool}`,
    context.device && `设备 ${context.device}`,
    context.pathState && `路径 ${context.pathState}`,
    context.printState && `打印 ${context.printState}`,
  ].filter(Boolean).join(' · ') : ''
  const button = standalone ? 'standalone-button' : 'fluidd-button'
  const rows = Array.from({ length: ENCODER_CALIBRATION_DEFAULTS.segmentCount }, (_, index) => {
    const segment = calibration.segments[index]
    if (!segment) return `<div class="sim-encoder-segment pending"><strong>第 ${index + 1} 段</strong><span>${escapeHtml(state.encoderCalibrationLength)} mm</span><span>等待测量</span><span>--</span></div>`
    const tone = !segment.valid || (calibration.complete && calibration.state === 'rejected') ? 'rejected' : calibration.complete && calibration.state === 'warning' ? 'warning' : 'passed'
    return `<div class="sim-encoder-segment ${tone}"><strong>第 ${index + 1} 段</strong><span>${segment.length.toFixed(1)} mm · ${segment.pulses} 脉冲</span><span>${segment.resolution === null ? '--' : `${segment.resolution.toFixed(4)} mm/脉冲`}</span><span>偏差 ${segment.deviationPercent === null ? '--' : `${segment.deviationPercent.toFixed(1)}%`}</span></div>`
  }).join('')
  return `<section class="sim-encoder-maintenance ${standalone ? 'standalone' : ''}">
    <div class="sim-encoder-column">
      <div class="sim-encoder-heading"><strong>共享编码器手动校准</strong><span class="${encoder.calibrationActive ? 'active' : ''}">${encoder.configured ? (encoder.calibrationActive ? '校准中' : '待机') : '未配置'}</span></div>
      <p>本向导不会驱动 ACE 或挤出机。开始计数后，请手动移动耗材，再填写实际移动长度。</p>
      <div class="sim-pulse-readout"><span>实时脉冲数</span><strong>${encoder.configured ? encoder.counts : '--'}</strong></div>
      <div class="sim-encoder-summary ${calibration.state}"><strong>${calibration.completedCount}/${calibration.segmentCount} 段</strong><span>${escapeHtml(calibration.message)}</span></div>
      <div class="sim-encoder-segments">${rows}</div>
      <div class="sim-encoder-actions"><label>每段移动长度（mm）<input id="sim-encoder-length" type="number" min="0.01" max="2000" step="0.01" value="${escapeHtml(state.encoderCalibrationLength)}" ${encoder.calibrationActive ? 'disabled' : ''}></label><button class="${button} primary" data-sim-encoder="start" ${attrDisabled(start)}>开始三段校准</button><button class="${button}" data-sim-encoder="record" ${attrDisabled(recordDecision)}>记录第 ${Math.min(calibration.completedCount + 1, calibration.segmentCount)} 段</button><button class="${button}" data-sim-encoder="finish" ${attrDisabled(finishDecision)}>完成并保存</button><button class="${button}" data-sim-encoder="reset" ${encoder.calibrationActive ? '' : 'disabled'}>重置分段</button><button class="${button} danger-text" data-sim-encoder="cancel" ${attrDisabled(cancel)}>取消</button></div>
      ${blocker ? `<p class="sim-inline-warning">${escapeHtml(blocker)}</p>` : ''}
    </div>
    <div class="sim-encoder-column sim-print-monitor">
      <div class="sim-encoder-heading"><strong>打印监测</strong><span class="monitor-${escapeHtml(monitor.tone)}">${encoder.configured ? escapeHtml(monitor.statusLabel) : '未配置'}</span></div>
      <div class="sim-monitor-metrics"><div><span>模式</span><strong>${escapeHtml(monitor.modeLabel)}</strong></div><div><span>检测长度</span><strong>${formatMonitorLength(monitor.detectionLength)}</strong></div><div><span>已挤出未动</span><strong>${formatMonitorLength(monitor.extrusionSinceMotion)}</strong></div><div><span>检测余量</span><strong>${formatMonitorLength(monitor.headroom)}</strong></div></div>
      ${issue ? `<div class="sim-monitor-issue"><strong>${escapeHtml(issue.message)}</strong>${issue.probableCause ? `<span>可能原因：${escapeHtml(issue.probableCause)}</span>` : ''}${contextLabel ? `<span>现场：${escapeHtml(contextLabel)}</span>` : ''}${monitor.pauseRequested ? '<span class="pause-note">打印已请求暂停，请排查后再恢复。</span>' : ''}<div class="sim-monitor-sensors">${renderMonitorSensors(issue)}</div></div>` : `<p>${monitor.mode === 'monitor' ? '监测模式只提示异常，不会请求暂停打印。' : monitor.mode === 'pause' ? '暂停保护检测到故障时会请求暂停打印。' : '打印监测当前关闭。'}</p>`}
    </div>
  </section>`
}

function renderDeviceStatus (device, viewModel) {
  const raw = device.raw
  const fanSpeed = Number(raw.fan_speed || 0)
  const upperPolicy = viewModel.status.path.sensorPolicy.upper
  const lowerPolicy = viewModel.status.path.sensorPolicy.lower
  const sensor = (value, role = '') => {
    const label = value === true ? '有料' : value === false ? '无料' : '未提供'
    if (role === 'upper') {
      const tone = value === true ? 'present' : value === false ? 'empty' : 'unknown'
      return `<strong class="acepro-sensor-status acepro-sensor-status--${tone}"><span class="acepro-sensor-status__dot"></span>控制闭环 · ${label}</strong>`
    }
    if (role === 'monitor-only') {
      return `<strong class="acepro-sensor-status acepro-sensor-status--monitor-only" title="当前读数：${label}。该传感器仅用于监测，不参与换料控制。"><span class="acepro-sensor-status__dot"></span>仅监测 · ${label}</strong>`
    }
    const tone = value === true ? 'present' : value === false ? 'empty' : 'unknown'
    return `<strong class="acepro-sensor-status acepro-sensor-status--${tone}"><span class="acepro-sensor-status__dot"></span>${label}</strong>`
  }
  const firstStageSensor = viewModel.usesFirstStageHubs
    ? `<div class="acepro-info-item"><span>一级五通传感器</span>${sensor(device.hubSensor)}</div>`
    : ''
  const pathLabel = viewModel.usesFirstStageHubs
    ? 'ACE -&gt; 一级五通 -&gt; 总五通 -&gt; 打印头'
    : 'ACE -&gt; 总五通 -&gt; 打印头'
  return `<section class="acepro-panel">
    <div class="acepro-panel__title">设备状态</div>
    <div class="acepro-info-grid">
      <div class="acepro-info-item"><span>型号</span><strong>${device.modelLabel}</strong></div>
      <div class="acepro-info-item"><span>运行状态</span><strong class="tone-${device.statusTone}">${device.connected ? (device.currentAction || '待机') : '离线'}</strong></div>
      <div class="acepro-info-item"><span>设备温度</span><strong>${device.temperatureLabel}</strong></div>
      <div class="acepro-info-item"><span>风扇转速</span><strong>${fanSpeed}%</strong></div>
      <div class="acepro-info-item"><span>RFID</span><strong>${device.rfidLabel}</strong></div>
      <div class="acepro-info-item"><span>当前装载</span><strong>${viewModel.status.system.currentToolLabel}</strong></div>
      <div class="acepro-info-item"><span>上方传感器</span>${sensor(viewModel.status.path.sensors.upper, 'upper')}</div>
      <div class="acepro-info-item"><span>上方送料超时</span><strong>${formatFeedTimeout(upperPolicy.feedTimeout)}</strong></div>
      <div class="acepro-info-item"><span>下方传感器</span>${sensor(viewModel.status.path.sensors.lower, lowerPolicy.monitorOnly ? 'monitor-only' : '')}</div>
      <div class="acepro-info-item"><span>挤出机标定距离</span><strong>${formatMonitorLength(lowerPolicy.bypassLoadLength)}</strong></div>
      ${firstStageSensor}
      <div class="acepro-info-item"><span>总五通传感器</span>${sensor(viewModel.status.path.sensors.rdm)}</div>
      <div class="acepro-info-item"><span>共享编码器</span>${renderEncoderStatus(viewModel.sharedEncoder)}</div>
      <div class="acepro-info-item"><span>编码器最低跟随比例</span><strong>${formatTrackingRatio(viewModel.sharedEncoder.minTrackingRatio)}</strong></div>
      <div class="acepro-info-item"><span>无限续料</span><strong>${viewModel.endlessSpool.enabled ? '已开启' : '已关闭'}</strong></div>
      <div class="acepro-info-item acepro-info-item--wide"><span>送料控制</span><strong>ACE 参考送料 -&gt; 上方传感器闭环终止</strong></div>
      <div class="acepro-info-item acepro-info-item--wide"><span>耗材路径</span><strong>${pathLabel}</strong></div>
    </div>
  </section>`
}

function renderDryer (device, status) {
  const start = canPerformAction(status, ACE_ACTIONS.START_DRYING, { device })
  const stop = canPerformAction(status, ACE_ACTIONS.STOP_DRYING, { device })
  return `<section class="acepro-panel">
    <div class="acepro-panel__title">烘干控制</div>
    <div class="acepro-dryer__row">
      <label>设定温度<div class="input-suffix"><input type="number" value="${device.dryer.targetTemperature || 45}" min="20" max="75"><span>°C</span></div></label>
      <label>烘干时长<div class="input-suffix"><input type="number" value="240" min="10" max="1440"><span>min</span></div></label>
    </div>
    <div class="acepro-dryer__status">
      <div class="acepro-info-item"><span>烘干状态</span><strong>${device.dryer.active ? '烘干中' : '未运行'}</strong></div>
      <div class="acepro-info-item"><span>目标温度</span><strong>${device.dryer.targetTemperature || '--'}°C</strong></div>
      <div class="acepro-info-item"><span>剩余时间</span><strong>${device.dryer.remainingMinutes || '--'} 分钟</strong></div>
    </div>
    <div class="acepro-dryer__actions">
      <button type="button" class="fluidd-button primary" data-dryer="${device.id}" ${attrDisabled(device.dryer.active ? stop : start)}>${device.dryer.active ? '停止烘干' : '开始烘干'}</button>
      <button type="button" class="fluidd-button text danger-text" ${attrDisabled(stop)}>停止烘干</button>
    </div>
  </section>`
}

function renderAceCard (viewModel, pageMode = false) {
  const selected = viewModel.devices.find(device => device.id === state.selectedDeviceId) || viewModel.devices[0]
  const connectionTone = selected.connected ? 'connected' : 'disconnected'
  const connectionLabel = selected.connected ? '已连接' : '未连接'
  const showExtra = pageMode || state.extraOpen
  const feed = canPerformAction(viewModel.status, ACE_ACTIONS.FEED, { device: selected, slot: selected.slots[0] })
  const retract = canPerformAction(viewModel.status, ACE_ACTIONS.RETRACT, { device: selected, slot: selected.slots[0] })
  const enableAssist = canPerformAction(viewModel.status, ACE_ACTIONS.ENABLE_FEED_ASSIST, { device: selected, slot: selected.slots[0] })
  const activeAssistDevice = viewModel.status.devices.find(device => device.id === viewModel.feedAssist.deviceId)
  const activeAssistSlot = activeAssistDevice?.slots[viewModel.feedAssist.slot]
  const disableAssist = viewModel.feedAssist.active && activeAssistDevice
    ? canPerformAction(viewModel.status, ACE_ACTIONS.DISABLE_FEED_ASSIST, { device: activeAssistDevice, slot: activeAssistSlot })
    : { allowed: false, reason: viewModel.feedAssist.active ? '后端未提供当前辅助送料槽位。' : '当前没有启用 ACE 辅助送料。' }
  const unload = canPerformAction(viewModel.status, ACE_ACTIONS.UNLOAD, { device: selected })
  const endless = canPerformAction(viewModel.status, ACE_ACTIONS.SET_ENDLESS_SPOOL)
  return `<div class="acepro-card ${pageMode ? 'acepro-card--page' : ''}">
    <div class="acepro-card__header">
      <div><div class="acepro-card__title">ACE Pro 管理中心</div><div class="acepro-card__subtitle">V2.5ahpha · 设备状态、烘干控制、料槽管理</div></div>
      <div class="acepro-card__connection acepro-card__connection--${connectionTone}"><span class="acepro-card__dot"></span>${connectionLabel}</div>
    </div>
    ${renderDeviceSwitch(viewModel)}
    ${renderGlobalCurrentTool(viewModel)}
    ${renderToolchangeMode(viewModel)}
    ${selected.readOnly ? '<div class="acepro-alert warning">此设备的物理动作已禁用；状态、RFID 和库存仍可使用。</div>' : ''}
    ${!selected.connected ? '<div class="acepro-alert error">设备连接已中断，当前显示上次状态；物理动作已禁用。</div>' : ''}
    <div class="acepro-card__top-grid">${renderDeviceStatus(selected, viewModel)}${renderDryer(selected, viewModel.status)}</div>
    <section class="acepro-panel acepro-panel--slots">
      <div class="acepro-panel__header"><div class="acepro-panel__title">料槽管理</div><div class="acepro-panel__tool-indicator">当前装载: ${viewModel.status.system.currentToolLabel}</div></div>
      <div class="acepro-slot-grid">${selected.slots.map(slot => renderSlotCard(selected, slot, viewModel.status)).join('')}</div>
    </section>
    <section class="acepro-panel">
      <div class="acepro-panel__title">手动送料</div>
      <div class="acepro-manual-controls">
        <label>料槽<select>${selected.slots.map(slot => `<option>${slot.tool} · ${slot.label}</option>`).join('')}</select></label>
        <label>长度<div class="input-suffix"><input type="number" value="50"><span>mm</span></div></label>
        <label>速度<div class="input-suffix"><input type="number" value="50"><span>mm/s</span></div></label>
        <button type="button" class="fluidd-button primary" data-generic="手动送料" ${attrDisabled(feed)}>送料</button>
        <button type="button" class="fluidd-button" data-generic="手动回抽" ${attrDisabled(retract)}>回抽</button>
      </div>
    </section>
    <section class="acepro-panel acepro-panel--feed-assist">
      <div class="acepro-panel__header"><div class="acepro-panel__title">ACE 辅助送料</div><div class="acepro-feed-assist__status ${viewModel.feedAssist.active ? 'active' : ''}">当前：${escapeHtml(viewModel.feedAssist.label)}</div></div>
      <div class="acepro-feed-assist__controls"><label>辅助送料槽位<select id="sim-feed-assist-slot">${selected.slots.map(slot => `<option value="${slot.index}">${slot.tool} · ${slot.materialLabel}</option>`).join('')}</select></label>
        <button type="button" class="fluidd-button primary" data-enable-feed-assist="${selected.id}" ${attrDisabled(enableAssist)}>${viewModel.feedAssist.active ? '切换到所选槽位' : '启用辅助送料'}</button>
        <button type="button" class="fluidd-button danger-text" data-disable-feed-assist ${attrDisabled(disableAssist)}>停用辅助送料</button>
      </div>
    </section>
    <section class="acepro-panel acepro-panel--quick">
      <div class="acepro-panel__title">快捷操作</div>
      <div class="acepro-quick-actions">
        <button type="button" class="fluidd-button primary" data-refresh>刷新状态</button>
        <button type="button" class="fluidd-button" data-unload ${attrDisabled(unload)}>卸载当前耗材</button>
        <button type="button" class="fluidd-button" data-generic="保存库存">保存库存</button>
        <button type="button" class="fluidd-button text" data-generic="诊断传感器">诊断传感器</button>
        <label class="inline-switch" title="${escapeHtml(endless.reason)}">无限续料 · 材料与颜色一致<input type="checkbox" data-endless ${viewModel.endlessSpool.enabled ? 'checked' : ''} ${attrDisabled(endless)}></label>
      </div>
    </section>
    ${pageMode ? '' : `<button type="button" class="acepro-more-toggle" data-extra><span>更多功能</span><span>${showExtra ? '⌃' : '⌄'}</span></button>`}
    ${showExtra ? `<div class="acepro-extra-functions"><section class="acepro-panel"><div class="acepro-panel__title">诊断与维护</div>${renderEncoderMaintenance(viewModel)}<div class="acepro-advanced-actions"><button class="fluidd-button" data-generic="运行诊断">运行诊断</button><button class="fluidd-button danger-text" data-generic="恢复设备">恢复设备</button></div><p class="diagnostic-line">${escapeHtml(selected.diagnostics.port || '--')} · 重连 ${selected.diagnostics.reconnects} 次</p></section></div>` : ''}
  </div>`
}

function fluiddSidebar (active) {
  const items = ['控制台', '任务', '历史', '温度', '宏', '设置']
  return `<aside class="fluidd-sidebar">
    <div class="fluidd-logo"><span>F</span><strong>fluidd</strong></div>
    <nav>${items.map(item => `<button type="button">${item}</button>`).join('')}<button type="button" class="${active === 'ace' ? 'active' : ''}" data-open-page>ACE Pro 管理中心</button></nav>
    <div class="fluidd-sidebar__footer"><span class="sim-live-dot"></span>SV08 · 就绪</div>
  </aside>`
}

function renderContextWidgets () {
  return `<aside class="context-widgets">
    <section class="fluidd-widget compact-widget"><div class="fluidd-widget__header"><strong>打印状态</strong><span>待机</span></div><div class="job-state"><strong>准备就绪</strong><span>0 / 0 层</span><div class="progress-track"><i></i></div></div></section>
    <section class="fluidd-widget compact-widget"><div class="fluidd-widget__header"><strong>温度</strong><button type="button" class="icon-action" title="刷新">↻</button></div><div class="temperature-row"><span>喷嘴</span><strong>27.4°C</strong><i style="--level:35%"></i></div><div class="temperature-row"><span>热床</span><strong>25.8°C</strong><i style="--level:22%"></i></div></section>
    <section class="fluidd-widget compact-widget"><div class="fluidd-widget__header"><strong>工具头</strong><span>绝对坐标</span></div><div class="axis-grid"><span>X<strong>110.0</strong></span><span>Y<strong>110.0</strong></span><span>Z<strong>24.6</strong></span></div></section>
  </aside>`
}

function renderFluidd (viewModel, pageMode = false) {
  return `<div class="fluidd-shell">
    ${fluiddSidebar(pageMode ? 'ace' : 'dashboard')}
    <div class="fluidd-main">
      <header class="fluidd-topbar"><div><strong>${pageMode ? 'ACE Pro 管理中心' : '控制台'}</strong><span>SV08</span></div><div class="topbar-status"><span><i class="green"></i>Klipper</span><span><i class="green"></i>Moonraker</span><button type="button" class="icon-action" title="刷新" data-refresh>↻</button></div></header>
      <div class="fluidd-content ${pageMode ? 'fluidd-content--page' : ''}">
        ${pageMode ? `<div class="fluidd-page-heading"><div><h2>ACE Pro 管理中心</h2><p>V2.5ahpha · ${viewModel.connectedDeviceCount}/${viewModel.configuredDeviceCount} 台设备在线 · ${viewModel.tools[0].tool}-${viewModel.tools.at(-1).tool}</p></div></div>` : ''}
        <div class="fluidd-dashboard-grid ${pageMode ? 'page-grid' : ''}">
          <section class="fluidd-widget ace-widget"><div class="fluidd-widget__header"><strong>ACE Pro 管理中心</strong>${pageMode ? '<span>多设备管理</span>' : '<button type="button" class="fluidd-button text" data-open-page>打开页面</button>'}</div><div class="fluidd-widget__body">${renderAceCard(viewModel, pageMode)}</div></section>
          ${pageMode ? '' : renderContextWidgets()}
        </div>
      </div>
    </div>
  </div>`
}

const standaloneTabs = [
  ['overview', '总览与换料'], ['inventory', '库存'], ['maintenance', '维护'], ['drying', '烘干'],
  ['endless', '无限续料'], ['calibration', '校准'], ['diagnostics', '诊断与恢复'],
]

function standaloneSlot (device, slot, status) {
  const action = slot.active ? ACE_ACTIONS.UNLOAD : ACE_ACTIONS.SELECT_TOOL
  const decision = canPerformAction(status, action, { device, slot })
  return `<article class="standalone-slot ${slot.active ? 'active' : ''}">
    <div class="standalone-slot__title"><span class="swatch" style="background:${escapeHtml(slot.color)}"></span><strong>${escapeHtml(slot.materialLabel)}</strong></div>
    <div class="standalone-slot__route"><strong>${slot.tool}</strong><span>${slot.label}</span></div>
    <p>${slot.remainingLabel}<br>RFID ${slot.rfidLabel}</p>
    <button type="button" class="standalone-button ${slot.active ? 'danger' : 'primary'}" data-slot-action="${device.id}:${slot.index}" ${attrDisabled(decision)}>${slot.active ? '卸载' : '更换耗材'}</button>
  </article>`
}

function renderStandaloneOverview (viewModel) {
  const device = viewModel.devices.find(item => item.id === state.selectedDeviceId) || viewModel.devices[0]
  const dryer = canPerformAction(viewModel.status, ACE_ACTIONS.START_DRYING, { device })
  return `<div class="standalone-heading"><div><h2>设备与换料</h2><p>${viewModel.connectedDeviceCount}/${viewModel.configuredDeviceCount} 台在线 · 工具 ${viewModel.tools[0].tool}-${viewModel.tools.at(-1).tool}</p></div></div>
    <div class="standalone-device-list"><section class="standalone-device">
      <div class="standalone-device__header"><div><span class="status-dot ${device.statusTone}"></span><strong>${device.name}</strong><small>${device.modelLabel} · ${device.connectionLabel}</small></div><div><span>${device.temperatureLabel}</span><span>湿度 ${device.humidityLabel}</span>${device.readOnly ? '<span class="readonly">只读</span>' : ''}</div></div>
      ${device.readOnly ? '<p class="standalone-warning">状态读取和槽位资料可用，物理动作保持禁用。</p>' : ''}
      <div class="standalone-slot-grid">${device.slots.map(slot => standaloneSlot(device, slot, viewModel.status)).join('')}</div>
      <div class="standalone-device__footer"><button class="standalone-button" data-refresh>刷新耗材数据</button><button class="standalone-button primary" data-dryer="${device.id}" ${attrDisabled(dryer)}>打开烘干设置</button></div>
    </section></div>`
}

function renderStandaloneInventory (viewModel) {
  const device = viewModel.devices.find(item => item.id === state.selectedDeviceId) || viewModel.devices[0]
  return `<div class="standalone-heading"><div><h2>工具与库存</h2><p>按设备配置顺序固定映射</p></div></div><div class="table-wrap"><table><thead><tr><th>工具</th><th>设备 / 槽位</th><th>材料</th><th>颜色</th><th>余量</th><th>RFID</th></tr></thead><tbody>${device.slots.map(slot => `<tr><td><strong>${slot.tool}${slot.active ? ' · 当前' : ''}</strong></td><td>${device.name} / ${slot.label}</td><td>${slot.materialLabel}</td><td><span class="swatch" style="background:${slot.color}"></span></td><td>${slot.remainingLabel}</td><td>${slot.rfidLabel}</td></tr>`).join('')}</tbody></table></div>`
}

function renderStandaloneControls (viewModel, tab) {
  const device = viewModel.devices.find(item => item.id === state.selectedDeviceId) || viewModel.devices[0]
  const titleMap = {
    maintenance: ['维护动作', '共享路径动作按设备能力和打印状态执行门禁'],
    drying: ['烘干控制', '目标温度与时长由后端再次校验'],
    endless: ['无限续料', '候选槽位可以跨设备选择'],
    calibration: ['共享编码器校准', '手动移动耗材完成脉冲与长度标定'],
    diagnostics: ['诊断与恢复', '连接、身份和错误状态'],
  }
  const [title, subtitle] = titleMap[tab]
  if (tab === 'endless') {
    return `<div class="standalone-heading"><div><h2>${title}</h2><p>${subtitle}</p></div></div><section class="standalone-control"><h3>共享打印头</h3><p>状态：<strong>${viewModel.endlessSpool.enabled ? '已启用' : '已停用'}</strong></p><div class="standalone-action-row"><label>匹配方式<select><option>材料与颜色一致</option><option>仅材料一致</option></select></label><button class="standalone-button primary" data-endless>${viewModel.endlessSpool.enabled ? '停用无限续料' : '启用无限续料'}</button></div></section>`
  }
  if (tab === 'calibration') {
    return `<div class="standalone-heading"><div><h2>${title}</h2><p>${subtitle}</p></div></div>${renderEncoderMaintenance(viewModel, true)}`
  }
  const deviceControls = `<div class="standalone-control-grid"><section class="standalone-control"><h3>${device.name} · ${device.modelLabel}</h3><p>${tab === 'diagnostics' ? `${device.diagnostics.port || '--'} · 重连 ${device.diagnostics.reconnects} 次` : `${device.connectionLabel} · ${device.readOnly ? '物理动作只读' : '动作按能力开放'}`}</p><div class="standalone-action-row">${tab === 'maintenance' ? `<label>长度（mm）<input type="number" value="50"></label><button class="standalone-button" data-generic="手动送丝">手动送丝</button><button class="standalone-button" data-generic="手动回抽">手动回抽</button><button class="standalone-button primary" data-enable-feed-assist="${device.id}">启用辅助送料</button>` : ''}${tab === 'drying' ? '<label>温度（°C）<input type="number" value="45"></label><label>时长（分钟）<input type="number" value="240"></label><button class="standalone-button primary" data-generic="开始烘干">开始烘干</button>' : ''}${tab === 'diagnostics' ? '<button class="standalone-button" data-generic="运行诊断">运行诊断</button><button class="standalone-button danger" data-generic="执行恢复">执行恢复</button>' : ''}</div></section></div>`
  return `<div class="standalone-heading"><div><h2>${title}</h2><p>${subtitle}</p></div></div>${deviceControls}${tab === 'maintenance' ? renderEncoderMaintenance(viewModel, true) : ''}`
}

function renderStandalone (viewModel) {
  let content = renderStandaloneOverview(viewModel)
  if (state.standaloneTab === 'inventory') content = renderStandaloneInventory(viewModel)
  else if (state.standaloneTab !== 'overview') content = renderStandaloneControls(viewModel, state.standaloneTab)
  const transaction = viewModel.status.transaction.active ? viewModel.status.transaction.phase : '空闲'
  const pathSummary = viewModel.status.system.pathLocked ? '占用' : '空闲'
  const pathActivity = viewModel.status.transaction.active ? `${pathSummary} · ${transaction}` : pathSummary
  const encoder = viewModel.sharedEncoder
  const upper = viewModel.status.path.sensors.upper === true ? '有料' : viewModel.status.path.sensors.upper === false ? '无料' : '未提供'
  const lower = viewModel.status.path.sensors.lower === true ? '有料' : viewModel.status.path.sensors.lower === false ? '无料' : '未提供'
  const lowerPolicy = viewModel.status.path.sensorPolicy.lower.bypassed ? `仅监测 · ${lower}` : `参与控制 · ${lower}`
  const lowerTitle = viewModel.status.path.sensorPolicy.lower.bypassed
    ? `当前读数：${lower}。仅用于监测，不参与换料控制。`
    : `当前读数：${lower}。该传感器参与换料控制。`
  const selected = viewModel.devices.find(item => item.id === state.selectedDeviceId) || viewModel.devices[0]
  const unload = viewModel.status.system.currentTool
    ? canPerformAction(viewModel.status, ACE_ACTIONS.UNLOAD, { device: selected })
    : { allowed: false, reason: '当前没有已装载耗材。' }
  return `<div class="standalone-app">
    <header class="standalone-header"><div class="standalone-brand"><span>ACE</span><div><h2>ACE Pro 管理中心</h2><p>V2.5ahpha · ${viewModel.connectedDeviceCount}/${viewModel.configuredDeviceCount} 台设备在线</p></div></div><div><button class="standalone-button danger" data-unload ${attrDisabled(unload)}>卸载当前耗材</button><button class="icon-action light" data-refresh title="刷新">↻</button></div></header>
    <section class="standalone-metrics"><div><span>打印状态</span><strong>${escapeHtml(viewModel.status.system.printState)}</strong></div><div><span>当前工具</span><strong>${escapeHtml(viewModel.status.system.currentToolLabel)}</strong></div><div><span>共享路径</span><strong>${escapeHtml(pathActivity)}</strong></div><div><span>换料模式</span><strong>${viewModel.toolchange.mode === 'manual' ? '手动模式' : viewModel.toolchange.ready ? '自动换料已就绪' : '自动换料未就绪'}</strong></div><div><span>ACE 送料</span><strong>参考送料 · 上方传感器闭环终止</strong></div><div><span>上方传感器</span><strong>控制闭环 · ${upper}</strong></div><div><span>下方传感器</span><strong title="${lowerTitle}">${lowerPolicy}</strong></div><div><span>辅助送料</span><strong>${escapeHtml(viewModel.feedAssist.label)}</strong></div><div><span>共享编码器</span><strong class="encoder-tone-${escapeHtml(encoder.tone)}" title="${escapeHtml(encoder.fault?.message || encoder.summaryLabel)}">${escapeHtml(encoder.summaryLabel)}</strong></div></section>
    <nav class="standalone-tabs">${standaloneTabs.map(([id, label]) => `<button type="button" class="${state.standaloneTab === id ? 'active' : ''}" data-standalone-tab="${id}">${label}</button>`).join('')}</nav>
    <div class="standalone-workspace">${renderDeviceSwitch(viewModel)}${renderToolchangeMode(viewModel)}${content}</div>
  </div>`
}

function render () {
  const viewModel = getViewModel()
  observeToolchangeNotices(viewModel.status)
  observePrintMonitorEvent(viewModel.status)
  syncControls()
  syncUrl()
  if (state.view === 'standalone') root.innerHTML = renderStandalone(viewModel)
  else root.innerHTML = renderFluidd(viewModel, state.view === 'page')
}

function findRawTarget (value) {
  const [deviceId, slotText] = value.split(':')
  const device = state.rawStatus.devices.find(item => item.id === deviceId)
  return { device, slot: device?.slots[Number(slotText)] }
}

function unloadCurrent () {
  state.rawStatus.system.current_tool = null
  state.rawStatus.path.state = 'empty'
  state.rawStatus.devices.forEach(device => device.slots.forEach(slot => { slot.loaded = false }))
}

document.addEventListener('click', event => {
  const viewButton = event.target.closest('[data-view]')
  if (viewButton) {
    state.view = viewButton.dataset.view
    render()
    return
  }

  const currentToolJump = event.target.closest('[data-jump-current-tool]')
  if (currentToolJump) {
    state.selectedDeviceId = currentToolJump.dataset.jumpCurrentTool
    render()
    return
  }

  const deviceButton = event.target.closest('[data-device]')
  if (deviceButton) {
    state.selectedDeviceId = deviceButton.dataset.device
    render()
    return
  }

  if (event.target.closest('[data-open-page]')) {
    state.view = 'page'
    render()
    return
  }

  const tab = event.target.closest('[data-standalone-tab]')
  if (tab) {
    state.standaloneTab = tab.dataset.standaloneTab
    render()
    return
  }

  const slotAction = event.target.closest('[data-slot-action]')
  if (slotAction) {
    const { device, slot } = findRawTarget(slotAction.dataset.slotAction)
    const viewModel = getViewModel()
    const viewDevice = viewModel.status.devices.find(item => item.id === device?.id)
    const viewSlot = viewDevice?.slots[slot?.slot]
    const action = viewSlot?.loaded ? ACE_ACTIONS.UNLOAD : ACE_ACTIONS.SELECT_TOOL
    const decision = viewDevice && viewSlot
      ? canPerformAction(viewModel.status, action, { device: viewDevice, slot: viewSlot })
      : { allowed: false, reason: '目标槽位不存在。' }
    if (!decision.allowed) {
      toast('操作不可用', decision.reason)
      return
    }
    if (state.rawStatus.system.current_tool === slot.tool) {
      unloadCurrent()
      toast('模拟卸载完成', `${slot.tool} 已退出共享路径`)
    } else {
      unloadCurrent()
      state.rawStatus.system.current_tool = slot.tool
      state.rawStatus.path.state = 'nozzle'
      slot.loaded = true
      toast('模拟换料完成', `${slot.tool} · ${slot.material}`)
    }
    render()
    return
  }

  const enableFeedAssist = event.target.closest('[data-enable-feed-assist]')
  if (enableFeedAssist) {
    const device = state.rawStatus.devices.find(item => item.id === enableFeedAssist.dataset.enableFeedAssist)
    const slot = Number(document.querySelector('#sim-feed-assist-slot')?.value ?? 0)
    if (!device?.slots[slot]) return
    state.rawStatus.feed_assist = { active: true, device_id: device.id, slot, tool: device.slots[slot].tool }
    toast('辅助送料已启用', `${device.slots[slot].tool} · ${device.name}`)
    render()
    return
  }

  if (event.target.closest('[data-disable-feed-assist]')) {
    const active = state.rawStatus.feed_assist
    if (!active?.active) return
    const label = active.tool || '当前槽位'
    state.rawStatus.feed_assist = { active: false, device_id: '', slot: null, tool: '' }
    toast('辅助送料已停用', label)
    render()
    return
  }

  const dryerButton = event.target.closest('[data-dryer]')
  if (dryerButton) {
    const device = state.rawStatus.devices.find(item => item.id === dryerButton.dataset.dryer)
    const viewModel = getViewModel()
    const viewDevice = viewModel.status.devices.find(item => item.id === device?.id)
    const action = viewDevice?.dryer.active ? ACE_ACTIONS.STOP_DRYING : ACE_ACTIONS.START_DRYING
    if (!viewDevice || !canPerformAction(viewModel.status, action, { device: viewDevice }).allowed) return
    device.dryer.active = !device.dryer.active
    device.dryer.remaining_minutes = device.dryer.active ? 240 : 0
    toast(device.dryer.active ? '模拟烘干已开始' : '模拟烘干已停止', device.name)
    render()
    return
  }

  if (event.target.closest('[data-endless]')) {
    const viewModel = getViewModel()
    if (!canPerformAction(viewModel.status, ACE_ACTIONS.SET_ENDLESS_SPOOL).allowed) return
    state.rawStatus.endless_spool.enabled = !state.rawStatus.endless_spool.enabled
    toast('无限续料', state.rawStatus.endless_spool.enabled ? '已开启' : '已关闭')
    render()
    return
  }

  if (event.target.closest('[data-unload]')) {
    const current = state.rawStatus.system.current_tool
    if (current === null) return
    unloadCurrent()
    toast('模拟卸载完成', `${current} 已退出共享路径`)
    render()
    return
  }

  if (event.target.closest('[data-refresh]')) {
    state.rawStatus.generated_at = new Date().toISOString()
    toast('状态已刷新', '本地模拟数据已更新')
    render()
    return
  }

  if (event.target.closest('[data-extra]')) {
    state.extraOpen = !state.extraOpen
    render()
    return
  }

  const encoderAction = event.target.closest('[data-sim-encoder]')
  if (encoderAction) {
    const step = encoderAction.dataset.simEncoder
    const encoder = state.rawStatus.path.encoders.shared
    if (step === 'reset') {
      state.encoderCalibrationSegments = []
      state.encoderCalibrationLastCounts = Number(encoder.counts || 0)
      toast('分段结果已重置', '请从当前位置开始第 1 段测量。')
      render()
      return
    }
    if (step === 'record') {
      const currentCounts = Number(encoder.counts || 0)
      const pulses = currentCounts - Number(state.encoderCalibrationLastCounts)
      state.encoderCalibrationSegments.push({ length: Number(state.encoderCalibrationLength), pulses })
      state.encoderCalibrationLastCounts = currentCounts
      const evaluation = evaluateEncoderCalibrationSegments(state.encoderCalibrationSegments)
      const pulseDetail = pulses >= ENCODER_CALIBRATION_DEFAULTS.minimumPulses
        ? `${pulses} 脉冲`
        : `检测到 ${pulses} 脉冲，至少需要 ${ENCODER_CALIBRATION_DEFAULTS.minimumPulses} 个正向脉冲；请重置分段后重测。`
      toast(pulses >= ENCODER_CALIBRATION_DEFAULTS.minimumPulses ? `第 ${evaluation.completedCount} 段已记录` : '本段测量已拒绝', pulseDetail)
      render()
      return
    }
    const action = step === 'start'
      ? ACE_ACTIONS.ENCODER_CALIBRATION_START
      : step === 'finish'
        ? ACE_ACTIONS.ENCODER_CALIBRATION_FINISH
        : ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL
    const viewModel = getViewModel()
    const decision = canPerformAction(viewModel.status, action)
    if (!decision.allowed) {
      toast('操作不可用', decision.reason)
      return
    }
    if (step === 'start') {
      encoder.calibration_active = true
      state.calibrationStartCounts = Number(encoder.counts || 0)
      state.encoderCalibrationSegments = []
      state.encoderCalibrationLastCounts = Number(encoder.counts || 0)
      toast('编码器计数已开始', '请手动移动耗材；模拟器不会驱动任何设备。')
    } else if (step === 'finish') {
      const evaluation = evaluateEncoderCalibrationSegments(state.encoderCalibrationSegments)
      if (!evaluation.canSave) {
        toast('校准结果已拒绝', evaluation.message)
        return
      }
      encoder.calibration_active = false
      encoder.calibrated = true
      encoder.resolution = evaluation.totalLength / evaluation.totalPulses
      state.calibrationStartCounts = null
      state.encoderCalibrationSegments = []
      state.encoderCalibrationLastCounts = null
      toast('共享编码器校准已保存', `${evaluation.totalLength} mm · ${evaluation.totalPulses} 脉冲`)
    } else {
      encoder.calibration_active = false
      state.calibrationStartCounts = null
      state.encoderCalibrationSegments = []
      state.encoderCalibrationLastCounts = null
      toast('共享编码器校准已取消', '未保存新的分辨率。')
    }
    syncCalibrationTimer()
    render()
    return
  }

  const save = event.target.closest('[data-save-slot]')
  if (save) {
    const { slot } = findRawTarget(save.dataset.saveSlot)
    toast('槽位资料已保存', slot?.tool || '')
    return
  }

  const clear = event.target.closest('[data-clear-slot]')
  if (clear) {
    const { slot } = findRawTarget(clear.dataset.clearSlot)
    if (!slot) return
    slot.state = 'empty'
    slot.material = 'unknown'
    slot.rfid = 0
    slot.remaining_percent = 0
    toast('槽位已清空', slot.tool)
    render()
    return
  }

  const generic = event.target.closest('[data-generic]')
  if (generic) toast(`${generic.dataset.generic}已模拟`, '没有向打印机发送命令')
})

document.addEventListener('input', event => {
  if (event.target.id !== 'sim-encoder-length') return
  state.encoderCalibrationLength = event.target.value
  const finish = document.querySelector('[data-sim-encoder="finish"]')
  if (!finish) return
  const length = Number(event.target.value)
  const valid = Number.isFinite(length) && length >= 0.01 && length <= 2000 && event.target.validity.valid
  const evaluation = evaluateEncoderCalibrationSegments(state.encoderCalibrationSegments)
  finish.disabled = !valid || !evaluation.canSave
  finish.title = valid ? evaluation.message : '每段移动长度必须在 0.01..2000 mm 之间。'
})

document.addEventListener('change', event => {
  const material = event.target.closest('[data-material]')
  if (material) {
    const { slot } = findRawTarget(material.dataset.material)
    if (slot) slot.material = material.value
    render()
    return
  }
  const color = event.target.closest('[data-color]')
  if (color) {
    const { slot } = findRawTarget(color.dataset.color)
    if (slot) slot.color = color.value
    render()
  }
})

noticeButton.addEventListener('click', emitToolchangeNotice)

countSelect.addEventListener('change', () => {
  state.deviceCount = Number(countSelect.value)
  resetStatus()
  render()
})

modelsSelect.addEventListener('change', () => {
  state.modelMode = modelsSelect.value
  resetStatus()
  render()
})

scenarioSelect.addEventListener('change', () => {
  state.scenario = scenarioSelect.value
  resetStatus()
  render()
})

encoderSelect.addEventListener('change', () => {
  state.encoderScenario = encoderSelect.value
  resetStatus()
  render()
})

resetStatus()
render()
