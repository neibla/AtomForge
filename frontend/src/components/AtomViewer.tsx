"use client";

import React, {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useEffect,
  useState,
} from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, PerspectiveCamera } from "@react-three/drei";
import { Play, Pause, RotateCcw, SlidersHorizontal } from "lucide-react";
import { Color, Vector3 } from "three";
import type { InstancedMesh, PerspectiveCamera as ThreePerspectiveCamera } from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import {
  cellVectorLengths,
  elementLegendEntries,
  elementStyle,
  isPeriodicStructure,
} from "@/lib/atoms";
import { cn, numericRange } from "@/lib/utils";
import {
  classifyDefectAtoms,
  displacementMagnitudes,
  selectAtomIndices,
  type AtomFilter,
} from "@/lib/pkaExplorer";
import type { AtomisticVisualizationData, ColorMode } from "@/types";

const EMPTY_POSITIONS: number[][] = [];
const EMPTY_NUMBERS: number[] = [];

interface AtomViewerProps {
  data: AtomisticVisualizationData | null;
  colorMode: ColorMode;
  frame?: number;
  onFrameChange?: (frame: number) => void;
  replicas?: number;
  filterMode?: AtomFilter;
  showInitialPositions?: boolean;
  showTrails?: boolean;
  showViewportControls?: boolean;
  title?: string;
  description?: string | null;
}

const ENERGY_COLORS = [
  // Blue → orange avoids relying on a red/green distinction for energy.
  new Color("#4f8fc0"),
  new Color("#63b4bd"),
  new Color("#c4b45f"),
  new Color("#df8b4f"),
  new Color("#d8614f"),
];

const ELEMENT_COLOR_CACHE = new Map<number, string>();

function cachedElementColor(atomicNumber: number): string {
  const cached = ELEMENT_COLOR_CACHE.get(atomicNumber);
  if (cached) return cached;
  const color = elementStyle(atomicNumber).color;
  ELEMENT_COLOR_CACHE.set(atomicNumber, color);
  return color;
}

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

      float edge = 1.0 - smoothstep(0.8, 1.0, r2);

      gl_FragColor = vec4(vColor * (diff * uBrightness + 0.3), edge);
    }
  `,
};

const VacancyShader = {
  uniforms: {
    uSize: { value: 0.28 },
    uBrightness: { value: 2.0 },
  },
  vertexShader: SphereShader.vertexShader,
  fragmentShader: `
    uniform float uBrightness;
    varying vec2 vUv;

    void main() {
      float r2 = dot(vUv, vUv);
      if (r2 > 1.0) discard;

      float ring = smoothstep(0.4, 0.75, r2) - smoothstep(0.8, 1.0, r2);
      float centerGlow = 1.0 - r2;
      float alpha = max(ring * 0.8, centerGlow * 0.2);

      vec3 color = vec3(0.96, 0.25, 0.37); // Rose #f43f5e
      gl_FragColor = vec4(color * uBrightness, alpha * 0.65);
    }
  `,
};

function HighPerfAtoms({
  data,
  colorMode,
  frame = 0,
  replicas = 1,
  filterMode = "all",
}: AtomViewerProps) {
  const meshRef = useRef<InstancedMesh>(null);

  const basePositions = data?.positions || EMPTY_POSITIONS;
  const numbers = data?.numbers || EMPTY_NUMBERS;
  const energies = data?.energies || EMPTY_NUMBERS;
  const trajectory = data?.trajectory;

  const positions =
    trajectory && trajectory.length > 0
      ? trajectory[Math.min(frame, trajectory.length - 1)]
      : basePositions;
  const atomIndices = useMemo(
    () => (data ? selectAtomIndices(data, frame, filterMode) : []),
    [data, frame, filterMode],
  );
  const count = atomIndices.length;
  const defectFlags = useMemo(
    () =>
      data && colorMode === "defect"
        ? classifyDefectAtoms(data, frame)
        : null,
    [data, colorMode, frame],
  );
  const replicaOffsets = useMemo(() => {
    const cellVecs = data?.cell || [
      [10, 0, 0],
      [0, 10, 0],
      [0, 0, 10],
    ];
    const offsets: number[][] = [];
    for (let dx = 0; dx < replicas; dx++) {
      for (let dy = 0; dy < replicas; dy++) {
        for (let dz = 0; dz < replicas; dz++) {
          offsets.push([
            dx * cellVecs[0][0] + dy * cellVecs[1][0] + dz * cellVecs[2][0],
            dx * cellVecs[0][1] + dy * cellVecs[1][1] + dz * cellVecs[2][1],
            dx * cellVecs[0][2] + dy * cellVecs[1][2] + dz * cellVecs[2][2],
          ]);
        }
      }
    }
    return offsets;
  }, [data?.cell, replicas]);

  const [posAttr, colAttr, totalCount] = useMemo(() => {
    const tCount = count * replicaOffsets.length;

    const p = new Float32Array(tCount * 3);
    const c = new Float32Array(tCount * 3);
    const tempColor = new Color();

    const minE =
      colorMode === "energy" && energies.length > 0
        ? energies.reduce((minimum, value) => Math.min(minimum, value), Infinity)
        : 0;
    const maxE =
      colorMode === "energy" && energies.length > 0
        ? energies.reduce((maximum, value) => Math.max(maximum, value), -Infinity)
        : 1;
    const energySpan = maxE - minE;
    const range = energySpan || 1;

    let idx = 0;
    for (const [ox, oy, oz] of replicaOffsets) {
      for (const atomIndex of atomIndices) {
        p[idx * 3 + 0] = positions[atomIndex][0] + ox;
        p[idx * 3 + 1] = positions[atomIndex][1] + oy;
        p[idx * 3 + 2] = positions[atomIndex][2] + oz;

        if (colorMode === "element") {
          tempColor.set(cachedElementColor(numbers[atomIndex]));
        } else if (colorMode === "energy" && energies.length > atomIndex) {
          const norm =
            energySpan < 1e-9 ? 0.5 : (energies[atomIndex] - minE) / range;
          const colorIdx = Math.max(
            0,
            Math.min(
              Math.floor(norm * ENERGY_COLORS.length),
              ENERGY_COLORS.length - 1,
            ),
          );
          tempColor.copy(ENERGY_COLORS[colorIdx]);
        } else if (colorMode === "defect" && defectFlags) {
          tempColor.set(defectFlags[atomIndex] ? "#ffb85c" : "#9bb8c4");
        } else {
          tempColor.set("#0ea5e9");
        }

        c[idx * 3 + 0] = tempColor.r;
        c[idx * 3 + 1] = tempColor.g;
        c[idx * 3 + 2] = tempColor.b;
        idx++;
      }
    }
    return [p, c, tCount];
  }, [
    positions,
    numbers,
    colorMode,
    defectFlags,
    energies,
    count,
    replicaOffsets,
    atomIndices,
  ]);

  useEffect(() => {
    if (meshRef.current) {
      meshRef.current.geometry.attributes.instancePosition.needsUpdate = true;
      meshRef.current.geometry.attributes.instanceColor.needsUpdate = true;
    }
  }, [posAttr, colAttr]);

  if (totalCount === 0) return null;

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, totalCount]}
      frustumCulled={false}
    >
      <planeGeometry args={[1, 1]}>
        <instancedBufferAttribute
          attach="attributes-instancePosition"
          args={[posAttr, 3]}
        />
        <instancedBufferAttribute
          attach="attributes-instanceColor"
          args={[colAttr, 3]}
        />
      </planeGeometry>
      <shaderMaterial
        args={[SphereShader]}
        toneMapped={false}
        transparent={true}
        depthWrite={true}
        depthTest={true}
      />
    </instancedMesh>
  );
}

function InitialPositionGhosts({
  data,
  frame,
  filterMode,
}: {
  data: AtomisticVisualizationData;
  frame: number;
  filterMode: AtomFilter;
}) {
  const positions = data.initial_positions ?? EMPTY_POSITIONS;
  const indices = useMemo(
    () => selectAtomIndices(data, frame, filterMode),
    [data, frame, filterMode],
  );
  const points = useMemo(
    () => indices.map((index) => positions[index]).filter(Boolean),
    [indices, positions],
  );
  if (!points.length) return null;
  return (
    <points>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[new Float32Array(points.flat()), 3]}
        />
      </bufferGeometry>
      <pointsMaterial
        color="#94a3b8"
        size={0.18}
        transparent
        opacity={0.35}
        depthWrite={false}
      />
    </points>
  );
}

function DisplacementTrails({
  data,
  frame,
  filterMode,
}: {
  data: AtomisticVisualizationData;
  frame: number;
  filterMode: AtomFilter;
}) {
  const initial = data.initial_positions ?? EMPTY_POSITIONS;
  const current = data.trajectory?.[frame] ?? data.positions;
  const indices = useMemo(
    () => selectAtomIndices(data, frame, filterMode),
    [data, frame, filterMode],
  );
  const magnitudes = useMemo(
    () => displacementMagnitudes(data, frame),
    [data, frame],
  );
  const vertices = useMemo(() => {
    const selected = indices
      .filter((index) => magnitudes[index] > 0.5)
      .slice(0, 2_000);
    return new Float32Array(
      selected.flatMap((index) => [...initial[index], ...current[index]]),
    );
  }, [current, indices, initial, magnitudes]);
  if (!vertices.length) return null;
  return (
    <lineSegments>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[vertices, 3]} />
      </bufferGeometry>
      <lineBasicMaterial
        color="#d88a52"
        transparent
        opacity={0.42}
        depthWrite={false}
      />
    </lineSegments>
  );
}

function VacancyGhosts({
  positions,
  cell,
  replicas,
}: {
  positions: number[][];
  cell: number[][];
  replicas: number;
}) {
  const count = positions.length;
  const numReplicas = replicas * replicas * replicas;
  const totalCount = count * numReplicas;

  const meshRef = useRef<InstancedMesh>(null);

  const posAttr = useMemo(() => {
    const cellVecs = cell || [
      [10, 0, 0],
      [0, 10, 0],
      [0, 0, 10],
    ];
    const p = new Float32Array(totalCount * 3);
    let idx = 0;
    for (let dx = 0; dx < replicas; dx++) {
      for (let dy = 0; dy < replicas; dy++) {
        for (let dz = 0; dz < replicas; dz++) {
          const ox =
            dx * cellVecs[0][0] + dy * cellVecs[1][0] + dz * cellVecs[2][0];
          const oy =
            dx * cellVecs[0][1] + dy * cellVecs[1][1] + dz * cellVecs[2][1];
          const oz =
            dx * cellVecs[0][2] + dy * cellVecs[1][2] + dz * cellVecs[2][2];

          for (let i = 0; i < count; i++) {
            p[idx * 3 + 0] = positions[i][0] + ox;
            p[idx * 3 + 1] = positions[i][1] + oy;
            p[idx * 3 + 2] = positions[i][2] + oz;
            idx++;
          }
        }
      }
    }
    return p;
  }, [positions, cell, count, replicas, totalCount]);

  useEffect(() => {
    if (meshRef.current) {
      meshRef.current.geometry.attributes.instancePosition.needsUpdate = true;
    }
  }, [posAttr]);

  if (totalCount === 0) return null;

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, totalCount]}
      frustumCulled={false}
    >
      <planeGeometry args={[1, 1]}>
        <instancedBufferAttribute
          attach="attributes-instancePosition"
          args={[posAttr, 3]}
        />
        <instancedBufferAttribute
          attach="attributes-instanceColor"
          args={[new Float32Array(totalCount * 3), 3]}
        />
      </planeGeometry>
      <shaderMaterial
        args={[VacancyShader]}
        transparent={true}
        depthWrite={false}
        depthTest={true}
      />
    </instancedMesh>
  );
}

type CameraView = "3d" | "top" | "side";

function CellFrame({
  cell,
  replicas = 1,
}: {
  cell: number[][];
  replicas?: number;
}) {
  const vertices = useMemo(() => {
    const [a, b, c] = cell;
    const edges = [
      [0, 1],
      [0, 2],
      [0, 3],
      [1, 4],
      [1, 5],
      [2, 4],
      [2, 6],
      [3, 5],
      [3, 6],
      [4, 7],
      [5, 7],
      [6, 7],
    ];
    const vertices: number[] = [];
    for (let dx = 0; dx < replicas; dx++) {
      for (let dy = 0; dy < replicas; dy++) {
        for (let dz = 0; dz < replicas; dz++) {
          const offset = [
            dx * a[0] + dy * b[0] + dz * c[0],
            dx * a[1] + dy * b[1] + dz * c[1],
            dx * a[2] + dy * b[2] + dz * c[2],
          ];
          const corners = [
            offset,
            a.map((value, axis) => value + offset[axis]),
            b.map((value, axis) => value + offset[axis]),
            c.map((value, axis) => value + offset[axis]),
            a.map((value, axis) => value + b[axis] + offset[axis]),
            a.map((value, axis) => value + c[axis] + offset[axis]),
            b.map((value, axis) => value + c[axis] + offset[axis]),
            a.map((value, axis) => value + b[axis] + c[axis] + offset[axis]),
          ];
          for (const [start, end] of edges) {
            vertices.push(...corners[start], ...corners[end]);
          }
        }
      }
    }
    return new Float32Array(vertices);
  }, [cell, replicas]);

  return (
    <lineSegments frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[vertices, 3]} />
      </bufferGeometry>
      <lineBasicMaterial
        color="#b96845"
        transparent
        opacity={0.42}
        depthWrite={false}
      />
    </lineSegments>
  );
}

function SceneCamera({
  positions,
  cell,
  replicas,
  view,
  cameraRevision,
}: {
  positions: number[][];
  cell: number[][];
  replicas: number;
  view: CameraView;
  cameraRevision: number;
}) {
  const { center, distance } = useMemo(() => {
    const [a, b, c] = cell;
    const displayedPositions = [];
    for (let dx = 0; dx < replicas; dx++) {
      for (let dy = 0; dy < replicas; dy++) {
        for (let dz = 0; dz < replicas; dz++) {
          const offset = [
            dx * a[0] + dy * b[0] + dz * c[0],
            dx * a[1] + dy * b[1] + dz * c[1],
            dx * a[2] + dy * b[2] + dz * c[2],
          ];
          displayedPositions.push(
            ...positions.map((position) =>
              position.map((value, axis) => value + offset[axis]),
            ),
          );
        }
      }
    }
    const minimum = [Infinity, Infinity, Infinity];
    const maximum = [-Infinity, -Infinity, -Infinity];
    displayedPositions.forEach((position) => {
      position.forEach((value, axis) => {
        minimum[axis] = Math.min(minimum[axis], value);
        maximum[axis] = Math.max(maximum[axis], value);
      });
    });
    const midpoint = minimum.map(
      (value, axis) => (value + maximum[axis]) / 2,
    ) as [number, number, number];
    const extent = Math.max(
      ...maximum.map((value, axis) => value - minimum[axis]),
      4,
    );
    return { center: midpoint, distance: extent * 1.05 };
  }, [cell, positions, replicas]);
  const position = useMemo<[number, number, number]>(
    () =>
      view === "top"
        ? [center[0], center[1], center[2] + distance * 1.8]
        : view === "side"
          ? [center[0] + distance * 1.8, center[1], center[2]]
          : [center[0] + distance, center[1] + distance, center[2] + distance],
    [center, distance, view],
  );
  const up = useMemo<[number, number, number]>(
    () => (view === "side" ? [0, 0, 1] : [0, 1, 0]),
    [view],
  );
  const cameraRef = useRef<ThreePerspectiveCamera>(null);
  const controlsRef = useRef<OrbitControlsImpl>(null);
  const previousCenterRef = useRef<Vector3 | null>(null);
  const resetKeyRef = useRef<string | null>(null);

  useLayoutEffect(() => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;

    const nextCenter = new Vector3(...center);
    const resetKey = `${view}:${cameraRevision}`;
    const previousCenter = previousCenterRef.current;
    const shouldReset = resetKeyRef.current !== resetKey || !previousCenter;
    if (shouldReset) {
      camera.position.set(...position);
      camera.up.set(...up);
      controls.target.copy(nextCenter);
    } else if (previousCenter) {
      const delta = nextCenter.clone().sub(previousCenter);
      camera.position.add(delta);
      controls.target.add(delta);
    }
    camera.updateProjectionMatrix();
    controls.update();
    previousCenterRef.current = nextCenter;
    resetKeyRef.current = resetKey;
  }, [cameraRevision, center, position, up, view]);

  return (
    <>
      <PerspectiveCamera ref={cameraRef} makeDefault fov={40} />
      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.05}
        rotateSpeed={0.5}
      />
    </>
  );
}

export default function AtomViewer({
  data,
  colorMode,
  frame: controlledFrame,
  onFrameChange,
  filterMode = "all",
  showInitialPositions = false,
  showTrails = false,
  showViewportControls = true,
  title,
  description,
}: AtomViewerProps) {
  const [internalFrame, setInternalFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed] = useState(150); // 150ms per frame loop
  const periodicStructure = data ? isPeriodicStructure(data) : false;
  const [replicas, setReplicas] = useState(periodicStructure ? 2 : 1);
  const replicaOptions =
    periodicStructure && (data?.positions.length ?? 0) <= 16
      ? [1, 2, 3, 5]
      : [1, 2];
  const [cameraView, setCameraView] = useState<CameraView>("3d");
  const [cameraRevision, setCameraRevision] = useState(0);
  const [showDetails, setShowDetails] = useState(false);
  const frame = controlledFrame ?? internalFrame;
  const setFrame = useCallback(
    (next: number | ((previous: number) => number)) => {
      const value = typeof next === "function" ? next(frame) : next;
      if (controlledFrame === undefined) setInternalFrame(value);
      onFrameChange?.(value);
    },
    [controlledFrame, frame, onFrameChange],
  );

  const maxFrames = data?.trajectory?.length ? data.trajectory.length - 1 : 0;
  const isScrubbable = maxFrames > 0;
  const vacancyPositions = data?.vacancy_positions || EMPTY_POSITIONS;

  // Trajectory Playback loop
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;
    if (isPlaying && maxFrames > 0) {
      interval = setInterval(() => {
        setFrame((prev) => (prev >= maxFrames ? 0 : prev + 1));
      }, playbackSpeed);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isPlaying, maxFrames, playbackSpeed, setFrame]);

  const energies = data?.energies;
  const energyRange = useMemo(() => {
    if (colorMode !== "energy" || !energies?.length) return null;
    return numericRange(energies);
  }, [colorMode, energies]);
  const uniformEnergy = energyRange
    ? Math.abs(energyRange.max - energyRange.min) < 1e-9
    : false;

  if (!data || !data.positions || data.positions.length === 0) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-[#101a20] text-sm text-[#a7b4b3]">
        No atomic structure available
      </div>
    );
  }

  const cell = data?.cell || [
    [10, 0, 0],
    [0, 10, 0],
    [0, 0, 10],
  ];
  const legendEntries = elementLegendEntries(data.numbers);
  const cellLengths = cellVectorLengths(cell);
  const displayedCellLengths = cellLengths.map((length) => length * replicas);
  const isFcc111Slab = title?.includes("FCC(111)") ?? false;
  const viewGuidance = isFcc111Slab
    ? cameraView === "top"
      ? "Top view reveals the repeating triangular FCC(111) surface lattice."
      : cameraView === "side"
        ? "Side view reveals the stacked atomic planes and the vacuum gap along the cell height."
        : "Perspective view shows the slab in 3D; depth overlap can make the ordered planes look scattered."
    : "Spheres are atoms; the orange wireframe marks the simulation cell.";

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-[#101a20]">
      <div className="relative min-h-0 flex-1">
        <Canvas
          gl={{
            antialias: true,
            powerPreference: "high-performance",
            alpha: true,
          }}
        >
          <SceneCamera
            positions={data.positions}
            cell={cell}
            replicas={replicas}
            view={cameraView}
            cameraRevision={cameraRevision}
          />
          <fog attach="fog" args={["#101a20", 20, 150]} />
          <React.Suspense fallback={null}>
            <CellFrame cell={cell} replicas={replicas} />
            <HighPerfAtoms
              data={data}
              colorMode={colorMode}
              frame={frame}
              replicas={replicas}
              filterMode={filterMode}
            />
            {showInitialPositions && data ? (
              <InitialPositionGhosts
                data={data}
                frame={frame}
                filterMode={filterMode}
              />
            ) : null}
            {showTrails && data ? (
              <DisplacementTrails
                data={data}
                frame={frame}
                filterMode={filterMode}
              />
            ) : null}
            {colorMode === "defect" && (
              <VacancyGhosts
                positions={vacancyPositions}
                cell={cell}
                replicas={replicas}
              />
            )}
          </React.Suspense>
        </Canvas>

        {showViewportControls ? (
          <div
            className="absolute left-5 top-5 flex items-center gap-1 border border-[#30464f] bg-[#16262e] p-1 shadow-sm"
            role="group"
            aria-label="Camera view"
          >
            {(["3d", "top", "side"] as CameraView[]).map((view) => (
              <button
                type="button"
                key={view}
                aria-pressed={cameraView === view}
                onClick={() => setCameraView(view)}
                className={cn(
                  "min-h-11 rounded px-2.5 py-1.5 text-[0.68rem] font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]",
                  cameraView === view
                    ? "bg-[#edf1eb] text-[#101a20]"
                    : "text-[#a7b4b3] hover:bg-[#243b44] hover:text-[#edf1eb]",
                )}
              >
                {view === "3d" ? "3D" : view === "top" ? "Top" : "Side"}
              </button>
            ))}
            <button
              type="button"
              aria-label="Reset camera"
              title="Reset camera"
              onClick={() => setCameraRevision((revision) => revision + 1)}
              className="grid min-h-11 min-w-11 place-items-center rounded p-1.5 text-[#a7b4b3] transition hover:bg-[#243b44] hover:text-[#edf1eb] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}

        {showViewportControls ? (
          <div className="pointer-events-none absolute right-4 top-4 flex max-w-[calc(100%-2rem)] flex-col items-end gap-2 lg:right-5 lg:top-5">
            <div className="pointer-events-auto flex items-center gap-2 border border-[#30464f] bg-[#16262e] px-3 py-2 shadow-sm">
              <span className="text-xs font-medium text-[#edf1eb]">
                {(
                  data.positions.length *
                  replicas *
                  replicas *
                  replicas
                ).toLocaleString()}{" "}
                atoms shown
              </span>
              <button
                type="button"
                onClick={() => setShowDetails((visible) => !visible)}
                aria-expanded={showDetails}
                aria-controls="atom-viewer-details"
                className="ml-1 inline-flex min-h-11 items-center gap-1 rounded border border-[#3a5662] px-2 py-1 text-[0.65rem] font-semibold text-[#c4d2d5] transition hover:border-[#d5794f] hover:text-[#fff2e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]"
              >
                <SlidersHorizontal className="h-3 w-3" />
                {showDetails ? "Hide details" : "Details"}
              </button>
            </div>

            <div
              className="pointer-events-auto flex max-w-[18rem] flex-wrap items-center justify-end gap-1.5 border border-[#30464f] bg-[#16262e] px-3 py-2 shadow-sm"
              aria-label="Atom color legend"
            >
              <span className="mr-1 text-[0.62rem] font-semibold uppercase tracking-[0.1em] text-[#8ea5af]">
                {colorMode === "element"
                  ? "Element colors"
                  : colorMode === "energy"
                    ? "Energy colors"
                    : "Defect colors"}
              </span>
              {colorMode === "element" ? (
                legendEntries.map((entry) => (
                  <span
                    key={entry.atomicNumber}
                    className="inline-flex items-center gap-1 rounded-full border border-[#3a5662] px-1.5 py-0.5 text-[0.62rem] font-semibold text-[#dce7e4]"
                    title={`${entry.name} (Z=${entry.atomicNumber})`}
                  >
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: entry.color }}
                    />
                    {entry.symbol}
                  </span>
                ))
              ) : colorMode === "defect" ? (
                <>
                  <span className="inline-flex items-center gap-1 text-[0.62rem] text-[#a7b4b3]">
                    <span className="h-2 w-2 rounded-full bg-[#ffb85c]" />{" "}
                    displaced
                  </span>
                  <span className="inline-flex items-center gap-1 text-[0.62rem] text-[#a7b4b3]">
                    <span className="h-2 w-2 rounded-full bg-[#9bb8c4]" />{" "}
                    stable
                  </span>
                </>
              ) : (
                <span className="text-[0.62rem] text-[#a7b4b3]">
                  low → high
                </span>
              )}
            </div>

            {data && showDetails && (
              <div
                id="atom-viewer-details"
                className="pointer-events-auto flex max-h-[calc(100vh-16rem)] max-w-[18rem] flex-col gap-2 overflow-y-auto border border-[#30464f] bg-[#16262e] px-4 py-3 shadow-sm"
              >
                {title ? (
                  <div className="text-xs font-semibold text-[#edf1eb]">
                    {title}
                  </div>
                ) : null}
                {description ? (
                  <div className="text-[0.68rem] leading-relaxed text-[#9fb2b9]">
                    {description}
                  </div>
                ) : null}

                <div className="border-t border-[#30464f] pt-2 text-[0.68rem] leading-relaxed text-[#b8c7c8]">
                  {viewGuidance}
                </div>
                <div className="border-l-2 border-[#b96845] pl-2 text-[0.68rem] leading-[1.55] text-[#aababe]">
                  Geometry view only: use this to inspect composition,
                  orientation, and cell construction. Scientific acceptance
                  comes from the evidence checks above.
                </div>
                <div className="font-mono text-[0.63rem] text-[#8298a0]">
                  Base cell{" "}
                  {cellLengths.map((length) => length.toFixed(2)).join(" × ")} Å
                </div>
                <div className="font-mono text-[0.63rem] text-[#8298a0]">
                  Displayed extent{" "}
                  {displayedCellLengths
                    .map((length) => length.toFixed(2))
                    .join(" × ")}{" "}
                  Å
                </div>
                <div className="text-[0.68rem] leading-[1.5] text-[#8298a0]">
                  Drag to orbit · scroll to zoom · orange lines show the
                  displayed replicas
                </div>

                <div className="border-t border-[#30464f] pt-3 text-[0.7rem] font-semibold tracking-[0.02em] text-[#b8c7c8]">
                  Display replicas
                </div>
                <div className="text-[0.68rem] leading-[1.5] text-[#8298a0]">
                  Visualization only; the saved calculation used the base cell
                  above.
                </div>
                <div
                  className="flex gap-1 bg-[#101a20] p-1"
                  role="group"
                  aria-label="Displayed cell replicas"
                >
                  {replicaOptions.map((r) => (
                    <button
                      type="button"
                      key={r}
                      aria-pressed={replicas === r}
                      onClick={() => setReplicas(r)}
                      className={cn(
                        "pointer-events-auto min-h-11 flex-1 rounded px-2 py-1 text-xs font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]",
                        replicas === r
                          ? "bg-[#edf1eb] text-[#101a20]"
                          : "text-[#a7b4b3] hover:text-[#edf1eb]",
                      )}
                    >
                      {r}×{r}×{r}
                    </button>
                  ))}
                </div>

                {colorMode === "defect" && (
                  <div className="space-y-1.5 border-t border-[#30464f] pt-2">
                    <div className="text-xs font-medium text-[#a7b4b3]">
                      Wigner–Seitz result
                    </div>
                    <div className="text-[0.68rem] leading-[1.5] text-[#c3cfcc]">
                      Periodic defect count from the backend result
                    </div>
                    <div className="text-[0.68rem] leading-[1.5] text-[#8fa09f]">
                      Atom colors preview displacement.
                    </div>
                    <div className="space-y-0.5 font-mono text-xs text-[#edf1eb]">
                      <div>
                        Vacancies:{" "}
                        <span className="text-rose-400 font-bold">
                          {data.n_defects ?? vacancyPositions.length}
                        </span>
                      </div>
                      <div>
                        Interstitials:{" "}
                        <span className="text-rose-400 font-bold">
                          {data.interstitials ?? 0}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 pt-1">
                      <div className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-rose-500" />
                        <span className="text-xs text-[#a7b4b3]">
                          Displaced / vacancy
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-[#293942]" />
                        <span className="text-xs text-[#a7b4b3]">
                          Stable site
                        </span>
                      </div>
                    </div>
                  </div>
                )}
                {colorMode === "energy" && energyRange && (
                  <div className="space-y-1 border-t border-[#30464f] pt-2">
                    <div className="text-xs font-medium text-[#a7b4b3]">
                      Energy range
                    </div>
                    <div className="font-mono text-xs text-[#edf1eb]">
                      {uniformEnergy
                        ? `${energyRange.min.toFixed(3)} eV / atom (uniform)`
                        : `${energyRange.min.toFixed(3)} to ${energyRange.max.toFixed(3)} eV / atom`}
                    </div>
                    {uniformEnergy ? (
                      <div className="text-[0.68rem] leading-relaxed text-[#9fb2b9]">
                        No per-atom energy variation is visible at this
                        precision.
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : null}
      </div>

      {isScrubbable && showViewportControls && (
        <div className="absolute bottom-6 left-1/2 z-10 flex w-[min(32rem,calc(100%-2rem))] -translate-x-1/2 flex-col gap-3 border border-[#30464f] bg-[#16262e] p-4 shadow-lg">
          <div className="flex justify-between items-end px-1">
            <div className="flex flex-col">
              <span className="text-xs text-[#a7b4b3]">Trajectory</span>
              <span className="font-mono text-xs font-medium text-[#edf1eb]">
                Frame {frame.toString().padStart(3, "0")}
              </span>
            </div>

            <div className="flex items-center gap-2 pointer-events-auto">
              <button
                type="button"
                onClick={() => {
                  setFrame(0);
                  setIsPlaying(false);
                }}
                aria-label="Reset trajectory"
                className="grid min-h-11 min-w-11 place-items-center rounded-md p-1.5 text-[#a7b4b3] transition hover:bg-[#243b44] hover:text-[#edf1eb] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]"
                title="Reset trajectory"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setIsPlaying(!isPlaying)}
                aria-label={isPlaying ? "Pause trajectory" : "Play trajectory"}
                className="grid min-h-11 min-w-11 place-items-center rounded-md border border-[#30464f] bg-[#edf1eb] p-1.5 text-[#101a20] transition hover:bg-[#cbd8d3] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]"
                title={isPlaying ? "Pause trajectory" : "Play trajectory"}
              >
                {isPlaying ? (
                  <Pause className="h-3.5 w-3.5" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
              </button>
            </div>

            <span className="font-mono text-xs text-[#a7b4b3]">
              {maxFrames + 1} frames
            </span>
          </div>
          <div className="px-1 text-xs text-[#a7b4b3]">
            {colorMode === "defect"
              ? "Replay of atomic displacement during the cascade"
              : colorMode === "energy"
                ? "Per-atom potential energy from the final result"
                : "Atomic positions at the selected frame"}
          </div>
          <input
            type="range"
            min="0"
            max={maxFrames}
            value={frame}
            onChange={(e) => setFrame(parseInt(e.target.value))}
            aria-label="Trajectory frame"
            aria-valuetext={`Frame ${frame + 1} of ${maxFrames + 1}`}
            className="h-5 w-full cursor-pointer appearance-none rounded-full bg-[#30464f] accent-[#d88a52] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e28a5f]"
          />
        </div>
      )}
    </div>
  );
}
