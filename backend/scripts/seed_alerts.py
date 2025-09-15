import asyncio
import time
from typing import List, Tuple

import aiosqlite

from ..config import DB_PATH
from ..db import init_db


Rows = List[Tuple[str, str, str, float, int]]


def _ts_offset(minutes: float) -> str:
    t = time.time() - minutes * 60.0
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


async def seed():
    await init_db()
    rows: Rows = [
        ("ERROR",    "CPU 使用率过高",   "当前 95% ≥ 阈值 90%",                       5,  0),
        ("WARN",     "内存占用过高",     "当前 88% 接近阈值 90%",                     15, 0),
        ("ERROR",    "磁盘 IO 过高",     "当前 1250 MB/s ≥ 阈值 1000 MB/s",            28, 0),
        ("ERROR",    "GPU 温度过高",     "当前 92℃ ≥ 阈值 85℃",                        35, 0),
        ("WARN",     "网络延迟过高",     "当前 420 ms ≥ 阈值 300 ms",                  43, 0),
        ("CRITICAL", "系统日志关键字",   "在 /var/log/syslog 命中 FATAL",               58, 0),
        ("WARN",     "磁盘剩余空间不足", "/data 分区剩余 4%",                            65, 1),
        ("ERROR",    "SMART 错误",       "sda 出现 Reallocated_Sector_Ct 上升",          75, 0),
        ("ERROR",    "风扇故障",         "FAN2 转速为 0",                               95, 1),
        ("WARN",     "电源异常",         "PSU1 输入电压不稳定",                          110,1),
        ("ERROR",    "接口 flapping",    "eth0 5 分钟内 flap 12 次",                     125,0),
        ("ERROR",    "服务进程退出",     "prometheus 进程异常退出 (code=1)",            140,0),
        ("WARN",     "温度传感器异常",   "TMP_INLET 读数间歇性丢失",                      160,0),
        ("CRITICAL", "磁盘只读",         "/ 以只读方式挂载，业务不可写",                  185,0),
    ]
    async with aiosqlite.connect(DB_PATH) as db:
        for level, title, message, mins, ack in rows:
            created_at = _ts_offset(mins)
            await db.execute(
                "INSERT INTO alerts(level,title,message,acknowledged,created_at) VALUES(?,?,?,?,?)",
                (level, title, message, int(ack), created_at),
            )
        await db.commit()
    return len(rows)


if __name__ == "__main__":
    n = asyncio.run(seed())
    print(f"Seeded {n} alert rows into {DB_PATH}")

