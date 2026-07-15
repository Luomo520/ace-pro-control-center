import { describe, expect, it } from 'vitest'
import {
  buildAceSetSlotGcode,
  resolveAceProApiState,
} from './acepro'

describe('ACEPROSV08 Fluidd adapter', () => {
  it('normalizes the single-device API including sensors and feed assist', () => {
    const state = resolveAceProApiState({
      api_version: 1,
      driver: 'ACEPROSV08',
      connected: true,
      status: 'ready',
      current_tool: 2,
      feed_assist_index: 2,
      printing: false,
      sensors: {
        upper: { name: 'extruder_sensor', available: true, detected: true },
        lower: { name: 'toolhead_sensor', available: true, detected: false },
      },
      slots: [
        { status: 'ready', material: 'PLA', color: { rgb: [12, 34, 56] }, temperature: 210 },
      ],
    })

    expect(state.connected).toBe(true)
    expect(state.currentIndex).toBe(2)
    expect(state.feedAssistIndex).toBe(2)
    expect(state.sensors.upper.detected).toBe(true)
    expect(state.sensors.lower.detected).toBe(false)
    expect(state.slots[0].color).toEqual([12, 34, 56])
  })

  it('builds inventory G-code with INDEX and never the Kobra-S1 T parameter', () => {
    const gcode = buildAceSetSlotGcode(1, 'petg', [1, 2, 3], 240)

    expect(gcode).toBe('ACE_SET_SLOT INDEX=1 MATERIAL=PETG COLOR=1,2,3 TEMP=240')
    expect(gcode).not.toContain(' T=')
  })
})
