import '@testing-library/jest-dom/vitest';

// The DOM stubs below only exist to run under jsdom; the token tests
// opt into the plain node environment, where there is no window.
if (typeof window !== 'undefined') {
  // jsdom ships no matchMedia; the reduced-motion hooks read it on every
  // render. Tests default to "motion allowed"; a test that needs the
  // reduced path stubs it again with matches: false.
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {
        return false;
      },
    })) as unknown as typeof window.matchMedia;
  }

  // Some entrance effects observe visibility; tests render synchronously,
  // so an always-visible observer is the honest stand-in.
  if (!window.IntersectionObserver) {
    class FakeIntersectionObserver implements IntersectionObserver {
      readonly root = null;
      readonly rootMargin = '';
      readonly thresholds: ReadonlyArray<number> = [];
      disconnect() {}
      observe() {}
      unobserve() {}
      takeRecords(): IntersectionObserverEntry[] {
        return [];
      }
    }
    window.IntersectionObserver = FakeIntersectionObserver;
  }

  // Hover-chrome components watch their own box; a no-op observer keeps
  // them mounted so the tests can assert what they render.
  if (!window.ResizeObserver) {
    class FakeResizeObserver implements ResizeObserver {
      disconnect() {}
      observe() {}
      unobserve() {}
    }
    window.ResizeObserver = FakeResizeObserver;
  }

  // The animation library probes declared-property support through
  // CSS.supports, which jsdom does not implement. Answering true keeps
  // the standard CSS path (the system's 150-200ms transitions) exercised.
  const css = window.CSS as unknown as Record<string, unknown> | undefined;
  if (!css || typeof css.supports !== 'function') {
    Object.defineProperty(window, 'CSS', {
      value: { ...(css ?? {}), supports: () => true, escape: (v: string) => v },
      configurable: true,
    });
  }
}
