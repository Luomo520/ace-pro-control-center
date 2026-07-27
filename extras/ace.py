import serial, threading, time, logging, json, struct, queue, traceback, re, copy
from serial import SerialException
import serial.tools.list_ports

ACEPROSV08_DRIVER_VERSION = "1.1.0-luomo"
CALIBRATION_FORMAT_VERSION = 1

AUTO_DRYING_DURATION_MINUTES = 1440
AUTO_DRYING_KNOWN_MATERIALS = {
    'PLA', 'ABS', 'ABSCF', 'PETG', 'PAHTCF', 'PETCF', 'PEEK'
}
AUTO_DRYING_MESSAGES = {
    'EMPTY': '未检测到可烘干耗材，本次打印不会自动启动烘干。',
    'UNKNOWN': '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。',
    'PLA_MIXED': (
        '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；'
        '其他高温材料的烘干效果可能受限。'),
    'PLA_ONLY': '自动烘干使用 45°C：全部已装载耗材均为 PLA。',
    'HIGH_TEMP': '自动烘干使用 60°C：已装载耗材均为高温材料。',
}
SLOT_POSITION_VALUES = {
    'internal_or_unknown',
    'preload_parked_estimated',
    'upper_sensor',
    'toolhead',
    'nozzle',
    'unknown',
}


def calculate_parking_distance(feed_upper_bound, bowden_tube_length,
                               parking_margin, max_distance):
    parking_distance = (
        float(feed_upper_bound)
        - float(bowden_tube_length)
        + float(parking_margin))
    if parking_distance <= 0 or parking_distance > float(max_distance):
        raise ValueError('calculated parking distance is outside safe bounds')
    return parking_distance


def calibration_is_valid(record, bowden_tube_length, parking_margin,
                         format_version=CALIBRATION_FORMAT_VERSION):
    if not isinstance(record, dict) or record.get('valid') is not True:
        return False
    try:
        if int(record.get('format_version', -1)) != int(format_version):
            return False
        if abs(float(record.get('bowden_tube_length'))
               - float(bowden_tube_length)) > 1e-6:
            return False
        if abs(float(record.get('parking_margin'))
               - float(parking_margin)) > 1e-6:
            return False
        feed_upper_bound = float(record.get('feed_upper_bound'))
        parking_distance = float(record.get('parking_distance'))
        expected_parking = (
            feed_upper_bound - float(bowden_tube_length)
            + float(parking_margin))
        return (
            feed_upper_bound > 0
            and parking_distance > 0
            and abs(parking_distance - expected_parking) <= 1e-6)
    except (TypeError, ValueError):
        return False


def select_auto_drying_policy(slots):
    loaded = []
    for slot_data in slots:
        status = str(slot_data.get('status') or 'empty').strip().lower()
        if status == 'empty':
            continue
        loaded.append(str(slot_data.get('material') or '').strip().upper())
    if not loaded:
        return 0, 'EMPTY'
    if any(not material or material not in AUTO_DRYING_KNOWN_MATERIALS
           for material in loaded):
        return 45, 'UNKNOWN'
    has_pla = 'PLA' in loaded
    if has_pla and any(material != 'PLA' for material in loaded):
        return 50, 'PLA_MIXED'
    if has_pla:
        return 45, 'PLA_ONLY'
    return 60, 'HIGH_TEMP'


class FilamentFeedError(Exception):
    """A bounded filament feed failed and the print must remain paused."""


class BunnyAce:
    def __init__(self, config):
        self._connected = False
        self._serial = None
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self._name = config.get_name()
        self.lock = False
        self.send_time = None
        self.read_buffer = bytearray()
        if self._name.startswith('ace '):
            self._name = self._name[4:]
        self.variables = self.printer.lookup_object('save_variables').allVariables
        self._load_slot_positions()

        self.serial_name = config.get('serial', '/dev/ttyACM0')
        self.baud = config.getint('baud', 115200)
        extruder_sensor_pin = config.get('extruder_sensor_pin', None)
        toolhead_sensor_pin = config.get('toolhead_sensor_pin', None)
        self.feed_speed = config.getint('feed_speed', 50)
        self.retract_speed = config.getint('retract_speed', 50)
        self.feed_fast_speed = config.getfloat(
            'feed_fast_speed', float(self.feed_speed), above=0.)
        self.feed_approach_speed = config.getfloat(
            'feed_approach_speed', min(float(self.feed_speed), 25.), above=0.)
        self.feed_approach_length = config.getfloat(
            'feed_approach_length', 100., minval=0.)
        self.intermittent_feed = config.getboolean(
            'intermittent_feed', False)
        self.feed_fast_chunk_length = config.getfloat(
            'feed_fast_chunk_length', 1000., above=0.)
        self.feed_slip_compensation_length = config.getfloat(
            'feed_slip_compensation_length', 400., minval=0.)
        self.feed_slip_compensation_chunk = config.getfloat(
            'feed_slip_compensation_chunk', 50., above=0.)
        self.feed_slip_compensation_speed = config.getfloat(
            'feed_slip_compensation_speed', min(float(self.feed_speed), 25.),
            above=0.)
        self.retract_fast_speed = config.getfloat(
            'retract_fast_speed', float(self.retract_speed), above=0.)
        self.retract_parking_speed = config.getfloat(
            'retract_parking_speed', min(float(self.retract_speed), 25.),
            above=0.)
        self.retract_parking_length = config.getfloat(
            'retract_parking_length', 200., minval=0.)
        self.intermittent_retract = config.getboolean(
            'intermittent_retract', False)
        self.toolhead_feed_fast_speed = config.getfloat(
            'toolhead_feed_fast_speed', 8., above=0.)
        self.toolhead_feed_slow_speed = config.getfloat(
            'toolhead_feed_slow_speed', 5., above=0.)
        self.toolhead_feed_fast_length = config.getfloat(
            'toolhead_feed_fast_length', 10., minval=0.)
        self.toolhead_feed_fast_step = config.getfloat(
            'toolhead_feed_fast_step', 5., above=0.)
        self.toolhead_feed_slow_step = config.getfloat(
            'toolhead_feed_slow_step', 1., above=0.)
        self.toolhead_to_nozzle_speed = config.getfloat(
            'toolhead_to_nozzle_speed', 5., above=0.)
        self.toolchange_retract_length = config.getint('toolchange_retract_length', 150)
        self.toolchange_load_length = config.getint('toolchange_load_length', 630)
        self.toolhead_sensor_to_nozzle_length = config.getint('toolhead_sensor_to_nozzle', 0)
        self.extruder_sensor_timeout = config.getfloat(
            'extruder_sensor_timeout', 15., above=0.)
        self.toolhead_sensor_max_feed_length = config.getfloat(
            'toolhead_sensor_max_feed_length', 200., above=0.)
        self.ace_ready_timeout = config.getfloat(
            'ace_ready_timeout', 15., above=0.)
        self.ace_stop_ready_timeout = config.getfloat(
            'ace_stop_ready_timeout', 25., above=0.)
        self.ace_request_timeout = config.getfloat(
            'ace_request_timeout', 5., above=0.)
        self.ace_reconnect_timeout = config.getfloat(
            'ace_reconnect_timeout', 30., above=0.)
        self.ace_reconnect_stable_time = config.getfloat(
            'ace_reconnect_stable_time', 3., above=0.)
        self.ace_motion_chunk_length = config.getfloat(
            'ace_motion_chunk_length', 100., above=0.)
        self.ace_resume_max_retries = config.getint(
            'ace_resume_max_retries', 1)
        if self.ace_resume_max_retries < 0:
            raise config.error('ace_resume_max_retries must be >= 0')
        self.auto_toolchange_recovery = config.getboolean(
            'auto_toolchange_recovery', True)
        self.auto_toolchange_recovery_max_retries = config.getint(
            'auto_toolchange_recovery_max_retries', 3)
        if self.auto_toolchange_recovery_max_retries < 0:
            raise config.error(
                'auto_toolchange_recovery_max_retries must be >= 0')
        self.auto_resume_after_ace_reconnect = config.getboolean(
            'auto_resume_after_ace_reconnect', True)
        # self.extruder_to_blade_length = config.getint('extruder_to_blade', None)
        self.bowden_tube_length = config.getint('bowden_tube_length', 1000)
        self.five_way_parking_margin = config.getfloat(
            'five_way_parking_margin', 20., minval=0.)
        self.calibration_speed = config.getfloat(
            'calibration_speed', 25., above=0.)
        self.calibration_chunk_length = config.getfloat(
            'calibration_chunk_length', 5., above=0.)
        self.calibration_final_chunk_length = config.getfloat(
            'calibration_final_chunk_length', 2., above=0.)
        self._calibration_preview = None
        self._calibration_phase = 'idle'
        self._calibration_last_error = ''
        self._motion_owner = None
        self._load_calibration_record()

        self.max_dryer_temperature = config.getint('max_dryer_temperature', 55)

        # Endless spool configuration - load from persistent variables if available
        saved_endless_spool_enabled = self.variables.get('ace_endless_spool_enabled', False)
        
        self.endless_spool_enabled = config.getboolean('endless_spool', saved_endless_spool_enabled)
        self.endless_spool_in_progress = False
        self.endless_spool_runout_detected = False

        saved_auto_drying = self.variables.get(
            'ace_auto_drying_enabled', False)
        self.auto_drying_enabled = (
            saved_auto_drying is True
            or str(saved_auto_drying).strip().lower() in ('1', 'true', 'yes'))
        self.auto_drying_active = False
        self.auto_drying_owned_by_auto = False
        self.auto_drying_suppressed_for_job = False
        self.auto_drying_temperature = 0
        self.auto_drying_reason = 'EMPTY'
        self.auto_drying_print_state = 'standby'
        self.auto_drying_last_error = ''
        self.auto_drying_notice_id = 0
        self.auto_drying_notice_message = ''
        self._auto_drying_job_active = False
        self._auto_drying_print_samples = 0
        self._auto_drying_pending_action = None
        self._auto_drying_pending_token = None
        self._auto_drying_stop_required = False
        self._auto_drying_temperature_ceiling = 0
        self._auto_drying_notices_seen = set()
        self._auto_drying_retry_count = 0
        self._auto_drying_next_retry = 0.
        self._auto_drying_max_retries = 3

        self._callback_map = {}
        self._inflight_request = None
        self._priority_queue = None
        self._queue = None
        self._main_queue = None
        self.writer_timer = None
        self.reader_timer = None
        self.connect_timer = None
        self.endless_spool_timer = None
        self.auto_drying_timer = None
        self._connection_generation = 0
        self._connection_state = 'disconnected'
        self._connected_since = None
        self._last_status_time = None
        self._last_status_generation = -1
        self._last_disconnect_reason = None
        self._pending_feed_assist_restore = -1
        self._klippy_shutdown = False
        # This context is intentionally in-memory only.  A Klipper restart
        # must never replay a physical ACE action from stale saved variables.
        self._toolchange_context = None
        self._toolchange_last_error = None
        self._pending_toolchange_recovery = None
        self._toolchange_recovery_timer = None
        self._connection_pause_owned = False
        self.park_hit_count = 5
        self._feed_assist_index = -1
        self._request_id = 0
        self._last_assist_count = 0
        self._assist_hit_count = 0
        self._park_in_progress = False
        self._park_is_toolchange = False
        self._park_previous_tool = -1
        self._park_index = -1
        self.endstops = {}

        # Default data to prevent exceptions
        self._info = {
            'status': 'disconnected',
            'dryer': {
                'status': 'stop',
                'target_temp': 0,
                'duration': 0,
                'remain_time': 0
            },
            'temp': 0,
            'enable_rfid': 1,
            'fan_speed': 7000,
            'feed_assist_count': 0,
            'cont_assist_time': 0.0,
            'slots': [
                {
                    'index': 0,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                },
                {
                    'index': 1,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                },
                {
                    'index': 2,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                },
                {
                    'index': 3,
                    'status': 'empty',
                    'sku': '',
                    'type': '',
                    'color': [0, 0, 0]
                }
            ]
        }

        # Add inventory for 4 slots - load from persistent variables if available
        saved_inventory = self.variables.get('ace_inventory', None)
        if saved_inventory:
            self.inventory = saved_inventory
        else:
            self.inventory = [
                {"status": "empty", "color": [0, 0, 0], "material": "", "temp": 0} for _ in range(4)
            ]
        # Register inventory commands
        self.gcode.register_command(
            'ACE_SET_SLOT', self.cmd_ACE_SET_SLOT,
            desc="Set slot inventory: INDEX= COLOR= MATERIAL= TEMP= | Set status to empty with EMPTY=1"
        )
        self.gcode.register_command(
            'ACE_QUERY_SLOTS', self.cmd_ACE_QUERY_SLOTS,
            desc="Query all slot inventory as JSON"
        )

        self._create_mmu_sensor(config, extruder_sensor_pin, "extruder_sensor")
        self._create_mmu_sensor(config, toolhead_sensor_pin, "toolhead_sensor")
        self.printer.register_event_handler('klippy:ready', self._handle_ready)
        self.printer.register_event_handler('klippy:disconnect', self._handle_disconnect)
        self.gcode.register_command(
            'ACE_DEBUG', self.cmd_ACE_DEBUG,
            desc='self.cmd_ACE_DEBUG_help')
        self.gcode.register_command(
            'ACE_START_DRYING', self.cmd_ACE_START_DRYING,
            desc=self.cmd_ACE_START_DRYING_help)
        self.gcode.register_command(
            'ACE_STOP_DRYING', self.cmd_ACE_STOP_DRYING,
            desc=self.cmd_ACE_STOP_DRYING_help)
        self.gcode.register_command(
            'ACE_ENABLE_AUTO_DRYING', self.cmd_ACE_ENABLE_AUTO_DRYING,
            desc=self.cmd_ACE_ENABLE_AUTO_DRYING_help)
        self.gcode.register_command(
            'ACE_DISABLE_AUTO_DRYING', self.cmd_ACE_DISABLE_AUTO_DRYING,
            desc=self.cmd_ACE_DISABLE_AUTO_DRYING_help)
        self.gcode.register_command(
            'ACE_ENABLE_FEED_ASSIST', self.cmd_ACE_ENABLE_FEED_ASSIST,
            desc=self.cmd_ACE_ENABLE_FEED_ASSIST_help)
        self.gcode.register_command(
            'ACE_DISABLE_FEED_ASSIST', self.cmd_ACE_DISABLE_FEED_ASSIST,
            desc=self.cmd_ACE_DISABLE_FEED_ASSIST_help)
        self.gcode.register_command(
            'ACE_FEED', self.cmd_ACE_FEED,
            desc=self.cmd_ACE_FEED_help)
        self.gcode.register_command(
            'ACE_RETRACT', self.cmd_ACE_RETRACT,
            desc=self.cmd_ACE_RETRACT_help)
        self.gcode.register_command(
            'ACE_CHANGE_TOOL', self.cmd_ACE_CHANGE_TOOL,
            desc=self.cmd_ACE_CHANGE_TOOL_help)
        self.gcode.register_command(
            'ACE_ENABLE_ENDLESS_SPOOL', self.cmd_ACE_ENABLE_ENDLESS_SPOOL,
            desc=self.cmd_ACE_ENABLE_ENDLESS_SPOOL_help)
        self.gcode.register_command(
            'ACE_DISABLE_ENDLESS_SPOOL', self.cmd_ACE_DISABLE_ENDLESS_SPOOL,
            desc=self.cmd_ACE_DISABLE_ENDLESS_SPOOL_help)
        self.gcode.register_command(
            'ACE_ENDLESS_SPOOL_STATUS', self.cmd_ACE_ENDLESS_SPOOL_STATUS,
            desc=self.cmd_ACE_ENDLESS_SPOOL_STATUS_help)
        self.gcode.register_command(
            'ACE_SAVE_INVENTORY', self.cmd_ACE_SAVE_INVENTORY,
            desc=self.cmd_ACE_SAVE_INVENTORY_help)
        self.gcode.register_command(
            'ACE_TEST_RUNOUT_SENSOR', self.cmd_ACE_TEST_RUNOUT_SENSOR,
            desc=self.cmd_ACE_TEST_RUNOUT_SENSOR_help)
        self.gcode.register_command(
            'ACE_CHANGE_SPOOL', self.cmd_ACE_CHANGE_SPOOL,
            desc=self.cmd_ACE_CHANGE_SPOOL_help)
        self.gcode.register_command(
            'ACE_GET_CURRENT_INDEX', self.cmd_ACE_GET_CURRENT_INDEX,
            desc=self.cmd_ACE_GET_CURRENT_INDEX_help)
        self.gcode.register_command(
            'ACE_TOOLCHANGE_STATUS', self.cmd_ACE_TOOLCHANGE_STATUS,
            desc=self.cmd_ACE_TOOLCHANGE_STATUS_help)
        self.gcode.register_command(
            'ACE_ABORT_TOOLCHANGE', self.cmd_ACE_ABORT_TOOLCHANGE,
            desc=self.cmd_ACE_ABORT_TOOLCHANGE_help)
        self.gcode.register_command(
            'ACE_CALIBRATE_FEED', self.cmd_ACE_CALIBRATE_FEED,
            desc=self.cmd_ACE_CALIBRATE_FEED_help)
        self.gcode.register_command(
            'ACE_CALIBRATE_RETRACT', self.cmd_ACE_CALIBRATE_RETRACT,
            desc=self.cmd_ACE_CALIBRATE_RETRACT_help)
        self.gcode.register_command(
            'ACE_CALIBRATION_SAVE', self.cmd_ACE_CALIBRATION_SAVE,
            desc=self.cmd_ACE_CALIBRATION_SAVE_help)
        self.gcode.register_command(
            'ACE_CALIBRATION_CANCEL', self.cmd_ACE_CALIBRATION_CANCEL,
            desc=self.cmd_ACE_CALIBRATION_CANCEL_help)
        self.gcode.register_command(
            'ACE_PRELOAD', self.cmd_ACE_PRELOAD,
            desc=self.cmd_ACE_PRELOAD_help)

    def _load_slot_positions(self):
        saved = self.variables.get('ace_slot_positions')
        if isinstance(saved, str):
            try:
                saved = json.loads(saved)
            except (TypeError, ValueError):
                saved = None
        if (isinstance(saved, list) and len(saved) == 4
                and all(position in SLOT_POSITION_VALUES
                        for position in saved)):
            self.slot_positions = list(saved)
            return

        positions = ['unknown'] * 4
        try:
            current_index = int(self.variables.get('ace_current_index', -1))
        except (TypeError, ValueError):
            current_index = -1
        legacy = str(
            self.variables.get('ace_filament_pos', '') or '').strip().lower()
        legacy_map = {
            'nozzle': 'nozzle',
            'toolhead': 'toolhead',
            'bowden': 'preload_parked_estimated',
            'spliter': 'preload_parked_estimated',
            'splitter': 'preload_parked_estimated',
        }
        if 0 <= current_index < 4 and legacy in legacy_map:
            positions[current_index] = legacy_map[legacy]
        self.slot_positions = positions

    def _save_json_variable(self, name, value):
        stored = copy.deepcopy(value)
        self.variables[name] = stored
        encoded = json.dumps(stored, separators=(',', ':'))
        self.gcode.run_script_from_command(
            "SAVE_VARIABLE VARIABLE=%s VALUE='%s'" % (name, encoded))

    def _set_slot_position(self, index, position, persist=True):
        if index < 0 or index >= 4:
            raise ValueError('ACE slot index must be between 0 and 3')
        if position not in SLOT_POSITION_VALUES:
            raise ValueError('ACE slot position is invalid')
        self.slot_positions[index] = position
        if persist:
            self._save_json_variable(
                'ace_slot_positions', self.slot_positions)

    def _load_calibration_record(self):
        record = self.variables.get('ace_calibration')
        if isinstance(record, str):
            try:
                record = json.loads(record)
            except (TypeError, ValueError):
                record = None
        self.calibration_record = (
            copy.deepcopy(record) if isinstance(record, dict) else None)
        self.calibration_valid = calibration_is_valid(
            self.calibration_record,
            self.bowden_tube_length,
            self.five_way_parking_margin)

    def _save_calibration_record(self, record):
        if not calibration_is_valid(
                record,
                self.bowden_tube_length,
                self.five_way_parking_margin):
            raise ValueError(
                'ACE calibration record does not match current config')
        self.calibration_record = copy.deepcopy(record)
        self.calibration_valid = True
        self._save_json_variable(
            'ace_calibration', self.calibration_record)

    def _print_state(self):
        print_stats = self.printer.lookup_object('print_stats', None)
        if print_stats is None:
            return 'unknown'
        try:
            return str(print_stats.get_status(
                self.reactor.monotonic()).get('state') or '').lower()
        except Exception:
            return 'unknown'

    def _acquire_motion(self, owner):
        if self._motion_owner is not None:
            raise RuntimeError(
                'ACE：%s 正在运行，不能同时启动 %s' % (
                    self._motion_owner, owner))
        self._motion_owner = owner

    def _release_motion(self, owner):
        if self._motion_owner == owner:
            self._motion_owner = None

    def _require_calibration_preflight(self):
        state = self._print_state()
        if state in ('printing', 'paused'):
            raise RuntimeError('ACE：打印或暂停期间禁止距离标定')
        if not self._connected or self._info.get('status') != 'ready':
            raise RuntimeError('ACE：设备未连接或尚未就绪')
        if (self._sensor_present('extruder_sensor')
                or self._sensor_present('toolhead_sensor')):
            raise RuntimeError('ACE：标定前上下传感器必须均无料')

    def _save_current_index(self, index):
        self.variables['ace_current_index'] = int(index)
        self.gcode.run_script_from_command(
            'SAVE_VARIABLE VARIABLE=ace_current_index VALUE=%d' % int(index))

    def _calibrate_feed(self, index):
        max_distance = (
            float(self.toolchange_load_length)
            + float(self.feed_slip_compensation_length))
        completed = 0.
        self._calibration_preview = None
        self._calibration_phase = 'feeding'
        self._calibration_last_error = ''
        try:
            while completed < max_distance:
                if self._sensor_present('extruder_sensor'):
                    upper_bound = completed
                    break
                step = min(
                    float(self.calibration_chunk_length),
                    max_distance - completed)
                result = self._feed(
                    index, step, self.calibration_speed,
                    stop_sensor='extruder_sensor')
                if result.get('uncertain'):
                    raise RuntimeError(
                        'ACE：标定送料连接状态不确定，未重放该分段')
                triggered = (
                    result.get('stopped_by_sensor')
                    or self._sensor_present('extruder_sensor'))
                if triggered:
                    upper_bound = completed + step
                    break
                completed += step
                self.wait_ace_ready()
            else:
                raise FilamentFeedError(
                    'ACE：达到标定最大距离 %.1f mm 后上方传感器仍未触发'
                    % max_distance)

            if upper_bound <= 0:
                raise RuntimeError('ACE：上方传感器在送料前已触发')
            parking_distance = calculate_parking_distance(
                upper_bound,
                self.bowden_tube_length,
                self.five_way_parking_margin,
                max_distance)
            preview = {
                'phase': 'feed_complete',
                'source_slot': int(index),
                'feed_completed': completed,
                'feed_upper_bound': upper_bound,
                'parking_distance': parking_distance,
                'bowden_tube_length': float(self.bowden_tube_length),
                'parking_margin': float(self.five_way_parking_margin),
            }
            self._calibration_preview = preview
            self._calibration_phase = 'feed_complete'
            self._set_slot_position(index, 'upper_sensor')
            self._save_current_index(index)
            return copy.deepcopy(preview)
        except Exception as exc:
            self._calibration_preview = None
            self._calibration_phase = 'failed'
            self._calibration_last_error = str(exc)
            self._set_slot_position(index, 'unknown', persist=False)
            raise

    cmd_ACE_CALIBRATE_FEED_help = (
        'Calibrate shared ACE feed distance - INDEX= CONFIRM=1')

    def cmd_ACE_CALIBRATE_FEED(self, gcmd):
        index = gcmd.get_int('INDEX')
        if index < 0 or index >= 4:
            raise gcmd.error('ACE：槽位编号必须为 0-3')
        if gcmd.get_int('CONFIRM', 0) != 1:
            gcmd.respond_info(
                'ACE：将使用 T%d 以 %.1f mm/s 分段送料；确认后请执行 '
                'ACE_CALIBRATE_FEED INDEX=%d CONFIRM=1' % (
                    index, self.calibration_speed, index))
            return
        try:
            self._require_calibration_preflight()
            self._acquire_motion('距离送料标定')
            preview = self._calibrate_feed(index)
            gcmd.respond_info(
                'ACE：送料标定完成，已确认 %.1f mm，上界 %.1f mm；'
                '请确认后执行回料标定' % (
                    preview['feed_completed'],
                    preview['feed_upper_bound']))
        except Exception as exc:
            raise gcmd.error(str(exc))
        finally:
            self._release_motion('距离送料标定')

    cmd_ACE_CALIBRATE_RETRACT_help = (
        'Calibrate shared ACE retract distance - CONFIRM=1')

    def _calibrate_retract(self):
        preview = self._calibration_preview
        if (not isinstance(preview, dict)
                or preview.get('phase') != 'feed_complete'):
            raise RuntimeError('ACE：请先完成送料标定')
        index = int(preview['source_slot'])
        target = float(preview['parking_distance'])
        retracted = 0.
        sensor_clear_completed = None
        sensor_clear_upper_bound = None
        self._calibration_phase = 'retracting'
        self._calibration_last_error = ''
        try:
            if not self._sensor_present('extruder_sensor'):
                raise RuntimeError('ACE：回料标定开始前上方传感器必须有料')
            if self._sensor_present('toolhead_sensor'):
                raise RuntimeError('ACE：回料标定前下方传感器必须无料')

            while self._sensor_present('extruder_sensor'):
                remaining = target - retracted
                if remaining <= 0:
                    raise RuntimeError(
                        'ACE：达到估算停车距离后上方传感器仍未解除')
                step = min(float(self.calibration_chunk_length), remaining)
                result = self._retract(index, step, self.calibration_speed)
                if result.get('uncertain'):
                    raise RuntimeError(
                        'ACE：标定回料连接状态不确定，未重放该分段')
                if not self._sensor_present('extruder_sensor'):
                    sensor_clear_completed = retracted
                    sensor_clear_upper_bound = retracted + step
                retracted += step
                self.wait_ace_ready()

            if sensor_clear_upper_bound is None:
                raise RuntimeError('ACE：未能记录上方传感器解除距离')

            while retracted < target:
                remaining = target - retracted
                chunk = (
                    self.calibration_final_chunk_length
                    if remaining <= 20. else self.calibration_chunk_length)
                step = min(float(chunk), remaining)
                result = self._retract(index, step, self.calibration_speed)
                if result.get('uncertain'):
                    raise RuntimeError(
                        'ACE：停车回料连接状态不确定，未重放该分段')
                retracted += step
                self.wait_ace_ready()

            if (self._sensor_present('extruder_sensor')
                    or self._sensor_present('toolhead_sensor')):
                raise RuntimeError('ACE：回料结束后上下传感器未全部清除')

            preview.update({
                'phase': 'retract_complete',
                'sensor_clear_completed': sensor_clear_completed,
                'sensor_clear_upper_bound': sensor_clear_upper_bound,
                'sensor_clear_distance': sensor_clear_upper_bound,
                'retract_distance': retracted,
            })
            self._calibration_preview = preview
            self._calibration_phase = 'retract_complete'
            self._set_slot_position(
                index, 'preload_parked_estimated')
            self._save_current_index(-1)
            return copy.deepcopy(preview)
        except Exception as exc:
            self._calibration_preview = None
            self._calibration_phase = 'failed'
            self._calibration_last_error = str(exc)
            self._set_slot_position(index, 'unknown', persist=False)
            raise

    def cmd_ACE_CALIBRATE_RETRACT(self, gcmd):
        preview = self._calibration_preview
        if (not isinstance(preview, dict)
                or preview.get('phase') != 'feed_complete'):
            raise gcmd.error('ACE：请先完成送料标定')
        if gcmd.get_int('CONFIRM', 0) != 1:
            gcmd.respond_info(
                'ACE：将把 T%d 回收到估算预停放位置 %.1f mm；'
                '确认后请执行 ACE_CALIBRATE_RETRACT CONFIRM=1' % (
                    preview['source_slot'], preview['parking_distance']))
            return
        try:
            state = self._print_state()
            if state in ('printing', 'paused'):
                raise RuntimeError('ACE：打印或暂停期间禁止距离标定')
            if not self._connected or self._info.get('status') != 'ready':
                raise RuntimeError('ACE：设备未连接或尚未就绪')
            self._acquire_motion('距离回料标定')
            result = self._calibrate_retract()
            gcmd.respond_info(
                'ACE：回料标定完成，上方传感器解除上界 %.1f mm，'
                '估算停车距离 %.1f mm；请确认后保存' % (
                    result['sensor_clear_upper_bound'],
                    result['retract_distance']))
        except Exception as exc:
            raise gcmd.error(str(exc))
        finally:
            self._release_motion('距离回料标定')

    cmd_ACE_CALIBRATION_SAVE_help = (
        'Save the completed ACE calibration preview - CONFIRM=1')

    def cmd_ACE_CALIBRATION_SAVE(self, gcmd):
        preview = self._calibration_preview
        if (not isinstance(preview, dict)
                or preview.get('phase') != 'retract_complete'):
            raise gcmd.error('ACE：请先完成送料和回料标定')
        if gcmd.get_int('CONFIRM', 0) != 1:
            gcmd.respond_info(
                'ACE：待保存送料上界 %.1f mm、停车距离 %.1f mm；'
                '确认后请执行 ACE_CALIBRATION_SAVE CONFIRM=1' % (
                    preview['feed_upper_bound'],
                    preview['parking_distance']))
            return
        record = copy.deepcopy(preview)
        record.update({
            'format_version': CALIBRATION_FORMAT_VERSION,
            'valid': True,
            'measured_at': time.time(),
        })
        try:
            self._save_calibration_record(record)
        except Exception as exc:
            raise gcmd.error(str(exc))
        self._calibration_phase = 'saved'
        self._calibration_preview['phase'] = 'saved'
        gcmd.respond_info('ACE：距离标定结果已保存')

    cmd_ACE_CALIBRATION_CANCEL_help = 'Discard the in-memory calibration preview'

    def cmd_ACE_CALIBRATION_CANCEL(self, gcmd):
        self._calibration_preview = None
        self._calibration_phase = 'idle'
        self._calibration_last_error = ''
        gcmd.respond_info('ACE：已取消未保存的距离标定结果')

    def _cold_extruder_move(self, length, speed):
        self.gcode.run_script_from_command(
            'FORCE_MOVE STEPPER=extruder DISTANCE=%.3f VELOCITY=%.3f\nM400'
            % (float(length), float(speed)))

    def _preload_feed_limit(self, index):
        if (self.slot_positions[index] == 'preload_parked_estimated'
                and calibration_is_valid(
                    self.calibration_record,
                    self.bowden_tube_length,
                    self.five_way_parking_margin)):
            return float(self.calibration_record['parking_distance'])
        return float(self.toolchange_load_length)

    def _require_preload_preflight(self, index):
        state = self._print_state()
        if state in ('printing', 'paused'):
            raise RuntimeError('ACE：打印或暂停期间禁止冷态预装载')
        if not self._connected or self._info.get('status') != 'ready':
            raise RuntimeError('ACE：设备未连接或尚未就绪')
        slots = self._info.get('slots') or []
        if len(slots) <= index or slots[index].get('status') != 'ready':
            raise RuntimeError('ACE：目标槽位 T%d 未就绪' % index)

        current = int(self.variables.get('ace_current_index', -1))
        upper = self._sensor_present('extruder_sensor')
        lower = self._sensor_present('toolhead_sensor')
        current_position = (
            self.slot_positions[current]
            if 0 <= current < 4 else 'unknown')
        if lower and current_position in (
                'nozzle', 'unknown', 'internal_or_unknown'):
            raise RuntimeError(
                'ACE：下方传感器有料且位置不可信，禁止冷态回抽；'
                '请先加热并执行安全卸料')
        if (upper or lower) and not 0 <= current < 4:
            raise RuntimeError(
                'ACE：传感器检测到耗材但当前槽位未知，禁止猜测槽位')
        if lower and current_position != 'toolhead':
            raise RuntimeError(
                'ACE：下方传感器状态与保存位置矛盾，禁止冷态回抽')
        if (upper and current_position not in ('upper_sensor', 'toolhead')):
            raise RuntimeError(
                'ACE：上方传感器状态与保存位置矛盾，禁止猜测回抽距离')

    def _clear_preload_path(self):
        upper = self._sensor_present('extruder_sensor')
        lower = self._sensor_present('toolhead_sensor')
        if not upper and not lower:
            return

        current = int(self.variables.get('ace_current_index', -1))
        if not 0 <= current < 4:
            raise RuntimeError('ACE：清道回抽缺少可信的当前槽位')

        try:
            cold_retracted = 0.
            while self._sensor_present('toolhead_sensor'):
                if cold_retracted >= self.toolhead_sensor_max_feed_length:
                    raise RuntimeError(
                        'ACE：冷态反向清道 %.1f mm 后下方传感器仍未解除'
                        % cold_retracted)
                step = min(
                    self.toolhead_feed_slow_step,
                    self.toolhead_sensor_max_feed_length - cold_retracted)
                self._cold_extruder_move(
                    -step, self.toolhead_feed_slow_speed)
                cold_retracted += step

            valid_calibration = calibration_is_valid(
                self.calibration_record,
                self.bowden_tube_length,
                self.five_way_parking_margin)
            if self._sensor_present('extruder_sensor'):
                if self._feed_assist_index == current:
                    self._disable_feed_assist(
                        current, allow_reconnect=False)
                retract_distance = (
                    float(self.calibration_record['parking_distance'])
                    if valid_calibration
                    else float(self.toolchange_retract_length))
                self._retract_in_chunks(
                    current,
                    retract_distance,
                    self.retract_fast_speed,
                    'PRELOAD_CLEAR')

            if (self._sensor_present('extruder_sensor')
                    or self._sensor_present('toolhead_sensor')):
                raise RuntimeError(
                    'ACE：清道回抽结束后上下传感器未全部清除')

            self._set_slot_position(
                current,
                'preload_parked_estimated'
                if valid_calibration else 'internal_or_unknown')
            self._save_current_index(-1)
        except Exception:
            self._set_slot_position(current, 'unknown')
            raise

    def _preload_to_toolhead(self, index):
        self.wait_ace_ready()
        if not self._sensor_present('extruder_sensor'):
            feed_limit = self._preload_feed_limit(index)
            self._feed_until_sensor(
                index,
                'extruder_sensor',
                feed_limit,
                self.feed_fast_speed,
                'ACE：冷态预装载送料 %.1f mm 后上方传感器仍未触发')
        if not self._sensor_present('extruder_sensor'):
            raise FilamentFeedError('ACE：冷态预装载未确认上方传感器')

        self._set_slot_position(index, 'upper_sensor')
        self._save_current_index(index)
        self.wait_ace_ready()
        self._enable_feed_assist(index)

        moved = 0.
        while not self._sensor_present('toolhead_sensor'):
            if moved >= self.toolhead_sensor_max_feed_length:
                raise FilamentFeedError(
                    'ACE：冷态挤出机送料 %.1f mm 后下方传感器仍未触发'
                    % moved)
            remaining = self.toolhead_sensor_max_feed_length - moved
            if moved < self.toolhead_feed_fast_length:
                step = min(
                    self.toolhead_feed_fast_step,
                    self.toolhead_feed_fast_length - moved,
                    remaining)
                speed = self.toolhead_feed_fast_speed
            else:
                step = min(self.toolhead_feed_slow_step, remaining)
                speed = self.toolhead_feed_slow_speed
            self._cold_extruder_move(step, speed)
            moved += step

        self._set_slot_position(index, 'toolhead')
        self._save_current_index(index)
        return moved

    cmd_ACE_PRELOAD_help = (
        'Cold preload one ACE slot to the lower sensor - INDEX= CONFIRM=1')

    def cmd_ACE_PRELOAD(self, gcmd):
        index = gcmd.get_int('INDEX')
        if index < 0 or index >= 4:
            raise gcmd.error('ACE：槽位编号必须为 0-3')
        if gcmd.get_int('CONFIRM', 0) != 1:
            gcmd.respond_info(
                'ACE：将冷态预装载 T%d，只送到下方传感器；确认后请执行 '
                'ACE_PRELOAD INDEX=%d CONFIRM=1' % (index, index))
            return

        target_motion_started = False
        try:
            self._require_preload_preflight(index)
            self._acquire_motion('冷态预装载')
            self._clear_preload_path()
            target_motion_started = True
            moved = self._preload_to_toolhead(index)
            gcmd.respond_info(
                'ACE：T%d 冷态预装载完成，挤出机送料 %.1f mm，'
                '已停在下方传感器' % (index, moved))
        except Exception as exc:
            if target_motion_started:
                self._set_slot_position(index, 'unknown')
            try:
                if self._connected and self._feed_assist_index == index:
                    self._disable_feed_assist(index, allow_reconnect=False)
            except Exception:
                logging.exception('ACE: Failed to stop preload feed assist')
            raise gcmd.error(str(exc))
        finally:
            self._release_motion('冷态预装载')


    def _calc_crc(self, buffer):
        _crc = 0xffff
        for byte in buffer:
            data = byte
            data ^= _crc & 0xff
            data ^= (data & 0x0f) << 4
            _crc = ((data << 8) | (_crc >> 8)) ^ (data >> 4) ^ (data << 3)
        return _crc

    def _send_request(self, request):
        if not 'id' in request:
            request['id'] = self._request_id
            self._request_id += 1

        payload = json.dumps(request)
        payload = bytes(payload, 'utf-8')

        data = bytes([0xFF, 0xAA])
        data += struct.pack('<H', len(payload))
        data += payload
        data += struct.pack('<H', self._calc_crc(payload))
        data += bytes([0xFE])
        self._serial.write(data)
        return True

    def _safe_unregister_timer(self, timer):
        if timer is None:
            return
        try:
            self.reactor.unregister_timer(timer)
        except Exception:
            # Klipper may already be unregistering the timer during shutdown.
            pass

    def _is_serial_open(self):
        if self._serial is None:
            return False
        state = getattr(self._serial, 'is_open', None)
        if state is not None:
            return bool(state)
        return bool(self._serial.isOpen())

    def _finish_request_token(self, token, response=None, reason=None):
        if not token:
            return
        token['response'] = response
        token['reason'] = reason
        token['lost'] = reason is not None
        token['done'] = True

    def _fail_inflight_request(self, reason):
        """Finish the in-flight request without replaying its physical action."""
        token = self._inflight_request
        self._inflight_request = None
        self.lock = False
        if token:
            request_id = token.get('id')
            if request_id is not None:
                self._callback_map.pop(request_id, None)
            self._finish_request_token(token, reason=reason)

    def _cancel_queued_requests(self, reason):
        for request_queue in (self._priority_queue, self._queue):
            if request_queue is None:
                continue
            while True:
                try:
                    task = request_queue.get_nowait()
                except queue.Empty:
                    break
                token = task.get('token') if isinstance(task, dict) else None
                self._finish_request_token(token, reason=reason)

    def _schedule_reconnect(self, delay=0.5):
        if self._klippy_shutdown or self.connect_timer is not None:
            return
        self.connect_timer = self.reactor.register_timer(
            self._connect, self.reactor.monotonic() + delay)

    def _mark_connection_lost(self, reason):
        inflight_operation = ''
        if self._inflight_request is not None:
            inflight_operation = self._inflight_request.get('operation', '')
        self._connected = False
        self._connection_state = 'disconnected'
        self._connected_since = None
        self._last_disconnect_reason = reason
        self._connection_generation += 1
        self._info['status'] = 'disconnected'
        self._last_status_generation = -1
        self.read_buffer = bytearray()
        if (self._feed_assist_index >= 0
                and self._toolchange_context is None
                and inflight_operation != 'stop feed assist'):
            self._pending_feed_assist_restore = self._feed_assist_index
            self._feed_assist_index = -1
        elif inflight_operation == 'stop feed assist':
            self._feed_assist_index = -1
        self._fail_inflight_request(reason)
        self._callback_map.clear()
        self._cancel_queued_requests(reason)

    def _wait_for_request(self, token, timeout=None, poll_callback=None):
        """Wait for one response while allowing Klipper timers to run."""
        if token is None:
            raise self.printer.command_error('ACE：请求未能进入队列')
        timeout = self.ace_request_timeout if timeout is None else timeout
        deadline = self.reactor.monotonic() + timeout
        while not token.get('done'):
            if poll_callback is not None:
                poll_callback()
            if self.reactor.monotonic() >= deadline:
                return False
            self.reactor.pause(self.reactor.monotonic() + .05)
        return True

    def _request_timeout_for_inflight(self):
        timeout = self.ace_request_timeout
        token = self._inflight_request
        if token is None:
            return timeout
        request = token.get('request', {})
        params = request.get('params', {})
        if request.get('method') in ('feed_filament', 'unwind_filament'):
            try:
                length = float(params.get('length', 0))
                speed = max(float(params.get('speed', 1)), 1.)
                timeout = max(timeout, length / speed + 2.)
            except (TypeError, ValueError):
                pass
        return timeout

    def _wait_for_stable_connection(self, timeout=None):
        """Wait for a fresh status heartbeat after a serial reconnect."""
        timeout = self.ace_reconnect_timeout if timeout is None else timeout
        deadline = self.reactor.monotonic() + timeout
        while self.reactor.monotonic() < deadline:
            now = self.reactor.monotonic()
            if (self._connected and self._connected_since is not None
                    and self._last_status_generation == self._connection_generation
                    and self._last_status_time is not None
                    and now - self._connected_since >= self.ace_reconnect_stable_time):
                return True
            self.reactor.pause(now + .1)
        return False

    def _wait_ready_after_reconnect(self):
        if not self._wait_for_stable_connection():
            raise self.printer.command_error(
                'ACE：%.1f 秒内未能稳定重连' %
                self.ace_reconnect_timeout)
        wait_start = self.reactor.monotonic()
        while self._info.get('status') != 'ready':
            if self.reactor.monotonic() - wait_start >= self.ace_ready_timeout:
                raise self.printer.command_error(
                    'ACE：重连后 %.1f 秒内未恢复就绪' %
                    self.ace_ready_timeout)
            self.reactor.pause(self.reactor.monotonic() + .1)

    def _request_status_callback(self, response):
        if response and isinstance(response.get('result'), dict):
            self._info = response['result']
            self._connection_state = 'connected'
            self._last_status_time = self.reactor.monotonic()
            self._last_status_generation = self._connection_generation
            self._maybe_restore_feed_assist()

    def _maybe_restore_feed_assist(self):
        """Restore assist only after a fresh, stable heartbeat and no toolchange."""
        if self._pending_feed_assist_restore < 0:
            return
        if self._toolchange_context is not None or self._park_in_progress:
            return
        if not self._connected or self._connected_since is None:
            return
        if (self.reactor.monotonic() - self._connected_since
                < self.ace_reconnect_stable_time):
            return
        index = self._pending_feed_assist_restore
        current_index = self.variables.get('ace_current_index', -1)
        upper_present = self._sensor_present('extruder_sensor')
        lower_present = self._sensor_present('toolhead_sensor')
        if current_index != index or not (upper_present or lower_present):
            self._pending_feed_assist_restore = -1
            self._feed_assist_index = -1
            self.gcode.respond_info(
                'ACE：保存的槽位或物理传感器状态不一致，已跳过恢复辅助送料')
            return
        self._pending_feed_assist_restore = -1
        try:
            self._enable_feed_assist(index, allow_reconnect=False)
        except Exception as exc:
            self.gcode.respond_info(
                'ACE：重连后恢复辅助送料失败：%s' % exc)

    def _is_transport_error(self, error):
        """Classify serial failures without treating filament faults as transport errors."""
        message = str(error).lower()
        transport_words = (
            'ace is disconnected', 'connection lost', 'connection timeout',
            'request timeout', 'serial', 'no response', 'reconnecting')
        if any(word in message for word in transport_words):
            return True
        return self._connection_state == 'disconnected' and not self._connected

    def _cancel_toolchange_recovery(self):
        self._pending_toolchange_recovery = None
        self._safe_unregister_timer(self._toolchange_recovery_timer)
        self._toolchange_recovery_timer = None

    def _queue_toolchange_recovery(self, tool, previous_tool, error,
                                   resume_after_success=False):
        """Queue one sensor-reconciled T<n> retry after a serial disconnect."""
        if not self.auto_toolchange_recovery:
            return False
        pending = self._pending_toolchange_recovery
        attempts = pending.get('attempts', 0) if pending else 0
        if pending:
            resume_after_success = (
                resume_after_success
                or pending.get('resume_after_success', False))
        if attempts >= self.auto_toolchange_recovery_max_retries:
            self.gcode.respond_info(
                'ACE：自动恢复换料已达到最大重试次数：%d 次' %
                attempts)
            return False
        context = copy.deepcopy(self._toolchange_context or {})
        self._pending_toolchange_recovery = {
            'tool': tool,
            'previous_tool': previous_tool,
            'attempts': attempts,
            'phase': context.get('phase', 'UNKNOWN'),
            'resume_after_success': resume_after_success,
            'error': str(error),
        }
        self.gcode.respond_info(
            'ACE：换料在阶段 %s 中断；等待连接稳定后根据传感器状态自动恢复'
            '（第 %d/%d 次）' % (
                context.get('phase', 'UNKNOWN'), attempts + 1,
                self.auto_toolchange_recovery_max_retries))
        if self._toolchange_recovery_timer is None:
            self._toolchange_recovery_timer = self.reactor.register_timer(
                self._toolchange_recovery_tick,
                self.reactor.monotonic() + 1.0)
        return True

    def _toolchange_recovery_tick(self, eventtime):
        pending = self._pending_toolchange_recovery
        if pending is None:
            self._toolchange_recovery_timer = None
            return self.reactor.NEVER
        if self._toolchange_context is not None or self._park_in_progress:
            return eventtime + 1.0
        if not self._connected or self._info.get('status') != 'ready':
            return eventtime + 1.0
        if (self._connected_since is None
                or self._last_status_generation != self._connection_generation
                or self._last_status_time is None
                or self.reactor.monotonic() - self._connected_since
                < self.ace_reconnect_stable_time):
            return eventtime + 1.0

        pending['attempts'] += 1
        self.gcode.respond_info(
            'ACE：已重新连接，正在根据实时传感器状态继续 T%d' %
            pending['tool'])
        self.gcode.run_script_from_command(
            'ACE_CHANGE_TOOL TOOL=%d' % pending['tool'])
        return eventtime + 1.0

    def _pause_for_toolchange_recovery(self):
        """Pause only an active print and remember that ACE owns the pause."""
        print_stats = self.printer.lookup_object('print_stats', None)
        state = ''
        if print_stats is not None:
            try:
                state = (print_stats.get_status(
                    self.reactor.monotonic()).get('state') or '').lower()
            except Exception:
                pass
        if state == 'printing':
            self.gcode.run_script_from_command('PAUSE')
            self._connection_pause_owned = True
        return self._connection_pause_owned

    def _pause_for_filament_failure(self):
        """Pause an active print without creating an automatic resume owner."""
        print_stats = self.printer.lookup_object('print_stats', None)
        state = ''
        if print_stats is not None:
            try:
                state = (print_stats.get_status(
                    self.reactor.monotonic()).get('state') or '').lower()
            except Exception:
                pass
        if state == 'printing':
            self.gcode.run_script_from_command('PAUSE')
            return True
        return state == 'paused'

    def _resume_owned_pause(self, eventtime):
        if not self._connection_pause_owned:
            return self.reactor.NEVER
        self._connection_pause_owned = False
        print_stats = self.printer.lookup_object('print_stats', None)
        state = ''
        if print_stats is not None:
            try:
                state = (print_stats.get_status(eventtime).get('state')
                         or '').lower()
            except Exception:
                pass
        if state == 'paused':
            self.gcode.run_script_from_command('RESUME')
            self.gcode.respond_info(
                'ACE：换料已自动恢复，打印已继续')
        return self.reactor.NEVER

    def _complete_toolchange_recovery(self):
        pending = self._pending_toolchange_recovery
        resume_after_success = bool(
            pending and pending.get('resume_after_success'))
        self._cancel_toolchange_recovery()
        if (resume_after_success and self.auto_resume_after_ace_reconnect
                and self._connection_pause_owned):
            self.reactor.register_timer(
                self._resume_owned_pause,
                self.reactor.monotonic() + .1)


    def _reader(self, eventtime):
        if (self.lock and self.send_time is not None
                and self.reactor.monotonic() - self.send_time
                > self._request_timeout_for_inflight()):
            self.gcode.respond_info(
                'ACE：请求等待 %.1f 秒后超时，将重连且不重复发送物理动作' %
                self._request_timeout_for_inflight())
            self._mark_connection_lost('request timeout')
            self._serial_disconnect('request timeout', already_marked=True)
            self._schedule_reconnect()
            return self.reactor.NEVER

        try:
            raw_bytes = self._serial.read(size=4096)
        except SerialException:
            self.gcode.respond_info(
                'ACE：无法与 ACE PRO 通信\n' +
                traceback.format_exc())
            self.gcode.respond_info('ACE：请检查连接并尝试重新连接')
            self._mark_connection_lost('serial read error')
            self._serial_disconnect('serial read error', already_marked=True)
            self._schedule_reconnect()
            return self.reactor.NEVER

        if not raw_bytes:
            return eventtime + 0.1
        self.read_buffer += raw_bytes

        while True:
            header = self.read_buffer.find(bytes([0xFF, 0xAA]))
            if header < 0:
                # Keep a possible first header byte for the next read.
                self.read_buffer = self.read_buffer[-1:]
                break
            if header:
                del self.read_buffer[:header]
            if len(self.read_buffer) < 4:
                break
            payload_len = struct.unpack('<H', self.read_buffer[2:4])[0]
            if payload_len > 8192:
                self.gcode.respond_info(
                    'ACE：无效数据帧长度 %d，正在重新同步' % payload_len)
                del self.read_buffer[:2]
                continue
            frame_len = 4 + payload_len + 2 + 1
            if len(self.read_buffer) < frame_len:
                break
            frame = bytes(self.read_buffer[:frame_len])
            del self.read_buffer[:frame_len]
            if frame[-1] != 0xFE:
                self.gcode.respond_info('ACE：收到无效的数据帧结束符')
                continue
            payload = frame[4:4 + payload_len]
            crc_data = frame[4 + payload_len:4 + payload_len + 2]
            crc = struct.pack('<H', self._calc_crc(payload))
            if crc_data != crc:
                self.gcode.respond_info('ACE：收到无效数据，CRC 校验失败')
                continue
            try:
                ret = json.loads(payload.decode('utf-8'))
            except (UnicodeDecodeError, ValueError) as exc:
                self.gcode.respond_info('ACE：收到无效 JSON 数据：%s' % exc)
                continue
            request_id = ret.get('id')
            entry = self._callback_map.pop(request_id, None)
            if entry is None:
                continue
            if isinstance(entry, tuple):
                callback, token = entry
            else:
                callback, token = entry, None
            if token is not None:
                self._finish_request_token(token, response=ret)
                if self._inflight_request is token:
                    self._inflight_request = None
            self.lock = False
            try:
                callback(self=self, response=ret)
            except Exception:
                logging.exception('ACE response callback failed')
            if (self._priority_queue is not None
                    and not self._priority_queue.empty()
                    and self.writer_timer is not None):
                try:
                    self.reactor.update_timer(
                        self.writer_timer, self.reactor.NOW)
                except Exception:
                    pass
        return eventtime + 0.1

    def _writer(self, eventtime):
        if self._queue is None or not self._connected:
            return eventtime + 0.5
        try:
            if self.lock:
                return eventtime + 0.1

            task = None
            if (self._priority_queue is not None
                    and not self._priority_queue.empty()):
                task = self._priority_queue.get()
            elif not self._queue.empty():
                task = self._queue.get()
            if task is None:
                request = {"method": "get_status"}
                callback = lambda self, response: self._request_status_callback(response)
                token = {
                    'request': request,
                    'callback': callback,
                    'operation': 'status',
                    'done': False,
                    'response': None,
                    'reason': None,
                    'lost': False,
                    'sent': False,
                }
            else:
                request = task['request']
                callback = task['callback']
                token = task['token']

            request_id = self._request_id
            self._request_id += 1
            request['id'] = request_id
            token['id'] = request_id
            token['generation'] = self._connection_generation
            self._callback_map[request_id] = (callback, token)
            self._inflight_request = token
            self._send_request(request)
            token['sent'] = True
            token['sent_time'] = eventtime
            self.send_time = eventtime
            self.lock = True
        except serial.serialutil.SerialException:
            logging.info('ACE error: ' + traceback.format_exc())
            self.gcode.respond_info('ACE：请检查连接并尝试重新连接')
            self._mark_connection_lost('serial write error')
            self._serial_disconnect('serial write error', already_marked=True)
            self._schedule_reconnect()
            return self.reactor.NEVER
        except Exception as exc:
            self.gcode.respond_info(str(exc))
            logging.info('ACE: Write error ' + str(exc))
            self._fail_inflight_request('write error: %s' % exc)
        return eventtime + 0.5

    def _auto_drying_slots(self):
        slots = []
        hardware_slots = self._info.get('slots') or []
        for index in range(4):
            inventory = (
                self.inventory[index] if index < len(self.inventory) else {})
            hardware = (
                hardware_slots[index]
                if index < len(hardware_slots) else {})
            inventory_status = str(
                inventory.get('status') or 'empty').strip().lower()
            hardware_status = str(
                hardware.get('status') or 'empty').strip().lower()
            loaded = (
                inventory_status != 'empty' or hardware_status != 'empty')
            slots.append({
                'status': 'ready' if loaded else 'empty',
                'material': (
                    inventory.get('material') or hardware.get('type') or ''),
            })
        return slots

    def _publish_auto_drying_notice(self, key, message, force=False):
        if not force and key in self._auto_drying_notices_seen:
            return
        self._auto_drying_notices_seen.add(key)
        self.auto_drying_notice_id += 1
        self.auto_drying_notice_message = message
        self.gcode.respond_info('ACE 自动烘干：' + message)

    def _record_auto_drying_failure(self, eventtime, message):
        self.auto_drying_last_error = message
        self._auto_drying_next_retry = eventtime + 30.0
        self._publish_auto_drying_notice(
            'ERROR_%s' % self._auto_drying_retry_count,
            message,
            force=True)

    def _clear_auto_drying_pending(self):
        action = self._auto_drying_pending_action
        self._auto_drying_pending_action = None
        self._auto_drying_pending_token = None
        return action

    def _auto_drying_can_retry(self, eventtime):
        return (
            self._auto_drying_retry_count < self._auto_drying_max_retries
            and eventtime >= self._auto_drying_next_retry)

    def _reconcile_auto_drying_pending(self, eventtime, print_state):
        token = self._auto_drying_pending_token
        if (self._auto_drying_pending_action is None or token is None
                or not token.get('done') or not token.get('lost')):
            return
        action = self._clear_auto_drying_pending()
        self._auto_drying_retry_count += 1
        self._record_auto_drying_failure(
            eventtime,
            '%s请求因连接中断未确认：%s' % (
                '启动' if action == 'start' else '停止',
                token.get('reason') or '未知原因'))
        if (action == 'stop'
                or (action == 'start' and token.get('sent')
                    and print_state in (
                        'complete', 'cancelled', 'error', 'standby'))):
            self._auto_drying_stop_required = True

    def _queue_auto_drying_start(self, temperature, eventtime):
        if self._auto_drying_pending_action is not None:
            return False
        if not self._connected:
            return False
        if not self._auto_drying_can_retry(eventtime):
            return False
        temperature = min(
            int(temperature), int(self.max_dryer_temperature))
        if temperature <= 0:
            return False
        self._auto_drying_pending_action = 'start'
        self._auto_drying_pending_token = None

        def callback(self, response):
            self._clear_auto_drying_pending()
            if response.get('code', 0) != 0:
                self._auto_drying_retry_count += 1
                self._record_auto_drying_failure(
                    self.reactor.monotonic(),
                    '启动失败：%s' % response.get('msg', '未知错误'))
                return
            self._auto_drying_retry_count = 0
            self._auto_drying_next_retry = 0.
            self.auto_drying_active = True
            self.auto_drying_owned_by_auto = True
            self.auto_drying_temperature = temperature
            self._auto_drying_temperature_ceiling = temperature
            self.auto_drying_last_error = ''
            dryer = self._info.setdefault('dryer', {})
            dryer['status'] = 'drying'
            dryer['target_temp'] = temperature
            dryer['duration'] = AUTO_DRYING_DURATION_MINUTES
            dryer['remain_time'] = AUTO_DRYING_DURATION_MINUTES
            if (self._auto_drying_stop_required
                    or not self._auto_drying_job_active
                    or not self.auto_drying_enabled
                    or self.auto_drying_suppressed_for_job):
                self._auto_drying_stop_required = True
                self._queue_auto_drying_stop(self.reactor.monotonic())
                return
            self._publish_auto_drying_notice(
                'START_%s' % self.auto_drying_reason,
                '已随打印启动，目标温度 %d°C。' % temperature,
                force=True)

        try:
            token = self.send_request(
                request={
                    'method': 'drying',
                    'params': {
                        'temp': temperature,
                        'fan_speed': 7000,
                        'duration': AUTO_DRYING_DURATION_MINUTES,
                    },
                },
                callback=callback,
                operation='自动烘干启动')
            if self._auto_drying_pending_action == 'start':
                self._auto_drying_pending_token = token
            return True
        except Exception as exc:
            self._clear_auto_drying_pending()
            self._auto_drying_retry_count += 1
            self._record_auto_drying_failure(
                eventtime, '启动失败：%s' % exc)
            return False

    def _queue_auto_drying_stop(self, eventtime, restart_temperature=0):
        if self._auto_drying_pending_action is not None:
            return False
        if not self._connected:
            return False
        if not self._auto_drying_can_retry(eventtime):
            return False
        self._auto_drying_pending_action = 'stop'
        self._auto_drying_pending_token = None
        self._auto_drying_stop_required = True

        def callback(self, response):
            self._clear_auto_drying_pending()
            if response.get('code', 0) != 0:
                self._auto_drying_retry_count += 1
                self._record_auto_drying_failure(
                    self.reactor.monotonic(),
                    '停止失败：%s' % response.get('msg', '未知错误'))
                return
            self._auto_drying_retry_count = 0
            self._auto_drying_next_retry = 0.
            self.auto_drying_active = False
            self.auto_drying_owned_by_auto = False
            self._auto_drying_stop_required = False
            self.auto_drying_last_error = ''
            dryer = self._info.setdefault('dryer', {})
            dryer['status'] = 'stop'
            dryer['remain_time'] = 0
            if (restart_temperature > 0 and self._auto_drying_job_active
                    and self.auto_drying_enabled
                    and not self.auto_drying_suppressed_for_job):
                self._queue_auto_drying_start(
                    restart_temperature, self.reactor.monotonic())

        try:
            token = self.send_request(
                request={'method': 'drying_stop'},
                callback=callback,
                operation='自动烘干停止')
            if self._auto_drying_pending_action == 'stop':
                self._auto_drying_pending_token = token
            return True
        except Exception as exc:
            self._clear_auto_drying_pending()
            self._auto_drying_retry_count += 1
            self._record_auto_drying_failure(
                eventtime, '停止失败：%s' % exc)
            return False

    def _reset_auto_drying_job(self):
        self._auto_drying_job_active = False
        self._auto_drying_print_samples = 0
        self.auto_drying_suppressed_for_job = False
        self._auto_drying_temperature_ceiling = 0
        self._auto_drying_notices_seen.clear()
        if (not self._auto_drying_stop_required
                and self._auto_drying_pending_action is None):
            self._auto_drying_retry_count = 0
            self._auto_drying_next_retry = 0.

    def _auto_drying_monitor(self, eventtime):
        print_stats = self.printer.lookup_object('print_stats', None)
        state = 'standby'
        if print_stats is not None:
            try:
                state = str(
                    print_stats.get_status(eventtime).get('state')
                    or 'standby').lower()
            except Exception as exc:
                self.auto_drying_last_error = '无法读取打印状态：%s' % exc
        self.auto_drying_print_state = state
        self._reconcile_auto_drying_pending(eventtime, state)

        recommended, reason = select_auto_drying_policy(
            self._auto_drying_slots())
        if recommended > 0:
            recommended = min(recommended, self.max_dryer_temperature)
        self.auto_drying_reason = reason
        if not self.auto_drying_owned_by_auto:
            self.auto_drying_temperature = recommended

        if state in ('complete', 'cancelled', 'error', 'standby'):
            if (self.auto_drying_owned_by_auto
                    or self._auto_drying_pending_action == 'start'):
                self._auto_drying_stop_required = True
            self._reset_auto_drying_job()
            if (self._auto_drying_stop_required
                    and self._auto_drying_pending_action is None
                    and self._connected
                    and self._auto_drying_can_retry(eventtime)):
                self._queue_auto_drying_stop(eventtime)
            return eventtime + 1.0

        if state == 'printing':
            self._auto_drying_print_samples += 1
            if (not self._auto_drying_job_active
                    and self._auto_drying_print_samples >= 2):
                self._auto_drying_job_active = True
                self.auto_drying_suppressed_for_job = False
                self._auto_drying_notices_seen.clear()
                self._auto_drying_retry_count = 0
                self._auto_drying_next_retry = 0.
        elif state != 'paused':
            self._auto_drying_print_samples = 0
            return eventtime + 1.0

        if not self._auto_drying_job_active:
            return eventtime + 1.0
        if self._auto_drying_stop_required:
            if (self._auto_drying_pending_action is None
                    and self._connected
                    and self._auto_drying_can_retry(eventtime)):
                self._queue_auto_drying_stop(eventtime)
            return eventtime + 1.0
        if not self.auto_drying_enabled:
            if (self.auto_drying_owned_by_auto
                    or self._auto_drying_pending_action == 'start'):
                self._auto_drying_stop_required = True
            return eventtime + 1.0
        if self.auto_drying_suppressed_for_job:
            return eventtime + 1.0
        if reason == 'EMPTY':
            self._publish_auto_drying_notice(
                reason, AUTO_DRYING_MESSAGES[reason])
            if (self.auto_drying_owned_by_auto
                    or self._auto_drying_pending_action == 'start'):
                self._auto_drying_stop_required = True
                if (self._auto_drying_pending_action is None
                        and self._connected
                        and self._auto_drying_can_retry(eventtime)):
                    self._queue_auto_drying_stop(eventtime)
            return eventtime + 1.0
        if not self._connected:
            self.auto_drying_last_error = (
                'ACE 未连接，自动烘干将在连接恢复后重试。')
            self._publish_auto_drying_notice(
                'DISCONNECTED', self.auto_drying_last_error)
            return eventtime + 1.0
        if self._auto_drying_pending_action is not None:
            return eventtime + 1.0

        dryer_running = str(
            self._info.get('dryer', {}).get('status') or 'stop'
        ).lower() not in ('stop', 'stopped', 'idle', 'off')
        self.auto_drying_active = (
            self.auto_drying_owned_by_auto and dryer_running)

        if dryer_running and not self.auto_drying_owned_by_auto:
            return eventtime + 1.0

        if self.auto_drying_owned_by_auto and dryer_running:
            if (recommended > 0
                    and recommended < self._auto_drying_temperature_ceiling):
                self._publish_auto_drying_notice(
                    reason, AUTO_DRYING_MESSAGES[reason])
                self._queue_auto_drying_stop(
                    eventtime, restart_temperature=recommended)
            return eventtime + 1.0

        if reason in ('UNKNOWN', 'PLA_MIXED'):
            self._publish_auto_drying_notice(
                reason, AUTO_DRYING_MESSAGES[reason])
        target = recommended
        if self.auto_drying_owned_by_auto:
            target = min(
                recommended,
                self._auto_drying_temperature_ceiling or recommended)
        if self._auto_drying_can_retry(eventtime):
            self._queue_auto_drying_start(target, eventtime)
        return eventtime + 1.0

    def _handle_ready(self):
        self.toolhead = self.printer.lookup_object('toolhead')
        logging.info('ACE: Connecting to ' + self.serial_name)
        self._klippy_shutdown = False
        self._connected = False
        self._connection_state = 'disconnected'
        self._priority_queue = queue.Queue()
        self._queue = queue.Queue()
        self._main_queue = queue.Queue()
        self._schedule_reconnect(0)
        # Start endless spool monitoring timer
        if hasattr(self, 'endless_spool_enabled'):
            self.endless_spool_timer = self.reactor.register_timer(self._endless_spool_monitor, self.reactor.NOW)
            # Hook into gcode move events for broader extruder monitoring
            self.printer.register_event_handler('toolhead:move', self._on_toolhead_move)
        self.auto_drying_timer = self.reactor.register_timer(
            self._auto_drying_monitor, self.reactor.NOW)


    def _handle_disconnect(self):
        logging.info('ACE: Closing connection to ' + self.serial_name)
        self._klippy_shutdown = True
        self._mark_connection_lost('klippy shutdown')
        # A Klipper lifecycle restart is not the same as a short USB reconnect.
        # Never carry a physical recovery action across this boundary.
        self._pending_feed_assist_restore = -1
        self._feed_assist_index = -1
        self._cancel_toolchange_recovery()
        self._connection_pause_owned = False
        self._toolchange_context = None
        self._park_in_progress = False
        self._serial_disconnect('klippy shutdown', already_marked=True)
        self._safe_unregister_timer(self.endless_spool_timer)
        self.endless_spool_timer = None
        self._safe_unregister_timer(self.auto_drying_timer)
        self.auto_drying_timer = None
        self._priority_queue = None
        self._queue = None
        self._main_queue = None

    def dwell(self, delay = 1.):
        currTs = self.reactor.monotonic()
        self.reactor.pause(currTs + delay)

    def send_request(self, request, callback, operation=None,
                     high_priority=False):
        if self._queue is None or not self._connected:
            raise self.printer.command_error('ACE：设备未连接')
        token = {
            'request': request,
            'callback': callback,
            'operation': operation or request.get('method', 'unknown'),
            'done': False,
            'response': None,
            'reason': None,
            'lost': False,
            'sent': False,
        }
        self._info['status'] = 'busy'
        request_queue = (
            self._priority_queue if high_priority else self._queue)
        request_queue.put({
            'request': request,
            'callback': callback,
            'token': token,
        })
        if high_priority and self.writer_timer is not None:
            try:
                self.reactor.update_timer(
                    self.writer_timer, self.reactor.NOW)
            except Exception:
                pass
        return token

    def wait_ace_ready(self, timeout=None):
        timeout = self.ace_ready_timeout if timeout is None else float(timeout)
        wait_start = self.reactor.monotonic()
        while self._info['status'] != 'ready':
            if not self._connected:
                if self._toolchange_context is None:
                    raise self.printer.command_error('ACE：设备未连接')
                self._wait_ready_after_reconnect()
                return
            if self.reactor.monotonic() - wait_start >= timeout:
                raise self.printer.command_error(
                    'ACE：%.1f 秒内未恢复就绪' %
                    timeout)
            currTs = self.reactor.monotonic()
            self.reactor.pause(currTs + .5)

    def _motion_stop_ready_timeout(self, length, speed):
        motion_time = float(length) / float(speed) if speed > 0 else 0.
        return max(self.ace_stop_ready_timeout, motion_time + 3.)

    def _extruder_move(self, length, speed):
        pos = self.toolhead.get_position()
        pos[3] += length
        self.toolhead.move(pos, speed)
        
        return pos[3]

    def _endless_spool_monitor(self, eventtime):
        """Monitor for runout detection during printing"""
        if not self.endless_spool_enabled or self._park_in_progress or self.endless_spool_in_progress:
            return eventtime + 0.1

        # Only monitor if we have an active tool and we're not already in runout state
        current_tool = self.variables.get('ace_current_index', -1)
        if current_tool == -1:
            return eventtime + 0.1

        # Check if we're currently printing - be more aggressive about detecting print state
        try:
            # Check multiple indicators that we might be printing
            toolhead = self.printer.lookup_object('toolhead')
            print_stats = self.printer.lookup_object('print_stats', None)
            
            is_printing = False
            
            # Method 1: Check if toolhead is moving
            if hasattr(toolhead, 'get_status'):
                toolhead_status = toolhead.get_status(eventtime)
                if 'homed_axes' in toolhead_status and toolhead_status['homed_axes']:
                    is_printing = True
            
            # Method 2: Check print stats if available
            if print_stats:
                stats = print_stats.get_status(eventtime)
                if stats.get('state') in ['printing']:
                    is_printing = True
            
            # Method 3: Check idle timeout state
            try:
                printer_idle = self.printer.lookup_object('idle_timeout')
                idle_state = printer_idle.get_status(eventtime)['state']
                if idle_state in ['Printing', 'Ready']:  # Ready means potentially printing
                    is_printing = True
            except:
                # If idle_timeout doesn't exist, assume we might be printing
                is_printing = True

            # Always check for runout if endless spool is enabled and we have an active tool
            # Don't rely only on print state detection
            if current_tool >= 0:
                self._endless_spool_runout_handler()
            
            # Adjust monitoring frequency based on state
            if is_printing:
                return eventtime + 0.05  # Check every 50ms during printing
            else:
                return eventtime + 0.2   # Check every 200ms when idle
                
        except Exception as e:
            logging.info(f'ACE: Endless spool monitor error: {str(e)}')
            return eventtime + 0.1

    def _on_toolhead_move(self, print_time, newpos, oldpos):
        """Monitor toolhead moves for extruder movement during printing - removed distance tracking"""
        # This method is kept for potential future use but distance tracking removed
        pass

    def _create_mmu_sensor(self, config, pin, name):
        section = "filament_switch_sensor %s" % name
        config.fileconfig.add_section(section)
        config.fileconfig.set(section, "switch_pin", pin)
        config.fileconfig.set(section, "pause_on_runout", "False")
        fs = self.printer.load_object(config, section)

        ppins = self.printer.lookup_object('pins')
        pin_params = ppins.parse_pin(pin, True, True)
        share_name = "%s:%s" % (pin_params['chip_name'], pin_params['pin'])
        ppins.allow_multi_use_pin(share_name)
        mcu_endstop = ppins.setup_pin('endstop', pin)

        query_endstops = self.printer.load_object(config, "query_endstops")
        query_endstops.register_endstop(mcu_endstop, share_name)
        self.endstops[name] = mcu_endstop

    def _check_endstop_state(self, name):
        print_time = self.toolhead.get_last_move_time()
        return bool(self.endstops[name].query_endstop(print_time))

    def _serial_disconnect(self, reason='serial disconnect', already_marked=False):
        if not already_marked:
            self._mark_connection_lost(reason)
        if self._serial is not None:
            try:
                if self._is_serial_open():
                    self._serial.close()
            except Exception:
                pass
        self._serial = None
        self._safe_unregister_timer(self.reader_timer)
        self._safe_unregister_timer(self.writer_timer)
        self.reader_timer = None
        self.writer_timer = None

    def _connect(self, eventtime):
        if self._klippy_shutdown:
            return self.reactor.NEVER
        if self._connected:
            return self.reactor.NEVER
        try:
            port = self.find_com_port('ACE')
            if port is None:
                return eventtime + 1
            self.gcode.respond_info('ACE：正在尝试连接')
            self._serial = serial.Serial(
                port=port,
                baudrate=self.baud,
                timeout=0,
                write_timeout=0)

            if self._is_serial_open():
                self._connected = True
                self._connection_state = 'probing'
                self._connected_since = self.reactor.monotonic()
                self._last_status_time = None
                self._last_status_generation = -1
                try:
                    self._serial.reset_input_buffer()
                    self._serial.reset_output_buffer()
                except Exception:
                    pass
                logging.info('ACE: Connected to ' + port)
                self.gcode.respond_info(f'ACE：已连接到 {port}，时间 {eventtime}')
                self.writer_timer = self.reactor.register_timer(self._writer, self.reactor.NOW)
                self.reader_timer = self.reactor.register_timer(self._reader, self.reactor.NOW)
                self.send_request(request={"method": "get_info"},
                                  callback=lambda self, response: self.gcode.respond_info(str(response)))
                self._safe_unregister_timer(self.connect_timer)
                self.connect_timer = None
                return self.reactor.NEVER
        except serial.serialutil.SerialException:
            self._serial_disconnect('connect failed')
        except Exception as exc:
            logging.warning('ACE: Connect failed: %s', exc)
            self._serial_disconnect('connect failed')
        return eventtime + 1


    cmd_ACE_START_DRYING_help = 'Starts ACE Pro dryer'

    def cmd_ACE_START_DRYING(self, gcmd):
        temperature = gcmd.get_int('TEMP')
        duration = gcmd.get_int('DURATION', 240)

        if duration <= 0:
            raise gcmd.error('烘干时长错误')
        if temperature <= 0 or temperature > self.max_dryer_temperature:
            raise gcmd.error('烘干温度错误')

        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                raise gcmd.error("ACE 错误：" + response['msg'])

            self.auto_drying_active = False
            self.auto_drying_owned_by_auto = False
            self._auto_drying_stop_required = False
            self.gcode.respond_info('ACE：已开始烘干')

        self.send_request(
            request={"method": "drying", "params": {"temp": temperature, "fan_speed": 7000, "duration": duration}},
            callback=callback)

    cmd_ACE_STOP_DRYING_help = 'Stops ACE Pro dryer'

    def cmd_ACE_STOP_DRYING(self, gcmd):
        if (self.auto_drying_owned_by_auto
                or self._auto_drying_pending_action == 'start'):
            if self._auto_drying_job_active:
                self.auto_drying_suppressed_for_job = True
            self._auto_drying_stop_required = True
            if (self._auto_drying_pending_action is None
                    and self._connected
                    and self._auto_drying_can_retry(
                        self.reactor.monotonic())):
                self._queue_auto_drying_stop(self.reactor.monotonic())
            gcmd.respond_info('ACE：已请求停止自动烘干')
            return

        def callback(self, response):
            if 'code' in response and response['code'] != 0:
                raise gcmd.error("ACE 错误：" + response['msg'])

            self.gcode.respond_info('ACE：已停止烘干')

        self.send_request(request={"method": "drying_stop"}, callback=callback)

    cmd_ACE_ENABLE_AUTO_DRYING_help = 'Enable print-following ACE drying'

    def cmd_ACE_ENABLE_AUTO_DRYING(self, gcmd):
        if gcmd.get_command_parameters():
            raise gcmd.error('ACE_ENABLE_AUTO_DRYING 不接受参数')
        self.auto_drying_enabled = True
        self.variables['ace_auto_drying_enabled'] = True
        self.gcode.run_script_from_command(
            'SAVE_VARIABLE VARIABLE=ace_auto_drying_enabled VALUE=True')
        gcmd.respond_info('ACE：自动跟随打印烘干已开启，设置已保存')

    cmd_ACE_DISABLE_AUTO_DRYING_help = 'Disable print-following ACE drying'

    def cmd_ACE_DISABLE_AUTO_DRYING(self, gcmd):
        if gcmd.get_command_parameters():
            raise gcmd.error('ACE_DISABLE_AUTO_DRYING 不接受参数')
        self.auto_drying_enabled = False
        self.variables['ace_auto_drying_enabled'] = False
        self.gcode.run_script_from_command(
            'SAVE_VARIABLE VARIABLE=ace_auto_drying_enabled VALUE=False')
        if (self.auto_drying_owned_by_auto
                or self._auto_drying_pending_action == 'start'):
            self.auto_drying_suppressed_for_job = True
            self._auto_drying_stop_required = True
            if (self._auto_drying_pending_action is None
                    and self._connected
                    and self._auto_drying_can_retry(
                        self.reactor.monotonic())):
                self._queue_auto_drying_stop(self.reactor.monotonic())
        gcmd.respond_info('ACE：自动跟随打印烘干已关闭，设置已保存')

    def _request_sync(self, request, operation, allow_reconnect=False,
                      retryable=False, high_priority=False):
        attempts = 0
        while True:
            if not self._connected:
                if not allow_reconnect or not self._wait_for_stable_connection():
                    raise self.printer.command_error(
                        'ACE：执行 %s 时设备未连接' % operation)

            token = self.send_request(
                request=copy.deepcopy(request),
                callback=lambda self, response: None,
                operation=operation,
                high_priority=high_priority)
            if not self._wait_for_request(
                    token, timeout=self.ace_request_timeout + .5):
                self._mark_connection_lost('%s response timeout' % operation)
                self._serial_disconnect(
                    '%s response timeout' % operation, already_marked=True)
                self._schedule_reconnect()

            if token.get('lost'):
                if (not allow_reconnect or not retryable
                        or attempts >= self.ace_resume_max_retries):
                    raise self.printer.command_error(
                        'ACE：执行 %s 时连接中断' % operation)
                attempts += 1
                if self._toolchange_context is not None:
                    total_attempts = (
                        self._toolchange_context.get('resume_attempts', 0) + 1)
                    if total_attempts > self.ace_resume_max_retries:
                        raise self.printer.command_error(
                            'ACE：执行 %s 时已达到重连次数上限' % operation)
                    self._toolchange_context['resume_attempts'] = total_attempts
                self.gcode.respond_info(
                    'ACE：正在重连，随后重试可安全重复的操作 %s（%d/%d）' % (
                        operation, attempts, self.ace_resume_max_retries))
                self._wait_ready_after_reconnect()
                continue

            response = token.get('response') or {}
            if response.get('code', 0) != 0:
                raise ValueError(
                    'ACE 错误：' + response.get('msg', '未知错误'))
            return response

    def _recover_sent_motion(self, operation, token):
        context = self._toolchange_context
        if context is None:
            raise self.printer.command_error(
                'ACE：执行 %s 时连接中断，物理动作不会重复发送' %
                operation)
        resume_attempts = context.get('resume_attempts', 0) + 1
        context['resume_attempts'] = resume_attempts
        context['last_lost_operation'] = operation
        context['last_lost_request_sent'] = bool(token.get('sent'))
        if resume_attempts > self.ace_resume_max_retries:
            raise self.printer.command_error(
                'ACE：执行 %s 时已达到重连次数上限' % operation)
        self.gcode.respond_info(
            'ACE：执行 %s 时连接中断，正在等待稳定重连（%d/%d）' % (
                operation, resume_attempts, self.ace_resume_max_retries))
        self._wait_ready_after_reconnect()
        if token.get('sent'):
            self.gcode.respond_info(
                'ACE：上一条物理动作可能已经执行，不会重复发送；'
                '将根据实时传感器状态继续')
            return 'sent_unknown'
        return 'retry'

    def _run_ace_motion(self, method, index, length, speed,
                        stop_sensor=None):
        operation = '%s slot=%d length=%.1f' % (method, index, length)
        allow_reconnect = self._toolchange_context is not None
        while True:
            if not self._connected:
                if not allow_reconnect:
                    raise self.printer.command_error('ACE：设备未连接')
                self._wait_ready_after_reconnect()
            generation = self._connection_generation
            request = {
                'method': method,
                'params': {
                    'index': index,
                    'length': length,
                    'speed': speed,
                },
            }
            token = self.send_request(
                request=request,
                callback=lambda self, response: None,
                operation=operation)
            motion_timeout = max(
                self.ace_request_timeout + .5,
                float(length) / float(speed) + 2.5)
            queued_stop = [None]

            def monitor_stop_sensor():
                if (stop_sensor is None or queued_stop[0] is not None
                        or not self._sensor_present(stop_sensor)):
                    return
                self._set_toolchange_phase(
                    'UPPER_SENSOR_TRIGGERED',
                    stop_feed_requested=True)
                self.gcode.respond_info(
                    'ACE：上方耗材传感器已触发，停止 ACE 送料并交给挤出机继续送料')
                queued_stop[0] = self._queue_stop_feed(index)

            if not self._wait_for_request(
                    token, timeout=motion_timeout,
                    poll_callback=monitor_stop_sensor):
                self._mark_connection_lost('%s response timeout' % operation)
                self._serial_disconnect(
                    '%s response timeout' % operation, already_marked=True)
                self._schedule_reconnect()

            if token.get('lost'):
                recovery = self._recover_sent_motion(operation, token)
                if recovery == 'retry':
                    continue
                return {'code': 0, 'recovered': True, 'uncertain': True}

            if queued_stop[0] is not None:
                self._stop_feed(index, token=queued_stop[0])
                self.wait_ace_ready(
                    timeout=self._motion_stop_ready_timeout(length, speed))
                return {
                    'code': 0,
                    'stopped_by_sensor': True,
                }

            response = token.get('response') or {}
            if response.get('code', 0) != 0:
                raise ValueError(
                    'ACE 错误：' + response.get('msg', '未知错误'))

            motion_deadline = (
                token.get('sent_time', self.reactor.monotonic())
                + (float(length) / float(speed)) + .1)
            while self.reactor.monotonic() < motion_deadline:
                if (stop_sensor is not None
                        and self._sensor_present(stop_sensor)):
                    monitor_stop_sensor()
                    self._stop_feed(index, token=queued_stop[0])
                    self.wait_ace_ready(
                        timeout=self._motion_stop_ready_timeout(length, speed))
                    return {
                        'code': 0,
                        'stopped_by_sensor': True,
                    }
                if (not self._connected
                        or self._connection_generation != generation):
                    self._recover_sent_motion(operation, token)
                    return {'code': 0, 'recovered': True, 'uncertain': True}
                self.reactor.pause(
                    min(
                        motion_deadline,
                        self.reactor.monotonic()
                        + (.02 if stop_sensor is not None else .1)))
            return response

    def _enable_feed_assist(self, index, allow_reconnect=None):
        if allow_reconnect is None:
            allow_reconnect = self._toolchange_context is not None
        response = self._request_sync(
            request={
                "method": "start_feed_assist",
                "params": {"index": index},
            },
            operation='start feed assist',
            allow_reconnect=allow_reconnect,
            retryable=True)
        self._feed_assist_index = index
        request_id = response.get('id')
        request_suffix = (
            '（请求编号 %s）' % request_id
            if request_id is not None else '')
        if response.get('code', 0) == 0:
            self.gcode.respond_info(
                'ACE：槽位 T%d 辅助送料已开启%s' % (
                    index, request_suffix))
        else:
            self.gcode.respond_info(
                'ACE：槽位 T%d 辅助送料返回错误（错误码 %s）：%s' % (
                    index, response.get('code'),
                    response.get('msg', '未知错误')))
        self.dwell(delay=0.1)

    cmd_ACE_ENABLE_FEED_ASSIST_help = 'Enables ACE feed assist'

    def cmd_ACE_ENABLE_FEED_ASSIST(self, gcmd):
        index = gcmd.get_int('INDEX')

        if index < 0 or index >= 4:
            raise gcmd.error('槽位编号错误')

        self._enable_feed_assist(index)

    def _disable_feed_assist(self, index, allow_reconnect=None):
        if allow_reconnect is None:
            allow_reconnect = self._toolchange_context is not None
        self._request_sync(
            request={
                "method": "stop_feed_assist",
                "params": {"index": index},
            },
            operation='stop feed assist',
            allow_reconnect=allow_reconnect,
            retryable=True)
        self._feed_assist_index = -1
        self.gcode.respond_info('ACE：已关闭辅助送料')
        self.dwell(0.1)

    cmd_ACE_DISABLE_FEED_ASSIST_help = 'Disables ACE feed assist'

    def cmd_ACE_DISABLE_FEED_ASSIST(self, gcmd):
        if self._feed_assist_index != -1:
            index = gcmd.get_int('INDEX', self._feed_assist_index)
        else:
            index = gcmd.get_int('INDEX')

        if index < 0 or index >= 4:
            raise gcmd.error('槽位编号错误')

        self._disable_feed_assist(index)

    def _queue_stop_feed(self, index):
        return self.send_request(
            request={
                'method': 'stop_feed_filament',
                'params': {'index': index},
            },
            callback=lambda self, response: None,
            operation='stop feed filament',
            high_priority=True)

    def _stop_feed(self, index, token=None):
        if token is not None:
            if not self._wait_for_request(
                    token, timeout=self.ace_request_timeout + 1.):
                self._mark_connection_lost(
                    'stop feed filament response timeout')
                self._serial_disconnect(
                    'stop feed filament response timeout',
                    already_marked=True)
                self._schedule_reconnect()
            if not token.get('lost'):
                response = token.get('response') or {}
                if (response.get('code', 0) == 0
                        or 'FORBIDDEN' in
                        response.get('msg', '').upper()):
                    self.gcode.respond_info(
                        'ACE：槽位 T%d 已停止送料' % index)
                    return response
        try:
            response = self._request_sync(
                request={
                    'method': 'stop_feed_filament',
                    'params': {'index': index},
                },
                operation='stop feed filament',
                allow_reconnect=self._toolchange_context is not None,
                retryable=True,
                high_priority=True)
        except ValueError as exc:
            if 'FORBIDDEN' not in str(exc).upper():
                raise
            response = {'code': 0, 'msg': 'already stopped'}
        self.gcode.respond_info(
            'ACE：槽位 T%d 已停止送料' % index)
        return response

    def _feed(self, index, length, speed, stop_sensor=None):
        return self._run_ace_motion(
            'feed_filament', index, length, speed,
            stop_sensor=stop_sensor)

    cmd_ACE_FEED_help = 'Feeds filament from ACE'

    def cmd_ACE_FEED(self, gcmd):
        index = gcmd.get_int('INDEX')
        length = gcmd.get_int('LENGTH')
        speed = gcmd.get_int('SPEED', self.feed_speed)

        if index < 0 or index >= 4:
            raise gcmd.error('槽位编号错误')
        if length <= 0:
            raise gcmd.error('送料长度错误')
        if speed <= 0:
            raise gcmd.error('送料速度错误')

        self._feed(index, length, speed)

    def _retract(self, index, length, speed):
        return self._run_ace_motion(
            'unwind_filament', index, length, speed)

    def _set_toolchange_phase(self, phase, **values):
        if self._toolchange_context is None:
            return
        self._toolchange_context['phase'] = phase
        self._toolchange_context.update(values)

    def _sensor_present(self, name):
        if name == 'toolhead_sensor':
            return self._check_endstop_state(name)
        sensor = self.printer.lookup_object(
            'filament_switch_sensor %s' % name, None)
        if sensor is None:
            return False
        return bool(sensor.runout_helper.filament_present)

    def _sensor_confirmation_timeout(self):
        return self.extruder_sensor_timeout

    def _feed_until_sensor(self, tool, sensor_name, total_length, speed,
                           failure_message):
        """Feed until a physical sensor confirms arrival using the configured mode."""
        if self._sensor_present(sensor_name):
            return 0.0
        if not self.intermittent_feed:
            return self._feed_continuously_until_sensor(
                tool, sensor_name, total_length, speed, failure_message)

        fed = 0.0
        total_length = float(total_length)
        approach_length = min(self.feed_approach_length, total_length)
        fast_end = total_length - approach_length
        compensation_used = 0.0
        while not self._sensor_present(sensor_name):
            if fed < total_length:
                is_compensation = False
                remaining = total_length - fed
                if fed < fast_end:
                    step = min(self.feed_fast_chunk_length, fast_end - fed)
                    segment_speed = speed
                    phase = 'ACE_FEED_FAST'
                else:
                    step = min(self.ace_motion_chunk_length, remaining)
                    segment_speed = self.feed_approach_speed
                    phase = 'ACE_FEED_APPROACH'
            else:
                is_compensation = True
                compensation_remaining = (
                    self.feed_slip_compensation_length - compensation_used)
                if compensation_remaining <= 0:
                    message = failure_message % fed
                    raise FilamentFeedError(
                        '%s；低速补偿送料 %.1f mm 后仍未触发，可能存在打滑或堵料'
                        % (message, compensation_used))
                step = min(self.feed_slip_compensation_chunk,
                           compensation_remaining)
                segment_speed = self.feed_slip_compensation_speed
                phase = 'ACE_FEED_SLIP_COMPENSATION'
            self._set_toolchange_phase(
                phase, feed_length=fed + step,
                feed_speed=segment_speed,
                compensation_used=compensation_used)
            result = self._feed(
                tool, step, segment_speed, stop_sensor=sensor_name)
            fed += step
            if is_compensation:
                compensation_used += step
            elif fed == total_length:
                self.gcode.respond_info(
                    'ACE：送料 %.1f mm 后上方传感器仍未触发，'
                    '开始有限低速补偿送料' % fed)
            if result.get('stopped_by_sensor'):
                return fed
            self.wait_ace_ready()
            if phase != 'ACE_FEED_FAST':
                self.dwell(delay=.05)
        return fed

    def _feed_continuously_until_sensor(self, tool, sensor_name,
                                        total_length, speed,
                                        failure_message):
        """Use one fast request and one slow approach request."""
        total_length = float(total_length)
        approach_length = min(self.feed_approach_length, total_length)
        fast_length = total_length - approach_length
        fed = 0.
        for length, segment_speed, phase in (
                (fast_length, speed, 'ACE_FEED_FAST_CONTINUOUS'),
                (approach_length, self.feed_approach_speed,
                 'ACE_FEED_APPROACH_CONTINUOUS')):
            if length <= 0 or self._sensor_present(sensor_name):
                continue
            self._set_toolchange_phase(
                phase,
                feed_length=fed + length,
                feed_speed=segment_speed,
                compensation_used=0.)
            result = self._feed(
                tool, length, segment_speed, stop_sensor=sensor_name)
            fed += length
            if (result.get('stopped_by_sensor')
                    or self._sensor_present(sensor_name)):
                return fed
            if result.get('uncertain'):
                raise FilamentFeedError(
                    'ACE：连续送料期间连接状态不确定，未重复发送物理动作')
            self.wait_ace_ready()

        compensation = float(self.feed_slip_compensation_length)
        if compensation <= 0:
            raise FilamentFeedError(failure_message % fed)

        self.gcode.respond_info(
            'ACE：连续送料 %.1f mm 后上方传感器仍未触发，'
            '开始一次有限低速补偿送料' % fed)
        self._set_toolchange_phase(
            'ACE_FEED_SLIP_COMPENSATION_CONTINUOUS',
            feed_length=fed + compensation,
            feed_speed=self.feed_slip_compensation_speed,
            compensation_used=compensation)
        result = self._feed(
            tool, compensation, self.feed_slip_compensation_speed,
            stop_sensor=sensor_name)
        if result.get('stopped_by_sensor') or self._sensor_present(sensor_name):
            return fed + compensation
        if result.get('uncertain'):
            raise FilamentFeedError(
                'ACE：低速补偿送料期间连接状态不确定，未重复发送物理动作')
        self.wait_ace_ready()
        message = failure_message % (fed + compensation)
        raise FilamentFeedError(
            '%s；一次连续低速补偿送料 %.1f mm 后仍未触发，'
            '可能存在打滑或堵料' % (message, compensation))

    def _retract_in_chunks(self, index, length, speed, phase):
        remaining = float(length)
        slow_length = min(self.retract_parking_length, remaining)
        fast_remaining = remaining - slow_length

        if not self.intermittent_retract:
            if fast_remaining > 0:
                self._set_toolchange_phase(
                    phase + '_FAST',
                    retract_remaining=slow_length,
                    retract_speed=speed)
                self._retract(index, fast_remaining, speed)
                self.wait_ace_ready()
            if slow_length > 0:
                self._set_toolchange_phase(
                    phase + '_APPROACH',
                    retract_remaining=0.,
                    retract_speed=self.retract_parking_speed)
                self._retract(
                    index, slow_length, self.retract_parking_speed)
                self.wait_ace_ready()
            return

        retracted = 0.0
        while remaining > 0:
            if retracted < fast_remaining:
                step = min(self.ace_motion_chunk_length,
                           fast_remaining - retracted)
                segment_speed = speed
                segment_phase = phase + '_FAST'
            else:
                step = min(self.ace_motion_chunk_length, remaining)
                segment_speed = self.retract_parking_speed
                segment_phase = phase + '_APPROACH'
            self._set_toolchange_phase(
                segment_phase,
                retract_remaining=max(0., remaining - step),
                retract_speed=segment_speed)
            self._retract(index, step, segment_speed)
            remaining -= step
            retracted += step
            self.wait_ace_ready()

    @staticmethod
    def _tool_label(index):
        return '未装载' if index == -1 else 'T%d' % index

    def _filament_failure_details(self):
        context = self._toolchange_context or {}
        phase = context.get('phase', 'UNKNOWN')
        feed_length = context.get('feed_length')
        toolhead_feed_length = context.get('toolhead_feed_length')
        upper = self._sensor_present('extruder_sensor')
        lower = self._sensor_present('toolhead_sensor')

        if lower:
            position = '已到达下方挤出机传感器或其下方'
        elif upper:
            position = '已通过上方传感器，但尚未到达下方传感器'
        elif phase.startswith('ACE_FEED'):
            position = 'ACE 槽位与上方传感器之间'
        else:
            position = '上下传感器均未确认，具体位置未知'

        distances = []
        if feed_length is not None:
            distances.append('ACE 已送料 %.1f mm' % float(feed_length))
        if toolhead_feed_length is not None:
            distances.append(
                '挤出机已送料 %.1f mm' % float(toolhead_feed_length))
        distance_text = '，'.join(distances) if distances else '执行距离未知'
        return (
            '失败阶段=%s；%s；上方传感器=%s；下方传感器=%s；推断位置=%s' % (
                phase, distance_text,
                '已触发' if upper else '未触发',
                '已触发' if lower else '未触发', position))

    def _abort_toolchange(self, tool, gcmd, endless_spool_was_enabled,
                          message):
        details = self._filament_failure_details()
        full_message = '%s；%s' % (message, details)
        self._toolchange_last_error = full_message
        self._set_toolchange_phase(
            'FAILED_FILAMENT_FEED', error=full_message,
            failed_phase=(self._toolchange_context or {}).get('phase'))
        try:
            if 0 <= tool < 4:
                self._disable_feed_assist(tool)
        except Exception:
            logging.exception('ACE: Failed to disable feed assist after '
                              'toolchange failure')
        self._park_in_progress = False
        if endless_spool_was_enabled:
            self.endless_spool_enabled = True
        self._toolchange_context = None
        paused = self._pause_for_filament_failure()
        self.gcode.respond_info(
            'ACE：%s；%s' % (
                full_message,
                '打印已暂停，请检查耗材路径' if paused
                else '当前没有正在打印的任务，未执行暂停'))
        self.gcode.respond_info(
            'ACE：已在上述位置停止，失败后不会自动继续送料或回抽')
        raise FilamentFeedError(full_message)

    cmd_ACE_RETRACT_help = 'Retracts filament back to ACE'

    def cmd_ACE_RETRACT(self, gcmd):
        index = gcmd.get_int('INDEX')
        length = gcmd.get_int('LENGTH')
        speed = gcmd.get_int('SPEED', self.retract_speed)

        if index < 0 or index >= 4:
            raise gcmd.error('槽位编号错误')
        if length <= 0:
            raise gcmd.error('回收长度错误')
        if speed <= 0:
            raise gcmd.error('回收速度错误')

        self._retract(index, length, speed)

    def _park_to_toolhead(self, tool, gcmd, endless_spool_was_enabled):
        self.wait_ace_ready()

        self._set_toolchange_phase('ACE_FEED_TO_UPPER')
        if not self._sensor_present('extruder_sensor'):
            try:
                self._feed_until_sensor(
                    tool,
                    'extruder_sensor',
                    self.toolchange_load_length,
                    self.feed_fast_speed,
                    'ACE：送料 %.1f mm 后上方传感器仍未触发')
            except FilamentFeedError as exc:
                self._abort_toolchange(
                    tool, gcmd, endless_spool_was_enabled, str(exc))
        else:
            self.gcode.respond_info(
                'ACE：上方传感器已经触发，跳过 ACE 送料')
        self.variables['ace_filament_pos'] = "spliter"

        self.wait_ace_ready()

        self._set_toolchange_phase('ENABLE_FEED_ASSIST')
        self._enable_feed_assist(tool)

        toolhead_feed_length = 0.
        self._set_toolchange_phase('EXTRUDER_FEED_TO_LOWER')
        while not self._check_endstop_state('toolhead_sensor'):
            if toolhead_feed_length >= self.toolhead_sensor_max_feed_length:
                self._abort_toolchange(
                    tool, gcmd, endless_spool_was_enabled,
                    'ACE：挤出机送料 %.1f mm 后，下方传感器仍未触发'
                    % toolhead_feed_length)
            remaining = (
                self.toolhead_sensor_max_feed_length - toolhead_feed_length)
            if toolhead_feed_length < self.toolhead_feed_fast_length:
                step = min(
                    self.toolhead_feed_fast_step,
                    self.toolhead_feed_fast_length - toolhead_feed_length,
                    remaining)
                toolhead_speed = self.toolhead_feed_fast_speed
                toolhead_phase = 'EXTRUDER_FEED_FAST'
            else:
                step = min(self.toolhead_feed_slow_step, remaining)
                toolhead_speed = self.toolhead_feed_slow_speed
                toolhead_phase = 'EXTRUDER_FEED_SLOW'
            self._set_toolchange_phase(
                toolhead_phase,
                toolhead_feed_length=toolhead_feed_length + step,
                feed_speed=toolhead_speed)
            self._extruder_move(step, toolhead_speed)
            toolhead_feed_length += step
            self.dwell(delay=0.01)

        self.variables['ace_filament_pos'] = "toolhead"

        self._set_toolchange_phase('EXTRUDER_FEED_TO_NOZZLE')
        self._extruder_move(
            self.toolhead_sensor_to_nozzle_length,
            self.toolhead_to_nozzle_speed)
        self.variables['ace_filament_pos'] = "nozzle"

    cmd_ACE_CHANGE_TOOL_help = 'Changes tool'

    def cmd_ACE_CHANGE_TOOL(self, gcmd):
        tool = gcmd.get_int('TOOL')
        sensor_extruder = self.printer.lookup_object("filament_switch_sensor %s" % "extruder_sensor", None)

        if tool < -1 or tool >= 4:
            raise gcmd.error('工具槽位错误')

        was = self.variables.get('ace_current_index', -1)
        recovery_pending = self._pending_toolchange_recovery
        recovery_phase = (recovery_pending or {}).get('phase', '')
        if was == tool:
            gcmd.respond_info('ACE：当前已经是 T%d，无需换料' % tool)
            if tool >= 0:
                self._enable_feed_assist(tool)
            return

        if self._toolchange_context is not None:
            raise gcmd.error('ACE：另一个换料流程正在执行')

        if tool != -1:
            if not self._connected:
                raise gcmd.error('ACE：设备未连接')
            slots = self._info.get('slots') or []
            if len(slots) <= tool:
                raise gcmd.error('ACE：槽位状态尚不可用')
            status = slots[tool].get('status')
            if status != 'ready':
                self.gcode.run_script_from_command('_ACE_ON_EMPTY_ERROR INDEX=' + str(tool))
                return

        # Temporarily disable endless spool during manual toolchange
        endless_spool_was_enabled = self.endless_spool_enabled
        if endless_spool_was_enabled:
            self.endless_spool_enabled = False
            self.endless_spool_runout_detected = False
        self._pending_feed_assist_restore = -1
        self._park_in_progress = True
        self._toolchange_last_error = None
        self._toolchange_context = {
            'kind': 'manual',
            'from': was,
            'to': tool,
            'phase': 'PREPARE',
            'resume_attempts': 0,
            'started': self.reactor.monotonic(),
        }
        gcmd.respond_info(
            'ACE：换料 %s -> %s 已开始' % (
                self._tool_label(was), self._tool_label(tool)))
        completed = False
        try:
            self.gcode.run_script_from_command(
                '_ACE_PRE_TOOLCHANGE FROM=' + str(was) + ' TO=' + str(tool))

            logging.info('ACE: Toolchange ' + str(was) + ' => ' + str(tool))
            if was != -1:
                self._set_toolchange_phase('DISABLE_OLD_FEED_ASSIST')
                self._disable_feed_assist(was)
                self.wait_ace_ready()
                filament_pos = self.variables.get('ace_filament_pos', "spliter")
                upper_detected = bool(sensor_extruder.runout_helper.filament_present)
                lower_detected = self._check_endstop_state('toolhead_sensor')
                self.gcode.respond_info(
                    'ACE：卸料状态：保存位置=%s，上方传感器=%s，下方传感器=%s' % (
                        filament_pos,
                        '已触发' if upper_detected else '未触发',
                        '已触发' if lower_detected else '未触发'))

                # A stale saved "nozzle" state is not enough to run the cutter.
                skip_cutter_after_reconnect = recovery_phase in (
                    'CUT_COMPLETE', 'OLD_TOOLHEAD_RETRACT',
                    'OLD_BOWDEN_RETRACT')
                if lower_detected and not skip_cutter_after_reconnect:
                    self._set_toolchange_phase('CUTTING')
                    self.gcode.respond_info(
                        'ACE：下方传感器已触发，正在执行 CUT_TIP 切料')
                    self.gcode.run_script_from_command('CUT_TIP')
                    self.variables['ace_filament_pos'] = "toolhead"
                    self._set_toolchange_phase('CUT_COMPLETE')
                elif filament_pos == "nozzle":
                    self.gcode.respond_info(
                        'ACE：保存的位置为喷嘴，但上下传感器均未确认挤出机下方有料，'
                        '已忽略该过期状态')

                if upper_detected or lower_detected:
                    self.gcode.respond_info(
                        'ACE：正在从挤出机回抽耗材')
                    retract_attempts = 0
                    max_retract_attempts = 10
                    while bool(sensor_extruder.runout_helper.filament_present):
                        if retract_attempts >= max_retract_attempts:
                            raise gcmd.error(
                                'ACE：挤出机回抽 %d 次后上方传感器仍未清除'
                                % max_retract_attempts)
                        self._set_toolchange_phase(
                            'OLD_TOOLHEAD_RETRACT',
                            retract_attempt=retract_attempts + 1)
                        self._extruder_move(-50, 10)
                        self._retract(was, 100, self.retract_fast_speed)
                        self.wait_ace_ready()
                        retract_attempts += 1
                    self.variables['ace_filament_pos'] = "bowden"

                self.wait_ace_ready()
                self._retract_in_chunks(
                    was,
                    self.toolchange_retract_length,
                    self.retract_fast_speed,
                    'OLD_BOWDEN_RETRACT')
                self.variables['ace_filament_pos'] = "spliter"
                self.variables['ace_current_index'] = -1
                self.gcode.run_script_from_command(
                    'SAVE_VARIABLE VARIABLE=ace_current_index VALUE=-1')
                self.gcode.run_script_from_command(
                    "SAVE_VARIABLE VARIABLE=ace_filament_pos VALUE='\"spliter\"'")

                if tool != -1:
                    self._park_to_toolhead(
                        tool, gcmd, endless_spool_was_enabled)
            elif tool != -1:
                self._park_to_toolhead(
                    tool, gcmd, endless_spool_was_enabled)

            self._set_toolchange_phase('POST_PROCESS')
            gcode_move = self.printer.lookup_object('gcode_move')
            gcode_move.reset_last_position()

            self.gcode.run_script_from_command(
                '_ACE_POST_TOOLCHANGE FROM=' + str(was) + ' TO=' + str(tool))
            self.variables['ace_current_index'] = tool
            gcode_move.reset_last_position()
            self.gcode.run_script_from_command(
                'SAVE_VARIABLE VARIABLE=ace_current_index VALUE=' + str(tool))
            self.gcode.run_script_from_command(
                f"""SAVE_VARIABLE VARIABLE=ace_filament_pos VALUE='"{self.variables['ace_filament_pos']}"'""")
            completed = True
            gcmd.respond_info(
                'ACE：换料 %s -> %s 已完成' % (
                    self._tool_label(was), self._tool_label(tool)))
        except Exception as exc:
            if isinstance(exc, FilamentFeedError):
                self._cancel_toolchange_recovery()
                self.gcode.respond_info(
                    'ACE：送料失败，换料已停止，打印保持暂停')
                return
            transport_error = self._is_transport_error(exc)
            if transport_error:
                resume_after_success = self._pause_for_toolchange_recovery()
                if self._queue_toolchange_recovery(
                        tool, was, exc,
                        resume_after_success=resume_after_success):
                    if self._pending_toolchange_recovery is not None:
                        self._pending_toolchange_recovery[
                            'resume_after_success'] = (
                                self._pending_toolchange_recovery.get(
                                    'resume_after_success', False)
                                or resume_after_success)
                    self.gcode.respond_info(
                        'ACE：换料已暂停，等待自动重连恢复')
                    return
            self._cancel_toolchange_recovery()
            self._toolchange_last_error = str(exc)
            self._set_toolchange_phase(
                'FAILED_AMBIGUOUS', error=str(exc))
            self._pending_feed_assist_restore = -1
            if self._connected and self._feed_assist_index >= 0:
                try:
                    self._disable_feed_assist(
                        self._feed_assist_index, allow_reconnect=False)
                except Exception:
                    logging.exception(
                        'ACE: Failed to disable feed assist during cleanup')
            raise
        finally:
            self._park_in_progress = False
            if endless_spool_was_enabled:
                self.endless_spool_enabled = True
            if completed:
                self._toolchange_last_error = None
                self._complete_toolchange_recovery()
            self._toolchange_context = None

    def _find_next_available_slot(self, current_slot):
        """Find the next available slot with filament for endless spool"""
        slots = self._info.get('slots') or []
        for i in range(4):
            next_slot = (current_slot + 1 + i) % 4
            if next_slot != current_slot:
                # Check both inventory and ACE status
                if (len(slots) > next_slot
                        and self.inventory[next_slot]["status"] == "ready"
                        and slots[next_slot].get('status') == 'ready'):
                    return next_slot
        return -1  # No available slots

    def _endless_spool_runout_handler(self):
        """Handle runout detection for endless spool"""
        if not self.endless_spool_enabled or self.endless_spool_in_progress:
            return

        current_tool = self.variables.get('ace_current_index', -1)
        if current_tool == -1:
            return

        try:
            sensor_extruder = self.printer.lookup_object("filament_switch_sensor extruder_sensor", None)
            if sensor_extruder:
                # Check both runout helper and direct endstop state
                runout_helper_present = bool(sensor_extruder.runout_helper.filament_present)
                endstop_triggered = self._check_endstop_state('extruder_sensor')
                
                # Log sensor states for debugging (remove after testing)
                # logging.info(f"ACE Debug: runout_helper={runout_helper_present}, endstop={endstop_triggered}")
                
                # Runout detected if filament is not present
                if not runout_helper_present or not endstop_triggered:
                    if not self.endless_spool_runout_detected:  # Only trigger once
                        self.endless_spool_runout_detected = True
                        self.gcode.respond_info("ACE：检测到断料，正在执行无限续料切换")
                        logging.info(f"ACE: Runout detected - runout_helper={runout_helper_present}, endstop={endstop_triggered}")
                        # Execute endless spool change immediately
                        self._execute_endless_spool_change()
        except Exception as e:
            logging.info(f'ACE: Runout detection error: {str(e)}')

    def _execute_endless_spool_change(self):
        """Execute the endless spool toolchange - simplified for extruder sensor only"""
        if self.endless_spool_in_progress:
            return

        current_tool = self.variables.get('ace_current_index', -1)
        next_tool = self._find_next_available_slot(current_tool)
        
        if next_tool == -1:
            self.gcode.respond_info("ACE：无限续料没有可用槽位，打印已暂停")
            self.gcode.run_script_from_command('PAUSE')
            self.endless_spool_runout_detected = False
            return

        self.endless_spool_in_progress = True
        self.endless_spool_runout_detected = False
        if self._toolchange_context is not None:
            self.endless_spool_in_progress = False
            self.gcode.respond_info(
                'ACE：另一个换料流程正在执行，无法启动无限续料')
            return
        self._toolchange_context = {
            'kind': 'endless',
            'from': current_tool,
            'to': next_tool,
            'phase': 'PREPARE',
            'resume_attempts': 0,
            'started': self.reactor.monotonic(),
        }
        self._park_in_progress = True
        
        self.gcode.respond_info(
            f"ACE：无限续料正在从 T{current_tool} 切换到 T{next_tool}")
        
        # Mark current slot as empty in inventory
        if current_tool >= 0:
            self.inventory[current_tool] = {"status": "empty", "color": [0, 0, 0], "material": "", "temp": 0}
            # Save updated inventory to persistent variables
            self.variables['ace_inventory'] = self.inventory
            self.gcode.run_script_from_command(f'SAVE_VARIABLE VARIABLE=ace_inventory VALUE=\'{json.dumps(self.inventory)}\'')
        
        completed = False
        try:
            # Direct endless spool change - no toolchange macros needed for runout response
            
            # Step 1: Disable feed assist on empty slot
            if current_tool != -1:
                self._set_toolchange_phase('DISABLE_OLD_FEED_ASSIST')
                self._disable_feed_assist(current_tool)
                self.wait_ace_ready()

            # Step 2: Feed filament from next slot until it reaches extruder sensor
            self._set_toolchange_phase('ACE_FEED_TO_UPPER')
            self._feed_until_sensor(
                next_tool,
                'extruder_sensor',
                self.toolchange_load_length,
                self.feed_fast_speed,
                'ACE：无限续料送料 %.1f mm 后上方传感器仍未触发')

            # Step 3: Enable feed assist for new slot
            self._set_toolchange_phase('ENABLE_FEED_ASSIST')
            self._enable_feed_assist(next_tool)

            # Step 4: Update current index and save state
            self.variables['ace_current_index'] = next_tool
            self.gcode.run_script_from_command('SAVE_VARIABLE VARIABLE=ace_current_index VALUE=' + str(next_tool))
            
            completed = True
            self.gcode.respond_info(f"ACE：无限续料切换完成，当前使用 T{next_tool}")
            
        except Exception as e:
            self.gcode.respond_info(f"ACE：无限续料切换失败：{str(e)}")
            self._toolchange_last_error = str(e)
            self._set_toolchange_phase('FAILED_AMBIGUOUS', error=str(e))
            self._pending_feed_assist_restore = -1
            if self._connected and self._feed_assist_index >= 0:
                try:
                    self._disable_feed_assist(
                        self._feed_assist_index, allow_reconnect=False)
                except Exception:
                    logging.exception(
                        'ACE: Failed to disable feed assist during endless cleanup')
            self.gcode.run_script_from_command('PAUSE')
        finally:
            self.endless_spool_in_progress = False
            self._park_in_progress = False
            if completed:
                self._toolchange_last_error = None
            self._toolchange_context = None

    cmd_ACE_ENABLE_ENDLESS_SPOOL_help = 'Enable endless spool feature'

    cmd_ACE_ENABLE_ENDLESS_SPOOL_help = 'Enable endless spool feature'

    def cmd_ACE_ENABLE_ENDLESS_SPOOL(self, gcmd):
        self.endless_spool_enabled = True
        
        # Save to persistent variables
        self.variables['ace_endless_spool_enabled'] = True
        self.gcode.run_script_from_command('SAVE_VARIABLE VARIABLE=ace_endless_spool_enabled VALUE=True')
        
        gcmd.respond_info("ACE：无限续料已启用，断料后立即切换，设置已保存")

    cmd_ACE_DISABLE_ENDLESS_SPOOL_help = 'Disable endless spool feature'

    def cmd_ACE_DISABLE_ENDLESS_SPOOL(self, gcmd):
        self.endless_spool_enabled = False
        self.endless_spool_runout_detected = False
        self.endless_spool_in_progress = False
        
        # Save to persistent variables
        self.variables['ace_endless_spool_enabled'] = False
        self.gcode.run_script_from_command('SAVE_VARIABLE VARIABLE=ace_endless_spool_enabled VALUE=False')
        
        gcmd.respond_info("ACE：无限续料已关闭，设置已保存")

    cmd_ACE_ENDLESS_SPOOL_STATUS_help = 'Show endless spool status'

    def cmd_ACE_ENDLESS_SPOOL_STATUS(self, gcmd):
        status = self.get_status()['endless_spool']
        saved_enabled = self.variables.get('ace_endless_spool_enabled', False)
        
        gcmd.respond_info("ACE：无限续料状态：")
        gcmd.respond_info(f"  - 当前启用：{status['enabled']}")
        gcmd.respond_info(f"  - 已保存设置：{saved_enabled}")
        gcmd.respond_info("  - 模式：检测到断料后立即切换")
        
        if status['enabled']:
            gcmd.respond_info(f"  - 已检测到断料：{status['runout_detected']}")
            gcmd.respond_info(f"  - 正在执行：{status['in_progress']}")

    def find_com_port(self, device_name):
        com_ports = serial.tools.list_ports.comports()
        for port, desc, hwid in com_ports:
            if device_name in desc:
                return port
        return None

    def cmd_ACE_DEBUG(self, gcmd):
        method = gcmd.get('METHOD')
        params = gcmd.get('PARAMS', '{}')

        try:
            def callback(self, response):
                self.gcode.respond_info(str(response))

            self.send_request(request = {"method": method, "params": json.loads(params)}, callback = callback)
        except Exception as e:
            self.gcode.respond_info('ACE：调试命令错误：' + str(e))
        #self.gcode.respond_info(str(self.find_com_port('ACE')))


    def get_status(self, eventtime=None):
        status = copy.deepcopy(self._info)
        status['driver_version'] = ACEPROSV08_DRIVER_VERSION
        status['endless_spool'] = {
            'enabled': self.endless_spool_enabled,
            'runout_detected': self.endless_spool_runout_detected,
            'in_progress': self.endless_spool_in_progress
        }
        status['auto_drying'] = {
            'enabled': self.auto_drying_enabled,
            'active': self.auto_drying_active,
            'owned_by_auto': self.auto_drying_owned_by_auto,
            'suppressed_for_job': self.auto_drying_suppressed_for_job,
            'temperature': self.auto_drying_temperature,
            'reason': self.auto_drying_reason,
            'print_state': self.auto_drying_print_state,
            'last_error': self.auto_drying_last_error,
            'notice_id': self.auto_drying_notice_id,
            'notice_message': self.auto_drying_notice_message,
        }
        context = copy.deepcopy(self._toolchange_context)
        if context is not None:
            context.pop('started', None)
        status['connection'] = {
            'state': self._connection_state,
            'connected': self._connected,
            'generation': self._connection_generation,
            'last_disconnect_reason': self._last_disconnect_reason,
            'feed_assist_restore_pending': self._pending_feed_assist_restore >= 0,
        }
        status['toolchange'] = {
            'active': context is not None,
            'context': context,
            'last_error': self._toolchange_last_error,
        }
        status['intermittent_feed'] = self.intermittent_feed
        status['intermittent_retract'] = self.intermittent_retract
        status['ace_stop_ready_timeout'] = self.ace_stop_ready_timeout
        status['slot_positions'] = list(self.slot_positions)
        try:
            current_index = int(self.variables.get('ace_current_index', -1))
        except (TypeError, ValueError):
            current_index = -1
        status['filament_position'] = (
            self.slot_positions[current_index]
            if 0 <= current_index < 4 else 'unknown')
        return status

    def cmd_ACE_SET_SLOT(self, gcmd):
        idx = gcmd.get_int('INDEX')
        if idx < 0 or idx >= 4:
            raise gcmd.error('槽位编号无效')
        if gcmd.get_int('EMPTY', 0):
            self.inventory[idx] = {"status": "empty", "color": [0, 0, 0], "material": "", "temp": 0}
            # Save to persistent variables
            self.variables['ace_inventory'] = self.inventory
            self.gcode.run_script_from_command(f'SAVE_VARIABLE VARIABLE=ace_inventory VALUE=\'{json.dumps(self.inventory)}\'')
            gcmd.respond_info(f"ACE：槽位 T{idx} 已设为空")
            return
        color_str = gcmd.get('COLOR', None)
        material = gcmd.get('MATERIAL', "")
        temp = gcmd.get_int('TEMP', 0)
        if not color_str or not material or temp <= 0:
            raise gcmd.error('除 EMPTY=1 外，必须设置 COLOR、MATERIAL 和 TEMP')
        color = [int(x) for x in color_str.split(',')]
        if len(color) != 3:
            raise gcmd.error('COLOR 必须是 R,G,B 格式')
        self.inventory[idx] = {
            "status": "ready",
            "color": color,
            "material": material,
            "temp": temp
        }
        # Save to persistent variables
        self.variables['ace_inventory'] = self.inventory
        self.gcode.run_script_from_command(f'SAVE_VARIABLE VARIABLE=ace_inventory VALUE=\'{json.dumps(self.inventory)}\'')
        gcmd.respond_info(
            f"ACE：槽位 T{idx} 已保存：颜色={color}，材料={material}，温度={temp}")

    def cmd_ACE_QUERY_SLOTS(self, gcmd):
        status_labels = {
            'ready': '可用',
            'empty': '空',
        }
        gcmd.respond_info('ACE：料槽库存：')
        for idx, slot in enumerate(self.inventory):
            color = slot.get('color') or [0, 0, 0]
            color = (list(color) + [0, 0, 0])[:3]
            status = str(slot.get('status') or 'empty')
            status_text = status_labels.get(status, status)
            material = str(slot.get('material') or '未设置')
            temp = slot.get('temp') or 0
            temp_text = '%s℃' % temp if temp else '未设置'
            gcmd.respond_info(
                '  T%d：%s，颜色 RGB(%s, %s, %s)，材料 %s，温度 %s' % (
                    idx, status_text, color[0], color[1], color[2],
                    material, temp_text))

    cmd_ACE_SAVE_INVENTORY_help = 'Manually save current inventory to persistent storage'

    def cmd_ACE_SAVE_INVENTORY(self, gcmd):
        self.variables['ace_inventory'] = self.inventory
        self.gcode.run_script_from_command(f'SAVE_VARIABLE VARIABLE=ace_inventory VALUE=\'{json.dumps(self.inventory)}\'')
        gcmd.respond_info("ACE：耗材库存已保存")

    cmd_ACE_TEST_RUNOUT_SENSOR_help = 'Test and display runout sensor states'

    def cmd_ACE_TEST_RUNOUT_SENSOR(self, gcmd):
        try:
            sensor_extruder = self.printer.lookup_object("filament_switch_sensor extruder_sensor", None)
            if sensor_extruder:
                runout_helper_present = bool(sensor_extruder.runout_helper.filament_present)
                endstop_triggered = self._check_endstop_state('extruder_sensor')
                
                gcmd.respond_info("ACE：挤出机传感器状态：")
                gcmd.respond_info(f"  - 耗材存在：{runout_helper_present}")
                gcmd.respond_info(f"  - 开关触发：{endstop_triggered}")
                gcmd.respond_info(f"  - 无限续料启用：{self.endless_spool_enabled}")
                gcmd.respond_info(f"  - 当前槽位：{self.variables.get('ace_current_index', -1)}")
                gcmd.respond_info(f"  - 已检测到断料：{self.endless_spool_runout_detected}")
                
                # Test runout detection logic
                would_trigger = not runout_helper_present or not endstop_triggered
                gcmd.respond_info(f"  - 当前状态会触发断料：{would_trigger}")
            else:
                gcmd.respond_info("ACE：未找到挤出机耗材传感器")
        except Exception as e:
            gcmd.respond_info(f"ACE：测试传感器时出错：{str(e)}")

    cmd_ACE_GET_CURRENT_INDEX_help = 'Get the currently loaded slot index'

    def cmd_ACE_GET_CURRENT_INDEX(self, gcmd):
        current_index = self.variables.get('ace_current_index', -1)
        gcmd.respond_info(str(current_index))

    cmd_ACE_TOOLCHANGE_STATUS_help = 'Show ACE connection and toolchange recovery state'

    def cmd_ACE_TOOLCHANGE_STATUS(self, gcmd):
        gcmd.respond_info(json.dumps(self.get_status().get('toolchange', {})))
        gcmd.respond_info(json.dumps(self.get_status().get('connection', {})))

    cmd_ACE_ABORT_TOOLCHANGE_help = 'Abort the in-memory ACE toolchange recovery state'

    def cmd_ACE_ABORT_TOOLCHANGE(self, gcmd):
        if (self._toolchange_context is None
                and self._pending_toolchange_recovery is None):
            gcmd.respond_info('ACE：当前没有需要终止的换料恢复状态')
            return
        self._toolchange_last_error = '用户已终止换料'
        self._cancel_toolchange_recovery()
        self._toolchange_context = None
        self._pending_feed_assist_restore = -1
        self._park_in_progress = False
        self.endless_spool_in_progress = False
        if self._connected and self._feed_assist_index >= 0:
            try:
                self._disable_feed_assist(
                    self._feed_assist_index, allow_reconnect=False)
            except Exception:
                logging.exception('ACE: Failed to disable feed assist on abort')
        gcmd.respond_info(
            'ACE：换料恢复状态已清除；再次换料前请检查上下传感器')

    cmd_ACE_CHANGE_SPOOL_help = 'Change spool for a specific index - INDEX= (retracts filament from tube, unloads if loaded first)'

    def cmd_ACE_CHANGE_SPOOL(self, gcmd):
        index = gcmd.get_int('INDEX', None)
        
        if index is None:
            raise gcmd.error('必须提供 INDEX 参数')
        
        if index < 0 or index >= 4:
            raise gcmd.error('槽位编号错误，必须是 0-3')
        
        gcmd.respond_info(f"ACE：正在更换槽位 T{index} 的料卷")
        
        # Check if this slot is currently loaded (active tool)
        current_tool = self.variables.get('ace_current_index', -1)
        
        if current_tool == index:
            # If this is the currently loaded tool, unload it first (T-1)
            gcmd.respond_info(f"ACE：T{index} 当前已装载，先执行卸料")
            # Create a proper gcode command to unload the tool
            unload_cmd = "ACE_CHANGE_TOOL TOOL=-1"
            self.gcode.run_script_from_command(unload_cmd)
            gcmd.respond_info("ACE：耗材已卸载")
        
        # Check if slot is not empty (has filament loaded in the system)
        slot_status = None
        if hasattr(self, '_info') and self._info and 'slots' in self._info:
            slot_status = self._info['slots'][index]['status']
        
        inventory_status = self.inventory[index]['status']
        
        # If slot is not empty or has filament in the system, retract it
        if (slot_status and slot_status != 'empty') or (inventory_status and inventory_status != 'empty'):
            gcmd.respond_info(f"ACE：正在从特氟龙管回收 T{index} 耗材")
            gcmd.respond_info(
                f"ACE：回收距离 {self.bowden_tube_length} mm，速度 "
                f"{self.retract_speed} mm/s")
            
            try:
                self._retract(index, self.bowden_tube_length, self.retract_speed)
                gcmd.respond_info(f"ACE：T{index} 耗材已回收")
            except Exception as e:
                gcmd.respond_info(f"ACE：回收耗材时出错：{str(e)}")
                raise gcmd.error(f"ACE：回收耗材失败：{str(e)}")
        else:
            gcmd.respond_info(f"ACE：T{index} 已为空，无需回收")
        
        gcmd.respond_info(f"ACE：T{index} 料卷更换流程完成")


def load_config(config):
    return BunnyAce(config)
