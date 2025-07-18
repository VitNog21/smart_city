const amqp = require('amqplib');

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
 * Conecta ao RabbitMQ e publica uma mensagem de forma assíncrona e confiável,
 * usando a API baseada em Promises (async/await).
 * @param {string} routingKey - O tópico para o qual a mensagem será enviada.
 * @param {object} messageBody - O objeto JavaScript a ser enviado como JSON.
 */
async function publishMessage(routingKey, messageBody) {
    let connection;
    try {
        const connStr = `amqp://user:password@${RABBITMQ_HOST}`;
        connection = await amqp.connect(connStr);
        const channel = await connection.createChannel();
        
        const exchange = 'smart_city';
        await channel.assertExchange(exchange, 'topic', { durable: false });
        
        channel.publish(exchange, routingKey, Buffer.from(JSON.stringify(messageBody)));

    } catch (err) {
        console.error(`[${DEVICE_ID}] ERRO ao publicar no RabbitMQ:`, err.message);
    } finally {
        if (connection) {
            // Aguarda um pequeno instante antes de fechar para garantir o envio da mensagem.
            await new Promise(resolve => setTimeout(resolve, 500));
            await connection.close();
        }
    }
}

/**
 * Prepara e envia a mensagem de presença (heartbeat) do dispositivo
 * para o tópico de descoberta do Gateway.
 */
function sendHeartbeat() {
    const routingKey = `device.discovery.${DEVICE_ID}`;
    console.log(`[${DEVICE_ID}] Enviando anúncio/heartbeat...`);
    publishMessage(routingKey, deviceState);
}

// Simula a leitura de um novo dado do sensor e o publica no tópico de dados a cada 15 segundos.
setInterval(() => {
    deviceState.value = parseFloat((20 + Math.random() * 5 - 2.5).toFixed(2));
    const routingKey = `device.data.${DEVICE_TYPE}.${DEVICE_ID}`;
    console.log(`[${DEVICE_ID}] Enviando dado: ${deviceState.value}°C`);
    publishMessage(routingKey, deviceState);
}, 15000);

// Envia o heartbeat do dispositivo para o Gateway a cada 10 segundos para indicar que está ativo.
setInterval(sendHeartbeat, 10000);

// Envia o anúncio de presença inicial imediatamente quando o script é iniciado.
console.log(`[*] Sensor '${DEVICE_ID}': Iniciado. Anunciando presença...`);
sendHeartbeat();