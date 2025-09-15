#!/usr/bin/env python3
"""
测试增强监控功能
"""
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.utils.enhanced_system import collect_system_snapshot
from backend.utils.alert_manager import alert_manager


async def test_system_snapshot():
    """测试系统快照收集"""
    print("=== 测试系统快照收集 ===")
    try:
        snap = collect_system_snapshot()
        print(f"✓ 系统快照收集成功")
        print(f"  - CPU使用率: {snap.get('cpu_percent', 0):.1f}%")
        print(f"  - 内存使用率: {snap.get('mem_percent', 0):.1f}%")
        print(f"  - GPU利用率: {snap.get('gpu_util_avg', 0):.1f}%")
        print(f"  - GPU温度: {snap.get('gpu_temp_avg', 0):.1f}°C")
        print(f"  - 磁盘IO: {snap.get('disk_mb_s', 0):.1f} MB/s")
        print(f"  - 进程数量: {snap.get('processes', 0)}")
        
        # 检查告警
        alerts = snap.get('alerts', [])
        if alerts:
            print(f"  - 检测到 {len(alerts)} 个告警:")
            for alert in alerts:
                print(f"    * {alert['level']}: {alert['title']}")
        else:
            print("  - 无告警")
            
        return True
    except Exception as e:
        print(f"✗ 系统快照收集失败: {e}")
        return False


async def test_alert_manager():
    """测试告警管理器"""
    print("\n=== 测试告警管理器 ===")
    try:
        # 创建测试告警
        alert_id = await alert_manager.create_alert(
            level="WARNING",
            title="测试告警",
            message="这是一个测试告警"
        )
        print(f"✓ 创建测试告警成功，ID: {alert_id}")
        
        # 获取最近告警
        recent_alerts = await alert_manager.get_recent_alerts(hours=1)
        print(f"✓ 获取最近告警成功，数量: {len(recent_alerts)}")
        
        # 获取严重告警
        critical_alerts = await alert_manager.get_critical_alerts(hours=1)
        print(f"✓ 获取严重告警成功，数量: {len(critical_alerts)}")
        
        # 确认告警
        success = await alert_manager.acknowledge_alert(alert_id)
        print(f"✓ 确认告警: {'成功' if success else '失败'}")
        
        # 删除测试告警
        success = await alert_manager.delete_alert(alert_id)
        print(f"✓ 删除测试告警: {'成功' if success else '失败'}")
        
        return True
    except Exception as e:
        print(f"✗ 告警管理器测试失败: {e}")
        return False


async def test_network_io():
    """测试网络IO统计"""
    print("\n=== 测试网络IO统计 ===")
    try:
        from backend.utils.enhanced_system import _get_network_io
        network_io = _get_network_io()
        print(f"✓ 网络接口数量: {len(network_io)}")
        
        for interface, stats in list(network_io.items())[:3]:  # 只显示前3个接口
            print(f"  - {interface}: 发送 {stats['bytes_sent']} 字节, 接收 {stats['bytes_recv']} 字节")
        
        return True
    except Exception as e:
        print(f"✗ 网络IO统计测试失败: {e}")
        return False


async def test_process_info():
    """测试进程信息统计"""
    print("\n=== 测试进程信息统计 ===")
    try:
        from backend.utils.enhanced_system import _get_process_info
        process_info = _get_process_info()
        print(f"✓ 进程统计成功")
        print(f"  - 总进程数: {process_info.get('total', 0)}")
        print(f"  - 状态统计: {process_info.get('status_count', {})}")
        print(f"  - CPU使用率前5: {len(process_info.get('top_cpu', []))}")
        print(f"  - 内存使用率前5: {len(process_info.get('top_memory', []))}")
        
        return True
    except Exception as e:
        print(f"✗ 进程信息统计测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("开始测试增强监控功能...\n")
    
    tests = [
        test_system_snapshot,
        test_alert_manager,
        test_network_io,
        test_process_info
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"✗ 测试 {test.__name__} 异常: {e}")
            results.append(False)
    
    print(f"\n=== 测试结果 ===")
    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")
    
    if passed == total:
        print("🎉 所有测试通过！增强监控功能正常工作。")
    else:
        print("⚠️  部分测试失败，请检查相关功能。")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
