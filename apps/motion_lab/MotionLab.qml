import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: win
    width: 1500
    height: 900
    visible: true
    title: "Motion Lab — отладка детектора движения"
    color: "#121419"

    palette.window: "#121419"
    palette.base: "#1d2027"
    palette.button: "#262a33"
    palette.text: "#e6e8ee"
    palette.buttonText: "#e6e8ee"
    palette.windowText: "#e6e8ee"
    palette.highlight: "#4c8dff"

    readonly property color panel: "#1a1d23"
    readonly property color line: "#2a2e38"
    readonly property color muted: "#8a90a0"
    readonly property color hitColor: "#3ddc84"
    readonly property color missColor: "#ff5a5a"
    readonly property color warnColor: "#ffc23d"

    // --------------------------------------------------------------- helpers
    component SettingSlider: ColumnLayout {
        id: ss
        property string label
        property real value
        property real from: 0
        property real to: 100
        property real stepSize: 1
        property int decimals: 0
        property string suffix: ""
        property string hint: ""
        signal moved(real v)
        Layout.fillWidth: true
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Label { text: ss.label; color: win.muted; font.pixelSize: 12; Layout.fillWidth: true }
            Label { text: ss.value.toFixed(ss.decimals) + ss.suffix; font.family: "monospace"; font.pixelSize: 12 }
        }
        Slider {
            Layout.fillWidth: true
            from: ss.from; to: ss.to; stepSize: ss.stepSize
            value: ss.value
            onMoved: ss.moved(value)
            ToolTip.visible: ss.hint !== "" && hovered
            ToolTip.text: ss.hint
            ToolTip.delay: 600
        }
    }

    component Section: Label {
        font.bold: true
        font.pixelSize: 13
        topPadding: 6
    }

    component Divider: Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: win.line }

    component Stat: RowLayout {
        property string name
        property string val
        property color valColor: palette.text
        Layout.fillWidth: true
        Label { text: name; color: win.muted; font.pixelSize: 12; Layout.fillWidth: true }
        Label { text: val; color: valColor; font.family: "monospace"; font.pixelSize: 12 }
    }

    FileDialog {
        id: bgDialog
        title: "Картинка фона (скриншот игры)"
        nameFilters: ["Изображения (*.png *.jpg *.jpeg *.bmp *.webp)"]
        onAccepted: backend.loadBackground(selectedFile)
    }
    FileDialog {
        id: targetDialog
        title: "Цель — PNG с прозрачностью"
        nameFilters: ["PNG (*.png)", "Изображения (*.png *.jpg *.bmp *.webp)"]
        onAccepted: backend.loadTarget(selectedFile)
    }

    // --------------------------------------------------------------- toolbar
    header: ToolBar {
        background: Rectangle { color: "#171a20" }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 6

            Button { text: "Фон…"; onClicked: bgDialog.open() }
            Button { text: "Случайный фон"; onClicked: backend.generateBackground() }
            ToolSeparator {}
            Button { text: "Цель (PNG)…"; onClicked: targetDialog.open() }
            Button { text: "Силуэт"; onClicked: backend.defaultTarget() }
            ToolSeparator {}
            Button {
                text: "Проход цели  [Space]"
                highlighted: true
                onClicked: backend.startPass()
            }
            Switch {
                text: "Авто-проходы"
                checked: backend.autoPass
                onToggled: backend.autoPass = checked
            }
            Button { text: "Убрать цель"; onClicked: backend.hideTarget() }
            Item { Layout.fillWidth: true }
            Button {
                text: backend.paused ? "▶ Продолжить" : "⏸ Пауза"
                onClicked: backend.paused = !backend.paused
            }
            Button { text: "Сбросить счётчики"; onClicked: backend.resetCounters() }
        }
    }

    // --------------------------------------------------------------- keyboard
    Item {
        id: keys
        focus: true
        Keys.onPressed: (e) => {
            const step = (e.modifiers & Qt.ShiftModifier) ? 12 : 3
            if (e.key === Qt.Key_Left || e.key === Qt.Key_A) backend.nudgeRoi(-step, 0)
            else if (e.key === Qt.Key_Right || e.key === Qt.Key_D) backend.nudgeRoi(step, 0)
            else if (e.key === Qt.Key_Up || e.key === Qt.Key_W) backend.nudgeRoi(0, -step)
            else if (e.key === Qt.Key_Down || e.key === Qt.Key_S) backend.nudgeRoi(0, step)
            else if (e.key === Qt.Key_Space) backend.startPass()
            else if (e.key === Qt.Key_P) backend.paused = !backend.paused
            else return
            e.accepted = true
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        // =========================================================== scene
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            Rectangle {
                id: sceneBox
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: win.panel
                radius: 6
                clip: true

                Label {
                    text: "Сцена — тащи рамку (камера) или цель мышкой; стрелки/WASD двигают рамку"
                    color: win.muted
                    font.pixelSize: 12
                    anchors { left: parent.left; top: parent.top; margins: 8 }
                }

                Item {
                    id: stage
                    readonly property real s: Math.min((sceneBox.width - 16) / backend.sceneW,
                                                       (sceneBox.height - 36) / backend.sceneH)
                    width: backend.sceneW * s
                    height: backend.sceneH * s
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 28 + (sceneBox.height - 36 - height) / 2

                    Image {
                        anchors.fill: parent
                        cache: false
                        source: "image://frames/bg/" + backend.bgId
                    }

                    // клик по пустому месту — перенести туда прицел
                    MouseArea {
                        anchors.fill: parent
                        onClicked: (m) => {
                            keys.forceActiveFocus()
                            backend.moveRoi(m.x / stage.s - backend.roiW / 2, m.y / stage.s - backend.roiH / 2)
                        }
                    }

                    // ---- окно захвата (ROI)
                    Rectangle {
                        id: roiRect
                        x: backend.roiX * stage.s
                        y: backend.roiY * stage.s
                        width: backend.roiW * stage.s
                        height: backend.roiH * stage.s
                        color: "transparent"
                        border.width: 2
                        border.color: backend.motion ? win.warnColor : (backend.cameraMotion ? "#9aa0ad" : "#4c8dff")

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.SizeAllCursor
                            property point grab
                            onPressed: (m) => { keys.forceActiveFocus(); grab = Qt.point(m.x, m.y) }
                            onPositionChanged: (m) => {
                                const p = mapToItem(stage, m.x - grab.x, m.y - grab.y)
                                backend.moveRoi(p.x / stage.s, p.y / stage.s)
                            }
                        }
                    }

                    // ---- цель
                    Image {
                        id: spriteImg
                        visible: backend.spriteVisible
                        x: backend.spriteX * stage.s
                        y: backend.spriteY * stage.s
                        width: backend.spriteW * stage.s
                        height: backend.spriteH * stage.s
                        cache: false
                        source: "image://frames/sprite/" + backend.spriteId
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.OpenHandCursor
                            property point grab
                            onPressed: (m) => { keys.forceActiveFocus(); grab = Qt.point(m.x, m.y) }
                            onPositionChanged: (m) => {
                                const p = mapToItem(stage, m.x - grab.x, m.y - grab.y)
                                backend.moveSprite(p.x / stage.s, p.y / stage.s)
                            }
                        }
                    }

                    // ---- следы выстрелов
                    Repeater {
                        model: backend.shots
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: 8; height: 8; radius: 4
                            x: modelData.x * stage.s - 4
                            y: modelData.y * stage.s - 4
                            color: modelData.hit ? win.hitColor : win.missColor
                            opacity: 0.35 + 0.65 * (index + 1) / backend.shots.length
                            border.color: "black"
                        }
                    }

                    // ---- прицел (поверх всего, мышь не ловит)
                    Item {
                        x: (backend.roiX + Math.floor(backend.roiW / 2)) * stage.s
                        y: (backend.roiY + Math.floor(backend.roiH / 2)) * stage.s
                        Rectangle { x: -10; y: -0.5; width: 7; height: 1.5; color: "white" }
                        Rectangle { x: 3; y: -0.5; width: 7; height: 1.5; color: "white" }
                        Rectangle { y: -10; x: -0.5; width: 1.5; height: 7; color: "white" }
                        Rectangle { y: 3; x: -0.5; width: 1.5; height: 7; color: "white" }
                        Rectangle {
                            readonly property real r: (backend.zoneRadius + 0.5) * stage.s
                            x: -r; y: -r; width: 2 * r; height: 2 * r
                            color: "transparent"
                            border.color: win.warnColor
                            border.width: 1
                        }
                    }
                }
            }

            // ---- журнал
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 150
                color: win.panel
                radius: 6
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 16
                    ColumnLayout {
                        Layout.fillHeight: true
                        Layout.preferredWidth: 360
                        spacing: 2
                        Label { text: "Журнал срабатываний"; color: win.muted; font.pixelSize: 12 }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: backend.log
                            delegate: Label {
                                required property string modelData
                                text: modelData
                                font.family: "monospace"
                                font.pixelSize: 12
                                color: modelData.indexOf("ПОПАЛ") >= 0 ? win.hitColor : win.missColor
                            }
                        }
                    }
                    Rectangle { Layout.fillHeight: true; implicitWidth: 1; color: win.line }
                    GridLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        columns: 2
                        columnSpacing: 32
                        rowSpacing: 4
                        Stat { name: "Кадров"; val: backend.frames }
                        Stat { name: "С движением"; val: backend.motionFrames }
                        Stat { name: "Движение камеры"; val: backend.cameraFrames }
                        Stat { name: "FPS / обработка"; val: backend.fps.toFixed(0) + " / " + backend.procMs.toFixed(1) + " мс" }
                        Stat { name: "Проходов цели"; val: backend.passes }
                        Stat { name: "Проходов с выстрелом"; val: backend.passesHit
                               valColor: backend.passes && backend.passesHit < backend.passes ? win.warnColor : palette.text }
                        Stat { name: "Лишних выстрелов"; val: backend.extraShots
                               valColor: backend.extraShots ? win.warnColor : palette.text }
                        Stat { name: "Сдвиг камеры"; val: backend.shiftX + ", " + backend.shiftY }
                    }
                }
            }
        }

        // =========================================================== debug views
        ColumnLayout {
            Layout.preferredWidth: 300
            Layout.maximumWidth: 300
            Layout.fillWidth: false
            Layout.fillHeight: true
            spacing: 10

            // ---- большой индикатор
            Rectangle {
                id: fireBox
                Layout.fillWidth: true
                Layout.preferredHeight: 128
                radius: 6
                color: win.panel
                property color flashColor: win.hitColor

                Rectangle {
                    id: flash
                    anchors.fill: parent
                    radius: 6
                    color: fireBox.flashColor
                    opacity: 0
                    NumberAnimation on opacity { id: flashAnim; running: false; from: 0.9; to: 0; duration: 450; easing.type: Easing.OutCubic }
                }
                Connections {
                    target: backend
                    function onFired(hit) {
                        fireBox.flashColor = hit ? win.hitColor : win.missColor
                        flashAnim.restart()
                    }
                }

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 0
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: backend.triggers
                        font.pixelSize: 52
                        font.bold: true
                    }
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: "срабатываний"
                        color: win.muted
                    }
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 14
                        Label { text: "попал " + backend.hits; color: win.hitColor; font.bold: true }
                        Label { text: "мимо " + backend.misses; color: win.missColor; font.bold: true }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: stateCol.implicitHeight + 20
                color: win.panel
                radius: 6
                ColumnLayout {
                    id: stateCol
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 3
                    Stat {
                        name: "Состояние"
                        val: backend.stateName
                        valColor: backend.stateName === "задержка" ? win.warnColor
                                 : backend.stateName === "кулдаун" ? win.missColor : palette.text
                    }
                    Stat { name: "Изменение в зоне"; val: backend.zonePct.toFixed(0) + " %"
                           valColor: backend.motion ? win.warnColor : palette.text }
                    Stat { name: "Изменение вокруг"; val: backend.ringPct.toFixed(1) + " %"
                           valColor: backend.cameraMotion ? "#9aa0ad" : palette.text }
                    Stat { name: "Порог пикселя"; val: backend.pixelThreshold }
                }
            }

            // ---- что видит детектор
            Repeater {
                model: [
                    { key: "roi", title: "Окно захвата" },
                    { key: "mask", title: "Маска изменений" }
                ]
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: win.panel
                    radius: 6
                    clip: true

                    Label {
                        text: modelData.title
                        color: win.muted
                        font.pixelSize: 12
                        anchors { left: parent.left; top: parent.top; margins: 8 }
                    }
                    Image {
                        id: dbgImg
                        anchors { fill: parent; margins: 8; topMargin: 26 }
                        fillMode: Image.PreserveAspectFit
                        smooth: false
                        cache: false
                        source: "image://frames/" + modelData.key + "/" + backend.frameId

                        // рамка зоны прицела
                        Rectangle {
                            readonly property real k: dbgImg.paintedWidth / Math.max(1, backend.roiW)
                            readonly property real side: (2 * backend.zoneRadius + 1) * k
                            x: (dbgImg.width - dbgImg.paintedWidth) / 2 + (Math.floor(backend.roiW / 2) - backend.zoneRadius) * k
                            y: (dbgImg.height - dbgImg.paintedHeight) / 2 + (Math.floor(backend.roiH / 2) - backend.zoneRadius) * k
                            width: side
                            height: side
                            color: "transparent"
                            border.color: win.warnColor
                            border.width: 1
                        }
                    }
                }
            }
        }

        // =========================================================== settings
        Rectangle {
            Layout.preferredWidth: 300
            Layout.maximumWidth: 300
            Layout.fillHeight: true
            color: win.panel
            radius: 6

            ScrollView {
                id: settingsScroll
                anchors.fill: parent
                anchors.margins: 12
                contentWidth: availableWidth
                clip: true

                ColumnLayout {
                    width: settingsScroll.availableWidth
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        Section { text: "Детектор"; Layout.fillWidth: true }
                        Button { text: "По умолчанию"; flat: true; onClicked: backend.resetDetectorDefaults() }
                    }
                    SettingSlider {
                        label: "Чувствительность"
                        hint: "Выше — реагирует на более слабое изменение яркости пикселя (меньше порог)"
                        value: backend.sensitivity; from: 0; to: 100
                        onMoved: (v) => backend.sensitivity = v
                    }
                    SettingSlider {
                        label: "Радиус зоны прицела"; suffix: " px"
                        hint: "Квадрат (2r+1) в центре окна, в котором ищем движение"
                        value: backend.zoneRadius; from: 1; to: 40
                        onMoved: (v) => backend.zoneRadius = v
                    }
                    SettingSlider {
                        label: "Мин. площадь в зоне"; suffix: " %"
                        hint: "Сколько пикселей зоны должно измениться, чтобы считать это движением"
                        value: backend.minArea * 100; from: 1; to: 100
                        onMoved: (v) => backend.minArea = v / 100
                    }
                    SettingSlider {
                        label: "Подтверждение"; suffix: " кадр."
                        hint: "Сколько кадров подряд должно быть движение — фильтр одиночных вспышек"
                        value: backend.confirmFrames; from: 1; to: 10
                        onMoved: (v) => backend.confirmFrames = v
                    }
                    SettingSlider {
                        label: "Задержка выстрела"; suffix: " мс"
                        hint: "Пауза между обнаружением и выстрелом"
                        value: backend.fireDelayMs; from: 0; to: 500; stepSize: 5
                        onMoved: (v) => backend.fireDelayMs = v
                    }
                    SettingSlider {
                        label: "Кулдаун"; suffix: " мс"
                        hint: "Минимальный интервал между выстрелами"
                        value: backend.cooldownMs; from: 0; to: 2000; stepSize: 10
                        onMoved: (v) => backend.cooldownMs = v
                    }
                    CheckBox {
                        text: "Ждать покоя в зоне после выстрела"
                        checked: backend.rearmOnCalm
                        onToggled: backend.rearmOnCalm = checked
                    }
                    RowLayout {
                        Label { text: "Уменьшение кадра"; color: win.muted; font.pixelSize: 12; Layout.fillWidth: true }
                        ComboBox {
                            model: ["1×", "2×", "4×"]
                            currentIndex: [1, 2, 4].indexOf(backend.downscale)
                            onActivated: (i) => backend.downscale = [1, 2, 4][i]
                            implicitWidth: 80
                        }
                    }

                    Divider {}
                    Section { text: "Движение камеры" }
                    CheckBox {
                        text: "Компенсировать сдвиг камеры"
                        checked: backend.compensateCamera
                        onToggled: backend.compensateCamera = checked
                        ToolTip.visible: hovered
                        ToolTip.delay: 600
                        ToolTip.text: "Фазовая корреляция: находит, насколько сдвинулся весь кадр, и вычитает этот сдвиг"
                    }
                    CheckBox {
                        text: "Игнорировать, если меняется всё вокруг"
                        checked: backend.ignoreCamera
                        onToggled: backend.ignoreCamera = checked
                    }
                    SettingSlider {
                        label: "Порог «меняется всё»"; suffix: " %"
                        enabled: backend.ignoreCamera
                        value: backend.cameraLimit * 100; from: 1; to: 100
                        onMoved: (v) => backend.cameraLimit = v / 100
                    }

                    Divider {}
                    Section { text: "Симуляция" }
                    SettingSlider {
                        label: "Скорость цели"; suffix: " px/с"
                        value: backend.targetSpeed; from: 30; to: 2000; stepSize: 10
                        onMoved: (v) => backend.targetSpeed = v
                    }
                    SettingSlider {
                        label: "Высота цели"; suffix: " px"
                        value: backend.targetHeight; from: 16; to: 400
                        onMoved: (v) => backend.targetHeight = v
                    }
                    SettingSlider {
                        label: "Траектория выше/ниже прицела"; suffix: " px"
                        value: backend.targetOffsetY; from: -200; to: 200
                        onMoved: (v) => backend.targetOffsetY = v
                    }
                    SettingSlider {
                        label: "Пауза между проходами"; suffix: " мс"
                        value: backend.passPauseMs; from: 0; to: 3000; stepSize: 50
                        onMoved: (v) => backend.passPauseMs = v
                    }
                    SettingSlider {
                        label: "Покачивание камеры"; suffix: " px"
                        value: backend.swayAmp; from: 0; to: 150
                        onMoved: (v) => backend.swayAmp = v
                    }
                    SettingSlider {
                        label: "Частота покачивания"; suffix: " Гц"; decimals: 1
                        enabled: backend.swayAmp > 0
                        value: backend.swayHz; from: 0.1; to: 4; stepSize: 0.1
                        onMoved: (v) => backend.swayHz = v
                    }
                    SettingSlider {
                        label: "Шум кадра (σ)"; decimals: 1
                        hint: "Имитация сжатия/сглаживания — проверка, не стреляет ли на шум"
                        value: backend.noise; from: 0; to: 20; stepSize: 0.5
                        onMoved: (v) => backend.noise = v
                    }
                    SettingSlider {
                        label: "FPS симуляции"
                        value: backend.labFps; from: 10; to: 240
                        onMoved: (v) => backend.labFps = v
                    }
                    RowLayout {
                        Label { text: "Окно захвата"; color: win.muted; font.pixelSize: 12; Layout.fillWidth: true }
                        SpinBox {
                            id: roiSize
                            from: 32; to: 800; stepSize: 16; editable: true
                            value: backend.roiW
                            implicitWidth: 110
                            onValueModified: backend.setRoiSize(value, value)
                        }
                    }
                    Item { implicitHeight: 8 }
                }
            }
        }
    }
}
