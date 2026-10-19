/**
 * MenuSelect — the shared dropdown.
 *
 * Its popover renders in a portal on purpose. As an absolutely-positioned child
 * it was clipped by any ancestor with `overflow` (a scrolling panel, a rounded
 * card), which is a nasty failure: the control looks fine, the click registers,
 * and the menu opens into a region nobody can see — so it reads as "the dropdown
 * doesn't work". These pin the escape.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MenuSelect } from "./MenuSelect";

afterEach(cleanup);

const OPTIONS = [
  { value: "call", label: "Call" },
  { value: "email", label: "Email" },
  { value: "note", label: "Note" },
];

/** The exact situation that broke it: a rounded card with overflow-hidden. */
function ClippingParent({ onChange = () => {} }: { onChange?: (v: string) => void }) {
  return (
    <div style={{ overflow: "hidden" }} data-testid="clipper">
      <MenuSelect value="call" options={OPTIONS} onChange={onChange} ariaLabel="Type" />
    </div>
  );
}

describe("MenuSelect", () => {
  it("renders its options outside the clipping ancestor", () => {
    const { getByTestId } = render(<ClippingParent />);
    fireEvent.click(screen.getByLabelText("Type"));

    const option = screen.getByRole("option", { name: /Email/ });
    expect(option).toBeTruthy();
    // The whole point: the menu is NOT inside the overflow:hidden subtree.
    expect(getByTestId("clipper").contains(option)).toBe(false);
  });

  it("reports the chosen value and closes", () => {
    const onChange = vi.fn();
    render(<ClippingParent onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Type"));
    fireEvent.click(screen.getByRole("option", { name: /Note/ }));

    expect(onChange).toHaveBeenCalledWith("note");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("marks the current option selected so the checkmark is meaningful", () => {
    render(<ClippingParent />);
    fireEvent.click(screen.getByLabelText("Type"));
    const list = screen.getByRole("listbox");
    expect(within(list).getByRole("option", { name: /Call/ }).getAttribute("aria-selected")).toBe("true");
    expect(within(list).getByRole("option", { name: /Email/ }).getAttribute("aria-selected")).toBe("false");
  });

  it("closes on Escape and on outside click", () => {
    render(<ClippingParent />);
    fireEvent.click(screen.getByLabelText("Type"));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();

    fireEvent.click(screen.getByLabelText("Type"));
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("closes when an ancestor scrolls, rather than drifting away from its trigger", () => {
    // Fixed positioning doesn't follow a scrolling ancestor — leaving the menu
    // open would park it over unrelated content.
    render(<ClippingParent />);
    fireEvent.click(screen.getByLabelText("Type"));
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.scroll(document, {});
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("falls back to the raw value when it matches no option", () => {
    // A legacy or server-side value must still show, not render the trigger blank.
    render(<MenuSelect value="legacy_thing" options={OPTIONS} onChange={() => {}} ariaLabel="Type" />);
    expect(screen.getByLabelText("Type").textContent).toContain("legacy_thing");
  });
});
