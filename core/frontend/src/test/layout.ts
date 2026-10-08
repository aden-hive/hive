/**
 * Layout simulation for jsdom.
 *
 * jsdom has no layout engine: `scrollHeight`, `clientHeight`, `offsetHeight`
 * are all `0` and there is no `ResizeObserver`. The lazy-history windowing
 * is entirely a layout-overflow concern, so the tests need a controllable
 * stand-in. This module installs one:
 *
 *   • `offsetHeight`  — taken from an element's inline `style.height`, else
 *     its `data-test-h` attribute, else 0.
 *   • `scrollHeight`  — sum of an element's direct children's offsetHeight.
 *   • `clientHeight`  — taken from a `data-test-vh` attribute (the viewport).
 *   • `scrollTop`     — a real read/write number that dispatches `scroll`.
 *   • `ResizeObserver`— a no-op observer whose callbacks fire on demand via
 *     `flushResizeObservers()`.
 *
 * A test builds a DOM where each row carries `data-test-h` and the scroll
 * container carries `data-test-vh`, and gets deterministic overflow maths.
 */

type Descriptor = PropertyDescriptor | undefined;

const saved: Record<string, Descriptor> = {};
let installed = false;

const scrollTops = new WeakMap<Element, number>();

interface MockResizeObserver {
  cb: ResizeObserverCallback;
}
const resizeObservers = new Set<MockResizeObserver>();
let savedResizeObserver: typeof ResizeObserver | undefined;

let rafSeq = 0;
const rafQueue = new Map<number, FrameRequestCallback>();
let savedRaf: typeof requestAnimationFrame | undefined;
let savedCancelRaf: typeof cancelAnimationFrame | undefined;

function pxAttr(el: HTMLElement, attr: string): number | null {
  const raw = el.getAttribute(attr);
  if (raw == null) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/** Install the layout simulation. Idempotent. Pair with `uninstallLayoutShim`. */
export function installLayoutShim(): void {
  if (installed) return;
  installed = true;

  saved.offsetHeight = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "offsetHeight",
  );
  saved.scrollHeight = Object.getOwnPropertyDescriptor(
    Element.prototype,
    "scrollHeight",
  );
  saved.clientHeight = Object.getOwnPropertyDescriptor(
    Element.prototype,
    "clientHeight",
  );
  saved.scrollTop = Object.getOwnPropertyDescriptor(
    Element.prototype,
    "scrollTop",
  );

  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get(this: HTMLElement): number {
      const styleH = this.style?.height;
      if (styleH && styleH.endsWith("px")) {
        return parseFloat(styleH) || 0;
      }
      return pxAttr(this, "data-test-h") ?? 0;
    },
  });

  Object.defineProperty(Element.prototype, "scrollHeight", {
    configurable: true,
    get(this: Element): number {
      let sum = 0;
      for (const child of Array.from(this.children)) {
        sum += (child as HTMLElement).offsetHeight ?? 0;
      }
      return sum;
    },
  });

  Object.defineProperty(Element.prototype, "clientHeight", {
    configurable: true,
    get(this: Element): number {
      return pxAttr(this as HTMLElement, "data-test-vh") ?? 0;
    },
  });

  Object.defineProperty(Element.prototype, "scrollTop", {
    configurable: true,
    get(this: Element): number {
      return scrollTops.get(this) ?? 0;
    },
    set(this: Element, value: number) {
      scrollTops.set(this, value);
      this.dispatchEvent(new Event("scroll"));
    },
  });

  savedResizeObserver = globalThis.ResizeObserver;
  class MockRO implements MockResizeObserver {
    cb: ResizeObserverCallback;
    constructor(cb: ResizeObserverCallback) {
      this.cb = cb;
      resizeObservers.add(this);
    }
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {
      resizeObservers.delete(this);
    }
  }
  globalThis.ResizeObserver = MockRO as unknown as typeof ResizeObserver;

  // requestAnimationFrame becomes an explicit queue the test drains via
  // `flushAnimationFrames()` — the auto-fill effect defers each reveal
  // step onto a frame, so tests need deterministic control of them.
  savedRaf = globalThis.requestAnimationFrame;
  savedCancelRaf = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = ((cb: FrameRequestCallback): number => {
    const id = ++rafSeq;
    rafQueue.set(id, cb);
    return id;
  }) as typeof requestAnimationFrame;
  globalThis.cancelAnimationFrame = ((id: number): void => {
    rafQueue.delete(id);
  }) as typeof cancelAnimationFrame;
}

/** Restore the real (jsdom) descriptors. */
export function uninstallLayoutShim(): void {
  if (!installed) return;
  installed = false;
  if (saved.offsetHeight) {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", saved.offsetHeight);
  }
  if (saved.scrollHeight) {
    Object.defineProperty(Element.prototype, "scrollHeight", saved.scrollHeight);
  }
  if (saved.clientHeight) {
    Object.defineProperty(Element.prototype, "clientHeight", saved.clientHeight);
  }
  if (saved.scrollTop) {
    Object.defineProperty(Element.prototype, "scrollTop", saved.scrollTop);
  }
  resizeObservers.clear();
  globalThis.ResizeObserver = savedResizeObserver as typeof ResizeObserver;
  rafQueue.clear();
  if (savedRaf) globalThis.requestAnimationFrame = savedRaf;
  if (savedCancelRaf) globalThis.cancelAnimationFrame = savedCancelRaf;
}

/** Fire every live ResizeObserver's callback — simulates a layout change. */
export function flushResizeObservers(): void {
  for (const ro of Array.from(resizeObservers)) {
    ro.cb([], ro as unknown as ResizeObserver);
  }
}

/** Run every currently-queued animation-frame callback once. Returns how
 *  many ran. Callbacks that schedule further frames (the auto-fill loop)
 *  are NOT drained here — the caller re-flushes inside `act()` so React
 *  can commit the re-render that queues the next frame. */
export function flushAnimationFrames(): number {
  const pending = [...rafQueue.entries()];
  rafQueue.clear();
  for (const [, cb] of pending) cb(performance.now());
  return pending.length;
}

/** Number of animation-frame callbacks currently queued. */
export function pendingAnimationFrames(): number {
  return rafQueue.size;
}
