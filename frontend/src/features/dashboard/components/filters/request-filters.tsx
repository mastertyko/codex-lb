import { RotateCcw, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MultiSelectFilter, type MultiSelectOption } from "@/features/dashboard/components/filters/multi-select-filter";
import { TimeframeSelect } from "@/features/dashboard/components/filters/timeframe-select";
import type { FilterState } from "@/features/dashboard/schemas";
import { REQUEST_KIND_LABEL_KEYS } from "@/features/dashboard/request-log-presentation";

export type RequestFiltersProps = {
  filters: FilterState;
  accountOptions: MultiSelectOption[];
  apiKeyOptions: MultiSelectOption[];
  modelOptions: MultiSelectOption[];
  statusOptions: MultiSelectOption[];
  /** Hide the API key filter (read-only guests receive no key options). */
  showApiKeyFilter?: boolean;
  onSearchChange: (value: string) => void;
  onTimeframeChange: (value: FilterState["timeframe"]) => void;
  onAccountChange: (values: string[]) => void;
  onApiKeyChange: (values: string[]) => void;
  onModelChange: (values: string[]) => void;
  onStatusChange: (values: string[]) => void;
  onRequestKindChange: (values: string[]) => void;
  onTransportChange: (values: string[]) => void;
  onUpstreamTransportChange: (values: string[]) => void;
  onConversationDismiss: () => void;
  onReset: () => void;
};

export function RequestFilters({
  filters,
  accountOptions,
  apiKeyOptions,
  modelOptions,
  statusOptions,
  showApiKeyFilter = true,
  onSearchChange,
  onTimeframeChange,
  onAccountChange,
  onApiKeyChange,
  onModelChange,
  onStatusChange,
  onRequestKindChange,
  onTransportChange,
  onUpstreamTransportChange,
  onConversationDismiss,
  onReset,
}: RequestFiltersProps) {
  const { t } = useTranslation();
  const kindOptions = Object.entries(REQUEST_KIND_LABEL_KEYS)
    .filter(([value]) => value !== "limit_warmup")
    .map(([value, key]) => ({ value, label: t(key) }));
  const transportOptions = [
    { value: "http", label: "HTTP" },
    { value: "websocket", label: "WS" },
    { value: "unknown", label: t("dashboard.filters.unknownTransport") },
  ];

  return (
    <div className="space-y-2 rounded-xl border bg-card p-4">
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" aria-hidden="true" />
          <Input
            value={filters.search}
            onChange={(event) => onSearchChange(event.target.value)}
            className="h-8 pl-9"
            placeholder={t("dashboard.filters.searchPlaceholder")}
          />
        </div>

        <TimeframeSelect value={filters.timeframe} onChange={onTimeframeChange} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <MultiSelectFilter
          label={t("dashboard.filters.accounts")}
          values={filters.accountIds}
          options={accountOptions}
          onChange={onAccountChange}
        />
        {showApiKeyFilter ? (
          <MultiSelectFilter
            label={t("dashboard.filters.apiKeys")}
            values={filters.apiKeyIds}
            options={apiKeyOptions}
            onChange={onApiKeyChange}
          />
        ) : null}
        <MultiSelectFilter
          label={t("dashboard.filters.models")}
          values={filters.modelOptions}
          options={modelOptions}
          onChange={onModelChange}
        />
        <MultiSelectFilter
          label={t("dashboard.filters.statuses")}
          values={filters.statuses}
          options={statusOptions}
          onChange={onStatusChange}
        />
        <MultiSelectFilter
          label={t("dashboard.filters.requestKinds")}
          values={filters.requestKinds}
          options={kindOptions}
          onChange={onRequestKindChange}
        />
        <MultiSelectFilter
          label={t("dashboard.filters.transport")}
          values={filters.transports}
          options={transportOptions}
          onChange={onTransportChange}
        />
        <MultiSelectFilter
          label={t("dashboard.filters.upstreamTransport")}
          values={filters.upstreamTransports}
          options={transportOptions}
          onChange={onUpstreamTransportChange}
        />
        {filters.conversationId ? (
          <Badge variant="outline" className="h-8 gap-1.5 px-3 text-xs font-normal">
            <span className="max-w-[200px] truncate" title={filters.conversationId}>
              {t("dashboard.filters.conversationBadge", { id: filters.conversationId })}
            </span>
            <button
              type="button"
              className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              onClick={onConversationDismiss}
              aria-label={t("dashboard.filters.conversationDismiss")}
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </Badge>
        ) : null}

        <Button type="button" variant="ghost" size="sm" onClick={onReset} className="h-8 gap-1.5 text-xs text-muted-foreground">
          <RotateCcw className="h-3 w-3" aria-hidden="true" />
          {t("common.actions.reset")}
        </Button>
      </div>
    </div>
  );
}
