import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'


test('standalone page exposes automatic drying status and switch', async () => {
  const html = await readFile('ace_status_integration/web/ace.html', 'utf8')
  assert.match(html, /自动烘干/)
  assert.match(html, /自动跟随打印/)
  assert.match(html, /toggleAutoDrying/)
  assert.match(html, /autoDryingStatusText/)
  assert.match(html, /autoDryingBasisText/)
})


test('standalone client sends only strict switch commands', async () => {
  const source = await readFile(
    'ace_status_integration/web/ace-dashboard.js',
    'utf8'
  )
  assert.match(source, /ACE_ENABLE_AUTO_DRYING/)
  assert.match(source, /ACE_DISABLE_AUTO_DRYING/)
  assert.doesNotMatch(source, /ACE_ENABLE_AUTO_DRYING TEMP=/)
  assert.match(source, /PLA 与其他材料混装/)
  assert.match(source, /未知材料，将以 \$\{temperatureText\}/)
})


test('Fluidd keeps transient ACE API startup failures in a loading state', async () => {
  const mixin = await readFile(
    'fluidd-source-overlay/src/mixins/acePro.ts',
    'utf8'
  )
  const card = await readFile(
    'fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue',
    'utf8'
  )

  assert.match(mixin, /error\?\.response\?\.status === 404/)
  assert.match(mixin, /get aceProApiLoading \(\): boolean/)
  assert.match(card, /v-if="aceProApiLoading"/)
  assert.match(card, /正在读取 ACE Pro 状态/)
})
