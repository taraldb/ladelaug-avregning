import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { resetMockState, server } from "./handlers";

// Node's global fetch (undici) can't resolve the relative URLs our client uses
// ("/api/..."), and jsdom doesn't provide fetch. Normalise to an absolute URL
// against the jsdom origin BEFORE MSW wraps fetch in `server.listen()`.
const origin =
  typeof window !== "undefined" ? window.location.origin : "http://localhost";
const realFetch = globalThis.fetch;
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  if (typeof input === "string" && input.startsWith("/")) {
    return realFetch(origin + input, init);
  }
  return realFetch(input, init);
}) as typeof fetch;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockState();
});

afterAll(() => server.close());
