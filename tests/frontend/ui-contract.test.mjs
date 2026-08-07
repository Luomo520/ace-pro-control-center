import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const project = path.resolve(here, '../..')
const read = relative => readFile(path.join(project, relative), 'utf8')

test('frontend publishes the Ace Pro Control Center product identity', async () => {
  const [dashboard, dashboardApp, simulator, simulatorApp, card, core, overlayCore, packageJson, manifest] = await Promise.all([
    read('frontend/dashboard/index.html'),
    read('frontend/dashboard/app.js'),
    read('frontend/simulator/index.html'),
    read('frontend/simulator/app.js'),
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue'),
    read('frontend/shared/ace-core.js'),
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/ace-core.js'),
    read('frontend/package.json'),
    read('frontend/fluidd-overlay/manifest.json'),
  ])
  const packageMetadata = JSON.parse(packageJson)
  const overlayMetadata = JSON.parse(manifest)
  const publicSource = [dashboard, simulator, simulatorApp, card, core].join('\n')

  assert.equal(packageMetadata.name, 'ace-pro-control-center-frontend')
  assert.equal(packageMetadata.version, '2.5.0-alpha.0')
  assert.equal(overlayMetadata.name, 'ace-pro-control-center-fluidd-overlay')
  assert.equal(overlayMetadata.version, '2.5.0-alpha.0')
  assert.equal(overlayMetadata.navigation_label, 'ACE Pro 管理中心')
  assert.match(publicSource, /ACE Pro 管理中心/)
  assert.match(core, /Ace Pro Control Center shared frontend core, version V2\.5ahpha\./)
  assert.doesNotMatch(publicSource, /ACE Driver V3|ACE V3 控制中心|ACE Pro 控制面板/)
  assert.equal(overlayCore, core)

  for (const source of [dashboard, dashboardApp, simulator, simulatorApp]) {
    assert.match(source, /V2\.5ahpha/)
    assert.doesNotMatch(source, /3\.0\.0a1-/)
  }
})

test('dashboard exposes all required product areas and explicit material actions', async () => {
  const html = await read('frontend/dashboard/index.html')
  const script = await read('frontend/dashboard/app.js')
  const styles = await read('frontend/dashboard/styles.css')
  for (const label of ['总览与换料', '库存', '维护', '烘干', '无限续料', '校准', '诊断与恢复', '卸载当前耗材']) {
    assert.match(html, new RegExp(label))
  }
  assert.match(script, /更换耗材/)
  assert.match(script, /卸载/)
  assert.match(script, /buildViewModel/)
  assert.match(script, /canPerformAction/)
  assert.match(script, /AceApiClient/)
  assert.match(script, /device\.rfidLabel/)
  assert.match(script, /slot\.rfidLabel/)
  assert.match(script, /viewModel\?\.materialTypes/)
  assert.match(script, /slotMaterialOptions\.replaceChildren/)
  assert.match(html, /<input name="material" list="slot-material-options" autocomplete="off">/)
  assert.match(html, /<datalist id="slot-material-options">/)
  assert.doesNotMatch(html, /<select name="material">/)
  assert.doesNotMatch(script, /slot\.rfid\s*\|\|/)
  assert.match(script, /client\.action\(ACE_ACTIONS\.REFRESH/)
  assert.match(script, /device_id:\s*deviceId,\s*slot,\s*length/)
  assert.match(script, /ACE_ACTIONS\.ENABLE_FEED_ASSIST/)
  assert.match(script, /ACE_ACTIONS\.DISABLE_FEED_ASSIST/)
  assert.match(script, /ACE 辅助送料/)
  assert.doesNotMatch(html + script, /缓冲器/)
  assert.match(script, /共享编码器/)
  assert.match(script, /status\.path\.encoders\.shared/)
  assert.match(script, /encoder\.summaryLabel/)
  assert.match(script, /encoder-tone-\$\{escapeHtml\(encoder\.tone\)\}/)
  for (const label of ['上方送料超时', '挤出机标定距离', '编码器最低跟随比例']) assert.match(script, new RegExp(label))
  for (const tone of ['muted', 'monitor', 'protect', 'warning', 'error']) {
    assert.match(styles, new RegExp(`encoder-tone-${tone}`))
  }
  assert.match(script, /data-select-device/)
  assert.match(script, /observeToolchangeNotices/)
  assert.match(script, /collectToolchangeNotices\(notices, app\.noticeCursor, app\.noticeCursorSignature\)/)
  assert.doesNotMatch(html + script, /spool_id|maintenance:\s*data\.get|value="next"/)
})

test('shared core exposes the four stable public APIs', async () => {
  const source = await read('frontend/shared/ace-core.js')
  for (const name of ['normalizeAceState', 'buildViewModel', 'canPerformAction', 'AceApiClient']) {
    assert.match(source, new RegExp(`export (?:const|class) ${name}`))
  }
})

test('standalone dashboard versions module imports for upgrade-safe caching', async () => {
  const [html, app] = await Promise.all([
    read('frontend/dashboard/index.html'),
    read('frontend/dashboard/app.js'),
  ])
  const version = html.match(/app\.js\?v=([^"']+)/)?.[1]
  assert.ok(version)
  assert.match(html, new RegExp(`styles\\.css\\?v=${version.replaceAll('.', '\\.').replaceAll('-', '\\-')}`))
  assert.match(app, new RegExp(`ace-core\\.js\\?v=${version.replaceAll('.', '\\.').replaceAll('-', '\\-')}`))
})

test('standalone dialogs only act on an explicit submit button', async () => {
  const script = await read('frontend/dashboard/app.js')
  assert.match(script, /returnValue = ''/)
  assert.match(script, /event\.submitter\?\.value === 'confirm'/)
  assert.match(script, /event\.submitter\?\.value === 'save'/)
  assert.match(script, /addEventListener\('cancel'/)
  assert.doesNotMatch(script, /addEventListener\('close'[\s\S]*returnValue ===/)
})

test('Fluidd card uses the V2 hierarchy with an explicit multi-device switch', async () => {
  const source = await read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue')
  const slotSource = await read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3SlotCard.vue')
  const positions = [
    source.indexOf('acepro-card__header'),
    source.indexOf('acepro-device-switch'),
    source.indexOf('acepro-card__top-grid'),
    source.indexOf('acepro-panel--slots'),
    source.indexOf('acepro-panel--manual'),
    source.indexOf('acepro-panel--quick'),
    source.indexOf('acepro-more-toggle'),
  ]
  assert.ok(positions.every(position => position >= 0))
  assert.deepEqual([...positions].sort((a, b) => a - b), positions)
  assert.match(source, /layout-path="dashboard\.ace-v3-card"/)
  assert.match(source, /viewModel\.devices\.length > 1/)
  assert.match(source, /acepro-device-switch/)
  assert.match(source, /selectedDeviceId/)
  assert.match(source, /selectDevice\(device\.id\)/)
  assert.match(source, /--ace-device-count/)
  assert.match(source, /narrow:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/)
  assert.match(source, /acepro-card--narrow/)
  assert.match(source, /ref="slotCards"/)
  assert.match(source, /import AceV3SlotCard/)
  assert.match(source, /<ace-v3-slot-card/)
  assert.match(source, /:material-types="viewModel\.materialTypes"/)
  assert.match(source, /设备状态/)
  assert.match(source, /烘干控制/)
  assert.match(source, /料槽管理/)
  assert.match(source, /手动送料/)
  assert.match(source, /快捷操作/)
  assert.match(source, /风扇转速/)
  assert.match(source, /RFID/)
  assert.match(source, /上方传感器/)
  assert.match(source, /下方传感器/)
  assert.match(source, /控制闭环/)
  assert.match(source, /仅监测/)
  assert.match(source, /不参与换料控制/)
  assert.match(source, /ACE 参考送料 -> 上方传感器闭环终止/)
  assert.match(source, /一级五通传感器/)
  assert.match(source, /v-if="viewModel\.usesFirstStageHubs"/)
  assert.match(source, /总五通传感器/)
  assert.match(source, /共享编码器/)
  assert.match(source, /sharedEncoder\.summaryLabel/)
  for (const label of ['上方送料超时', '挤出机标定距离', '编码器最低跟随比例']) assert.match(source, new RegExp(label))
  assert.match(source, /sharedEncoder\.state === 'not_armed'[\s\S]*保护模式尚未启用/)
  assert.match(source, /acepro-encoder-status--monitor/)
  assert.match(source, /acepro-encoder-status--protect/)
  assert.match(source, /acepro-encoder-status--warning/)
  assert.match(source, /acepro-encoder-status--error/)
  assert.match(source, /acepro-info-item--wide/)
  assert.match(source, /ACE -> 总五通 -> 打印头/)
  assert.match(source, /ACE -> 一级五通 -> 总五通 -> 打印头/)
  assert.doesNotMatch(source, /回料传感器/)
  assert.match(source, /acepro-sensor-status--present/)
  assert.match(source, /acepro-sensor-status--empty/)
  assert.match(source, /acepro-sensor-status--unknown/)
  assert.match(source, /acepro-sensor-status--monitor-only/)
  assert.doesNotMatch(source, /已屏蔽/)
  assert.match(source, /\.acepro-sensor-status--empty\s*\{[\s\S]*#fee2e2[\s\S]*rgba\(153, 27, 27, 0\.82\)/)
  assert.match(source, /sensorStatusClass\('upper'\)/)
  assert.match(source, /sensorStatusClass\('lower'\)/)
  assert.match(source, /sensorStatusClass\('hub'\)/)
  assert.match(source, /sensorStatusClass\('rdm'\)/)
  assert.match(source, /this\.selectedDevice\?\.hubSensor/)
  assert.match(source, /this\.status\?\.path\?\.sensors/)
  assert.match(source, /!this\.statusStale && this\.selectedDevice\?\.connected/)
  assert.match(source, /tone === 'ready'/)
  assert.match(source, /tone === 'busy'/)
  assert.doesNotMatch(source, /tone === 'busy' \|\| tone === 'readonly'/)
  assert.match(source, /\.acepro-card__connection--connected\s*\{[\s\S]*#dcfce7[\s\S]*rgba\(21, 128, 61, 0\.82\)/)
  assert.match(source, /\.acepro-card__value--ready\s*\{[\s\S]*#4ade80/)
  assert.match(source, /\.acepro-card__value--error\s*\{[\s\S]*#f87171/)
  assert.match(source, /Vue\.\$socket\.emit\(method, \{ params \}\)/)
  assert.match(source, /statusStale/)
  assert.match(source, /状态已过期/)
  assert.doesNotMatch(source, /pathSensors\[name\]\s*\|\|/)
  assert.match(source, /更换耗材/)
  assert.match(source, /卸载当前耗材/)
  assert.match(source, /保存库存/)
  assert.match(source, /诊断传感器/)
  assert.doesNotMatch(source, /ACE2 当前提供状态读取/)
  assert.match(source, /物理动作已关闭；状态、RFID 和库存仍可使用/)
  assert.match(source, /ACE 辅助送料/)
  assert.doesNotMatch(source, /缓冲器/)
  assert.match(source, /ACE_ACTIONS\.ENABLE_FEED_ASSIST/)
  assert.match(source, /ACE_ACTIONS\.DISABLE_FEED_ASSIST/)
  assert.match(source, /requestEnableFeedAssist/)
  assert.match(source, /requestDisableFeedAssist[\s\S]*runImmediate/)
  assert.match(source, /v-snackbar/)
  assert.match(source, /collectToolchangeNotices\(notices, this\.noticeCursor, this\.noticeCursorSignature\)/)
  assert.match(source, /this\.noticeQueue\.push\(\.\.\.batch\.notices\)/)
  assert.doesNotMatch(source, /this\.noticeQueue\s*=\s*\[\]/)
  assert.match(source, /toolchangeModeClass/)
  assert.match(source, /acepro-toolchange-mode--manual/)
  assert.match(source, /canPerformAction/)
  assert.match(source, /refreshDevice\(selectedDevice\)/)
  assert.match(source, /device_id:\s*this\.selectedDevice\.id/)
  assert.match(slotSource, /acepro-slot-card__spool-svg/)
  assert.match(slotSource, /acepro-slot-card__editor/)
  assert.match(slotSource, /acepro-slot-card__actions/)
  assert.match(slotSource, />SKU</)
  assert.match(slotSource, /\{\{ rfidText \}\}/)
  assert.match(slotSource, /this\.slot\.rfidLabel/)
  assert.match(slotSource, /materialTypes:\s*\{\s*type:\s*Array/)
  assert.match(slotSource, /:items="materialTypes"/)
  assert.doesNotMatch(slotSource, /materialOptions/)
  assert.doesNotMatch(slotSource, /识别失败|未识别/)
  assert.match(slotSource, /开启助推/)
  assert.match(slotSource, /换卷/)
  assert.match(slotSource, /\{\{ slot\.tool \|\| '--' \}\}/)
  assert.match(slotSource, /this\.isDirty && !this\.localValuesMatchSlot/)
  assert.match(slotSource, /getDraft \(\)/)
  assert.doesNotMatch(source, /acepro-live-status/)
  assert.doesNotMatch(slotSource, /诊断槽位|刷新状态/)
  assert.doesNotMatch(source + slotSource, /AceProMixin|executeAceCommand|slotDraft\.spool_id|slotDraft\.maintenance/)
})

test('Fluidd card preserves the real V2 visual fingerprint', async () => {
  const [card, slot] = await Promise.all([
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue'),
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3SlotCard.vue'),
  ])
  assert.match(card, /\.acepro-card__header\s*\{[\s\S]*border-radius:\s*8px[\s\S]*linear-gradient\(145deg/)
  assert.match(card, /\.acepro-panel\s*\{[\s\S]*border-radius:\s*8px[\s\S]*box-shadow:/)
  assert.match(card, /cols="12"[\s\S]*sm="6"[\s\S]*lg="3"/)
  assert.match(card, /repeat\(var\(--ace-device-count\),\s*minmax\(0,\s*1fr\)\)/)
  assert.match(slot, /\.acepro-slot-card\s*\{[\s\S]*background:\s*#1a1f26/)
  assert.match(slot, /\.acepro-slot-card--active\s*\{[\s\S]*#22d3ee/)
  assert.match(slot, /@media \(min-width: 961px\)/)
  assert.match(slot, /@media \(max-width: 600px\)/)
  assert.match(slot, /letter-spacing:\s*0/)
})

test('frontends have no raw control fallback and only declare V3 API endpoints', async () => {
  const files = await Promise.all([
    read('frontend/shared/ace-core.js'),
    read('frontend/dashboard/app.js'),
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue'),
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3SlotCard.vue'),
  ])
  const source = files.join('\n')
  assert.doesNotMatch(source, /printer\/gcode\/script|run_script|TOOL=-1|ACE_CHANGE_TOOL/)
  const endpointMatches = [...source.matchAll(/\/server\/ace\/[a-z_]+/g)].map(match => match[0])
  assert.deepEqual([...new Set(endpointMatches)].sort(), ['/server/ace/action', '/server/ace/status'])
})

test('Fluidd overlay core is byte-for-byte synchronized with the shared core', async () => {
  const [shared, overlay] = await Promise.all([
    read('frontend/shared/ace-core.js'),
    read('frontend/fluidd-overlay/src/components/widgets/ace-v3/ace-core.js'),
  ])
  assert.equal(overlay, shared)
})

test('responsive CSS has stable four-column slots and mobile bounds', async () => {
  const dashboardCss = await read('frontend/dashboard/styles.css')
  const card = await read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue')
  const slot = await read('frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3SlotCard.vue')
  const page = await read('frontend/fluidd-overlay/src/views/AcePro.vue')
  assert.match(dashboardCss, /grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(dashboardCss, /@media \(max-width: 430px\)/)
  assert.match(dashboardCss, /overflow-wrap:\s*anywhere/)
  assert.match(card, /grid-template-columns:\s*repeat\(var\(--ace-device-count\),\s*minmax\(0,\s*1fr\)\)/)
  assert.match(card, /@media \(max-width: 380px\)/)
  assert.match(card, /\.acepro-card\s*\{[\s\S]*box-sizing:\s*border-box[\s\S]*width:\s*100%[\s\S]*max-width:\s*100%[\s\S]*min-width:\s*0/)
  assert.match(card, /@media \(max-width: 960px\)[\s\S]*\.acepro-card__top-grid\s*\{[\s\S]*grid-template-columns:\s*1fr/)
  assert.match(card, /@media \(max-width: 600px\)[\s\S]*\.acepro-info-grid,[\s\S]*grid-template-columns:\s*1fr/)
  assert.match(card, /\.acepro-card--narrow \.acepro-card__top-grid,[\s\S]*grid-template-columns:\s*1fr/)
  assert.match(card, /\.acepro-card--narrow \.acepro-slot-grid__col\s*\{[\s\S]*flex:\s*0 0 100%[\s\S]*max-width:\s*100%/)
  assert.match(slot, /overflow-wrap:\s*anywhere/)
  assert.match(slot, /\.acepro-slot-card\s*\{[\s\S]*width:\s*100%[\s\S]*max-width:\s*100%[\s\S]*min-width:\s*0/)
  assert.match(page, /ace-v3-page/)
  assert.match(page, /\.ace-v3-page\s*\{[\s\S]*box-sizing:\s*border-box[\s\S]*width:\s*100%[\s\S]*max-width:\s*100%[\s\S]*min-width:\s*0/)
  assert.doesNotMatch(page, /padding-left:\s*3rem/)
  assert.match(page, /:collapse-extra-functions="false"/)
})

test('simulator covers one to four hubs, shared encoder states, device switching and notice scenarios', async () => {
  const [html, script, styles] = await Promise.all([
    read('frontend/simulator/index.html'),
    read('frontend/simulator/app.js'),
    read('frontend/simulator/styles.css'),
  ])
  for (const count of [1, 2, 3, 4]) assert.match(html, new RegExp(`<option value="${count}">${count} 台</option>`))
  for (const scenario of ['manual', 'not-ready', 'notice']) assert.match(html, new RegExp(`value="${scenario}"`))
  for (const encoder of ['protect', 'monitor', 'calibrating', 'uncalibrated', 'not-armed', 'fault', 'off', 'unconfigured']) {
    assert.match(html, new RegExp(`value="${encoder}"`))
  }
  for (const label of ['共享编码器', '暂停保护 · 监测中', '只读监测 · 监测中', '关闭 · 校准中', '保护 · 未校准', '保护 · 未启用', '暂停保护 · 故障', '已关闭', '未配置']) {
    assert.match(html + script, new RegExp(label.replace('·', '\\·')))
  }
  assert.match(html, /trigger-toolchange-notice/)
  assert.match(script, /toolchange_notices/)
  assert.match(script, /observeToolchangeNotices/)
  assert.match(script, /emitToolchangeNotice/)
  assert.match(script, /collectToolchangeNotices\(notices, state\.noticeCursor, state\.noticeCursorSignature\)/)
  assert.match(script, /ACE_ACTIONS\.ENABLE_FEED_ASSIST/)
  assert.match(script, /ACE 辅助送料/)
  assert.doesNotMatch(html + script, /缓冲器/)
  assert.match(script, /deviceCount: \[1, 2, 3, 4\]/)
  assert.match(script, /HUB_SENSOR_STATES/)
  assert.match(script, /sensors:\s*\{ upper: false, lower: false, rdm: false, hubs \}/)
  assert.match(script, /encoders:\s*\{ shared: createEncoderStatus\(\) \}/)
  assert.match(script, /renderEncoderStatus\(viewModel\.sharedEncoder\)/)
  assert.match(script, /ACE 参考送料 -&gt; 上方传感器闭环终止/)
  for (const label of ['上方送料超时', '挤出机标定距离', '编码器最低跟随比例']) assert.match(script, new RegExp(label))
  assert.match(script, /仅监测/)
  assert.match(script, /不参与换料控制/)
  assert.doesNotMatch(html + script, /已屏蔽/)
  assert.match(script, /encoderScenario/)
  assert.match(script, /syncEncoderCalibrationCapabilities\(state\.rawStatus\)/)
  assert.match(script, /status\.system\.current_tool !== null[\s\S]*共享路径处于空闲状态/)
  assert.match(script, /const blocker = encoder\.configured[\s\S]*sim-inline-warning/)
  assert.match(script, /document\.addEventListener\('input',[\s\S]*sim-encoder-length[\s\S]*state\.encoderCalibrationLength = event\.target\.value/)
  assert.match(script, /id="sim-encoder-length"[\s\S]*min="0\.01" max="2000"/)
  assert.match(script, /const valid = Number\.isFinite\(length\) && length >= 0\.01 && length <= 2000 && event\.target\.validity\.valid/)
  assert.match(script, /pulses >= ENCODER_CALIBRATION_DEFAULTS\.minimumPulses[\s\S]*至少需要/)
  assert.match(script, /sensor\(device\.hubSensor\)/)
  assert.match(script, /一级五通传感器/)
  assert.match(script, /总五通传感器/)
  assert.match(script, /viewModel\.usesFirstStageHubs/)
  assert.match(script, /ACE -&gt; 总五通 -&gt; 打印头/)
  assert.match(script, /ACE -&gt; 一级五通 -&gt; 总五通 -&gt; 打印头/)
  assert.match(script, /state\.selectedDeviceId = deviceButton\.dataset\.device[\s\S]*render\(\)/)
  assert.match(styles, /\.acepro-feed-assist__controls/)
  assert.match(styles, /\.acepro-toolchange-mode--blocked/)
  assert.match(styles, /\.acepro-encoder-status--monitor/)
  assert.match(styles, /\.acepro-encoder-status--protect/)
  assert.match(styles, /\.acepro-encoder-status--warning/)
  assert.match(styles, /\.acepro-encoder-status--error/)
})

test('frontend documentation rejects the invalid example image', async () => {
  const source = await read('docs/FRONTEND.zh-CN.md')
  assert.match(source, /acepro-fluidd-dashboard-overview\.png/)
  assert.match(source, /acepro-fluidd-card-detail\.png/)
  assert.match(source, /fluidd-acepro-card\.png[^\n]*无效示例图/)
})
