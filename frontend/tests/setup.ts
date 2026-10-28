import "@testing-library/jest-dom/vitest";
import { configure, cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

configure({ asyncUtilTimeout: 10_000 });

// jsdom lacks these browser APIs.
// jsdom's Blob may lack text() and arrayBuffer().
if (typeof Blob.prototype.text !== "function") {
  Object.defineProperty(Blob.prototype, "text", {
    configurable: true,
    value: async function (this: Blob): Promise<string> {
      return await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => {
          if (typeof reader.result === "string") {
            resolve(reader.result);
          } else {
            reject(new Error("Failed to read Blob as text"));
          }
        };

        reader.onerror = () => {
          reject(reader.error ?? new Error("Failed to read Blob"));
        };

        reader.readAsText(this);
      });
    },
  });
}
if (!("createObjectURL" in URL)) {
  Object.defineProperty(URL, "createObjectURL", { value: () => "blob:test", writable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: () => undefined, writable: true });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
