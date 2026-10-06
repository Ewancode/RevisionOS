import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { SIDEBAR_WIDTH, SidebarResizer, useSidebarWidth } from "./SidebarResizer";

function Harness() {
  const [width, setWidth] = useSidebarWidth();
  return (
    <aside data-testid="sidebar" style={{ width }}>
      <SidebarResizer width={width} onResize={setWidth} />
    </aside>
  );
}

// jsdom has no PointerEvent; without one, pointer events carry no position.
if (!("PointerEvent" in window)) {
  class PointerEventShim extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
    }
  }
  Object.assign(window, { PointerEvent: PointerEventShim });
}

const handle = () => screen.getByRole("separator", { name: "Resize sidebar" });
const width = () => screen.getByTestId("sidebar").style.width;

beforeEach(() => {
  localStorage.clear();
  window.innerWidth = 1400;
});

describe("resizing the sidebar", () => {
  it("follows the mouse while dragging and remembers the width", () => {
    render(<Harness />);
    expect(width()).toBe(`${SIDEBAR_WIDTH.default}px`);
    fireEvent.pointerDown(handle(), { button: 0, clientX: 256, pointerId: 1 });
    fireEvent.pointerMove(handle(), { clientX: 356, pointerId: 1 });
    expect(width()).toBe("356px");
    expect(localStorage.getItem("revision-os.sidebar-width")).toBeNull(); // saved on release
    fireEvent.pointerUp(handle(), { clientX: 336, pointerId: 1 });
    expect(width()).toBe("336px");
    expect(localStorage.getItem("revision-os.sidebar-width")).toBe("336");
    // Moving the mouse after letting go changes nothing.
    fireEvent.pointerMove(handle(), { clientX: 500, pointerId: 1 });
    expect(width()).toBe("336px");
  });

  it("stays within its limits and leaves the page room", () => {
    render(<Harness />);
    fireEvent.pointerDown(handle(), { button: 0, clientX: 256, pointerId: 1 });
    fireEvent.pointerUp(handle(), { clientX: 0, pointerId: 1 });
    expect(width()).toBe(`${SIDEBAR_WIDTH.min}px`);
    fireEvent.pointerDown(handle(), { button: 0, clientX: 200, pointerId: 1 });
    fireEvent.pointerUp(handle(), { clientX: 2000, pointerId: 1 });
    expect(width()).toBe(`${SIDEBAR_WIDTH.max}px`);

    // In a narrow window the page keeps its minimum.
    window.innerWidth = 700;
    fireEvent(window, new Event("resize"));
    expect(width()).toBe(`${700 - SIDEBAR_WIDTH.minPage}px`);
  });

  it("works from the keyboard and resets on double-click", () => {
    render(<Harness />);
    handle().focus();
    fireEvent.keyDown(handle(), { key: "ArrowRight" });
    expect(width()).toBe(`${SIDEBAR_WIDTH.default + SIDEBAR_WIDTH.step}px`);
    expect(handle().getAttribute("aria-valuenow")).toBe(String(SIDEBAR_WIDTH.default + SIDEBAR_WIDTH.step));
    fireEvent.keyDown(handle(), { key: "Home" });
    expect(width()).toBe(`${SIDEBAR_WIDTH.min}px`);
    fireEvent.keyDown(handle(), { key: "End" });
    expect(width()).toBe(`${SIDEBAR_WIDTH.max}px`);
    fireEvent.doubleClick(handle());
    expect(width()).toBe(`${SIDEBAR_WIDTH.default}px`);
  });

  it("starts at the remembered width, ignoring nonsense", () => {
    localStorage.setItem("revision-os.sidebar-width", "320");
    const { unmount } = render(<Harness />);
    expect(width()).toBe("320px");
    unmount();
    localStorage.setItem("revision-os.sidebar-width", "banana");
    render(<Harness />);
    expect(width()).toBe(`${SIDEBAR_WIDTH.default}px`);
  });
});
