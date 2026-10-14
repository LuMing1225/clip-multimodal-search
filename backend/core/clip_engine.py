# -*- coding: utf-8 -*-
"""
CLIP 多模态编码引擎
加载 OFA-Sys/chinese-clip-vit-base-patch16（transformers），
提供文本编码与图片编码（512维向量），GPU 加速，支持批量编码。
"""
import os
import sys

# 强制离线模式：模型已缓存到本地，避免启动时去 huggingface.co 检查更新导致超时
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import logging
from typing import List, Optional, Union

import numpy as np

import config

logger = logging.getLogger(__name__)


class CLIPEngine:
    """中文 CLIP 编码引擎单例。"""

    def __init__(self) -> None:
        self.model = None
        self.processor = None
        self.device = config.CLIP_DEVICE
        self.embedding_dim = config.CLIP_EMBEDDING_DIM
        self.batch_size = config.CLIP_BATCH_SIZE
        self.model_name = config.CLIP_MODEL_NAME
        self.loaded = False

    def load_model(self) -> bool:
        """加载 CLIP 模型到指定设备（GPU/CPU）。成功返回 True。"""
        try:
            import torch
            from transformers import ChineseCLIPModel, ChineseCLIPProcessor

            # 国内网络环境下使用 HuggingFace 镜像兜底（已设置则不覆盖）
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

            # 自动判断 CUDA 是否真正可用
            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA 不可用，回退到 CPU")
                self.device = "cpu"

            logger.info("正在加载 CLIP 模型: %s ...", self.model_name)
            self.processor = ChineseCLIPProcessor.from_pretrained(self.model_name)
            self.model = ChineseCLIPModel.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()
            self.loaded = True

            # 打印显存占用
            self.log_gpu_usage()
            return True
        except Exception as e:
            logger.exception("CLIP 模型加载失败: %s", e)
            self.loaded = False
            return False

    def log_gpu_usage(self) -> None:
        """打印模型加载状态与显存占用。"""
        try:
            import torch
            if self.device == "cuda" and torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated() / 1024 / 1024
                reserved = torch.cuda.memory_reserved() / 1024 / 1024
                logger.info(
                    "[CLIP] 模型已加载到 GPU | 显存 allocated=%.1fMB reserved=%.1fMB",
                    allocated, reserved,
                )
                print(f"[CLIP] 模型加载完成 -> GPU | allocated={allocated:.1f}MB reserved={reserved:.1f}MB")
            else:
                logger.info("[CLIP] 模型已加载到 CPU")
                print("[CLIP] 模型加载完成 -> CPU")
        except Exception as e:
            logger.warning("显存统计失败: %s", e)

    @staticmethod
    def _pool_text(last_hidden_state, attention_mask):
        """对文本 last_hidden_state 做 mean pooling（带 attention mask）。"""
        import torch
        mask = attention_mask.unsqueeze(-1).float()  # (B, L, 1)
        summed = (last_hidden_state * mask).sum(dim=1)  # (B, D)
        counts = mask.sum(dim=1).clamp(min=1e-9)  # (B, 1)
        return summed / counts

    # ---------- 文本编码 ----------
    def encode_text(self, texts: Union[str, List[str]]) -> np.ndarray:
        """编码文本，返回 L2 归一化后的向量 (N, 512)。"""
        import torch
        if not self.loaded:
            raise RuntimeError("CLIP 模型未加载")
        if isinstance(texts, str):
            texts = [texts]
        all_embeds: List[np.ndarray] = []
        with torch.no_grad():
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i:i + self.batch_size]
                inputs = self.processor(
                    text=batch, return_tensors="pt", padding=True, truncation=True
                ).to(self.device)
                # 底层调用 text_model，避免 get_text_features 在新版 transformers 的 bug
                text_outputs = self.model.text_model(
                    input_ids=inputs["input_ids"],
                    attention_mask=inputs["attention_mask"],
                )
                # text_model 输出无 pooler_output，用 mean pooling
                pooled = self._pool_text(
                    text_outputs.last_hidden_state, inputs["attention_mask"]
                )
                # 投影到 512 维共用空间
                feats = self.model.text_projection(pooled)
                feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
                all_embeds.append(feats.cpu().numpy())
        return np.vstack(all_embeds).astype(np.float32)

    # ---------- 图片编码 ----------
    def encode_images(self, images: List) -> np.ndarray:
        """编码图片（PIL Image 列表），返回归一化向量 (N, 512)。"""
        import torch
        if not self.loaded:
            raise RuntimeError("CLIP 模型未加载")
        all_embeds: List[np.ndarray] = []
        with torch.no_grad():
            for i in range(0, len(images), self.batch_size):
                batch = images[i:i + self.batch_size]
                inputs = self.processor(
                    images=batch, return_tensors="pt"
                ).to(self.device)
                # 底层调用 vision_model
                vision_outputs = self.model.vision_model(
                    pixel_values=inputs["pixel_values"]
                )
                # 优先取 pooler_output（CLS token），没有则取 last_hidden_state[:, 0]
                if vision_outputs.pooler_output is not None:
                    pooled = vision_outputs.pooler_output
                else:
                    pooled = vision_outputs.last_hidden_state[:, 0, :]
                # 投影到 512 维共用空间
                feats = self.model.visual_projection(pooled)
                feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
                all_embeds.append(feats.cpu().numpy())
        return np.vstack(all_embeds).astype(np.float32)

    def encode_image_file(self, path: str) -> np.ndarray:
        """编码单张图片文件路径，返回 (512,) 向量。"""
        from PIL import Image
        img = Image.open(path).convert("RGB")
        return self.encode_images([img])[0]

    def gpu_memory_used_mb(self) -> float:
        """返回当前 GPU 显存占用（MB），CPU 模式返回 0。"""
        try:
            import torch
            if self.device == "cuda" and torch.cuda.is_available():
                return round(torch.cuda.memory_allocated() / 1024 / 1024, 1)
        except Exception:
            pass
        return 0.0
