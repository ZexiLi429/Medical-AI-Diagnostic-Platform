#!/usr/bin/env python3
"""
快速测试MedSAM后端连接
"""
import requests
import sys

def test_backend():
    """测试后端连接"""
    print("🔍 测试MedSAM后端连接...")
    print("=" * 50)
    
    backend_url = "http://localhost:8000"
    
    # 测试1: 健康检查
    print("\n[1/3] 测试健康检查端点...")
    try:
        response = requests.get(f"{backend_url}/health", timeout=5)
        if response.status_code == 200:
            print("✅ 健康检查成功")
            print(f"   响应: {response.json()}")
        else:
            print(f"❌ 健康检查失败: HTTP {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到后端服务")
        print("\n请先启动MedSAM后端:")
        print("  cd MedSAM-main")
        print("  python medsam_service.py")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False
    
    # 测试2: 根路径
    print("\n[2/3] 测试根路径...")
    try:
        response = requests.get(backend_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("✅ 根路径访问成功")
            print(f"   服务名称: {data.get('service')}")
            print(f"   状态: {data.get('status')}")
            print(f"   设备: {data.get('device')}")
            print(f"   模型已加载: {data.get('model_loaded')}")
        else:
            print(f"❌ 根路径访问失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ 错误: {e}")
    
    # 测试3: CORS配置
    print("\n[3/3] 测试CORS配置...")
    try:
        headers = {
            'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'POST',
        }
        response = requests.options(f"{backend_url}/segment", headers=headers, timeout=5)
        
        cors_headers = response.headers.get('Access-Control-Allow-Origin', '')
        if cors_headers:
            print("✅ CORS配置正常")
            print(f"   允许的源: {cors_headers}")
            print(f"   允许的方法: {response.headers.get('Access-Control-Allow-Methods', '')}")
        else:
            print("⚠️  CORS响应头缺失，可能需要检查配置")
    except Exception as e:
        print(f"⚠️  CORS测试失败: {e}")
    
    print("\n" + "=" * 50)
    print("✅ 后端测试完成！")
    print("\n📌 前端连接说明:")
    print("1. 确保前端也在运行: http://localhost:3000")
    print("2. 选择 'MedSAM Viewer' 模式")
    print("3. 加载DICOM数据后，SAM按钮应该可以点击")
    print("\n📚 详细文档: 前后端连接诊断和修复指南.md")
    return True

if __name__ == "__main__":
    success = test_backend()
    sys.exit(0 if success else 1)
