import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MathMarkdown } from "./MathMarkdown";

function html(markdown: string) {
  const { container } = render(<MathMarkdown>{markdown}</MathMarkdown>);
  return container;
}

describe("MathMarkdown", () => {
  it("renders inline and display maths with KaTeX", () => {
    const view = html("Area $\\int_0^1 x^2\\,dx$ and\n\n$$\\begin{pmatrix} 1 & 0 \\\\ 0 & 1 \\end{pmatrix}$$");
    expect(view.querySelectorAll(".katex").length).toBe(2);
    expect(view.querySelector(".katex-display")).not.toBeNull();
    // Accessible MathML is emitted alongside the visual rendering.
    expect(view.querySelector("math")).not.toBeNull();
  });

  it("renders headings, lists and tables", () => {
    const view = html("## Rates\n\n- one\n- two\n\n| term | rate |\n| --- | --- |\n| 1y | 4.5% |");
    expect(view.querySelector("h2")?.textContent).toBe("Rates");
    expect(view.querySelectorAll("li")).toHaveLength(2);
    expect(view.querySelector("td")?.textContent).toBe("1y");
  });

  it("never runs scripts or loads remote images from document text", () => {
    const view = html(
      '<script>window.pwned = true</script><img src="https://evil.example/x.png" onerror="alert(1)">\n\n' +
        "![tracker](https://evil.example/t.png)\n\n[click](javascript:alert(1))",
    );
    expect(view.querySelector("script")).toBeNull();
    expect(view.querySelector("img")).toBeNull();
    const link = view.querySelector("a");
    expect(link?.getAttribute("href") ?? "").not.toContain("javascript:");
  });

  it("refuses LaTeX that would create links", () => {
    const view = html("$\\href{https://evil.example}{x}$");
    expect(view.querySelector("a")).toBeNull();
  });

  it("shows broken LaTeX as an error instead of crashing", () => {
    const view = html("$\\frac{1}{$");
    expect(view.textContent).toContain("\\frac");
  });
});

describe("normaliseDisplayMaths", () => {
  it("fences one-line display maths and leaves everything else alone", async () => {
    const { normaliseDisplayMaths } = await import("./MathMarkdown");
    expect(normaliseDisplayMaths("text\n$$ a^2 + b^2 $$\nmore")).toBe("text\n$$\na^2 + b^2\n$$\nmore");
    expect(normaliseDisplayMaths("inline $x$ and $$y$$ here")).toBe("inline $x$ and $$y$$ here");
    expect(normaliseDisplayMaths("$$\nalready\n$$")).toBe("$$\nalready\n$$");
  });
});
