import Component from 'vue-class-component'
import StateMixin from '@/mixins/state'
import { getAceStatus, runAceCommand } from '@/api/acePro'
import type { AceProResolvedSlot, AceProResolvedState } from '@/types/acePro'
import {
  autoDryingBasisLabel,
  autoDryingStatusLabel,
  autoDryingWarningMessage,
  detectAceProObjectKey,
  hasAceProConfig,
  hexToRgb,
  resolveAceProApiState,
  resolveAceProState,
  rgbToCss,
  rgbToHex,
  shouldResetAceNoticeSequence,
  shouldShowAceNotice,
} from '@/util/acepro'

const WAIT_REFRESH = 'acepro-refresh'
const WAIT_SLOT_ACTION = 'acepro-slot-action'
const WAIT_DRYER_ACTION = 'acepro-dryer-action'
const WAIT_QUICK_ACTION = 'acepro-quick-action'
const ACE_API_UNAVAILABLE_ERROR = 'ACE Pro 控制 API 不可用，请安装或更新 Moonraker [ace_status] 组件。'

@Component
export default class AceProMixin extends StateMixin {
  aceProApiStatus: Record<string, any> | null = null
  aceProApiAvailable: boolean | null = null
  aceProApiWaits: string[] = []
  aceProPollTimer: ReturnType<typeof setInterval> | null = null
  aceProLastError = ''
  aceProLastNoticeId: number | null = null

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

  get aceProApiLoading (): boolean {
    return this.aceProApiAvailable == null &&
      !this.aceProDetected &&
      !hasAceProConfig(this.aceProPrinterState)
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
    return this.aceProState.stale ||
      this.aceProHasWait([WAIT_REFRESH, WAIT_SLOT_ACTION, WAIT_DRYER_ACTION, WAIT_QUICK_ACTION]) ||
      this.aceProState.endlessSpool.inProgress ||
      this.aceProStatus === 'busy' ||
      this.aceProState.toolchange.active ||
      this.aceProState.toolchange.recoveryRequired ||
      this.aceProState.motionOwner.length > 0
  }

  get aceProToolchangeActive (): boolean {
    return this.aceProState.toolchange.active
  }

  get aceProToolchangeRecoveryRequired (): boolean {
    return this.aceProState.toolchange.recoveryRequired
  }

  get aceProPrinting (): boolean {
    return this.aceProState.printing
  }

  get aceProMotionControlsDisabled (): boolean {
    return this.aceProMotionBlockReason !== ''
  }

  get aceProMotionBlockReason (): string {
    if (!this.aceProConnected) return 'ACE 未连接'
    if (this.aceProState.stale) return '状态已过期，等待刷新'
    if (this.aceProPrinting) return '打印或暂停期间不可操作'
    if (this.aceProState.toolchange.recoveryRequired) return '换料恢复尚未完成'
    if (this.aceProState.toolchange.active) return '换料动作正在执行'
    if (this.aceProState.motionOwner.length > 0) {
      return `动作锁：${this.aceProState.motionOwner}`
    }
    if (this.aceProHasWait([WAIT_REFRESH, WAIT_SLOT_ACTION, WAIT_DRYER_ACTION, WAIT_QUICK_ACTION])) {
      return '操作请求正在执行'
    }
    if (this.aceProState.endlessSpool.inProgress) return '无限续料动作正在执行'
    if (this.aceProStatus === 'busy') return 'ACE 正忙'
    return ''
  }

  get aceProCalibrationBlockReason (): string {
    if (this.aceProMotionBlockReason) return this.aceProMotionBlockReason
    const sensors = this.aceProState.sensors
    const unavailable = []
    if (!sensors.upper.available) unavailable.push('上方传感器')
    if (!sensors.lower.available) unavailable.push('下方传感器')
    if (unavailable.length > 0) return `传感器不可用：${unavailable.join('、')}`

    const detected = []
    if (sensors.upper.detected) detected.push('上方传感器')
    if (sensors.lower.detected) detected.push('下方传感器')
    if (sensors.parking.available && sensors.parking.detected) detected.push('五通传感器')
    if (detected.length > 0) return `仍检测到耗材：${detected.join('、')}`
    return ''
  }

  get aceProConfigurationDiagnostics (): Array<{ label: string; value: string }> {
    const configuration = this.aceProState.configuration
    const value = (raw: number | null, suffix = '') => raw == null ? '未报告' : `${raw}${suffix}`
    return [
      { label: '配置版本', value: value(configuration.aceConfigVersion, '') },
      { label: '上方传感器消抖', value: value(configuration.extruderSensorDebounceCount, ' 次') },
      { label: '下方传感器消抖', value: value(configuration.toolheadSensorDebounceCount, ' 次') },
      { label: '送料绝对上限', value: value(configuration.toolchangeFeedHardLimit, ' mm') },
      { label: '回料绝对上限', value: value(configuration.toolchangeRetractHardLimit, ' mm') },
    ]
  }

  get aceProActiveWarnings (): string[] {
    const historicalError = this.aceProState.toolchange.lastError
    if (!historicalError || this.aceProState.toolchange.active || this.aceProState.toolchange.recoveryRequired) {
      return this.aceProState.warnings
    }
    return this.aceProState.warnings.filter(warning => warning !== historicalError)
  }

  get aceProFaultControlLabel (): string {
    return this.aceProState.toolchange.active ||
      this.aceProState.toolchange.recoveryRequired ||
      this.aceProState.motionOwner.length > 0
      ? '紧急停止'
      : '清除故障'
  }

  get aceProCalibrationStatusLabel (): string {
    const calibration = this.aceProState.calibration
    if (!calibration.available) return '不可用'
    if (calibration.lastError || calibration.phase === 'failed') return '失败'
    if (calibration.stale) return '已过期'
    if (calibration.valid) return '有效'
    const labels: Record<string, string> = {
      idle: '未探测',
      feeding: '正在探测送料路径',
      feed_complete: '送料路径已探测，等待回料探测',
      retracting: '正在探测回料路径',
      retract_complete: '料管长度已探测，等待保存',
      saved: '探测结果已保存',
      unavailable: '不可用',
    }
    return labels[calibration.phase] || '未标定'
  }

  get aceProCalibrationCanRetract (): boolean {
    return this.aceProState.calibration.phase === 'feed_complete'
  }

  get aceProCalibrationCanSave (): boolean {
    return this.aceProState.calibration.phase === 'retract_complete'
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

  get aceProAutoDryingStatusLabel (): string {
    return autoDryingStatusLabel(this.aceProState.autoDrying)
  }

  get aceProAutoDryingBasisLabel (): string {
    return autoDryingBasisLabel(this.aceProState.autoDrying)
  }

  get aceProAutoDryingAvailable (): boolean {
    return this.aceProState.autoDrying.available
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
      const status = await getAceStatus()
      const resolved = resolveAceProApiState(
        status,
        resolveAceProState(this.aceProPrinterState)
      )
      this.aceProApiStatus = status
      this.aceProApiAvailable = true
      await this.handleAceProAutoDryingNotice(resolved)
    } catch (error: any) {
      if (error?.response?.status === 404) {
        this.aceProApiAvailable = false
        this.aceProApiStatus = null
      }
    }
  }

  private async handleAceProAutoDryingNotice (state: AceProResolvedState) {
    const notice = state.autoDrying
    if (this.aceProLastNoticeId == null) {
      this.aceProLastNoticeId = notice.noticeId
      return
    }
    if (shouldResetAceNoticeSequence(notice.noticeId, this.aceProLastNoticeId)) {
      this.aceProLastNoticeId = notice.noticeId
      return
    }
    if (!shouldShowAceNotice(notice.noticeId, this.aceProLastNoticeId)) return
    this.aceProLastNoticeId = notice.noticeId
    const description = notice.noticeMessage || notice.lastError
    if (!description) return
    await this.$typedDispatch('notifications/pushNotification', {
      id: `ace-auto-drying-${notice.noticeId}`,
      type: notice.lastError ? 'error' : 'info',
      title: 'ACE Pro 自动烘干',
      description,
      snackbar: true,
      clear: true,
    })
  }

  private async executeAceCommand (
    command: string,
    params: Record<string, string | number | boolean | number[]>,
    wait: string
  ): Promise<boolean> {
    if (this.aceProApiAvailable === false) {
      this.aceProLastError = ACE_API_UNAVAILABLE_ERROR
      return false
    }

    this.aceProApiWaits = [...this.aceProApiWaits, wait]
    try {
      await runAceCommand({ command, params })
      this.aceProApiAvailable = true
      this.aceProLastError = ''
      await this.pollAceProApi()
      return true
    } catch (error: any) {
      const status = error?.response?.status
      const responseData = error?.response?.data?.result ?? error?.response?.data
      const serverMessage = responseData?.error?.message

      if (status === 404) {
        this.aceProApiAvailable = false
        this.aceProApiStatus = null
      }

      if (status === 404) {
        this.aceProLastError = ACE_API_UNAVAILABLE_ERROR
      } else if (typeof serverMessage === 'string' && serverMessage.trim() !== '') {
        this.aceProLastError = serverMessage
      } else if (status === 409) {
        this.aceProLastError = 'ACE Pro 操作被当前打印机状态拒绝（HTTP 409）。'
      } else if (typeof status === 'number' && status >= 500) {
        this.aceProLastError = `ACE Pro 控制服务错误（HTTP ${status}）。`
      } else if (error?.response == null) {
        this.aceProLastError = `无法连接 ACE Pro 控制 API：${error?.message || '网络错误'}`
      } else {
        this.aceProLastError = error?.message || `${command} 执行失败`
      }

      console.error(`ACE Pro command failed: ${command}`, error)
      return false
    } finally {
      this.aceProApiWaits = this.aceProApiWaits.filter(item => item !== wait)
    }
  }

  async refreshAcePro () {
    await this.pollAceProApi()
  }

  async handleSlotPrimaryAction (slot: AceProResolvedSlot) {
    if (slot.isActive) {
      const result = await this.$confirm(
        `要卸载 ${slot.index + 1} 号料槽中的耗材吗？`,
        { title: 'ACE Pro', color: 'card-heading', icon: '$warning' }
      )

      if (result) {
        await this.executeAceCommand('ACE_CHANGE_TOOL', { TOOL: -1 }, WAIT_SLOT_ACTION)
      }
      return
    }

    if (!slot.ready) return

    const result = await this.$confirm(
      `要装载 ${slot.index + 1} 号料槽中的耗材吗？`,
      { title: 'ACE Pro', color: 'card-heading', icon: '$warning' }
    )

    if (result) {
      await this.executeAceCommand('ACE_CHANGE_TOOL', { TOOL: slot.index }, WAIT_SLOT_ACTION)
    }
  }

  async saveSlot (index: number, material: string, colorHex: string, temperature: number) {
    const color = this.aceHexColorToRgb(colorHex)
    await this.executeAceCommand('ACE_SET_SLOT', {
      INDEX: index,
      MATERIAL: material.trim().toUpperCase(),
      COLOR: color,
      TEMP: Math.round(temperature),
    }, WAIT_SLOT_ACTION)
  }

  async clearSlot (index: number) {
    await this.executeAceCommand('ACE_SET_SLOT', { INDEX: index, EMPTY: 1 }, WAIT_SLOT_ACTION)
  }

  async unloadCurrentSlot () {
    const result = await this.$confirm(
      '确认卸载当前耗材并执行完整回料流程？',
      { title: 'ACE Pro 卸载耗材', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand('ACE_CHANGE_TOOL', { TOOL: -1 }, WAIT_QUICK_ACTION)
  }

  async abortToolchange () {
    await this.executeAceCommand(
      'ACE_ABORT_TOOLCHANGE',
      {},
      WAIT_QUICK_ACTION
    )
    await this.pollAceProApi()
  }

  aceProSlotPositionLabel (position: string): string {
    const labels: Record<string, string> = {
      internal_or_unknown: 'ACE 内部或未知',
      preload_parked_estimated: '五通预停放',
      upper_sensor: '上方传感器',
      toolhead: '挤出机内',
      nozzle: '喷嘴',
      unknown: '位置未知',
    }
    return labels[position] || '位置未知'
  }

  async saveInventory () {
    await this.executeAceCommand('ACE_SAVE_INVENTORY', {}, WAIT_QUICK_ACTION)
  }

  async toggleEndlessSpool (enabled: boolean) {
    const command = enabled ? 'ACE_ENABLE_ENDLESS_SPOOL' : 'ACE_DISABLE_ENDLESS_SPOOL'
    await this.executeAceCommand(command, {}, WAIT_SLOT_ACTION)
  }

  async toggleAceProAutoDrying (enabled: boolean) {
    const autoDrying = this.aceProState.autoDrying
    if (enabled && (autoDrying.reason === 'PLA_MIXED' || autoDrying.reason === 'UNKNOWN')) {
      const accepted = await this.$confirm(
        autoDryingWarningMessage(autoDrying.reason, autoDrying.temperature),
        { title: 'ACE Pro 自动烘干', color: 'card-heading', icon: '$warning' }
      )
      if (!accepted) return
    }
    const command = enabled
      ? 'ACE_ENABLE_AUTO_DRYING'
      : 'ACE_DISABLE_AUTO_DRYING'
    await this.executeAceCommand(command, {}, WAIT_DRYER_ACTION)
  }

  async startDrying (temperature: number, duration: number) {
    const temp = Math.round(temperature)
    const minutes = Math.round(duration)
    await this.executeAceCommand('ACE_START_DRYING', { TEMP: temp, DURATION: minutes }, WAIT_DRYER_ACTION)
  }

  async stopDrying () {
    await this.executeAceCommand('ACE_STOP_DRYING', {}, WAIT_DRYER_ACTION)
  }

  async toggleFeedAssist (index: number, enabled: boolean) {
    const command = enabled ? 'ACE_ENABLE_FEED_ASSIST' : 'ACE_DISABLE_FEED_ASSIST'
    await this.executeAceCommand(command, { INDEX: index }, WAIT_SLOT_ACTION)
  }

  async changeSpool (index: number) {
    const result = await this.$confirm(
      `要回抽并释放 ${index + 1} 号料槽吗？`,
      { title: 'ACE Pro 换卷', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand('ACE_CHANGE_SPOOL', { INDEX: index, CONFIRM: 1 }, WAIT_SLOT_ACTION)
  }

  async manualFeed (index: number, length: number, speed: number) {
    const params = { INDEX: Math.round(index), LENGTH: Math.round(length), SPEED: Math.round(speed), CONFIRM: 1 }
    const result = await this.$confirm(
      `确认从 T${params.INDEX} 手动送料 ${params.LENGTH} mm，速度 ${params.SPEED} mm/s？`,
      { title: 'ACE Pro 手动送料', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_FEED',
      params,
      WAIT_QUICK_ACTION
    )
  }

  async manualRetract (index: number, length: number, speed: number) {
    const params = { INDEX: Math.round(index), LENGTH: Math.round(length), SPEED: Math.round(speed), CONFIRM: 1 }
    const result = await this.$confirm(
      `确认从 T${params.INDEX} 手动回抽 ${params.LENGTH} mm，速度 ${params.SPEED} mm/s？`,
      { title: 'ACE Pro 手动回抽', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_RETRACT',
      params,
      WAIT_QUICK_ACTION
    )
  }

  async preloadSlot (index: number) {
    const result = await this.$confirm(
      `确认将 T${index} 冷态预装载到挤出机下方传感器？此操作不会加热或送到喷嘴。`,
      { title: 'ACE Pro 冷态预装载', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_PRELOAD',
      { INDEX: index, CONFIRM: 1 },
      WAIT_QUICK_ACTION
    )
  }

  async calibrateFeed (index: number) {
    const result = await this.$confirm(
      `确认使用 T${index} 开始自动探测料管长度？开始前上下传感器必须均无料。`,
      { title: 'ACE Pro 自动探测料管长度', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_CALIBRATE_FEED',
      { INDEX: index, CONFIRM: 1 },
      WAIT_QUICK_ACTION
    )
  }

  async calibrate (index: number) {
    const result = await this.$confirm(
      '确认使用 T' + index + ' 自动探测料管长度并完成回料定位？开始前上下方及五通传感器必须均无料。',
      { title: 'ACE Pro 自动探测料管长度', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_CALIBRATE',
      { INDEX: index, CONFIRM: 1 },
      WAIT_QUICK_ACTION
    )
  }

  async calibrateRetract () {
    const result = await this.$confirm(
      '确认继续探测回料路径，并将耗材回收到五通预停放位置？',
      { title: 'ACE Pro 自动探测料管长度', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_CALIBRATE_RETRACT',
      { CONFIRM: 1 },
      WAIT_QUICK_ACTION
    )
  }

  async saveCalibration () {
    const result = await this.$confirm(
      '确认保存自动探测的料管长度和停放距离？配置中的管长或停车余量变化后需要重新探测。',
      { title: 'ACE Pro 保存探测结果', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_CALIBRATION_SAVE',
      { CONFIRM: 1 },
      WAIT_QUICK_ACTION
    )
  }

  async cancelCalibration () {
    await this.executeAceCommand(
      'ACE_CALIBRATION_CANCEL',
      {},
      WAIT_QUICK_ACTION
    )
  }

  async fullUnload (index: number) {
    const result = await this.$confirm(
      `确认将 T${index} 完全退回 ACE 内部？请确认料路没有卡料。`,
      { title: 'ACE Pro 完全卸载', color: 'card-heading', icon: '$warning' }
    )
    if (!result) return
    await this.executeAceCommand(
      'ACE_FULL_UNLOAD',
      { INDEX: index, CONFIRM: 1 },
      WAIT_QUICK_ACTION
    )
  }

  async testRunoutSensors () {
    await this.executeAceCommand(
      'ACE_TEST_RUNOUT_SENSOR',
      {},
      WAIT_QUICK_ACTION
    )
    await this.pollAceProApi()
  }
}
