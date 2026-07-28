import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { runInNewContext } from 'node:vm'

const source = await readFile(
  'fluidd-source-overlay/src/mixins/acePro.ts',
  'utf8'
)

function loadAsyncMethod (name, nextName, dependencies = {}) {
  const startMarker = `  private async ${name} (`
  const publicStartMarker = `  async ${name} (`
  const start = source.indexOf(startMarker) >= 0
    ? source.indexOf(startMarker)
    : source.indexOf(publicStartMarker)
  const end = source.indexOf(`\n  async ${nextName} (`, start)

  assert.notEqual(start, -1, `missing ${name}`)
  assert.notEqual(end, -1, `missing ${nextName}`)

  const method = source
    .slice(start, end)
    .trim()
    .replace(/^(?:private )?async /, 'async function ')
  const javascript = stripTypeScriptTypes(method, { mode: 'transform' })

  return runInNewContext(`${javascript}\n${name}`, dependencies)
}

function createHarness (apiAvailable = true) {
  const sendGcodeCalls = []
  let pollCount = 0

  return {
    instance: {
      aceProApiAvailable: apiAvailable,
      aceProApiStatus: { connected: true },
      aceProApiWaits: [],
      aceProLastError: '旧错误',
      sendGcode: (...args) => sendGcodeCalls.push(args),
      pollAceProApi: async () => { pollCount += 1 },
    },
    sendGcodeCalls,
    get pollCount () { return pollCount },
  }
}

function httpError (status, data = undefined) {
  const error = new Error(`Request failed with status code ${status}`)
  error.response = { status, data }
  return error
}

test('ACE commands succeed only through the Moonraker command API', async () => {
  const requests = []
  const executeAceCommand = loadAsyncMethod(
    'executeAceCommand',
    'refreshAcePro',
    {
      runAceCommand: async payload => { requests.push(payload) },
      ACE_API_UNAVAILABLE_ERROR: 'API unavailable',
    }
  )
  const harness = createHarness(null)

  const result = await executeAceCommand.call(
    harness.instance,
    'ACE_STOP_DRYING',
    {},
    'ace-wait'
  )

  assert.equal(result, true)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].command, 'ACE_STOP_DRYING')
  assert.equal(Object.keys(requests[0].params).length, 0)
  assert.equal(harness.instance.aceProApiAvailable, true)
  assert.equal(harness.instance.aceProLastError, '')
  assert.equal(harness.instance.aceProApiWaits.length, 0)
  assert.equal(harness.pollCount, 1)
  assert.deepEqual(harness.sendGcodeCalls, [])
})

for (const scenario of [
  {
    name: '404',
    error: httpError(404, { error: { message: 'Not Found' } }),
    expectedError: /控制 API 不可用/,
    apiAvailable: false,
  },
  {
    name: 'network error',
    error: new Error('Network Error'),
    expectedError: /无法连接 ACE Pro 控制 API：Network Error/,
    apiAvailable: true,
  },
  {
    name: 'driver command error',
    error: Object.assign(new Error('达到最大距离后上方传感器未触发'), {
      isAceCommandError: true,
    }),
    expectedError: /^达到最大距离后上方传感器未触发$/,
    apiAvailable: true,
  },
  {
    name: '409',
    error: httpError(409, { error: { message: '打印中不允许执行该操作' } }),
    expectedError: /打印中不允许执行该操作/,
    apiAvailable: true,
  },
  {
    name: '5xx',
    error: httpError(503),
    expectedError: /HTTP 503/,
    apiAvailable: true,
  },
]) {
  test(`ACE commands fail closed on ${scenario.name}`, async () => {
    const executeAceCommand = loadAsyncMethod(
      'executeAceCommand',
      'refreshAcePro',
      {
        runAceCommand: async () => { throw scenario.error },
        ACE_API_UNAVAILABLE_ERROR: 'ACE Pro 控制 API 不可用，请安装或更新 Moonraker [ace_status] 组件。',
      }
    )
    const harness = createHarness(true)
    const originalConsoleError = console.error
    console.error = () => {}

    try {
      const result = await executeAceCommand.call(
        harness.instance,
        'ACE_FEED',
        { INDEX: 0, LENGTH: 20, SPEED: 10, CONFIRM: 1 },
        'ace-wait'
      )

      assert.equal(result, false)
      assert.equal(harness.instance.aceProApiAvailable, scenario.apiAvailable)
      assert.match(harness.instance.aceProLastError, scenario.expectedError)
      assert.equal(harness.instance.aceProApiWaits.length, 0)
      assert.equal(harness.pollCount, 0)
      assert.deepEqual(harness.sendGcodeCalls, [])
    } finally {
      console.error = originalConsoleError
    }
  })
}

test('known unavailable API blocks commands without any fallback', async () => {
  let requestCount = 0
  const executeAceCommand = loadAsyncMethod(
    'executeAceCommand',
    'refreshAcePro',
    {
      runAceCommand: async () => { requestCount += 1 },
      ACE_API_UNAVAILABLE_ERROR: 'ACE Pro 控制 API 不可用，请安装或更新 Moonraker [ace_status] 组件。',
    }
  )
  const harness = createHarness(false)

  const result = await executeAceCommand.call(
    harness.instance,
    'ACE_CHANGE_TOOL',
    { TOOL: 0 },
    'ace-wait'
  )

  assert.equal(result, false)
  assert.equal(requestCount, 0)
  assert.match(harness.instance.aceProLastError, /控制 API 不可用/)
  assert.equal(harness.instance.aceProApiWaits.length, 0)
  assert.deepEqual(harness.sendGcodeCalls, [])
})

test('manual refresh never sends raw ACE G-code', async () => {
  const refreshAcePro = loadAsyncMethod('refreshAcePro', 'handleSlotPrimaryAction')
  const harness = createHarness(false)

  await refreshAcePro.call(harness.instance)

  assert.equal(harness.pollCount, 1)
  assert.deepEqual(harness.sendGcodeCalls, [])
})
