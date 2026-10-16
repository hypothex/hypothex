/**
 * A fake ResizeObserver for happy-dom (which never reports sizes): every observed element
 * reports `width` at once, and `resize(w)` reports `w` to every live observer. Call
 * `restore()` in `afterEach`. Wrap `resize` in `act()`.
 */
export interface FakeResize {
  resize(width: number): void;
  restore(): void;
}

export function fakeResize(width: number): FakeResize {
  const real = globalThis.ResizeObserver;
  let current = width;
  const live = new Set<{ cb: ResizeObserverCallback; els: Element[] }>();
  const entry = (el: Element) => ({ target: el, contentRect: { width: current, height: 0 } }) as unknown as ResizeObserverEntry;
  class Fake {
    private rec: { cb: ResizeObserverCallback; els: Element[] };
    constructor(cb: ResizeObserverCallback) {
      this.rec = { cb, els: [] };
      live.add(this.rec);
    }
    observe(el: Element): void {
      this.rec.els.push(el);
      this.rec.cb([entry(el)], this as unknown as ResizeObserver);
    }
    unobserve(): void {}
    disconnect(): void {
      live.delete(this.rec);
    }
  }
  globalThis.ResizeObserver = Fake as unknown as typeof ResizeObserver;
  return {
    resize(w: number) {
      current = w;
      for (const rec of live) rec.cb(rec.els.map(entry), {} as ResizeObserver);
    },
    restore() {
      globalThis.ResizeObserver = real;
    },
  };
}
