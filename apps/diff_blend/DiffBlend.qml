import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1180
    height: 720
    visible: true
    title: "Difference Blend — захват и разница кадров"
    color: "#15171c"

    palette.window: "#15171c"
    palette.base: "#1e2128"
    palette.button: "#262a33"
    palette.text: "#e6e8ee"
    palette.buttonText: "#e6e8ee"
    palette.windowText: "#e6e8ee"
    palette.highlight: "#4c8dff"

    readonly property color panel: "#1c1f26"
    readonly property color muted: "#8a90a0"

    component Labeled: ColumnLayout {
        property alias text: lbl.text
        spacing: 2
        Label { id: lbl; color: win.muted; font.pixelSize: 11 }
    }

    header: ToolBar {
        background: Rectangle { color: "#1a1d23" }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 10

            Label { text: "Источник"; color: win.muted }
            ComboBox {
                id: sourceBox
                model: backend.screenAvailable() ? ["screen", "demo"] : ["demo"]
                currentIndex: Math.max(0, model.indexOf(backend.sourceKind))
                onActivated: backend.sourceKind = currentText
                implicitWidth: 110
            }
            Label { text: "X"; color: win.muted }
            SpinBox { from: 0; to: 10000; editable: true; value: backend.regionX; onValueModified: backend.regionX = value; implicitWidth: 100 }
            Label { text: "Y"; color: win.muted }
            SpinBox { from: 0; to: 10000; editable: true; value: backend.regionY; onValueModified: backend.regionY = value; implicitWidth: 100 }
            Label { text: "W"; color: win.muted }
            SpinBox { from: 8; to: 4000; editable: true; value: backend.regionW; onValueModified: backend.regionW = value; implicitWidth: 100 }
            Label { text: "H"; color: win.muted }
            SpinBox { from: 8; to: 4000; editable: true; value: backend.regionH; onValueModified: backend.regionH = value; implicitWidth: 100 }
            Label { text: "FPS"; color: win.muted }
            SpinBox { from: 1; to: 240; editable: true; value: backend.captureFps; onValueModified: backend.captureFps = value; implicitWidth: 90 }

            Item { Layout.fillWidth: true }

            Button {
                text: backend.running ? "Перезапустить" : "Старт"
                highlighted: !backend.running
                onClicked: backend.start()
            }
            Button {
                text: "Стоп"
                enabled: backend.running
                onClicked: backend.stop()
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12

        // ---------------------------------------------------------- views
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12

                Repeater {
                    model: [
                        { key: "live", title: "Захват" },
                        { key: "diff", title: "Difference Blend" }
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: win.panel
                        radius: 6

                        Label {
                            id: viewTitle
                            text: modelData.title
                            color: win.muted
                            anchors { left: parent.left; top: parent.top; margins: 10 }
                        }
                        Image {
                            anchors { fill: parent; margins: 10; topMargin: 32 }
                            fillMode: Image.PreserveAspectFit
                            cache: false
                            smooth: false
                            source: backend.frameId > 0 ? "image://frames/" + modelData.key + "/" + backend.frameId : ""
                        }
                        Label {
                            anchors.centerIn: parent
                            visible: backend.frameId === 0
                            text: "Нажмите «Старт»"
                            color: win.muted
                        }
                    }
                }
            }

            Label {
                text: backend.status
                color: win.muted
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
        }

        // ---------------------------------------------------------- controls
        Rectangle {
            Layout.preferredWidth: 280
            Layout.fillHeight: true
            color: win.panel
            radius: 6

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 12

                Label { text: "Статистика"; font.bold: true }
                GridLayout {
                    columns: 2
                    columnSpacing: 12
                    rowSpacing: 4
                    Label { text: "FPS обработки"; color: win.muted }
                    Label { text: backend.fps.toFixed(1); font.family: "monospace" }
                    Label { text: "Изменилось"; color: win.muted }
                    Label { text: backend.changedPct.toFixed(2) + " %"; font.family: "monospace" }
                    Label { text: "Макс. разница"; color: win.muted }
                    Label { text: backend.maxDiff; font.family: "monospace" }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: "#2c303a" }
                Label { text: "Сравнивать с"; font.bold: true }

                ColumnLayout {
                    spacing: 0
                    RadioButton {
                        text: "предыдущим кадром"
                        checked: backend.mode === "prev"
                        onToggled: if (checked) backend.mode = "prev"
                    }
                    RowLayout {
                        Layout.leftMargin: 32
                        enabled: backend.mode === "prev"
                        Label { text: "через N кадров"; color: win.muted }
                        SpinBox { from: 1; to: 15; value: backend.frameStep; onValueModified: backend.frameStep = value; implicitWidth: 90 }
                    }
                    RadioButton {
                        text: "опорным снимком"
                        checked: backend.mode === "ref"
                        onToggled: if (checked) backend.mode = "ref"
                    }
                    Button {
                        Layout.leftMargin: 32
                        text: backend.hasReference ? "Обновить снимок" : "Сделать снимок"
                        enabled: backend.running
                        onClicked: { backend.snapshotReference(); backend.mode = "ref" }
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: "#2c303a" }
                Label { text: "Обработка"; font.bold: true }

                Labeled {
                    Layout.fillWidth: true
                    text: "Усиление: ×" + backend.gain.toFixed(1)
                    Slider {
                        Layout.fillWidth: true
                        from: 1; to: 20; stepSize: 0.5
                        value: backend.gain
                        onMoved: backend.gain = value
                    }
                }
                Labeled {
                    Layout.fillWidth: true
                    text: "Порог шума: " + backend.threshold
                    Slider {
                        Layout.fillWidth: true
                        from: 0; to: 100; stepSize: 1
                        value: backend.threshold
                        onMoved: backend.threshold = value
                    }
                }
                CheckBox {
                    text: "Бинарная маска"
                    checked: backend.binary
                    onToggled: backend.binary = checked
                }

                Item { Layout.fillHeight: true }
            }
        }
    }
}
