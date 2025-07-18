import asyncio
import json
import threading
import socket
import pika
import grpc
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict, Any, List, Set
import time
import subprocess

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import device_pb2
import device_pb2_grpc

# --- Configurações ---
GATEWAY_HOST = '0.0.0.0'
RABBITMQ_HOST = 'localhost'
DEVICE_TIMEOUT_SECONDS = 15 # Tempo em segundos para considerar um dispositivo offline

# --- Lógica para Criação Dinâmica ---
SCRIPT_MAP = {
    "light_post": ["python", "-m", "devices.poste"],
    "temperature_sensor": ["node", "devices/JS/sensor_temperatura.js"]
}
next_grpc_port = 50051

# --- Estado do Gateway ---
devices: Dict[str, Dict[str, Any]] = {}
update_queues: List[asyncio.Queue] = []
devices_lock = threading.Lock()

app = FastAPI()

# --- Comunicação entre Threads e Startup ---
main_event_loop = None

@app.on_event("startup")
async def startup_event():
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    main_event_loop.run_in_executor(None, pika_subscriber, main_event_loop)
    main_event_loop.run_in_executor(None, health_check_thread, main_event_loop)

# --- Montagem de Arquivos Estáticos ---
app.mount("/static", StaticFiles(directory="client"), name="static")

# --- Lógica de Health Check e Remoção ---
def health_check_thread(loop: asyncio.AbstractEventLoop):
    while True:
        time.sleep(5) # Verifica a cada 5 segundos
        
        devices_removed = False
        with devices_lock:
            # Cria uma lista de dispositivos para remover para evitar modificar o dict durante a iteração
            devices_to_remove = []
            for device_id, info in devices.items():
                last_seen = info.get('last_seen', 0)
                if time.time() - last_seen > DEVICE_TIMEOUT_SECONDS:
                    devices_to_remove.append(device_id)
            
            for device_id in devices_to_remove:
                print(f" [!] Health Check: Dispositivo '{device_id}' atingiu o timeout. Removendo.")
                del devices[device_id]
                devices_removed = True

        if devices_removed:
            asyncio.run_coroutine_threadsafe(push_update(), loop)

# --- Endpoints e outras funções ---
# (O código restante é para a funcionalidade principal)

def pika_subscriber(loop: asyncio.AbstractEventLoop):
    while True:
        try:
            credentials = pika.PlainCredentials('user', 'password')
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials))
            channel = connection.channel()
            channel.exchange_declare(exchange='smart_city', exchange_type='topic')
            
            # Fila para dados normais
            data_queue_result = channel.queue_declare(queue='', exclusive=True)
            data_queue_name = data_queue_result.method.queue
            channel.queue_bind(exchange='smart_city', queue=data_queue_name, routing_key='device.data.#')

            # Fila para anúncios de presença e heartbeats
            discovery_queue_result = channel.queue_declare(queue='', exclusive=True)
            discovery_queue_name = discovery_queue_result.method.queue
            channel.queue_bind(exchange='smart_city', queue=discovery_queue_name, routing_key='device.discovery.#')
            
            print(' [*] RabbitMQ Subscriber: Waiting for messages.')

            def on_message(ch, method, properties, body):
                message = json.loads(body)
                device_id = message['id']
                
                with devices_lock:
                    # Atualiza o timestamp sempre que ouvimos do dispositivo
                    message['last_seen'] = time.time()
                    if device_id in devices:
                        devices[device_id].update(message)
                    else:
                        print(f" [>] Discovery: Novo dispositivo anunciado: {device_id}")
                        devices[device_id] = message
                
                asyncio.run_coroutine_threadsafe(push_update(), loop)

            channel.basic_consume(queue=data_queue_name, on_message_callback=on_message, auto_ack=True)
            channel.basic_consume(queue=discovery_queue_name, on_message_callback=on_message, auto_ack=True)
            
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as e:
            print(f" [!] RabbitMQ Subscriber: Connection failed. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f" [!] RabbitMQ Subscriber: An unexpected error occurred: {e}. Restarting...")
            time.sleep(5)

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

    command_parts = command_parts[:]
    command_parts.extend(["--id", device_id, "--location", location])

    if device_type == "light_post":
        command_parts.extend(["--port", str(next_grpc_port)])
        next_grpc_port += 1
    
    try:
        subprocess.Popen(command_parts, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return {"message": f"Comando para criar o dispositivo '{device_id}' enviado com sucesso."}
    except Exception as e:
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
            return {"message": response.message, "status": "success"}
    except grpc.aio.AioRpcError as e:
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