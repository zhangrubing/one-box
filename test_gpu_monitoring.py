#!/usr/bin/env python3
"""
测试GPU监控功能
"""
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.utils.gpu_monitor import get_detailed_gpu_info, get_gpu_utilization_history, calculate_gpu_statistics, get_gpu_realtime_data


async def test_gpu_info():
    """测试GPU信息获取"""
    print("=== 测试GPU信息获取 ===")
    try:
        gpu_info = get_detailed_gpu_info()
        print(f"✓ GPU信息获取成功")
        print(f"  - GPU数量: {gpu_info.get('count', 0)}")
        print(f"  - 时间戳: {gpu_info.get('timestamp', 0)}")
        
        gpus = gpu_info.get('gpus', [])
        if gpus:
            print(f"  - GPU详情:")
            for i, gpu in enumerate(gpus):
                print(f"    GPU {gpu.get('index', i)}:")
                print(f"      型号: {gpu.get('name', 'Unknown')}")
                print(f"      利用率: {gpu.get('utilization', 0):.1f}%")
                print(f"      温度: {gpu.get('temperature', 0):.1f}°C")
                print(f"      显存: {gpu.get('memory_used', 0):.0f}/{gpu.get('memory_total', 0):.0f} MB")
                print(f"      功耗: {gpu.get('power_draw', 0):.1f}W")
                print(f"      进程数: {len(gpu.get('processes', []))}")
        else:
            print("  - 未检测到GPU设备")
            
        return True
    except Exception as e:
        print(f"✗ GPU信息获取失败: {e}")
        return False


async def test_gpu_history():
    """测试GPU历史数据获取"""
    print("\n=== 测试GPU历史数据获取 ===")
    try:
        import time
        now = int(time.time())
        one_hour_ago = now - 3600
        
        history_data = await get_gpu_utilization_history(one_hour_ago, now)
        print(f"✓ GPU历史数据获取成功")
        print(f"  - 数据点数量: {len(history_data)}")
        
        if history_data:
            # 计算统计信息
            stats = calculate_gpu_statistics(history_data)
            print(f"  - 平均利用率: {stats['avg_utilization']:.1f}%")
            print(f"  - 最大利用率: {stats['max_utilization']:.1f}%")
            print(f"  - 平均温度: {stats['avg_temperature']:.1f}°C")
            print(f"  - 最大温度: {stats['max_temperature']:.1f}°C")
        else:
            print("  - 无历史数据")
            
        return True
    except Exception as e:
        print(f"✗ GPU历史数据获取失败: {e}")
        return False


async def test_gpu_realtime():
    """测试GPU实时数据获取"""
    print("\n=== 测试GPU实时数据获取 ===")
    try:
        realtime_data = await get_gpu_realtime_data()
        print(f"✓ GPU实时数据获取成功")
        print(f"  - GPU数量: {realtime_data.get('count', 0)}")
        print(f"  - 时间戳: {realtime_data.get('timestamp', 0)}")
        
        stats = realtime_data.get('realtime_stats', {})
        if stats:
            print(f"  - 实时统计:")
            print(f"    平均利用率: {stats.get('avg_utilization', 0):.1f}%")
            print(f"    最大利用率: {stats.get('max_utilization', 0):.1f}%")
            print(f"    平均温度: {stats.get('avg_temperature', 0):.1f}°C")
            print(f"    最大温度: {stats.get('max_temperature', 0):.1f}°C")
            print(f"    数据点: {stats.get('data_points', 0)}")
        
        return True
    except Exception as e:
        print(f"✗ GPU实时数据获取失败: {e}")
        return False


async def test_gpu_statistics():
    """测试GPU统计计算"""
    print("\n=== 测试GPU统计计算 ===")
    try:
        # 创建测试数据
        test_data = [
            {'gpu_util_avg': 50.0, 'gpu_temp_avg': 65.0},
            {'gpu_util_avg': 75.0, 'gpu_temp_avg': 70.0},
            {'gpu_util_avg': 25.0, 'gpu_temp_avg': 60.0},
            {'gpu_util_avg': 90.0, 'gpu_temp_avg': 80.0},
            {'gpu_util_avg': 60.0, 'gpu_temp_avg': 68.0}
        ]
        
        stats = calculate_gpu_statistics(test_data)
        print(f"✓ GPU统计计算成功")
        print(f"  - 平均利用率: {stats['avg_utilization']:.1f}%")
        print(f"  - 最大利用率: {stats['max_utilization']:.1f}%")
        print(f"  - 最小利用率: {stats['min_utilization']:.1f}%")
        print(f"  - 平均温度: {stats['avg_temperature']:.1f}°C")
        print(f"  - 最大温度: {stats['max_temperature']:.1f}°C")
        print(f"  - 最小温度: {stats['min_temperature']:.1f}°C")
        print(f"  - 数据点: {stats['data_points']}")
        
        return True
    except Exception as e:
        print(f"✗ GPU统计计算失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("🚀 GPU监控功能测试")
    print("=" * 50)
    
    tests = [
        test_gpu_info,
        test_gpu_history,
        test_gpu_realtime,
        test_gpu_statistics
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
        print("🎉 所有测试通过！GPU监控功能正常工作。")
    else:
        print("⚠️  部分测试失败，请检查相关功能。")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
