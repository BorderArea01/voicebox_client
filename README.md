# Voicebox Client

这是一个基于 MQTT 接收大模型流式文本，并调用内部 Voicebox 服务进行流式语音（TTS）播放的客户端。该项目实现了首句极速响应、多线程预加载以及全局打断机制。

## 项目目录结构

```text
voicebox_client/
├── src/
│   ├── mqtt_tts_client.py     # 主程序入口
│   └── stream_client.py       # (其他流式测试脚本)
├── docs/
│   ├── mqtt_tts_client_doc.md # 技术文档
│   └── websocket_vs_http_tts.md # WebSocket与HTTP对比分析
├── requirements.txt           # Python 依赖
├── config.json                # 敏感配置文件（已忽略，需手动创建）
└── .gitignore                 # Git 忽略配置
```

## 快速开始

### 1. 安装依赖
请确保您的环境安装了 Python 3，并执行以下命令安装必要依赖：

```bash
pip install -r requirements.txt
```

### 2. 创建配置文件 (重要)
为了防止账号密码和服务器 IP 泄露，本项目使用独立的 `config.json` 文件进行配置。**该文件已被加入 `.gitignore`，不会被提交到版本库中。**

请在**项目根目录**下创建一个名为 `config.json` 的文件，并填入以下内容（请根据实际情况修改对应参数）：

```json
{
    "MQTT": {
        "BROKER": "192.168.x.x",
        "PORT": 1883,
        "USER": "your_mqtt_username",
        "PASS": "your_mqtt_password",
        "TOPIC": "your_mqtt_topic"
    },
    "VOICEBOX": {
        "URL": "http://192.168.x.x:port",
        "PROFILE_INDEX": 0,
        "TTS_PARAMS": {
            "language": "zh",
            "seed": 0,
            "model_size": "1.7B",
            "engine": "qwen",
            "max_chunk_chars": 800,
            "crossfade_ms": 50,
            "normalize": true,
            "effects_chain": []
        }
    },
    "APP": {
        "TARGET_DEMP_ID": "your_target_device_id",
        "TARGET_MSG_TYPE": "0",
        "MAX_WORKERS": 3,
        "CHUNK_SIZE": 4096,
        "FRAMES_PER_BUFFER": 4096,
        "TIMEOUT": 3
    }
}
```

**配置模块说明**：

1. **`MQTT` (消息队列配置)**
   - `BROKER` / `PORT`: MQTT 服务器的地址和端口。
   - `USER` / `PASS`: 连接 MQTT 的账号密码。
   - `TOPIC`: 需要监听的 MQTT Topic。

2. **`VOICEBOX` (TTS 服务配置)**
   - `URL`: 后端 Voicebox TTS 服务的接口基础地址。
   - `PROFILE_INDEX`: 语音配置的索引值，配置为 `0` 表示使用接口返回的第一个音色配置。
   - `TTS_PARAMS`: 发送给 Voicebox 引擎的请求参数，如语言 (`language`)、模型大小 (`model_size`)、引擎类型 (`engine`) 等，可根据服务端支持情况自由调整。

3. **`APP` (客户端运行参数)**
   - `TARGET_DEMP_ID`: 需要过滤和处理的特定设备/业务 ID。
   - `TARGET_MSG_TYPE`: MQTT 数据包中，需要过滤提取的有效文本消息 `type` 值。
   - `MAX_WORKERS`: 并发请求 TTS 音频流的线程池最大数量，用于预加载后续句子。
   - `CHUNK_SIZE`: HTTP 流式下载时单次拉取的数据块大小（字节）。
   - `FRAMES_PER_BUFFER`: PyAudio 播放时的硬件缓冲区大小，增大此值可减少爆音和卡顿。
   - `TIMEOUT`: HTTP 请求的超时时间（秒）。

### 3. 运行程序
配置完成后，运行以下命令启动客户端：

```bash
python src/mqtt_tts_client.py
```

## 技术文档
关于内部打断机制、多线程缓冲、架构详情等，请参阅 [docs/mqtt_tts_client_doc.md](docs/mqtt_tts_client_doc.md)。