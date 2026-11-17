import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Supply layout measurements for responsive charts in the DOM test environment.
globalThis.ResizeObserver = class {
  constructor(callback) {
    this.callback = callback;
  }
  observe() {
    this.callback([{ contentRect: { width: 640, height: 280 } }]);
  }
  unobserve() {}
  disconnect() {}
};
