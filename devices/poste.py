import sys
import os
import grpc
import pika
import time
import json
import threading
from concurrent import futures
import argparse
import socket

# Garante que os módulos gRPC gerados possam ser importados.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from . import device_pb2
from . import device_pb2_grpc

parser = argparse.ArgumentParser(description="Simulador de Poste de Luz Inteligente.")
parser.add_argument("--id", type=str, required=True)
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--location", type=str, default="Localização não definida")
args = parser.parse_args()

DEVICE_ID = args.id
DEVICE_TYPE = "light_post"
GRPC_PORT = args.port
MULTICAST_GROUP = '224.1.1.1'
MULTICAST_PORT = 5007

device_state = {
    "id": DEVICE_ID,
    "type": DEVICE_TYPE,
    "status": "OFF",
    "location": args.location,
    "grpc_port": GRPC_PORT
}
rabbit_mq_info = {}

def publish_state():
    """
    Publica o estado atual do dispositivo no RabbitMQ. Esta função só executa
    após as informações do broker serem recebidas via descoberta UDP.
    """
    if not rabbit_mq_info:
        return
    try:
        credentials = pika.PlainCredentials('user', 'password')
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_mq_info['host'], credentials=credentials))
        channel = connection.channel()
        channel.exchange_declare(exchange='smart_city', exchange_type='topic')
        routing_key = f"device.{DEVICE_TYPE}.{DEVICE_ID}"
        message = json.dumps(device_state)
        channel.basic_publish(exchange='smart_city', routing_key=routing_key, body=message)
        connection.close()
    except Exception as e:
        print(f" [!] {DEVICE_ID}: Falha ao publicar estado: {e}")

class DeviceServiceImpl(device_pb2_grpc.DeviceServiceServicer):
    """
    Implementa os métodos do serviço gRPC para o poste de luz, permitindo que
    o Gateway chame remotamente as funções deste dispositivo.
    """
    def SetStatus(self, request, context):
        """
        Altera o estado do dispositivo (ON/OFF) conforme solicitado pelo Gateway
        e publica a atualização de estado.
        """
        global device_state
        new_status = "ON" if request.status else "OFF"
        if device_state["status"] != new_status:
            device_state["status"] = new_status
            publish_state()
        return device_pb2.StatusResponse(message=f"Poste {DEVICE_ID} agora está {new_status}")

def listen_for_discovery():
    """
    Executada em uma thread separada para escutar por broadcasts UDP Multicast
    do Gateway, responder com suas informações e anunciar sua presença.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', MULTICAST_PORT))
    mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton('0.0.0.0')
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    print(f" [*] {DEVICE_ID}: Aguardando descoberta pelo Gateway...")
    while True:
        data, addr = sock.recvfrom(1024)
        print(f" [*] {DEVICE_ID}: Gateway descoberto em {addr}")
        global rabbit_mq_info
        message = json.loads(data.decode())
        rabbit_mq_info = message.get('rabbitmq', {})
        response_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        response_data = json.dumps({
            "id": DEVICE_ID,
            "type": DEVICE_TYPE,
            "grpc_port": GRPC_PORT
        }).encode()
        response_sock.sendto(response_data, addr)
        response_sock.close()
        publish_state()

def serve_grpc():
    """
    Inicializa e inicia o servidor gRPC, que fica aguardando por chamadas
    de métodos remotos vindas do Gateway.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    device_pb2_grpc.add_DeviceServiceServicer_to_server(DeviceServiceImpl(), server)
    server.add_insecure_port(f'[::]:{GRPC_PORT}')
    server.start()
    print(f" [*] Poste '{DEVICE_ID}': Servidor gRPC iniciado na porta {GRPC_PORT}")
    server.wait_for_termination()

if __name__ == '__main__':
    discovery_thread = threading.Thread(target=listen_for_discovery, daemon=True)
    discovery_thread.start()
    serve_grpc()