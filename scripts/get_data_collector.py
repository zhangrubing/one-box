#!/usr/bin/env python3
"""
GPU数据收集脚本
定期收集GPU数据并存储到数据库
"""

import asyncio
import time
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.gpu_monitor import get_detailed_gpu_info, store_gpu_detailed_data

async def collect_gpu_data():
    """收集GPU数据"""
    try:
        # 获取当前GPU信息
        gpu_data = get_detailed_gpu_info()
        
        # 存储到数据库
        await store_gpu_detailed_data(gpu_data)
        
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Collected GPU data for {gpu_data['count']} GPUs")
        
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Error collecting GPU data: {e}")

async def main():
    """主函数"""
    print("Starting GPU data collector...")
    
    while True:
        await collect_gpu_data()
        
        # 每30秒收集一次
        await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping GPU data collector...")
