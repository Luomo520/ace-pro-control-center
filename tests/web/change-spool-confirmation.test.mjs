import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { runInNewContext } from 'node:vm'

const fluiddSource = await readFile(
  'fluidd-source-overlay/src/mixins/acePro.ts',
  'utf8'
)
const dashboardSource = await readFile(
  'ace_status_integration/web/ace-dashboard.js',
  'utf8'
)

function loadFluiddChangeSpool () {
  const start = fluiddSource.indexOf('  async changeSpool (')
  const end = fluiddSource.indexOf('\n  async manualFeed (', start)

  assert.notEqual(start, -1, 'missing Fluidd changeSpool')
  assert.notEqual(end, -1, 'missing Fluidd manualFeed')

  const method = fluiddSource
    .slice(start, end)
    .trim()
    .replace(/^async /, 'async function ')
  const javascript = stripTypeScriptTypes(method, { mode: 'transform' })

  return runInNewContext(
    `${javascript}\nchangeSpool`,
    { WAIT_SLOT_ACTION: 'ace-slot-action' }
  )
}

function loadDashboardChangeSpool (confirm) {
  const start = dashboardSource.indexOf('        async changeSpool(')
  const end = dashboardSource.indexOf('\n        async toggleEndlessSpool(', start)

  assert.notEqual(start, -1, 'missing dashboard changeSpool')
  assert.notEqual(end, -1, 'missing dashboard toggleEndlessSpool')

  const method = dashboardSource
    .slice(start, end)
    .trim()
    .replace(/,$/, '')
    .replace(/^async /, 'async function ')

  return runInNewContext(
    `${method}\nchangeSpool`,
    { window: { confirm } }
  )
}

test('Fluidd sends one-time confirmation only after the user accepts', async () => {
  const changeSpool = loadFluiddChangeSpool()
  const commandCalls = []
  let confirmResult = true
  let confirmCount = 0
  const instance = {
    $confirm: async () => {
      confirmCount += 1
      return confirmResult
    },
    executeAceCommand: async (...args) => { commandCalls.push(args) },
  }

  await changeSpool.call(instance, 2)

  assert.equal(confirmCount, 1)
  assert.equal(commandCalls.length, 1)
  assert.equal(commandCalls[0][0], 'ACE_CHANGE_SPOOL')
  assert.deepEqual(Object.keys(commandCalls[0][1]).sort(), ['CONFIRM', 'INDEX'])
  assert.equal(commandCalls[0][1].INDEX, 2)
  assert.equal(commandCalls[0][1].CONFIRM, 1)
  assert.equal(commandCalls[0][2], 'ace-slot-action')

  confirmResult = false
  await changeSpool.call(instance, 1)

  assert.equal(confirmCount, 2)
  assert.equal(commandCalls.length, 1)
})

test('standalone dashboard sends one-time confirmation only after the user accepts', async () => {
  let confirmResult = true
  let confirmCount = 0
  const changeSpool = loadDashboardChangeSpool(() => {
    confirmCount += 1
    return confirmResult
  })
  const commandCalls = []
  const instance = {
    executeCommand: async (...args) => { commandCalls.push(args) },
  }

  await changeSpool.call(instance, 3)

  assert.equal(confirmCount, 1)
  assert.equal(commandCalls.length, 1)
  assert.equal(commandCalls[0][0], 'ACE_CHANGE_SPOOL')
  assert.deepEqual(Object.keys(commandCalls[0][1]).sort(), ['CONFIRM', 'INDEX'])
  assert.equal(commandCalls[0][1].INDEX, 3)
  assert.equal(commandCalls[0][1].CONFIRM, 1)

  confirmResult = false
  await changeSpool.call(instance, 0)

  assert.equal(confirmCount, 2)
  assert.equal(commandCalls.length, 1)
})
