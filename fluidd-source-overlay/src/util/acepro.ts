import type {
  AceProAutoDryingReason,
  AceProAutoDryingState,
  AceProDryerStatus,
  AceProEndlessSpoolState,
  AceProHardwareSlot,
  AceProInventorySlot,
  AceProResolvedSlot,
  AceProResolvedState,
  AceProSensorState,
} from '@/types/acePro'

type PrinterState = Record<string, any>

const EMPTY_COLOR: [number, number, number] = [0, 0, 0]

function isObject (value: unknown): value is Record<string, any> {
  return typeof value === 'object' && value !== null
}

function isRgbTriplet (value: unknown): value is [number, number, number] {
  return Array.isArray(value) &&
    value.length === 3 &&
    value.every(channel => typeof channel === 'number' && Number.isFinite(channel))
}

function normalizeRgb (value: unknown): [number, number, number] {
  if (isRgbTriplet(value)) {
    return value.map(channel => Math.max(0, Math.min(255, Math.round(channel)))) as [number, number, number]
  }

  if (typeof value === 'string') {
    const hex = value.trim().replace('#', '')
    if (/^[0-9a-f]{6}$/i.test(hex)) {
      return [
        Number.parseInt(hex.slice(0, 2), 16),
        Number.parseInt(hex.slice(2, 4), 16),
        Number.parseInt(hex.slice(4, 6), 16),
      ]
    }
  }

  return [...EMPTY_COLOR]
}

function safeNumber (value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }

  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }

  return fallback
}

function safeString (value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function safeBoolean (value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') {
    return value
  }

  if (typeof value === 'string') {
    if (value === 'True' || value === 'true' || value === '1') return true
    if (value === 'False' || value === 'false' || value === '0') return false
  }

  if (typeof value === 'number') {
    return value !== 0
  }

  return fallback
}

function parseJsonIfNeeded<T> (value: unknown, fallback: T): T {
  if (typeof value === 'string') {
    try {
      return JSON.parse(value) as T
    } catch {
      return fallback
    }
  }

  return (value as T) ?? fallback
}

function resolveSensor (printerState: PrinterState, name: string): AceProSensorState {
  const sensor = printerState[`filament_switch_sensor ${name}`]
  return {
    name,
    available: isObject(sensor),
    detected: isObject(sensor) && safeBoolean(sensor.filament_detected, false),
  }
}

function resolveApiSensor (value: unknown, fallback: AceProSensorState): AceProSensorState {
  const sensor = isObject(value) ? value : {}
  return {
    name: safeString(sensor.name, fallback.name),
    available: safeBoolean(sensor.available, fallback.available),
    detected: safeBoolean(sensor.detected, fallback.detected),
  }
}

function resolveWarnings (value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((warning): warning is string => typeof warning === 'string')
    : []
}

const AUTO_DRYING_REASONS: AceProAutoDryingReason[] = [
  'EMPTY', 'UNKNOWN', 'PLA_MIXED', 'PLA_ONLY', 'HIGH_TEMP',
]

const AUTO_DRYING_BASIS: Record<AceProAutoDryingReason, string> = {
  EMPTY: '未检测到耗材',
  UNKNOWN: '未知材料',
  PLA_MIXED: 'PLA 混装',
  PLA_ONLY: '全部 PLA',
  HIGH_TEMP: '高温材料',
}

function resolveAutoDrying (
  value: unknown,
  fallback?: AceProAutoDryingState
): AceProAutoDryingState {
  const available = isObject(value)
  const raw = available ? value : {}
  const rawReason = safeString(raw.reason, fallback?.reason ?? 'EMPTY')
  const reason = AUTO_DRYING_REASONS.includes(rawReason as AceProAutoDryingReason)
    ? rawReason as AceProAutoDryingReason
    : 'UNKNOWN'
  return {
    available: available
      ? safeBoolean(raw.available, true)
      : (fallback?.available ?? false),
    enabled: safeBoolean(raw.enabled, fallback?.enabled ?? false),
    active: safeBoolean(raw.active, fallback?.active ?? false),
    ownedByAuto: safeBoolean(raw.owned_by_auto, fallback?.ownedByAuto ?? false),
    suppressedForJob: safeBoolean(
      raw.suppressed_for_job,
      fallback?.suppressedForJob ?? false
    ),
    temperature: safeNumber(raw.temperature, fallback?.temperature ?? 0),
    reason,
    printState: safeString(raw.print_state, fallback?.printState ?? 'standby'),
    lastError: safeString(raw.last_error, fallback?.lastError ?? ''),
    noticeId: safeNumber(raw.notice_id, fallback?.noticeId ?? 0),
    noticeMessage: safeString(
      raw.notice_message,
      fallback?.noticeMessage ?? ''
    ),
  }
}

export function autoDryingStatusLabel (state: AceProAutoDryingState): string {
  if (!state.available) return '状态不可用'
  if (!state.enabled) return '已关闭'
  if (state.active) return `运行中 ${state.temperature}°C`
  return '已开启'
}

export function autoDryingBasisLabel (state: AceProAutoDryingState): string {
  const basis = AUTO_DRYING_BASIS[state.reason]
  return state.temperature > 0 ? `${state.temperature}°C · ${basis}` : basis
}

export function autoDryingWarningMessage (reason: AceProAutoDryingReason): string {
  if (reason === 'PLA_MIXED') {
    return '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；其他高温材料的烘干效果可能受限。'
  }
  if (reason === 'UNKNOWN') {
    return '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。'
  }
  return ''
}

export function shouldShowAceNotice (incoming: number, seen: number): boolean {
  return incoming > 0 && incoming > seen
}

export function shouldResetAceNoticeSequence (incoming: number, seen: number): boolean {
  return incoming >= 0 && incoming < seen
}

export function detectAceProObjectKey (printerState: PrinterState): string | undefined {
  return Object.keys(printerState).find((key) => {
    if (!/^ace(?:\s|$)/i.test(key)) return false
    const value = printerState[key]
    return isObject(value) && (Array.isArray(value.slots) || isObject(value.dryer))
  })
}

export function hasAceProConfig (printerState: PrinterState): boolean {
  const settings = printerState.configfile?.settings
  if (!isObject(settings)) return false
  return Object.keys(settings).some(key => /^ace(?:\s|$)/i.test(key))
}

export function getAceProObject (printerState: PrinterState): Record<string, any> | undefined {
  const objectKey = detectAceProObjectKey(printerState)
  if (objectKey == null) return undefined
  const value = printerState[objectKey]
  return isObject(value) ? value : undefined
}

export function getAceProVariables (printerState: PrinterState): Record<string, any> {
  const variables = printerState.save_variables?.variables
  return isObject(variables) ? variables : {}
}

export function resolveAceProInventory (printerState: PrinterState): AceProInventorySlot[] {
  const variables = getAceProVariables(printerState)
  const inventory = parseJsonIfNeeded<unknown[]>(variables.ace_inventory, [])

  return Array.from({ length: 4 }, (_, index) => {
    const slot = inventory[index]
    if (!isObject(slot)) {
      return {
        status: 'empty',
        color: [...EMPTY_COLOR],
        material: '',
        temp: 0,
      }
    }

    return {
      status: safeString(slot.status, 'empty'),
      color: normalizeRgb(slot.color),
      material: safeString(slot.material),
      temp: safeNumber(slot.temp),
    }
  })
}

export function resolveAceProHardwareSlots (printerState: PrinterState): AceProHardwareSlot[] {
  const acePro = getAceProObject(printerState)
  const slots = Array.isArray(acePro?.slots) ? acePro?.slots : []

  return Array.from({ length: 4 }, (_, index) => {
    const slot = slots[index]
    if (!isObject(slot)) {
      return {
        index,
        status: 'unknown',
        sku: '',
        type: '',
        color: [...EMPTY_COLOR],
      }
    }

    return {
      index,
      status: safeString(slot.status, 'unknown'),
      sku: safeString(slot.sku),
      type: safeString(slot.type),
      color: normalizeRgb(slot.color),
    }
  })
}

export function resolveAceProCurrentIndex (printerState: PrinterState): number {
  const variables = getAceProVariables(printerState)
  return safeNumber(variables.ace_current_index, -1)
}

export function resolveAceProEndlessSpool (printerState: PrinterState): AceProEndlessSpoolState {
  const acePro = getAceProObject(printerState)
  const variables = getAceProVariables(printerState)
  const endlessSpool = isObject(acePro?.endless_spool) ? acePro?.endless_spool : {}

  return {
    enabled: safeBoolean(endlessSpool.enabled, safeBoolean(variables.ace_endless_spool_enabled, false)),
    runoutDetected: safeBoolean(endlessSpool.runout_detected, false),
    inProgress: safeBoolean(endlessSpool.in_progress, false),
  }
}

export function resolveAceProDryer (printerState: PrinterState): AceProDryerStatus {
  const acePro = getAceProObject(printerState)
  const dryer = isObject(acePro?.dryer)
    ? acePro?.dryer
    : isObject(acePro?.dryer_status) ? acePro?.dryer_status : {}

  return {
    status: safeString(dryer.status ?? dryer.state, 'stop'),
    target_temp: safeNumber(dryer.target_temp ?? dryer.target_temperature ?? dryer.temperature),
    duration: safeNumber(dryer.duration ?? dryer.duration_minutes),
    remain_time: safeNumber(dryer.remain_time ?? dryer.remaining_minutes ?? dryer.remaining_time),
  }
}

export function resolveAceProSlots (printerState: PrinterState): AceProResolvedSlot[] {
  const inventory = resolveAceProInventory(printerState)
  const hardwareSlots = resolveAceProHardwareSlots(printerState)
  const currentIndex = resolveAceProCurrentIndex(printerState)

  return inventory.map((inventorySlot, index) => {
    const hardwareSlot = hardwareSlots[index]
    const material = inventorySlot.material || hardwareSlot.type || ''
    const color = inventorySlot.status === 'ready' ? inventorySlot.color : hardwareSlot.color
    const ready = inventorySlot.status === 'ready' || hardwareSlot.status === 'ready'

    return {
      index,
      isActive: currentIndex === index,
      inventoryStatus: inventorySlot.status,
      hardwareStatus: hardwareSlot.status,
      material,
      temperature: inventorySlot.temp,
      color,
      sku: hardwareSlot.sku ?? '',
      type: hardwareSlot.type ?? '',
      ready,
    }
  })
}

export function resolveAceProState (printerState: PrinterState): AceProResolvedState {
  const aceProObjectKey = detectAceProObjectKey(printerState)
  const acePro = getAceProObject(printerState)
  const slots = resolveAceProSlots(printerState)
  const detected = aceProObjectKey != null || hasAceProConfig(printerState) || slots.some(slot => slot.material !== '')

  return {
    detected,
    objectKey: aceProObjectKey,
    connected: acePro != null,
    model: safeString(acePro?.model, 'Anycubic Color Engine Pro'),
    firmware: safeString(acePro?.firmware, ''),
    bootFirmware: safeString(acePro?.boot_firmware, ''),
    status: safeString(acePro?.status, detected ? 'unknown' : 'offline'),
    connectionState: safeString(acePro?.connection_state, acePro != null ? 'connected' : 'disconnected'),
    temperature: safeNumber(acePro?.temp),
    humidity: acePro?.humidity == null ? null : safeNumber(acePro?.humidity),
    fanSpeed: safeNumber(acePro?.fan_speed),
    rfidEnabled: safeBoolean(acePro?.enable_rfid, false),
    usbPort: safeString(acePro?.usb_port),
    usbPath: safeString(acePro?.usb_path),
    currentIndex: resolveAceProCurrentIndex(printerState),
    feedAssistIndex: safeNumber(acePro?.feed_assist_index, -1),
    sensors: {
      upper: resolveSensor(printerState, 'extruder_sensor'),
      lower: resolveSensor(printerState, 'toolhead_sensor'),
    },
    printing: safeString(printerState.print_stats?.state).toLowerCase() === 'printing',
    warnings: [],
    toolchange: {
      active: false,
      context: {},
      lastError: '',
      recoveryRequired: false,
      cancelRequested: false,
    },
    endlessSpool: resolveAceProEndlessSpool(printerState),
    autoDrying: resolveAutoDrying(acePro?.auto_drying),
    dryer: resolveAceProDryer(printerState),
    slots,
  }
}

export function resolveAceProApiState (
  payload: Record<string, any>,
  fallback?: AceProResolvedState
): AceProResolvedState {
  if (payload.api_version === 1 && payload.driver === 'ACEPROSV08') {
    const apiSlots = Array.isArray(payload.slots) ? payload.slots : []
    const slots = Array.from({ length: 4 }, (_, index): AceProResolvedSlot => {
      const slot = isObject(apiSlots[index]) ? apiSlots[index] : {}
      const colorSource = isObject(slot.color) ? slot.color.rgb : slot.color
      const status = safeString(slot.status, 'empty')

      return {
        index,
        isActive: safeNumber(payload.current_tool, -1) === index,
        inventoryStatus: status,
        hardwareStatus: status,
        material: safeString(slot.material),
        temperature: safeNumber(slot.temperature),
        color: normalizeRgb(colorSource),
        sku: '',
        type: safeString(slot.material),
        ready: status === 'ready',
      }
    })

    const dryer = isObject(payload.dryer) ? payload.dryer : {}
    const autoDrying = isObject(payload.auto_drying) ? payload.auto_drying : undefined
    const endlessSpool = isObject(payload.endless_spool) ? payload.endless_spool : {}
    const sensors = isObject(payload.sensors) ? payload.sensors : {}
    const fallbackUpper = fallback?.sensors.upper ?? resolveSensor({}, 'extruder_sensor')
    const fallbackLower = fallback?.sensors.lower ?? resolveSensor({}, 'toolhead_sensor')

    return {
      detected: true,
      objectKey: 'ace',
      connected: safeBoolean(payload.connected, false),
      model: 'Anycubic Color Engine Pro',
      firmware: '',
      bootFirmware: '',
      status: safeString(payload.status, payload.connected ? 'ready' : 'offline'),
      connectionState: safeBoolean(payload.connected, false) ? 'connected' : 'disconnected',
      temperature: safeNumber(payload.temperature),
      humidity: fallback?.humidity ?? null,
      fanSpeed: safeNumber(payload.fan_speed),
      rfidEnabled: false,
      usbPort: '',
      usbPath: '',
      currentIndex: safeNumber(payload.current_tool, -1),
      feedAssistIndex: safeNumber(payload.feed_assist_index, -1),
      sensors: {
        upper: resolveApiSensor(sensors.upper, fallbackUpper),
        lower: resolveApiSensor(sensors.lower, fallbackLower),
      },
      printing: safeBoolean(payload.printing, false),
      warnings: resolveWarnings(payload.warnings),
      toolchange: {
        active: safeBoolean(payload.toolchange?.active, false),
        context: isObject(payload.toolchange?.context) ? payload.toolchange.context : {},
        lastError: safeString(payload.toolchange?.last_error),
        recoveryRequired: safeBoolean(payload.toolchange?.recovery_required, false),
        cancelRequested: safeBoolean(payload.toolchange?.cancel_requested, false),
      },
      endlessSpool: {
        enabled: safeBoolean(endlessSpool.enabled, false),
        runoutDetected: safeBoolean(endlessSpool.runout_detected, false),
        inProgress: safeBoolean(endlessSpool.in_progress, false),
      },
      autoDrying: resolveAutoDrying(autoDrying, fallback?.autoDrying),
      dryer: {
        status: safeString(dryer.status, 'stop'),
        target_temp: safeNumber(dryer.target_temperature),
        duration: safeNumber(dryer.duration_minutes),
        remain_time: safeNumber(dryer.remaining_minutes),
      },
      slots,
    }
  }

  const manager = isObject(payload.ace_manager) ? payload.ace_manager : {}
  const autoDrying = isObject(payload.auto_drying) ? payload.auto_drying : undefined
  const dryer = isObject(payload.dryer_status) ? payload.dryer_status : {}
  const dryerDuration = safeNumber(dryer.duration, fallback?.dryer.duration ?? 0)
  const rawRemainTime = safeNumber(dryer.remain_time, fallback?.dryer.remain_time ?? 0)
  const remainTime = rawRemainTime > 1440 ||
    (dryerDuration > 0 && rawRemainTime > dryerDuration * 1.5 && rawRemainTime > 60)
    ? rawRemainTime / 60
    : rawRemainTime
  const apiSlots = Array.isArray(payload.slots) ? payload.slots : []
  const currentIndex = safeNumber(manager.current_index, fallback?.currentIndex ?? -1)

  const slots = Array.from({ length: 4 }, (_, index): AceProResolvedSlot => {
    const slot = isObject(apiSlots[index]) ? apiSlots[index] : {}
    const fallbackSlot = fallback?.slots[index]
    const status = safeString(slot.status, fallbackSlot?.hardwareStatus ?? 'unknown')
    const material = safeString(slot.material, fallbackSlot?.material ?? '')

    return {
      index,
      isActive: currentIndex === index,
      inventoryStatus: status,
      hardwareStatus: status,
      material: material === 'Unknown' ? '' : material,
      temperature: safeNumber(slot.temp, fallbackSlot?.temperature ?? 0),
      color: slot.color == null ? (fallbackSlot?.color ?? [...EMPTY_COLOR]) : normalizeRgb(slot.color),
      sku: safeString(slot.sku, fallbackSlot?.sku ?? ''),
      type: safeString(slot.type, fallbackSlot?.type ?? ''),
      ready: status === 'ready',
    }
  })

  const connectionState = safeString(payload.connection_state, 'disconnected')

  return {
    detected: true,
    connected: connectionState === 'connected',
    model: safeString(payload.model, fallback?.model ?? 'Anycubic Color Engine Pro'),
    firmware: safeString(payload.firmware, fallback?.firmware ?? ''),
    bootFirmware: safeString(payload.boot_firmware, fallback?.bootFirmware ?? ''),
    status: safeString(payload.status, 'unknown'),
    connectionState,
    temperature: safeNumber(payload.temp, fallback?.temperature ?? 0),
    humidity: payload.humidity == null ? (fallback?.humidity ?? null) : safeNumber(payload.humidity),
    fanSpeed: safeNumber(payload.fan_speed, fallback?.fanSpeed ?? 0),
    rfidEnabled: safeBoolean(payload.enable_rfid, fallback?.rfidEnabled ?? false),
    usbPort: safeString(payload.usb_port, fallback?.usbPort ?? ''),
    usbPath: safeString(payload.usb_path, fallback?.usbPath ?? ''),
    currentIndex,
    feedAssistIndex: safeNumber(payload.feed_assist_index, fallback?.feedAssistIndex ?? -1),
    sensors: fallback?.sensors ?? {
      upper: resolveSensor({}, 'extruder_sensor'),
      lower: resolveSensor({}, 'toolhead_sensor'),
    },
    printing: safeBoolean(payload.printing, fallback?.printing ?? false),
    warnings: resolveWarnings(payload.warnings),
    toolchange: {
      active: safeBoolean(payload.toolchange?.active, fallback?.toolchange.active ?? false),
      context: isObject(payload.toolchange?.context)
        ? payload.toolchange.context
        : (fallback?.toolchange.context ?? {}),
      lastError: safeString(payload.toolchange?.last_error, fallback?.toolchange.lastError ?? ''),
      recoveryRequired: safeBoolean(
        payload.toolchange?.recovery_required,
        fallback?.toolchange.recoveryRequired ?? false
      ),
      cancelRequested: safeBoolean(
        payload.toolchange?.cancel_requested,
        fallback?.toolchange.cancelRequested ?? false
      ),
    },
    endlessSpool: {
      enabled: safeBoolean(manager.endless_spool_enabled, fallback?.endlessSpool.enabled ?? false),
      runoutDetected: safeBoolean(manager.runout_detected, fallback?.endlessSpool.runoutDetected ?? false),
      inProgress: safeBoolean(manager.in_progress, fallback?.endlessSpool.inProgress ?? false),
    },
    autoDrying: resolveAutoDrying(autoDrying, fallback?.autoDrying),
    dryer: {
      status: safeString(dryer.status, fallback?.dryer.status ?? 'stop'),
      target_temp: safeNumber(dryer.target_temp, fallback?.dryer.target_temp ?? 0),
      duration: dryerDuration,
      remain_time: remainTime,
    },
    slots,
  }
}

export function rgbToHex (value: [number, number, number]): string {
  return `#${value.map(channel => channel.toString(16).padStart(2, '0')).join('')}`.toUpperCase()
}

export function hexToRgb (value: string): [number, number, number] {
  return normalizeRgb(value)
}

export function rgbToCss (value: [number, number, number]): string {
  return `rgb(${value[0]}, ${value[1]}, ${value[2]})`
}

export function buildAceSetSlotGcode (
  index: number,
  material: string,
  color: [number, number, number],
  temperature: number
): string {
  const cleanMaterial = material.trim().toUpperCase()
  return `ACE_SET_SLOT INDEX=${index} MATERIAL=${cleanMaterial} COLOR=${color.join(',')} TEMP=${Math.round(temperature)}`
}
