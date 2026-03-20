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
    "MQTT_BROKER": "你的MQTT服务器地址",
    "MQTT_PORT": 1234,
    "MQTT_USER": "你的MQTT用户名",
    "MQTT_PASS": "你的MQTT密码",
    "MQTT_TOPIC": "你的MQTT主题",
    "VOICEBOX_URL": "你的Voicebox TTS服务地址",
    "TARGET_DEMP_ID": "你的目标设备ID"
}
```

**参数说明**：
- `MQTT_BROKER` / `MQTT_PORT`: MQTT 服务器的地址和端口。
- `MQTT_USER` / `MQTT_PASS`: 连接 MQTT 的账号密码。
- `MQTT_TOPIC`: 需要监听的 MQTT Topic（默认为 `soul2user`）。
- `VOICEBOX_URL`: 后端 Voicebox TTS 服务的接口地址。
- `TARGET_DEMP_ID`: 需要过滤和处理的特定设备/业务 ID。

### 3. 运行程序
配置完成后，运行以下命令启动客户端：

```bash
python src/mqtt_tts_client.py
```

## 技术文档
关于内部打断机制、多线程缓冲、架构详情等，请参阅 [docs/mqtt_tts_client_doc.md](docs/mqtt_tts_client_doc.md)。