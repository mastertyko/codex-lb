import { describe, expect, it } from "vitest";

import {
  ApiKeyCreateRequestSchema,
  ApiKeyCreateResponseSchema,
  ApiKeySchema,
  ApiKeyUpdateRequestSchema,
  LimitRuleCreateSchema,
  ModelItemSchema,
} from "@/features/api-keys/schemas";

const ISO = "2026-01-01T00:00:00+00:00";

describe("ApiKeySchema", () => {
  it("parses api key entity payload with limits", () => {
    const parsed = ApiKeySchema.parse({
      id: "key-1",
      name: "Service Key",
      keyPrefix: "sk-live",
      allowedModels: ["gpt-4.1"],
      applyToCodexModel: true,
      expiresAt: null,
      isActive: true,
      createdAt: ISO,
      lastUsedAt: ISO,
      limits: [
        {
          id: 1,
          limitType: "total_tokens",
          limitWindow: "weekly",
          maxValue: 100000,
          currentValue: 1200,
          modelFilter: null,
          resetAt: ISO,
        },
      ],
    });

    expect(parsed.id).toBe("key-1");
    expect(parsed.allowedModels).toEqual(["gpt-4.1"]);
    expect(parsed.applyToCodexModel).toBe(true);
    expect(parsed.limits).toHaveLength(1);
    expect(parsed.limits[0].limitType).toBe("total_tokens");
    expect(parsed.trafficClass).toBe("foreground");
  });

  it("defaults limits to empty array when not provided", () => {
    const parsed = ApiKeySchema.parse({
      id: "key-1",
      name: "Service Key",
      keyPrefix: "sk-live",
      allowedModels: null,
      expiresAt: null,
      isActive: true,
      createdAt: ISO,
      lastUsedAt: null,
    });

    expect(parsed.limits).toEqual([]);
    expect(parsed.applyToCodexModel).toBe(false);
    expect(parsed.pooledRemainingPercentPrimary).toBeNull();
    expect(parsed.pooledRemainingPercentSecondary).toBeNull();
    expect(parsed.pooledCapacityCreditsPrimary).toBe(0);
  });

  it("parses pooled credit fields", () => {
    const parsed = ApiKeySchema.parse({
      id: "key-1",
      name: "Service Key",
      keyPrefix: "sk-live",
      allowedModels: null,
      expiresAt: null,
      isActive: true,
      createdAt: ISO,
      lastUsedAt: null,
      pooledRemainingPercentPrimary: 67.5,
      pooledRemainingPercentSecondary: 85.0,
      pooledCapacityCreditsPrimary: 225.0,
    });

    expect(parsed.pooledRemainingPercentPrimary).toBe(67.5);
    expect(parsed.pooledRemainingPercentSecondary).toBe(85.0);
    expect(parsed.pooledCapacityCreditsPrimary).toBe(225.0);
  });

  it("parses assigned model source ids", () => {
    const parsed = ApiKeySchema.parse({
      id: "key-1",
      name: "Service Key",
      keyPrefix: "sk-live",
      allowedModels: null,
      sourceAssignmentScopeEnabled: true,
      assignedSourceIds: ["src_vllm"],
      expiresAt: null,
      isActive: true,
      createdAt: ISO,
      lastUsedAt: null,
    });

    expect(parsed.sourceAssignmentScopeEnabled).toBe(true);
    expect(parsed.assignedSourceIds).toEqual(["src_vllm"]);
  });

  it("defaults usage sections to both visible sections", () => {
    const parsed = ApiKeySchema.parse({
      id: "key-1",
      name: "Service Key",
      keyPrefix: "sk-live",
      allowedModels: null,
      expiresAt: null,
      isActive: true,
      createdAt: ISO,
      lastUsedAt: null,
    });

    expect(parsed.usageSections).toBe("upstream_limits,account_pool_usage");
  });
});

describe("ApiKeyCreateResponseSchema", () => {
  it("requires plain key field in create response", () => {
    const parsed = ApiKeyCreateResponseSchema.parse({
      id: "key-2",
      name: "New Key",
      keyPrefix: "sk-test",
      key: "sk-test-plaintext",
      allowedModels: null,
      expiresAt: null,
      isActive: true,
      createdAt: ISO,
      lastUsedAt: null,
      limits: [],
    });

    expect(parsed.key).toBe("sk-test-plaintext");
  });
});

describe("ApiKeyCreateRequestSchema", () => {
  it("accepts optional assigned accounts", () => {
    const parsed = ApiKeyCreateRequestSchema.parse({
      name: "Scoped Key",
      assignedAccountIds: ["acc_primary"],
      usageSections: "account_pool_usage",
    });

    expect(parsed.assignedAccountIds).toEqual(["acc_primary"]);
    expect(parsed.usageSections).toBe("account_pool_usage");
  });

  it("accepts optional assigned model sources", () => {
    const parsed = ApiKeyCreateRequestSchema.parse({
      name: "Source Scoped Key",
      assignedSourceIds: ["src_vllm"],
    });

    expect(parsed.assignedSourceIds).toEqual(["src_vllm"]);
  });

  it("accepts opportunistic traffic class in create payload", () => {
    const parsed = ApiKeyCreateRequestSchema.parse({
      name: "Opportunistic Key",
      trafficClass: "opportunistic",
    });

    expect(parsed.trafficClass).toBe("opportunistic");
  });

  it("rejects invalid traffic class in create payload", () => {
    const result = ApiKeyCreateRequestSchema.safeParse({
      name: "Bad Key",
      trafficClass: "bulk",
    });

    expect(result.success).toBe(false);
  });
});

describe("ApiKeyUpdateRequestSchema", () => {
  it("accepts partial update payload", () => {
    const parsed = ApiKeyUpdateRequestSchema.parse({
      name: "Updated Key",
      allowedModels: ["gpt-4.1-mini"],
      applyToCodexModel: true,
      weeklyTokenLimit: 50000,
      expiresAt: ISO,
      isActive: false,
      usageSections: "upstream_limits",
    });

    expect(parsed.name).toBe("Updated Key");
    expect(parsed.applyToCodexModel).toBe(true);
    expect(parsed.isActive).toBe(false);
    expect(parsed.usageSections).toBe("upstream_limits");
  });

  it("rejects invalid weeklyTokenLimit", () => {
    const result = ApiKeyUpdateRequestSchema.safeParse({
      weeklyTokenLimit: 0,
    });

    expect(result.success).toBe(false);
  });

  it("accepts limits array", () => {
    const parsed = ApiKeyUpdateRequestSchema.parse({
      limits: [
        { limitType: "cost_usd", limitWindow: "daily", maxValue: 500000 },
      ],
    });

    expect(parsed.limits).toHaveLength(1);
    expect(parsed.limits![0].limitType).toBe("cost_usd");
  });

  it("accepts resetUsage flag", () => {
    const parsed = ApiKeyUpdateRequestSchema.parse({
      resetUsage: true,
    });

    expect(parsed.resetUsage).toBe(true);
  });

  it("accepts clearing assigned model sources", () => {
    const parsed = ApiKeyUpdateRequestSchema.parse({
      assignedSourceIds: [],
    });

    expect(parsed.assignedSourceIds).toEqual([]);
  });

  it("accepts opportunistic traffic class in update payload", () => {
    const parsed = ApiKeyUpdateRequestSchema.parse({
      trafficClass: "opportunistic",
    });

    expect(parsed.trafficClass).toBe("opportunistic");
  });
});

describe("reasoning effort schemas", () => {
  it("accepts max across API-key and dashboard model contracts", () => {
    const apiKey = ApiKeySchema.parse({
      id: "key-max",
      name: "Max policy",
      keyPrefix: "sk-max",
      allowedModels: ["gpt-5.6-sol"],
      enforcedReasoningEffort: "max",
      expiresAt: null,
      isActive: true,
      createdAt: ISO,
      lastUsedAt: null,
    });
    const createRequest = ApiKeyCreateRequestSchema.parse({
      name: "Max policy",
      enforcedReasoningEffort: "max",
    });
    const updateRequest = ApiKeyUpdateRequestSchema.parse({
      enforcedReasoningEffort: "max",
    });
    const model = ModelItemSchema.parse({
      id: "gpt-5.6-sol",
      name: "GPT-5.6 Sol",
      supportedReasoningEfforts: ["low", "max"],
      defaultReasoningEffort: "max",
    });

    expect(apiKey.enforcedReasoningEffort).toBe("max");
    expect(createRequest.enforcedReasoningEffort).toBe("max");
    expect(updateRequest.enforcedReasoningEffort).toBe("max");
    expect(model.supportedReasoningEfforts).toEqual(["low", "max"]);
    expect(model.defaultReasoningEffort).toBe("max");
  });

  it("rejects native-only ultra on wire-policy contracts", () => {
    expect(
      ApiKeyCreateRequestSchema.safeParse({
        name: "Native-only policy",
        enforcedReasoningEffort: "ultra",
      }).success,
    ).toBe(false);
    expect(
      ApiKeyUpdateRequestSchema.safeParse({
        enforcedReasoningEffort: "ultra",
      }).success,
    ).toBe(false);
    expect(
      ModelItemSchema.safeParse({
        id: "gpt-5.6-sol",
        name: "GPT-5.6 Sol",
        supportedReasoningEfforts: ["max", "ultra"],
      }).success,
    ).toBe(false);
  });
});

describe("LimitRuleCreateSchema", () => {
  it("parses valid limit rule", () => {
    const parsed = LimitRuleCreateSchema.parse({
      limitType: "total_tokens",
      limitWindow: "weekly",
      maxValue: 1000000,
    });

    expect(parsed.limitType).toBe("total_tokens");
    expect(parsed.maxValue).toBe(1000000);
  });

  it("rejects invalid limit type", () => {
    const result = LimitRuleCreateSchema.safeParse({
      limitType: "invalid",
      limitWindow: "weekly",
      maxValue: 100,
    });
    expect(result.success).toBe(false);
  });

  it("rejects non-positive maxValue", () => {
    const result = LimitRuleCreateSchema.safeParse({
      limitType: "total_tokens",
      limitWindow: "weekly",
      maxValue: 0,
    });
    expect(result.success).toBe(false);
  });
});
