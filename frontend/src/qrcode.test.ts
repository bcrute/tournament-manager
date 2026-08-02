import { describe, expect, it } from "vitest";
import { invitationLink, roomIdFromScan } from "./table/qrPayload";

/**
 * A room is identified by 128 random bits in base64url, not by the old
 * five-character code. Two things follow, and both are easy to get wrong:
 * case is meaningful, and the identifier belongs in a fragment so it never
 * reaches a server log.
 */
const ID = "kJ3xR_9pQz-A1BcDeFgHi";
const OTHER = "Zm9vYmFyYmF6cXV4MTIzNA";

describe("roomIdFromScan", () => {
  it("reads the invitation link we produce", () => {
    expect(roomIdFromScan(`https://mtg.skadoosh.dev/table#r/${ID}`)).toBe(ID);
  });

  it("reads a bare identifier, for a QR someone made themselves", () => {
    expect(roomIdFromScan(ID)).toBe(ID);
  });

  it("reads the room's own address, which is now also an invitation", () => {
    expect(roomIdFromScan(`https://mtg.skadoosh.dev/table/r/${ID}`)).toBe(ID);
  });

  it("still reads the old query form, for links already in the world", () => {
    expect(roomIdFromScan(`https://mtg.skadoosh.dev/table?join=${ID}`)).toBe(ID);
  });

  it("reads a bare fragment, which is what a half-pasted link looks like", () => {
    expect(roomIdFromScan(`#r/${ID}`)).toBe(ID);
  });

  it("ignores whitespace around the payload", () => {
    expect(roomIdFromScan(`  ${ID} \n`)).toBe(ID);
  });

  it("never changes the case, because base64url case is meaningful", () => {
    // the old code was upper-cased on the way in; doing that here would hand
    // the server an identifier that resolves to nothing
    expect(roomIdFromScan(ID)).toBe(ID);
    expect(roomIdFromScan(ID.toUpperCase())).toBe(ID.toUpperCase());
    expect(roomIdFromScan(ID)).not.toBe(ID.toUpperCase());
  });

  it("refuses a five-character code — it opens nothing now", () => {
    expect(roomIdFromScan("7Q4KP")).toBeNull();
    expect(roomIdFromScan("https://mtg.skadoosh.dev/table?join=7Q4KP")).toBeNull();
    expect(roomIdFromScan("https://mtg.skadoosh.dev/table/r/7Q4KP")).toBeNull();
  });

  it("refuses somebody else's QR", () => {
    expect(roomIdFromScan("WIFI:S:CoffeeShop;T:WPA;P:hunter2;;")).toBeNull();
    expect(roomIdFromScan("https://example.com/menu")).toBeNull();
    expect(roomIdFromScan("not a url at all")).toBeNull();
    expect(roomIdFromScan("")).toBeNull();
    expect(roomIdFromScan("   ")).toBeNull();
  });

  it("refuses a tournament link, where joining the wrong thing is worse", () => {
    expect(roomIdFromScan(`https://mtg.skadoosh.dev/tournament/${ID}`)).toBeNull();
  });

  it("does not confuse two rooms", () => {
    expect(roomIdFromScan(`https://mtg.skadoosh.dev/table#r/${OTHER}`)).toBe(OTHER);
    expect(roomIdFromScan(`https://mtg.skadoosh.dev/table#r/${OTHER}`)).not.toBe(ID);
  });
});

describe("invitationLink", () => {
  it("puts the identifier in the fragment, never the query", () => {
    const link = invitationLink("https://mtg.skadoosh.dev", ID);
    expect(link).toBe(`https://mtg.skadoosh.dev/table#r/${ID}`);
    // a fragment is never sent to a server, so it cannot reach an access log
    expect(new URL(link).search).toBe("");
    expect(link).not.toContain("?");
  });

  it("round-trips through the scanner", () => {
    expect(roomIdFromScan(invitationLink("https://mtg.skadoosh.dev", ID))).toBe(ID);
  });
});
