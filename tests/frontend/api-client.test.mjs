import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ACE_ACTIONS,
  ACE_ENDPOINTS,
  AceApiClient,
  AceContractError,
} from '../../frontend/shared/ace-core.js'
import { jsonResponse, makeStatus } from './fixtures.mjs'

test('client only reads status and posts structured actions', async () => {
  const calls = []
  const client = new AceApiClient({
    client: 'test-client',
    fetchImpl: async (url, options) => {
      calls.push({ url, options })
      if (options.method === 'GET') return jsonResponse({ result: makeStatus(2) })
      return jsonResponse({ ok: true, result: { accepted: true, transaction_id: 'tx-1' } })
    },
  })
  const status = await client.getStatus()
  assert.equal(status.devices.length, 2)
  await client.action(ACE_ACTIONS.SELECT_TOOL, { tool: 'T5' }, { confirm: true, deviceCount: 2 })

  assert.equal(calls[0].url, ACE_ENDPOINTS.status)
  assert.equal(calls[0].options.method, 'GET')
  assert.equal(calls[1].url, ACE_ENDPOINTS.action)
  assert.equal(calls[1].options.method, 'POST')
  const body = JSON.parse(calls[1].options.body)
  assert.deepEqual(body, {
    action: 'select_tool', params: { tool: 'T5' }, confirm: true, client: 'test-client',
  })
  assert.equal('gcode' in body, false)
  assert.equal('command' in body, false)
})

test('client rejects raw command fields and unknown actions', async () => {
  const client = new AceApiClient({ fetchImpl: async () => jsonResponse({ ok: true, result: {} }) })
  await assert.rejects(() => client.action('run_script', {}, { confirm: true }), AceContractError)
  await assert.rejects(() => client.action(ACE_ACTIONS.FEED, { gcode: 'forbidden' }, { confirm: true }), /禁止发送字段/)
  await assert.rejects(() => client.action(ACE_ACTIONS.SELECT_TOOL, { tool: 'T16' }, { confirm: true }), /T0\.\.T15/)
})

test('client accepts structured feed-assist actions', async () => {
  const requests = []
  const client = new AceApiClient({
    client: 'feed-assist-test',
    fetchImpl: async (_url, options) => {
      requests.push(JSON.parse(options.body))
      return jsonResponse({ ok: true, result: { accepted: true } })
    },
  })

  await client.action(ACE_ACTIONS.ENABLE_FEED_ASSIST, { device_id: 'ace1', slot: 2 }, { confirm: true, deviceCount: 2 })
  await client.action(ACE_ACTIONS.DISABLE_FEED_ASSIST, { device_id: 'ace1', slot: 2 }, { confirm: false, deviceCount: 2 })

  assert.deepEqual(requests.map(request => request.action), ['enable_feed_assist', 'disable_feed_assist'])
  assert.deepEqual(requests.map(request => request.confirm), [true, false])
  assert.ok(requests.every(request => request.params.device_id === 'ace1' && request.params.slot === 2))
})

test('identical in-flight actions are deduplicated and are not retried', async () => {
  let resolveRequest
  let calls = 0
  const client = new AceApiClient({
    fetchImpl: async () => {
      calls += 1
      await new Promise(resolve => { resolveRequest = resolve })
      return jsonResponse({ ok: true, result: { accepted: true } })
    },
  })
  const first = client.action(ACE_ACTIONS.UNLOAD, {}, { confirm: true })
  const second = client.action(ACE_ACTIONS.UNLOAD, {}, { confirm: true })
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(calls, 1)
  resolveRequest()
  assert.deepEqual(await first, { accepted: true })
  assert.deepEqual(await second, { accepted: true })
})

test('failed action does not fall back to another endpoint', async () => {
  const calls = []
  const client = new AceApiClient({
    fetchImpl: async url => {
      calls.push(url)
      return jsonResponse({ error: { code: 'ACE_BUSY', message: '路径忙', next_action: '等待' } }, 409)
    },
  })
  await assert.rejects(() => client.action(ACE_ACTIONS.UNLOAD, {}, { confirm: true }), /路径忙/)
  assert.deepEqual(calls, [ACE_ENDPOINTS.action])
})

test('Fluidd client can use the active Moonraker websocket RPC', async () => {
  const calls = []
  const client = new AceApiClient({
    client: 'fluidd-card',
    rpcImpl: async (method, params) => {
      calls.push({ method, params })
      if (method === 'server.ace.status') return { result: makeStatus(1) }
      return { ok: true, result: { accepted: true } }
    },
  })

  const status = await client.getStatus()
  const action = await client.action(ACE_ACTIONS.SET_ENDLESS_SPOOL, { enabled: true })

  assert.equal(status.devices.length, 1)
  assert.deepEqual(action, { accepted: true })
  assert.deepEqual(calls.map(call => call.method), ['server.ace.status', 'server.ace.action'])
  assert.deepEqual(calls[1].params, {
    action: 'set_endless_spool',
    params: { enabled: true },
    confirm: false,
    client: 'fluidd-card',
  })
})

test('client times out a stalled RPC instead of retaining actionable stale state', async () => {
  const client = new AceApiClient({
    timeoutMs: 5,
    rpcImpl: () => new Promise(() => {}),
  })

  await assert.rejects(() => client.getStatus(), /请求超时/)
})
