import { python } from "@codemirror/lang-python";
import { StreamLanguage } from "@codemirror/language";
import { r } from "@codemirror/legacy-modes/mode/r";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

/**
 * CodeMirror 6 for Python or R. Controlled: `value` replaces the document
 * when it changes from outside (reset, load your last submission).
 */
export function CodeEditor({
  value,
  onChange,
  language,
  label,
  onRun,
}: {
  value: string;
  onChange: (value: string) => void;
  language: "python" | "r";
  label: string;
  /** Ctrl+Enter (Cmd+Enter on a Mac). */
  onRun?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const latest = useRef({ onChange, onRun });
  latest.current = { onChange, onRun };

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          language === "python" ? python() : StreamLanguage.define(r),
          EditorView.contentAttributes.of({ "aria-label": label }),
          EditorView.domEventHandlers({
            keydown: (event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && latest.current.onRun) {
                event.preventDefault();
                latest.current.onRun();
                return true;
              }
              return false;
            },
          }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) latest.current.onChange(update.state.doc.toString());
          }),
          EditorView.theme({
            "&": { fontSize: "13px", border: "1px solid var(--color-border)", borderRadius: "6px" },
            ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", minHeight: "14rem" },
          }),
        ],
      }),
    });
    view.current = editor;
    return () => editor.destroy();
    // The editor is created once per language; `value` is synced below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, label]);

  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} className="overflow-hidden" />;
}
