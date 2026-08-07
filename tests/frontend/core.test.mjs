import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ACE_ACTIONS,
  AceApiClient,
  AceApiError,
  AceContractError,
  buildViewModel,
  canPerformAction,
  collectPrintMonitorEvent,
  ENCODER_CALIBRATION_DEFAULTS,
  evaluateEncoderCalibrationSegments,
  formatApiError,
  normalizeAceState,
  targetToTool,
  toolToTarget,
  validateActionRequest,
} from '../../frontend/shared/ace-core.js'
import { DEFAULT_MATERIAL_TYPES, makeStatus } from './fixtures.mjs'

test('stable public exports normalize one to four devices', () => {
  for (let count = 1; count <= 4; count += 1) {
    const state = normalizeAceState(makeStatus(count))
    const viewModel = buildViewModel(state)
    assert.equal(state.devices.length, count)
    assert.equal(viewModel.tools.length, count * 4)
    assert.equal(viewModel.tools.at(-1).tool, `T${count * 4 - 1}`)
    assert.equal(viewModel.devices[0].slots[0].label, '槽1')
    const expectedHubIds = count > 1 ? Array.from({ length: count }, (_, index) => `ace${index}`) : []
    const expectedHubStates = count > 1 ? [true, false, null, true].slice(0, count) : [null]
    assert.deepEqual(Object.keys(state.path.sensors.hubs), expectedHubIds)
    assert.deepEqual(viewModel.devices.map(device => device.hubSensor), expectedHubStates)
  }
  assert.equal(typeof AceApiClient, 'function')
  assert.equal(typeof canPerformAction, 'function')
})

test('null current tool represents an unloaded path', () => {
  const raw = makeStatus(1)
  raw.system.current_tool = null
  const state = normalizeAceState(raw)
  assert.equal(state.system.currentTool, null)
})

test('configured material types preserve API order through the view model', () => {
  const raw = makeStatus(1)
  raw.material_types = ['PLA Silk', 'PETG-HF', 'TPU 95A']

  const state = normalizeAceState(raw)
  const viewModel = buildViewModel(state)
  assert.deepEqual(state.materialTypes, ['PLA Silk', 'PETG-HF', 'TPU 95A'])
  assert.strictEqual(viewModel.materialTypes, state.materialTypes)
  assert.equal(Object.isFrozen(viewModel.materialTypes), true)
})

test('empty or invalid material types use the complete default list', () => {
  const invalidValues = [undefined, null, [], 'PLA,PETG', ['PLA', ''], ['PLA', 42]]
  for (const value of invalidValues) {
    const raw = makeStatus(1)
    if (value === undefined) delete raw.material_types
    else raw.material_types = value

    const viewModel = buildViewModel(normalizeAceState(raw))
    assert.deepEqual(viewModel.materialTypes, DEFAULT_MATERIAL_TYPES)
  }
})

test('shared path keeps configured false sensor readings', () => {
  const raw = makeStatus(1)
  raw.devices[0].state = 'ready'
  raw.path = {
    busy: false,
    state: 'empty',
    sensors: { upper: false, lower: false, rdm: false },
  }

  const state = normalizeAceState(raw)
  const device = buildViewModel(state).devices[0]
  assert.equal(state.path.busy, false)
  assert.equal(state.path.state, 'empty')
  assert.deepEqual(state.path.sensors, { upper: false, lower: false, rdm: false, hubs: {} })
  assert.deepEqual(state.path.topology, {
    currentDevice: null,
    route: [],
    branchClearance: {},
  })
  assert.equal(device.hasFirstStageHub, false)
  assert.equal(buildViewModel(state).usesFirstStageHubs, false)
  assert.equal(device.statusTone, 'ready')
})

test('multi-hub sensors and two-stage topology are normalized per configured device', () => {
  const raw = makeStatus(4)
  raw.path.sensors.hubs = { ace0: false, ace1: true, ace2: 'invalid', ace3: null, ace4: true }
  raw.path.topology = {
    current_device: 'ace2',
    route: 'device_hub -> rdm -> upper -> lower',
    branch_clearance: { ace0: 0, ace1: '42.5', ace2: null, ace3: 'invalid', ace4: 99 },
  }

  const state = normalizeAceState(raw)
  const viewModel = buildViewModel(state)
  assert.deepEqual(state.path.sensors.hubs, { ace0: false, ace1: true, ace2: null, ace3: null })
  assert.deepEqual(state.path.topology, {
    currentDevice: 'ace2',
    route: ['device_hub', 'rdm', 'upper', 'lower'],
    branchClearance: { ace0: 0, ace1: 42.5, ace2: null, ace3: null },
  })
  assert.deepEqual(viewModel.devices.map(device => device.hubSensor), [false, true, null, null])
  assert.equal(viewModel.usesFirstStageHubs, true)
  assert.equal(viewModel.devices.every(device => device.hasFirstStageHub), true)
  assert.equal(Object.isFrozen(state.path.sensors.hubs), true)
  assert.equal(Object.isFrozen(state.path.topology.route), true)
  assert.equal(Object.isFrozen(state.path.topology.branchClearance), true)
})

test('legacy status without hubs or topology remains compatible', () => {
  const raw = makeStatus(3)
  delete raw.path.sensors.hubs
  delete raw.path.topology

  const state = normalizeAceState(raw)
  assert.deepEqual(state.path.sensors.hubs, { ace0: null, ace1: null, ace2: null })
  assert.deepEqual(state.path.topology, {
    currentDevice: null,
    route: [],
    branchClearance: { ace0: null, ace1: null, ace2: null },
  })
  assert.deepEqual(buildViewModel(state).devices.map(device => device.hubSensor), [null, null, null])
})

test('shared encoder normalizes mode and health without breaking legacy status', () => {
  const cases = [
    {
      name: 'unconfigured',
      encoder: null,
      expected: { mode: 'off', state: 'unconfigured', label: '未配置', tone: 'muted' },
    },
    {
      name: 'off',
      encoder: { configured: true, available: true, mode: 'off', calibrated: true, resolution: 0.75 },
      expected: { mode: 'off', state: 'off', label: '已关闭', tone: 'muted' },
    },
    {
      name: 'monitor',
      encoder: { configured: true, available: true, mode: 'monitor', calibrated: true, resolution: 0.75 },
      expected: { mode: 'monitor', state: 'normal', label: '监测 · 只读', tone: 'monitor' },
    },
    {
      name: 'protect',
      encoder: { configured: true, available: true, mode: 'protect', calibrated: true, armed: true, resolution: 0.75 },
      expected: { mode: 'protect', state: 'normal', label: '保护 · 正常', tone: 'protect' },
    },
    {
      name: 'protect not armed',
      encoder: { configured: true, available: true, mode: 'protect', calibrated: true, armed: false, resolution: 0.75 },
      expected: { mode: 'protect', state: 'not_armed', label: '保护 · 未启用', tone: 'warning' },
    },
    {
      name: 'protect missing armed',
      encoder: { configured: true, available: true, mode: 'protect', calibrated: true, resolution: 0.75 },
      expected: { mode: 'protect', state: 'not_armed', label: '保护 · 未启用', tone: 'warning' },
    },
    {
      name: 'uncalibrated',
      encoder: { configured: true, available: true, mode: 'protect', calibrated: false, resolution: null },
      expected: { mode: 'protect', state: 'uncalibrated', label: '保护 · 未校准', tone: 'warning' },
    },
    {
      name: 'calibrating',
      encoder: { configured: true, available: true, mode: 'off', calibrated: false, calibration_active: true },
      expected: { mode: 'off', state: 'calibrating', label: '关闭 · 校准中', tone: 'warning' },
    },
    {
      name: 'fault',
      encoder: {
        configured: true,
        available: true,
        mode: 'protect',
        calibrated: true,
        resolution: 0.75,
        fault: { code: 'encoder_no_motion', message: 'no motion' },
      },
      expected: { mode: 'protect', state: 'fault', label: '保护 · 故障', tone: 'error' },
    },
  ]

  for (const { name, encoder, expected } of cases) {
    const raw = makeStatus(1)
    if (encoder === null) delete raw.path.encoders
    else raw.path.encoders.shared = encoder
    const state = normalizeAceState(raw)
    const shared = state.path.encoders.shared
    assert.equal(shared.mode, expected.mode, name)
    assert.equal(shared.state, expected.state, name)
    assert.equal(shared.summaryLabel, expected.label, name)
    assert.equal(shared.tone, expected.tone, name)
    assert.strictEqual(buildViewModel(state).sharedEncoder, shared, name)
    assert.equal(Object.isFrozen(shared), true, name)
  }
})

test('shared encoder keeps measurements and fault details from path.encoders.shared', () => {
  const raw = makeStatus(1)
  raw.path.encoders.shared = {
    configured: true,
    available: false,
    mode: 'monitor',
    calibrated: true,
    resolution: '0.625',
    detection_length: '18.5',
    counts: 320,
    position: 200,
    tracking_ratio: '0.98',
    min_tracking_ratio: '0.625',
    calibration_active: true,
  }

  const shared = normalizeAceState(raw).path.encoders.shared
  assert.equal(shared.state, 'calibrating')
  assert.equal(shared.summaryLabel, '监测 · 校准中')
  assert.equal(shared.resolution, 0.625)
  assert.equal(shared.detectionLength, 18.5)
  assert.equal(shared.counts, 320)
  assert.equal(shared.position, 200)
  assert.equal(shared.trackingRatio, 0.98)
  assert.equal(shared.minTrackingRatio, 0.625)
  assert.equal(shared.calibrationActive, true)
})

test('shared encoder accepts camel case minimum tracking ratio and rejects invalid fractions', () => {
  const camelRaw = makeStatus(1)
  camelRaw.path.encoders.shared.minTrackingRatio = 0.72
  delete camelRaw.path.encoders.shared.min_tracking_ratio
  assert.equal(normalizeAceState(camelRaw).path.encoders.shared.minTrackingRatio, 0.72)

  for (const value of [0, -0.1, 1.01, 'invalid']) {
    const raw = makeStatus(1)
    raw.path.encoders.shared.min_tracking_ratio = value
    assert.equal(normalizeAceState(raw).path.encoders.shared.minTrackingRatio, null)
  }
})

test('legacy encoder protection and faults never leak into print_monitor', () => {
  const raw = makeStatus(1)
  raw.path.encoders.shared = {
    configured: true,
    available: true,
    enabled: true,
    mode: 'protect',
    calibrated: true,
    resolution: 0.625,
    fault: { code: 'encoder_fault', message: 'ACE encoder fault' },
    last_event: { code: 'encoder_event', message: 'ACE encoder event' },
    event_sequence: 99,
  }

  const shared = normalizeAceState(raw).path.encoders.shared
  assert.equal(shared.mode, 'protect')
  assert.equal(shared.fault.code, 'encoder_fault')
  assert.deepEqual(shared.printMonitor, {
    mode: 'off',
    modeLabel: '关闭',
    enabled: false,
    active: false,
    state: 'off',
    statusLabel: '关闭',
    tone: 'muted',
    detectionLength: null,
    extrusionSinceMotion: null,
    headroom: null,
    eventSequence: 0,
    lastEvent: null,
    fault: null,
    pauseRequested: false,
    raw: {},
  })
})

test('print_monitor only accepts off monitor and pause and preserves fault context', () => {
  const raw = makeStatus(1)
  raw.path.encoders.shared.print_monitor = {
    mode: 'pause',
    enabled: true,
    active: false,
    state: 'pause_requested',
    detection_length: 20,
    extrusion_since_motion: 20,
    headroom: 0,
    event_sequence: 7,
    fault: {
      code: 'encoder_no_motion',
      message: 'No motion',
      probable_cause: 'Filament slip',
      pause_requested: true,
      context: {
        tool: 'T0',
        device: 'ace0',
        path_state: 'loaded',
        print_state: 'printing',
        sensors: { upper: true, lower: false, hubs: { ace0: true } },
      },
    },
  }

  const monitor = normalizeAceState(raw).path.encoders.shared.printMonitor
  assert.equal(monitor.mode, 'pause')
  assert.equal(monitor.statusLabel, '故障')
  assert.equal(monitor.pauseRequested, true)
  assert.equal(monitor.fault.message, '编码器未检测到耗材移动。')
  assert.equal(monitor.fault.probableCause, '耗材可能打滑或卡住。')
  assert.doesNotMatch(`${monitor.fault.message} ${monitor.fault.probableCause}`, /No motion|Filament slip/)
  assert.deepEqual(monitor.fault.context, {
    tool: 'T0',
    device: 'ace0',
    pathState: 'loaded',
    printState: 'printing',
    sensors: { upper: true, lower: false, hubs: { ace0: true } },
  })

  raw.path.encoders.shared.print_monitor.mode = 'protect'
  assert.equal(normalizeAceState(raw).path.encoders.shared.printMonitor.mode, 'off')
})

test('print monitor events are delivered once per event_sequence', () => {
  const raw = makeStatus(1)
  raw.path.encoders.shared.print_monitor = {
    mode: 'monitor', enabled: true, active: true, state: 'monitoring', event_sequence: 0,
    last_event: null,
  }
  const baseline = collectPrintMonitorEvent(
    normalizeAceState(raw).path.encoders.shared.printMonitor
  )
  assert.equal(baseline.cursor, 0)
  assert.equal(baseline.event, null)

  raw.path.encoders.shared.print_monitor.event_sequence = 3
  raw.path.encoders.shared.print_monitor.last_event = {
    code: 'encoder_no_motion', message: 'No motion',
  }
  const monitor = normalizeAceState(raw).path.encoders.shared.printMonitor
  const first = collectPrintMonitorEvent(
    monitor, baseline.cursor, baseline.cursorSignature
  )
  const repeated = collectPrintMonitorEvent(monitor, first.cursor, first.cursorSignature)
  assert.equal(first.event.message, '编码器未检测到耗材移动。')
  assert.equal(repeated.event, null)

  const refreshedPage = collectPrintMonitorEvent(monitor)
  assert.equal(refreshedPage.event, null)
  assert.equal(refreshedPage.cursor, 3)

  raw.path.encoders.shared.print_monitor.event_sequence = 4
  raw.path.encoders.shared.print_monitor.last_event.message = 'Second event'
  const next = collectPrintMonitorEvent(
    normalizeAceState(raw).path.encoders.shared.printMonitor,
    repeated.cursor,
    repeated.cursorSignature,
  )
  assert.equal(next.event.message, '编码器未检测到耗材移动。')
  assert.doesNotMatch(next.event.message, /Second event/)
})

test('API errors localize known and unknown English without changing API codes', () => {
  const known = formatApiError(new AceApiError('The shared filament path is busy.', {
    code: 'path_busy',
    reason: 'The shared filament path is busy.',
    nextAction: 'Wait',
    recoverable: true,
  }))
  assert.equal(known.code, 'path_busy')
  assert.equal(known.message, '共享耗材路径正忙。')
  assert.equal(known.reason, '共享耗材路径正忙。')
  assert.equal(known.nextAction, '请等待当前操作完成后重试。')
  assert.doesNotMatch(`${known.message} ${known.reason} ${known.nextAction}`, /shared filament path|wait/i)

  const unknown = formatApiError(new AceApiError('Servo flux mismatch', {
    code: 'future_backend_error',
    reason: 'Motor phase was unexpected',
    nextAction: 'Replace the undocumented component',
  }))
  assert.equal(unknown.code, 'future_backend_error')
  assert.equal(unknown.message, 'ACE 操作未完成，请检查参数、设备连接和诊断信息。')
  assert.equal(unknown.reason, '后端返回的错误原因暂无中文说明，请检查诊断信息。')
  assert.equal(unknown.nextAction, '请刷新状态，检查设备连接和诊断信息后重试。')
  assert.doesNotMatch(`${unknown.message} ${unknown.reason} ${unknown.nextAction}`, /Servo|Motor|Replace|undocumented/i)

  const codeOnly = formatApiError(new AceApiError('', { code: 'device_offline' }))
  assert.equal(codeOnly.code, 'device_offline')
  assert.equal(codeOnly.message, '目标 ACE 设备未连接。')

  const chinese = formatApiError(new AceApiError('设备连接已断开。', {
    code: 'device_offline',
    reason: '串口当前不可用。',
    nextAction: '重新连接后重试。',
  }))
  assert.equal(chinese.message, '设备连接已断开。')
  assert.equal(chinese.reason, '串口当前不可用。')
  assert.equal(chinese.nextAction, '重新连接后重试。')
})

test('status issues, notices and capability reasons never expose backend English', () => {
  const raw = makeStatus(1)
  raw.devices[0].capabilities = {
    ...raw.devices[0].capabilities,
    feed: {
      available: false,
      physical: true,
      reason: 'Physical actions are disabled.',
    },
  }
  raw.diagnostics = {
    errors: [{
      code: 'future_diagnostic_code',
      message: 'Undocumented diagnostic failure',
      probable_cause: 'Unknown motor condition',
      next_action: 'Inspect the undocumented component',
      context: { tool: 'T0', device: 'ace0' },
    }],
  }
  raw.toolchange_ready = false
  raw.toolchange_blocked_reason = 'future_toolchange_gate'
  raw.toolchange_blocked_detail = 'An undocumented toolchange gate is active'
  raw.toolchange_notice = {
    sequence: 1,
    code: 'FUTURE_NOTICE',
    command: 'T0',
    message: 'Undocumented toolchange notice',
  }

  const state = normalizeAceState(raw)
  const issue = state.diagnostics.errors[0]
  assert.equal(state.devices[0].capabilities.feed.reason, 'ACE 物理动作已禁用。')
  assert.equal(issue.code, 'future_diagnostic_code')
  assert.equal(issue.context.tool, 'T0')
  assert.equal(issue.context.device, 'ace0')
  assert.equal(issue.message, 'ACE 返回了一条未翻译的状态或故障信息，请检查诊断信息。')
  assert.equal(issue.probableCause, '暂时无法确定具体原因，请检查耗材路径、传感器和设备连接。')
  assert.equal(issue.nextAction, '请检查耗材路径、传感器和设备连接后再重试。')
  assert.equal(state.toolchangeBlockedReason, '自动换料当前不可用，请检查 ACE 配置和诊断信息。')
  assert.equal(state.toolchangeNotice.code, 'FUTURE_NOTICE')
  assert.equal(state.toolchangeNotice.command, 'T0')
  assert.equal(state.toolchangeNotice.message, 'ACE 返回了一条未翻译的换料提示，请检查诊断信息。')
  assert.doesNotMatch(
    [
      state.devices[0].capabilities.feed.reason,
      issue.message,
      issue.probableCause,
      issue.nextAction,
      state.toolchangeBlockedReason,
      state.toolchangeNotice.message,
    ].join(' '),
    /Physical actions|Undocumented|Unknown motor|Inspect the/i,
  )
})

test('shared encoder calibration requests use strict fixed action contracts', () => {
  assert.equal(validateActionRequest(ACE_ACTIONS.ENCODER_CALIBRATION_START).action, 'encoder_calibration_start')
  assert.deepEqual(validateActionRequest(ACE_ACTIONS.ENCODER_CALIBRATION_FINISH, { length: 100 }).params, { length: 100 })
  assert.equal(validateActionRequest(ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL).action, 'encoder_calibration_cancel')
  assert.throws(() => validateActionRequest(ACE_ACTIONS.ENCODER_CALIBRATION_START, { device_id: 'ace0' }), /不接受参数/)
  assert.throws(() => validateActionRequest(ACE_ACTIONS.ENCODER_CALIBRATION_FINISH, {}), /只接受 length/)
  for (const length of [0, 0.009, 2000.01, true, '100', Infinity]) {
    assert.throws(() => validateActionRequest(ACE_ACTIONS.ENCODER_CALIBRATION_FINISH, { length }), /0\.01\.\.2000/)
  }
})

test('three-segment encoder calibration applies pulse and deviation gates', () => {
  assert.deepEqual(ENCODER_CALIBRATION_DEFAULTS, {
    segmentCount: 3,
    segmentLength: 150,
    passDeviationPercent: 5,
    warningDeviationPercent: 10,
    minimumPulses: 2,
  })

  const passed = evaluateEncoderCalibrationSegments([
    { length: 150, pulses: 100 },
    { length: 150, pulses: 100 },
    { length: 150, pulses: 100 },
  ])
  assert.equal(passed.state, 'passed')
  assert.equal(passed.canSave, true)

  const warning = evaluateEncoderCalibrationSegments([
    { length: 140, pulses: 100 },
    { length: 150, pulses: 100 },
    { length: 160, pulses: 100 },
  ])
  assert.equal(warning.state, 'warning')
  assert.equal(warning.canSave, true)

  const rejected = evaluateEncoderCalibrationSegments([
    { length: 120, pulses: 100 },
    { length: 150, pulses: 100 },
    { length: 180, pulses: 100 },
  ])
  assert.equal(rejected.state, 'rejected')
  assert.equal(rejected.canSave, false)

  const tooFewPulses = evaluateEncoderCalibrationSegments([
    { length: 150, pulses: 1 },
    { length: 150, pulses: 100 },
    { length: 150, pulses: 100 },
  ])
  assert.equal(tooFewPulses.state, 'rejected')
  assert.equal(tooFewPulses.canSave, false)
})

test('connected non-action states use the ready tone', () => {
  for (const deviceState of ['idle', 'ready', 'standby', 'online', 'complete', 'completed']) {
    const raw = makeStatus(1)
    raw.devices[0].state = deviceState
    const device = buildViewModel(normalizeAceState(raw)).devices[0]
    assert.equal(device.statusTone, 'ready', deviceState)
  }
})

test('read-only capability does not override the connected ready tone', () => {
  const raw = makeStatus(2, ['ace1', 'ace2'])
  raw.devices[0].physical_actions_enabled = false
  raw.devices[1].physical_actions_enabled = false
  raw.devices[0].state = 'ready'
  raw.devices[1].state = 'ready'

  const devices = buildViewModel(normalizeAceState(raw)).devices
  assert.equal(devices[0].readOnly, true)
  assert.equal(devices[0].statusTone, 'ready')
  assert.equal(devices[1].readOnly, true)
  assert.equal(devices[1].statusTone, 'ready')
})

test('device error states always use the error tone', () => {
  for (const withEnvelope of [false, true]) {
    const raw = makeStatus(1)
    raw.devices[0].state = 'error'
    if (withEnvelope) raw.devices[0].error = { code: 'DEVICE_ERROR', message: 'failed' }
    const device = buildViewModel(normalizeAceState(raw)).devices[0]
    assert.equal(device.statusTone, 'error')
  }
})

test('RFID defaults enabled and exposes user-facing slot labels', () => {
  const raw = makeStatus(1)
  const readings = [0, 1, 2, 3]
  raw.devices[0].slots.forEach((slot, index) => {
    slot.rfid = readings[index]
  })

  const device = normalizeAceState(raw).devices[0]
  assert.equal(device.rfidEnabled, true)
  assert.equal(device.rfidLabel, '识别中')
  assert.deepEqual(device.slots.map(slot => slot.rfidEnabled), [true, true, true, true])
  assert.deepEqual(device.slots.map(slot => slot.rfidState), ['missing', 'failed', 'identified', 'identifying'])
  assert.deepEqual(device.slots.map(slot => slot.rfidLabel), ['已关闭', '已关闭', '已识别', '识别中'])
})

test('RFID summary follows configuration and mixed protocol states', () => {
  const cases = [
    { configured: false, slots: [2, 3, 2, 3], expected: '已关闭' },
    { configured: true, slots: [1, 0, 1, 0], expected: '已关闭' },
    { configured: undefined, slots: [2, 2, 2, 2], expected: '已识别' },
    { configured: undefined, slots: [3, 0, 2, null], expected: '识别中' },
    { configured: undefined, slots: [2, 1, 2, 0], expected: '部分识别' },
    { configured: undefined, slots: ['rfid-uid', 'rfid-uid', 'rfid-uid', 'rfid-uid'], expected: '已识别' },
    { configured: undefined, slots: [null, null, null, null], expected: '未提供' },
  ]

  for (const { configured, slots, expected } of cases) {
    const raw = makeStatus(1)
    if (configured !== undefined) raw.devices[0].rfid_enabled = configured
    raw.devices[0].slots.forEach((slot, index) => {
      slot.rfid = slots[index]
    })
    const stateDevice = normalizeAceState(raw).devices[0]
    const viewDevice = buildViewModel(normalizeAceState(raw)).devices[0]
    assert.equal(stateDevice.rfidEnabled, configured ?? true)
    assert.equal(stateDevice.rfidLabel, expected)
    assert.equal(viewDevice.rfidLabel, expected)
    assert.equal(viewDevice.rfidSummaryLabel, expected)
    if (configured === false) {
      assert.ok(stateDevice.slots.every(slot => slot.rfidEnabled === false && slot.rfidLabel === '已关闭'))
    }
  }
})

test('tool mapping is stable through T15', () => {
  assert.deepEqual(toolToTarget('T5', 2), {
    tool: 'T5', toolIndex: 5, deviceId: 'ace1', deviceIndex: 1, slot: 1,
  })
  assert.equal(targetToTool('ace3', 3, 4), 'T15')
  assert.throws(() => toolToTarget('T8', 2), AceContractError)
  assert.throws(() => targetToTool('ace2', 0, 2), AceContractError)
})

test('device order and slot mapping fail closed', () => {
  const wrongOrder = makeStatus(2)
  wrongOrder.devices[1].id = 'ace2'
  assert.throws(() => normalizeAceState(wrongOrder), /配置顺序连续/)

  const wrongTool = makeStatus(1)
  wrongTool.devices[0].slots[2].tool = 'T3'
  assert.throws(() => normalizeAceState(wrongTool), /工具映射应为 T2/)
})

test('device model does not override backend physical capabilities', () => {
  const state = normalizeAceState(makeStatus(2, ['ace1', 'ace2']))
  const ace2 = state.devices[1]
  assert.equal(ace2.physicalActionsEnabled, true)
  assert.equal(ace2.readOnly, false)
  const select = canPerformAction(state, ACE_ACTIONS.SELECT_TOOL, { device: ace2, slot: ace2.slots[0] })
  const dryer = canPerformAction(state, ACE_ACTIONS.START_DRYING, { device: ace2 })
  const inventory = canPerformAction(state, ACE_ACTIONS.SET_SLOT, { device: ace2, slot: ace2.slots[0] })
  assert.equal(select.allowed, true)
  assert.equal(dryer.allowed, true)
  assert.equal(inventory.allowed, true)

  const blockedRaw = makeStatus(2, ['ace1', 'ace2'])
  blockedRaw.devices[1].physical_actions_enabled = false
  const blocked = normalizeAceState(blockedRaw)
  assert.equal(canPerformAction(blocked, ACE_ACTIONS.FEED, { device: blocked.devices[1] }).allowed, false)
})

test('offline diagnostics and recovery remain available', () => {
  const raw = makeStatus(1)
  raw.devices[0].connected = false
  const state = normalizeAceState(raw)
  const device = state.devices[0]

  assert.equal(canPerformAction(state, ACE_ACTIONS.DIAGNOSE, { device }).allowed, true)
  assert.equal(canPerformAction(state, ACE_ACTIONS.RECOVER, { device }).allowed, true)
  assert.equal(canPerformAction(state, ACE_ACTIONS.SELECT_TOOL, { device, slot: device.slots[1] }).allowed, false)
})

test('endless spool is one global non-physical setting', () => {
  const raw = makeStatus(2, ['ace1', 'ace2'])
  raw.endless_spool = { enabled: true, match_mode: 'material' }
  const state = normalizeAceState(raw)
  const viewModel = buildViewModel(state)

  assert.deepEqual(viewModel.endlessSpool, {
    enabled: true,
    matchMode: 'material',
    candidates: [],
    lastSelection: '',
  })
  assert.equal(canPerformAction(state, ACE_ACTIONS.SET_ENDLESS_SPOOL).allowed, true)
})

test('physical actions obey transaction, path and print gates', () => {
  const activeTransaction = makeStatus(1)
  activeTransaction.transaction = { active: true, action: 'feed', phase: 'feeding' }
  let state = normalizeAceState(activeTransaction)
  assert.match(canPerformAction(state, ACE_ACTIONS.SELECT_TOOL, { device: state.devices[0], slot: state.devices[0].slots[1] }).reason, /事务结束/)

  const printing = makeStatus(1)
  printing.system.print_state = 'printing'
  state = normalizeAceState(printing)
  assert.equal(canPerformAction(state, ACE_ACTIONS.SELECT_TOOL, { device: state.devices[0], slot: state.devices[0].slots[1] }).allowed, false)
  assert.equal(canPerformAction(state, ACE_ACTIONS.START_DRYING, { device: state.devices[0] }).allowed, true)

  const unknown = makeStatus(1)
  unknown.system.print_state = 'unknown'
  state = normalizeAceState(unknown)
  assert.equal(canPerformAction(state, ACE_ACTIONS.SELECT_TOOL, { device: state.devices[0], slot: state.devices[0].slots[1] }).allowed, false)

  const locked = makeStatus(1)
  locked.path_lock = { locked: true, owner: 'ace-maintenance' }
  state = normalizeAceState(locked)
  assert.match(canPerformAction(state, ACE_ACTIONS.UNLOAD, { device: state.devices[0] }).reason, /ace-maintenance/)
})

test('missing capabilities never become executable', () => {
  const raw = makeStatus(1)
  raw.capabilities = {}
  raw.devices[0].capabilities = {}
  const state = normalizeAceState(raw)
  const decision = canPerformAction(state, ACE_ACTIONS.SELECT_TOOL, { device: state.devices[0], slot: state.devices[0].slots[1] })
  assert.equal(decision.allowed, false)
  assert.match(decision.reason, /未声明/)
})

test('manual and not-ready modes only gate automatic toolchange actions', () => {
  for (const mode of ['manual', 'automatic']) {
    const raw = makeStatus(1)
    raw.toolchange_mode = mode
    raw.toolchange_ready = false
    raw.toolchange_blocked_reason = mode === 'manual' ? '当前为手动模式。' : '自动换料配置缺少切刀坐标。'
    const state = normalizeAceState(raw)
    const device = state.devices[0]
    const slot = device.slots[1]

    assert.equal(state.toolchangeMode, mode)
    assert.equal(state.toolchangeReady, false)
    assert.equal(canPerformAction(state, ACE_ACTIONS.SELECT_TOOL, { device, slot }).allowed, false)
    assert.equal(canPerformAction(state, ACE_ACTIONS.UNLOAD, { device }).allowed, false)
    assert.equal(canPerformAction(state, ACE_ACTIONS.SET_ENDLESS_SPOOL).allowed, false)
    assert.equal(canPerformAction(state, ACE_ACTIONS.FEED, { device, slot }).allowed, true)
    assert.equal(canPerformAction(state, ACE_ACTIONS.RETRACT, { device, slot }).allowed, true)
    assert.equal(canPerformAction(state, ACE_ACTIONS.START_DRYING, { device }).allowed, true)
    assert.equal(canPerformAction(state, ACE_ACTIONS.ENABLE_FEED_ASSIST, { device, slot }).allowed, true)
    assert.equal(canPerformAction(state, ACE_ACTIONS.SET_SLOT, { device, slot }).allowed, true)
    assert.equal(buildViewModel(state).devices[0].statusTone, 'ready')
  }
})

test('missing toolchange contract defaults to non-failing manual mode', () => {
  const raw = makeStatus(1)
  delete raw.toolchange_mode
  delete raw.toolchange_ready
  delete raw.toolchange_blocked_reason
  const state = normalizeAceState(raw)
  assert.equal(state.toolchangeMode, 'manual')
  assert.equal(state.toolchangeReady, false)
  assert.match(state.toolchangeBlockedReason, /自动换料未启用/)
})

test('toolchange reason codes are rendered as user-facing text', () => {
  const manual = makeStatus(1)
  manual.toolchange_mode = 'manual'
  manual.toolchange_ready = false
  manual.toolchange_blocked_reason = 'manual_mode'
  manual.toolchange_blocked_detail = 'ACE automatic tool changes are not enabled'
  assert.equal(
    normalizeAceState(manual).toolchangeBlockedReason,
    '自动换料未启用，当前仅可使用手动功能。',
  )

  const bypass = makeStatus(1)
  bypass.toolchange_mode = 'automatic'
  bypass.toolchange_ready = false
  bypass.toolchange_blocked_reason = 'lower_sensor_bypass_uncalibrated'
  assert.equal(
    normalizeAceState(bypass).toolchangeBlockedReason,
    '上方传感器触发后，挤出机定距送料尚未校准。',
  )

  const future = makeStatus(1)
  future.toolchange_mode = 'automatic'
  future.toolchange_ready = false
  future.toolchange_blocked_reason = 'future_reason_code'
  future.toolchange_blocked_detail = '自动换料正在等待维护确认。'
  assert.equal(
    normalizeAceState(future).toolchangeBlockedReason,
    '自动换料正在等待维护确认。',
  )
})

test('toolchange notice queue is ordered, deduplicated and preserves latest notice', () => {
  const raw = makeStatus(1)
  raw.toolchange_notices = [
    { sequence: 3, code: 'IGNORED', command: 'T3', message: '第三条' },
    { sequence: 1, code: 'IGNORED', command: 'T1', message: '第一条' },
    { sequence: 2, code: 'IGNORED', command: 'T2', message: '旧内容' },
    { sequence: 2, code: 'IGNORED', command: 'T2', message: '第二条' },
    { sequence: 'bad', command: 'T0', message: '无效条目' },
  ]
  raw.toolchange_notice = { sequence: 4, code: 'IGNORED', command: 'TR', message: '第四条' }
  const state = normalizeAceState(raw)

  assert.deepEqual(state.toolchangeNotices.map(notice => notice.sequence), [1, 2, 3, 4])
  assert.equal(state.toolchangeNotices[1].message, '第二条')
  assert.deepEqual(state.toolchangeNotice, state.toolchangeNotices.at(-1))
  assert.strictEqual(state.toolchange.notices, state.toolchangeNotices)
})

test('feed assist capability and active global slot are normalized', () => {
  const raw = makeStatus(2, ['ace1', 'ace2'])
  raw.feed_assist = { active: true, device_id: 'ace1', slot: 2 }
  raw.system.print_state = 'printing'
  const state = normalizeAceState(raw)
  const activeDevice = state.devices[1]
  const activeSlot = activeDevice.slots[2]

  assert.deepEqual(state.feedAssist, {
    active: true,
    deviceId: 'ace1',
    slot: 2,
    tool: 'T6',
    targetValid: true,
    label: 'T6 · ACE 2 · 槽3',
  })
  assert.strictEqual(buildViewModel(state).feedAssist, state.feedAssist)
  const enable = canPerformAction(state, ACE_ACTIONS.ENABLE_FEED_ASSIST, { device: state.devices[0], slot: state.devices[0].slots[1] })
  const disable = canPerformAction(state, ACE_ACTIONS.DISABLE_FEED_ASSIST, { device: activeDevice, slot: activeSlot })
  assert.equal(enable.allowed, true)
  assert.equal(enable.requiresConfirmation, true)
  assert.equal(disable.allowed, true)
  assert.equal(disable.requiresConfirmation, false)

  raw.devices[1].connected = false
  raw.devices[1].physical_actions_enabled = false
  raw.path_lock = { locked: true, owner: 'print-path' }
  raw.transaction = { active: true, action: 'feed', phase: 'printing' }
  const constrained = normalizeAceState(raw)
  const stop = canPerformAction(constrained, ACE_ACTIONS.DISABLE_FEED_ASSIST, {
    device: constrained.devices[1],
    slot: constrained.devices[1].slots[2],
  })
  assert.equal(stop.allowed, true)
  assert.equal(stop.requiresConfirmation, false)
})
