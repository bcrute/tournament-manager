import { describe, expect, it } from "vitest";
import { codeFromScan } from "./table/qrPayload";

describe("codeFromScan", () => {
  it("reads our own join link", () => {
    expect(codeFromScan("https://mtg.skadoosh.dev/table?join=7Q4KP")).toBe("7Q4KP");
  });

  it("reads a room URL, which is what a shared link looks like", () => {
    expect(codeFromScan("https://mtg.skadoosh.dev/table/r/7Q4KP")).toBe("7Q4KP");
  });

  it("accepts a bare code, in case someone made their own QR", () => {
    expect(codeFromScan("7q4kp")).toBe("7Q4KP");
  });

  it("ignores whitespace around the payload", () => {
    expect(codeFromScan("  7Q4KP \n")).toBe("7Q4KP");
  });

  it("refuses anything that isn't a room — a QR in the wild is usually not ours", () => {
    for (const junk of [
      "https://example.com",
      "https://mtg.skadoosh.dev/tournament/7Q4KP",
      "WIFI:S:home;T:WPA;P:hunter2;;",
      "not a url at all",
      "",
      "TOOLONGCODE",
    ]) {
      expect(codeFromScan(junk), junk).toBeNull();
    }
  });

  it("does not treat a tournament code as a room code", () => {
    // both are five characters; only the path tells them apart
    expect(codeFromScan("https://mtg.skadoosh.dev/tournament/ABCDE")).toBeNull();
  });
});
