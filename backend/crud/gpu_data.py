"""
GPU数据管理工具 - SQLite3增删改查操作
"""
import sqlite3
import aiosqlite
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from backend.config import DB_PATH


class GPUDataManager:
    """GPU数据管理器 - 提供完整的SQLite3增删改查操作"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
    
    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)
    
    async def get_async_connection(self):
        """获取异步数据库连接"""
        return aiosqlite.connect(self.db_path)
    
    # ==================== 查询操作 (SELECT) ====================
    
    def get_gpu_data_by_time_range(self, start_time: int, end_time: int) -> List[Dict[str, Any]]:
        """根据时间范围查询GPU数据"""
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    g.id, g.ts, g.gpu_util_avg, g.gpu_temp_avg,
                    c.cpu_percent, m.mem_percent, d.disk_mb_s
                FROM gpu_data g
                LEFT JOIN cpu_data c ON g.ts = c.ts
                LEFT JOIN mem_data m ON g.ts = m.ts  
                LEFT JOIN diskio_data d ON g.ts = d.ts
                WHERE g.ts BETWEEN ? AND ? 
                ORDER BY g.ts DESC
            """, (start_time, end_time))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_latest_gpu_data(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最新的GPU数据"""
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    g.id, g.ts, g.gpu_util_avg, g.gpu_temp_avg,
                    c.cpu_percent, m.mem_percent, d.disk_mb_s
                FROM gpu_data g
                LEFT JOIN cpu_data c ON g.ts = c.ts
                LEFT JOIN mem_data m ON g.ts = m.ts
                LEFT JOIN diskio_data d ON g.ts = d.ts
                WHERE g.gpu_util_avg IS NOT NULL OR g.gpu_temp_avg IS NOT NULL
                ORDER BY g.ts DESC 
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_gpu_statistics(self, start_time: int, end_time: int) -> Dict[str, Any]:
        """获取GPU统计信息"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as data_points,
                    AVG(gpu_util_avg) as avg_utilization,
                    MAX(gpu_util_avg) as max_utilization,
                    MIN(gpu_util_avg) as min_utilization,
                    AVG(gpu_temp_avg) as avg_temperature,
                    MAX(gpu_temp_avg) as max_temperature,
                    MIN(gpu_temp_avg) as min_temperature
                FROM gpu_data 
                WHERE ts BETWEEN ? AND ? 
                AND (gpu_util_avg IS NOT NULL OR gpu_temp_avg IS NOT NULL)
            """, (start_time, end_time))
            
            result = cursor.fetchone()
            if result:
                return {
                    'data_points': result[0],
                    'avg_utilization': result[1] or 0,
                    'max_utilization': result[2] or 0,
                    'min_utilization': result[3] or 0,
                    'avg_temperature': result[4] or 0,
                    'max_temperature': result[5] or 0,
                    'min_temperature': result[6] or 0
                }
            return {}
        finally:
            conn.close()
    
    def get_gpu_data_by_id(self, data_id: int) -> Optional[Dict[str, Any]]:
        """根据ID查询单条GPU数据"""
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    g.id, g.ts, g.gpu_util_avg, g.gpu_temp_avg,
                    c.cpu_percent, m.mem_percent, d.disk_mb_s
                FROM gpu_data g
                LEFT JOIN cpu_data c ON g.ts = c.ts
                LEFT JOIN mem_data m ON g.ts = m.ts
                LEFT JOIN diskio_data d ON g.ts = d.ts
                WHERE g.id = ?
            """, (data_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
        finally:
            conn.close()
    
    def search_gpu_data(self, 
                       min_utilization: float = None,
                       max_utilization: float = None,
                       min_temperature: float = None,
                       max_temperature: float = None,
                       start_time: int = None,
                       end_time: int = None,
                       limit: int = 100) -> List[Dict[str, Any]]:
        """搜索GPU数据（支持多条件查询）"""
        conn = self.get_connection()
        try:
            conn.row_factory = sqlite3.Row
            
            # 构建查询条件
            conditions = []
            params = []
            
            if min_utilization is not None:
                conditions.append("g.gpu_util_avg >= ?")
                params.append(min_utilization)
            
            if max_utilization is not None:
                conditions.append("g.gpu_util_avg <= ?")
                params.append(max_utilization)
            
            if min_temperature is not None:
                conditions.append("g.gpu_temp_avg >= ?")
                params.append(min_temperature)
            
            if max_temperature is not None:
                conditions.append("g.gpu_temp_avg <= ?")
                params.append(max_temperature)
            
            if start_time is not None:
                conditions.append("g.ts >= ?")
                params.append(start_time)
            
            if end_time is not None:
                conditions.append("g.ts <= ?")
                params.append(end_time)
            
            # 确保有GPU数据
            conditions.append("(g.gpu_util_avg IS NOT NULL OR g.gpu_temp_avg IS NOT NULL)")
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.append(limit)
            
            query = f"""
                SELECT 
                    g.id, g.ts, g.gpu_util_avg, g.gpu_temp_avg,
                    c.cpu_percent, m.mem_percent, d.disk_mb_s
                FROM gpu_data g
                LEFT JOIN cpu_data c ON g.ts = c.ts
                LEFT JOIN mem_data m ON g.ts = m.ts
                LEFT JOIN diskio_data d ON g.ts = d.ts
                WHERE {where_clause}
                ORDER BY g.ts DESC 
                LIMIT ?
            """
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    # ==================== 插入操作 (INSERT) ====================
    
    def insert_gpu_data(self, 
                       gpu_util_avg: float,
                       gpu_temp_avg: float,
                       cpu_percent: float = None,
                       mem_percent: float = None,
                       disk_mb_s: float = None,
                       timestamp: int = None) -> int:
        """插入GPU数据"""
        conn = self.get_connection()
        try:
            if timestamp is None:
                timestamp = int(time.time())
            
            cursor = conn.execute("""
                INSERT INTO metric_samples 
                (ts, gpu_util_avg, gpu_temp_avg, cpu_percent, mem_percent, disk_mb_s)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (timestamp, gpu_util_avg, gpu_temp_avg, cpu_percent, mem_percent, disk_mb_s))
            
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    
    def batch_insert_gpu_data(self, data_list: List[Dict[str, Any]]) -> int:
        """批量插入GPU数据"""
        conn = self.get_connection()
        try:
            cursor = conn.executemany("""
                INSERT INTO metric_samples 
                (ts, gpu_util_avg, gpu_temp_avg, cpu_percent, mem_percent, disk_mb_s)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                (
                    item.get('ts', int(time.time())),
                    item.get('gpu_util_avg', 0),
                    item.get('gpu_temp_avg', 0),
                    item.get('cpu_percent'),
                    item.get('mem_percent'),
                    item.get('disk_mb_s')
                )
                for item in data_list
            ])
            
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    
    # ==================== 更新操作 (UPDATE) ====================
    
    def update_gpu_data(self, 
                       data_id: int,
                       gpu_util_avg: float = None,
                       gpu_temp_avg: float = None,
                       cpu_percent: float = None,
                       mem_percent: float = None,
                       disk_mb_s: float = None) -> bool:
        """更新GPU数据"""
        conn = self.get_connection()
        try:
            # 构建更新字段
            updates = []
            params = []
            
            if gpu_util_avg is not None:
                updates.append("gpu_util_avg = ?")
                params.append(gpu_util_avg)
            
            if gpu_temp_avg is not None:
                updates.append("gpu_temp_avg = ?")
                params.append(gpu_temp_avg)
            
            if cpu_percent is not None:
                updates.append("cpu_percent = ?")
                params.append(cpu_percent)
            
            if mem_percent is not None:
                updates.append("mem_percent = ?")
                params.append(mem_percent)
            
            if disk_mb_s is not None:
                updates.append("disk_mb_s = ?")
                params.append(disk_mb_s)
            
            if not updates:
                return False
            
            params.append(data_id)
            
            cursor = conn.execute(f"""
                UPDATE metric_samples 
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def update_gpu_data_by_time_range(self, 
                                     start_time: int,
                                     end_time: int,
                                     gpu_util_avg: float = None,
                                     gpu_temp_avg: float = None) -> int:
        """根据时间范围更新GPU数据"""
        conn = self.get_connection()
        try:
            updates = []
            params = []
            
            if gpu_util_avg is not None:
                updates.append("gpu_util_avg = ?")
                params.append(gpu_util_avg)
            
            if gpu_temp_avg is not None:
                updates.append("gpu_temp_avg = ?")
                params.append(gpu_temp_avg)
            
            if not updates:
                return 0
            
            params.extend([start_time, end_time])
            
            cursor = conn.execute(f"""
                UPDATE metric_samples 
                SET {', '.join(updates)}
                WHERE ts BETWEEN ? AND ?
            """, params)
            
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    
    # ==================== 删除操作 (DELETE) ====================
    
    def delete_gpu_data_by_id(self, data_id: int) -> bool:
        """根据ID删除GPU数据"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("DELETE FROM metric_samples WHERE id = ?", (data_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def delete_gpu_data_by_time_range(self, start_time: int, end_time: int) -> int:
        """根据时间范围删除GPU数据"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("""
                DELETE FROM metric_samples 
                WHERE ts BETWEEN ? AND ?
            """, (start_time, end_time))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    
    def delete_old_gpu_data(self, days: int = 30) -> int:
        """删除旧的GPU数据"""
        conn = self.get_connection()
        try:
            cutoff_time = int(time.time()) - (days * 24 * 3600)
            cursor = conn.execute("""
                DELETE FROM metric_samples 
                WHERE ts < ?
            """, (cutoff_time,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    
    # ==================== 统计和分析操作 ====================
    
    def get_gpu_data_summary(self) -> Dict[str, Any]:
        """获取GPU数据摘要"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_records,
                    MIN(ts) as earliest_time,
                    MAX(ts) as latest_time,
                    COUNT(CASE WHEN gpu_util_avg IS NOT NULL THEN 1 END) as gpu_util_records,
                    COUNT(CASE WHEN gpu_temp_avg IS NOT NULL THEN 1 END) as gpu_temp_records
                FROM metric_samples
            """)
            
            result = cursor.fetchone()
            if result:
                return {
                    'total_records': result[0],
                    'earliest_time': result[1],
                    'latest_time': result[2],
                    'gpu_util_records': result[3],
                    'gpu_temp_records': result[4],
                    'earliest_datetime': datetime.fromtimestamp(result[1]).isoformat() if result[1] else None,
                    'latest_datetime': datetime.fromtimestamp(result[2]).isoformat() if result[2] else None
                }
            return {}
        finally:
            conn.close()
    
    def export_gpu_data_to_csv(self, start_time: int, end_time: int, filename: str = None) -> str:
        """导出GPU数据到CSV文件"""
        import csv
        
        if filename is None:
            filename = f"gpu_data_{start_time}_{end_time}.csv"
        
        data = self.get_gpu_data_by_time_range(start_time, end_time)
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            if data:
                fieldnames = data[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
        
        return filename
    
    def export_gpu_data_to_json(self, start_time: int, end_time: int, filename: str = None) -> str:
        """导出GPU数据到JSON文件"""
        if filename is None:
            filename = f"gpu_data_{start_time}_{end_time}.json"
        
        data = self.get_gpu_data_by_time_range(start_time, end_time)
        
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            json.dump(data, jsonfile, indent=2, ensure_ascii=False)
        
        return filename


# ==================== 使用示例和测试 ====================

def demo_gpu_data_operations():
    """演示GPU数据操作"""
    print("🚀 GPU数据管理工具演示")
    print("=" * 50)
    
    manager = GPUDataManager()
    
    # 1. 查看数据摘要
    print("\n📊 数据摘要:")
    summary = manager.get_gpu_data_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    # 2. 查询最新数据
    print("\n📈 最新10条GPU数据:")
    latest_data = manager.get_latest_gpu_data(10)
    for item in latest_data[:5]:  # 只显示前5条
        print(f"  ID: {item['id']}, 时间: {datetime.fromtimestamp(item['ts']).strftime('%Y-%m-%d %H:%M:%S')}, "
              f"利用率: {item['gpu_util_avg']:.1f}%, 温度: {item['gpu_temp_avg']:.1f}°C")
    
    # 3. 查询统计信息
    print("\n📊 最近1小时统计:")
    now = int(time.time())
    one_hour_ago = now - 3600
    stats = manager.get_gpu_statistics(one_hour_ago, now)
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")
    
    # 4. 搜索高利用率数据
    print("\n🔍 搜索利用率>50%的数据:")
    high_util_data = manager.search_gpu_data(min_utilization=50, limit=5)
    for item in high_util_data:
        print(f"  ID: {item['id']}, 利用率: {item['gpu_util_avg']:.1f}%, 温度: {item['gpu_temp_avg']:.1f}°C")
    
    # 5. 插入测试数据
    print("\n➕ 插入测试数据:")
    test_id = manager.insert_gpu_data(
        gpu_util_avg=75.5,
        gpu_temp_avg=68.2,
        cpu_percent=45.3,
        mem_percent=32.1
    )
    print(f"  插入成功，ID: {test_id}")
    
    # 6. 更新测试数据
    print("\n✏️ 更新测试数据:")
    success = manager.update_gpu_data(test_id, gpu_util_avg=80.0, gpu_temp_avg=70.0)
    print(f"  更新{'成功' if success else '失败'}")
    
    # 7. 删除测试数据
    print("\n🗑️ 删除测试数据:")
    success = manager.delete_gpu_data_by_id(test_id)
    print(f"  删除{'成功' if success else '失败'}")


if __name__ == "__main__":
    demo_gpu_data_operations()
