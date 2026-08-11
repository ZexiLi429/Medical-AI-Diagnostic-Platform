"""实验数据采集脚本 —— 遍历 Orthanc 中所有 study，自动分割并收集指标"""
import requests
import time
import json
import statistics
from datetime import datetime

ORTHANC = "http://localhost:8042"
TOTALSEG = "http://localhost:8004"

def collect_all_metrics():
    results = []
    
    # 1. 获取所有 studies
    studies = requests.get(f"{ORTHANC}/studies", timeout=10).json()
    total = len(studies)
    print(f"Total studies: {total}")
    
    for i, sid in enumerate(studies):
        info = requests.get(f"{ORTHANC}/studies/{sid}", timeout=10).json()
        desc = info.get("MainDicomTags", {}).get("StudyDescription", "N/A")
        
        # 获取第一个 series 的 UID
        series_list = info.get("Series", [])
        if not series_list:
            continue
        sinfo = requests.get(f"{ORTHANC}/series/{series_list[0]}", timeout=10).json()
        uid = sinfo.get("MainDicomTags", {}).get("SeriesInstanceUID", "")
        slices = len(sinfo.get("Instances", []))
        
        print(f"\n[{i+1}/{total}] {desc} ({slices} slices)")
        
        try:
            # 2. 调用 /segment （获取器官列表+体积，不生成 mesh，快）
            t0 = time.time()
            resp = requests.post(f"{TOTALSEG}/segment", json={
                "series_instance_uid": uid,
            }, timeout=900)
            elapsed = time.time() - t0
            
            if resp.status_code != 200:
                print(f"  ERROR: {resp.status_code}")
                continue
            
            data = resp.json()
            organs = data.get("organs", [])
            num_organs = len(organs)
            top_organ = organs[0]["name"] if organs else "N/A"
            top_vol = organs[0]["volume_cm3"] if organs else 0
            total_vol = sum(o["volume_cm3"] for o in organs)
            
            # 3. 检查可用病灶
            organ_names = [o["name"] for o in organs]
            has_liver = any("liver" in n for n in organ_names)
            has_kidney = any("kidney" in n for n in organ_names)
            has_lung = any("lung" in n for n in organ_names)
            
            lesion_results = {}
            for organ_type, has_organ in [("liver", has_liver), ("kidney", has_kidney), ("lung", has_lung)]:
                if not has_organ:
                    continue
                try:
                    t1 = time.time()
                    lr = requests.post(f"{TOTALSEG}/segment_lesion_by_organ", json={
                        "series_instance_uid": uid,
                        "organ_name": organ_type,
                    }, timeout=900)
                    lt = time.time() - t1
                    if lr.status_code == 200:
                        ld = lr.json()
                        lesion_count = len(ld.get("meshes", []))
                        lesion_results[organ_type] = {"count": lesion_count, "time_s": round(lt, 1)}
                        print(f"  {organ_type}: {lesion_count} lesions ({lt:.0f}s)")
                except Exception as e:
                    print(f"  {organ_type} lesion error: {e}")

            result = {
                "study": desc,
                "slices": slices,
                "organs": num_organs,
                "top_organ": top_organ,
                "top_volume_cm3": round(top_vol, 1),
                "total_volume_cm3": round(total_vol, 1),
                "inference_time_s": round(elapsed, 1),
                "has_liver": has_liver,
                "has_kidney": has_kidney,
                "has_lung": has_lung,
                "lesions": lesion_results,
            }
            results.append(result)
            print(f"  => {num_organs} organs, top: {top_organ} ({top_vol:.0f} cm³), {elapsed:.0f}s")
            
            # 防止 OOM：每 2 个 study 清一次缓存（下次会重新跑）
            if i % 2 == 1:
                requests.post(f"{TOTALSEG}/segment", json={"series_instance_uid": "clear_cache"})
                
        except Exception as e:
            print(f"  ERROR: {e}")
    
    # 4. 汇总统计
    print("\n" + "="*60)
    print("SUMMARY STATISTICS")
    print("="*60)
    
    organ_counts = [r["organs"] for r in results]
    times = [r["inference_time_s"] for r in results]
    slices_list = [r["slices"] for r in results]
    
    print(f"Studies processed: {len(results)}")
    print(f"Slices: {min(slices_list)}-{max(slices_list)} (mean {statistics.mean(slices_list):.0f})")
    print(f"Organs per case: {statistics.mean(organ_counts):.1f} ± {statistics.stdev(organ_counts):.1f} (range {min(organ_counts)}-{max(organ_counts)})")
    if times:
        print(f"Inference time: {statistics.mean(times):.0f}s ± {statistics.stdev(times):.0f}s per case")
    
    # 病灶统计
    for organ_type in ["liver", "kidney", "lung"]:
        detected = [r for r in results if r["lesions"].get(organ_type, {}).get("count", 0) > 0]
        total_with = sum(1 for r in results if r[f"has_{organ_type}"])
        print(f"{organ_type} lesions: {len(detected)}/{total_with} cases had lesions")
    
    # 保存原始数据
    report = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "summary": {
            "n_studies": len(results),
            "mean_organs": round(statistics.mean(organ_counts), 1) if organ_counts else 0,
            "std_organs": round(statistics.stdev(organ_counts), 1) if len(organ_counts) > 1 else 0,
            "mean_time_s": round(statistics.mean(times), 0) if times else 0,
            "min_slices": min(slices_list),
            "max_slices": max(slices_list),
        }
    }
    
    outfile = "c:/Users/Dell/Desktop/miscada-project-master/experiment_results.json"
    with open(outfile, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {outfile}")
    
    return report

if __name__ == "__main__":
    collect_all_metrics()
