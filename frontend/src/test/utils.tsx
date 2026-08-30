import { render, type RenderResult } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { SWRConfig } from "swr";
import { AuthProvider } from "../auth/AuthContext";

interface Options {
  route?: string;
}

/**
 * Render a component inside the full app shell: fresh SWR cache (no cross-test
 * bleed), an in-memory router, and the real `AuthProvider` (which hits the
 * mocked `/api/auth/me`).
 */
export function renderApp(
  ui: ReactElement,
  { route = "/" }: Options = {},
): RenderResult & { user: ReturnType<typeof userEvent.setup> } {
  const user = userEvent.setup();
  const result = render(
    <SWRConfig
      value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}
    >
      <MemoryRouter
        initialEntries={[route]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </SWRConfig>,
  );
  return { ...result, user };
}
