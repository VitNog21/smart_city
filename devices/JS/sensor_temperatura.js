const amqp = require('amqplib/callback_api');

const args = {};
process.argv.slice(2).forEach((val, index, array) => {
    if (val.startsWith('--')) {
        const key = val.substring(2);
        if (array[index + 1] && !array[index + 1].startsWith('--')) {
            args[key] = array[index + 1];
        }
    }
});

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

/**
 * Estabelece uma conexão com o RabbitMQ e publica uma única mensagem
 * JSON para um tópico (routing key) específico.
 * @param {string} routingKey - O tópico para o qual a mensagem será enviada.
 * @param {object} messageBody - O objeto JavaScript a ser enviado como JSON.
 */
function publishMessage(routingKey, messageBody) {
    const connStr = `amqp://user:password@${RABBITMQ_HOST}`;
    amqp.connect(connStr, (err, conn) => {
        if (err) {
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
            setTimeout(() => { conn.close(); }, 500);
        });
    });
}

/**
 * Envia uma mensagem de presença (heartbeat) para o tópico de descoberta do Gateway.
 */
function sendHeartbeat() {
    const routingKey = `device.discovery.${DEVICE_ID}`;
    console.log(`[${DEVICE_ID}] Enviando anúncio/heartbeat...`);
    publishMessage(routingKey, deviceState);
}

// Bloco que simula a leitura de um novo dado do sensor e o publica a cada 15 segundos.
setInterval(() => {
    deviceState.value = parseFloat((20 + Math.random() * 5 - 2.5).toFixed(2));
    const routingKey = `device.data.${DEVICE_TYPE}.${DEVICE_ID}`;
    console.log(`[${DEVICE_ID}] Enviando dado: ${deviceState.value}°C`);
    publishMessage(routingKey, deviceState);
}, 15000);

// Bloco que envia o heartbeat do dispositivo para o Gateway a cada 10 segundos.
setInterval(sendHeartbeat, 10000);

// Bloco que envia o anúncio de presença inicial assim que o script é iniciado.
console.log(`[*] Sensor '${DEVICE_ID}': Iniciado. Anunciando presença...`);
sendHeartbeat();