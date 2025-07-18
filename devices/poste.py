import sys
import os
import grpc
import pika
import time
import json
import threading
from concurrent import futures
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from . import device_pb2
from . import device_pb2_grpc

# --- Leitura de Argumentos ---
parser = argparse.ArgumentParser(description="Simulador de Poste de Luz Inteligente.")
parser.add_argument("--id", type=str, required=True, help="ID único do dispositivo.")
parser.add_argument("--port", type=int, required=True, help="Porta gRPC para o dispositivo.")
parser.add_argument("--location", type=str, default="Localização não definida", help="Localização do dispositivo.")
args = parser.parse_args()

# --- Configurações do Dispositivo ---
DEVICE_ID = args.id
DEVICE_TYPE = "light_post"
GRPC_PORT = args.port
RABBITMQ_HOST = "localhost"

# --- Estado do Dispositivo ---
device_state = {
    "id": DEVICE_ID,
    "type": DEVICE_TYPE,
    "status": "OFF",
    "location": args.location,
    "grpc_port": GRPC_PORT
}

# --- Lógica de Publicação ---
def publish_message(routing_key, message_body):
    try:
        credentials = pika.PlainCredentials('user', 'password')
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials))
        channel = connection.channel()
        channel.exchange_declare(exchange='smart_city', exchange_type='topic')
        channel.basic_publish(exchange='smart_city', routing_key=routing_key, body=json.dumps(message_body))
        # print(f" [>] {DEVICE_ID}: Mensagem enviada para '{routing_key}'")
        connection.close()
    except Exception as e:
        print(f" [!] {DEVICE_ID}: Falha ao publicar no RabbitMQ: {e}")

# --- Heartbeat e Anúncio ---
def heartbeat_thread():
    """Envia uma mensagem de presença/heartbeat a cada 10 segundos."""
    routing_key = f"device.discovery.{DEVICE_ID}"
    while True:
        # print(f" [>] {DEVICE_ID}: Enviando heartbeat...")
        publish_message(routing_key, device_state)
        time.sleep(10)

# --- Implementação do Servidor gRPC ---
class DeviceServiceImpl(device_pb2_grpc.DeviceServiceServicer):
    def SetStatus(self, request, context):
        global device_state
        new_status = "ON" if request.status else "OFF"
        
        if device_state["status"] != new_status:
            print(f" [!] {DEVICE_ID}: Comando gRPC recebido! Mudar estado para: {new_status}")
            device_state["status"] = new_status
            
            # Publica a mudança de estado no tópico de DADOS
            routing_key = f"device.data.{DEVICE_TYPE}.{DEVICE_ID}"
            publish_message(routing_key, device_state)
        
        return device_pb2.StatusResponse(message=f"Poste {DEVICE_ID} agora está {new_status}")

def serve_grpc():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    device_pb2_grpc.add_DeviceServiceServicer_to_server(DeviceServiceImpl(), server)
    server.add_insecure_port(f'[::]:{GRPC_PORT}')
    server.start()
    print(f" [*] Poste '{DEVICE_ID}': Servidor gRPC iniciado na porta {GRPC_PORT}")
    server.wait_for_termination()

if __name__ == '__main__':
    # Inicia a thread de heartbeat
    hb_thread = threading.Thread(target=heartbeat_thread, daemon=True)
    hb_thread.start()

    # Inicia o servidor gRPC na thread principal
    serve_grpc()