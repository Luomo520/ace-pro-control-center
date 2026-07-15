import Component from 'vue-class-component'
import StateMixin from '@/mixins/state'
import { getAceStatus, runAceCommand } from '@/api/acePro'
import type { AceProResolvedSlot, AceProResolvedState } from '@/types/acePro'
import {
  buildAceSetSlotGcode,
  detectAceProObjectKey,
  hasAceProConfig,
  hexToRgb,
  resolveAceProApiState,
  resolveAceProState,
  rgbToCss,
  rgbToHex,
} from '@/util/acepro'

const WAIT_REFRESH = 'acepro-refresh'
const WAIT_SLOT_ACTION = 'acepro-slot-action'
const WAIT_DRYER_ACTION = 'acepro-dryer-action'
const WAIT_QUICK_ACTION = 'acepro-quick-action'

@Component
export default class AceProMixin extends StateMixin {
  aceProApiStatus: Record<string, any> | null = null
  aceProApiAvailable: boolean | null = null
  aceProApiWaits: string[] = []
  aceProPollTimer: ReturnType<typeof setInterval> | null = null
  aceProLastError = ''

  created () {
    this.pollAceProApi()
    this.aceProPollTimer = setInterval(() => this.pollAceProApi(), 5000)
  }

  beforeDestroy () {
    if (this.aceProPollTimer != null) {
      clearInterval(this.aceProPollTimer)
    }
  }

  get aceProPrinterState (): Record<string, any> {
    return this.$typedState.printer.printer as Record<string, any>
  }

  get aceProState (): AceProResolvedState {
    const fallback = resolveAceProState(this.aceProPrinterState)
    return this.aceProApiStatus != null
      ? resolveAceProApiState(this.aceProApiStatus, fallback)
      : fallback
  }

  get aceProDetected (): boolean {
    return this.aceProState.detected
  }

  get aceProConnected (): boolean {
    return this.aceProState.connected
  }

  get aceProObjectKey (): string | undefined {
    return detectAceProObjectKey(this.aceProPrinterState)
  }

  get aceProSupportsUi (): boolean {
    return this.aceProApiAvailable === true || this.aceProDetected || hasAceProConfig(this.aceProPrinterState)
  }

  get aceProStatus (): string {
    return this.aceProState.status
  }

  get aceProSlots (): AceProResolvedSlot[] {
    return this.aceProState.slots
  }

  get aceProCurrentIndex (): number {
    return this.aceProState.currentIndex
  }

  get aceProBusy (): boolean {
    return this.aceProHasWait([WAIT_REFRESH, WAIT_SLOT_ACTION, WAIT_DRYER_ACTION, WAIT_QUICK_ACTION]) ||
      this.aceProState.endlessSpool.inProgress ||
      this.aceProStatus === 'busy'
  }

  get aceProPrinting (): boolean {
    return this.aceProState.printing
  }

  get aceProDryerActive (): boolean {
    return this.aceProState.dryer.status !== 'stop'
  }

  get aceProDryerLabel (): string {
    const dryer = this.aceProState.dryer
    if (dryer.status === 'stop') return '烘干待机'
    const remainTime = dryer.remain_time > 0
      ? `，剩余 ${dryer.remain_time} 分钟`
      : ''
    return `${dryer.target_temp}C，${dryer.status}${remainTime}`
  }

  get aceProWaitRefresh (): string {
    return WAIT_REFRESH
  }

  get aceProWaitSlotAction (): string {
    return WAIT_SLOT_ACTION
  }

  get aceProWaitDryerAction (): string {
    return WAIT_DRYER_ACTION
  }

  get aceProWaitQuickAction (): string {
    return WAIT_QUICK_ACTION
  }

  aceColorCss (color: [number, number, number]): string {
    return rgbToCss(color)
  }

  aceColorHex (color: [number, number, number]): string {
    return rgbToHex(color)
  }

  aceHexColorToRgb (value: string): [number, number, number] {
    return hexToRgb(value)
  }

  aceProHasWait (wait: string | string[]): boolean {
    const waits = Array.isArray(wait) ? wait : [wait]
    return this.hasWait(waits) || waits.some(item => this.aceProApiWaits.includes(item))
  }

  async pollAceProApi () {
    try {
      this.aceProApiStatus = await getAceStatus()
      this.aceProApiAvailable = true
    } catch {
      this.aceProApiAvailable = false
      this.aceProApiStatus = null
    }
  }

  private async executeAceCommand (
    command: string,
    params: Record<string, string | number | boolean | number[]>,
    wait: string,
    fallbackGcode: string
  ): Promise<boolean> {
    if (this.aceProApiAvailable !== false) {
      this.aceProApiWaits = [...this.aceProApiWaits, wait]
      try {
        await runAceCommand({ command, params })
        this.aceProApiAvailable = true
        this.aceProLastError = ''
        await this.pollAceProApi()
        return true
      } catch (error: any) {
        if (error?.response?.status !== 404) {
          console.error(`ACE Pro command failed: ${command}`, error)
          this.aceProLastError = error?.message || `${command} 执行失败`
          return false
        }
        this.aceProApiAvailable = false
        this.aceProApiStatus = null
      } finally {
        this.aceProApiWaits = this.aceProApiWaits.filter(item => item !== wait)
      }
    }

    this.sendGcode(fallbackGcode, wait)
    this.aceProLastError = ''
    return true
  }

  async refreshAcePro () {
    await this.pollAceProApi()
    if (this.aceProApiAvailable === false) {
      this.sendGcode('ACE_QUERY_SLOTS\nACE_ENDLESS_SPOOL_STATUS\nACE_GET_CURRENT_INDEX', WAIT_REFRESH)
    }
  }

  async handleSlotPrimaryAction (slot: AceProResolvedSlot) {
    if (slot.isActive) {
      const result = await this.$confirm(
        `要卸载 ${slot.index + 1} 号料槽中的耗材吗？`,
        { title: 'ACE Pro', color: 'card-heading', icon: '$warning' }
      )

      if (result) {
        await this.executeAceCommand('ACE_CHANGE_TOOL', { TOOL: -1 }, WAIT_SLOT_ACTION, 'ACE_CHANGE_TOOL TOOL=-1')
      }
      return
    }

    if (!slot.ready) return

    const result = await this.$confirm(
      `要装载 ${slot.index + 1} 号料槽中的耗材吗？`,
      { title: 'ACE Pro', color: 'card-heading', icon: '$warning' }
    )

    if (result) {
      await this.executeAceCommand('ACE_CHANGE_TOOL', { TOOL: slot.index }, WAIT_SLOT_ACTION, `ACE_CHANGE_TOOL TOOL=${slot.index}`)
    }
  }

  async saveSlot (index: number, material: string, colorHex: string, temperature: number) {
    const color = this.aceHexColorToRgb(colorHex)
    const gcode = buildAceSetSlotGcode(index, material, color, temperature)
    await this.executeAceCommand('ACE_SET_SLOT', {
      INDEX: index,
      MATERIAL: material.trim().toUpperCase(),
      COLOR: color,
      TEMP: Math.round(temperature),
    }, WAIT_SLOT_ACTION, gcode)
  }

  async clearSlot (index: number) {
    await this.executeAceCommand('ACE_SET_SLOT', { INDEX: index, EMPTY: 1 }, WAIT_SLOT_ACTION, `ACE_SET_SLOT INDEX=${index} EMPTY=1`)
  }

  async unloadCurrentSlot () {
    await this.executeAceCommand('ACE_CHANGE_TOOL', { TOOL: -1 }, WAIT_QUICK_ACTION, 'ACE_CHANGE_TOOL TOOL=-1')
  }

  async saveInventory () {
    await this.executeAceCommand('ACE_SAVE_INVENTORY', {}, WAIT_QUICK_ACTION, 'ACE_SAVE_INVENTORY')
  }

  async toggleEndlessSpool (enabled: boolean) {
    const command = enabled ? 'ACE_ENABLE_ENDLESS_SPOOL' : 'ACE_DISABLE_ENDLESS_SPOOL'
    await this.executeAceCommand(command, {}, WAIT_SLOT_ACTION, command)
  }

  async startDrying (temperature: number, duration: number) {
    const temp = Math.round(temperature)
    const minutes = Math.round(duration)
    await this.executeAceCommand('ACE_START_DRYING', { TEMP: temp, DURATION: minutes }, WAIT_DRYER_ACTION, `ACE_START_DRYING TEMP=${temp} DURATION=${minutes}`)
  }

  async stopDrying () {
    await this.executeAceCommand('ACE_STOP_DRYING', {}, WAIT_DRYER_ACTION, 'ACE_STOP_DRYING')
  }

  async toggleFeedAssist (index: number, enabled: boolean) {
    const command = enabled ? 'ACE_ENABLE_FEED_ASSIST' : 'ACE_DISABLE_FEED_ASSIST'
    await this.executeAceCommand(command, { INDEX: index }, WAIT_SLOT_ACTION, `${command} INDEX=${index}`)
  }

  async changeSpool (index: number) {
    const result = await this.$confirm(
      `要回抽并释放 ${index + 1} 号料槽吗？`,
      { title: 'ACE Pro 换卷', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand('ACE_CHANGE_SPOOL', { INDEX: index }, WAIT_SLOT_ACTION, `ACE_CHANGE_SPOOL INDEX=${index}`)
  }

  async manualFeed (index: number, length: number, speed: number) {
    const params = { INDEX: Math.round(index), LENGTH: Math.round(length), SPEED: Math.round(speed) }
    await this.executeAceCommand(
      'ACE_FEED',
      params,
      WAIT_QUICK_ACTION,
      `ACE_FEED INDEX=${params.INDEX} LENGTH=${params.LENGTH} SPEED=${params.SPEED}`
    )
  }

  async manualRetract (index: number, length: number, speed: number) {
    const params = { INDEX: Math.round(index), LENGTH: Math.round(length), SPEED: Math.round(speed) }
    await this.executeAceCommand(
      'ACE_RETRACT',
      params,
      WAIT_QUICK_ACTION,
      `ACE_RETRACT INDEX=${params.INDEX} LENGTH=${params.LENGTH} SPEED=${params.SPEED}`
    )
  }

  async testRunoutSensors () {
    await this.executeAceCommand(
      'ACE_TEST_RUNOUT_SENSOR',
      {},
      WAIT_QUICK_ACTION,
      'ACE_TEST_RUNOUT_SENSOR'
    )
    await this.pollAceProApi()
  }
}
