import { useEffect, useState } from "react";

/** The time now (epoch ms), updated every `intervalMs` for clocks and timers. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return (): void => {
      clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}
