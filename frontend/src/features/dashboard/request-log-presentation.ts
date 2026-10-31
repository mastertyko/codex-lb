import type { RequestLog } from "@/features/dashboard/schemas";
import { formatCurrency } from "@/utils/formatters";

export const REQUEST_KIND_LABEL_KEYS: Record<string, string> = {
  normal: "dashboard.requests.kinds.normal",
  prewarm: "dashboard.requests.kinds.prewarm",
  warmup: "dashboard.requests.kinds.warmup",
  limit_warmup: "dashboard.requests.kinds.warmup",
  compaction: "dashboard.requests.kinds.compaction",
  realtime_live: "dashboard.requests.kinds.realtime",
  codex_control_alpha_search: "dashboard.requests.webSearch",
};

const preciseCurrency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
});

export function formatRequestCost(value: number | null | undefined, detail = false): string {
  if (value == null || !Number.isFinite(value)) {
    return formatCurrency(null);
  }
  if (value > 0 && value < (detail ? 0.000001 : 0.005)) {
    return detail ? "< $0.000001" : "< $0.01";
  }
  return detail ? preciseCurrency.format(value) : formatCurrency(value);
}

type PricingTier = "standard" | "priority" | "flex" | "ultrafast";
type EstimateBasis = "upstream" | "requested" | "recorded" | "unknown" | "provider" | "unavailable";

function pricingTier(tier: string | null | undefined): PricingTier | null {
  switch (tier?.trim().toLowerCase()) {
    case "default":
    case "auto":
      return "standard";
    case "priority":
    case "fast":
      return "priority";
    case "flex":
      return "flex";
    case "ultrafast":
      return "ultrafast";
    default:
      return null;
  }
}

export function requestCostPresentation(request: RequestLog): { tier: PricingTier | null; basis: EstimateBasis } {
  if (request.costUsd == null || !Number.isFinite(request.costUsd)) {
    return { tier: null, basis: "unavailable" };
  }
  if (request.modelSourceId || request.modelSourceKind) {
    return { tier: null, basis: "provider" };
  }
  const tier = pricingTier(request.serviceTier);
  if (!tier) {
    return { tier: null, basis: "unknown" };
  }
  if (tier === pricingTier(request.actualServiceTier)) {
    return { tier, basis: "upstream" };
  }
  if (tier === pricingTier(request.requestedServiceTier)) {
    return { tier, basis: "requested" };
  }
  return { tier, basis: "recorded" };
}
