# -*- coding: utf-8 -*-
"""
语音转文本模块
基于 faster-whisper（model size=base）实现中文语音识别。
若 faster-whisper 安装失败，则降级：返回空文本并在日志中标注。
"""
import logging
import os
from typing import Any, Dict

import config

logger = logging.getLogger(__name__)


class VoiceRecognizer:
    """语音识别器（带降级方案）。"""

    def __init__(self) -> None:
        self.model = None
        self.available = False
        self._load()

    def _load(self) -> None:
        """尝试加载 faster-whisper 模型。"""
        try:
            from faster_whisper import WhisperModel
            size = config.WHISPER_MODEL_SIZE
            # CPU int8 推理，避免显存压力
            self.model = WhisperModel(size, device="cpu", compute_type="int8")
            self.available = True
            logger.info("faster-whisper 模型加载成功: size=%s", size)
            print(f"[Voice] faster-whisper 加载成功 (size={size})")
        except Exception as e:
            logger.warning("faster-whisper 不可用，启用降级方案: %s", e)
            self.available = False
            print(f"[Voice] faster-whisper 加载失败，降级为占位模式: {e}")

    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        """识别音频文件，返回 {text, language, duration_sec}。"""
        if not self.available or self.model is None:
            logger.warning("[降级] faster-whisper 不可用，返回空文本: %s", audio_path)
            return {"text": "", "language": "zh", "duration_sec": 0.0,
                    "degraded": True}
        try:
            segments, info = self.model.transcribe(audio_path, language="zh")
            text = "".join(seg.text for seg in segments).strip()
            return {
                "text": text,
                "language": getattr(info, "language", "zh"),
                "duration_sec": round(getattr(info, "duration", 0.0), 2),
                "degraded": False,
            }
        except Exception as e:
            logger.exception("语音识别失败: %s", e)
            return {"text": "", "language": "zh", "duration_sec": 0.0,
                    "degraded": True, "error": str(e)}
