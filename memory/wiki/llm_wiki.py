# -*- coding: utf-8 -*-
"""
LLM-Wiki 模块
基于 SQLite 存储结构化 Markdown 文档（用户偏好、商家搭配文档等）。
表结构: wiki_documents(id, user_id, title, content, metadata_json, created_at, updated_at)
"""
import json
import sqlite3
import time
import logging
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)


class LLMWiki:
    """LLM-Wiki 文档存储（SQLite 实现，替代 PostgreSQL）。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or config.SQLITE_DB_PATH
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """建立 SQLite 连接（启用外键 + utf-8）。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """建表（若不存在）。"""
        ddl = """
        CREATE TABLE IF NOT EXISTS wiki_documents (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT NOT NULL,
            title        TEXT NOT NULL,
            content      TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL
        );
        """
        idx_sql = (
            "CREATE INDEX IF NOT EXISTS idx_wiki_user ON wiki_documents(user_id);"
        )
        with self._connect() as conn:
            conn.execute(ddl)
            conn.execute(idx_sql)
            conn.commit()
        logger.info("LLM-Wiki 表结构初始化完成: %s", self.db_path)

    # ---------- 增 ----------
    def add_document(
        self,
        user_id: str,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """新增一篇 Wiki 文档，返回文档 id。"""
        now = time.time()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO wiki_documents(user_id,title,content,metadata_json,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (user_id, title, content, meta_json, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    # ---------- 删 ----------
    def delete_document(self, doc_id: int) -> int:
        """按 id 删除文档。"""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM wiki_documents WHERE id=?", (doc_id,))
            conn.commit()
            return cur.rowcount

    def clear_user(self, user_id: str) -> int:
        """清除某用户的全部 Wiki 文档。"""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM wiki_documents WHERE user_id=?", (user_id,)
            )
            conn.commit()
            return cur.rowcount

    # ---------- 改 ----------
    def update_document(
        self,
        doc_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """更新文档字段。"""
        fields, params = [], []
        if title is not None:
            fields.append("title=?")
            params.append(title)
        if content is not None:
            fields.append("content=?")
            params.append(content)
        if metadata is not None:
            fields.append("metadata_json=?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        if not fields:
            return 0
        fields.append("updated_at=?")
        params.append(time.time())
        params.append(doc_id)
        sql = f"UPDATE wiki_documents SET {', '.join(fields)} WHERE id=?"
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount

    # ---------- 查 ----------
    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """按 id 获取单篇文档。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wiki_documents WHERE id=?", (doc_id,)
            ).fetchone()
            return self._row_to_dict(row)

    def list_by_user(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """列出某用户的全部文档（按更新时间倒序）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM wiki_documents WHERE user_id=?"
                " ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def count_all(self) -> int:
        """统计文档总数。"""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM wiki_documents").fetchone()
            return int(row["c"])

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        """把 SQLite Row 转成字典，metadata_json 反序列化为 dict。"""
        if row is None:
            return None
        d = dict(row)
        try:
            d["metadata"] = json.loads(d.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            d["metadata"] = {}
        return d
