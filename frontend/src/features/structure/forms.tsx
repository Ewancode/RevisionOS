import { useState, type FormEvent } from "react";

import { Button, ErrorText, Field, Modal } from "@/components/ui";

import { useCreateModule, useCreateYear, useUpdateModule, type Module, type Year } from "./queries";

/** UK academic year default: late September to mid June. */
function defaultYear(now = new Date()) {
  const start = now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1;
  return {
    label: `${start}/${String(start + 1).slice(2)}`,
    start_date: `${start}-09-21`,
    end_date: `${start + 1}-06-12`,
  };
}

export function YearDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (year: Year) => void;
}) {
  const create = useCreateYear();
  const [form, setForm] = useState(defaultYear);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const year = await create.mutateAsync(form).catch(() => undefined);
    if (year) {
      onCreated?.(year);
      onOpenChange(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="New academic year">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field
          label="Label"
          hint="For example 2026/27 — Year 1"
          required
          maxLength={40}
          value={form.label}
          onChange={(e) => setForm({ ...form, label: e.target.value })}
        />
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Starts"
            type="date"
            required
            value={form.start_date}
            onChange={(e) => setForm({ ...form, start_date: e.target.value })}
          />
          <Field
            label="Ends"
            type="date"
            required
            value={form.end_date}
            onChange={(e) => setForm({ ...form, end_date: e.target.value })}
          />
        </div>
        <ErrorText error={create.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Create year
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface ModuleForm {
  code: string;
  title: string;
  subject_tag: string;
  credits: string;
  colour: string;
}

function toForm(module?: Module): ModuleForm {
  return {
    code: module?.code ?? "",
    title: module?.title ?? "",
    subject_tag: module?.subject_tag ?? "",
    credits: module?.credits?.toString() ?? "",
    colour: module?.colour ?? "#4f46e5",
  };
}

function fromForm(form: ModuleForm) {
  return {
    code: form.code,
    title: form.title,
    subject_tag: form.subject_tag.trim() || null,
    credits: form.credits === "" ? null : Number(form.credits),
    colour: form.colour,
  };
}

function ModuleFields({ form, setForm }: { form: ModuleForm; setForm: (f: ModuleForm) => void }) {
  return (
    <>
      <div className="grid grid-cols-[1fr_2fr] gap-3">
        <Field
          label="Code"
          required
          maxLength={20}
          placeholder="MATH103"
          value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value })}
        />
        <Field
          label="Title"
          required
          maxLength={200}
          placeholder="Linear Algebra"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
      </div>
      <div className="grid grid-cols-[2fr_1fr_auto] gap-3">
        <Field
          label="Subject (optional)"
          hint="Groups modules in the sidebar"
          maxLength={60}
          placeholder="Mathematics"
          value={form.subject_tag}
          onChange={(e) => setForm({ ...form, subject_tag: e.target.value })}
        />
        <Field
          label="Credits"
          type="number"
          min={0}
          max={120}
          value={form.credits}
          onChange={(e) => setForm({ ...form, credits: e.target.value })}
        />
        <Field
          label="Colour"
          type="color"
          className="h-9 w-12 rounded-md border border-border bg-bg p-1"
          value={form.colour}
          onChange={(e) => setForm({ ...form, colour: e.target.value })}
        />
      </div>
    </>
  );
}

export function NewModuleDialog({
  open,
  onOpenChange,
  yearId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  yearId: string;
  onCreated?: (module: Module) => void;
}) {
  const create = useCreateModule();
  const [form, setForm] = useState(() => toForm());

  async function submit(event: FormEvent) {
    event.preventDefault();
    const module = await create
      .mutateAsync({ academic_year_id: yearId, ...fromForm(form) })
      .catch(() => undefined);
    if (module) {
      setForm(toForm());
      onCreated?.(module);
      onOpenChange(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="New module">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <ModuleFields form={form} setForm={setForm} />
        <ErrorText error={create.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            Create module
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function EditModuleDialog({
  open,
  onOpenChange,
  module,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  module: Module;
}) {
  const update = useUpdateModule(module.id);
  const [form, setForm] = useState(() => toForm(module));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const saved = await update.mutateAsync(fromForm(form)).catch(() => undefined);
    if (saved) onOpenChange(false);
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={`Edit ${module.code}`}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <ModuleFields form={form} setForm={setForm} />
        <ErrorText error={update.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={update.isPending}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}
