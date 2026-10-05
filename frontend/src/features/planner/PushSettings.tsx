import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import type { ReactNode } from "react";

import { Button, ErrorText } from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";

import { currentSubscription, deviceLabel, pushSupport, subscribe } from "./push";

const keys = { config: ["push", "config"] as const, device: ["push", "device"] as const };

/** Reminders on this device even when Revision OS is closed (Web Push). */
export function PushSettings() {
  const qc = useQueryClient();
  const support = pushSupport();
  const config = useQuery({ queryKey: keys.config, queryFn: () => unwrap(api.GET("/api/v1/push/config")) });
  const device = useQuery({ queryKey: keys.device, queryFn: currentSubscription, enabled: support === "supported" });
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["push"] })]);

  const on = useMutation({
    mutationFn: async () => {
      const key = config.data?.public_key;
      if (!key) throw new Error("Push is not set up on the server.");
      const sub = await subscribe(key);
      await unwrap(api.POST("/api/v1/push/subscriptions", { body: { ...sub, label: deviceLabel() } }));
    },
    onSuccess: refresh,
  });
  const off = useMutation({
    mutationFn: async () => {
      const sub = await currentSubscription();
      if (!sub) return;
      await unwrap(api.POST("/api/v1/push/unsubscribe", { body: { endpoint: sub.endpoint } }));
      await sub.unsubscribe();
    },
    onSuccess: refresh,
  });
  const test = useMutation({ mutationFn: () => unwrap(api.POST("/api/v1/push/test")) });

  let body: ReactNode;
  if (support === "unsupported") {
    body = <p className="text-sm text-muted">This browser cannot receive push notifications.</p>;
  } else if (support === "insecure") {
    body = (
      <p className="text-sm text-muted">
        Push needs a secure (HTTPS) connection. It works on this computer at localhost, and on your phone once
        Revision OS is deployed.
      </p>
    );
  } else if (config.data && !config.data.enabled) {
    body = (
      <p className="text-sm text-muted">
        Push is not set up on the server yet: run <code>make vapid-keys</code>, then restart the API and scheduler.
      </p>
    );
  } else if (!device.data && Notification.permission === "denied") {
    body = (
      <p className="text-sm text-muted">
        Notifications are blocked for this site. Allow them in your browser's site settings, then reload.
      </p>
    );
  } else if (device.data) {
    body = (
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm">On for this device.</p>
        <Button size="sm" onClick={() => test.mutate()} disabled={test.isPending}>
          Send a test
        </Button>
        <Button size="sm" variant="ghost" onClick={() => off.mutate()} disabled={off.isPending}>
          Turn off
        </Button>
        {test.data && (
          <p role="status" className="text-xs text-muted">
            Sent to {test.data.delivered} device{test.data.delivered === 1 ? "" : "s"}.
          </p>
        )}
      </div>
    );
  } else {
    body = (
      <div>
        <Button size="sm" onClick={() => on.mutate()} disabled={on.isPending || !config.data}>
          <BellRing size={14} /> Turn on for this device
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2" role="group" aria-label="Notifications on this device">
      <h3 className="text-sm font-medium">On this device</h3>
      <p className="text-xs text-muted">
        Reminders arrive here even when Revision OS is closed, with the same switches and quiet hours as above.
        {config.data && config.data.devices > 0 ? ` ${config.data.devices} device(s) receive them.` : ""}
      </p>
      {body}
      <ErrorText error={on.error ?? off.error ?? test.error ?? config.error} />
    </div>
  );
}
