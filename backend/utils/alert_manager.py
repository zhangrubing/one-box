import asyncio
import aiosqlite
from typing import List, Dict, Any
from ..config import DB_PATH


class AlertManager:
    """告警管理器，负责处理系统告警的创建、更新和查询"""
    
    def __init__(self):
        self.db_path = DB_PATH
    
    async def create_alert(self, level: str, title: str, message: str) -> int:
        """创建新告警"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO alerts (level, title, message) VALUES (?, ?, ?)",
                (level, title, message)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def get_recent_alerts(self, hours: int = 24, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的告警"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM alerts 
                   WHERE created_at >= datetime('now', '-{} hours')
                   ORDER BY created_at DESC 
                   LIMIT ?""".format(hours),
                (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def get_critical_alerts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取严重告警"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM alerts 
                   WHERE level IN ('CRITICAL', 'ERROR', 'SEVERE', 'FATAL')
                   AND created_at >= datetime('now', '-{} hours')
                   ORDER BY created_at DESC""".format(hours)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def acknowledge_alert(self, alert_id: int) -> bool:
        """确认告警"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE alerts SET acknowledged = 1 WHERE id = ?",
                (alert_id,)
            )
            await db.commit()
            return cursor.rowcount > 0
    
    async def delete_alert(self, alert_id: int) -> bool:
        """删除告警"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM alerts WHERE id = ?",
                (alert_id,)
            )
            await db.commit()
            return cursor.rowcount > 0
    
    async def cleanup_old_alerts(self, days: int = 30) -> int:
        """清理旧告警"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM alerts WHERE created_at < datetime('now', '-{} days')".format(days)
            )
            await db.commit()
            return cursor.rowcount


# 全局告警管理器实例
alert_manager = AlertManager()
