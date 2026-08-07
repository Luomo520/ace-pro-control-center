<template>
  <collapsable-card
    title="ACE Pro 管理中心"
    icon="$mmu"
    :draggable="showPageLink"
    layout-path="dashboard.ace-v3-card"
  >
    <template #menu>
      <div class="acepro-toolbar-menu">
        <app-btn
          v-if="showPageLink"
          small
          text
          title="打开 ACE Pro 管理中心"
          @click="openDashboard"
        >
          打开页面
        </app-btn>
      </div>
    </template>

    <v-card-text v-if="loading && !viewModel">
      <v-alert
        dense
        outlined
        type="info"
      >
        <v-progress-circular
          indeterminate
          size="18"
          width="2"
          class="mr-2"
        />
        ACE Pro 管理中心正在读取设备状态...
      </v-alert>
    </v-card-text>

    <v-card-text v-else-if="loadIssue && !viewModel">
      <v-alert
        dense
        outlined
        type="error"
      >
        <strong>{{ loadIssue.title }}</strong>
        <div>{{ loadIssue.message }}</div>
        <div>{{ loadIssue.nextAction }}</div>
      </v-alert>
      <app-btn
        small
        class="mt-2"
        @click="refresh"
      >
        重试
      </app-btn>
    </v-card-text>

    <v-card-text
      v-else-if="viewModel && selectedDevice"
      class="acepro-card"
      :class="{ 'acepro-card--narrow': narrow }"
    >
      <v-alert
        v-if="statusStale"
        dense
        outlined
        type="error"
        class="mb-2"
      >
        <strong>ACE 状态连接已中断</strong>
        <div>当前显示的是上次成功读取的状态，恢复连接前物理动作已禁用。</div>
      </v-alert>

      <v-alert
        v-if="feedback"
        dense
        outlined
        :type="feedback.type"
        class="mb-2"
      >
        <strong>{{ feedback.title }}</strong>
        <div v-if="feedback.message">
          {{ feedback.message }}
        </div>
      </v-alert>

      <div class="acepro-card__header">
        <div>
          <div class="acepro-card__title">
            ACE Pro 管理中心
          </div>
          <div class="acepro-card__subtitle">
            V2.5ahpha · 设备状态、烘干控制、料槽管理
          </div>
        </div>
        <div
          class="acepro-card__connection"
          :class="connectionClass"
        >
          <span class="acepro-card__dot" />
          {{ connectionLabel }}
        </div>
      </div>

      <div
        v-if="viewModel.devices.length > 1"
        class="acepro-global-tool"
        aria-label="全局当前工具"
      >
        <div>
          <span>全局当前工具</span>
          <strong>{{ viewModel.currentToolLabel }}</strong>
          <small v-if="currentToolDevice">{{ currentToolDevice.name }} · 槽{{ currentToolTarget.slot + 1 }}</small>
          <small v-else>当前没有装载工具</small>
        </div>
        <app-btn
          v-if="currentToolDevice && currentToolDevice.id !== selectedDeviceId"
          small
          outlined
          @click="jumpToCurrentTool"
        >
          转到所属 ACE
        </app-btn>
      </div>

      <div
        class="acepro-toolchange-mode"
        :class="toolchangeModeClass"
      >
        <div>
          <strong>{{ toolchangeModeLabel }}</strong>
          <span>{{ toolchangeModeDescription }}</span>
        </div>
        <span class="acepro-toolchange-mode__state">{{ status.toolchangeReady ? '可自动换料' : '自动换料不可用' }}</span>
      </div>

      <div
        v-if="viewModel.devices.length > 1"
        class="acepro-device-switch"
        :style="{ '--ace-device-count': viewModel.devices.length }"
        role="group"
        aria-label="选择 ACE 设备"
      >
        <app-btn
          v-for="device in viewModel.devices"
          :key="device.id"
          small
          :outlined="device.id !== selectedDeviceId"
          :color="device.id === selectedDeviceId ? 'primary' : undefined"
          :aria-pressed="device.id === selectedDeviceId ? 'true' : 'false'"
          @click="selectDevice(device.id)"
        >
          <span
            class="acepro-device-switch__dot"
            :class="`acepro-device-switch__dot--${device.statusTone}`"
          />
          <span>{{ device.name }}</span>
          <span class="acepro-device-switch__tools">{{ device.slots[0].tool }}-{{ device.slots[3].tool }}</span>
        </app-btn>
      </div>

      <v-alert
        v-if="selectedDevice.readOnly"
        dense
        outlined
        type="warning"
        class="acepro-card__notice"
      >
        {{ selectedDevice.name }} 的物理动作已关闭；状态、RFID 和库存仍可使用。
      </v-alert>

      <div class="acepro-card__top-grid">
        <section
          class="acepro-panel"
          aria-labelledby="acepro-device-status-title"
        >
          <div
            id="acepro-device-status-title"
            class="acepro-panel__title"
          >
            设备状态
          </div>
          <div class="acepro-info-grid">
            <div class="acepro-info-item">
              <span>型号</span>
              <strong>{{ selectedDevice.modelLabel }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>运行状态</span>
              <strong :class="statusValueClass">{{ stateLabel(selectedDevice.state) }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>设备温度</span>
              <strong>{{ selectedDevice.temperatureLabel }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>风扇转速</span>
              <strong>{{ fanSpeedLabel }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>RFID</span>
              <strong>{{ rfidSummaryLabel }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>当前装载</span>
              <strong>{{ selectedCurrentTool }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>上方传感器</span>
              <strong
                class="acepro-sensor-status"
                :class="sensorStatusClass('upper')"
              >
                <span class="acepro-sensor-status__dot" />
                {{ upperSensorLabel }}
              </strong>
            </div>
            <div class="acepro-info-item">
              <span>上方送料超时</span>
              <strong>{{ upperFeedTimeoutLabel }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>下方传感器</span>
              <strong
                class="acepro-sensor-status"
                :class="sensorStatusClass('lower')"
                :title="lowerSensorTitle"
              >
                <span class="acepro-sensor-status__dot" />
                {{ lowerSensorLabel }}
              </strong>
            </div>
            <div class="acepro-info-item">
              <span>挤出机标定距离</span>
              <strong>{{ extruderCalibrationDistanceLabel }}</strong>
            </div>
            <div
              v-if="viewModel.usesFirstStageHubs"
              class="acepro-info-item"
            >
              <span>一级五通传感器</span>
              <strong
                class="acepro-sensor-status"
                :class="sensorStatusClass('hub')"
              >
                <span class="acepro-sensor-status__dot" />
                {{ hubSensorLabel }}
              </strong>
            </div>
            <div class="acepro-info-item">
              <span>总五通传感器</span>
              <strong
                class="acepro-sensor-status"
                :class="sensorStatusClass('rdm')"
              >
                <span class="acepro-sensor-status__dot" />
                {{ rdmSensorLabel }}
              </strong>
            </div>
            <div class="acepro-info-item">
              <span>共享编码器</span>
              <strong
                class="acepro-encoder-status"
                :class="sharedEncoderStatusClass"
                :title="sharedEncoderTitle"
              >
                <span class="acepro-encoder-status__dot" />
                {{ sharedEncoder.summaryLabel }}
              </strong>
            </div>
            <div class="acepro-info-item">
              <span>编码器最低跟随比例</span>
              <strong>{{ encoderMinTrackingRatioLabel }}</strong>
            </div>
            <div class="acepro-info-item">
              <span>无限续料</span>
              <strong>{{ endlessSpool.enabled ? '已开启' : '已关闭' }}</strong>
            </div>
            <div class="acepro-info-item acepro-info-item--wide">
              <span>送料控制</span>
              <strong>{{ feedControlLabel }}</strong>
            </div>
            <div class="acepro-info-item acepro-info-item--wide">
              <span>耗材路径</span>
              <strong>{{ filamentPathLabel }}</strong>
            </div>
          </div>
        </section>

        <section
          class="acepro-panel"
          aria-labelledby="acepro-dryer-title"
        >
          <div
            id="acepro-dryer-title"
            class="acepro-panel__title"
          >
            烘干控制
          </div>
          <div class="acepro-dryer">
            <div class="acepro-dryer__row">
              <div class="acepro-dryer__field">
                <label for="acepro-dryer-temperature">设定温度</label>
                <v-text-field
                  id="acepro-dryer-temperature"
                  v-model.number="dryerTemperature"
                  dense
                  outlined
                  hide-details
                  type="number"
                  min="20"
                  max="75"
                  suffix="°C"
                  :disabled="selectedDevice.dryer.active || actionBusy"
                />
              </div>
              <div class="acepro-dryer__field">
                <label for="acepro-dryer-duration">烘干时长</label>
                <v-text-field
                  id="acepro-dryer-duration"
                  v-model.number="dryerDuration"
                  dense
                  outlined
                  hide-details
                  type="number"
                  min="10"
                  max="1440"
                  suffix="min"
                  :disabled="selectedDevice.dryer.active || actionBusy"
                />
              </div>
            </div>
            <div class="acepro-dryer__status">
              <div class="acepro-info-item">
                <span>烘干状态</span>
                <strong>{{ selectedDevice.dryer.active ? '烘干中' : '未运行' }}</strong>
              </div>
              <div class="acepro-info-item">
                <span>目标温度</span>
                <strong>{{ dryerTargetLabel }}</strong>
              </div>
              <div class="acepro-info-item">
                <span>剩余时间</span>
                <strong>{{ dryerRemainingLabel }}</strong>
              </div>
            </div>
            <div class="acepro-dryer__actions">
              <app-btn
                small
                :disabled="selectedDevice.dryer.active || !startDryerDecision.allowed || !dryerInputValid || actionBusy"
                :title="startDryerDecision.reason"
                @click="requestStartDryer"
              >
                开始烘干
              </app-btn>
              <app-btn
                small
                text
                color="error"
                :disabled="!selectedDevice.dryer.active || !stopDryerDecision.allowed || actionBusy"
                :title="stopDryerDecision.reason"
                @click="requestStopDryer"
              >
                停止烘干
              </app-btn>
            </div>
          </div>
        </section>
      </div>

      <section
        class="acepro-panel acepro-panel--slots"
        aria-labelledby="acepro-slots-title"
      >
        <div class="acepro-panel__header">
          <div
            id="acepro-slots-title"
            class="acepro-panel__title"
          >
            料槽管理
          </div>
          <div
            class="acepro-panel__tool-indicator"
            :class="{ 'acepro-panel__tool-indicator--none': selectedCurrentTool === '未装载' }"
          >
            当前装载: {{ selectedCurrentTool }}
          </div>
        </div>
        <div
          v-for="device in viewModel.devices"
          v-show="device.id === selectedDeviceId"
          :key="device.id"
          class="acepro-device-slot-view"
        >
          <v-row class="acepro-slot-grid">
            <v-col
              v-for="slot in device.slots"
              :key="`${device.id}-${slot.index}`"
              cols="12"
              sm="6"
              lg="3"
              class="acepro-slot-grid__col"
            >
              <ace-v3-slot-card
                ref="slotCards"
                :slot="slot"
                :material-types="viewModel.materialTypes"
                :busy="actionBusy"
                :primary-decision="slotDecision(device, slot)"
                :settings-decision="actionDecision(ACE_ACTIONS.SET_SLOT, device, slot)"
                @primary="requestSlotAction(device, $event)"
                @save="saveSlotInline(device, $event)"
                @clear="requestClearSlot(device, $event)"
              />
            </v-col>
          </v-row>
        </div>
      </section>

      <section
        class="acepro-panel acepro-panel--manual"
        aria-labelledby="acepro-manual-title"
      >
        <div
          id="acepro-manual-title"
          class="acepro-panel__title"
        >
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
            :disabled="actionBusy"
          />
          <v-text-field
            v-model.number="manualLength"
            dense
            outlined
            hide-details
            type="number"
            min="1"
            max="2000"
            label="长度"
            suffix="mm"
            :disabled="actionBusy"
          />
          <v-text-field
            v-model.number="manualSpeed"
            dense
            outlined
            hide-details
            type="number"
            min="1"
            max="1000"
            label="速度"
            suffix="mm/s"
            :disabled="actionBusy"
          />
          <app-btn
            small
            :disabled="!manualDecision(ACE_ACTIONS.FEED).allowed || !manualInputValid || actionBusy"
            :title="manualDecision(ACE_ACTIONS.FEED).reason"
            @click="requestManual(ACE_ACTIONS.FEED)"
          >
            送料
          </app-btn>
          <app-btn
            small
            text
            :disabled="!manualDecision(ACE_ACTIONS.RETRACT).allowed || !manualInputValid || actionBusy"
            :title="manualDecision(ACE_ACTIONS.RETRACT).reason"
            @click="requestManual(ACE_ACTIONS.RETRACT)"
          >
            回抽
          </app-btn>
        </div>
      </section>

      <section
        class="acepro-panel acepro-panel--feed-assist"
        aria-labelledby="acepro-feed-assist-title"
      >
        <div class="acepro-panel__header">
          <div
            id="acepro-feed-assist-title"
            class="acepro-panel__title"
          >
            ACE 辅助送料
          </div>
          <div
            class="acepro-feed-assist__status"
            :class="{ 'acepro-feed-assist__status--active': feedAssist.active }"
          >
            当前：{{ feedAssist.label }}
          </div>
        </div>
        <div class="acepro-feed-assist__controls">
          <v-select
            v-model.number="feedAssistSlot"
            :items="manualSlotOptions"
            dense
            outlined
            hide-details
            label="辅助送料槽位"
            :disabled="actionBusy"
          />
          <app-btn
            small
            :disabled="!feedAssistEnableDecision.allowed || actionBusy"
            :title="feedAssistEnableDecision.reason"
            @click="requestEnableFeedAssist"
          >
            {{ feedAssist.active ? '切换到所选槽位' : '启用辅助送料' }}
          </app-btn>
          <app-btn
            small
            text
            color="error"
            :disabled="!feedAssistDisableDecision.allowed || actionBusy"
            :title="feedAssistDisableDecision.reason"
            @click="requestDisableFeedAssist"
          >
            停用辅助送料
          </app-btn>
        </div>
      </section>

      <section
        class="acepro-panel acepro-panel--quick"
        aria-labelledby="acepro-quick-title"
      >
        <div
          id="acepro-quick-title"
          class="acepro-panel__title"
        >
          快捷操作
        </div>
        <div class="acepro-quick-actions">
          <app-btn
            small
            :loading="loading"
            @click="refreshDevice(selectedDevice)"
          >
            刷新状态
          </app-btn>
          <app-btn
            small
            :disabled="!currentUnload.allowed || actionBusy"
            :title="currentUnload.reason"
            @click="requestUnloadCurrent"
          >
            卸载当前耗材
          </app-btn>
          <app-btn
            small
            :disabled="actionBusy"
            @click="saveInventory"
          >
            保存库存
          </app-btn>
          <app-btn
            small
            text
            :disabled="!diagnoseDecision.allowed || actionBusy"
            :title="diagnoseDecision.reason"
            @click="runDiagnostics"
          >
            诊断传感器
          </app-btn>
          <div
            class="acepro-quick-actions__switch"
            :title="endlessDecision.reason"
          >
            <span>无限续料 · {{ matchModeLabel }}</span>
            <v-switch
              :input-value="endlessSpool.enabled"
              inset
              hide-details
              :disabled="!endlessDecision.allowed || actionBusy"
              @change="toggleEndless"
            />
          </div>
        </div>
      </section>

      <button
        v-if="collapseExtraFunctions"
        type="button"
        class="acepro-more-toggle"
        :aria-expanded="showExtraFunctions ? 'true' : 'false'"
        @click="extraFunctionsOpen = !extraFunctionsOpen"
      >
        <span>更多功能</span>
        <v-icon small>
          {{ showExtraFunctions ? '$chevronUp' : '$chevronDown' }}
        </v-icon>
      </button>

      <v-expand-transition>
        <div
          v-show="showExtraFunctions"
          class="acepro-extra-functions"
        >
          <section class="acepro-panel acepro-panel--advanced">
            <div class="acepro-panel__title">
              诊断与维护
            </div>
            <div class="acepro-maintenance-grid">
              <div class="acepro-encoder-calibration">
                <div class="acepro-maintenance-heading">
                  <strong>共享编码器手动校准</strong>
                  <span :class="sharedEncoder.calibrationActive ? 'is-active' : ''">
                    {{ sharedEncoder.configured ? (sharedEncoder.calibrationActive ? '校准中' : '待机') : '未配置' }}
                  </span>
                </div>
                <p>
                  本向导不会驱动 ACE 或挤出机。开始计数后，请手动移动耗材，再填写实际移动长度。
                </p>
                <div class="acepro-calibration-readout">
                  <span>实时脉冲数</span>
                  <strong>{{ sharedEncoder.configured ? sharedEncoder.counts : '--' }}</strong>
                </div>
                <div
                  class="acepro-calibration-summary"
                  :class="`acepro-calibration-summary--${encoderCalibrationEvaluation.state}`"
                >
                  <strong>{{ encoderCalibrationEvaluation.completedCount }}/{{ encoderCalibrationEvaluation.segmentCount }} 段</strong>
                  <span>{{ encoderCalibrationEvaluation.message }}</span>
                </div>
                <div class="acepro-calibration-segments">
                  <div
                    v-for="segment in encoderCalibrationRows"
                    :key="segment.index"
                    class="acepro-calibration-segment"
                    :class="`acepro-calibration-segment--${segment.state}`"
                  >
                    <strong>第 {{ segment.index + 1 }} 段</strong>
                    <span>{{ segment.measurement }}</span>
                    <span>{{ segment.resolution }}</span>
                    <span>{{ segment.deviation }}</span>
                  </div>
                </div>
                <div class="acepro-calibration-controls">
                  <v-text-field
                    v-model.number="encoderCalibrationLength"
                    dense
                    outlined
                    hide-details
                    type="number"
                    min="0.01"
                    max="2000"
                    step="0.01"
                    label="每段移动长度"
                    suffix="mm"
                    :disabled="sharedEncoder.calibrationActive || actionBusy"
                  />
                  <app-btn
                    small
                    :disabled="!encoderCalibrationStartDecision.allowed || actionBusy"
                    :title="encoderCalibrationStartDecision.reason"
                    @click="startEncoderCalibration"
                  >
                    开始三段校准
                  </app-btn>
                  <app-btn
                    small
                    :disabled="!encoderCalibrationRecordAllowed || actionBusy"
                    :title="encoderCalibrationRecordReason"
                    @click="recordEncoderCalibrationSegment"
                  >
                    记录第 {{ Math.min(encoderCalibrationEvaluation.completedCount + 1, encoderCalibrationEvaluation.segmentCount) }} 段
                  </app-btn>
                  <app-btn
                    small
                    :disabled="!encoderCalibrationFinishDecision.allowed || !encoderCalibrationLengthValid || !encoderCalibrationEvaluation.canSave || actionBusy"
                    :title="encoderCalibrationEvaluation.canSave ? encoderCalibrationFinishDecision.reason : encoderCalibrationEvaluation.message"
                    @click="finishEncoderCalibration"
                  >
                    完成并保存
                  </app-btn>
                  <app-btn
                    small
                    outlined
                    :disabled="!sharedEncoder.calibrationActive || actionBusy"
                    @click="resetEncoderCalibrationSegments"
                  >
                    重置分段
                  </app-btn>
                  <app-btn
                    small
                    text
                    color="error"
                    :disabled="!encoderCalibrationCancelDecision.allowed || actionBusy"
                    :title="encoderCalibrationCancelDecision.reason"
                    @click="cancelEncoderCalibration"
                  >
                    取消
                  </app-btn>
                </div>
                <p
                  v-if="encoderCalibrationBlockReason"
                  class="acepro-maintenance-note"
                >
                  {{ encoderCalibrationBlockReason }}
                </p>
              </div>

              <div class="acepro-print-monitor">
                <div class="acepro-maintenance-heading">
                  <strong>打印监测</strong>
                  <span :class="`acepro-monitor-state--${printMonitor.tone}`">
                    {{ sharedEncoder.configured ? printMonitor.statusLabel : '未配置' }}
                  </span>
                </div>
                <div class="acepro-monitor-metrics">
                  <div><span>模式</span><strong>{{ printMonitor.modeLabel }}</strong></div>
                  <div><span>检测长度</span><strong>{{ formatMonitorLength(printMonitor.detectionLength) }}</strong></div>
                  <div><span>已挤出未动</span><strong>{{ formatMonitorLength(printMonitor.extrusionSinceMotion) }}</strong></div>
                  <div><span>检测余量</span><strong>{{ formatMonitorLength(printMonitor.headroom) }}</strong></div>
                </div>
                <div
                  v-if="printMonitorIssue"
                  class="acepro-monitor-issue"
                >
                  <strong>{{ printMonitorIssue.message }}</strong>
                  <span v-if="printMonitorIssue.probableCause">可能原因：{{ printMonitorIssue.probableCause }}</span>
                  <span v-if="monitorContextLabel">现场：{{ monitorContextLabel }}</span>
                  <span
                    v-if="printMonitor.pauseRequested"
                    class="acepro-monitor-pause-note"
                  >打印已请求暂停，请排查后再恢复。</span>
                  <div
                    v-if="monitorSensorEntries.length"
                    class="acepro-monitor-sensors"
                  >
                    <span
                      v-for="sensor in monitorSensorEntries"
                      :key="sensor.name"
                      class="acepro-sensor-status"
                      :class="`acepro-sensor-status--${sensor.tone}`"
                    >
                      <i class="acepro-sensor-status__dot" />{{ sensor.label }}
                    </span>
                  </div>
                </div>
                <p
                  v-else
                  class="acepro-maintenance-note"
                >
                  {{ printMonitor.mode === 'monitor' ? '监测模式只提示异常，不会请求暂停打印。' : printMonitor.mode === 'pause' ? '暂停保护检测到故障时会请求暂停打印。' : '打印监测当前关闭。' }}
                </p>
              </div>
            </div>
            <div class="acepro-advanced-actions">
              <app-btn
                small
                text
                :disabled="!recoverDecision.allowed || actionBusy"
                :title="recoverDecision.reason"
                @click="requestRecovery"
              >
                重新连接设备
              </app-btn>
            </div>
            <div
              v-if="selectedDevice.error"
              class="acepro-last-error"
            >
              {{ selectedDevice.error.message }}
            </div>
          </section>
        </div>
      </v-expand-transition>
    </v-card-text>

    <v-card-text v-else>
      <v-alert
        dense
        outlined
        type="info"
      >
        ACE Pro 管理中心未检测到设备。请确认管理中心与 Moonraker 组件均已加载。
      </v-alert>
    </v-card-text>

    <v-dialog
      v-model="confirmDialog"
      max-width="520"
      persistent
    >
      <v-card>
        <v-card-title>{{ confirmation.title }}</v-card-title>
        <v-card-text>
          <p>{{ confirmation.summary }}</p>
          <p class="acepro-confirm-note">
            Moonraker 将再次校验设备能力、打印状态和共享路径锁。
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <app-btn
            text
            :disabled="actionBusy"
            @click="cancelConfirmation"
          >
            取消
          </app-btn>
          <app-btn
            color="primary"
            :loading="actionBusy"
            @click="executeConfirmation"
          >
            确认执行
          </app-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar
      v-model="noticeSnackbar"
      top
      multi-line
      :color="(activeNotice && activeNotice.color) || 'info'"
      :timeout="6500"
      @input="handleNoticeSnackbar"
    >
      <strong>{{ activeNoticeTitle }}</strong>
      <span class="acepro-toolchange-snackbar__message">{{ activeNotice && activeNotice.message }}</span>
      <template #action="{ attrs }">
        <app-btn
          text
          v-bind="attrs"
          @click="noticeSnackbar = false"
        >
          知道了
        </app-btn>
      </template>
    </v-snackbar>
  </collapsable-card>
</template>

<script lang="ts">
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-nocheck -- Fluidd consumes this framework-neutral JavaScript API at runtime.
import Vue from 'vue'
import {
  ACE_ASSIST_ONLY_MESSAGE,
  ACE_ACTIONS,
  ENCODER_CALIBRATION_DEFAULTS,
  AceApiClient,
  buildViewModel,
  canPerformAction,
  collectPrintMonitorEvent,
  evaluateEncoderCalibrationSegments,
  formatApiError,
} from './ace-core.js'
import AceV3SlotCard from './AceV3SlotCard.vue'

function collectToolchangeNotices (notices, cursor, cursorSignature = '') {
  if (!notices.length) return { cursor, cursorSignature, notices: [] }
  const latest = notices[notices.length - 1]
  const latestSignature = JSON.stringify([latest.sequence, latest.code || '', latest.command || '', latest.message || ''])
  const sequenceRestarted = cursor !== null && (
    latest.sequence < cursor ||
    (latest.sequence === cursor && cursorSignature && latestSignature !== cursorSignature)
  )
  const unseen = cursor === null || sequenceRestarted
    ? notices
    : notices.filter(notice => notice.sequence > cursor)
  return {
    cursor: latest.sequence,
    cursorSignature: latestSignature,
    notices: unseen,
  }
}

export default {
  name: 'AceV3Card',
  components: {
    AceV3SlotCard,
  },
  props: {
    showPageLink: { type: Boolean, default: true },
    collapseExtraFunctions: { type: Boolean, default: true },
    narrow: { type: Boolean, default: false },
  },
  data () {
    return {
      ACE_ACTIONS,
      client: null,
      status: null,
      viewModel: null,
      statusStale: false,
      selectedDeviceId: '',
      loading: false,
      actionBusy: false,
      loadIssue: null,
      feedback: null,
      pollTimer: null,
      pollingStopped: false,
      confirmDialog: false,
      extraFunctionsOpen: false,
      confirmation: { title: '', summary: '', action: '', params: {}, deviceId: '' },
      dryerTemperature: 45,
      dryerDuration: 240,
      manualSlot: 0,
      manualLength: 100,
      manualSpeed: 80,
      feedAssistSlot: 0,
      encoderCalibrationLength: ENCODER_CALIBRATION_DEFAULTS.segmentLength,
      encoderCalibrationSegments: [],
      encoderCalibrationLastCounts: null,
      monitorEventCursor: null,
      monitorEventCursorSignature: '',
      noticeCursor: null,
      noticeCursorSignature: '',
      noticeQueue: [],
      activeNotice: null,
      noticeSnackbar: false,
    }
  },
  computed: {
    currentToolTarget () {
      return this.viewModel?.currentToolTarget || null
    },
    currentToolDevice () {
      return this.currentToolTarget
        ? this.viewModel?.devices.find(device => device.id === this.currentToolTarget.deviceId) || null
        : null
    },
    selectedDevice () {
      if (!this.viewModel) return null
      return this.viewModel.devices.find(device => device.id === this.selectedDeviceId) || this.viewModel.devices[0] || null
    },
    selectedCurrentTool () {
      if (!this.selectedDevice || !this.status?.system.currentTool) return '未装载'
      return this.selectedDevice.slots.some(slot => slot.tool === this.status.system.currentTool)
        ? this.status.system.currentTool
        : '未装载'
    },
    fanSpeedLabel () {
      const raw = this.selectedDevice?.raw || {}
      const value = raw.fan_speed ?? raw.fanSpeed ?? raw.fan?.speed
      const number = Number(value)
      return Number.isFinite(number) ? String(Math.round(number)) : '--'
    },
    rfidSummaryLabel () {
      return this.selectedDevice?.rfidSummaryLabel || '未提供'
    },
    upperSensorPolicy () {
      return this.status?.path?.sensorPolicy?.upper || {
        controlEndpoint: false,
        feedTimeout: null,
      }
    },
    upperSensorLabel () {
      return `控制闭环 · ${this.sensorLabel('upper')}`
    },
    upperFeedTimeoutLabel () {
      return this.formatFeedTimeout(this.upperSensorPolicy.feedTimeout)
    },
    lowerSensorPolicy () {
      return this.status?.path?.sensorPolicy?.lower || {
        bypassed: false,
        configured: false,
        controlEnabled: false,
        monitorOnly: false,
        bypassLoadLength: 0,
      }
    },
    lowerSensorLabel () {
      const raw = this.sensorLabel('lower')
      if (this.lowerSensorPolicy.monitorOnly) return `仅监测 · ${raw}`
      return this.lowerSensorPolicy.controlEnabled ? `参与控制 · ${raw}` : `未参与控制 · ${raw}`
    },
    lowerSensorTitle () {
      const raw = this.sensorLabel('lower')
      if (this.lowerSensorPolicy.monitorOnly) {
        return `当前读数：${raw}。该传感器仅用于监测，不参与换料控制。`
      }
      return this.lowerSensorPolicy.controlEnabled
        ? `当前读数：${raw}。该传感器参与换料控制。`
        : `当前读数：${raw}。该传感器未参与换料控制。`
    },
    extruderCalibrationDistanceLabel () {
      return this.formatMonitorLength(this.lowerSensorPolicy.bypassLoadLength)
    },
    hubSensorLabel () {
      return this.sensorLabel('hub')
    },
    rdmSensorLabel () {
      return this.sensorLabel('rdm')
    },
    filamentPathLabel () {
      return this.viewModel?.usesFirstStageHubs
        ? 'ACE -> 一级五通 -> 总五通 -> 打印头'
        : 'ACE -> 总五通 -> 打印头'
    },
    feedControlLabel () {
      return 'ACE 参考送料 -> 上方传感器闭环终止'
    },
    sharedEncoder () {
      return this.viewModel?.sharedEncoder || {
        configured: false,
        summaryLabel: '未配置',
        tone: 'muted',
        resolution: null,
        counts: 0,
        calibrationActive: false,
        printMonitor: {
          mode: 'off',
          modeLabel: '关闭',
          statusLabel: '关闭',
          tone: 'muted',
          detectionLength: null,
          extrusionSinceMotion: null,
          headroom: null,
          lastEvent: null,
          fault: null,
          pauseRequested: false,
        },
        fault: null,
      }
    },
    printMonitor () {
      return this.sharedEncoder.printMonitor
    },
    printMonitorIssue () {
      return this.printMonitor.fault || this.printMonitor.lastEvent || null
    },
    monitorContextLabel () {
      const context = this.printMonitorIssue?.context
      if (!context) return ''
      return [
        context.tool && `工具 ${context.tool}`,
        context.device && `设备 ${context.device}`,
        context.pathState && `路径 ${context.pathState}`,
        context.printState && `打印 ${context.printState}`,
      ].filter(Boolean).join(' · ')
    },
    monitorSensorEntries () {
      const sensors = this.printMonitorIssue?.context?.sensors
      if (!sensors || typeof sensors !== 'object') return []
      return Object.entries(sensors).flatMap(([name, value]) => {
        if (name === 'hubs' && value && typeof value === 'object') {
          return Object.entries(value).map(([device, sensor]) => this.monitorSensorEntry(`${device} 五通`, sensor))
        }
        return [this.monitorSensorEntry(this.monitorSensorName(name), value)]
      })
    },
    sharedEncoderStatusClass () {
      return `acepro-encoder-status--${this.sharedEncoder.tone || 'muted'}`
    },
    encoderMinTrackingRatioLabel () {
      return this.formatTrackingRatio(this.sharedEncoder.minTrackingRatio)
    },
    sharedEncoderTitle () {
      if (this.sharedEncoder.fault?.message) return this.sharedEncoder.fault.message
      if (this.sharedEncoder.state === 'not_armed') return '保护模式尚未启用，当前不会参与送料保护。'
      if (this.sharedEncoder.mode === 'monitor') return '只读监测耗材移动；发现异常时仅提示，不参与控制。'
      if (this.sharedEncoder.mode === 'protect') return '保护模式监测耗材移动；发现异常时参与送料保护。'
      if (Number.isFinite(this.sharedEncoder.resolution)) {
        return `分辨率 ${this.sharedEncoder.resolution.toFixed(4)} mm/脉冲`
      }
      return this.sharedEncoder.summaryLabel
    },
    connectionClass () {
      return !this.statusStale && this.selectedDevice?.connected
        ? 'acepro-card__connection--connected'
        : 'acepro-card__connection--disconnected'
    },
    connectionLabel () {
      return this.statusStale ? '状态已失联' : this.selectedDevice?.connectionLabel || '未连接'
    },
    statusValueClass () {
      const tone = this.selectedDevice?.statusTone
      if (tone === 'ready') return 'acepro-card__value--ready'
      if (tone === 'busy') return 'acepro-card__value--busy'
      if (tone === 'error') return 'acepro-card__value--error'
      return 'acepro-card__value--muted'
    },
    showExtraFunctions () {
      return !this.collapseExtraFunctions || this.extraFunctionsOpen
    },
    matchModeLabel () {
      return this.endlessSpool.matchMode === 'material' ? '同材料匹配' : '完全匹配'
    },
    endlessSpool () {
      return this.viewModel?.endlessSpool || { enabled: false, matchMode: 'exact' }
    },
    toolchangeModeLabel () {
      if (this.status?.toolchangeMode === 'manual') return '手动模式'
      return this.status?.toolchangeReady ? '自动换料已就绪' : '自动换料未就绪'
    },
    toolchangeModeDescription () {
      if (this.status?.toolchangeReady) return '工具指令、卸载和无限续料可用。'
      return this.status?.toolchange?.assistanceMessage || ACE_ASSIST_ONLY_MESSAGE
    },
    toolchangeModeClass () {
      if (this.status?.toolchangeMode === 'manual') return 'acepro-toolchange-mode--manual'
      return this.status?.toolchangeReady ? 'acepro-toolchange-mode--ready' : 'acepro-toolchange-mode--blocked'
    },
    feedAssist () {
      return this.viewModel?.feedAssist || { active: false, deviceId: '', slot: null, tool: '', targetValid: false, label: '未启用' }
    },
    feedAssistEnableDecision () {
      if (!this.selectedDevice) return { allowed: false, reason: '状态尚未加载。' }
      const slot = this.selectedDevice.slots[this.feedAssistSlot]
      return this.actionDecision(ACE_ACTIONS.ENABLE_FEED_ASSIST, this.selectedDevice, slot)
    },
    feedAssistDisableDecision () {
      if (!this.feedAssist.active) return { allowed: false, reason: '当前没有启用 ACE 辅助送料。' }
      if (!this.feedAssist.targetValid) return { allowed: false, reason: '后端未提供当前辅助送料槽位。' }
      const device = this.status?.devices.find(item => item.id === this.feedAssist.deviceId)
      const slot = device?.slots[this.feedAssist.slot]
      return device
        ? this.actionDecision(ACE_ACTIONS.DISABLE_FEED_ASSIST, device, slot)
        : { allowed: false, reason: '当前辅助送料设备未配置。' }
    },
    endlessDecision () {
      return this.status
        ? this.actionDecision(ACE_ACTIONS.SET_ENDLESS_SPOOL, null)
        : { allowed: false, reason: '状态尚未加载。' }
    },
    startDryerDecision () {
      return this.selectedDevice
        ? this.actionDecision(ACE_ACTIONS.START_DRYING, this.selectedDevice)
        : { allowed: false, reason: '状态尚未加载。' }
    },
    stopDryerDecision () {
      return this.selectedDevice
        ? this.actionDecision(ACE_ACTIONS.STOP_DRYING, this.selectedDevice)
        : { allowed: false, reason: '状态尚未加载。' }
    },
    encoderCalibrationStartDecision () {
      return this.actionDecision(ACE_ACTIONS.ENCODER_CALIBRATION_START, null)
    },
    encoderCalibrationFinishDecision () {
      return this.actionDecision(ACE_ACTIONS.ENCODER_CALIBRATION_FINISH, null)
    },
    encoderCalibrationCancelDecision () {
      return this.actionDecision(ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL, null)
    },
    encoderCalibrationLengthValid () {
      const length = Number(this.encoderCalibrationLength)
      return Number.isFinite(length) && length >= 0.01 && length <= 2000
    },
    encoderCalibrationEvaluation () {
      return evaluateEncoderCalibrationSegments(this.encoderCalibrationSegments)
    },
    encoderCalibrationRows () {
      return Array.from({ length: ENCODER_CALIBRATION_DEFAULTS.segmentCount }, (_, index) => {
        const segment = this.encoderCalibrationEvaluation.segments[index]
        if (!segment) {
          return {
            index,
            state: 'pending',
            measurement: `${Number(this.encoderCalibrationLength)} mm`,
            resolution: '等待测量',
            deviation: '--',
          }
        }
        const state = !segment.valid || (this.encoderCalibrationEvaluation.complete && this.encoderCalibrationEvaluation.state === 'rejected')
          ? 'rejected'
          : this.encoderCalibrationEvaluation.complete && this.encoderCalibrationEvaluation.state === 'warning'
            ? 'warning'
            : 'passed'
        return {
          index,
          state,
          measurement: `${segment.length.toFixed(1)} mm · ${segment.pulses} 脉冲`,
          resolution: segment.resolution === null ? '--' : `${segment.resolution.toFixed(4)} mm/脉冲`,
          deviation: segment.deviationPercent === null ? '偏差 --' : `偏差 ${segment.deviationPercent.toFixed(1)}%`,
        }
      })
    },
    encoderCalibrationRecordAllowed () {
      return this.sharedEncoder.calibrationActive && this.encoderCalibrationLastCounts !== null && !this.encoderCalibrationEvaluation.complete
    },
    encoderCalibrationRecordReason () {
      if (!this.sharedEncoder.calibrationActive) return '请先开始校准。'
      if (this.encoderCalibrationLastCounts === null) return '请先重置分段以建立计数基线。'
      if (this.encoderCalibrationEvaluation.complete) return '三段测量已完成。'
      return ''
    },
    encoderCalibrationBlockReason () {
      if (!this.status) return '状态尚未加载。'
      if (!this.sharedEncoder.configured) return '共享编码器未配置。'
      const decision = this.sharedEncoder.calibrationActive
        ? (this.encoderCalibrationEvaluation.canSave ? this.encoderCalibrationFinishDecision : { allowed: false, reason: this.encoderCalibrationEvaluation.message })
        : this.encoderCalibrationStartDecision
      return decision.allowed ? '' : decision.reason
    },
    activeNoticeTitle () {
      if (this.activeNotice?.title) return this.activeNotice.title
      return `${this.activeNotice?.command || '工具指令'} 已忽略`
    },
    recoverDecision () {
      return this.selectedDevice
        ? this.actionDecision(ACE_ACTIONS.RECOVER, this.selectedDevice)
        : { allowed: false, reason: '状态尚未加载。' }
    },
    diagnoseDecision () {
      return this.selectedDevice
        ? this.actionDecision(ACE_ACTIONS.DIAGNOSE, this.selectedDevice, this.selectedDevice.slots[this.manualSlot])
        : { allowed: false, reason: '状态尚未加载。' }
    },
    currentUnload () {
      if (this.statusStale) return { allowed: false, reason: 'ACE 状态已过期，请先恢复连接。' }
      if (!this.status?.system.currentTool || !this.viewModel) return { allowed: false, reason: '当前没有已装载耗材。' }
      const target = this.viewModel.tools.find(tool => tool.tool === this.status.system.currentTool)
      const device = this.status.devices.find(item => item.id === target?.deviceId)
      return canPerformAction(this.status, ACE_ACTIONS.UNLOAD, { device })
    },
    dryerInputValid () {
      return Number.isFinite(Number(this.dryerTemperature)) && Number(this.dryerTemperature) >= 20 &&
        Number(this.dryerTemperature) <= 75 && Number.isInteger(Number(this.dryerDuration)) &&
        Number(this.dryerDuration) >= 10 && Number(this.dryerDuration) <= 1440
    },
    dryerTargetLabel () {
      const value = this.selectedDevice?.dryer.targetTemperature
      return value === null || value === undefined ? '--' : `${Math.round(value)}°C`
    },
    dryerRemainingLabel () {
      const value = this.selectedDevice?.dryer.remainingMinutes
      return value === null || value === undefined ? '--' : `${Math.max(0, Math.round(value))} min`
    },
    manualSlotOptions () {
      return this.selectedDevice
        ? this.selectedDevice.slots.map(slot => ({ text: `${slot.tool} · ${slot.label} · ${slot.materialLabel}`, value: slot.index }))
        : []
    },
    manualInputValid () {
      return Number.isInteger(Number(this.manualSlot)) && Number(this.manualSlot) >= 0 && Number(this.manualSlot) <= 3 &&
        Number.isFinite(Number(this.manualLength)) && Number(this.manualLength) > 0 && Number(this.manualLength) <= 2000 &&
        Number.isFinite(Number(this.manualSpeed)) && Number(this.manualSpeed) > 0 && Number(this.manualSpeed) <= 1000
    },
  },
  mounted () {
    this.client = new AceApiClient({
      client: 'fluidd-card',
      timeoutMs: 8000,
      rpcImpl: (method, params) => {
        if (!Vue.$socket) throw new Error('Fluidd Moonraker 连接尚未建立。')
        return Vue.$socket.emit(method, { params })
      },
    })
    this.refresh().finally(() => this.schedulePoll())
  },
  beforeDestroy () {
    this.pollingStopped = true
    if (this.pollTimer) window.clearTimeout(this.pollTimer)
    this.pollTimer = null
  },
  methods: {
    schedulePoll () {
      if (this.pollingStopped) return
      if (this.pollTimer) window.clearTimeout(this.pollTimer)
      const delay = this.sharedEncoder.calibrationActive ? 1000 : 5000
      this.pollTimer = window.setTimeout(async () => {
        if (this.pollingStopped) return
        if (!document.hidden && !this.confirmDialog) await this.refresh(true)
        this.schedulePoll()
      }, delay)
    },
    actionDecision (action, device, slot = null) {
      if (!this.status) return { allowed: false, reason: '状态尚未加载。' }
      if (this.statusStale) return { allowed: false, reason: 'ACE 状态已过期，请先恢复连接。' }
      return canPerformAction(this.status, action, { device, slot })
    },
    slotDecision (device, slot) {
      return this.actionDecision(slot.active ? ACE_ACTIONS.UNLOAD : ACE_ACTIONS.SELECT_TOOL, device, slot)
    },
    manualDecision (action) {
      if (!this.selectedDevice) return { allowed: false, reason: '状态尚未加载。' }
      return this.actionDecision(action, this.selectedDevice, this.selectedDevice.slots[this.manualSlot])
    },
    stateLabel (state) {
      const labels = { idle: '空闲', ready: '就绪', busy: '忙碌', feeding: '送料中', retracting: '回抽中', drying: '烘干中', error: '故障', offline: '离线' }
      return labels[state] || state || '未知'
    },
    sensorLabel (name) {
      const pathSensors = this.status?.path?.sensors ?? {}
      const raw = this.selectedDevice?.raw || {}
      const sensors = raw.sensors && typeof raw.sensors === 'object' ? raw.sensors : {}
      const camelName = `${name}Sensor`
      const snakeName = `${name}_sensor`
      const sensor = name === 'hub'
        ? this.selectedDevice?.hubSensor
        : pathSensors[name] ?? sensors[name] ?? raw[snakeName] ?? raw[camelName]
      if (sensor === null || sensor === undefined) return '未提供'
      if (typeof sensor === 'boolean') return sensor ? '有料' : '无料'
      if (typeof sensor === 'string') return sensor || '未提供'
      if (typeof sensor !== 'object') return '未提供'
      if (sensor.available === false) return '未提供'
      const detected = sensor.detected ?? sensor.triggered ?? sensor.present
      if (typeof detected === 'boolean') return detected ? '有料' : '无料'
      return sensor.label || sensor.state || '未提供'
    },
    sensorStatusClass (name) {
      if (name === 'lower' && this.lowerSensorPolicy.monitorOnly) {
        return 'acepro-sensor-status--monitor-only'
      }
      const value = String(this.sensorLabel(name) || '').trim().toLowerCase()
      if (['有料', '已触发', '触发', 'detected', 'present', 'true', '1', 'on'].includes(value)) {
        return 'acepro-sensor-status--present'
      }
      if (['无料', '未触发', '空', 'empty', 'absent', 'false', '0', 'off'].includes(value)) {
        return 'acepro-sensor-status--empty'
      }
      return 'acepro-sensor-status--unknown'
    },
    formatMonitorLength (value) {
      if (value === null || value === undefined || value === '') return '--'
      const number = Number(value)
      return Number.isFinite(number) ? `${number.toFixed(1)} mm` : '--'
    },
    formatFeedTimeout (value) {
      if (value === null || value === undefined || value === '') return '--'
      const number = Number(value)
      return Number.isFinite(number) && number >= 0 ? `${number.toFixed(1)} 秒` : '--'
    },
    formatTrackingRatio (value) {
      if (value === null || value === undefined || value === '') return '--'
      const number = Number(value)
      if (!Number.isFinite(number) || number <= 0 || number > 1) return '--'
      return `${(number * 100).toFixed(1).replace(/\.0$/, '')}%`
    },
    monitorSensorName (name) {
      const labels = { upper: '上方', lower: '下方', rdm: '总五通', hub: '一级五通' }
      return labels[name] || name
    },
    monitorSensorEntry (name, value) {
      const detected = value && typeof value === 'object'
        ? value.detected ?? value.triggered ?? value.present
        : value
      const tone = detected === true ? 'present' : detected === false ? 'empty' : 'unknown'
      const state = detected === true ? '有料' : detected === false ? '无料' : '未知'
      return { name, tone, label: `${name}：${state}` }
    },
    selectDevice (deviceId) {
      if (!this.viewModel?.devices.some(device => device.id === deviceId)) return
      this.selectedDeviceId = deviceId
      this.manualSlot = 0
      this.feedAssistSlot = 0
      const device = this.viewModel.devices.find(item => item.id === deviceId)
      this.dryerTemperature = device?.dryer.targetTemperature || 45
      this.dryerDuration = device?.dryer.remainingMinutes || 240
      this.feedback = null
    },
    jumpToCurrentTool () {
      if (!this.currentToolDevice) return
      this.selectDevice(this.currentToolDevice.id)
    },
    ensureSelectedDevice () {
      if (!this.viewModel?.devices.length) {
        this.selectedDeviceId = ''
        return
      }
      if (!this.viewModel.devices.some(device => device.id === this.selectedDeviceId)) {
        this.selectDevice(this.viewModel.devices[0].id)
      }
    },
    observeToolchangeNotices (status) {
      const notices = Array.isArray(status?.toolchangeNotices) ? status.toolchangeNotices : []
      const batch = collectToolchangeNotices(notices, this.noticeCursor, this.noticeCursorSignature)
      this.noticeCursor = batch.cursor
      this.noticeCursorSignature = batch.cursorSignature
      if (!batch.notices.length) return
      this.noticeQueue.push(...batch.notices)
      this.showNextToolchangeNotice()
    },
    observePrintMonitorEvent (status) {
      const monitor = status?.path?.encoders?.shared?.printMonitor
      const batch = collectPrintMonitorEvent(monitor, this.monitorEventCursor, this.monitorEventCursorSignature)
      this.monitorEventCursor = batch.cursor
      this.monitorEventCursorSignature = batch.cursorSignature
      if (!batch.event) return
      const passive = monitor.mode === 'monitor'
      const details = [
        batch.event.message,
        batch.event.probableCause && `可能原因：${batch.event.probableCause}`,
        passive ? '监测模式仅提示，未请求暂停。' : monitor.pauseRequested ? '打印已请求暂停。' : '',
      ].filter(Boolean).join(' ')
      this.noticeQueue.push({
        title: passive ? '打印监测提示' : '打印监测故障',
        message: details,
        color: passive ? 'warning' : 'error',
      })
      this.showNextToolchangeNotice()
    },
    showNextToolchangeNotice () {
      if (this.noticeSnackbar || this.activeNotice || !this.noticeQueue.length) return
      this.activeNotice = this.noticeQueue.shift()
      this.noticeSnackbar = true
    },
    handleNoticeSnackbar (value) {
      if (value) return
      this.activeNotice = null
      this.$nextTick(() => this.showNextToolchangeNotice())
    },
    applyStatus (status) {
      const calibrationWasActive = this.sharedEncoder.calibrationActive
      this.observeToolchangeNotices(status)
      this.observePrintMonitorEvent(status)
      this.status = status
      this.viewModel = buildViewModel(status)
      this.ensureSelectedDevice()
      if (this.pollTimer && calibrationWasActive !== this.sharedEncoder.calibrationActive) this.schedulePoll()
    },
    async refresh (quiet = false) {
      if (!this.client || this.loading) return
      this.loading = true
      try {
        this.applyStatus(await this.client.getStatus())
        this.statusStale = false
        this.loadIssue = null
      } catch (error) {
        const issue = formatApiError(error)
        this.statusStale = Boolean(this.viewModel)
        this.loadIssue = issue
        if (!quiet && this.viewModel) {
          this.feedback = { type: 'error', title: issue.title, message: `${issue.message} ${issue.nextAction}` }
        }
      } finally {
        this.loading = false
      }
    },
    async refreshDevice (device) {
      await this.runImmediate(ACE_ACTIONS.REFRESH, { device_id: device.id }, '耗材数据已刷新')
    },
    openDashboard () {
      if (this.$route?.name === 'acepro') return
      if (this.$router) {
        const navigation = this.$router.push({ name: 'acepro' })
        if (navigation?.catch) navigation.catch(() => {})
        return
      }
      window.location.hash = '#/acepro'
    },
    requestSlotAction (device, slot) {
      const action = slot.active ? ACE_ACTIONS.UNLOAD : ACE_ACTIONS.SELECT_TOOL
      const params = slot.active ? {} : { tool: slot.tool }
      this.queueConfirmation(
        action,
        params,
        device,
        slot.active ? `卸载当前耗材 ${slot.tool}` : `更换耗材至 ${slot.tool} · ${slot.materialLabel}`,
        slot
      )
    },
    requestUnloadCurrent () {
      const target = this.viewModel.tools.find(tool => tool.tool === this.status.system.currentTool)
      const device = this.status.devices.find(item => item.id === target?.deviceId)
      const slot = device?.slots.find(item => item.tool === this.status.system.currentTool)
      this.queueConfirmation(ACE_ACTIONS.UNLOAD, {}, device, `卸载当前耗材 ${this.status.system.currentTool}`, slot)
    },
    toggleEndless () {
      this.queueConfirmation(
        ACE_ACTIONS.SET_ENDLESS_SPOOL,
        { enabled: !this.endlessSpool.enabled, match_mode: this.endlessSpool.matchMode },
        null,
        `${this.endlessSpool.enabled ? '停用' : '启用'}共享打印头无限续料`
      )
    },
    requestStartDryer () {
      if (!this.selectedDevice || !this.dryerInputValid) return
      const params = {
        device_id: this.selectedDevice.id,
        temperature: Number(this.dryerTemperature),
        duration_minutes: Number(this.dryerDuration),
      }
      this.queueConfirmation(
        ACE_ACTIONS.START_DRYING,
        params,
        this.selectedDevice,
        `${this.selectedDevice.name} · ${params.temperature}°C · ${params.duration_minutes} 分钟`
      )
    },
    requestStopDryer () {
      if (!this.selectedDevice) return
      this.queueConfirmation(
        ACE_ACTIONS.STOP_DRYING,
        { device_id: this.selectedDevice.id },
        this.selectedDevice,
        `停止 ${this.selectedDevice.name} 烘干`
      )
    },
    requestManual (action) {
      if (!this.selectedDevice || !this.manualInputValid) return
      const slot = this.selectedDevice.slots[this.manualSlot]
      const actionName = action === ACE_ACTIONS.FEED || action === 'feed' ? ACE_ACTIONS.FEED : ACE_ACTIONS.RETRACT
      this.queueConfirmation(
        actionName,
        {
          device_id: this.selectedDevice.id,
          slot: Number(this.manualSlot),
          length: Number(this.manualLength),
          speed: Number(this.manualSpeed),
        },
        this.selectedDevice,
        `${actionName === ACE_ACTIONS.FEED ? '手动送丝' : '手动回抽'} ${slot.tool} · ${this.manualLength} mm`,
        slot
      )
    },
    requestEnableFeedAssist () {
      if (!this.selectedDevice) return
      const slot = this.selectedDevice.slots[this.feedAssistSlot]
      if (!slot) return
      const verb = this.feedAssist.active ? '切换' : '启用'
      this.queueConfirmation(
        ACE_ACTIONS.ENABLE_FEED_ASSIST,
        { device_id: this.selectedDevice.id, slot: Number(slot.index) },
        this.selectedDevice,
        `${verb} ACE 辅助送料至 ${slot.tool} · ${slot.materialLabel}`,
        slot
      )
    },
    requestDisableFeedAssist () {
      if (!this.feedAssist.active || !this.feedAssist.targetValid) return
      const device = this.status.devices.find(item => item.id === this.feedAssist.deviceId)
      const slot = device?.slots[this.feedAssist.slot]
      if (!device || !slot) return
      this.runImmediate(
        ACE_ACTIONS.DISABLE_FEED_ASSIST,
        { device_id: device.id, slot: Number(slot.index) },
        `${slot.tool} ACE 辅助送料已停用`
      )
    },
    async startEncoderCalibration () {
      if (!this.encoderCalibrationStartDecision.allowed || this.actionBusy) return
      await this.runImmediate(
        ACE_ACTIONS.ENCODER_CALIBRATION_START,
        {},
        '编码器计数已开始，请手动移动耗材'
      )
      if (this.sharedEncoder.calibrationActive) {
        this.encoderCalibrationSegments = []
        this.encoderCalibrationLastCounts = Number(this.sharedEncoder.counts || 0)
      }
    },
    recordEncoderCalibrationSegment () {
      if (!this.encoderCalibrationRecordAllowed || this.actionBusy) return
      const currentCounts = Number(this.sharedEncoder.counts)
      const previousCounts = Number(this.encoderCalibrationLastCounts)
      const pulses = currentCounts - previousCounts
      this.encoderCalibrationSegments.push({
        length: Number(this.encoderCalibrationLength),
        pulses,
      })
      this.encoderCalibrationLastCounts = currentCounts
      this.feedback = pulses >= ENCODER_CALIBRATION_DEFAULTS.minimumPulses
        ? { type: 'success', title: `第 ${this.encoderCalibrationEvaluation.completedCount} 段已记录`, message: `${pulses} 脉冲` }
        : { type: 'error', title: '本段测量已拒绝', message: '未检测到有效脉冲，请检查接线、压紧轮并重置分段。' }
    },
    resetEncoderCalibrationSegments () {
      if (!this.sharedEncoder.calibrationActive || this.actionBusy) return
      this.encoderCalibrationSegments = []
      this.encoderCalibrationLastCounts = Number(this.sharedEncoder.counts || 0)
      this.feedback = { type: 'info', title: '分段结果已重置', message: '请从当前位置开始第 1 段测量。' }
    },
    async finishEncoderCalibration () {
      if (!this.encoderCalibrationFinishDecision.allowed || !this.encoderCalibrationLengthValid || !this.encoderCalibrationEvaluation.canSave || this.actionBusy) return
      await this.runImmediate(
        ACE_ACTIONS.ENCODER_CALIBRATION_FINISH,
        { length: this.encoderCalibrationEvaluation.totalLength },
        `共享编码器校准已保存 · ${this.encoderCalibrationEvaluation.totalLength} mm`
      )
      if (!this.sharedEncoder.calibrationActive) {
        this.encoderCalibrationSegments = []
        this.encoderCalibrationLastCounts = null
      }
    },
    async cancelEncoderCalibration () {
      if (!this.encoderCalibrationCancelDecision.allowed || this.actionBusy) return
      await this.runImmediate(
        ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL,
        {},
        '共享编码器校准已取消'
      )
      if (!this.sharedEncoder.calibrationActive) {
        this.encoderCalibrationSegments = []
        this.encoderCalibrationLastCounts = null
      }
    },
    requestRecovery () {
      if (!this.selectedDevice) return
      this.queueConfirmation(
        ACE_ACTIONS.RECOVER,
        { device_id: this.selectedDevice.id },
        this.selectedDevice,
        `重新连接 ${this.selectedDevice.name}`
      )
    },
    async runDiagnostics () {
      if (!this.selectedDevice) return
      await this.runImmediate(
        ACE_ACTIONS.DIAGNOSE,
        { device_id: this.selectedDevice.id, slot: Number(this.manualSlot) },
        `${this.selectedDevice.name} 诊断已完成`
      )
    },
    async saveInventory () {
      if (!this.client || !this.selectedDevice || this.actionBusy) return
      if (this.statusStale) {
        this.feedback = { type: 'warning', title: '库存无法保存', message: 'ACE 状态已过期，请先恢复连接。' }
        return
      }
      const references = Array.isArray(this.$refs.slotCards)
        ? this.$refs.slotCards
        : [this.$refs.slotCards].filter(Boolean)
      const drafts = references
        .map(component => component.getDraft?.())
        .filter(draft => draft?.dirty && this.selectedDevice.slots.some(slot => slot.tool === draft.slot?.tool))

      if (!drafts.length) {
        this.feedback = { type: 'info', title: '库存无需保存', message: '当前 ACE 没有未保存的槽位修改。' }
        return
      }
      const invalid = drafts.find(draft => !draft.valid)
      if (invalid) {
        this.feedback = { type: 'warning', title: '槽位资料不完整', message: `${invalid.slot.tool} 需要材料、温度和有效颜色。` }
        return
      }
      const blocked = drafts.find(draft => !canPerformAction(
        this.status,
        ACE_ACTIONS.SET_SLOT,
        { device: this.selectedDevice, slot: draft.slot }
      ).allowed)
      if (blocked) {
        const decision = canPerformAction(
          this.status,
          ACE_ACTIONS.SET_SLOT,
          { device: this.selectedDevice, slot: blocked.slot }
        )
        this.feedback = { type: 'warning', title: '库存无法保存', message: decision.reason }
        return
      }

      this.actionBusy = true
      try {
        for (const draft of drafts) {
          await this.client.action(ACE_ACTIONS.SET_SLOT, {
            device_id: this.selectedDevice.id,
            slot: Number(draft.slot.index),
            material: draft.material,
            color: draft.color,
            target_temperature: Number(draft.targetTemperature),
          }, { deviceCount: this.status.devices.length })
        }
        this.feedback = { type: 'success', title: '库存已保存', message: `已保存 ${drafts.length} 个槽位。` }
        this.applyStatus(await this.client.getStatus())
        this.loadIssue = null
      } catch (error) {
        const issue = formatApiError(error)
        this.feedback = { type: 'error', title: issue.title, message: `${issue.message} ${issue.nextAction}` }
      } finally {
        this.actionBusy = false
      }
    },
    queueConfirmation (action, params, device, title, slot = null) {
      const decision = this.actionDecision(action, device, slot)
      if (!decision.allowed) {
        this.feedback = { type: 'warning', title: '操作不可用', message: decision.reason }
        return
      }
      this.confirmation = {
        title,
        summary: `${device?.name || '共享打印头'} · 打印状态 ${this.status.system.printState}`,
        action,
        params,
        deviceId: device?.id || '',
      }
      this.confirmDialog = true
    },
    cancelConfirmation () {
      this.confirmDialog = false
      this.confirmation = { title: '', summary: '', action: '', params: {}, deviceId: '' }
    },
    async executeConfirmation () {
      const request = this.confirmation
      if (!request.action || this.actionBusy) return
      this.actionBusy = true
      try {
        await this.client.action(request.action, request.params, {
          confirm: true,
          deviceCount: this.status.devices.length,
        })
        this.feedback = { type: 'success', title: '操作已提交', message: request.title }
        this.confirmDialog = false
        await this.refresh(true)
      } catch (error) {
        const issue = formatApiError(error)
        this.feedback = { type: 'error', title: issue.title, message: `${issue.message} ${issue.nextAction}` }
      } finally {
        this.actionBusy = false
      }
    },
    async runImmediate (action, params, successMessage) {
      if (!this.client || this.actionBusy) return
      if (this.statusStale && action !== ACE_ACTIONS.REFRESH) {
        this.feedback = { type: 'warning', title: '操作不可用', message: 'ACE 状态已过期，请先恢复连接。' }
        return
      }
      this.actionBusy = true
      try {
        await this.client.action(action, params, { deviceCount: this.status.devices.length })
        this.feedback = { type: 'success', title: successMessage, message: '' }
        this.applyStatus(await this.client.getStatus())
        this.loadIssue = null
      } catch (error) {
        const issue = formatApiError(error)
        this.feedback = { type: 'error', title: issue.title, message: `${issue.message} ${issue.nextAction}` }
      } finally {
        this.actionBusy = false
      }
    },
    async saveSlotInline (device, payload) {
      if (!device || !payload) return
      const slot = payload.slot || device.slots.find(item => item.index === Number(payload.index))
      if (!slot) return
      const decision = canPerformAction(this.status, ACE_ACTIONS.SET_SLOT, { device, slot })
      if (!decision.allowed) {
        this.feedback = { type: 'warning', title: '槽位不可编辑', message: decision.reason }
        return
      }
      await this.runImmediate(ACE_ACTIONS.SET_SLOT, {
        device_id: device.id,
        slot: Number(slot.index),
        material: String(payload.material || '').trim(),
        color: payload.color,
        target_temperature: Number(payload.targetTemperature),
      }, `${slot.tool} 槽位资料已保存`)
    },
    requestClearSlot (device, slot) {
      if (!device || !slot) return
      this.queueConfirmation(
        ACE_ACTIONS.SET_SLOT,
        {
          device_id: device.id,
          slot: Number(slot.index),
          material: 'UNKNOWN',
          color: '#808080',
          target_temperature: 0,
          status: 'empty',
        },
        device,
        `清空 ${slot.tool} 槽位资料`,
        slot
      )
    },
  },
}
</script>

<style lang="scss" scoped>
.acepro-card {
  box-sizing: border-box;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  padding-top: 4px;
}

.acepro-toolbar-menu {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.acepro-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  margin-bottom: 8px;
  border: 1px solid rgba(65, 74, 88, 0.55);
  border-radius: 8px;
  background: linear-gradient(145deg, rgba(23, 28, 36, 0.98), rgba(16, 20, 26, 0.98));
  box-shadow: 0 16px 30px rgba(0, 0, 0, 0.24);
}

.acepro-global-tool {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 6px 9px;
  margin-bottom: 6px;
  color: #dbe3ee;
  border: 1px solid rgba(34, 211, 238, 0.42);
  border-left: 4px solid #22d3ee;
  border-radius: 6px;
  background: rgba(8, 47, 73, 0.34);
}

.acepro-global-tool > div {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.acepro-global-tool span,
.acepro-global-tool small {
  color: rgba(191, 203, 217, 0.86);
  font-size: 10px;
  overflow-wrap: anywhere;
}

.acepro-global-tool strong {
  color: #67e8f9;
  font-size: 15px;
}

.acepro-toolchange-mode {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 7px 10px;
  margin-bottom: 6px;
  color: #dbe3ee;
  border: 1px solid rgba(100, 116, 139, 0.5);
  border-radius: 7px;
  background: rgba(30, 36, 45, 0.9);
  font-size: 11px;
}

.acepro-toolchange-mode > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.acepro-toolchange-mode strong,
.acepro-toolchange-mode span {
  overflow-wrap: anywhere;
}

.acepro-toolchange-mode strong {
  color: #f3f6fb;
  font-size: 12px;
}

.acepro-toolchange-mode--ready {
  border-color: rgba(74, 222, 128, 0.45);
  background: rgba(20, 83, 45, 0.42);
}

.acepro-toolchange-mode--blocked {
  border-color: rgba(245, 158, 11, 0.46);
  background: rgba(120, 53, 15, 0.42);
}

.acepro-toolchange-mode__state {
  flex: 0 0 auto;
  padding: 3px 7px;
  color: #e2e8f0;
  border: 1px solid rgba(148, 163, 184, 0.4);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.52);
  font-weight: 700;
}

.acepro-card__title {
  color: #f5f7fb;
  font-size: 17px;
  font-weight: 800;
}

.acepro-card__subtitle {
  margin-top: 1px;
  color: rgba(185, 195, 207, 0.82);
  font-size: 11px;
}

.acepro-card__connection {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 6px;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.acepro-card__connection--connected {
  color: #dcfce7;
  border: 1px solid rgba(74, 222, 128, 0.58);
  background: rgba(21, 128, 61, 0.82);
}

.acepro-card__connection--connecting {
  color: #fef3c7;
  border: 1px solid rgba(245, 158, 11, 0.4);
  background: rgba(120, 53, 15, 0.7);
}

.acepro-card__connection--disconnected {
  color: #fecaca;
  border: 1px solid rgba(248, 113, 113, 0.4);
  background: rgba(127, 29, 29, 0.68);
}

.acepro-card__dot,
.acepro-device-switch__dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: currentColor;
}

.acepro-device-switch {
  display: grid;
  grid-template-columns: repeat(var(--ace-device-count), minmax(0, 1fr));
  gap: 5px;
  margin-bottom: 6px;
  padding: 6px;
  border: 1px solid rgba(61, 71, 86, 0.5);
  border-radius: 7px;
  background: rgba(15, 20, 27, 0.88);
}

.acepro-device-switch ::v-deep .v-btn {
  min-width: 0;
  padding: 0 8px;
}

.acepro-device-switch__dot {
  flex: 0 0 7px;
  width: 7px;
  height: 7px;
  margin-right: 5px;
  color: #94a3b8;
}

.acepro-device-switch__dot--ready {
  color: #86efac;
}

.acepro-device-switch__dot--busy,
.acepro-device-switch__dot--readonly {
  color: #fbbf24;
}

.acepro-device-switch__dot--error {
  color: #f87171;
}

.acepro-device-switch__tools {
  margin-left: 5px;
  font-size: 9px;
  opacity: 0.72;
}

.acepro-card__top-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.acepro-panel {
  min-width: 0;
  padding: 10px;
  margin-bottom: 8px;
  border: 1px solid rgba(61, 71, 86, 0.45);
  border-radius: 8px;
  background: linear-gradient(180deg, rgba(28, 34, 43, 0.96), rgba(16, 20, 26, 0.98));
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.22);
}

.acepro-panel--slots {
  margin-bottom: 8px;
}

.acepro-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.acepro-panel__title {
  margin-bottom: 6px;
  color: #f3f6fb;
  font-size: 14px;
  font-weight: 800;
}

.acepro-panel__header .acepro-panel__title {
  margin-bottom: 0;
}

.acepro-panel__tool-indicator {
  padding: 3px 8px;
  color: #cffafe;
  border: 1px solid rgba(34, 211, 238, 0.3);
  border-radius: 6px;
  background: rgba(8, 145, 178, 0.18);
  font-size: 11px;
  font-weight: 700;
}

.acepro-panel__tool-indicator--none {
  color: #d0d7e2;
  border-color: rgba(107, 114, 128, 0.35);
  background: rgba(55, 65, 81, 0.46);
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
  min-width: 0;
  min-height: 32px;
  gap: 8px;
  padding: 5px 7px;
  color: rgba(188, 197, 210, 0.82);
  border: 1px solid rgba(56, 66, 79, 0.4);
  border-radius: 6px;
  background: rgba(12, 16, 21, 0.6);
  font-size: 12px;
}

.acepro-info-item--wide {
  grid-column: 1 / -1;
}

.acepro-info-item strong {
  color: #f3f7fc;
  text-align: right;
  overflow-wrap: anywhere;
}

.acepro-info-item .acepro-sensor-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  gap: 5px;
  min-width: 64px;
  min-height: 24px;
  padding: 3px 8px;
  border: 1px solid;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
}

.acepro-sensor-status__dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 999px;
  background: currentColor;
}

.acepro-info-item .acepro-sensor-status--present {
  color: #dcfce7;
  border-color: rgba(74, 222, 128, 0.58);
  background: rgba(21, 128, 61, 0.82);
}

.acepro-info-item .acepro-sensor-status--empty {
  color: #fee2e2;
  border-color: rgba(248, 113, 113, 0.62);
  background: rgba(153, 27, 27, 0.82);
}

.acepro-info-item .acepro-sensor-status--monitor-only {
  color: #e5e7eb;
  border-color: rgba(156, 163, 175, 0.58);
  background: rgba(75, 85, 99, 0.82);
}

.acepro-info-item .acepro-sensor-status--unknown {
  color: #fef3c7;
  border-color: rgba(245, 158, 11, 0.5);
  background: rgba(146, 64, 14, 0.78);
}

.acepro-info-item .acepro-encoder-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  gap: 5px;
  min-width: 76px;
  min-height: 24px;
  max-width: 100%;
  padding: 3px 8px;
  border: 1px solid;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
}

.acepro-encoder-status__dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 999px;
  background: currentColor;
}

.acepro-info-item .acepro-encoder-status--muted {
  color: #d0d7e2;
  border-color: rgba(148, 163, 184, 0.42);
  background: rgba(55, 65, 81, 0.72);
}

.acepro-info-item .acepro-encoder-status--monitor {
  color: #dbeafe;
  border-color: rgba(96, 165, 250, 0.58);
  background: rgba(30, 64, 175, 0.78);
}

.acepro-info-item .acepro-encoder-status--protect {
  color: #dcfce7;
  border-color: rgba(74, 222, 128, 0.58);
  background: rgba(21, 128, 61, 0.82);
}

.acepro-info-item .acepro-encoder-status--warning {
  color: #fef3c7;
  border-color: rgba(245, 158, 11, 0.5);
  background: rgba(146, 64, 14, 0.78);
}

.acepro-info-item .acepro-encoder-status--error {
  color: #fee2e2;
  border-color: rgba(248, 113, 113, 0.62);
  background: rgba(153, 27, 27, 0.82);
}

.acepro-card__value--ready {
  color: #4ade80 !important;
}

.acepro-card__value--busy {
  color: #fbbf24 !important;
}

.acepro-card__value--error {
  color: #f87171 !important;
}

.acepro-card__value--muted {
  color: #d0d7e2 !important;
}

.acepro-dryer__row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.acepro-dryer__field,
.acepro-device-slot-view {
  min-width: 0;
}

.acepro-dryer__field label {
  display: block;
  margin-bottom: 3px;
  color: #dbe3ee;
  font-size: 12px;
  font-weight: 700;
}

.acepro-dryer__status {
  display: grid;
  gap: 5px;
  margin-top: 6px;
}

.acepro-dryer__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.acepro-slot-grid {
  margin: -4px;
}

.acepro-slot-grid__col {
  min-width: 0;
  padding: 4px;
}

.acepro-manual-controls {
  display: grid;
  grid-template-columns: minmax(100px, 0.7fr) repeat(2, minmax(120px, 1fr)) auto auto;
  align-items: center;
  gap: 6px;
}

.acepro-feed-assist__controls {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto auto;
  align-items: center;
  gap: 6px;
}

.acepro-feed-assist__controls ::v-deep .v-input__slot {
  min-height: 32px !important;
}

.acepro-feed-assist__status {
  min-width: 0;
  padding: 3px 7px;
  color: #cbd5e1;
  border: 1px solid rgba(100, 116, 139, 0.42);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.5);
  font-size: 10px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.acepro-feed-assist__status--active {
  color: #dcfce7;
  border-color: rgba(74, 222, 128, 0.5);
  background: rgba(21, 128, 61, 0.7);
}

.acepro-toolchange-snackbar__message {
  display: block;
  margin-top: 3px;
  overflow-wrap: anywhere;
}

.acepro-manual-controls ::v-deep .v-input__slot {
  min-height: 32px !important;
}

.acepro-quick-actions,
.acepro-advanced-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.acepro-maintenance-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  min-width: 0;
  margin-bottom: 7px;
  border-top: 1px solid rgba(61, 71, 86, 0.45);
  border-bottom: 1px solid rgba(61, 71, 86, 0.45);
}

.acepro-encoder-calibration,
.acepro-print-monitor {
  min-width: 0;
  padding: 9px 8px;
}

.acepro-print-monitor {
  border-left: 1px solid rgba(61, 71, 86, 0.45);
}

.acepro-maintenance-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  margin-bottom: 6px;
  color: #f3f6fb;
  font-size: 12px;
}

.acepro-maintenance-heading > span {
  flex: 0 0 auto;
  padding: 2px 6px;
  color: #cbd5e1;
  border: 1px solid rgba(148, 163, 184, 0.38);
  border-radius: 999px;
  background: rgba(55, 65, 81, 0.62);
  font-size: 10px;
  font-weight: 700;
}

.acepro-maintenance-heading > span.is-active,
.acepro-maintenance-heading > span.acepro-monitor-state--active {
  color: #dcfce7;
  border-color: rgba(74, 222, 128, 0.5);
  background: rgba(21, 128, 61, 0.72);
}

.acepro-maintenance-heading > span.acepro-monitor-state--monitor {
  color: #dbeafe;
  border-color: rgba(96, 165, 250, 0.58);
  background: rgba(30, 64, 175, 0.72);
}

.acepro-maintenance-heading > span.acepro-monitor-state--protect {
  color: #dcfce7;
  border-color: rgba(74, 222, 128, 0.5);
  background: rgba(21, 128, 61, 0.72);
}

.acepro-maintenance-heading > span.acepro-monitor-state--error {
  color: #fee2e2;
  border-color: rgba(248, 113, 113, 0.62);
  background: rgba(153, 27, 27, 0.82);
}

.acepro-encoder-calibration > p,
.acepro-maintenance-note {
  margin: 0 0 6px;
  color: rgba(188, 197, 210, 0.84);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.acepro-calibration-readout {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  padding: 5px 7px;
  color: rgba(188, 197, 210, 0.82);
  border-left: 3px solid #22d3ee;
  background: rgba(8, 145, 178, 0.1);
  font-size: 11px;
}

.acepro-calibration-readout strong {
  color: #cffafe;
  font-size: 18px;
  overflow-wrap: anywhere;
}

.acepro-calibration-summary {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 6px;
  padding: 5px 7px;
  border-left: 3px solid #64748b;
  background: rgba(51, 65, 85, 0.32);
  font-size: 10px;
}

.acepro-calibration-summary span { color: rgba(205, 214, 226, 0.86); overflow-wrap: anywhere; }
.acepro-calibration-summary--passed { border-left-color: #4ade80; background: rgba(20, 83, 45, 0.32); }
.acepro-calibration-summary--warning { border-left-color: #fbbf24; background: rgba(120, 53, 15, 0.32); }
.acepro-calibration-summary--rejected { border-left-color: #f87171; background: rgba(127, 29, 29, 0.32); }

.acepro-calibration-segments { display: grid; gap: 4px; margin-bottom: 6px; }
.acepro-calibration-segment {
  display: grid;
  grid-template-columns: 58px repeat(3, minmax(0, 1fr));
  gap: 5px;
  min-width: 0;
  padding: 4px 6px;
  border: 1px solid rgba(71, 85, 105, 0.55);
  border-left: 3px solid #64748b;
  border-radius: 4px;
  background: rgba(12, 16, 21, 0.56);
  font-size: 9px;
}
.acepro-calibration-segment span { color: rgba(188, 197, 210, 0.82); overflow-wrap: anywhere; }
.acepro-calibration-segment--passed { border-left-color: #4ade80; }
.acepro-calibration-segment--warning { border-left-color: #fbbf24; }
.acepro-calibration-segment--rejected { border-left-color: #f87171; }

.acepro-calibration-controls {
  display: grid;
  grid-template-columns: minmax(130px, 1fr) repeat(5, auto);
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.acepro-calibration-controls ::v-deep .v-input__slot {
  min-height: 32px !important;
}

.acepro-monitor-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
}

.acepro-monitor-metrics > div {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  padding: 4px 6px;
  color: rgba(188, 197, 210, 0.82);
  background: rgba(12, 16, 21, 0.56);
  font-size: 10px;
}

.acepro-monitor-metrics strong {
  color: #f3f7fc;
  text-align: right;
  overflow-wrap: anywhere;
}

.acepro-monitor-issue {
  display: grid;
  gap: 3px;
  margin-top: 6px;
  padding: 6px 7px;
  color: #fecaca;
  border-left: 3px solid #f87171;
  background: rgba(127, 29, 29, 0.24);
  font-size: 10px;
  overflow-wrap: anywhere;
}

.acepro-monitor-issue > span {
  color: #e2e8f0;
}

.acepro-monitor-issue .acepro-monitor-pause-note {
  color: #fecaca;
  font-weight: 700;
}

.acepro-monitor-sensors {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 3px;
}

.acepro-monitor-sensors .acepro-sensor-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 3px 6px;
  border: 1px solid;
  border-radius: 999px;
  overflow-wrap: anywhere;
}

.acepro-monitor-sensors .acepro-sensor-status--present {
  color: #dcfce7;
  border-color: rgba(74, 222, 128, 0.58);
  background: rgba(21, 128, 61, 0.82);
}

.acepro-monitor-sensors .acepro-sensor-status--empty {
  color: #fee2e2;
  border-color: rgba(248, 113, 113, 0.62);
  background: rgba(153, 27, 27, 0.82);
}

.acepro-monitor-sensors .acepro-sensor-status--unknown {
  color: #fef3c7;
  border-color: rgba(245, 158, 11, 0.5);
  background: rgba(146, 64, 14, 0.78);
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
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 6px;
  min-height: 30px;
  margin-left: auto;
  padding: 2px 6px;
  border: 1px solid rgba(56, 66, 79, 0.4);
  border-radius: 6px;
  background: rgba(12, 16, 21, 0.56);
  font-size: 11px;
}

.acepro-quick-actions__switch ::v-deep .v-input--selection-controls {
  flex: 0 0 auto;
  margin: 0;
  padding: 0;
}

.acepro-quick-actions__switch ::v-deep .v-input__slot {
  margin: 0;
}

.acepro-more-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  min-height: 36px;
  padding: 7px 10px;
  color: #f3f6fb;
  border: 1px solid rgba(61, 71, 86, 0.55);
  border-radius: 8px;
  background: rgba(24, 30, 39, 0.96);
  font: inherit;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.acepro-more-toggle:hover {
  border-color: rgba(34, 211, 238, 0.42);
  background: rgba(29, 37, 48, 0.98);
}

.acepro-more-toggle:focus-visible {
  outline: 2px solid #22d3ee;
  outline-offset: 2px;
}

.acepro-extra-functions {
  margin-top: 6px;
}

.acepro-card__notice {
  margin: 0 0 8px;
  font-size: 11px;
}

.acepro-last-error {
  margin-top: 6px;
  color: #fca5a5;
  font-size: 11px;
  overflow-wrap: anywhere;
}

.acepro-confirm-note {
  color: var(--v-secondary-base);
  font-size: 12px;
}

@media (min-width: 961px) {
  .acepro-card__header {
    padding: 6px 10px;
    margin-bottom: 6px;
  }

  .acepro-card__title {
    font-size: 15px;
  }

  .acepro-card__subtitle,
  .acepro-card__connection {
    font-size: 10px;
  }

  .acepro-card__connection {
    padding: 3px 7px;
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

  .acepro-panel__header,
  .acepro-panel__title {
    margin-bottom: 4px;
  }

  .acepro-panel__title {
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

  .acepro-dryer__status {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .acepro-info-item {
    min-height: 26px;
    padding: 3px 5px;
    font-size: 10px;
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

  .acepro-dryer__actions ::v-deep .v-btn,
  .acepro-quick-actions ::v-deep .v-btn,
  .acepro-manual-controls ::v-deep .v-btn,
  .acepro-feed-assist__controls ::v-deep .v-btn,
  .acepro-calibration-controls ::v-deep .v-btn,
  .acepro-advanced-actions ::v-deep .v-btn {
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
}

@media (max-width: 960px) {
  .acepro-card__top-grid {
    grid-template-columns: 1fr;
  }

  .acepro-device-switch {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .acepro-manual-controls {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .acepro-feed-assist__controls {
    grid-template-columns: minmax(160px, 1fr) repeat(2, auto);
  }

  .acepro-maintenance-grid {
    grid-template-columns: 1fr;
  }

  .acepro-print-monitor {
    border-top: 1px solid rgba(61, 71, 86, 0.45);
    border-left: 0;
  }

  .acepro-panel--quick {
    align-items: flex-start;
    flex-direction: column;
  }

  .acepro-panel--quick .acepro-panel__title {
    margin-bottom: 4px;
  }

  .acepro-quick-actions {
    width: 100%;
  }
}

@media (max-width: 600px) {
  .acepro-card__header,
  .acepro-panel__header,
  .acepro-toolchange-mode,
  .acepro-global-tool {
    align-items: flex-start;
    flex-direction: column;
  }

  .acepro-info-grid,
  .acepro-dryer__row,
  .acepro-manual-controls,
  .acepro-feed-assist__controls {
    grid-template-columns: 1fr;
  }

  .acepro-calibration-controls,
  .acepro-monitor-metrics {
    grid-template-columns: 1fr;
  }

  .acepro-calibration-segment {
    grid-template-columns: 1fr 1fr;
  }

  .acepro-calibration-controls ::v-deep .v-btn {
    width: 100%;
  }

  .acepro-toolchange-mode__state,
  .acepro-feed-assist__status {
    width: 100%;
  }

  .acepro-quick-actions__switch {
    justify-content: space-between;
    width: 100%;
    margin-left: 0;
  }
}

@media (max-width: 430px) {
  .acepro-device-switch {
    grid-template-columns: 1fr;
  }

  .acepro-toolbar-menu ::v-deep .v-btn {
    min-width: 0;
    padding: 0 5px;
    font-size: 10px;
  }
}

@media (max-width: 380px) {
  .acepro-device-switch {
    grid-template-columns: 1fr;
  }
}

.acepro-card--narrow .acepro-card__header,
.acepro-card--narrow .acepro-panel__header,
.acepro-card--narrow .acepro-toolchange-mode,
.acepro-card--narrow .acepro-global-tool {
  align-items: flex-start;
  flex-direction: column;
}

.acepro-card--narrow .acepro-calibration-segment {
  grid-template-columns: 1fr 1fr;
}

.acepro-card--narrow .acepro-card__top-grid,
.acepro-card--narrow .acepro-device-switch,
.acepro-card--narrow .acepro-dryer__row,
.acepro-card--narrow .acepro-dryer__status,
.acepro-card--narrow .acepro-manual-controls,
.acepro-card--narrow .acepro-feed-assist__controls {
  grid-template-columns: 1fr;
}

.acepro-card--narrow .acepro-maintenance-grid,
.acepro-card--narrow .acepro-calibration-controls,
.acepro-card--narrow .acepro-monitor-metrics {
  grid-template-columns: 1fr;
}

.acepro-card--narrow .acepro-print-monitor {
  border-top: 1px solid rgba(61, 71, 86, 0.45);
  border-left: 0;
}

.acepro-card--narrow .acepro-calibration-controls ::v-deep .v-btn {
  width: 100%;
}

.acepro-card--narrow .acepro-toolchange-mode__state,
.acepro-card--narrow .acepro-feed-assist__status {
  width: 100%;
}

.acepro-card--narrow .acepro-slot-grid__col {
  flex: 0 0 100%;
  max-width: 100%;
}

.acepro-card--narrow .acepro-panel--quick {
  align-items: flex-start;
  flex-direction: column;
}

.acepro-card--narrow .acepro-quick-actions {
  width: 100%;
}

.acepro-card--narrow .acepro-quick-actions__switch {
  justify-content: space-between;
  width: 100%;
  margin-left: 0;
}

.acepro-card--narrow ::v-deep .acepro-slot-card {
  padding: 8px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__header {
  align-items: flex-start;
  margin-bottom: 6px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__tool {
  font-size: 15px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__slot-label,
.acepro-card--narrow ::v-deep .acepro-slot-card__meta-row {
  font-size: 11px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__badge {
  padding: 2px 6px;
  font-size: 10px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__spool {
  margin-bottom: 6px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__spool-svg {
  height: 68px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__meta {
  gap: 5px;
  margin-bottom: 6px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__meta-row {
  min-height: 0;
  padding: 4px 6px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__editor {
  margin-bottom: 5px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__editor .v-input__slot {
  min-height: 34px !important;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__editor .v-label,
.acepro-card--narrow ::v-deep .acepro-slot-card__editor input {
  font-size: 12px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__color-row {
  gap: 5px;
  margin-top: 5px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__picker {
  width: 30px;
  height: 30px;
}

.acepro-card--narrow ::v-deep .acepro-slot-card__actions .v-btn {
  min-height: 30px;
  padding: 0 5px;
  font-size: 11px;
}
</style>
