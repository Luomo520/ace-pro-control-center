import { describe, expect, it } from 'vitest'
import {
  autoDryingBasisLabel,
  autoDryingStatusLabel,
  autoDryingWarningMessage,
  buildAceSetSlotGcode,
  resolveAceProApiState,
  shouldShowAceNotice,
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

  it('normalizes automatic drying without recalculating temperature', () => {
    const state = resolveAceProApiState({
      api_version: 1,
      driver: 'ACEPROSV08',
      auto_drying: {
        enabled: true,
        active: true,
        owned_by_auto: true,
        suppressed_for_job: false,
        temperature: 50,
        reason: 'PLA_MIXED',
        print_state: 'printing',
        last_error: '',
        notice_id: 9,
        notice_message: '混装提示',
      },
    })

    expect(state.autoDrying.temperature).toBe(50)
    expect(state.autoDrying.reason).toBe('PLA_MIXED')
    expect(autoDryingStatusLabel(state.autoDrying)).toBe('运行中 50°C')
    expect(autoDryingBasisLabel(state.autoDrying)).toBe('50°C · PLA 混装')
  })

  it('marks absent legacy automatic drying state as unavailable', () => {
    const state = resolveAceProApiState({
      api_version: 1,
      driver: 'ACEPROSV08',
    })

    expect(state.autoDrying.available).toBe(false)
    expect(autoDryingStatusLabel(state.autoDrying)).toBe('状态不可用')
  })

  it('uses the approved safety warnings', () => {
    expect(autoDryingWarningMessage('PLA_MIXED')).toBe(
      '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；其他高温材料的烘干效果可能受限。'
    )
    expect(autoDryingWarningMessage('UNKNOWN')).toBe(
      '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。'
    )
  })

  it('shows each increasing backend notice once', () => {
    expect(shouldShowAceNotice(0, 0)).toBe(false)
    expect(shouldShowAceNotice(4, 4)).toBe(false)
    expect(shouldShowAceNotice(5, 4)).toBe(true)
    expect(shouldShowAceNotice(1, 5)).toBe(false)
  })
})
