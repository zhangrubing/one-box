from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from ..deps import require_user
from ..utils.gpu_monitor import get_detailed_gpu_info, get_gpu_utilization_history, calculate_gpu_statistics, get_gpu_realtime_data
from ..web import render
import time


router = APIRouter()


@router.get("/gpu", response_class=HTMLResponse)
async def gpu_page(request: Request):
    return render(request, "gpu_enhanced.html")


@router.get("/api/system/gpu")
async def api_system_gpu(request: Request, user: dict = Depends(require_user)):
    """获取GPU基本信息（保持向后兼容）"""
    return get_detailed_gpu_info()


@router.get("/api/gpu/info")
async def api_gpu_info(request: Request, user: dict = Depends(require_user)):
    """获取GPU基本信息"""
    return get_detailed_gpu_info()


@router.get("/api/gpu/realtime")
async def api_gpu_realtime(request: Request, user: dict = Depends(require_user)):
    """获取GPU实时数据"""
    return await get_gpu_realtime_data()


@router.get("/api/gpu/history")
async def api_gpu_history(
    request: Request,
    period: str = Query("1h", description="时间周期: 1h, 6h, 1d, 7d, 30d"),
    user: dict = Depends(require_user)
):
    """获取GPU历史数据"""
    now = int(time.time())
    
    # 根据周期计算时间范围
    period_map = {
        "1h": 3600,      # 1小时
        "6h": 21600,     # 6小时
        "1d": 86400,     # 1天
        "7d": 604800,    # 7天
        "30d": 2592000   # 30天
    }
    
    if period not in period_map:
        period = "1h"
    
    since = now - period_map[period]
    
    # 获取历史数据
    history_data = await get_gpu_utilization_history(since, now)
    
    # 计算统计信息
    stats = calculate_gpu_statistics(history_data)
    
    return {
        'period': period,
        'since': since,
        'until': now,
        'data': history_data,
        'statistics': stats,
        'data_points': len(history_data)
    }


@router.get("/api/gpu/statistics")
async def api_gpu_statistics(
    request: Request,
    since: int = Query(..., description="开始时间戳"),
    until: int = Query(..., description="结束时间戳"),
    user: dict = Depends(require_user)
):
    """获取指定时间段的GPU统计信息"""
    history_data = await get_gpu_utilization_history(since, until)
    stats = calculate_gpu_statistics(history_data)
    
    return {
        'since': since,
        'until': until,
        'statistics': stats,
        'data_points': len(history_data)
    }


@router.get("/api/gpu/processes")
async def api_gpu_processes(request: Request, user: dict = Depends(require_user)):
    """获取GPU进程信息"""
    gpu_info = get_detailed_gpu_info()
    
    # 提取所有GPU的进程信息
    all_processes = []
    for gpu in gpu_info.get('gpus', []):
        for process in gpu.get('processes', []):
            process['gpu_index'] = gpu['index']
            process['gpu_name'] = gpu['name']
            all_processes.append(process)
    
    return {
        'processes': all_processes,
        'total_processes': len(all_processes),
        'gpu_count': gpu_info.get('count', 0)
    }
