import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export type MeshData = {
  vertices: number[][];
  faces: number[][];
  dims: number[];
  origin?: number[];
  spacing?: number[];
} | {
  vertices: number[][];
  dims: number[];
  origin?: number[];
  spacing?: number[];
} | null;

type Props = {
  mesh: MeshData;
  volumeMm3?: number | null;
  slicesWritten?: number;
  onClose: () => void;
};

const Segmentation3DMeshModal: React.FC<Props> = ({ mesh, volumeMm3, slicesWritten, onClose }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mesh || !canvasRef.current || !containerRef.current) return;
    const canvas = canvasRef.current;
    const container = containerRef.current;
    let animFrameId = 0;
    let renderer: THREE.WebGLRenderer | null = null;
    let ro: ResizeObserver | null = null;

    try {
      const rect = container.getBoundingClientRect();
      const W = rect.width || 600;
      const H = rect.height || 500;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x1a1a2e);

      const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 10000);
      camera.position.set(300, 200, 400);
      camera.lookAt(0, 0, 0);

      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, premultipliedAlpha: false });
      renderer.setSize(W, H);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

      scene.add(new THREE.AmbientLight(0x404060, 2.5));
      const sun = new THREE.DirectionalLight(0xffffff, 3); sun.position.set(1, 1, 1); scene.add(sun);
      const fill = new THREE.DirectionalLight(0x88aaff, 1.5); fill.position.set(-1, -0.5, -0.5); scene.add(fill);
      scene.add(new THREE.GridHelper(500, 20, 0x333355, 0x222244));

      const verts = mesh.vertices;
      let cx = 0, cy = 0, cz = 0;
      if (verts.length > 0) {
        let sx = 0, sy = 0, sz = 0;
        for (const v of verts) { sx += v[0]; sy += v[1]; sz += v[2]; }
        cx = sx / verts.length; cy = sy / verts.length; cz = sz / verts.length;
      }

      if ('faces' in mesh && mesh.faces && mesh.faces.length > 0) {
        const positions: number[] = [];
        for (const v of verts) positions.push(v[0]-cx, v[1]-cy, v[2]-cz);
        const indices: number[] = [];
        for (const f of mesh.faces) if (f.length >= 3) indices.push(f[0], f[1], f[2]);
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geo.setIndex(indices);
        geo.computeVertexNormals();
        scene.add(new THREE.Mesh(geo, new THREE.MeshPhongMaterial({
          color: 0x22c55e, specular: 0x44ff88, shininess: 40,
          transparent: true, opacity: 0.70, side: THREE.DoubleSide,
        })));
        scene.add(new THREE.LineSegments(
          new THREE.WireframeGeometry(geo),
          new THREE.LineBasicMaterial({ color: 0x16a34a, transparent: true, opacity: 0.25 })
        ));
      } else {
        const positions: number[] = [], colors: number[] = [];
        for (const v of verts) { positions.push(v[0]-cx, v[1]-cy, v[2]-cz); colors.push(0.13, 0.77, 0.37); }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
        scene.add(new THREE.Points(geo, new THREE.PointsMaterial({ size: 2.5, vertexColors: true })));
      }

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true; controls.dampingFactor = 0.08; controls.target.set(0, 0, 0); controls.update();

      const animate = () => { animFrameId = requestAnimationFrame(animate); controls.update(); renderer!.render(scene, camera); };
      animate();

      ro = new ResizeObserver(() => {
        const r = container.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) { renderer!.setSize(r.width, r.height); camera.aspect = r.width / r.height; camera.updateProjectionMatrix(); }
      });
      ro.observe(container);
      setLoading(false);
    } catch (e: any) {
      console.error('[3D Mesh] Init error:', e);
      setError(e?.message ?? 'Failed to initialize 3D viewer');
      setLoading(false);
    }
    return () => { cancelAnimationFrame(animFrameId); ro?.disconnect(); renderer?.dispose(); };
  }, [mesh]);

  const fmtVol = (v?: number | null) => v == null ? 'N/A' : v >= 1000 ? (v/1000).toFixed(2) + ' cm3' : v.toFixed(1) + ' mm3';

  return (
    <div ref={containerRef} style={{ width:'100%', height:'520px', position:'relative', borderRadius:8, overflow:'hidden', background:'#1a1a2e', display:'flex', flexDirection:'column' }}>
      <div style={{ position:'absolute', top:0, left:0, right:0, zIndex:10, padding:'8px 14px', background:'linear-gradient(180deg,rgba(0,0,0,.7) 0%,transparent 100%)', color:'#e5e7eb', fontSize:12, display:'flex', justifyContent:'space-between', alignItems:'center', pointerEvents:'none' }}>
        <span>3D Segmentation {slicesWritten != null ? ' / ' + slicesWritten + ' slices' : ''}{volumeMm3 != null ? ' / ' + fmtVol(volumeMm3) : ''}</span>
        <span style={{ color:'#9ca3af', fontSize:11 }}>drag . scroll zoom</span>
      </div>
      <button onClick={onClose} style={{ position:'absolute', top:8, right:8, zIndex:11, background:'rgba(0,0,0,.5)', color:'#fff', border:'1px solid rgba(255,255,255,.2)', borderRadius:4, padding:'4px 10px', cursor:'pointer', fontSize:14 }}>X</button>
      {loading && <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', color:'#9ca3af', zIndex:5 }}>Loading 3D viewer...</div>}
      {error && <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', color:'#ef4444', zIndex:5, padding:20, textAlign:'center' }}>{error}</div>}
      <canvas ref={canvasRef} style={{ flex:1, width:'100%', height:'100%', display:'block' }} />
    </div>
  );
};

export default Segmentation3DMeshModal;
