from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from ..deps import require_user
from ..utils.enhanced_system import collect_system_snapshot, _get_network_io, _get_process_info
from ..utils.alert_manager import alert_manager
from ..web import render


router = APIRouter()


@router.get("/enhanced-monitoring", response_class=HTMLResponse)
async def enhanced_monitoring_page(request: Request):
    return render(request, "enhanced_monitoring.html")


@router.get("/api/enhanced/system/snapshot")
async def api_enhanced_system_snapshot(request: Request, user: dict = Depends(require_user)):
    """获取增强的系统快照数据"""
    return collect_system_snapshot()


@router.get("/api/enhanced/network/io")
async def api_enhanced_network_io(request: Request, user: dict = Depends(require_user)):
    """获取网络IO统计"""
    return _get_network_io()


@router.get("/api/enhanced/process/info")
async def api_enhanced_process_info(request: Request, user: dict = Depends(require_user)):
    """获取进程统计信息"""
    return _get_process_info()


@router.get("/api/enhanced/alerts/recent")
async def api_enhanced_alerts_recent(hours: int = 24, user: dict = Depends(require_user)):
    """获取最近的告警"""
    return await alert_manager.get_recent_alerts(hours=hours)


@router.get("/api/enhanced/alerts/critical")
async def api_enhanced_alerts_critical(hours: int = 24, user: dict = Depends(require_user)):
    """获取严重告警"""
    return await alert_manager.get_critical_alerts(hours=hours)


@router.post("/api/enhanced/alerts/{alert_id}/ack")
async def api_enhanced_alerts_ack(alert_id: int, user: dict = Depends(require_user)):
    """确认告警"""
    success = await alert_manager.acknowledge_alert(alert_id)
    return {"success": success}


@router.delete("/api/enhanced/alerts/{alert_id}")
async def api_enhanced_alerts_delete(alert_id: int, user: dict = Depends(require_user)):
    """删除告警"""
    success = await alert_manager.delete_alert(alert_id)
    return {"success": success}


@router.post("/api/enhanced/alerts/cleanup")
async def api_enhanced_alerts_cleanup(days: int = 30, user: dict = Depends(require_user)):
    """清理旧告警"""
    count = await alert_manager.cleanup_old_alerts(days=days)
    return {"deleted_count": count}
