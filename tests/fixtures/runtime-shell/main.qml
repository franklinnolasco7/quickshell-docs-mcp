import Quickshell
import Quickshell.Io
import QtQuick

// Minimal managed-runtime fixture shell. Exposes an IpcHandler target
// "inspector" so runtime tools can introspect and drive the UI over `qs ipc`.
PanelWindow {
    id: root
    width: 200
    height: 60
    color: "#1e1e2e"

    property string greeting: "hello"
    property int counter: 0

    Text {
        id: label
        anchors.centerIn: parent
        text: root.greeting + " #" + root.counter
        color: "#cdd6f4"
    }

    IpcHandler {
        target: "inspector"

        function getProperty(name: string): string {
            return String(root[name]);
        }

        function setProperty(name: string, value: string): void {
            root[name] = value;
        }

        function getGreeting(): string {
            return root.greeting;
        }

        function getCounter(): int {
            return root.counter;
        }

        function bumpCounter(): void {
            root.counter += 1;
        }

        signal counterChanged(value: int);
    }
}
