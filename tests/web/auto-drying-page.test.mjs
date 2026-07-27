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
  assert.match(source, /未知材料，将以 45°C/)
})
