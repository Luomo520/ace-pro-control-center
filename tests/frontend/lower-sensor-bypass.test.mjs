import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { normalizeAceState } from '../../frontend/shared/ace-core.js'
import { makeStatus } from './fixtures.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const project = path.resolve(here, '../..')
const read = relative => readFile(path.join(project, relative), 'utf8')

test('lower sensor policy is normalized without replacing the raw sensor reading', () => {
  const raw = makeStatus(1)
  raw.path.sensors.lower = false
  raw.path.sensor_policy.upper = {
    control_endpoint: true,
    feed_timeout: '45.5',
  }
  raw.path.sensor_policy.lower = {
    bypassed: true,
    configured: true,
    calibrated: true,
    control_enabled: false,
    monitor_only: true,
    bypass_load_length: '123.5',
  }

  const state = normalizeAceState(raw)

  assert.equal(state.path.sensors.lower, false)
  assert.deepEqual(state.path.sensorPolicy.upper, {
    controlEndpoint: true,
    feedTimeout: 45.5,
  })
  assert.deepEqual(state.path.sensorPolicy.lower, {
    bypassed: true,
    configured: true,
    calibrated: true,
    controlEnabled: false,
    monitorOnly: true,
    bypassLoadLength: 123.5,
  })
  assert.equal(Object.isFrozen(state.path.sensorPolicy), true)
  assert.equal(Object.isFrozen(state.path.sensorPolicy.lower), true)
})

test('lower sensor policy supports camel case input and safe legacy defaults', () => {
  const camelRaw = makeStatus(1)
  delete camelRaw.path.sensor_policy
  camelRaw.path.sensorPolicy = {
    upper: { controlEndpoint: true, feedTimeout: 42 },
    lower: {
      bypassed: true,
      configured: false,
      calibrated: false,
      controlEnabled: false,
      monitorOnly: true,
      bypassLoadLength: 88,
    },
  }
  assert.deepEqual(normalizeAceState(camelRaw).path.sensorPolicy.upper, {
    controlEndpoint: true,
    feedTimeout: 42,
  })
  assert.deepEqual(normalizeAceState(camelRaw).path.sensorPolicy.lower, {
    bypassed: true,
    configured: false,
    calibrated: false,
    controlEnabled: false,
    monitorOnly: true,
    bypassLoadLength: 88,
  })

  const legacyRaw = makeStatus(1)
  delete legacyRaw.path.sensor_policy
  assert.deepEqual(normalizeAceState(legacyRaw).path.sensorPolicy.upper, {
    controlEndpoint: false,
    feedTimeout: null,
  })
  assert.deepEqual(normalizeAceState(legacyRaw).path.sensorPolicy.lower, {
    bypassed: false,
    configured: false,
    calibrated: false,
    controlEnabled: false,
    monitorOnly: false,
    bypassLoadLength: 0,
  })
})

test('upper sensor feed timeout rejects values outside the backend contract', () => {
  for (const value of [0, 120.01, -1, 'invalid']) {
    const raw = makeStatus(1)
    raw.path.sensor_policy.upper.feed_timeout = value
    assert.equal(normalizeAceState(raw).path.sensorPolicy.upper.feedTimeout, null)
  }
})

test('Fluidd card presents upper closed-loop control and lower monitoring without fault semantics', async () => {
  const card = await read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue')

  assert.match(card, /lowerSensorPolicy \(\)[\s\S]*this\.status\?\.path\?\.sensorPolicy\?\.lower/)
  assert.match(card, /upperSensorLabel \(\)[\s\S]*控制闭环 · \$\{this\.sensorLabel\('upper'\)\}/)
  assert.match(card, /lowerSensorLabel \(\)[\s\S]*this\.lowerSensorPolicy\.monitorOnly[\s\S]*仅监测[\s\S]*this\.lowerSensorPolicy\.controlEnabled[\s\S]*参与控制/)
  assert.match(card, /lowerSensorTitle \(\)[\s\S]*仅用于监测，不参与换料控制/)
  assert.match(card, /sensorStatusClass \(name\)[\s\S]*name === 'lower' && this\.lowerSensorPolicy\.monitorOnly[\s\S]*acepro-sensor-status--monitor-only/)
  assert.match(card, /feedControlLabel \(\)[\s\S]*ACE 参考送料 -> 上方传感器闭环终止/)
  for (const label of ['上方送料超时', '挤出机标定距离', '编码器最低跟随比例']) assert.match(card, new RegExp(label))
  assert.match(card, /sharedEncoder\.state === 'not_armed'[\s\S]*保护模式尚未启用/)
  assert.match(card, /sharedEncoder\.mode === 'monitor'[\s\S]*仅提示，不参与控制[\s\S]*sharedEncoder\.mode === 'protect'[\s\S]*参与送料保护/)
  assert.match(card, /\.acepro-info-item \.acepro-sensor-status--monitor-only\s*\{[\s\S]*#e5e7eb[\s\S]*rgba\(75, 85, 99, 0\.82\)/)
  assert.doesNotMatch(card, /已屏蔽/)
})

test('simulator exposes and renders the lower sensor bypass scenario', async () => {
  const [html, script, styles, sharedCore, overlayCore] = await Promise.all([
    read('frontend/simulator/index.html'),
    read('frontend/simulator/app.js'),
    read('frontend/simulator/styles.css'),
    read('frontend/shared/ace-core.js'),
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/ace-core.js'),
  ])

  assert.match(html, /<option value="lower-bypass">下方仅监测<\/option>/)
  assert.match(script, /sensor_policy:\s*\{[\s\S]*bypassed: state\.scenario === 'lower-bypass'[\s\S]*bypass_load_length:/)
  assert.match(script, /sensor\(viewModel\.status\.path\.sensors\.lower, lowerPolicy\.monitorOnly \? 'monitor-only' : ''\)/)
  assert.match(script, /acepro-sensor-status--monitor-only[\s\S]*不参与换料控制[\s\S]*仅监测 · \$\{label\}/)
  assert.match(script, /ACE 参考送料 -&gt; 上方传感器闭环终止/)
  for (const label of ['上方送料超时', '挤出机标定距离', '编码器最低跟随比例']) assert.match(script, new RegExp(label))
  assert.match(script, /encoder\.state === 'not_armed'[\s\S]*保护模式尚未启用/)
  assert.match(styles, /\.acepro-info-item \.acepro-sensor-status--monitor-only\s*\{[\s\S]*#e5e7eb[\s\S]*rgba\(75, 85, 99, 0\.82\)/)
  assert.doesNotMatch(html + script, /已屏蔽/)
  assert.equal(overlayCore, sharedCore)
})

test('standalone status presents the same normalized sensor policy metrics', async () => {
  const [dashboard, simulator] = await Promise.all([
    read('frontend/dashboard/app.js'),
    read('frontend/simulator/app.js'),
  ])

  for (const source of [dashboard, simulator]) {
    assert.match(source, /ACE 送料[\s\S]*参考送料 · 上方传感器闭环终止/)
    assert.match(source, /上方传感器[\s\S]*控制闭环/)
    assert.match(source, /下方传感器/)
    assert.match(source, /不参与换料控制/)
    assert.doesNotMatch(source, /下方传感器已屏蔽|下方传感器.*故障/)
    for (const label of ['上方送料超时', '挤出机标定距离', '编码器最低跟随比例']) assert.match(source, new RegExp(label))
  }
  assert.match(dashboard, /lowerPolicyLabel[\s\S]*仅监测 · \$\{lower\}/)
  assert.match(simulator, /lowerPolicy\.monitorOnly \? 'monitor-only' : ''/)
  assert.match(simulator, /仅监测 · \$\{label\}/)
})
