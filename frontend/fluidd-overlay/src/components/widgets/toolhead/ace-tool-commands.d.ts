export type AceToolCommand = {
  name: string
}

export declare const ACE_SLOTS_PER_DEVICE: 4

export declare function getAceDeviceCount (
  printerState: object | null | undefined
): number | null

export declare function getAceToolCommandGroups<T extends AceToolCommand> (
  commands: readonly T[],
  deviceCount: number | null
): T[][] | null
