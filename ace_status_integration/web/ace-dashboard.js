// ValgACE Dashboard JavaScript

const { createApp } = Vue;

createApp({
    data() {
        return {
            currentLanguage: 'zh',
            translations: {
                zh: {
                    header: {
                        title: 'ACE Pro 控制面板',
                        connectionLabel: '连接状态',
                        connected: '已连接',
                        disconnected: '未连接',
                        instance: 'ACE 设备：',
                        instanceLabel: 'ACE {index}'
                    },
                    cards: {
                        deviceStatus: '设备状态',
                        dryer: '烘干控制',
                        slots: '料槽管理',
                        quickActions: '快捷操作'
                    },
                    deviceInfo: {
                        model: '型号',
                        firmware: '固件版本',
                        bootFirmware: '启动固件',
                        status: '运行状态',
                        temp: '设备温度',
                        fan: '风扇转速',
                        usb: 'USB',
                        rfid: 'RFID',
                        rfidOn: '已启用',
                        rfidOff: '已禁用'
                    },
                    dryer: {
                        status: '当前状态',
                        targetTemp: '目标温度',
                        duration: '设定时长',
                        remainingTime: '剩余时间',
                        currentTemperature: '当前温度',
                        inputs: {
                            temp: '烘干温度（°C）：',
                            duration: '烘干时长（分钟）：'
                        },
                        buttons: {
                            start: '开始烘干',
                            stop: '停止烘干'
                        }
                    },
                    slots: {
                        slot: '料槽',
                        status: '状态',
                        type: '材料',
                        temp: '温度',
                        sku: 'SKU',
                        rfid: 'RFID'
                    },
                    quickActions: {
                        unload: '保存库存',
                        stopAssist: '停止全部助推',
                        refresh: '刷新状态'
                    },
                    buttons: {
                        load: '装载',
                        unload: '卸载',
                        assistOn: '开启助推',
                        assistOff: '关闭助推'
                    },
                    dialogs: {
                        feedTitle: '送料 - 料槽 {slot}',
                        retractTitle: '回抽 - 料槽 {slot}',
                        length: '长度（mm）：',
                        speed: '速度（mm/s）：',
                        execute: '执行',
                        cancel: '取消'
                    },
                    notifications: {
                        websocketConnected: '实时连接已建立',
                        websocketDisconnected: '实时连接已断开',
                        apiError: 'API 错误：{error}',
                        loadError: '状态加载失败：{error}',
                        commandSuccess: '命令 {command} 执行成功',
                        commandSent: '命令 {command} 已发送',
                        commandError: '错误：{error}',
                        commandErrorGeneric: '命令执行失败',
                        executeError: '命令执行失败：{error}',
                        feedAssistOn: '料槽 {index} 助推已开启',
                        feedAssistOff: '料槽 {index} 助推已关闭',
                        feedAssistAllOff: '所有料槽助推均已关闭',
                        feedAssistAllOffError: '关闭助推失败',
                        refreshStatus: '状态已刷新',
                        validation: {
                            tempRange: '烘干温度必须在 20～55°C 之间',
                            durationMin: '烘干时长至少为 1 分钟',
                            feedLength: '送料长度至少为 1 mm',
                            retractLength: '回抽长度至少为 1 mm'
                        }
                    },
                    statusMap: {
                        ready: '就绪',
                        busy: '忙碌',
                        unknown: '未知',
                        disconnected: '未连接'
                    },
                    dryerStatusMap: {
                        drying: '烘干中',
                        stop: '已停止'
                    },
                    connectionStateMap: {
                        connected: '已连接',
                        reconnecting: '正在重连',
                        connecting: '正在连接',
                        initializing: '正在初始化',
                        disabled: '已禁用',
                        disconnected: '未连接',
                        unknown: '未知'
                    },
                    slotStatusMap: {
                        ready: '就绪',
                        empty: '空槽',
                        busy: '忙碌',
                        unknown: '未知'
                    },
                    rfidStatusMap: {
                        0: '未检测到',
                        1: '读取错误',
                        2: '已识别',
                        3: '识别中…'
                    },
                    common: {
                        unknown: '未知'
                    },
                    time: {
                        hours: '小时',
                        minutes: '分钟',
                        minutesShort: '分',
                        secondsShort: '秒'
                    }
                }
            },
            // Connection
            wsConnected: false,
            ws: null,
            apiBase: ACE_DASHBOARD_CONFIG?.apiBase || window.location.origin,

            // Device Status
            deviceStatus: {
                status: 'unknown',
                connection_state: 'unknown',
                model: 'Anycubic Color Engine Pro',
                firmware: '--',
                boot_firmware: '--',
                temp: 0,
                humidity: null,
                fan_speed: 0,
                enable_rfid: 0,
                usb_port: '',
                usb_path: ''
            },
            sensors: {
                upper: { name: 'extruder_sensor', available: false, detected: false },
                lower: { name: 'toolhead_sensor', available: false, detected: false }
            },
            endlessSpool: {
                enabled: false,
                runout_detected: false,
                in_progress: false
            },
            autoDrying: {
                available: false,
                enabled: false,
                active: false,
                owned_by_auto: false,
                suppressed_for_job: false,
                temperature: 0,
                reason: 'EMPTY',
                print_state: 'standby',
                last_error: '',
                notice_id: 0,
                notice_message: ''
            },
            lastAutoDryingNoticeId: null,
            slotPositions: ['unknown', 'unknown', 'unknown', 'unknown'],
            motionOwner: '',
            printing: false,
            calibration: {
                available: false,
                valid: false,
                stale: false,
                phase: 'unavailable',
                selected_slot: -1,
                feed_completed: 0,
                feed_upper_bound: 0,
                sensor_clear_completed: 0,
                sensor_clear_upper_bound: 0,
                retract_distance: 0,
                parking_distance: 0,
                last_error: ''
            },
            calibrationSlot: 0,

            // Dryer
            dryerStatus: {
                status: 'stop',
                target_temp: 0,
                duration: 0,
                remain_time: 0
            },
            dryingTemp: ACE_DASHBOARD_CONFIG?.defaults?.dryingTemp || 45,
            dryingTempTouched: false,
            autoDryingTemp: 45,
            dryingDuration: ACE_DASHBOARD_CONFIG?.defaults?.dryingDuration || 240,

            // Slots
            slots: [],
            currentTool: -1,
            feedAssistSlot: -1,  // Индекс слота с активным feed assist (-1 = выключен)
            instanceOptions: [],
            selectedInstance: 0,
            statusRequestSeq: 0,
            instancesPanels: [],
            colorPresets: ['#ff0000', '#00ff00', '#0000ff', '#ff9900', '#ffff00', '#ff00ff', '#00ffff', '#ffffff', '#808080', '#000000'],
            colorPickerTarget: null,
            materialOptions: {
                'PLA': 200,
                'PETG': 235,
                'PETCF': 260,
                'ABS': 240,
                'ABSCF': 260,
                'ASA': 245,
                'PAHTCF': 260,
                'PEEK': 300,
                'PVA': 185,
                'HIPS': 230,
                'PC': 260,
                'PLA+': 210,
                'PLA Glow': 210,
                'PLA High Speed': 215,
                'PLA Marble': 205,
                'PLA Matte': 205,
                'PLA SE': 210,
                'PLA Silk': 215,
                'TPU': 210
            },
            rfidSyncEnabled: false,
            editingHex: {},

            // Modals
            showFeedModal: false,
            showRetractModal: false,
            feedSlot: 0,
            feedLength: ACE_DASHBOARD_CONFIG?.defaults?.feedLength || 50,
            feedSpeed: ACE_DASHBOARD_CONFIG?.defaults?.feedSpeed || 25,
            retractSlot: 0,
            retractLength: ACE_DASHBOARD_CONFIG?.defaults?.retractLength || 50,
            retractSpeed: ACE_DASHBOARD_CONFIG?.defaults?.retractSpeed || 25,

            // Notifications
            notification: {
                show: false,
                message: '',
                type: 'info'
            }
        };
    },

    mounted() {
        this.connectWebSocket();
        this.loadStatus();
        this.updateDocumentTitle();

            // Auto-refresh
        const refreshInterval = ACE_DASHBOARD_CONFIG?.autoRefreshInterval || 5000;
        setInterval(() => {
            if (this.wsConnected) {
                this.loadStatus();
            }
        }, refreshInterval);
    },

    methods: {
        t(path, params = {}) {
            const keys = path.split('.');
            let value = this.translations[this.currentLanguage];
            for (const key of keys) {
                if (value && Object.prototype.hasOwnProperty.call(value, key)) {
                    value = value[key];
                } else {
                    return undefined;
                }
            }
            if (typeof value === 'string') {
                return value.replace(/\{(\w+)\}/g, (match, token) => {
                    return Object.prototype.hasOwnProperty.call(params, token) ? params[token] : match;
                });
            }
            return undefined;
        },

        isSlotHexEditing(instIndex, slotIndex) {
            const key = `${instIndex}-${slotIndex}`;
            return !!this.editingHex[key];
        },

        getPreviousHex(prevPanel, slotIndex) {
            if (!prevPanel || !Array.isArray(prevPanel.slots)) return null;
            const found = prevPanel.slots.find(s => s.index === slotIndex);
            return found ? found.hex : null;
        },

        startHexEdit(instIndex, slotIndex) {
            const key = `${instIndex}-${slotIndex}`;
            const next = { ...this.editingHex };
            next[key] = true;
            this.editingHex = next;
        },

        commitSlotHex(slot, instanceIndex) {
            if (!slot) return;
            const val = slot.hex || '';
            const hex = (typeof val === 'string' && /^#?[0-9a-fA-F]{6}$/.test(val.trim())) ? (val.trim().startsWith('#') ? val.trim() : `#${val.trim()}`) : null;
            if (!hex) {
                this.showNotification('颜色值格式无效', 'error');
                return;
            }
            const normalized = hex.trim().startsWith('#') ? hex.trim() : `#${hex.trim()}`;
            slot.hex = normalized;
            this.setSlotColor(slot.index, instanceIndex, normalized, slot.tool, slot.material || slot.type || '', slot.temp);
            const key = `${instanceIndex}-${slot.index}`;
            const next = { ...this.editingHex };
            delete next[key];
            this.editingHex = next;
        },
        getInstanceFeedAssistSlot(instanceIndex) {
            const panel = this.instancesPanels.find(p => p.index === instanceIndex);
            return (panel && typeof panel.feedAssistSlot === 'number') ? panel.feedAssistSlot : -1;
        },
        setInstanceFeedAssistSlot(instanceIndex, slotIndex) {
            this.instancesPanels = this.instancesPanels.map(panel => {
                if (panel.index !== instanceIndex) {
                    return panel;
                }
                return { ...panel, feedAssistSlot: slotIndex };
            });
            if (instanceIndex === this.selectedInstance) {
                this.feedAssistSlot = slotIndex;
            }
        },
        isSlotLocked(inst, slot) {
            const instIndex = typeof inst === 'number' ? inst : inst?.index;
            const panel = this.instancesPanels.find(p => p.index === instIndex);
            const syncEnabled = panel ? panel.rfidSyncEnabled : this.rfidSyncEnabled;
            return !!(syncEnabled && slot && slot.rfid === 2);
        },

        updateDocumentTitle() {
            document.title = this.t('header.title');
        },

        // WebSocket Connection
        connectWebSocket() {
            const wsUrl = getWebSocketUrl();

            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                this.wsConnected = true;
                this.showNotification(this.t('notifications.websocketConnected'), 'success');
                this.subscribeToStatus();
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleWebSocketMessage(data);
                } catch (e) {
                    console.error('Error parsing WebSocket message:', e);
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.wsConnected = false;
            };

            this.ws.onclose = () => {
                this.wsConnected = false;
                this.showNotification(this.t('notifications.websocketDisconnected'), 'error');
                // Reconnect after configured timeout
                const reconnectTimeout = ACE_DASHBOARD_CONFIG?.wsReconnectTimeout || 3000;
                setTimeout(() => this.connectWebSocket(), reconnectTimeout);
            };
        },

        subscribeToStatus() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

            this.ws.send(JSON.stringify({
                jsonrpc: "2.0",
                method: "printer.objects.subscribe",
                params: {
                    objects: {
                        "ace": null
                    }
                },
                id: 5434
            }));
        },

        handleWebSocketMessage(data) {
            if (data.method === "notify_status_update") {
                const aceData = data.params[0]?.ace;
                if (aceData && typeof aceData === 'object') {
                    const wsInstance = Number(aceData.instance_index);
                    if (!Number.isInteger(wsInstance)) {
                        // Manager-level push updates are not instance-scoped.
                        // Apply only global fields that are safe across instances.
                        const globalUpdate = {};
                        if (aceData.current_index !== undefined) {
                            globalUpdate.current_index = aceData.current_index;
                        }
                        if (typeof aceData.rfid_sync_enabled === 'boolean') {
                            globalUpdate.rfid_sync_enabled = aceData.rfid_sync_enabled;
                        }
                        if (Object.keys(globalUpdate).length > 0) {
                            this.updateStatus(globalUpdate);
                        }
                        return;
                    }
                    if (wsInstance !== this.selectedInstance) {
                        // Ignore updates for other instances; periodic polling will fetch selected instance
                        return;
                    }
                    this.updateStatus(aceData);
                }
            }
        },

        // API Calls
        async loadStatus() {
            try {
                const inst = Number.isInteger(this.selectedInstance) ? this.selectedInstance : 0;
                const requestSeq = ++this.statusRequestSeq;
                const requestInstance = inst;
                const response = await fetch(`${this.apiBase}/server/ace/status?instance=${inst}`);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const result = await response.json();

                if (ACE_DASHBOARD_CONFIG?.debug) {
                    console.log('Status response:', result);
                }

                if (result.error) {
                    console.error('API error:', result.error);
                    this.showNotification(this.t('notifications.apiError', { error: result.error }), 'error');
                    return;
                }

                // API может возвращать данные напрямую или в result.result
                // Обрабатываем оба случая
                const statusData = result.result || result;

                // Ignore stale responses from older requests.
                if (requestSeq !== this.statusRequestSeq) {
                    return;
                }

                // Ignore response if user changed selected instance while request was in flight.
                if (this.selectedInstance !== requestInstance) {
                    return;
                }

                // Reject mismatched instance payloads to prevent cross-instance display bleed-through.
                if (
                    Number.isInteger(requestInstance) &&
                    typeof statusData?.instance_index === 'number' &&
                    statusData.instance_index !== requestInstance
                ) {
                    console.warn('Ignoring mismatched ACE status payload:', {
                        requested: requestInstance,
                        received: statusData.instance_index
                    });
                    return;
                }

                // Проверяем, что это действительно данные статуса (есть хотя бы одно из полей)
                if (statusData && typeof statusData === 'object' &&
                    (statusData.status !== undefined || statusData.slots !== undefined || statusData.dryer !== undefined)) {
                    this.updateStatus(statusData);
                } else {
                    console.warn('Invalid status data in response:', result);
                }
            } catch (error) {
                console.error('Error loading status:', error);
                this.showNotification(this.t('notifications.loadError', { error: error.message }), 'error');
            }
        },

        dryerTemperatureForMaterial(material) {
            const normalized = String(material || '').trim().toUpperCase();
            if (normalized.startsWith('ABS') || normalized.startsWith('PETG')) return 60;
            if (normalized.startsWith('PAHTCF') || normalized.startsWith('PETCF') || normalized.startsWith('PEEK')) return 60;
            return 45;
        },

        syncDryingTemperature() {
            const activeSlot = this.slots.find(slot => slot.index === this.currentTool || slot.loaded || slot.active);
            if (!activeSlot || !activeSlot.material) return;

            const nextTemperature = this.dryerTemperatureForMaterial(activeSlot.material);
            if (!this.dryingTempTouched || this.dryingTemp === this.autoDryingTemp) {
                this.dryingTemp = nextTemperature;
                this.autoDryingTemp = nextTemperature;
            }
        },

        updateStatus(data) {
            if (!data || typeof data !== 'object') {
                console.warn('Invalid status data:', data);
                return;
            }

            // Sync active global tool from manager status when provided.
            // Accept ACEPROSV08 current_tool plus legacy current_index fields.
            let incomingCurrentTool = null;
            const sv08Current = Number(data.current_tool);
            const topLevelCurrent = Number(data.current_index);
            const managerCurrent = Number(data?.ace_manager?.current_index);
            if (Number.isInteger(sv08Current)) {
                incomingCurrentTool = sv08Current;
            } else if (Number.isInteger(topLevelCurrent)) {
                incomingCurrentTool = topLevelCurrent;
            } else if (Number.isInteger(managerCurrent)) {
                incomingCurrentTool = managerCurrent;
            }
            if (incomingCurrentTool !== null) {
                this.currentTool = incomingCurrentTool;
            }

            if (typeof data.rfid_sync_enabled === 'boolean') {
                this.rfidSyncEnabled = data.rfid_sync_enabled;
            }

            if (ACE_DASHBOARD_CONFIG?.debug) {
                console.log('Updating status with data:', data);
            }

            // Track instances list
            const instances = Array.isArray(data.instances) ? data.instances : null;
            if (instances) {
                this.instanceOptions = instances
                    .map(item => ({ index: typeof item?.index === 'number' ? item.index : 0 }))
                    .sort((a, b) => a.index - b.index);
                if (typeof data.instance_index === 'number') {
                    if (
                        !Number.isInteger(this.selectedInstance) ||
                        !this.instanceOptions.find(opt => opt.index === this.selectedInstance)
                    ) {
                        this.selectedInstance = data.instance_index;
                    }
                }
            }

            // Обновляем статус устройства (обновляем только если поля присутствуют)
            if (data.status !== undefined) {
                this.deviceStatus.status = data.status;
            }
            if (data.connection_state !== undefined) {
                this.deviceStatus.connection_state = data.connection_state || 'unknown';
            } else if (data.connected !== undefined) {
                this.deviceStatus.connection_state = data.connected ? 'connected' : 'disconnected';
            }
            if (data.model !== undefined) {
                this.deviceStatus.model = data.model;
            }
            if (data.firmware !== undefined) {
                this.deviceStatus.firmware = data.firmware;
            }
            if (data.boot_firmware !== undefined) {
                this.deviceStatus.boot_firmware = data.boot_firmware;
            }
            if (data.temp !== undefined) {
                this.deviceStatus.temp = data.temp;
            } else if (data.temperature !== undefined) {
                this.deviceStatus.temp = data.temperature;
            }
            if (data.humidity !== undefined) {
                this.deviceStatus.humidity = data.humidity;
            } else {
                const hasProtocol = data.protocol !== undefined && data.protocol !== null;
                const protocolName = hasProtocol ? String(data.protocol).toLowerCase() : '';
                // Only clear when payload explicitly identifies a non-ACE2 protocol.
                // Partial updates may omit protocol and humidity, and should not wipe
                // a previously displayed ACE2 humidity value.
                if (hasProtocol && protocolName !== 'ace2_proto') {
                    this.deviceStatus.humidity = null;
                }
            }
            if (data.fan_speed !== undefined) {
                this.deviceStatus.fan_speed = data.fan_speed;
            }
            if (data.usb_port !== undefined) {
                this.deviceStatus.usb_port = data.usb_port;
            }
            if (data.usb_path !== undefined) {
                this.deviceStatus.usb_path = data.usb_path;
            }
            if (data.enable_rfid !== undefined) {
                this.deviceStatus.enable_rfid = data.enable_rfid;
            }
            if (data.sensors && typeof data.sensors === 'object') {
                this.sensors.upper = { ...this.sensors.upper, ...(data.sensors.upper || {}) };
                this.sensors.lower = { ...this.sensors.lower, ...(data.sensors.lower || {}) };
            }
            if (data.endless_spool && typeof data.endless_spool === 'object') {
                this.endlessSpool = { ...this.endlessSpool, ...data.endless_spool };
            }
            if (Array.isArray(data.slot_positions)) {
                this.slotPositions = Array.from({ length: 4 }, (_, index) => data.slot_positions[index] || 'unknown');
            }
            if (data.motion_owner !== undefined) {
                this.motionOwner = String(data.motion_owner || '');
            }
            if (data.printing !== undefined) {
                this.printing = Boolean(data.printing);
            }
            if (data.calibration && typeof data.calibration === 'object') {
                this.calibration = {
                    ...this.calibration,
                    ...data.calibration,
                    available: data.calibration.available !== false
                };
            }
            if (data.auto_drying && typeof data.auto_drying === 'object') {
                const nextAutoDrying = {
                    ...this.autoDrying,
                    ...data.auto_drying,
                    available: data.auto_drying.available !== false
                };
                const incomingNoticeId = Number(nextAutoDrying.notice_id) || 0;
                if (this.lastAutoDryingNoticeId === null || incomingNoticeId < this.lastAutoDryingNoticeId) {
                    this.lastAutoDryingNoticeId = incomingNoticeId;
                } else if (incomingNoticeId > this.lastAutoDryingNoticeId) {
                    this.lastAutoDryingNoticeId = incomingNoticeId;
                    const message = nextAutoDrying.notice_message || nextAutoDrying.last_error;
                    if (message) {
                        this.showNotification(message, nextAutoDrying.last_error ? 'error' : 'info');
                    }
                }
                this.autoDrying = nextAutoDrying;
            }

            // Обновляем статус сушилки
            const dryer = data.dryer || data.dryer_status;

            if (dryer && typeof dryer === 'object') {
                // duration всегда в минутах (данные из ace.py уже нормализованы)
                if (dryer.duration !== undefined) {
                    this.dryerStatus.duration = Math.floor(dryer.duration); // Целое число минут
                } else if (dryer.duration_minutes !== undefined) {
                    this.dryerStatus.duration = Math.floor(dryer.duration_minutes);
                }

                // remain_time: данные из ace.py уже конвертированы из секунд в минуты
                // Но на всякий случай проверяем: если значение слишком большое (> 1440 минут = 24 часа),
                // значит оно не было конвертировано и все еще в секундах
                if (dryer.remain_time !== undefined) {
                    let remain_time = dryer.remain_time;

                    // Если remain_time > 1440 (24 часа в минутах), это точно секунды, конвертируем
                    if (remain_time > 1440) {
                        remain_time = remain_time / 60;
                    }
                    // Также проверяем: если remain_time значительно больше duration (в минутах),
                    // и значение > 60, вероятно это секунды
                    else if (this.dryerStatus.duration > 0 && remain_time > this.dryerStatus.duration * 1.5 && remain_time > 60) {
                        remain_time = remain_time / 60;
                    }

                    this.dryerStatus.remain_time = remain_time; // Может быть дробным (минуты.секунды)
                } else if (dryer.remaining_minutes !== undefined) {
                    this.dryerStatus.remain_time = dryer.remaining_minutes;
                }
                if (dryer.status !== undefined) {
                    this.dryerStatus.status = dryer.status;
                }
                if (dryer.target_temp !== undefined) {
                    this.dryerStatus.target_temp = dryer.target_temp;
                } else if (dryer.target_temperature !== undefined) {
                    this.dryerStatus.target_temp = dryer.target_temperature;
                }
            }

            // Обновляем слоты и панели инстансов
            const instancesRaw = Array.isArray(data.instances) ? data.instances : [];
            const prevPanels = this.instancesPanels || [];
            if (instancesRaw.length > 0) {
                this.instancesPanels = instancesRaw.map(item => {
                    const slotsArr = Array.isArray(item.slots) ? item.slots : [];
                    const prevPanel = prevPanels.find(p => p.index === item.index);
                    return {
                        index: typeof item.index === 'number' ? item.index : 0,
                        slots: slotsArr.map(slot => ({
                            index: slot.index !== undefined ? slot.index : -1,
                            tool: slot.tool !== undefined ? slot.tool : null,
                            status: slot.status || 'unknown',
                            type: slot.type || slot.material || '',
                            material: slot.material || slot.type || '',
                            temp: typeof slot.temp === 'number' ? slot.temp : 0,
                            color: Array.isArray(slot.color) ? slot.color : [0, 0, 0],
                            hex: this.isSlotHexEditing(item.index, slot.index)
                                ? this.getPreviousHex(prevPanel, slot.index) || this.getColorHex(slot.color)
                                : this.getColorHex(slot.color),
                            sku: slot.sku || '',
                            rfid: slot.rfid !== undefined ? slot.rfid : 0,
                            position: slot.position || this.slotPositions[slot.index] || 'unknown'
                        })),
                        feedAssistSlot: typeof item.feed_assist_slot === 'number' ? item.feed_assist_slot : -1,
                        rfidSyncEnabled: typeof item.rfid_sync_enabled === 'boolean' ? item.rfid_sync_enabled : this.rfidSyncEnabled
                    };
                });
                const selectedPanel = this.instancesPanels.find(p => p.index === this.selectedInstance) || this.instancesPanels[0];
                if (selectedPanel) {
                    this.slots = selectedPanel.slots;
                    this.feedAssistSlot = selectedPanel.feedAssistSlot ?? -1;
                }
            } else if (data.slots !== undefined) {
                if (Array.isArray(data.slots)) {
                    this.slots = data.slots.map(slot => ({
                        index: slot.index !== undefined ? slot.index : -1,
                        tool: slot.tool !== undefined ? slot.tool : null,
                        status: slot.status || 'unknown',
                        type: slot.type || slot.material || '',
                        material: slot.material || slot.type || '',
                        color: Array.isArray(slot.color) ? slot.color : (Array.isArray(slot.color?.rgb) ? slot.color.rgb : [0, 0, 0]),
                        hex: this.isSlotHexEditing(this.selectedInstance, slot.index)
                            ? (this.slots.find(s => s.index === slot.index)?.hex || this.getColorHex(slot.color))
                            : this.getColorHex(slot.color),
                        temp: typeof slot.temp === 'number' ? slot.temp : (typeof slot.temperature === 'number' ? slot.temperature : 0),
                        sku: slot.sku || '',
                        rfid: slot.rfid !== undefined ? slot.rfid : 0,
                        position: slot.position || this.slotPositions[slot.index] || 'unknown'
                    }));
                } else {
                    console.warn('Slots data is not an array:', data.slots);
                }
                if (data.feed_assist_index !== undefined) {
                    this.feedAssistSlot = data.feed_assist_index;
                } else if (data.feed_assist_slot !== undefined) {
                    this.feedAssistSlot = data.feed_assist_slot;
                } else if (data.feed_assist_count !== undefined && data.feed_assist_count > 0) {
                    if (this.feedAssistSlot === -1 && this.currentTool !== -1 && this.currentTool < 4) {
                        this.feedAssistSlot = this.currentTool;
                    }
                } else {
                    this.feedAssistSlot = -1;
                }
            }

            this.syncDryingTemperature();

            if (ACE_DASHBOARD_CONFIG?.debug) {
                console.log('Status updated:', {
                    deviceStatus: this.deviceStatus,
                    dryerStatus: this.dryerStatus,
                    slotsCount: this.slots.length,
                    feedAssistSlot: this.feedAssistSlot
                });
            }
        },

        onInstanceChange() {
            this.deviceStatus.humidity = null;
            this.loadStatus();
        },

        async executeCommand(command, params = {}) {
            try {
                const cmdParams = { ...params };
                // ACEPROSV08 v0.1.0 exposes one ACE device only. Keep old UI call sites
                // compatible while never sending INSTANCE to the strict Moonraker API.
                delete cmdParams.INSTANCE;

                const response = await fetch(`${this.apiBase}/server/ace/command`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        command: command,
                        params: cmdParams
                    })
                });

                const result = await response.json();

                if (ACE_DASHBOARD_CONFIG?.debug) {
                    console.log('Command response:', result);
                }

                if (result.error) {
                    const errorText = result.error.message || JSON.stringify(result.error);
                    this.showNotification(this.t('notifications.apiError', { error: errorText }), 'error');
                    return false;
                }

                if (result.result) {
                    if (result.result.success !== false && !result.result.error) {
                        this.showNotification(this.t('notifications.commandSuccess', { command }), 'success');
                        // Reload status after command
                        setTimeout(() => this.loadStatus(), 1000);
                        return true;
                    } else {
                        const commandError = result.result.error;
                        const errorMsg = commandError?.message || commandError || result.result.message || this.t('notifications.commandErrorGeneric');
                        this.showNotification(this.t('notifications.commandError', { error: errorMsg }), 'error');
                        return false;
                    }
                }

                // Если нет result, но и нет ошибки - считаем успехом
                this.showNotification(this.t('notifications.commandSent', { command }), 'success');
                setTimeout(() => this.loadStatus(), 1000);
                return true;
            } catch (error) {
                console.error('Error executing command:', error);
                this.showNotification(this.t('notifications.executeError', { error: error.message }), 'error');
                return false;
            }
        },

        // Device Actions
        async changeToolForInstance(tool, instanceIndex) {
            const message = tool < 0
                ? '确认卸载当前耗材并执行完整回料流程？'
                : `确认装载 T${tool} 并送入喷嘴？`;
            if (!window.confirm(message)) return;
            const success = await this.executeCommand('ACE_CHANGE_TOOL', { TOOL: tool, INSTANCE: instanceIndex });
            if (success && instanceIndex === this.selectedInstance) {
                this.currentTool = tool;
            }
        },

        async unloadFilament(instanceIndex) {
            await this.changeToolForInstance(-1, instanceIndex);
        },

        async changeSpool(index) {
            if (!window.confirm(`确认回抽并释放料槽 ${index + 1}？`)) return;
            await this.executeCommand('ACE_CHANGE_SPOOL', { INDEX: index });
        },

        async toggleEndlessSpool() {
            const command = this.endlessSpool.enabled
                ? 'ACE_DISABLE_ENDLESS_SPOOL'
                : 'ACE_ENABLE_ENDLESS_SPOOL';
            const success = await this.executeCommand(command, {});
            if (success) {
                this.endlessSpool.enabled = !this.endlessSpool.enabled;
                setTimeout(() => this.loadStatus(), 500);
            }
        },

        async toggleAutoDrying() {
            const enabling = !this.autoDrying.enabled;
            if (enabling && ['PLA_MIXED', 'UNKNOWN'].includes(this.autoDrying.reason)) {
                const message = this.autoDrying.reason === 'PLA_MIXED'
                    ? '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；其他高温材料的烘干效果可能受限。'
                    : '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。';
                if (!window.confirm(message)) return;
            }
            const command = enabling
                ? 'ACE_ENABLE_AUTO_DRYING'
                : 'ACE_DISABLE_AUTO_DRYING';
            const success = await this.executeCommand(command, {});
            if (success) await this.loadStatus();
        },

        async testRunoutSensors() {
            const success = await this.executeCommand('ACE_TEST_RUNOUT_SENSOR', {});
            if (success) setTimeout(() => this.loadStatus(), 500);
        },

        async stopAssist() {
            let anySuccess = false;
            const instances = this.instanceOptions.length > 0 ? this.instanceOptions : [{ index: this.selectedInstance || 0 }];
            for (const inst of instances) {
                const activeSlot = this.getInstanceFeedAssistSlot(inst.index);
                if (activeSlot !== -1) {
                    const success = await this.disableFeedAssist(activeSlot, inst.index, true);
                    if (success) {
                        anySuccess = true;
                    }
                    continue;
                }

                // Fallback: try to disable all slots if we don't know which one is active
                for (let index = 0; index < 4; index++) {
                    const success = await this.executeCommand('ACE_DISABLE_FEED_ASSIST', { INDEX: index, INSTANCE: inst.index });
                    if (success) {
                        anySuccess = true;
                        this.setInstanceFeedAssistSlot(inst.index, -1);
                    }
                }
            }
            if (anySuccess) {
                this.instancesPanels = this.instancesPanels.map(panel => ({ ...panel, feedAssistSlot: -1 }));
                this.feedAssistSlot = -1;
                this.showNotification(this.t('notifications.feedAssistAllOff'), 'success');
            } else {
                this.showNotification(this.t('notifications.feedAssistAllOffError'), 'error');
            }
        },

        async saveInventoryAll() {
            let anySuccess = false;
            const instances = this.instanceOptions.length > 0 ? this.instanceOptions : [{ index: this.selectedInstance || 0 }];
            for (const inst of instances) {
                const success = await this.executeCommand('ACE_SAVE_INVENTORY', { INSTANCE: inst.index });
                if (success) {
                    anySuccess = true;
                }
            }
            if (anySuccess) {
                await this.loadStatus();
                this.showNotification(this.t('notifications.commandSuccess', { command: 'ACE_SAVE_INVENTORY' }), 'success');
            } else {
                this.showNotification(this.t('notifications.commandErrorGeneric'), 'error');
            }
        },

        // Feed Assist Actions
        async toggleFeedAssist(index, instanceIndex) {
            const targetInstance = Number.isInteger(instanceIndex) ? instanceIndex : (this.selectedInstance || 0);
            const activeSlot = this.getInstanceFeedAssistSlot(targetInstance);
            if (activeSlot === index) {
                await this.disableFeedAssist(index, targetInstance);
            } else {
                if (activeSlot !== -1) {
                    await this.disableFeedAssist(activeSlot, targetInstance, true);
                }
                await this.enableFeedAssist(index, targetInstance);
            }
        },

        async enableFeedAssist(index, instanceIndex) {
            const targetInstance = Number.isInteger(instanceIndex) ? instanceIndex : (this.selectedInstance || 0);
            const activeSlot = this.getInstanceFeedAssistSlot(targetInstance);
            if (activeSlot !== -1 && activeSlot !== index) {
                await this.disableFeedAssist(activeSlot, targetInstance, true);
            }
            const success = await this.executeCommand('ACE_ENABLE_FEED_ASSIST', { INDEX: index, INSTANCE: targetInstance });
            if (success) {
                this.setInstanceFeedAssistSlot(targetInstance, index);
                this.showNotification(this.t('notifications.feedAssistOn', { index }), 'success');
            }
            return success;
        },

        async disableFeedAssist(index, instanceIndex, silent = false) {
            const targetInstance = Number.isInteger(instanceIndex) ? instanceIndex : (this.selectedInstance || 0);
            const success = await this.executeCommand('ACE_DISABLE_FEED_ASSIST', { INDEX: index, INSTANCE: targetInstance });
            if (success) {
                this.setInstanceFeedAssistSlot(targetInstance, -1);
                if (!silent) {
                    this.showNotification(this.t('notifications.feedAssistOff', { index }), 'success');
                }
            }
            return success;
        },

        // Dryer Actions
        async startDrying() {
            if (this.dryingTemp < 20 || this.dryingTemp > 65) {
                this.showNotification(this.t('notifications.validation.tempRange'), 'error');
                return;
            }

            if (this.dryingDuration < 1) {
                this.showNotification(this.t('notifications.validation.durationMin'), 'error');
                return;
            }

            await this.executeCommand('ACE_START_DRYING', {
                TEMP: this.dryingTemp,
                DURATION: this.dryingDuration,
                INSTANCE: this.selectedInstance
            });
        },

        async stopDrying() {
            await this.executeCommand('ACE_STOP_DRYING', { INSTANCE: this.selectedInstance });
        },

        // Feed/Retract Actions
        showFeedDialog(slot) {
            this.feedSlot = slot;
            this.feedLength = ACE_DASHBOARD_CONFIG?.defaults?.feedLength || 50;
            this.feedSpeed = ACE_DASHBOARD_CONFIG?.defaults?.feedSpeed || 25;
            this.showFeedModal = true;
        },

        closeFeedDialog() {
            this.showFeedModal = false;
        },

        async executeFeed() {
            if (this.feedLength < 1 || this.feedLength > 500 || this.feedSpeed < 1 || this.feedSpeed > 120) {
                this.showNotification(this.t('notifications.validation.feedLength'), 'error');
                return;
            }

            if (!window.confirm(`确认从 T${this.feedSlot} 手动送料 ${this.feedLength} mm，速度 ${this.feedSpeed} mm/s？`)) return;
            const success = await this.executeCommand('ACE_FEED', {
                INDEX: this.feedSlot,
                LENGTH: this.feedLength,
                SPEED: this.feedSpeed,
                CONFIRM: 1
            });

            if (success) {
                this.closeFeedDialog();
            }
        },

        showRetractDialog(slot) {
            this.retractSlot = slot;
            this.retractLength = ACE_DASHBOARD_CONFIG?.defaults?.retractLength || 50;
            this.retractSpeed = ACE_DASHBOARD_CONFIG?.defaults?.retractSpeed || 25;
            this.showRetractModal = true;
        },

        closeRetractDialog() {
            this.showRetractModal = false;
        },

        async executeRetract() {
            if (this.retractLength < 1 || this.retractLength > 500 || this.retractSpeed < 1 || this.retractSpeed > 120) {
                this.showNotification(this.t('notifications.validation.retractLength'), 'error');
                return;
            }

            if (!window.confirm(`确认从 T${this.retractSlot} 手动回抽 ${this.retractLength} mm，速度 ${this.retractSpeed} mm/s？`)) return;
            const success = await this.executeCommand('ACE_RETRACT', {
                INDEX: this.retractSlot,
                LENGTH: this.retractLength,
                SPEED: this.retractSpeed,
                CONFIRM: 1
            });

            if (success) {
                this.closeRetractDialog();
            }
        },

        async preloadSlot(index) {
            if (!window.confirm(`确认将 T${index} 冷态预装载到挤出机下方传感器？此操作不会加热或送到喷嘴。`)) return;
            await this.executeCommand('ACE_PRELOAD', { INDEX: index, CONFIRM: 1 });
        },

        async calibrateFeed(index) {
            if (!window.confirm(`确认使用 T${index} 开始送料距离标定？开始前上下传感器必须均无料。`)) return;
            await this.executeCommand('ACE_CALIBRATE_FEED', { INDEX: index, CONFIRM: 1 });
        },

        async calibrateRetract() {
            if (!window.confirm('确认继续回料距离标定，并将耗材回收到估算的五通预停放位置？')) return;
            await this.executeCommand('ACE_CALIBRATE_RETRACT', { CONFIRM: 1 });
        },

        async saveCalibration() {
            if (!window.confirm('确认保存当前送料和回料标定结果？配置中的料管长度或停车余量变化后需要重新标定。')) return;
            await this.executeCommand('ACE_CALIBRATION_SAVE', { CONFIRM: 1 });
        },

        async cancelCalibration() {
            await this.executeCommand('ACE_CALIBRATION_CANCEL', {});
        },

        async fullUnload(index) {
            if (!window.confirm(`确认将 T${index} 完全退回 ACE 内部？请确认料路没有卡料。`)) return;
            await this.executeCommand('ACE_FULL_UNLOAD', { INDEX: index, CONFIRM: 1 });
        },

        async abortToolchange() {
            await this.executeCommand('ACE_ABORT_TOOLCHANGE', {});
        },

        async refreshStatus() {
            await this.loadStatus();
            this.showNotification(this.t('notifications.refreshStatus'), 'success');
        },

        // Utility Functions
        getStatusText(status) {
            return this.t(`statusMap.${status}`) || status;
        },

        getConnectionStateText(state) {
            const key = state || 'unknown';
            return this.t(`connectionStateMap.${key}`) || this.t('common.unknown');
        },

        sensorText(sensor) {
            if (!sensor || !sensor.available) return '不可用';
            return sensor.detected ? '有料' : '无料';
        },

        sensorClass(sensor) {
            if (!sensor || !sensor.available) return 'missing';
            return sensor.detected ? 'on' : 'off';
        },

        slotPositionText(position) {
            const labels = {
                internal_or_unknown: 'ACE 内部或未知',
                preload_parked_estimated: '五通预停放',
                upper_sensor: '上方传感器',
                toolhead: '挤出机内',
                nozzle: '喷嘴',
                unknown: '位置未知'
            };
            return labels[position] || '位置未知';
        },

        calibrationStatusText() {
            if (!this.calibration.available) return '不可用';
            if (this.calibration.last_error || this.calibration.phase === 'failed') return '失败';
            if (this.calibration.stale) return '已过期';
            if (this.calibration.valid) return '有效';
            const labels = {
                idle: '未标定',
                feeding: '正在标定送料',
                feed_complete: '送料完成，等待回料',
                retracting: '正在标定回料',
                retract_complete: '回料完成，等待保存',
                saved: '已保存',
                unavailable: '不可用'
            };
            return labels[this.calibration.phase] || '未标定';
        },

        calibrationFeedResult() {
            if (Number(this.calibration.feed_upper_bound) <= 0) return '--';
            return `${Number(this.calibration.feed_completed).toFixed(1)} / ${Number(this.calibration.feed_upper_bound).toFixed(1)} mm`;
        },

        calibrationRetractResult() {
            if (Number(this.calibration.retract_distance) <= 0) return '--';
            return `${Number(this.calibration.retract_distance).toFixed(1)} mm · 停放 ${Number(this.calibration.parking_distance).toFixed(1)} mm`;
        },

        calibrationSensorsClear() {
            return this.sensors.upper.available && this.sensors.lower.available &&
                !this.sensors.upper.detected && !this.sensors.lower.detected;
        },

        motionControlsDisabled() {
            return this.printing || !this.wsConnected || this.deviceStatus.connection_state !== 'connected' ||
                Boolean(this.motionOwner) || this.deviceStatus.status === 'busy';
        },

        connectionBadgeClass() {
            if (!this.wsConnected) return 'disconnected';
            return this.deviceStatus.connection_state || 'unknown';
        },

        getDryerStatusText(status) {
            return this.t(`dryerStatusMap.${status}`) || status;
        },

        autoDryingStatusText() {
            if (!this.autoDrying.available) return '状态不可用';
            if (!this.autoDrying.enabled) return '已关闭';
            if (this.autoDrying.active) return `运行中 ${this.autoDrying.temperature}°C`;
            return '已开启';
        },

        autoDryingBasisText() {
            const labels = {
                EMPTY: '未检测到耗材',
                UNKNOWN: '未知材料',
                PLA_MIXED: 'PLA 混装',
                PLA_ONLY: '全部 PLA',
                HIGH_TEMP: '高温材料'
            };
            const basis = labels[this.autoDrying.reason] || labels.UNKNOWN;
            return this.autoDrying.temperature > 0
                ? `${this.autoDrying.temperature}°C · ${basis}`
                : basis;
        },

        getSlotStatusText(status) {
            return this.t(`slotStatusMap.${status}`) || status;
        },

        getRfidStatusText(rfid) {
            // API sometimes returns boolean/null; normalize to numeric codes used in translations
            let key;
            if (rfid === true) key = 2;         // treat true as identified
            else if (rfid === false || rfid === null || rfid === undefined) key = 0; // not found
            else key = rfid;
            const value = this.t(`rfidStatusMap.${key}`);
            return value === undefined ? this.t('common.unknown') : value;
        },

        isRfidIdentified(rfid) {
            if (rfid === true) return true;
            if (rfid === false || rfid === null || rfid === undefined) return false;
            if (typeof rfid === 'number') return rfid === 2;
            const str = String(rfid).toLowerCase();
            return str === '2' || str === 'identified';
        },

        formatUsbPath(port, usbPath) {
            let displayPort = port;
            if (displayPort && displayPort.includes('USB_Single_Serial_')) {
                displayPort = displayPort.replace(/(USB_Single_Serial_)[A-Z0-9]+(-if)/i, '$1***$2');
            }
            if (displayPort && usbPath) {
                return `${displayPort} (${usbPath})`;
            }
            if (displayPort) return displayPort;
            if (usbPath) return usbPath;
            return this.t('common.unknown');
        },

        getColorHex(color) {
            if (!color || !Array.isArray(color) || color.length < 3) {
                return '#000000';
            }
            const r = Math.max(0, Math.min(255, color[0])).toString(16).padStart(2, '0');
            const g = Math.max(0, Math.min(255, color[1])).toString(16).padStart(2, '0');
            const b = Math.max(0, Math.min(255, color[2])).toString(16).padStart(2, '0');
            return `#${r}${g}${b}`;
        },

        rgbToHex(rgb) {
            if (!Array.isArray(rgb) || rgb.length < 3) return '#000000';
            const [r, g, b] = rgb.map(v => Math.max(0, Math.min(255, Number(v) || 0)));
            return '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('');
        },

        hexToRgb(hex) {
            if (typeof hex !== 'string') return null;
            const m = hex.trim().match(/^#?([0-9a-fA-F]{6})$/);
            if (!m) return null;
            const intVal = parseInt(m[1], 16);
            return [(intVal >> 16) & 255, (intVal >> 8) & 255, intVal & 255];
        },

        async setSlotColor(slotIndex, instanceIndex, hex, toolNumber = null, material = '', temp = 0) {
            const rgb = this.hexToRgb(hex);
            if (!rgb) {
                this.showNotification('颜色值无效', 'error');
                return;
            }
            const payload = {};
            payload.INSTANCE = instanceIndex;
            payload.INDEX = slotIndex;
            payload.COLOR = `${rgb[0]},${rgb[1]},${rgb[2]}`; // ACE driver expects R,G,B or named color
            const safeMaterial = (typeof material === 'string' && material.trim()) ? material.trim() : 'PLA';
            let safeTemp = Number(temp);
            if (!Number.isFinite(safeTemp) || safeTemp <= 0 || safeTemp > 300) {
                safeTemp = 200;
            }
            payload.MATERIAL = safeMaterial;
            payload.TEMP = safeTemp;
            const success = await this.executeCommand('ACE_SET_SLOT', payload);
            if (success) {
                // Keep local state; periodic refresh will pull latest
            }
        },

        async setSlotMaterial(slotIndex, instanceIndex, toolNumber, material, currentColor, currentTemp) {
            const panel = this.instancesPanels.find(p => p.index === instanceIndex);
            const locked = (panel && panel.rfidSyncEnabled) ? (panel.slots.find(s => s.index === slotIndex)?.rfid === 2) : false;
            if (locked) {
                this.showNotification('RFID 已锁定：请先关闭 RFID 同步再编辑', 'error');
                return;
            }
            const hex = this.getColorHex(currentColor);
            const rgb = this.hexToRgb(hex);
            const tempDefault = this.materialOptions[material] || currentTemp || 200;
            const payload = {};
            payload.INSTANCE = instanceIndex;
            payload.INDEX = slotIndex;
            payload.COLOR = Array.isArray(rgb) ? `${rgb[0]},${rgb[1]},${rgb[2]}` : hex || '255,255,255';
            payload.MATERIAL = material && material.trim() ? material.trim() : 'PLA';
            payload.TEMP = Math.max(1, Math.min(300, tempDefault));
            const success = await this.executeCommand('ACE_SET_SLOT', payload);
            if (success) {
                setTimeout(() => this.loadStatus(), 500);
            }
        },

        async setSlotTemp(slotIndex, instanceIndex, toolNumber, tempValue, currentColor, currentMaterial) {
            const panel = this.instancesPanels.find(p => p.index === instanceIndex);
            const locked = (panel && panel.rfidSyncEnabled) ? (panel.slots.find(s => s.index === slotIndex)?.rfid === 2) : false;
            if (locked) {
                this.showNotification('RFID 已锁定：请先关闭 RFID 同步再编辑', 'error');
                return;
            }
            const hex = this.getColorHex(currentColor);
            const rgb = this.hexToRgb(hex);
            let temp = Number(tempValue);
            if (!Number.isFinite(temp) || temp <= 0 || temp > 300) {
                temp = 200;
            }
            const payload = {};
            payload.INSTANCE = instanceIndex;
            payload.INDEX = slotIndex;
            payload.COLOR = Array.isArray(rgb) ? `${rgb[0]},${rgb[1]},${rgb[2]}` : hex || '255,255,255';
            payload.MATERIAL = currentMaterial && currentMaterial.trim() ? currentMaterial.trim() : 'PLA';
            payload.TEMP = temp;
            const success = await this.executeCommand('ACE_SET_SLOT', payload);
            if (success) {
                setTimeout(() => this.loadStatus(), 500);
            }
        },

        commitSlotTemp(slotIndex, instanceIndex, toolNumber, event, currentColor, currentMaterial) {
            const val = event && event.target ? event.target.value : null;
            const parsed = Number(val);
            const temp = (!Number.isFinite(parsed) || parsed <= 0 || parsed > 300) ? 200 : parsed;
            if (event && event.target) {
                event.target.value = temp;
            }
            this.setSlotTemp(slotIndex, instanceIndex, toolNumber, temp, currentColor, currentMaterial);
            this.updateLocalSlotTemp(instanceIndex, slotIndex, temp);
        },

        updateLocalSlotTemp(instanceIndex, slotIndex, temp) {
            // Update in instancesPanels
            this.instancesPanels = this.instancesPanels.map(panel => {
                if (panel.index !== instanceIndex) return panel;
                const slots = panel.slots.map(slot => {
                    if (slot.index === slotIndex) {
                        return { ...slot, temp };
                    }
                    return slot;
                });
                return { ...panel, slots };
            });
            // Update current slots view if matching instance
            if (this.selectedInstance === instanceIndex) {
                this.slots = this.slots.map(slot => {
                    if (slot.index === slotIndex) {
                        return { ...slot, temp };
                    }
                    return slot;
                });
            }
        },

        getSlotToolNumber(slot, instanceIndex) {
            if (slot && slot.tool !== null && slot.tool !== undefined) {
                const toolNum = Number(slot.tool);
                return Number.isInteger(toolNum) ? toolNum : null;
            }

            const slotIndex = Number(slot?.index);
            if (!Number.isInteger(slotIndex)) {
                return null;
            }

            // If slot.tool is missing, derive instance tool offset from known slots.
            const panel = this.instancesPanels.find(p => p.index === instanceIndex);
            if (panel && Array.isArray(panel.slots)) {
                const sample = panel.slots.find(s => Number.isInteger(Number(s?.tool)) && Number.isInteger(Number(s?.index)));
                if (sample) {
                    const sampleTool = Number(sample.tool);
                    const sampleIndex = Number(sample.index);
                    const offset = sampleTool - sampleIndex;
                    return offset + slotIndex;
                }
            }

            // Legacy single-instance fallback.
            if (this.instancesPanels.length <= 1) {
                return slotIndex;
            }
            return null;
        },

        isCurrentToolSlot(slot, instanceIndex) {
            if (!Number.isInteger(this.currentTool) || this.currentTool < 0) {
                return false;
            }
            const slotTool = this.getSlotToolNumber(slot, instanceIndex);
            return slotTool !== null && slotTool === this.currentTool;
        },

        openColorPicker(instanceIndex, slotIndex, currentColor, toolNumber, material, temp, slotObj) {
            const panel = this.instancesPanels.find(p => p.index === instanceIndex);
            const locked = (panel && panel.rfidSyncEnabled && slotIndex !== undefined) ? (panel.slots.find(s => s.index === slotIndex)?.rfid === 2) : false;
            if (locked) return;
            this.colorPickerTarget = { instanceIndex, slotIndex, toolNumber, material, temp, slotObj };
            const picker = this.$refs.globalColorPicker;
            if (picker) {
                const hex = slotObj?.hex || this.getColorHex(currentColor);
                picker.value = hex;
                picker.click();
            }
        },

        handleColorPicked(event) {
            if (!this.colorPickerTarget) return;
            const { instanceIndex, slotIndex, toolNumber, material, temp, slotObj } = this.colorPickerTarget;
            const hex = event.target.value;
            if (slotObj) slotObj.hex = hex;
            this.setSlotColor(slotIndex, instanceIndex, hex, toolNumber, material, temp);
            this.colorPickerTarget = null;
        },

        formatTime(minutes) {
            if (!minutes || minutes <= 0) return `0 ${this.t('time.minutes')}`;
            const hours = Math.floor(minutes / 60);
            const mins = minutes % 60;
            if (hours > 0) {
                return `${hours}${this.t('time.hours')} ${mins}${this.t('time.minutesShort')}`;
            }
            return `${mins} ${this.t('time.minutes')}`;
        },

        formatRemainingTime(minutes) {
            // Форматирует оставшееся время сушки в формате "119м 59с"
            // minutes может быть дробным числом (119.983 = 119 минут 59 секунд)
            if (!minutes || minutes <= 0) return `0${this.t('time.minutesShort')} 0${this.t('time.secondsShort')}`;

            const totalMinutes = Math.floor(minutes);
            const fractionalPart = minutes - totalMinutes;
            const seconds = Math.round(fractionalPart * 60);

            if (totalMinutes > 0) {
                if (seconds > 0) {
                    return `${totalMinutes}${this.t('time.minutesShort')} ${seconds}${this.t('time.secondsShort')}`;
                }
                return `${totalMinutes}${this.t('time.minutesShort')}`;
            }
            return `${seconds}${this.t('time.secondsShort')}`;
        },

        showNotification(message, type = 'info') {
            this.notification = {
                show: true,
                message: message,
                type: type
            };

            setTimeout(() => {
                this.notification.show = false;
            }, 3000);
        }
    }
    }).mount('#app');
