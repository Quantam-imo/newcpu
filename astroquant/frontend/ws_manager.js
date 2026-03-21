export class WSManager {
    constructor(path, onMessage) {
        this.path = path;
        this.onMessage = onMessage;
        this.ws = null;
        this.reconnectDelay = 2000;
        this.connect();
    }

    connect() {
        const protocol = location.protocol === "https:" ? "wss" : "ws";
        this.ws = new WebSocket(`${protocol}://${location.host}${this.path}`);

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.onMessage(data);
        };

        this.ws.onclose = () => {
            setTimeout(() => this.connect(), this.reconnectDelay);
        };

        this.ws.onerror = () => {
            this.ws.close();
        };
    }

    close() {
        if (this.ws) this.ws.close();
    }
}
