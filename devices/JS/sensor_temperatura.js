const dgram = require('dgram');
const amqp = require('amqplib/callback_api');

// --- Leitura de Argumentos da Linha de Comando ---
const args = {};
process.argv.slice(2).forEach((val, index, array) => {
    if (val.startsWith('--')) {
        const key = val.substring(2);
        // Pega o próximo valor se ele não for outra flag
        if (array[index + 1] && !array[index + 1].startsWith('--')) {
            args[key] = array[index + 1];
        }
    }
});

// --- Configurações do Dispositivo (Agora Dinâmicas) ---
const DEVICE_ID = args.id || "sensor-default-01"; // ID padrão caso não seja fornecido
const DEVICE_TYPE = "temperature_sensor";
const MULTICAST_GROUP = '224.1.1.1';
const MULTICAST_PORT = 5007;

let rabbitMqInfo = null;

const deviceState = {
    id: DEVICE_ID,
    type: DEVICE_TYPE,
    value: 20.0,
    unit: "Celsius",
    location: args.location || "Localização Padrão" // Localização padrão
};

// --- Lógica de Publicação ---
function publishState() {
    if (!rabbitMqInfo) {
        return;
    }

    const connStr = `amqp://user:password@${rabbitMqInfo.host}`;
    amqp.connect(connStr, (err, conn) => {
        if (err) {
            console.error(`[${DEVICE_ID}] Erro ao conectar no RabbitMQ:`, err.message);
            return;
        }
        conn.createChannel((err, ch) => {
            if (err) throw err;
            const exchange = 'smart_city';
            const routingKey = `device.${DEVICE_TYPE}.${DEVICE_ID}`;
            const msg = JSON.stringify(deviceState);

            ch.assertExchange(exchange, 'topic', { durable: false });
            ch.publish(exchange, routingKey, Buffer.from(msg));
            console.log(`[${DEVICE_ID}] Enviado: '${msg}'`);
        });

        setTimeout(() => { conn.close(); }, 500);
    });
}

// Simula uma nova leitura a cada 15 segundos
setInterval(() => {
    deviceState.value = parseFloat((20 + Math.random() * 5 - 2.5).toFixed(2));
    publishState();
}, 15000);

// --- Lógica de Descoberta ---
const socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });

socket.on('listening', () => {
    try {
        socket.addMembership(MULTICAST_GROUP);
        const address = socket.address();
        console.log(`[${DEVICE_ID}] Aguardando descoberta do gateway em ${address.address}:${address.port}`);
    } catch (e) {
        console.error(`[${DEVICE_ID}] Falha ao entrar no grupo multicast:`, e);
    }
});

socket.on('message', (msg, rinfo) => {
    console.log(`[${DEVICE_ID}] Gateway descoberto em ${rinfo.address}:${rinfo.port}`);
    const gatewayData = JSON.parse(msg.toString());
    rabbitMqInfo = gatewayData.rabbitmq;

    const responseData = JSON.stringify({
        id: DEVICE_ID,
        type: DEVICE_TYPE,
        grpc_port: null // Sensores não têm porta gRPC
    });

    const client = dgram.createSocket('udp4');
    client.send(responseData, rinfo.port, rinfo.address, (err) => {
        client.close();
    });
    
    publishState(); // Publica o estado inicial
});

socket.bind(MULTICAST_PORT);