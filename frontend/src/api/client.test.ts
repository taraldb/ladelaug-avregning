import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApiError, get, post } from "./client";
import { server } from "../test/handlers";

describe("api client", () => {
  it("throws ApiError carrying code + message from detail", async () => {
    server.use(
      http.get("/api/thing", () =>
        HttpResponse.json(
          { detail: { code: "reference_taken", message: "Already in use" } },
          { status: 422 },
        ),
      ),
    );

    const err = await get("/api/thing").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 422,
      code: "reference_taken",
      message: "Already in use",
    });
  });

  it("falls back to a status-derived code when detail is malformed", async () => {
    server.use(
      http.get("/api/thing", () =>
        HttpResponse.json({ nope: true }, { status: 404 }),
      ),
    );

    const err = (await get("/api/thing").catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("not_found");
    expect(err.status).toBe(404);
  });

  it("adds X-Requested-With: fetch on writes", async () => {
    let header: string | null = null;
    server.use(
      http.post("/api/thing", ({ request }) => {
        header = request.headers.get("x-requested-with");
        return HttpResponse.json({ ok: true });
      }),
    );

    await post("/api/thing", { a: 1 });
    expect(header).toBe("fetch");
  });

  it("surfaces the rate_limited code on 429", async () => {
    server.use(
      http.get("/api/thing", () =>
        HttpResponse.json(
          { detail: { code: "rate_limited", message: "Too many attempts" } },
          { status: 429, headers: { "Retry-After": "30" } },
        ),
      ),
    );

    const err = (await get("/api/thing").catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("rate_limited");
    expect(err.status).toBe(429);
  });
});
