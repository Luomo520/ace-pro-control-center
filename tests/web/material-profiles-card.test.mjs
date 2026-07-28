import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'


test('Fluidd slot cards use driver material profiles for both temperatures', async () => {
  const [card, slotCard, types] = await Promise.all([
    readFile(
      'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
      'utf8'
    ),
    readFile(
      'fluidd-source-overlay/src/components/widgets/acepro/AceProSlotCard.vue',
      'utf8'
    ),
    readFile('fluidd-source-overlay/src/types/acePro.ts', 'utf8'),
  ])

  assert.match(card, /activeSlot\.dryingTemperature/)
  assert.doesNotMatch(card, /normalized\.startsWith\('ABS'\)/)
  assert.match(slotCard, /耗材温度/)
  assert.match(slotCard, /烘干温度/)
  assert.match(slotCard, /slot\.dryingTemperature/)
  assert.match(types, /dryingTemperature:\s*number/)
  assert.match(types, /materialProfiles:/)
})


test('standalone dashboard uses the same driver material profiles', async () => {
  const [dashboard, page] = await Promise.all([
    readFile('ace_status_integration/web/ace-dashboard.js', 'utf8'),
    readFile('ace_status_integration/web/ace.html', 'utf8'),
  ])

  assert.match(dashboard, /data\.material_profiles/)
  assert.match(dashboard, /profile\.drying_temperature/)
  assert.doesNotMatch(dashboard, /normalized\.startsWith\('ABS'\)/)
  assert.match(page, /耗材温度/)
  assert.match(page, /烘干温度/)
  assert.match(page, /slot\.drying_temperature/)
})
