import type { PortraitDescriptor } from "@/api/queens";

const STROKE = "#1B1814";
const ACCENT = "oklch(0.62 0.14 70)";

const FACE_SHAPES: Record<string, string> = {
  oval: "M50,28 C68,28 76,46 76,62 C76,80 64,90 50,90 C36,90 24,80 24,62 C24,46 32,28 50,28 Z",
  round: "M50,30 C70,30 78,48 78,62 C78,80 66,90 50,90 C34,90 22,80 22,62 C22,48 30,30 50,30 Z",
  long: "M50,26 C66,26 74,46 74,64 C74,84 62,94 50,94 C38,94 26,84 26,64 C26,46 34,26 50,26 Z",
  rect: "M50,28 C66,28 74,42 74,58 L74,72 C74,86 62,92 50,92 C38,92 26,86 26,72 L26,58 C26,42 34,28 50,28 Z",
  square: "M50,30 L72,32 L74,72 L60,90 L40,90 L26,72 L28,32 Z",
};

interface HairDef {
  top: string | null;
  side?: string;
}

const HAIR_PATHS: Record<string, HairDef> = {
  short: { top: "M28,46 C28,32 38,22 50,22 C62,22 72,32 72,46 C70,42 64,38 58,38 C54,38 50,40 46,40 C42,40 38,42 30,46 Z" },
  "short-back": { top: "M30,48 C30,32 40,22 50,22 C60,22 70,32 70,48 C66,42 60,40 50,40 C40,40 34,42 30,48 Z" },
  "short-bob": { top: "M26,52 C26,30 38,20 50,20 C62,20 74,30 74,52 L72,58 L70,46 L30,46 L28,58 Z" },
  "short-grey": { top: "M30,46 C30,32 40,22 50,22 C60,22 70,32 70,46 C66,42 60,40 50,40 C40,40 34,42 30,46 Z" },
  "short-thin": { top: "M34,42 C34,32 42,24 50,24 C58,24 66,32 66,42 C62,40 56,38 50,38 C44,38 38,40 34,42 Z" },
  crop: { top: "M30,42 C30,30 40,22 50,22 C60,22 70,30 70,42 C66,38 60,36 50,36 C40,36 34,38 30,42 Z" },
  "crop-thin": { top: "M34,40 C34,30 42,24 50,24 C58,24 66,30 66,40 C62,38 56,36 50,36 C44,36 38,38 34,40 Z" },
  "side-back": {
    top: "M28,48 C28,32 38,22 50,22 C62,22 72,32 72,48 C66,40 56,40 46,42 C40,42 34,42 28,48 Z",
    side: "M70,40 C72,46 70,52 66,54 L62,42 Z",
  },
  "side-back-grey": {
    top: "M28,48 C28,32 38,22 50,22 C62,22 72,32 72,48 C66,40 56,40 46,42 C40,42 34,42 28,48 Z",
    side: "M70,40 C72,46 70,52 66,54 L62,42 Z",
  },
  "side-bushy-grey": {
    top: "M22,46 C22,30 36,18 50,18 C64,18 78,30 78,46 C74,38 66,38 56,40 C46,42 36,38 22,46 Z",
    side: "M70,38 C76,46 74,56 66,58 L60,42 Z",
  },
  "side-short": { top: "M28,46 C28,32 38,22 50,22 C62,22 72,32 72,46 C68,40 56,38 46,40 C40,40 34,42 28,46 Z" },
  "side-short-grey": { top: "M28,46 C28,32 38,22 50,22 C62,22 72,32 72,46 C68,40 56,38 46,40 C40,40 34,42 28,46 Z" },
  parted: { top: "M26,50 C26,30 38,20 50,20 C62,20 74,30 74,50 C70,40 60,38 52,42 L50,30 L48,42 C40,38 30,40 26,50 Z" },
  "swept-front": { top: "M28,48 C28,32 38,22 50,22 C62,22 72,32 72,48 C70,40 60,38 52,40 C46,42 38,46 32,52 L34,46 C32,46 30,46 28,48 Z" },
  "slick-back": { top: "M30,46 C30,30 40,22 50,22 C60,22 70,30 70,46 C68,40 64,38 58,38 C56,38 54,38 52,38 L50,30 L48,38 C44,38 38,40 30,46 Z" },
  "wave-long": {
    top: "M22,52 C22,30 38,20 50,20 C62,20 78,30 78,52 C72,44 66,50 60,46 C56,50 50,46 44,50 C38,46 30,52 22,52 Z",
    side: "M22,54 C20,62 22,72 28,76 L30,52 Z M78,54 C80,62 78,72 72,76 L70,52 Z",
  },
  "wild-curly": { top: "M22,42 C24,26 38,16 50,16 C62,16 76,26 78,42 C74,38 66,42 60,32 C56,42 50,38 44,32 C38,42 28,38 22,42 Z" },
  "wild-curly-grey": { top: "M22,42 C24,26 38,16 50,16 C62,16 76,26 78,42 C74,38 66,42 60,32 C56,42 50,38 44,32 C38,42 28,38 22,42 Z" },
  "curls-fringe": { top: "M26,46 C26,30 38,22 50,22 C62,22 74,30 74,46 C70,44 66,46 62,42 C58,46 54,42 50,46 C46,42 42,46 38,42 C34,46 30,44 26,46 Z" },
  "pulled-tight": {
    top: "M30,42 C30,30 40,22 50,22 C60,22 70,30 70,42 C66,40 60,38 50,38 C40,38 34,40 30,42 Z",
    side: "M70,40 C76,50 74,60 70,66 L66,42 Z M30,40 C24,50 26,60 30,66 L34,42 Z",
  },
  "long-straight": { top: "M22,80 C22,40 32,20 50,20 C68,20 78,40 78,80 L70,76 L70,46 L30,46 L30,76 Z" },
  "long-wavy": { top: "M22,80 C22,40 32,20 50,20 C68,20 78,40 78,80 C76,72 72,74 70,68 L70,46 L30,46 L30,68 C28,74 24,72 22,80 Z" },
  "bob-long": { top: "M22,72 C22,32 34,18 50,18 C66,18 78,32 78,72 L72,66 L70,46 L30,46 L28,66 Z" },
  "bob-sharp-bangs": {
    top: "M22,54 L22,30 C22,22 36,18 50,18 C64,18 78,22 78,30 L78,54 L70,52 L66,40 L34,40 L30,52 Z",
    side: "M30,40 L34,52 L34,40 Z M70,40 L66,52 L66,40 Z",
  },
  "bald-shine": { top: null, side: "M50,24 C46,26 44,28 44,32 L48,30 Z" },
  bald: { top: null },
};

const MOUTH_PATHS: Record<string, string> = {
  flat: "M44,76 L56,76",
  smile: "M43,75 Q50,80 57,75",
  "smile-soft": "M44,76 Q50,79 56,76",
  "smile-broad": "M42,74 Q50,82 58,74",
  smirk: "M44,76 Q50,79 56,75",
};

interface QueenPortraitGlyphProps {
  p: PortraitDescriptor;
  className?: string;
  /** Draw the inset dashed honeycomb frame behind the portrait. Turn off
   * when the consumer already clips the glyph into a hexagon (org chart)
   * to avoid a hex-inside-hex double border. */
  frame?: boolean;
}

export default function QueenPortraitGlyph({ p, className, frame = true }: QueenPortraitGlyphProps) {
  const skin = p.skin || "#F1D6BA";
  const hair = p.hair || "#3B312A";
  const cut = p.cut || "short";
  const face = p.face || "oval";
  const eyes = p.eyes || "kind";
  const mouth = p.mouth || "flat";

  const faceShape = FACE_SHAPES[face] || FACE_SHAPES.oval;
  const hairDef = HAIR_PATHS[cut] || HAIR_PATHS.short;
  const mouthShape = MOUTH_PATHS[mouth] || MOUTH_PATHS.flat;

  const eyeY = 58;
  const eyeXL = 41;
  const eyeXR = 59;
  const eyeR = eyes === "wide" ? 2.6 : 2.0;
  const browY = eyeY - 6;
  const browArch = p.brow === "arched" ? -1.5 : 0;

  const showBrow = !p.glasses || p.glasses === "sun";
  const showEyes = p.glasses !== "sun";

  const shirt = p.shirt;
  const collar = p.collar;
  const neck = p.neck;

  return (
    <svg
      viewBox={frame ? "0 0 100 100" : "6 6 88 96"}
      xmlns="http://www.w3.org/2000/svg"
      preserveAspectRatio="xMidYMid meet"
      className={className}
    >
      {frame && (
        <>
          <polygon points="50,4 92,28 92,72 50,96 8,72 8,28" fill={ACCENT} opacity="0.08" />
          <polygon
            points="50,4 92,28 92,72 50,96 8,72 8,28"
            fill="none"
            stroke={ACCENT}
            strokeOpacity="0.4"
            strokeWidth="0.8"
            strokeDasharray="2 2"
          />
        </>
      )}

      {shirt === "tee-black" || neck === "turtleneck" ? (
        <rect x="26" y={neck === "turtleneck" ? 88 : 92} width="48" height="12" fill="#1F1B17" />
      ) : shirt === "tee-grey" ? (
        <rect x="26" y="92" width="48" height="12" fill="#5C544A" />
      ) : shirt === "shirt-tie" ? (
        <g>
          <path d="M26,94 L42,90 L50,94 L58,90 L74,94 L74,100 L26,100 Z" fill="#F4F1E8" />
          <path d="M48,90 L52,90 L54,100 L46,100 Z" fill={ACCENT} />
          <path d="M48,90 L50,93 L52,90 Z" fill="#1F1B17" />
        </g>
      ) : shirt === "shirt-blue" ? (
        <g>
          <path d="M26,94 L42,89 L50,93 L58,89 L74,94 L74,100 L26,100 Z" fill="#7AA0BB" />
          <path d="M42,89 L46,98 M58,89 L54,98" stroke="#5A8099" strokeWidth="0.8" />
        </g>
      ) : shirt === "shirt-aloha" ? (
        <g>
          <path d="M26,92 L42,88 L50,92 L58,88 L74,92 L74,100 L26,100 Z" fill="#E8917A" />
          <circle cx="34" cy="96" r="1.2" fill="#F4F1E8" />
          <circle cx="42" cy="98" r="1.2" fill="#F4F1E8" />
          <circle cx="58" cy="96" r="1.2" fill="#F4F1E8" />
          <circle cx="66" cy="98" r="1.2" fill="#F4F1E8" />
        </g>
      ) : shirt === "sweater-vee" ? (
        <g>
          <rect x="26" y="92" width="48" height="12" fill="#9C8E78" />
          <path d="M42,92 L50,98 L58,92 L58,94 L50,100 L42,94 Z" fill="#F4F1E8" />
        </g>
      ) : p.leather ? (
        <path d="M26,92 L40,88 L60,88 L74,92 L74,100 L26,100 Z" fill="#0F0E0C" />
      ) : collar === "jabot" ? (
        <g>
          <rect x="26" y="92" width="48" height="12" fill="#1F1B17" />
          <path d="M40,90 L50,86 L60,90 L60,100 L40,100 Z" fill="#FFFFFF" />
          <path d="M44,90 L46,98 M50,88 L50,100 M54,90 L52,98" stroke="#D8D2C5" strokeWidth="0.8" fill="none" />
        </g>
      ) : collar === "robe" ? (
        <g>
          <rect x="26" y="92" width="48" height="12" fill="#1F1B17" />
          <path d="M42,92 L50,96 L58,92" stroke="#3C342B" strokeWidth="1.2" fill="none" />
        </g>
      ) : (
        <rect x="42" y="86" width="16" height="14" fill={skin} />
      )}

      <path d={faceShape} fill={skin} stroke={STROKE} strokeWidth="1" />

      <ellipse cx="36" cy="68" rx="3" ry="1.6" fill={ACCENT} opacity="0.18" />
      <ellipse cx="64" cy="68" rx="3" ry="1.6" fill={ACCENT} opacity="0.18" />

      {hairDef.top && <path d={hairDef.top} fill={hair} stroke={STROKE} strokeWidth="0.8" />}
      {hairDef.side && (
        <path d={hairDef.side} fill={hair} stroke={STROKE} strokeWidth="0.6" opacity="0.95" />
      )}

      {cut === "bald-shine" && (
        <path d="M40,32 Q50,26 60,32" stroke="rgba(255,255,255,0.45)" strokeWidth="1.2" fill="none" />
      )}

      {showBrow &&
        (p.brow === "bushy" ? (
          <g fill={hair}>
            <path d={`M${eyeXL - 5.5},${browY - 1} q5,-2 11,1 q-5.5,2 -11,-1 Z`} />
            <path d={`M${eyeXR - 5.5},${browY - 1} q5.5,-3 11,1 q-5,2 -11,-1 Z`} />
          </g>
        ) : (
          <g stroke={STROKE} strokeWidth="1.4" strokeLinecap="round">
            <line x1={eyeXL - 4} y1={browY} x2={eyeXL + 4} y2={browY + browArch} />
            <line x1={eyeXR - 4} y1={browY + browArch} x2={eyeXR + 4} y2={browY} />
          </g>
        ))}

      {showEyes && (
        <g fill={STROKE}>
          <circle cx={eyeXL} cy={eyeY} r={eyeR} />
          <circle cx={eyeXR} cy={eyeY} r={eyeR} />
        </g>
      )}

      {p.glasses === "round" && (
        <g fill="none" stroke={STROKE} strokeWidth="1.4">
          <circle cx={eyeXL} cy={eyeY} r="6" fill="rgba(255,255,255,0.18)" />
          <circle cx={eyeXR} cy={eyeY} r="6" fill="rgba(255,255,255,0.18)" />
          <line x1={eyeXL + 6} y1={eyeY} x2={eyeXR - 6} y2={eyeY} />
        </g>
      )}
      {p.glasses === "round-rimless" && (
        <g fill="none" stroke={STROKE} strokeWidth="0.7" opacity="0.85">
          <circle cx={eyeXL} cy={eyeY} r="6" />
          <circle cx={eyeXR} cy={eyeY} r="6" />
          <line x1={eyeXL + 6} y1={eyeY} x2={eyeXR - 6} y2={eyeY} />
        </g>
      )}
      {p.glasses === "round-thick" && (
        <g fill="none" stroke={STROKE} strokeWidth="2.2">
          <circle cx={eyeXL} cy={eyeY} r="6.5" />
          <circle cx={eyeXR} cy={eyeY} r="6.5" />
          <line x1={eyeXL + 6.5} y1={eyeY} x2={eyeXR - 6.5} y2={eyeY} strokeWidth="1.6" />
        </g>
      )}
      {(p.glasses === "square" || p.glasses === "rect") && (
        <g fill="none" stroke={STROKE} strokeWidth="1.4">
          <rect x={eyeXL - 7} y={eyeY - 5} width="14" height="10" rx="1.5" fill="rgba(255,255,255,0.15)" />
          <rect x={eyeXR - 7} y={eyeY - 5} width="14" height="10" rx="1.5" fill="rgba(255,255,255,0.15)" />
          <line x1={eyeXL + 7} y1={eyeY} x2={eyeXR - 7} y2={eyeY} />
        </g>
      )}
      {p.glasses === "rect-thick" && (
        <g fill="none" stroke={STROKE} strokeWidth="2.2">
          <rect x={eyeXL - 7.5} y={eyeY - 5} width="15" height="10" rx="1.5" />
          <rect x={eyeXR - 7.5} y={eyeY - 5} width="15" height="10" rx="1.5" />
          <line x1={eyeXL + 7.5} y1={eyeY} x2={eyeXR - 7.5} y2={eyeY} strokeWidth="1.6" />
        </g>
      )}
      {p.glasses === "square-thick" && (
        <g fill="none" stroke={STROKE} strokeWidth="2.4">
          <rect x={eyeXL - 7} y={eyeY - 6} width="14" height="12" rx="1" />
          <rect x={eyeXR - 7} y={eyeY - 6} width="14" height="12" rx="1" />
          <line x1={eyeXL + 7} y1={eyeY} x2={eyeXR - 7} y2={eyeY} strokeWidth="1.6" />
        </g>
      )}
      {p.glasses === "sun" && (
        <g>
          <rect x={eyeXL - 9} y={eyeY - 5} width="17" height="9" rx="1" fill={STROKE} />
          <rect x={eyeXR - 8} y={eyeY - 5} width="17" height="9" rx="1" fill={STROKE} />
          <line x1={eyeXL + 8} y1={eyeY - 1} x2={eyeXR - 8} y2={eyeY - 1} stroke={STROKE} strokeWidth="1.4" />
          <path d={`M${eyeXL - 7},${eyeY - 3} L${eyeXL + 5},${eyeY - 3.5}`} stroke="rgba(255,255,255,0.25)" strokeWidth="0.8" />
          <path d={`M${eyeXR - 7},${eyeY - 3} L${eyeXR + 5},${eyeY - 3.5}`} stroke="rgba(255,255,255,0.25)" strokeWidth="0.8" />
        </g>
      )}

      <path
        d="M50,62 L48,70 L52,70"
        fill="none"
        stroke={STROKE}
        strokeWidth="1"
        strokeLinejoin="round"
        opacity="0.55"
      />

      {p.moustache && (
        <path d="M40,73 Q50,78 60,73 L58,75 Q50,77 42,75 Z" fill={hair} />
      )}

      <path d={mouthShape} fill="none" stroke={STROKE} strokeWidth="1.4" strokeLinecap="round" />

      {p.beard === "goatee-stubble" && (
        <g>
          <path d="M40,80 C44,86 56,86 60,80 L60,84 C56,88 44,88 40,84 Z" fill={hair} opacity="0.55" />
          <path d="M46,80 L46,86 L54,86 L54,80 Z" fill={hair} opacity="0.85" />
        </g>
      )}
      {p.beard === "stubble" && (
        <path
          d="M36,76 C40,86 60,86 64,76 L64,82 C58,88 42,88 36,82 Z"
          fill={hair}
          opacity="0.4"
        />
      )}
      {(p.beard === "full" || p.beard === "full-grey") && (
        <g>
          <path
            d="M28,66 C30,86 42,94 50,94 C58,94 70,86 72,66 C68,80 56,80 50,80 C44,80 32,80 28,66 Z"
            fill={p.beard === "full-grey" ? "#C8BEB0" : hair}
          />
          <path
            d="M40,73 Q50,77 60,73 L58,75 Q50,77 42,75 Z"
            fill={p.beard === "full-grey" ? "#C8BEB0" : hair}
          />
        </g>
      )}

      {p.earring && <circle cx="74" cy="66" r="1.6" fill={ACCENT} />}
    </svg>
  );
}
