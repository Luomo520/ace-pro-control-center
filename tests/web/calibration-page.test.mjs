import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'


test('standalone page matches the Fluidd calibration and preload controls', async () => {
  const html = await readFile('ace_status_integration/web/ace.html', 'utf8')

  for (const label of [
    '自动探测料管长度',
    '冷态预装载',
    '上方传感器 → 五通传感器',
    '五通传感器',
    '保存探测结果',
    '取消探测',
    '完全卸载',
    '紧急停止',
  ]) {
    assert.match(html, new RegExp(label))
  }
})


test('standalone page sends the complete strict ACE command set', async () => {
  const source = await readFile(
    'ace_status_integration/web/ace-dashboard.js',
    'utf8'
  )

  for (const command of [
    'ACE_PRELOAD',
    'ACE_CALIBRATE_FEED',
    'ACE_CALIBRATE',
    'ACE_CALIBRATE_RETRACT',
    'ACE_CALIBRATION_SAVE',
    'ACE_CALIBRATION_CANCEL',
    'ACE_FULL_UNLOAD',
    'ACE_ABORT_TOOLCHANGE',
    'ACE_CHANGE_TOOL',
  ]) {
    assert.match(source, new RegExp(command))
  }

  assert.doesNotMatch(source, /ACE_ACK_TOOLCHANGE/)
  assert.match(source, /ACE_FEED[\s\S]*CONFIRM:\s*1/)
  assert.match(source, /ACE_RETRACT[\s\S]*CONFIRM:\s*1/)
  assert.match(source, /calibrationParkingDistanceLabel\(\)/)
  assert.match(source, /calibrationUpperToParkingSensorResult\(\)/)
  assert.match(source, /calibrationUpperToParkingResult\(\)/)
  assert.match(source, /ACE_CALIBRATE[\s\S]*INDEX: index[\s\S]*CONFIRM: 1/)
})


test('standalone movement methods require a fresh browser confirmation', async () => {
  const source = await readFile(
    'ace_status_integration/web/ace-dashboard.js',
    'utf8'
  )

  for (const method of [
    'changeToolForInstance',
    'preloadSlot',
    'calibrateFeed',
    'calibrate',
    'calibrateRetract',
    'saveCalibration',
    'fullUnload',
  ]) {
    const block = source.match(new RegExp(`async ${method}\\([^)]*\\) \\{([\\s\\S]*?)\\n        \\},`))
    assert.ok(block, `missing ${method}`)
    assert.match(block[1], /window\.confirm/)
  }
})


test('standalone status and calibration panels remain compact in the dark theme', async () => {
  const [html, css] = await Promise.all([
    readFile('ace_status_integration/web/ace.html', 'utf8'),
    readFile('ace_status_integration/web/ace-dashboard.css', 'utf8'),
  ])

  assert.doesNotMatch(html, /class="info-col"/)
  assert.match(css, /\.card-row\s*\{[^}]*align-items:\s*start/s)
  assert.match(css, /\.calibration-status-item\s*\{[^}]*background:\s*#151921/s)
  assert.match(css, /\.calibration-slot-select select\s*\{[^}]*background:\s*#0f1216/s)
  assert.match(html, /五通后传感器/)
  assert.doesNotMatch(html, /deviceInfo\.rfid/)
})


test('standalone calibration exposes safe lock reasons and replaces fresh critical state', async () => {
  const [html, source] = await Promise.all([
    readFile('ace_status_integration/web/ace.html', 'utf8'),
    readFile('ace_status_integration/web/ace-dashboard.js', 'utf8'),
  ])

  assert.match(html, /calibrationBlockReason\(\)/)
  assert.match(html, /清除故障/)
  assert.match(source, /statusStale/)
  assert.match(source, /toolchange\.recovery_required/)
  assert.match(source, /状态已过期，等待刷新/)
  assert.match(source, /仍检测到耗材/)
  assert.match(source, /updateStatus\(statusData, true\)/)
  assert.match(source, /replaceCriticalState/)
})


test('configuration diagnostics stay read-only and preserve missing values', async () => {
  const [html, source, types, adapter, mixin] = await Promise.all([
    readFile('ace_status_integration/web/ace.html', 'utf8'),
    readFile('ace_status_integration/web/ace-dashboard.js', 'utf8'),
    readFile('fluidd-source-overlay/src/types/acePro.ts', 'utf8'),
    readFile('fluidd-source-overlay/src/util/acepro.ts', 'utf8'),
    readFile('fluidd-source-overlay/src/mixins/acePro.ts', 'utf8'),
  ])

  const fields = [
    'ace_config_version',
    'extruder_sensor_debounce_count',
    'toolhead_sensor_debounce_count',
    'toolchange_feed_hard_limit',
    'toolchange_retract_hard_limit',
  ]
  for (const field of fields) {
    assert.match(source, new RegExp(field))
    assert.match(adapter, new RegExp(field))
  }

  assert.match(html, /驱动配置诊断/)
  assert.match(html, /configurationDiagnostics\(\)/)
  assert.match(source, /value === null \? '未报告'/)
  assert.match(types, /AceProConfigurationState/)
  assert.match(adapter, /fallback\?\.configuration/)
  assert.match(mixin, /aceProConfigurationDiagnostics/)
  assert.doesNotMatch(html, /ACE_SET_CONFIG|保存驱动配置/)
})
