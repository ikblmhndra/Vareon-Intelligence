"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/providers/auth-provider";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { getActiveClientId } from "@/lib/auth/client-id";

type Schemas = components["schemas"];
export type DashboardMap = Schemas["DashboardMap"];
export type DashboardAttention = Schemas["DashboardAttention"];
export type TrendingResponse = Schemas["TrendingResponse"];
export type RansomwareOverview = Schemas["RansomwareOverview"];
export type CveExposure = Schemas["CveExposure"];

/** Client aktif ikut masuk query key: ganti client (reload penuh) tidak boleh memakai cache client lain. */
function useClientKey(): string | null {
  const { user } = useAuth();
  return getActiveClientId() ?? user?.client_ids[0] ?? null;
}

const DASHBOARD_PATHS = {
  map: "/api/dashboard/map",
  attention: "/api/dashboard/attention",
  trending: "/api/dashboard/trending",
  ransomware: "/api/dashboard/ransomware",
  "cve-exposure": "/api/dashboard/cve-exposure",
} as const;

function useDashboardEndpoint<T>(
  name: keyof typeof DASHBOARD_PATHS,
  days: number | null,
  incidentOnly?: boolean,
) {
  const clientId = useClientKey();
  return useQuery({
    queryKey: ["dashboard", name, days, incidentOnly ?? null, clientId],
    queryFn: async () => {
      // Kelima rute punya bentuk query sama (`days`); `incident_only` hanya dikirim untuk
      // attention (brief ikut toggle KPI). Tipe respons dipasang lewat generik hook.
      const { data, error } = await api.GET(DASHBOARD_PATHS[name], {
        params: { query: { days: days ?? undefined, ...(incidentOnly !== undefined && { incident_only: incidentOnly }) } },
      });
      if (error) throw error;
      return data as unknown as T;
    },
    // Ganti periode: tampilkan data lama sampai yang baru datang.
    placeholderData: keepPreviousData,
  });
}

export const useDashboardMap = (days: number | null) => useDashboardEndpoint<DashboardMap>("map", days);
export const useDashboardAttention = (days: number | null, incidentOnly: boolean) =>
  useDashboardEndpoint<DashboardAttention>("attention", days, incidentOnly);
export const useDashboardTrending = (days: number | null) =>
  useDashboardEndpoint<TrendingResponse>("trending", days);
export const useDashboardRansomware = (days: number | null) =>
  useDashboardEndpoint<RansomwareOverview>("ransomware", days);
export const useCveExposure = (days: number | null) =>
  useDashboardEndpoint<CveExposure>("cve-exposure", days);
