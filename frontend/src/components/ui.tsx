/** Small shared UI primitives. Radix supplies the behaviour for dialogs. */
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import {
  forwardRef,
  useId,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:opacity-90",
  secondary: "border border-border bg-bg hover:bg-surface",
  ghost: "hover:bg-surface",
  danger: "bg-danger text-on-danger hover:opacity-90",
};

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }
>(function Button({ variant = "secondary", size = "md", className = "", type = "button", ...props }, ref) {
  const sizing = size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-3 text-sm";
  return (
    <button
      ref={ref}
      type={type}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md font-medium disabled:opacity-50 ${sizing} ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
});

export function Field({
  label,
  hint,
  error,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className="h-9 rounded-md border border-border bg-bg px-2 text-sm"
        {...props}
      />
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <p role="alert" className="text-sm text-danger">
      {message}
    </p>
  );
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-bg p-5 shadow-xl">
          <div className="mb-3 flex items-start justify-between gap-4">
            <Dialog.Title className="text-base font-semibold">{title}</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm" aria-label="Close">
                <X size={16} />
              </Button>
            </Dialog.Close>
          </div>
          {description ? (
            <Dialog.Description className="mb-4 text-sm text-muted">{description}</Dialog.Description>
          ) : (
            <Dialog.Description className="sr-only">{title}</Dialog.Description>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Every delete goes through this: nothing is removed until the user
 * confirms (SPEC §17). Deleted items go to the trash for 30 days.
 */
export function ConfirmDelete({
  open,
  onOpenChange,
  thing,
  detail,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  thing: string;
  detail?: string;
  onConfirm: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete ${thing}?`}
      description={detail ?? "It moves to the trash, where you can restore it for 30 days."}
    >
      <ErrorText error={error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button
          variant="danger"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await onConfirm();
              onOpenChange(false);
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Delete
        </Button>
      </div>
    </Modal>
  );
}
