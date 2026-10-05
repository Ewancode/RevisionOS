/** Web Push in this browser: subscribe through the service worker. */

export type PushSupport = "supported" | "insecure" | "unsupported";

export function pushSupport(): PushSupport {
  if (typeof window === "undefined" || !("serviceWorker" in navigator) || !("PushManager" in window)) {
    return "unsupported";
  }
  return window.isSecureContext ? "supported" : "insecure";
}

/** VAPID public keys are URL-safe base64; the browser wants bytes. */
export function keyBytes(base64url: string): Uint8Array {
  const padded = base64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (base64url.length % 4)) % 4);
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (pushSupport() !== "supported") return null;
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

/** Ask permission and subscribe; returns what the server needs to store. */
export async function subscribe(publicKey: string): Promise<{ endpoint: string; keys: { p256dh: string; auth: string } }> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notifications are blocked for this site. Allow them in your browser's site settings.");
  }
  const registration = await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(publicKey) as BufferSource,
    }));
  const json = subscription.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
  return { endpoint: json.endpoint, keys: json.keys };
}

/** A label so you can tell your devices apart. */
export function deviceLabel(): string {
  const ua = navigator.userAgent;
  const platform = /iPhone|iPad/.test(ua) ? "iPhone or iPad" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : "This device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "browser";
  return `${platform} · ${browser}`;
}
