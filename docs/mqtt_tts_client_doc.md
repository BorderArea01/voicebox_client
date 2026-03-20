# mqtt_tts_client.py 技术文档

## 1. 概述
`mqtt_tts_client.py` 是一个基于 Python 的客户端程序。它的核心功能是通过 MQTT 协议接收外部系统（如大模型流式输出）发送的文本内容，并将这些文本实时转换为语音（Text-To-Speech, TTS）进行流式播放。该系统特别设计了**多线程预加载机制**、**首句极速响应**以及**实时打断（Interrupt）机制**，以确保对话的流畅性和自然度。

---

## 2. 核心系统架构
整个系统由以下几个主要模块协同工作：
1. **MQTT 接收模块**：监听特定 Topic，接收并拼接流式文本。
2. **文本分句与队列模块**：按标点符号或长度将长文本切割为短句，并将其排入处理队列。
3. **TTS 音频获取模块（多线程）**：从远端 Voicebox 服务器并发拉取生成的流式音频数据。
4. **音频播放模块（独立线程）**：按句子顺序，无缝读取并播放音频流。
5. **打断控制模块**：支持收到停止/打断指令后，立即清空缓冲区并停止当前播放。

---

## 3. 核心机制详解

### 3.1 文本分句与低延迟机制
为了降低大模型回复时的“首句等待延迟”，系统在 `on_message` 回调中对接收到的流式文本进行了实时处理：
- **实时拼接与打印**：通过 `text_buffer` 累加接收到的字词，并实时打印在控制台。
- **动态标点截断**：遇到 `。！？\n.!?，,；;：:` 等标点符号时，立即进行截断并形成一个完整的句子（`SentenceItem`）。这种处理使得第一句话一旦生成完毕即可立即送去 TTS，极大降低了首句延迟。
- **长度截断后备**：如果一段文本长达 50 个字符仍未遇到标点符号，系统会强制截断，避免 TTS 单次请求负担过重或导致不合理的停顿。
- **结束标志处理**：当收到 `is_end=True` 的消息时，会将缓冲区内剩余的字词打包发送。

### 3.2 队列与并发流式合成
系统使用了 `SentenceItem` 类和多线程来保证播放的连续性：
- `SentenceItem`: 包装了文本内容、所属的 Session ID，以及一个无限容量的 `chunk_queue`（用于存放该句子的音频片段）。
- **`sentence_queue` (FIFO)**: 用于保持句子的全局播放顺序。
- **`tts_executor` (ThreadPoolExecutor)**: 拥有 3 个 Worker 的线程池。当句子被放入 `sentence_queue` 时，系统会同时将其提交给线程池。这样，当前句子在播放时，后续的句子已经在并发进行 TTS 合成了（预加载）。

### 3.3 音频播放线程 (`audio_play_worker`)
- 独立于主线程和网络线程运行，专门负责从 `sentence_queue` 中按顺序取出句子。
- 取出句子后，循环读取其内部的 `chunk_queue`，解析出音频格式（Format、Channels、Rate）并初始化 PyAudio 流。
- 随后将纯音频数据（Audio Data）写入声卡缓冲 `current_stream.write`。播放速度由声卡硬件自然控制（阻塞写入），实现了无缝衔接。

### 3.4 全局打断机制 (Interrupt)
这是该客户端在对话交互中的一个重要特性。当用户打断机器人讲话时：
1. MQTT 接收到 `type="interrupt"` 或 `action="stop"` 的指令。
2. 触发 `interrupt_playback()` 函数：
   - 全局 `global_session_id` 自增 1。这是打断的核心逻辑，通过 Session ID 的变化来使当前所有排队的任务失效。
   - 清空当前的文本缓冲区 `text_buffer`。
   - 清空 `sentence_queue` 中尚未播放的句子。
   - 立即停止当前正在播放的音频流 `current_stream.stop_stream()`。
3. 后台正在请求 TTS 或排队播放的线程，如果发现自身持有的 `session_id` 不等于全局最新的 `global_session_id`，会自动退出并丢弃数据。

---

## 4. 数据与接口规范

### 4.1 MQTT 通信协议
- **Topic**: `soul2user`
- **正常文本数据包格式**:
  要求 `type == "0"` 且 `demp_id` 与配置中的 `TARGET_DEMP_ID` 匹配。
  ```json
  {
      "type": "0",
      "demp_id": "1976222524412792833",
      "content": "你好",
      "is_end": false
  }
  ```
- **打断控制指令**:
  ```json
  {
      "type": "interrupt" 
  }
  // 或
  {
      "action": "stop"
  }
  ```

### 4.2 Voicebox TTS 接口
- **URL**: `{VOICEBOX_URL}/generate/stream`
- **请求方式**: `POST` (Stream)
- **请求参数**: 包含 profile_id, text, model_size (1.7B), engine (qwen) 等。
- **响应处理**: HTTP 流式返回，程序会手动解析前 44 字节的 WAV 头部来提取采样率和通道数，随后的数据作为纯音频流放入队列。

---

## 5. 配置参数说明
脚本顶部的全局变量用于配置环境：
- `MQTT_BROKER` / `MQTT_PORT`: MQTT 服务器地址与端口（默认 192.168.11.24:1883）。
- `MQTT_USER` / `MQTT_PASS`: MQTT 认证信息。
- `MQTT_TOPIC`: 监听的主题（默认 soul2user）。
- `VOICEBOX_URL`: 内部 TTS 服务的地址（默认 http://192.168.2.236:17493）。
- `TARGET_DEMP_ID`: 过滤特定设备的标识符。

---

## 6. 异常处理与资源管理
- **文本清洗**: `clean_text` 函数过滤了 Markdown 符号和非法不可见字符，防止 TTS 引擎因特殊字符返回 500 错误。
- **连接复用**: 使用 `requests.Session()` 维持与 TTS 服务器的 HTTP 长连接，避免了每次请求的 TCP/HTTP 握手开销。
- **优雅退出**: 在 `main()` 函数中捕获了 `KeyboardInterrupt`，退出时确保关闭 MQTT 连接、关闭线程池以及终止 PyAudio 实例。

---

## 7. 依赖库
运行此脚本需要安装以下 Python 包：
```bash
pip install paho-mqtt requests pyaudio
```