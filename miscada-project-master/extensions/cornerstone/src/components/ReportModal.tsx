import React, { useRef, useState, useCallback } from 'react';
import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';

type ReportData = {
  report: string;
  metrics: {
    volume_cm3: number;
    volume_mm3: number;
    max_slice_area_cm2: number;
    max_slice_area_mm2: number;
    slices_with_lesion: number;
    total_slices_in_series: number;
    physical_size_mm: [number, number];
    pixel_bbox: [number, number, number, number];
    organ_hint: string;
    sphericity: number;
    mean_intensity_hu: number | null;
    pixel_spacing: [number, number];
    slice_thickness: number;
  };
  evaluation: {
    all_pass: boolean;
    checks: Array<{ id: string; pass: boolean; msg: string }>;
  };
  segImageBase64?: string;
  screenshot3DBase64?: string;
};

type Props = {
  reportData: ReportData;
  isLoading: boolean;
  error: string | null;
  onClose: () => void;
};

const ReportModal: React.FC<Props> = ({
  reportData,
  isLoading,
  error,
  onClose,
}) => {
  const [annotations, setAnnotations] = useState('');
  const [pdfGenerating, setPdfGenerating] = useState(false);
  const printableRef = useRef<HTMLDivElement>(null);

  const handleDownloadPDF = useCallback(async () => {
    if (!reportData) return;
    setPdfGenerating(true);
    try {
      const { report, metrics, evaluation } = reportData;
      const pdf = new jsPDF('p', 'mm', 'a4');
      const margin = 20;
      const pageW = 210;
      const pageH = 297;
      let y = margin;
      const maxW = pageW - margin * 2;

      // helper: add text and handle page breaks
      const addText = (text: string, size: number, bold: boolean, color: [number,number,number] = [0,0,0], indent = 0) => {
        pdf.setFontSize(size);
        pdf.setFont('helvetica', bold ? 'bold' : 'normal');
        pdf.setTextColor(...color);
        const lines = pdf.splitTextToSize(text, maxW - indent);
        const lineH = size * 0.4;
        for (const line of lines) {
          if (y + lineH > pageH - margin) { pdf.addPage(); y = margin; }
          pdf.text(line, margin + indent, y);
          y += lineH;
        }
        y += 2; // spacing after paragraph
      };

      // ── Title ──
      pdf.setFontSize(18);
      pdf.setFont('helvetica', 'bold');
      pdf.setTextColor(30, 64, 175);
      pdf.text('AI-Assisted Radiology Report', margin, y);
      y += 8;
      pdf.setFontSize(9);
      pdf.setFont('helvetica', 'normal');
      pdf.setTextColor(100, 100, 100);
      pdf.text(`Generated: ${new Date().toLocaleString()}  |  Groq Llama 3.3 70B`, margin, y);
      y += 4;
      pdf.setDrawColor(30, 64, 175);
      pdf.line(margin, y, pageW - margin, y);
      y += 8;

      // ── Metrics ──
      pdf.setFontSize(10);
      pdf.setFont('helvetica', 'bold');
      pdf.setTextColor(50, 50, 50);
      pdf.text('QUANTITATIVE METRICS', margin, y);
      y += 5;
      pdf.setFontSize(9);
      pdf.setFont('helvetica', 'normal');
      pdf.setTextColor(60, 60, 60);
      const metricLines = [
        `Volume: ${metrics.volume_cm3?.toFixed(2)} cm³  |  Max Area: ${metrics.max_slice_area_cm2?.toFixed(1)} cm²`,
        `Slices: ${metrics.slices_with_lesion}/${metrics.total_slices_in_series}  |  Sphericity: ${metrics.sphericity?.toFixed(2)}  |  Organ: ${metrics.organ_hint || 'N/A'}`,
        `Dimensions: ${metrics.physical_size_mm?.[0]?.toFixed(1) ?? '?'} x ${metrics.physical_size_mm?.[1]?.toFixed(1) ?? '?'} mm  |  HU: ${metrics.mean_intensity_hu != null ? metrics.mean_intensity_hu.toFixed(0) : 'N/A'}`,
      ];
      for (const ml of metricLines) {
        pdf.text(ml, margin, y);
        y += 5;
      }
      y += 4;

      // ── Screenshots (side by side) ──
      const imgH_mm = 50;
      const imgW_mm = maxW / 2 - 3;
      const addImageBlock = async (label: string, base64: string | undefined, x: number) => {
        pdf.setFontSize(8);
        pdf.setFont('helvetica', 'bold');
        pdf.setTextColor(80, 80, 80);
        pdf.text(label, x, y);
        y += 3.5;
        if (base64 && base64.length > 100) {
          try {
            pdf.addImage(base64, 'PNG', x, y, imgW_mm, imgH_mm);
          } catch(e) { /* skip broken image */ }
        }
        y += imgH_mm + 1;
      };

      // Check if we need a page break for images
      if (y + imgH_mm + 14 > pageH - margin) { pdf.addPage(); y = margin; }

      const imgY = y;
      await addImageBlock('2D Segmentation (Key Slice)', reportData.segImageBase64, margin);
      const rightX = margin + imgW_mm + 6;
      y = imgY;
      await addImageBlock('3D Volume Rendering', reportData.screenshot3DBase64, rightX);
      y = Math.max(y, imgY + imgH_mm + 3);
      y += 4;

      // ── Evaluation ──
      if (y + 30 > pageH - margin) { pdf.addPage(); y = margin; }
      pdf.setFontSize(9);
      pdf.setFont('helvetica', 'bold');
      pdf.setTextColor(evaluation?.all_pass ? 22 : 133, evaluation?.all_pass ? 101 : 77, evaluation?.all_pass ? 52 : 14);
      pdf.text(evaluation?.all_pass ? 'Validation: All checks passed' : 'Validation: Some checks flagged', margin, y);
      y += 5;
      pdf.setFontSize(8);
      pdf.setFont('helvetica', 'normal');
      pdf.setTextColor(80, 80, 80);
      for (const c of (evaluation?.checks || [])) {
        pdf.text((c.pass ? '[OK] ' : '[!]  ') + c.msg, margin, y);
        y += 4;
      }
      y += 4;

      // ── Report sections ──
      const sections = report ? report.split(/^##\s+/m).filter(Boolean) : [];
      for (const section of sections) {
        const titleMatch = section.match(/^(\w+)/);
        const title = titleMatch ? titleMatch[1] : '';
        const body = section.replace(/^\w+\s*\n?/, '').trim();

        if (y + 20 > pageH - margin) { pdf.addPage(); y = margin; }
        pdf.setFontSize(12);
        pdf.setFont('helvetica', 'bold');
        pdf.setTextColor(30, 64, 175);
        pdf.text(title, margin, y);
        y += 6;

        // clean markdown
        const cleanBody = body
          .replace(/\*\*(.*?)\*\*/g, '$1')
          .replace(/^[-*]\s/gm, '  • ')
          .replace(/^\d+\.\s/gm, '  $&');
        addText(cleanBody, 9, false, [50, 50, 50], 2);
      }

      // ── Doctor Annotations ──
      if (annotations.trim()) {
        if (y + 20 > pageH - margin) { pdf.addPage(); y = margin; }
        pdf.setDrawColor(180, 180, 180);
        pdf.line(margin, y, pageW - margin, y);
        y += 6;
        pdf.setFontSize(11);
        pdf.setFont('helvetica', 'bold');
        pdf.setTextColor(60, 60, 60);
        pdf.text('Doctor Annotations', margin, y);
        y += 5;
        addText(annotations, 9, false, [80, 80, 80], 2);
      }

      pdf.save(`Radiology_Report_${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (e) {
      console.error('PDF failed:', e);
      alert('PDF generation failed. Try using browser Print (Ctrl+P).');
    } finally {
      setPdfGenerating(false);
    }
  }, [reportData, annotations]);

  if (isLoading) {
    return (
      <div className="min-w-[500px] min-h-[300px] flex items-center justify-center bg-gray-900 text-white p-8 rounded-lg">
        <div className="text-center">
          <div className="animate-spin text-4xl mb-4">⚕️</div>
          <p className="text-lg">Generating AI Radiology Report...</p>
          <p className="text-sm text-gray-400 mt-2">Consulting Groq Llama 3.3 70B</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-w-[400px] p-8 bg-gray-900 text-white rounded-lg">
        <p className="text-red-400 text-lg mb-2">Report Generation Failed</p>
        <p className="text-gray-400 text-sm mb-4">{error}</p>
        <button onClick={onClose} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm transition">Close</button>
      </div>
    );
  }

  if (!reportData) return null;

  const { report, metrics, evaluation } = reportData;
  const sections = report
    ? report.split(/^##\s+/m).filter(Boolean)
    : [];

  return (
    <div className="min-w-[680px] max-h-[80vh] overflow-hidden bg-gray-900 text-white rounded-lg flex flex-col" id="radiology-report-wrapper">
      {/* ── Header (no-print) ── */}
      <div className="no-print sticky top-0 bg-gradient-to-r from-blue-800 to-blue-950 p-4 flex justify-between items-center z-10 rounded-t-lg">
        <div>
          <h1 className="text-xl font-bold tracking-wide">AI-Assisted Radiology Report</h1>
          <p className="text-blue-200 text-xs mt-1">
            {new Date().toLocaleString()} · Groq Llama 3.3 70B
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={handleDownloadPDF} disabled={pdfGenerating}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-sm rounded transition disabled:opacity-50">
            {pdfGenerating ? '...' : '📥 PDF'}
          </button>
          <button onClick={() => onClose()}
            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-sm rounded transition">
            ✕ Close
          </button>
        </div>
      </div>

      {/* ── Printable content ── */}
      <div ref={printableRef} className="overflow-y-auto flex-1 bg-white text-gray-900" style={{ padding: '24px 28px' }}>
        {/* Title for PDF */}
        <div className="mb-4 pb-3 border-b-2 border-blue-600">
          <h2 className="text-xl font-bold text-blue-900">AI-Assisted Radiology Report</h2>
          <p className="text-xs text-gray-500 mt-1">{new Date().toLocaleString()} · Groq Llama 3.3 70B</p>
        </div>

        {/* ── Quick Metrics Bar ── */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          <MetricCard label="Volume" value={`${metrics.volume_cm3?.toFixed(2)} cm³`} />
          <MetricCard label="Max Area" value={`${metrics.max_slice_area_cm2?.toFixed(1)} cm²`} />
          <MetricCard label="Slices" value={`${metrics.slices_with_lesion}/${metrics.total_slices_in_series}`} />
          <MetricCard label="Sphericity" value={`${metrics.sphericity?.toFixed(2)}`} />
          <MetricCard label="Organ" value={metrics.organ_hint || 'N/A'} />
        </div>

        {/* ── Images ── */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
          <div style={{ flex: 1, border: '1px solid #e5e7eb', borderRadius: 6, padding: 6 }}>
            <p style={{ fontSize: 11, color: '#6b7280', marginBottom: 4, fontWeight: 600 }}>2D Segmentation (Key Slice)</p>
            {reportData.segImageBase64 ? (
              <img src={reportData.segImageBase64} alt="2D" style={{ width: '100%', borderRadius: 4, maxHeight: 200, objectFit: 'contain' }} />
            ) : (
              <div style={{ background: '#f9fafb', height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af', fontSize: 13 }}>
                No 2D capture — use 📸 before 3D tracking
              </div>
            )}
          </div>
          <div style={{ flex: 1, border: '1px solid #e5e7eb', borderRadius: 6, padding: 6 }}>
            <p style={{ fontSize: 11, color: '#6b7280', marginBottom: 4, fontWeight: 600 }}>3D Volume Rendering</p>
            {reportData.screenshot3DBase64 ? (
              <img src={reportData.screenshot3DBase64} alt="3D" style={{ width: '100%', borderRadius: 4, maxHeight: 200, objectFit: 'contain' }} />
            ) : (
              <div style={{ background: '#f9fafb', height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af', fontSize: 13 }}>
                No 3D capture — use 📸 in floating bar
              </div>
            )}
          </div>
        </div>

        {/* ── Evaluation Badge ── */}
        <div style={{
          padding: '8px 12px', borderRadius: 6, marginBottom: 14, fontSize: 13,
          background: evaluation?.all_pass ? '#f0fdf4' : '#fefce8',
          border: evaluation?.all_pass ? '1px solid #bbf7d0' : '1px solid #fde68a',
        }}>
          <span style={{ fontWeight: 600 }}>
            {evaluation?.all_pass ? 'All validations passed' : 'Some validations flagged'}
          </span>
          <div style={{ marginTop: 4 }}>
            {evaluation?.checks?.map((c) => (
              <div key={c.id} style={{ fontSize: 12, color: '#4b5563', display: 'flex', alignItems: 'center', gap: 4 }}>
                <span>{c.pass ? '✓' : '!'}</span>
                <span>{c.msg}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Report Text ── */}
        {sections.map((section, idx) => {
          const titleMatch = section.match(/^(\w+)/);
          const title = titleMatch ? titleMatch[1] : '';
          const body = section.replace(/^\w+\s*\n?/, '').trim();
          return (
            <div key={idx} style={{ borderLeft: '4px solid #3b82f6', paddingLeft: 14, marginBottom: 14 }}>
              <h3 style={{ fontWeight: 700, color: '#1e3a5f', fontSize: 14, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
                {title}
              </h3>
              <div
                style={{ fontSize: 13, lineHeight: 1.7, color: '#374151', whiteSpace: 'pre-line' }}
                dangerouslySetInnerHTML={{
                  __html: body
                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                    .replace(/^[-*]\s/gm, '• ')
                    .replace(/(\d+\.\s)/g, '<br/>$1'),
                }}
              />
            </div>
          );
        })}

        {/* ── Doctor Annotations ── */}
        <div style={{ borderTop: '2px solid #d1d5db', paddingTop: 14, marginTop: 8 }}>
          <h3 style={{ fontWeight: 700, color: '#1f2937', fontSize: 14, marginBottom: 6 }}>
            Doctor Annotations
          </h3>
          <textarea
            className="no-print"
            style={{
              width: '100%', height: 80, maxHeight: 120, padding: 10, border: '1px solid #d1d5db', borderRadius: 6,
              fontSize: 13, resize: 'none', outline: 'none', overflow: 'auto',
            }}
            placeholder="Enter your clinical notes, corrections, or recommendations here..."
            value={annotations}
            onChange={(e) => setAnnotations(e.target.value)}
          />
        </div>

        {/* ── Footer (no-print) ── */}
        <div className="no-print" style={{ borderTop: '1px solid #e5e7eb', paddingTop: 14, marginTop: 14, textAlign: 'right' }}>
          <button onClick={handleDownloadPDF} disabled={pdfGenerating}
            style={{
              padding: '10px 24px', background: '#1d4ed8', color: '#fff', borderRadius: 6,
              fontSize: 14, fontWeight: 500, border: 'none', cursor: 'pointer', opacity: pdfGenerating ? 0.5 : 1,
            }}>
            {pdfGenerating ? 'Generating PDF...' : 'Download PDF Report'}
          </button>
        </div>
      </div>
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ flex: 1, background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, padding: '8px 10px', textAlign: 'center' }}>
    <p style={{ fontSize: 11, color: '#6b7280', textTransform: 'uppercase', letterSpacing: 0.5, margin: 0 }}>{label}</p>
    <p style={{ fontSize: 16, fontWeight: 700, color: '#1f2937', margin: '2px 0 0 0' }}>{value}</p>
  </div>
);

export default ReportModal;
