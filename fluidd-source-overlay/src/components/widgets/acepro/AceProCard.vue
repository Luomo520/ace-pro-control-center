<template>
  <collapsable-card
    title="ACE Pro"
    icon="$mmu"
    draggable
    layout-path="dashboard.ace-pro-card"
  >
    <template #menu>
      <app-btn
        v-if="showPageLink"
        small
        text
        :to="{ name: 'acepro' }"
      >
        打开页面
      </app-btn>
    </template>

    <v-card-text
      v-if="aceProSupportsUi"
      class="acepro-card"
    >
      <div class="acepro-card__header">
        <div>
          <div class="acepro-card__title">
            ACE Pro 控制面板
          </div>
          <div class="acepro-card__subtitle">
            设备状态、烘干控制、料槽管理
          </div>
        </div>

        <div
          class="acepro-card__connection"
          :class="connectionClass"
        >
          <span class="acepro-card__dot" />
          {{ connectionText }}
        </div>
      </div>

      <v-alert
        v-if="aceProToolchangeRecoveryRequired"
        dense
        outlined
        type="error"
        class="acepro-card__recovery"
      >
        <div>换料已停止，耗材位置不确定。请检查路径和上下传感器。</div>
        <div class="acepro-recovery-actions">
          <app-btn
            small
            color="error"
            :loading="aceProHasWait(aceProWaitQuickAction)"
            @click="abortToolchange"
          >
            重新发送停止
          </app-btn>
          <app-btn
            small
            text
            :disabled="!aceProToolchangeCanAcknowledge"
            :loading="aceProHasWait(aceProWaitQuickAction)"
            @click="acknowledgeToolchange"
          >
            确认已安全处理
          </app-btn>
        </div>
      </v-alert>
      <v-alert
        v-else-if="aceProToolchangeActive"
        dense
        outlined
        type="warning"
        class="acepro-card__recovery"
      >
        <div>换料进行中：{{ aceProState.toolchange.context.phase || '准备中' }}</div>
        <app-btn
          small
          text
          color="error"
          :loading="aceProHasWait(aceProWaitQuickAction)"
          @click="abortToolchange"
        >
          停止换料
        </app-btn>
      </v-alert>

      <div class="acepro-card__top-grid">
        <section class="acepro-panel">
          <div class="acepro-panel__title">
            设备状态
          </div>

          <div class="acepro-info-grid">
            <div class="acepro-info-item">
              <span>型号</span>
              <strong>{{ aceProState.model || 'Anycubic Color Engine Pro' }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>运行状态</span>
              <strong :class="statusClass">{{ statusText }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>设备温度</span>
              <strong>{{ aceProState.temperature }}°C</strong>
            </div>
            <div
              v-if="aceProState.humidity != null"
              class="acepro-info-item"
            >
              <span>湿度</span>
              <strong>{{ humidityText }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>风扇转速</span>
              <strong>{{ aceProState.fanSpeed || 0 }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>RFID</span>
              <strong>{{ aceProState.rfidEnabled ? '已启用' : '未启用' }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>当前装载</span>
              <strong>{{ currentToolText }}</strong>
            </div>
            <div class="acepro-sensor-row">
              <span>上方传感器</span>
              <strong
                class="acepro-sensor"
                :class="sensorClass(aceProState.sensors.upper.available, aceProState.sensors.upper.detected)"
              >
                {{ sensorText(aceProState.sensors.upper.available, aceProState.sensors.upper.detected) }}
              </strong>
            </div>
            <div class="acepro-sensor-row">
              <span>下方传感器</span>
              <strong
                class="acepro-sensor"
                :class="sensorClass(aceProState.sensors.lower.available, aceProState.sensors.lower.detected)"
              >
                {{ sensorText(aceProState.sensors.lower.available, aceProState.sensors.lower.detected) }}
              </strong>
            </div>
            <div class="acepro-info-item">
              <span>无限续料</span>
              <strong>{{ aceProState.endlessSpool.enabled ? '已开启' : '已关闭' }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>自动烘干</span>
              <strong>{{ aceProAutoDryingStatusLabel }}</strong>
            </div>
          </div>
        </section>

        <section class="acepro-panel">
          <div class="acepro-panel__title">
            烘干控制
          </div>

          <div class="acepro-dryer">
            <div class="acepro-dryer__row">
              <div class="acepro-dryer__field">
                <label>设定温度</label>
                <v-text-field
                  v-model.number="dryerTemperature"
                  dense
                  outlined
                  hide-details
                  type="number"
                  min="20"
                  max="65"
                  suffix="°C"
                  :disabled="aceProBusy || aceProDryerActive"
                  @input="dryerTemperatureTouched = true"
                />
              </div>
              <div class="acepro-dryer__field">
                <label>烘干时长</label>
                <v-text-field
                  v-model.number="dryerDuration"
                  dense
                  outlined
                  hide-details
                  type="number"
                  min="1"
                  suffix="min"
                  :disabled="aceProBusy || aceProDryerActive"
                />
              </div>
            </div>

            <div class="acepro-dryer__status">
              <div class="acepro-info-item">
                <span>烘干状态</span>
                <strong>{{ dryerStatusText }}</strong>
              </div>
              <div class="acepro-info-item">
                <span>目标温度</span>
                <strong>{{ dryerTargetTemperatureText }}</strong>
              </div>
              <div class="acepro-info-item">
                <span>剩余时间</span>
                <strong>{{ remainTimeText }}</strong>
              </div>
            </div>

            <div class="acepro-auto-drying">
              <div class="acepro-auto-drying__copy">
                <strong>自动跟随打印</strong>
                <span>{{ aceProAutoDryingBasisLabel }}</span>
              </div>
              <v-switch
                :input-value="aceProState.autoDrying.enabled"
                inset
                hide-details
                :disabled="!aceProAutoDryingAvailable || aceProHasWait(aceProWaitDryerAction)"
                :loading="aceProHasWait(aceProWaitDryerAction)"
                @change="toggleAceProAutoDrying"
              />
            </div>
            <div
              v-if="aceProState.autoDrying.lastError"
              class="acepro-auto-drying__error"
            >
              {{ aceProState.autoDrying.lastError }}
            </div>

            <div class="acepro-dryer__actions">
              <app-btn
                small
                :disabled="aceProBusy || dryerTemperature <= 0 || dryerDuration <= 0 || aceProDryerActive"
                :loading="aceProHasWait(aceProWaitDryerAction)"
                @click="startDrying(dryerTemperature, dryerDuration)"
              >
                开始烘干
              </app-btn>
              <app-btn
                small
                text
                color="error"
                :disabled="aceProBusy || !aceProDryerActive"
                :loading="aceProHasWait(aceProWaitDryerAction)"
                @click="stopDrying"
              >
                停止烘干
              </app-btn>
            </div>
          </div>
        </section>
      </div>

      <section class="acepro-panel acepro-panel--slots">
        <div class="acepro-panel__header">
          <div class="acepro-panel__title">
            料槽管理
          </div>
          <div
            class="acepro-panel__tool-indicator"
            :class="{ 'acepro-panel__tool-indicator--none': aceProCurrentIndex < 0 }"
          >
            当前装载: {{ currentToolText }}
          </div>
        </div>

        <v-row class="acepro-slot-grid">
          <v-col
            v-for="slot in aceProSlots"
            :key="slot.index"
            cols="12"
            sm="6"
            md="4"
            lg="3"
            xl="3"
            class="acepro-slot-grid__col"
          >
            <ace-pro-slot-card
              :slot="slot"
              :active="slot.isActive"
              :busy="aceProHasWait(aceProWaitSlotAction)"
              :disabled="aceProBusy"
              :assist-active="aceProState.feedAssistIndex === slot.index"
              @primary="handleSlotPrimaryAction"
              @save="saveSlotFromEvent"
              @empty="clearSlot"
              @assist="toggleFeedAssist($event.index, $event.enabled)"
              @change-spool="changeSpool"
            />
          </v-col>
        </v-row>
      </section>

      <section class="acepro-panel acepro-panel--manual">
        <div class="acepro-panel__title">
          手动送料
        </div>
        <div class="acepro-manual-controls">
          <v-select
            v-model.number="manualSlot"
            :items="manualSlotOptions"
            dense
            outlined
            hide-details
            label="料槽"
            :disabled="aceProBusy || aceProPrinting"
          />
          <v-text-field
            v-model.number="manualLength"
            dense
            outlined
            hide-details
            type="number"
            min="1"
            max="500"
            label="长度"
            suffix="mm"
            :disabled="aceProBusy || aceProPrinting"
          />
          <v-text-field
            v-model.number="manualSpeed"
            dense
            outlined
            hide-details
            type="number"
            min="1"
            max="120"
            label="速度"
            suffix="mm/s"
            :disabled="aceProBusy || aceProPrinting"
          />
          <app-btn
            small
            :disabled="aceProBusy || aceProPrinting || !manualValuesValid"
            :loading="aceProHasWait(aceProWaitQuickAction)"
            @click="runManualFeed"
          >
            送料
          </app-btn>
          <app-btn
            small
            text
            :disabled="aceProBusy || aceProPrinting || !manualValuesValid"
            :loading="aceProHasWait(aceProWaitQuickAction)"
            @click="runManualRetract"
          >
            回抽
          </app-btn>
        </div>
        <div
          v-if="aceProPrinting"
          class="acepro-card__notice"
        >
          打印中已禁用手动送料与回抽。
        </div>
      </section>

      <section class="acepro-panel acepro-panel--quick">
        <div class="acepro-panel__title">
          快捷操作
        </div>

        <div class="acepro-quick-actions">
          <app-btn
            small
            :loading="aceProHasWait(aceProWaitQuickAction) || aceProHasWait(aceProWaitRefresh)"
            @click="refreshAcePro"
          >
            刷新状态
          </app-btn>
          <app-btn
            small
            :disabled="aceProBusy || aceProCurrentIndex < 0"
            :loading="aceProHasWait(aceProWaitQuickAction)"
            @click="unloadCurrentSlot"
          >
            卸载当前耗材
          </app-btn>
          <app-btn
            small
            :disabled="aceProBusy"
            :loading="aceProHasWait(aceProWaitQuickAction)"
            @click="saveInventory"
          >
            保存库存
          </app-btn>
          <app-btn
            small
            text
            :disabled="aceProBusy"
            :loading="aceProHasWait(aceProWaitQuickAction)"
            @click="testRunoutSensors"
          >
            诊断传感器
          </app-btn>
          <div class="acepro-quick-actions__switch">
            <span>无限续料</span>
            <v-switch
              :input-value="aceProState.endlessSpool.enabled"
              inset
              hide-details
              :disabled="aceProBusy"
              @change="toggleEndlessSpool"
            />
          </div>
        </div>
      </section>

      <v-alert
        v-if="aceProLastError || aceProState.warnings.length"
        dense
        outlined
        type="warning"
        class="acepro-card__warning"
      >
        {{ aceProLastError || aceProState.warnings.join('；') }}
      </v-alert>
    </v-card-text>

    <v-card-text v-else>
      <v-alert
        dense
        outlined
        type="info"
      >
        未检测到 ACE Pro。请确认已安装 ACEPROSV08 驱动，并已启用 Moonraker [ace_status] 组件。
      </v-alert>
    </v-card-text>
  </collapsable-card>
</template>

<script lang="ts">
import { Component, Mixins, Prop, Watch } from 'vue-property-decorator'
import AceProMixin from '@/mixins/acePro'
import AceProSlotCard from '@/components/widgets/acepro/AceProSlotCard.vue'

@Component({
  components: {
    AceProSlotCard,
  },
})
export default class AceProCard extends Mixins(AceProMixin) {
  @Prop({ type: Boolean, default: true })
  readonly showPageLink!: boolean

  dryerTemperature = 45
  dryerDuration = 240
  dryerTemperatureTouched = false
  autoDryerTemperature = 45
  manualSlot = 0
  manualLength = 50
  manualSpeed = 25

  mounted () {
    this.syncDryerTemperature()
  }

  @Watch('aceProState', { deep: true })
  onAceProStateChanged () {
    this.syncDryerTemperature()
  }

  getDryerTemperatureForMaterial (material: string): number {
    const normalized = material.trim().toUpperCase()
    if (normalized.startsWith('ABS') || normalized.startsWith('PETG')) return 60
    if (normalized.startsWith('PAHTCF') || normalized.startsWith('PETCF') || normalized.startsWith('PEEK')) return 60
    return 45
  }

  syncDryerTemperature () {
    const activeSlot = this.aceProSlots.find(slot => slot.isActive)
    if (!activeSlot?.material) return

    const nextTemperature = this.getDryerTemperatureForMaterial(activeSlot.material)
    if (!this.dryerTemperatureTouched || this.dryerTemperature === this.autoDryerTemperature) {
      this.dryerTemperature = nextTemperature
      this.autoDryerTemperature = nextTemperature
    }
  }

  readonly manualSlotOptions = [
    { text: '料槽 1', value: 0 },
    { text: '料槽 2', value: 1 },
    { text: '料槽 3', value: 2 },
    { text: '料槽 4', value: 3 },
  ]

  get connectionClass (): string {
    const state = this.aceProState.connectionState || (this.aceProConnected ? 'connected' : 'disconnected')

    if (state === 'connected') return 'acepro-card__connection--connected'
    if (state === 'reconnecting' || state === 'connecting' || state === 'initializing') return 'acepro-card__connection--connecting'
    return 'acepro-card__connection--disconnected'
  }

  get connectionText (): string {
    const state = this.aceProState.connectionState || (this.aceProConnected ? 'connected' : 'disconnected')

    if (state === 'connected') return '已连接'
    if (state === 'reconnecting') return '重连中'
    if (state === 'connecting') return '连接中'
    if (state === 'initializing') return '初始化中'
    return '未连接'
  }

  get statusClass (): string {
    if (this.aceProStatus === 'ready') return 'acepro-card__value--ready'
    if (this.aceProStatus === 'busy') return 'acepro-card__value--busy'
    return 'acepro-card__value--muted'
  }

  get statusText (): string {
    if (this.aceProStatus === 'ready') return '就绪'
    if (this.aceProStatus === 'busy') return '忙碌'
    if (this.aceProStatus === 'offline') return '离线'
    return this.aceProStatus || '未知'
  }

  get dryerStatusText (): string {
    if (this.aceProState.dryer.status === 'drying') return '烘干中'
    if (this.aceProState.dryer.status === 'stop') return '已停止'
    return this.aceProState.dryer.status || '未知'
  }

  get currentToolText (): string {
    return this.aceProCurrentIndex >= 0
      ? `${this.aceProCurrentIndex + 1} 号料槽`
      : '无'
  }

  get humidityText (): string {
    return this.aceProState.humidity == null
      ? '--'
      : `${this.aceProState.humidity}% RH`
  }

  get dryerTargetTemperatureText (): string {
    const target = Math.round(this.aceProState.dryer.target_temp || 0)
    return target > 0 ? `${target}°C` : '--'
  }

  get remainTimeText (): string {
    const remain = Math.ceil(this.aceProState.dryer.remain_time || 0)
    if (remain <= 0) return '--'

    const hours = Math.floor(remain / 60)
    const minutes = remain % 60

    return hours > 0
      ? `${hours} 小时 ${minutes} 分`
      : `${minutes} 分`
  }

  get manualValuesValid (): boolean {
    return this.manualSlot >= 0 && this.manualSlot <= 3 &&
      this.manualLength >= 1 && this.manualLength <= 500 &&
      this.manualSpeed >= 1 && this.manualSpeed <= 120
  }

  sensorText (available: boolean, detected: boolean): string {
    if (!available) return '不可用'
    return detected ? '有料' : '无料'
  }

  sensorClass (available: boolean, detected: boolean): Record<string, boolean> {
    return {
      'acepro-sensor--on': available && detected,
      'acepro-sensor--off': available && !detected,
      'acepro-sensor--missing': !available,
    }
  }

  runManualFeed () {
    if (!this.manualValuesValid) return
    this.manualFeed(this.manualSlot, this.manualLength, this.manualSpeed)
  }

  runManualRetract () {
    if (!this.manualValuesValid) return
    this.manualRetract(this.manualSlot, this.manualLength, this.manualSpeed)
  }

  saveSlotFromEvent (payload: { index: number, material: string, colorHex: string, temperature: number }) {
    this.saveSlot(payload.index, payload.material, payload.colorHex, payload.temperature)
  }
}
</script>

<style scoped>
.acepro-card {
  padding-top: 4px;
}

.acepro-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  margin-bottom: 8px;
  border-radius: 8px;
  background:
    linear-gradient(145deg, rgba(23, 28, 36, 0.98), rgba(16, 20, 26, 0.98));
  border: 1px solid rgba(65, 74, 88, 0.55);
  box-shadow: 0 16px 30px rgba(0, 0, 0, 0.24);
}

.acepro-card__title {
  font-size: 17px;
  font-weight: 800;
  color: #f5f7fb;
}

.acepro-card__subtitle {
  margin-top: 1px;
  font-size: 11px;
  color: rgba(185, 195, 207, 0.82);
}

.acepro-card__connection {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.acepro-card__connection--connected {
  color: #d1fae5;
  background: rgba(20, 83, 45, 0.72);
  border: 1px solid rgba(49, 196, 141, 0.4);
}

.acepro-card__connection--connecting {
  color: #fef3c7;
  background: rgba(120, 53, 15, 0.7);
  border: 1px solid rgba(245, 158, 11, 0.4);
}

.acepro-card__connection--disconnected {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.68);
  border: 1px solid rgba(248, 113, 113, 0.4);
}

.acepro-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: currentColor;
}

.acepro-card__top-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.acepro-panel {
  padding: 10px;
  margin-bottom: 8px;
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(28, 34, 43, 0.96), rgba(16, 20, 26, 0.98));
  border: 1px solid rgba(61, 71, 86, 0.45);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.22);
}

.acepro-panel--slots {
  margin-bottom: 8px;
}

.acepro-slot-grid {
  margin: -4px;
}

.acepro-slot-grid__col {
  padding: 4px;
}

.acepro-panel__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 6px;
}

.acepro-panel__title {
  margin-bottom: 6px;
  font-size: 14px;
  font-weight: 800;
  color: #f3f6fb;
}

.acepro-panel__tool-indicator {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  color: #cffafe;
  background: rgba(8, 145, 178, 0.18);
  border: 1px solid rgba(34, 211, 238, 0.3);
}

.acepro-panel__tool-indicator--none {
  color: #d0d7e2;
  background: rgba(55, 65, 81, 0.46);
  border-color: rgba(107, 114, 128, 0.35);
}

.acepro-info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
}

.acepro-info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 5px 7px;
  border-radius: 6px;
  background: rgba(12, 16, 21, 0.6);
  border: 1px solid rgba(56, 66, 79, 0.4);
  font-size: 12px;
}

.acepro-info-item span {
  color: rgba(188, 197, 210, 0.82);
}

.acepro-info-item strong {
  color: #f3f7fc;
  text-align: right;
}

.acepro-sensor-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 32px;
  padding: 5px 7px;
  border-radius: 6px;
  background: rgba(12, 16, 21, 0.6);
  border: 1px solid rgba(56, 66, 79, 0.4);
  font-size: 12px;
  color: rgba(188, 197, 210, 0.82);
}

.acepro-sensor {
  min-width: 48px;
  padding: 2px 7px;
  border-radius: 999px;
  text-align: center;
  font-size: 10px;
  border: 1px solid transparent;
}

.acepro-sensor--on {
  color: #d1fae5;
  background: rgba(20, 83, 45, 0.72);
  border-color: rgba(49, 196, 141, 0.4);
}

.acepro-sensor--off {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.6);
  border-color: rgba(248, 113, 113, 0.35);
}

.acepro-sensor--missing {
  color: #d0d7e2;
  background: rgba(55, 65, 81, 0.7);
}

.acepro-card__value--ready {
  color: #86efac !important;
}

.acepro-card__value--busy {
  color: #fbbf24 !important;
}

.acepro-card__value--muted {
  color: #d0d7e2 !important;
}

.acepro-dryer__row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.acepro-dryer__field label {
  display: block;
  margin-bottom: 3px;
  font-size: 12px;
  font-weight: 700;
  color: #dbe3ee;
}

.acepro-dryer__status {
  display: grid;
  gap: 5px;
  margin-top: 6px;
}

.acepro-dryer__actions {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}

.acepro-auto-drying {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 34px;
  margin-top: 6px;
  padding: 3px 7px;
  border-radius: 6px;
  background: rgba(12, 16, 21, 0.56);
  border: 1px solid rgba(56, 66, 79, 0.4);
}

.acepro-auto-drying__copy {
  display: grid;
  min-width: 0;
  font-size: 10px;
}

.acepro-auto-drying__copy span {
  color: #aeb9c8;
  overflow-wrap: anywhere;
}

.acepro-auto-drying__error {
  margin-top: 3px;
  font-size: 10px;
  color: #fca5a5;
}

.acepro-auto-drying ::v-deep .v-input--selection-controls {
  flex: 0 0 auto;
  margin: 0;
  padding: 0;
}

.acepro-quick-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.acepro-manual-controls {
  display: grid;
  grid-template-columns: minmax(100px, 0.7fr) repeat(2, minmax(120px, 1fr)) auto auto;
  gap: 6px;
  align-items: center;
}

.acepro-manual-controls ::v-deep .v-input__slot {
  min-height: 32px !important;
}

.acepro-card__notice {
  margin-top: 5px;
  font-size: 10px;
  color: #fbbf24;
}

.acepro-card__warning {
  margin: 0;
  font-size: 11px;
}

.acepro-card__recovery {
  margin: 0 0 8px;
  font-size: 11px;
}

.acepro-recovery-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.acepro-quick-actions__switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  min-height: 30px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(12, 16, 21, 0.56);
  border: 1px solid rgba(56, 66, 79, 0.4);
}

@media (min-width: 961px) {
  .acepro-card__header {
    padding: 6px 10px;
    margin-bottom: 6px;
  }

  .acepro-card__title {
    font-size: 15px;
  }

  .acepro-card__subtitle {
    font-size: 10px;
  }

  .acepro-card__connection {
    padding: 3px 7px;
    font-size: 10px;
  }

  .acepro-card__dot {
    width: 6px;
    height: 6px;
  }

  .acepro-card__top-grid {
    gap: 6px;
    margin-bottom: 6px;
  }

  .acepro-panel {
    padding: 7px;
    margin-bottom: 6px;
  }

  .acepro-panel__header {
    margin-bottom: 4px;
  }

  .acepro-panel__title {
    margin-bottom: 4px;
    font-size: 12px;
  }

  .acepro-panel__tool-indicator {
    padding: 2px 6px;
    font-size: 9px;
  }

  .acepro-info-grid,
  .acepro-dryer__status {
    gap: 3px;
  }

  .acepro-info-item {
    min-height: 26px;
    padding: 3px 5px;
    font-size: 10px;
  }

  .acepro-sensor-row {
    min-height: 26px;
    padding: 3px 5px;
    font-size: 10px;
  }

  .acepro-dryer__row {
    gap: 5px;
  }

  .acepro-dryer__field label {
    margin-bottom: 2px;
    font-size: 10px;
  }

  .acepro-dryer ::v-deep .v-input__slot {
    min-height: 32px !important;
  }

  .acepro-dryer ::v-deep input,
  .acepro-dryer ::v-deep .v-label,
  .acepro-dryer ::v-deep .v-input__append-inner {
    font-size: 11px;
  }

  .acepro-dryer__status,
  .acepro-dryer__actions {
    margin-top: 4px;
  }

  .acepro-dryer__actions ::v-deep .v-btn,
  .acepro-quick-actions ::v-deep .v-btn,
  .acepro-manual-controls ::v-deep .v-btn {
    min-height: 28px;
    padding: 0 8px;
    font-size: 10px;
  }

  .acepro-slot-grid {
    margin: -3px;
  }

  .acepro-slot-grid__col {
    padding: 3px;
  }

  .acepro-panel--slots {
    margin-bottom: 6px;
  }

  .acepro-panel--quick {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 42px;
  }

  .acepro-panel--quick .acepro-panel__title {
    flex: 0 0 auto;
    margin: 0;
  }

  .acepro-panel--quick .acepro-quick-actions {
    flex: 1;
  }

  .acepro-quick-actions__switch {
    padding: 1px 5px;
    font-size: 10px;
  }
}

@media (max-width: 960px) {
  .acepro-card__top-grid {
    grid-template-columns: 1fr;
  }

  .acepro-manual-controls {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .acepro-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .acepro-panel__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .acepro-info-grid,
  .acepro-dryer__row {
    grid-template-columns: 1fr;
  }

  .acepro-quick-actions__switch {
    margin-left: 0;
    width: 100%;
    justify-content: space-between;
  }

  .acepro-manual-controls {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
