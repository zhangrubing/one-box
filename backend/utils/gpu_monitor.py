import os, time, json, subprocess, shutil, platform
from typing import Dict, Any, List, Optional
import psutil
import aiosqlite
from ..config import DB_PATH


def get_detailed_gpu_info() -> Dict[str, Any]:
    """获取详细的GPU信息，包括每个GPU的详细信息"""
    gpus = []
    
    try:
        if platform.system() == "Linux" and shutil.which("nvidia-smi"):
            try:
                # 先获取GPU的UUID信息
                uuid_query = [
                    "nvidia-smi",
                    "--query-gpu=index,uuid",
                    "--format=csv,noheader,nounits"
                ]
                uuid_out = subprocess.check_output(uuid_query, timeout=5).decode(errors="ignore")
                
                # 建立index到UUID的映射
                index_to_uuid = {}
                for line in uuid_out.strip().split('\n'):
                    if line.strip():
                        parts = [x.strip() for x in line.split(',', 1)]  # 只分割第一个逗号
                        if len(parts) >= 2:
                            index = int(parts[0]) if parts[0].isdigit() else 0
                            uuid = parts[1].strip()
                            index_to_uuid[index] = uuid
                
                # 获取基本GPU信息
                basic_query = [
                    "nvidia-smi",
                    "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.total,memory.used,memory.free,driver_version,power.draw,power.limit,clocks.current.graphics,clocks.current.memory",
                    "--format=csv,noheader,nounits"
                ]
                basic_out = subprocess.check_output(basic_query, timeout=5).decode(errors="ignore")
                
                # 获取进程信息
                process_query = [
                    "nvidia-smi",
                    "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
                    "--format=csv,noheader,nounits"
                ]
                processes = {}
                try:
                    process_out = subprocess.check_output(process_query, timeout=3).decode(errors="ignore")
                    for line in process_out.strip().split('\n'):
                        if line.strip():
                            # 使用正确的分割方法处理可能包含逗号的进程名
                            parts = [x.strip() for x in line.split(',')]
                            if len(parts) >= 4:
                                gpu_uuid = parts[0].strip()
                                pid = parts[1].strip()
                                # 处理进程名可能包含逗号的情况
                                if len(parts) > 4:
                                    process_name = ','.join(parts[2:-1]).strip()
                                    memory = parts[-1].strip()
                                else:
                                    process_name = parts[2].strip()
                                    memory = parts[3].strip()
                                
                                if gpu_uuid not in processes:
                                    processes[gpu_uuid] = []
                                processes[gpu_uuid].append({
                                    'pid': pid,
                                    'name': process_name,
                                    'memory': memory
                                })
                except Exception as e:
                    print(f"Error getting process info: {e}")
                    processes = {}
                
                # 解析基本GPU信息
                for line in basic_out.strip().split('\n'):
                    if line.strip():
                        parts = [x.strip() for x in line.split(',')]
                        if len(parts) >= 12:
                            gpu_index = int(parts[0]) if parts[0].isdigit() else 0
                            gpu_uuid = index_to_uuid.get(gpu_index, "")
                            
                            gpu_info = {
                                'index': gpu_index,
                                'uuid': gpu_uuid,
                                'name': parts[1],
                                'temperature': float(parts[2]) if parts[2] else 0,
                                'utilization': float(parts[3]) if parts[3] else 0,
                                'memory_total': float(parts[4]) if parts[4] else 0,
                                'memory_used': float(parts[5]) if parts[5] else 0,
                                'memory_free': float(parts[6]) if parts[6] else 0,
                                'driver_version': parts[7],
                                'power_draw': float(parts[8]) if parts[8] else 0,
                                'power_limit': float(parts[9]) if parts[9] else 0,
                                'clock_graphics': float(parts[10]) if parts[10] else 0,
                                'clock_memory': float(parts[11]) if parts[11] else 0,
                                'memory_percent': 0,
                                'processes': []
                            }
                            
                            # 计算内存使用百分比
                            if gpu_info['memory_total'] > 0:
                                gpu_info['memory_percent'] = (gpu_info['memory_used'] / gpu_info['memory_total']) * 100
                            
                            # 使用正确的UUID匹配进程信息
                            if gpu_uuid in processes:
                                gpu_info['processes'] = processes[gpu_uuid]
                            
                            gpus.append(gpu_info)
                            
            except Exception as e:
                print(f"Error getting GPU info: {e}")
                
        elif platform.system() == "Windows" and shutil.which("nvidia-smi"):
            try:
                # Windows下的GPU信息获取
                basic_query = [
                    "nvidia-smi",
                    "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.total,memory.used,memory.free,driver_version,power.draw,power.limit",
                    "--format=csv,noheader,nounits"
                ]
                basic_out = subprocess.check_output(basic_query, timeout=5).decode(errors="ignore")
                
                for line in basic_out.strip().split('\n'):
                    if line.strip():
                        parts = [x.strip() for x in line.split(',')]
                        if len(parts) >= 10:
                            gpu_index = int(parts[0]) if parts[0].isdigit() else 0
                            gpu_info = {
                                'index': gpu_index,
                                'name': parts[1],
                                'temperature': float(parts[2]) if parts[2] else 0,
                                'utilization': float(parts[3]) if parts[3] else 0,
                                'memory_total': float(parts[4]) if parts[4] else 0,
                                'memory_used': float(parts[5]) if parts[5] else 0,
                                'memory_free': float(parts[6]) if parts[6] else 0,
                                'driver_version': parts[7],
                                'power_draw': float(parts[8]) if parts[8] else 0,
                                'power_limit': float(parts[9]) if parts[9] else 0,
                                'memory_percent': 0,
                                'processes': []
                            }
                            
                            if gpu_info['memory_total'] > 0:
                                gpu_info['memory_percent'] = (gpu_info['memory_used'] / gpu_info['memory_total']) * 100
                            
                            gpus.append(gpu_info)
                            
            except Exception as e:
                print(f"Error getting GPU info on Windows: {e}")
                
    except Exception as e:
        print(f"Error in get_detailed_gpu_info: {e}")
    
    return {
        'gpus': gpus,
        'count': len(gpus),
        'timestamp': int(time.time())
    }


async def get_gpu_utilization_history(since: int, until: int) -> List[Dict[str, Any]]:
    """获取GPU利用率历史数据"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT ts, gpu_util_avg, gpu_temp_avg FROM gpu_data WHERE ts BETWEEN ? AND ? ORDER BY ts",
                (since, until)
            )).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error getting GPU history: {e}")
        return []


def calculate_gpu_statistics(gpu_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算GPU统计信息"""
    if not gpu_data:
        return {
            'avg_utilization': 0,
            'max_utilization': 0,
            'min_utilization': 0,
            'avg_temperature': 0,
            'max_temperature': 0,
            'min_temperature': 0,
            'data_points': 0
        }
    
    utilizations = [d.get('gpu_util_avg', 0) for d in gpu_data if d.get('gpu_util_avg') is not None]
    temperatures = [d.get('gpu_temp_avg', 0) for d in gpu_data if d.get('gpu_temp_avg') is not None]
    
    return {
        'avg_utilization': sum(utilizations) / len(utilizations) if utilizations else 0,
        'max_utilization': max(utilizations) if utilizations else 0,
        'min_utilization': min(utilizations) if utilizations else 0,
        'avg_temperature': sum(temperatures) / len(temperatures) if temperatures else 0,
        'max_temperature': max(temperatures) if temperatures else 0,
        'min_temperature': min(temperatures) if temperatures else 0,
        'data_points': len(gpu_data)
    }


async def get_gpu_realtime_data() -> Dict[str, Any]:
    """获取GPU实时数据"""
    gpu_info = get_detailed_gpu_info()
    
    # 获取最近1小时的平均数据
    now = int(time.time())
    one_hour_ago = now - 3600
    history_data = await get_gpu_utilization_history(one_hour_ago, now)
    stats = calculate_gpu_statistics(history_data)
    
    return {
        'gpus': gpu_info['gpus'],
        'count': gpu_info['count'],
        'timestamp': gpu_info['timestamp'],
        'realtime_stats': stats
    }
async def store_gpu_detailed_data(gpu_data: Dict[str, Any]) -> None:
    """存储详细的GPU数据到数据库"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            ts = int(time.time())
            
            for gpu in gpu_data.get('gpus', []):
                await db.execute("""
                    INSERT INTO gpu_detailed_data 
                    (ts, gpu_index, gpu_name, utilization, temperature, memory_used, 
                     memory_total, memory_percent, power_draw, clock_graphics, clock_memory)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ts, gpu['index'], gpu['name'], gpu['utilization'], gpu['temperature'],
                    gpu['memory_used'], gpu['memory_total'], gpu['memory_percent'],
                    gpu['power_draw'], gpu['clock_graphics'], gpu['clock_memory']
                ))
            
            # 存储进程数据
            for gpu in gpu_data.get('gpus', []):
                for process in gpu.get('processes', []):
                    await db.execute("""
                        INSERT INTO gpu_process_data 
                        (ts, gpu_index, pid, process_name, memory_used)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        ts, gpu['index'], process['pid'], process['name'], process['memory']
                    ))
            
            await db.commit()
    except Exception as e:
        print(f"Error storing GPU data: {e}")


async def get_gpu_utilization_trend(since: int, until: int) -> List[Dict[str, Any]]:
    """获取GPU利用率趋势数据"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("""
                SELECT ts, gpu_index, gpu_name, utilization, temperature
                FROM gpu_detailed_data 
                WHERE ts BETWEEN ? AND ? 
                ORDER BY ts, gpu_index
            """, (since, until))).fetchall()
            
            # 按GPU索引分组数据
            gpu_data = {}
            for row in rows:
                gpu_index = row['gpu_index']
                if gpu_index not in gpu_data:
                    gpu_data[gpu_index] = {
                        'gpu_index': gpu_index,
                        'gpu_name': row['gpu_name'],
                        'data_points': []
                    }
                gpu_data[gpu_index]['data_points'].append({
                    'ts': row['ts'],
                    'utilization': row['utilization'],
                    'temperature': row['temperature']
                })
            
            return list(gpu_data.values())
    except Exception as e:
        print(f"Error getting GPU utilization trend: {e}")
        return []


async def get_gpu_temperature_trend(since: int, until: int) -> List[Dict[str, Any]]:
    """获取GPU温度趋势数据"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("""
                SELECT ts, gpu_index, gpu_name, temperature, power_draw
                FROM gpu_detailed_data 
                WHERE ts BETWEEN ? AND ? 
                ORDER BY ts, gpu_index
            """, (since, until))).fetchall()
            
            # 按GPU索引分组数据
            gpu_data = {}
            for row in rows:
                gpu_index = row['gpu_index']
                if gpu_index not in gpu_data:
                    gpu_data[gpu_index] = {
                        'gpu_index': gpu_index,
                        'gpu_name': row['gpu_name'],
                        'data_points': []
                    }
                gpu_data[gpu_index]['data_points'].append({
                    'ts': row['ts'],
                    'temperature': row['temperature'],
                    'power_draw': row['power_draw']
                })
            
            return list(gpu_data.values())
    except Exception as e:
        print(f"Error getting GPU temperature trend: {e}")
        return []


async def get_gpu_processes_history(since: int, until: int) -> List[Dict[str, Any]]:
    """获取GPU进程历史数据"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("""
                SELECT ts, gpu_index, pid, process_name, memory_used
                FROM gpu_process_data 
                WHERE ts BETWEEN ? AND ? 
                ORDER BY ts DESC, gpu_index, memory_used DESC
            """, (since, until))).fetchall()
            
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error getting GPU processes history: {e}")
        return []


async def calculate_and_store_gpu_statistics(period: str, since: int, until: int) -> Dict[str, Any]:
    """计算并存储GPU统计信息"""
    try:
        # 获取详细数据
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            # 获取利用率数据
            util_rows = await (await db.execute("""
                SELECT utilization FROM gpu_detailed_data 
                WHERE ts BETWEEN ? AND ?
            """, (since, until))).fetchall()
            
            # 获取温度数据
            temp_rows = await (await db.execute("""
                SELECT temperature FROM gpu_detailed_data 
                WHERE ts BETWEEN ? AND ?
            """, (since, until))).fetchall()
            
            # 获取进程数据
            process_rows = await (await db.execute("""
                SELECT COUNT(DISTINCT pid) as process_count, COUNT(DISTINCT gpu_index) as gpu_count
                FROM gpu_process_data 
                WHERE ts BETWEEN ? AND ?
            """, (since, until))).fetchone()
            
            # 计算统计信息
            utilizations = [row['utilization'] for row in util_rows if row['utilization'] is not None]
            temperatures = [row['temperature'] for row in temp_rows if row['temperature'] is not None]
            
            stats = {
                'avg_utilization': sum(utilizations) / len(utilizations) if utilizations else 0,
                'max_utilization': max(utilizations) if utilizations else 0,
                'min_utilization': min(utilizations) if utilizations else 0,
                'avg_temperature': sum(temperatures) / len(temperatures) if temperatures else 0,
                'max_temperature': max(temperatures) if temperatures else 0,
                'min_temperature': min(temperatures) if temperatures else 0,
                'total_processes': process_rows['process_count'] if process_rows else 0,
                'gpu_count': process_rows['gpu_count'] if process_rows else 0
            }
            
            # 存储统计信息
            await db.execute("""
                INSERT INTO gpu_statistics 
                (ts, period, avg_utilization, max_utilization, min_utilization, 
                 avg_temperature, max_temperature, min_temperature, total_processes, gpu_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                until, period, stats['avg_utilization'], stats['max_utilization'],
                stats['min_utilization'], stats['avg_temperature'], stats['max_temperature'],
                stats['min_temperature'], stats['total_processes'], stats['gpu_count']
            ))
            
            await db.commit()
            return stats
            
    except Exception as e:
        print(f"Error calculating GPU statistics: {e}")
        return {}


async def get_gpu_statistics(period: str, since: int, until: int) -> Dict[str, Any]:
    """获取GPU统计信息"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            
            # 先尝试从统计表获取
            row = await (await db.execute("""
                SELECT * FROM gpu_statistics 
                WHERE period = ? AND ts BETWEEN ? AND ?
                ORDER BY ts DESC LIMIT 1
            """, (period, since, until))).fetchone()
            
            if row:
                return dict(row)
            else:
                # 如果没有统计数据，实时计算
                return await calculate_and_store_gpu_statistics(period, since, until)
                
    except Exception as e:
        print(f"Error getting GPU statistics: {e}")
        return {}