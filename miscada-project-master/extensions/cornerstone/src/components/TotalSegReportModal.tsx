import React, { useRef, useState, useCallback } from 'react';
import jsPDF from 'jspdf';

export type TotalSegReportData = {
  report: string;
  organs: Array<{ name: string; volume_cm3: number }>;
  lesions: Array<{ name: string; volume_cm3: number }>;
  patientInfo: {
    age: number;
    gender: string;
    chiefComplaint: string;
    clinicalQuestion: string;
    medicalHistory: string;
  };
  screenshot3DBase64: string;
};

type Props = {
  reportData: TotalSegReportData;
  isLoading: boolean;
  error: string | null;
  onClose: () => void;
};

const MiniStat: React.FC<{ label: string; value: string; color?: string }> = ({ label, value, color }) => (
  <div style={{
    flex: 1, background: '#f8fafc', border: '1px solid #e2e8f0',
    borderRadius: 6, padding: '8px 10px', textAlign: 'center', minWidth: 70,
  }}>
    <div style={{ fontSize: 9, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 }}>{label}</div>
    <div style={{ fontSize: 13, fontWeight: 700, color: color || '#1e293b' }}>{value}</div>
  </div>
);

const TotalSegReportModal: React.FC<Props> = ({ reportData, isLoading, error, onClose }) => {
  const [annotations, setAnnotations] = useState('');
  const [pdfGenerating, setPdfGenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleDownloadPDF = useCallback(async () => {
    if (!reportData) return;
    setPdfGenerating(true);
    try {
      const { report, organs, lesions, patientInfo, screenshot3DBase64 } = reportData;
      const pdf = new jsPDF('p', 'mm', 'a4');
      const m = 18; const pw = 210; const ph = 297; let y = m; const mw = pw - m * 2;

      const addText = (text: string, size: number, bold: boolean, color: [number,number,number] = [0,0,0], indent = 0) => {
        pdf.setFontSize(size);
        pdf.setFont('helvetica', bold ? 'bold' : 'normal');
        pdf.setTextColor(...color);
        const lines = pdf.splitTextToSize(text, mw - indent);
        const lh = size * 0.52;
        for (const line of lines) {
          if (y + lh > ph - m) { pdf.addPage(); y = m; }
          pdf.text(line, m + indent, y); y += lh;
        }
        y += 1;
      };

      pdf.setFontSize(18);
      pdf.setFont('helvetica', 'bold');
      pdf.setTextColor(13, 148, 136);
      pdf.text('Radiology Report', m, y); y += 7;
      pdf.setFontSize(8);
      pdf.setFont('helvetica', 'normal');
      pdf.setTextColor(148, 163, 184);
      pdf.text(`Generated: ${new Date().toLocaleString()} | AI-Assisted (Groq Llama 3.3)`, m, y); y += 2;
      pdf.setDrawColor(13, 148, 136);
      pdf.line(m, y, pw - m, y); y += 6;

      pdf.setFontSize(10);
      pdf.setFont('helvetica', 'bold');
      pdf.setTextColor(51, 65, 85);
      pdf.text('PATIENT INFORMATION', m, y); y += 4;
      pdf.setFontSize(8);
      pdf.setFont('helvetica', 'normal');
      pdf.setTextColor(71, 85, 105);
      pdf.text(`Age: ${patientInfo.age || 'N/A'}  |  Gender: ${patientInfo.gender || 'N/A'}  |  Complaint: ${patientInfo.chiefComplaint || 'N/A'}`, m, y); y += 3.5;
      if (patientInfo.medicalHistory) { pdf.text(`History: ${patientInfo.medicalHistory}`, m, y); y += 3.5; }
      y += 3;

      if (organs.length + lesions.length > 0) {
        pdf.setFontSize(9); pdf.setFont('helvetica', 'bold'); pdf.setTextColor(51, 65, 85);
        pdf.text('SEGMENTATION SUMMARY', m, y); y += 4;
        pdf.setFontSize(7); pdf.setFont('helvetica', 'normal');
        for (const o of organs) {
          pdf.text(`  ${o.name}: ${(o.volume_cm3||0).toFixed(1)} cm3`, m, y); y += 3;
          if (y > ph - m) { pdf.addPage(); y = m; }
        }
        for (const l of lesions) {
          pdf.setTextColor(185, 28, 28);
          pdf.text(`  [LESION] ${l.name}: ${(l.volume_cm3||0).toFixed(1)} cm3`, m, y); y += 3;
          pdf.setTextColor(71, 85, 105);
          if (y > ph - m) { pdf.addPage(); y = m; }
        }
        y += 2;
      }

      if (screenshot3DBase64 && screenshot3DBase64.length > 100) {
        if (y + 45 > ph - m) { pdf.addPage(); y = m; }
        pdf.setFontSize(8); pdf.setFont('helvetica', 'bold'); pdf.setTextColor(71, 85, 105);
        pdf.text('3D VOLUME RENDERING', m, y); y += 3.5;
        try { pdf.addImage(screenshot3DBase64, 'PNG', m, y, mw * 0.6, 40); y += 42; } catch(e) {}
        y += 2;
      }

      const rawSections = report ? report.split(/^##\s*/m).filter(Boolean) : [];
      for (const section of rawSections) {
        const firstLine = section.split('\n')[0];
        const titleEnd = firstLine.search(/[.:\n]/);
        const title = titleEnd > 0 ? firstLine.slice(0, titleEnd).trim() : firstLine.slice(0, 40).trim();
        const body = titleEnd > 0 ? section.slice(section.indexOf(firstLine) + titleEnd + 1).trim() : section.slice(firstLine.length).trim();
        if (y + 18 > ph - m) { pdf.addPage(); y = m; }
        pdf.setFontSize(11); pdf.setFont('helvetica', 'bold'); pdf.setTextColor(13, 148, 136);
        pdf.text(title, m, y); y += 5;
        const clean = body.replace(/\*\*(.*?)\*\*/g, '$1').replace(/^[-*\u2022]\s/gm, '  - ').replace(/^\d+\.\s/gm, '  $&');
        addText(clean, 8, false, [51, 65, 85], 1);
      }

      if (annotations.trim()) {
        if (y + 12 > ph - m) { pdf.addPage(); y = m; }
        pdf.setDrawColor(203, 213, 225); pdf.line(m, y, pw - m, y); y += 4;
        pdf.setFontSize(10); pdf.setFont('helvetica', 'bold'); pdf.setTextColor(51, 65, 85);
        pdf.text('DOCTOR ANNOTATIONS', m, y); y += 4;
        addText(annotations, 8, false, [71, 85, 105], 1);
      }

      pdf.save(`Radiology_Report_${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (e) {
      console.error('PDF failed:', e);
      alert('PDF generation failed. Try Print (Ctrl+P).');
    } finally {
      setPdfGenerating(false);
    }
  }, [reportData, annotations]);

  const handleCopy = () => {
    if (!reportData?.report) return;
    navigator.clipboard.writeText(reportData.report).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    }).catch(() => alert('Copy failed'));
  };

  if (isLoading) {
    return (
      <div style={{ background:'#0f172a', borderRadius:14, padding:40, minWidth:360, textAlign:'center', color:'#f1f5f9', boxShadow:'0 20px 50px rgba(0,0,0,0.35)' }}>
        <div style={{ fontSize:36, marginBottom:10 }}>{'\u2695\uFE0F'}</div>
        <div style={{ fontSize:15, fontWeight:600, marginBottom:4 }}>Generating Radiology Report</div>
        <div style={{ fontSize:11, color:'#94a3b8' }}>Analyzing organ volumes &amp; clinical context</div>
        <div style={{ fontSize:10, color:'#64748b', marginTop:4 }}>Groq Llama 3.3 70B</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ background:'#fff', borderRadius:14, padding:32, minWidth:360, border:'1px solid #fecaca', boxShadow:'0 20px 50px rgba(0,0,0,0.15)' }}>
        <div style={{ color:'#dc2626', fontSize:15, fontWeight:600, marginBottom:6 }}>Report Generation Failed</div>
        <div style={{ color:'#64748b', fontSize:12, marginBottom:14, lineHeight:1.5 }}>{error}</div>
        <button onClick={onClose} style={{ padding:'7px 18px', background:'#0d9488', color:'#fff', border:'none', borderRadius:6, fontSize:12, cursor:'pointer' }}>Close</button>
      </div>
    );
  }

  if (!reportData) return null;

  const { report, organs, lesions, patientInfo, screenshot3DBase64 } = reportData;
  const rawSections = report ? report.split(/^##\s*/m).filter(Boolean) : [];
  const sections = rawSections.map((sec: string) => {
    const firstLine = sec.split('\n')[0];
    const titleEnd = firstLine.search(/[.:\n]/);
    const title = titleEnd > 0 ? firstLine.slice(0, titleEnd).trim() : firstLine.slice(0, 40).trim();
    const body = titleEnd > 0 ? sec.slice(sec.indexOf(firstLine) + titleEnd + 1).trim() : sec.slice(firstLine.length).trim();
    return { title, body };
  });
  const totalOrgans = organs.length;
  const totalLesions = lesions.length;

  return (
    <div style={{
      width: 760, maxWidth: '94vw', maxHeight: '90vh',
      background: '#fff', borderRadius: 12, overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      {/* Header */}
      <div style={{
        background: '#0f172a', padding: '12px 18px',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0,
      }}>
        <div>
          <div style={{ color: '#f1f5f9', fontSize: 16, fontWeight: 700 }}>Radiology Report</div>
          <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 1 }}>
            {new Date().toLocaleString()} &middot; {patientInfo.age ? `${patientInfo.age}y ${patientInfo.gender}` : 'No patient info'} &middot; AI-Assisted
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={handleCopy}
            style={{ padding:'5px 10px', background: copied ? '#059669' : '#334155', color:'#fff', border:'none', borderRadius:5, fontSize:11, fontWeight:500, cursor:'pointer' }}>
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button onClick={handleDownloadPDF} disabled={pdfGenerating}
            style={{ padding:'5px 10px', background:'#0d9488', color:'#fff', border:'none', borderRadius:5, fontSize:11, fontWeight:500, cursor:'pointer', opacity: pdfGenerating ? 0.6 : 1 }}>
            {pdfGenerating ? '...' : 'Download PDF'}
          </button>
          <button onClick={onClose}
            style={{ background:'none', border:'none', color:'#94a3b8', fontSize:18, cursor:'pointer', padding:'0 4px', lineHeight:1 }}>
            &times;
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ overflowY: 'auto', flex: 1, padding: '14px 20px' }}>
        {/* Patient info bar */}
        <div style={{
          background: '#f8fafc', borderRadius: 6, padding: '8px 12px',
          marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 12,
          fontSize: 11, color: '#475569', border: '1px solid #e2e8f0',
        }}>
          {patientInfo.age > 0 && <span><strong>Age:</strong> {patientInfo.age}</span>}
          {patientInfo.gender && <span><strong>Gender:</strong> {patientInfo.gender}</span>}
          {patientInfo.chiefComplaint && <span><strong>Complaint:</strong> {patientInfo.chiefComplaint}</span>}
          {patientInfo.clinicalQuestion && <span><strong>Question:</strong> {patientInfo.clinicalQuestion}</span>}
          {patientInfo.medicalHistory && <span><strong>PMH:</strong> {patientInfo.medicalHistory}</span>}
        </div>

        {/* Stats */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
          <MiniStat label="Organs" value={String(totalOrgans)} color="#0d9488" />
          <MiniStat label="Organ Volume" value={organs.length > 0 ? `${organs.reduce((s,o)=>s+(o.volume_cm3||0),0).toFixed(0)} cm3` : 'N/A'} />
          <MiniStat label="Lesions" value={String(totalLesions)} color={totalLesions > 0 ? '#dc2626' : '#0d9488'} />
          <MiniStat label="Lesion Volume" value={lesions.length > 0 ? `${lesions.reduce((s,l)=>s+(l.volume_cm3||0),0).toFixed(1)} cm3` : 'None'} color={totalLesions > 0 ? '#dc2626' : undefined} />
        </div>

        {/* Organ/Lesion tables */}
        {(organs.length > 0 || lesions.length > 0) && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 10, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Segmentation Results
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {organs.length > 0 && (
                <div style={{ flex: 1, background: '#f8fafc', borderRadius: 6, border: '1px solid #e2e8f0', padding: '4px 8px', maxHeight: 140, overflowY: 'auto' }}>
                  <div style={{ fontSize: 9, color: '#94a3b8', marginBottom: 3, fontWeight: 600 }}>ORGANS</div>
                  {organs.slice(0, 12).map((o, i) => (
                    <div key={i} style={{ fontSize: 10, display: 'flex', justifyContent: 'space-between', padding: '1px 0', color: '#1e293b' }}>
                      <span>{o.name}</span>
                      <span style={{ color: '#94a3b8', fontFamily: 'monospace' }}>{(o.volume_cm3||0).toFixed(1)} cm3</span>
                    </div>
                  ))}
                  {organs.length > 12 && <div style={{ fontSize:9, color:'#94a3b8' }}>+{organs.length - 12} more</div>}
                </div>
              )}
              {lesions.length > 0 && (
                <div style={{ flex: 1, background: '#fef2f2', borderRadius: 6, border: '1px solid #fecaca', padding: '4px 8px', maxHeight: 140, overflowY: 'auto' }}>
                  <div style={{ fontSize: 9, color: '#dc2626', marginBottom: 3, fontWeight: 600 }}>LESIONS</div>
                  {lesions.map((l, i) => (
                    <div key={i} style={{ fontSize: 10, display: 'flex', justifyContent: 'space-between', padding: '1px 0' }}>
                      <span style={{ color: '#991b1b' }}>{l.name}</span>
                      <span style={{ color: '#b91c1c', fontFamily: 'monospace' }}>{(l.volume_cm3||0).toFixed(1)} cm3</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 3D Screenshot */}
        {screenshot3DBase64 && screenshot3DBase64.length > 100 && (
          <div style={{ marginBottom: 12, borderRadius: 6, overflow: 'hidden', border: '1px solid #e2e8f0' }}>
            <div style={{ fontSize: 9, color: '#64748b', padding: '4px 10px', background: '#f8fafc', fontWeight: 600, borderBottom: '1px solid #e2e8f0' }}>
              3D Volume Rendering
            </div>
            <div style={{ background: '#0f172a', padding: 0 }}>
              <img src={screenshot3DBase64} alt="3D" style={{ width: '100%', maxHeight: 220, objectFit: 'contain', display: 'block' }} />
            </div>
          </div>
        )}

        {/* Report sections */}
        {sections.map(({ title, body }, idx) => {
          const colors: Record<string, string> = {
            'CLINICAL HISTORY': '#6366f1',
            'FINDINGS': '#0d9488',
            'IMPRESSION': '#7c3aed',
            'RECOMMENDATIONS': '#059669',
          };
          return (
            <div key={idx} style={{
              borderLeft: `3px solid ${colors[title] || '#0d9488'}`,
              paddingLeft: 12, marginBottom: 10,
            }}>
              <div style={{
                fontWeight: 700, fontSize: 13, color: '#1e293b',
                textTransform: 'uppercase', letterSpacing: 0.3, marginBottom: 3,
              }}>
                {title}
              </div>
              <div
                style={{ fontSize: 12, lineHeight: 1.65, color: '#475569' }}
                dangerouslySetInnerHTML={{
                  __html: body
                    .replace(/\*\*(.*?)\*\*/g, '<strong style="color:#1e293b">$1</strong>')
                    .replace(/^[-*\u2022]\s/gm, '<span style="color:#0d9488">&bull;</span> ')
                    .replace(/(\d+\.)\s/g, '<br/><strong>$1</strong> '),
                }}
              />
            </div>
          );
        })}

        {/* Doctor annotations */}
        <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 10, marginTop: 6 }}>
          <div style={{ fontWeight: 600, fontSize: 12, color: '#475569', marginBottom: 4 }}>
            Doctor Annotations
          </div>
          <textarea
            style={{
              width: '100%', minHeight: 60, padding: 8,
              border: '1px solid #e2e8f0', borderRadius: 6,
              fontSize: 11, resize: 'vertical', outline: 'none',
              color: '#1e293b', background: '#fafafa', fontFamily: 'inherit',
              boxSizing: 'border-box',
            }}
            placeholder="Add clinical notes, corrections, or recommendations..."
            value={annotations}
            onChange={e => setAnnotations(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
};

export default TotalSegReportModal;

