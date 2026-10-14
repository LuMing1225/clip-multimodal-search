# -*- coding: utf-8 -*-
"""
Chat Memory 模块
基于 fakeredis（内存版Redis兼容层）实现会话记忆存储，带 TTL 过期机制，
并通过 Redis Stream（agent_signals）进行 Agent 间信号发布/订阅。
"""
import json
import time
import logging
from typing import Any, Dict, List, Optional

import fakeredis
import redis

import config

logger = logging.getLogger(__name__)


class ChatMemory:
    """会话记忆存储器（fakeredis 实现）。

    - 会话消息以 list 结构按 user_id 存储，自动带 TTL 过期。
    - Agent 信号通过 Redis Stream（config.REDIS_STREAM_NAME）发布与消费。
    """

    def __init__(self) -> None:
        # 使用 fakeredis 内存实例，替代真实 Redis 服务
        self.client: redis.Redis = fakeredis.FakeStrictRedis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            decode_responses=True,
        )
        self.ttl = config.CHAT_MEMORY_TTL
        self.stream_name = config.REDIS_STREAM_NAME
        self.group_name = config.REDIS_STREAM_CONSUMER_GROUP
        # 初始化 Stream 消费者组（已存在则忽略）
        self._ensure_consumer_group()
        logger.info("ChatMemory 初始化完成（fakeredis），TTL=%ss", self.ttl)

    # ---------- 消费者组 ----------
    def _ensure_consumer_group(self) -> None:
        """确保 Redis Stream 消费者组存在。"""
        try:
            self.client.xgroup_create(
                name=self.stream_name,
                groupname=self.group_name,
                id="0",
                mkstream=True,
            )
        except redis.exceptions.ResponseError as e:
            # 组已存在时 redis 返回 BUSYGROUP 错误，属于正常情况
            if "BUSYGROUP" not in str(e):
                logger.warning("创建消费者组异常: %s", e)

    # ---------- 会话消息读写 ----------
    def _chat_key(self, user_id: str) -> str:
        """生成会话记忆的 Redis key。"""
        return f"chat:memory:{user_id}"

    def save_message(
        self,
        user_id: str,
        role: str,
        content: str,
        session_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """向用户会话记忆追加一条消息，返回消息ID。"""
        msg = {
            "role": role,
            "content": content,
            "session_id": session_id or "",
            "timestamp": time.time(),
            "extra": extra or {},
        }
        key = self._chat_key(user_id)
        self.client.rpush(key, json.dumps(msg, ensure_ascii=False))
        # 每次写入刷新 TTL
        self.client.expire(key, self.ttl)
        return key

    def get_history(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """读取用户最近的会话历史。"""
        key = self._chat_key(user_id)
        items = self.client.lrange(key, -limit, -1)
        history: List[Dict[str, Any]] = []
        for raw in items:
            try:
                history.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return history

    def clear_user(self, user_id: str) -> int:
        """删除指定用户的全部会话记忆，返回删除的 key 数量。"""
        key = self._chat_key(user_id)
        return self.client.delete(key)

    # ---------- Redis Stream 信号发布/订阅 ----------
    def publish_signal(self, event_type: str, payload: Dict[str, Any]) -> str:
        """向 agent_signals Stream 发布一条 Agent 信号，返回 stream id。"""
        message = {
            "event": event_type,
            "payload": json.dumps(payload, ensure_ascii=False),
            "timestamp": time.time(),
        }
        msg_id = self.client.xadd(self.stream_name, message)
        logger.info("已发布信号 event=%s id=%s", event_type, msg_id)
        return msg_id

    def consume_signals(
        self,
        consumer_name: str = "retriever_worker",
        count: int = 10,
        block_ms: int = 1000,
    ) -> List[Dict[str, Any]]:
        """从 Stream 拉取未处理的信号（供检索 Agent 订阅）。"""
        results = []
        try:
            resp = self.client.xreadgroup(
                groupname=self.group_name,
                consumername=consumer_name,
                streams={self.stream_name: ">"},
                count=count,
                block=block_ms,
            )
        except redis.exceptions.ResponseError as e:
            logger.warning("消费信号异常: %s", e)
            return results
        # resp 结构: [[stream_name, [(msg_id, {fields}), ...]]]
        for _stream, entries in resp:
            for msg_id, fields in entries:
                try:
                    results.append(
                        {
                            "msg_id": msg_id,
                            "event": fields.get("event", ""),
                            "payload": json.loads(fields.get("payload", "{}")),
                            "timestamp": float(fields.get("timestamp", 0)),
                        }
                    )
                    # 手动 ACK，避免堆积
                    self.client.xack(self.stream_name, self.group_name, msg_id)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("解析信号消息失败: %s", e)
        return results

    def get_signal_count(self) -> int:
        """返回 Stream 当前长度。"""
        try:
            return self.client.xlen(self.stream_name)
        except redis.exceptions.RedisError:
            return 0
