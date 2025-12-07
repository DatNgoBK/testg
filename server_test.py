# Imports
import aiohttp
from aiohttp import web
import numpy as np
from openwakeword import Model
import resampy
import argparse
import json
import logging

# Cấu hình log đơn giản để dễ debug
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define websocket handler
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    logger.info("Client đã kết nối")

    # Gửi danh sách các model đã load ngay khi kết nối thành công (Handshake)
    await ws.send_str(json.dumps({"loaded_models": list(owwModel.models.keys())}))

    # Giá trị mặc định nếu client không gửi thông tin sample rate
    sample_rate = 16000 

    # Bắt đầu lắng nghe tin nhắn từ client
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            # Giao thức quy định: Nếu gửi Text -> Đó là Sample Rate
            try:
                received_rate = int(msg.data)
                sample_rate = received_rate
                logger.info(f"Đã cập nhật sample rate: {sample_rate}")
            except ValueError:
                logger.warning("Nhận tin nhắn Text không phải số nguyên")
                
        elif msg.type == aiohttp.WSMsgType.BINARY:
            # Giao thức quy định: Nếu gửi Binary -> Đó là Audio Chunk
            audio_bytes = msg.data

            # Xử lý padding nếu số lượng bytes lẻ
            if len(msg.data) % 2 == 1:
                audio_bytes += (b'\x00')

            # Convert audio sang định dạng int16
            data = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # Resample nếu sample rate của client khác 16000Hz
            if sample_rate != 16000:
                data = resampy.resample(data, sample_rate, 16000)

            # Dự đoán (Predict)
            predictions = owwModel.predict(data)

            # Lọc các kết quả có độ tin cậy >= 0.5
            activations = []
            for key in predictions:
                if predictions[key] >= 0.5:
                    activations.append(key)

            # Chỉ gửi phản hồi về Client nếu phát hiện từ khóa
            if activations:
                logger.info(f"Phát hiện từ khóa: {activations}")
                await ws.send_str(json.dumps({"activations": activations}))
        
        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f"WebSocket error: {ws.exception()}")

    logger.info("Client đã ngắt kết nối")
    return ws

app = web.Application()

# CHỈ GIỮ LẠI ROUTE WEBSOCKET
app.add_routes([web.get('/ws', websocket_handler)])

if __name__ == '__main__':
    # Parse CLI arguments
    parser=argparse.ArgumentParser()
    parser.add_argument(
        "--chunk_size",
        help="How much audio (in number of samples) to predict on at once",
        type=int,
        default=1280,
        required=False
    )
    parser.add_argument(
        "--model_path",
        help="The path of a specific model to load",
        type=str,
        default="",
        required=False
    )
    parser.add_argument(
        "--inference_framework",
        help="The inference framework to use (either 'onnx' or 'tflite'",
        type=str,
        default='tflite',
        required=False
    )
    args=parser.parse_args()

    # Load openWakeWord models
    if args.model_path != "":
        owwModel = Model(wakeword_models=[args.model_path], inference_framework=args.inference_framework)
    else:
        owwModel = Model(inference_framework=args.inference_framework)

    print("Server đang chạy tại ws://localhost:9000/ws")
    # Start webapp
    web.run_app(app, host='localhost', port=9000)
