import asyncio
import json
import threading
import socket
import pika
import grpc
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, Any, List
import time
import subprocess

# Forçar o caminho para o reloader do Uvicorn e para imports diretos
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import device_pb2
import device_pb2_grpc

# --- Configurações ---
GATEWAY_HOST = '0.0.0.0'
GATEWAY_PORT = 8000
RABBITMQ_HOST = 'localhost'
MULTICAST_GROUP = '224.1.1.1'
MULTICAST_PORT = 5007

# --- Lógica para Criação Dinâmica de Dispositivos ---
SCRIPT_MAP = {
    "light_post": ["python", "-m", "devices.poste"],
    "temperature_sensor": ["node", "devices/JS/sensor_temperatura.js"]
}
next_grpc_port = 50051 # Porta inicial para o primeiro atuador dinâmico

# --- Estado do Gateway ---
devices: Dict[str, Dict[str, Any]] = {}
update_queues: List[asyncio.Queue] = []
devices_lock = threading.Lock()

app = FastAPI()

# --- Comunicação entre Threads e Startup ---
main_event_loop = None

@app.on_event("startup")
async def startup_event():
    """Obtém o loop de eventos principal e inicia as tarefas de background."""
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    main_event_loop.run_in_executor(None, pika_subscriber, main_event_loop)
    main_event_loop.run_in_executor(None, udp_discover, main_event_loop)

# --- Montagem de Arquivos Estáticos ---
app.mount("/static", StaticFiles(directory="client"), name="static")

# --- Endpoints da API REST ---
@app.get("/")
async def read_root():
    with open("client/index.html") as f:
        return HTMLResponse(content=f.read(), status_code=200)

@app.post("/api/devices/create")
async def create_device(config: Dict[str, Any]):
    global next_grpc_port
    device_type = config.get("type")
    device_id = config.get("id")
    location = config.get("location")

    if not all([device_type, device_id, location]):
        return {"error": "Tipo, ID e localização são obrigatórios"}, 400

    command_parts = SCRIPT_MAP.get(device_type)
    if not command_parts:
        return {"error": "Tipo de dispositivo inválido"}, 400

    command_parts = command_parts[:] # Cria uma cópia da lista
    command_parts.extend(["--id", device_id, "--location", location])

    if device_type == "light_post":
        command_parts.extend(["--port", str(next_grpc_port)])
        next_grpc_port += 1
    
    try:
        print(f"--- [!] Gateway: Criando novo dispositivo com comando: {' '.join(command_parts)} ---")
        subprocess.Popen(command_parts, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return {"message": f"Comando para criar o dispositivo '{device_id}' enviado com sucesso."}
    except Exception as e:
        print(f"--- [!] Gateway: Falha ao criar processo do dispositivo: {e} ---")
        return {"error": f"Falha ao iniciar o processo do dispositivo: {e}"}, 500

@app.post("/api/devices/{device_id}/command")
async def device_command(device_id: str, command_data: Dict[str, Any]):
    with devices_lock:
        device_info = devices.get(device_id)
    
    if not device_info or 'grpc_port' not in device_info or not device_info['grpc_port']:
        return {"error": "Dispositivo não é um atuador ou não possui porta gRPC."}, 404

    try:
        grpc_port = device_info['grpc_port']
        status_to_send = command_data.get("status", False)
        async with grpc.aio.insecure_channel(f'localhost:{grpc_port}') as channel:
            stub = device_pb2_grpc.DeviceServiceStub(channel)
            response = await stub.SetStatus(device_pb2.CommandRequest(device_id=device_id, status=status_to_send))
            print(f"--- [>] Gateway: Comando gRPC enviado para {device_id}. Resposta: {response.message} ---")
            return {"message": response.message, "status": "success"}
    except grpc.aio.AioRpcError as e:
        print(f"--- [!] Gateway: FALHA na chamada gRPC para {device_id}: {e.details()} ---")
        return {"error": f"gRPC call failed: {e.details()}"}, 500

async def sse_generator(request: Request):
    queue = asyncio.Queue()
    update_queues.append(queue)
    try:
        while True:
            update_data = await queue.get()
            yield f"data: {json.dumps(update_data)}\n\n"
            queue.task_done()
    except asyncio.CancelledError:
        update_queues.remove(queue)

async def push_update():
    with devices_lock:
        data_to_send = list(devices.values())
    for q in update_queues:
        await q.put(data_to_send)

@app.get("/api/events")
async def event_stream(request: Request):
    return StreamingResponse(sse_generator(request), media_type="text/event-stream")

@app.get("/api/devices")
async def get_devices():
    with devices_lock:
        return list(devices.values())

def pika_subscriber(loop: asyncio.AbstractEventLoop):
    while True:
        try:
            credentials = pika.PlainCredentials('user', 'password')
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials))
            channel = connection.channel()
            channel.exchange_declare(exchange='smart_city', exchange_type='topic')
            result = channel.queue_declare(queue='', exclusive=True)
            queue_name = result.method.queue
            channel.queue_bind(exchange='smart_city', queue=queue_name, routing_key='device.#')
            print(' [*] RabbitMQ Subscriber: Waiting for messages.')

            def callback(ch, method, properties, body):
                message = json.loads(body)
                device_id = message['id']
                with devices_lock:
                    if device_id in devices:
                        devices[device_id].update(message)
                    else:
                        devices[device_id] = message
                asyncio.run_coroutine_threadsafe(push_update(), loop)

            channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            print(f" [!] RabbitMQ Subscriber: Connection failed: {e}. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f" [!] RabbitMQ Subscriber: An unexpected error occurred: {e}. Restarting...")
            time.sleep(5)

def udp_discover(loop: asyncio.AbstractEventLoop):
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listen_sock.bind((GATEWAY_HOST, GATEWAY_PORT))
    multicast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    
    discovery_message = json.dumps({"rabbitmq": {"host": RABBITMQ_HOST}}).encode()
    
    while True:
        print(" [>] UDP Discover: Broadcasting gateway discovery message...")
        multicast_sock.sendto(discovery_message, (MULTICAST_GROUP, MULTICAST_PORT))
        
        listen_sock.settimeout(10.0)
        while True:
            try:
                data, addr = listen_sock.recvfrom(1024)
                device_info = json.loads(data.decode())
                device_id = device_info['id']
                
                with devices_lock:
                    if device_id not in devices:
                        devices[device_id] = {}
                    devices[device_id].update(device_info)
                    devices[device_id]['address'] = addr[0]
                
                asyncio.run_coroutine_threadsafe(push_update(), loop)
            except socket.timeout:
                break 
        time.sleep(15)