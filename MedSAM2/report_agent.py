"""
Report Agent — 调用 Groq 免费 Llama 3.1 70B 生成英文放射诊断报告。
通过环境变量 GROQ_API_KEY 配置 API Key。
"""
import os
import requests
from typing import Dict, Any

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY = os.getenv("GROQ_API_KEY", "")


class ReportAgent:
    """Groq Llama 3.1 70B — 免费英文放射诊断报告"""

    def __init__(self):
        pass

    def _init_model(self):
        pass  # HF API 无需初始化

    def _build_prompt(self, metrics: Dict[str, Any], extra_context: str = "") -> str:
        """组装医学报告 prompt"""
        vol = metrics.get("volume_cm3", 0)
        area = metrics.get("max_slice_area_cm2", 0)
        size = metrics.get("physical_size_mm", (0, 0))
        organ = metrics.get("organ_hint", "unspecified")
        slices_affected = metrics.get("slices_with_lesion", 0)
        total_slices = metrics.get("total_slices_in_series", 0)
        sphericity = metrics.get("sphericity", 0)
        hu = metrics.get("mean_intensity_hu")

        density_desc = ""
        if hu is not None:
            if hu < 0:
                density_desc = f"hypodense ({hu:.0f} HU), suggestive of fatty content or lipid-rich material"
            elif hu < 20:
                density_desc = f"hypodense ({hu:.0f} HU), consistent with simple fluid or cystic nature"
            elif hu < 40:
                density_desc = f"mildly hypodense ({hu:.0f} HU), possibly proteinaceous fluid or early cellular infiltration"
            elif hu < 60:
                density_desc = f"isodense to soft tissue ({hu:.0f} HU), suggestive of solid cellular composition"
            elif hu < 100:
                density_desc = f"mildly hyperdense ({hu:.0f} HU), possible hemorrhagic component or proteinaceous content"
            else:
                density_desc = f"hyperdense ({hu:.0f} HU), suggestive of calcification, acute hemorrhage, or contrast enhancement"

        return f"""You are a board-certified radiologist. Generate a COMPREHENSIVE diagnostic radiology report in English only. Do NOT output any Chinese characters or non-English text. Use professional medical English throughout.

PATIENT CONTEXT:
- Modality: CT (Computed Tomography)
- Organ: {organ}
- Total slices in series: {total_slices}
- Slice thickness: {metrics.get('slice_thickness', 'N/A')} mm
- Pixel spacing: {metrics.get('pixel_spacing', ('N/A', 'N/A'))}

QUANTITATIVE FINDINGS:
- Lesion Volume: {vol:.2f} cm³
- Maximum cross-sectional area: {area:.2f} cm²
- Physical dimensions: {size[0]:.1f} x {size[1]:.1f} mm (max axial width x height)
- Affected slices: {slices_affected} / {total_slices} contiguous slices
- Sphericity index: {sphericity:.2f} (1.00 = perfect sphere, <0.7 = irregular/flat)
- CT attenuation: {density_desc if density_desc else 'not available'}

{extra_context}

Generate a DETAILED radiology report with ALL of the following sections in English:

## FINDINGS
Write 4-6 sentences in professional radiological language:
- Precise anatomical location within the {organ}
- Size in three dimensions (axial width, height, craniocaudal extent from slice count)
- Margins (well-defined vs ill-defined, smooth vs irregular, presence of capsule)
- Internal characteristics (homogeneous vs heterogeneous, septations, calcifications, necrosis, hemorrhage)
- Relationship to adjacent structures (mass effect, vascular involvement, biliary dilatation if relevant)
- Enhancement characteristics if discernible
- Integrate ALL quantitative metrics naturally into the narrative

## IMPRESSION
Provide 2-4 differential diagnoses ranked by likelihood:
1. **Most likely diagnosis** - with 2-3 sentence justification referencing the specific quantitative findings (size, density in HU, sphericity, organ context)
2. **Alternative diagnosis** - with brief reasoning explaining why it is less likely
3. **Additional possibility** - note under what clinical circumstances this would be considered
4. (Optional) If relevant based on organ and density

## RECOMMENDATIONS
Provide 4-6 specific, actionable clinical recommendations:
- Short-term follow-up imaging interval with specific modality (e.g., triphasic liver CT in 3 months)
- Whether biopsy or histopathological confirmation is indicated and under what conditions
- Relevant laboratory tests (tumor markers, liver function tests, etc.)
- Multidisciplinary team discussion recommendation
- Additional imaging sequences for better characterization (MRI with hepatobiliary contrast, PET-CT, etc.)
- Reference relevant clinical guidelines (LI-RADS for liver, Bosniak for renal, Fleischner for lung, etc.)

IMPORTANT: Output in English only. Be specific and reference the actual numbers. Make the report clinically useful for a treating physician. Write at least 350 words."""
# End of prompt — this is a comment in the code

    def generate(self, metrics: Dict[str, Any], extra_context: str = "") -> str:
        prompt = self._build_prompt(metrics, extra_context)
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a board-certified radiologist with 20 years of experience. Write comprehensive, clinically actionable diagnostic reports. Output in English only - never use Chinese characters or any non-English language. Provide specific differential diagnoses with detailed clinical reasoning. Reference quantitative data precisely. Be thorough and detailed - at least 350 words."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 1500,
        }
        try:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                if text and len(text) > 100:
                    print(f"[ReportAgent] Groq Llama 3.3 generated {len(text)} chars")
                    return text.strip()
            else:
                print(f"[ReportAgent] Groq API returned {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            print(f"[ReportAgent] Groq API call failed: {e}")

        # Fallback: 模板报告
        return self._template_fallback(metrics)

    def _template_fallback(self, metrics: Dict[str, Any]) -> str:
        vol = metrics.get("volume_cm3", 0)
        area = metrics.get("max_slice_area_cm2", 0)
        size = metrics.get("physical_size_mm", (0, 0))
        organ = metrics.get("organ_hint", "unspecified").title()
        slices = metrics.get("slices_with_lesion", 0)
        sphericity = metrics.get("sphericity", 0)
        hu = metrics.get("mean_intensity_hu")

        density_line = ""
        if hu is not None:
            if hu < 20:
                density_line = f"The lesion demonstrates hypodense attenuation ({hu:.0f} HU), consistent with simple fluid or cystic composition."
            elif hu < 60:
                density_line = f"The lesion shows soft tissue attenuation ({hu:.0f} HU), suggesting solid cellular content."
            else:
                density_line = f"The lesion is hyperdense ({hu:.0f} HU), possibly reflecting calcification, hemorrhage, or proteinaceous material."

        shape_desc = "roughly spherical" if sphericity > 0.85 else "moderately irregular" if sphericity > 0.6 else "markedly irregular and flattened"

        return f"""## FINDINGS
A {shape_desc} focal lesion is identified in the {organ} on non-contrast CT.
The lesion measures approximately {size[0]:.1f} x {size[1]:.1f} mm in maximal axial cross-section
and spans {slices} contiguous slices (slice thickness {metrics.get('slice_thickness', 1.0)} mm),
yielding a total volume of {vol:.2f} cm³. The maximum cross-sectional area is {area:.2f} cm².
{density_line}
The margins appear relatively well-circumscribed without evidence of adjacent organ invasion
or significant mass effect on surrounding structures. No calcifications or internal septations
are definitively identified on the current non-contrast examination.

## IMPRESSION
1. **{organ} cyst** (most likely if hypodense <20 HU) - Simple cystic lesions are common
   incidental findings and typically benign. The well-defined margins and homogeneous fluid
   attenuation are characteristic. In the liver, a simple cyst requires no further workup.
2. **Hemangioma** - If located in the liver, a typical hemangioma would demonstrate
   characteristic peripheral nodular enhancement with centripetal filling on contrast-enhanced
   imaging. Non-contrast CT alone is insufficient to confirm or exclude this diagnosis.
3. **Primary neoplasm** - A solid lesion of this size warrants exclusion of malignancy.
   The {shape_desc} morphology and well-defined margins provide some reassurance but do not
   definitively exclude neoplastic etiology. Hepatocellular carcinoma, cholangiocarcinoma,
   or other primary {organ} malignancies should be considered.
4. **Metastasis** - In the appropriate clinical context (known primary malignancy), a solitary
   {organ} lesion of this size and morphology could represent metastatic disease. Correlation
   with oncologic history is essential.

## RECOMMENDATIONS
- Obtain contrast-enhanced CT or multiphase MRI for definitive characterization of the {organ}
  lesion. If hepatic, perform multiphase liver CT or MRI with hepatobiliary contrast per LI-RADS
  guidelines.
- Consider serum tumor markers (AFP, CA 19-9, CEA) and comprehensive liver function tests if
  clinically indicated.
- Schedule short-interval follow-up imaging in 3-6 months to assess for interval growth if the
  lesion is not immediately characterized on contrast-enhanced imaging.
- Refer for multidisciplinary hepatobiliary tumor board discussion if imaging features are
  indeterminate or if there is clinical concern for malignancy.
- Evaluate for underlying chronic liver disease or risk factors (hepatitis B/C, alcohol use,
  metabolic syndrome) that may influence the differential diagnosis.
- Correlate with complete clinical history including any symptoms (pain, weight loss, early
  satiety), prior imaging studies, and family history of malignancy.
"""


def generate_report(metrics: Dict[str, Any], extra_context: str = "") -> str:
    """Convenience entry point."""
    agent = ReportAgent()
    return agent.generate(metrics, extra_context)
