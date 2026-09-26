import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { setViewport } from "../test/setup";
import { useIsCompact, useIsNarrow, useMediaQuery } from "./useMediaQuery";

describe("useMediaQuery", () => {
  it("reports the desktop branch by default", () => {
    expect(renderHook(() => useMediaQuery("(min-width: 640px)")).result.current).toBe(
      true,
    );
    expect(renderHook(() => useIsNarrow()).result.current).toBe(false);
    expect(renderHook(() => useIsCompact()).result.current).toBe(false);
  });

  it("reports the mobile branch after setViewport('mobile')", () => {
    setViewport("mobile");
    expect(renderHook(() => useMediaQuery("(min-width: 640px)")).result.current).toBe(
      false,
    );
    expect(renderHook(() => useIsNarrow()).result.current).toBe(true);
    expect(renderHook(() => useIsCompact()).result.current).toBe(true);
  });

  it("falls back to the desktop branch when matchMedia is missing", () => {
    const real = window.matchMedia;
    // @ts-expect-error — deliberately removing it to exercise the fallback
    delete window.matchMedia;
    try {
      expect(renderHook(() => useIsNarrow()).result.current).toBe(false);
    } finally {
      window.matchMedia = real;
    }
  });
});
