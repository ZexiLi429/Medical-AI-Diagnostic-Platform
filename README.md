<div align="center">

<div align="center">

# 🏥 MISCADA

### Multi-Agent Collaborative CT Intelligent Segmentation & Diagnostic Report Platform

[![TypeScript](https://img.shields.io/badge/TypeScript-5.0%2B-3178C6)](https://typescriptlang.org)
[![React](https://img.shields.io/badge/React-18-61DAFB)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104%2B-009688)](https://fastapi.tiangolo.com)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C)](https://pytorch.org)
[![MedSAM](https://img.shields.io/badge/Segmentation-MedSAM%2FMedSAM2-blueviolet)](https://github.com/bowang-lab/MedSAM)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**2D Lesion Segmentation → 3D Full-Sequence Tracking → Structured Radiology Report Generation**

</div>

---

<a href="https://github.com/ZexiLi429/Medical-AI-Diagnostic-Platform/blob/master/demo.mp4">
  <img src="demo.png" alt="Demo Video" width="100%">
</a>
<p align="center"><em>👆 Click the image to watch the demo video</em></p>

---

## 🧠 Overview

MISCADA is a self-developed research platform that builds a **multi-agent collaborative CT image analysis system**, covering the full closed loop from 2D lesion segmentation to 3D full-sequence tracking to structured radiology report generation. Based on **OHIF Viewer + Cornerstone3D** for medical imaging interaction, integrated with **MedSAM/MedSAM2** for AI segmentation, and powered by a self-developed **Analyze → Evaluate → Report** three-agent pipeline. Unified DICOM spatial metadata (IPP/IOP/PixelSpacing) enables sub-millimeter precision alignment across coordinate systems, achieving accurate lesion quantification and automatic structured English report generation.

## 🏗 Architecture

```
OHIF Viewer + Cornerstone3D (:3000)     ← 2D MPR · 3D Volume Rendering · Interactive Annotation
        │
FastAPI Backend (:8004)                 ← Orchestration · Session State · DICOM Metadata Parsing
        │
   ┌────┼────────┐
   ▼    ▼         ▼
MedSAM/MedSAM2    Orthanc PACS (:8042)    LLM (Groq)
Lesion Seg.       DICOM Storage          Report Gen.
        │
   ─────┼────────────────────────────────
        │
   Three-Agent Pipeline
   Analyze → Evaluate → Report
```

## ✨ Key Features

### 🔬 DICOM 3D Coordinate Calibration & Mesh Auto-Alignment
Parsing DICOM metadata strings returned by Orthanc PACS to uniformly extract pixel spacing, image position (IPP), and direction cosines (IOP). Lesion masks are reconstructed into 3D surface meshes via Marching Cubes and transformed to physical coordinates through the DICOM standard coordinate system. The frontend directly consumes physical coordinates to construct rendering geometry with origin offset, achieving **sub-millimeter precision auto-overlay** of lesion 3D meshes onto volume-rendered CT data.

### 🤖 Multi-Agent Report Generation Pipeline
- **Quantification Agent** — traverses full-sequence masks to compute lesion volume, cross-sectional area, sphericity, CT mean value, and other metrics
- **Evaluation Agent** — executes medical rule checks including volume consistency, organ range, and slice proportion
- **Report Agent** — interfaces with LLM to fuse quantitative data, DICOM meta-information, and clinician-provided history, generating structured English reports with differential diagnoses and clinical guideline references

### 🎯 RLE Mask Intersection Post-Processing
Implements Run-Length Encoding (RLE) mask intersection: AI segmentation output and clinician annotation masks are decoded → pixel-wise AND → re-encoded, precisely constraining segmentation results within the region of interest to eliminate cross-organ over-segmentation.

### 🔗 UUID Session Full-Chain State Management
Create → Segment → Report endpoints linked through a global session ID spanning the entire workflow. Backend in-memory dictionary manages session state including segmentation results and analysis caches. Progress endpoint provides real-time bidirectional progress streaming. Frontend dynamically injects clinician-selected organs and medical history when requesting reports, with support for in-session analysis overwrites.

### 📄 Native PDF Report Layout & Interaction
Text-native layout with automatic line breaking, intelligent pagination, and side-by-side image embedding. Dynamic hiding of interface controls during generation. Interactive highlights: one-click screenshot preview in modal, completion notification floating action bar, DICOM metadata auto-populated organ selection, global degradation trigger mechanism.

## 🛠 Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | TypeScript · React 18 · OHIF Viewer · Cornerstone3D · vtk.js |
| **Backend** | Python · FastAPI · PyTorch |
| **AI Models** | MedSAM · MedSAM2 · TotalSegmentator v2 |
| **PACS** | Orthanc (DICOMweb) |
| **LLM** | Groq API · Llama 3.3 70B |
| **Data** | DICOM · NIfTI · RLE Encoding |

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+** · **Node.js 18+** · **Docker 24.0+**
- **Groq API key** ([free tier](https://console.groq.com))

### 1. Docker

```bash
docker run -d --name orthanc --network=host jodogne/orthanc-plugins
docker pull wasserth/totalsegmentator:latest
```

### 2. Backend

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
set GROQ_API_KEY=gsk_your_key
python totalseg_service.py          # → http://localhost:8004
```

### 3. Frontend

```bash
cd miscada-project-master
yarn install && yarn start          # → http://localhost:3000
```

Upload DICOM to Orthanc (`:8042`) → open viewer → segmentation triggers automatically.

## 📡 API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/segment_3d` | Full organ segmentation → 3D meshes |
| `POST` | `/segment_by_name` | Semantic organ query |
| `POST` | `/segment_lesion` | Box-guided lesion detection |
| `POST` | `/generate_report` | Three-agent diagnostic report |
| `POST` | `/analyze_lesions` | LLM lesion analysis |
| `GET` | `/health` | Health check |
| `GET` | `/progress/{session_id}` | Real-time progress streaming |

## 📁 Structure

```
├── totalseg_service.py      # FastAPI backend (port 8004)
├── demo.mp4 / demo.png      # Demo media
├── miscada-project-master/  # OHIF + Cornerstone3D frontend
├── MedSAM2/                 # MedSAM2 inference + report agent
├── MedSAM-main/             # MedSAM v1
├── MedSAM-LiteMedSAM/       # LiteMedSAM
├── service/                 # Deployed service copy
├── test/                    # Experiment & evaluation scripts
├── figures/                 # Thesis figure generation
├── result/                  # Experimental results
├── data/                    # Dataset utilities
└── legacy/                  # Deprecated scripts
```

## License

MIT
