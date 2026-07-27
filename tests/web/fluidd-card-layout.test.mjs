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
