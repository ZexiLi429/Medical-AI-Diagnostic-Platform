"""
服务测试脚本
测试MedSAM和LLM诊断服务是否正常运行
"""
import requests
import json
from pathlib import Path

# 服务端点
MEDSAM_URL = "http://localhost:8000"
LLM_URL = "http://localhost:8001"

def test_medsam_health():
    """测试MedSAM服务健康状态"""
    print("=" * 50)
    print("测试 MedSAM 服务...")
    print("=" * 50)
    
    try:
        response = requests.get(f"{MEDSAM_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ MedSAM服务运行正常")
            print(f"   响应: {response.json()}")
            return True
        else:
            print(f"❌ MedSAM服务异常: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到MedSAM服务 (http://localhost:8000)")
        print("   请确保服务已启动: python medsam_service.py")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


def test_llm_health():
    """测试LLM诊断服务健康状态"""
    print("\n" + "=" * 50)
    print("测试 LLM 诊断服务...")
    print("=" * 50)
    
    try:
        response = requests.get(f"{LLM_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ LLM服务运行正常")
            print(f"   响应: {response.json()}")
            return True
        else:
            print(f"❌ LLM服务异常: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到LLM服务 (http://localhost:8001)")
        print("   请确保服务已启动: python llm_diagnostic_service.py")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


def test_llm_report_generation():
    """测试LLM诊断报告生成"""
    print("\n" + "=" * 50)
    print("测试 LLM 诊断报告生成...")
    print("=" * 50)
    
    # 模拟诊断请求
    test_data = {
        "patient_id": "TEST_PATIENT_001",
        "patient_age": 45,
        "patient_gender": "Male",
        "modality": "CT",
        "body_region": "Chest",
        "clinical_history": "Patient presents with persistent cough and chest pain for 2 weeks. History of smoking (20 pack-years).",
        "imaging_findings": "5cm mass in right upper lobe with irregular margins. Mediastinal lymphadenopathy noted.",
        "segmentation_results": {
            "organs": ["lung_right", "lung_left"],
            "lesions": 1,
            "volume": 65.4
        },
        "measurements": [
            {"type": "Length", "length": 52.3},
            {"type": "Area", "area": 1247.8},
            {"type": "Volume", "volume": 65432.1}
        ],
        "model": "gpt-4"
    }
    
    try:
        print("📤 发送诊断请求...")
        print(f"   患者ID: {test_data['patient_id']}")
        print(f"   模态: {test_data['modality']}")
        print(f"   区域: {test_data['body_region']}")
        
        response = requests.post(
            f"{LLM_URL}/generate_report",
            json=test_data,
            timeout=60  # LLM响应可能较慢
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                print("✅ 诊断报告生成成功！")
                print("\n" + "=" * 50)
                print("生成的诊断报告:")
                print("=" * 50)
                print(result.get("report", ""))
                print("\n" + "=" * 50)
                print(f"使用模型: {result.get('model_used')}")
                print(f"生成时间: {result.get('timestamp')}")
                return True
            else:
                print(f"❌ 报告生成失败: {result.get('error')}")
                return False
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"   错误信息: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ 请求超时 (60秒)")
        print("   这可能是因为LLM API响应较慢或API密钥未配置")
        return False
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


def test_medsam_info():
    """获取MedSAM服务信息"""
    print("\n" + "=" * 50)
    print("获取 MedSAM 服务信息...")
    print("=" * 50)
    
    try:
        response = requests.get(f"{MEDSAM_URL}/")
        if response.status_code == 200:
            info = response.json()
            print("✅ 服务信息:")
            print(f"   服务名称: {info.get('service')}")
            print(f"   运行状态: {info.get('status')}")
            print(f"   计算设备: {info.get('device')}")
            print(f"   模型已加载: {info.get('model_loaded')}")
            return True
    except Exception as e:
        print(f"❌ 获取信息失败: {e}")
        return False


def test_llm_info():
    """获取LLM服务信息"""
    print("\n" + "=" * 50)
    print("获取 LLM 服务信息...")
    print("=" * 50)
    
    try:
        response = requests.get(f"{LLM_URL}/")
        if response.status_code == 200:
            info = response.json()
            print("✅ 服务信息:")
            print(f"   服务名称: {info.get('service')}")
            print(f"   运行状态: {info.get('status')}")
            print(f"   支持的模型: {', '.join(info.get('supported_models', []))}")
            print(f"   OpenAI已配置: {info.get('openai_configured')}")
            print(f"   Anthropic已配置: {info.get('anthropic_configured')}")
            
            if not info.get('openai_configured') and not info.get('anthropic_configured'):
                print("\n⚠️  警告: 未配置任何LLM API密钥")
                print("   请在 .env 文件中配置 OPENAI_API_KEY 或 ANTHROPIC_API_KEY")
            
            return True
    except Exception as e:
        print(f"❌ 获取信息失败: {e}")
        return False


def main():
    """主测试函数"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "MISCADA 服务测试脚本" + " " * 28 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    results = {
        "MedSAM健康检查": test_medsam_health(),
        "LLM健康检查": test_llm_health(),
        "MedSAM信息": test_medsam_info(),
        "LLM信息": test_llm_info(),
    }
    
    # 只有在服务运行正常时才测试报告生成
    if results["LLM健康检查"]:
        results["LLM报告生成"] = test_llm_report_generation()
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name:20s} : {status}")
    
    print("=" * 60)
    print(f"总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！系统运行正常。")
    else:
        print("\n⚠️  部分测试失败，请检查服务状态。")
        print("\n故障排除:")
        if not results["MedSAM健康检查"]:
            print("  • 启动MedSAM: python medsam_service.py")
        if not results["LLM健康检查"]:
            print("  • 启动LLM服务: python llm_diagnostic_service.py")
            print("  • 确保已配置API密钥（.env文件）")
    
    print()


if __name__ == "__main__":
    main()
