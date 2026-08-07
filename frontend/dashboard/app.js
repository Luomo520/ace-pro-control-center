import {
  ACE_ASSIST_ONLY_MESSAGE,
  ACE_ACTIONS,
  ENCODER_CALIBRATION_DEFAULTS,
  AceApiClient,
  actionLabel,
  buildViewModel,
  canPerformAction,
  collectPrintMonitorEvent,
  evaluateEncoderCalibrationSegments,
  formatApiError,
} from '../shared/ace-core.js?v=V2.5ahpha'

const client = new AceApiClient({ client: 'ace-dashboard' })
const dom = {
  connection: document.querySelector('#connection-summary'),
  systemStrip: document.querySelector('#system-strip'),
  loading: document.querySelector('#loading-state'),
  error: document.querySelector('#error-state'),
  root: document.querySelector('#view-root'),
  refresh: document.querySelector('#refresh-status'),
  unload: document.querySelector('#unload-current'),
  confirmDialog: document.querySelector('#confirm-dialog'),
  confirmTitle: document.querySelector('#confirm-title'),
  confirmContent: document.querySelector('#confirm-content'),
  confirmSubmit: document.querySelector('#confirm-submit'),
  slotDialog: document.querySelector('#slot-dialog'),
  slotForm: document.querySelector('#slot-form'),
  slotTitle: document.querySelector('#slot-title'),
  slotMaterialOptions: document.querySelector('#slot-material-options'),
  slotBlocker: document.querySelector('#slot-blocker'),
  slotSave: document.querySelector('#slot-save'),
  toastRegion: document.querySelector('#toast-region'),
}

const app = {
  status: null,
  viewModel: null,
  tab: 'overview',
  loading: false,
  statusStale: false,
  pendingConfirmation: null,
  pollTimer: null,
  selectedDeviceId: '',
  encoderCalibrationLength: ENCODER_CALIBRATION_DEFAULTS.segmentLength,
  encoderCalibrationSegments: [],
  encoderCalibrationLastCounts: null,
  encoderActionBusy: false,
  monitorEventCursor: null,
  monitorEventCursorSignature: '',
  noticeCursor: null,
  noticeCursorSignature: '',
}

const escapeHtml = value => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#039;')

function attrDisabled (decision) {
  return decision?.allowed ? '' : `disabled title="${escapeHtml(decision?.reason || '当前不可用')}"`
}

function toast (title, message = '', error = false) {
  const node = document.createElement('div')
  node.className = `toast${error ? ' error' : ''}`
  node.innerHTML = `<strong>${escapeHtml(title)}</strong>${message ? `<span>${escapeHtml(message)}</span>` : ''}`
  dom.toastRegion.append(node)
  window.setTimeout(() => node.remove(), 5200)
}

function syncMaterialOptions () {
  const options = (app.viewModel?.materialTypes || []).map(material => {
    const option = document.createElement('option')
    option.value = material
    return option
  })
  dom.slotMaterialOptions.replaceChildren(...options)
}

function ensureSelectedDevice () {
  if (!app.viewModel?.devices.length) {
    app.selectedDeviceId = ''
    return null
  }
  const selected = app.viewModel.devices.find(device => device.id === app.selectedDeviceId)
  if (selected) return selected
  app.selectedDeviceId = app.viewModel.devices[0].id
  return app.viewModel.devices[0]
}

function selectedDevice () {
  return ensureSelectedDevice()
}

function renderDeviceSwitch () {
  if (!app.viewModel || app.viewModel.devices.length < 2) return ''
  return `<div class="device-switch" role="group" aria-label="选择 ACE 设备">
    ${app.viewModel.devices.map(device => `<button type="button" class="device-switch__button${device.id === app.selectedDeviceId ? ' active' : ''}" data-select-device="${device.id}" aria-pressed="${device.id === app.selectedDeviceId}">
      <span class="status-dot ${escapeHtml(device.statusTone)}"></span><strong>${escapeHtml(device.name)}</strong><span>${device.slots[0].tool}-${device.slots[3].tool}</span>
    </button>`).join('')}
  </div>`
}

function renderGlobalCurrentTool () {
  if (!app.viewModel || app.viewModel.devices.length < 2) return ''
  const target = app.viewModel.currentToolTarget
  const targetDevice = target && app.viewModel.devices.find(device => device.id === target.deviceId)
  const canJump = Boolean(targetDevice && targetDevice.id !== app.selectedDeviceId)
  return `<section class="global-tool" aria-label="全局当前工具">
    <div><span>全局当前工具</span><strong>${escapeHtml(app.viewModel.currentToolLabel)}</strong>${targetDevice ? `<small>${escapeHtml(targetDevice.name)} · 槽${target.slot + 1}</small>` : '<small>当前没有装载工具</small>'}</div>
    ${canJump ? `<button type="button" class="command secondary small" data-jump-current-tool="${targetDevice.id}">转到所属 ACE</button>` : ''}
  </section>`
}

function renderToolchangeMode () {
  const toolchange = app.viewModel.toolchange
  const tone = toolchange.mode === 'manual' ? 'manual' : toolchange.ready ? 'ready' : 'blocked'
  const label = toolchange.mode === 'manual' ? '手动模式' : toolchange.ready ? '自动换料已就绪' : '自动换料未就绪'
  const description = toolchange.ready ? '工具指令、卸载和无限续料可用。' : (toolchange.assistanceMessage || ACE_ASSIST_ONLY_MESSAGE)
  const detail = !toolchange.ready && toolchange.blockedReason && toolchange.blockedReason !== description
    ? `<small>${escapeHtml(toolchange.blockedReason)}</small>`
    : ''
  return `<section class="toolchange-mode ${tone}" aria-label="换料模式"><div><strong>${escapeHtml(label)}</strong><span>${escapeHtml(description)}</span>${detail}</div><span>${toolchange.ready ? '可自动换料' : '自动换料不可用'}</span></section>`
}

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

function observeToolchangeNotices (status) {
  const notices = Array.isArray(status?.toolchangeNotices) ? status.toolchangeNotices : []
  const batch = collectToolchangeNotices(notices, app.noticeCursor, app.noticeCursorSignature)
  app.noticeCursor = batch.cursor
  app.noticeCursorSignature = batch.cursorSignature
  for (const notice of batch.notices) toast(`${notice.command || '工具指令'} 已忽略`, notice.message)
}

function observePrintMonitorEvent (status) {
  const monitor = status?.path?.encoders?.shared?.printMonitor
  const batch = collectPrintMonitorEvent(monitor, app.monitorEventCursor, app.monitorEventCursorSignature)
  app.monitorEventCursor = batch.cursor
  app.monitorEventCursorSignature = batch.cursorSignature
  if (!batch.event) return
  const passive = monitor.mode === 'monitor'
  const message = [
    batch.event.message,
    batch.event.probableCause && `可能原因：${batch.event.probableCause}`,
    passive ? '监测模式仅提示，未请求暂停。' : monitor.pauseRequested ? '打印已请求暂停。' : '',
  ].filter(Boolean).join(' ')
  toast(passive ? '打印监测提示' : '打印监测故障', message, !passive)
}

function renderSystem () {
  if (!app.status) {
    dom.systemStrip.innerHTML = ''
    return
  }
  const status = app.status
  const transaction = status.transaction.active
    ? `${actionLabel(status.transaction.action)} · ${status.transaction.phase || '进行中'}`
    : '空闲'
  const pathSummary = status.system.pathLocked
    ? `占用 · ${status.system.pathOwner || '事务'}`
    : '空闲'
  const pathActivity = status.transaction.active ? `${pathSummary} · ${transaction}` : pathSummary
  const encoder = status.path.encoders.shared
  const encoderTitle = encoder.fault?.message || (encoder.state === 'not_armed'
    ? '保护模式尚未启用，当前不会参与送料保护。'
    : encoder.summaryLabel)
  const sensorLabel = value => value === true ? '有料' : value === false ? '无料' : '未提供'
  const upper = sensorLabel(status.path.sensors.upper)
  const lower = sensorLabel(status.path.sensors.lower)
  const upperPolicy = status.path.sensorPolicy.upper
  const lowerPolicy = status.path.sensorPolicy.lower
  const lowerPolicyLabel = lowerPolicy.monitorOnly
    ? `仅监测 · ${lower}`
    : lowerPolicy.controlEnabled ? `参与控制 · ${lower}` : `未参与控制 · ${lower}`
  const lowerTitle = lowerPolicy.monitorOnly
    ? `当前读数：${lower}。仅用于监测，不参与换料控制。`
    : lowerPolicy.controlEnabled
      ? `当前读数：${lower}。该传感器参与换料控制。`
      : `当前读数：${lower}。该传感器未参与换料控制。`
  dom.systemStrip.innerHTML = `
    <div class="metric"><span>打印状态</span><strong>${escapeHtml(status.system.printState)}</strong></div>
    <div class="metric"><span>当前工具</span><strong>${escapeHtml(status.system.currentToolLabel)}</strong></div>
    <div class="metric"><span>共享路径</span><strong>${escapeHtml(pathActivity)}</strong></div>
    <div class="metric"><span>换料模式</span><strong>${status.toolchangeMode === 'manual' ? '手动模式' : status.toolchangeReady ? '自动换料已就绪' : '自动换料未就绪'}</strong></div>
    <div class="metric"><span>ACE 送料</span><strong>参考送料 · 上方传感器闭环终止</strong></div>
    <div class="metric"><span>上方传感器</span><strong>控制闭环 · ${upper}</strong></div>
    <div class="metric"><span>上方送料超时</span><strong>${formatFeedTimeout(upperPolicy.feedTimeout)}</strong></div>
    <div class="metric"><span>下方传感器</span><strong title="${lowerTitle}">${lowerPolicyLabel}</strong></div>
    <div class="metric"><span>挤出机标定距离</span><strong>${formatMonitorLength(lowerPolicy.bypassLoadLength)}</strong></div>
    <div class="metric"><span>辅助送料</span><strong>${escapeHtml(status.feedAssist.label)}</strong></div>
    <div class="metric"><span>共享编码器</span><strong class="encoder-tone-${escapeHtml(encoder.tone)}" title="${escapeHtml(encoderTitle)}">${escapeHtml(encoder.summaryLabel)}</strong></div>
    <div class="metric"><span>编码器最低跟随比例</span><strong>${formatTrackingRatio(encoder.minTrackingRatio)}</strong></div>`
}

function renderDevicePanel (device) {
  const endless = canPerformAction(app.status, ACE_ACTIONS.SET_ENDLESS_SPOOL)
  const dryerAction = device.dryer.active ? ACE_ACTIONS.STOP_DRYING : ACE_ACTIONS.START_DRYING
  const dryer = canPerformAction(app.status, dryerAction, { device })
  const slots = device.slots.map(slot => {
    const isUnload = slot.active
    const action = isUnload ? ACE_ACTIONS.UNLOAD : ACE_ACTIONS.SELECT_TOOL
    const decision = canPerformAction(app.status, action, { device, slot })
    const params = isUnload ? '{}' : JSON.stringify({ tool: slot.tool })
    return `<article class="slot-card${slot.active ? ' active' : ''}">
      <div class="slot-title"><span class="swatch" style="background:${escapeHtml(slot.color)}"></span><strong>${escapeHtml(slot.materialLabel)}</strong></div>
      <div class="slot-route"><strong>${escapeHtml(slot.tool)}</strong><span>${escapeHtml(slot.label)}</span></div>
      <div class="slot-detail"><span>${escapeHtml(slot.remainingLabel)}</span><span>RFID ${escapeHtml(slot.rfidLabel)}</span></div>
      <button class="command slot-action ${isUnload ? 'is-unload' : 'primary'}" type="button"
        data-action="${action}" data-device="${device.id}" data-params='${escapeHtml(params)}' ${attrDisabled(decision)}>
        ${isUnload ? '卸载' : '更换耗材'}
      </button>
    </article>`
  }).join('')
  const settings = device.slots.map(slot => `
    <button class="command secondary small" type="button" data-slot-settings="${device.id}:${slot.index}">设置 ${escapeHtml(slot.label)}</button>`).join('')
  return `<section class="device-panel" aria-label="${escapeHtml(device.name)}">
    <div class="device-top-row">
      <div class="device-identity">
        <span class="status-dot ${escapeHtml(device.statusTone)}"></span>
        <div><h3>${escapeHtml(device.name)}</h3><p>${escapeHtml(device.modelLabel)} · ${escapeHtml(device.connectionLabel)} · ${escapeHtml(device.currentAction || device.state)}</p>
          ${device.readOnly ? '<p class="device-block-reason">此设备的物理动作已禁用；状态、RFID 和库存仍可使用。</p>' : ''}</div>
      </div>
      <div class="status-badges">
        <span class="badge">${escapeHtml(device.temperatureLabel)}</span>
        <span class="badge">湿度 ${escapeHtml(device.humidityLabel)}</span>
        <span class="badge">RFID ${escapeHtml(device.rfidLabel)}</span>
        ${device.readOnly ? '<span class="badge readonly">只读</span>' : ''}
        <label class="switch-control" title="${escapeHtml(endless.reason)}">全局无限续料
          <input type="checkbox" data-endless ${app.viewModel.endlessSpool.enabled ? 'checked' : ''} ${attrDisabled(endless)}>
        </label>
      </div>
    </div>
    <div class="slot-row">${slots}</div>
    <div class="slot-settings-row">${settings}</div>
    <div class="device-bottom-row">
      <button class="command secondary" type="button" data-refresh-device="${device.id}">刷新耗材数据</button>
      <button class="command ${device.dryer.active ? 'danger' : 'primary'}" type="button" data-dryer="${device.id}" ${attrDisabled(dryer)}>
        ${device.dryer.active ? '停止烘干' : '打开烘干设置'} · ${escapeHtml(device.dryerLabel)}
      </button>
    </div>
  </section>`
}

function renderOverview () {
  const device = selectedDevice()
  return `<div class="section-heading"><div><h2>设备与换料</h2><p>${app.viewModel.connectedDeviceCount}/${app.viewModel.configuredDeviceCount} 台在线 · 工具 ${app.viewModel.tools[0]?.tool || '--'}-${app.viewModel.tools.at(-1)?.tool || '--'}</p></div></div>
    <div class="device-list">${device ? renderDevicePanel(device) : ''}</div>`
}

function renderInventory () {
  const device = selectedDevice()
  return `<div class="section-heading"><div><h2>工具与库存</h2><p>全局工具编号按 ace0..ace3 固定映射</p></div></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>工具</th><th>设备 / 槽位</th><th>材料</th><th>颜色</th><th>余量</th><th>RFID</th><th>操作</th></tr></thead><tbody>
    ${device.slots.map(slot => `<tr>
      <td><strong>${slot.tool}${slot.active ? ' · 当前' : ''}</strong></td><td>${escapeHtml(device.name)} / ${slot.label}</td>
      <td>${escapeHtml(slot.materialLabel)}</td><td><span class="swatch" style="display:inline-block;background:${escapeHtml(slot.color)}"></span></td>
      <td>${escapeHtml(slot.remainingLabel)}</td><td>${escapeHtml(slot.rfidLabel)}</td>
      <td><button class="command secondary small" data-slot-settings="${device.id}:${slot.index}" type="button">编辑库存</button></td>
    </tr>`).join('')}</tbody></table></div>`
}

function renderMaintenance () {
  const device = selectedDevice()
  const feed = canPerformAction(app.status, ACE_ACTIONS.FEED, { device })
  const retract = canPerformAction(app.status, ACE_ACTIONS.RETRACT, { device })
  const assistSlot = device.slots[0]
  const enableAssist = canPerformAction(app.status, ACE_ACTIONS.ENABLE_FEED_ASSIST, { device, slot: assistSlot })
  const activeAssist = app.viewModel.feedAssist
  const activeDevice = app.status.devices.find(item => item.id === activeAssist.deviceId)
  const activeSlot = activeDevice?.slots[activeAssist.slot]
  const disableAssist = activeAssist.active && activeDevice
    ? canPerformAction(app.status, ACE_ACTIONS.DISABLE_FEED_ASSIST, { device: activeDevice, slot: activeSlot })
    : { allowed: false, reason: activeAssist.active ? '后端未提供当前辅助送料槽位。' : '当前没有启用 ACE 辅助送料。' }
  return `<div class="section-heading"><div><h2>维护动作</h2><p>共享路径动作按设备能力和打印状态执行门禁</p></div></div>
    <div class="control-grid"><section class="control-panel"><h3>${escapeHtml(device.name)} · 手动送料</h3>
        <div class="action-row"><label>槽位<select id="slot-${device.id}">${device.slots.map(slot => `<option value="${slot.index}">${escapeHtml(slot.tool)} · ${escapeHtml(slot.materialLabel)}</option>`).join('')}</select></label>
          <label>长度（mm）<input id="length-${device.id}" type="number" min="1" max="2000" value="50"></label>
          <button class="command secondary" data-maintenance="feed" data-device="${device.id}" ${attrDisabled(feed)}>手动送丝</button>
          <button class="command secondary" data-maintenance="retract" data-device="${device.id}" ${attrDisabled(retract)}>手动回抽</button>
        </div>${!feed.allowed ? `<p class="inline-warning">${escapeHtml(feed.reason)}</p>` : ''}</section>
      <section class="control-panel feed-assist-panel"><h3>ACE 辅助送料</h3><p>当前：<strong>${escapeHtml(activeAssist.label)}</strong></p>
        <div class="action-row"><label>辅助送料槽位<select id="feed-assist-slot-${device.id}">${device.slots.map(slot => `<option value="${slot.index}">${escapeHtml(slot.tool)} · ${escapeHtml(slot.materialLabel)}</option>`).join('')}</select></label>
          <button class="command primary" data-enable-feed-assist="${device.id}" ${attrDisabled(enableAssist)}>${activeAssist.active ? '切换到所选槽位' : '启用辅助送料'}</button>
          <button class="command danger" data-disable-feed-assist ${attrDisabled(disableAssist)}>停用辅助送料</button>
        </div></section></div>${renderEncoderMaintenance()}`
}

function renderDrying () {
  const device = selectedDevice()
  const start = canPerformAction(app.status, ACE_ACTIONS.START_DRYING, { device })
  const stop = canPerformAction(app.status, ACE_ACTIONS.STOP_DRYING, { device })
  return `<div class="section-heading"><div><h2>烘干控制</h2><p>目标温度与时长由后端再次校验</p></div></div>
    <div class="control-grid"><section class="control-panel"><h3>${escapeHtml(device.name)} · ${escapeHtml(device.dryerLabel)}</h3>
        <div class="action-row"><label>温度（°C）<input id="dryer-temp-${device.id}" type="number" min="20" max="75" value="45"></label>
          <label>时长（分钟）<input id="dryer-time-${device.id}" type="number" min="10" max="1440" value="240"></label>
          <button class="command primary" data-start-dryer="${device.id}" ${attrDisabled(start)}>开始烘干</button>
          <button class="command danger" data-action="stop_drying" data-device="${device.id}" data-params='{"device_id":"${device.id}"}' ${attrDisabled(stop)}>停止烘干</button>
        </div>${!start.allowed ? `<p class="inline-warning">${escapeHtml(start.reason)}</p>` : ''}</section></div>`
}

function renderEndless () {
  return `<div class="section-heading"><div><h2>无限续料</h2><p>候选槽位可跨设备，但共享路径始终只执行一个事务</p></div></div>
    <div class="control-grid">${(() => {
      const endless = app.viewModel.endlessSpool
      const decision = canPerformAction(app.status, ACE_ACTIONS.SET_ENDLESS_SPOOL)
      return `<section class="control-panel"><h3>共享打印头</h3>
        <p>状态：<strong>${endless.enabled ? '已启用' : '已停用'}</strong> · 上次选择：${escapeHtml(endless.lastSelection || '--')}</p>
        <div class="action-row"><label>匹配方式<select id="match-endless"><option value="exact" ${endless.matchMode === 'exact' ? 'selected' : ''}>材料与颜色一致</option><option value="material" ${endless.matchMode === 'material' ? 'selected' : ''}>仅材料一致</option></select></label>
          <button class="command ${endless.enabled ? 'danger' : 'primary'}" data-endless-button ${attrDisabled(decision)}>${endless.enabled ? '停用无限续料' : '启用无限续料'}</button>
        </div>${!decision.allowed ? `<p class="inline-warning">${escapeHtml(decision.reason)}</p>` : ''}</section>`
    })()}</div>`
}

function formatMonitorLength (value) {
  if (value === null || value === undefined || value === '') return '--'
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(1)} mm` : '--'
}

function formatFeedTimeout (value) {
  if (value === null || value === undefined || value === '') return '--'
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? `${number.toFixed(1)} 秒` : '--'
}

function formatTrackingRatio (value) {
  if (value === null || value === undefined || value === '') return '--'
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0 || number > 1) return '--'
  return `${(number * 100).toFixed(1).replace(/\.0$/, '')}%`
}

function monitorSensorEntry (name, value) {
  const detected = value && typeof value === 'object'
    ? value.detected ?? value.triggered ?? value.present
    : value
  const tone = detected === true ? 'present' : detected === false ? 'empty' : 'unknown'
  const state = detected === true ? '有料' : detected === false ? '无料' : '未知'
  return `<span class="sensor-snapshot ${tone}"><i></i>${escapeHtml(name)}：${state}</span>`
}

function renderMonitorSensors (issue) {
  const sensors = issue?.context?.sensors
  if (!sensors || typeof sensors !== 'object') return ''
  const names = { upper: '上方', lower: '下方', rdm: '总五通', hub: '一级五通' }
  return Object.entries(sensors).flatMap(([name, value]) => {
    if (name === 'hubs' && value && typeof value === 'object') {
      return Object.entries(value).map(([device, sensor]) => monitorSensorEntry(`${device} 五通`, sensor))
    }
    return [monitorSensorEntry(names[name] || name, value)]
  }).join('')
}

function encoderCalibrationEvaluation () {
  return evaluateEncoderCalibrationSegments(app.encoderCalibrationSegments)
}

function encoderCalibrationRows (evaluation) {
  return Array.from({ length: ENCODER_CALIBRATION_DEFAULTS.segmentCount }, (_, index) => {
    const segment = evaluation.segments[index]
    if (!segment) {
      return `<div class="encoder-segment pending"><strong>第 ${index + 1} 段</strong><span>${escapeHtml(app.encoderCalibrationLength)} mm</span><span>等待测量</span><span>--</span></div>`
    }
    const state = !segment.valid ? 'rejected' : evaluation.complete && evaluation.state === 'rejected' ? 'rejected' : evaluation.complete && evaluation.state === 'warning' ? 'warning' : 'passed'
    const deviation = segment.deviationPercent === null ? '--' : `${segment.deviationPercent.toFixed(1)}%`
    const resolution = segment.resolution === null ? '--' : `${segment.resolution.toFixed(4)} mm/脉冲`
    return `<div class="encoder-segment ${state}"><strong>第 ${index + 1} 段</strong><span>${segment.length.toFixed(1)} mm · ${segment.pulses} 脉冲</span><span>${resolution}</span><span>偏差 ${deviation}</span></div>`
  }).join('')
}

function renderEncoderMaintenance () {
  const encoder = app.viewModel.sharedEncoder
  const calibration = encoderCalibrationEvaluation()
  const monitor = encoder.printMonitor
  const start = canPerformAction(app.status, ACE_ACTIONS.ENCODER_CALIBRATION_START)
  const finish = canPerformAction(app.status, ACE_ACTIONS.ENCODER_CALIBRATION_FINISH)
  const cancel = canPerformAction(app.status, ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL)
  const length = Number(app.encoderCalibrationLength)
  const lengthValid = Number.isFinite(length) && length >= 0.01 && length <= 2000
  const busy = app.encoderActionBusy
  const busyDecision = decision => busy ? { allowed: false, reason: '校准请求正在处理中。' } : decision
  const finishDecision = lengthValid && calibration.canSave
    ? finish
    : { allowed: false, reason: lengthValid ? calibration.message : '每段移动长度必须在 0.01..2000 mm 之间。' }
  const recordDecision = encoder.calibrationActive && app.encoderCalibrationLastCounts !== null && calibration.completedCount < ENCODER_CALIBRATION_DEFAULTS.segmentCount
    ? { allowed: true, reason: '' }
    : { allowed: false, reason: app.encoderCalibrationLastCounts === null ? '请先建立本次校准的计数基线。' : calibration.complete ? '三段测量已完成。' : '请先开始校准。' }
  const blocker = encoder.configured
    ? (encoder.calibrationActive ? (calibration.canSave ? finish.reason : calibration.message) : start.reason)
    : '共享编码器未配置。'
  const issue = monitor.fault || monitor.lastEvent
  const context = issue?.context
  const contextLabel = context
    ? [
        context.tool && `工具 ${context.tool}`,
        context.device && `设备 ${context.device}`,
        context.pathState && `路径 ${context.pathState}`,
        context.printState && `打印 ${context.printState}`,
      ].filter(Boolean).join(' · ')
    : ''
  return `<section class="encoder-maintenance" aria-label="共享编码器维护">
    <div class="encoder-maintenance__column">
      <div class="encoder-maintenance__heading"><h3>共享编码器手动校准</h3><span class="${encoder.calibrationActive ? 'active' : ''}">${encoder.configured ? (encoder.calibrationActive ? '校准中' : '待机') : '未配置'}</span></div>
      <p>本向导不会驱动 ACE 或挤出机。开始计数后，请手动移动耗材，再填写实际移动长度。</p>
      <div class="encoder-pulse-readout"><span>实时脉冲数</span><strong>${encoder.configured ? escapeHtml(encoder.counts) : '--'}</strong></div>
      <div class="encoder-calibration-summary ${calibration.state}"><strong>${calibration.completedCount}/${calibration.segmentCount} 段</strong><span>${escapeHtml(calibration.message)}</span></div>
      <div class="encoder-segments">${encoderCalibrationRows(calibration)}</div>
      <div class="encoder-calibration-actions">
        <label>每段移动长度（mm）<input id="encoder-calibration-length" type="number" min="0.01" max="2000" step="0.01" value="${escapeHtml(app.encoderCalibrationLength)}" ${encoder.calibrationActive || busy ? 'disabled' : ''}></label>
        <button class="command primary" data-encoder-calibration="start" ${attrDisabled(busyDecision(start))}>开始三段校准</button>
        <button class="command secondary" data-encoder-calibration="record" ${attrDisabled(busyDecision(recordDecision))}>记录第 ${Math.min(calibration.completedCount + 1, calibration.segmentCount)} 段</button>
        <button class="command secondary" data-encoder-calibration="finish" ${attrDisabled(busyDecision(finishDecision))}>完成并保存</button>
        <button class="command secondary" data-encoder-calibration="reset" ${!encoder.calibrationActive || busy ? 'disabled' : ''}>重置分段</button>
        <button class="command danger" data-encoder-calibration="cancel" ${attrDisabled(busyDecision(cancel))}>取消</button>
      </div>
      ${blocker ? `<p class="inline-warning">${escapeHtml(blocker)}</p>` : ''}
    </div>
    <div class="encoder-maintenance__column print-monitor">
      <div class="encoder-maintenance__heading"><h3>打印监测</h3><span class="monitor-${escapeHtml(monitor.tone)}">${encoder.configured ? escapeHtml(monitor.statusLabel) : '未配置'}</span></div>
      <div class="print-monitor__metrics">
        <div><span>模式</span><strong>${escapeHtml(monitor.modeLabel)}</strong></div>
        <div><span>检测长度</span><strong>${formatMonitorLength(monitor.detectionLength)}</strong></div>
        <div><span>已挤出未动</span><strong>${formatMonitorLength(monitor.extrusionSinceMotion)}</strong></div>
        <div><span>检测余量</span><strong>${formatMonitorLength(monitor.headroom)}</strong></div>
      </div>
      ${issue ? `<div class="print-monitor__issue"><strong>${escapeHtml(issue.message)}</strong>${issue.probableCause ? `<span>可能原因：${escapeHtml(issue.probableCause)}</span>` : ''}${contextLabel ? `<span>现场：${escapeHtml(contextLabel)}</span>` : ''}${monitor.pauseRequested ? '<span class="pause-note">打印已请求暂停，请排查后再恢复。</span>' : ''}<div class="sensor-snapshots">${renderMonitorSensors(issue)}</div></div>` : `<p>${monitor.mode === 'monitor' ? '监测模式只提示异常，不会请求暂停打印。' : monitor.mode === 'pause' ? '暂停保护检测到故障时会请求暂停打印。' : '打印监测当前关闭。'}</p>`}
    </div>
  </section>`
}

function renderCalibration () {
  return `<div class="section-heading"><div><h2>共享编码器校准</h2><p>手动移动耗材完成脉冲与长度标定</p></div></div>${renderEncoderMaintenance()}`
}

function renderDiagnostics () {
  const device = selectedDevice()
  const issues = [
    ...app.status.diagnostics.errors.map(issue => ({ ...issue, tone: 'error' })),
    ...app.status.diagnostics.warnings.map(issue => ({ ...issue, tone: '' })),
    ...(app.status.diagnostics.lastError ? [{ ...app.status.diagnostics.lastError, tone: 'error' }] : []),
  ]
  const diagnose = canPerformAction(app.status, ACE_ACTIONS.DIAGNOSE, { device })
  const recover = canPerformAction(app.status, ACE_ACTIONS.RECOVER, { device })
  return `<div class="section-heading"><div><h2>诊断与恢复</h2><p>连接、身份、错误和下一步建议</p></div></div>
    <div class="control-grid">
      <section class="control-panel"><h3>${escapeHtml(device.name)}</h3>
          <p>协议 ${escapeHtml(device.protocol)} · 固件 ${escapeHtml(device.firmware)}<br>端口 ${escapeHtml(device.diagnostics.port || '--')}<br>UID ${escapeHtml(device.diagnostics.uid || '--')} · 重连 ${device.diagnostics.reconnects}</p>
          <div class="action-row"><button class="command secondary" data-action="diagnose" data-device="${device.id}" data-params='{"device_id":"${device.id}"}' ${attrDisabled(diagnose)}>运行诊断</button>
          <button class="command danger" data-action="recover" data-device="${device.id}" data-params='{"device_id":"${device.id}"}' ${attrDisabled(recover)}>执行恢复</button></div>
          ${device.error ? `<p class="inline-warning">${escapeHtml(device.error.message)} ${escapeHtml(device.error.nextAction)}</p>` : ''}</section>
      <section class="control-panel"><h3>系统问题</h3><div class="issue-list">${issues.length ? issues.map(issue => `<div class="issue ${issue.tone}"><strong>${escapeHtml(issue.code || '提示')}</strong><span>${escapeHtml(issue.message)} ${escapeHtml(issue.nextAction)}</span></div>`).join('') : '<p>当前没有报告问题。</p>'}</div></section>
    </div>`
}

const renderers = { overview: renderOverview, inventory: renderInventory, maintenance: renderMaintenance, drying: renderDrying, endless: renderEndless, calibration: renderCalibration, diagnostics: renderDiagnostics }

function render () {
  renderSystem()
  if (!app.viewModel) return
  ensureSelectedDevice()
  dom.root.innerHTML = `${renderGlobalCurrentTool()}${renderDeviceSwitch()}${renderToolchangeMode()}${renderers[app.tab]()}`
  dom.root.hidden = false
  const current = app.status.system.currentTool
  if (app.statusStale) {
    dom.unload.disabled = true
    dom.unload.title = 'ACE 状态已过期，请先恢复连接。'
    return
  }
  if (current) {
    const target = app.viewModel.tools.find(tool => tool.tool === current)
    const device = target ? app.status.devices.find(item => item.id === target.deviceId) : null
    const decision = canPerformAction(app.status, ACE_ACTIONS.UNLOAD, { device })
    dom.unload.disabled = !decision.allowed
    dom.unload.title = decision.reason
  } else {
    dom.unload.disabled = true
    dom.unload.title = '当前没有已装载耗材。'
  }
}

async function refresh ({ quiet = false } = {}) {
  if (app.loading) return
  app.loading = true
  dom.refresh.disabled = true
  if (!quiet && !app.viewModel) dom.loading.hidden = false
  try {
    const status = await client.getStatus()
    observeToolchangeNotices(status)
    observePrintMonitorEvent(status)
    app.status = status
    app.viewModel = buildViewModel(app.status)
    ensureSelectedDevice()
    app.statusStale = false
    syncMaterialOptions()
    dom.connection.textContent = `${app.viewModel.connectedDeviceCount}/${app.viewModel.configuredDeviceCount} 台设备在线`
    dom.loading.hidden = true
    dom.error.hidden = true
    render()
  } catch (error) {
    const issue = formatApiError(error)
    app.statusStale = Boolean(app.viewModel)
    dom.connection.textContent = 'Moonraker 状态不可用'
    if (!app.viewModel) {
      dom.loading.hidden = true
      dom.error.hidden = false
      dom.error.textContent = `${issue.title}：${issue.message} ${issue.nextAction}`
    } else if (!quiet) toast(issue.title, `${issue.message} ${issue.nextAction}`, true)
  } finally {
    app.loading = false
    dom.refresh.disabled = false
  }
}

function findContext (deviceId, params) {
  const device = app.status.devices.find(item => item.id === deviceId)
  const tool = params.tool
  const slot = tool
    ? device?.slots.find(item => item.tool === tool)
    : Number.isInteger(params.slot) ? device?.slots[params.slot] : null
  return { device, slot }
}

function confirmAction (action, params, deviceId) {
  if (app.statusStale) {
    toast('操作不可用', 'ACE 状态已过期，请先恢复连接。', true)
    return
  }
  const context = findContext(deviceId, params)
  const decision = canPerformAction(app.status, action, context)
  if (!decision.allowed) {
    toast('操作不可用', decision.reason, true)
    return
  }
  const route = params.tool ? app.viewModel.tools.find(tool => tool.tool === params.tool) : null
  dom.confirmTitle.textContent = actionLabel(action)
  dom.confirmContent.innerHTML = `<p><strong>${escapeHtml(actionLabel(action))}</strong></p>
    <p>设备：${escapeHtml(context.device?.name || '共享打印头')}<br>
    ${route ? `工具：${escapeHtml(route.tool)} · ${escapeHtml(route.slotLabel)} · ${escapeHtml(route.material)}<br>` : ''}
    当前打印状态：${escapeHtml(app.status.system.printState)}</p>
    <p>确认后请求将由 Moonraker 再次进行能力、路径锁和打印状态校验。</p>`
  app.pendingConfirmation = { action, params, deviceId }
  dom.confirmDialog.returnValue = ''
  dom.confirmDialog.showModal()
}

async function executeConfirmed () {
  const pending = app.pendingConfirmation
  app.pendingConfirmation = null
  if (!pending) return
  try {
    dom.confirmSubmit.disabled = true
    await client.action(pending.action, pending.params, { confirm: true, deviceCount: app.status.devices.length })
    toast(`${actionLabel(pending.action)}已提交`, '状态将在操作进度更新后刷新。')
    await refresh({ quiet: true })
  } catch (error) {
    const issue = formatApiError(error)
    toast(issue.title, `${issue.message} ${issue.nextAction}`, true)
  } finally {
    dom.confirmSubmit.disabled = false
  }
}

async function executeImmediate (action, params, deviceId, successMessage) {
  if (app.statusStale) {
    toast('操作不可用', 'ACE 状态已过期，请先恢复连接。', true)
    return
  }
  const decision = canPerformAction(app.status, action, findContext(deviceId, params))
  if (!decision.allowed) {
    toast('操作不可用', decision.reason, true)
    return
  }
  try {
    await client.action(action, params, { confirm: false, deviceCount: app.status.devices.length })
    toast(successMessage)
    await refresh({ quiet: true })
  } catch (error) {
    const issue = formatApiError(error)
    toast(issue.title, `${issue.message} ${issue.nextAction}`, true)
  }
}

async function executeEncoderCalibration (step) {
  if (app.encoderActionBusy || app.statusStale) return
  if (step === 'reset') {
    app.encoderCalibrationSegments = []
    app.encoderCalibrationLastCounts = Number(app.status?.path?.encoders?.shared?.counts || 0)
    render()
    return
  }
  if (step === 'record') {
    const currentCounts = Number(app.status?.path?.encoders?.shared?.counts)
    const previousCounts = Number(app.encoderCalibrationLastCounts)
    const pulses = currentCounts - previousCounts
    app.encoderCalibrationSegments.push({ length: Number(app.encoderCalibrationLength), pulses })
    app.encoderCalibrationLastCounts = currentCounts
    const evaluation = encoderCalibrationEvaluation()
    toast(pulses >= ENCODER_CALIBRATION_DEFAULTS.minimumPulses ? `第 ${evaluation.completedCount} 段已记录` : '本段测量已拒绝', pulses >= 1 ? `${pulses} 脉冲` : '未检测到有效脉冲，请检查接线、压紧轮并重置分段。', pulses < 1)
    render()
    return
  }
  const actions = {
    start: ACE_ACTIONS.ENCODER_CALIBRATION_START,
    finish: ACE_ACTIONS.ENCODER_CALIBRATION_FINISH,
    cancel: ACE_ACTIONS.ENCODER_CALIBRATION_CANCEL,
  }
  const action = actions[step]
  if (!action) return
  const evaluation = encoderCalibrationEvaluation()
  if (step === 'finish' && !evaluation.canSave) {
    toast('校准结果已拒绝', evaluation.message, true)
    return
  }
  const params = step === 'finish' ? { length: evaluation.totalLength } : {}
  const decision = canPerformAction(app.status, action)
  if (!decision.allowed) {
    toast('操作不可用', decision.reason, true)
    return
  }
  try {
    app.encoderActionBusy = true
    render()
    await client.action(action, params, { confirm: false, deviceCount: app.status.devices.length })
    toast(step === 'start' ? '编码器计数已开始' : step === 'finish' ? '共享编码器校准已保存' : '共享编码器校准已取消', step === 'start' ? '请手动移动耗材，然后填写实际移动长度。' : '')
    await refresh({ quiet: true })
    if (step === 'start') {
      app.encoderCalibrationSegments = []
      app.encoderCalibrationLastCounts = Number(app.status?.path?.encoders?.shared?.counts || 0)
    } else {
      app.encoderCalibrationSegments = []
      app.encoderCalibrationLastCounts = null
    }
  } catch (error) {
    const issue = formatApiError(error)
    toast(issue.title, `${issue.message} ${issue.nextAction}`, true)
  } finally {
    app.encoderActionBusy = false
    render()
    schedulePoll()
  }
}

function openSlotSettings (deviceId, slotIndex) {
  const device = app.status.devices.find(item => item.id === deviceId)
  const slot = device?.slots[slotIndex]
  if (!device || !slot) return
  const decision = app.statusStale
    ? { allowed: false, reason: 'ACE 状态已过期，请先恢复连接。' }
    : canPerformAction(app.status, ACE_ACTIONS.SET_SLOT, { device, slot })
  dom.slotTitle.textContent = `${device.name} · ${slot.label} · ${slot.tool}`
  dom.slotForm.elements.device_id.value = device.id
  dom.slotForm.elements.slot.value = slot.index
  dom.slotForm.elements.material.value = slot.materialLabel === '未设置'
    ? app.viewModel.materialTypes[0]
    : slot.materialLabel
  dom.slotForm.elements.color.value = /^#[0-9a-f]{6}$/i.test(slot.color) ? slot.color : '#8b929a'
  dom.slotForm.elements.target_temperature.value = slot.targetTemperature ?? ''
  dom.slotSave.disabled = !decision.allowed
  dom.slotBlocker.hidden = decision.allowed
  dom.slotBlocker.textContent = decision.reason
  dom.slotDialog.returnValue = ''
  dom.slotDialog.showModal()
}

async function saveSlot () {
  const data = new FormData(dom.slotForm)
  const params = {
    device_id: data.get('device_id'),
    slot: Number(data.get('slot')),
    material: String(data.get('material') || '').trim(),
    color: data.get('color'),
    target_temperature: Number(data.get('target_temperature')) || null,
  }
  try {
    await client.action(ACE_ACTIONS.SET_SLOT, params, { confirm: true, deviceCount: app.status.devices.length })
    toast('槽位已保存', `${params.device_id} · 槽${params.slot + 1}`)
    await refresh({ quiet: true })
  } catch (error) {
    const issue = formatApiError(error)
    toast(issue.title, `${issue.message} ${issue.nextAction}`, true)
  }
}

dom.refresh.addEventListener('click', () => refresh())
dom.unload.addEventListener('click', () => {
  if (!app.status?.system.currentTool) return
  const target = app.viewModel.tools.find(tool => tool.tool === app.status.system.currentTool)
  confirmAction(ACE_ACTIONS.UNLOAD, {}, target?.deviceId || '')
})
dom.confirmDialog.querySelector('form').addEventListener('submit', event => {
  if (event.submitter?.value === 'confirm') executeConfirmed()
  else app.pendingConfirmation = null
})
dom.confirmDialog.addEventListener('cancel', () => {
  app.pendingConfirmation = null
})
dom.slotForm.addEventListener('submit', event => {
  if (event.submitter?.value === 'save') saveSlot()
})

document.querySelector('.tabs').addEventListener('click', event => {
  const tab = event.target.closest('[data-tab]')
  if (!tab) return
  app.tab = tab.dataset.tab
  document.querySelectorAll('[data-tab]').forEach(item => {
    const active = item === tab
    item.classList.toggle('active', active)
    item.setAttribute('aria-selected', String(active))
  })
  render()
  dom.root.focus({ preventScroll: true })
})

dom.root.addEventListener('click', event => {
  const currentToolJump = event.target.closest('[data-jump-current-tool]')
  if (currentToolJump) {
    app.selectedDeviceId = currentToolJump.dataset.jumpCurrentTool
    app.tab = 'overview'
    document.querySelector('[data-tab="overview"]')?.click()
    render()
    return
  }
  const deviceSwitch = event.target.closest('[data-select-device]')
  if (deviceSwitch) {
    app.selectedDeviceId = deviceSwitch.dataset.selectDevice
    render()
    return
  }
  const encoderCalibration = event.target.closest('[data-encoder-calibration]')
  if (encoderCalibration) {
    executeEncoderCalibration(encoderCalibration.dataset.encoderCalibration)
    return
  }
  const actionButton = event.target.closest('[data-action]')
  if (actionButton) {
    const params = JSON.parse(actionButton.dataset.params || '{}')
    confirmAction(actionButton.dataset.action, params, actionButton.dataset.device || params.device_id || '')
    return
  }
  const settings = event.target.closest('[data-slot-settings]')
  if (settings) {
    const [deviceId, slot] = settings.dataset.slotSettings.split(':')
    openSlotSettings(deviceId, Number(slot))
    return
  }
  const maintenance = event.target.closest('[data-maintenance]')
  if (maintenance) {
    const deviceId = maintenance.dataset.device
    const length = Number(document.querySelector(`#length-${deviceId}`).value)
    const slot = Number(document.querySelector(`#slot-${deviceId}`).value)
    confirmAction(maintenance.dataset.maintenance, { device_id: deviceId, slot, length }, deviceId)
    return
  }
  const enableFeedAssist = event.target.closest('[data-enable-feed-assist]')
  if (enableFeedAssist) {
    const deviceId = enableFeedAssist.dataset.enableFeedAssist
    const slot = Number(document.querySelector(`#feed-assist-slot-${deviceId}`).value)
    const device = app.status.devices.find(item => item.id === deviceId)
    const target = device?.slots[slot]
    if (!device || !target) return
    confirmAction(ACE_ACTIONS.ENABLE_FEED_ASSIST, { device_id: deviceId, slot }, deviceId)
    return
  }
  const disableFeedAssist = event.target.closest('[data-disable-feed-assist]')
  if (disableFeedAssist) {
    const active = app.status.feedAssist
    if (!active.active || !active.targetValid) return
    executeImmediate(ACE_ACTIONS.DISABLE_FEED_ASSIST, {
      device_id: active.deviceId,
      slot: active.slot,
    }, active.deviceId, `${active.tool} ACE 辅助送料已停用`)
    return
  }
  const deviceRefresh = event.target.closest('[data-refresh-device]')
  if (deviceRefresh) {
    client.action(ACE_ACTIONS.REFRESH, { device_id: deviceRefresh.dataset.refreshDevice })
      .then(() => refresh({ quiet: true }))
      .catch(error => {
        const issue = formatApiError(error)
        toast(issue.title, `${issue.message} ${issue.nextAction}`, true)
      })
    return
  }
  const startDryer = event.target.closest('[data-start-dryer]')
  if (startDryer) {
    const deviceId = startDryer.dataset.startDryer
    confirmAction(ACE_ACTIONS.START_DRYING, {
      device_id: deviceId,
      temperature: Number(document.querySelector(`#dryer-temp-${deviceId}`).value),
      duration_minutes: Number(document.querySelector(`#dryer-time-${deviceId}`).value),
    }, deviceId)
    return
  }
  const dryer = event.target.closest('[data-dryer]')
  if (dryer) {
    const device = app.status.devices.find(item => item.id === dryer.dataset.dryer)
    if (device?.dryer.active) confirmAction(ACE_ACTIONS.STOP_DRYING, { device_id: device.id }, device.id)
    else {
      app.tab = 'drying'
      document.querySelector('[data-tab="drying"]').click()
    }
    return
  }
  const endless = event.target.closest('[data-endless-button]')
  if (endless) {
    const current = app.viewModel.endlessSpool
    confirmAction(ACE_ACTIONS.SET_ENDLESS_SPOOL, {
      enabled: !current.enabled,
      match_mode: document.querySelector('#match-endless').value,
    }, '')
  }
})

dom.root.addEventListener('input', event => {
  if (event.target.id !== 'encoder-calibration-length') return
  app.encoderCalibrationLength = event.target.value
})

dom.root.addEventListener('change', event => {
  const toggle = event.target.closest('[data-endless]')
  if (!toggle) return
  const current = app.viewModel.endlessSpool
  toggle.checked = current.enabled
  confirmAction(ACE_ACTIONS.SET_ENDLESS_SPOOL, { enabled: !current.enabled, match_mode: current.matchMode }, '')
})

function schedulePoll () {
  if (app.pollTimer) window.clearTimeout(app.pollTimer)
  const delay = app.status?.path?.encoders?.shared?.calibrationActive ? 1000 : 5000
  app.pollTimer = window.setTimeout(async () => {
    if (!document.hidden && !app.pendingConfirmation && !dom.slotDialog.open) await refresh({ quiet: true })
    schedulePoll()
  }, delay)
}

refresh().finally(schedulePoll)
