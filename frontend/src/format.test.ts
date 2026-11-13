import { describe, expect, it } from "vitest";
import { addDays, pct, rupees, signedRupees } from "./format";

describe("format", () => {
  it("uses Indian digit grouping", () => {
    expect(rupees(1548186)).toBe("₹15,48,186");
    expect(rupees(null)).toBe("—");
  });

  it("signs profit and loss", () => {
    expect(signedRupees(3620.4)).toBe("+₹3,620");
    expect(signedRupees(-10020)).toBe("−₹10,020");
    expect(signedRupees(0.2)).toBe("₹0");
  });

  it("formats percentages with a sign", () => {
    expect(pct(0.2069)).toBe("+20.7%");
    expect(pct(-0.6773)).toBe("−67.7%");
  });

  it("adds days across month ends", () => {
    expect(addDays("2026-10-28", 7)).toBe("2026-11-04");
  });
});
