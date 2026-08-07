import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ACE_SLOTS_PER_DEVICE,
  getAceDeviceCount,
  getAceToolCommandGroups,
} from '../../frontend/fluidd-overlay/src/components/widgets/toolhead/ace-tool-commands.js'

const commands = Array.from({ length: 17 }, (_, index) => ({ name: `T${index}` }))

test('ACE device count is read only from a valid Klipper ace status object', () => {
  for (const deviceCount of [1, 2, 3, 4]) {
    assert.equal(getAceDeviceCount({ ace: { device_count: deviceCount } }), deviceCount)
  }

  for (const state of [
    undefined,
    null,
    {},
    { ace: null },
    { ace: {} },
    { ace: { device_count: '1' } },
    { ace: { device_count: 0 } },
    { ace: { device_count: 5 } },
  ]) {
    assert.equal(getAceDeviceCount(state), null)
  }
})

test('one to four ACE devices produce one aligned four-tool row per device', () => {
  for (const deviceCount of [1, 2, 3, 4]) {
    const groups = getAceToolCommandGroups(commands, deviceCount)
    assert.ok(groups)
    assert.equal(groups.length, deviceCount)
    assert.deepEqual(
      groups.map(group => group.map(command => command.name)),
      Array.from({ length: deviceCount }, (_, deviceIndex) =>
        Array.from(
          { length: ACE_SLOTS_PER_DEVICE },
          (_, slot) => `T${deviceIndex * ACE_SLOTS_PER_DEVICE + slot}`
        )
      )
    )
  }
})

test('ACE grouping excludes excess tools and keeps device row boundaries', () => {
  const groups = getAceToolCommandGroups(
    [{ name: 'T0' }, { name: 'T4' }, { name: 'T7' }, { name: 'T8' }, { name: 'invalid' }],
    2
  )
  assert.deepEqual(groups, [
    [{ name: 'T0' }],
    [{ name: 'T4' }, { name: 'T7' }],
  ])
})

test('missing or invalid ACE state delegates to Fluidd original grouping', () => {
  for (const deviceCount of [null, 0, 5, Number.NaN]) {
    assert.equal(getAceToolCommandGroups(commands, deviceCount), null)
  }
})
