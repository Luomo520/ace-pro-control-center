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
