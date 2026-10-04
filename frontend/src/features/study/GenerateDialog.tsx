import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { Button, ErrorText, Modal } from "@/components/ui";
import { useDocuments } from "@/features/documents/queries";
import { useTopicTree, type TopicNode } from "@/features/structure/queries";

import {
  DIFFICULTIES,
  MATERIAL_KINDS,
  QUESTION_TYPES,
  useGenerate,
  type Difficulty,
  type GenerateRequest,
  type MaterialKind,
  type QuestionType,
} from "./queries";

export function flattenTopics(nodes: TopicNode[], depth = 0): { id: string; title: string }[] {
  return nodes.flatMap((n) => [
    { id: n.id, title: `${"— ".repeat(depth)}${n.title}` },
    ...flattenTopics(n.children ?? [], depth + 1),
  ]);
}

const KIND_TITLE = {
  material: "revision material",
  questions: "practice questions",
  flashcards: "flashcards",
  coding: "coding exercises",
};

const field = "flex flex-col gap-1 text-sm";
const control = "h-9 rounded-md border border-border bg-bg px-2 text-sm";

/**
 * Ask Claude for a draft. Claude writes from your materials (chosen files,
 * or the best passages for the topic); you preview the draft before saving.
 */
export function GenerateDialog({
  open,
  onOpenChange,
  moduleId,
  kind,
  improveMaterialId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  moduleId: string;
  kind: GenerateRequest["kind"];
  improveMaterialId?: string;
}) {
  const navigate = useNavigate();
  const generate = useGenerate();
  const topics = useTopicTree(moduleId);
  const documents = useDocuments(moduleId);
  const [topicId, setTopicId] = useState("");
  const [materialKind, setMaterialKind] = useState<MaterialKind>("guide");
  const [count, setCount] = useState(kind === "coding" ? 2 : 8);
  const [language, setLanguage] = useState<"python" | "r">("python");
  const [difficulty, setDifficulty] = useState<Difficulty | "mixed">("mixed");
  const [types, setTypes] = useState<QuestionType[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [instructions, setInstructions] = useState("");
  const ready = (documents.data ?? []).filter((d) => d.status === "ready");

  const submit = async () => {
    const draft = await generate.mutateAsync({
      module_id: moduleId,
      topic_id: topicId || null,
      kind,
      material_kind: kind === "material" && !improveMaterialId ? materialKind : null,
      count: kind === "material" ? null : count,
      difficulty: kind === "questions" || kind === "coding" ? difficulty : null,
      language: kind === "coding" ? language : null,
      types: kind === "questions" && types.length ? types : null,
      document_ids: files,
      instructions: instructions.trim() || null,
      improve_material_id: improveMaterialId ?? null,
    });
    onOpenChange(false);
    await navigate({ to: "/drafts/$draftId", params: { draftId: draft.id } });
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={improveMaterialId ? "Improve with Claude" : `Generate ${KIND_TITLE[kind]}`}
      description={
        improveMaterialId
          ? "Claude writes an improved version from your materials. Your original stays as it is."
          : "Claude writes a draft from your materials. You preview it before anything is saved."
      }
    >
      <form
        className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {!improveMaterialId && (
          <label className={field}>
            Topic
            <select className={control} value={topicId} onChange={(e) => setTopicId(e.target.value)}>
              <option value="">Whole module</option>
              {flattenTopics(topics.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "material" && !improveMaterialId && (
          <label className={field}>
            Kind
            <select
              className={control}
              value={materialKind}
              onChange={(e) => setMaterialKind(e.target.value as MaterialKind)}
            >
              {MATERIAL_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "coding" && (
          <label className={field}>
            Language
            <select className={control} value={language} onChange={(e) => setLanguage(e.target.value as "python" | "r")}>
              <option value="python">Python</option>
              <option value="r">R</option>
            </select>
          </label>
        )}
        {kind !== "material" && (
          <label className={field}>
            How many
            <input
              type="number"
              min={1}
              max={kind === "coding" ? 4 : 20}
              className={control}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            />
          </label>
        )}
        {kind === "questions" && (
          <>
            <label className={field}>
              Difficulty
              <select
                className={control}
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value as Difficulty | "mixed")}
              >
                <option value="mixed">Mixed</option>
                {DIFFICULTIES.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="flex flex-col gap-1 text-sm">
              <legend className="mb-1">Types (none ticked: Claude chooses)</legend>
              <div className="grid grid-cols-2 gap-1">
                {QUESTION_TYPES.map((t) => (
                  <label key={t.value} className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={types.includes(t.value)}
                      onChange={(e) =>
                        setTypes((all) => (e.target.checked ? [...all, t.value] : all.filter((x) => x !== t.value)))
                      }
                    />
                    {t.label}
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        )}
        {ready.length > 0 && (
          <fieldset className="flex flex-col gap-1 text-sm">
            <legend className="mb-1">From these files (optional)</legend>
            {ready.map((d) => (
              <label key={d.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={files.includes(d.id)}
                  onChange={(e) =>
                    setFiles((all) => (e.target.checked ? [...all, d.id] : all.filter((x) => x !== d.id)))
                  }
                />
                {d.original_filename}
                {d.week !== null && <span className="text-muted">· week {d.week}</span>}
              </label>
            ))}
          </fieldset>
        )}
        <label className={field}>
          Anything to focus on? (optional)
          <textarea
            className="min-h-16 rounded-md border border-border bg-bg p-2 text-sm"
            value={instructions}
            maxLength={2000}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="e.g. the ratio and root tests, with worked examples"
          />
        </label>
        <ErrorText error={generate.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={generate.isPending}>
            {generate.isPending ? "Starting…" : "Generate"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
