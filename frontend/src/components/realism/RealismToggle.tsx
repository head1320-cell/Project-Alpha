"use client";

import { Sparkles, Zap } from "lucide-react";

interface Props {
  mode: "ideal" | "reality";
  onChange: (mode: "ideal" | "reality") => void;
}

export default function RealismToggle({ mode, onChange }: Props) {
  const isReality = mode === "reality";

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="text-[10px] uppercase tracking-[0.2em] text-zinc-500 font-medium">
        Reality Bridge — Backtest Truth Filter
      </div>

      <div
        className="
          relative flex items-center bg-[#0f0f0f] rounded-full p-1.5
          border border-zinc-800 shadow-[0_0_40px_rgba(222,255,154,0.08)]
        "
        style={{ width: 480 }}
      >
        {/* Sliding indicator */}
        <div
          className="
            absolute top-1.5 bottom-1.5 rounded-full
            transition-all duration-500 ease-out
          "
          style={{
            width: "calc(50% - 6px)",
            left: isReality ? "calc(50% + 0px)" : "6px",
            background: isReality
              ? "linear-gradient(135deg, #DEFF9A 0%, #b8e673 100%)"
              : "linear-gradient(135deg, #1f1f1f 0%, #2a2a2a 100%)",
            boxShadow: isReality
              ? "0 0 32px rgba(222,255,154,0.5), 0 0 64px rgba(222,255,154,0.2)"
              : "0 0 16px rgba(255,255,255,0.04)",
          }}
        />

        {/* Ideal button */}
        <button
          onClick={() => onChange("ideal")}
          className={`
            relative z-10 flex-1 flex items-center justify-center gap-2
            py-3 px-6 rounded-full text-[11px] font-semibold uppercase tracking-wider
            transition-colors duration-300
            ${!isReality ? "text-[#DEFF9A]" : "text-zinc-500 hover:text-zinc-300"}
          `}
        >
          <Sparkles size={13} />
          <span>Stage 11 · Ideal</span>
        </button>

        {/* Reality button */}
        <button
          onClick={() => onChange("reality")}
          className={`
            relative z-10 flex-1 flex items-center justify-center gap-2
            py-3 px-6 rounded-full text-[11px] font-semibold uppercase tracking-wider
            transition-colors duration-300
            ${isReality ? "text-black" : "text-zinc-500 hover:text-zinc-300"}
          `}
        >
          <Zap size={13} />
          <span>Stage 12 · Production Reality</span>
        </button>
      </div>

      <div className="text-[9px] text-zinc-600 font-mono uppercase tracking-widest">
        {isReality
          ? "5 physics applied — market impact · cash yield · capacity · buying power · regime adaptive"
          : "frictionless backtest — pure mathematical alpha"}
      </div>
    </div>
  );
}
