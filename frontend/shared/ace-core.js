/*
 * Ace Pro Control Center shared frontend core, version V2.5ahpha.
 *
 * The control center is informed by the SV08 interaction model. It does
 * not contain protocol frames, G-code generation, or printer-specific logic.
 */

export const ACE_ENDPOINTS = Object.freeze({
  status: '/server/ace/status',
  action: '/server/ace/action',
})

export const ACE_ACTIONS = Object.freeze({
  REFRESH: 'refresh',
  SELECT_TOOL: 'select_tool',
  UNLOAD: 'unload',
  FEED: 'feed',
  RETRACT: 'retract',
  ENABLE_FEED_ASSIST: 'enable_feed_assist',
  DISABLE_FEED_ASSIST: 'disable_feed_assist',
  SET_SLOT: 'set_slot',
  START_DRYING: 'start_drying',
  STOP_DRYING: 'stop_drying',
  SET_ENDLESS_SPOOL: 'set_endless_spool',
  ENCODER_CALIBRATION_START: 'encoder_calibration_start',
  ENCODER_CALIBRATION_FINISH: 'encoder_calibration_finish',
  ENCODER_CALIBRATION_CANCEL: 'encoder_calibration_cancel',
  CALIBRATE: 'calibrate',
  SAVE_CALIBRATION: 'save_calibration',
  CANCEL_CALIBRATION: 'cancel_calibration',
  DIAGNOSE: 'diagnose',
  RECOVER: 'recover',
})

export const ACE_ASSIST_ONLY_MESSAGE = 'ACE 未配置，仅可使用手动辅助送料；自动换料不可用'

export const ENCODER_CALIBRATION_DEFAULTS = Object.freeze({
  segmentCount: 3,
  segmentLength: 150,
  passDeviationPercent: 5,
  warningDeviationPercent: 10,
  minimumPulses: 2,
})

export function evaluateEncoderCalibrationSegments (segments, options = {}) {
  const segmentCount = Number.isInteger(options.segmentCount) && options.segmentCount > 0
    ? options.segmentCount
    : ENCODER_CALIBRATION_DEFAULTS.segmentCount
  const passLimit = Number.isFinite(Number(options.passDeviationPercent))
    ? Number(options.passDeviationPercent)
    : ENCODER_CALIBRATION_DEFAULTS.passDeviationPercent
  const warningLimit = Number.isFinite(Number(options.warningDeviationPercent))
    ? Number(options.warningDeviationPercent)
    : ENCODER_CALIBRATION_DEFAULTS.warningDeviationPercent
  const minimumPulses = Number.isFinite(Number(options.minimumPulses))
    ? Math.max(1, Number(options.minimumPulses))
    : ENCODER_CALIBRATION_DEFAULTS.minimumPulses
  const source = Array.isArray(segments) ? segments.slice(0, segmentCount) : []
  const normalized = source.map((segment, index) => {
    const length = Number(segment?.length)
    const pulses = Number(segment?.pulses)
    const valid = Number.isFinite(length) && length > 0 && Number.isFinite(pulses) && pulses >= minimumPulses
    return {
      index,
      length: Number.isFinite(length) && length > 0 ? length : 0,
      pulses: Number.isFinite(pulses) ? pulses : 0,
      resolution: valid ? length / pulses : null,
      valid,
    }
  })
  const validResolutions = normalized.filter(segment => segment.valid).map(segment => segment.resolution)
  const meanResolution = validResolutions.length
    ? validResolutions.reduce((sum, value) => sum + value, 0) / validResolutions.length
    : null
  const results = normalized.map(segment => Object.freeze({
    ...segment,
    deviationPercent: segment.valid && meanResolution > 0
      ? Math.abs(segment.resolution - meanResolution) / meanResolution * 100
      : null,
  }))
  const complete = results.length === segmentCount
  const invalid = results.some(segment => !segment.valid)
  const maxDeviationPercent = results.reduce((maximum, segment) => (
    segment.deviationPercent === null ? maximum : Math.max(maximum, segment.deviationPercent)
  ), 0)
  let state = 'incomplete'
  if (invalid) state = 'rejected'
  else if (complete && maxDeviationPercent > warningLimit) state = 'rejected'
  else if (complete && maxDeviationPercent > passLimit) state = 'warning'
  else if (complete) state = 'passed'
  const messages = {
    incomplete: `请完成 ${segmentCount} 段测量。`,
    passed: `三段结果一致，最大偏差 ${maxDeviationPercent.toFixed(1)}%，可以保存。`,
    warning: `最大偏差 ${maxDeviationPercent.toFixed(1)}%，结果有波动；确认压紧轮和耗材路径后仍可保存。`,
    rejected: invalid
      ? '至少一段没有获得有效脉冲，已拒绝保存，请重测。'
      : `最大偏差 ${maxDeviationPercent.toFixed(1)}%，超过 10%，已拒绝保存，请检查打滑并重测。`,
  }
  return Object.freeze({
    segmentCount,
    completedCount: results.length,
    complete,
    state,
    canSave: complete && !invalid && maxDeviationPercent <= warningLimit,
    meanResolution,
    maxDeviationPercent,
    totalLength: results.reduce((sum, segment) => sum + segment.length, 0),
    totalPulses: results.reduce((sum, segment) => sum + Math.max(0, segment.pulses), 0),
    message: messages[state],
    segments: Object.freeze(results),
  })
}

const ACTION_SET = new Set(Object.values(ACE_ACTIONS))
const DEVICE_ID = /^ace([0-3])$/
const TOOL_ID = /^T(?:\d|1[0-5])$/
const MODELS = new Set(['ace1', 'ace2', 'auto'])
const READY_DEVICE_STATES = new Set(['idle', 'ready', 'standby', 'online', 'complete', 'completed'])
const ERROR_DEVICE_STATES = new Set(['error', 'fault', 'failed', 'alarm'])
const TOOLCHANGE_MODES = new Set(['manual', 'automatic'])
const ENCODER_MODES = new Set(['off', 'monitor', 'protect'])
const PRINT_MONITOR_MODES = new Set(['off', 'monitor', 'pause'])
const TOOLCHANGE_BLOCKED_LABELS = Object.freeze({
  manual_mode: '自动换料未启用，当前仅可使用手动功能。',
  physical_actions_disabled: 'ACE 物理动作尚未启用。',
  machine_hooks_incomplete: '自动换料所需机器宏尚未配置完整。',
  machine_macros_not_configured: '自动换料所需机器宏尚未配置完整。',
  path_sensors_incomplete: '自动换料所需路径传感器尚未配置完整。',
  lower_sensor_bypass_uncalibrated: '上方传感器触发后，挤出机定距送料尚未校准。',
  total_hub_sensor_missing: '多 ACE 自动换料必须配置总五通传感器。',
  branch_clearance_incomplete: '一级五通分支回退距离尚未校准。',
  path_state_unknown: '耗材路径状态未知，请先检查传感器。',
})
const AUTOMATIC_TOOLCHANGE_ACTIONS = new Set([
  ACE_ACTIONS.SELECT_TOOL,
  ACE_ACTIONS.UNLOAD,
  ACE_ACTIONS.SET_ENDLESS_SPOOL,
])
const ENCODER_CALIBRATION_ACTIONS = new Set([
  ACE_ACTIONS.ENCODER_CALIBRATION_START,
  ACE_ACTIONS.ENCODER_CALIBRATION_FINISH,
  ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL,
])
const DEFAULT_MATERIAL_TYPES = Object.freeze([
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
const PHYSICAL_ACTIONS = new Set([
  ACE_ACTIONS.SELECT_TOOL,
  ACE_ACTIONS.UNLOAD,
  ACE_ACTIONS.FEED,
  ACE_ACTIONS.RETRACT,
  ACE_ACTIONS.ENABLE_FEED_ASSIST,
  ACE_ACTIONS.DISABLE_FEED_ASSIST,
  ACE_ACTIONS.START_DRYING,
  ACE_ACTIONS.STOP_DRYING,
  ACE_ACTIONS.CALIBRATE,
  ACE_ACTIONS.SAVE_CALIBRATION,
  ACE_ACTIONS.CANCEL_CALIBRATION,
])
const PRINT_STATE_GATED_ACTIONS = new Set([
  ...PHYSICAL_ACTIONS,
  ...ENCODER_CALIBRATION_ACTIONS,
  ACE_ACTIONS.RECOVER,
])
const CONNECTION_OPTIONAL_ACTIONS = new Set([
  ACE_ACTIONS.REFRESH,
  ACE_ACTIONS.DIAGNOSE,
  ACE_ACTIONS.RECOVER,
  ACE_ACTIONS.SET_SLOT,
  ACE_ACTIONS.SET_ENDLESS_SPOOL,
  ...ENCODER_CALIBRATION_ACTIONS,
])

const ACTION_LABELS = Object.freeze({
  refresh: '刷新',
  select_tool: '更换耗材',
  unload: '卸载耗材',
  feed: '手动送丝',
  retract: '手动回抽',
  enable_feed_assist: '启用 ACE 辅助送料',
  disable_feed_assist: '停用 ACE 辅助送料',
  set_slot: '保存槽位',
  start_drying: '开始烘干',
  stop_drying: '停止烘干',
  set_endless_spool: '设置无限续料',
  encoder_calibration_start: '开始共享编码器校准',
  encoder_calibration_finish: '完成共享编码器校准',
  encoder_calibration_cancel: '取消共享编码器校准',
  calibrate: '开始校准',
  save_calibration: '保存校准',
  cancel_calibration: '取消校准',
  diagnose: '运行诊断',
  recover: '执行恢复',
})

const MATERIAL_LABELS = Object.freeze({
  pla: 'PLA',
  petg: 'PETG',
  abs: 'ABS',
  asa: 'ASA',
  tpu: 'TPU',
  pa: 'PA',
  pc: 'PC',
  hips: 'HIPS',
  pva: 'PVA',
  unknown: '未设置',
})

const CHINESE_TEXT = /[\u3400-\u9fff]/
const BACKEND_CODE_MESSAGES = Object.freeze({
  ace_action_rejected: 'ACE 拒绝执行此操作。',
  ace_api_error: 'ACE 请求失败。',
  ace_busy: '共享耗材路径正忙，请等待当前操作完成。',
  ace_error: 'ACE 操作未完成。',
  ace_not_loaded: 'Klipper 尚未加载 ACE 驱动。',
  ace2_read_only: 'ACE2 物理协议完成真机验证前仅允许读取状态。',
  capability_unavailable: '当前 ACE 设备不支持或未启用此操作。',
  confirmation_required: '此 ACE 操作需要明确确认。',
  connect_failed: 'ACE 连接失败，请检查串口、供电和接线。',
  device_error: 'ACE 设备报告故障。',
  device_offline: '目标 ACE 设备未连接。',
  device_rejected: 'ACE 设备拒绝了本次请求。',
  duplicate_parameter: '请求中存在重复参数。',
  encoder_calibration_active: '共享编码器正在校准，当前 ACE 动作已阻止。',
  encoder_calibration_failed: '共享编码器校准未完成。',
  encoder_event: '共享编码器报告了状态事件。',
  encoder_fault: '共享编码器发生故障。',
  encoder_motion_fault: '共享编码器未确认耗材移动。',
  encoder_no_motion: '编码器未检测到耗材移动。',
  encoder_not_ready: '共享编码器保护尚未就绪。',
  execution_failed: 'Klipper 未能完成 ACE 操作。',
  invalid_client: 'client 标识无效。',
  invalid_confirmation: 'confirm 必须为 true 或 false。',
  invalid_device: 'device 无效，必须使用 ace0 至 ace3。',
  invalid_parameter: '参数无效，请检查本次操作填写的内容。',
  invalid_params: 'params 必须是 JSON 对象。',
  invalid_request: '请求格式无效。',
  invalid_response: 'ACE 返回了无法识别的数据。',
  invalid_tool: 'tool 无效，必须使用 T0 至 T15。',
  missing_parameter: '缺少执行此操作所需的参数。',
  path_busy: '共享耗材路径正忙，请等待当前操作完成。',
  physical_actions_disabled: '所选 ACE 设备未启用物理动作。',
  physical_state_unknown: 'ACE 物理动作结果未确认，请先检查耗材路径并执行恢复。',
  print_state_blocked: '当前打印机状态禁止执行此 ACE 操作。',
  request_failed: 'ACE 通信请求失败，请检查连接后重试。',
  safety_rejected: '安全检查拒绝了此操作。',
  status_unavailable: '无法读取 ACE 状态。',
  target_mismatch: 'device、slot 与 tool 指向的目标不一致。',
  target_unavailable: '无法安全确定 ACE 操作目标。',
  toolchange_unavailable: '自动换料当前不可用。',
  transport_error: 'ACE 通信失败，请检查连接后重试。',
  unknown_action: '请求的 action 不受支持。',
  unknown_parameter: '请求包含不支持的字段或参数。',
  upper_sensor_feed_timeout: '送料超时前上方传感器始终未触发。',
})

const BACKEND_TEXT_MESSAGES = Object.freeze({
  'ace capabilities could not be read from klipper': '无法从 Klipper 读取 ACE 能力信息。',
  'ace encoder event': '共享编码器报告了状态事件。',
  'ace encoder fault': '共享编码器发生故障。',
  'ace request failed': 'ACE 请求失败，请检查设备连接。',
  'ace status could not be read from klipper': '无法从 Klipper 读取 ACE 状态。',
  'ace2 is read-only in this release': '当前版本仅允许读取 ACE2 状态。',
  'ace2 physical actions are disabled until hardware validation is complete': 'ACE2 完成真机验证前禁止执行物理动作。',
  'action is not in the ace whitelist': '请求的 action 不在 ACE 允许列表中。',
  'another tool owns the shared filament path': '共享耗材路径正由其他工具通道占用。',
  'automatic tool changing is disabled in manual mode': '当前处于手动模式，自动换料未启用。',
  'automatic tool changing is not ready': '自动换料尚未就绪。',
  'calibration mode must be probe, save, or cancel': 'mode 必须是 probe、save 或 cancel。',
  'capability is not supported': '当前设备不支持此能力。',
  'capability is unavailable': '此能力当前不可用。',
  'check diagnostics': '请检查 ACE 诊断信息。',
  'check the connection and retry': '请检查设备连接后重试。',
  'client must be a short string': 'client 必须是长度合规的字符串。',
  'color must use #rrggbb format': 'color 必须使用 #RRGGBB 格式。',
  'confirm must be true or false': 'confirm 必须为 true 或 false。',
  'device does not match the requested feed-assist tool': 'device 与请求的辅助送料 tool 不匹配。',
  'dryer temperature exceeds the configured maximum': '烘干温度超过配置允许的上限。',
  'encoder calibration requires an empty filament path': '编码器校准前必须清空耗材路径。',
  'encoder calibration requires feed assist to be disabled': '编码器校准前必须关闭辅助送料。',
  'encoder calibration requires no loaded tool': '编码器校准前不得装载 tool。',
  'enabled must be true or false': 'enabled 必须为 true 或 false。',
  'endless spool is disabled': '无限续料尚未启用。',
  'feed assist requires tool or both device and slot': '辅助送料必须提供 tool，或同时提供 device 和 slot。',
  'filament slip': '耗材可能打滑或卡住。',
  'klipper does not expose the ace pro control center status object': 'Klipper 尚未提供 ACE 状态对象，请检查驱动是否已加载。',
  'klipper rejected or failed the ace action': 'Klipper 拒绝或未能完成 ACE 操作。',
  'klipper returned an invalid object status response': 'Klipper 返回的 ACE 状态格式无效。',
  'manual feed or retract requires a slot or the current loaded tool': '手动送料或回料必须指定 slot，或已有已装载的 tool。',
  'no current tool is available for endless spool': '当前没有可用于无限续料的工具通道。',
  'no motion': '编码器未检测到耗材移动。',
  'params must be a json object': 'params 必须是 JSON 对象。',
  'physical actions are disabled': 'ACE 物理动作已禁用。',
  'physical actions are disabled for the selected ace device': '所选 ACE 设备未启用物理动作。',
  'physical actions are disabled for this ace device': '此 ACE 设备未启用物理动作。',
  'refresh status and retry': '请刷新 ACE 状态后重试。',
  'request body must be a json object': '请求正文必须是 JSON 对象。',
  'required ace action parameters are missing': '缺少执行此 action 所需的参数。',
  'return-path sensor did not clear within the configured retract limit': '在设定回抽范围内五通传感器仍未解除触发。',
  'retry': '请重试此操作。',
  'shared filament encoder calibration is already active': '共享编码器校准已在进行中。',
  'shared filament encoder calibration is not active': '共享编码器当前没有进行中的校准。',
  'shared filament encoder cannot finish motion tracking': '共享编码器无法完成动作监测。',
  'shared filament encoder cannot monitor ace motion': '共享编码器无法监测 ACE 动作。',
  'shared filament encoder did not confirm ace motion': '共享编码器未确认 ACE 耗材移动。',
  'shared filament encoder is not configured': '共享编码器未配置。',
  'shared filament encoder is unavailable; calibration cannot be finished': '共享编码器尚未报告有效脉冲，无法完成校准。',
  'slot does not match the requested feed-assist tool': 'slot 与请求的辅助送料 tool 不匹配。',
  'status is not a supported slot state': 'status 不是支持的槽位状态。',
  'target slot is not ready': '目标槽位尚未就绪。',
  'the ace device is offline': 'ACE 设备未连接。',
  'the current printer state blocks this ace action': '当前打印机状态禁止执行此 ACE action。',
  'the filament path and current tool state are inconsistent': '耗材路径与当前 tool 状态不一致。',
  'the loaded filament path has no known owning tool': '已装载耗材没有对应的 tool。',
  'the physical ace target cannot be resolved safely': '无法安全确定物理 ACE 操作目标。',
  'the printer state blocks this physical action': '当前打印机状态禁止执行此物理动作。',
  'the printer state is not safe for this physical action': '当前打印机状态不适合执行此物理动作。',
  'the requested ace device is not configured': '请求的 ACE device 尚未配置。',
  'the selected ace device does not support this action': '所选 ACE 设备不支持此 action。',
  'the selected ace device is offline': '所选 ACE 设备未连接。',
  'the selected ace target does not declare this capability': '所选 ACE 目标未声明支持此能力。',
  'the shared filament path already has an active transaction': '共享耗材路径已有正在执行的事务。',
  'the shared filament path is busy': '共享耗材路径正忙。',
  'the shared filament path requires manual recovery': '共享耗材路径需要人工检查并恢复。',
  'this ace action requires explicit confirmation': '此 ACE action 需要明确确认。',
  'this action requires explicit confirmation': '此 action 需要明确确认。',
  'this release supports exact or material endless-spool matching': '当前版本的 match_mode 仅支持 exact 或 material。',
  'tool must be t0 through t15': 'tool 必须是 T0 至 T15。',
  'unknown ace action parameters were rejected': '请求包含此 ACE action 不支持的参数。',
  'unknown top-level request fields were rejected': '请求包含不支持的顶层字段。',
  'upper filament sensor did not trigger before the ace feed timeout': '送料超时前上方传感器始终未触发。',
  'wait': '请等待当前操作完成后重试。',
})

const BACKEND_TEXT_PATTERNS = Object.freeze([
  [/^([a-z_][\w.-]*) is outside its allowed range$/i, match => `${match[1]} 超出允许范围。`],
  [/^([a-z_][\w.-]*) must be a short string$/i, match => `${match[1]} 必须是长度合规的字符串。`],
  [/^([a-z_][\w.-]*) contains unsafe characters$/i, match => `${match[1]} 包含不安全字符。`],
  [/^([a-z_][\w.-]*) and ([a-z_][\w.-]*) cannot both be supplied$/i, match => `${match[1]} 与 ${match[2]} 不能同时提供。`],
  [/^(ace\d+) is offline$/i, match => `${match[1]} 未连接。`],
  [/^(ace\d+) has not passed uid verification$/i, match => `${match[1]} 尚未通过 UID 验证。`],
  [/^physical action '([^']+)' is disabled for (ace\d+)$/i, match => `${match[2]} 的物理动作 ${match[1]} 未启用。`],
  [/^required filament sensor '([^']+)' is not configured$/i, match => `必需的耗材传感器 ${match[1]} 未配置。`],
  [/^ace filament sensor '([^']+)' is not registered$/i, match => `ACE 耗材传感器 ${match[1]} 未注册。`],
  [/^ace filament sensor '([^']+)' has no detected state$/i, match => `ACE 耗材传感器 ${match[1]} 没有可读取的检测状态。`],
  [/^unsupported ace action: (.+)$/i, match => `不支持的 ACE action：${match[1]}。`],
])

export class AceContractError extends Error {
  constructor (message, path = '') {
    super(path ? `${path}: ${message}` : message)
    this.name = 'AceContractError'
    this.code = 'ACE_CONTRACT_ERROR'
    this.path = path
  }
}

export class AceApiError extends Error {
  constructor (message, options = {}) {
    super(message)
    this.name = 'AceApiError'
    this.code = options.code || 'ACE_API_ERROR'
    this.status = options.status || 0
    this.reason = options.reason || ''
    this.recoverable = options.recoverable === true
    this.retryable = options.retryable === true
    this.nextAction = options.nextAction || ''
    this.details = options.details || null
  }
}

function isRecord (value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function record (value, path) {
  if (!isRecord(value)) throw new AceContractError('必须是对象', path)
  return value
}

function finiteNumber (value, fallback = null) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function boolean (value, fallback = false) {
  return typeof value === 'boolean' ? value : fallback
}

function string (value, fallback = '') {
  return typeof value === 'string' ? value.trim() : fallback
}

function integer (value, fallback = null) {
  return Number.isInteger(value) ? value : fallback
}

function firstDefined (...values) {
  return values.find(value => value !== undefined && value !== null)
}

function localizeBackendText (value, options = {}) {
  const text = string(value)
  const code = string(options.code).toLowerCase()
  if (!text) return BACKEND_CODE_MESSAGES[code] || options.fallback || ''
  if (CHINESE_TEXT.test(text)) return text

  const candidate = text.replace(/[.!?]+$/g, '').trim()
  const exact = BACKEND_TEXT_MESSAGES[candidate.toLowerCase()]
  if (exact) return exact
  for (const [pattern, formatter] of BACKEND_TEXT_PATTERNS) {
    const match = candidate.match(pattern)
    if (match) return formatter(match)
  }

  return BACKEND_CODE_MESSAGES[code] || options.fallback || 'ACE 返回了未翻译的信息，请检查诊断信息。'
}

function normalizeMaterialTypes (value) {
  if (!Array.isArray(value) || value.length === 0) return DEFAULT_MATERIAL_TYPES
  if (value.some(item => typeof item !== 'string' || item.trim() === '')) return DEFAULT_MATERIAL_TYPES
  return Object.freeze(value.map(item => item.trim()))
}

function flagValue (value) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number' && Number.isFinite(value)) return value !== 0
  if (typeof value !== 'string') return null
  const normalized = value.trim().toLowerCase()
  if (['1', 'true', 'on', 'enabled', 'yes'].includes(normalized)) return true
  if (['0', 'false', 'off', 'disabled', 'no'].includes(normalized)) return false
  return null
}

function rfidReadingState (value) {
  if (value === null || value === undefined || value === '') return 'unknown'
  if (typeof value === 'boolean') return value ? 'identified' : 'missing'
  const numeric = typeof value === 'number'
    ? value
    : (typeof value === 'string' && /^[0-3]$/.test(value.trim()) ? Number(value.trim()) : null)
  if (numeric === 0) return 'missing'
  if (numeric === 1) return 'failed'
  if (numeric === 2) return 'identified'
  if (numeric === 3) return 'identifying'
  return typeof value === 'string' && value.trim() ? 'identified' : 'unknown'
}

function rfidReadingLabel (state, enabled) {
  if (!enabled) return '已关闭'
  if (state === 'identified') return '已识别'
  if (state === 'identifying') return '识别中'
  if (state === 'missing' || state === 'failed') return '已关闭'
  return '未提供'
}

function rfidSummaryLabel (enabled, slots) {
  if (!enabled) return '已关闭'

  const readings = slots.map(slot => slot.rfidState)
  if (readings.includes('identifying')) return '识别中'
  if (readings.includes('identified') && readings.some(value => value !== 'identified')) return '部分识别'
  if (readings.includes('identified')) return '已识别'
  if (readings.some(value => value === 'failed' || value === 'missing')) return '已关闭'
  return '未提供'
}

function unwrapResponse (payload) {
  let value = payload
  if (isRecord(value) && isRecord(value.data)) value = value.data
  if (isRecord(value) && value.ok === false) throw responseError(value.error, value)
  if (isRecord(value) && isRecord(value.result)) {
    if (value.result.ok === false) throw responseError(value.result.error, value.result)
    if (value.result.ok === true && isRecord(value.result.result)) return value.result.result
    return value.result
  }
  return value
}

function responseError (rawError, envelope = {}) {
  const error = isRecord(rawError) ? rawError : {}
  const code = string(error.code, 'ACE_ACTION_REJECTED')
  return new AceApiError(
    localizeBackendText(firstDefined(error.message, error.reason, envelope.message), {
      code,
      fallback: 'ACE 请求被拒绝，请检查参数、设备连接和诊断信息。',
    }),
    {
      code,
      reason: localizeBackendText(error.reason, {
        code,
        fallback: error.reason ? '后端返回的错误原因暂无中文说明，请检查诊断信息。' : '',
      }),
      recoverable: boolean(error.recoverable),
      retryable: boolean(error.retryable),
      nextAction: localizeBackendText(firstDefined(error.next_action, error.nextAction), {
        fallback: firstDefined(error.next_action, error.nextAction)
          ? '请刷新状态，检查设备连接和诊断信息后重试。'
          : '',
      }),
      details: error,
    }
  )
}

function normalizeCapabilityEntry (raw, defaultPhysical = false) {
  if (raw === true) {
    return Object.freeze({ available: true, physical: defaultPhysical, allowedWhenPrinting: false, reason: '', requiresConfirmation: defaultPhysical })
  }
  if (raw === false || raw === null || raw === undefined) {
    return Object.freeze({ available: false, physical: defaultPhysical, allowedWhenPrinting: false, reason: '后端未声明此能力可用。', requiresConfirmation: defaultPhysical })
  }
  const item = record(raw, 'capability')
  const available = boolean(firstDefined(item.available, item.enabled, item.supported))
  const rawReason = firstDefined(item.reason, item.blocked_reason, item.disabled_reason)
  return Object.freeze({
    available,
    physical: boolean(item.physical, defaultPhysical),
    allowedWhenPrinting: boolean(firstDefined(item.allowed_when_printing, item.allowedWhenPrinting)),
    reason: localizeBackendText(rawReason, {
      code: item.code,
      fallback: rawReason || !available ? '此能力当前不可用，请检查 ACE 配置和设备状态。' : '',
    }),
    requiresConfirmation: boolean(firstDefined(item.requires_confirmation, item.requiresConfirmation), defaultPhysical),
  })
}

function normalizeCapabilities (raw) {
  const actions = {}
  if (Array.isArray(raw)) {
    for (const action of raw) {
      if (typeof action === 'string' && ACTION_SET.has(action)) {
        actions[action] = normalizeCapabilityEntry(true, PHYSICAL_ACTIONS.has(action))
      }
    }
  } else if (isRecord(raw)) {
    const source = isRecord(raw.actions) ? raw.actions : raw
    const feedAssist = firstDefined(source.feed_assist, source.feedAssist, raw.feed_assist, raw.feedAssist)
    if (feedAssist !== undefined) {
      const capability = normalizeCapabilityEntry(feedAssist, true)
      for (const action of [ACE_ACTIONS.ENABLE_FEED_ASSIST, ACE_ACTIONS.DISABLE_FEED_ASSIST]) {
        actions[action] = Object.freeze({
          ...capability,
          allowedWhenPrinting: true,
          requiresConfirmation: action === ACE_ACTIONS.ENABLE_FEED_ASSIST,
        })
      }
    }
    const encoderCalibration = firstDefined(
      source.encoder_calibration,
      source.encoderCalibration,
      raw.encoder_calibration,
      raw.encoderCalibration
    )
    if (encoderCalibration !== undefined) {
      const capability = normalizeCapabilityEntry(encoderCalibration, false)
      for (const action of ENCODER_CALIBRATION_ACTIONS) actions[action] = capability
    }
    for (const [action, value] of Object.entries(source)) {
      if (ACTION_SET.has(action)) actions[action] = normalizeCapabilityEntry(value, PHYSICAL_ACTIONS.has(action))
    }
  }
  return Object.freeze(actions)
}

function normalizeSlot (raw, deviceIndex, expectedSlot, rfidEnabled) {
  const slot = record(raw, `devices[${deviceIndex}].slots[${expectedSlot}]`)
  const index = integer(firstDefined(slot.index, slot.slot), expectedSlot)
  if (index !== expectedSlot || index < 0 || index > 3) {
    throw new AceContractError('槽位必须按 0..3 连续排列', `devices[${deviceIndex}].slots`)
  }
  const expectedTool = `T${deviceIndex * 4 + index}`
  const tool = string(slot.tool, expectedTool).toUpperCase()
  if (tool !== expectedTool) {
    throw new AceContractError(`工具映射应为 ${expectedTool}`, `devices[${deviceIndex}].slots[${index}].tool`)
  }
  const materialKey = string(firstDefined(slot.material, slot.material_type), 'unknown').toLowerCase()
  const remaining = finiteNumber(firstDefined(slot.remaining_percent, slot.remaining, slot.level), null)
  const rfid = firstDefined(slot.rfid, slot.rfid_source, slot.source) ?? null
  const rfidState = rfidReadingState(rfid)
  return Object.freeze({
    index,
    tool,
    label: `槽${index + 1}`,
    state: string(slot.state, 'unknown').toLowerCase(),
    available: boolean(firstDefined(slot.available, slot.usable), true),
    empty: boolean(slot.empty) || ['empty', 'absent', 'missing'].includes(string(slot.state).toLowerCase()),
    loaded: boolean(slot.loaded) || boolean(slot.active),
    material: string(firstDefined(slot.material, slot.material_type), 'unknown'),
    materialLabel: MATERIAL_LABELS[materialKey] || string(firstDefined(slot.material, slot.material_type), '未设置').toUpperCase(),
    color: normalizeColor(firstDefined(slot.color, slot.colour)),
    remainingPercent: remaining === null ? null : Math.max(0, Math.min(100, remaining)),
    targetTemperature: finiteNumber(firstDefined(slot.target_temperature, slot.temperature), null),
    spoolId: string(firstDefined(slot.spool_id, slot.spoolId)),
    rfid,
    rfidEnabled,
    rfidState,
    rfidLabel: rfidReadingLabel(rfidState, rfidEnabled),
    maintenance: string(firstDefined(slot.maintenance, slot.note)),
    raw: slot,
  })
}

function normalizeColor (value) {
  const color = string(value, '#8b929a')
  if (/^#[0-9a-f]{3,8}$/i.test(color) || /^rgb\(/i.test(color) || /^[a-z]+$/i.test(color)) return color
  return '#8b929a'
}

function normalizeEndlessSpool (raw) {
  const value = isRecord(raw) ? raw : {}
  return Object.freeze({
    enabled: boolean(value.enabled),
    matchMode: string(firstDefined(value.match_mode, value.matchMode), 'exact'),
    candidates: Array.isArray(value.candidates) ? value.candidates.filter(item => typeof item === 'string' && TOOL_ID.test(item)) : [],
    lastSelection: string(firstDefined(value.last_selection, value.lastSelection)),
  })
}

function normalizeToolchangeNotice (raw) {
  if (!isRecord(raw)) return null
  const sequence = Number(firstDefined(raw.sequence, raw.seq))
  if (!Number.isSafeInteger(sequence) || sequence < 0) return null
  const command = string(firstDefined(raw.command, raw.tool)).toUpperCase()
  const message = localizeBackendText(raw.message, {
    code: raw.code,
    fallback: 'ACE 返回了一条未翻译的换料提示，请检查诊断信息。',
  })
  if (!message) return null
  return Object.freeze({
    sequence,
    code: string(raw.code),
    command: /^(?:T(?:\d|1[0-5])|TR)$/.test(command) ? command : '',
    message,
  })
}

function normalizeToolchangeNotices (status) {
  const bySequence = new Map()
  const queue = firstDefined(status.toolchange_notices, status.toolchangeNotices)
  if (Array.isArray(queue)) {
    for (const raw of queue) {
      const notice = normalizeToolchangeNotice(raw)
      if (notice) bySequence.set(notice.sequence, notice)
    }
  }
  const latest = normalizeToolchangeNotice(firstDefined(status.toolchange_notice, status.toolchangeNotice))
  if (latest) bySequence.set(latest.sequence, latest)
  const notices = Object.freeze([...bySequence.values()].sort((left, right) => left.sequence - right.sequence))
  return Object.freeze({
    latest: latest || notices[notices.length - 1] || null,
    notices,
  })
}

function normalizeFeedAssist (status, devices) {
  const systemRaw = isRecord(status.system) ? status.system : {}
  const pathRaw = isRecord(status.path) ? status.path : {}
  let raw = firstDefined(status.feed_assist, status.feedAssist, systemRaw.feed_assist, systemRaw.feedAssist, pathRaw.feed_assist, pathRaw.feedAssist)
  let sourceDevice = null

  if (!isRecord(raw)) {
    for (const device of devices) {
      const deviceRaw = device.raw
      const slot = device.slots.find(item => flagValue(firstDefined(item.raw.feed_assist_active, item.raw.feedAssistActive, item.raw.feed_assist)) === true)
      const deviceSlot = firstDefined(deviceRaw.feed_assist_slot, deviceRaw.feedAssistSlot, slot?.index)
      const deviceActive = flagValue(firstDefined(deviceRaw.feed_assist_active, deviceRaw.feedAssistActive, deviceRaw.feed_assist_enabled, deviceRaw.feedAssistEnabled))
      if (slot || deviceActive === true || deviceSlot !== undefined) {
        raw = {
          active: true,
          device_id: device.id,
          slot: deviceSlot,
          tool: slot?.tool,
        }
        sourceDevice = device
        break
      }
    }
  }

  const value = isRecord(raw) ? raw : {}
  const activeFlag = flagValue(firstDefined(value.active, value.enabled, value.running))
  let tool = string(firstDefined(value.tool, value.active_tool, value.activeTool)).toUpperCase()
  let deviceId = string(firstDefined(value.device_id, value.deviceId, value.device), sourceDevice?.id).toLowerCase()
  let slot = Number(firstDefined(value.slot, value.index, value.slot_index, value.slotIndex))
  if (!Number.isInteger(slot) || slot < 0 || slot > 3) slot = null

  if (TOOL_ID.test(tool)) {
    const toolIndex = Number(tool.slice(1))
    if (toolIndex < devices.length * 4) {
      deviceId = `ace${Math.floor(toolIndex / 4)}`
      slot = toolIndex % 4
    } else {
      tool = ''
    }
  } else {
    tool = ''
  }
  const device = devices.find(item => item.id === deviceId)
  if (device && slot !== null) tool = tool || device.slots[slot]?.tool || ''
  const targetValid = Boolean(device && slot !== null && tool)
  const active = activeFlag === true || (activeFlag !== false && targetValid)

  return Object.freeze({
    active,
    deviceId: targetValid ? deviceId : '',
    slot: targetValid ? slot : null,
    tool: targetValid ? tool : '',
    targetValid,
    label: active ? (targetValid ? `${tool} · ${device.name} · 槽${slot + 1}` : '活动槽位未知') : '未启用',
  })
}

function normalizeDevice (raw, expectedIndex, globalCapabilities, globalEndlessSpool = null) {
  const device = record(raw, `devices[${expectedIndex}]`)
  const id = string(device.id, `ace${expectedIndex}`).toLowerCase()
  const match = id.match(DEVICE_ID)
  const index = integer(device.index, match ? Number(match[1]) : expectedIndex)
  if (!match || index !== expectedIndex || id !== `ace${expectedIndex}`) {
    throw new AceContractError('设备必须从 ace0 起按配置顺序连续排列', `devices[${expectedIndex}].id`)
  }
  const model = string(device.model, 'auto').toLowerCase()
  if (!MODELS.has(model)) throw new AceContractError('型号必须是 ace1、ace2 或 auto', `${id}.model`)
  if (!Array.isArray(device.slots) || device.slots.length !== 4) {
    throw new AceContractError('每台设备必须包含四个槽位', `${id}.slots`)
  }
  const connected = boolean(firstDefined(device.connected, device.online))
  const enabled = boolean(device.enabled, true)
  const physicalActionsEnabled = boolean(firstDefined(device.physical_actions_enabled, device.physicalActionsEnabled))
  const capabilities = Object.freeze({
    ...globalCapabilities,
    ...normalizeCapabilities(device.capabilities),
  })
  const dryerRaw = isRecord(device.dryer) ? device.dryer : {}
  const endlessRaw = isRecord(device.endless_spool) ? device.endless_spool : {}
  const diagnosticsRaw = isRecord(device.diagnostics) ? device.diagnostics : {}
  const configuredRfid = flagValue(firstDefined(device.rfid_enabled, device.rfidEnabled))
  const rfidEnabled = configuredRfid ?? true
  const slots = Object.freeze(device.slots.map((slot, slotIndex) => normalizeSlot(slot, index, slotIndex, rfidEnabled)))
  const rfidLabel = rfidSummaryLabel(rfidEnabled, slots)
  return Object.freeze({
    id,
    index,
    name: string(device.name, `ACE ${index + 1}`),
    model,
    modelLabel: model === 'ace1' ? 'ACE Pro 1' : model === 'ace2' ? 'ACE Pro 2' : '型号待确认',
    protocol: string(device.protocol, model.toUpperCase()),
    firmware: string(firstDefined(device.firmware, device.firmware_version), '未知'),
    connected,
    enabled,
    connectionLabel: !enabled ? '已禁用' : connected ? '已连接' : '未连接',
    state: connected ? string(firstDefined(device.state, device.status), 'idle').toLowerCase() : 'offline',
    currentAction: string(firstDefined(device.current_action, device.action)),
    rfidEnabled,
    rfidLabel,
    physicalActionsEnabled,
    readOnly: !physicalActionsEnabled,
    temperature: finiteNumber(firstDefined(device.temperature, dryerRaw.temperature), null),
    humidity: finiteNumber(firstDefined(device.humidity, dryerRaw.humidity), null),
    dryer: Object.freeze({
      active: boolean(firstDefined(dryerRaw.active, dryerRaw.enabled, device.drying)),
      temperature: finiteNumber(firstDefined(dryerRaw.temperature, device.temperature), null),
      targetTemperature: finiteNumber(firstDefined(dryerRaw.target_temperature, dryerRaw.targetTemperature), null),
      remainingMinutes: finiteNumber(firstDefined(dryerRaw.remaining_minutes, dryerRaw.remaining, dryerRaw.time_remaining), null),
      autoFollow: boolean(firstDefined(dryerRaw.auto_follow, dryerRaw.autoFollow)),
    }),
    endlessSpool: globalEndlessSpool || normalizeEndlessSpool({
      ...endlessRaw,
      enabled: firstDefined(endlessRaw.enabled, device.endless_spool_enabled),
    }),
    slots,
    capabilities,
    error: normalizeIssue(firstDefined(device.error, device.last_error)),
    diagnostics: Object.freeze({
      port: string(firstDefined(diagnosticsRaw.port, device.serial)),
      uid: string(firstDefined(diagnosticsRaw.uid, device.uid, device.device_uid)),
      lastSeen: string(firstDefined(diagnosticsRaw.last_seen, device.last_seen)),
      reconnects: finiteNumber(firstDefined(diagnosticsRaw.reconnects, device.reconnects), 0),
      warnings: normalizeIssues(firstDefined(diagnosticsRaw.warnings, device.warnings)),
    }),
    raw: device,
  })
}

function normalizeSnapshotValue (value) {
  if (Array.isArray(value)) return Object.freeze(value.map(normalizeSnapshotValue))
  if (isRecord(value)) {
    return Object.freeze(Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, normalizeSnapshotValue(item)])
    ))
  }
  return ['string', 'number', 'boolean'].includes(typeof value) || value === null ? value : String(value)
}

function normalizeIssueContext (raw) {
  if (!isRecord(raw)) return null
  const sensors = isRecord(raw.sensors) ? normalizeSnapshotValue(raw.sensors) : Object.freeze({})
  return Object.freeze({
    tool: string(raw.tool),
    device: string(firstDefined(raw.device, raw.device_id, raw.deviceId)),
    pathState: string(firstDefined(raw.path_state, raw.pathState)),
    printState: string(firstDefined(raw.print_state, raw.printState)),
    sensors,
  })
}

function normalizeIssue (raw) {
  if (!raw) return null
  if (typeof raw === 'string') {
    return Object.freeze({
      code: '',
      message: localizeBackendText(raw, { fallback: 'ACE 返回了一条未翻译的状态或故障信息，请检查诊断信息。' }),
      recoverable: false,
      nextAction: '',
      probableCause: '',
      context: null,
      pauseRequested: false,
    })
  }
  if (!isRecord(raw)) {
    return Object.freeze({
      code: '',
      message: 'ACE 返回的状态或故障信息格式无效，请检查诊断信息。',
      recoverable: false,
      nextAction: '',
      probableCause: '',
      context: null,
      pauseRequested: false,
    })
  }
  const code = string(raw.code)
  return Object.freeze({
    code,
    message: localizeBackendText(firstDefined(raw.message, raw.reason, raw.title), {
      code,
      fallback: 'ACE 返回了一条未翻译的状态或故障信息，请检查诊断信息。',
    }),
    recoverable: boolean(raw.recoverable),
    nextAction: localizeBackendText(firstDefined(raw.next_action, raw.nextAction), {
      fallback: firstDefined(raw.next_action, raw.nextAction)
        ? '请检查耗材路径、传感器和设备连接后再重试。'
        : '',
    }),
    probableCause: localizeBackendText(firstDefined(raw.probable_cause, raw.probableCause, raw.cause), {
      fallback: firstDefined(raw.probable_cause, raw.probableCause, raw.cause)
        ? '暂时无法确定具体原因，请检查耗材路径、传感器和设备连接。'
        : '',
    }),
    context: normalizeIssueContext(raw.context),
    pauseRequested: boolean(firstDefined(raw.pause_requested, raw.pauseRequested)),
  })
}

function normalizeIssues (raw) {
  if (!Array.isArray(raw)) return []
  return raw.map(normalizeIssue).filter(Boolean)
}

function normalizePrintMonitor (raw, configured) {
  const nested = isRecord(raw) ? raw : {}
  const rawMode = string(nested.mode, 'off').toLowerCase()
  const mode = PRINT_MONITOR_MODES.has(rawMode) ? rawMode : 'off'
  const enabled = configured && mode !== 'off' && (flagValue(nested.enabled) ?? true)
  const active = enabled && (flagValue(nested.active) ?? false)
  const state = string(nested.state, active ? 'monitoring' : enabled ? 'idle' : 'off').toLowerCase()
  const lastEvent = normalizeIssue(firstDefined(nested.last_event, nested.lastEvent))
  const fault = normalizeIssue(firstDefined(nested.fault, nested.last_fault, nested.error))
  const eventSequence = integer(firstDefined(
    nested.event_sequence,
    nested.eventSequence
  ), 0)
  const detectionLength = finiteNumber(firstDefined(
    nested.detection_length,
    nested.detectionLength
  ), null)
  const extrusionSinceMotion = finiteNumber(firstDefined(nested.extrusion_since_motion, nested.extrusionSinceMotion), null)
  const reportedHeadroom = finiteNumber(nested.headroom, null)
  const headroom = reportedHeadroom ?? (
    detectionLength !== null && extrusionSinceMotion !== null
      ? Math.max(0, detectionLength - extrusionSinceMotion)
      : null
  )
  const faultState = fault || ['fault', 'error', 'failed'].includes(state)
  const monitoringState = active || ['active', 'monitoring', 'watching'].includes(state)
  const pauseRequested = Boolean(
    fault?.pauseRequested || lastEvent?.pauseRequested ||
    ['pause', 'paused', 'pause_requested'].includes(state) ||
    (mode === 'pause' && faultState)
  )
  const modeLabel = mode === 'monitor' ? '监测' : mode === 'pause' ? '暂停保护' : '关闭'
  const statusLabel = faultState
    ? '故障'
    : monitoringState
      ? '监测中'
      : enabled
        ? modeLabel
        : '关闭'
  const tone = faultState ? 'error' : monitoringState ? 'active' : enabled ? (mode === 'monitor' ? 'monitor' : 'protect') : 'muted'

  return Object.freeze({
    mode,
    modeLabel,
    enabled,
    active,
    state,
    statusLabel,
    tone,
    detectionLength,
    extrusionSinceMotion,
    headroom,
    eventSequence: eventSequence !== null && eventSequence >= 0 ? eventSequence : 0,
    lastEvent,
    fault,
    pauseRequested,
    raw: nested,
  })
}

function normalizeSharedEncoder (raw) {
  const source = isRecord(raw) ? raw : {}
  const configuredFlag = flagValue(firstDefined(source.configured, source.present))
  const configured = configuredFlag ?? Object.keys(source).length > 0
  const rawMode = string(source.mode, 'off').toLowerCase()
  const mode = ENCODER_MODES.has(rawMode) ? rawMode : 'off'
  const resolution = finiteNumber(firstDefined(source.resolution, source.encoder_resolution), null)
  const available = configured && (flagValue(source.available) ?? false)
  const calibrated = configured && (
    flagValue(source.calibrated) ?? (resolution !== null && resolution > 0)
  )
  const armed = configured && (flagValue(source.armed) ?? false)
  const minTrackingRatioValue = finiteNumber(firstDefined(
    source.min_tracking_ratio,
    source.minTrackingRatio,
    source.minimum_tracking_ratio,
    source.minimumTrackingRatio
  ), null)
  const minTrackingRatio = minTrackingRatioValue !== null && minTrackingRatioValue > 0 && minTrackingRatioValue <= 1
    ? minTrackingRatioValue
    : null
  const calibrationActive = configured && (flagValue(firstDefined(source.calibration_active, source.calibrationActive)) ?? false)
  const fault = configured
    ? normalizeIssue(firstDefined(source.fault, source.last_fault, source.error))
    : null
  const printMonitor = normalizePrintMonitor(firstDefined(source.print_monitor, source.printMonitor), configured)

  let state = 'normal'
  if (!configured) state = 'unconfigured'
  else if (fault) state = 'fault'
  else if (calibrationActive) state = 'calibrating'
  else if (mode === 'off') state = 'off'
  else if (!calibrated) state = 'uncalibrated'
  else if (!available) state = 'unavailable'
  else if (mode === 'protect' && !armed) state = 'not_armed'

  const modeLabels = { off: '关闭', monitor: '监测', protect: '保护' }
  const stateLabels = {
    unconfigured: '未配置',
    off: '已关闭',
    calibrating: '校准中',
    uncalibrated: '未校准',
    unavailable: '未就绪',
    not_armed: '未启用',
    normal: '正常',
    fault: '故障',
  }
  const modeLabel = configured ? modeLabels[mode] : '未配置'
  const stateLabel = stateLabels[state]
  const summaryLabel = ['unconfigured', 'off'].includes(state)
    ? stateLabel
    : mode === 'monitor' && state === 'normal'
      ? '监测 · 只读'
      : `${modeLabel} · ${stateLabel}`
  let tone = mode === 'monitor' ? 'monitor' : 'protect'
  if (state === 'fault') tone = 'error'
  else if (['calibrating', 'uncalibrated', 'unavailable', 'not_armed'].includes(state)) tone = 'warning'
  else if (['unconfigured', 'off'].includes(state)) tone = 'muted'

  return Object.freeze({
    configured,
    available,
    mode,
    modeLabel,
    calibrated,
    armed,
    calibrationActive,
    state,
    stateLabel,
    summaryLabel,
    tone,
    resolution: resolution !== null && resolution > 0 ? resolution : null,
    detectionLength: finiteNumber(firstDefined(source.detection_length, source.detectionLength), null),
    counts: finiteNumber(source.counts, 0),
    position: finiteNumber(source.position, null),
    trackingRatio: finiteNumber(firstDefined(source.tracking_ratio, source.trackingRatio), null),
    minTrackingRatio,
    printMonitor,
    fault,
    raw: source,
  })
}

function normalizePathHubs (raw, devices) {
  if (devices.length < 2) return Object.freeze({})
  const source = isRecord(raw) ? raw : {}
  return Object.freeze(Object.fromEntries(devices.map(device => [
    device.id,
    typeof source[device.id] === 'boolean' ? source[device.id] : null,
  ])))
}

function normalizeSensorPolicy (raw) {
  const source = isRecord(raw) ? raw : {}
  const upper = isRecord(source.upper) ? source.upper : {}
  const lower = isRecord(source.lower) ? source.lower : {}
  const bypassed = flagValue(lower.bypassed) ?? false
  const configured = flagValue(lower.configured) ?? false
  const calibrated = flagValue(lower.calibrated) ?? false
  const controlEnabled = flagValue(firstDefined(lower.control_enabled, lower.controlEnabled)) ?? (configured && !bypassed)
  const monitorOnly = flagValue(firstDefined(lower.monitor_only, lower.monitorOnly)) ?? bypassed
  const feedTimeoutValue = finiteNumber(firstDefined(upper.feed_timeout, upper.feedTimeout), null)
  return Object.freeze({
    upper: Object.freeze({
      controlEndpoint: flagValue(firstDefined(upper.control_endpoint, upper.controlEndpoint)) ?? false,
      feedTimeout: feedTimeoutValue !== null && feedTimeoutValue >= 1 && feedTimeoutValue <= 120 ? feedTimeoutValue : null,
    }),
    lower: Object.freeze({
      bypassed,
      configured,
      calibrated,
      controlEnabled,
      monitorOnly,
      bypassLoadLength: Math.max(0, finiteNumber(firstDefined(lower.bypass_load_length, lower.bypassLoadLength), 0)),
    }),
  })
}

function normalizePathTopology (raw, devices) {
  const multiDevice = devices.length > 1
  const source = isRecord(raw) ? raw : {}
  const currentDeviceRaw = string(firstDefined(source.current_device, source.currentDevice))
  const currentDevice = devices.some(device => device.id === currentDeviceRaw) ? currentDeviceRaw : null
  const routeSource = Array.isArray(source.route)
    ? source.route
    : typeof source.route === 'string'
      ? source.route.split('->')
      : []
  const routeItems = routeSource.map(item => string(item)).filter(Boolean)
  const route = Object.freeze(multiDevice ? routeItems : routeItems.filter(item => item !== 'device_hub'))
  const branchClearanceValue = firstDefined(source.branch_clearance, source.branchClearance)
  const branchClearanceSource = isRecord(branchClearanceValue) ? branchClearanceValue : {}
  const branchClearance = Object.freeze(multiDevice
    ? Object.fromEntries(devices.map(device => [
        device.id,
        branchClearanceSource[device.id] === null || branchClearanceSource[device.id] === undefined
          ? null
          : finiteNumber(branchClearanceSource[device.id], null),
      ]))
    : {})
  return Object.freeze({ currentDevice, route, branchClearance })
}

export function normalizeAceStatus (payload) {
  const status = record(unwrapResponse(payload), 'status')
  const devicesRaw = status.devices
  if (!Array.isArray(devicesRaw) || devicesRaw.length < 1 || devicesRaw.length > 4) {
    throw new AceContractError('devices 必须包含 1 至 4 台设备', 'status.devices')
  }
  const globalCapabilities = normalizeCapabilities(status.capabilities)
  const globalEndlessSpool = isRecord(status.endless_spool)
    ? normalizeEndlessSpool(status.endless_spool)
    : null
  const devices = Object.freeze(devicesRaw.map((device, index) => normalizeDevice(device, index, globalCapabilities, globalEndlessSpool)))
  const systemRaw = isRecord(status.system) ? status.system : status
  const sharedPathRaw = isRecord(status.path) ? status.path : {}
  const pathSensorsRaw = isRecord(sharedPathRaw.sensors) ? sharedPathRaw.sensors : {}
  const pathEncodersRaw = isRecord(sharedPathRaw.encoders) ? sharedPathRaw.encoders : {}
  const pathHubs = normalizePathHubs(pathSensorsRaw.hubs, devices)
  const sensorPolicy = normalizeSensorPolicy(firstDefined(sharedPathRaw.sensor_policy, sharedPathRaw.sensorPolicy))
  const pathTopology = normalizePathTopology(sharedPathRaw.topology, devices)
  const sharedEncoderSource = firstDefined(
    pathEncodersRaw.shared,
    pathEncodersRaw.sharedEncoder,
    sharedPathRaw.shared_encoder,
    sharedPathRaw.sharedEncoder,
    status.shared_encoder,
    status.sharedEncoder,
    status.encoder
  )
  const sharedEncoder = normalizeSharedEncoder(sharedEncoderSource)
  const transactionRaw = isRecord(firstDefined(status.transaction, sharedPathRaw.transaction, systemRaw.transaction, status.activity))
    ? firstDefined(status.transaction, sharedPathRaw.transaction, systemRaw.transaction, status.activity)
    : {}
  const pathLockRaw = isRecord(firstDefined(status.path_lock, systemRaw.path_lock))
    ? firstDefined(status.path_lock, systemRaw.path_lock)
    : {}
  const pathBusy = boolean(sharedPathRaw.busy) ||
    boolean(firstDefined(pathLockRaw.locked, pathLockRaw.active, systemRaw.path_locked))
  let currentTool = [systemRaw.current_tool, systemRaw.active_tool, status.current_tool, status.active_tool]
    .find(value => value !== undefined)
  if (currentTool === undefined) currentTool = null
  if (currentTool === -1 || currentTool === 'TR' || currentTool === '') currentTool = null
  if (typeof currentTool === 'number') currentTool = `T${currentTool}`
  if (currentTool !== null && (typeof currentTool !== 'string' || !TOOL_ID.test(currentTool))) {
    throw new AceContractError('当前工具必须是 T0..T15 或 null', 'status.system.current_tool')
  }
  if (currentTool !== null && Number(currentTool.slice(1)) >= devices.length * 4) {
    throw new AceContractError('当前工具超出已配置设备范围', 'status.system.current_tool')
  }
  const diagnosticsRaw = isRecord(status.diagnostics) ? status.diagnostics : {}
  const toolchangeModeRaw = string(firstDefined(status.toolchange_mode, status.toolchangeMode), 'manual').toLowerCase()
  const toolchangeMode = TOOLCHANGE_MODES.has(toolchangeModeRaw) ? toolchangeModeRaw : 'manual'
  const toolchangeReady = toolchangeMode === 'automatic' && boolean(firstDefined(status.toolchange_ready, status.toolchangeReady))
  const toolchangeBlockedCode = string(firstDefined(status.toolchange_blocked_reason, status.toolchangeBlockedReason))
  const toolchangeBlockedDetail = string(firstDefined(status.toolchange_blocked_detail, status.toolchangeBlockedDetail))
  const toolchangeBlockedSource = toolchangeBlockedDetail || toolchangeBlockedCode
  const toolchangeBlockedReason = TOOLCHANGE_BLOCKED_LABELS[toolchangeBlockedCode] || localizeBackendText(toolchangeBlockedSource, {
    code: toolchangeBlockedCode,
    fallback: toolchangeBlockedSource
      ? '自动换料当前不可用，请检查 ACE 配置和诊断信息。'
      : (toolchangeMode === 'manual' ? '自动换料未启用，当前仅可使用手动功能。' : '自动换料配置尚未就绪。'),
  })
  const toolchangeNotices = normalizeToolchangeNotices(status)
  const feedAssist = normalizeFeedAssist(status, devices)
  const normalized = {
    schemaVersion: string(firstDefined(status.schema_version, status.version), '3.0'),
    generatedAt: string(firstDefined(status.generated_at, status.timestamp)),
    materialTypes: normalizeMaterialTypes(firstDefined(status.material_types, status.materialTypes)),
    toolchangeMode,
    toolchangeReady,
    toolchangeBlockedReason: toolchangeReady ? '' : toolchangeBlockedReason,
    toolchangeNotice: toolchangeNotices.latest,
    toolchangeNotices: toolchangeNotices.notices,
    toolchange: Object.freeze({
      mode: toolchangeMode,
      modeLabel: toolchangeMode === 'manual' ? '手动模式' : '自动换料',
      ready: toolchangeReady,
      blockedReason: toolchangeReady ? '' : toolchangeBlockedReason,
      assistanceOnly: !toolchangeReady,
      assistanceMessage: toolchangeReady ? '' : ACE_ASSIST_ONLY_MESSAGE,
      notice: toolchangeNotices.latest,
      notices: toolchangeNotices.notices,
    }),
    feedAssist,
    system: Object.freeze({
      printState: string(firstDefined(systemRaw.print_state, systemRaw.printState), 'unknown').toLowerCase(),
      currentTool,
      currentToolLabel: currentTool || '未装载',
      pathLocked: pathBusy,
      pathOwner: string(firstDefined(sharedPathRaw.owner, pathLockRaw.owner, pathLockRaw.device_id, systemRaw.path_owner)),
      degraded: boolean(systemRaw.degraded),
      degradedReason: localizeBackendText(firstDefined(systemRaw.degraded_reason, systemRaw.degradedReason), {
        code: firstDefined(systemRaw.degraded_code, systemRaw.degradedCode),
        fallback: firstDefined(systemRaw.degraded_reason, systemRaw.degradedReason)
          ? 'ACE 当前处于降级状态，请检查配置、连接和诊断信息。'
          : '',
      }),
    }),
    transaction: Object.freeze({
      active: boolean(firstDefined(transactionRaw.active, transactionRaw.busy)),
      id: string(firstDefined(transactionRaw.id, transactionRaw.transaction_id)),
      action: string(firstDefined(transactionRaw.action, transactionRaw.kind)),
      phase: string(firstDefined(transactionRaw.phase, transactionRaw.phase_label)),
      progress: finiteNumber(transactionRaw.progress, null),
      deviceId: string(firstDefined(transactionRaw.device_id, transactionRaw.device)),
      tool: string(transactionRaw.tool),
    }),
    path: Object.freeze({
      busy: pathBusy,
      state: string(sharedPathRaw.state, 'unknown').toLowerCase(),
      sensors: Object.freeze({
        upper: pathSensorsRaw.upper ?? null,
        lower: pathSensorsRaw.lower ?? null,
        rdm: pathSensorsRaw.rdm ?? null,
        hubs: pathHubs,
      }),
      sensorPolicy,
      encoders: Object.freeze({ shared: sharedEncoder }),
      topology: pathTopology,
    }),
    devices,
    capabilities: globalCapabilities,
    endlessSpool: globalEndlessSpool || devices[0].endlessSpool,
    calibration: Object.freeze(isRecord(status.calibration) ? status.calibration : {}),
    diagnostics: Object.freeze({
      warnings: normalizeIssues(diagnosticsRaw.warnings),
      errors: normalizeIssues(firstDefined(diagnosticsRaw.errors, diagnosticsRaw.issues)),
      lastError: normalizeIssue(firstDefined(diagnosticsRaw.last_error, status.last_error)),
    }),
  }
  return Object.freeze(normalized)
}

// Stable public name used by both shipped frontends.
export const normalizeAceState = normalizeAceStatus

function capabilityReason (status, action, context = {}) {
  const device = context.device || (context.deviceId ? status.devices.find(item => item.id === context.deviceId) : null)
  const capability = ENCODER_CALIBRATION_ACTIONS.has(action)
    ? status.capabilities[action]
    : device?.capabilities[action] || status.capabilities[action]
  if (action === ACE_ACTIONS.DISABLE_FEED_ASSIST) {
    return status.feedAssist.active ? '' : '当前没有启用 ACE 辅助送料。'
  }
  if (AUTOMATIC_TOOLCHANGE_ACTIONS.has(action) && !status.toolchangeReady) {
    return status.toolchangeBlockedReason || '自动换料尚未就绪。'
  }
  if (ENCODER_CALIBRATION_ACTIONS.has(action)) {
    const encoder = status.path.encoders.shared
    if (!encoder.configured) return '共享编码器未配置。'
    if (action === ACE_ACTIONS.ENCODER_CALIBRATION_START && encoder.calibrationActive) return '共享编码器校准已在进行中。'
    if (action !== ACE_ACTIONS.ENCODER_CALIBRATION_START && !encoder.calibrationActive) return '共享编码器当前没有进行中的校准。'
    if (action !== ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL && !encoder.available) return '共享编码器尚未报告有效脉冲。'
  }
  if (!capability || capability.available !== true) return capability?.reason || '后端未声明此动作可用。'
  if (device && !device.enabled) return `${device.name} 已禁用。`
  if (device && !device.connected && !CONNECTION_OPTIONAL_ACTIONS.has(action)) return `${device.name} 未连接。`
  if (PHYSICAL_ACTIONS.has(action)) {
    if (!device && action !== ACE_ACTIONS.UNLOAD) return '无法确定动作目标设备。'
    if (device && !device.physicalActionsEnabled) return `${device.name} 的物理动作已被配置禁用。`
  }
  if (PRINT_STATE_GATED_ACTIONS.has(action)) {
    if (action !== ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL && status.transaction.active) return `正在执行 ${status.transaction.action || '另一项操作'}，请等待事务结束。`
    if (action !== ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL && status.system.pathLocked) return `共享耗材路径已由 ${status.system.pathOwner || '另一事务'} 占用。`
    if (!capability.allowedWhenPrinting && !['idle', 'standby', 'complete', 'ready'].includes(status.system.printState)) {
      return `打印状态为 ${status.system.printState}，此动作已被安全门禁。`
    }
  }
  if (action === ACE_ACTIONS.SELECT_TOOL && context.slot) {
    if (context.slot.empty) return `${context.slot.tool} 对应槽位为空。`
    if (!context.slot.available) return `${context.slot.tool} 当前不可用。`
  }
  if (action === ACE_ACTIONS.ENABLE_FEED_ASSIST && context.slot) {
    if (context.slot.empty) return `${context.slot.tool} 对应槽位为空。`
    if (!context.slot.available) return `${context.slot.tool} 当前不可用。`
  }
  return ''
}

export function getActionAvailability (status, action, context = {}) {
  if (!ACTION_SET.has(action)) return Object.freeze({ allowed: false, reason: '未知动作。', capability: null })
  const device = context.device || (context.deviceId ? status.devices.find(item => item.id === context.deviceId) : null)
  const capability = ENCODER_CALIBRATION_ACTIONS.has(action)
    ? status.capabilities[action] || null
    : device?.capabilities[action] || status.capabilities[action] || null
  const reason = capabilityReason(status, action, { ...context, device })
  return Object.freeze({
    allowed: reason === '',
    reason,
    capability,
    requiresConfirmation: action === ACE_ACTIONS.DISABLE_FEED_ASSIST
      ? false
      : capability?.requiresConfirmation === true || PHYSICAL_ACTIONS.has(action),
  })
}

// Stable public name. The return value includes both the decision and reason.
export const canPerformAction = getActionAvailability

export function toolToTarget (tool, deviceCount = 4) {
  if (typeof tool !== 'string' || !TOOL_ID.test(tool)) throw new AceContractError('工具必须是 T0..T15', 'tool')
  const index = Number(tool.slice(1))
  if (index >= deviceCount * 4) throw new AceContractError('工具超出已配置设备范围', 'tool')
  return Object.freeze({ tool, toolIndex: index, deviceId: `ace${Math.floor(index / 4)}`, deviceIndex: Math.floor(index / 4), slot: index % 4 })
}

export function targetToTool (deviceId, slot, deviceCount = 4) {
  const match = typeof deviceId === 'string' ? deviceId.match(DEVICE_ID) : null
  if (!match || !Number.isInteger(slot) || slot < 0 || slot > 3) throw new AceContractError('设备或槽位无效', 'target')
  const deviceIndex = Number(match[1])
  if (deviceIndex >= deviceCount) throw new AceContractError('设备未配置', 'target.deviceId')
  return `T${deviceIndex * 4 + slot}`
}

export function buildAceViewModel (status) {
  const usesFirstStageHubs = status.devices.length > 1
  const devices = status.devices.map(device => Object.freeze({
    ...device,
    badge: device.readOnly ? '动作只读' : device.connected ? '在线' : '离线',
    statusTone: device.error || ERROR_DEVICE_STATES.has(device.state) ? 'error' : !device.connected ? 'offline' : READY_DEVICE_STATES.has(device.state) ? 'ready' : 'busy',
    rfidSummaryLabel: device.rfidLabel,
    temperatureLabel: device.temperature === null ? '--' : `${Math.round(device.temperature)}°C`,
    humidityLabel: device.humidity === null ? '--' : `${Math.round(device.humidity)}%`,
    dryerLabel: device.dryer.active
      ? `${device.dryer.targetTemperature ?? '--'}°C · ${device.dryer.remainingMinutes ?? '--'} 分钟`
      : '未运行',
    hasFirstStageHub: usesFirstStageHubs,
    hubSensor: usesFirstStageHubs ? status.path.sensors.hubs?.[device.id] ?? null : null,
    slots: device.slots.map(slot => Object.freeze({
      ...slot,
      active: status.system.currentTool === slot.tool || slot.loaded,
      routeLabel: `${slot.tool} · ${device.name} · ${slot.label}`,
      remainingLabel: slot.remainingPercent === null ? '余量未知' : `余量 ${Math.round(slot.remainingPercent)}%`,
      selectAvailability: getActionAvailability(status, ACE_ACTIONS.SELECT_TOOL, { device, slot }),
      settingsAvailability: getActionAvailability(status, ACE_ACTIONS.SET_SLOT, { device, slot }),
    })),
  }))
  const tools = devices.flatMap(device => device.slots.map(slot => Object.freeze({
    tool: slot.tool,
    deviceId: device.id,
    deviceName: device.name,
    slot: slot.index,
    slotLabel: slot.label,
    material: slot.materialLabel,
    color: slot.color,
    available: slot.available && !slot.empty,
    active: slot.active,
  })))
  const currentToolTarget = status.system.currentTool
    ? tools.find(tool => tool.tool === status.system.currentTool) || null
    : null
  const blockers = [
    status.system.degradedReason,
    ...devices.filter(device => !device.connected).map(device => `${device.name} 未连接。`),
    ...devices.filter(device => device.readOnly).map(device => `${device.name} 的物理动作已禁用。`),
    ...(status.toolchangeMode === 'automatic' && !status.toolchangeReady ? [status.toolchangeBlockedReason] : []),
    ...status.diagnostics.warnings.map(issue => issue.message),
    ...status.diagnostics.errors.map(issue => issue.message),
  ].filter(Boolean)
  return Object.freeze({
    status,
    materialTypes: status.materialTypes,
    devices: Object.freeze(devices),
    tools: Object.freeze(tools),
    currentTool: status.system.currentTool,
    currentToolLabel: status.system.currentToolLabel,
    currentToolTarget,
    endlessSpool: status.endlessSpool,
    toolchange: status.toolchange,
    feedAssist: status.feedAssist,
    sharedEncoder: status.path.encoders.shared,
    usesFirstStageHubs,
    configuredDeviceCount: devices.length,
    connectedDeviceCount: devices.filter(device => device.connected).length,
    busy: status.transaction.active,
    activityLabel: status.transaction.active ? status.transaction.phase || ACTION_LABELS[status.transaction.action] || status.transaction.action : '空闲',
    blockers: Object.freeze(blockers),
  })
}

// Stable public name used by both shipped frontends.
export const buildViewModel = buildAceViewModel

function sanitizeParams (params) {
  const source = record(params || {}, 'params')
  const forbidden = /^(?:gcode|command|script|raw|serial|payload)$/i
  const result = {}
  for (const [key, value] of Object.entries(source)) {
    if (forbidden.test(key)) throw new AceContractError(`禁止发送字段 ${key}`, 'params')
    if (typeof value === 'function' || typeof value === 'symbol' || value === undefined) throw new AceContractError(`字段 ${key} 无法序列化`, 'params')
    result[key] = value
  }
  return result
}

export function validateActionRequest (action, params = {}, options = {}) {
  if (!ACTION_SET.has(action)) throw new AceContractError('动作不在前端白名单中', 'action')
  const cleanParams = sanitizeParams(params)
  if ([ACE_ACTIONS.ENCODER_CALIBRATION_START, ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL].includes(action) && Object.keys(cleanParams).length) {
    throw new AceContractError('共享编码器校准开始和取消动作不接受参数', 'params')
  }
  if (action === ACE_ACTIONS.ENCODER_CALIBRATION_FINISH) {
    if (Object.keys(cleanParams).length !== 1 || !Object.hasOwn(cleanParams, 'length')) {
      throw new AceContractError('完成共享编码器校准只接受 length 参数', 'params')
    }
    if (typeof cleanParams.length !== 'number' || !Number.isFinite(cleanParams.length) || cleanParams.length < 0.01 || cleanParams.length > 2000) {
      throw new AceContractError('length 必须是 0.01..2000 的有限数值', 'params.length')
    }
  }
  if ('tool' in cleanParams) toolToTarget(String(cleanParams.tool), options.deviceCount || 4)
  if ('device_id' in cleanParams && !DEVICE_ID.test(String(cleanParams.device_id))) throw new AceContractError('device_id 必须是 ace0..ace3', 'params.device_id')
  if ('slot' in cleanParams && (!Number.isInteger(cleanParams.slot) || cleanParams.slot < 0 || cleanParams.slot > 3)) throw new AceContractError('slot 必须是 0..3', 'params.slot')
  return Object.freeze({
    action,
    params: Object.freeze(cleanParams),
    confirm: options.confirm === true,
    client: string(options.client, 'ace-dashboard'),
  })
}

export function collectPrintMonitorEvent (monitor, cursor = null, cursorSignature = '') {
  const sequence = Number(monitor?.eventSequence)
  if (!Number.isInteger(sequence) || sequence < 0) {
    return Object.freeze({ cursor, cursorSignature, event: null })
  }
  const issue = monitor?.mode === 'monitor'
    ? monitor.lastEvent || monitor.fault
    : monitor?.fault || monitor?.lastEvent
  if (!issue) {
    return Object.freeze({ cursor: sequence, cursorSignature: '', event: null })
  }
  const signature = JSON.stringify([
    sequence,
    monitor.mode || '',
    issue.code || '',
    issue.message || '',
    issue.probableCause || '',
    issue.context || null,
  ])
  if (cursor === null) {
    return Object.freeze({ cursor: sequence, cursorSignature: signature, event: null })
  }
  const sequenceRestarted = cursor !== null && (
    sequence < cursor ||
    (sequence === cursor && cursorSignature && signature !== cursorSignature)
  )
  const unseen = sequence > cursor || sequenceRestarted
  return Object.freeze({
    cursor: sequence,
    cursorSignature: signature,
    event: unseen ? issue : null,
  })
}

function requestId () {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `ace-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function withTimeout (promise, timeoutMs) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) return promise
  let timer
  const timeout = new Promise((_resolve, reject) => {
    timer = globalThis.setTimeout(() => {
      reject(new AceApiError('Moonraker ACE 请求超时。', {
        code: 'ACE_REQUEST_TIMEOUT',
        retryable: true,
      }))
    }, timeoutMs)
  })
  return Promise.race([promise, timeout]).finally(() => globalThis.clearTimeout(timer))
}

async function parseResponse (response) {
  let payload
  try {
    payload = await response.json()
  } catch {
    throw new AceApiError('Moonraker 返回了无效 JSON。', { status: response.status })
  }
  if (!response.ok) {
    const error = responseError(payload?.error || payload, payload)
    error.status = response.status
    throw error
  }
  return unwrapResponse(payload)
}

export class AceApiClient {
  constructor (options = {}) {
    this.rpcImpl = options.rpcImpl
    this.fetchImpl = options.fetchImpl || globalThis.fetch?.bind(globalThis)
    if (typeof this.rpcImpl !== 'function' && typeof this.fetchImpl !== 'function') throw new TypeError('需要 fetch 或 Moonraker RPC 实现。')
    this.baseUrl = string(options.baseUrl).replace(/\/$/, '')
    this.clientName = string(options.client, 'ace-dashboard')
    this.timeoutMs = finiteNumber(options.timeoutMs, 8000)
    this.pending = new Map()
  }

  async getStatus ({ signal } = {}) {
    if (typeof this.rpcImpl === 'function') {
      const payload = await withTimeout(
        Promise.resolve().then(() => this.rpcImpl('server.ace.status', {}, { signal })),
        this.timeoutMs
      )
      return normalizeAceStatus(payload)
    }
    return withTimeout((async () => {
      const response = await this.fetchImpl(`${this.baseUrl}${ACE_ENDPOINTS.status}`, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
        signal,
      })
      return normalizeAceStatus(await parseResponse(response))
    })(), this.timeoutMs)
  }

  async action (actionName, params = {}, actionOptions = {}) {
    const body = validateActionRequest(actionName, params, {
      confirm: actionOptions.confirm,
      client: actionOptions.client || this.clientName,
      deviceCount: actionOptions.deviceCount,
    })
    const key = actionOptions.dedupeKey || `${body.action}:${JSON.stringify(body.params)}`
    if (this.pending.has(key)) return this.pending.get(key)
    const promise = (async () => {
      if (typeof this.rpcImpl === 'function') {
        const payload = await withTimeout(
          Promise.resolve().then(() => this.rpcImpl('server.ace.action', body, { signal: actionOptions.signal })),
          this.timeoutMs
        )
        return unwrapResponse(payload)
      }
      return withTimeout((async () => {
        const response = await this.fetchImpl(`${this.baseUrl}${ACE_ENDPOINTS.action}`, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'X-ACE-Request-ID': requestId(),
          },
          credentials: 'same-origin',
          signal: actionOptions.signal,
          body: JSON.stringify(body),
        })
        return parseResponse(response)
      })(), this.timeoutMs)
    })()
    this.pending.set(key, promise)
    try {
      return await promise
    } finally {
      this.pending.delete(key)
    }
  }

  isPending (key) {
    return this.pending.has(key)
  }
}

export function createAceClient (options = {}) {
  return new AceApiClient(options)
}

export function actionLabel (action) {
  return ACTION_LABELS[action] || action
}

export function formatApiError (error) {
  if (error instanceof AceApiError) {
    const code = string(error.code, 'ACE_API_ERROR')
    return Object.freeze({
      title: code === 'ACE_ACTION_REJECTED' ? '操作被拒绝' : '操作失败',
      code,
      message: localizeBackendText(error.message, {
        code,
        fallback: 'ACE 操作未完成，请检查参数、设备连接和诊断信息。',
      }),
      reason: localizeBackendText(error.reason, {
        code,
        fallback: error.reason ? '后端返回的错误原因暂无中文说明，请检查诊断信息。' : '',
      }),
      nextAction: error.nextAction
        ? localizeBackendText(error.nextAction, { fallback: '请刷新状态，检查设备连接和诊断信息后重试。' })
        : (error.retryable ? '确认连接恢复后重试。' : '刷新状态并检查诊断信息。'),
      recoverable: error.recoverable,
    })
  }
  if (error instanceof AceContractError) {
    return Object.freeze({
      title: '状态数据不完整',
      code: error.code,
      message: localizeBackendText(error.message, {
        fallback: error.path ? `字段 ${error.path} 的状态数据无效。` : 'ACE 状态数据不符合前端约定。',
      }),
      reason: '',
      nextAction: '检查 ACE Pro 管理中心 V2.5ahpha 的 Moonraker 组件版本。',
      recoverable: false,
    })
  }
  const code = error && typeof error.code === 'string' ? error.code : ''
  return Object.freeze({
    title: '请求失败',
    code,
    message: localizeBackendText(error instanceof Error ? error.message : '', {
      code,
      fallback: '请求未完成，请检查网络连接和 ACE 诊断信息。',
    }),
    reason: '',
    nextAction: '检查网络连接后刷新状态。',
    recoverable: false,
  })
}
