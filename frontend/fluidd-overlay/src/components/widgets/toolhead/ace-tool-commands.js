export const ACE_SLOTS_PER_DEVICE = 4

const MIN_DEVICE_COUNT = 1
const MAX_DEVICE_COUNT = 4
const TOOL_COMMAND = /^t(\d+)$/i

function isDeviceCount (value) {
  return Number.isInteger(value) &&
    value >= MIN_DEVICE_COUNT &&
    value <= MAX_DEVICE_COUNT
}

function toolIndex (name) {
  const match = TOOL_COMMAND.exec(name)
  return match === null ? null : Number(match[1])
}

export function getAceDeviceCount (printerState) {
  if (printerState === null || typeof printerState !== 'object') return null
  const aceState = printerState.ace
  if (aceState === null || typeof aceState !== 'object') return null
  return isDeviceCount(aceState.device_count) ? aceState.device_count : null
}

export function getAceToolCommandGroups (commands, deviceCount) {
  if (!isDeviceCount(deviceCount)) return null

  const groups = Array.from({ length: deviceCount }, () => [])
  for (const command of commands) {
    const index = toolIndex(command.name)
    if (index === null || index >= deviceCount * ACE_SLOTS_PER_DEVICE) continue
    groups[Math.floor(index / ACE_SLOTS_PER_DEVICE)].push(command)
  }
  return groups.filter(group => group.length > 0)
}
