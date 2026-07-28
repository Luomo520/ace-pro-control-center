export interface AceProInventorySlot {
  status: string;
  color: [number, number, number];
  material: string;
  temp: number;
}

export interface AceProMaterialProfile {
  name: string;
  dryingTemperature: number;
  materialTemperature: number;
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

export type AceProSlotPosition =
  | 'internal_or_unknown'
  | 'preload_parked_estimated'
  | 'upper_sensor'
  | 'toolhead'
  | 'nozzle'
  | 'unknown'

export interface AceProCalibrationState {
  available: boolean;
  valid: boolean;
  stale: boolean;
  phase: string;
  mode: string;
  selectedSlot: number;
  feedCompleted: number;
  feedUpperBound: number;
  sensorClearCompleted: number;
  sensorClearUpperBound: number;
  retractDistance: number;
  parkingDistance: number;
  parkingSensorCleared: boolean;
  parkingDirection: string;
  parkingOffset: number;
  upperToParkingSensorDistance: number;
  upperToParkingDistance: number;
  bowdenTubeLength: number;
  lastError: string;
}

export interface AceProResolvedSlot {
  index: number;
  isActive: boolean;
  inventoryStatus: string;
  hardwareStatus: string;
  material: string;
  temperature: number;
  dryingTemperature: number;
  profileKnown: boolean;
  color: [number, number, number];
  sku: string;
  type: string;
  ready: boolean;
  position: AceProSlotPosition;
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
  slotPositions: AceProSlotPosition[];
  filamentPosition: AceProSlotPosition;
  motionOwner: string;
  activeMotion: Record<string, any>;
  calibration: AceProCalibrationState;
  sensors: {
    upper: AceProSensorState;
    lower: AceProSensorState;
    parking: AceProSensorState;
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
  materialProfiles: Record<string, AceProMaterialProfile>;
  slots: AceProResolvedSlot[];
}
