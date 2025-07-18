import sys
import os
import grpc
import pika
import time
import json
import threading
from concurrent import futures
import argparse

# Garante que os módulos gRPC gerados possam ser importados.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from . import device_pb2
from . import device_pb2_grpc

parser = argparse.ArgumentParser(description="Simulador de Câmera Inteligente.")
parser.add_argument("--id", type=str, required=True, help="ID único do dispositivo.")
parser.add_argument("--port", type=int, required=True, help="Porta gRPC para o dispositivo.")
parser.add_argument("--location", type=str, default="Localização não definida", help="Localização do dispositivo.")
args = parser.parse_args()

DEVICE_ID = args.id
DEVICE_TYPE = "camera"
GRPC_PORT = args.port
RABBITMQ_HOST = "localhost"

device_state = {
    "id": DEVICE_ID,
    "type": DEVICE_TYPE,
    "status": "ON",
    "resolution": "HD",
    "location": args.location,
    "grpc_port": GRPC_PORT
}

def publish_message(routing_key, message_body):
    """
    Estabelece uma conexão com o RabbitMQ e publica uma única mensagem
    JSON para um tópico (routing key) específico.
    """
    try:
        credentials = pika.PlainCredentials('user', 'password')
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials))
        channel = connection.channel()
        channel.exchange_declare(exchange='smart_city', exchange_type='topic')
        channel.basic_publish(exchange='smart_city', routing_key=routing_key, body=json.dumps(message_body))
        connection.close()
    except Exception as e:
        print(f" [!] {DEVICE_ID}: Falha ao publicar no RabbitMQ: {e}")

def heartbeat_thread():
    """
    Executada em uma thread separada, envia uma mensagem de presença (heartbeat)
    periodicamente para o tópico de descoberta do Gateway.
    """
    routing_key = f"device.discovery.{DEVICE_ID}"
    while True:
        publish_message(routing_key, device_state)
        time.sleep(10)

class DeviceServiceImpl(device_pb2_grpc.DeviceServiceServicer):
    """
    Implementa os métodos do serviço gRPC para a câmera, permitindo que o
    Gateway chame remotamente as funções deste dispositivo.
    """
    def SetStatus(self, request, context):
        """
        Altera o estado de energia da câmera (ON/OFF) conforme solicitado pelo Gateway
        e publica a atualização no tópico de dados.
        """
        global device_state
        new_status = "ON" if request.status else "OFF"
        if device_state["status"] != new_status:
            print(f" [!] {DEVICE_ID}: Comando gRPC recebido! Mudar status para: {new_status}")
            device_state["status"] = new_status
            routing_key = f"device.data.{DEVICE_TYPE}.{DEVICE_ID}"
            publish_message(routing_key, device_state)
        return device_pb2.StatusResponse(message=f"Câmera {DEVICE_ID} agora está {new_status}")

    def SetConfig(self, request, context):
        """
        Altera uma configuração específica da câmera (ex: resolução) conforme
        solicitado pelo Gateway e publica a atualização no tópico de dados.
        """
        global device_state
        config_key = request.key
        config_value = request.value
        
        if config_key == "resolution" and device_state.get(config_key) != config_value:
            print(f" [!] {DEVICE_ID}: Comando gRPC recebido! Mudar {config_key} para: {config_value}")
            device_state[config_key] = config_value
            # Publica a mudança de estado no tópico de DADOS para notificar o Gateway.
            routing_key = f"device.data.{DEVICE_TYPE}.{DEVICE_ID}"
            publish_message(routing_key, device_state)
            return device_pb2.StatusResponse(message=f"Resolução da Câmera {DEVICE_ID} alterada para {config_value}")
        
        return device_pb2.StatusResponse(message=f"Configuração '{config_key}' não alterada.")

def serve_grpc():
    """
    Inicializa e inicia o servidor gRPC, que fica aguardando por chamadas
    de métodos remotos vindas do Gateway.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    device_pb2_grpc.add_DeviceServiceServicer_to_server(DeviceServiceImpl(), server)
    server.add_insecure_port(f'[::]:{GRPC_PORT}')
    server.start()
    print(f" [*] Câmera '{DEVICE_ID}': Servidor gRPC iniciado na porta {GRPC_PORT}")
    server.wait_for_termination()

if __name__ == '__main__':
    hb_thread = threading.Thread(target=heartbeat_thread, daemon=True)
    hb_thread.start()
    serve_grpc()