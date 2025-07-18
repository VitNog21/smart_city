import sys
import os
import grpc
import pika
import time
import json
import threading
import socket
from concurrent import futures
import argparse # <-- Importar a biblioteca

# Forçar o Python a encontrar os módulos na pasta correta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from . import device_pb2
from . import device_pb2_grpc

# --- Lendo Argumentos da Linha de Comando ---
parser = argparse.ArgumentParser(description="Simulador de Poste de Luz Inteligente.")
parser.add_argument("--id", type=str, required=True, help="ID único do dispositivo.")
parser.add_argument("--port", type=int, required=True, help="Porta gRPC para o dispositivo.")
parser.add_argument("--location", type=str, default="Localização não definida", help="Localização do dispositivo.")
args = parser.parse_args()

# --- Configurações do Dispositivo (Agora Dinâmicas) ---
DEVICE_ID = args.id
DEVICE_TYPE = "light_post"
GRPC_PORT = args.port
MULTICAST_GROUP = '224.1.1.1'
MULTICAST_PORT = 5007

# --- Estado do Dispositivo ---
device_state = {
    "id": DEVICE_ID,
    "type": DEVICE_TYPE,
    "status": "OFF",
    "location": args.location,
    "grpc_port": GRPC_PORT
}
rabbit_mq_info = {}

# O RESTANTE DO CÓDIGO (publish_state, DeviceServiceImpl, etc.) PERMANECE O MESMO
# ... (cole o restante do código do poste.py anterior aqui) ...
# --- Lógica de Publicação ---
def publish_state():
    """Publica o estado ATUAL do dispositivo no RabbitMQ."""
    if not rabbit_mq_info:
        # print(f" [!] {DEVICE_ID}: RabbitMQ info not available.")
        return
    
    try:
        credentials = pika.PlainCredentials('user', 'password')
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_mq_info['host'], credentials=credentials))
        channel = connection.channel()
        channel.exchange_declare(exchange='smart_city', exchange_type='topic')
        
        routing_key = f"device.{DEVICE_TYPE}.{DEVICE_ID}"
        message = json.dumps(device_state)
        
        channel.basic_publish(exchange='smart_city', routing_key=routing_key, body=message)
        print(f" [>] {DEVICE_ID}: Estado publicado: '{message}'")
        connection.close()
    except Exception as e:
        print(f" [!] {DEVICE_ID}: Falha ao publicar estado: {e}")

# --- Implementação do Servidor gRPC ---
class DeviceServiceImpl(device_pb2_grpc.DeviceServiceServicer):
    def SetStatus(self, request, context):
        global device_state
        new_status = "ON" if request.status else "OFF"
        
        print(f" [!] {DEVICE_ID}: Comando gRPC recebido! Mudar estado para: {new_status}")
        
        device_state["status"] = new_status
        publish_state()
        
        return device_pb2.StatusResponse(message=f"Poste {DEVICE_ID} agora está {new_status}")

# --- Lógica de Descoberta ---
def listen_for_discovery():
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
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    device_pb2_grpc.add_DeviceServiceServicer_to_server(DeviceServiceImpl(), server)
    server.add_insecure_port(f'[::]:{GRPC_PORT}')
    server.start()
    print(f" [*] {DEVICE_ID}: Servidor gRPC iniciado na porta {GRPC_PORT}")
    server.wait_for_termination()

if __name__ == '__main__':
    discovery_thread = threading.Thread(target=listen_for_discovery, daemon=True)
    discovery_thread.start()

    serve_grpc()