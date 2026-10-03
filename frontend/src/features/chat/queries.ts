import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import { api, ApiError, readCookie, toApiError, unwrap, type Schemas } from "@/lib/api/client";

export type Conversation = Schemas["ConversationOut"];
export type ChatMessage = Schemas["MessageOut"];
export type Citation = Schemas["CitationOut"];
export type PendingAction = Schemas["PendingActionOut"];
export type MessageLink = Schemas["MessageLink"];
export type Usage = Schemas["UsageOut"];

export const chatKeys = {
  list: ["conversations"] as const,
  one: (id: string) => ["conversation", id] as const,
  usage: (days: number) => ["ai", "usage", days] as const,
};

export function useConversations() {
  return useQuery({
    queryKey: chatKeys.list,
    queryFn: () => unwrap(api.GET("/api/v1/conversations")),
  });
}

export function useConversation(id: string) {
  return useQuery({
    queryKey: chatKeys.one(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
  });
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ConversationCreate"]) =>
      unwrap(api.POST("/api/v1/conversations", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: chatKeys.list }),
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/v1/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: chatKeys.list }),
  });
}

export function usePendingActionMutations(conversationId: string) {
  const qc = useQueryClient();
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: chatKeys.one(conversationId) }),
      // A confirmed delete changes documents, modules, topics and the trash.
      qc.invalidateQueries({ queryKey: ["documents"] }),
      qc.invalidateQueries({ queryKey: ["document"] }),
      qc.invalidateQueries({ queryKey: ["modules"] }),
      qc.invalidateQueries({ queryKey: ["module"] }),
      qc.invalidateQueries({ queryKey: ["topics"] }),
      qc.invalidateQueries({ queryKey: ["trash"] }),
    ]);
  const path = (id: string) => ({ params: { path: { action_id: id } } });
  return {
    confirm: useMutation({
      mutationFn: (id: string) =>
        unwrap(api.POST("/api/v1/pending-actions/{action_id}/confirm", path(id))),
      onSuccess: refresh,
    }),
    cancel: useMutation({
      mutationFn: (id: string) =>
        unwrap(api.POST("/api/v1/pending-actions/{action_id}/cancel", path(id))),
      onSuccess: refresh,
    }),
  };
}

export function useUsage(days: number) {
  return useQuery({
    queryKey: chatKeys.usage(days),
    queryFn: () => unwrap(api.GET("/api/v1/ai/usage", { params: { query: { days } } })),
  });
}

// --- the answer being streamed ------------------------------------------------------

/**
 * An answer in progress. It lives outside React, keyed by conversation, so it
 * keeps streaming if you navigate away and back; the server saves it either
 * way. Once the saved message has been refetched, the live copy is dropped.
 */
export interface LiveAnswer {
  /** Saved messages before this question; later ones are shown live instead. */
  baseline: number;
  question: string;
  text: string;
  statuses: string[];
  actions: PendingAction[];
  links: MessageLink[];
  error?: ApiError;
  stopped: boolean;
  controller: AbortController;
}

const SAVE_POLLS = 5;
const SAVE_POLL_MS = 400;

const live = new Map<string, LiveAnswer>();
const listeners = new Set<() => void>();

function publish(id: string, next: LiveAnswer | undefined) {
  if (next) live.set(id, next);
  else live.delete(id);
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLiveAnswer(id: string): LiveAnswer | undefined {
  return useSyncExternalStore(subscribe, () => live.get(id));
}

export function stopAnswer(id: string) {
  live.get(id)?.controller.abort();
}

interface SseEvent {
  event: string;
  data: unknown;
}

/** Parse complete `event:`/`data:` frames out of a buffer; return the remainder. */
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: SseEvent[] = [];
  for (const frame of frames) {
    let event = "message";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (data) events.push({ event, data: JSON.parse(data) as unknown });
  }
  return { events, rest };
}

/**
 * Send a question and stream the answer into the live store. EventSource
 * cannot POST or send the CSRF header, so this reads the response body.
 */
export async function ask(qc: QueryClient, conversationId: string, question: string): Promise<void> {
  const controller = new AbortController();
  const saved = qc.getQueryData<Schemas["ConversationDetail"]>(chatKeys.one(conversationId));
  let state: LiveAnswer = {
    baseline: saved?.messages.length ?? 0,
    question,
    text: "",
    statuses: [],
    actions: [],
    links: [],
    stopped: false,
    controller,
  };
  const update = (patch: Partial<LiveAnswer>) => {
    state = { ...state, ...patch };
    publish(conversationId, state);
  };
  update({});

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const csrf = readCookie("__Host-rev_csrf");
  if (csrf) headers["X-CSRF-Token"] = csrf;

  try {
    const origin = globalThis.location?.origin ?? "";
    const response = await fetch(`${origin}/api/v1/conversations/${conversationId}/messages`, {
      method: "POST",
      headers,
      body: JSON.stringify({ content: question }),
      credentials: "same-origin",
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      const body: unknown = await response.json().catch(() => undefined);
      throw toApiError(response.status, body);
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const parsed = parseSse(buffer + value);
      buffer = parsed.rest;
      for (const { event, data } of parsed.events) {
        if (event === "status") update({ statuses: [...state.statuses, (data as { text: string }).text] });
        else if (event === "delta") update({ text: state.text + (data as { text: string }).text });
        else if (event === "action") update({ actions: [...state.actions, data as PendingAction] });
        else if (event === "link") update({ links: [...state.links, data as MessageLink] });
        else if (event === "error") {
          const error = data as { code: string; message: string };
          update({ error: new ApiError(200, error.code, error.message) });
        }
      }
    }
  } catch (error) {
    if (controller.signal.aborted) update({ stopped: true });
    else update({ error: error instanceof ApiError ? error : new ApiError(0, "network_error", "The connection was lost.") });
  } finally {
    void qc.invalidateQueries({ queryKey: chatKeys.list });
    void qc.invalidateQueries({ queryKey: ["ai"] });
    // A request refused before anything was saved keeps its error on screen.
    const nothingSaved = state.error !== undefined && state.error.status !== 200;
    if (!nothingSaved) {
      await showSaved(qc, conversationId);
      publish(conversationId, undefined);
    }
  }
}

/**
 * Refetch until the saved answer is there, so the live copy can be swapped
 * for it without a gap. After Stop the server saves a moment later.
 */
async function showSaved(qc: QueryClient, conversationId: string) {
  for (let attempt = 0; attempt < SAVE_POLLS; attempt++) {
    await qc.refetchQueries({ queryKey: chatKeys.one(conversationId) });
    const data = qc.getQueryData<Schemas["ConversationDetail"]>(chatKeys.one(conversationId));
    if (data?.messages.at(-1)?.role === "assistant") return;
    await new Promise((resolve) => setTimeout(resolve, SAVE_POLL_MS));
  }
}

export function dismissLiveError(conversationId: string) {
  publish(conversationId, undefined);
}
