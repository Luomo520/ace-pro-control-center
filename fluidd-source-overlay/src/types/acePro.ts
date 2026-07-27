export interface AceProInventorySlot {
  status: string;
  color: [number, number, number];
  material: string;
  temp: number;
}

export interface AceProHardwareSlot {
  index: number;
  status: string;
  sku?: string;
  type?: string;
  color: [number, number, number];
}

export interface AceProDryerStatus {
  status: string;
  target_temp: number;
  duration: number;
  remain_time: number;
}

export interface AceProEndlessSpoolState {
  enabled: boolean;
  runoutDetected: boolean;
  inProgress: boolean;
}

export type AceProAutoDryingReason =
  | 'EMPTY'
  | 'UNKNOWN'
  | 'PLA_MIXED'
  | 'PLA_ONLY'
  | 'HIGH_TEMP'

export interface AceProAutoDryingState {
  available: boolean;
  enabled: boolean;
  active: boolean;
  ownedByAuto: boolean;
  suppressedForJob: boolean;
  temperature: number;
  reason: AceProAutoDryingReason;
  printState: string;
  lastError: string;
  noticeId: number;
  noticeMessage: string;
}

export interface AceProSensorState {
  name: string;
  available: boolean;
  detected: boolean;
}

export interface AceProResolvedSlot {
  index: number;
  isActive: boolean;
  inventoryStatus: string;
  hardwareStatus: string;
  material: string;
  temperature: number;
  color: [number, number, number];
  sku: string;
  type: string;
  ready: boolean;
}

export interface AceProResolvedState {
  detected: boolean;
  objectKey?: string;
  connected: boolean;
  model: string;
  firmware: string;
  bootFirmware: string;
  status: string;
  connectionState: string;
  temperature: number;
  humidity: number | null;
  fanSpeed: number;
  rfidEnabled: boolean;
  usbPort: string;
  usbPath: string;
  currentIndex: number;
  feedAssistIndex: number;
  sensors: {
    upper: AceProSensorState;
    lower: AceProSensorState;
  };
  printing: boolean;
  warnings: string[];
  toolchange: {
    active: boolean;
    context: Record<string, any>;
    lastError: string;
    recoveryRequired: boolean;
    cancelRequested: boolean;
  };
  endlessSpool: AceProEndlessSpoolState;
  autoDrying: AceProAutoDryingState;
  dryer: AceProDryerStatus;
  slots: AceProResolvedSlot[];
}
