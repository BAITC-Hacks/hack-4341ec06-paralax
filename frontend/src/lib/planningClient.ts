import type {
  PlanningInput,
  PlanningResult,
} from "../types/planning.generated";

const baseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export type Dataset = "synthetic" | "iek";
export type Explanation = {
  summary: string;
  drivers: string[];
  risk: string;
  review_question: string;
  source: "fallback" | "openai";
};

function assertRun(value: unknown): PlanningResult {
  if (
    !value ||
    typeof value !== "object" ||
    !("run_id" in value) ||
    typeof value.run_id !== "string" ||
    !("recommendations" in value) ||
    !Array.isArray(value.recommendations)
  ) {
    throw new Error("Сервер вернул результат в неожиданном формате.");
  }
  return value as PlanningResult;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, init);
  } catch {
    throw new Error("Нет связи с backend. Запустите сервер на порту 8000.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: { reason?: string } };
      detail = body.detail?.reason ?? "";
    } catch {
      // The status remains useful when the server does not return JSON.
    }
    throw new Error(detail || `Сервис вернул ошибку ${response.status}.`);
  }
  return response;
}

export async function createRun(dataset: Dataset): Promise<PlanningResult> {
  if (dataset === "iek") {
    return assertRun(
      await (
        await request("/api/iek/planning-runs", { method: "POST" })
      ).json(),
    );
  }
  const input = (await (
    await request("/api/demo/planning-input")
  ).json()) as PlanningInput;
  return assertRun(
    await (
      await request("/api/planning-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      })
    ).json(),
  );
}

export async function readRun(runId: string): Promise<PlanningResult> {
  return assertRun(
    await (
      await request(`/api/planning-runs/${encodeURIComponent(runId)}`)
    ).json(),
  );
}

export async function updateQuantity(
  runId: string,
  sku: string,
  quantity: number,
): Promise<PlanningResult> {
  if (!Number.isSafeInteger(quantity) || quantity < 0) {
    throw new Error("Введите целое неотрицательное количество.");
  }
  return assertRun(
    await (
      await request(
        `/api/planning-runs/${encodeURIComponent(runId)}/recommendations/${encodeURIComponent(sku)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ selected_quantity: quantity }),
        },
      )
    ).json(),
  );
}

export async function approveRun(runId: string): Promise<PlanningResult> {
  return assertRun(
    await (
      await request(`/api/planning-runs/${encodeURIComponent(runId)}/approve`, {
        method: "POST",
      })
    ).json(),
  );
}

export async function exportRun(runId: string): Promise<Blob> {
  return (
    await request(`/api/planning-runs/${encodeURIComponent(runId)}/export`)
  ).blob();
}

export async function explainRun(
  runId: string,
  sku: string,
): Promise<Explanation> {
  return (await (
    await request(
      `/api/planning-runs/${encodeURIComponent(runId)}/recommendations/${encodeURIComponent(sku)}/explanation`,
      { method: "POST" },
    )
  ).json()) as Explanation;
}
