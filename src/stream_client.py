import requests
import pyaudio
import json
import sys

# Voicebox API 基础地址
BASE_URL = "http://192.168.2.236:17493"

def get_first_profile_id():
    """尝试获取默认的 profile_id"""
    try:
        response = requests.get(f"{BASE_URL}/profiles", timeout=3)
        if response.status_code == 200:
            profiles = response.json()
            if profiles and isinstance(profiles, list) and len(profiles) > 0:
                return profiles[0].get("id", "default")
    except Exception as e:
        print(f"Warning: Could not fetch profiles ({e}). Using 'default'.")
    return "default"

def stream_audio():
    url = f"{BASE_URL}/generate/stream"
    
    # 尝试自动获取 profile_id
    profile_id = get_first_profile_id()
    
    # 请求参数
    payload = {
        "profile_id": profile_id,
        "text": "这是一段流式语音合成的测试。你听到声音的时候，我还在继续生成中。",
        "language": "zh",
        "seed": 0,
        "model_size": "1.7B",
        "engine": "qwen",
        "max_chunk_chars": 800,
        "crossfade_ms": 50,
        "normalize": True,
        "effects_chain": []
    }

    print(f"[*] 准备连接到 {url}...")
    print(f"[*] 使用 Payload: {json.dumps(payload, ensure_ascii=False)}")
    
    try:
        # stream=True 允许边下边读
        response = requests.post(url, json=payload, stream=True)
        
        if response.status_code != 200:
            print(f"[!] 错误: 服务器返回状态码 {response.status_code}")
            print(response.text)
            return
            
    except requests.exceptions.RequestException as e:
        print(f"[!] 连接失败: {e}")
        return

    # 初始化 PyAudio
    p = pyaudio.PyAudio()
    stream = None
    
    print("[*] 开始接收音频流...")
    
    buffer = b""
    header_parsed = False
    
    try:
        # 每次读取 4096 字节
        for chunk in response.iter_content(chunk_size=4096):
            if not chunk:
                continue
                
            if not header_parsed:
                buffer += chunk
                # 标准 WAV 头部通常是 44 字节
                if len(buffer) >= 44:
                    # 从 WAV 头部解析音频格式
                    channels = int.from_bytes(buffer[22:24], byteorder='little')
                    samplerate = int.from_bytes(buffer[24:28], byteorder='little')
                    bits_per_sample = int.from_bytes(buffer[34:36], byteorder='little')
                    
                    print(f"[*] 成功解析音频格式: {channels} 通道, {samplerate} Hz, {bits_per_sample} 位")
                    
                    if bits_per_sample == 16:
                        fmt = pyaudio.paInt16
                    elif bits_per_sample == 32:
                        fmt = pyaudio.paFloat32
                    elif bits_per_sample == 8:
                        fmt = pyaudio.paInt8
                    else:
                        fmt = pyaudio.paInt16
                        
                    # 打开播放流
                    stream = p.open(format=fmt,
                                    channels=channels,
                                    rate=samplerate,
                                    output=True)
                    
                    # 播放除去 44 字节头部之后的音频数据
                    stream.write(buffer[44:])
                    header_parsed = True
                    buffer = b"" # 清空缓冲
            else:
                # 头部解析完成后，直接将接收到的数据写入声卡播放
                stream.write(chunk)
                
        print("[*] 播放结束。")
        
    except KeyboardInterrupt:
        print("\n[*] 用户手动中断播放。")
    except Exception as e:
        print(f"\n[!] 发生异常: {e}")
    finally:
        if stream:
            stream.stop_stream()
            stream.close()
        p.terminate()

if __name__ == "__main__":
    stream_audio()
