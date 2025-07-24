const dgram = require('dgram');
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
const MULTICAST_GROUP = '224.1.1.1';
const MULTICAST_PORT = 5007;

// O estado do dispositivo, que será enviado nas publicações de dados.
const deviceState = {
    id: DEVICE_ID,
    type: DEVICE_TYPE,
    value: 20.0,
    unit: "Celsius",
    location: args.location || "Localização Padrão JS"
};

// Variável para armazenar a configuração do RabbitMQ recebida do Gateway.
let rabbitMQConfig = null;
let dataInterval = null; // Variável para controlar o intervalo de envio de dados.

/**
 * Conecta ao RabbitMQ e publica uma mensagem de forma assíncrona.
 * Só funciona após o gateway ser descoberto.
 * @param {string} routingKey - O tópico para o qual a mensagem será enviada.
 * @param {object} messageBody - O objeto JavaScript a ser enviado como JSON.
 */
async function publishMessage(routingKey, messageBody) {
    if (!rabbitMQConfig) {
        console.error(`[${DEVICE_ID}] RabbitMQ não configurado. Aguardando descoberta...`);
        return;
    }

    let connection;
    try {
        const connStr = `amqp://user:password@${rabbitMQConfig.host}`;
        connection = await amqp.connect(connStr);
        const channel = await connection.createChannel();
        
        const exchange = 'smart_city';
        await channel.assertExchange(exchange, 'topic', { durable: false });
        
        channel.publish(exchange, routingKey, Buffer.from(JSON.stringify(messageBody)));

    } catch (err) {
        console.error(`[${DEVICE_ID}] ERRO ao publicar no RabbitMQ:`, err.message);
    } finally {
        if (connection) {
            await new Promise(resolve => setTimeout(resolve, 500));
            await connection.close();
        }
    }
}

/**
 * Inicia o envio periódico de dados de temperatura.
 * Esta função é chamada somente após o dispositivo ser descoberto.
 */
function startSendingData() {
    if (dataInterval) {
        // Evita criar múltiplos intervalos se a descoberta ocorrer mais de uma vez.
        return;
    }
    
    console.log(`[${DEVICE_ID}] Gateway descoberto. Iniciando envio de dados a cada 15 segundos.`);
    
    dataInterval = setInterval(() => {
        deviceState.value = parseFloat((20 + Math.random() * 5 - 2.5).toFixed(2));
        const routingKey = `device.data.${DEVICE_TYPE}.${DEVICE_ID}`;
        console.log(`[${DEVICE_ID}] Enviando dado: ${deviceState.value}°C`);
        publishMessage(routingKey, deviceState);
    }, 15000);
}


/**
 * Cria e configura o socket UDP para escutar as mensagens de descoberta do Gateway.
 */
function listenForDiscovery() {
    const socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });

    socket.on('error', (err) => {
        console.error(`[${DEVICE_ID}] Erro no socket: \n${err.stack}`);
        socket.close();
    });

    // Escuta por mensagens multicast do Gateway.
    socket.on('message', (msg, rinfo) => {
        console.log(`[${DEVICE_ID}] Mensagem de descoberta recebida do Gateway em ${rinfo.address}:${rinfo.port}`);
        
        // Armazena a configuração do RabbitMQ.
        const gatewayMessage = JSON.parse(msg.toString());
        rabbitMQConfig = gatewayMessage.rabbitmq;

        // Prepara a resposta para o Gateway.
        const responsePayload = Buffer.from(JSON.stringify({
            id: DEVICE_ID,
            type: DEVICE_TYPE,
            // Sensores não têm porta gRPC, então não a enviamos.
        }));

        // Envia a resposta diretamente para o Gateway (Unicast).
        const responseSocket = dgram.createSocket('udp4');
        responseSocket.send(responsePayload, 0, responsePayload.length, rinfo.port, rinfo.address, (err) => {
            if (err) {
                console.error(`[${DEVICE_ID}] Erro ao enviar resposta UDP:`, err);
            } else {
                console.log(`[${DEVICE_ID}] Resposta de descoberta enviada para o Gateway.`);
            }
            responseSocket.close();
        });

        // Inicia o envio de dados, pois o Gateway agora está ciente deste dispositivo.
        startSendingData();
    });

    socket.bind(MULTICAST_PORT, () => {
        socket.addMembership(MULTICAST_GROUP);
        console.log(`[*] Sensor '${DEVICE_ID}': Aguardando descoberta pelo Gateway no grupo ${MULTICAST_GROUP}:${MULTICAST_PORT}`);
    });
}

// Inicia o processo de escuta pela descoberta.
listenForDiscovery();