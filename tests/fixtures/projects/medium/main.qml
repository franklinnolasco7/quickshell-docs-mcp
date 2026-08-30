import Quickshell
import Quickshell.Services.Pipewire
import QtQuick 2.15
import "components"

PanelWindow {
    width: 200

    Text {
        text: "volume"
    }

    VolumeWidget {}
}
