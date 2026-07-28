import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'


test('dashboard folds advanced ACE controls behind more features', async () => {
  const [card, page] = await Promise.all([
    readFile(
      'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
      'utf8'
    ),
    readFile('fluidd-source-overlay/src/views/AcePro.vue', 'utf8'),
  ])

  assert.match(card, /readonly collapseExtraFunctions!:\s*boolean/)
  assert.match(card, /更多功能/)
  assert.match(card, /:aria-expanded="showExtraFunctions \? 'true' : 'false'"/)
  assert.match(
    card,
    /<v-expand-transition>[\s\S]*v-show="showExtraFunctions"[\s\S]*acepro-panel--calibration[\s\S]*acepro-panel--manual[\s\S]*acepro-panel--quick[\s\S]*<\/v-expand-transition>/
  )
  assert.match(page, /:collapse-extra-functions="false"/)
})


test('toolchange status is compact in the ACE Pro title bar', async () => {
  const source = await readFile(
    'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
    'utf8'
  )
  const menu = source.match(/<template #menu>([\s\S]*?)<\/template>/)

  assert.ok(menu)
  assert.match(menu[1], /class="acepro-toolbar-menu"/)
  assert.match(menu[1], /aceProToolchangeRecoveryRequired \|\| aceProToolchangeActive/)
  assert.match(menu[1], /class="acepro-toolbar-toolchange"/)
  assert.match(menu[1], /换料已停止，位置待确认/)
  assert.match(menu[1], /换料中：/)
  assert.match(menu[1], /@click="abortToolchange"/)
  assert.doesNotMatch(source, /class="acepro-card__recovery"/)
})


test('endless spool follows diagnostics without forced right alignment', async () => {
  const source = await readFile(
    'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
    'utf8'
  )
  const diagnostics = source.indexOf('诊断传感器')
  const endlessSwitch = source.indexOf('class="acepro-quick-actions__switch"')
  assert.ok(diagnostics >= 0)
  assert.ok(endlessSwitch > diagnostics)
  const baseRule = source.match(/\.acepro-quick-actions__switch\s*\{([^}]*)\}/s)
  assert.ok(baseRule)
  assert.doesNotMatch(baseRule[1], /margin-left:\s*auto/)
  assert.match(baseRule[1], /flex:\s*0\s+0\s+auto/)
})


test('card exposes automatic drying in status and dryer controls', async () => {
  const source = await readFile(
    'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
    'utf8'
  )
  assert.match(source, /自动烘干/)
  assert.match(source, /自动跟随打印/)
  assert.match(source, /aceProAutoDryingStatusLabel/)
  assert.match(source, /toggleAceProAutoDrying/)
})

test('device status replaces RFID with the downstream five-way sensor', async () => {
  const card = await readFile(
    'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
    'utf8'
  )

  assert.match(card, /五通后传感器/)
  assert.doesNotMatch(card, />RFID</)
})


test('desktop dryer status uses one compact row', async () => {
  const source = await readFile(
    'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
    'utf8'
  )
  const desktop = source.match(/@media \(min-width: 961px\) \{([\s\S]*?)\n\}/)
  assert.ok(desktop)
  assert.match(
    desktop[1],
    /\.acepro-dryer__status\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/s
  )
})


test('endless spool switch removes Vuetify selection-control offset', async () => {
  const source = await readFile(
    'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
    'utf8'
  )
  const switchRule = source.match(
    /\.acepro-quick-actions__switch ::v-deep \.v-input--selection-controls\s*\{([^}]*)\}/s
  )
  assert.ok(switchRule)
  assert.match(switchRule[1], /margin:\s*0/)
  assert.match(switchRule[1], /padding:\s*0/)
})


test('Fluidd card exposes the complete ACE calibration and preload workflow', async () => {
  const [card, mixin] = await Promise.all([
    readFile(
      'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
      'utf8'
    ),
    readFile('fluidd-source-overlay/src/mixins/acePro.ts', 'utf8'),
  ])

  for (const label of [
    '自动探测料管长度',
    '冷态预装载',
    '上方传感器 → 五通传感器',
    'calibrationParkingDistanceLabel',
    'calibrationUpperToParkingSensorResult',
    'calibrationUpperToParkingResult',
    '保存探测结果',
    '取消探测',
    '完全卸载',
    '紧急停止',
  ]) {
    assert.match(card, new RegExp(label))
  }

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
    assert.match(mixin, new RegExp(command))
  }
})


test('Fluidd sends explicit confirmation for every direct filament movement', async () => {
  const mixin = await readFile(
    'fluidd-source-overlay/src/mixins/acePro.ts',
    'utf8'
  )

  assert.doesNotMatch(mixin, /ACE_ACK_TOOLCHANGE/)
  assert.match(mixin, /ACE_FEED[\s\S]*CONFIRM:\s*1/)
  assert.match(mixin, /ACE_RETRACT[\s\S]*CONFIRM:\s*1/)
  assert.match(mixin, /ACE_PRELOAD[\s\S]*CONFIRM:\s*1/)
  assert.match(mixin, /ACE_CALIBRATE_FEED[\s\S]*CONFIRM:\s*1/)
  assert.match(mixin, /ACE_CALIBRATE_RETRACT[\s\S]*CONFIRM:\s*1/)
  assert.match(mixin, /ACE_CALIBRATE[\s\S]*CONFIRM:\s*1/)
  assert.match(mixin, /ACE_FULL_UNLOAD[\s\S]*CONFIRM:\s*1/)

  const unload = mixin.match(/async unloadCurrentSlot \(\) \{([\s\S]*?)\n  \}/)
  assert.ok(unload)
  assert.match(unload[1], /this\.\$confirm/)
})
