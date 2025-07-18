const amqp = require('amqplib/callback_api');

// --- Leitura de Argumentos da Linha de Comando ---
const args = {};
process.argv.slice(2).forEach((val, index, array) => {
    if (val.startsWith('--')) {
        const key = val.substring(2);
        if (array[index + 1] && !array[index + 1].startsWith('--')) {
            args[key] = array[index + 1];
        }
    }
});

// --- Configurações do Dispositivo ---
const DEVICE_ID = args.id || "sensor-js-01";
const DEVICE_TYPE = "temperature_sensor";
const RABBITMQ_HOST = "localhost";

const deviceState = {
    id: DEVICE_ID,
    type: DEVICE_TYPE,
    value: 20.0,
    unit: "Celsius",
    location: args.location || "Localização Padrão"
};

// --- Lógica de Publicação (com log de erro) ---
function publishMessage(routingKey, messageBody) {
    const connStr = `amqp://user:password@${RABBITMQ_HOST}`;
    amqp.connect(connStr, (err, conn) => {
        if (err) {
            // ERRO AGORA SERÁ VISÍVEL NO TERMINAL
            console.error(`[${DEVICE_ID}] ERRO ao conectar no RabbitMQ:`, err.message);
            return;
        }
        conn.createChannel((err, ch) => {
            if (err) {
                console.error(`[${DEVICE_ID}] ERRO ao criar canal:`, err.message);
                conn.close();
                return;
            };
            const exchange = 'smart_city';
            ch.assertExchange(exchange, 'topic', { durable: false });
            ch.publish(exchange, routingKey, Buffer.from(JSON.stringify(messageBody)));
            // console.log(`[${DEVICE_ID}] Mensagem enviada para '${routingKey}'`);
            setTimeout(() => { conn.close(); }, 500);
        });
    });
}

// --- Envio de Dados do Sensor (tópico device.data) ---
setInterval(() => {
    deviceState.value = parseFloat((20 + Math.random() * 5 - 2.5).toFixed(2));
    const routingKey = `device.data.${DEVICE_TYPE}.${DEVICE_ID}`;
    console.log(`[${DEVICE_ID}] Enviando dado: ${deviceState.value}°C`);
    publishMessage(routingKey, deviceState);
}, 15000);

// --- Heartbeat e Anúncio (tópico device.discovery) ---
function sendHeartbeat() {
    const routingKey = `device.discovery.${DEVICE_ID}`;
    console.log(`[${DEVICE_ID}] Enviando anúncio/heartbeat...`);
    publishMessage(routingKey, deviceState);
}

// Envia heartbeat a cada 10 segundos
setInterval(sendHeartbeat, 10000);

// Envia o anúncio inicial imediatamente ao iniciar
console.log(`[*] Sensor '${DEVICE_ID}': Iniciado. Anunciando presença...`);
sendHeartbeat();