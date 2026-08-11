# CT Analysis Platform — Multi-Agent Diagnostic System

<video src="https://raw.githubusercontent.com/ZexiLi429/Medical-AI-Diagnostic-Platform/master/demo.mp4" controls width="100%"></video>

> **Dissertation Project**: Computer-aided CT analysis platform integrating real-time 3D visualisation, multi-organ segmentation, box-guided lesion detection, and LLM-powered diagnostic report generation.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  OHIF/vtk.js Frontend (port 3000)                   │
│  • 2D MPR viewer + 3D volume rendering              │
│  • Semi-transparent organ meshes                    │
│  • Box-select lesion ROI                            │
├─────────────────────────────────────────────────────┤
│  FastAPI Backend (port 8004)                        │
│  • TotalSegmentator orchestration                   │
│  • MedSAM2 interactive refinement                   │
│  • Groq-hosted Llama 3.3 70B (report generation)    │
│  • Dual-level caching (organ + lesion)              │
├─────────────────────────────────────────────────────┤
│  Docker Containers                                  │
│  • TotalSegmentator v2 (117-class nnU-Net v2)       │
│  • Orthanc PACS (port 8042)                         │
│  • MedSAM2 (port 8003, interactive lesion seg)      │
└─────────────────────────────────────────────────────┘
```

## Features

| Feature | Description |
|---------|-------------|
| **Multi-organ Segmentation** | 117 anatomical structures via TotalSegmentator v2 |
| **Semantic Organ Queries** | Natural-language organ lookup (e.g. `"left lung"`, `"rib"`) |
| **Lesion Detection** | Box-guided: liver lesions, lung nodules, kidney cysts |
| **3D Visualisation** | vtk.js volume rendering with organ mesh overlay |
| **Diagnostic Reports** | Three-agent LLM workflow (Analysis → Evaluation → Generation) |
| **CPU-only Operation** | Adaptive Z-axis downsampling, dual-level caching |

---

## Prerequisites

| Component | Version | Notes |
|-----------|---------|-------|
| **Python** | 3.10+ | Backend service |
| **Docker** | 24.0+ | TotalSegmentator + Orthanc + MedSAM2 |
| **Node.js** | 18+ | OHIF frontend |
| **Groq API Key** | Free tier | For LLM report generation |

---

## Docker Setup

### 1. TotalSegmentator

```bash
docker pull wasserth/totalsegmentator:latest
```

Uses `--network=host` mode. The backend auto-pulls the image on first use if not present.

### 2. Orthanc PACS

```bash
docker run -d --name orthanc --network=host \
  -v orthanc_data:/var/lib/orthanc/db \
  jodogne/orthanc-plugins
```

Access at http://localhost:8042

### 3. MedSAM2 (optional, for interactive lesion refinement)

```bash
docker run -d --name medsam2 --network=host \
  -v ./MedSAM2:/workspace \
  medsam2:latest
```

---

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/YOUR_USERNAME/CT-Analysis-Platform.git
cd CT-Analysis-Platform

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS

pip install -r requirements.txt
```

### 2. Configuration

```bash
# Set Groq API key (free tier available at console.groq.com)
set GROQ_API_KEY=gsk_your_key_here
```

No other configuration needed — all defaults are pre-set for local development.

### 3. Start Docker Containers

```bash
# Orthanc PACS (required)
docker run -d --name orthanc --network=host jodogne/orthanc-plugins

# TotalSegmentator (auto-pulled by backend on first request)
# No manual start needed — the backend issues docker run on-demand
```

### 4. Start Backend

```bash
python totalseg_service.py
```

Backend starts at **http://localhost:8004**. Verify:

```bash
curl http://localhost:8004/health
# {"status": "ok"}
```

### 5. Start Frontend (OHIF)

```bash
cd miscada-project-master
yarn install
yarn start
```

Frontend at **http://localhost:3000**

### 6. Load DICOM Data

Upload DICOM files to Orthanc (port 8042), then open the OHIF viewer. The platform auto-detects the study and triggers segmentation on first view.

---

## API Endpoints (port 8004)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/segment_3d` | Full 117-organ segmentation → 3D meshes |
| `POST` | `/segment_by_name` | Query-specific organ (e.g. `"liver"`, `"left lung"`) |
| `POST` | `/segment_file` | Segment a NIfTI file directly |
| `POST` | `/segment_lesion` | Box-guided lesion detection (liver/lung/kidney) |
| `POST` | `/analyze_lesions` | LLM analysis: which organs likely contain lesions |
| `POST` | `/generate_report` | Full diagnostic report generation |
| `GET` | `/health` | Health check |

---

## Key Results

| Metric | Value | Context |
|--------|-------|---------|
| **Segmentation Time** | 1.3–5.8 min | 5 Orthanc cases, 400-slice limit |
| **Kidney Dice** | 0.76 ± 0.14 | 5 KiTS19 NIfTI volumes, provenance-matched GT |
| **Coordinate Alignment** | 0.00 mm origin delta | TS mesh vs DICOM world coords |
| **Organ Classes** | 117 | TotalSegmentator v2 via Docker |
| **Lesion Types** | 3 | Liver lesions, lung nodules, kidney cysts |

Full experimental data: [`result/experiment_results/`](result/experiment_results/)

---

## Project Structure

```
├── totalseg_service.py      # Main backend (FastAPI, port 8004)
├── service/                 # Deployed service copy
├── test/                    # Experiment & evaluation scripts
├── figures/                 # Thesis figure generation
├── result/                  # Experimental results (JSON, CSV, NPY)
├── data/                    # Dataset utilities
├── legacy/                  # Deprecated debug scripts
├── miscada-project-master/  # OHIF vtk.js frontend
├── MedSAM2/                 # MedSAM2 inference + report agent
├── MedSAM-LiteMedSAM/       # LiteMedSAM models
├── MedSAM-main/             # MedSAM v1
└── demo.mp4                 # Demo video
```

---

## Citation

If you use this work, please cite:

```bibtex
@mastersthesis{miscada2025,
  title  = {Computer-Aided CT Analysis Platform with Multi-Agent Diagnostic Report Generation},
  author = {Your Name},
  school = {Your University},
  year   = {2025}
}
```

## License

MIT
