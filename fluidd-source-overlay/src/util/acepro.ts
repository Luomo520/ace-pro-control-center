import type {
  AceProAutoDryingReason,
  AceProAutoDryingState,
  AceProCalibrationState,
  AceProConfigurationState,
  AceProDryerStatus,
  AceProEndlessSpoolState,
  AceProHardwareSlot,
  AceProInventorySlot,
  AceProMaterialProfile,
  AceProResolvedSlot,
  AceProResolvedState,
  AceProSensorState,
  AceProSlotPosition,
} from '@/types/acePro'

type PrinterState = Record<string, any>

const EMPTY_COLOR: [number, number, number] = [0, 0, 0]
const SLOT_POSITIONS: AceProSlotPosition[] = [
  'internal_or_unknown',
  'preload_parked_estimated',
  'upper_sensor',
  'toolhead',
  'nozzle',
  'unknown',
]

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

function optionalNumber (value: unknown, fallback: number | null = null): number | null {
  if (value == null) return fallback
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
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

function resolveMaterialProfiles (
  value: unknown,
  fallback: Record<string, AceProMaterialProfile> = {}
): Record<string, AceProMaterialProfile> {
  if (!isObject(value)) return fallback

  return Object.entries(value).reduce<Record<string, AceProMaterialProfile>>(
    (profiles, [rawKey, rawValue]) => {
      if (!isObject(rawValue) || rawKey.toLowerCase() === '__meta__') return profiles
      const key = rawKey.startsWith('__') ? rawKey.toLowerCase() : rawKey.trim().toUpperCase()
      if (!key) return profiles
      profiles[key] = {
        name: safeString(rawValue.name, rawKey),
        dryingTemperature: safeNumber(rawValue.drying_temperature),
        materialTemperature: safeNumber(rawValue.material_temperature),
      }
      return profiles
    },
    {}
  )
}

function normalizeSlotPosition (value: unknown): AceProSlotPosition {
  return typeof value === 'string' && SLOT_POSITIONS.includes(value as AceProSlotPosition)
    ? value as AceProSlotPosition
    : 'unknown'
}

function resolveSlotPositions (value: unknown): AceProSlotPosition[] {
  const parsed = parseJsonIfNeeded<unknown[]>(value, [])
  return Array.from({ length: 4 }, (_, index) => normalizeSlotPosition(parsed[index]))
}

function resolveCalibration (
  value: unknown,
  fallback?: AceProCalibrationState
): AceProCalibrationState {
  const available = isObject(value)
  const raw = available ? value : {}
  return {
    available: available
      ? safeBoolean(raw.available, true)
      : (fallback?.available ?? false),
    valid: safeBoolean(raw.valid, fallback?.valid ?? false),
    stale: safeBoolean(raw.stale, fallback?.stale ?? false),
    phase: safeString(
      raw.phase,
      fallback?.phase ?? (available ? 'idle' : 'unavailable')
    ),
    mode: safeString(raw.mode, fallback?.mode ?? 'legacy_feed'),
    selectedSlot: safeNumber(raw.selected_slot, fallback?.selectedSlot ?? -1),
    feedCompleted: safeNumber(raw.feed_completed, fallback?.feedCompleted ?? 0),
    feedUpperBound: safeNumber(raw.feed_upper_bound, fallback?.feedUpperBound ?? 0),
    sensorClearCompleted: safeNumber(
      raw.sensor_clear_completed,
      fallback?.sensorClearCompleted ?? 0
    ),
    sensorClearUpperBound: safeNumber(
      raw.sensor_clear_upper_bound,
      fallback?.sensorClearUpperBound ?? 0
    ),
    retractDistance: safeNumber(raw.retract_distance, fallback?.retractDistance ?? 0),
    parkingDistance: safeNumber(raw.parking_distance, fallback?.parkingDistance ?? 0),
    parkingSensorCleared: safeBoolean(
      raw.parking_sensor_cleared,
      fallback?.parkingSensorCleared ?? false
    ),
    parkingDirection: safeString(
      raw.parking_direction,
      fallback?.parkingDirection ?? ''
    ),
    parkingOffset: safeNumber(raw.parking_offset, fallback?.parkingOffset ?? 0),
    upperToParkingSensorDistance: safeNumber(
      raw.upper_to_parking_sensor_distance,
      fallback?.upperToParkingSensorDistance ?? 0
    ),
    upperToParkingDistance: safeNumber(
      raw.upper_to_parking_distance,
      fallback?.upperToParkingDistance ?? 0
    ),
    bowdenTubeLength: safeNumber(raw.bowden_tube_length, fallback?.bowdenTubeLength ?? 0),
    lastError: safeString(raw.last_error, fallback?.lastError ?? ''),
  }
}

function resolveConfiguration (
  value: unknown,
  fallback?: AceProConfigurationState
): AceProConfigurationState {
  const raw = isObject(value) ? value : {}
  const nested = isObject(raw.configuration) ? raw.configuration : {}
  const read = (key: string, fallbackValue: number | null): number | null => {
    const candidate = raw[key] ?? nested[key]
    return optionalNumber(candidate, fallbackValue)
  }

  return {
    aceConfigVersion: read('ace_config_version', fallback?.aceConfigVersion ?? null),
    extruderSensorDebounceCount: read(
      'extruder_sensor_debounce_count',
      fallback?.extruderSensorDebounceCount ?? null
    ),
    toolheadSensorDebounceCount: read(
      'toolhead_sensor_debounce_count',
      fallback?.toolheadSensorDebounceCount ?? null
    ),
    toolchangeFeedHardLimit: read(
      'toolchange_feed_hard_limit',
      fallback?.toolchangeFeedHardLimit ?? null
    ),
    toolchangeRetractHardLimit: read(
      'toolchange_retract_hard_limit',
      fallback?.toolchangeRetractHardLimit ?? null
    ),
  }
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

export function autoDryingWarningMessage (reason: AceProAutoDryingReason, temperature = 0): string {
  const temperatureText = temperature > 0 ? `${temperature}°C` : '配置温度'
  if (reason === 'PLA_MIXED') {
    return `检测到 PLA 与其他材料混装，自动烘干使用 ${temperatureText} 以保护 PLA；其他材料的烘干效果可能受限。`
  }
  if (reason === 'UNKNOWN') {
    return `检测到未知材料，将以 ${temperatureText} 进行自动烘干，烘干效果可能受限。`
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
  const acePro = getAceProObject(printerState)
  const materialProfiles = resolveMaterialProfiles(acePro?.material_profiles)
  const variables = getAceProVariables(printerState)
  const slotPositions = resolveSlotPositions(
    acePro?.slot_positions ?? variables.ace_slot_positions
  )

  return inventory.map((inventorySlot, index) => {
    const hardwareSlot = hardwareSlots[index]
    const material = inventorySlot.material || hardwareSlot.type || ''
    const color = inventorySlot.status === 'ready' ? inventorySlot.color : hardwareSlot.color
    const ready = inventorySlot.status === 'ready' || hardwareSlot.status === 'ready'
    const profile = materialProfiles[material.trim().toUpperCase()]

    return {
      index,
      isActive: currentIndex === index,
      inventoryStatus: inventorySlot.status,
      hardwareStatus: hardwareSlot.status,
      material,
      temperature: inventorySlot.temp || profile?.materialTemperature || 0,
      dryingTemperature: profile?.dryingTemperature || 0,
      profileKnown: profile != null,
      color,
      sku: hardwareSlot.sku ?? '',
      type: hardwareSlot.type ?? '',
      ready,
      position: slotPositions[index],
    }
  })
}

export function resolveAceProState (printerState: PrinterState): AceProResolvedState {
  const aceProObjectKey = detectAceProObjectKey(printerState)
  const acePro = getAceProObject(printerState)
  const slots = resolveAceProSlots(printerState)
  const detected = aceProObjectKey != null || hasAceProConfig(printerState) || slots.some(slot => slot.material !== '')
  const variables = getAceProVariables(printerState)
  const slotPositions = resolveSlotPositions(
    acePro?.slot_positions ?? variables.ace_slot_positions
  )
  const currentIndex = resolveAceProCurrentIndex(printerState)
  const materialProfiles = resolveMaterialProfiles(acePro?.material_profiles)

  return {
    detected,
    stale: false,
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
    currentIndex,
    feedAssistIndex: safeNumber(acePro?.feed_assist_index, -1),
    slotPositions,
    filamentPosition: normalizeSlotPosition(
      acePro?.filament_position ?? slotPositions[currentIndex]
    ),
    motionOwner: safeString(acePro?.motion_owner),
    activeMotion: isObject(acePro?.active_motion) ? acePro.active_motion : {},
    calibration: resolveCalibration(acePro?.calibration),
    configuration: resolveConfiguration(acePro),
    sensors: {
      upper: resolveSensor(printerState, 'extruder_sensor'),
      lower: resolveSensor(printerState, 'toolhead_sensor'),
      parking: resolveApiSensor(
        acePro?.parking_sensor,
        resolveSensor({}, 'parking_sensor')
      ),
    },
    printing: ['printing', 'paused'].includes(
      safeString(printerState.print_stats?.state).toLowerCase()
    ),
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
    materialProfiles,
    slots,
  }
}

export function resolveAceProApiState (
  payload: Record<string, any>,
  fallback?: AceProResolvedState
): AceProResolvedState {
  if (
    payload.api_version === 1 &&
    ['ACE_PRO_CONTROL_CENTER', 'ACEPROSV08'].includes(payload.driver)
  ) {
    const materialProfiles = resolveMaterialProfiles(
      payload.material_profiles,
      fallback?.materialProfiles
    )
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
        temperature: safeNumber(slot.material_temperature ?? slot.temperature),
        dryingTemperature: safeNumber(slot.drying_temperature),
        profileKnown: safeBoolean(slot.profile_known, false),
        color: normalizeRgb(colorSource),
        sku: '',
        type: safeString(slot.material),
        ready: status === 'ready',
        position: normalizeSlotPosition(payload.slot_positions?.[index]),
      }
    })

    const dryer = isObject(payload.dryer) ? payload.dryer : {}
    const autoDrying = isObject(payload.auto_drying) ? payload.auto_drying : undefined
    const endlessSpool = isObject(payload.endless_spool) ? payload.endless_spool : {}
    const sensors = isObject(payload.sensors) ? payload.sensors : {}
    const fallbackUpper = fallback?.sensors.upper ?? resolveSensor({}, 'extruder_sensor')
    const fallbackLower = fallback?.sensors.lower ?? resolveSensor({}, 'toolhead_sensor')
    const fallbackParking = fallback?.sensors.parking ?? resolveSensor({}, 'parking_sensor')
    const slotPositions = resolveSlotPositions(payload.slot_positions)
    const currentIndex = safeNumber(payload.current_tool, -1)

    return {
      detected: true,
      stale: safeBoolean(payload.stale, false),
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
      currentIndex,
      feedAssistIndex: safeNumber(payload.feed_assist_index, -1),
      slotPositions,
      filamentPosition: normalizeSlotPosition(
        payload.filament_position ?? slotPositions[currentIndex]
      ),
      motionOwner: safeString(payload.motion_owner),
      activeMotion: isObject(payload.active_motion) ? payload.active_motion : {},
      calibration: resolveCalibration(payload.calibration, fallback?.calibration),
      configuration: resolveConfiguration(payload, fallback?.configuration),
      sensors: {
        upper: resolveApiSensor(sensors.upper, fallbackUpper),
        lower: resolveApiSensor(sensors.lower, fallbackLower),
        parking: resolveApiSensor(sensors.parking, fallbackParking),
      },
      printing: safeBoolean(payload.printing, false) || (fallback?.printing ?? false),
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
      materialProfiles,
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
  const materialProfiles = resolveMaterialProfiles(
    payload.material_profiles,
    fallback?.materialProfiles
  )

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
      dryingTemperature: safeNumber(
        slot.drying_temperature,
        fallbackSlot?.dryingTemperature ?? 0
      ),
      profileKnown: safeBoolean(
        slot.profile_known,
        fallbackSlot?.profileKnown ?? false
      ),
      color: slot.color == null ? (fallbackSlot?.color ?? [...EMPTY_COLOR]) : normalizeRgb(slot.color),
      sku: safeString(slot.sku, fallbackSlot?.sku ?? ''),
      type: safeString(slot.type, fallbackSlot?.type ?? ''),
      ready: status === 'ready',
      position: fallbackSlot?.position ?? 'unknown',
    }
  })

  const connectionState = safeString(payload.connection_state, 'disconnected')

  return {
    detected: true,
    stale: safeBoolean(payload.stale, fallback?.stale ?? false),
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
    slotPositions: fallback?.slotPositions ?? resolveSlotPositions(undefined),
    filamentPosition: normalizeSlotPosition(
      payload.filament_position ?? fallback?.filamentPosition
    ),
    motionOwner: safeString(payload.motion_owner, fallback?.motionOwner ?? ''),
    activeMotion: isObject(payload.active_motion)
      ? payload.active_motion
      : (fallback?.activeMotion ?? {}),
    calibration: resolveCalibration(payload.calibration, fallback?.calibration),
    configuration: resolveConfiguration(payload, fallback?.configuration),
    sensors: fallback?.sensors ?? {
      upper: resolveSensor({}, 'extruder_sensor'),
      lower: resolveSensor({}, 'toolhead_sensor'),
      parking: resolveSensor({}, 'parking_sensor'),
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
    materialProfiles,
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
