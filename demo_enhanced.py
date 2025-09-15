#!/usr/bin/env python3
"""
增强监控系统演示脚本
展示真实数据收集和告警功能
"""
import asyncio
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.utils.enhanced_system import collect_system_snapshot
from backend.utils.alert_manager import alert_manager


async def demo_system_monitoring():
    """演示系统监控功能"""
    print("🔍 增强监控系统演示")
    print("=" * 50)
    
    # 收集系统快照
    print("\n📊 收集系统快照...")
    snap = collect_system_snapshot()
    
    print(f"✅ 系统信息:")
    print(f"   🖥️  CPU使用率: {snap.get('cpu_percent', 0):.1f}%")
    print(f"   💾 内存使用率: {snap.get('mem_percent', 0):.1f}%")
    print(f"   🎮 GPU利用率: {snap.get('gpu_util_avg', 0):.1f}%")
    print(f"   🌡️  GPU温度: {snap.get('gpu_temp_avg', 0):.1f}°C")
    print(f"   💿 磁盘IO: {snap.get('disk_mb_s', 0):.1f} MB/s")
    print(f"   🔄 进程数量: {snap.get('processes', 0)}")
    
    # 显示负载信息
    load = snap.get('load_avg', [0, 0, 0])
    print(f"   ⚖️  系统负载: {load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}")
    
    # 显示网络统计
    network_io = snap.get('network_io', {})
    print(f"   🌐 网络接口: {len(network_io)} 个")
    
    # 显示进程统计
    process_info = snap.get('process_info', {})
    print(f"   🔧 进程状态: {process_info.get('status_count', {})}")
    
    # 检查告警
    alerts = snap.get('alerts', [])
    if alerts:
        print(f"\n🚨 检测到 {len(alerts)} 个告警:")
        for alert in alerts:
            level_icon = "🔴" if alert['level'] == 'CRITICAL' else "🟡"
            print(f"   {level_icon} {alert['level']}: {alert['title']}")
    else:
        print(f"\n✅ 系统状态正常，无告警")
    
    return snap


async def demo_alert_system():
    """演示告警系统功能"""
    print(f"\n🚨 告警系统演示")
    print("=" * 50)
    
    # 创建测试告警
    print("📝 创建测试告警...")
    test_alerts = [
        ("WARNING", "CPU使用率较高", "CPU使用率达到85%，超过80%阈值"),
        ("CRITICAL", "内存使用率过高", "内存使用率达到96%，超过95%阈值"),
        ("WARNING", "GPU温度较高", "GPU平均温度达到82℃，超过80℃阈值")
    ]
    
    alert_ids = []
    for level, title, message in test_alerts:
        alert_id = await alert_manager.create_alert(level, title, message)
        alert_ids.append(alert_id)
        print(f"   ✅ 创建告警: {level} - {title} (ID: {alert_id})")
    
    # 查询告警
    print(f"\n📋 查询告警...")
    recent_alerts = await alert_manager.get_recent_alerts(hours=1)
    print(f"   📊 最近1小时告警数量: {len(recent_alerts)}")
    
    critical_alerts = await alert_manager.get_critical_alerts(hours=1)
    print(f"   🔴 严重告警数量: {len(critical_alerts)}")
    
    # 显示告警详情
    print(f"\n📋 告警详情:")
    for alert in recent_alerts:
        status = "已确认" if alert.get('acknowledged') else "待处理"
        level_icon = "🔴" if alert['level'] == 'CRITICAL' else "🟡"
        print(f"   {level_icon} [{alert['level']}] {alert['title']} - {status}")
    
    # 确认告警
    if alert_ids:
        print(f"\n✅ 确认告警...")
        for alert_id in alert_ids[:2]:  # 确认前两个告警
            success = await alert_manager.acknowledge_alert(alert_id)
            print(f"   {'✅' if success else '❌'} 确认告警 ID {alert_id}")
    
    # 删除测试告警
    print(f"\n🗑️  清理测试告警...")
    for alert_id in alert_ids:
        success = await alert_manager.delete_alert(alert_id)
        print(f"   {'✅' if success else '❌'} 删除告警 ID {alert_id}")


async def demo_real_time_monitoring():
    """演示实时监控"""
    print(f"\n⏱️  实时监控演示")
    print("=" * 50)
    print("📊 开始5秒实时监控...")
    
    for i in range(5):
        snap = collect_system_snapshot()
        cpu = snap.get('cpu_percent', 0)
        mem = snap.get('mem_percent', 0)
        gpu = snap.get('gpu_util_avg', 0)
        
        print(f"   [{i+1}/5] CPU: {cpu:.1f}% | 内存: {mem:.1f}% | GPU: {gpu:.1f}%")
        await asyncio.sleep(1)
    
    print("✅ 实时监控完成")


async def main():
    """主演示函数"""
    print("🚀 增强监控系统功能演示")
    print("=" * 60)
    
    try:
        # 演示系统监控
        await demo_system_monitoring()
        
        # 演示告警系统
        await demo_alert_system()
        
        # 演示实时监控
        await demo_real_time_monitoring()
        
        print(f"\n🎉 演示完成！")
        print(f"💡 提示: 访问 http://localhost:8000/enhanced-monitoring 查看增强监控界面")
        
    except Exception as e:
        print(f"❌ 演示过程中出现错误: {e}")
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
