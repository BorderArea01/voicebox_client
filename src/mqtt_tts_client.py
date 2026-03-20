import os
import paho.mqtt.client as mqtt
import json
import threading
import queue
import requests
import pyaudio
import concurrent.futures
import re

# --- 配置区 ---
# 自动寻找项目根目录下的 config.json
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
try:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        _config = json.load(f)
except FileNotFoundError:
    print(f"[!] 错误: 未找到配置文件 {CONFIG_PATH}")
    print("[!] 请参考 README.md 在项目根目录创建 config.json 文件。")
    exit(1)
except json.JSONDecodeError as e:
    print(f"[!] 错误: 配置文件格式不正确 {CONFIG_PATH}\n详细信息: {e}")
    exit(1)

MQTT_BROKER = _config.get("MQTT_BROKER", "192.168.11.24")
MQTT_PORT = _config.get("MQTT_PORT", 1883)
MQTT_USER = _config.get("MQTT_USER", "")
MQTT_PASS = _config.get("MQTT_PASS", "")
MQTT_TOPIC = _config.get("MQTT_TOPIC", "soul2user")

VOICEBOX_URL = _config.get("VOICEBOX_URL", "http://192.168.2.236:17493")
TARGET_DEMP_ID = _config.get("TARGET_DEMP_ID", "1976222524412792833")

# 全局队列和状态
class SentenceItem:
    def __init__(self, text, session_id):
        self.text = text
        self.session_id = session_id
        self.chunk_queue = queue.Queue() # 用于存放该句子的音频块，容量无限

sentence_queue = queue.Queue() # 用于保持句子的播放顺序
tts_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3) # 允许3个并发请求，提前合成后续句子
http_session = requests.Session() # 使用 Session 保持长连接，省去每次请求 TCP/HTTP 握手的耗时
text_buffer = ""
profile_id = "default"
pyaudio_instance = pyaudio.PyAudio()

# --- 新增：打断机制相关状态 ---
global_session_id = 0
session_lock = threading.Lock()
current_stream = None

def clean_text(text):
    """清理无效字符，过滤掉可能导致 TTS 引擎 500 报错的特殊符号和 Markdown"""
    # 移除常见的 Markdown 符号
    text = re.sub(r'[*#_~`>\]\[]', '', text)
    # 移除非法不可见字符，保留中英文、数字和常见标点
    text = re.sub(r'[^\w\s\u4e00-\u9fa5，。！？、；：“”‘’（）《》,.!?\-—]', '', text)
    return text.strip()

def interrupt_playback():
    """触发打断：更新 session_id，清空队列和当前播放流"""
    global global_session_id, text_buffer, current_stream
    print("\n[*] 触发打断机制，停止当前播放并清空缓冲...")
    with session_lock:
        global_session_id += 1
    text_buffer = ""
    
    # 清空句子队列
    while not sentence_queue.empty():
        try:
            sentence_queue.get_nowait()
        except queue.Empty:
            break
            
    # 停止当前流
    if current_stream and current_stream.is_active():
        current_stream.stop_stream()

def get_first_profile_id():
    """尝试获取 Voicebox 的默认 profile_id"""
    try:
        response = http_session.get(f"{VOICEBOX_URL}/profiles", timeout=3)
        if response.status_code == 200:
            profiles = response.json()
            if profiles and isinstance(profiles, list) and len(profiles) > 0:
                return profiles[0].get("id", "default")
    except Exception as e:
        print(f"[*] 获取 Profile 失败: {e}")
    return "default"

def fetch_tts_stream_to_item(item):
    """请求 Voicebox 接口获取流式音频并放入句子的音频队列"""
    if item.session_id != global_session_id:
        item.chunk_queue.put({"type": "done"})
        return
        
    text = clean_text(item.text)
    if not text:
        item.chunk_queue.put({"type": "done"})
        return
        
    print(f"\n[TTS Fetcher] 开始请求合成: {text}")
    url = f"{VOICEBOX_URL}/generate/stream"
    payload = {
        "profile_id": profile_id,
        "text": text,
        "language": "zh",
        "seed": 0,
        "model_size": "1.7B",
        "engine": "qwen",
        "max_chunk_chars": 800,
        "crossfade_ms": 50,
        "normalize": True,
        "effects_chain": []
    }
    
    try:
        response = http_session.post(url, json=payload, stream=True)
        if response.status_code != 200:
            print(f"[!] TTS 请求失败: {response.status_code}")
            item.chunk_queue.put({"type": "error"})
            return
            
        buffer = b""
        header_parsed = False
        
        # 增大 chunk_size 可以更高效地读取数据
        for chunk in response.iter_content(chunk_size=4096):
            if item.session_id != global_session_id: # 如果在下载过程中被打断，立即中止
                break
                
            if not chunk:
                continue
                
            if not header_parsed:
                buffer += chunk
                # 提取 WAV 头部 (至少 44 字节)
                if len(buffer) >= 44:
                    channels = int.from_bytes(buffer[22:24], byteorder='little')
                    samplerate = int.from_bytes(buffer[24:28], byteorder='little')
                    bits_per_sample = int.from_bytes(buffer[34:36], byteorder='little')
                    
                    fmt = pyaudio.paInt16
                    if bits_per_sample == 32: fmt = pyaudio.paFloat32
                    elif bits_per_sample == 8: fmt = pyaudio.paInt8
                    
                    audio_format = {
                        "format": fmt,
                        "channels": channels,
                        "rate": samplerate
                    }
                    
                    # 放入格式信息
                    item.chunk_queue.put({"type": "format", "data": audio_format})
                    
                    # 剩下的数据作为纯音频
                    audio_data = buffer[44:]
                    if audio_data:
                        item.chunk_queue.put({"type": "audio", "data": audio_data})
                    
                    header_parsed = True
                    buffer = b""
            else:
                item.chunk_queue.put({"type": "audio", "data": chunk})
                
        item.chunk_queue.put({"type": "done"})
    except Exception as e:
        print(f"[!] TTS 请求异常: {e}")
        item.chunk_queue.put({"type": "error"})

def audio_play_worker():
    """专门负责按顺序读取句子对象并播放的线程，保证播放连续性"""
    global current_stream
    print("[*] Audio Player 线程准备就绪")
    current_format = None
    
    while True:
        item = sentence_queue.get()
        if item is None:
            break
            
        if item.session_id != global_session_id:
            continue
            
        while True:
            if item.session_id != global_session_id:
                break
                
            chunk_msg = item.chunk_queue.get()
            
            if chunk_msg["type"] in ("done", "error"):
                break
                
            elif chunk_msg["type"] == "format":
                new_format = chunk_msg["data"]
                # 如果格式改变或者流还没打开，则重新打开流
                if current_stream is None or new_format != current_format:
                    if current_stream:
                        current_stream.stop_stream()
                        current_stream.close()
                    current_format = new_format
                    current_stream = pyaudio_instance.open(
                        format=current_format["format"],
                        channels=current_format["channels"],
                        rate=current_format["rate"],
                        output=True,
                        frames_per_buffer=4096 # 增加硬件缓冲区，减少爆音和卡顿
                    )
                    
            elif chunk_msg["type"] == "audio":
                if current_stream and item.session_id == global_session_id:
                    # 阻塞写入，速度由声卡自然控制
                    current_stream.write(chunk_msg["data"])

# --- MQTT 回调函数 ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[*] 成功连接到 MQTT 服务器: {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
        print(f"[*] 已订阅主题: {MQTT_TOPIC}")
    else:
        print(f"[!] MQTT 连接失败，返回码: {rc}")

def on_message(client, userdata, msg):
    global text_buffer, global_session_id
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        
        # 支持通过特定指令触发打断机制
        if payload.get("type") == "interrupt" or payload.get("action") == "stop":
            interrupt_playback()
            return
            
        # 严格过滤：type == "0" 且 demp_id 匹配
        if payload.get("type") == "0" and payload.get("demp_id") == TARGET_DEMP_ID:
            content = payload.get("content", "")
            is_end = payload.get("is_end", False)
            
            if content:
                text_buffer += content
                print(f"{content}", end="", flush=True) # 实时打印接收到的字
                
                # 分句逻辑：因为现在有多线程无缝衔接，可以恢复逗号截断，大幅降低首句延迟
                punctuations = ['。', '！', '？', '\n', '.', '!', '?', '，', ',', '；', ';', '：', ':']
                first_punc_idx = -1
                for i, char in enumerate(text_buffer):
                    if char in punctuations:
                        first_punc_idx = i
                        break # 遇到第一个标点就立刻截断，保证最短的首句延迟
                
                # 如果缓冲里包含标点，或者缓冲区已经积攒了足够长的字数
                if first_punc_idx != -1:
                    sentence = text_buffer[:first_punc_idx+1]
                    text_buffer = text_buffer[first_punc_idx+1:]
                    if len(sentence.strip()) > 1: # 忽略只有标点的情况
                        item = SentenceItem(sentence, global_session_id)
                        sentence_queue.put(item)
                        tts_executor.submit(fetch_tts_stream_to_item, item)
                elif len(text_buffer) > 50: # 放宽长度截断阈值(从15改到50)，避免将长句强行拦腰截断导致不合理停顿
                    item = SentenceItem(text_buffer, global_session_id)
                    sentence_queue.put(item)
                    tts_executor.submit(fetch_tts_stream_to_item, item)
                    text_buffer = ""
            
            # 如果是最后一条消息，把缓冲区剩下的没有标点的字也发给 TTS
            if is_end:
                print("\n\n[MQTT] 收到结束标志 (is_end=true)")
                if text_buffer.strip():
                    item = SentenceItem(text_buffer, global_session_id)
                    sentence_queue.put(item)
                    tts_executor.submit(fetch_tts_stream_to_item, item)
                text_buffer = ""
                
    except json.JSONDecodeError:
        pass
    except Exception as e:
        print(f"\n[!] 消息处理异常: {e}")

def main():
    global profile_id
    profile_id = get_first_profile_id()
    print(f"[*] Voicebox Profile 初始化为: {profile_id}")

    # 1. 启动专门的音频播放线程
    play_thread = threading.Thread(target=audio_play_worker, daemon=True)
    play_thread.start()
    
    # 2. 设置并启动 MQTT 客户端
    client = mqtt.Client()
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    
    print(f"[*] 正在连接 MQTT {MQTT_BROKER}...")
    try:
        # 连接并永久阻塞循环，保持接收
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[*] 正在退出程序...")
    finally:
        client.disconnect()
        tts_executor.shutdown(wait=False)
        pyaudio_instance.terminate()

if __name__ == "__main__":
    main()