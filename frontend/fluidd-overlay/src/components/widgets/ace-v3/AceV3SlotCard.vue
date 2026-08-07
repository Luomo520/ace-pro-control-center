<template>
  <div
    class="acepro-slot-card"
    :class="slotClasses"
  >
    <div class="acepro-slot-card__header">
      <div class="acepro-slot-card__tool">
        {{ slot.tool || '--' }}
        <span class="acepro-slot-card__slot-label">
          {{ slot.label || '料槽' }} · {{ displayMaterial }}
        </span>
      </div>

      <div class="acepro-slot-card__badges">
        <span
          v-if="slot.active"
          class="acepro-slot-card__badge acepro-slot-card__badge--loaded"
        >
          已装载
        </span>
        <span
          class="acepro-slot-card__badge"
          :class="statusBadgeClass"
        >
          {{ statusText }}
        </span>
      </div>
    </div>

    <div class="acepro-slot-card__spool">
      <div class="acepro-slot-card__spool-visual">
        <svg
          viewBox="0 0 200 140"
          class="acepro-slot-card__spool-svg"
          aria-hidden="true"
        >
          <ellipse
            cx="60"
            cy="70"
            rx="36"
            ry="64"
            class="acepro-slot-card__spool-flange-back"
          />
          <rect
            x="58"
            y="18"
            width="90"
            height="104"
            rx="40"
            ry="40"
            :fill="colorHex"
            class="acepro-slot-card__spool-body"
          />
          <ellipse
            cx="142"
            cy="70"
            rx="36"
            ry="64"
            class="acepro-slot-card__spool-flange-front"
          />
          <ellipse
            cx="142"
            cy="70"
            rx="10"
            ry="20"
            class="acepro-slot-card__spool-hole"
          />
        </svg>
      </div>
    </div>

    <div class="acepro-slot-card__meta">
      <div class="acepro-slot-card__meta-row">
        <span>RFID</span>
        <strong>{{ rfidText }}</strong>
      </div>
      <div class="acepro-slot-card__meta-row">
        <span>SKU</span>
        <strong>{{ skuText }}</strong>
      </div>
    </div>

    <div class="acepro-slot-card__editor">
      <v-row dense>
        <v-col cols="7">
          <v-combobox
            v-model="localMaterial"
            :items="materialTypes"
            dense
            outlined
            hide-details
            label="材料"
            :disabled="busy || !settingsDecision.allowed"
            :title="settingsDecision.reason"
            @input="markDirty"
          />
        </v-col>
        <v-col cols="5">
          <v-text-field
            v-model.number="localTemperature"
            dense
            outlined
            hide-details
            type="number"
            min="0"
            label="温度"
            suffix="°C"
            :disabled="busy || !settingsDecision.allowed"
            :title="settingsDecision.reason"
            @input="markDirty"
          />
        </v-col>
      </v-row>

      <div class="acepro-slot-card__color-row">
        <input
          v-model="localColor"
          class="acepro-slot-card__picker"
          type="color"
          aria-label="耗材颜色"
          :disabled="busy || !settingsDecision.allowed"
          @input="markDirty"
        >
        <v-text-field
          v-model="localColor"
          dense
          outlined
          hide-details
          class="acepro-slot-card__color-field"
          label="颜色"
          :disabled="busy || !settingsDecision.allowed"
          :title="settingsDecision.reason"
          @input="markDirty"
        />
      </div>
    </div>

    <div class="acepro-slot-card__actions">
      <app-btn
        small
        :disabled="busy || !primaryDecision.allowed"
        :loading="busy"
        :title="primaryDecision.reason"
        @click="$emit('primary', slot)"
      >
        {{ slot.active ? '卸载' : '更换耗材' }}
      </app-btn>
      <app-btn
        small
        :disabled="busy || !settingsDecision.allowed || !canSave"
        :loading="busy"
        :title="settingsDecision.reason"
        @click="emitSave"
      >
        保存
      </app-btn>
      <app-btn
        small
        text
        color="error"
        :disabled="busy || !settingsDecision.allowed"
        :loading="busy"
        :title="settingsDecision.reason"
        @click="emitClear"
      >
        清空
      </app-btn>
    </div>

    <div class="acepro-slot-card__secondary-actions">
      <app-btn
        small
        text
        disabled
        title="当前版本不开放独立助推控制"
      >
        开启助推
      </app-btn>
      <app-btn
        small
        text
        disabled
        title="请先清空并重新配置槽位资料"
      >
        换卷
      </app-btn>
    </div>
  </div>
</template>

<script lang="ts">
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-nocheck -- Fluidd consumes V3 slot view models at runtime.
export default {
  name: 'AceV3SlotCard',
  props: {
    // `slot` is the established V2/V3 card contract despite Vue's reserved attribute name.
    // eslint-disable-next-line vue/no-reserved-props
    slot: { type: Object, required: true },
    materialTypes: { type: Array, default: () => [] },
    busy: { type: Boolean, default: false },
    primaryDecision: {
      type: Object,
      default: () => ({ allowed: false, reason: '状态尚未加载。' }),
    },
    settingsDecision: {
      type: Object,
      default: () => ({ allowed: false, reason: '状态尚未加载。' }),
    },
  },
  data () {
    return {
      localMaterial: '',
      localTemperature: 0,
      localColor: '#000000',
      isDirty: false,
    }
  },
  computed: {
    displayMaterial () {
      return this.slot.empty ? '未配置' : (this.slotMaterial || '未配置')
    },
    slotMaterial () {
      const material = String(this.slot.materialLabel || '').trim()
      return ['未设置', '未配置', '--'].includes(material) ? '' : material
    },
    slotTemperature () {
      const temperature = Number(this.slot.targetTemperature)
      return Number.isFinite(temperature) && temperature > 0 ? temperature : 0
    },
    slotColorHex () {
      return this.normalizeColor(this.slot.color)
    },
    colorHex () {
      return this.normalizeColor(this.localColor)
    },
    canSave () {
      return this.localMaterial.trim().length > 0 &&
        Number(this.localTemperature) > 0 &&
        /^#[0-9a-f]{6}$/i.test(this.localColor)
    },
    localValuesMatchSlot () {
      return this.localMaterial.trim().toUpperCase() === this.slotMaterial.toUpperCase() &&
        Number(this.localTemperature) === this.slotTemperature &&
        this.normalizeColor(this.localColor) === this.slotColorHex
    },
    statusText () {
      if (this.slot.empty) return '空槽'
      if (!this.slot.available) return '不可用'

      const labels = {
        idle: '空闲',
        ready: '就绪',
        busy: '忙碌',
        feeding: '送料中',
        retracting: '回抽中',
        drying: '烘干中',
        error: '故障',
        offline: '离线',
      }
      return labels[this.slot.state] || this.slot.state || '未知'
    },
    rfidText () {
      return this.slot.rfidLabel || '未提供'
    },
    skuText () {
      if (this.slot.spoolId) return String(this.slot.spoolId)
      if (typeof this.slot.rfid === 'string' && this.slot.rfid.trim() && !/^[0-3]$/.test(this.slot.rfid.trim())) {
        return this.slot.rfid.trim()
      }
      return '--'
    },
    statusBadgeClass () {
      if (this.slot.state === 'error') return 'acepro-slot-card__badge--error'
      if (['busy', 'feeding', 'retracting', 'drying'].includes(this.slot.state)) {
        return 'acepro-slot-card__badge--busy'
      }
      if (this.slot.available && !this.slot.empty) return 'acepro-slot-card__badge--ready'
      return 'acepro-slot-card__badge--empty'
    },
    slotClasses () {
      return {
        'acepro-slot-card--ready': this.slot.available && !this.slot.empty,
        'acepro-slot-card--active': this.slot.active,
        'acepro-slot-card--empty': this.slot.empty,
        'acepro-slot-card--unavailable': !this.slot.available,
      }
    },
  },
  watch: {
    slot: {
      immediate: true,
      deep: true,
      handler () {
        if (this.isDirty && !this.localValuesMatchSlot) return
        this.isDirty = false
        this.syncFromSlot()
      },
    },
  },
  methods: {
    normalizeColor (value) {
      const color = String(value || '').trim()
      return /^#[0-9a-f]{6}$/i.test(color) ? color.toUpperCase() : '#000000'
    },
    markDirty () {
      this.isDirty = true
    },
    getDraft () {
      return {
        slot: this.slot,
        material: this.localMaterial.trim(),
        color: this.normalizeColor(this.localColor),
        targetTemperature: Number(this.localTemperature),
        dirty: this.isDirty,
        valid: this.canSave,
      }
    },
    emitSave () {
      if (!this.canSave || !this.settingsDecision.allowed || this.busy) return

      this.$emit('save', {
        slot: this.slot,
        material: this.localMaterial.trim(),
        color: this.normalizeColor(this.localColor),
        targetTemperature: Number(this.localTemperature),
      })
    },
    emitClear () {
      if (!this.settingsDecision.allowed || this.busy) return
      this.isDirty = false
      this.$emit('clear', this.slot)
    },
    syncFromSlot () {
      this.localMaterial = this.slotMaterial
      this.localTemperature = this.slotTemperature
      this.localColor = this.slotColorHex
    },
  },
}
</script>

<style scoped>
.acepro-slot-card {
  box-sizing: border-box;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  padding: 8px;
  border: 1px solid rgba(90, 106, 128, 0.4);
  border-radius: 8px;
  background: #1a1f26;
  box-shadow: 0 10px 18px rgba(0, 0, 0, 0.28);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.acepro-slot-card:hover {
  transform: translateY(-1px);
}

.acepro-slot-card--ready {
  border-color: rgba(16, 185, 129, 0.55);
}

.acepro-slot-card--empty {
  opacity: 0.86;
}

.acepro-slot-card--unavailable {
  opacity: 0.72;
}

.acepro-slot-card--active {
  border-color: #22d3ee;
  box-shadow:
    0 0 0 3px rgba(34, 211, 238, 0.2),
    0 0 18px rgba(34, 211, 238, 0.18),
    0 10px 18px rgba(0, 0, 0, 0.28);
}

.acepro-slot-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 6px;
}

.acepro-slot-card__tool {
  min-width: 0;
  font-size: 15px;
  font-weight: 800;
  color: #eef2f7;
}

.acepro-slot-card__slot-label {
  margin-left: 4px;
  font-size: 11px;
  font-weight: 600;
  color: rgba(183, 194, 208, 0.8);
  overflow-wrap: anywhere;
}

.acepro-slot-card__badges {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 3px;
}

.acepro-slot-card__badge {
  padding: 2px 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0;
}

.acepro-slot-card__badge--loaded {
  color: #cffafe;
  background: rgba(12, 74, 110, 0.7);
  border: 1px solid rgba(34, 211, 238, 0.42);
}

.acepro-slot-card__badge--ready {
  color: #d1fae5;
  background: rgba(20, 83, 45, 0.72);
}

.acepro-slot-card__badge--busy {
  color: #fef3c7;
  background: rgba(120, 53, 15, 0.75);
}

.acepro-slot-card__badge--empty {
  color: #d4d9e1;
  background: rgba(55, 65, 81, 0.75);
}

.acepro-slot-card__badge--error {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.75);
}

.acepro-slot-card__spool {
  margin-bottom: 6px;
}

.acepro-slot-card__spool-visual {
  border-radius: 7px;
  border: 1px solid #2c323c;
  background: linear-gradient(180deg, #10141a, #0b0f14);
  overflow: hidden;
}

.acepro-slot-card__spool-svg {
  display: block;
  width: 100%;
  height: 68px;
}

.acepro-slot-card__spool-flange-back {
  fill: #a8845e;
  stroke: #6d563d;
  stroke-width: 1.5;
  filter: drop-shadow(-1px 2px 4px rgba(0, 0, 0, 0.35));
}

.acepro-slot-card__spool-flange-front {
  fill: #b4926c;
  stroke: #7a6142;
  stroke-width: 1.5;
  filter: drop-shadow(1px 3px 6px rgba(0, 0, 0, 0.35));
}

.acepro-slot-card__spool-body {
  stroke: #11161c;
  stroke-width: 1.5;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.25));
}

.acepro-slot-card__spool-hole {
  fill: #0b0d11;
  stroke: #1f242c;
  stroke-width: 2;
}

.acepro-slot-card__meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
  margin-bottom: 6px;
}

.acepro-slot-card__meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 5px;
  min-width: 0;
  padding: 4px 6px;
  border-radius: 5px;
  background: rgba(12, 16, 21, 0.5);
  font-size: 11px;
  color: rgba(194, 203, 214, 0.86);
  border: 1px solid rgba(77, 86, 97, 0.22);
}

.acepro-slot-card__meta-row strong {
  min-width: 0;
  color: #eef2f7;
  overflow-wrap: anywhere;
  text-align: right;
}

.acepro-slot-card__editor {
  margin-bottom: 5px;
}

.acepro-slot-card__editor ::v-deep .v-input__slot {
  min-height: 34px !important;
}

.acepro-slot-card__editor ::v-deep .v-label,
.acepro-slot-card__editor ::v-deep input {
  font-size: 12px;
}

.acepro-slot-card__color-row {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 5px;
}

.acepro-slot-card__picker {
  width: 30px;
  height: 30px;
  border: none;
  padding: 0;
  border-radius: 6px;
  background: transparent;
}

.acepro-slot-card__color-field {
  flex: 1;
  min-width: 0;
}

.acepro-slot-card__actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
}

.acepro-slot-card__actions ::v-deep .v-btn {
  min-height: 30px;
  min-width: 0;
  padding: 0 5px;
  font-size: 11px;
}

.acepro-slot-card__secondary-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  margin-top: 3px;
}

.acepro-slot-card__secondary-actions ::v-deep .v-btn {
  min-height: 25px;
  min-width: 0;
  padding: 0 5px;
  font-size: 10px;
}

@media (max-width: 600px) {
  .acepro-slot-card__spool-svg {
    height: 82px;
  }

  .acepro-slot-card__actions ::v-deep .v-btn {
    min-height: 36px;
  }

  .acepro-slot-card__secondary-actions ::v-deep .v-btn {
    min-height: 25px;
    padding: 0 5px;
    font-size: 9px;
  }
}

@media (min-width: 961px) {
  .acepro-slot-card {
    padding: 6px;
  }

  .acepro-slot-card__header {
    align-items: center;
    margin-bottom: 4px;
  }

  .acepro-slot-card__tool {
    font-size: 13px;
  }

  .acepro-slot-card__slot-label,
  .acepro-slot-card__meta-row,
  .acepro-slot-card__editor ::v-deep .v-label,
  .acepro-slot-card__editor ::v-deep input {
    font-size: 10px;
  }

  .acepro-slot-card__badge {
    padding: 1px 5px;
    font-size: 9px;
  }

  .acepro-slot-card__spool {
    margin-bottom: 4px;
  }

  .acepro-slot-card__spool-svg {
    height: 48px;
  }

  .acepro-slot-card__meta {
    gap: 3px;
    margin-bottom: 4px;
  }

  .acepro-slot-card__meta-row {
    min-height: 24px;
    padding: 2px 4px;
  }

  .acepro-slot-card__editor {
    margin-bottom: 3px;
  }

  .acepro-slot-card__editor ::v-deep .v-input__slot {
    min-height: 30px !important;
  }

  .acepro-slot-card__color-row {
    gap: 4px;
    margin-top: 3px;
  }

  .acepro-slot-card__picker {
    width: 26px;
    height: 26px;
  }

  .acepro-slot-card__actions ::v-deep .v-btn {
    min-height: 28px;
    padding: 0 6px;
    font-size: 10px;
  }
}
</style>
