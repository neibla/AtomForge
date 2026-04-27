"use client";

import React, { useMemo, useRef, useEffect } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, PerspectiveCamera, Stars } from "@react-three/drei";
import * as THREE from "three";
import { cn } from "@/lib/utils";

interface AtomData {
  positions: number[][];       
  numbers: number[];          
  initial_positions?: number[][];
  energies?: number[];        
  cell?: number[][];
  trajectory?: number[][][];          
}

interface AtomViewerProps {
  data: AtomData | null;
  colorMode: "element" | "energy" | "defect";
  frame?: number;
}

const ATOM_COLORS: Record<number, THREE.Color> = {
  74: new THREE.Color("#fbbf24"),  // Tungsten (W) - Amber
  29: new THREE.Color("#f97316"),  // Copper (Cu) - Orange
  26: new THREE.Color("#94a3b8"),  // Iron (Fe) - Slate
  24: new THREE.Color("#22d3ee"),  // Chromium (Cr) - Cyan
  28: new THREE.Color("#e2e8f0"),  // Nickel (Ni) - Gray
  6:  new THREE.Color("#334155"),  // Carbon (C) - Slate 700
  22: new THREE.Color("#cbd5e1"),  // Titanium (Ti) - Slate 300
  13: new THREE.Color("#f1f5f9"),  // Aluminum (Al) - Slate 100
};

const ENERGY_COLORS = [
  new THREE.Color("#06b6d4"), // Cyan
  new THREE.Color("#3b82f6"), // Blue
  new THREE.Color("#6366f1"), // Indigo
  new THREE.Color("#a855f7"), // Purple
  new THREE.Color("#ec4899"), // Pink
];

const SphereShader = {
  uniforms: {
    uSize: { value: 0.35 },
    uBrightness: { value: 1.2 },
  },
  vertexShader: `
    uniform float uSize;
    attribute vec3 instancePosition;
    attribute vec3 instanceColor;
    varying vec3 vColor;
    varying vec2 vUv;

    void main() {
      vColor = instanceColor;
      vUv = uv * 2.0 - 1.0;
      
      // Billboard logic
      vec4 mvPosition = modelViewMatrix * vec4(instancePosition, 1.0);
      mvPosition.xy += position.xy * uSize;
      gl_Position = projectionMatrix * mvPosition;
    }
  `,
  fragmentShader: `
    uniform float uBrightness;
    varying vec3 vColor;
    varying vec2 vUv;
    
    void main() {
      float r2 = dot(vUv, vUv);
      if (r2 > 1.0) discard; 
      
      float z = sqrt(1.0 - r2);
      vec3 normal = vec3(vUv, z);
      vec3 light = normalize(vec3(1.0, 1.0, 2.0));
      float diff = max(dot(normal, light), 0.0);
      
      // Add subtle glow at edges
      float edge = 1.0 - smoothstep(0.8, 1.0, r2);
      
      gl_FragColor = vec4(vColor * (diff * uBrightness + 0.3), edge);
    }
  `
};

function HighPerfAtoms({ data, colorMode, frame = 0 }: AtomViewerProps) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  
  const basePositions = data?.positions || [];
  const numbers = data?.numbers || [];
  const initial_positions = data?.initial_positions || [];
  const energies = data?.energies || [];
  const trajectory = data?.trajectory;
  
  const positions = trajectory && trajectory.length > 0 ? trajectory[Math.min(frame, trajectory.length - 1)] : basePositions;
  const count = positions.length;

  const [posAttr, colAttr] = useMemo(() => {
    const p = new Float32Array(count * 3);
    const c = new Float32Array(count * 3);
    const tempColor = new THREE.Color();

    const minE = (colorMode === "energy" && energies.length > 0) ? Math.min(...energies) : 0;
    const maxE = (colorMode === "energy" && energies.length > 0) ? Math.max(...energies) : 1;
    const range = maxE - minE || 1;

    for (let i = 0; i < count; i++) {
      p[i * 3 + 0] = positions[i][0];
      p[i * 3 + 1] = positions[i][1];
      p[i * 3 + 2] = positions[i][2];

      if (colorMode === "element") {
        tempColor.copy(ATOM_COLORS[numbers[i]] || ATOM_COLORS[74]);
      } 
      else if (colorMode === "energy" && energies.length > i) {
        const norm = (energies[i] - minE) / range;
        const colorIdx = Math.max(0, Math.min(Math.floor(norm * ENERGY_COLORS.length), ENERGY_COLORS.length - 1));
        tempColor.copy(ENERGY_COLORS[colorIdx]);
      }
      else if (colorMode === "defect" && initial_positions?.[i]) {
        const d2 = Math.pow(positions[i][0] - initial_positions[i][0], 2) +
                   Math.pow(positions[i][1] - initial_positions[i][1], 2) +
                   Math.pow(positions[i][2] - initial_positions[i][2], 2);
        // Defect threshold: ~1.2 Angstrom displacement
        tempColor.set(d2 > 1.44 ? "#f43f5e" : "#1e293b"); 
      } else {
        tempColor.set("#0ea5e9");
      }
      
      c[i * 3 + 0] = tempColor.r;
      c[i * 3 + 1] = tempColor.g;
      c[i * 3 + 2] = tempColor.b;
    }
    return [p, c];
  }, [positions, numbers, colorMode, initial_positions, energies, count, frame]);

  useEffect(() => {
    if (meshRef.current) {
      meshRef.current.geometry.attributes.instancePosition.needsUpdate = true;
      meshRef.current.geometry.attributes.instanceColor.needsUpdate = true;
    }
  }, [posAttr, colAttr]);

  if (count === 0) return null;

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, count]}>
      <planeGeometry args={[1, 1]}>
        <instancedBufferAttribute attach="attributes-instancePosition" args={[posAttr, 3]} />
        <instancedBufferAttribute attach="attributes-instanceColor" args={[colAttr, 3]} />
      </planeGeometry>
      <shaderMaterial 
        args={[SphereShader]} 
        transparent={true}
        depthWrite={true}
        depthTest={true}
      />
    </instancedMesh>
  );
}

export default function AtomViewer({ data, colorMode }: AtomViewerProps) {
  const [frame, setFrame] = React.useState(0);
  const maxFrames = data?.trajectory?.length ? data.trajectory.length - 1 : 0;
  const isScrubbable = maxFrames > 0;
  const positions = data?.trajectory && data.trajectory.length > 0
    ? data.trajectory[Math.min(frame, data.trajectory.length - 1)]
    : data?.positions || [];
  const defectThresholdSq = 1.44;

  const defectCount = useMemo(() => {
    if (colorMode !== "defect" || !data?.initial_positions?.length) return null;
    let total = 0;
    for (let i = 0; i < Math.min(positions.length, data.initial_positions.length); i++) {
      const d2 = Math.pow(positions[i][0] - data.initial_positions[i][0], 2) +
                 Math.pow(positions[i][1] - data.initial_positions[i][1], 2) +
                 Math.pow(positions[i][2] - data.initial_positions[i][2], 2);
      if (d2 > defectThresholdSq) total += 1;
    }
    return total;
  }, [colorMode, data?.initial_positions, positions]);

  const energyRange = useMemo(() => {
    if (colorMode !== "energy" || !data?.energies?.length) return null;
    return {
      min: Math.min(...data.energies),
      max: Math.max(...data.energies),
    };
  }, [colorMode, data?.energies]);

  if (!data || !data.positions || data.positions.length === 0) {
    return (
      <div className="w-full h-full bg-[#050505] flex items-center justify-center text-zinc-500 text-[10px] uppercase tracking-[0.3em]">
        Awaiting physics stream
      </div>
    );
  }

  return (
    <div className="w-full h-full bg-[#050505] relative overflow-hidden flex flex-col">
      <div className="flex-1 relative">
        <Canvas gl={{ antialias: true, powerPreference: "high-performance", alpha: true }}>
          <PerspectiveCamera makeDefault position={[30, 30, 30]} fov={40} />
          <OrbitControls makeDefault enableDamping dampingFactor={0.05} rotateSpeed={0.5} />
          <Stars radius={100} depth={50} count={3000} factor={4} saturation={0} fade speed={0.5} />
          <fog attach="fog" args={["#050505", 20, 150]} />
          <React.Suspense fallback={null}>
            <HighPerfAtoms data={data} colorMode={colorMode} frame={frame} />
          </React.Suspense>
        </Canvas>
        
        {/* Legend */}
        <div className="absolute top-6 right-6 flex flex-col gap-3 pointer-events-none">
          <div className="px-4 py-2 rounded-2xl bg-black/40 border border-white/10 backdrop-blur-xl flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-cyan-500 shadow-[0_0_10px_#06b6d4]" />
            <span className="text-[10px] font-black text-white/90 uppercase tracking-widest italic">
              {data ? `${data.positions.length.toLocaleString()} Nodes Synchronized` : "Awaiting Physics Stream..."}
            </span>
          </div>
          
          {data && (
            <div className="px-4 py-3 rounded-2xl bg-black/40 border border-white/10 backdrop-blur-xl flex flex-col gap-2 max-w-[18rem]">
               <div className="text-[8px] font-bold text-zinc-500 uppercase tracking-widest">Active Gradient</div>
               <div className="flex items-center gap-2">
                  <div className={cn("w-3 h-3 rounded-md", colorMode === "element" ? "bg-amber-400" : colorMode === "energy" ? "bg-cyan-500" : "bg-rose-500")} />
                  <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-tighter">{colorMode} analysis</span>
               </div>
               {colorMode === "defect" && (
                 <div className="space-y-1 pt-1">
                   <div className="text-[8px] text-zinc-500 uppercase tracking-widest">Defect Threshold</div>
                   <div className="text-[10px] text-zinc-300 font-mono">Displacement &gt; 1.2 Å from initial position</div>
                   <div className="text-[10px] text-zinc-300 font-mono">
                     Flagged atoms: {defectCount ?? 0}
                   </div>
                   <div className="flex items-center gap-3 pt-1">
                     <div className="flex items-center gap-1.5">
                       <span className="w-2 h-2 rounded-full bg-rose-500" />
                       <span className="text-[8px] text-zinc-500 uppercase tracking-widest">Displaced</span>
                     </div>
                     <div className="flex items-center gap-1.5">
                       <span className="w-2 h-2 rounded-full bg-slate-700" />
                       <span className="text-[8px] text-zinc-500 uppercase tracking-widest">Stable</span>
                     </div>
                   </div>
                 </div>
               )}
               {colorMode === "energy" && energyRange && (
                 <div className="space-y-1 pt-1">
                   <div className="text-[8px] text-zinc-500 uppercase tracking-widest">Energy Range</div>
                   <div className="text-[10px] text-zinc-300 font-mono">
                     {energyRange.min.toFixed(3)} to {energyRange.max.toFixed(3)} eV / atom
                   </div>
                 </div>
               )}
            </div>
          )}
        </div>
      </div>

      {isScrubbable && (
        <div className="absolute bottom-10 left-1/2 -translate-x-1/2 w-[30rem] p-6 rounded-[2rem] bg-[#0c0c0e]/80 border border-white/10 shadow-2xl backdrop-blur-2xl flex flex-col gap-4 z-10 transition-all hover:border-cyan-500/30 group">
          <div className="flex justify-between items-end px-1">
             <div className="flex flex-col">
                <span className="text-[9px] font-black text-zinc-600 uppercase tracking-widest italic">Temporal Sequence</span>
                <span className="text-xs font-mono text-white font-bold">FRAME {frame.toString().padStart(3, '0')}</span>
             </div>
             <span className="text-[10px] font-mono text-zinc-500 uppercase">Limit: {maxFrames}</span>
          </div>
          <div className="text-[9px] text-zinc-500 uppercase tracking-widest px-1">
            {colorMode === "defect"
              ? "Replay of atomic displacement during the cascade"
              : colorMode === "energy"
                ? "Per-atom potential energy at the selected frame"
                : "Atomic positions at the selected frame"}
          </div>
          <input 
            type="range" min="0" max={maxFrames} value={frame}
            onChange={(e) => setFrame(parseInt(e.target.value))}
            className="w-full h-1 bg-white/5 rounded-full appearance-none cursor-pointer accent-cyan-500 hover:accent-cyan-400 transition-all"
          />
        </div>
      )}
    </div>
  );
}
