import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, unwrap, type Schemas } from "@/lib/api/client";
import { applyAppearance } from "@/lib/theme";

export type Session = Schemas["SessionOut"];
export const SESSION_KEY = ["auth", "session"] as const;

/** The signed-in session, or null when signed out. */
export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: async (): Promise<Session | null> => {
      try {
        const session = await unwrap(api.GET("/api/v1/auth/session"));
        applyAppearance(session.settings);
        return session;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["LoginRequest"]) =>
      unwrap(api.POST("/api/v1/auth/login", { body })),
    onSuccess: (session) => {
      // Drop anything cached under a previous account before showing data.
      queryClient.clear();
      applyAppearance(session.settings);
      queryClient.setQueryData(SESSION_KEY, session);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/logout")),
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(SESSION_KEY, null);
    },
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["SettingsUpdate"]) =>
      unwrap(api.PATCH("/api/v1/settings", { body })),
    onSuccess: (session) => {
      applyAppearance(session.settings);
      queryClient.setQueryData(SESSION_KEY, session);
    },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: Schemas["ChangePasswordRequest"]) =>
      unwrap(api.POST("/api/v1/auth/password", { body })),
  });
}
