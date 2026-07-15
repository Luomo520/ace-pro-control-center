<template>
  <div
    class="acepro-slot-card"
    :class="slotClasses"
  >
    <div class="acepro-slot-card__header">
      <div>
        <div class="acepro-slot-card__tool">
          T{{ slot.index }}
          <span class="acepro-slot-card__slot-label">
            料槽{{ slot.index + 1 }} · {{ displayMaterial }}
          </span>
        </div>
      </div>

      <div class="acepro-slot-card__badges">
        <span
          v-if="active"
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
        <span>硬件状态</span>
        <strong>{{ hardwareText }}</strong>
      </div>
      <div class="acepro-slot-card__meta-row">
        <span>SKU</span>
        <strong>{{ slot.sku || '--' }}</strong>
      </div>
    </div>

    <div class="acepro-slot-card__editor">
      <v-row dense>
        <v-col cols="7">
          <v-combobox
            v-model="localMaterial"
            :items="materialOptions"
            dense
            outlined
            hide-details
            label="材料"
            :disabled="disabled"
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
            suffix="C"
            :disabled="disabled"
            @input="markDirty"
          />
        </v-col>
      </v-row>

      <div class="acepro-slot-card__color-row">
        <input
          v-model="localColor"
          class="acepro-slot-card__picker"
          type="color"
          :disabled="disabled"
          @input="markDirty"
        >
        <v-text-field
          v-model="localColor"
          dense
          outlined
          hide-details
          class="acepro-slot-card__color-field"
          label="颜色"
          :disabled="disabled"
          @input="markDirty"
        />
      </div>
    </div>

    <div class="acepro-slot-card__actions">
      <app-btn
        small
        :disabled="disabled || (!slot.ready && !active)"
        :loading="busy"
        @click="$emit('primary', slot)"
      >
        {{ active ? '卸载' : '装载' }}
      </app-btn>
      <app-btn
        small
        :disabled="disabled || !canSave"
        :loading="busy"
        @click="emitSave"
      >
        保存
      </app-btn>
      <app-btn
        small
        text
        color="error"
        :disabled="disabled"
        :loading="busy"
        @click="emitClear"
      >
        清空
      </app-btn>
    </div>

    <div class="acepro-slot-card__secondary-actions">
      <app-btn
        small
        text
        :color="assistActive ? 'warning' : undefined"
        :disabled="disabled || !slot.ready"
        :loading="busy"
        @click="$emit('assist', { index: slot.index, enabled: !assistActive })"
      >
        {{ assistActive ? '关闭助推' : '开启助推' }}
      </app-btn>
      <app-btn
        small
        text
        :disabled="disabled"
        :loading="busy"
        @click="$emit('change-spool', slot.index)"
      >
        换卷
      </app-btn>
    </div>
  </div>
</template>

<script lang="ts">
import { Component, Prop, Vue, Watch } from 'vue-property-decorator'
import type { AceProResolvedSlot } from '@/types/acePro'

@Component
export default class AceProSlotCard extends Vue {
  @Prop({ type: Object, required: true })
  readonly slot!: AceProResolvedSlot

  @Prop({ type: Boolean, default: false })
  readonly active!: boolean

  @Prop({ type: Boolean, default: false })
  readonly busy!: boolean

  @Prop({ type: Boolean, default: false })
  readonly disabled!: boolean

  @Prop({ type: Boolean, default: false })
  readonly assistActive!: boolean

  localMaterial = ''
  localTemperature = 0
  localColor = '#000000'
  isDirty = false

  readonly materialOptions = [
    'PLA',
    'PLA+',
    'PETG',
    'PETG-CF',
    'ABS',
    'ASA',
    'TPU',
    'PA',
    'PA-CF',
    'PET-CF',
    'PC',
    'PBT-CF',
    'PVA',
    'HIPS',
  ]

  mounted () {
    this.syncFromProps()
  }

  @Watch('slot', { immediate: true, deep: true })
  onSlotChange () {
    if (this.isDirty && !this.localValuesMatchSlot) return
    this.isDirty = false
    this.syncFromProps()
  }

  get displayMaterial (): string {
    return this.slot.material || '未配置'
  }

  get statusText (): string {
    if (this.slot.inventoryStatus === 'ready') return '就绪'
    if (this.slot.inventoryStatus === 'empty') return '空槽'
    if (this.slot.inventoryStatus === 'busy') return '忙碌'
    return this.slot.inventoryStatus || '未知'
  }

  get hardwareText (): string {
    if (this.slot.hardwareStatus === 'ready') return '已识别'
    if (this.slot.hardwareStatus === 'empty') return '无耗材'
    if (this.slot.hardwareStatus === 'busy') return '处理中'
    return this.slot.hardwareStatus || '未知'
  }

  get colorHex (): string {
    return this.localColor
  }

  get canSave (): boolean {
    return this.localMaterial.trim().length > 0 &&
      this.localTemperature > 0 &&
      /^#[0-9a-f]{6}$/i.test(this.localColor)
  }

  get slotColorHex (): string {
    return `#${this.slot.color.map(value => value.toString(16).padStart(2, '0')).join('')}`.toUpperCase()
  }

  get localValuesMatchSlot (): boolean {
    return this.localMaterial.trim().toUpperCase() === this.slot.material.trim().toUpperCase() &&
      Number(this.localTemperature) === Number(this.slot.temperature) &&
      this.localColor.toUpperCase() === this.slotColorHex
  }

  get statusBadgeClass (): string {
    if (this.slot.inventoryStatus === 'ready') return 'acepro-slot-card__badge--ready'
    if (this.slot.inventoryStatus === 'busy') return 'acepro-slot-card__badge--busy'
    return 'acepro-slot-card__badge--empty'
  }

  get slotClasses (): Record<string, boolean> {
    return {
      'acepro-slot-card--ready': this.slot.ready,
      'acepro-slot-card--active': this.active,
      'acepro-slot-card--empty': !this.slot.ready,
    }
  }

  emitSave () {
    if (!this.canSave) return

    this.$emit('save', {
      index: this.slot.index,
      material: this.localMaterial.trim(),
      colorHex: this.localColor,
      temperature: this.localTemperature,
    })
  }

  emitClear () {
    this.isDirty = false
    this.$emit('empty', this.slot.index)
  }

  markDirty () {
    this.isDirty = true
  }

  private syncFromProps () {
    this.localMaterial = this.slot.material
    this.localTemperature = this.slot.temperature
    this.localColor = this.slotColorHex
  }
}
</script>

<style scoped>
.acepro-slot-card {
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
  font-size: 15px;
  font-weight: 800;
  color: #eef2f7;
}

.acepro-slot-card__slot-label {
  margin-left: 4px;
  font-size: 11px;
  font-weight: 600;
  color: rgba(183, 194, 208, 0.8);
}

.acepro-slot-card__badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 3px;
}

.acepro-slot-card__badge {
  padding: 2px 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
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
  color: #eef2f7;
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
}

.acepro-slot-card__actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
}

.acepro-slot-card__actions ::v-deep .v-btn {
  min-height: 30px;
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
