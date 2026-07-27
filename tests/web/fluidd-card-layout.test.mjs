import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'


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
