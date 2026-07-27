import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'


test('standalone page matches the Fluidd calibration and preload controls', async () => {
  const html = await readFile('ace_status_integration/web/ace.html', 'utf8')

  for (const label of [
    '距离标定',
    '冷态预装载',
    '送料结果',
    '回料结果',
    '保存标定',
    '取消标定',
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
    'calibrateRetract',
    'saveCalibration',
    'fullUnload',
  ]) {
    const block = source.match(new RegExp(`async ${method}\\([^)]*\\) \\{([\\s\\S]*?)\\n        \\},`))
    assert.ok(block, `missing ${method}`)
    assert.match(block[1], /window\.confirm/)
  }
})
